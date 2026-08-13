# -*- coding: utf-8 -*-
"""
Extractor de Drivers de Mercado Libre - Interfaz grafica (PySide6)

Todo se maneja con botones: no hay que presionar ENTER en una terminal.
El registro de actividad se ve en un panel dentro de la misma ventana.

Flujo:
  1. "Abrir Mercado Libre"  -> lanza Chrome en la pagina de drivers
  2. Inicias sesion a mano
  3. "Extraer TODO"         -> listado, telefonos y guardado, de una vez
"""

import os
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QColor, QPalette, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QFrame,
    QMessageBox,
    QFileDialog,
    QGridLayout,
    QSizePolicy,
)

import extraer_api as nucleo

# ---------------------------------------------------------------- colores
FONDO = "#1e2128"
PANEL = "#272b34"
BORDE = "#3a3f4b"
TEXTO = "#e8eaed"
SUAVE = "#9aa0aa"
AMARILLO = "#ffe600"      # el amarillo de Mercado Libre
AZUL = "#3483fa"
VERDE = "#00a650"
ROJO = "#f23d4f"


class Puente(QObject):
    """Permite que el hilo de trabajo mande mensajes a la ventana."""

    mensaje = Signal(str)
    avance = Signal(int, int)      # hechos, total
    terminado = Signal(str, object)  # etapa, datos
    fallo = Signal(str)


class Ordenes(QObject):
    """Señales para pedirle trabajo al hilo secundario.

    Hay que invocarlo por señal y no llamando al metodo directo: una llamada
    normal correria en el hilo de la ventana y la congelaria.
    """

    abrir = Signal()
    todo = Signal()
    cerrar = Signal()


class Trabajador(QObject):
    """Corre la extraccion fuera del hilo de la interfaz.

    Si esto corriera en el hilo principal, la ventana se congelaria durante
    los minutos que tarda la consulta de fichas.
    """

    def __init__(self, puente):
        super().__init__()
        self.puente = puente
        self.driver = None
        self.registros = []
        self.cancelado = False

    def log(self, texto):
        self.puente.mensaje.emit(texto)

    # ------------------------------------------------------------ etapas
    @Slot()
    def abrir_navegador(self):
        try:
            self.log("Preparando Chrome...")
            # Redirigir el log del nucleo hacia la interfaz
            nucleo.log = self.log

            # Si ya habia una ventana de una corrida anterior, cerrarla:
            # de lo contrario Chrome abre en blanco por el perfil bloqueado.
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

            self.driver = nucleo.crear_driver()
            self.driver.get(nucleo.URL)
            self.log("Chrome abierto. Inicia sesion en esa ventana.")
            self.puente.terminado.emit("navegador", None)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot()
    def descargar_todo(self):
        """Hace todo el trabajo de una sola vez: listado, fichas y guardado."""
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            if not self._preparar_pagina():
                return

            # --- 1) Listado ---
            self.log("Paso 1 de 3: extrayendo la lista de drivers...")
            inicio = time.time()
            self.registros = nucleo.extraer_todo(self.driver)

            if not self.registros:
                self.puente.fallo.emit(
                    "La API no devolvio registros.\n\n"
                    "Revisa que la lista de drivers este visible en Chrome "
                    "y que tu sesion siga activa."
                )
                return

            self.log(
                f"  {len(self.registros)} drivers en {time.time() - inicio:.1f} s"
            )
            # Avisar ya: las tarjetas se llenan sin esperar a las fichas
            self.puente.terminado.emit("listado", self.registros)

            # Respaldo temprano, por si las fichas se interrumpen
            try:
                nucleo.guardar(self.registros)
            except Exception:
                pass

            # --- 2) Fichas ---
            self.log("Paso 2 de 3: trayendo telefonos y correos...")
            self._consultar_fichas()

            # --- 3) Guardado ---
            self.log("Paso 3 de 3: guardando archivos...")
            rutas = nucleo.guardar(self.registros)
            self.log(f"  {os.path.basename(rutas[0])}")
            self.log(f"  {os.path.basename(rutas[1])}")

            self.puente.terminado.emit("todo", (self.registros, rutas))
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    def _consultar_fichas(self):
        """Consulta las fichas informando el avance a la barra."""
        total = sum(1 for r in self.registros if r.get("id") and r["id"] != "0")
        if not total:
            return
        self.puente.avance.emit(0, total)

        hechos = {"n": 0}
        original = nucleo.pedir_lote_perfiles

        def con_avance(driver, ids):
            if self.cancelado:
                raise KeyboardInterrupt("cancelado")
            res = original(driver, ids)
            hechos["n"] += len(ids)
            self.puente.avance.emit(min(hechos["n"], total), total)
            return res

        nucleo.pedir_lote_perfiles = con_avance
        try:
            nucleo.completar_contactos(self.driver, self.registros)
        except KeyboardInterrupt:
            self.log("  Cancelado; se guarda lo obtenido hasta ahora.")
        finally:
            nucleo.pedir_lote_perfiles = original

    def _preparar_pagina(self):
        """Deja a Chrome parado en el dominio de MELI, con sesion activa.

        El fetch se ejecuta DENTRO de la pagina, asi que solo funciona si el
        navegador esta en envios.adminml.com. Si esta en otro dominio (o en
        otra pestana), el navegador lo bloquea y devuelve
        'TypeError: Failed to fetch' con status 0.
        """
        # 1) Si hay varias pestanas, pasar a la que tenga el panel abierto
        try:
            pestanas = self.driver.window_handles
            if len(pestanas) > 1:
                for p in pestanas:
                    self.driver.switch_to.window(p)
                    if "adminml.com" in (self.driver.current_url or ""):
                        break
        except Exception:
            pass

        # 2) Si no estamos en el dominio correcto, navegar ahi
        url = self.driver.current_url or ""
        if "envios.adminml.com" not in url:
            self.log(f"Chrome esta en otra pagina; volviendo al panel...")
            self.driver.get(nucleo.URL)
            time.sleep(2)

        # 3) Esperar a que el panel cargue de verdad (hasta 30 s)
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
        except Exception:
            # Puede que la lista aun no aparezca pero la sesion si sirva;
            # se comprueba llamando la API antes de rendirse.
            pass

        # 4) Comprobacion final: una llamada de prueba a la API
        try:
            sonda = nucleo.llamar_api(self.driver, None)
            if isinstance(sonda, dict) and (
                sonda.get("result") or sonda.get("results")
            ):
                return True
        except Exception as e:
            texto = str(e).lower()
            if "failed to fetch" in texto:
                self.puente.fallo.emit(
                    "El navegador bloqueo la consulta.\n\n"
                    "Esto pasa cuando Chrome no esta en la pagina de Mercado "
                    "Libre.\n\n"
                    "Que hacer:\n"
                    "1. Ve a la ventana de Chrome que abrio el programa\n"
                    "2. Asegurate de estar en la LISTA DE TRANSPORTISTAS\n"
                    "   (envios.adminml.com/logistics/provider-management/drivers)\n"
                    "3. Presiona otra vez 'Extraer TODO'"
                )
                return False
            if "401" in texto or "403" in texto or "no devolvio json" in texto:
                self.puente.fallo.emit(
                    "Tu sesion de Mercado Libre no esta activa.\n\n"
                    "Inicia sesion en la ventana de Chrome y vuelve a "
                    "presionar 'Extraer TODO'."
                )
                return False

        self.puente.fallo.emit(
            "No se pudo consultar la lista de drivers.\n\n"
            "Revisa que en Chrome se vea la lista de transportistas y que "
            "tu sesion siga abierta, luego presiona otra vez 'Extraer TODO'."
        )
        return False

    @Slot()
    def cerrar(self):
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception:
            pass

    # ------------------------------------------------------------ ayuda
    def _explicar(self, e):
        """Convierte los errores tecnicos en algo entendible."""
        texto = str(e).split("Stacktrace:")[0].strip()
        bajo = texto.lower()

        if "user data directory is already in use" in bajo:
            return (
                "El perfil de Chrome esta en uso por otra ventana.\n\n"
                "Cierra las ventanas de Chrome que abrio este programa "
                "y vuelve a intentarlo."
            )
        if "devtoolsactiveport" in bajo or "failed to start" in bajo:
            return (
                "Chrome no pudo arrancar.\n\n"
                "Suele pasar si quedo una copia abierta. Cierra Chrome "
                "y vuelve a intentar; si sigue, borra la carpeta "
                f"'chrome_profile' que esta junto al programa."
            )
        if "no such window" in bajo or "target window already closed" in bajo:
            return (
                "Se cerro la ventana de Chrome.\n\n"
                "Presiona 'Abrir Mercado Libre' para empezar de nuevo."
            )
        if "failed to fetch" in bajo or "respondio 0" in bajo:
            return (
                "El navegador bloqueo la consulta.\n\n"
                "Chrome debe estar en la pagina de Mercado Libre para que el "
                "programa pueda pedir los datos.\n\n"
                "Ve a la ventana de Chrome, entra a la lista de "
                "transportistas y presiona otra vez el boton 2."
            )
        if "not json" in bajo or "sesion caduco" in bajo or "401" in bajo or "403" in bajo:
            return (
                "La sesion de Mercado Libre caduco.\n\n"
                "Inicia sesion otra vez en la ventana de Chrome y vuelve a "
                "presionar 'Extraer TODO'."
            )
        return texto[:400] if texto else type(e).__name__


class Tarjeta(QFrame):
    """Recuadro con un numero grande y su etiqueta."""

    def __init__(self, etiqueta, color=TEXTO):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 8px; }}"
        )
        caja = QVBoxLayout(self)
        caja.setContentsMargins(8, 5, 8, 5)
        caja.setSpacing(0)

        self.valor = QLabel("-")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.valor.setFont(f)
        self.valor.setStyleSheet(f"color: {color}; border: none;")

        self.texto = QLabel(etiqueta)
        self.texto.setStyleSheet(f"color: {SUAVE}; font-size: 9px; border: none;")

        caja.addWidget(self.valor)
        caja.addWidget(self.texto)

    def poner(self, v):
        self.valor.setText(str(v))


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Extractor de Drivers - Mercado Libre")
        self.resize(560, 400)
        self.setMinimumSize(460, 340)
        self.registros = []
        self.rutas = None

        self._armar_interfaz()
        self._armar_hilo()

    # ------------------------------------------------------------ interfaz
    def _armar_interfaz(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background: {FONDO};")
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(7)

        # --- encabezado ---
        titulo = QLabel("Extractor de Drivers")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        titulo.setFont(f)
        titulo.setStyleSheet(f"color: {TEXTO};")
        raiz.addWidget(titulo)

        self.paso = QLabel("Paso 1 de 2  ·  Abre Mercado Libre e inicia sesion")
        self.paso.setStyleSheet(f"color: {AMARILLO}; font-size: 11px;")
        raiz.addWidget(self.paso)

        # --- botones ---
        fila = QHBoxLayout()
        fila.setSpacing(7)

        self.b_abrir = self._boton("1 · Abrir Mercado Libre", AZUL, True)
        self.b_todo = self._boton("2 · Extraer TODO", VERDE)
        self.b_guardar = self._boton("Abrir carpeta", AMARILLO)

        self.b_abrir.clicked.connect(self.al_abrir)
        self.b_todo.clicked.connect(self.al_descargar_todo)
        self.b_guardar.clicked.connect(self.al_guardar)

        for b in (self.b_abrir, self.b_todo, self.b_guardar):
            fila.addWidget(b)
        # El boton principal se lleva mas ancho
        fila.setStretch(0, 2)
        fila.setStretch(1, 3)
        fila.setStretch(2, 2)
        raiz.addLayout(fila)

        self.b_todo.setEnabled(False)
        self.b_guardar.setEnabled(False)

        # --- tarjetas ---
        # Se arman al vuelo segun los estatus que traiga la extraccion, para
        # que las categorias siempre sumen el total y no quede nada fuera.
        self.rejilla = QGridLayout()
        self.rejilla.setSpacing(6)
        self.tarjetas = {}          # estatus -> Tarjeta

        self.t_total = Tarjeta("Drivers", TEXTO)
        self.t_telefonos = Tarjeta("Con telefono", AZUL)
        self.rejilla.addWidget(self.t_total, 0, 0)
        self.rejilla.addWidget(self.t_telefonos, 0, 1)
        raiz.addLayout(self.rejilla)

        # --- barra de avance ---
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setFixedHeight(15)
        self.barra.setStyleSheet(
            f"QProgressBar {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 4px; color: {TEXTO}; font-size: 9px; }}"
            f"QProgressBar::chunk {{ background: {AZUL}; border-radius: 3px; }}"
        )
        self.barra.hide()
        raiz.addWidget(self.barra)

        # --- registro ---
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(90)
        self.registro.setStyleSheet(
            f"QPlainTextEdit {{ background: #16181d; color: #b9c0cb;"
            f" border: 1px solid {BORDE}; border-radius: 6px; padding: 6px;"
            f" font-family: Consolas, monospace; font-size: 10px; }}"
        )
        raiz.addWidget(self.registro, 1)

        # --- pie ---
        self.pie = QLabel("Listo para empezar")
        self.pie.setStyleSheet(f"color: {SUAVE}; font-size: 10px;")
        raiz.addWidget(self.pie)

    def _boton(self, texto, color, principal=False):
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(30)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        letra = "#1e2128" if color in (AMARILLO,) else "#ffffff"
        if color == PANEL:
            letra = TEXTO
        b.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {letra};"
            f" border: none; border-radius: 6px; font-size: 11px;"
            f" font-weight: 600; padding: 0 8px; }}"
            f"QPushButton:hover {{ background: {color}; opacity: 0.9; }}"
            f"QPushButton:disabled {{ background: #2c3038; color: #5a616d; }}"
        )
        return b

    def _armar_hilo(self):
        self.puente = Puente()
        self.ordenes = Ordenes()
        self.hilo = QThread()
        self.trabajador = Trabajador(self.puente)
        self.trabajador.moveToThread(self.hilo)

        # De la ventana hacia el trabajador
        self.ordenes.abrir.connect(self.trabajador.abrir_navegador)
        self.ordenes.todo.connect(self.trabajador.descargar_todo)
        self.ordenes.cerrar.connect(self.trabajador.cerrar)

        # Del trabajador hacia la ventana
        self.puente.mensaje.connect(self.escribir)
        self.puente.avance.connect(self.mover_barra)
        self.puente.terminado.connect(self.al_terminar)
        self.puente.fallo.connect(self.al_fallar)

        self.hilo.start()

    # ------------------------------------------------------------ acciones
    def escribir(self, texto):
        hora = datetime.now().strftime("%H:%M:%S")
        self.registro.appendPlainText(f"[{hora}]  {texto}")
        self.registro.verticalScrollBar().setValue(
            self.registro.verticalScrollBar().maximum()
        )

    def mover_barra(self, hechos, total):
        if total:
            self.barra.show()
            self.barra.setMaximum(total)
            self.barra.setValue(hechos)
            self.barra.setFormat(f"{hechos} de {total} fichas  (%p%)")

    def _habilitar(self, boton, si=True):
        boton.setProperty("listo", si)
        boton.setEnabled(si)

    def al_abrir(self):
        self.escribir("Abriendo Chrome...")
        self.b_abrir.setEnabled(False)
        self.pie.setText("Abriendo Chrome, espera un momento...")
        self.ordenes.abrir.emit()

    def al_descargar_todo(self):
        self.b_todo.setEnabled(False)
        self.b_todo.setText("Extrayendo...")
        self.pie.setText("Extrayendo. Puedes seguir usando la PC.")
        self.escribir("Iniciando extraccion completa...")
        self.ordenes.todo.emit()

    def al_guardar(self):
        """Abre la carpeta donde quedaron los archivos."""
        destino = os.path.dirname(self.rutas[0]) if self.rutas else _carpeta_base()
        QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    # ------------------------------------------------------------ eventos
    def al_terminar(self, etapa, datos):
        QApplication.restoreOverrideCursor()

        if etapa == "navegador":
            self.paso.setText(
                "Paso 2 de 2  ·  Inicia sesion en Chrome y presiona 'Extraer TODO'"
            )
            self._habilitar(self.b_todo, True)
            self.b_abrir.setText("Reabrir Chrome")
            self.b_abrir.setEnabled(True)
            self.pie.setText("Esperando a que inicies sesion")

        elif etapa == "listado":
            # Avance intermedio: las tarjetas se llenan mientras siguen las fichas
            self.registros = datos or []
            self._resumir()
            self.pie.setText(
                f"{len(self.registros)} drivers extraidos. Trayendo telefonos..."
            )

        elif etapa == "todo":
            registros, rutas = datos
            self.registros = registros
            self.rutas = rutas
            self._resumir()
            self.barra.hide()

            self.paso.setText("Listo  ·  Los archivos ya estan guardados")
            self.b_todo.setText("Extraer otra vez")
            self._habilitar(self.b_todo, True)
            self._habilitar(self.b_guardar, True)
            self.pie.setText(f"{len(self.registros)} drivers guardados")
            self._avisar_final(registros, rutas)

    def _avisar_final(self, registros, rutas):
        """Cuadro final con el resumen y el acceso a la carpeta."""
        conteo = {}
        for r in registros:
            c = r.get("estatus") or "Sin estatus"
            conteo[c] = conteo.get(c, 0) + 1

        n_tel = sum(1 for r in registros if r.get("telefono"))
        lineas = [f"{c}: {conteo[c]}" for c in sorted(conteo, key=lambda k: -conteo[k])]
        detalle = f"{n_tel} con telefono."

        caja = QMessageBox(self)
        caja.setWindowTitle("Extraccion completa")
        caja.setIcon(QMessageBox.Information)
        caja.setText(
            f"Se extrajeron {len(registros)} drivers.\n\n" + "\n".join(lineas)
        )
        caja.setInformativeText(
            f"{detalle}\n\n"
            f"{os.path.basename(rutas[0])}\n{os.path.basename(rutas[1])}"
        )
        abrir = caja.addButton("Abrir carpeta", QMessageBox.AcceptRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.exec()

        if caja.clickedButton() is abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(rutas[0])))

    def al_fallar(self, mensaje):
        QApplication.restoreOverrideCursor()
        self.barra.hide()
        self.escribir(f"ERROR: {mensaje.splitlines()[0]}")
        self.b_abrir.setEnabled(True)
        self.b_todo.setText("2 · Extraer TODO")
        for b in (self.b_todo, self.b_guardar):
            if b.property("listo") is True:
                b.setEnabled(True)
        QMessageBox.warning(self, "Algo salio mal", mensaje)
        self.pie.setText("Ocurrio un error, revisa el registro")

    # Color por estatus; lo que no este aqui usa gris
    COLORES = {
        "Activo": VERDE,
        "Bloqueado": ROJO,
        "Inactivo": "#ff9500",
        "Registro pendiente": "#a78bfa",
        "Invitacion vencida": "#a78bfa",
        "Pausado": "#ff9500",
    }

    def _resumir(self):
        r = self.registros
        self.t_total.poner(len(r))
        self.t_telefonos.poner(sum(1 for x in r if x.get("telefono")))

        conteo = {}
        for x in r:
            clave = x.get("estatus") or "Sin estatus"
            conteo[clave] = conteo.get(clave, 0) + 1

        # Una tarjeta por estatus, del mas numeroso al menos
        orden = sorted(conteo, key=lambda k: -conteo[k])
        for clave in orden:
            if clave not in self.tarjetas:
                self.tarjetas[clave] = Tarjeta(clave, self.COLORES.get(clave, SUAVE))
            self.tarjetas[clave].poner(conteo[clave])

        for i in reversed(range(self.rejilla.count())):
            self.rejilla.itemAt(i).widget().setParent(None)

        widgets = [self.t_total, self.t_telefonos] + [self.tarjetas[c] for c in orden]
        for i, w in enumerate(widgets):      # 3 por fila: la ventana es angosta
            self.rejilla.addWidget(w, i // 3, i % 3)

        # El desglose por escrito: se ve que las partes suman el total
        if conteo:
            partes = "  ".join(f"{c}: {conteo[c]}" for c in orden)
            self.escribir(f"Desglose  ->  {partes}   (total {len(r)})")

    def closeEvent(self, evento):
        # Avisa al trabajador que se detenga en el proximo lote
        self.trabajador.cancelado = True

        # Cerrar Chrome desde el hilo que lo creo, no desde este
        self.ordenes.cerrar.emit()

        self.hilo.quit()
        if not self.hilo.wait(6000):
            # Si el hilo sigue ocupado (una peticion larga), cerramos igual;
            # los procesos sueltos de Chrome los limpia el proximo arranque.
            self.hilo.terminate()
            self.hilo.wait(1500)
        evento.accept()


def _carpeta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    # Sin consola no hay donde ver un fallo de arranque: se deja por escrito.
    registro_error = os.path.join(_carpeta_base(), "error_arranque.txt")

    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        ventana = Ventana()
        ventana.show()
        ventana.raise_()
        ventana.activateWindow()
        ventana.escribir("Extractor de Drivers listo.")
        ventana.escribir("Presiona '1 · Abrir Mercado Libre' para empezar.")
        codigo = app.exec()
        # Si llegamos aqui todo fue bien; no dejar basura de corridas previas
        try:
            if os.path.exists(registro_error):
                os.remove(registro_error)
        except Exception:
            pass
        sys.exit(codigo)
    except Exception:
        try:
            with open(registro_error, "w", encoding="utf-8") as f:
                f.write("El programa no pudo arrancar.\n\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()

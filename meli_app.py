# -*- coding: utf-8 -*-
"""
Extractor de Drivers de Mercado Libre - Interfaz grafica (PySide6)

Todo se maneja con botones: no hay que presionar ENTER en una terminal.
El registro de actividad se ve en un panel dentro de la misma ventana.

Flujo:
  1. "Abrir Mercado Libre"  -> lanza Chrome en la pagina de drivers
  2. Inicias sesion a mano
  3. "Ya inicie sesion"     -> extrae el listado por API (segundos)
  4. "Traer telefonos"      -> opcional, consulta las fichas
  5. "Guardar resultado"    -> escribe el TXT y el CSV
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
    extraer = Signal()
    contactos = Signal()
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
    def extraer_listado(self):
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            if not self._preparar_pagina():
                return

            self.log("Consultando la API del listado...")
            inicio = time.time()
            self.registros = nucleo.extraer_todo(self.driver)
            tardo = time.time() - inicio

            if not self.registros:
                self.puente.fallo.emit(
                    "La API no devolvio registros.\n\n"
                    "Revisa que la lista de drivers este visible en Chrome "
                    "y que tu sesion siga activa."
                )
                return

            self.log(f"Listo: {len(self.registros)} drivers en {tardo:.1f} s")
            self.puente.terminado.emit("listado", self.registros)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

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
                    "3. Presiona otra vez el boton 2"
                )
                return False
            if "401" in texto or "403" in texto or "no devolvio json" in texto:
                self.puente.fallo.emit(
                    "Tu sesion de Mercado Libre no esta activa.\n\n"
                    "Inicia sesion en la ventana de Chrome y vuelve a "
                    "presionar el boton 2."
                )
                return False

        self.puente.fallo.emit(
            "No se pudo consultar la lista de drivers.\n\n"
            "Revisa que en Chrome se vea la lista de transportistas y que "
            "tu sesion siga abierta, luego presiona otra vez el boton 2."
        )
        return False

    @Slot()
    def traer_contactos(self):
        try:
            if not self.registros:
                self.puente.fallo.emit("Primero hay que extraer el listado.")
                return

            total = sum(
                1 for r in self.registros if r.get("id") and r["id"] != "0"
            )
            self.puente.avance.emit(0, total)

            # Enganchar el avance del nucleo al de la ventana
            hechos = {"n": 0}
            original = nucleo.pedir_lote_perfiles

            def con_avance(driver, ids):
                if self.cancelado:
                    raise KeyboardInterrupt("cancelado por el usuario")
                res = original(driver, ids)
                hechos["n"] += len(ids)
                self.puente.avance.emit(min(hechos["n"], total), total)
                return res

            nucleo.pedir_lote_perfiles = con_avance
            try:
                nucleo.completar_contactos(self.driver, self.registros)
            finally:
                nucleo.pedir_lote_perfiles = original

            self.puente.terminado.emit("contactos", self.registros)
        except KeyboardInterrupt:
            self.log("Consulta de fichas cancelada.")
            self.puente.terminado.emit("contactos", self.registros)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

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
                "presionar el boton 2."
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
        caja.setContentsMargins(14, 10, 14, 10)
        caja.setSpacing(2)

        self.valor = QLabel("-")
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.valor.setFont(f)
        self.valor.setStyleSheet(f"color: {color}; border: none;")

        self.texto = QLabel(etiqueta)
        self.texto.setStyleSheet(f"color: {SUAVE}; font-size: 11px; border: none;")

        caja.addWidget(self.valor)
        caja.addWidget(self.texto)

    def poner(self, v):
        self.valor.setText(str(v))


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Extractor de Drivers - Mercado Libre")
        self.resize(880, 660)
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
        raiz.setContentsMargins(22, 18, 22, 18)
        raiz.setSpacing(14)

        # --- encabezado ---
        titulo = QLabel("Extractor de Drivers")
        f = QFont()
        f.setPointSize(19)
        f.setBold(True)
        titulo.setFont(f)
        titulo.setStyleSheet(f"color: {TEXTO};")
        raiz.addWidget(titulo)

        self.paso = QLabel("Paso 1 de 3  ·  Abre Mercado Libre e inicia sesion")
        self.paso.setStyleSheet(f"color: {AMARILLO}; font-size: 13px;")
        raiz.addWidget(self.paso)

        # --- botones ---
        fila = QHBoxLayout()
        fila.setSpacing(10)

        self.b_abrir = self._boton("1 · Abrir Mercado Libre", AZUL, True)
        self.b_extraer = self._boton("2 · Ya inicie sesion, extraer", VERDE)
        self.b_contactos = self._boton("3 · Traer telefonos (opcional)", PANEL)
        self.b_guardar = self._boton("Guardar resultado", AMARILLO)

        self.b_abrir.clicked.connect(self.al_abrir)
        self.b_extraer.clicked.connect(self.al_extraer)
        self.b_contactos.clicked.connect(self.al_contactos)
        self.b_guardar.clicked.connect(self.al_guardar)

        for b in (self.b_abrir, self.b_extraer, self.b_contactos, self.b_guardar):
            fila.addWidget(b)
        raiz.addLayout(fila)

        self.b_extraer.setEnabled(False)
        self.b_contactos.setEnabled(False)
        self.b_guardar.setEnabled(False)

        # --- tarjetas ---
        rejilla = QGridLayout()
        rejilla.setSpacing(10)
        self.t_total = Tarjeta("Drivers", TEXTO)
        self.t_activos = Tarjeta("Activos", VERDE)
        self.t_bloqueados = Tarjeta("Bloqueados", ROJO)
        self.t_telefonos = Tarjeta("Con telefono", AZUL)
        for i, t in enumerate(
            (self.t_total, self.t_activos, self.t_bloqueados, self.t_telefonos)
        ):
            rejilla.addWidget(t, 0, i)
        raiz.addLayout(rejilla)

        # --- barra de avance ---
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setFixedHeight(22)
        self.barra.setStyleSheet(
            f"QProgressBar {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 5px; color: {TEXTO}; font-size: 11px; }}"
            f"QProgressBar::chunk {{ background: {AZUL}; border-radius: 4px; }}"
        )
        self.barra.hide()
        raiz.addWidget(self.barra)

        # --- registro ---
        etiqueta = QLabel("Registro de actividad")
        etiqueta.setStyleSheet(f"color: {SUAVE}; font-size: 11px;")
        raiz.addWidget(etiqueta)

        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setStyleSheet(
            f"QPlainTextEdit {{ background: #16181d; color: #b9c0cb;"
            f" border: 1px solid {BORDE}; border-radius: 8px; padding: 10px;"
            f" font-family: Consolas, monospace; font-size: 12px; }}"
        )
        raiz.addWidget(self.registro, 1)

        # --- pie ---
        self.pie = QLabel("Listo para empezar")
        self.pie.setStyleSheet(f"color: {SUAVE}; font-size: 11px;")
        raiz.addWidget(self.pie)

    def _boton(self, texto, color, principal=False):
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(42)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        letra = "#1e2128" if color in (AMARILLO,) else "#ffffff"
        if color == PANEL:
            letra = TEXTO
        b.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {letra};"
            f" border: none; border-radius: 8px; font-size: 13px;"
            f" font-weight: 600; padding: 0 14px; }}"
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
        self.ordenes.extraer.connect(self.trabajador.extraer_listado)
        self.ordenes.contactos.connect(self.trabajador.traer_contactos)
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

    def al_extraer(self):
        self.b_extraer.setEnabled(False)
        self.pie.setText("Consultando la API...")
        self.ordenes.extraer.emit()

    def al_contactos(self):
        n = sum(1 for r in self.registros if r.get("id") and r["id"] != "0")
        minutos = max(1, round(n / 12 / 60))
        r = QMessageBox.question(
            self,
            "Traer telefonos y correos",
            f"Se consultara la ficha de {n} drivers para obtener su telefono, "
            f"correo y motivo de bloqueo.\n\n"
            f"Tomara alrededor de {minutos} a {minutos * 3} minutos.\n\n"
            "El listado que ya tienes no se pierde. Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if r != QMessageBox.Yes:
            return
        self.b_contactos.setEnabled(False)
        self.pie.setText("Consultando fichas... puedes seguir usando la PC.")
        self.ordenes.contactos.emit()

    def al_guardar(self):
        if not self.registros:
            return
        try:
            txt, csvf = nucleo.guardar(self.registros)
            self.rutas = (txt, csvf)
            self.escribir(f"Guardado: {os.path.basename(txt)}")
            self.escribir(f"Guardado: {os.path.basename(csvf)}")

            caja = QMessageBox(self)
            caja.setWindowTitle("Resultado guardado")
            caja.setIcon(QMessageBox.Information)
            caja.setText(
                f"Se guardaron {len(self.registros)} drivers.\n\n"
                f"{os.path.basename(txt)}\n{os.path.basename(csvf)}"
            )
            caja.setInformativeText(
                "El TXT se pega directo en Excel; el CSV se abre con doble clic."
            )
            abrir = caja.addButton("Abrir carpeta", QMessageBox.AcceptRole)
            caja.addButton("Cerrar", QMessageBox.RejectRole)
            caja.exec()

            if caja.clickedButton() is abrir:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(os.path.dirname(txt))
                )
        except Exception as e:
            QMessageBox.critical(self, "No se pudo guardar", str(e)[:300])

    # ------------------------------------------------------------ eventos
    def al_terminar(self, etapa, datos):
        QApplication.restoreOverrideCursor()

        if etapa == "navegador":
            self.paso.setText(
                "Paso 2 de 3  ·  Inicia sesion en Chrome, luego presiona el boton 2"
            )
            self._habilitar(self.b_extraer, True)
            self.b_abrir.setText("Reabrir Chrome")
            self.b_abrir.setEnabled(True)
            self.pie.setText("Esperando a que inicies sesion")

        elif etapa == "listado":
            self.registros = datos or []
            self._resumir()
            self.paso.setText(
                "Paso 3 de 3  ·  Guarda el resultado, o trae tambien los telefonos"
            )
            self._habilitar(self.b_contactos, True)
            self._habilitar(self.b_guardar, True)
            self.b_extraer.setEnabled(True)
            self.pie.setText(
                f"{len(self.registros)} drivers listos para guardar"
            )

            # Guardado automatico: no perder lo ya extraido
            try:
                txt, csvf = nucleo.guardar(self.registros)
                self.rutas = (txt, csvf)
                self.escribir(f"Respaldo automatico: {os.path.basename(txt)}")
            except Exception:
                pass

        elif etapa == "contactos":
            self.registros = datos or self.registros
            self._resumir()
            self.barra.hide()
            self._habilitar(self.b_contactos, True)
            self.b_contactos.setText("Reintentar fichas faltantes")
            self.pie.setText("Fichas consultadas. Ya puedes guardar.")

    def al_fallar(self, mensaje):
        QApplication.restoreOverrideCursor()
        self.barra.hide()
        self.escribir(f"ERROR: {mensaje.splitlines()[0]}")
        for b in (self.b_abrir, self.b_extraer, self.b_contactos, self.b_guardar):
            if b.property("listo") is True or b is self.b_abrir:
                b.setEnabled(True)
        QMessageBox.warning(self, "Algo salio mal", mensaje)
        self.pie.setText("Ocurrio un error, revisa el registro")

    def _resumir(self):
        r = self.registros
        self.t_total.poner(len(r))
        self.t_activos.poner(sum(1 for x in r if x.get("estatus") == "Activo"))
        self.t_bloqueados.poner(
            sum(1 for x in r if x.get("estatus") == "Bloqueado")
        )
        self.t_telefonos.poner(sum(1 for x in r if x.get("telefono")))

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

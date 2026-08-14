# -*- coding: utf-8 -*-
"""
Extractor de Prefacturas con ID de conductor - Interfaz grafica

Le das el numero de prefactura y hace todo:
  1. Baja el detalle de la prefactura (trae el ID de ruta)
  2. Baja el reporte de operacion del periodo (ruta -> ID de conductor)
  3. Cruza por NUMERO de ruta, no por nombre
  4. Le agrega CURP y telefono del padron
"""

import os
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QFrame, QMessageBox, QGridLayout,
    QSizePolicy, QLineEdit, QComboBox,
)

import extraer_billing as nucleo
import listar_prefacturas as lista

# ---------------------------------------------------------------- colores
FONDO = "#1e2128"
PANEL = "#272b34"
BORDE = "#3a3f4b"
TEXTO = "#e8eaed"
SUAVE = "#9aa0aa"
AMARILLO = "#ffe600"
AZUL = "#3483fa"
VERDE = "#00a650"
ROJO = "#f23d4f"

FUENTE = '"Segoe UI Semibold", "Segoe UI", Arial'
FUENTE_NUM = '"Segoe UI Black", "Segoe UI", Impact, Arial'


def barra_titulo_oscura(ventana):
    """Pinta de oscuro la barra de titulo, que la dibuja Windows y no Qt."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(ventana.winId()))
        dwm = ctypes.windll.dwmapi
        activar = ctypes.c_int(1)
        for atributo in (20, 19):
            if dwm.DwmSetWindowAttribute(
                hwnd, ctypes.c_uint(atributo),
                ctypes.byref(activar), ctypes.sizeof(activar),
            ) == 0:
                break
        r, g, b = (int(FONDO[i:i + 2], 16) for i in (1, 3, 5))
        color = ctypes.c_uint((b << 16) | (g << 8) | r)
        dwm.DwmSetWindowAttribute(
            hwnd, ctypes.c_uint(35),
            ctypes.byref(color), ctypes.sizeof(color),
        )
    except Exception:
        pass


def _carpeta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class Puente(QObject):
    mensaje = Signal(str)
    terminado = Signal(str, object)
    fallo = Signal(str)


class Ordenes(QObject):
    """Señales para pedirle trabajo al hilo secundario."""

    abrir = Signal()
    cargar_lista = Signal()
    extraer = Signal(str)
    cerrar = Signal()


class Trabajador(QObject):
    """Hace el trabajo fuera del hilo de la interfaz, que si no se congela."""

    def __init__(self, puente):
        super().__init__()
        self.puente = puente
        self.driver = None

    def log(self, t):
        self.puente.mensaje.emit(t)

    @Slot()
    def abrir_navegador(self):
        try:
            self.log("Preparando Chrome...")
            nucleo.log = self.log
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            self.driver = nucleo.crear_driver()
            self.driver.get("https://envios.adminml.com/logistics/billing/invoices")
            self.log("Chrome abierto. Inicia sesion en esa ventana.")
            self.puente.terminado.emit("navegador", None)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot()
    def cargar_lista(self):
        """Trae las prefacturas para llenar los desplegables."""
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            # El fetch corre dentro de la pagina: hay que estar en el panel
            if "billing" not in (self.driver.current_url or ""):
                self.driver.get(
                    "https://envios.adminml.com/logistics/billing/invoices")
                time.sleep(3)

            self.log("Buscando las prefacturas disponibles...")
            prefacturas = lista.bajar_lista(self.driver, log=self.log)
            if not prefacturas:
                self.puente.fallo.emit(
                    "No se encontraron prefacturas.\n\n"
                    "Revisa que hayas iniciado sesion y que se vea el "
                    "listado en Chrome."
                )
                return
            self.puente.terminado.emit("lista", prefacturas)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot(str)
    def extraer(self, id_pref):
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            # Situarnos en la prefactura: el fetch corre dentro de la pagina
            url = nucleo.WEB + id_pref
            if id_pref not in (self.driver.current_url or ""):
                self.log(f"Abriendo la prefactura {id_pref}...")
                self.driver.get(url)
                time.sleep(4)

            # 1) Detalle de la prefactura
            self.log("Paso 1 de 3: detalle de la prefactura...")
            filas, periodo, crudo = nucleo.bajar_detalle(self.driver, id_pref)
            cabecera = nucleo.cabecera_prefactura(crudo)
            if not filas:
                self.puente.fallo.emit(
                    "La prefactura no trajo lineas de detalle.\n\n"
                    "Revisa que el numero sea correcto y que la sesion "
                    "siga activa."
                )
                return

            # 2) Reporte del periodo
            desde, hasta = nucleo.periodo_a_fechas(periodo)
            if not desde:
                self.puente.fallo.emit(
                    f"No se entendio el periodo '{periodo}'.\n\n"
                    "Se esperaba algo como 202607Q1."
                )
                return

            self.log("Paso 2 de 3: reporte de operacion del periodo...")
            mapa = {}
            try:
                mapa = nucleo.bajar_mapa_rutas(self.driver, desde, hasta)
            except Exception as e:
                self.log(f"No se pudo traer el reporte: {str(e)[:120]}")
                self.log("Se continua sin ID de usuario.")

            # 3) Cruce por numero de ruta
            self.log("Paso 3 de 3: cruzando por ID de ruta...")
            con_id = sin_ruta = sin_mapa = 0
            for f in filas:
                ruta = f.get("ruta", "")
                if not ruta:
                    sin_ruta += 1
                    continue
                info = mapa.get(ruta)
                if not info:
                    sin_mapa += 1
                    continue
                f["id_usuario"] = info["id"]
                f["nombre"] = info["nombre"]
                con_id += 1

            ruta_csv = nucleo.guardar(filas, id_pref, periodo, cabecera)
            self.log(f"Guardado: {os.path.basename(ruta_csv)}")

            # Comprobar contra lo que declara Meli
            suma = 0.0
            for f in filas:
                try:
                    suma += float((f.get("total") or "0").replace(",", ""))
                except ValueError:
                    pass
            declarado = cabecera.get("total", 0)
            if declarado:
                dif = round(suma - declarado, 2)
                if abs(dif) < 0.01:
                    self.log(f"El detalle cuadra con Meli: {declarado:,.2f}")
                else:
                    self.log(f"OJO: el detalle da {suma:,.2f} y Meli declara "
                             f"{declarado:,.2f} (difieren {dif:,.2f})")

            resumen = {
                "filas": len(filas), "con_id": con_id,
                # Cuantas personas distintas aparecen en la prefactura
                "con_curp": len({f["id_usuario"] for f in filas
                                 if f.get("id_usuario")}),
                "sin_ruta": sin_ruta, "sin_mapa": sin_mapa,
                "periodo": periodo, "desde": desde, "hasta": hasta,
                "rutas_mapa": len(mapa),
                "declarado": cabecera.get("total", 0),
                "suma": suma,
                "cuadra": abs(round(suma - cabecera.get("total", 0), 2)) < 0.01,
            }
            self.puente.terminado.emit("listo", (resumen, ruta_csv))

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

    def _explicar(self, e):
        t = str(e).split("Stacktrace:")[0].strip()
        b = t.lower()
        if "user data directory is already in use" in b:
            return ("El perfil de Chrome esta en uso por otra ventana.\n\n"
                    "Cierra las ventanas que abrio este programa y reintenta.")
        if "devtoolsactiveport" in b or "failed to start" in b:
            return ("Chrome no pudo arrancar.\n\n"
                    "Cierra Chrome y reintenta; si sigue, borra la carpeta "
                    "'chrome_profile' que esta junto al programa.")
        if "no such window" in b or "target window already closed" in b:
            return ("Se cerro la ventana de Chrome.\n\n"
                    "Presiona 'Abrir Mercado Libre' para empezar de nuevo.")
        if "failed to fetch" in b:
            return ("El navegador bloqueo la consulta.\n\n"
                    "Chrome debe estar en la pagina de Mercado Libre.")
        if "401" in b or "403" in b or "respondio 4" in b:
            return ("La sesion de Mercado Libre caduco.\n\n"
                    "Inicia sesion otra vez en la ventana de Chrome.")
        return t[:400] if t else type(e).__name__


class Tarjeta(QFrame):
    def __init__(self, etiqueta, color=TEXTO):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 7px; }}"
        )
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 6, 10, 6)
        caja.setSpacing(1)

        self.valor = QLabel("-")
        self.valor.setStyleSheet(
            f"color: {color}; border: none; font-family: {FUENTE_NUM};"
            f" font-size: 21px; font-weight: 900;"
        )
        self.texto = QLabel(etiqueta.upper())
        self.texto.setStyleSheet(
            f"color: {SUAVE}; border: none; font-family: {FUENTE};"
            f" font-size: 9px; font-weight: 700; letter-spacing: 1px;"
        )
        caja.addWidget(self.valor)
        caja.addWidget(self.texto)

    def poner(self, v):
        self.valor.setText(str(v))


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prefacturas con ID - Mercado Libre")
        self.resize(620, 470)
        self.setMinimumSize(540, 420)
        self.archivo = None        # el CSV generado
        self._armar()
        self._hilo()

    def _armar(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background: {FONDO};")
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(7)

        titulo = QLabel("PREFACTURAS CON ID")
        titulo.setStyleSheet(
            f"color: {TEXTO}; font-family: {FUENTE_NUM}; font-size: 17px;"
            f" font-weight: 900; letter-spacing: 1px;"
        )
        raiz.addWidget(titulo)

        self.paso = QLabel("Paso 1 de 2  ·  Abre Mercado Libre e inicia sesion")
        self.paso.setStyleSheet(
            f"color: {AMARILLO}; font-family: {FUENTE}; font-size: 11px;"
            f" font-weight: 600;"
        )
        raiz.addWidget(self.paso)

        # --- elegir la prefactura por mes y Q ---
        fila_sel = QHBoxLayout()
        fila_sel.setSpacing(7)

        est_etiqueta = (f"color: {SUAVE}; font-family: {FUENTE};"
                        f" font-size: 11px;")
        est_combo = (
            f"QComboBox {{ background: {PANEL}; color: {TEXTO};"
            f" border: 1px solid {BORDE}; border-radius: 6px; padding: 0 8px;"
            f" font-family: {FUENTE}; font-size: 11px; }}"
            f"QComboBox:hover {{ border: 1px solid {AZUL}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {PANEL};"
            f" color: {TEXTO}; selection-background-color: {AZUL}; }}"
        )

        eti_anio = QLabel("Año")
        eti_anio.setStyleSheet(est_etiqueta)
        self.combo_anio = QComboBox()
        self.combo_anio.setFixedHeight(28)
        self.combo_anio.setStyleSheet(est_combo)
        self.combo_anio.currentIndexChanged.connect(self.al_cambiar_anio)

        eti_mes = QLabel("Mes")
        eti_mes.setStyleSheet(est_etiqueta)
        self.combo_mes = QComboBox()
        self.combo_mes.setFixedHeight(28)
        self.combo_mes.setStyleSheet(est_combo)
        self.combo_mes.currentIndexChanged.connect(self.al_cambiar_mes)

        eti_q = QLabel("Q")
        eti_q.setStyleSheet(est_etiqueta)
        self.combo_q = QComboBox()
        self.combo_q.setFixedHeight(28)
        self.combo_q.setStyleSheet(est_combo)
        self.combo_q.currentIndexChanged.connect(self.al_cambiar_q)

        fila_sel.addWidget(eti_anio)
        fila_sel.addWidget(self.combo_anio, 2)
        fila_sel.addWidget(eti_mes)
        fila_sel.addWidget(self.combo_mes, 3)
        fila_sel.addWidget(eti_q)
        fila_sel.addWidget(self.combo_q, 1)
        raiz.addLayout(fila_sel)

        # Que prefactura quedo elegida (siempre Regular · Last Mile)
        self.elegida = QLabel("Abre Mercado Libre para ver las prefacturas")
        self.elegida.setStyleSheet(
            f"color: {SUAVE}; font-family: {FUENTE}; font-size: 11px;"
            f" padding: 2px 0;"
        )
        raiz.addWidget(self.elegida)

        for c in (self.combo_anio, self.combo_mes, self.combo_q):
            c.setEnabled(False)
        self.prefacturas = []      # todas las del listado
        self.actual = None         # la elegida ahora mismo

        # --- botones ---
        fila = QHBoxLayout()
        fila.setSpacing(7)
        self.b_abrir = self._boton("1 · Abrir Mercado Libre", AZUL)
        self.b_extraer = self._boton("2 · Extraer TODO", VERDE)
        self.b_carpeta = self._boton("Abrir carpeta", AMARILLO)
        self.b_abrir.clicked.connect(self.al_abrir)
        self.b_extraer.clicked.connect(self.al_extraer)
        self.b_carpeta.clicked.connect(self.al_carpeta)
        for b in (self.b_abrir, self.b_extraer, self.b_carpeta):
            fila.addWidget(b)
        fila.setStretch(0, 2)
        fila.setStretch(1, 3)
        fila.setStretch(2, 2)
        raiz.addLayout(fila)
        self.b_extraer.setEnabled(False)
        self.b_carpeta.setEnabled(False)

        # --- tarjetas ---
        rejilla = QGridLayout()
        rejilla.setSpacing(6)
        self.t_lineas = Tarjeta("Lineas", TEXTO)
        self.t_id = Tarjeta("Con ID usuario", VERDE)
        self.t_curp = Tarjeta("Conductores", AZUL)
        for i, t in enumerate((self.t_lineas, self.t_id, self.t_curp)):
            rejilla.addWidget(t, 0, i)
        raiz.addLayout(rejilla)

        # --- registro ---
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(100)
        self.registro.setStyleSheet(
            f"QPlainTextEdit {{ background: #16181d; color: #b9c0cb;"
            f" border: 1px solid {BORDE}; border-radius: 6px; padding: 6px;"
            f" font-family: Consolas, monospace; font-size: 10px; }}"
        )
        raiz.addWidget(self.registro, 1)

        self.pie = QLabel("Listo para empezar")
        self.pie.setStyleSheet(
            f"color: {SUAVE}; font-family: {FUENTE}; font-size: 10px;"
        )
        raiz.addWidget(self.pie)

    def _boton(self, texto, color):
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(30)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        letra = "#1e2128" if color == AMARILLO else "#ffffff"
        b.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {letra};"
            f" border: none; border-radius: 6px; font-family: {FUENTE};"
            f" font-size: 11px; font-weight: 800; padding: 0 8px;"
            f" letter-spacing: 0.4px; }}"
            f"QPushButton:disabled {{ background: #2c3038; color: #5a616d; }}"
        )
        return b

    def _hilo(self):
        self.puente = Puente()
        self.ordenes = Ordenes()
        self.hilo = QThread()
        self.trabajador = Trabajador(self.puente)
        self.trabajador.moveToThread(self.hilo)

        self.ordenes.abrir.connect(self.trabajador.abrir_navegador)
        self.ordenes.cargar_lista.connect(self.trabajador.cargar_lista)
        self.ordenes.extraer.connect(self.trabajador.extraer)
        self.ordenes.cerrar.connect(self.trabajador.cerrar)

        self.puente.mensaje.connect(self.escribir)
        self.puente.terminado.connect(self.al_terminar)
        self.puente.fallo.connect(self.al_fallar)
        self.hilo.start()

    # --------------------------------------------------------- acciones
    def escribir(self, t):
        hora = datetime.now().strftime("%H:%M:%S")
        self.registro.appendPlainText(f"[{hora}]  {t}")
        self.registro.verticalScrollBar().setValue(
            self.registro.verticalScrollBar().maximum()
        )

    def al_abrir(self):
        self.b_abrir.setEnabled(False)
        self.escribir("Abriendo Chrome...")
        self.pie.setText("Abriendo Chrome, espera un momento...")
        self.ordenes.abrir.emit()

    def llenar_selectores(self, prefacturas):
        """Llena los tres desplegables: año actual, ultimo mes, ultimo Q."""
        self.prefacturas = prefacturas
        anios = lista.anios_disponibles(prefacturas, "regular", "last_mile")

        if not anios:
            self.elegida.setText("No hay prefacturas para elegir")
            return

        self.combo_anio.blockSignals(True)
        self.combo_anio.clear()
        for a in anios:
            self.combo_anio.addItem(a, a)
        # El año en curso si tiene prefacturas; si no, el mas reciente
        preferido = lista.anio_por_defecto(prefacturas, "regular", "last_mile")
        i = self.combo_anio.findData(preferido)
        self.combo_anio.setCurrentIndex(i if i >= 0 else 0)
        self.combo_anio.blockSignals(False)

        for c in (self.combo_anio, self.combo_mes, self.combo_q):
            c.setEnabled(True)

        self.escribir(f"{len(prefacturas)} prefacturas en el listado")
        self.al_cambiar_anio()

    def al_cambiar_anio(self):
        """Al elegir año, recargar sus meses y quedarse en el ultimo."""
        anio = self.combo_anio.currentData()
        if not anio:
            return
        meses = lista.meses_de_anio(
            self.prefacturas, anio, "regular", "last_mile")

        self.combo_mes.blockSignals(True)
        self.combo_mes.clear()
        for clave, etiqueta in meses:
            self.combo_mes.addItem(etiqueta, clave)
        self.combo_mes.setCurrentIndex(0)      # el mes mas reciente
        self.combo_mes.blockSignals(False)
        self.al_cambiar_mes()

    def al_cambiar_mes(self):
        """Al elegir mes, recargar sus quincenas y quedarse en la ultima."""
        mes = self.combo_mes.currentData()
        if not mes:
            self.actual = None
            self.combo_q.clear()
            self.elegida.setText("Sin prefacturas ese año")
            return
        quincenas = lista.quincenas_de_mes(
            self.prefacturas, mes, "regular", "last_mile")

        self.combo_q.blockSignals(True)
        self.combo_q.clear()
        for q, pres in quincenas:
            self.combo_q.addItem(q, pres)
        self.combo_q.setCurrentIndex(0)        # Q2 antes que Q1
        self.combo_q.blockSignals(False)
        self.al_cambiar_q()

    def al_cambiar_q(self):
        """Mostrar la prefactura que corresponde a mes + Q."""
        pres = self.combo_q.currentData()
        if not pres:
            self.actual = None
            self.elegida.setText("Sin prefactura para ese periodo")
            return

        # Si hay varias, la de id mas alto es la ultima emitida
        self.actual = sorted(pres, key=lambda p: int(p["id"] or 0),
                             reverse=True)[0]
        texto = lista.describir(self.actual)
        if len(pres) > 1:
            texto += f"   (+{len(pres) - 1} mas en el periodo)"
        self.elegida.setText(texto)
        self.elegida.setStyleSheet(
            f"color: {TEXTO}; font-family: {FUENTE}; font-size: 11px;"
            f" padding: 2px 0;"
        )

    def al_extraer(self):
        if not self.b_extraer.isEnabled():
            return
        if not self.actual:
            QMessageBox.warning(
                self, "Sin prefactura",
                "Elige un mes y una quincena con prefactura disponible."
            )
            return
        id_pref = self.actual["id"]
        self.b_extraer.setEnabled(False)
        self.b_extraer.setText("Extrayendo...")
        self.pie.setText("Extrayendo. Puedes seguir usando la PC.")
        self.escribir(f"Extrayendo la prefactura {id_pref} "
                      f"({lista.periodo_legible(self.actual['periodo'])})...")
        self.ordenes.extraer.emit(id_pref)

    def al_carpeta(self):
        destino = os.path.dirname(self.archivo) if self.archivo else _carpeta_base()
        QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    def al_terminar(self, etapa, datos):
        if etapa == "navegador":
            self.paso.setText(
                "Paso 2 de 2  ·  Elige el periodo y presiona 'Extraer TODO'"
            )
            self.b_extraer.setEnabled(True)
            self.b_extraer.setProperty("listo", True)
            self.b_abrir.setText("Reabrir Chrome")
            self.b_abrir.setEnabled(True)
            self.pie.setText("Buscando las prefacturas disponibles...")
            # Llenar los desplegables solos, sin que el usuario haga nada
            self.ordenes.cargar_lista.emit()

        elif etapa == "lista":
            self.llenar_selectores(datos)
            self.pie.setText("Listo para extraer")

        elif etapa == "listado" or etapa == "listo":
            resumen, archivo = datos
            self.archivo = archivo
            self.t_lineas.poner(resumen["filas"])
            self.t_id.poner(resumen["con_id"])
            self.t_curp.poner(resumen["con_curp"])

            self.paso.setText("Listo  ·  El archivo ya esta guardado")
            self.b_extraer.setText("Extraer otra vez")
            self.b_extraer.setEnabled(True)
            self.b_carpeta.setEnabled(True)
            self.b_carpeta.setProperty("listo", True)
            self.pie.setText(f"{resumen['filas']} lineas guardadas")
            self._avisar(resumen, archivo)

    def al_fallar(self, mensaje):
        self.escribir(f"ERROR: {mensaje.splitlines()[0]}")
        self.b_abrir.setEnabled(True)
        self.b_extraer.setText("2 · Extraer TODO")
        for b in (self.b_extraer, self.b_carpeta):
            if b.property("listo") is True:
                b.setEnabled(True)
        aviso = QMessageBox(self)
        aviso.setWindowTitle("Algo salio mal")
        aviso.setIcon(QMessageBox.Warning)
        aviso.setText(mensaje)
        aviso.show()
        barra_titulo_oscura(aviso)
        aviso.exec()
        self.pie.setText("Ocurrio un error, revisa el registro")

    def _avisar(self, r, archivo):
        detalle = [
            f"Periodo {r['periodo']}  ({r['desde']} a {r['hasta']})",
            f"{r['con_id']} lineas con ID de usuario",
            f"{r['con_curp']} conductores distintos",
        ]
        # Lo primero que hay que saber: cuadra con lo que cobra Meli?
        if r.get("declarado"):
            if r.get("cuadra"):
                detalle.insert(1, f"Total {r['declarado']:,.2f} — cuadra con Meli")
            else:
                detalle.insert(1, f"OJO: el detalle da {r['suma']:,.2f} y Meli "
                                  f"declara {r['declarado']:,.2f}")
        if r["sin_mapa"]:
            detalle.append(
                f"{r['sin_mapa']} rutas no estaban en el reporte del periodo"
            )
        if r["sin_ruta"]:
            detalle.append(f"{r['sin_ruta']} lineas sin ID de ruta")

        caja = QMessageBox(self)
        caja.setWindowTitle("Extraccion completa")
        caja.setIcon(QMessageBox.Information)
        caja.setText(f"Se extrajeron {r['filas']} lineas.\n\n" + "\n".join(detalle))
        caja.setInformativeText(os.path.basename(archivo))
        abrir = caja.addButton("Abrir carpeta", QMessageBox.AcceptRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.show()
        barra_titulo_oscura(caja)
        caja.exec()
        if caja.clickedButton() is abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(archivo)))

    def closeEvent(self, evento):
        self.ordenes.cerrar.emit()
        self.hilo.quit()
        if not self.hilo.wait(6000):
            self.hilo.terminate()
            self.hilo.wait(1500)
        evento.accept()


def main():
    registro_error = os.path.join(_carpeta_base(), "error_arranque.txt")
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        v = Ventana()
        v.show()
        barra_titulo_oscura(v)
        v.raise_()
        v.activateWindow()
        v.escribir("Extractor de prefacturas listo.")
        v.escribir("Presiona '1 · Abrir Mercado Libre' para empezar.")
        codigo = app.exec()
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

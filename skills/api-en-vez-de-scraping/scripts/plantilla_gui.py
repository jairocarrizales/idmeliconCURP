# -*- coding: utf-8 -*-
"""
Plantilla de ventana para un extractor: PySide6, sin terminal.

Por que una GUI y no consola: con `input()`, cuando el foco esta en Chrome
la consola de Windows se traga las primeras pulsaciones de ENTER y el usuario
cree que el programa se colgo. Un boton no tiene ese problema.

Lo importante de la estructura:
  - El trabajo corre en un QThread: la ventana no se congela.
  - Se le pide por SEÑAL, no llamando al metodo: una llamada normal correria
    en el hilo de la interfaz y anularia el proposito.
  - Los errores se traducen antes de mostrarse.

Compilar:
    pyinstaller --onefile --windowed --name MiExtractor \
                --collect-all selenium plantilla_gui.py
"""

import os
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QFrame, QMessageBox, QGridLayout, QSizePolicy,
)

# ---------------------------------------------------------------- apariencia
FONDO, PANEL, BORDE = "#1e2128", "#272b34", "#3a3f4b"
TEXTO, SUAVE = "#e8eaed", "#9aa0aa"
AMARILLO, AZUL, VERDE, ROJO = "#ffe600", "#3483fa", "#00a650", "#f23d4f"
FUENTE = '"Segoe UI Semibold", "Segoe UI", Arial'
FUENTE_NUM = '"Segoe UI Black", "Segoe UI", Impact, Arial'


def barra_titulo_oscura(ventana):
    """La barra de titulo la dibuja Windows, no Qt: hay que pedirselo aparte.

    El atributo 20 (modo oscuro) funciona desde Win10 20H1; el 35 (color
    exacto) solo en Win11. En Win10 la barra queda negra, que es lo mas
    parecido posible.
    """
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
                ctypes.byref(activar), ctypes.sizeof(activar)) == 0:
                break
        r, g, b = (int(FONDO[i:i + 2], 16) for i in (1, 3, 5))
        color = ctypes.c_uint((b << 16) | (g << 8) | r)   # COLORREF: 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(35),
                                  ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass


def carpeta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class Puente(QObject):
    """Del hilo de trabajo hacia la ventana."""

    mensaje = Signal(str)
    avance = Signal(int, int)
    terminado = Signal(str, object)
    fallo = Signal(str)


class Ordenes(QObject):
    """De la ventana hacia el hilo de trabajo.

    Hay que usar señales: llamar el metodo directo lo ejecutaria en el hilo
    de la interfaz y la congelaria.
    """

    abrir = Signal()
    trabajar = Signal()
    cerrar = Signal()


class Trabajador(QObject):
    def __init__(self, puente):
        super().__init__()
        self.puente = puente
        self.driver = None
        self.cancelado = False

    def log(self, t):
        self.puente.mensaje.emit(t)

    @Slot()
    def abrir_navegador(self):
        try:
            self.log("Preparando Chrome...")
            # from perfil_chrome import crear_driver
            # self.driver = crear_driver()
            # self.driver.get(URL_PANEL)
            self.log("Chrome abierto. Inicia sesion en esa ventana.")
            self.puente.terminado.emit("navegador", None)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot()
    def trabajar(self):
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            self.log("Paso 1 de 2: descargando...")
            # datos = mi_extraccion(self.driver)

            # Guarda ANTES de los pasos opcionales: si el siguiente falla,
            # no se pierde lo que ya costo traer.

            self.log("Paso 2 de 2: guardando...")
            # rutas = guardar(datos)

            self.puente.terminado.emit("listo", ({"filas": 0}, ("a.txt", "b.csv")))
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
        texto = str(e).split("Stacktrace:")[0].strip()
        bajo = texto.lower()
        if "user data directory is already in use" in bajo:
            return ("El perfil de Chrome esta en uso por otra ventana.\n\n"
                    "Cierra las que abrio este programa y reintenta.")
        if "devtoolsactiveport" in bajo or "failed to start" in bajo:
            return ("Chrome no pudo arrancar.\n\n"
                    "Cierra Chrome; si sigue, borra la carpeta "
                    "'chrome_profile' que esta junto al programa.")
        if "failed to fetch" in bajo:
            return ("El navegador bloqueo la consulta.\n\n"
                    "Debe estar en la pagina del panel.")
        if "401" in bajo or "403" in bajo:
            return "La sesion caduco.\n\nInicia sesion otra vez en Chrome."
        return texto[:400] if texto else type(e).__name__


class Tarjeta(QFrame):
    """Recuadro con un numero grande y su etiqueta."""

    def __init__(self, etiqueta, color=TEXTO):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {PANEL};"
                           f" border: 1px solid {BORDE}; border-radius: 7px; }}")
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 6, 10, 6)
        caja.setSpacing(1)
        self.valor = QLabel("-")
        self.valor.setStyleSheet(
            f"color: {color}; border: none; font-family: {FUENTE_NUM};"
            f" font-size: 21px; font-weight: 900;")
        self.texto = QLabel(etiqueta.upper())
        self.texto.setStyleSheet(
            f"color: {SUAVE}; border: none; font-family: {FUENTE};"
            f" font-size: 9px; font-weight: 700; letter-spacing: 1px;")
        caja.addWidget(self.valor)
        caja.addWidget(self.texto)

    def poner(self, v):
        self.valor.setText(str(v))


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mi Extractor")
        self.resize(560, 400)
        self.setMinimumSize(460, 340)
        self.rutas = None
        self._armar()
        self._hilo()

    def _armar(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background: {FONDO};")
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(7)

        titulo = QLabel("MI EXTRACTOR")
        titulo.setStyleSheet(f"color: {TEXTO}; font-family: {FUENTE_NUM};"
                             f" font-size: 17px; font-weight: 900;"
                             f" letter-spacing: 1px;")
        raiz.addWidget(titulo)

        self.paso = QLabel("Paso 1 de 2  ·  Abre el panel e inicia sesion")
        self.paso.setStyleSheet(f"color: {AMARILLO}; font-family: {FUENTE};"
                                f" font-size: 11px; font-weight: 600;")
        raiz.addWidget(self.paso)

        fila = QHBoxLayout()
        fila.setSpacing(7)
        self.b_abrir = self._boton("1 · Abrir el panel", AZUL)
        self.b_trabajar = self._boton("2 · Extraer TODO", VERDE)
        self.b_carpeta = self._boton("Abrir carpeta", AMARILLO)
        self.b_abrir.clicked.connect(self.al_abrir)
        self.b_trabajar.clicked.connect(self.al_trabajar)
        self.b_carpeta.clicked.connect(self.al_carpeta)
        for b in (self.b_abrir, self.b_trabajar, self.b_carpeta):
            fila.addWidget(b)
        fila.setStretch(1, 2)
        raiz.addLayout(fila)
        self.b_trabajar.setEnabled(False)
        self.b_carpeta.setEnabled(False)

        rejilla = QGridLayout()
        rejilla.setSpacing(6)
        self.t1 = Tarjeta("Registros", TEXTO)
        self.t2 = Tarjeta("Completos", VERDE)
        self.t3 = Tarjeta("Pendientes", AZUL)
        for i, t in enumerate((self.t1, self.t2, self.t3)):
            rejilla.addWidget(t, 0, i)
        raiz.addLayout(rejilla)

        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(90)
        self.registro.setStyleSheet(
            f"QPlainTextEdit {{ background: #16181d; color: #b9c0cb;"
            f" border: 1px solid {BORDE}; border-radius: 6px; padding: 6px;"
            f" font-family: Consolas, monospace; font-size: 10px; }}")
        raiz.addWidget(self.registro, 1)

        self.pie = QLabel("Listo para empezar")
        self.pie.setStyleSheet(f"color: {SUAVE}; font-family: {FUENTE};"
                               f" font-size: 10px;")
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
            f" font-size: 11px; font-weight: 800; padding: 0 8px; }}"
            f"QPushButton:disabled {{ background: #2c3038; color: #5a616d; }}")
        return b

    def _hilo(self):
        self.puente = Puente()
        self.ordenes = Ordenes()
        self.hilo = QThread()
        self.trabajador = Trabajador(self.puente)
        self.trabajador.moveToThread(self.hilo)

        self.ordenes.abrir.connect(self.trabajador.abrir_navegador)
        self.ordenes.trabajar.connect(self.trabajador.trabajar)
        self.ordenes.cerrar.connect(self.trabajador.cerrar)

        self.puente.mensaje.connect(self.escribir)
        self.puente.terminado.connect(self.al_terminar)
        self.puente.fallo.connect(self.al_fallar)
        self.hilo.start()

    def escribir(self, t):
        self.registro.appendPlainText(f"[{datetime.now():%H:%M:%S}]  {t}")
        self.registro.verticalScrollBar().setValue(
            self.registro.verticalScrollBar().maximum())

    def al_abrir(self):
        self.b_abrir.setEnabled(False)
        self.pie.setText("Abriendo Chrome...")
        self.ordenes.abrir.emit()

    def al_trabajar(self):
        self.b_trabajar.setEnabled(False)
        self.b_trabajar.setText("Extrayendo...")
        self.pie.setText("Trabajando. Puedes seguir usando la PC.")
        self.ordenes.trabajar.emit()

    def al_carpeta(self):
        destino = os.path.dirname(self.rutas[0]) if self.rutas else carpeta_base()
        QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    def al_terminar(self, etapa, datos):
        if etapa == "navegador":
            self.paso.setText("Paso 2 de 2  ·  Presiona 'Extraer TODO'")
            self.b_trabajar.setEnabled(True)
            self.b_trabajar.setProperty("listo", True)
            self.b_abrir.setText("Reabrir")
            self.b_abrir.setEnabled(True)
        elif etapa == "listo":
            resumen, rutas = datos
            self.rutas = rutas
            self.t1.poner(resumen.get("filas", 0))
            self.paso.setText("Listo  ·  El archivo ya esta guardado")
            self.b_trabajar.setText("Extraer otra vez")
            self.b_trabajar.setEnabled(True)
            self.b_carpeta.setEnabled(True)
            self.b_carpeta.setProperty("listo", True)

    def al_fallar(self, mensaje):
        self.escribir(f"ERROR: {mensaje.splitlines()[0]}")
        self.b_abrir.setEnabled(True)
        self.b_trabajar.setText("2 · Extraer TODO")
        for b in (self.b_trabajar, self.b_carpeta):
            if b.property("listo") is True:
                b.setEnabled(True)
        aviso = QMessageBox(self)
        aviso.setWindowTitle("Algo salio mal")
        aviso.setIcon(QMessageBox.Warning)
        aviso.setText(mensaje)
        aviso.show()
        barra_titulo_oscura(aviso)
        aviso.exec()

    def closeEvent(self, evento):
        self.trabajador.cancelado = True
        self.ordenes.cerrar.emit()          # cerrar Chrome desde su hilo
        self.hilo.quit()
        if not self.hilo.wait(6000):
            self.hilo.terminate()
            self.hilo.wait(1500)
        evento.accept()


def main():
    # Sin consola no hay donde ver un fallo de arranque: se deja por escrito
    registro_error = os.path.join(carpeta_base(), "error_arranque.txt")
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        v = Ventana()
        v.show()
        barra_titulo_oscura(v)      # despues de show(): antes no hay handle
        v.raise_()
        v.activateWindow()
        v.escribir("Listo. Presiona '1 · Abrir el panel' para empezar.")
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

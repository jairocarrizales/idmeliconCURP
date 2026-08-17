# -*- coding: utf-8 -*-
"""
Extractor de Rutas Diarias - Interfaz grafica

Eliges un rango de fechas en dos calendarios y presionas extraer. Por
defecto viene puesto el dia de ayer, que es el caso mas comun.
"""

import os
import sys
import time
import traceback
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QUrl, QDate
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QFrame, QMessageBox, QGridLayout,
    QSizePolicy, QDateEdit, QProgressBar, QCalendarWidget,
)

import extraer_rutas as nucleo

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
    """La barra de titulo la dibuja Windows, no Qt: hay que pedirselo."""
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
        color = ctypes.c_uint((b << 16) | (g << 8) | r)
        dwm.DwmSetWindowAttribute(hwnd, ctypes.c_uint(35),
                                  ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass


def _carpeta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class Puente(QObject):
    mensaje = Signal(str)
    avance = Signal(int, int)
    terminado = Signal(str, object)
    fallo = Signal(str)


class Ordenes(QObject):
    """Señales para pedirle trabajo al hilo secundario."""

    abrir = Signal()
    extraer = Signal(str, str)
    historial = Signal()
    cerrar = Signal()


class Trabajador(QObject):
    """Hace el trabajo fuera del hilo de la interfaz."""

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
            nucleo.log = self.log
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            self.driver = nucleo.crear_driver()
            self.driver.get(nucleo.PANEL)
            self.log("Chrome abierto. Inicia sesion en esa ventana.")
            self.puente.terminado.emit("navegador", None)
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot()
    def revisar_historial(self):
        """Busca desde que fecha MELI todavia tiene datos."""
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return
            if "adminml.com" not in (self.driver.current_url or ""):
                self.driver.get(nucleo.PANEL)
                time.sleep(3)

            self.log("Buscando hasta donde llega el historial...")
            viejo, sin_datos = nucleo.ultimo_dia_con_datos(
                self.driver, log=self.log)
            self.puente.terminado.emit("historial", (viejo, sin_datos))
        except Exception as e:
            self.puente.fallo.emit(self._explicar(e))

    @Slot(str, str)
    def extraer(self, desde, hasta):
        try:
            if not self.driver:
                self.puente.fallo.emit("Primero hay que abrir Chrome.")
                return

            if "adminml.com" not in (self.driver.current_url or ""):
                self.log("Volviendo al panel...")
                self.driver.get(nucleo.PANEL)
                time.sleep(3)

            # Comprobar que haya datos antes de gastar minutos extrayendo
            self.log("Comprobando que el rango tenga datos...")
            hay, aviso = nucleo.revisar_rango(
                self.driver, desde, hasta, log=self.log)
            if not hay:
                self.puente.fallo.emit("SINDATOS:" + aviso)
                return
            if aviso:
                self.log(f"AVISO: {aviso.splitlines()[0]}")

            registros = nucleo.bajar_reporte(self.driver, desde, hasta)
            if not registros:
                self.puente.fallo.emit(
                    f"No hay rutas del {desde} al {hasta}.\n\n"
                    "Revisa que el rango sea correcto y que la sesion siga "
                    "activa."
                )
                return

            conteo = nucleo.clasificar(registros)

            # El nombre de la ruta, con avance para la barra
            total = sum(1 for r in registros
                        if r.get("ID_Ruta") and not nucleo.sin_nombre_de_ruta(r))
            self.puente.avance.emit(0, total)
            hechos = {"n": 0}
            original = nucleo.pedir_lote_fichas

            def con_avance(driver, ids):
                if self.cancelado:
                    raise KeyboardInterrupt("cancelado")
                res = original(driver, ids)
                hechos["n"] += len(ids)
                self.puente.avance.emit(min(hechos["n"], total), total)
                return res

            nucleo.pedir_lote_fichas = con_avance
            try:
                nucleo.completar_nombres(self.driver, registros)
            except KeyboardInterrupt:
                self.log("  Cancelado; se guarda lo obtenido.")
            except Exception as e:
                self.log(f"No se pudieron traer los nombres: {str(e)[:110]}")
            finally:
                nucleo.pedir_lote_fichas = original

            rutas = nucleo.guardar(registros, desde, hasta)
            self.log(f"Guardado: {os.path.basename(rutas[1])}")

            esperan = [r for r in registros
                       if not nucleo.sin_nombre_de_ruta(r)]
            resumen = {
                "filas": len(registros),
                "con_id": sum(1 for r in registros if r.get("ID_USUARIO")),
                "con_nombre": sum(1 for r in registros if r.get("RUTA")),
                "esperan_nombre": len(esperan),
                "sp": conteo["SP"], "rd": conteo["RD"],
                "asistencia": conteo.get("AS", 0),
                "desde": desde, "hasta": hasta,
            }
            self.puente.terminado.emit("listo", (resumen, rutas[1]))

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
                    "Cierra las que abrio este programa y reintenta.")
        if "devtoolsactiveport" in b or "failed to start" in b:
            return ("Chrome no pudo arrancar.\n\n"
                    "Cierra Chrome; si sigue, borra la carpeta "
                    "'chrome_profile' que esta junto al programa.")
        if "no such window" in b or "target window already closed" in b:
            return ("Se cerro la ventana de Chrome.\n\n"
                    "Presiona 'Abrir Mercado Libre' para empezar de nuevo.")
        if "failed to fetch" in b:
            return ("El navegador bloqueo la consulta.\n\n"
                    "Chrome debe estar en la pagina de Mercado Libre.")
        if "401" in b or "403" in b or "respondio 4" in b:
            return ("La sesion caduco.\n\n"
                    "Inicia sesion otra vez en la ventana de Chrome.")
        return t[:400] if t else type(e).__name__


class Tarjeta(QFrame):
    def __init__(self, etiqueta, color=TEXTO):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 7px; }}")
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
        self.setWindowTitle("Rutas Diarias - Mercado Libre")
        self.resize(600, 470)
        self.setMinimumSize(520, 430)
        self.archivo = None
        self._armar()
        self._hilo()

    def _armar(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background: {FONDO};")
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(12, 10, 12, 10)
        raiz.setSpacing(7)

        titulo = QLabel("RUTAS DIARIAS")
        titulo.setStyleSheet(
            f"color: {TEXTO}; font-family: {FUENTE_NUM}; font-size: 17px;"
            f" font-weight: 900; letter-spacing: 1px;")
        raiz.addWidget(titulo)

        self.paso = QLabel("Paso 1 de 2  ·  Abre Mercado Libre e inicia sesion")
        self.paso.setStyleSheet(
            f"color: {AMARILLO}; font-family: {FUENTE}; font-size: 11px;"
            f" font-weight: 600;")
        raiz.addWidget(self.paso)

        # --- rango de fechas ---
        fila_f = QHBoxLayout()
        fila_f.setSpacing(7)
        est_eti = f"color: {SUAVE}; font-family: {FUENTE}; font-size: 11px;"
        # El calendario emergente: hay que darle color a cada parte, o Qt lo
        # dibuja con el tema claro sobre el fondo oscuro y no se lee.
        est_fecha = (
            f"QDateEdit {{ background: {PANEL}; color: {TEXTO};"
            f" border: 1px solid {BORDE}; border-radius: 6px;"
            f" padding: 0 6px 0 8px; font-family: {FUENTE};"
            f" font-size: 12px; font-weight: 600; }}"
            f"QDateEdit:hover {{ border: 1px solid {AZUL}; }}"
            f"QDateEdit::drop-down {{ subcontrol-origin: padding;"
            f" subcontrol-position: center right; width: 22px;"
            f" border-left: 1px solid {BORDE}; }}"
            f"QDateEdit::down-arrow {{ image: none; width: 0; height: 0;"
            f" border-left: 4px solid transparent;"
            f" border-right: 4px solid transparent;"
            f" border-top: 5px solid {AMARILLO}; }}"
            # El calendario
            f"QCalendarWidget QWidget {{ background: {PANEL};"
            f" color: {TEXTO}; }}"
            f"QCalendarWidget QAbstractItemView {{ background: {PANEL};"
            f" color: {TEXTO}; selection-background-color: {AZUL};"
            f" selection-color: white; outline: none; }}"
            # La barra de arriba, con mes y año
            f"QCalendarWidget QWidget#qt_calendar_navigationbar {{"
            f" background: {BORDE}; }}"
            f"QCalendarWidget QToolButton {{ background: transparent;"
            f" color: {TEXTO}; font-family: {FUENTE}; font-size: 12px;"
            f" font-weight: 700; padding: 4px 8px; border-radius: 4px; }}"
            f"QCalendarWidget QToolButton:hover {{ background: {AZUL}; }}"
            f"QCalendarWidget QToolButton::menu-indicator {{ image: none; }}"
            # Los desplegables de mes y año
            f"QCalendarWidget QMenu {{ background: {PANEL}; color: {TEXTO}; }}"
            f"QCalendarWidget QMenu::item:selected {{ background: {AZUL}; }}"
            f"QCalendarWidget QSpinBox {{ background: {PANEL}; color: {TEXTO};"
            f" selection-background-color: {AZUL}; }}"
            # Los dias de otro mes, apagados
            f"QCalendarWidget QAbstractItemView:disabled {{ color: {SUAVE}; }}"
        )

        # Por defecto, ayer: es lo que casi siempre se quiere
        ayer = QDate.currentDate().addDays(-1)

        eti_d = QLabel("Desde")
        eti_d.setStyleSheet(est_eti)
        self.f_desde = self._fecha(ayer, est_fecha)

        eti_h = QLabel("Hasta")
        eti_h.setStyleSheet(est_eti)
        self.f_hasta = self._fecha(ayer, est_fecha)

        # Atajos para los rangos que se piden a diario
        self.b_ayer = self._chico("Ayer")
        self.b_ayer.clicked.connect(lambda: self._rango(1, 1))
        self.b_semana = self._chico("7 dias")
        self.b_semana.clicked.connect(lambda: self._rango(7, 1))
        self.b_quincena = self._chico("15 dias")
        self.b_quincena.clicked.connect(lambda: self._rango(15, 1))

        fila_f.addWidget(eti_d)
        fila_f.addWidget(self.f_desde, 2)
        fila_f.addWidget(eti_h)
        fila_f.addWidget(self.f_hasta, 2)
        fila_f.addWidget(self.b_ayer)
        fila_f.addWidget(self.b_semana)
        fila_f.addWidget(self.b_quincena)
        raiz.addLayout(fila_f)

        # MELI no guarda el reporte indefinidamente: este boton dice
        # desde que fecha todavia se puede extraer
        self.b_historial = self._chico(
            "Hasta cuando hay datos en Mercado Libre")
        self.b_historial.clicked.connect(self.al_revisar_historial)
        self.b_historial.setEnabled(False)
        raiz.addWidget(self.b_historial)

        # --- botones ---
        fila = QHBoxLayout()
        fila.setSpacing(7)
        self.b_abrir = self._boton("1 · Abrir Mercado Libre", AZUL)
        self.b_extraer = self._boton("2 · Extraer rutas", VERDE)
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
        self.t_rutas = Tarjeta("Rutas", TEXTO)
        self.t_sp = Tarjeta("Service Partner", AZUL)
        self.t_rd = Tarjeta("RD / SDD", VERDE)
        self.t_as = Tarjeta("Assistance", AMARILLO)
        for i, t in enumerate((self.t_rutas, self.t_sp, self.t_rd,
                               self.t_as)):
            rejilla.addWidget(t, 0, i)
        raiz.addLayout(rejilla)

        # --- barra de avance ---
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setFixedHeight(15)
        self.barra.setStyleSheet(
            f"QProgressBar {{ background: {PANEL}; border: 1px solid {BORDE};"
            f" border-radius: 4px; color: {TEXTO}; font-size: 9px; }}"
            f"QProgressBar::chunk {{ background: {AZUL}; border-radius: 3px; }}")
        self.barra.hide()
        raiz.addWidget(self.barra)

        # --- registro ---
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(95)
        self.registro.setStyleSheet(
            f"QPlainTextEdit {{ background: #16181d; color: #b9c0cb;"
            f" border: 1px solid {BORDE}; border-radius: 6px; padding: 6px;"
            f" font-family: Consolas, monospace; font-size: 10px; }}")
        raiz.addWidget(self.registro, 1)

        self.pie = QLabel("Listo para empezar")
        self.pie.setStyleSheet(
            f"color: {SUAVE}; font-family: {FUENTE}; font-size: 10px;")
        raiz.addWidget(self.pie)

    def _fecha(self, valor, estilo):
        """Un campo de fecha cuyo calendario abre al hacer clic encima.

        Por defecto QDateEdit solo abre el calendario con la flechita, y hay
        que atinarle. Aqui abre al pinchar en cualquier parte del campo.
        """
        campo = QDateEdit(valor)
        campo.setCalendarPopup(True)
        campo.setDisplayFormat("dd/MM/yyyy")
        campo.setFixedHeight(30)
        campo.setMinimumWidth(120)
        campo.setStyleSheet(estilo)
        campo.setCursor(Qt.PointingHandCursor)
        campo.setToolTip("Clic para elegir la fecha en el calendario")

        # El calendario, con mes y año elegibles desde su barra
        cal = campo.calendarWidget()
        if cal:
            cal.setGridVisible(False)
            cal.setNavigationBarVisible(True)
            cal.setFirstDayOfWeek(Qt.Monday)
            # Sin la columna de numero de semana, que estorba
            try:
                cal.setVerticalHeaderFormat(
                    QCalendarWidget.NoVerticalHeader)
            except Exception:
                pass

        # Abrir al hacer clic en cualquier parte, no solo en la flecha
        original = campo.mousePressEvent

        def al_pinchar(evento, c=campo, o=original):
            o(evento)
            if evento.button() == Qt.LeftButton:
                # Qt no expone el popup directamente: se dispara con F4
                from PySide6.QtGui import QKeyEvent
                from PySide6.QtCore import QEvent
                tecla = QKeyEvent(QEvent.KeyPress, Qt.Key_F4, Qt.NoModifier)
                QApplication.sendEvent(c, tecla)

        campo.mousePressEvent = al_pinchar
        return campo

    def _rango(self, dias, hasta_hace):
        """Pone un rango que termina ayer y abarca 'dias' hacia atras."""
        fin = QDate.currentDate().addDays(-hasta_hace)
        self.f_hasta.setDate(fin)
        self.f_desde.setDate(fin.addDays(-(dias - 1)))

    def _chico(self, texto):
        b = QPushButton(texto)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(28)
        b.setStyleSheet(
            f"QPushButton {{ background: {PANEL}; color: {SUAVE};"
            f" border: 1px solid {BORDE}; border-radius: 6px;"
            f" font-family: {FUENTE}; font-size: 10px; padding: 0 8px; }}"
            f"QPushButton:hover {{ color: {TEXTO}; border-color: {AZUL}; }}")
        return b

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
            f"QPushButton:disabled {{ background: #2c3038; color: #5a616d; }}")
        return b

    def _hilo(self):
        self.puente = Puente()
        self.ordenes = Ordenes()
        self.hilo = QThread()
        self.trabajador = Trabajador(self.puente)
        self.trabajador.moveToThread(self.hilo)

        self.ordenes.abrir.connect(self.trabajador.abrir_navegador)
        self.ordenes.extraer.connect(self.trabajador.extraer)
        self.ordenes.historial.connect(self.trabajador.revisar_historial)
        self.ordenes.cerrar.connect(self.trabajador.cerrar)

        self.puente.mensaje.connect(self.escribir)
        self.puente.avance.connect(self.mover_barra)
        self.puente.terminado.connect(self.al_terminar)
        self.puente.fallo.connect(self.al_fallar)
        self.hilo.start()

    # --------------------------------------------------------- acciones
    def escribir(self, t):
        hora = datetime.now().strftime("%H:%M:%S")
        self.registro.appendPlainText(f"[{hora}]  {t}")
        self.registro.verticalScrollBar().setValue(
            self.registro.verticalScrollBar().maximum())

    def mover_barra(self, hechos, total):
        if total:
            self.barra.show()
            self.barra.setMaximum(total)
            self.barra.setValue(hechos)
            self.barra.setFormat(f"{hechos} de {total} nombres  (%p%)")

    def al_abrir(self):
        self.b_abrir.setEnabled(False)
        self.escribir("Abriendo Chrome...")
        self.pie.setText("Abriendo Chrome, espera un momento...")
        self.ordenes.abrir.emit()

    def al_extraer(self):
        desde = self.f_desde.date()
        hasta = self.f_hasta.date()
        if desde > hasta:
            QMessageBox.warning(
                self, "Rango invalido",
                "La fecha inicial es posterior a la final.")
            return

        dias = desde.daysTo(hasta) + 1
        if dias > 20:
            r = QMessageBox.question(
                self, "Rango largo",
                f"Son {dias} dias. Con muchas rutas, Chrome puede no "
                "alcanzar a leer todos los nombres.\n\n"
                "Se recomienda ir por quincenas. Continuar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return

        self.b_extraer.setEnabled(False)
        self.b_extraer.setText("Extrayendo...")
        self.pie.setText("Extrayendo. Puedes seguir usando la PC.")
        d = desde.toString("yyyy-MM-dd")
        h = hasta.toString("yyyy-MM-dd")
        self.escribir(f"Extrayendo del {d} al {h}...")
        self.ordenes.extraer.emit(d, h)

    def al_revisar_historial(self):
        self.b_historial.setEnabled(False)
        self.b_historial.setText("Buscando...")
        self.pie.setText("Buscando hasta donde llega el historial...")
        self.escribir("Revisando el historial disponible...")
        self.ordenes.historial.emit()

    def al_carpeta(self):
        destino = os.path.dirname(self.archivo) if self.archivo else _carpeta_base()
        QDesktopServices.openUrl(QUrl.fromLocalFile(destino))

    def al_terminar(self, etapa, datos):
        if etapa == "navegador":
            self.paso.setText(
                "Paso 2 de 2  ·  Elige el rango y presiona 'Extraer rutas'")
            self.b_extraer.setEnabled(True)
            self.b_extraer.setProperty("listo", True)
            self.b_historial.setEnabled(True)
            self.b_abrir.setText("Reabrir Chrome")
            self.b_abrir.setEnabled(True)
            self.pie.setText("Listo para extraer")

        elif etapa == "historial":
            viejo, sin_datos = datos
            self.b_historial.setEnabled(True)
            self.b_historial.setText("Hasta cuando hay datos en Mercado Libre")

            if not viejo:
                self.escribir("No se encontraron datos en ninguna fecha.")
                self.pie.setText("Sin datos disponibles")
                QMessageBox.warning(
                    self, "Sin datos",
                    "No se encontraron rutas en ninguna fecha reciente.\n\n"
                    "Revisa que la sesion siga activa.")
                return

            self.escribir(f"Hay datos desde el {viejo}")
            self.pie.setText(f"Historial disponible desde el {viejo}")

            texto = f"Se puede extraer desde el {viejo} en adelante."
            if sin_datos:
                texto += f"\n\nEl {sin_datos} ya no tiene datos."

            caja = QMessageBox(self)
            caja.setWindowTitle("Historial disponible")
            caja.setIcon(QMessageBox.Information)
            caja.setText(texto)
            caja.setInformativeText(
                "Mercado Libre no guarda el reporte de operacion "
                "indefinidamente.")
            usar = caja.addButton("Poner esa fecha en 'Desde'",
                                  QMessageBox.AcceptRole)
            caja.addButton("Cerrar", QMessageBox.RejectRole)
            caja.show()
            barra_titulo_oscura(caja)
            caja.exec()
            if caja.clickedButton() is usar:
                self.f_desde.setDate(QDate.fromString(viejo, "yyyy-MM-dd"))
                self.escribir(f"'Desde' puesto en {viejo}")

        elif etapa == "listo":
            r, archivo = datos
            self.archivo = archivo
            self.t_rutas.poner(r["filas"])
            self.t_sp.poner(r["sp"])
            self.t_rd.poner(r["rd"])
            self.t_as.poner(r.get("asistencia", 0))
            self.barra.hide()

            self.paso.setText("Listo  ·  El archivo ya esta guardado")
            self.b_extraer.setText("Extraer otra vez")
            self.b_extraer.setEnabled(True)
            self.b_carpeta.setEnabled(True)
            self.b_carpeta.setProperty("listo", True)
            self.pie.setText(f"{r['filas']} rutas guardadas")
            self._avisar(r, archivo)

    def al_fallar(self, mensaje):
        # SINDATOS: el rango elegido no tiene informacion, no es un error
        sin_datos = mensaje.startswith("SINDATOS:")
        if sin_datos:
            mensaje = mensaje[len("SINDATOS:"):]

        self.escribir(f"{'AVISO' if sin_datos else 'ERROR'}: "
                      f"{mensaje.splitlines()[0]}")
        self.barra.hide()
        self.b_abrir.setEnabled(True)
        self.b_extraer.setText("2 · Extraer rutas")
        self.b_historial.setEnabled(True)
        self.b_historial.setText("Hasta cuando hay datos en Mercado Libre")
        for b in (self.b_extraer, self.b_carpeta):
            if b.property("listo") is True:
                b.setEnabled(True)

        aviso = QMessageBox(self)
        aviso.setWindowTitle("Ese rango no tiene datos" if sin_datos
                             else "Algo salio mal")
        aviso.setIcon(QMessageBox.Information if sin_datos
                      else QMessageBox.Warning)
        aviso.setText(mensaje)
        if sin_datos:
            revisar = aviso.addButton("Buscar hasta cuando hay",
                                      QMessageBox.AcceptRole)
            aviso.addButton("Cerrar", QMessageBox.RejectRole)
        aviso.show()
        barra_titulo_oscura(aviso)
        aviso.exec()

        if sin_datos and aviso.clickedButton() is revisar:
            self.al_revisar_historial()
            return

        self.pie.setText("Elige otro rango" if sin_datos
                         else "Ocurrio un error, revisa el registro")

    def _avisar(self, r, archivo):
        detalle = [
            f"Del {r['desde']} al {r['hasta']}",
            f"{r['con_id']} con ID de usuario",
            f"{r['con_nombre']} de {r['esperan_nombre']} con nombre de ruta",
        ]
        n_as = r.get("asistencia", 0)
        if n_as:
            detalle.append(f"{n_as} rutas de Assistance (especiales)")
        faltan = r["esperan_nombre"] - r["con_nombre"]
        if faltan > 0:
            # Unas pocas son normales: rutas que MELI no llego a nombrar
            if faltan <= max(30, r["esperan_nombre"] // 40):
                detalle.append(f"{faltan} rutas no tienen nombre en el "
                               "portal (normal)")
            else:
                detalle.append(f"Faltaron {faltan} nombres: prueba un rango "
                               "mas corto")

        caja = QMessageBox(self)
        caja.setWindowTitle("Extraccion completa")
        caja.setIcon(QMessageBox.Information)
        caja.setText(f"Se extrajeron {r['filas']} rutas.\n\n"
                     + "\n".join(detalle))
        caja.setInformativeText(os.path.basename(archivo))
        abrir = caja.addButton("Abrir carpeta", QMessageBox.AcceptRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.show()
        barra_titulo_oscura(caja)
        caja.exec()
        if caja.clickedButton() is abrir:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(archivo)))

    def closeEvent(self, evento):
        self.trabajador.cancelado = True
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
        v.escribir("Extractor de rutas listo.")
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

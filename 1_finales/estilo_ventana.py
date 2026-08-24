# -*- coding: utf-8 -*-
"""
Piezas compartidas por las ventanas de los extractores.

Los cuatro programas dibujan la misma clase de ventana oscura, con las
mismas tarjetas y los mismos botones. Esto vive en un solo sitio para que
un arreglo de aspecto no haya que repetirlo cuatro veces.

Por ahora solo lo usa pnr_app.py. Las otras tres ventanas siguen con su
copia: funcionan, y cambiarlas sin motivo seria arriesgar lo que ya sirve.
Cuando haya que retocar el aspecto de alguna, ese es el momento de que
pase por aqui.
"""

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QFrame, QVBoxLayout, QSizePolicy,
    QDateEdit, QCalendarWidget,
)


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

def boton(texto, color):
    """El boton grande de accion."""
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


def boton_chico(texto):
    """El boton secundario, discreto."""
    b = QPushButton(texto)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedHeight(28)
    b.setStyleSheet(
        f"QPushButton {{ background: {PANEL}; color: {SUAVE};"
        f" border: 1px solid {BORDE}; border-radius: 6px;"
        f" font-family: {FUENTE}; font-size: 10px; padding: 0 8px; }}"
        f"QPushButton:hover {{ color: {TEXTO}; border-color: {AZUL}; }}")
    return b

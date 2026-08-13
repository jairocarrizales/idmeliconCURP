# -*- coding: utf-8 -*-
"""
Perfil persistente de Chrome, sin la ventana en blanco.

El problema que resuelve: si el programa se cierra a la fuerza, quedan
procesos de Chrome vivos agarrados al perfil y un lockfile. En el siguiente
arranque Chrome no puede abrirlo y muestra una ventana EN BLANCO, sin decir
nada.

Borrar el lockfile no basta: con procesos vivos lo vuelven a crear. Hay que
cerrarlos primero, y solo los que usan NUESTRO perfil (no el Chrome personal
del usuario).
"""

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# 'LOCK' (dentro de Default) es el que provoca el crash
# "DevToolsActivePort file doesn't exist" y suele olvidarse.
BLOQUEOS = ("lockfile", "LOCK", "SingletonLock", "SingletonCookie",
            "SingletonSocket", "DevToolsActivePort")


def log(msg):
    print(msg, flush=True)


def cerrar_chrome_huerfano():
    """Cierra los Chrome que quedaron usando nuestro perfil.

    Se identifican por la carpeta del perfil en su linea de comando, asi que
    el Chrome personal del usuario NO se toca.
    """
    if os.name != "nt":
        return 0

    # OJO: no uses la ruta completa en el -like. Sus backslashes rompen el
    # patron de PowerShell y el filtro devuelve 0 procesos aunque haya 8.
    marca = os.path.basename(PROFILE_DIR)
    proyecto = os.path.basename(os.path.dirname(PROFILE_DIR))
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{proyecto}*' -and "
        f"$_.CommandLine -like '*{marca}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue; $_.ProcessId }"
    )
    try:
        import subprocess

        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cerrados = [l for l in (res.stdout or "").split() if l.strip().isdigit()]
        if cerrados:
            log(f"Se cerraron {len(cerrados)} Chrome de una corrida anterior.")
            time.sleep(2)
        return len(cerrados)
    except Exception:
        return 0


def limpiar_lock():
    """Libera el perfil. Primero los procesos, luego los archivos."""
    if not os.path.isdir(PROFILE_DIR):
        return
    cerrar_chrome_huerfano()
    for nombre in BLOQUEOS:
        for carpeta in (PROFILE_DIR, os.path.join(PROFILE_DIR, "Default")):
            try:
                ruta = os.path.join(carpeta, nombre)
                if os.path.exists(ruta):
                    os.remove(ruta)
            except Exception:
                pass


def crear_driver(con_log_red=False):
    """Chrome con perfil persistente: la sesion sobrevive entre corridas."""
    limpiar_lock()

    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-MX")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    if con_log_red:
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        opts.add_experimental_option(
            "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False}
        )

    try:
        return webdriver.Chrome(options=opts)
    except Exception as e:
        # Traduce el error tecnico a algo accionable
        if "user data directory is already in use" in str(e).lower():
            log("ERROR: el perfil esta en uso por otra ventana de Chrome.")
            log("Cierra las que abrio este programa y reintenta.")
            log(f"Si sigue, borra la carpeta: {PROFILE_DIR}")
        raise


def preparar_pagina(driver, url_panel, dominio, selector_espera=None,
                    log=log):
    """Deja el navegador donde el fetch va a funcionar.

    El fetch corre DENTRO de la pagina, asi que solo funciona si el navegador
    esta en el dominio de la API. Si no, devuelve
    'TypeError: Failed to fetch' con status 0.
    """
    # 1) Si hay varias pestañas, pasar a la del panel
    try:
        pestanas = driver.window_handles
        if len(pestanas) > 1:
            for p in pestanas:
                driver.switch_to.window(p)
                if dominio in (driver.current_url or ""):
                    break
    except Exception:
        pass

    # 2) Si no estamos en el dominio, navegar
    if dominio not in (driver.current_url or ""):
        log("El navegador esta en otra pagina; volviendo al panel...")
        driver.get(url_panel)
        time.sleep(2)

    # 3) Esperar a que cargue de verdad, no un sleep fijo
    if selector_espera:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector_espera))
            )
        except Exception:
            pass          # puede que la sesion sirva aunque la tabla tarde

    return True


def explicar_error(e):
    """Convierte los errores de Selenium en algo que un humano entienda."""
    texto = str(e).split("Stacktrace:")[0].strip()
    bajo = texto.lower()

    if "user data directory is already in use" in bajo:
        return ("El perfil de Chrome esta en uso por otra ventana.\n\n"
                "Cierra las ventanas que abrio este programa y reintenta.")
    if "devtoolsactiveport" in bajo or "failed to start" in bajo:
        return ("Chrome no pudo arrancar.\n\n"
                "Suele pasar si quedo una copia abierta. Cierra Chrome; "
                "si sigue, borra la carpeta 'chrome_profile'.")
    if "no such window" in bajo or "target window already closed" in bajo:
        return ("Se cerro la ventana de Chrome.\n\n"
                "Vuelve a abrirla para continuar.")
    if "failed to fetch" in bajo:
        return ("El navegador bloqueo la consulta.\n\n"
                "Debe estar en la pagina del panel para poder pedir los datos.")
    if "401" in bajo or "403" in bajo:
        return ("La sesion caduco.\n\n"
                "Inicia sesion otra vez en la ventana de Chrome.")
    return texto[:400] if texto else type(e).__name__

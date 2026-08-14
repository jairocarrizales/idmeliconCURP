# -*- coding: utf-8 -*-
"""
Sonda de los dos botones de descarga que necesitamos automatizar:

  1. "Descargar CSV" de Reportes de operacion  (/carriers/reports)
     -> trae Id de ruta + Id del transportista + Nombre

  2. "Descargar" del detalle de prefactura     (/logistics/billing/invoices/<id>)
     -> trae el detalle con ID de ruta pero sin id de usuario

Con esos dos endpoints, el extractor final puede bajar todo solo y cruzarlo
por numero de ruta, sin depender de nombres.

Este script NO descarga datos: solo reporta las URLs y sus parametros.
"""

import os
import re
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

REPORTES = "https://envios.adminml.com/carriers/reports"
PREFACTURA = "https://envios.adminml.com/logistics/billing/invoices/"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    if os.path.isdir(PROFILE_DIR) and os.name == "nt":
        marca = os.path.basename(PROFILE_DIR)
        proyecto = os.path.basename(os.path.dirname(PROFILE_DIR))
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{proyecto}*' -and "
            f"$_.CommandLine -like '*{marca}*' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
            "-ErrorAction SilentlyContinue }"
        )
        try:
            import subprocess

            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1.5)
        except Exception:
            pass
    for n in ("lockfile", "LOCK", "SingletonLock", "DevToolsActivePort"):
        for c in (PROFILE_DIR, os.path.join(PROFILE_DIR, "Default")):
            try:
                p = os.path.join(c, n)
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-MX")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option(
        "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False}
    )
    return webdriver.Chrome(options=opts)


def peticiones(driver):
    """URLs XHR/Fetch/Document nuevas desde la ultima lectura.

    Se incluye Document porque una descarga puede navegar en vez de usar XHR.
    """
    vistas = {}
    try:
        entradas = driver.get_log("performance")
    except Exception:
        return []
    for e in entradas:
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        if m.get("method") != "Network.requestWillBeSent":
            continue
        p = m.get("params", {})
        req = p.get("request") or {}
        url = req.get("url", "")
        if not url.startswith("http"):
            continue
        if p.get("type") not in ("XHR", "Fetch", "Document", "Other"):
            continue
        basura = (".js", ".css", ".png", ".svg", ".woff", ".ico", "/metrics",
                  "melidata", "kaspersky", "google-analytics", "newrelic",
                  "mlstatic", "o11y", "datadog", "__modules", "__resolve")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = req.get("method", "GET")
    return list(vistas.items())


def clic_en_descargar(driver, tope=2):
    """Busca y presiona los enlaces de descarga de la pantalla.

    En la prefactura el 'Descargar' es un enlace azul dentro de cada seccion
    (junto a 'Regulares'), no un boton unico arriba. Por eso se buscan varios
    y se presionan hasta 'tope'.
    """
    patrones = ("descargar", "download", "exportar", "export")
    presionados = 0
    vistos = set()

    # El texto exacto primero: evita agarrar el contenedor entero
    xpath = (
        "//*[self::a or self::button or self::span]"
        "[normalize-space(translate(., 'DESCARGAR', 'descargar'))='descargar'"
        " or normalize-space(translate(., 'DESCARGAR CSV', 'descargar csv'))='descargar csv']"
    )
    candidatos = []
    try:
        candidatos = driver.find_elements(By.XPATH, xpath)
    except Exception:
        pass

    # Respaldo: cualquier elemento chico cuyo texto mencione descargar
    if not candidatos:
        for etiqueta in ("a", "button", "span"):
            try:
                for el in driver.find_elements(By.TAG_NAME, etiqueta):
                    texto = (el.text or "").strip().lower()
                    if texto and len(texto) <= 30 and any(p in texto for p in patrones):
                        candidatos.append(el)
            except Exception:
                continue

    for el in candidatos:
        try:
            if not el.is_displayed():
                continue
            marca = el.id
            if marca in vistos:
                continue
            vistos.add(marca)

            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el
            )
            time.sleep(0.4)
            driver.execute_script("arguments[0].click();", el)
            log(f"  Presionado: '{(el.text or '').strip()[:40]}'")
            presionados += 1
            time.sleep(3.5)
            if presionados >= tope:
                break
        except Exception:
            continue

    return presionados


def interesante(url):
    """Puntua que tanto huele a una descarga de datos."""
    u = url.lower()
    puntos = 0
    for palabra, valor in (
        ("download", 10), ("export", 10), ("csv", 8), ("xlsx", 8),
        ("report", 6), ("carrier", 4), ("detail", 4), ("invoice", 4),
        ("pre-invoice", 5), ("date", 3), ("from", 2), ("to", 2),
    ):
        if palabra in u:
            puntos += valor
    return puntos


def main():
    print("=" * 70)
    print("  SONDA - endpoints de descarga")
    print("=" * 70)
    print()
    print("  Busca las URLs detras de:")
    print("    1. 'Descargar CSV' de Reportes de operacion")
    print("    2. 'Descargar' del detalle de prefactura")
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Numero de prefactura (ENTER para 6442506): ").strip()
    if not id_pref:
        id_pref = "6442506"

    log("Abriendo Chrome...")
    driver = crear_driver()
    todo = []

    try:
        # ---------- 1) Reportes de operacion ----------
        driver.get(REPORTES)
        print("-" * 70)
        print("  PARTE 1: Reportes de operacion")
        print("  Inicia sesion, elige el rango de fechas que quieras,")
        print("  y espera a ver el resumen en pantalla.")
        print("-" * 70)
        input("\n>>> ENTER cuando lo veas... ")

        peticiones(driver)                     # vaciar
        log("Presionando 'Descargar CSV'...")
        n = clic_en_descargar(driver)
        if not n:
            log("  No se encontro el boton. Presionalo TU ahora.")
            input(">>> Presiona 'Descargar CSV' en Chrome y luego ENTER... ")
        time.sleep(4)

        nuevas = peticiones(driver)
        log(f"  Peticiones capturadas: {len(nuevas)}")
        todo += [("reportes", m, u) for u, m in nuevas]

        # ---------- 2) Detalle de prefactura ----------
        driver.get(PREFACTURA + id_pref)
        print()
        print("-" * 70)
        print("  PARTE 2: Detalle de la prefactura")
        print("  Espera a que cargue el detalle.")
        print("-" * 70)
        input("\n>>> ENTER cuando lo veas... ")

        peticiones(driver)                     # vaciar
        log("Presionando 'Descargar'...")
        n = clic_en_descargar(driver)
        if not n:
            log("  No se encontro el boton. Presionalo TU ahora.")
            input(">>> Presiona 'Descargar' en Chrome y luego ENTER... ")
        time.sleep(4)

        nuevas = peticiones(driver)
        log(f"  Peticiones capturadas: {len(nuevas)}")
        todo += [("prefactura", m, u) for u, m in nuevas]

        # ---------- Reporte ----------
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"descargas_{sello}.txt")

        candidatas = sorted(
            [t for t in todo if interesante(t[2]) > 0],
            key=lambda t: -interesante(t[2]),
        )

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("ENDPOINTS DE DESCARGA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}\n")
            f.write("NOTA: no se incluyen cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")

            if candidatas:
                f.write("CANDIDATAS (mejores primero)\n\n")
                for origen, metodo, url in candidatas:
                    f.write(f"[{origen}] {metodo}  (puntaje {interesante(url)})\n")
                    f.write(f"  {url}\n\n")
            else:
                f.write("Ninguna peticion parece una descarga.\n")
                f.write("Quiza el archivo se genera en el navegador.\n\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("TODAS LAS PETICIONES\n")
            f.write("=" * 70 + "\n")
            for origen, metodo, url in todo:
                f.write(f"[{origen}] {metodo}  {url}\n")

        print()
        print("=" * 70)
        if candidatas:
            print("  CANDIDATAS ENCONTRADAS:")
            print()
            for origen, metodo, url in candidatas[:6]:
                print(f"  [{origen}] {metodo}")
                print(f"    {url[:110]}")
                print()
        else:
            print("  No se detectaron endpoints de descarga.")
        print(f"  Reporte: {rep}")
        print("=" * 70)

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
    finally:
        input("\n>>> ENTER para cerrar... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

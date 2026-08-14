# -*- coding: utf-8 -*-
"""
Sonda del DETALLE de una ruta: de ahi sale el nombre "Ruta C1_AM1".

El listado (get-routes-list) trae 124 campos pero no el nombre de la ruta.
La pantalla de detalle si lo muestra, junto con la zona, sacas y tiempos:

    /logistics/monitoring-distribution/detail/<id>?site=MLM

Este script espia esa pantalla y vuelca TODOS los campos de la respuesta,
para ver cuales sirven para las columnas que le faltan al control:

    RUTA (C1_AM1), ZONA_DE_RUTA, CODIGO_POSTAL, Tipo_de_ruta, SACAS

Los textos van enmascarados; los numeros completos.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

DETALLE = "https://envios.adminml.com/logistics/monitoring-distribution/detail/{ruta}?site=MLM"

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
        if not url.startswith("http") or p.get("type") not in ("XHR", "Fetch"):
            continue
        basura = (".js", ".css", ".png", ".svg", ".woff", "/metrics",
                  "melidata", "kaspersky", "google-analytics", "newrelic",
                  "mlstatic", "o11y", "datadog", "__modules", "__resolve",
                  "tracks/internal", "kraken-menu")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = {"metodo": req.get("method", "GET"),
                       "cuerpo": (req.get("postData") or "")[:400]}
    return list(vistas.items())


def pedir(driver, url, metodo="GET", cuerpo=None):
    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include',
                headers: {'Accept': 'application/json, text/plain, */*'}};
    if (cuerpo) { op.headers['Content-Type'] = 'application/json'; op.body = cuerpo; }
    fetch(url, op)
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", ""):
        return t
    if t.replace(".", "").replace("-", "").replace(",", "").isdigit():
        return t
    # Los nombres de ruta son cortos y no son datos personales: se ven enteros
    if len(t) <= 12 and any(c.isdigit() for c in t) and "_" in t:
        return t
    return t[:6] + "*" * min(8, max(0, len(t) - 6))


def volcar(obj, ruta="", salida=None, nivel=0):
    if salida is None:
        salida = []
    if nivel > 8:
        return salida
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            if isinstance(v, (dict, list)):
                volcar(v, camino, salida, nivel + 1)
            else:
                salida.append((camino, v))
    elif isinstance(obj, list):
        if not obj:
            salida.append((f"{ruta}[]", "(vacia)"))
        for i, v in enumerate(obj[:1]):
            volcar(v, f"{ruta}[{i}]", salida, nivel + 1)
    return salida


def main():
    print("=" * 74)
    print("  SONDA - detalle de ruta (de aqui sale 'Ruta C1_AM1')")
    print("=" * 74)
    print()

    ruta = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not ruta:
        ruta = input(">>> ID de ruta (ENTER para 151255890): ").strip() or "151255890"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        url_pagina = DETALLE.format(ruta=ruta)
        driver.get(url_pagina)
        print("-" * 74)
        print("  Espera a ver el detalle de la ruta (con su nombre arriba).")
        print("-" * 74)
        input("\n>>> ENTER cuando lo veas... ")

        # Recargar con el log limpio, para capturar todo desde cero
        peticiones(driver)
        log("Recargando para capturar todas las peticiones...")
        driver.get(url_pagina)
        time.sleep(10)

        urls = peticiones(driver)
        log(f"Peticiones XHR/Fetch: {len(urls)}")

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"detalle_ruta_{sello}.txt")
        hallazgos = []

        print()
        print("=" * 74)
        print("  REVISANDO RESPUESTAS")
        print("=" * 74)

        for url, datos in urls:
            try:
                r = pedir(driver, url, datos["metodo"], datos["cuerpo"] or None)
            except Exception:
                continue
            if r.get("status") != 200:
                continue
            try:
                obj = json.loads(r.get("body") or "")
            except json.JSONDecodeError:
                continue

            campos = volcar(obj)
            corta = url.replace("https://envios.adminml.com", "")
            print(f"  {datos['metodo']:<5} {corta[:62]}  ({len(campos)} campos)")
            hallazgos.append((url, datos, obj, campos))
            time.sleep(0.2)

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("DETALLE DE RUTA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Ruta: {ruta}\n")
            f.write("Textos enmascarados; numeros y nombres de ruta completos.\n")
            f.write("=" * 74 + "\n\n")

            hallazgos.sort(key=lambda h: -len(h[3]))
            for url, datos, obj, campos in hallazgos:
                f.write(f"{datos['metodo']} {url}\n")
                if datos["cuerpo"]:
                    f.write(f"  cuerpo: {datos['cuerpo']}\n")
                f.write(f"  {len(campos)} campos\n")
                for camino, valor in campos:
                    f.write(f"    {camino} = {tapar(valor)}\n")
                f.write("\n")

        # Que columna del control llena cada campo
        print()
        print("=" * 74)
        print("  LO QUE LE FALTA AL CONTROL")
        print("=" * 74)
        buscar = {
            "RUTA (C1_AM1)": ("routename", "name", "code", "label", "title",
                              "description"),
            "ZONA_DE_RUTA": ("zone", "zona", "area", "sector", "polygon"),
            "CODIGO_POSTAL": ("zip", "postal", "cp"),
            "Tipo_de_ruta": ("routetype", "islocal", "isforeign", "local",
                             "foranea"),
            "SACAS": ("bag", "saca", "sack"),
        }
        with open(rep, "a", encoding="utf-8-sig") as f:
            f.write("\n" + "=" * 74 + "\nLO QUE LE FALTA AL CONTROL\n")
            f.write("=" * 74 + "\n")
            for columna, patrones in buscar.items():
                encontrados = []
                for url, datos, obj, campos in hallazgos:
                    for camino, valor in campos:
                        if any(p in camino.lower() for p in patrones):
                            if valor not in (None, "", 0, False):
                                encontrados.append((camino, valor))
                if encontrados:
                    print(f"\n  {columna}:")
                    f.write(f"\n{columna}:\n")
                    for c, v in encontrados[:6]:
                        linea = f"      {c} = {tapar(v)}"
                        print(linea)
                        f.write(linea + "\n")
                else:
                    print(f"\n  {columna}: NO ENCONTRADO")
                    f.write(f"\n{columna}: NO ENCONTRADO\n")

        print()
        print("=" * 74)
        print(f"  Reporte: {rep}")
        print("=" * 74)

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

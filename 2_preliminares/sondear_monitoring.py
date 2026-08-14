# -*- coding: utf-8 -*-
"""
Sonda: buscar el driver_id en la pantalla de detalle de ruta.

La URL viene del repo meli_extractores del usuario:
    /logistics/monitoring-distribution/detail/<ID_RUTA>

Esa pantalla muestra el conductor de la ruta. Si la API que la alimenta
devuelve su ID, tenemos el puente definitivo:

    CSV (ID de ruta) -> API de monitoring -> driver_id -> padron

A diferencia de adivinar URLs, aqui ESPIAMOS el trafico real de la pagina,
que es la tecnica que ya funciono con drivers y con billing.

Nombres enmascarados; ids completos.
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

BASE = "https://envios.adminml.com/logistics/monitoring-distribution"
DETALLE = BASE + "/detail/{ruta}"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

PALABRAS = ("driver", "conductor", "chofer", "employee", "carrier")


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


def urls_del_log(driver):
    """URLs XHR/Fetch vistas desde la ultima lectura."""
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
        url = (p.get("request") or {}).get("url", "")
        if not url.startswith("http") or p.get("type") not in ("XHR", "Fetch"):
            continue
        basura = (".js", ".css", ".png", ".svg", ".woff", "/metrics",
                  "melidata", "kaspersky", "google-analytics", "newrelic",
                  "mlstatic", "o11y", "datadog")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = True
    return list(vistas)


def pedir(driver, url):
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials:'include', headers:{'Accept':'application/json'}})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(60)
    return driver.execute_async_script(script, url)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", "") or t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:3] + "*" * min(10, max(0, len(t) - 3))


def buscar_driver(obj, ruta="", salida=None):
    """Todo campo que hable de conductor, con su valor. Baja a los anidados."""
    if salida is None:
        salida = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            es_driver = re.search(r"driver|conductor|chofer|employee", k, re.I)
            if es_driver and isinstance(v, dict):
                for k2, v2 in v.items():
                    if not isinstance(v2, (dict, list)):
                        salida[f"{camino}.{k2}"] = v2
                buscar_driver(v, camino, salida)
            elif es_driver and not isinstance(v, list):
                salida[camino] = v
            else:
                buscar_driver(v, camino, salida)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            buscar_driver(v, f"{ruta}[{i}]", salida)
    return salida


def rutas_del_csv():
    """IDs de ruta del CSV de la carpeta billing."""
    carpeta = os.path.join(BASE_DIR, "billing")
    if not os.path.isdir(carpeta):
        return []
    for nombre in os.listdir(carpeta):
        if not nombre.lower().endswith(".csv"):
            continue
        try:
            with open(os.path.join(carpeta, nombre), encoding="utf-8-sig",
                      errors="replace") as f:
                ids = []
                for linea in f:
                    partes = linea.split(";")
                    if len(partes) > 5 and partes[1].strip().isdigit():
                        ids.append(partes[1].strip())
                    if len(ids) >= 3:
                        return ids
        except Exception:
            continue
    return []


def main():
    print("=" * 70)
    print("  SONDA - driver_id en la pantalla de rutas")
    print("=" * 70)
    print()
    print("  Espia el trafico de /monitoring-distribution/detail/<ruta>")
    print("  para ver si alguna API devuelve el ID del conductor.")
    print()

    ruta = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not ruta:
        delcsv = rutas_del_csv()
        sugerida = delcsv[0] if delcsv else "147326006"
        if delcsv:
            print(f"  Rutas de tu CSV: {', '.join(delcsv)}")
        ruta = input(f">>> ID de ruta (ENTER para {sugerida}): ").strip() or sugerida

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(BASE)
        print("-" * 70)
        print("  1) Inicia sesion si hace falta.")
        print("  2) Espera a ver el panel de monitoreo.")
        print("-" * 70)
        input("\n>>> ENTER cuando lo veas... ")

        urls_del_log(driver)          # vaciar el log

        url_detalle = DETALLE.format(ruta=ruta)
        log(f"Abriendo la ruta {ruta}...")
        driver.get(url_detalle)
        time.sleep(9)                 # que cargue todo

        urls = urls_del_log(driver)
        log(f"Peticiones XHR/Fetch observadas: {len(urls)}")

        # Ver que muestra la pantalla, para confirmar que cargo la ruta
        try:
            cuerpo = driver.find_element(By.TAG_NAME, "body").text
            if "no encontrada" in cuerpo.lower() or len(cuerpo.strip()) < 60:
                log("AVISO: la pagina se ve vacia; quiza la ruta ya no existe.")
        except Exception:
            pass

        print()
        print("=" * 70)
        print("  REVISANDO RESPUESTAS")
        print("=" * 70)

        con_driver = []
        for url in urls:
            try:
                resp = pedir(driver, url)
            except Exception:
                continue
            if resp.get("status") != 200:
                continue
            cuerpo = resp.get("body") or ""
            try:
                obj = json.loads(cuerpo)
            except json.JSONDecodeError:
                continue

            campos = buscar_driver(obj)
            corta = url.replace("https://envios.adminml.com", "")
            if campos:
                # Solo interesa si ademas hay algo que parezca un id
                ids = {k: v for k, v in campos.items()
                       if re.search(r"id$|^id", k.split(".")[-1], re.I)}
                marca = "  <-- CONDUCTOR CON ID" if ids else "  (conductor sin id)"
                print(f"  {corta[:76]}{marca}")
                for k, v in list(campos.items())[:8]:
                    print(f"       {k} = {tapar(v)}")
                con_driver.append((url, campos, bool(ids), len(cuerpo)))
            else:
                print(f"  {corta[:76]}")
            time.sleep(0.2)

        # --- Reporte ---
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"sonda_monitoring_{sello}.txt")
        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("SONDA - DRIVER_ID EN LA PANTALLA DE RUTAS\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Ruta probada: {ruta}\n")
            f.write("Nombres enmascarados; ids completos.\n")
            f.write("=" * 70 + "\n\n")

            con_id = [c for c in con_driver if c[2]]
            if con_id:
                f.write("APIS CON CONDUCTOR + ID\n\n")
                for url, campos, _, tam in con_id:
                    f.write(f"URL   : {url}\n")
                    f.write(f"Tamano: {tam} caracteres\n")
                    for k, v in campos.items():
                        f.write(f"  {k} = {tapar(v)}\n")
                    f.write("\n")
            elif con_driver:
                f.write("Hay conductor, pero sin id a la vista:\n\n")
                for url, campos, _, tam in con_driver:
                    f.write(f"URL: {url}\n")
                    for k, v in campos.items():
                        f.write(f"  {k} = {tapar(v)}\n")
                    f.write("\n")
            else:
                f.write("Ninguna respuesta menciona al conductor.\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("TODAS LAS PETICIONES\n")
            f.write("=" * 70 + "\n")
            for u in urls:
                f.write(u + "\n")

        print()
        print("=" * 70)
        if any(c[2] for c in con_driver):
            print("  ENCONTRADO: hay una API con el ID del conductor")
        elif con_driver:
            print("  Hay conductor en las respuestas, pero sin ID.")
        else:
            print("  Ninguna respuesta menciona al conductor.")
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

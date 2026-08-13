# -*- coding: utf-8 -*-
"""
Sonda de la API de Monitoreo Last Mile.

El reporte de operacion (/api/carriers/reports) ya da fecha, ruta, driver,
placa, KM y entregados. Pero al control le faltan campos que solo se ven en
el monitoreo por estacion:

    ZONA_DE_RUTA, CODIGO_POSTAL, RUTA (A7_PM1), Tipo_de_servicio,
    Tipo_de_ruta, CEDIS_MELI, Vehiculo, SACAS

Este script espia el trafico de:
    /logistics/monitoring-distribution            (listado por estacion)
    /logistics/monitoring-distribution/detail/<id> (una ruta)

y reporta que APIs los alimentan. Aplica la tecnica que ya funciono con
drivers y con billing.

Los nombres van enmascarados; los ids completos.
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

LISTADO = "https://envios.adminml.com/logistics/monitoring-distribution"
DETALLE = LISTADO + "/detail/{ruta}?site=MLM"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Lo que le falta al control y hay que encontrar
BUSCADOS = (
    "zone", "zona", "postal", "zip", "cp",
    "route", "ruta", "name", "nombre",
    "service", "servicio", "type", "tipo",
    "station", "estacion", "center", "cedis",
    "vehicle", "vehiculo", "bag", "saca",
    "driver", "conductor",
)


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
    """URLs XHR/Fetch nuevas, con su metodo y cuerpo."""
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
                  "tracks/internal")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = {
            "metodo": req.get("method", "GET"),
            "cuerpo": (req.get("postData") or "")[:400],
        }
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
    driver.set_script_timeout(60)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", "") or t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:4] + "*" * min(8, max(0, len(t) - 4))


def campos_utiles(obj, ruta="", salida=None, nivel=0):
    """Claves que sirven para llenar el control, con su valor."""
    if salida is None:
        salida = {}
    if nivel > 6:
        return salida
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            if isinstance(v, (dict, list)):
                campos_utiles(v, camino, salida, nivel + 1)
            elif any(b in k.lower() for b in BUSCADOS) and v not in (None, ""):
                salida[camino] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            campos_utiles(v, f"{ruta}[{i}]", salida, nivel + 1)
    return salida


def main():
    print("=" * 70)
    print("  SONDA - Monitoreo Last Mile")
    print("=" * 70)
    print()
    print("  Busca las APIs que dan zona, codigo postal, nombre de ruta")
    print("  y tipo de servicio, que el reporte de operacion no trae.")
    print()

    ruta = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not ruta:
        ruta = input(">>> ID de ruta (ENTER para 151255890): ").strip() or "151255890"

    log("Abriendo Chrome...")
    driver = crear_driver()
    todo = []

    try:
        # ---------- 1) Listado por estacion ----------
        driver.get(LISTADO)
        print("-" * 70)
        print("  PARTE 1: listado del monitoreo")
        print("  Inicia sesion, ELIGE UNA ESTACION y aplica.")
        print("  Espera a ver la lista de rutas.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas las rutas... ")

        nuevas = peticiones(driver)
        log(f"  Peticiones del listado: {len(nuevas)}")
        todo += [("listado", u, d) for u, d in nuevas]

        # ---------- 2) Detalle de una ruta ----------
        peticiones(driver)                      # vaciar
        url_det = DETALLE.format(ruta=ruta)
        log(f"Abriendo el detalle de la ruta {ruta}...")
        driver.get(url_det)
        time.sleep(9)

        nuevas = peticiones(driver)
        log(f"  Peticiones del detalle: {len(nuevas)}")
        todo += [("detalle", u, d) for u, d in nuevas]

        # ---------- 3) Revisar respuestas ----------
        print()
        print("=" * 70)
        print("  REVISANDO RESPUESTAS")
        print("=" * 70)

        hallazgos = []
        for origen, url, datos in todo:
            try:
                r = pedir(driver, url, datos["metodo"], datos["cuerpo"] or None)
            except Exception:
                continue
            if r.get("status") != 200:
                continue
            cuerpo = r.get("body") or ""
            try:
                obj = json.loads(cuerpo)
            except json.JSONDecodeError:
                continue

            campos = campos_utiles(obj)
            corta = url.replace("https://envios.adminml.com", "")
            marca = f"  <-- {len(campos)} campos utiles" if campos else ""
            print(f"  [{origen}] {corta[:66]}{marca}")
            if campos:
                for k, v in list(campos.items())[:10]:
                    print(f"       {k} = {tapar(v)}")
                hallazgos.append((origen, url, datos, campos, len(cuerpo)))
            time.sleep(0.2)

        # ---------- 4) Reporte ----------
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"sonda_rutas_{sello}.txt")
        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("SONDA - MONITOREO LAST MILE\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Ruta de prueba: {ruta}\n")
            f.write("Nombres enmascarados; ids completos. Sin cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")

            if hallazgos:
                hallazgos.sort(key=lambda h: -len(h[3]))
                f.write("APIS CON CAMPOS UTILES (mas ricas primero)\n\n")
                for origen, url, datos, campos, tam in hallazgos:
                    f.write(f"[{origen}] {datos['metodo']} {url}\n")
                    if datos["cuerpo"]:
                        f.write(f"  cuerpo: {datos['cuerpo']}\n")
                    f.write(f"  tamano: {tam} caracteres, {len(campos)} campos\n")
                    for k, v in campos.items():
                        f.write(f"    {k} = {tapar(v)}\n")
                    f.write("\n")
            else:
                f.write("Ninguna respuesta trae campos utiles.\n")

            f.write("\n" + "=" * 70 + "\nTODAS LAS PETICIONES\n" + "=" * 70 + "\n")
            for origen, url, datos in todo:
                f.write(f"[{origen}] {datos['metodo']}  {url}\n")

        print()
        print("=" * 70)
        if hallazgos:
            print(f"  {len(hallazgos)} APIs con campos utiles.")
        else:
            print("  No se encontraron campos utiles en las respuestas.")
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

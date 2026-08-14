# -*- coding: utf-8 -*-
"""
Busca donde vive el nombre de la ruta ("Ruta C1_AM1").

La sonda anterior solo capturo 5 peticiones secundarias (distancia, notas,
trazas). La principal se cargo antes de empezar a mirar. Aqui se ataca de
tres formas a la vez:

  1. Leer el nombre del DOM y buscar ese texto en cada respuesta JSON.
     Asi no dependemos de adivinar el nombre del campo.
  2. Probar las rutas hermanas de /logistics/api/monitoring-route/*, que ya
     conocemos por las secundarias.
  3. Mirar el plannedRouteId (502632738001), que aparecio en la traza y no
     estaba en el listado: el nombre suele ser de la ruta planificada.

Los textos van enmascarados, salvo nombres de ruta y zona.
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

DETALLE = "https://envios.adminml.com/logistics/monitoring-distribution/detail/{ruta}?site=MLM"
BASE = "https://envios.adminml.com/logistics/api"

# Rutas candidatas, siguiendo el patron de las que ya conocemos
CANDIDATAS = [
    "/monitoring-route/detail?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/get-route?routeId={id}&siteId=MLM",
    "/monitoring-route/route?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/header?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/summary?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/resume?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/info?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring-route/stops?routeId={id}&routeType=last_mile&siteId=MLM",
    "/monitoring/route/{id}?siteId=MLM",
    "/monitoring/get-route-detail?routeId={id}&siteId=MLM",
]

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
                  "tracks/internal", "kraken-menu", "xtools-frm")
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
    driver.set_script_timeout(60)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def nombre_del_dom(driver):
    """Lee el nombre de la ruta de la pantalla (ej. 'Ruta C1_AM1')."""
    for sel in ("h1", "h2", "h3", "[class*='title']", "[class*='name']"):
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                t = (el.text or "").strip()
                # "Ruta C1_AM1": empieza con Ruta y trae guion bajo
                if t.lower().startswith("ruta ") and "_" in t and len(t) < 40:
                    return t.split(" ", 1)[1].strip()
                if re.fullmatch(r"[A-Z0-9]{1,4}_[A-Z0-9_]{2,12}", t):
                    return t
        except Exception:
            continue
    return ""


def donde_esta(obj, buscado, ruta="", hallados=None):
    """Busca un texto en el JSON y devuelve el camino donde aparece."""
    if hallados is None:
        hallados = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            if isinstance(v, (dict, list)):
                donde_esta(v, buscado, camino, hallados)
            elif isinstance(v, str) and buscado.lower() in v.lower():
                hallados.append((camino, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:30]):
            donde_esta(v, buscado, f"{ruta}[{i}]", hallados)
    return hallados


def main():
    print("=" * 74)
    print("  BUSCAR EL NOMBRE DE LA RUTA")
    print("=" * 74)
    print()

    ruta = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not ruta:
        ruta = input(">>> ID de ruta (ENTER para 151255890): ").strip() or "151255890"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        # Empezar a capturar ANTES de cargar: la principal se pide al inicio
        driver.get("https://envios.adminml.com/logistics/monitoring-distribution")
        print("-" * 74)
        print("  Inicia sesion si hace falta y presiona ENTER.")
        print("-" * 74)
        input("\n>>> ENTER... ")

        peticiones(driver)                     # vaciar el log
        log(f"Cargando el detalle de la ruta {ruta}...")
        driver.get(DETALLE.format(ruta=ruta))
        time.sleep(11)

        urls = peticiones(driver)
        log(f"Peticiones capturadas: {len(urls)}")

        # El nombre, leido de la pantalla
        nombre = nombre_del_dom(driver)
        if nombre:
            log(f"Nombre en pantalla: '{nombre}'")
        else:
            nombre = input(">>> No lo pude leer. Escribelo (ej. C1_AM1): ").strip()

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"nombre_ruta_{sello}.txt")
        encontrado = []

        print()
        print("=" * 74)
        print(f"  BUSCANDO '{nombre}' EN LAS RESPUESTAS")
        print("=" * 74)

        # 1) En lo que la pagina pidio
        for url, datos in urls:
            try:
                r = pedir(driver, url, datos["metodo"], datos["cuerpo"] or None)
            except Exception:
                continue
            if r.get("status") != 200:
                continue
            cuerpo = r.get("body") or ""
            corta = url.replace("https://envios.adminml.com", "")

            if nombre and nombre.lower() in cuerpo.lower():
                try:
                    obj = json.loads(cuerpo)
                    caminos = donde_esta(obj, nombre)
                except json.JSONDecodeError:
                    caminos = [("(no es JSON)", "")]
                print(f"  ENCONTRADO en {corta[:56]}")
                for c, v in caminos[:4]:
                    print(f"       {c} = {v}")
                encontrado.append((url, datos, caminos))
            else:
                print(f"  no esta en {corta[:60]}")
            time.sleep(0.2)

        # 2) Rutas candidatas por si la principal no se capturo
        if not encontrado:
            print()
            print("=" * 74)
            print("  PROBANDO RUTAS CANDIDATAS")
            print("=" * 74)
            for plantilla in CANDIDATAS:
                url = BASE + plantilla.format(id=ruta)
                try:
                    r = pedir(driver, url)
                except Exception:
                    continue
                estado = r.get("status")
                cuerpo = r.get("body") or ""
                corta = plantilla.split("?")[0]
                if estado != 200:
                    print(f"  {corta:<44} {estado}")
                    continue
                tiene = nombre and nombre.lower() in cuerpo.lower()
                marca = "  <-- TIENE EL NOMBRE" if tiene else ""
                print(f"  {corta:<44} 200 ({len(cuerpo)} car.){marca}")
                if tiene:
                    try:
                        obj = json.loads(cuerpo)
                        caminos = donde_esta(obj, nombre)
                        for c, v in caminos[:4]:
                            print(f"       {c} = {v}")
                        encontrado.append((url, {"metodo": "GET", "cuerpo": ""},
                                           caminos))
                    except json.JSONDecodeError:
                        pass
                time.sleep(0.25)

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("DONDE ESTA EL NOMBRE DE LA RUTA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Ruta: {ruta}   Nombre en pantalla: {nombre}\n")
            f.write("=" * 74 + "\n\n")
            if encontrado:
                for url, datos, caminos in encontrado:
                    f.write(f"{datos['metodo']} {url}\n")
                    if datos["cuerpo"]:
                        f.write(f"  cuerpo: {datos['cuerpo']}\n")
                    for c, v in caminos:
                        f.write(f"  {c} = {v}\n")
                    f.write("\n")
            else:
                f.write("No se encontro el nombre en ninguna respuesta.\n")
                f.write("Quiza la pagina lo arma desde el HTML del servidor.\n\n")
            f.write("\nPETICIONES OBSERVADAS\n" + "=" * 74 + "\n")
            for url, datos in urls:
                f.write(f"{datos['metodo']}  {url}\n")

        print()
        print("=" * 74)
        if encontrado:
            print(f"  ENCONTRADO en {len(encontrado)} respuesta(s)")
        else:
            print("  No aparece en ninguna respuesta JSON.")
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

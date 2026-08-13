# -*- coding: utf-8 -*-
"""
Sonda: buscar el driver_id a partir del ID de ruta del CSV.

La API de billing no trae driver_id (0 de 416 items). Pero el CSV si trae
"ID de ruta" (ej. 147326006), y una ruta tiene conductor asignado. Si existe
una API de rutas que devuelva su driver, tenemos el puente:

    CSV (ID de ruta)  ->  API de rutas  ->  driver_id

Este script prueba rutas candidatas con UN solo ID y reporta cual responde.
Los nombres se enmascaran; los ids se muestran completos.
"""

import os
import re
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

WEB = "https://envios.adminml.com/logistics/provider-management/drivers"

# Bases donde puede vivir una API de rutas
BASES = [
    "https://envios.adminml.com/logistics/routes/api",
    "https://envios.adminml.com/logistics/api",
    "https://envios.adminml.com/logistics/provider-management/api",
    "https://envios.adminml.com/logistics/billing/api",
    "https://envios.adminml.com/api",
]

# Formas tipicas de pedir el detalle de una ruta
PLANTILLAS = [
    "/routes/{id}",
    "/route/{id}",
    "/routes/{id}/detail",
    "/routes/detail/{id}",
    "/shipping-routes/{id}",
    "/routes/{id}/driver",
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
    return webdriver.Chrome(options=opts)


def pedir(driver, url):
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials:'include', headers:{'Accept':'application/json'}})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(45)
    return driver.execute_async_script(script, url)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", "") or t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:3] + "*" * min(10, max(0, len(t) - 3))


def campos_driver(obj, ruta="", salida=None):
    """Busca cualquier clave que hable de conductor, a cualquier nivel."""
    if salida is None:
        salida = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            del_conductor = re.search(r"driver|conductor|chofer|employee", k, re.I)

            if del_conductor and isinstance(v, dict):
                # El nodo ES el conductor: volcar sus campos simples, que es
                # donde viene el id que nos interesa.
                for k2, v2 in v.items():
                    if not isinstance(v2, (dict, list)):
                        salida[f"{camino}.{k2}"] = v2
                campos_driver(v, camino, salida)
            elif del_conductor and not isinstance(v, list):
                salida[camino] = v
            else:
                campos_driver(v, camino, salida)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            campos_driver(v, f"{ruta}[{i}]", salida)
    return salida


def leer_rutas_del_csv():
    """Saca IDs de ruta del CSV de la carpeta billing, si esta."""
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
    print("  SONDA - del ID de ruta al conductor")
    print("=" * 70)
    print()
    print("  La API de billing no trae driver_id, pero el CSV si trae el")
    print("  ID de ruta. Aqui buscamos una API de rutas que de el conductor.")
    print()

    id_ruta = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_ruta:
        del_csv = leer_rutas_del_csv()
        sugerido = del_csv[0] if del_csv else "147326006"
        if del_csv:
            print(f"  IDs de ruta tomados del CSV: {', '.join(del_csv)}")
        id_ruta = input(f">>> ID de ruta (ENTER para {sugerido}): ").strip() or sugerido

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(WEB)
        print("-" * 70)
        print("  Inicia sesion si hace falta y espera a ver el panel.")
        print("-" * 70)
        input("\n>>> ENTER cuando estes listo... ")

        if "adminml.com" not in (driver.current_url or ""):
            driver.get(WEB)
            time.sleep(4)

        print()
        print("=" * 70)
        print(f"  PROBANDO RUTAS PARA EL ID {id_ruta}")
        print("=" * 70)

        aciertos = []
        for base in BASES:
            for plantilla in PLANTILLAS:
                url = base + plantilla.format(id=id_ruta)
                try:
                    resp = pedir(driver, url)
                except Exception:
                    continue
                estado = resp.get("status")
                if estado != 200:
                    continue
                cuerpo = resp.get("body") or ""
                try:
                    obj = json.loads(cuerpo)
                except json.JSONDecodeError:
                    continue

                campos = campos_driver(obj)
                marca = "  <-- TIENE CONDUCTOR" if campos else ""
                corta = url.replace("https://envios.adminml.com", "")
                print(f"  {corta[:78]} 200{marca}")
                aciertos.append((url, obj, campos, len(cuerpo)))
                if campos:
                    for k, v in list(campos.items())[:6]:
                        print(f"       {k} = {tapar(v)}")
                time.sleep(0.25)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_rep = os.path.join(BASE_DIR, f"sonda_ruta_{sello}.txt")
        with open(ruta_rep, "w", encoding="utf-8-sig") as f:
            f.write("SONDA - DEL ID DE RUTA AL CONDUCTOR\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"ID de ruta probado: {id_ruta}\n")
            f.write("Nombres enmascarados; ids completos.\n")
            f.write("=" * 70 + "\n\n")

            con_driver = [a for a in aciertos if a[2]]
            if con_driver:
                f.write("APIS QUE DAN EL CONDUCTOR\n\n")
                for url, obj, campos, tam in con_driver:
                    f.write(f"URL   : {url}\n")
                    f.write(f"Tamano: {tam} caracteres\n")
                    for k, v in campos.items():
                        f.write(f"  {k} = {tapar(v)}\n")
                    f.write(f"  claves de la raiz: {', '.join(list(obj.keys())[:24])}\n\n")
            elif aciertos:
                f.write("Rutas que responden, pero sin conductor:\n")
                for url, obj, _, tam in aciertos:
                    claves = list(obj.keys())[:20] if isinstance(obj, dict) else []
                    f.write(f"  {url}\n    ({tam} car.) claves: {', '.join(claves)}\n")
            else:
                f.write("Ninguna ruta candidata respondio 200 con JSON.\n")
                f.write("Habria que abrir una ruta en el panel y espiar el trafico.\n")

        print()
        print("=" * 70)
        if any(a[2] for a in aciertos):
            print("  ENCONTRADO: hay una API de ruta que da el conductor")
        elif aciertos:
            print(f"  {len(aciertos)} rutas responden, pero ninguna trae conductor.")
        else:
            print("  Ninguna ruta candidata respondio.")
        print(f"  Reporte: {ruta_rep}")
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

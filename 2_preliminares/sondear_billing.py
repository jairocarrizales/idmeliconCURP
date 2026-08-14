# -*- coding: utf-8 -*-
"""
Sonda de la API de detalle de prefacturas.

DescubrirBilling encontro este endpoint:
  /logistics/billing/api/pre-invoices/complementary/details/<id>

Este script lo consulta directo y muestra su estructura: que claves trae,
si incluye conductores y si esos conductores tienen id. Tambien prueba
rutas hermanas por si el detalle fino vive en otra.

Los valores se enmascaran al imprimir. No guarda datos personales.
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

BASE_WEB = "https://envios.adminml.com/logistics/billing/invoices/"
BASE_API = "https://envios.adminml.com/logistics/billing/api"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Rutas a probar. La primera es la que ya vimos en el trafico real.
RUTAS = [
    "/pre-invoices/complementary/details/{id}",
    "/pre-invoices/details/{id}",
    "/pre-invoices/{id}",
    "/pre-invoices/{id}/details",
    "/pre-invoices/{id}/items",
    "/pre-invoices/{id}/routes",
    "/pre-invoices/regular/details/{id}",
    "/pre-invoices/{id}/download",
    "/pre-invoices/{id}/export",
]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def cerrar_chrome_huerfano():
    if os.name != "nt":
        return
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


def crear_driver():
    if os.path.isdir(PROFILE_DIR):
        cerrar_chrome_huerfano()
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
    driver.set_script_timeout(60)
    return driver.execute_async_script(script, url)


def esqueleto(obj, nivel=0, tope=3):
    """Describe la forma del JSON sin volcar los datos."""
    sangria = "  " * (nivel + 1)
    lineas = []

    if isinstance(obj, dict):
        for k, v in list(obj.items())[:22]:
            if isinstance(v, dict):
                lineas.append(f"{sangria}{k}: {{...}}")
                if nivel < tope:
                    lineas += esqueleto(v, nivel + 1, tope)
            elif isinstance(v, list):
                lineas.append(f"{sangria}{k}: [{len(v)} elementos]")
                if v and nivel < tope:
                    lineas.append(f"{sangria}  el primero:")
                    lineas += esqueleto(v[0], nivel + 2, tope)
            else:
                texto = str(v)
                # Enmascarar: puede haber nombres y datos personales
                if len(texto) > 3 and not texto.replace(".", "").isdigit():
                    texto = texto[:3] + "*" * min(9, len(texto) - 3)
                lineas.append(f"{sangria}{k} = {texto}")
    elif isinstance(obj, list):
        lineas.append(f"{sangria}[{len(obj)} elementos]")
        if obj and nivel < tope:
            lineas += esqueleto(obj[0], nivel + 1, tope)
    return lineas


def claves_de(obj, encontradas=None):
    """Todas las claves que aparecen en el JSON, a cualquier profundidad."""
    if encontradas is None:
        encontradas = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            encontradas.add(k)
            claves_de(v, encontradas)
    elif isinstance(obj, list):
        for v in obj[:5]:
            claves_de(v, encontradas)
    return encontradas


def main():
    print("=" * 70)
    print("  SONDA - API de detalle de prefacturas")
    print("=" * 70)
    print()
    print("  Consulta el endpoint del detalle y muestra su estructura,")
    print("  para ver si trae el ID del conductor.")
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Numero de prefactura (ENTER para 6442506): ").strip()
    if not id_pref:
        id_pref = "6442506"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(BASE_WEB + id_pref)
        print("-" * 70)
        print("  Inicia sesion si hace falta y espera a ver la prefactura.")
        print("-" * 70)
        input("\n>>> ENTER cuando la veas... ")

        if "billing" not in (driver.current_url or ""):
            driver.get(BASE_WEB + id_pref)
            time.sleep(4)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_rep = os.path.join(BASE_DIR, f"sonda_billing_{sello}.txt")
        reporte = []

        print()
        print("=" * 70)
        print("  PROBANDO RUTAS")
        print("=" * 70)

        exitosas = []
        for plantilla in RUTAS:
            url = BASE_API + plantilla.format(id=id_pref)
            try:
                resp = pedir(driver, url)
            except Exception as e:
                print(f"  {plantilla:<44} error")
                continue

            estado = resp.get("status")
            cuerpo = resp.get("body") or ""

            if estado != 200:
                print(f"  {plantilla:<44} {estado}")
                continue

            try:
                obj = json.loads(cuerpo)
            except json.JSONDecodeError:
                tipo = "CSV" if ";" in cuerpo[:200] else "texto"
                print(f"  {plantilla:<44} 200 ({tipo}, {len(cuerpo)} car.)")
                exitosas.append((plantilla, url, cuerpo, None))
                continue

            claves = claves_de(obj)
            # Claves que delatan al conductor y su id
            del_conductor = sorted(
                k for k in claves
                if re.search(r"driver|conductor|carrier|employee", k, re.I)
            )
            hay_id = sorted(
                k for k in claves
                if re.search(r"^id$|.*Id$|_id$", k) and len(k) < 24
            )

            marca = "  <-- CONDUCTOR" if del_conductor else ""
            print(f"  {plantilla:<44} 200 JSON ({len(cuerpo)} car.){marca}")
            exitosas.append((plantilla, url, cuerpo, obj))

            if del_conductor:
                print(f"       claves de conductor: {', '.join(del_conductor[:6])}")
            if hay_id:
                print(f"       claves de id       : {', '.join(hay_id[:8])}")
            time.sleep(0.3)

        # --- Reporte detallado ---
        with open(ruta_rep, "w", encoding="utf-8-sig") as f:
            f.write("SONDA - API DE DETALLE DE PREFACTURAS\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}\n")
            f.write("Los valores van enmascarados.\n")
            f.write("=" * 70 + "\n\n")

            for plantilla, url, cuerpo, obj in exitosas:
                f.write(f"--- {plantilla} ---\n")
                f.write(f"URL: {url}\n")
                f.write(f"Tamano: {len(cuerpo)} caracteres\n")
                if obj is None:
                    f.write("No es JSON. Primeras lineas:\n")
                    for l in cuerpo.splitlines()[:6]:
                        f.write(f"  {l[:160]}\n")
                else:
                    f.write("Estructura:\n")
                    f.write("\n".join(esqueleto(obj)) + "\n")
                    f.write("\nTodas las claves:\n")
                    f.write("  " + ", ".join(sorted(claves_de(obj))[:60]) + "\n")
                f.write("\n")

        print()
        print("=" * 70)
        print(f"  Reporte con la estructura: {ruta_rep}")
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

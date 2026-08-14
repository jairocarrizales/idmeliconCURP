# -*- coding: utf-8 -*-
"""
Encuentra el endpoint que sirve el CSV de la prefactura.

Antes se reconstruia el archivo desde el JSON, lo que cambiaba el formato.
Ahora se quiere descargar el CSV TAL CUAL y solo insertarle una columna,
asi que hace falta saber que URL lo entrega.

Prueba varias rutas candidatas y, si ninguna sirve, espia el trafico al
presionar 'Descargar' -> CSV.
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

WEB = "https://envios.adminml.com/logistics/billing/invoices/"
BASE = "https://envios.adminml.com/logistics/billing/api/pre-invoices"

CANDIDATAS = [
    "/{id}/reports/details/csv",
    "/{id}/reports/details?format=csv",
    "/{id}/reports/csv",
    "/{id}/csv",
    "/{id}/export",
    "/{id}/export/csv",
    "/{id}/download",
    "/{id}/reports/download",
]

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(
    os.path.dirname(BASE_DIR), "1_finales", "chrome_profile")
if not os.path.isdir(PROFILE_DIR):
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


def pedir(driver, url, metodo="GET", cuerpo=None):
    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include'};
    if (cuerpo) { op.headers = {'Content-Type': 'application/json'}; op.body = cuerpo; }
    fetch(url, op)
      .then(r => r.text().then(t => done({status: r.status,
                                          tipo: r.headers.get('content-type'),
                                          body: t})))
      .catch(e => done({status: 0, tipo: '', body: String(e)}));
    """
    driver.set_script_timeout(120)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def es_el_csv(texto):
    """El CSV de la prefactura empieza con Producto;Pais;Transportadora."""
    if not texto or len(texto) < 200:
        return False
    primera = texto.splitlines()[0].lower()
    return ";" in primera and ("producto" in primera or "descripcion" in primera
                               or "descripción" in primera)


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
        if not url.startswith("http"):
            continue
        if p.get("type") not in ("XHR", "Fetch", "Document", "Other"):
            continue
        if any(b in url.lower() for b in (".js", ".css", ".png", "melidata",
                                          "kaspersky", "tracks/internal",
                                          "kraken", "__modules")):
            continue
        vistas[url] = {"metodo": req.get("method", "GET"),
                       "cuerpo": (req.get("postData") or "")[:300]}
    return list(vistas.items())


def main():
    print("=" * 74)
    print("  BUSCAR EL CSV DE LA PREFACTURA")
    print("=" * 74)
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Prefactura (ENTER para 6442506): ").strip() or "6442506"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(WEB + id_pref)
        print("-" * 74)
        print("  Espera a ver el detalle de la prefactura y presiona ENTER.")
        print("-" * 74)
        input("\n>>> ENTER... ")

        print()
        print("=" * 74)
        print("  PROBANDO RUTAS CANDIDATAS")
        print("=" * 74)

        encontrada = None
        for plantilla in CANDIDATAS:
            url = BASE + plantilla.format(id=id_pref)
            try:
                r = pedir(driver, url)
            except Exception:
                continue
            estado = r.get("status")
            cuerpo = r.get("body") or ""
            corta = plantilla.split("?")[0]
            if estado != 200:
                print(f"  {corta:<34} {estado}")
                continue
            if es_el_csv(cuerpo):
                print(f"  {corta:<34} 200  <-- ES EL CSV ({len(cuerpo)} car.)")
                print(f"       {cuerpo.splitlines()[0][:88]}")
                encontrada = (url, "GET", None)
                break
            print(f"  {corta:<34} 200 ({r.get('tipo')}, {len(cuerpo)} car.)")
            time.sleep(0.25)

        # El POST que ya conocemos, pidiendo CSV en el cuerpo
        if not encontrada:
            print()
            print("  Probando el POST con formato csv en el cuerpo...")
            for cuerpo_post in ('{"tolls_items":null,"format":"csv"}',
                                '{"format":"csv"}',
                                '{"tolls_items":null,"type":"csv"}'):
                url = f"{BASE}/{id_pref}/reports/details"
                try:
                    r = pedir(driver, url, "POST", cuerpo_post)
                except Exception:
                    continue
                cuerpo = r.get("body") or ""
                if r.get("status") == 200 and es_el_csv(cuerpo):
                    print(f"    {cuerpo_post}  <-- ES EL CSV")
                    encontrada = (url, "POST", cuerpo_post)
                    break
                print(f"    {cuerpo_post}: {r.get('status')} "
                      f"({r.get('tipo')}, {len(cuerpo)} car.)")

        # Si nada funciono, espiar el boton
        if not encontrada:
            print()
            print("=" * 74)
            print("  Ninguna ruta sirvio. Vamos a espiar el boton.")
            print("=" * 74)
            peticiones(driver)
            print("  EN CHROME: presiona 'Descargar' y elige CSV.")
            input("\n>>> ENTER cuando lo hayas descargado... ")
            for url, datos in peticiones(driver):
                print(f"  {datos['metodo']:<5} {url[:88]}")
                if datos["cuerpo"]:
                    print(f"        cuerpo: {datos['cuerpo']}")

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = os.path.join(os.path.dirname(BASE_DIR), "diagnosticos")
        os.makedirs(carpeta, exist_ok=True)
        rep = os.path.join(carpeta, f"csv_prefactura_{sello}.txt")
        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("ENDPOINT DEL CSV DE LA PREFACTURA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}\n")
            f.write("=" * 74 + "\n\n")
            if encontrada:
                f.write(f"ENCONTRADO\n  {encontrada[1]} {encontrada[0]}\n")
                if encontrada[2]:
                    f.write(f"  cuerpo: {encontrada[2]}\n")
            else:
                f.write("No se encontro. Ver las peticiones de abajo.\n\n")
                for url, datos in peticiones(driver):
                    f.write(f"{datos['metodo']}  {url}\n")
                    if datos["cuerpo"]:
                        f.write(f"    cuerpo: {datos['cuerpo']}\n")

        print()
        print("=" * 74)
        if encontrada:
            print(f"  CSV: {encontrada[1]} {encontrada[0]}")
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

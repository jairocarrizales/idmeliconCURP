# -*- coding: utf-8 -*-
"""
Sonda del cuerpo del POST de descarga de prefactura.

SondearDescargas encontro el endpoint:
    POST /logistics/billing/api/pre-invoices/<id>/reports/details

Pero un POST lleva un cuerpo, y ahi va la eleccion de formato (CSV o PDF)
que el usuario hace a mano en el dialogo. Sin ese cuerpo no se puede
reproducir la descarga.

Este script captura el postData exacto de esa peticion. Tambien prueba el
GET del reporte de operacion para confirmar que responde.
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

PREFACTURA = "https://envios.adminml.com/logistics/billing/invoices/"
API_REPORTE = "https://envios.adminml.com/api/carriers/reports"

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


def posts_con_cuerpo(driver):
    """Devuelve los POST vistos, con su cuerpo y cabeceras relevantes.

    Se ignoran cookie y authorization: no hacen falta y no deben guardarse.
    """
    salida = []
    try:
        entradas = driver.get_log("performance")
    except Exception:
        return salida

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
        if req.get("method") != "POST" or not url.startswith("http"):
            continue
        if any(b in url.lower() for b in ("melidata", "tracks/internal",
                                          "kaspersky", "datadog", "o11y")):
            continue

        cabeceras = {
            k: v for k, v in (req.get("headers") or {}).items()
            if k.lower() in ("content-type", "accept", "x-requested-with")
        }
        salida.append({
            "url": url,
            "cuerpo": req.get("postData") or "",
            "cabeceras": cabeceras,
        })
    return salida


def pedir(driver, url, metodo="GET", cuerpo=None, tipo="application/json"):
    """Llama la API desde la pagina, reusando su sesion."""
    script = """
    const [url, metodo, cuerpo, tipo] = arguments;
    const done = arguments[arguments.length - 1];
    const opciones = {method: metodo, credentials: 'include',
                      headers: {'Accept': 'application/json, text/csv, */*'}};
    if (cuerpo !== null) {
      opciones.headers['Content-Type'] = tipo;
      opciones.body = cuerpo;
    }
    fetch(url, opciones)
      .then(r => r.text().then(t => done({status: r.status, body: t,
                                          tipo: r.headers.get('content-type')})))
      .catch(e => done({status: 0, body: String(e), tipo: ''}));
    """
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url, metodo, cuerpo, tipo)


def main():
    print("=" * 70)
    print("  SONDA - cuerpo del POST de descarga")
    print("=" * 70)
    print()
    print("  Captura que envia el boton 'Descargar' cuando eliges CSV.")
    print("  Sin ese dato no se puede automatizar la descarga.")
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Prefactura (ENTER para 6442506): ").strip() or "6442506"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(PREFACTURA + id_pref)
        print("-" * 70)
        print("  1) Espera a ver el detalle de la prefactura.")
        print("  2) Presiona ENTER aqui.")
        print("  3) Luego, EN CHROME: clic en 'Descargar' y elige CSV.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas el detalle... ")

        posts_con_cuerpo(driver)          # vaciar el log

        print()
        print("*" * 70)
        print("  AHORA, en la ventana de Chrome:")
        print("     - Clic en 'Descargar' (el azul junto a 'Regulares')")
        print("     - Elige CSV en el dialogo")
        print("*" * 70)
        input("\n>>> ENTER cuando hayas descargado el CSV... ")

        capturados = posts_con_cuerpo(driver)
        log(f"POST capturados: {len(capturados)}")

        # Los de prefactura primero
        capturados.sort(
            key=lambda c: 0 if "pre-invoices" in c["url"] else 1
        )

        print()
        print("=" * 70)
        print("  PETICIONES POST CAPTURADAS")
        print("=" * 70)
        for c in capturados:
            corta = c["url"].replace("https://envios.adminml.com", "")
            print(f"\n  POST {corta[:88]}")
            if c["cabeceras"]:
                for k, v in c["cabeceras"].items():
                    print(f"       {k}: {v[:60]}")
            if c["cuerpo"]:
                print(f"       cuerpo: {c['cuerpo'][:300]}")
            else:
                print("       (sin cuerpo)")

        # Probar el GET del reporte de operacion
        print()
        print("=" * 70)
        print("  PROBANDO EL GET DEL REPORTE DE OPERACION")
        print("=" * 70)
        url_rep = (
            f"{API_REPORTE}?mile=LM&init_date=2026-07-01"
            "&end_date=2026-07-15&report_type=carrier"
        )
        try:
            r = pedir(driver, url_rep)
            print(f"  status : {r.get('status')}")
            print(f"  tipo   : {r.get('tipo')}")
            cuerpo = r.get("body") or ""
            print(f"  tamano : {len(cuerpo)} caracteres")
            if cuerpo:
                primera = cuerpo.splitlines()[0][:150] if "\n" in cuerpo else cuerpo[:150]
                print(f"  empieza: {primera}")
        except Exception as e:
            print(f"  error: {str(e)[:120]}")

        # --- Reporte ---
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"post_descarga_{sello}.txt")
        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("CUERPO DEL POST DE DESCARGA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}\n")
            f.write("NOTA: no se incluyen cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")
            for c in capturados:
                f.write(f"POST {c['url']}\n")
                for k, v in c["cabeceras"].items():
                    f.write(f"  {k}: {v}\n")
                f.write(f"  cuerpo: {c['cuerpo']}\n\n")
            f.write("\nGET del reporte de operacion:\n")
            f.write(f"  {url_rep}\n")

        print()
        print("=" * 70)
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

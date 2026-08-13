# -*- coding: utf-8 -*-
"""
Inspecciona los 'items' de una prefactura para ver si traen driver_id.

La sonda mostro que /pre-invoices/<id> devuelve 134 KB con las claves
driver_id, carrier_name e items. Aqui bajamos a un item concreto para ver
como se relaciona el conductor con cada linea del detalle.

Los nombres se enmascaran; los ids se muestran completos.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE_WEB = "https://envios.adminml.com/logistics/billing/invoices/"
API = "https://envios.adminml.com/logistics/billing/api/pre-invoices/"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    if os.path.isdir(PROFILE_DIR):
        if os.name == "nt":
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
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url)


def tapar(valor):
    """Enmascara texto; deja los numeros intactos."""
    t = str(valor)
    if t in ("None", "True", "False", "") or t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:3] + "*" * min(10, max(0, len(t) - 3))


def describir(item, sangria="    "):
    lineas = []
    for k, v in item.items():
        if isinstance(v, dict):
            lineas.append(f"{sangria}{k}: {{{', '.join(list(v.keys())[:8])}}}")
            for k2, v2 in list(v.items())[:8]:
                if not isinstance(v2, (dict, list)):
                    lineas.append(f"{sangria}    {k2} = {tapar(v2)}")
        elif isinstance(v, list):
            lineas.append(f"{sangria}{k}: [{len(v)} elementos]")
            if v and isinstance(v[0], dict):
                lineas.append(f"{sangria}    claves: {', '.join(list(v[0].keys())[:12])}")
                for k2, v2 in list(v[0].items())[:10]:
                    if not isinstance(v2, (dict, list)):
                        lineas.append(f"{sangria}      {k2} = {tapar(v2)}")
        else:
            lineas.append(f"{sangria}{k} = {tapar(v)}")
    return lineas


def main():
    print("=" * 70)
    print("  ITEMS DE LA PREFACTURA - buscando driver_id")
    print("=" * 70)
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Prefactura (ENTER para 6442506): ").strip() or "6442506"

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

        log(f"Pidiendo la prefactura {id_pref}...")
        resp = pedir(driver, API + id_pref)
        if resp.get("status") != 200:
            log(f"Respondio {resp.get('status')}: {(resp.get('body') or '')[:160]}")
            input(">>> ENTER para cerrar... ")
            return

        datos = json.loads(resp["body"])
        items = datos.get("items") or []
        log(f"La prefactura trae {len(items)} items.")

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(BASE_DIR, f"items_billing_{sello}.txt")

        with open(ruta, "w", encoding="utf-8-sig") as f:
            f.write("ITEMS DE LA PREFACTURA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}   Items: {len(items)}\n")
            f.write("Los nombres van enmascarados; los ids completos.\n")
            f.write("=" * 70 + "\n\n")

            # Cuantos items traen driver_id con valor
            con_driver = [
                i for i in items
                if isinstance(i, dict) and i.get("driver_id") not in (None, "", 0)
            ]
            resumen = (
                f"Items con driver_id: {len(con_driver)} de {len(items)}"
            )
            print(f"  {resumen}")
            f.write(resumen + "\n\n")

            # Que claves tienen los items
            if items and isinstance(items[0], dict):
                claves = sorted(items[0].keys())
                print(f"  Claves de un item: {', '.join(claves[:14])}")
                f.write(f"CLAVES DE UN ITEM:\n  {', '.join(claves)}\n\n")

            # Los primeros items, con y sin driver
            for etiqueta, lote in (("ITEMS CON driver_id", con_driver[:3]),
                                   ("PRIMEROS ITEMS", items[:3])):
                if not lote:
                    continue
                f.write(f"--- {etiqueta} ---\n")
                for n, it in enumerate(lote, 1):
                    f.write(f"  item {n}:\n")
                    f.write("\n".join(describir(it)) + "\n\n")

            # Si los items anidan sub-items, mirar ahi tambien
            for it in items[:5]:
                if not isinstance(it, dict):
                    continue
                for k, v in it.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        hijas = set(v[0].keys())
                        if any("driver" in c.lower() for c in hijas):
                            f.write(f"--- SUB-ITEMS en '{k}' CON driver ---\n")
                            f.write(f"  claves: {', '.join(sorted(hijas))}\n")
                            for k2, v2 in list(v[0].items())[:14]:
                                if not isinstance(v2, (dict, list)):
                                    f.write(f"    {k2} = {tapar(v2)}\n")
                            f.write("\n")
                            print(f"  SUB-ITEMS en '{k}' traen driver!")
                            break

        print()
        print("=" * 70)
        print(f"  Reporte: {ruta}")
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

# -*- coding: utf-8 -*-
"""
Prueba los dos endpoints antes de construir el extractor final.

  1. GET  /api/carriers/reports?...           -> ruta + id transportista
  2. POST /logistics/billing/api/pre-invoices/<id>/reports/details
          cuerpo {"tolls_items":null}          -> detalle con id de ruta

Confirma que responden, que formato devuelven y si sus rutas cruzan.
Muestra solo estructura y conteos; los nombres van enmascarados.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

WEB = "https://envios.adminml.com/logistics/billing/invoices/"
API_REPORTE = "https://envios.adminml.com/api/carriers/reports"
API_DETALLE = (
    "https://envios.adminml.com/logistics/billing/api/pre-invoices/"
    "{id}/reports/details"
)

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


def llamar(driver, url, metodo="GET", cuerpo=None):
    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include',
                headers: {'Accept': 'application/json, text/plain, */*'}};
    if (cuerpo !== null) {
      op.headers['Content-Type'] = 'application/json';
      op.body = cuerpo;
    }
    fetch(url, op)
      .then(r => r.text().then(t => done({status: r.status, body: t,
                                          tipo: r.headers.get('content-type')})))
      .catch(e => done({status: 0, body: String(e), tipo: ''}));
    """
    driver.set_script_timeout(120)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", "") or t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:3] + "*" * min(8, max(0, len(t) - 3))


def resumir(obj, nivel=0, tope=2):
    lineas = []
    sangria = "    " * (nivel + 1)
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:18]:
            if isinstance(v, list):
                lineas.append(f"{sangria}{k}: [{len(v)}]")
                if v and nivel < tope:
                    lineas += resumir(v[0], nivel + 1, tope)
            elif isinstance(v, dict):
                lineas.append(f"{sangria}{k}: {{...}}")
                if nivel < tope:
                    lineas += resumir(v, nivel + 1, tope)
            else:
                lineas.append(f"{sangria}{k} = {tapar(v)}")
    elif isinstance(obj, list):
        lineas.append(f"{sangria}[{len(obj)} elementos]")
        if obj and nivel < tope:
            lineas += resumir(obj[0], nivel + 1, tope)
    return lineas


def main():
    print("=" * 70)
    print("  PRUEBA DE LOS DOS ENDPOINTS")
    print("=" * 70)
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Prefactura (ENTER para 6442506): ").strip() or "6442506"
    desde = input(">>> Fecha inicial (ENTER para 2026-07-01): ").strip() or "2026-07-01"
    hasta = input(">>> Fecha final   (ENTER para 2026-07-15): ").strip() or "2026-07-15"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(WEB + id_pref)
        print("-" * 70)
        print("  Espera a ver la prefactura y presiona ENTER.")
        print("-" * 70)
        input("\n>>> ENTER... ")

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"prueba_endpoints_{sello}.txt")
        salida = []

        def anota(t):
            print(t)
            salida.append(t)

        # ---------- 1) Reporte de operacion ----------
        anota("")
        anota("=" * 70)
        anota("  1) REPORTE DE OPERACION (ruta + id transportista)")
        anota("=" * 70)
        url = (f"{API_REPORTE}?mile=LM&init_date={desde}"
               f"&end_date={hasta}&report_type=carrier")
        anota(f"  GET {url.replace('https://envios.adminml.com','')}")

        rutas_reporte = {}
        try:
            r = llamar(driver, url)
            anota(f"  status: {r.get('status')}   tipo: {r.get('tipo')}")
            cuerpo = r.get("body") or ""
            anota(f"  tamano: {len(cuerpo)} caracteres")

            if r.get("status") == 200 and cuerpo:
                try:
                    obj = json.loads(cuerpo)
                    anota("  Estructura:")
                    salida.extend(resumir(obj))
                    print("\n".join(resumir(obj)[:12]))

                    # Buscar la lista de filas
                    filas = obj if isinstance(obj, list) else None
                    if filas is None and isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                filas = v
                                anota(f"  Filas en '{k}': {len(v)}")
                                break
                    if filas:
                        claves = list(filas[0].keys())
                        anota(f"  Claves: {', '.join(claves[:16])}")
                        # Armar el mapa ruta -> id
                        kr = next((k for k in claves if "route" in k.lower()
                                   and "id" in k.lower()), None)
                        kd = next((k for k in claves if ("driver" in k.lower()
                                   or "carrier" in k.lower()) and "id" in k.lower()), None)
                        if kr and kd:
                            for f in filas:
                                if f.get(kr):
                                    rutas_reporte[str(f[kr]).strip()] = str(f[kd]).strip()
                            anota(f"  MAPA ruta->id armado: {len(rutas_reporte)} rutas")
                            anota(f"    (usando '{kr}' y '{kd}')")
                except json.JSONDecodeError:
                    anota("  No es JSON. Primeras lineas:")
                    for l in cuerpo.splitlines()[:4]:
                        anota(f"    {l[:150]}")
                    # Puede ser CSV
                    if ";" in cuerpo or "," in cuerpo:
                        lineas = cuerpo.splitlines()
                        sep = ";" if ";" in lineas[0] else ","
                        cab = [c.strip('"') for c in lineas[0].split(sep)]
                        anota(f"  CSV con {len(lineas)-1} filas, {len(cab)} columnas")
                        anota(f"  Columnas: {', '.join(cab[:16])}")
        except Exception as e:
            anota(f"  ERROR: {str(e)[:150]}")

        # ---------- 2) Detalle de la prefactura ----------
        anota("")
        anota("=" * 70)
        anota("  2) DETALLE DE PREFACTURA (con ID de ruta)")
        anota("=" * 70)
        url2 = API_DETALLE.format(id=id_pref)
        anota(f"  POST {url2.replace('https://envios.adminml.com','')}")
        anota('  cuerpo: {"tolls_items":null}')

        try:
            r2 = llamar(driver, url2, "POST", '{"tolls_items":null}')
            anota(f"  status: {r2.get('status')}   tipo: {r2.get('tipo')}")
            cuerpo2 = r2.get("body") or ""
            anota(f"  tamano: {len(cuerpo2)} caracteres")

            if r2.get("status") == 200 and cuerpo2:
                try:
                    obj2 = json.loads(cuerpo2)
                    anota("  Estructura:")
                    salida.extend(resumir(obj2))
                    print("\n".join(resumir(obj2)[:12]))
                except json.JSONDecodeError:
                    lineas = cuerpo2.splitlines()
                    anota(f"  Texto plano con {len(lineas)} lineas")
                    for l in lineas[:6]:
                        anota(f"    {l[:150]}")
        except Exception as e:
            anota(f"  ERROR: {str(e)[:150]}")

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("PRUEBA DE ENDPOINTS\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}   Rango: {desde} a {hasta}\n")
            f.write("Nombres enmascarados.\n")
            f.write("=" * 70 + "\n")
            f.write("\n".join(salida) + "\n")

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

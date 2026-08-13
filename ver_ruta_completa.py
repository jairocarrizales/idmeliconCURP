# -*- coding: utf-8 -*-
"""
Muestra TODOS los campos de una ruta del monitoreo.

La sonda encontro la API:
    POST /logistics/api/monitoring/get-routes-list
         {"serviceCenterId":"SMT1","page":1,"pageSize":50,"siteId":"MLM"}

pero solo listo las claves que coincidian con ciertas palabras. Aqui se
vuelca la estructura entera de una ruta, para ver si trae zona, codigo
postal y nombre de ruta, que son los que le faltan al control.

Tambien prueba la paginacion y pide el detalle de una ruta.

Los textos van enmascarados; los numeros completos.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PANEL = "https://envios.adminml.com/logistics/monitoring-distribution"
API_LISTA = "https://envios.adminml.com/logistics/api/monitoring/get-routes-list"

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
    """Enmascara texto; deja numeros y booleanos."""
    t = str(v)
    if t in ("None", "True", "False", ""):
        return t
    if t.replace(".", "").replace("-", "").isdigit():
        return t
    return t[:6] + "*" * min(8, max(0, len(t) - 6))


def volcar(obj, ruta="", salida=None, nivel=0):
    """Aplana el JSON entero: cada hoja con su camino completo."""
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
            salida.append((f"{ruta}[]", "(lista vacia)"))
        for i, v in enumerate(obj[:1]):     # basta con el primero
            volcar(v, f"{ruta}[{i}]", salida, nivel + 1)
    return salida


def main():
    print("=" * 74)
    print("  ESTRUCTURA COMPLETA DE UNA RUTA DEL MONITOREO")
    print("=" * 74)
    print()

    estacion = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not estacion:
        estacion = input(">>> Estacion (ENTER para SMT1): ").strip() or "SMT1"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(PANEL)
        print("-" * 74)
        print("  Inicia sesion si hace falta y espera a ver el panel.")
        print("-" * 74)
        input("\n>>> ENTER cuando lo veas... ")

        if "adminml.com" not in (driver.current_url or ""):
            driver.get(PANEL)
            time.sleep(4)

        cuerpo = json.dumps({
            "serviceCenterId": estacion,
            "page": 1,
            "pageSize": 50,
            "siteId": "MLM",
            "order_by": "performance",
        })

        log(f"Pidiendo las rutas de {estacion}...")
        r = pedir(driver, API_LISTA, "POST", cuerpo)
        if r.get("status") != 200:
            log(f"Respondio {r.get('status')}: {(r.get('body') or '')[:200]}")
            input(">>> ENTER para cerrar... ")
            return

        datos = json.loads(r["body"])
        claves_raiz = list(datos.keys()) if isinstance(datos, dict) else []
        log(f"Claves de la raiz: {', '.join(claves_raiz)}")

        rutas = datos.get("routes") or []
        log(f"Rutas en la pagina 1: {len(rutas)}")

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        rep = os.path.join(BASE_DIR, f"ruta_completa_{sello}.txt")

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("ESTRUCTURA COMPLETA DE UNA RUTA\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Estacion: {estacion}\n")
            f.write("Los textos van enmascarados; los numeros completos.\n")
            f.write("=" * 74 + "\n\n")

            f.write(f"Claves de la raiz: {', '.join(claves_raiz)}\n")
            for k in claves_raiz:
                v = datos[k]
                if not isinstance(v, (dict, list)):
                    f.write(f"  {k} = {tapar(v)}\n")
                elif isinstance(v, list):
                    f.write(f"  {k}: [{len(v)} elementos]\n")
            f.write("\n")

            if rutas:
                campos = volcar(rutas[0])
                f.write(f"--- TODOS LOS CAMPOS DE UNA RUTA ({len(campos)}) ---\n")
                for camino, valor in campos:
                    f.write(f"  {camino} = {tapar(valor)}\n")

                print()
                print("=" * 74)
                print(f"  LA RUTA TIENE {len(campos)} CAMPOS")
                print("=" * 74)
                for camino, valor in campos:
                    print(f"  {camino:<52} = {tapar(valor)}")

                # Que columnas del control se pueden llenar
                f.write("\n--- LO QUE LE FALTA AL CONTROL ---\n")
                print()
                print("=" * 74)
                print("  COLUMNAS DEL CONTROL QUE SE PUEDEN LLENAR")
                print("=" * 74)
                buscar = {
                    "CEDIS_MELI": ("servicecenter", "facility", "station"),
                    "Vehiculo": ("vehicledescription", "vehicletype", "vehicle"),
                    "TIPO_DE_VEHICULO": ("vehicletype", "deliverytype"),
                    "Tipo_de_servicio": ("type", "servicetype", "deliverytype"),
                    "Tipo_de_ruta": ("isdelivery", "ispickup", "routetype"),
                    "ZONA_DE_RUTA": ("zone", "zona", "city", "municip", "area"),
                    "CODIGO_POSTAL": ("zip", "postal", "cp"),
                    "RUTA": ("routename", "name", "code", "label"),
                    "SACAS": ("bag", "saca"),
                }
                for columna, patrones in buscar.items():
                    hallados = [
                        (c, v) for c, v in campos
                        if any(p in c.lower() for p in patrones)
                    ]
                    if hallados:
                        linea = f"  {columna:<18} -> " + ", ".join(
                            f"{c.split('.')[-1]}={tapar(v)}" for c, v in hallados[:3])
                    else:
                        linea = f"  {columna:<18} -> NO ENCONTRADO"
                    print(linea)
                    f.write(linea + "\n")

            # Probar la paginacion
            print()
            log("Probando la paginacion (pagina 2)...")
            cuerpo2 = json.dumps({
                "serviceCenterId": estacion, "page": 2, "pageSize": 50,
                "siteId": "MLM", "order_by": "performance",
            })
            r2 = pedir(driver, API_LISTA, "POST", cuerpo2)
            if r2.get("status") == 200:
                d2 = json.loads(r2["body"])
                n2 = len(d2.get("routes") or [])
                log(f"  Pagina 2: {n2} rutas")
                f.write(f"\nPaginacion: la pagina 2 devuelve {n2} rutas\n")
                for k in ("total", "totalPages", "totalElements", "count"):
                    if isinstance(d2, dict) and k in d2:
                        log(f"  {k} = {d2[k]}")
                        f.write(f"  {k} = {d2[k]}\n")

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

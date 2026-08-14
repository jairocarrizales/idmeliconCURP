# -*- coding: utf-8 -*-
"""
Descubridor de la API de prefacturas (billing) de Mercado Libre.

El CSV que descarga la pagina trae el nombre del conductor pero NO su ID.
Este script observa que peticiones hace la pagina de la prefactura, para
ver si alguna devuelve el detalle CON el id del driver.

Igual que DescubrirAPI, pero apuntado a /logistics/billing/invoices/<id>.

El reporte NO incluye cookies ni tokens.
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE = "https://envios.adminml.com/logistics/billing/invoices/"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Palabras que identifican a la persona que conduce
PALABRAS_CONDUCTOR = ("driver", "conductor", "carrier", "employee", "chofer")

# Una clave cuenta como id si es "id" a secas, o termina en Id/_id
RE_ID = re.compile(r"^id$|Id$|_id$", re.I)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def cerrar_chrome_huerfano():
    """Cierra los Chrome que quedaron usando NUESTRO perfil."""
    if os.name != "nt":
        return 0
    marca = os.path.basename(PROFILE_DIR)
    proyecto = os.path.basename(os.path.dirname(PROFILE_DIR))
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{proyecto}*' -and "
        f"$_.CommandLine -like '*{marca}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue; $_.ProcessId }"
    )
    try:
        import subprocess

        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cerrados = [l for l in (res.stdout or "").split() if l.strip().isdigit()]
        if cerrados:
            log(f"Se cerraron {len(cerrados)} Chrome de una corrida anterior.")
            time.sleep(2)
        return len(cerrados)
    except Exception:
        return 0


def limpiar_lock():
    if not os.path.isdir(PROFILE_DIR):
        return
    cerrar_chrome_huerfano()
    for nombre in ("lockfile", "LOCK", "SingletonLock", "SingletonCookie",
                   "SingletonSocket", "DevToolsActivePort"):
        for carpeta in (PROFILE_DIR, os.path.join(PROFILE_DIR, "Default")):
            try:
                ruta = os.path.join(carpeta, nombre)
                if os.path.exists(ruta):
                    os.remove(ruta)
            except Exception:
                pass


def crear_driver():
    limpiar_lock()
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


def leer_peticiones(driver):
    """Peticiones XHR/Fetch vistas desde la ultima lectura."""
    vistas = {}
    try:
        entradas = driver.get_log("performance")
    except Exception as e:
        log(f"No se pudo leer el log de red: {e}")
        return []

    for entrada in entradas:
        try:
            mensaje = json.loads(entrada["message"])["message"]
        except Exception:
            continue
        if mensaje.get("method") != "Network.requestWillBeSent":
            continue
        params = mensaje.get("params", {})
        url = (params.get("request") or {}).get("url", "")
        if not url.startswith("http"):
            continue
        if params.get("type", "") not in ("XHR", "Fetch"):
            continue
        basura = (".js", ".css", ".png", ".svg", ".woff", "/metrics",
                  "melidata", "google-analytics", "newrelic", "o11y")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = True
    return list(vistas)


def pedir(driver, url):
    """GET desde la propia pagina, reusando su sesion. Cuerpo completo."""
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials:'include', headers:{'Accept':'application/json'}})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(45)
    return driver.execute_async_script(script, url)


def desplegar_secciones(driver):
    """Abre las secciones plegables (Subtotal de servicios, etc.).

    El detalle con los conductores suele pedirse recien al desplegarlas, asi
    que sin esto el log de red no lo ve nunca.
    """
    abiertas = 0
    selectores = (
        "svg[class*='chevron']",
        "[class*='accordion'] button",
        "[class*='collapse'] button",
        "[data-testid*='accordion']",
        "[class*='row'] svg",
        "button[aria-expanded='false']",
    )
    vistos = set()

    for sel in selectores:
        try:
            elementos = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue
        for el in elementos[:25]:          # tope: no queremos abrir media pagina
            try:
                if not el.is_displayed():
                    continue
                marca = el.id
                if marca in vistos:
                    continue
                vistos.add(marca)
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el
                )
                driver.execute_script("arguments[0].click();", el)
                abiertas += 1
                time.sleep(0.35)
            except Exception:
                continue
        if abiertas:
            break                          # con un selector que funcione basta
    return abiertas


def urls_de_descarga(driver):
    """Saca las URLs a las que apunta el boton 'Descargar', si las hay."""
    encontradas = []
    try:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = a.get_attribute("href") or ""
            if any(p in href.lower() for p in ("download", "descarga", "export",
                                               "csv", "detail", "invoice")):
                if href.startswith("http"):
                    encontradas.append(href)
    except Exception:
        pass
    return encontradas


def buscar_conductores(obj, ruta="", hallazgos=None):
    """Busca objetos que tengan nombre de conductor Y algun id cerca."""
    if hallazgos is None:
        hallazgos = []

    if isinstance(obj, dict):
        claves = list(obj.keys())

        # Caso A: el nodo mismo habla de un conductor (driverId, driverName...)
        # Solo cuenta si menciona explicitamente a un conductor: antes bastaba
        # con "name", y eso colaba el menu del sitio ({id, name}).
        propio = any(
            p in k.lower() for k in claves for p in PALABRAS_CONDUCTOR
        )
        # Caso B: el nodo ES el conductor porque su padre se llama "driver",
        # y entonces sus claves son las simples {id, name}
        heredado = any(
            p in ruta.rsplit(".", 1)[-1].lower() for p in PALABRAS_CONDUCTOR
        )

        tiene_id = any(RE_ID.search(k) for k in claves)

        if (propio or heredado) and tiene_id:
            muestra = {}
            for k in claves:
                bajo = k.lower()
                interesa = (
                    RE_ID.search(k)
                    or any(p in bajo for p in PALABRAS_CONDUCTOR)
                    or any(p in bajo for p in ("name", "nombre", "route",
                                               "ruta", "plate", "patente"))
                )
                if interesa and not isinstance(obj[k], (dict, list)):
                    muestra[k] = obj[k]
            if muestra:
                hallazgos.append((ruta or "(raiz)", muestra))

        for k, v in obj.items():
            buscar_conductores(v, f"{ruta}.{k}" if ruta else k, hallazgos)

    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):     # basta con mirar los primeros
            buscar_conductores(v, f"{ruta}[{i}]", hallazgos)

    return hallazgos


def main():
    print("=" * 70)
    print("  DESCUBRIDOR DE API - Prefacturas (billing)")
    print("=" * 70)
    print()
    print("  Busca si el detalle de la prefactura se puede pedir CON el")
    print("  id del conductor, que el CSV no incluye.")
    print()

    # El id de la prefactura: por argumento, preguntado, o el de ejemplo
    id_pref = ""
    if len(sys.argv) > 1:
        id_pref = sys.argv[1].strip()
    if not id_pref:
        id_pref = input(">>> Numero de prefactura (ENTER para 6442506): ").strip()
    if not id_pref:
        id_pref = "6442506"

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        url_pagina = BASE + id_pref
        driver.get(url_pagina)

        print("-" * 70)
        print("  1) Inicia sesion si hace falta.")
        print("  2) Espera a ver el DETALLE DE LA PREFACTURA.")
        print("  3) Regresa aqui y presiona ENTER.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas la prefactura... ")

        if "billing/invoices" not in (driver.current_url or ""):
            log("Volviendo a la pagina de la prefactura...")
            driver.get(url_pagina)
            time.sleep(4)

        # 1) Capturar lo que ya se pidio al cargar
        log("Leyendo el trafico de la pagina...")
        urls = leer_peticiones(driver)

        # 2) Recargar para capturar todo desde cero
        log("Recargando para ver todas las peticiones...")
        driver.refresh()
        time.sleep(8)
        urls = list(dict.fromkeys(urls + leer_peticiones(driver)))
        log(f"Peticiones al cargar: {len(urls)}")

        # 3) Desplegar las secciones: el detalle suele pedirse al abrirlas
        log("Desplegando las secciones de la prefactura...")
        abiertas = desplegar_secciones(driver)
        if abiertas:
            log(f"  Se desplegaron {abiertas} secciones; esperando sus datos...")
            time.sleep(6)
            nuevas = leer_peticiones(driver)
            antes = len(urls)
            urls = list(dict.fromkeys(urls + nuevas))
            if len(urls) > antes:
                log(f"  Aparecieron {len(urls) - antes} peticiones nuevas.")

        # 4) El boton "Descargar" puede pegarle a un endpoint con mas datos
        log("Buscando el endpoint del boton Descargar...")
        urls = list(dict.fromkeys(urls + urls_de_descarga(driver)))

        log(f"Total de peticiones a revisar: {len(urls)}")

        # 3) Revisar cada una
        print()
        print("=" * 70)
        print("  REVISANDO RESPUESTAS")
        print("=" * 70)

        con_id = []
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
                # No es JSON: puede ser el CSV del boton Descargar
                if ";" in cuerpo and "\n" in cuerpo and len(cuerpo) > 200:
                    cabecera = cuerpo.splitlines()[0][:120]
                    tiene_id = re.search(r"\bid\b", cabecera, re.I) is not None
                    marca = "  <-- CSV CON COLUMNA ID" if tiene_id else "  (CSV)"
                    print(f"  {url[:88]}{marca}")
                    if tiene_id:
                        con_id.append((url, [("CSV", {"cabecera": cabecera})],
                                       len(cuerpo)))
                continue

            hallazgos = buscar_conductores(obj)
            marca = ""
            if hallazgos:
                marca = "  <-- TIENE CONDUCTOR + ID"
                con_id.append((url, hallazgos, len(cuerpo)))
            print(f"  {url[:92]}{marca}")
            time.sleep(0.2)

        # 4) Reporte
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(BASE_DIR, f"api_billing_{sello}.txt")
        with open(ruta, "w", encoding="utf-8-sig") as f:
            f.write("REPORTE - API DE PREFACTURAS\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Prefactura: {id_pref}\n")
            f.write("NOTA: no se incluyen cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")

            if con_id:
                f.write("APIS CON CONDUCTOR + ID\n\n")
                for url, hallazgos, tam in con_id:
                    f.write(f"URL    : {url}\n")
                    f.write(f"Tamano : {tam} caracteres\n")
                    for ruta_campo, muestra in hallazgos[:6]:
                        f.write(f"  en {ruta_campo}:\n")
                        for k, v in muestra.items():
                            f.write(f"      {k} = {v}\n")
                    f.write("\n")
            else:
                f.write("Ninguna respuesta trae conductor junto con un id.\n")
                f.write("Quiza el detalle solo exista como CSV.\n\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("TODAS LAS PETICIONES OBSERVADAS\n")
            f.write("=" * 70 + "\n")
            for u in urls:
                f.write(u + "\n")

        print()
        print("=" * 70)
        if con_id:
            print("  ENCONTRADO: hay una API con conductor e id")
            print()
            for url, hallazgos, _ in con_id[:3]:
                print(f"  {url[:96]}")
                for ruta_campo, muestra in hallazgos[:2]:
                    campos = ", ".join(f"{k}={v}" for k, v in list(muestra.items())[:4])
                    print(f"     {campos[:88]}")
                print()
        else:
            print("  No se encontro conductor+id en las respuestas JSON.")
            print("  Alternativa: cruzar el CSV con el padron por nombre.")
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

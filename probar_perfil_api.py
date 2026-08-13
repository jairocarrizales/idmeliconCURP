# -*- coding: utf-8 -*-
"""
Sonda: averigua si existe una API de PERFIL que devuelva telefono y e-mail.

La API del listado (drivers-and-invites) no trae esos campos. Este script
prueba varias rutas candidatas con UN SOLO driver para ver cual responde,
antes de invertir tiempo en extraer 2000 perfiles.

No guarda datos: solo imprime que ruta funciono y que campos trae.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://envios.adminml.com/logistics/provider-management/drivers"
BASE_API = "https://envios.adminml.com/logistics/provider-management/api"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Rutas que suelen usarse para el detalle de un recurso
CANDIDATAS = [
    "/drivers/{id}",
    "/drivers/driver/{id}",
    "/drivers/{id}/detail",
    "/drivers/detail/{id}",
    "/drivers/{id}/profile",
    "/driver/{id}",
]

# Campos que nos interesan
BUSCADOS = ("phone", "phoneNumber", "email", "mobile", "telephone", "contact")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar_lock():
    if not os.path.isdir(PROFILE_DIR):
        return
    for nombre in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        for ruta in (
            os.path.join(PROFILE_DIR, nombre),
            os.path.join(PROFILE_DIR, "Default", nombre),
        ):
            try:
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


def pedir(driver, url):
    """GET desde la propia pagina, reusando la sesion.

    OJO: se devuelve el cuerpo COMPLETO. Recortarlo aqui partia el JSON a la
    mitad y json.loads fallaba con "Unterminated string". El recorte se hace
    al imprimir, no antes de parsear.
    """
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials:'include', headers:{'Accept':'application/json'}})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(30)
    return driver.execute_async_script(script, url)


def campos_interesantes(obj, prefijo=""):
    """Busca recursivamente claves que parezcan telefono o correo."""
    hallados = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            ruta = f"{prefijo}.{k}" if prefijo else k
            if any(b in k.lower() for b in BUSCADOS) and not isinstance(v, (dict, list)):
                hallados[ruta] = v
            elif isinstance(v, (dict, list)):
                hallados.update(campos_interesantes(v, ruta))
    elif isinstance(obj, list) and obj:
        hallados.update(campos_interesantes(obj[0], f"{prefijo}[0]"))
    return hallados


def leer_urls_del_log(driver):
    """Devuelve las URLs de tipo XHR/Fetch vistas desde la ultima lectura."""
    urls = {}
    try:
        entradas = driver.get_log("performance")
    except Exception:
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
        tipo = params.get("type", "")
        if not url.startswith("http"):
            continue
        if tipo not in ("XHR", "Fetch"):
            continue
        if any(b in url.lower() for b in (".js", ".css", "/metrics", "melidata")):
            continue
        urls[url] = True
    return list(urls)


def espiar_perfil(driver, id_prueba):
    """Abre la ficha real del driver y observa que peticiones dispara.

    Mas confiable que adivinar rutas: si la pantalla muestra el telefono,
    alguna de estas peticiones tuvo que traerlo.
    """
    url_perfil = (
        "https://envios.adminml.com/logistics/provider-management/drivers/edit/"
        f"{id_prueba}"
    )

    leer_urls_del_log(driver)          # vaciar el log
    log(f"Abriendo la ficha de prueba: /drivers/edit/{id_prueba}")
    driver.get(url_perfil)
    time.sleep(6)                      # dejar que cargue todo

    urls = leer_urls_del_log(driver)
    log(f"Peticiones XHR/Fetch observadas: {len(urls)}")

    hallazgos = []
    for url in urls:
        try:
            resp = pedir(driver, url)
        except Exception:
            continue
        if resp.get("status") != 200:
            continue
        try:
            obj = json.loads(resp.get("body") or "")
        except json.JSONDecodeError:
            continue
        campos = campos_interesantes(obj)
        marca = "  <-- TIENE CONTACTO" if campos else ""
        print(f"    {url[:88]}{marca}")
        if campos:
            hallazgos.append((url, obj, campos))
        time.sleep(0.2)

    return hallazgos


def main():
    print("=" * 70)
    print("  SONDA: hay API de perfil con telefono/e-mail?")
    print("=" * 70)
    print()
    print("  Prueba varias rutas con UN driver. No guarda datos.")
    print()

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(URL)
        print("-" * 70)
        print("  Inicia sesion y espera a ver la lista.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas la lista... ")

        if "provider-management" not in driver.current_url:
            driver.get(URL)
            time.sleep(3)

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
        except Exception:
            pass

        # 1) Sacar un ID de ejemplo del propio listado
        log("Pidiendo un driver de ejemplo al listado...")
        r = pedir(
            driver,
            f"{BASE_API}/drivers/drivers-and-invites"
            "?status=active&paginated=true",
        )
        cuerpo = r.get("body") or ""
        if r.get("status") != 200:
            log(f"El listado respondio {r.get('status')}.")
            log(f"Empieza con: {cuerpo[:150]}")
            log("Si es 401/403, la sesion caduco: inicia sesion de nuevo.")
            input(">>> ENTER para cerrar... ")
            return

        try:
            datos = json.loads(cuerpo)
        except json.JSONDecodeError as e:
            log(f"El listado no devolvio JSON valido: {e}")
            log(f"Longitud recibida: {len(cuerpo)} caracteres")
            log(f"Empieza con: {cuerpo[:150]}")
            input(">>> ENTER para cerrar... ")
            return

        resultados = datos.get("result") or datos.get("results") or []
        if not resultados:
            log("El listado respondio, pero sin registros.")
            log(f"Claves recibidas: {list(datos.keys())}")
            input(">>> ENTER para cerrar... ")
            return

        ejemplo = resultados[0]
        id_prueba = ejemplo.get("id")
        if not id_prueba:
            log(f"El primer registro no trae 'id'. Claves: {list(ejemplo.keys())}")
            input(">>> ENTER para cerrar... ")
            return

        nombre = f"{ejemplo.get('firstName','')} {ejemplo.get('lastName','')}".strip()
        log(f"Driver de prueba: {nombre} (id {id_prueba})")
        print()

        # 2) Probar cada ruta candidata
        print("=" * 70)
        print("  PROBANDO RUTAS")
        print("=" * 70)
        exitosas = []

        for plantilla in CANDIDATAS:
            ruta = plantilla.format(id=id_prueba)
            url = BASE_API + ruta
            try:
                resp = pedir(driver, url)
            except Exception as e:
                print(f"  {ruta:<28} ERROR  {str(e)[:40]}")
                continue

            estado = resp.get("status")
            cuerpo = resp.get("body") or ""

            if estado != 200:
                print(f"  {ruta:<28} {estado}")
                continue

            try:
                obj = json.loads(cuerpo)
            except json.JSONDecodeError:
                print(f"  {ruta:<28} 200 pero no es JSON")
                continue

            hallados = campos_interesantes(obj)
            marca = "  <-- TIENE CONTACTO" if hallados else ""
            print(f"  {ruta:<28} 200 JSON{marca}")
            exitosas.append((ruta, obj, hallados))
            time.sleep(0.3)

        # 3) Si adivinar no funciono, ESPIAR: abrir el perfil real y ver que pide
        if not any(e[2] for e in exitosas):
            print()
            log("Ninguna ruta adivinada trajo contacto. Vamos a espiar el perfil real...")
            espiadas = espiar_perfil(driver, id_prueba)
            for url, obj, hallados in espiadas:
                exitosas.append((url.replace(BASE_API, ""), obj, hallados))

        # 4) Reporte
        print()
        print("=" * 70)
        con_contacto = [e for e in exitosas if e[2]]

        if con_contacto:
            ruta, obj, hallados = con_contacto[0]
            print("  ENCONTRADA una API de perfil con datos de contacto:")
            completa = ruta if ruta.startswith("http") else BASE_API + ruta
            print(f"    {completa}")
            print()
            print("  Campos de contacto:")
            for k, v in hallados.items():
                # Enmascarar: esto es solo un diagnostico
                texto = str(v)
                visible = texto[:3] + "*" * max(0, len(texto) - 3)
                print(f"    {k:<28} = {visible}")
            print()
            print("  Todas las claves del registro:")
            claves = list(obj.keys()) if isinstance(obj, dict) else []
            print(f"    {', '.join(claves[:25])}")
        elif exitosas:
            print("  Hay rutas que responden JSON, pero NINGUNA trae telefono/e-mail.")
            for ruta, obj, _ in exitosas:
                claves = list(obj.keys()) if isinstance(obj, dict) else []
                print(f"    {ruta}: {', '.join(claves[:15])}")
        else:
            print("  Ninguna ruta candidata respondio.")
            print("  Alternativa: abre un perfil a mano con DevTools > Network")
            print("  y mira que peticion se dispara.")
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

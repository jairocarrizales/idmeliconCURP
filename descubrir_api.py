# -*- coding: utf-8 -*-
"""
Descubridor de la API que alimenta la tabla de drivers.

Abre Chrome con el log de red activado, espera tu login, presiona "Mostrar mas"
y te dice QUE peticiones se dispararon en ese momento. Esas son las candidatas
a ser la API que carga los datos.

Guarda el reporte en un .txt para que lo revises o me lo pases.

NOTA: el reporte NO incluye cookies ni tokens de autorizacion. Solo URLs,
metodo, tipo de contenido y una muestra de la respuesta.
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

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Cabeceras que jamas se escriben al reporte
CABECERAS_SECRETAS = {
    "cookie",
    "authorization",
    "x-csrf-token",
    "x-auth-token",
    "set-cookie",
    "proxy-authorization",
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-MX")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # Activar el log de rendimiento: ahi viene el trafico de red
    opts.set_capability(
        "goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"}
    )
    opts.add_experimental_option(
        "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False}
    )
    return webdriver.Chrome(options=opts)


def leer_peticiones(driver):
    """Saca las peticiones de red del performance log desde la ultima lectura."""
    peticiones = {}   # requestId -> datos
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

        metodo = mensaje.get("method", "")
        params = mensaje.get("params", {})
        rid = params.get("requestId")
        if not rid:
            continue

        if metodo == "Network.requestWillBeSent":
            req = params.get("request", {})
            peticiones.setdefault(rid, {}).update(
                {
                    "url": req.get("url", ""),
                    "metodo": req.get("method", ""),
                    "tipo": params.get("type", ""),
                    "post": (req.get("postData") or "")[:500],
                }
            )
        elif metodo == "Network.responseReceived":
            resp = params.get("response", {})
            peticiones.setdefault(rid, {}).update(
                {
                    "status": resp.get("status"),
                    "mime": resp.get("mimeType", ""),
                    "tipo": params.get("type", "") or peticiones.get(rid, {}).get("tipo", ""),
                }
            )

    return [dict(v, rid=k) for k, v in peticiones.items() if v.get("url")]


def es_candidata(p):
    """Filtra lo que parece una API de datos y descarta ruido."""
    url = p.get("url", "").lower()

    if not url.startswith("http"):
        return False

    # Descartar recursos estaticos y telemetria
    basura = (
        ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff",
        ".woff2", ".ttf", ".ico", ".map",
        "google-analytics", "googletagmanager", "doubleclick", "newrelic",
        "datadog", "sentry", "hotjar", "melidata", "/tracking", "/metrics",
        "/beacon", "mlstatic.com",
    )
    if any(b in url for b in basura):
        return False

    mime = (p.get("mime") or "").lower()
    tipo = (p.get("tipo") or "").lower()

    # Lo que nos interesa: JSON, o peticiones XHR/Fetch
    if "json" in mime:
        return True
    if tipo in ("xhr", "fetch"):
        return True

    # Palabras clave del dominio
    if any(k in url for k in ("driver", "provider", "carrier", "transport")):
        return True

    return False


def puntuar(p):
    """Que tan probable es que sea LA API de la tabla. Mas alto = mejor."""
    url = p.get("url", "").lower()
    puntos = 0
    if "driver" in url:
        puntos += 10
    if "provider-management" in url:
        puntos += 5
    if any(k in url for k in ("offset", "limit", "page", "scroll", "cursor")):
        puntos += 8
    if "json" in (p.get("mime") or "").lower():
        puntos += 4
    if "/api" in url or "/v1" in url or "/v2" in url:
        puntos += 3
    if p.get("metodo") == "GET":
        puntos += 1
    return puntos


def cuerpo_respuesta(driver, rid, limite=1200):
    """Pide a Chrome el cuerpo de una respuesta ya recibida."""
    try:
        r = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
        cuerpo = r.get("body", "")
        return cuerpo[:limite]
    except Exception:
        return ""


def main():
    print("=" * 70)
    print("  DESCUBRIDOR DE API - Tabla de drivers")
    print("=" * 70)
    print()
    print("  Este script NO extrae datos. Solo observa que peticiones hace")
    print("  la pagina al presionar 'Mostrar mas', para encontrar su API.")
    print()

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(URL)

        print("-" * 70)
        print("  1) Inicia sesion si hace falta.")
        print("  2) Espera a ver la LISTA DE DRIVERS.")
        print("  3) Regresa aqui y presiona ENTER.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas la lista... ")

        if "provider-management/drivers" not in driver.current_url:
            driver.get(URL)
            time.sleep(3)

        try:
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
        except Exception:
            log("No se detectaron filas, pero seguimos.")

        # Limpiar el log: nos interesa solo lo que pase de aqui en adelante
        leer_peticiones(driver)
        log("Log de red limpiado. Ahora presionaremos 'Mostrar mas'.")

        # Buscar y presionar el boton
        boton = None
        for sel in ("div.show-more-btn button", "div.show-more-btn .andes-button"):
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for b in els:
                if b.is_displayed():
                    boton = b
                    break
            if boton:
                break

        if boton is None:
            log("No se encontro 'Mostrar mas'. Bajando al fondo de la pagina...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            for b in driver.find_elements(By.CSS_SELECTOR, "div.show-more-btn button"):
                if b.is_displayed():
                    boton = b
                    break

        if boton is not None:
            log("Presionando 'Mostrar mas'...")
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", boton
            )
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", boton)
        else:
            log("Sin boton. Capturaremos el trafico de una recarga.")
            driver.refresh()

        log("Esperando la respuesta (8 s)...")
        time.sleep(8)

        peticiones = leer_peticiones(driver)
        log(f"Peticiones observadas: {len(peticiones)}")

        candidatas = [p for p in peticiones if es_candidata(p)]
        candidatas.sort(key=puntuar, reverse=True)
        log(f"Candidatas a API de datos: {len(candidatas)}")

        # Traer el cuerpo de las mejores
        for p in candidatas[:5]:
            p["muestra"] = cuerpo_respuesta(driver, p["rid"])

        # --- Reporte ---
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(BASE_DIR, f"api_encontrada_{sello}.txt")

        with open(ruta, "w", encoding="utf-8-sig") as f:
            f.write("REPORTE DE DESCUBRIMIENTO DE API\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Pagina: {URL}\n")
            f.write("NOTA: no se incluyen cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")

            if not candidatas:
                f.write(
                    "No se detectaron peticiones de datos.\n"
                    "Puede que la pagina cargue todo con HTML del servidor.\n\n"
                )

            for i, p in enumerate(candidatas, start=1):
                f.write(f"--- CANDIDATA {i} (puntaje {puntuar(p)}) ---\n")
                f.write(f"Metodo : {p.get('metodo')}\n")
                f.write(f"URL    : {p.get('url')}\n")
                f.write(f"Status : {p.get('status')}\n")
                f.write(f"MIME   : {p.get('mime')}\n")
                f.write(f"Tipo   : {p.get('tipo')}\n")
                if p.get("post"):
                    f.write(f"Body   : {p['post']}\n")
                if p.get("muestra"):
                    f.write("Muestra de la respuesta:\n")
                    f.write(p["muestra"] + "\n")
                f.write("\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("TODAS LAS PETICIONES OBSERVADAS\n")
            f.write("=" * 70 + "\n")
            for p in peticiones:
                f.write(f"{p.get('metodo','?'):6} {p.get('status','?'):>4}  {p.get('url','')}\n")

        print()
        print("=" * 70)
        if candidatas:
            print("  CANDIDATAS ENCONTRADAS (las mejores primero):")
            print()
            for i, p in enumerate(candidatas[:5], start=1):
                print(f"  {i}. [{puntuar(p)}] {p.get('metodo')} {p.get('url')[:110]}")
        else:
            print("  No se detecto ninguna API de datos.")
            print("  Probablemente la pagina renderiza en el servidor.")
        print()
        print(f"  Reporte completo: {ruta}")
        print("=" * 70)

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
    finally:
        input("\n>>> ENTER para cerrar el navegador... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

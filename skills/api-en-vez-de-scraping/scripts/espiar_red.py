# -*- coding: utf-8 -*-
"""
Descubridor generico de APIs: espia el trafico del propio navegador.

Adaptalo cambiando las tres constantes de arriba. El resto sirve igual para
cualquier panel web que cargue datos sin recargar la pagina.

Uso:
    python espiar_red.py

Genera un reporte con las URLs candidatas ordenadas por probabilidad y una
muestra de cada respuesta. No incluye cookies ni tokens.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ------------------------------------------------------------- AJUSTA ESTO
URL = "https://ejemplo.com/panel"          # la pagina con la tabla
PALABRA_CLAVE = "driver"                   # la palabra de tu dominio
SELECTOR_BOTON = "div.show-more-btn button"  # lo que dispara la carga
# --------------------------------------------------------------------------

BASE_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Lo que nunca es una API de datos
BASURA = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2",
    ".ttf", ".ico", ".map",
    "google-analytics", "googletagmanager", "doubleclick", "newrelic",
    "datadog", "sentry", "hotjar", "kaspersky", "/tracking", "/metrics",
    "/beacon", "__modules", "__resolve",
)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # Esto es lo que habilita el espionaje
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option(
        "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False}
    )
    return webdriver.Chrome(options=opts)


def leer_peticiones(driver):
    """Empareja requestWillBeSent con responseReceived por requestId."""
    peticiones = {}
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
            peticiones.setdefault(rid, {}).update({
                "url": req.get("url", ""),
                "metodo": req.get("method", ""),
                "tipo": params.get("type", ""),
                # El postData es clave para reproducir un POST
                "post": (req.get("postData") or "")[:500],
            })
        elif metodo == "Network.responseReceived":
            resp = params.get("response", {})
            peticiones.setdefault(rid, {}).update({
                "status": resp.get("status"),
                "mime": resp.get("mimeType", ""),
                "tipo": params.get("type", "") or peticiones.get(rid, {}).get("tipo", ""),
            })

    return [dict(v, rid=k) for k, v in peticiones.items() if v.get("url")]


def es_candidata(p):
    url = (p.get("url") or "").lower()
    if not url.startswith("http") or any(b in url for b in BASURA):
        return False
    if "json" in (p.get("mime") or "").lower():
        return True
    if (p.get("tipo") or "").lower() in ("xhr", "fetch"):
        return True
    return PALABRA_CLAVE in url


def puntuar(p):
    """Mas alto = mas probable que sea LA API de datos."""
    url = (p.get("url") or "").lower()
    puntos = 0
    if PALABRA_CLAVE in url:
        puntos += 10
    if any(k in url for k in ("offset", "limit", "page", "scroll", "cursor")):
        puntos += 8                      # la señal mas fuerte: paginacion
    if "json" in (p.get("mime") or "").lower():
        puntos += 4
    if "/api" in url or "/v1" in url or "/v2" in url:
        puntos += 3
    if p.get("metodo") == "GET":
        puntos += 1
    return puntos


def cuerpo_respuesta(driver, rid, limite=1500):
    try:
        r = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
        return (r.get("body") or "")[:limite]
    except Exception:
        return ""


def presionar(driver, selector):
    """Dispara la accion que provoca la carga de datos."""
    for sel in (selector, "button[aria-expanded='false']"):
        try:
            for b in driver.find_elements(By.CSS_SELECTOR, sel):
                if b.is_displayed():
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", b)
                    time.sleep(0.4)
                    driver.execute_script("arguments[0].click();", b)
                    return True
        except Exception:
            continue
    return False


def main():
    print("=" * 70)
    print("  DESCUBRIDOR DE API")
    print("=" * 70)
    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(URL)
        print("-" * 70)
        print("  Inicia sesion y espera a ver los datos en pantalla.")
        print("-" * 70)
        input("\n>>> ENTER cuando los veas... ")

        # Vaciar: solo interesa lo que dispare la accion
        leer_peticiones(driver)
        log("Log limpiado. Provocando la carga...")

        if not presionar(driver, SELECTOR_BOTON):
            log("No se encontro el boton; recargando la pagina.")
            driver.refresh()

        log("Esperando la respuesta (8 s)...")
        time.sleep(8)

        peticiones = leer_peticiones(driver)
        candidatas = sorted(
            [p for p in peticiones if es_candidata(p)],
            key=puntuar, reverse=True,
        )
        log(f"Peticiones: {len(peticiones)}   candidatas: {len(candidatas)}")

        for p in candidatas[:5]:
            p["muestra"] = cuerpo_respuesta(driver, p["rid"])

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(BASE_DIR, f"api_encontrada_{sello}.txt")
        with open(ruta, "w", encoding="utf-8-sig") as f:
            f.write(f"DESCUBRIMIENTO DE API\n{datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Pagina: {URL}\nNO incluye cookies ni tokens.\n")
            f.write("=" * 70 + "\n\n")
            for i, p in enumerate(candidatas, 1):
                f.write(f"--- CANDIDATA {i} (puntaje {puntuar(p)}) ---\n")
                f.write(f"Metodo : {p.get('metodo')}\n")
                f.write(f"URL    : {p.get('url')}\n")
                f.write(f"Status : {p.get('status')}   MIME: {p.get('mime')}\n")
                if p.get("post"):
                    f.write(f"Cuerpo : {p['post']}\n")
                if p.get("muestra"):
                    f.write(f"Muestra:\n{p['muestra']}\n")
                f.write("\n")
            f.write("\n" + "=" * 70 + "\nTODAS LAS PETICIONES\n" + "=" * 70 + "\n")
            for p in peticiones:
                f.write(f"{p.get('metodo','?'):6} {str(p.get('status','?')):>4}  "
                        f"{p.get('url','')}\n")

        print()
        for i, p in enumerate(candidatas[:5], 1):
            print(f"  {i}. [{puntuar(p)}] {p.get('metodo')} {p.get('url')[:100]}")
        print(f"\n  Reporte: {ruta}")

    finally:
        input("\n>>> ENTER para cerrar... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

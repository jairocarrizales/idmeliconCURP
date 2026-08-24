# -*- coding: utf-8 -*-
"""
Espia la red de la Bandeja de soporte (casos PNR) para encontrar su API.

No adivina URLs: le pide a Chrome su propio registro de red mientras se
carga la pestaña PNR, y puntua las peticiones que parecen traer los datos.

    https://envios.adminml.com/logistics/case-center/cases
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

URL = "https://envios.adminml.com/logistics/case-center/cases"
DOMINIO = "envios.adminml.com"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(os.path.dirname(BASE_DIR), "1_finales",
                           "chrome_profile")

# Lo que nunca es la API que buscamos
RUIDO = (".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ico",
         ".gif", ".webp", ".map")
TELEMETRIA = ("google-analytics", "googletagmanager", "newrelic", "datadog",
              "melidata", "/metrics", "kaspersky", "doubleclick",
              "facebook.com", "hotjar", "sentry")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # Aqui esta la clave: pedirle a Chrome que registre la red
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    return webdriver.Chrome(options=opts)


def leer_red(driver):
    """Saca del log de Chrome las peticiones, emparejando ida y vuelta."""
    peticiones = {}
    for entrada in driver.get_log("performance"):
        try:
            msg = json.loads(entrada["message"])["message"]
        except Exception:
            continue
        metodo = msg.get("method", "")
        p = msg.get("params", {}) or {}
        rid = p.get("requestId")
        if not rid:
            continue

        if metodo == "Network.requestWillBeSent":
            req = p.get("request", {}) or {}
            peticiones.setdefault(rid, {})["url"] = req.get("url", "")
            peticiones[rid]["metodo"] = req.get("method", "")
            peticiones[rid]["postData"] = req.get("postData")
        elif metodo == "Network.responseReceived":
            resp = p.get("response", {}) or {}
            d = peticiones.setdefault(rid, {})
            d["status"] = resp.get("status")
            d["mime"] = resp.get("mimeType", "")
            d["tipo"] = p.get("type", "")
    return peticiones


def interesante(p):
    url = (p.get("url") or "").lower()
    if not url or DOMINIO not in url:
        return False
    if any(url.split("?")[0].endswith(x) for x in RUIDO):
        return False
    if any(x in url for x in TELEMETRIA):
        return False
    return True


def puntuar(p):
    """Que tan probable es que sea LA API de los casos."""
    url = (p.get("url") or "").lower()
    pts = 0
    for palabra, valor in (("case", 12), ("pnr", 12), ("claim", 8),
                           ("reclamo", 8), ("support", 5)):
        if palabra in url:
            pts += valor
    if any(k in url for k in ("offset", "limit", "page", "cursor", "size")):
        pts += 8
    if "json" in (p.get("mime") or ""):
        pts += 4
    if "/api" in url or "/v1" in url:
        pts += 3
    if p.get("tipo") in ("XHR", "Fetch"):
        pts += 3
    return pts


def cuerpo(driver, rid):
    try:
        r = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
        return r.get("body", "")
    except Exception as e:
        return f"(no se pudo leer: {e})"


def main():
    print("=" * 70)
    print("  ESPIA DE RED - Bandeja de soporte / casos PNR")
    print("=" * 70)

    driver = crear_driver()
    try:
        driver.get(URL)
        print("\n1) Si pide login, entra en Chrome.")
        print("2) Ponte en la pestaña PNR y espera a que salga la tabla.")
        input("\n   Cuando la tabla PNR este a la vista, ENTER aqui... ")

        # Vaciar: la carga inicial genera cientos de peticiones
        driver.get_log("performance")
        log("Log vaciado. Ahora recarga o cambia de pestaña PNR.")
        input("   Haz clic en 'Last Mile' y vuelve a 'PNR', luego ENTER... ")

        peticiones = leer_red(driver)
        candidatas = [(rid, p) for rid, p in peticiones.items()
                      if interesante(p)]
        candidatas.sort(key=lambda x: -puntuar(x[1]))

        log(f"{len(peticiones)} peticiones, {len(candidatas)} candidatas.")
        print("\n" + "=" * 70)
        print("  LAS 15 MEJORES")
        print("=" * 70)
        for rid, p in candidatas[:15]:
            print(f"\n[{puntuar(p):>3} pts] {p.get('metodo','?')} "
                  f"{p.get('status','?')} {p.get('mime','')}")
            print(f"  {p.get('url','')[:240]}")
            if p.get("postData"):
                print(f"  BODY: {str(p['postData'])[:400]}")

        print("\n" + "=" * 70)
        print("  CUERPO DE LAS 5 MEJORES")
        print("=" * 70)
        salida = []
        for rid, p in candidatas[:5]:
            b = cuerpo(driver, rid)
            print(f"\n--- {p.get('url','')[:200]}")
            print(b[:2500])
            salida.append({"url": p.get("url"), "metodo": p.get("metodo"),
                           "status": p.get("status"),
                           "postData": p.get("postData"),
                           "body": b})

        arch = os.path.join(BASE_DIR, "red_pnr.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        log(f"Guardado completo en {arch}")

    finally:
        input("\nENTER para cerrar Chrome... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Espia la red de Pedidos de vehiculos (capacidad) para encontrar su API.

    https://envios.adminml.com/logistics/travel-requests/last-mile

La pantalla trae estacion, tipo de vehiculo y el estado de cada pedido
(para responder, aceptado, expirado, rechazado, cancelado por MELI).
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(os.path.dirname(BASE_DIR), "1_finales",
                           "chrome_profile")

DOMINIO = "envios.adminml.com"

# El dia anterior, que es lo que se pide por defecto
_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
URL = ("https://envios.adminml.com/logistics/travel-requests/last-mile"
       f"?date_lteq={_ayer}T06%3A00%3A00.000Z"
       f"&date_gteq={_ayer}T06%3A00%3A00.000Z")

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
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    return webdriver.Chrome(options=opts)


def leer_red(driver):
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
            d = peticiones.setdefault(rid, {})
            d["url"] = req.get("url", "")
            d["metodo"] = req.get("method", "")
            d["postData"] = req.get("postData")
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
    url = (p.get("url") or "").lower()
    pts = 0
    for palabra, valor in (("travel", 12), ("request", 10), ("vehicle", 10),
                           ("capacity", 10), ("last-mile", 6), ("order", 4)):
        if palabra in url:
            pts += valor
    if any(k in url for k in ("offset", "limit", "page", "cursor", "size",
                              "date_", "from", "to")):
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
        r = driver.execute_cdp_cmd("Network.getResponseBody",
                                   {"requestId": rid})
        return r.get("body", "")
    except Exception as e:
        return f"(no se pudo leer: {e})"


def main():
    print("=" * 70)
    print("  ESPIA - Pedidos de vehiculos (capacidad)")
    print("=" * 70)
    driver = crear_driver()
    try:
        driver.get(URL)
        log("Esperando la pantalla (entra en Chrome si te lo pide)...")
        t0 = time.time()
        listo = False
        while time.time() - t0 < 3600:
            try:
                h = driver.page_source
                if ("Pedidos de veh" in h or "travel-request" in h
                        or "Para responder" in h):
                    listo = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not listo:
            log("No cargo la pantalla.")
            return

        log("Pantalla visible. Vaciando el log y recargando...")
        time.sleep(3)
        driver.get_log("performance")
        driver.get(URL)             # provocar las llamadas otra vez
        time.sleep(8)

        peticiones = leer_red(driver)
        cands = sorted([(r, p) for r, p in peticiones.items()
                        if interesante(p)], key=lambda x: -puntuar(x[1]))
        log(f"{len(peticiones)} peticiones, {len(cands)} candidatas.")

        print("\n" + "=" * 70)
        print("  LAS 15 MEJORES")
        print("=" * 70)
        for rid, p in cands[:15]:
            print(f"\n[{puntuar(p):>3}] {p.get('metodo','?')} "
                  f"{p.get('status','?')} {p.get('mime','')}")
            print(f"  {p.get('url','')[:260]}")
            if p.get("postData"):
                print(f"  BODY: {str(p['postData'])[:500]}")

        salida = []
        print("\n" + "=" * 70)
        print("  CUERPOS DE LAS 6 MEJORES")
        print("=" * 70)
        for rid, p in cands[:6]:
            b = cuerpo(driver, rid)
            print(f"\n--- {p.get('url','')[:200]}")
            print(b[:2500])
            salida.append({"url": p.get("url"), "metodo": p.get("metodo"),
                           "status": p.get("status"),
                           "postData": p.get("postData"), "body": b})

        arch = os.path.join(BASE_DIR, "red_capacidad.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        log(f"Guardado en {arch}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

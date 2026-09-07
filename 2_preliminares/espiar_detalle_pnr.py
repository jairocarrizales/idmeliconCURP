# -*- coding: utf-8 -*-
"""
Espia la red al abrir el DETALLE de un caso PNR.

El listado ya lo tenemos. Al hacer clic en un registro se abre la ficha
del caso, que trae mucho mas: datos del reclamo, evidencias, actividad.
Esto averigua que APIs se disparan ahi.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROY = os.path.dirname(BASE_DIR)
PROFILE_DIR = os.path.join(PROY, "1_finales", "chrome_profile")
sys.path.insert(0, os.path.join(PROY, "1_finales"))

URL = "https://envios.adminml.com/logistics/case-center/cases"
DOMINIO = "envios.adminml.com"

RUIDO = (".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ico",
         ".gif", ".webp", ".map")
TELEMETRIA = ("google-analytics", "googletagmanager", "newrelic", "datadog",
              "melidata", "/metrics", "kaspersky", "doubleclick",
              "facebook.com", "hotjar", "sentry")


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def crear_driver():
    opts = Options()
    opts.add_argument("--user-data-dir=%s" % PROFILE_DIR)
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


def cuerpo(driver, rid):
    try:
        r = driver.execute_cdp_cmd("Network.getResponseBody",
                                   {"requestId": rid})
        return r.get("body", "")
    except Exception as e:
        return "(no se pudo leer: %s)" % e


def main():
    print("=" * 70)
    print("  ESPIA - Detalle de un caso PNR")
    print("=" * 70)
    driver = crear_driver()
    try:
        driver.get(URL)
        log("Esperando la bandeja (entra en Chrome si te lo pide)...")
        t0 = time.time()
        listo = False
        while time.time() - t0 < 3600:
            try:
                h = driver.page_source
                if "case-data" in h or "LOGISTICS_PNR" in h:
                    listo = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not listo:
            log("No cargo la bandeja.")
            return

        log("Bandeja visible. Yendo a la pestana PNR...")
        time.sleep(3)
        from selenium.webdriver.common.by import By
        try:
            tab = driver.find_element(By.ID, "LOGISTICS_PNR")
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'})", tab)
            tab.click()
            time.sleep(5)
        except Exception as e:
            log("No se pudo cambiar a PNR (%s)" % e)

        # Vaciar el log: solo interesa lo que dispara el clic
        driver.get_log("performance")
        log("Log vaciado. Abriendo el primer caso...")

        # Hacer clic en la primera fila de la tabla
        abierto = False
        for sel in ("div.cases-table-row", "div.case-data-container",
                    "div[class*='case-data-line']", "tr[class*='case']"):
            try:
                filas = driver.find_elements(By.CSS_SELECTOR, sel)
                if filas:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'})",
                        filas[0])
                    time.sleep(1)
                    filas[0].click()
                    log("Clic en '%s'" % sel)
                    abierto = True
                    break
            except Exception:
                continue

        if not abierto:
            log("No se pudo hacer clic. Abre TU un caso a mano.")
            log("Tienes 90 segundos; yo leo la red cuando termine.")
            time.sleep(90)
        else:
            time.sleep(9)

        log("URL actual: %s" % (driver.current_url or "")[:180])

        peticiones = leer_red(driver)
        cands = [(r, p) for r, p in peticiones.items() if interesante(p)]
        log("%d peticiones, %d candidatas." % (len(peticiones), len(cands)))

        print("\n" + "=" * 70)
        print("  TODO LO QUE SE PIDIO AL ABRIR EL DETALLE")
        print("=" * 70)
        for rid, p in cands:
            print("\n%s %s %s" % (p.get("metodo", "?"), p.get("status", "?"),
                                  p.get("mime", "")))
            print("  %s" % (p.get("url", "")[:250]))
            if p.get("postData"):
                print("  BODY: %s" % str(p["postData"])[:400])

        salida = []
        print("\n" + "=" * 70)
        print("  CUERPOS")
        print("=" * 70)
        for rid, p in cands:
            if "json" not in (p.get("mime") or ""):
                continue
            b = cuerpo(driver, rid)
            print("\n--- %s" % (p.get("url", "")[:190]))
            print(b[:3000])
            salida.append({"url": p.get("url"), "metodo": p.get("metodo"),
                           "status": p.get("status"),
                           "postData": p.get("postData"), "body": b})

        arch = os.path.join(BASE_DIR, "red_detalle_pnr.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        log("Guardado en %s" % arch)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Pide las APIs de monitoreo y busca coordenadas dentro.

El explorador anterior encontro cuatro APIs con pinta de geo pero no
miro que devuelven. Esto las llama de verdad, revisa si traen latitud y
longitud, y de paso saca un id de ruta para abrir por fin la ficha.
"""
import os
import re
import sys
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PROY = r"C:\ProyectosBDB\meliusuarios"
BASE_DIR = os.path.join(PROY, "2_preliminares")
PROFILE_DIR = os.path.join(PROY, "1_finales", "chrome_profile")
RAIZ = "https://envios.adminml.com"
PANEL = RAIZ + "/logistics/monitoring-distribution"

_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

SCRIPT = """
const url = arguments[0], metodo = arguments[1], cuerpo = arguments[2];
const done = arguments[arguments.length - 1];
const op = {credentials: 'include', method: metodo,
            headers: {'Accept': 'application/json'}};
if (metodo === 'POST') {
  op.headers['Content-Type'] = 'application/json';
  op.body = cuerpo || '{}';
}
fetch(url, op)
  .then(r => r.text().then(t => done({status: r.status, largo: t.length,
                                      body: t.slice(0, 300000)})))
  .catch(e => done({status: 0, body: String(e), largo: 0}));
"""

# Lo que buscamos dentro de cada respuesta
PISTAS = [
    (r'"lat(?:itude)?"\s*:\s*(-?\d+\.\d+)', "latitud"),
    (r'"l(?:ng|on|ongitude)"\s*:\s*(-?\d+\.\d+)', "longitud"),
    (r'"coordinates"\s*:', "coordinates"),
    (r'"geometry"\s*:', "geometry"),
    (r'"polyline"|"encodedPath"', "polyline"),
    (r'"waypoints?"\s*:', "waypoints"),
    (r'"stops?"\s*:\s*\[', "stops"),
    (r'"address"\s*:', "address"),
    (r'"destination"\s*:', "destination"),
]


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def crear():
    o = Options()
    o.add_argument("--user-data-dir=%s" % PROFILE_DIR)
    o.add_argument("--profile-directory=Default")
    o.add_argument("--start-maximized")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=o)


def pedir(d, url, metodo="GET", cuerpo=None):
    d.set_script_timeout(90)
    try:
        return d.execute_async_script(SCRIPT, url, metodo, cuerpo)
    except Exception as e:
        return {"status": 0, "body": str(e)[:200], "largo": 0}


def revisar(nombre, r):
    """Dice si la respuesta trae coordenadas y muestra una muestra."""
    est = r.get("status")
    cuerpo = r.get("body") or ""
    print("\n  %s" % nombre)
    print("     HTTP %s, %d caracteres" % (est, r.get("largo", 0)))
    if est != 200 or not cuerpo:
        print("     %s" % cuerpo[:160])
        return {}
    hallado = {}
    for patron, que in PISTAS:
        n = len(re.findall(patron, cuerpo, re.I))
        if n:
            hallado[que] = n
    if hallado:
        print("     GEO: %s" % hallado)
        # Mostrar el primer trozo con coordenadas
        m = re.search(r'"lat(?:itude)?"\s*:\s*-?\d+\.\d+', cuerpo, re.I)
        if m:
            i = m.start()
            print("     %s" % cuerpo[max(0, i - 200):i + 260]
                  .replace("\n", " ")[:420])
    else:
        print("     sin coordenadas")
        print("     %s" % cuerpo[:260].replace("\n", " "))
    return hallado


def main():
    print("=" * 68)
    print("  SONDEO DE LAS APIS DE MONITOREO")
    print("=" * 68)
    d = crear()
    try:
        d.get(PANEL)
        log("Esperando que entres...")
        # Igual que el explorador: la senal fiable es que el panel
        # responda JSON, no que el HTML sea grande.
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                if "login" not in u and "adminml.com/logistics" in u:
                    r = pedir(d, RAIZ + "/logistics/api/monitoring/"
                                        "get-routes-list?limit=1", "POST",
                              json.dumps({"limit": 1}))
                    if r.get("status") in (200, 400, 422):
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion.")
            return
        log("Sesion lista.")

        guardado = {}

        print("\n" + "=" * 68)
        print("  1) LAS APIS DE MONITOREO")
        print("=" * 68)
        # get-routes-list es la mas prometedora: la lista de rutas del
        # dia, que podria traer las paradas de cada una.
        for nombre, url, metodo, cuerpo in [
            ("get-routes-list (GET)",
             RAIZ + "/logistics/api/monitoring/get-routes-list", "GET", None),
            ("get-routes-list (POST)",
             RAIZ + "/logistics/api/monitoring/get-routes-list", "POST",
             json.dumps({"date": _ayer, "limit": 20})),
            ("get-routes-metrics-summaries",
             RAIZ + "/logistics/api/monitoring/get-routes-metrics-summaries",
             "POST", json.dumps({"date": _ayer})),
            ("get-routes-warnings-summaries",
             RAIZ + "/logistics/api/monitoring/get-routes-warnings-summaries",
             "POST", json.dumps({"date": _ayer})),
        ]:
            r = pedir(d, url, metodo, cuerpo)
            g = revisar(nombre, r)
            if r.get("status") == 200:
                guardado[nombre] = {"url": url, "metodo": metodo,
                                    "geo": g, "body": (r.get("body") or "")[:60000]}

        # 2) Un id de ruta, de la fuente natural
        print("\n" + "=" * 68)
        print("  2) UN ID DE RUTA")
        print("=" * 68)
        ruta_id = ""
        for clave, dat in guardado.items():
            ids = re.findall(r'"(?:route_?id|id)"\s*:\s*"?(\d{8,10})"?',
                             dat.get("body") or "")
            if ids:
                ruta_id = ids[0]
                print("     %s -> %s" % (clave, ruta_id))
                break
        if not ruta_id:
            # De la propia pantalla
            ids = re.findall(r"\b1[45]\d{7}\b", d.page_source)
            if ids:
                ruta_id = ids[0]
                print("     de la pantalla -> %s" % ruta_id)
        if not ruta_id:
            print("     (no se hallo ninguno)")

        # 3) La ficha de la ruta: nunca se ha probado
        if ruta_id:
            print("\n" + "=" * 68)
            print("  3) LA FICHA DE LA RUTA %s" % ruta_id)
            print("=" * 68)
            url = RAIZ + "/logistics/monitoring-distribution/detail/%s" % ruta_id
            d.get(url)
            time.sleep(8)
            html = d.page_source
            print("     HTML: %d caracteres" % len(html))
            hallado = {}
            for patron, que in PISTAS:
                n = len(re.findall(patron, html, re.I))
                if n:
                    hallado[que] = n
            print("     GEO en el HTML: %s" % (hallado or "ninguna"))
            for patron, que in PISTAS[:2]:
                m = re.search(patron, html, re.I)
                if m:
                    i = m.start()
                    print("\n     %s:" % que)
                    print("     %s" % html[max(0, i - 250):i + 300]
                          .replace("\n", " ")[:520])
                    break
            # Y si hay mapa dibujado
            mapa = d.execute_script("""
              return {canvas: document.querySelectorAll('canvas').length,
                      google: !!(window.google && window.google.maps),
                      leaflet: !!window.L,
                      mapbox: !!window.mapboxgl};
            """)
            print("\n     Mapa dibujado: %s" % mapa)
            guardado["ficha_ruta"] = {"url": url, "geo": hallado,
                                      "mapa": mapa}

        arch = os.path.join(BASE_DIR, "geo.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(guardado, f, ensure_ascii=False, indent=2)
        log("Guardado en %s" % arch)

        print("\n" + "=" * 68)
        print("  RESUMEN")
        print("=" * 68)
        for k, v in guardado.items():
            g = v.get("geo") or {}
            print("  %-32s %s" % (k, g if g else "sin coordenadas"))
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

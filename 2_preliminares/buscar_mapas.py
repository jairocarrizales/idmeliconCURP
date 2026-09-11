# -*- coding: utf-8 -*-
"""
Busca mapas y coordenadas en el panel de Mercado Libre.

Recorre las pantallas conocidas y en cada una mira tres cosas:
  1. Si hay un mapa dibujado (canvas, Google Maps, Leaflet, Mapbox)
  2. Si el HTML trae coordenadas (latitud/longitud)
  3. Que APIs se piden, por si alguna devuelve la geometria de la ruta

No adivina URLs: usa las que ya conocemos de los otros extractores, y
espia el trafico real de cada una.
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
DOM = "envios.adminml.com"

RUIDO = (".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ico",
         ".gif", ".webp", ".map")
TELE = ("google-analytics", "googletagmanager", "newrelic", "datadog",
        "melidata", "/metrics", "kaspersky", "doubleclick", "hotjar")

_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Las pantallas que ya conocemos de los otros extractores
PANTALLAS = [
    ("Monitoreo de distribucion",
     "https://envios.adminml.com/logistics/monitoring-distribution"),
    ("Pedidos de vehiculos",
     "https://envios.adminml.com/logistics/travel-requests/last-mile"
     "?date_lteq=%sT06%%3A00%%3A00.000Z&date_gteq=%sT06%%3A00%%3A00.000Z"
     % (_ayer, _ayer)),
    ("Bandeja de soporte",
     "https://envios.adminml.com/logistics/case-center/cases"),
    ("Conductores",
     "https://envios.adminml.com/logistics/provider-management/drivers"),
]


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def crear():
    o = Options()
    o.add_argument("--user-data-dir=%s" % PROFILE_DIR)
    o.add_argument("--profile-directory=Default")
    o.add_argument("--start-maximized")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    o.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    return webdriver.Chrome(options=o)


def leer_red(d):
    pet = {}
    for e in d.get_log("performance"):
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        p = m.get("params", {}) or {}
        rid = p.get("requestId")
        if not rid:
            continue
        if m.get("method") == "Network.requestWillBeSent":
            rq = p.get("request", {}) or {}
            x = pet.setdefault(rid, {})
            x["url"] = rq.get("url", "")
            x["metodo"] = rq.get("method", "")
        elif m.get("method") == "Network.responseReceived":
            rs = p.get("response", {}) or {}
            x = pet.setdefault(rid, {})
            x["status"] = rs.get("status")
            x["mime"] = rs.get("mimeType", "")
    return pet


def util(p):
    u = (p.get("url") or "").lower()
    if not u:
        return False
    # Las de mapas pueden ser de otro dominio (googleapis, mapbox)
    if DOM not in u and not any(x in u for x in
                                ("maps", "mapbox", "tile", "geo")):
        return False
    if any(u.split("?")[0].endswith(x) for x in RUIDO):
        return False
    return not any(x in u for x in TELE)


def recolectar(d, segundos):
    """El log se vacia al leerlo: hay que leerlo varias veces."""
    todas = {}
    fin = time.time() + segundos
    while time.time() < fin:
        for rid, p in leer_red(d).items():
            if util(p):
                todas.setdefault(rid, p)
        time.sleep(1.0)
    return todas


def revisar(d, nombre, url, segundos=12):
    print("\n" + "=" * 68)
    print("  %s" % nombre)
    print("  %s" % url[:110])
    print("=" * 68)
    d.get_log("performance")
    try:
        d.get(url)
    except Exception as e:
        print("   no cargo: %s" % str(e)[:120])
        return {}
    todas = recolectar(d, segundos)

    # 1) Hay un mapa dibujado?
    mapa = d.execute_script("""
      const out = {};
      out.canvas = document.querySelectorAll('canvas').length;
      out.googleMaps = !!(window.google && window.google.maps);
      out.leaflet = !!window.L || !!document.querySelector('.leaflet-container');
      out.mapbox = !!window.mapboxgl;
      const sel = ['[class*=map]', '[id*=map]', '[data-testid*=map]'];
      out.contenedores = [];
      for (const s of sel) {
        document.querySelectorAll(s).forEach(el => {
          const c = (el.className || '').toString();
          if (c && out.contenedores.length < 8 && /map|mapa/i.test(c))
            out.contenedores.push(c.slice(0, 60));
        });
      }
      return out;
    """)
    print("\n  --- Mapa en la pantalla ---")
    for k, v in mapa.items():
        if v:
            print("     %-14s %s" % (k, v))
    if not any(mapa.values()):
        print("     (ninguno)")

    # 2) Coordenadas en el HTML
    html = d.page_source
    print("\n  --- Coordenadas en el HTML ---")
    patrones = [
        (r'"lat(?:itude)?"\s*:\s*(-?\d+\.\d+)', "latitude"),
        (r'"lng"|"lon(?:gitude)?"\s*:\s*(-?\d+\.\d+)', "longitude"),
        (r'"geometry"', "geometry"),
        (r'"coordinates"', "coordinates"),
        (r'"polyline"|"encodedPath"', "polyline"),
        (r'"waypoints?"', "waypoints"),
        (r'"stops?"\s*:\s*\[', "stops"),
    ]
    hallado = False
    for patron, que in patrones:
        n = len(re.findall(patron, html, re.I))
        if n:
            hallado = True
            print("     %-14s x%d" % (que, n))
            m = re.search(patron, html, re.I)
            i = m.start()
            print("        %s" % html[max(0, i - 90):i + 160]
                  .replace("\n", " ")[:250])
    if not hallado:
        print("     (ninguna)")

    # 3) Las APIs que se pidieron
    # Un panel abierto pide varias APIs para dibujarse. Si solo hubo una,
    # lo que se cargo no era el panel: casi siempre, la pagina de login.
    if len(todas) <= 1:
        print("\n  !! Solo %d peticion: la pantalla NO cargo de verdad."
              % len(todas))
        print("     Lo que sigue no dice nada sobre si hay mapas.")
    print("\n  --- APIs (%d) ---" % len(todas))
    interesantes = []
    for rid, p in sorted(todas.items(), key=lambda x: x[1].get("url", "")):
        u = p.get("url", "")
        marca = ""
        if re.search(r"geo|map|coord|route|stop|track|polyline|location", u, re.I):
            marca = "   <<< geo"
            interesantes.append(p)
        if "json" in (p.get("mime") or "") or marca:
            print("     %s %s %s%s" % (p.get("metodo", "?"),
                                       p.get("status", "?"), u[:120], marca))
    return {"mapa": mapa, "apis": [p.get("url") for p in interesantes]}


def main():
    print("=" * 68)
    print("  BUSCANDO MAPAS EN EL PANEL")
    print("=" * 68)
    d = crear()
    try:
        d.get("https://envios.adminml.com/logistics/monitoring-distribution")
        log("Esperando que entres (si te lo pide)...")
        # Que el HTML sea grande no basta: la pagina de login tambien lo
        # es, y por eso dos intentos anteriores recorrieron las pantallas
        # sin estar dentro. La senal fiable es que el panel PIDA datos:
        # una pantalla abierta dispara varias APIs; el login, ninguna.
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                if "login" not in u and "adminml.com/logistics" in u:
                    d.get_log("performance")
                    d.refresh()
                    time.sleep(6)
                    apis = [p for p in leer_red(d).values()
                            if util(p) and "json" in (p.get("mime") or "")]
                    if len(apis) >= 2:
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion: el panel no pidio datos.")
            log("Revisa que entraste y vuelve a correrlo.")
            return
        time.sleep(3)
        log("Sesion lista (el panel respondio). Revisando pantallas...")

        resumen = {}
        for nombre, url in PANTALLAS:
            resumen[nombre] = revisar(d, nombre, url)

        # La ficha de una ruta concreta: la mas probable
        print("\n" + "=" * 68)
        print("  LA FICHA DE UNA RUTA (la mas probable)")
        print("=" * 68)
        ids = re.findall(r"\b15\d{7}\b", d.page_source)
        ruta_id = ids[0] if ids else ""
        if not ruta_id:
            # Pedirselo al propio panel: el reporte de operacion de ayer
            # trae el id de cada ruta. No depende de que haya un CSV
            # viejo en la carpeta.
            log("Buscando un id de ruta en el reporte de ayer...")
            try:
                r = d.execute_async_script("""
                  const url = arguments[0];
                  const done = arguments[arguments.length - 1];
                  fetch(url, {credentials: 'include'})
                    .then(r => r.text().then(t => done(t.slice(0, 400000))))
                    .catch(e => done(''));
                """, "https://envios.adminml.com/api/carriers/reports"
                     "?mile=LM&init_date=%s&end_date=%s&report_type=carrier"
                     % (_ayer, _ayer))
                hallados = re.findall(r"\b15\d{7}\b", r or "")
                if hallados:
                    ruta_id = hallados[0]
            except Exception as e:
                log("no se pudo: %s" % str(e)[:90])
        if ruta_id:
            log("Usando la ruta %s" % ruta_id)
            resumen["Ficha de ruta"] = revisar(
                d, "Ficha de la ruta %s" % ruta_id,
                "https://envios.adminml.com/logistics/"
                "monitoring-distribution/detail/%s" % ruta_id, 14)
        else:
            print("   (no encontre un id de ruta para probar)")

        print("\n" + "=" * 68)
        print("  RESUMEN")
        print("=" * 68)
        for nombre, r in resumen.items():
            m = r.get("mapa") or {}
            tiene = any(m.values())
            apis = r.get("apis") or []
            print("  %-30s mapa=%s  apis-geo=%d" % (
                nombre, "SI" if tiene else "no", len(apis)))
            for a in apis[:4]:
                print("        %s" % a[:110])

        with open(os.path.join(BASE_DIR, "mapas.json"), "w",
                  encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2)
        log("Guardado en mapas.json")
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

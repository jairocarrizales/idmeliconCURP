# -*- coding: utf-8 -*-
"""
Captura la estructura completa de las paradas de una ruta.

El sondeo encontro 370 coordenadas en la ficha, pero solo vi una muestra
de 420 caracteres. Antes de escribir el extractor hay que saber como se
llama cada campo de verdad: inventarlos fue lo que hizo fallar las APIs
de monitoreo con 404 y 422.
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
DETALLE = RAIZ + "/logistics/monitoring-distribution/detail/"
RUTA = "155197401"          # la de la captura: B3_AM2, 116 paradas

_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def crear():
    o = Options()
    o.add_argument("--user-data-dir=%s" % PROFILE_DIR)
    o.add_argument("--profile-directory=Default")
    o.add_argument("--start-maximized")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=o)


def recortar(texto, clave, abre="{", cierra="}"):
    """El objeto que sigue a "clave": contando llaves.

    Respeta las que van dentro de un texto, o cortaria a mitad. Es el
    mismo metodo que ya funciona con caseDetail en el extractor de PNR.
    """
    marca = '"%s":' % clave
    i = texto.find(marca)
    if i < 0:
        return None
    try:
        ini = texto.index(abre, i + len(marca))
    except ValueError:
        return None
    prof, en_texto, escapado = 0, False, False
    for j in range(ini, len(texto)):
        c = texto[j]
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
            continue
        if c == '"':
            en_texto = not en_texto
            continue
        if en_texto:
            continue
        if c == abre:
            prof += 1
        elif c == cierra:
            prof -= 1
            if prof == 0:
                return texto[ini:j + 1]
    return None


def main():
    print("=" * 68)
    print("  ESTRUCTURA DE LAS PARADAS")
    print("=" * 68)
    d = crear()
    try:
        d.get(DETALLE + RUTA)
        log("Esperando que entres...")
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                h = d.page_source
                if ("login" not in u and "monitoring-distribution" in u
                        and '"latitude"' in h):
                    dentro = True
                    break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion o la ficha no cargo.")
            return
        log("Ficha cargada.")
        time.sleep(3)
        html = d.page_source
        print("  HTML: %d caracteres" % len(html))

        # 1) Donde vive el arreglo de paradas
        print("\n" + "=" * 68)
        print("  1) DONDE ESTAN LAS PARADAS")
        print("=" * 68)
        for clave in ("stops", "routeStops", "points", "visits",
                      "deliveryStops", "zones", "sections"):
            n = len(re.findall(r'"%s"\s*:' % clave, html))
            if n:
                print("     \"%s\": aparece %d veces" % (clave, n))

        # 2) Una parada entera
        print("\n" + "=" * 68)
        print("  2) UNA PARADA COMPLETA")
        print("=" * 68)
        # Retroceder desde la primera latitud hasta el { que la abre
        m = re.search(r'"latitude"\s*:\s*-?\d+\.\d+', html)
        if m:
            i = m.start()
            # Subir hasta encontrar el inicio del objeto parada
            trozo = html[max(0, i - 4000):i + 4000]
            p = trozo.find('"stopAddress"')
            if p < 0:
                p = trozo.find('"address"')
            print(trozo[max(0, p - 1500):p + 2500][:3800])

        # 3) El arreglo de paradas, para contarlas y ver sus campos
        print("\n" + "=" * 68)
        print("  3) CAMPOS DE CADA PARADA")
        print("=" * 68)
        crudo = recortar(html, "stops", "[", "]")
        if crudo:
            print("     bloque \"stops\": %d caracteres" % len(crudo))
            try:
                paradas = json.loads(crudo)
                print("     %d paradas" % len(paradas))
                if paradas:
                    print("\n     campos de la primera:")
                    for k, v in paradas[0].items():
                        s = json.dumps(v, ensure_ascii=False)
                        print("       %-24s %s" % (k, s[:90]))
                    with open(os.path.join(BASE_DIR, "paradas.json"), "w",
                              encoding="utf-8") as f:
                        json.dump(paradas, f, ensure_ascii=False, indent=1)
                    log("Guardadas en paradas.json")
            except ValueError as e:
                print("     no parsea: %s" % str(e)[:120])
                print("     %s" % crudo[:600])
        else:
            print("     no se hallo el bloque \"stops\"")

        # 4) El nombre y los datos de la ruta
        print("\n" + "=" * 68)
        print("  4) DATOS DE LA RUTA")
        print("=" * 68)
        for clave in ("routeName", "route_name", "driverName", "zoneName",
                      "plannedRoute", "routeId", "shift"):
            m2 = re.search(r'"%s"\s*:\s*("[^"]{0,60}"|\d+)' % clave, html)
            if m2:
                print("     %-16s %s" % (clave, m2.group(1)))

        # 5) El trazo planificado (la capa "Ruta planificada")
        print("\n" + "=" * 68)
        print("  5) EL TRAZO PLANIFICADO")
        print("=" * 68)
        for clave in ("polyline", "encodedPath", "plannedPath", "geometry",
                      "coordinates", "path"):
            n = len(re.findall(r'"%s"\s*:' % clave, html))
            if n:
                print("     \"%s\" x%d" % (clave, n))
                m3 = re.search(r'"%s"\s*:' % clave, html)
                i3 = m3.start()
                print("        %s" % html[i3:i3 + 280].replace("\n", " "))
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Extractor de paradas - Mercado Libre

Cada ruta del monitoreo tiene su ficha:

    https://envios.adminml.com/logistics/monitoring-distribution/detail/<id>

Ahi el panel dibuja un mapa con las paradas numeradas. El mapa lo pinta
Leaflet en el navegador, asi que no hay imagen que descargar; lo que si
esta son los datos con los que lo dibuja: cada parada con su direccion,
sus coordenadas, su orden de visita y como termino.

La ficha NO pide esos datos a ninguna API: vienen dentro del HTML, en un
arreglo "stops". Se recorta contando llaves, igual que el caseDetail del
extractor de PNR.

Salida: un CSV para Excel y un KML para abrir en Google Earth o My Maps.
"""

import os
import re
import sys
import csv
import json
import time
import base64
from datetime import datetime, timedelta

# El arranque de Chrome, la llamada con sesion y el lector de XLSX ya
# estan resueltos y probados en el extractor de rutas. Se reusan en vez
# de duplicarlos: los mismos errores se arreglan en un solo sitio.
from extraer_rutas import (crear_driver, llamar, leer_xlsx, limpiar,
                           indice_de, API_REPORTE, log)

RAIZ = "https://envios.adminml.com"
DETALLE = RAIZ + "/logistics/monitoring-distribution/detail/"
DOMINIO = "envios.adminml.com"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cuantas fichas se piden a la vez. Cada una pesa ~2.7 MB de HTML, asi
# que el lote va corto: con el extractor de rutas, devolver el HTML
# entero de muchas fichas agoto la memoria de Chrome.
LOTE = 4
PAUSA = 0.3
REINTENTOS = 2
# Cada cuantas fichas se recarga en blanco para que Chrome suelte lo
# acumulado. Mismo remedio que en el extractor de rutas.
DESCANSO_CADA = 60

# Como se lee el estado de cada parada
ESTADOS = {
    "complete": "Exitosa",
    "incomplete": "Fallida",
    "pending": "Pendiente",
    "canceled": "Cancelada",
    "cancelled": "Cancelada",
}

# El color del pin en el KML, segun como termino la parada
COLORES = {
    "Exitosa": "ff2ba34c",      # verde
    "Fallida": "ff4f3df2",      # rojo
    "Pendiente": "ffaaaaaa",    # gris
    "Cancelada": "ff000000",
}


def ayer():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def preparar_pagina(driver, dia=None):
    """Deja al navegador en el panel, o el fetch lo bloquea el origen."""
    for pestana in driver.window_handles:
        driver.switch_to.window(pestana)
        if DOMINIO in (driver.current_url or ""):
            break
    if DOMINIO not in (driver.current_url or ""):
        driver.get(RAIZ + "/logistics/monitoring-distribution")
        time.sleep(3)


def rutas_del_dia(driver, dia):
    """Los ID de ruta de un dia, del reporte de operacion.

    Es el mismo reporte que usa el extractor de rutas, asi que no hay
    que adivinar ninguna URL nueva.
    """
    url = (f"{API_REPORTE}?mile=LM&init_date={dia}"
           f"&end_date={dia}&report_type=carrier")
    r = llamar(driver, url, binario=True)
    # Dos fallos distintos con soluciones distintas: si el status no es
    # 200 la sesion se cayo; si es 200 pero sin archivo, ese dia todavia
    # no tiene reporte (de madrugada aun no existe el del dia en curso).
    if r.get("status") != 200:
        raise RuntimeError(
            f"El reporte del {dia} respondio {r.get('status')}. "
            "Revisa que la sesion siga activa.")
    if not r.get("b64"):
        raise RuntimeError(
            f"Mercado Libre todavia no publica el reporte del {dia}. "
            "Si es el dia en curso, hay que esperar a que arranque la "
            "operacion.")
    cab, filas = leer_xlsx(base64.b64decode(r["b64"]))
    if not cab:
        return []

    # La columna del id de ruta, por nombre y no por posicion. El XLSX
    # la llama "Id de la ruta"; los nombres con guion bajo son los de
    # salida del extractor de rutas y aqui no existen.
    idx = indice_de(cab, "id de la ruta", "id_ruta", "id ruta")
    if idx is None:
        # Alguna columna cuyos valores parezcan id de ruta
        for i, _ in enumerate(cab):
            muestra = [f[i] for f in filas[:5] if i < len(f)]
            if muestra and all(re.fullmatch(r"1[45]\d{7}", str(x) or "")
                               for x in muestra):
                idx = i
                break
    if idx is None:
        raise RuntimeError("El reporte no trae la columna del id de ruta.")

    # El conductor y el centro, para el CSV. Los nombres son los que el
    # XLSX trae de verdad, leidos de su cabecera: no los de salida del
    # extractor de rutas ni los que uno supondria. Adivinarlos dejo
    # estas dos columnas vacias en 14.238 filas.
    i_drv = indice_de(cab, "nombre del transportista", "transportista")
    i_ced = indice_de(cab, "service center", "centro")
    # El nombre de la ruta (B3_AM2) no viene en el reporte: solo esta en
    # la ficha, y de ahi lo saca pedir_lote().
    i_ruta = None

    salida, vistos = [], set()
    for f in filas:
        if idx >= len(f):
            continue
        rid = limpiar(f[idx])
        if not rid or rid in vistos:
            continue
        vistos.add(rid)
        salida.append({
            "id_ruta": rid,
            "ruta": limpiar(f[i_ruta]) if i_ruta is not None and i_ruta < len(f) else "",
            "driver": limpiar(f[i_drv]) if i_drv is not None and i_drv < len(f) else "",
            "cedis": limpiar(f[i_ced]) if i_ced is not None and i_ced < len(f) else "",
        })
    return salida


SCRIPT_LOTE = """
const base = arguments[0];
const ids  = arguments[1];
const done = arguments[arguments.length - 1];

// Recorta el objeto o arreglo que sigue a "clave": contando llaves.
// Respeta las que van dentro de un texto, o cortaria a mitad.
function recortar(t, clave, abre, cierra) {
  const marca = '"' + clave + '":';
  const i = t.indexOf(marca);
  if (i < 0) return null;
  let ini = t.indexOf(abre, i + marca.length);
  if (ini < 0) return null;
  let prof = 0, enTexto = false, escapado = false;
  for (let j = ini; j < t.length; j++) {
    const c = t[j];
    if (escapado) { escapado = false; continue; }
    // La barra invertida se compara por su codigo (92): escribirla como
    // literal obliga a escaparla dos veces (Python y JavaScript) y es
    // facil dejarla mal, lo que rompe el script entero.
    if (c.charCodeAt(0) === 92) { escapado = true; continue; }
    if (c === '"') { enTexto = !enTexto; continue; }
    if (enTexto) continue;
    if (c === abre) prof++;
    else if (c === cierra) { prof--; if (prof === 0) return t.substring(ini, j + 1); }
  }
  return null;
}

Promise.all(ids.map(id =>
  fetch(base + id, {credentials: 'include'})
    .then(r => r.ok ? r.text() : null)
    .then(t => {
      if (!t) return {id: id, ok: false, stops: null};
      // El recorte se hace aqui: cada ficha pesa ~2.7 MB y traerlas
      // enteras a Python agotaria la memoria de Chrome.
      const stops = recortar(t, 'stops', '[', ']');
      // El nombre de la ruta y el conductor, de paso. Se prueban tres
      // formas, como hace el extractor de rutas: con una sola regex el
      // nombre vino vacio en las 168 fichas de la prueba.
      let nombre = '', driver = '';
      let m = t.match(/Ruta\\s+([A-Z0-9]{1,4}_[A-Z0-9_]{2,14})/);
      if (m) nombre = m[1];
      if (!nombre) {
        m = t.match(/"routeName"\\s*:\\s*"([^"]{1,40})"/);
        if (m) nombre = m[1];
      }
      if (!nombre) {
        m = t.match(/>\\s*([A-Z]{1,4}\\d{0,3}_[A-Z0-9_]{2,14})\\s*</);
        if (m) nombre = m[1];
      }
      m = t.match(/"driverName"\\s*:\\s*"([^"]{1,60})"/);
      if (m) driver = m[1];
      t = null;
      return {id: id, ok: !!stops, stops: stops,
              nombre: nombre, driver: driver};
    })
    .catch(() => ({id: id, ok: false, stops: null}))
)).then(done);
"""


def pedir_lote(driver, ids):
    """Pide varias fichas a la vez y devuelve {id: {stops, nombre, driver}}."""
    driver.set_script_timeout(240)
    respuestas = driver.execute_async_script(SCRIPT_LOTE, DETALLE,
                                             [str(i) for i in ids])
    salida = {}
    for r in respuestas or []:
        if not r or not r.get("ok") or not r.get("stops"):
            continue
        try:
            paradas = json.loads(r["stops"])
        except ValueError:
            continue
        salida[str(r.get("id"))] = {
            "paradas": paradas,
            "nombre": limpiar(r.get("nombre")),
            "driver": limpiar(r.get("driver")),
        }
    return salida


def _liberar_memoria(driver):
    """Recarga en blanco para que Chrome suelte lo acumulado."""
    try:
        actual = driver.current_url
        driver.get("about:blank")
        time.sleep(1.5)
        driver.get(actual)
        time.sleep(2.5)
    except Exception:
        pass


def normalizar(parada, ruta):
    """Una parada de la ficha convertida en fila plana."""
    dir_ = parada.get("address") or {}
    if not isinstance(dir_, dict):
        dir_ = {}
    lat = dir_.get("latitude")
    lon = dir_.get("longitude")

    # El tipo de domicilio, como lo muestra el panel
    if parada.get("addressTypeResidential"):
        tipo = "Residencial"
    elif parada.get("addressTypeBusiness"):
        tipo = "Comercial"
    else:
        tipo = ""

    est = limpiar(parada.get("status"))
    unidades = parada.get("transportUnitsAmount") or {}
    if not isinstance(unidades, dict):
        unidades = {}

    return {
        "fecha": ruta.get("fecha", ""),
        "cedis": ruta.get("cedis", ""),
        "id_ruta": ruta.get("id_ruta", ""),
        "ruta": ruta.get("ruta", ""),
        "driver": ruta.get("driver", ""),
        "secuencia": limpiar(parada.get("sequence")),
        "direccion": limpiar(parada.get("stopAddress")),
        "latitud": "" if lat is None else str(lat),
        "longitud": "" if lon is None else str(lon),
        "estado": ESTADOS.get(est, est),
        "paquetes": limpiar(parada.get("ordersAmount")),
        "envios": limpiar(unidades.get("shipments")),
        "sacas": limpiar(unidades.get("bags")),
        "tipo_domicilio": tipo,
        "precision": limpiar(dir_.get("geolocationType")),
        "id_parada": limpiar(parada.get("id")),
        "fuera_de_rango": "Si" if parada.get("outRangeDelivery") else "",
    }


def extraer_dia(driver, dia=None, avisar=None):
    """Todas las paradas de todas las rutas de un dia."""
    dia = dia or ayer()
    avisar = avisar or (lambda *a: None)
    preparar_pagina(driver, dia)

    log(f"Pidiendo las rutas del {dia}...")
    rutas = rutas_del_dia(driver, dia)
    if not rutas:
        log(f"El {dia} no tiene rutas.")
        return []
    log(f"{len(rutas)} rutas. Abriendo su ficha...")
    avisar(f"{len(rutas)} rutas")

    por_id = {r["id_ruta"]: r for r in rutas}
    for r in rutas:
        r["fecha"] = f"{dia[8:10]}/{dia[5:7]}/{dia[0:4]}"

    registros = []
    faltan = list(por_id.keys())
    hechas = 0

    for vuelta in range(REINTENTOS + 1):
        if not faltan:
            break
        tam = max(2, LOTE // (vuelta + 1))
        pausa = PAUSA * (vuelta + 1)
        if vuelta:
            log(f"Reintento {vuelta}: {len(faltan)} fichas en lotes de {tam}")

        pendientes, faltan = faltan, []
        fallo_dicho = False
        for i in range(0, len(pendientes), tam):
            lote = pendientes[i:i + tam]
            try:
                fichas = pedir_lote(driver, lote)
            except Exception as e:
                texto = str(e)
                if not fallo_dicho:
                    # Callar el error deja ceros sin explicacion
                    log(f"Fallo al pedir la ficha: {texto[:160]}")
                    fallo_dicho = True
                if ("out of memory" in texto.lower()
                        or "frame detached" in texto.lower()):
                    log("Chrome se quedo sin memoria; liberando...")
                    _liberar_memoria(driver)
                fichas = {}

            for rid in lote:
                f = fichas.get(rid)
                if not f:
                    faltan.append(rid)
                    continue
                ruta = dict(por_id[rid])
                # El nombre y el conductor de la ficha mandan sobre los
                # del reporte, que a veces vienen vacios
                if f.get("nombre"):
                    ruta["ruta"] = f["nombre"]
                if f.get("driver"):
                    ruta["driver"] = f["driver"]
                for p in f["paradas"]:
                    registros.append(normalizar(p, ruta))
                hechas += 1

            avisar(f"{hechas}/{len(por_id)} rutas  ·  {len(registros)} paradas")
            if hechas and hechas % 20 < tam:
                log(f"Fichas: {hechas}/{len(por_id)}  "
                    f"({len(registros)} paradas)")
            if hechas and hechas % DESCANSO_CADA < tam:
                _liberar_memoria(driver)
            time.sleep(pausa)

    if faltan:
        log(f"{len(faltan)} rutas no devolvieron paradas.")

    sin_coord = sum(1 for r in registros if not r["latitud"])
    if sin_coord:
        log(f"{sin_coord} paradas vienen sin coordenadas desde el panel.")

    return registros


COLUMNAS = [
    ("fecha", "FECHA"),
    ("cedis", "CEDIS"),
    ("ruta", "RUTA"),
    ("id_ruta", "ID RUTA"),
    ("driver", "DRIVER"),
    ("secuencia", "SECUENCIA"),
    ("direccion", "DIRECCION"),
    ("latitud", "LATITUD"),
    ("longitud", "LONGITUD"),
    ("estado", "ESTADO"),
    ("paquetes", "PAQUETES"),
    ("envios", "ENVIOS"),
    ("sacas", "SACAS"),
    ("tipo_domicilio", "TIPO DOMICILIO"),
    ("precision", "PRECISION GEO"),
    ("fuera_de_rango", "FUERA DE RANGO"),
    ("id_parada", "ID PARADA"),
]


def _escapar(t):
    """El texto que va dentro del XML del KML."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def guardar(registros, dia, sello=None):
    """Escribe el CSV para Excel y el KML para ver el mapa."""
    sello = sello or datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(BASE_DIR, f"paradas_{dia}_{sello}")
    csvf, kml = base + ".csv", base + ".kml"

    # utf-8-sig: sin el BOM, Excel rompe los acentos
    with open(csvf, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([t for _, t in COLUMNAS])
        for r in registros:
            w.writerow([limpiar(r.get(k, "")) for k, _ in COLUMNAS])

    # El KML agrupa por ruta, para poder encender y apagar cada una
    por_ruta = {}
    for r in registros:
        if not r["latitud"]:
            continue
        clave = (r["ruta"] or r["id_ruta"], r["id_ruta"])
        por_ruta.setdefault(clave, []).append(r)

    with open(kml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n')
        f.write("<name>Paradas %s</name>\n" % _escapar(dia))
        for estado, color in COLORES.items():
            f.write('<Style id="%s"><IconStyle><color>%s</color>'
                    '<scale>0.9</scale><Icon><href>http://maps.google.com/'
                    'mapfiles/kml/paddle/wht-blank.png</href></Icon>'
                    '</IconStyle></Style>\n' % (_escapar(estado), color))
        for (nombre, rid), paradas in sorted(por_ruta.items()):
            f.write("<Folder><name>%s (%d paradas)</name>\n"
                    % (_escapar(nombre), len(paradas)))
            # En orden de visita: asi el mapa se lee como el recorrido.
            # Unas pocas paradas llegan sin secuencia desde el panel (7
            # de 116 en la ruta de prueba); van al final en vez de
            # amontonarse en el cero.
            def _orden(x):
                s = (x["secuencia"] or "").strip()
                return (0, int(s)) if s.isdigit() else (1, 0)

            for p in sorted(paradas, key=_orden):
                etiqueta = (("%s. %s" % (p["secuencia"], p["direccion"][:40]))
                            if (p["secuencia"] or "").strip().isdigit()
                            else p["direccion"][:40] or "(sin direccion)")
                f.write("<Placemark><name>%s</name>\n" % _escapar(etiqueta))
                f.write("<styleUrl>#%s</styleUrl>\n" % _escapar(p["estado"]))
                f.write("<description>%s</description>\n" % _escapar(
                    "Ruta %s  ·  %s  ·  %s  ·  %s paquete(s)  ·  %s"
                    % (nombre, p["driver"], p["estado"], p["paquetes"],
                       p["direccion"])))
                f.write("<Point><coordinates>%s,%s,0</coordinates></Point>\n"
                        % (p["longitud"], p["latitud"]))
                f.write("</Placemark>\n")
            f.write("</Folder>\n")
        f.write("</Document></kml>\n")

    return csvf, kml


def resumen(registros):
    """Cuantas paradas por estado, y cuantas rutas."""
    por_estado, rutas = {}, set()
    for r in registros:
        por_estado[r["estado"]] = por_estado.get(r["estado"], 0) + 1
        if r["id_ruta"]:
            rutas.add(r["id_ruta"])
    return por_estado, len(rutas)


def main():
    print("=" * 62)
    print("  PARADAS - Mercado Libre")
    print("=" * 62)

    dia = ayer()
    if len(sys.argv) > 1:
        dia = sys.argv[1].strip()
    log(f"Dia: {dia}")

    driver = None
    try:
        driver = crear_driver()
        driver.get(RAIZ + "/logistics/monitoring-distribution")
        print("\nSi pide login, entra en la ventana de Chrome.")
        input("Cuando veas el monitoreo, presiona ENTER aqui... ")

        registros = extraer_dia(driver, dia)
        if not registros:
            log("No se extrajo ninguna parada.")
            return

        csvf, kml = guardar(registros, dia)
        por_estado, n_rutas = resumen(registros)

        print("\n" + "=" * 62)
        print(f"  {len(registros)} paradas de {n_rutas} rutas  ·  {dia}")
        print("=" * 62)
        for estado, n in sorted(por_estado.items(), key=lambda x: -x[1]):
            print(f"  {estado:<16} {n:>6}")
        print(f"\n  {csvf}")
        print(f"  {kml}")
        print("\n  El KML se abre en Google Earth, o se sube a")
        print("  google.com/mymaps para verlo en el navegador.")

    except Exception as e:
        log(f"ERROR: {e}")
        raise
    finally:
        if driver:
            input("\nENTER para cerrar Chrome... ")
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

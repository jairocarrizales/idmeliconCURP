# -*- coding: utf-8 -*-
"""
Extractor de capacidad - Pedidos de vehiculos de Mercado Libre

Los pedidos de vehiculos que MELI hace al transportista viven en:

    https://envios.adminml.com/logistics/travel-requests/last-mile

La pantalla los agrupa por estacion y hay que desplegar cada grupo. En
lugar de raspar eso, se llama la API que la alimenta:

    GET /logistics/travel-requests/api/requests

Trae mas de lo que la pantalla ensena junta: estacion, tipo de vehiculo,
estado, ETA, ETD, ciclo, flota fija o variable y la fecha de creacion.
"""

import os
import re
import sys
import csv
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE = "https://envios.adminml.com/logistics/travel-requests"
URL = BASE + "/last-mile"
API = BASE + "/api/requests"
API_RESUMEN = BASE + "/api/requests/summary"
API_FILTROS = BASE + "/api/requests/filters"
DOMINIO = "envios.adminml.com"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# La API acepta 500 por pagina sin quejarse; un dia normal trae ~160, asi
# que casi siempre basta una sola llamada.
POR_PAGINA = 500
PAUSA = 0.25
MAX_PAGINAS = 100

# El panel manda las 06:00 Z, que es la medianoche en Ciudad de Mexico.
# Asi el "dia 2" es el dia 2 local y no se corre al UTC.
HORA_CORTE = "T06:00:00.000Z"

# Como se lee cada estado. La API los manda en ingles.
ESTADOS = {
    "pending": "Para responder",
    "accepted": "Aceptado",
    "rejected": "Rechazado",
    "expired": "Expirado",
    "expiring": "Por expirar",
    "canceled": "Cancelado por MELI",
    "cancelled": "Cancelado por MELI",
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(texto):
    if texto is None:
        return ""
    t = str(texto).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", t).strip()


def ayer():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


# El arranque de Chrome ya esta resuelto y probado en el extractor de
# drivers. Se reusa en vez de duplicarlo.
from extraer_api import cerrar_chrome_huerfano, limpiar_lock, crear_driver  # noqa: E402


def preparar_pagina(driver, dia=None):
    """Deja al navegador en la pantalla, o el fetch lo bloquea el origen."""
    for pestana in driver.window_handles:
        driver.switch_to.window(pestana)
        if DOMINIO in (driver.current_url or ""):
            break
    if DOMINIO not in (driver.current_url or ""):
        d = dia or ayer()
        driver.get(f"{URL}?date_lteq={d}{HORA_CORTE}&date_gteq={d}{HORA_CORTE}")
        time.sleep(3)


SCRIPT_GET = """
const url = arguments[0];
const done = arguments[arguments.length - 1];
fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}})
  .then(r => r.text().then(t => done({ok: r.ok, status: r.status, body: t})))
  .catch(e => done({ok: false, status: 0, body: String(e)}));
"""


def _pedir(driver, url):
    driver.set_script_timeout(120)
    r = driver.execute_async_script(SCRIPT_GET, url)
    if not r or not r.get("ok"):
        estado = (r or {}).get("status", "?")
        detalle = (r or {}).get("body", "")[:300]
        if estado == 0 and "failed to fetch" in detalle.lower():
            raise RuntimeError(
                "El navegador bloqueo la consulta. Chrome debe estar en "
                "Pedidos de vehiculos de envios.adminml.com.")
        raise RuntimeError(f"La API respondio {estado}: {detalle}")
    return json.loads(r["body"])


def llamar_api(driver, desde, hasta, pagina=1):
    """Una pagina de pedidos del rango.

    status= vacio trae TODOS los estados mezclados. Omitir el parametro da
    422, y una lista separada por comas da 400: tiene que ir vacio.
    """
    url = (f"{API}?page={pagina}&per_page={POR_PAGINA}"
           f"&date_lt_eq={hasta}&date_gt_eq={desde}"
           f"&step_type=last_mile&status="
           f"&sort=facility,service_id,date:desc,eta,etd"
           f"&search=&attributes=&origins=&destinations=&vehicles=")
    return _pedir(driver, url)


def resumen_del_dia(driver, dia):
    """Los totales que muestran las tarjetas de la pantalla.

    Ojo: su 'total' no suma bien —se olvida de los expirados— asi que solo
    se usan los contadores por estado, no el total.
    """
    return _pedir(driver, f"{API_RESUMEN}?date_lt_eq={dia}&date_gt_eq={dia}"
                          f"&step_type=last_mile")


def catalogo(driver, dia=None):
    """Las estaciones y vehiculos que existen, con su nombre largo."""
    d = dia or ayer()
    return _pedir(driver, f"{API_FILTROS}?date_gt_eq={d}&date_lt_eq={d}"
                          f"&step_type=last_mile")


def solo_hora(valor):
    """'19:00' se queda igual; un ISO se recorta a la hora."""
    v = limpiar(valor)
    if len(v) >= 16 and "T" in v:
        return v[11:16]
    return v


def normalizar(p, nombres_estacion=None):
    """Un pedido de la API convertido en fila plana."""
    nombres_estacion = nombres_estacion or {}

    # Los atributos son etiquetas: flota fija/variable, SDD, ambulancia
    attrs = p.get("attributes") or []
    etiquetas = [limpiar(a.get("name")) for a in attrs if a.get("name")]
    ids_attr = {a.get("id") for a in attrs}
    if "fixed_fleet_type" in ids_attr:
        flota = "Fija"
    elif "variable_fleet_type" in ids_attr:
        flota = "Variable"
    else:
        flota = ""

    # El ciclo (AM1, SD2...) viene en el primer paso del viaje. Muchos
    # pedidos lo traen vacio desde Mercado Libre: no todos los viajes lo
    # llevan. No es un fallo de extraccion.
    pasos = p.get("steps") or []
    ciclo = limpiar(pasos[0].get("cycleId")) if pasos else ""

    fecha = limpiar(p.get("date"))[:10]
    if len(fecha) == 10:
        fecha = f"{fecha[8:10]}/{fecha[5:7]}/{fecha[0:4]}"

    creado = limpiar(p.get("createdAt"))
    if len(creado) >= 16:
        creado = f"{creado[8:10]}/{creado[5:7]}/{creado[0:4]} {creado[11:16]}"

    estacion = limpiar(p.get("facilityId"))
    estado_api = limpiar(p.get("status"))

    return {
        "fecha": fecha,
        "estacion": estacion,
        "nombre_estacion": nombres_estacion.get(estacion, ""),
        "vehiculo": limpiar(p.get("vehicleType")),
        "servicio": limpiar(p.get("melServiceDescription")),
        "estado": ESTADOS.get(estado_api, estado_api),
        "flota": flota,
        "sdd": "Si" if "sdd" in ids_attr else "",
        "ciclo": ciclo,
        "eta": solo_hora(p.get("eta")),
        "etd": solo_hora(p.get("etd")),
        "id_pedido": limpiar(p.get("requestId")),
        "id_viaje": limpiar(p.get("travelId")),
        "creado": creado,
        "etiquetas": ", ".join(etiquetas),
    }


def dias_del_rango(desde, hasta):
    """Los dias entre dos fechas ISO, ambos incluidos."""
    d = datetime.strptime(desde, "%Y-%m-%d")
    h = datetime.strptime(hasta, "%Y-%m-%d")
    salida = []
    while d <= h:
        salida.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return salida


def extraer_dia(driver, dia, nombres=None):
    """Todos los pedidos de un dia, de todos los estados."""
    registros, vistos = [], set()
    pagina = 1
    while pagina <= MAX_PAGINAS:
        datos = llamar_api(driver, dia, dia, pagina)
        lote = datos.get("requests") or []
        for p in lote:
            rid = p.get("requestId")
            if rid in vistos:
                continue
            vistos.add(rid)
            registros.append(normalizar(p, nombres))

        info = datos.get("pageInfo") or {}
        if pagina >= (info.get("numberOfPages") or 1):
            break
        if not lote:
            break
        pagina += 1
        time.sleep(PAUSA)
    return registros


def extraer_rango(driver, desde=None, hasta=None, avisar=None):
    """Los pedidos de cada dia del rango.

    La API acepta un rango, pero devuelve los dias de uno en uno; se pide
    dia por dia para saber cual vino vacio y poder decirlo.
    """
    desde = desde or ayer()
    hasta = hasta or desde
    avisar = avisar or (lambda *a: None)
    preparar_pagina(driver, desde)

    # Los nombres largos de las estaciones (SGD3 -> Guadalajara 3)
    nombres = {}
    try:
        cat = catalogo(driver, desde)
        for o in (cat.get("origins") or []):
            desc = limpiar(o.get("description"))
            if desc and desc != limpiar(o.get("id")):
                nombres[limpiar(o.get("id"))] = desc
    except Exception:
        pass

    dias = dias_del_rango(desde, hasta)
    todos, vacios = [], []
    for i, dia in enumerate(dias, 1):
        del_dia = extraer_dia(driver, dia, nombres)
        if del_dia:
            log(f"{dia}: {len(del_dia)} pedidos")
        else:
            vacios.append(dia)
            log(f"{dia}: sin datos")
        todos.extend(del_dia)
        avisar(f"{len(todos)} pedidos  ·  dia {i} de {len(dias)}")
        if i < len(dias):
            time.sleep(PAUSA)

    # Decirlo antes de que alguien lo lea como dato perdido
    sin_ciclo = sum(1 for r in todos if not r["ciclo"])
    if sin_ciclo:
        log(f"{sin_ciclo} pedidos vienen sin ciclo desde Mercado Libre "
            "(no todos los viajes lo llevan).")

    return todos, vacios


# Los estados en el orden en que los muestra la pantalla
ORDEN_ESTADOS = ["Para responder", "Aceptado", "Expirado", "Rechazado",
                 "Cancelado por MELI", "Por expirar"]


def agrupar(registros):
    """Resumen por fecha, estacion y tipo de vehiculo.

    Una fila por combinacion, con una columna por estado. Es la vista que
    sirve para planear: cuantos vehiculos pidieron y cuantos se aceptaron.
    """
    grupos = {}
    for r in registros:
        clave = (r["fecha"], r["estacion"], r["vehiculo"])
        g = grupos.setdefault(clave, {
            "fecha": r["fecha"],
            "estacion": r["estacion"],
            "nombre_estacion": r["nombre_estacion"],
            "vehiculo": r["vehiculo"],
            "flota": r["flota"],
            "total": 0,
        })
        g["total"] += 1
        g[r["estado"]] = g.get(r["estado"], 0) + 1

    def orden(g):
        # Por fecha (dd/mm/aaaa -> aaaammdd), luego estacion y vehiculo
        f = g["fecha"]
        iso = f"{f[6:10]}{f[3:5]}{f[0:2]}" if len(f) == 10 else f
        return (iso, g["estacion"], g["vehiculo"])

    return sorted(grupos.values(), key=orden)


COLUMNAS = [
    ("fecha", "Fecha"),
    ("estacion", "Estacion"),
    ("nombre_estacion", "Nombre estacion"),
    ("vehiculo", "Tipo de vehiculo"),
    ("estado", "Estado"),
    ("flota", "Flota"),
    ("sdd", "SDD"),
    ("ciclo", "Ciclo"),
    ("eta", "ETA"),
    ("etd", "ETD"),
    ("id_pedido", "ID pedido"),
    ("id_viaje", "ID viaje"),
    ("creado", "Creado"),
]


def _escribir(ruta_csv, encabezados, filas):
    """Solo CSV: el TXT no se usa y duplicaba cada archivo."""
    # utf-8-sig: sin el BOM, Excel rompe los acentos
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(encabezados)
        for fila in filas:
            w.writerow([limpiar(c) for c in fila])


def guardar(registros, desde, hasta):
    """Dos archivos: el detalle por vehiculo y el resumen por estacion."""
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    rango = desde if desde == hasta else f"{desde}_a_{hasta}"
    base = os.path.join(BASE_DIR, f"capacidad_{rango}_{sello}")

    # --- detalle: una fila por vehiculo pedido ---
    claves = [k for k, _ in COLUMNAS]
    _escribir(base + ".csv",
              [t for _, t in COLUMNAS],
              [[r.get(k, "") for k in claves] for r in registros])

    # --- resumen: una fila por estacion y tipo, con los estados en columnas ---
    grupos = agrupar(registros)
    estados_vistos = [e for e in ORDEN_ESTADOS
                      if any(g.get(e) for g in grupos)]
    enc = (["Fecha", "Estacion", "Nombre estacion", "Tipo de vehiculo",
            "Flota", "Total"] + estados_vistos)
    filas = [[g["fecha"], g["estacion"], g["nombre_estacion"], g["vehiculo"],
              g["flota"], g["total"]] + [g.get(e, 0) for e in estados_vistos]
             for g in grupos]
    _escribir(base + "_resumen.csv", enc, filas)

    return base + ".csv", base + "_resumen.csv"


def contar_estados(registros):
    """Cuantos hay de cada estado, en el orden de la pantalla."""
    cuenta = {}
    for r in registros:
        cuenta[r["estado"]] = cuenta.get(r["estado"], 0) + 1
    ordenado = {e: cuenta[e] for e in ORDEN_ESTADOS if e in cuenta}
    for e, n in cuenta.items():           # por si aparece uno nuevo
        ordenado.setdefault(e, n)
    return ordenado


def hay_datos(driver, dia):
    """Ese dia tiene pedidos? Una sola consulta, la mas barata."""
    try:
        r = resumen_del_dia(driver, dia)
    except Exception:
        return False
    # El 'total' del summary no suma bien (se olvida de los expirados),
    # asi que se miran los contadores por estado.
    return any(r.get(k) for k in
               ("accepted", "rejected", "pending", "canceled", "expired"))


def primer_dia_con_datos(driver, tope_dias=400, avisar=None):
    """El dia mas antiguo que Mercado Libre todavia guarda.

    Por biseccion: unas 9 consultas en vez de cientos. Medido en
    septiembre de 2026, el limite estaba en 88 dias hacia atras.
    """
    from datetime import date
    avisar = avisar or (lambda *a: None)
    preparar_pagina(driver)

    hoy = date.today()
    alto = hoy - timedelta(days=1)          # ayer, que casi siempre tiene
    bajo = hoy - timedelta(days=tope_dias)

    if hay_datos(driver, bajo.isoformat()):
        return bajo.isoformat()             # hay mas historial del que se busco
    if not hay_datos(driver, alto.isoformat()):
        # Ni ayer tiene datos; buscar hacia atras el primero que si
        for i in range(2, 15):
            d = hoy - timedelta(days=i)
            if hay_datos(driver, d.isoformat()):
                alto = d
                break
        else:
            return ""

    consultas = 0
    while (alto - bajo).days > 1:
        medio = bajo + (alto - bajo) / 2
        consultas += 1
        avisar(f"buscando... ({consultas} consultas)")
        if hay_datos(driver, medio.isoformat()):
            alto = medio
        else:
            bajo = medio
    log(f"Limite del historial: {alto} ({consultas} consultas)")
    return alto.isoformat()


def main():
    print("=" * 62)
    print("  CAPACIDAD - Pedidos de vehiculos de Mercado Libre")
    print("=" * 62)

    desde = hasta = ayer()
    if len(sys.argv) > 1:
        desde = sys.argv[1].strip()
        hasta = sys.argv[2].strip() if len(sys.argv) > 2 else desde
    log(f"Rango: {desde} a {hasta}")

    driver = None
    try:
        driver = crear_driver()
        driver.get(f"{URL}?date_lteq={desde}{HORA_CORTE}"
                   f"&date_gteq={desde}{HORA_CORTE}")
        print("\nSi pide login, entra en la ventana de Chrome.")
        input("Cuando veas los pedidos, presiona ENTER aqui... ")

        registros, vacios = extraer_rango(driver, desde, hasta)

        if not registros:
            log("No hay pedidos en ese rango.")
            limite = primer_dia_con_datos(driver)
            if limite:
                log(f"El historial llega hasta el {limite}.")
            return

        det, res = guardar(registros, desde, hasta)
        cuenta = contar_estados(registros)

        print("\n" + "=" * 62)
        print(f"  {len(registros)} pedidos  ·  {desde} a {hasta}")
        print("=" * 62)
        for estado, n in cuenta.items():
            print(f"  {estado:<24} {n:>5}")
        if vacios:
            print(f"\n  Sin datos ({len(vacios)} dias): "
                  f"{', '.join(vacios[:8])}"
                  f"{' ...' if len(vacios) > 8 else ''}")
        print(f"\n  {det}")
        print(f"  {res}")

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

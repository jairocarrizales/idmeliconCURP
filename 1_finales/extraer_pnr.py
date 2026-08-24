# -*- coding: utf-8 -*-
"""
Extractor de casos PNR - Bandeja de soporte de Mercado Libre

Los reclamos PNR (paquetes no recibidos) viven en:

    https://envios.adminml.com/logistics/case-center/cases

La tabla los muestra de 30 en 30. En lugar de raspar el HTML, se llama la
misma API que la alimenta:

    POST /logistics/case-center/api/feed/search-feed-cases-dec

Devuelve JSON con mas de lo que la pantalla ensena: ademas del driver, el
paquete y el monto, trae la ruta, el CEDIS y la fecha del reclamo.
"""

import os
import re
import sys
import csv
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

URL = "https://envios.adminml.com/logistics/case-center/cases"
API = ("https://envios.adminml.com/logistics/case-center/api/feed/"
       "search-feed-cases-dec")
API_FILTROS = ("https://envios.adminml.com/logistics/case-center/api/feed/"
               "set-filters-by-case-group")
DOMINIO = "envios.adminml.com"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# La API SOLO acepta 30 por pagina: con 50 o mas responde 400. Probado.
# Asi que 350 casos son 12 vueltas, y no hay forma de bajarlas.
POR_PAGINA = 30

# El parametro 'carrier' que manda la web NO hace falta: la sesion ya dice
# de que transportista es. Comprobado pidiendo sin el (351 casos, iguales).
# Se omite a proposito, para que el programa sirva a cualquier carrier.
PAUSA = 0.25
MAX_PAGINAS = 200

# Como se lee cada estado. La API los manda en ingles; la web los traduce
# igual que aqui.
ESTADOS = {
    "NEW": "Nuevo",
    "OPEN": "Revision en curso",
    "IN_PROGRESS": "Revision en curso",
    "CLOSED": "Cerrado",
    "CANCELLED": "Cancelado",
}

# El sub-estado es lo que la pantalla muestra como descripcion del caso
SUB_ESTADOS = {
    "WAITING_RECEIPT": "Esperando comprobante",
    "UPLOADED_RECEIPT": "Comprobante cargado",
    "TO_BILL": "Por facturar",
    "BILLED": "Enviado a facturacion",
    "NOT_BILLED": "Anulado",
    "IN_REVIEW": "En revision",
    "ON_REVIEW": "En revision",
    "WAITING_RESPONSE": "Esperando respuesta",
}

MOTIVOS = {
    "PNR_CLAIM": "Reclamo PNR",
    "CARRIER_NO_POD": "Sin comprobante de entrega",
    "INVALID_POD": "Comprobante incorrecto o incompleto",
    "PNR_NOT_SPECIFIED": "Motivo no especificado",
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(texto):
    """Deja el texto listo para un TXT separado por tabuladores."""
    if texto is None:
        return ""
    t = str(texto).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", t).strip()


# El arranque de Chrome (perfil persistente, cierre de huerfanos, limpieza
# de locks) ya esta resuelto en el extractor de drivers. Se reusa en vez de
# duplicarlo: los mismos errores se arreglan en un solo sitio.
from extraer_api import cerrar_chrome_huerfano, limpiar_lock, crear_driver  # noqa: E402


def preparar_pagina(driver):
    """Deja al navegador parado en la bandeja, o el fetch fallara.

    Un fetch lanzado desde otro dominio lo bloquea la politica de origen y
    devuelve 'TypeError: Failed to fetch' con status 0.
    """
    for pestana in driver.window_handles:
        driver.switch_to.window(pestana)
        if DOMINIO in (driver.current_url or ""):
            break
    if DOMINIO not in (driver.current_url or ""):
        driver.get(URL)
        time.sleep(3)


SCRIPT_POST = """
const url = arguments[0], cuerpo = arguments[1];
const done = arguments[arguments.length - 1];
fetch(url, {
  method: 'POST',
  credentials: 'include',
  headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  body: cuerpo
}).then(r => r.text().then(t => done({ok: r.ok, status: r.status, body: t})))
  .catch(e => done({ok: false, status: 0, body: String(e)}));
"""


def periodo_actual(hoy=None):
    """El periodo de facturacion en curso, formato 202608Q2.

    Q1 es del 1 al 15; Q2 del 16 al fin de mes.
    """
    hoy = hoy or datetime.now()
    q = "Q1" if hoy.day <= 15 else "Q2"
    return f"{hoy.year}{hoy.month:02d}{q}"


def rango_del_periodo(periodo):
    """Las fechas ISO que cubre un periodo como 202608Q2."""
    ano, mes, q = int(periodo[:4]), int(periodo[4:6]), periodo[6:]
    if q == "Q1":
        return (f"{ano}-{mes:02d}-01T00:00:00.000Z",
                f"{ano}-{mes:02d}-15T23:59:59.999Z")
    import calendar
    ultimo = calendar.monthrange(ano, mes)[1]
    return (f"{ano}-{mes:02d}-16T00:00:00.000Z",
            f"{ano}-{mes:02d}-{ultimo}T23:59:59.999Z")


def llamar_api(driver, periodo, pagina=1, tamano=POR_PAGINA):
    """Pide una pagina de casos PNR reusando la sesion del navegador."""
    desde, hasta = rango_del_periodo(periodo)
    busqueda = {
        "date_from": desde,
        "date_to": hasta,
        "order": "desc",
        "sort": "priority_weight",
        "period": periodo,
        "billingPeriod": {},
        "size": tamano,
        "page": pagina,
        "searchFieldOption": "case_id",
    }
    cuerpo = json.dumps({
        "searchParams": json.dumps(busqueda),
        "userType": "3PL",
        "application": "LOGISTICS_PNR",
    })

    driver.set_script_timeout(120)
    r = driver.execute_async_script(SCRIPT_POST, API, cuerpo)

    if not r or not r.get("ok"):
        estado = (r or {}).get("status", "?")
        detalle = (r or {}).get("body", "")[:300]
        if estado == 0 and "failed to fetch" in detalle.lower():
            raise RuntimeError(
                "El navegador bloqueo la consulta. Chrome debe estar en la "
                "Bandeja de soporte de envios.adminml.com.")
        raise RuntimeError(f"La API respondio {estado}: {detalle}")

    return json.loads(r["body"])


def aplanar(caso):
    """Saca los pares clave-valor del anidado cells[] -> lines[] -> [].

    La API los entrega asi porque la web dibuja una celda por grupo. Para
    nosotros son simplemente campos: {"case.driver_name": "...", ...}
    """
    campos = {}
    for celda in caso.get("cells") or []:
        for linea in celda.get("lines") or []:
            for par in linea or []:
                clave = par.get("key")
                if clave:
                    campos[clave] = par.get("value")
    return campos


def normalizar(caso):
    """Un caso de la API convertido en una fila plana."""
    c = aplanar(caso)

    # El monto llega como {"currency": "MXN", "amount": "399"}
    monto = c.get("case.shipment_amount") or {}
    if isinstance(monto, dict):
        cantidad = limpiar(monto.get("amount"))
        moneda = limpiar(monto.get("currency"))
    else:
        cantidad, moneda = limpiar(monto), ""

    # El estado y su detalle: juntos son la descripcion que ve el usuario
    estado = c.get("case.state") or {}
    if not isinstance(estado, dict):
        estado = {}
    st = limpiar(estado.get("status"))
    sub = limpiar(estado.get("sub_status"))
    descripcion = SUB_ESTADOS.get(sub, sub) or ESTADOS.get(st, st)

    fecha = limpiar(c.get("case.date_created"))
    if len(fecha) >= 10:
        # 2026-08-24T20:33:01Z -> 24/08/2026
        fecha = f"{fecha[8:10]}/{fecha[5:7]}/{fecha[0:4]}"

    # Algunos casos llegan con driver_name = " " (un espacio): MELI aun no
    # asigno conductor. limpiar() lo deja vacio, que es lo honesto.
    return {
        "driver": limpiar(c.get("case.driver_name")),
        "paquete": limpiar(c.get("case.shipment_id")),
        "monto": cantidad,
        "descripcion": descripcion,
        # Lo demas no se pidio, pero viene gratis en la misma respuesta
        "moneda": moneda,
        "caso": limpiar(caso.get("case_id") or c.get("case.id")),
        "estado": ESTADOS.get(st, st),
        "motivo": MOTIVOS.get(limpiar(c.get("case.type")),
                              limpiar(c.get("case.type"))),
        "ruta": limpiar(c.get("case.route_code")),
        "id_ruta": limpiar(c.get("case.route_id")),
        "cedis": limpiar(c.get("case.svc_name")),
        "fecha": fecha,
    }


def extraer_todo(driver, periodo=None, avisar=None):
    """Trae todos los casos PNR del periodo, pagina por pagina."""
    periodo = periodo or periodo_actual()
    avisar = avisar or (lambda *a: None)
    preparar_pagina(driver)

    registros, vistos = [], set()
    pagina, total_paginas, total = 1, None, None

    while pagina <= MAX_PAGINAS:
        datos = llamar_api(driver, periodo, pagina)

        pag = datos.get("paging") or {}
        if total_paginas is None:
            # Con size=100 la API recalcula las paginas; nos fiamos de eso
            total_paginas = pag.get("totalPages")
            total = pag.get("totalElements")
            if total is not None:
                log(f"El periodo {periodo} tiene {total} casos.")
                avisar(f"{total} casos en {periodo}")

        lote = datos.get("casesList") or []
        nuevos = 0
        for caso in lote:
            reg = normalizar(caso)
            # Deduplicar por numero de caso, por si dos paginas se traslapan
            if reg["caso"] and reg["caso"] in vistos:
                continue
            vistos.add(reg["caso"])
            registros.append(reg)
            nuevos += 1

        log(f"Pagina {pagina}: +{nuevos} (total {len(registros)})")
        avisar(f"{len(registros)} casos")

        if not lote:
            break
        if total_paginas and pagina >= total_paginas:
            break
        if total and len(registros) >= total:
            break
        pagina += 1
        time.sleep(PAUSA)

    if total and len(registros) != total:
        log(f"AVISO: se esperaban {total} casos y llegaron {len(registros)}.")

    # Si MELI agrega un estado nuevo, saldria en ingles y con guiones bajos.
    # Mejor decirlo que dejarlo pasar: el diccionario se completa en un
    # minuto, pero solo si alguien se entera.
    crudos = sorted({r["descripcion"] for r in registros
                     if r["descripcion"] and r["descripcion"].isupper()
                     and "_" in r["descripcion"]})
    if crudos:
        log(f"AVISO: estados sin traducir ({', '.join(crudos)}). "
            "Salen tal cual los manda Mercado Libre.")

    sin_driver = sum(1 for r in registros if not r["driver"])
    if sin_driver:
        log(f"{sin_driver} casos vienen sin conductor asignado en el panel; "
            "se completan por numero de ruta si se pide.")

    return registros


# Los cuatro datos pedidos, en ese orden. El resto viaja en el CSV largo.
COLUMNAS = [
    ("driver", "Driver"),
    ("paquete", "ID paquete"),
    ("monto", "Monto"),
    ("descripcion", "Descripcion"),
]

# Lo que la API regala y no cuesta nada guardar aparte
COLUMNAS_EXTRA = [
    ("caso", "ID caso"),
    ("fecha", "Fecha"),
    ("estado", "Estado"),
    ("motivo", "Motivo"),
    ("ruta", "Ruta"),
    ("id_ruta", "ID ruta"),
    ("cedis", "CEDIS"),
]


def guardar(registros, periodo, con_extras=False):
    """Escribe el TXT (para pegar en Excel) y el CSV."""
    cols = COLUMNAS + (COLUMNAS_EXTRA if con_extras else [])
    encabezados = [titulo for _, titulo in cols]
    claves = [clave for clave, _ in cols]

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"pnr_{periodo}_{sello}"
    txt = os.path.join(BASE_DIR, base + ".txt")
    csvf = os.path.join(BASE_DIR, base + ".csv")

    # utf-8-sig: sin el BOM, Excel rompe los acentos
    with open(txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(encabezados) + "\n")
        for r in registros:
            f.write("\t".join(limpiar(r.get(k, "")) for k in claves) + "\n")

    with open(csvf, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(encabezados)
        for r in registros:
            w.writerow([limpiar(r.get(k, "")) for k in claves])

    return txt, csvf


def resumen(registros):
    """Cuenta por estado y suma los montos, para el reporte final."""
    por_estado, suma, sin_monto = {}, 0.0, 0
    for r in registros:
        e = r.get("estado") or "(sin estado)"
        por_estado[e] = por_estado.get(e, 0) + 1
        try:
            suma += float(r.get("monto") or 0)
        except ValueError:
            sin_monto += 1
    return por_estado, suma, sin_monto


def main():
    print("=" * 62)
    print("  CASOS PNR - Bandeja de soporte de Mercado Libre")
    print("=" * 62)

    periodo = periodo_actual()
    if len(sys.argv) > 1:
        periodo = sys.argv[1].strip().upper()
    log(f"Periodo: {periodo}")

    driver = None
    try:
        driver = crear_driver()
        driver.get(URL)
        print("\nSi pide login, entra en la ventana de Chrome.")
        input("Cuando veas la bandeja, presiona ENTER aqui... ")

        registros = extraer_todo(driver, periodo)
        if not registros:
            log("No se encontraron casos en ese periodo.")
            return

        txt, csvf = guardar(registros, periodo, con_extras=True)
        por_estado, suma, sin_monto = resumen(registros)

        print("\n" + "=" * 62)
        print(f"  {len(registros)} casos PNR - periodo {periodo}")
        print("=" * 62)
        for estado, n in sorted(por_estado.items(), key=lambda x: -x[1]):
            print(f"  {estado:<24} {n:>5}")
        print(f"\n  Monto total{'':<13} ${suma:,.2f}")
        if sin_monto:
            print(f"  Sin monto legible{'':<7} {sin_monto}")
        print(f"\n  {txt}")
        print(f"  {csvf}")

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

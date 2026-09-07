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

    # La cruda se guarda tambien: el CSV del panel la lleva con hora
    fecha_cruda = limpiar(c.get("case.date_created"))
    fecha = fecha_cruda
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
        "fecha_completa": fecha_cruda.replace("Z", ""),
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

# Lo que solo aparece al abrir el caso. Ordenadas como en la pantalla:
# primero quien reclama, luego que se entrego, despues quien lo llevo.
COLUMNAS_DETALLE = [
    ("id_conductor", "ID conductor"),
    ("conductor", "Conductor (detalle)"),
    ("telefono", "Telefono conductor"),
    ("id_vehiculo", "ID vehiculo"),
    ("nombre_ruta", "Nombre ruta"),
    ("transportadora", "Transportadora"),
    ("envio", "ID envio"),
    ("valor_compra", "Valor de la compra"),
    ("reclamante", "Reclamante"),
    ("designado", "Designado para recibir"),
    ("seguimiento", "ID seguimiento"),
    ("mensaje", "Mensaje del reclamo"),
    ("productos", "Productos"),
    ("precios_productos", "Precios"),
    ("cantidad_productos", "Cuantos productos"),
    ("fecha_entrega", "Fecha de entrega"),
    ("recibio_quien", "Quien recibio"),
    ("recibio_nombre", "Nombre de quien recibio"),
    ("recibio_documento", "Documento"),
    ("geo_foto", "Geo de la foto"),
    ("geo_direccion", "Geo de la direccion"),
    ("distancia_geo", "Distancia entre geos"),
    ("evidencias", "Evidencias"),
    ("fecha_revision", "Fecha pedido de revision"),
    ("pedido_revision", "Pedido de revision"),
    ("rep_asistente", "Rep - asistente"),
    ("adjuntos", "Adjuntos"),
    ("fecha_cierre", "Fecha de cierre del caso"),
    ("periodo_facturacion", "Periodo facturacion"),
    ("prefactura", "Prefactura"),
    ("id_comprador", "ID comprador"),
    ("id_reclamo", "ID reclamo"),
    ("voluminoso", "Voluminoso"),
]


# El formato que se usa en el control: las mismas columnas, en el mismo
# orden, que traia el CSV que la plataforma generaba antes de quitar el
# boton de descarga.
COLUMNAS_CONTROL = [
    # Estas dos van primero aunque el CSV original no las traia: son las
    # que se usan para cruzar con el padron y para leer de un vistazo.
    ("id_conductor", "ID DEL DRIVER"),
    ("nombre_driver", "NOMBRE DEL DRIVER"),
    ("caso", "ID DEL CASO"),
    ("fecha_iso", "FECHA DEL CASO"),
    ("tipo_pnr", "TIPO DE PNR"),
    ("descripcion", "ESTADO"),
    ("periodo_facturacion", "PERIODO DE FACTURACION"),
    ("fecha_revision_iso", "FECHA PEDIDO DE REVISION"),
    ("pedido_revision", "PEDIDO DE REVISION"),
    ("fecha_cierre_iso", "FECHA DE CIERRE DE CASO"),
    ("rep_asistente", "REP - ASISTENTE"),
    # Estas dos vienen vacias del panel: en el CSV original tampoco las
    # traia casi ninguna fila. Se escriben para que el formato calce.
    ("comentario_cierre", "COMENTARIO DE CIERRE"),
    ("prefactura", "Nº DE PREFACTURA"),
    ("paquete", "ID DE ENVIO"),
    ("productos_csv", "PRODUCTOS"),
    ("valor_compra_csv", "VALOR DE LA COMPRA"),
    ("rep_transportadora", "REP TRANSPORTADORA"),
    ("id_transportadora", "ID DE TRANSPORTADORA"),
    ("transportadora", "TRANSPORTADORA"),
    ("cedis", "ESTACION DE ORIGEN"),
    ("id_ruta", "RUTA"),
    ("id_conductor", "ID DEL CONDUCTOR"),
    ("fecha_entrega_iso", "FECHA DE ENTREGA"),
    ("id_reclamo", "ID DE RECLAMO"),
    ("fecha_reclamo", "FECHA DEL RECLAMO"),
]


def _a_iso(valor):
    """'19/08/2026 18:13' -> '2026-08-19T18:13:41' (como el CSV original).

    Si ya viene en ISO se deja igual; si es solo fecha, se completa con
    las 00:00:00 para que el formato no cambie de una fila a otra.
    """
    t = limpiar(valor)
    if not t:
        return ""
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return t.replace(" ", "T")[:19]
    if len(t) >= 10 and t[2] == "/" and t[5] == "/":
        dia, mes, ano = t[0:2], t[3:5], t[6:10]
        hora = t[11:19] if len(t) > 11 else ""
        if len(hora) == 5:
            hora += ":00"
        return f"{ano}-{mes}-{dia}T{hora or '00:00:00'}"
    return t


def _fila_control(r, periodo):
    """Un registro con los nombres y formatos del CSV original."""
    monto = limpiar(r.get("valor_compra")) or limpiar(r.get("monto"))
    if monto and not monto.startswith("$"):
        monto = "$ " + monto
    # El CSV original escribe los productos separados por coma y termina
    # en coma; aqui llegan separados por '|' desde el detalle.
    productos = limpiar(r.get("productos"))
    if productos:
        productos = productos.replace(" | ", ", ")
        if not productos.endswith(","):
            productos += ", "
    # El nombre viene por dos vias: la ficha del caso y el listado. Se
    # prefiere el de la ficha, que es el que MELI muestra en el detalle.
    nombre = limpiar(r.get("conductor")) or limpiar(r.get("driver"))
    return {
        "id_conductor": limpiar(r.get("id_conductor")),
        "nombre_driver": nombre,
        "caso": limpiar(r.get("caso")),
        "fecha_iso": _a_iso(r.get("fecha_completa")
                            or r.get("fecha")),
        # En el CSV original todas las filas dicen lo mismo
        "tipo_pnr": "Reclamo de PNR" if r.get("caso") else "",
        "descripcion": limpiar(r.get("descripcion")),
        # Solo lo llevan los casos ya facturados; el panel lo deja vacio
        # en los abiertos, igual que el CSV original.
        "periodo_facturacion": (periodo if limpiar(r.get("descripcion"))
                                in ("Anulado", "Enviado a facturacion")
                                else ""),
        "fecha_revision_iso": _a_iso(r.get("fecha_revision")),
        "pedido_revision": limpiar(r.get("pedido_revision")),
        "fecha_cierre_iso": _a_iso(r.get("fecha_cierre")),
        "rep_asistente": limpiar(r.get("rep_asistente")),
        # Mercado Libre ya no expone estas dos: en el CSV original venian
        # vacias en casi todas las filas.
        "comentario_cierre": "",
        "prefactura": limpiar(r.get("prefactura")),
        "paquete": limpiar(r.get("paquete")),
        "productos_csv": productos,
        "valor_compra_csv": monto,
        "rep_transportadora": limpiar(r.get("rep_transportadora")),
        "id_transportadora": limpiar(r.get("id_transportadora")),
        "transportadora": limpiar(r.get("transportadora")),
        "cedis": limpiar(r.get("cedis")),
        "id_ruta": limpiar(r.get("id_ruta")),
        "id_conductor": limpiar(r.get("id_conductor")),
        "fecha_entrega_iso": _a_iso(r.get("fecha_entrega")),
        "id_reclamo": limpiar(r.get("id_reclamo")),
        "fecha_reclamo": _a_iso(r.get("fecha_reclamo")),
    }


def guardar_control(registros, periodo, sello=None):
    """El archivo con las 23 columnas del CSV que daba la plataforma.

    A diferencia del otro formato, aqui NO se omiten las columnas vacias:
    la hoja espera siempre las mismas, en el mismo sitio.
    """
    sello = sello or datetime.now().strftime("%Y%m%d_%H%M%S")
    # El nombre tambien como lo daba la plataforma: LOGISTICS_PNR - 202608Q2
    csvf = os.path.join(BASE_DIR, f"LOGISTICS_PNR - {periodo}_{sello}.csv")
    # Separador coma y sin BOM, igual que el original
    with open(csvf, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([t for _, t in COLUMNAS_CONTROL])
        for r in registros:
            fila = _fila_control(r, periodo)
            w.writerow([fila.get(k, "") for k, _ in COLUMNAS_CONTROL])
    return csvf


def guardar(registros, periodo, con_extras=False, con_detalle=False,
            sello=None):
    """Escribe el CSV.

    El TXT ya no se genera: duplicaba cada archivo y el CSV se abre igual
    en Excel.
    """
    cols = COLUMNAS + (COLUMNAS_EXTRA if con_extras else [])
    if con_detalle:
        # Solo las columnas del detalle que traigan algo: si un periodo no
        # tiene evidencias, no vale la pena una columna vacia
        cols = cols + [(k, t) for k, t in COLUMNAS_DETALLE
                       if any(r.get(k) for r in registros)]
    encabezados = [titulo for _, titulo in cols]
    claves = [clave for clave, _ in cols]

    # Si no se da sello, cada llamada crea su archivo. Pasarlo permite que
    # el listado y el del control lleven el mismo, y que reescribir el
    # listado con los detalles pise el suyo en vez de dejar dos.
    sello = sello or datetime.now().strftime("%Y%m%d_%H%M%S")
    csvf = os.path.join(BASE_DIR, f"pnr_{periodo}_{sello}.csv")

    # utf-8-sig: sin el BOM, Excel rompe los acentos
    with open(csvf, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(encabezados)
        for r in registros:
            w.writerow([limpiar(r.get(k, "")) for k in claves])

    return csvf


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

        # Se guarda el listado ANTES de pedir los detalles: si el segundo
        # paso falla o lo interrumpen, no se pierde lo ya traido.
        csvf = guardar(registros, periodo, con_extras=True)

        detalle = "--detalle" in [a.lower() for a in sys.argv]
        if detalle:
            log(f"Abriendo la ficha de cada uno de los {len(registros)} casos...")
            n = completar_detalles(driver, registros)
            log(f"Detalles completos: {n}/{len(registros)}")
            csvf = guardar(registros, periodo, con_extras=True,
                           con_detalle=True)
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


# --------------------------------------------------------------- DETALLE
#
# El detalle de un caso NO tiene API propia: la pagina
#
#     /logistics/case-center/cases/<id caso>
#
# se dibuja en el servidor y trae los datos como JSON dentro del HTML, en
# un objeto "caseDetail". Se busca ahi en vez de raspar la pantalla.

URL_DETALLE = "https://envios.adminml.com/logistics/case-center/cases/"

# Cuantos casos se piden a la vez. Cada uno es una pagina completa (~3 MB
# de HTML), asi que el lote va mas corto que en otros extractores para no
# llenar la memoria de Chrome.
LOTE_DETALLES = 6
PAUSA_DETALLES = 0.3
REINTENTOS_DETALLE = 2


def _recortar_json(html, clave):
    """Saca el objeto JSON que sigue a "clave": del HTML.

    Cuenta llaves para hallar donde termina, respetando las que van
    dentro de un texto. Un recorte a ojo daria 'Unterminated string'.
    """
    marca = '"%s":' % clave
    i = html.find(marca)
    if i < 0:
        return None
    try:
        ini = html.index("{", i + len(marca))
    except ValueError:
        return None

    prof, en_texto, escapado = 0, False, False
    for j in range(ini, len(html)):
        c = html[j]
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
        if c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0:
                try:
                    return json.loads(html[ini:j + 1])
                except ValueError:
                    return None
    return None


def _pares(obj, salida=None):
    """Todo par etiqueta/valor del detalle, este donde este anidado.

    Las tarjetas guardan sus filas en mainContent.mainRows[].cells[].
    primary, y cada tipo de tarjeta lo anida distinto; recorrer el arbol
    entero es mas corto y no se rompe si cambian la forma.
    """
    if salida is None:
        salida = []
    if isinstance(obj, dict):
        if "label" in obj and ("value" in obj or "text" in obj):
            etiqueta = limpiar(obj.get("label"))
            valor = obj.get("value", obj.get("text"))
            if etiqueta:
                salida.append((etiqueta, valor))
        for v in obj.values():
            _pares(v, salida)
    elif isinstance(obj, list):
        for v in obj:
            _pares(v, salida)
    return salida


# Como se llaman en el archivo los datos del detalle. La clave es la
# etiqueta tal como la escribe Mercado Libre; sin tildes para que no
# dependa de como venga codificada.
ETIQUETAS = {
    "ID de envio": "envio",
    "Valor de la compra": "valor_compra",
    "Nombre del reclamante": "reclamante",
    "Designado para recibir": "designado",
    "ID de seguimiento": "seguimiento",
    "Mensaje del reclamo": "mensaje",
    "Fecha de entrega": "fecha_entrega",
    "Recibio": "recibio_quien",
    "Nombre completo": "recibio_nombre",
    "Documento": "recibio_documento",
    "Ruta": "ruta_detalle",
    "Transportadora": "transportadora",
    "Conductor": "conductor",
    "ID del conductor": "id_conductor",
    "Telefono": "telefono",
    "Geo de la foto": "geo_foto",
    "Geo de la direccion": "geo_direccion",
    "Distancia entre geolocalizaciones": "distancia_geo",
}


def sin_tildes(t):
    """Para comparar etiquetas sin depender de la codificacion."""
    reemplazos = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"),
                  ("ú", "u"), ("ñ", "n"), ("Á", "A"), ("É", "E"),
                  ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("Ñ", "N"))
    for a, b in reemplazos:
        t = t.replace(a, b)
    return t


def normalizar_detalle(det):
    """El objeto caseDetail convertido en campos planos."""
    if not det:
        return {}

    salida = {}

    # Los IDs con los que se cruza contra el padron y las rutas
    for r in det.get("references") or []:
        tipo = limpiar(r.get("reference_type"))
        valor = limpiar(r.get("value"))
        detalle = limpiar(r.get("detail"))
        if tipo == "DRIVER_ID":
            salida["id_conductor"] = valor
        elif tipo == "VEHICLE_ID":
            salida["id_vehiculo"] = valor
        elif tipo == "BUYER_USER_ID":
            salida["id_comprador"] = valor
        elif tipo == "CLAIM_ID":
            salida["id_reclamo"] = valor
        elif tipo == "ROUTE_ID":
            salida["ruta_detalle"] = valor
            if detalle:
                salida["nombre_ruta"] = detalle
        elif tipo == "CARRIER_ID":
            salida["transportadora"] = detalle or valor
            salida["id_transportadora"] = valor

    # Las tarjetas: reclamo, quien recibio, ruta, evidencias
    for etiqueta, valor in _pares(det):
        clave = ETIQUETAS.get(sin_tildes(etiqueta))
        if clave and not salida.get(clave):
            salida[clave] = limpiar(valor)

    # La fecha de entrega llega en ISO; se deja como en el resto
    fe = salida.get("fecha_entrega") or ""
    if len(fe) >= 16 and "T" in fe:
        salida["fecha_entrega"] = "%s/%s/%s %s" % (fe[8:10], fe[5:7],
                                                   fe[0:4], fe[11:16])

    # Los productos del envio, con su precio
    productos, precios = [], []
    for p in (det.get("pnrClaimConfig") or {}).get("products") or []:
        titulo = limpiar(p.get("title"))
        if titulo:
            productos.append(titulo)
            pago = p.get("payment") or {}
            if pago.get("amount") is not None:
                precios.append(str(pago["amount"]))
    if productos:
        salida["productos"] = " | ".join(productos)
        salida["precios_productos"] = " | ".join(precios)
        salida["cantidad_productos"] = str(len(productos))

    # Datos sueltos que solo estan en el detalle
    # billingPeriod llega vacio en la practica (los 357 casos de una
    # prueba real); el periodo de verdad es el que se pidio. Se conserva
    # por si algun caso lo trae, y guardar() omite la columna si no.
    salida["periodo_facturacion"] = limpiar(det.get("billingPeriod"))
    salida["prefactura"] = limpiar(det.get("preInvoiceNumber"))
    salida["estacion_destino"] = limpiar(det.get("origin"))
    salida["estado_detalle"] = limpiar(det.get("status"))
    if det.get("bulky"):
        salida["voluminoso"] = "Si"

    # La geo de la evidencia, con sus coordenadas crudas
    geo = (det.get("caseDataComponent") or {}).get("order.geo_incident_data")
    if isinstance(geo, dict):
        foto = geo.get("evidence_location") or {}
        parada = geo.get("stop_location") or {}
        if foto.get("latitude") or foto.get("longitude"):
            salida["lat_foto"] = str(foto.get("latitude", ""))
            salida["lon_foto"] = str(foto.get("longitude", ""))
        if parada.get("latitude") or parada.get("longitude"):
            salida["lat_parada"] = str(parada.get("latitude", ""))
            salida["lon_parada"] = str(parada.get("longitude", ""))
        if geo.get("distance"):
            salida["distancia_metros"] = str(geo.get("distance"))
        salida["evidencias"] = str(len(geo.get("evidences") or []))

    salida.update(_del_historial(det))
    return salida


# Los eventos que marcan cada paso del caso. MELI los nombra asi.
EVENTOS_CIERRE = ("UPDATE_STATUS_TO_CLOSED", "CLOSED", "CANCEL")
EVENTOS_REVISION = ("REVIEW", "REVISION", "UPDATE_STATUS_TO_ON_REVIEW",
                    "REQUEST_REVIEW", "ATTACHED_RECEIPT")


def _fecha_hora(iso):
    """2026-09-01T04:51:54Z -> 01/09/2026 04:51"""
    t = limpiar(iso)
    if len(t) >= 16 and "T" in t:
        return f"{t[8:10]}/{t[5:7]}/{t[0:4]} {t[11:16]}"
    return t


def _del_historial(det):
    """La fecha de cierre y el pedido de revision, de events y notes.

    El CSV que la plataforma generaba traia estas columnas; el boton ya
    no existe, asi que se arman desde el historial del propio caso.
    """
    salida = {}

    nota_de_evento = []
    for ev in det.get("_events") or []:
        tipo = limpiar(ev.get("event_type")).upper()
        cuando = _fecha_hora(ev.get("date_created"))
        if not cuando:
            continue
        # Se queda el ultimo de cada clase: un caso puede reabrirse
        if any(m in tipo for m in EVENTOS_CIERRE):
            salida["fecha_cierre"] = cuando
        elif any(m in tipo for m in EVENTOS_REVISION):
            salida["fecha_revision"] = cuando
        # Algunos eventos (ATTACHED_RECEIPT) llevan la nota dentro
        n = ev.get("note")
        if isinstance(n, dict):
            m = limpiar(n.get("message") or n.get("text"))
            if m:
                nota_de_evento.append(m)

    # Las notas son lo que se escribio al pedir la revision. El campo se
    # llama 'message' (no 'text'), y trae quien la escribio y sus adjuntos.
    textos, quienes, adjuntos = [], [], 0
    for nota in det.get("_notes") or []:
        if isinstance(nota, dict):
            t = limpiar(nota.get("message") or nota.get("text")
                        or nota.get("note") or nota.get("comment"))
            creador = nota.get("created_by")
            if isinstance(creador, dict):
                autor = limpiar(creador.get("name"))
                # Su user_id es el 'REP TRANSPORTADORA' del CSV original
                uid = limpiar(creador.get("user_id"))
                if uid and not salida.get("rep_transportadora"):
                    salida["rep_transportadora"] = uid
            else:
                autor = limpiar(creador)
            if autor and autor not in quienes:
                quienes.append(autor)
            adjuntos += len(nota.get("files") or [])
            if not salida.get("fecha_revision"):
                cuando = _fecha_hora(nota.get("date_created")
                                     or nota.get("dateCreated"))
                if cuando:
                    salida["fecha_revision"] = cuando
        else:
            t = limpiar(nota)
        if t:
            textos.append(t)
    # Si notes viene vacio pero un evento traia la nota, sirve igual
    if not textos and nota_de_evento:
        textos = nota_de_evento
    if textos:
        salida["pedido_revision"] = " | ".join(textos)
    if quienes:
        salida["rep_asistente"] = " | ".join(quienes)
    if adjuntos:
        salida["adjuntos"] = str(adjuntos)

    return salida


SCRIPT_LOTE_HTML = """
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
    // facil dejarla mal, lo que rompe el script entero con
    // 'Invalid or unexpected token'.
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
      if (!t) return {id: id, ok: false, json: null};
      // Recortar en el navegador: devolver 3 MB de HTML por caso
      // llenaria la memoria. Se manda solo lo que se usa (~7 KB).
      const ficha  = recortar(t, 'caseDetail', '{', '}');
      // events y notes viven FUERA de caseDetail: traen el historial
      // (creacion, revision, cierre) y el texto del pedido de revision.
      const evs    = recortar(t, 'events', '[', ']');
      const notas  = recortar(t, 'notes', '[', ']');
      t = null;
      return {id: id, ok: !!ficha, json: ficha,
              events: evs, notes: notas};
    })
    .catch(() => ({id: id, ok: false, json: null}))
)).then(done);
"""


def pedir_lote_detalles(driver, ids):
    """Pide varias fichas a la vez y devuelve {id: caseDetail}.

    El recorte se hace dentro del navegador: cada pagina pesa ~3 MB y
    traerlas enteras a Python agotaria la memoria de Chrome en un lote
    de 350 casos.
    """
    driver.set_script_timeout(180)
    respuestas = driver.execute_async_script(
        SCRIPT_LOTE_HTML, URL_DETALLE, [str(i) for i in ids])

    salida = {}
    for r in respuestas or []:
        if not r or not r.get("ok") or not r.get("json"):
            continue
        try:
            ficha = json.loads(r["json"])
        except ValueError:
            continue
        # events y notes se guardan dentro de la ficha, con un nombre que
        # no pisa nada de MELI, para que normalizar_detalle los vea.
        for clave, campo in (("events", "_events"), ("notes", "_notes")):
            crudo = r.get(clave)
            if crudo:
                try:
                    ficha[campo] = json.loads(crudo)
                except ValueError:
                    pass
        salida[str(r.get("id"))] = ficha
    return salida


def completar_detalles(driver, registros, avisar=None):
    """Trae el detalle de cada caso y lo suma a su registro.

    Devuelve cuantos se completaron. Los que fallen se reintentan en
    lotes mas chicos: casi siempre es intermitencia, no un caso roto.
    """
    avisar = avisar or (lambda *a: None)
    porhacer = [r for r in registros if r.get("caso")]
    if not porhacer:
        return 0

    # El fetch se lanza desde la pagina: si el navegador quedo en otra
    # parte, la politica de origen lo bloquea y fallan TODOS en silencio.
    preparar_pagina(driver)

    por_id = {r["caso"]: r for r in porhacer}
    hechos = 0
    faltan = list(por_id.keys())

    for vuelta in range(REINTENTOS_DETALLE + 1):
        if not faltan:
            break
        # Cada reintento va con lotes mas chicos y mas pausa
        tam = max(2, LOTE_DETALLES // (vuelta + 1))
        pausa = PAUSA_DETALLES * (vuelta + 1)
        if vuelta:
            log(f"Reintento {vuelta}: {len(faltan)} casos en lotes de {tam}")

        pendientes = faltan
        faltan = []
        fallo_dicho = False
        for i in range(0, len(pendientes), tam):
            lote = pendientes[i:i + tam]
            try:
                fichas = pedir_lote_detalles(driver, lote)
            except Exception as e:
                # Callar el error deja 357 ceros sin explicacion. Se dice
                # una vez por vuelta: repetirlo 60 veces tampoco ayuda.
                texto = str(e)
                if not fallo_dicho:
                    log(f"Fallo al pedir el detalle: {texto[:160]}")
                    fallo_dicho = True
                if ("out of memory" in texto.lower()
                        or "frame detached" in texto.lower()):
                    log("Chrome se quedo sin memoria; liberando...")
                    _liberar_memoria(driver)
                fichas = {}

            for cid in lote:
                det = fichas.get(cid)
                if det:
                    por_id[cid].update(normalizar_detalle(det))
                    hechos += 1
                else:
                    faltan.append(cid)

            avisar(f"detalles {hechos}/{len(por_id)}")
            if hechos % 60 < tam:
                log(f"Detalles: {hechos}/{len(por_id)}")
            time.sleep(pausa)

    if faltan:
        log(f"{len(faltan)} casos no devolvieron detalle.")
    return hechos


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

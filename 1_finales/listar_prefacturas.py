# -*- coding: utf-8 -*-
"""
Lista las prefacturas para poder elegir por mes y Q, sin saberse el numero.

API descubierta espiando el listado:
    GET /logistics/billing/api/pre-invoices
        ?page=1&sort_by=id&sort_type=desc&userType=3PL&carrier_id=<id>

Cada prefactura trae lo que hace falta para filtrar:
    id, type (regular/complementary), step_type (last_mile/line_haul),
    period.name (202607Q2), period.date_from / date_to, total_cost, status
"""

import json
import time
from datetime import datetime

API = "https://envios.adminml.com/logistics/billing/api/pre-invoices"

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Como se ven los valores de la API en la pantalla
TIPOS = {"regular": "Regular", "complementary": "Complementaria"}
MILLAS = {"last_mile": "Last Mile", "line_haul": "Line Haul",
          "first_mile": "First Mile"}
ESTADOS = {
    "approved": "Aprobada", "paid": "Pagada", "to_pay": "Por pagar",
    "payment_sent": "Pago enviado", "payment_in_process": "Pago en proceso",
    "to_approve": "Por aprobar", "invoiced": "Facturada",
    "to_account": "Por contabilizar", "cancelled": "Cancelada",
}


def limpiar(v):
    if v is None:
        return ""
    return " ".join(str(v).split()).strip()


def bonito(valor, tabla):
    """De 'last_mile' a 'Last Mile'; si no esta en la tabla, se deja igual."""
    v = limpiar(valor).lower()
    return tabla.get(v, limpiar(valor))


def periodo_legible(nombre):
    """'202607Q2' -> 'Julio 2026 · Q2'"""
    n = limpiar(nombre)
    if len(n) >= 8 and n[4:6].isdigit() and n[:4].isdigit():
        anio, mes, q = n[:4], int(n[4:6]), n[6:]
        if 1 <= mes <= 12:
            return f"{MESES[mes - 1]} {anio} · {q}"
    return n


def llamar(driver, url):
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials: 'include',
                headers: {'Accept': 'application/json, text/plain, */*'}})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url)


def bajar_lista(driver, carrier_id="", max_paginas=14, log=print):
    """Trae las prefacturas, de la mas reciente a la mas vieja."""
    prefacturas = []
    vistos = set()

    for pagina in range(1, max_paginas + 1):
        url = (f"{API}?page={pagina}&sort_by=id&sort_type=desc"
               f"&userType=3PL")
        if carrier_id:
            url += f"&carrier_id={carrier_id}"

        r = llamar(driver, url)
        if r.get("status") != 200:
            if pagina == 1:
                raise RuntimeError(
                    f"El listado respondio {r.get('status')}. "
                    "Revisa que la sesion siga activa."
                )
            break

        datos = json.loads(r["body"])
        lote = datos.get("pre_invoices") or []
        if not lote:
            break

        for p in lote:
            if not isinstance(p, dict) or p.get("id") in vistos:
                continue
            vistos.add(p.get("id"))
            periodo = p.get("period") or {}
            prefacturas.append({
                "id": limpiar(p.get("id")),
                "tipo": limpiar(p.get("type")).lower(),
                "milla": limpiar(p.get("step_type")).lower(),
                "periodo": limpiar(periodo.get("name")),
                "desde": limpiar(periodo.get("date_from"))[:10],
                "hasta": limpiar(periodo.get("date_to"))[:10],
                "orden": periodo.get("order"),
                "total": p.get("total_cost") or 0,
                "estado": limpiar(p.get("status")).lower(),
                "creada": limpiar(p.get("date_created"))[:10],
            })

        # La pagina 1 dice cuantas hay en total
        info = datos.get("page") or {}
        total = info.get("total")
        if total and pagina >= total:
            break
        time.sleep(0.25)

    log(f"  {len(prefacturas)} prefacturas en el listado")
    return prefacturas


def periodos_de(prefacturas, tipo="regular", milla="last_mile"):
    """Los periodos que tienen prefactura del tipo y milla pedidos.

    Devuelve una lista de (periodo, [prefacturas]), de la mas reciente a la
    mas vieja, para llenar los desplegables.
    """
    por_periodo = {}
    for p in prefacturas:
        if tipo and p["tipo"] != tipo:
            continue
        if milla and p["milla"] != milla:
            continue
        if not p["periodo"]:
            continue
        por_periodo.setdefault(p["periodo"], []).append(p)

    # 202607Q2 ordena bien como texto: año, mes y Q en ese orden
    return [(k, por_periodo[k]) for k in sorted(por_periodo, reverse=True)]


def meses_disponibles(prefacturas, tipo="regular", milla="last_mile"):
    """Los meses con prefactura, del mas reciente al mas viejo.

    Devuelve [(clave, etiqueta)], ej. [("202607", "Julio 2026"), ...]
    """
    meses = {}
    for periodo, lista in periodos_de(prefacturas, tipo, milla):
        if len(periodo) >= 6:
            clave = periodo[:6]
            if clave not in meses:
                anio, mes = clave[:4], int(clave[4:6])
                if 1 <= mes <= 12:
                    meses[clave] = f"{MESES[mes - 1]} {anio}"
    return [(k, meses[k]) for k in sorted(meses, reverse=True)]


def quincenas_de_mes(prefacturas, mes, tipo="regular", milla="last_mile"):
    """Los Q disponibles de un mes: [("Q2", [prefacturas]), ("Q1", [...])]"""
    salida = []
    for periodo, lista in periodos_de(prefacturas, tipo, milla):
        if periodo.startswith(mes):
            salida.append((periodo[6:] or "Q1", lista))
    return salida


def mas_reciente(prefacturas, tipo="regular", milla="last_mile"):
    """La prefactura mas reciente que cumpla el filtro.

    Es lo que conviene preseleccionar al abrir el programa: casi siempre es
    la que se quiere descargar.
    """
    periodos = periodos_de(prefacturas, tipo, milla)
    if not periodos:
        return None
    periodo, lista = periodos[0]
    # Dentro del periodo, la de id mas alto es la ultima emitida
    return sorted(lista, key=lambda p: int(p["id"] or 0), reverse=True)[0]


def describir(p):
    """'#6595499 · Regular · Last Mile · 7,151,826.56 MXN · Por pagar'"""
    if not p:
        return ""
    partes = [f"#{p['id']}", bonito(p["tipo"], TIPOS),
              bonito(p["milla"], MILLAS)]
    try:
        partes.append(f"{float(p['total']):,.2f} MXN")
    except (ValueError, TypeError):
        pass
    if p.get("estado"):
        partes.append(bonito(p["estado"], ESTADOS))
    return "  ·  ".join(partes)

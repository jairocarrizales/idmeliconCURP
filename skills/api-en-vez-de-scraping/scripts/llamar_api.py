# -*- coding: utf-8 -*-
"""
Llamar la API desde dentro de la pagina, reusando la sesion del navegador.

Copia estas funciones a tu extractor. Ninguna lee ni guarda credenciales:
el navegador adjunta cookies y tokens solo, gracias a credentials:'include'.
"""

import json
import time
from urllib.parse import quote


# --------------------------------------------------------------- una llamada
def llamar(driver, url, metodo="GET", cuerpo=None):
    """GET o POST que devuelve texto. Lanza excepcion si no responde 200.

    OJO: NO recortes el cuerpo dentro del JS. Si lo haces, json.loads falla
    con 'Unterminated string' al partir el JSON a la mitad. Recorta al
    imprimir, nunca antes de parsear.
    """
    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include',
                headers: {'Accept': 'application/json, text/plain, */*'}};
    if (cuerpo !== null) {
      op.headers['Content-Type'] = 'application/json';
      op.body = cuerpo;
    }
    fetch(url, op)
      .then(r => r.text().then(t => done({status: r.status, body: t,
                                          tipo: r.headers.get('content-type')})))
      .catch(e => done({status: 0, body: String(e), tipo: ''}));
    """
    driver.set_script_timeout(120)
    resp = driver.execute_async_script(script, url, metodo, cuerpo)

    estado = resp.get("status")
    if estado != 200:
        muestra = (resp.get("body") or "")[:200]
        if "failed to fetch" in muestra.lower() or estado == 0:
            raise RuntimeError(
                "El navegador bloqueo la consulta: la pagina actual no es del "
                "mismo dominio que la API. Navega al panel antes de llamar."
            )
        raise RuntimeError(f"La API respondio {estado}: {muestra}")
    return resp["body"]


def llamar_json(driver, url, metodo="GET", cuerpo=None):
    texto = llamar(driver, url, metodo, cuerpo)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"La respuesta no es JSON (quiza caduco la sesion). "
            f"Empieza con: {texto[:120]}"
        )


# ------------------------------------------------------------------ binarios
def llamar_binario(driver, url, metodo="GET", cuerpo=None):
    """Para XLSX, PDF, ZIP: los trae en base64 y devuelve bytes.

    Pasarlos como texto los corrompe. Señal de que paso: el contenido empieza
    con 'PK' o se ve como caracteres raros.
    """
    import base64

    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include'};
    if (cuerpo !== null) {
      op.headers = {'Content-Type': 'application/json'};
      op.body = cuerpo;
    }
    fetch(url, op).then(r => r.blob().then(b => {
      const lector = new FileReader();
      lector.onloadend = () => done({status: r.status,
                                     b64: lector.result.split(',')[1] || ''});
      lector.onerror = () => done({status: r.status, b64: ''});
      lector.readAsDataURL(b);
    })).catch(e => done({status: 0, b64: '', error: String(e)}));
    """
    driver.set_script_timeout(180)
    resp = driver.execute_async_script(script, url, metodo, cuerpo)
    if resp.get("status") != 200 or not resp.get("b64"):
        raise RuntimeError(f"La descarga respondio {resp.get('status')}.")
    return base64.b64decode(resp["b64"])


# ---------------------------------------------------------------- paginacion
def paginar_por_cursor(driver, url_base, params=None, pausa=0.4,
                       max_paginas=500, log=print):
    """Recorre una API paginada por cursor y devuelve todos los registros.

    Espera respuestas con la forma:
        {"pagination": {"cursor": "...", "has_next": true}, "result": [...]}
    """
    registros, vistos, cursor, pagina = [], set(), None, 0
    params = params or []

    while pagina < max_paginas:
        pagina += 1
        partes = list(params)
        if cursor:
            # El cursor suele venir en base64 y terminar en '=': hay que
            # escaparlo o la URL se corrompe en silencio.
            partes.append("cursor=" + quote(str(cursor), safe=""))
        url = url_base + ("?" + "&".join(partes) if partes else "")

        datos = llamar_json(driver, url)
        lote = datos.get("result") or datos.get("results") or []
        if not isinstance(lote, list):
            log(f"Respuesta inesperada en la pagina {pagina}; se detiene.")
            break

        nuevos = 0
        for item in lote:
            if not isinstance(item, dict):
                continue
            clave = item.get("id")
            if clave is not None and clave in vistos:
                continue                     # dos paginas traslapadas
            if clave is not None:
                vistos.add(clave)
            registros.append(item)
            nuevos += 1

        log(f"Pagina {pagina}: +{nuevos} (total {len(registros)})")

        paginacion = datos.get("pagination") or {}
        if not paginacion.get("has_next"):
            break
        siguiente = paginacion.get("cursor")
        if not siguiente or siguiente == cursor:
            log("El cursor dejo de avanzar; se detiene.")
            break
        cursor = siguiente
        time.sleep(pausa)

    if pagina >= max_paginas:
        log(f"AVISO: se alcanzo el tope de {max_paginas} paginas.")
    return registros


# ------------------------------------------------------------------- lotes
def pedir_lote(driver, url_base, ids):
    """Pide varias fichas a la vez. Devuelve {id: datos} solo de las que ok.

    El tiempo lo domina la latencia, asi que el paralelismo es donde esta la
    ganancia: medido, 12 a la vez rinde 4x sobre una por una.
    """
    script = """
    const [base, ids] = arguments;
    const done = arguments[arguments.length - 1];
    Promise.all(ids.map(id =>
      fetch(base + id, {credentials:'include', headers:{'Accept':'application/json'}})
        .then(r => r.ok ? r.json() : null)
        .then(j => ({id: id, ok: !!j, data: j}))
        .catch(() => ({id: id, ok: false, data: null}))
    )).then(done);
    """
    driver.set_script_timeout(120)
    respuestas = driver.execute_async_script(script, url_base, list(ids))
    return {str(r["id"]): r["data"] for r in (respuestas or [])
            if r and r.get("ok")}


def completar_en_lotes(driver, url_base, ids, tamano=12, pausa=0.2,
                       reintentos=2, log=print):
    """Pide muchas fichas en lotes, con reintentos para las que fallen."""
    resultado, faltantes = {}, []
    total = len(ids)

    for i in range(0, total, tamano):
        lote = list(ids)[i:i + tamano]
        try:
            datos = pedir_lote(driver, url_base, lote)
        except Exception as e:
            log(f"  Lote fallido: {str(e)[:70]}")
            faltantes.extend(lote)
            continue
        resultado.update(datos)
        faltantes.extend([x for x in lote if str(x) not in datos])
        if (i + tamano) % 120 < tamano:
            log(f"  {min(i + tamano, total)}/{total}")
        time.sleep(pausa)

    # Una ficha puede fallar por intermitencia: reintentar mas suave
    for vuelta in range(1, reintentos + 1):
        if not faltantes:
            break
        log(f"Reintento {vuelta}: {len(faltantes)} sin respuesta...")
        time.sleep(1.5)
        quedan, paso = [], max(3, tamano // 2)
        for i in range(0, len(faltantes), paso):
            lote = faltantes[i:i + paso]
            try:
                datos = pedir_lote(driver, url_base, lote)
            except Exception:
                quedan.extend(lote)
                continue
            resultado.update(datos)
            quedan.extend([x for x in lote if str(x) not in datos])
            time.sleep(pausa * 2)
        log(f"  Recuperadas {len(faltantes) - len(quedan)}")
        faltantes = quedan

    return resultado, faltantes

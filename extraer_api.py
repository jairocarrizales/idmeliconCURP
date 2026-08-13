# -*- coding: utf-8 -*-
"""
Extractor de drivers por API - Mercado Libre Envios

Version rapida: en lugar de presionar "Mostrar mas" cientos de veces, llama
directo a la API que alimenta la tabla:

    /logistics/provider-management/api/drivers/drivers-and-invites

Abre Chrome, espera tu login, y luego pagina la API por cursor hasta traer
todos los registros. Tarda segundos en lugar de minutos.

El ID viene incluido en la respuesta, asi que no hay que abrir ningun perfil.
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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://envios.adminml.com/logistics/provider-management/drivers"
API = (
    "https://envios.adminml.com/logistics/provider-management/api/drivers/"
    "drivers-and-invites"
)

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Pausa entre llamadas: no conviene atosigar al servidor
PAUSA = 0.4
# Tope de vueltas, por si la paginacion nunca dijera has_next=false
MAX_PAGINAS = 500

# Como se traduce el status de la API a algo legible
ESTATUS = {
    "active": "Activo",
    "inactive": "Inactivo",
    "blocked": "Bloqueado",
    "pending": "Registro pendiente",
    "paused": "Pausado",
    "deleted": "Eliminado",
    # Las invitaciones enviadas pero no completadas llegan con estos estados
    "sent": "Registro pendiente",
    "invited": "Registro pendiente",
    "expired": "Invitacion vencida",
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(texto):
    if texto is None:
        return ""
    texto = str(texto).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(texto.split()).strip()


def limpiar_lock():
    """Libera el perfil si quedo bloqueado por un cierre a la fuerza."""
    if not os.path.isdir(PROFILE_DIR):
        return
    for nombre in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        for ruta in (
            os.path.join(PROFILE_DIR, nombre),
            os.path.join(PROFILE_DIR, "Default", nombre),
        ):
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
            except Exception:
                pass


def crear_driver():
    limpiar_lock()
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-MX")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    try:
        return webdriver.Chrome(options=opts)
    except Exception as e:
        if "user data directory is already in use" in str(e).lower():
            log("ERROR: el perfil de Chrome esta en uso por otra ventana.")
            log("Cierra las ventanas que abrio este programa y reintenta.")
            log(f"Si sigue igual, borra la carpeta: {PROFILE_DIR}")
        raise


def llamar_api(driver, cursor=None):
    """Llama la API desde el propio navegador, reusando su sesion.

    Usamos fetch() dentro de la pagina para que Chrome adjunte las cookies
    solo; asi no hay que extraer ni manipular tokens.
    """
    params = [
        "status=active,inactive,blocked",
        "paginated=true",
    ]
    if cursor:
        # El cursor viene en base64 y puede traer '='; hay que escaparlo
        from urllib.parse import quote

        params.append("cursor=" + quote(str(cursor), safe=""))

    url = API + "?" + "&".join(params)

    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}})
      .then(r => r.text().then(t => done({ok: r.ok, status: r.status, body: t})))
      .catch(e => done({ok: false, status: 0, body: String(e)}));
    """
    driver.set_script_timeout(60)
    resp = driver.execute_async_script(script, url)

    if not resp or not resp.get("ok"):
        estado = resp.get("status") if resp else "?"
        cuerpo = (resp.get("body") or "")[:200] if resp else ""
        raise RuntimeError(f"La API respondio {estado}: {cuerpo}")

    try:
        return json.loads(resp["body"])
    except json.JSONDecodeError:
        raise RuntimeError(
            "La API no devolvio JSON (quiza la sesion caduco). "
            f"Empieza con: {resp['body'][:120]}"
        )


def fecha_legible(epoch):
    """La API manda la fecha como segundos epoch."""
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%d/%m/%Y")
    except (ValueError, OSError, OverflowError):
        return ""


def motivo_bloqueo(bloqueo):
    """blockingReason a veces trae el porque del bloqueo."""
    if not isinstance(bloqueo, dict) or not bloqueo:
        return ""
    for clave in ("reason", "description", "detail", "message", "type", "name"):
        if bloqueo.get(clave):
            return limpiar(bloqueo[clave])
    # Si no reconocemos la forma, mostramos lo que haya
    return limpiar(json.dumps(bloqueo, ensure_ascii=False))[:120]


def normalizar(item):
    """Convierte un registro de la API a las columnas que exportamos."""
    nombre = limpiar(
        f"{item.get('firstName') or ''} {item.get('lastName') or ''}"
    )

    # Los registros pendientes vienen como invitaciones: sin nombre, con correo
    email = limpiar(item.get("email") or item.get("invitedEmail") or "")
    if not nombre and email:
        nombre = email

    estado_api = limpiar(item.get("status")).lower()
    estatus = ESTATUS.get(estado_api, limpiar(item.get("status")) or "")

    # Un driver puede venir active pero con disabled=true
    if item.get("disabled") and estado_api == "active":
        estatus = "Activo (deshabilitado)"

    curp = ""
    if limpiar(item.get("identificationType")).upper() == "CURP":
        curp = limpiar(item.get("identificationValue")).upper()
    else:
        curp = limpiar(item.get("identificationValue")).upper()

    return {
        "id": limpiar(item.get("id")),
        "nombre": nombre,
        "curp": curp,
        "estatus": estatus,
        "observacion": motivo_bloqueo(item.get("blockingReason")),
        "telefono": limpiar(item.get("phone") or item.get("phoneNumber") or ""),
        "email": email,
        "tipo": "Ayudante" if item.get("isOnlyHelper") else "Transportista",
        "fecha": fecha_legible(item.get("creationDate")),
        "carrier": limpiar(item.get("carrierId")),
    }


def extraer_todo(driver):
    """Pagina la API por cursor hasta agotar los registros."""
    registros = []
    vistos = set()
    cursor = None
    pagina = 0

    while pagina < MAX_PAGINAS:
        pagina += 1
        datos = llamar_api(driver, cursor)

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
                continue
            if clave is not None:
                vistos.add(clave)
            registros.append(normalizar(item))
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

        time.sleep(PAUSA)

    if pagina >= MAX_PAGINAS:
        log(f"AVISO: se alcanzo el tope de {MAX_PAGINAS} paginas.")

    # Numerar al final
    for i, r in enumerate(registros, start=1):
        r["n"] = i

    return registros


def guardar(registros):
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_txt = os.path.join(BASE_DIR, f"drivers_meli_{sello}.txt")
    ruta_csv = os.path.join(BASE_DIR, f"drivers_meli_{sello}.csv")

    encabezados = [
        "#",
        "ID",
        "Nombre",
        "CURP",
        "Estatus",
        "Observacion",
        "Telefono",
        "E-mail",
        "Tipo",
        "Fecha creacion",
    ]

    def campos(r):
        return [
            str(r.get("n", "")),
            r.get("id", ""),
            r.get("nombre", ""),
            r.get("curp", ""),
            r.get("estatus", ""),
            r.get("observacion", ""),
            r.get("telefono", ""),
            r.get("email", ""),
            r.get("tipo", ""),
            r.get("fecha", ""),
        ]

    # TXT con tabs -> se pega directo en Excel. utf-8-sig para los acentos.
    with open(ruta_txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(encabezados) + "\n")
        for r in registros:
            f.write("\t".join(campos(r)) + "\n")

    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(encabezados)
        for r in registros:
            w.writerow(campos(r))

    return ruta_txt, ruta_csv


def main():
    print("=" * 70)
    print("  EXTRACTOR DE DRIVERS POR API - MERCADO LIBRE ENVIOS")
    print("=" * 70)
    print()
    print("  Version rapida: consulta directo la API de la tabla.")
    print("  Trae ID, nombre, CURP y estatus sin abrir perfiles.")
    print()

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(URL)

        print("-" * 70)
        print("  1) Inicia sesion en la ventana de Chrome.")
        print("  2) Espera a ver la LISTA DE DRIVERS.")
        print("  3) Regresa aqui y presiona ENTER.")
        print("-" * 70)
        input("\n>>> ENTER cuando veas la lista... ")

        if "provider-management" not in driver.current_url:
            log("Volviendo a la pagina de drivers...")
            driver.get(URL)
            time.sleep(3)

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
        except Exception:
            log("No se vieron filas; intentamos la API de todos modos.")

        log("Consultando la API...")
        inicio = time.time()
        registros = extraer_todo(driver)
        segundos = time.time() - inicio

        if not registros:
            log("La API no devolvio registros.")
            input(">>> ENTER para cerrar... ")
            return

        txt, csv_path = guardar(registros)

        conteo = {}
        for r in registros:
            clave = r.get("estatus") or "(sin estatus)"
            conteo[clave] = conteo.get(clave, 0) + 1

        n_id = sum(1 for r in registros if r.get("id"))
        n_curp = sum(1 for r in registros if r.get("curp"))
        n_tel = sum(1 for r in registros if r.get("telefono"))
        n_mail = sum(1 for r in registros if r.get("email"))

        print()
        print("=" * 70)
        print(f"  LISTO. {len(registros)} drivers en {segundos:.1f} segundos.")
        print()
        for clave in sorted(conteo, key=lambda k: -conteo[k]):
            print(f"    {clave:<24} {conteo[clave]}")
        print()
        print(f"    Con ID                   {n_id}/{len(registros)}")
        print(f"    Con CURP                 {n_curp}/{len(registros)}")
        print(f"    Con telefono             {n_tel}/{len(registros)}")
        print(f"    Con e-mail               {n_mail}/{len(registros)}")
        print()
        if not n_tel:
            print("    Nota: la API del listado no devuelve telefono ni e-mail")
            print("    de los drivers activos; solo estan en la ficha individual.")
            print("    Usa ProbarPerfilAPI.exe para buscar la API de la ficha.")
            print()
        print(f"  TXT (tabs, para Excel): {txt}")
        print(f"  CSV (punto y coma)    : {csv_path}")
        print("=" * 70)

    except KeyboardInterrupt:
        log("Interrumpido por el usuario.")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
    finally:
        input("\n>>> ENTER para cerrar el navegador... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Extractor de prefacturas CON el ID del conductor.

El CSV que descarga el panel trae el nombre del conductor pero no su ID,
asi que dos personas con el mismo nombre son indistinguibles. Este programa
resuelve eso cruzando por NUMERO, no por texto:

  1. POST /logistics/billing/api/pre-invoices/<id>/reports/details
     -> detalle con external_route_id (ID de ruta) y driver_name

  2. GET  /api/carriers/reports?mile=LM&init_date=..&end_date=..
     -> XLSX con "Id de la ruta" + "Id del transportista"

  3. drivers_meli_*.txt (del extractor de drivers)
     -> CURP, telefono y estatus de cada ID

La cadena queda:  ruta -> id de usuario -> CURP
sin depender de los nombres en ningun paso.
"""

import io
import os
import re
import csv
import sys
import json
import time
import base64
import zipfile
import glob
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

WEB = "https://envios.adminml.com/logistics/billing/invoices/"
API_DETALLE = (
    "https://envios.adminml.com/logistics/billing/api/pre-invoices/"
    "{id}/reports/details"
)
API_REPORTE = "https://envios.adminml.com/api/carriers/reports"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Los periodos de MELI: Q1 = del 1 al 15, Q2 = del 16 al fin de mes
RE_PERIODO = re.compile(r"^(\d{4})(\d{2})Q(\d)$")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(v):
    if v is None:
        return ""
    t = str(v).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(t.split()).strip()


# ------------------------------------------------------------------ Chrome
def cerrar_chrome_huerfano():
    if os.name != "nt":
        return
    marca = os.path.basename(PROFILE_DIR)
    proyecto = os.path.basename(os.path.dirname(PROFILE_DIR))
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{proyecto}*' -and "
        f"$_.CommandLine -like '*{marca}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue }"
    )
    try:
        import subprocess

        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)
    except Exception:
        pass


def crear_driver():
    if os.path.isdir(PROFILE_DIR):
        cerrar_chrome_huerfano()
        for n in ("lockfile", "LOCK", "SingletonLock", "SingletonCookie",
                  "SingletonSocket", "DevToolsActivePort"):
            for c in (PROFILE_DIR, os.path.join(PROFILE_DIR, "Default")):
                try:
                    p = os.path.join(c, n)
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

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
            log(f"Cierra esas ventanas o borra: {PROFILE_DIR}")
        raise


def llamar(driver, url, metodo="GET", cuerpo=None, binario=False):
    """Llama la API desde la pagina, reusando su sesion.

    Con binario=True devuelve el contenido en base64: el XLSX no sobrevive
    si se pasa como texto.
    """
    if binario:
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
    else:
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
          .then(r => r.text().then(t => done({status: r.status, body: t})))
          .catch(e => done({status: 0, body: String(e)}));
        """
    driver.set_script_timeout(180)
    return driver.execute_async_script(script, url, metodo, cuerpo)


# ------------------------------------------------------- lectura del XLSX
def leer_xlsx(datos):
    """Lee un XLSX sin openpyxl: es un ZIP con XML adentro.

    Se hace a mano para no cargar una dependencia extra en el ejecutable.
    Devuelve (encabezados, filas).
    """
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        # Cadenas compartidas: las celdas de texto apuntan aqui por indice
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S):
                texto = "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
                compartidas.append(
                    texto.replace("&amp;", "&").replace("&lt;", "<")
                    .replace("&gt;", ">").replace("&quot;", '"')
                    .replace("&#39;", "'")
                )

        hojas = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        if not hojas:
            return [], []
        xml = z.read(sorted(hojas)[0]).decode("utf-8", "replace")

    filas = []
    for fila_xml in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
        celdas = {}
        for celda in re.findall(r"<c\s+([^>]*)>(.*?)</c>|<c\s+([^>]*)/>",
                                fila_xml, re.S):
            attrs = celda[0] or celda[2] or ""
            contenido = celda[1] or ""
            ref = re.search(r'r="([A-Z]+)\d+"', attrs)
            if not ref:
                continue
            # Columna A=0, B=1, ... AA=26
            col = 0
            for ch in ref.group(1):
                col = col * 26 + (ord(ch) - 64)
            col -= 1

            valor = ""
            v = re.search(r"<v>(.*?)</v>", contenido, re.S)
            if v:
                valor = v.group(1)
                if 't="s"' in attrs:           # indice a sharedStrings
                    try:
                        valor = compartidas[int(valor)]
                    except (ValueError, IndexError):
                        pass
            else:
                t = re.search(r"<t[^>]*>(.*?)</t>", contenido, re.S)
                if t:
                    valor = t.group(1)
            celdas[col] = valor

        if celdas:
            ancho = max(celdas) + 1
            filas.append([celdas.get(i, "") for i in range(ancho)])

    if not filas:
        return [], []
    return filas[0], filas[1:]


def periodo_a_fechas(periodo):
    """'202607Q1' -> ('2026-07-01', '2026-07-15')"""
    m = RE_PERIODO.match(limpiar(periodo))
    if not m:
        return None, None
    anio, mes, q = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if q == 1:
        return f"{anio}-{mes:02d}-01", f"{anio}-{mes:02d}-15"
    # Q2: del 16 al ultimo dia del mes
    import calendar

    ultimo = calendar.monthrange(anio, mes)[1]
    return f"{anio}-{mes:02d}-16", f"{anio}-{mes:02d}-{ultimo}"


# ------------------------------------------------------------- el padron
def cargar_padron():
    """Lee el drivers_meli_*.txt mas reciente: id -> datos del driver."""
    archivos = sorted(glob.glob(os.path.join(BASE_DIR, "drivers_meli_*.txt")))
    if not archivos:
        return {}, None

    ruta = archivos[-1]
    padron = {}
    try:
        with io.open(ruta, encoding="utf-8-sig") as f:
            cab = f.readline().rstrip("\n").split("\t")
            idx = {c.strip().lower(): i for i, c in enumerate(cab)}
            i_id = idx.get("id", 0)
            i_nom = idx.get("nombre", 1)
            i_curp = idx.get("curp", 2)
            i_est = idx.get("estatus", 3)
            i_tel = idx.get("telefono", 4)
            i_mail = idx.get("e-mail", 5)
            for linea in f:
                c = linea.rstrip("\n").split("\t")
                if len(c) <= i_id or not c[i_id].strip():
                    continue
                padron[c[i_id].strip()] = {
                    "nombre": c[i_nom] if len(c) > i_nom else "",
                    "curp": c[i_curp] if len(c) > i_curp else "",
                    "estatus": c[i_est] if len(c) > i_est else "",
                    "telefono": c[i_tel] if len(c) > i_tel else "",
                    "email": c[i_mail] if len(c) > i_mail else "",
                }
    except Exception as e:
        log(f"No se pudo leer el padron: {e}")
        return {}, ruta
    return padron, ruta


# --------------------------------------------------------------- extraer
def bajar_detalle(driver, id_pref):
    """El detalle de la prefactura, ya aplanado a una fila por servicio."""
    log(f"Pidiendo el detalle de la prefactura {id_pref}...")
    r = llamar(driver, API_DETALLE.format(id=id_pref), "POST",
               '{"tolls_items":null}')
    if r.get("status") != 200:
        raise RuntimeError(
            f"El detalle respondio {r.get('status')}. "
            "Revisa que la sesion siga activa."
        )
    datos = json.loads(r["body"])

    periodo = limpiar(datos.get("period_name"))
    filas = []
    for item in datos.get("items") or []:
        base = {
            "concepto": limpiar(item.get("description")),
            "tipo": limpiar((item.get("item_type") or {}).get("name")),
            "operacion": limpiar((item.get("item_type") or {}).get("operation")),
            "subtipo": limpiar(item.get("sub_type")),
        }
        detalles = item.get("details") or []
        if not detalles:
            # Item sin desglose: se conserva como una fila
            filas.append(dict(base, ruta="", placa="", vehiculo_id="",
                              conductor="", fecha_ini="", fecha_fin="",
                              cantidad=limpiar(item.get("amount")),
                              costo=limpiar(item.get("cost")),
                              total=limpiar(item.get("total_cost"))))
            continue

        for d in detalles:
            filas.append(dict(
                base,
                ruta=limpiar(d.get("external_route_id")),
                placa=limpiar(d.get("vehicle_license_plate")),
                vehiculo_id=limpiar(d.get("vehicle_id")),
                conductor=limpiar(d.get("driver_name")),
                fecha_ini=limpiar(d.get("init_date")),
                fecha_fin=limpiar(d.get("finish_date")),
                cantidad=limpiar(d.get("amount")),
                costo=limpiar(d.get("cost")),
                total=limpiar(d.get("total_cost") or d.get("cost")),
            ))

    log(f"  {len(filas)} lineas de detalle, periodo {periodo}")
    return filas, periodo, datos


def bajar_mapa_rutas(driver, desde, hasta):
    """Reporte de operacion -> {id_ruta: id_conductor}."""
    url = (f"{API_REPORTE}?mile=LM&init_date={desde}"
           f"&end_date={hasta}&report_type=carrier")
    log(f"Pidiendo el reporte de operacion {desde} a {hasta}...")

    r = llamar(driver, url, binario=True)
    if r.get("status") != 200 or not r.get("b64"):
        raise RuntimeError(f"El reporte respondio {r.get('status')}.")

    datos = base64.b64decode(r["b64"])
    log(f"  Recibidos {len(datos)} bytes")

    cab, filas = leer_xlsx(datos)
    if not cab:
        raise RuntimeError("El XLSX del reporte llego vacio.")

    idx = {limpiar(c).lower(): i for i, c in enumerate(cab)}

    def buscar(*claves):
        for c in claves:
            if c in idx:
                return idx[c]
        for k, i in idx.items():
            if any(c in k for c in claves):
                return i
        return None

    i_ruta = buscar("id de la ruta", "route id", "id ruta")
    i_drv = buscar("id del transportista", "driver id", "id transportista")
    i_nom = buscar("nombre del transportista", "driver name")

    if i_ruta is None or i_drv is None:
        raise RuntimeError(
            f"El reporte no trae las columnas esperadas. Tiene: {', '.join(cab[:12])}"
        )

    mapa = {}
    for f in filas:
        if len(f) > max(i_ruta, i_drv) and limpiar(f[i_ruta]):
            mapa[limpiar(f[i_ruta])] = {
                "id": limpiar(f[i_drv]),
                "nombre": limpiar(f[i_nom]) if i_nom is not None and len(f) > i_nom else "",
            }

    log(f"  {len(mapa)} rutas con su transportista")
    return mapa


def guardar(filas, id_pref):
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"billing_{id_pref}_{sello}"
    ruta_txt = os.path.join(BASE_DIR, base + ".txt")
    ruta_csv = os.path.join(BASE_DIR, base + ".csv")

    cab = [
        "ID ruta", "ID usuario", "Nombre", "CURP", "Estatus", "Telefono",
        "E-mail", "Placa", "Concepto", "Tipo", "Fecha inicio", "Fecha fin",
        "Cantidad", "Costo", "Total",
    ]

    def campos(f):
        return [
            f.get("ruta", ""), f.get("id_usuario", ""), f.get("nombre", ""),
            f.get("curp", ""), f.get("estatus", ""), f.get("telefono", ""),
            f.get("email", ""), f.get("placa", ""), f.get("concepto", ""),
            f.get("tipo", ""), f.get("fecha_ini", ""), f.get("fecha_fin", ""),
            f.get("cantidad", ""), f.get("costo", ""), f.get("total", ""),
        ]

    with io.open(ruta_txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(cab) + "\n")
        for fila in filas:
            f.write("\t".join(campos(fila)) + "\n")

    with io.open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(cab)
        for fila in filas:
            w.writerow(campos(fila))

    return ruta_txt, ruta_csv


def main():
    print("=" * 70)
    print("  EXTRACTOR DE PREFACTURAS CON ID DE CONDUCTOR")
    print("=" * 70)
    print()
    print("  Cruza la prefactura con el reporte de operacion por ID de ruta,")
    print("  y le agrega la CURP del padron. Todo por numero, sin nombres.")
    print()

    id_pref = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not id_pref:
        id_pref = input(">>> Numero de prefactura: ").strip()
    if not id_pref:
        print("Hace falta el numero de prefactura.")
        input(">>> ENTER para cerrar... ")
        return

    padron, ruta_padron = cargar_padron()
    if padron:
        log(f"Padron cargado: {len(padron)} drivers "
            f"({os.path.basename(ruta_padron)})")
    else:
        log("AVISO: no hay drivers_meli_*.txt; no se podra agregar CURP.")
        log("       Corre antes DriversMeli.exe para generarlo.")

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(WEB + id_pref)
        print("-" * 70)
        print("  Inicia sesion si hace falta y espera a ver la prefactura.")
        print("-" * 70)
        input("\n>>> ENTER cuando la veas... ")

        if "billing" not in (driver.current_url or ""):
            driver.get(WEB + id_pref)
            time.sleep(4)

        # 1) Detalle
        filas, periodo, cabecera = bajar_detalle(driver, id_pref)
        if not filas:
            log("La prefactura no trajo lineas de detalle.")
            input(">>> ENTER para cerrar... ")
            return

        # 2) Reporte del periodo
        desde, hasta = periodo_a_fechas(periodo)
        if not desde:
            log(f"No se entendio el periodo '{periodo}'.")
            desde = input(">>> Fecha inicial (aaaa-mm-dd): ").strip()
            hasta = input(">>> Fecha final   (aaaa-mm-dd): ").strip()

        try:
            mapa = bajar_mapa_rutas(driver, desde, hasta)
        except Exception as e:
            log(f"No se pudo traer el reporte: {e}")
            log("Se continua sin ID de usuario.")
            mapa = {}

        # 3) Cruce por numero de ruta
        con_id = sin_ruta = sin_mapa = 0
        for f in filas:
            ruta = f.get("ruta", "")
            if not ruta:
                sin_ruta += 1
                continue
            info = mapa.get(ruta)
            if not info:
                sin_mapa += 1
                continue
            f["id_usuario"] = info["id"]
            con_id += 1

            datos = padron.get(info["id"])
            if datos:
                f["nombre"] = datos["nombre"]
                f["curp"] = datos["curp"]
                f["estatus"] = datos["estatus"]
                f["telefono"] = datos["telefono"]
                f["email"] = datos["email"]
            else:
                # Sin padron, al menos el nombre del reporte
                f["nombre"] = info["nombre"]

        txt, csvf = guardar(filas, id_pref)

        con_curp = sum(1 for f in filas if f.get("curp"))
        print()
        print("=" * 70)
        print(f"  LISTO. {len(filas)} lineas de la prefactura {id_pref}")
        print(f"  Periodo {periodo}  ({desde} a {hasta})")
        print()
        print(f"    Con ID de usuario   {con_id}/{len(filas)}")
        print(f"    Con CURP            {con_curp}/{len(filas)}")
        if sin_ruta:
            print(f"    Sin ID de ruta      {sin_ruta}  (items sin desglose)")
        if sin_mapa:
            print(f"    Ruta no encontrada  {sin_mapa}  en el reporte del periodo")
        print()
        print(f"  TXT: {txt}")
        print(f"  CSV: {csvf}")
        print("=" * 70)

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
    finally:
        input("\n>>> ENTER para cerrar... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

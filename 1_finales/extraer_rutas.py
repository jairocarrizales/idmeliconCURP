# -*- coding: utf-8 -*-
"""
Extractor de rutas diarias para el control.

Genera UNA tabla con las 20 columnas que se pueden llenar automaticamente,
para un rango de fechas. Sin columnas vacias: lo que no viene de MELI no se
incluye.

Fuentes:
  1. GET /api/carriers/reports?mile=LM&init_date=..&end_date=..&report_type=carrier
     -> XLSX con fecha, ruta, id y nombre del transportista, placa, KM,
        despachados, entregados, no visitado, SPORH

  2. API del monitoreo por estacion  (pendiente: la encuentra SondearRutas)
     -> CEDIS_MELI, Vehiculo, Tipo_de_servicio, Tipo_de_ruta, ZONA_DE_RUTA,
        CODIGO_POSTAL, RUTA

El Tipo_de_servicio distingue las dos familias del control:
    "Service Partner"  -> SP
    "RD" / "SDD"       -> RD
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
from datetime import datetime, timedelta   # timedelta: para buscar dias atras

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PANEL = "https://envios.adminml.com/logistics/monitoring-distribution"
API_REPORTE = "https://envios.adminml.com/api/carriers/reports"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Las columnas del control, en su orden.
# Se quitaron TIPO_DE_VEHICULO y Tipo_de_ruta: no existen en ninguna
# fuente de MELI y solo estorbaban vacias.
COLUMNAS = [
    "FECHA", "CEDIS_MELI", "ID_USUARIO", "DRIVER", "Vehiculo", "Placas",
    "Tipo_de_servicio", "ZONA_DE_RUTA", "RUTA", "ID_Ruta",
    "SPR", "ENTREGADOS", "FALLIDOS", "KM", "NO_VISITADOS", "PROD_HORA",
    "PERFORMANCE",
]

# Ya no queda ninguna sin dato: todas las columnas se llenan
SIN_FUENTE = ()

# El nombre de la ruta (C1_AM1) no viene por API: la ficha llega del
# servidor con el ya puesto. Se lee del HTML, que tarda 0.7 s por ruta.
FICHA = ("https://envios.adminml.com/logistics/monitoring-distribution"
         "/detail/{ruta}?site=MLM")
LOTE_FICHAS = 12          # medido: 168 rutas en ~12 segundos
PAUSA_FICHAS = 0.2
# Chrome se cae en los trabajos largos: en una corrida de 2366 rutas murio
# a las 1260. Un descanso cada tantas fichas lo evita.
DESCANSO_CADA = 300
DESCANSO_SEG = 5
# Si varios lotes seguidos fallan, algo va mal: cortar en vez de insistir
MAX_FALLOS_SEGUIDOS = 4
# Cuanto esperar por un lote. Con 120 s, siete lotes fallidos eran 14
# minutos de espera inutil.
TIMEOUT_LOTE = 45


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(v):
    if v is None:
        return ""
    t = str(v).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(t.split()).strip()


def numero(v):
    """Devuelve el valor como numero, o None si no lo es."""
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def porcentaje(fraccion):
    """0.9684 -> '96,84%'

    Con coma decimal, que es lo que espera Excel en espanol.
    """
    try:
        return f"{fraccion * 100:.2f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return ""


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


def llamar(driver, url, binario=False):
    """Llama la API desde la pagina, reusando su sesion."""
    if binario:
        script = """
        const url = arguments[0];
        const done = arguments[arguments.length - 1];
        fetch(url, {credentials: 'include'}).then(r => r.blob().then(b => {
          const lector = new FileReader();
          lector.onloadend = () => done({status: r.status,
                                         b64: lector.result.split(',')[1] || ''});
          lector.onerror = () => done({status: r.status, b64: ''});
          lector.readAsDataURL(b);
        })).catch(e => done({status: 0, b64: '', error: String(e)}));
        """
    else:
        script = """
        const url = arguments[0];
        const done = arguments[arguments.length - 1];
        fetch(url, {credentials: 'include',
                    headers: {'Accept': 'application/json, text/plain, */*'}})
          .then(r => r.text().then(t => done({status: r.status, body: t})))
          .catch(e => done({status: 0, body: String(e)}));
        """
    driver.set_script_timeout(180)
    return driver.execute_async_script(script, url)


# ------------------------------------------------------- lectura del XLSX
def leer_xlsx(datos):
    """Lee un XLSX sin openpyxl: es un ZIP con XML adentro."""
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
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
            col = 0
            for ch in ref.group(1):
                col = col * 26 + (ord(ch) - 64)
            col -= 1

            valor = ""
            v = re.search(r"<v>(.*?)</v>", contenido, re.S)
            if v:
                valor = v.group(1)
                if 't="s"' in attrs:
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
            filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)])

    if not filas:
        return [], []
    return filas[0], filas[1:]


def sin_tildes(t):
    """'Kilómetros' -> 'kilometros'. El reporte usa acentos y hay que
    compararlos sin ellos para no depender de como los escriba MELI."""
    t = limpiar(t).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("ü", "u")):
        t = t.replace(a, b)
    return t


def indice_de(cab, *nombres):
    """Busca una columna por nombre exacto o parcial, ignorando tildes."""
    normal = {sin_tildes(c): i for i, c in enumerate(cab)}
    for n in nombres:
        clave = sin_tildes(n)
        if clave in normal:
            return normal[clave]
    for clave, i in normal.items():
        if any(sin_tildes(n) in clave for n in nombres):
            return i
    return None


# --------------------------------------------------------------- extraer
def hay_datos(driver, dia):
    """Un dia suelto: cuantas rutas tiene? -1 si ni siquiera responde.

    Se usa para avisar antes de extraer, en vez de fallar a la mitad.
    """
    url = (f"{API_REPORTE}?mile=LM&init_date={dia}"
           f"&end_date={dia}&report_type=carrier")
    try:
        r = llamar(driver, url, binario=True)
    except Exception:
        return -1
    if r.get("status") != 200 or not r.get("b64"):
        return -1
    try:
        cab, filas = leer_xlsx(base64.b64decode(r["b64"]))
        return len(filas) if cab else 0
    except Exception:
        return -1


def ultimo_dia_con_datos(driver, desde_hoy=None, tope=400, log=log):
    """Busca hacia atras el dia mas viejo que todavia tiene datos.

    Va por busqueda binaria para no pedir cientos de dias: primero
    encuentra un dia sin datos, y luego afina entre ese y el ultimo bueno.
    Suele resolverse en unas 10 consultas.

    Devuelve (mas_viejo_con_datos, mas_reciente_sin_datos) en aaaa-mm-dd.
    """
    hoy = (datetime.strptime(desde_hoy, "%Y-%m-%d").date()
           if desde_hoy else datetime.now().date())

    def dia(atras):
        return (hoy - timedelta(days=atras)).strftime("%Y-%m-%d")

    # 1) Un punto de partida con datos
    bueno = None
    for d in (1, 2, 3, 7):
        n = hay_datos(driver, dia(d))
        log(f"  {dia(d)}: {n if n >= 0 else 'no responde'} rutas")
        if n > 0:
            bueno = d
            break
    if bueno is None:
        return "", ""

    # 2) Duplicar hasta encontrar uno sin datos
    malo = None
    d = bueno * 2
    while d <= tope:
        n = hay_datos(driver, dia(d))
        log(f"  {dia(d)} ({d}d atras): "
            f"{n if n > 0 else 'sin datos'}")
        if n > 0:
            bueno = d
            d *= 2
        else:
            malo = d
            break
    if malo is None:
        # Hay datos hasta el tope: no encontramos el limite
        return dia(bueno), ""

    # 3) Afinar entre el ultimo bueno y el primero malo
    while malo - bueno > 1:
        medio = (bueno + malo) // 2
        n = hay_datos(driver, dia(medio))
        log(f"  {dia(medio)} ({medio}d atras): "
            f"{n if n > 0 else 'sin datos'}")
        if n > 0:
            bueno = medio
        else:
            malo = medio

    return dia(bueno), dia(malo)


def revisar_rango(driver, desde, hasta, log=log):
    """Comprueba que el rango tenga datos ANTES de extraer.

    Devuelve (hay, aviso). Si 'hay' es False, no vale la pena seguir.
    """
    n_desde = hay_datos(driver, desde)
    if n_desde > 0:
        return True, ""

    log(f"  El {desde} no tiene datos; buscando hasta donde llega...")
    n_hasta = hay_datos(driver, hasta)

    if n_hasta > 0:
        # El final si tiene: el rango esta a medias
        return True, (
            f"El {desde} no tiene datos, pero el {hasta} si.\n\n"
            "El reporte saldra incompleto: le faltaran los primeros dias."
        )

    return False, (
        f"Ni el {desde} ni el {hasta} tienen datos.\n\n"
        "Mercado Libre no guarda el reporte de operacion indefinidamente. "
        "Presiona 'Hasta cuando hay datos' para saber desde que fecha "
        "puedes extraer."
    )


def bajar_reporte(driver, desde, hasta):
    """Reporte de operacion: una fila por ruta, con id del transportista."""
    url = (f"{API_REPORTE}?mile=LM&init_date={desde}"
           f"&end_date={hasta}&report_type=carrier")
    log(f"Pidiendo el reporte del {desde} al {hasta}...")

    r = llamar(driver, url, binario=True)
    if r.get("status") != 200 or not r.get("b64"):
        raise RuntimeError(
            f"El reporte respondio {r.get('status')}. "
            "Revisa que la sesion siga activa."
        )

    datos = base64.b64decode(r["b64"])
    log(f"  Recibidos {len(datos)} bytes")

    cab, filas = leer_xlsx(datos)
    if not cab:
        raise RuntimeError("El XLSX llego vacio.")

    # Localizar las columnas por nombre: el orden podria cambiar
    idx = {
        "fecha": indice_de(cab, "fecha", "date"),
        "ruta": indice_de(cab, "id de la ruta", "route id"),
        "id_usuario": indice_de(cab, "id del transportista", "driver id"),
        "driver": indice_de(cab, "nombre del transportista", "driver name"),
        "vehiculo": indice_de(cab, "vehiculo", "vehicle"),
        "placa": indice_de(cab, "placa", "plate"),
        "municipio": indice_de(cab, "municipio visitado", "city"),
        "servicio": indice_de(cab, "service type", "tipo de servicio"),
        "km": indice_de(cab, "kilometros recorridos", "km"),
        "centro": indice_de(cab, "service center", "cedis"),
        "spr": indice_de(cab, "envios despachados", "dispatched"),
        "entregados": indice_de(cab, "envios entregados", "delivered"),
        "exitosa": indice_de(cab, "entrega exitosa", "success"),
        "no_visitado": indice_de(cab, "no visitado", "not visited"),
        "sporh": indice_de(cab, "sporh"),
    }

    faltan = [k for k, v in idx.items() if v is None]
    if idx["ruta"] is None or idx["id_usuario"] is None:
        raise RuntimeError(
            f"El reporte no trae las columnas clave. Tiene: {', '.join(cab[:12])}"
        )
    if faltan:
        log(f"  Columnas no halladas (quedaran vacias): {', '.join(faltan)}")

    def celda(f, clave):
        i = idx.get(clave)
        return limpiar(f[i]) if i is not None and i < len(f) else ""

    registros = []
    for f in filas:
        ruta = celda(f, "ruta")
        if not ruta:
            continue

        spr = numero(celda(f, "spr"))
        entregados = numero(celda(f, "entregados"))
        # El reporte no trae fallidos: se deducen
        fallidos = ""
        if spr is not None and entregados is not None:
            fallidos = int(spr - entregados)

        # PERFORMANCE = entregados / despachados, en porcentaje legible
        performance = ""
        if spr and entregados is not None:
            performance = porcentaje(entregados / spr)

        registros.append({
            "FECHA": celda(f, "fecha"),
            "CEDIS_MELI": celda(f, "centro"),
            "ID_USUARIO": celda(f, "id_usuario"),
            "DRIVER": celda(f, "driver"),
            "Vehiculo": celda(f, "vehiculo"),
            "Placas": celda(f, "placa"),
            "Tipo_de_servicio": celda(f, "servicio"),
            # El municipio visitado es lo que el control llama zona de ruta
            "ZONA_DE_RUTA": celda(f, "municipio"),
            "RUTA": "",                  # se llena leyendo la ficha
            "ID_Ruta": ruta,
            "SPR": celda(f, "spr"),
            "ENTREGADOS": celda(f, "entregados"),
            "FALLIDOS": str(fallidos) if fallidos != "" else "",
            "KM": celda(f, "km"),
            "NO_VISITADOS": celda(f, "no_visitado"),
            "PROD_HORA": celda(f, "sporh"),
            "PERFORMANCE": str(performance) if performance != "" else "",
        })

    log(f"  {len(registros)} rutas en el reporte")
    return registros


RE_NOMBRE_RUTA = re.compile(r"Ruta\s+([A-Z0-9]{1,4}_[A-Z0-9_]{2,14})")


def nombre_del_html(html):
    """Saca 'C1_AM1' del HTML de la ficha.

    Se prueban varias formas por si cambia el marcado: el texto "Ruta X",
    un campo JSON incrustado, o el nombre entre etiquetas.
    """
    m = RE_NOMBRE_RUTA.search(html)
    if m:
        return m.group(1)
    for clave in ("routeName", "route_name", "plannedRouteName"):
        m = re.search(rf'"{clave}"\s*:\s*"([A-Z0-9]{{1,4}}_[A-Z0-9_]{{2,14}})"',
                      html)
        if m:
            return m.group(1)
    m = re.search(r">\s*([A-Z]{1,4}\d{0,3}_[A-Z0-9_]{2,14})\s*<", html)
    return m.group(1) if m else ""


def pedir_lote_fichas(driver, ids):
    """Trae el HTML de varias fichas a la vez y devuelve {id: nombre}.

    El tiempo lo domina la latencia (0.7 s por ficha), asi que pedirlas en
    paralelo es donde esta la ganancia: 168 rutas en ~12 s.
    """
    script = """
    const [plantilla, ids] = arguments;
    const done = arguments[arguments.length - 1];
    Promise.all(ids.map(id =>
      fetch(plantilla.replace('{ruta}', id), {credentials: 'include'})
        .then(r => r.ok ? r.text() : '')
        .then(t => ({id: id, html: t}))
        .catch(() => ({id: id, html: ''}))
    )).then(done);
    """
    driver.set_script_timeout(TIMEOUT_LOTE)
    respuestas = driver.execute_async_script(script, FICHA, list(ids))

    salida = {}
    for r in respuestas or []:
        if not r or not r.get("html"):
            continue
        nombre = nombre_del_html(r["html"])
        if nombre:
            salida[str(r["id"])] = nombre
    return salida


def _chrome_vivo(driver):
    """Comprueba que la ventana siga abierta antes de insistir."""
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def sin_nombre_de_ruta(registro):
    """Las rutas de Service Partner no llevan nombre.

    Comprobado con datos reales: de 48 Service Partner, 0 traen nombre,
    mientras RD y SDD lo traen al 100%. Asi que no se consultan sus fichas
    -es tiempo perdido- ni se cuentan como faltantes.
    """
    return "SERVICE PARTNER" in (registro.get("Tipo_de_servicio") or "").upper()


def completar_nombres(driver, registros):
    """Llena la columna RUTA consultando la ficha de cada una.

    Pedir miles de fichas seguidas agota a Chrome: en una corrida real se
    cayo a las 1260 con 'target frame detached'. Por eso hay tres defensas:

      - Se descansa cada cierto numero de fichas, para que el navegador
        libere memoria.
      - Si un lote falla, se comprueba que Chrome siga vivo antes de seguir;
        si murio, se corta en vez de insistir con miles de lotes.
      - Se corta tambien tras varios fallos seguidos, aunque Chrome
        responda: algo va mal y no vale la pena tardar media hora.
    """
    # Las de Service Partner no tienen nombre: no se consultan
    pendientes = [r for r in registros
                  if r.get("ID_Ruta") and not sin_nombre_de_ruta(r)]
    omitidas = sum(1 for r in registros if sin_nombre_de_ruta(r))
    total = len(pendientes)
    if not total:
        return 0

    log(f"Trayendo el nombre de {total} rutas...")
    if omitidas:
        log(f"  ({omitidas} de Service Partner no llevan nombre; se omiten)")
    if total > DESCANSO_CADA:
        log(f"  (con una pausa cada {DESCANSO_CADA}, para no agotar Chrome)")

    por_id = {r["ID_Ruta"]: r for r in pendientes}
    hechos = 0
    fallos_seguidos = 0
    inicio = time.time()

    for i in range(0, total, LOTE_FICHAS):
        lote = [r["ID_Ruta"] for r in pendientes[i:i + LOTE_FICHAS]]
        try:
            nombres = pedir_lote_fichas(driver, lote)
            fallos_seguidos = 0
        except Exception as e:
            fallos_seguidos += 1
            log(f"  Lote fallido: {resumir(e)}")

            if not _chrome_vivo(driver):
                log("  Chrome se cerro. Se detiene la busqueda de nombres.")
                log(f"  Se conservan los {hechos} nombres ya obtenidos.")
                break
            if fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                log(f"  {fallos_seguidos} lotes seguidos fallaron; se detiene.")
                log(f"  Se conservan los {hechos} nombres ya obtenidos.")
                break
            # Darle aire antes de reintentar
            time.sleep(3)
            continue

        for id_ruta, nombre in nombres.items():
            reg = por_id.get(id_ruta)
            if reg:
                reg["RUTA"] = nombre
                hechos += 1

        procesados = min(i + LOTE_FICHAS, total)
        if procesados % 60 < LOTE_FICHAS or procesados == total:
            transcurrido = time.time() - inicio
            ritmo = procesados / transcurrido if transcurrido else 0
            faltan = (total - procesados) / ritmo if ritmo else 0
            log(f"  {procesados}/{total} ({ritmo:.0f}/s, "
                f"faltan ~{faltan / 60:.0f} min)")

        # Un respiro cada tantas fichas: sin esto Chrome se cae en los
        # trabajos largos
        if procesados % DESCANSO_CADA < LOTE_FICHAS and procesados < total:
            log(f"  Pausa de {DESCANSO_SEG} s para que Chrome respire...")
            time.sleep(DESCANSO_SEG)
        else:
            time.sleep(PAUSA_FICHAS)

    log(f"Nombres obtenidos: {hechos}/{total}")
    return hechos


def resumir(e):
    """El mensaje util del error, sin el stacktrace de Selenium."""
    t = str(e).split("Stacktrace:")[0].split("\n")[0].strip()
    return " ".join(t.split())[:90]


def servicio_desde_vehiculo(vehiculo):
    """Deduce el Tipo_de_servicio a partir del vehiculo.

    La columna 'Service type' del reporte llega vacia, pero el vehiculo la
    determina. Comparando el control con el reporte:

        MEDIA MILLA SP        -> Service Partner   (hoja SP)
        SMALL/LARGE VAN MLP   -> RD                (hoja RD)
        ...con sufijo SDD     -> SDD               (hoja RD)

    En el control, 1444 de 1445 rutas SP usan Media Milla, y todas las de
    Media Milla estan en SP.
    """
    v = (vehiculo or "").upper()
    if not v:
        return ""
    if "MEDIA MILLA" in v or "MEDIA MILLLA" in v:   # el control tiene ambas
        return "Service Partner"
    if "SDD" in v:
        return "SDD"
    if "MLP" in v or "VAN" in v or "CAR" in v:
        return "RD"
    return ""


def clasificar(registros):
    """Marca cada ruta como SP o RD, y completa el Tipo_de_servicio.

    En el control: "Service Partner" -> SP;  "RD" o "SDD" -> RD.
    """
    conteo = {"SP": 0, "RD": 0, "?": 0}
    for r in registros:
        # Si el reporte no trajo el servicio, deducirlo del vehiculo
        if not (r.get("Tipo_de_servicio") or "").strip():
            r["Tipo_de_servicio"] = servicio_desde_vehiculo(r.get("Vehiculo"))

        servicio = (r.get("Tipo_de_servicio") or "").upper()
        if "SERVICE PARTNER" in servicio or servicio == "SP":
            r["_familia"] = "SP"
        elif "SDD" in servicio or servicio == "RD":
            r["_familia"] = "RD"
        else:
            r["_familia"] = ""
        conteo[r["_familia"] or "?"] += 1
    return conteo


def guardar(registros, desde, hasta):
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"rutas_{desde}_a_{hasta}_{sello}".replace("-", "")
    ruta_txt = os.path.join(BASE_DIR, base + ".txt")
    ruta_csv = os.path.join(BASE_DIR, base + ".csv")

    def campos(r):
        return [limpiar(r.get(c, "")) for c in COLUMNAS]

    with io.open(ruta_txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(COLUMNAS) + "\n")
        for r in registros:
            f.write("\t".join(campos(r)) + "\n")

    with io.open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNAS)
        for r in registros:
            w.writerow(campos(r))

    return ruta_txt, ruta_csv


def rango_por_defecto():
    """Ayer, que es el caso mas comun."""
    ayer = datetime.now() - timedelta(days=1)
    return ayer.strftime("%Y-%m-%d"), ayer.strftime("%Y-%m-%d")


def main():
    print("=" * 70)
    print("  EXTRACTOR DE RUTAS DIARIAS")
    print("=" * 70)
    print()

    d_def, h_def = rango_por_defecto()
    desde = input(f">>> Fecha inicial (ENTER para {d_def}): ").strip() or d_def
    hasta = input(f">>> Fecha final   (ENTER para {h_def}): ").strip() or h_def

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(PANEL)
        print("-" * 70)
        print("  Inicia sesion si hace falta y espera a ver el panel.")
        print("-" * 70)
        input("\n>>> ENTER cuando lo veas... ")

        if "adminml.com" not in (driver.current_url or ""):
            driver.get(PANEL)
            time.sleep(4)

        registros = bajar_reporte(driver, desde, hasta)
        if not registros:
            log("El reporte no trajo rutas para ese rango.")
            input(">>> ENTER para cerrar... ")
            return

        conteo = clasificar(registros)

        # El nombre de la ruta se lee de la ficha: ~12 s para 168
        try:
            completar_nombres(driver, registros)
        except Exception as e:
            log(f"No se pudieron traer los nombres: {str(e)[:110]}")
            log("Se continua sin la columna RUTA.")

        txt, csvf = guardar(registros, desde, hasta)

        con_id = sum(1 for r in registros if r.get("ID_USUARIO"))
        con_nombre = sum(1 for r in registros if r.get("RUTA"))
        print()
        print("=" * 70)
        print(f"  LISTO. {len(registros)} rutas del {desde} al {hasta}")
        print()
        # Las de Service Partner no llevan nombre: no cuentan como faltantes
        esperan_nombre = [r for r in registros if not sin_nombre_de_ruta(r)]
        sin_sp = len(registros) - len(esperan_nombre)

        print(f"    Con ID de usuario   {con_id}/{len(registros)}")
        print(f"    Con nombre de ruta  {con_nombre}/{len(esperan_nombre)}")
        if sin_sp:
            print(f"      ({sin_sp} de Service Partner no llevan nombre)")
        faltan = len(esperan_nombre) - con_nombre
        if faltan > 0:
            print(f"      ({faltan} sin nombre: Chrome no alcanzo a leer sus")
            print("       fichas. Vuelve a correrlo con un rango mas corto)")
        print(f"    Service Partner     {conteo['SP']}")
        print(f"    RD / SDD            {conteo['RD']}")
        if conteo["?"]:
            print(f"    Sin clasificar      {conteo['?']}")
        if SIN_FUENTE:
            print()
            print("  Columnas que quedan VACIAS (hay que capturarlas aparte):")
            for c in SIN_FUENTE:
                print(f"    - {c}")
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

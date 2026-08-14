# -*- coding: utf-8 -*-
"""
Sonda del LISTADO de prefacturas.

Hoy hay que saberse el numero (#6595499) para descargar una prefactura.
La idea es elegir mes + Q en dos listas desplegables, y que el programa
encuentre el numero solo.

Para eso hace falta la API detras de:
    /logistics/billing/invoices?page=1&sort_by=id&sort_type=desc

De la captura del usuario, cada fila trae:
    #6595499 | Regular      <- tipo
    Last Mile              <- milla
    Periodo 202607Q2       <- el que se va a elegir
    7,151,826.56 MXN
    Por pagar              <- estado

Los nombres van enmascarados; los numeros completos.
"""

import os
import sys
import json
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

LISTADO = ("https://envios.adminml.com/logistics/billing/invoices"
           "?page=1&sort_by=id&sort_type=desc")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# El perfil vive junto a los ejecutables finales
PROFILE_DIR = os.path.join(
    os.path.dirname(BASE_DIR), "1_finales", "chrome_profile")
if not os.path.isdir(PROFILE_DIR):
    PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def crear_driver():
    if os.path.isdir(PROFILE_DIR) and os.name == "nt":
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
    for n in ("lockfile", "LOCK", "SingletonLock", "DevToolsActivePort"):
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
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option(
        "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False}
    )
    return webdriver.Chrome(options=opts)


def peticiones(driver):
    vistas = {}
    try:
        entradas = driver.get_log("performance")
    except Exception:
        return []
    for e in entradas:
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        if m.get("method") != "Network.requestWillBeSent":
            continue
        p = m.get("params", {})
        req = p.get("request") or {}
        url = req.get("url", "")
        if not url.startswith("http") or p.get("type") not in ("XHR", "Fetch"):
            continue
        basura = (".js", ".css", ".png", ".svg", ".woff", "/metrics",
                  "melidata", "kaspersky", "google-analytics", "newrelic",
                  "mlstatic", "o11y", "datadog", "__modules", "__resolve",
                  "tracks/internal", "kraken-menu", "xtools-frm", "pidgey")
        if any(b in url.lower() for b in basura):
            continue
        vistas[url] = {"metodo": req.get("method", "GET"),
                       "cuerpo": (req.get("postData") or "")[:400]}
    return list(vistas.items())


def pedir(driver, url, metodo="GET", cuerpo=None):
    script = """
    const [url, metodo, cuerpo] = arguments;
    const done = arguments[arguments.length - 1];
    const op = {method: metodo, credentials: 'include',
                headers: {'Accept': 'application/json, text/plain, */*'}};
    if (cuerpo) { op.headers['Content-Type'] = 'application/json'; op.body = cuerpo; }
    fetch(url, op)
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url, metodo, cuerpo)


def tapar(v):
    t = str(v)
    if t in ("None", "True", "False", ""):
        return t
    if t.replace(".", "").replace("-", "").replace(",", "").isdigit():
        return t
    # Periodos, tipos y millas se ven enteros: son los que hay que filtrar
    if len(t) <= 22 and any(p in t.lower() for p in
                            ("202", "q1", "q2", "regular", "complement",
                             "last", "line", "mile", "haul", "pag", "cobr")):
        return t
    return t[:6] + "*" * min(8, max(0, len(t) - 6))


def volcar(obj, ruta="", salida=None, nivel=0):
    if salida is None:
        salida = []
    if nivel > 7:
        return salida
    if isinstance(obj, dict):
        for k, v in obj.items():
            camino = f"{ruta}.{k}" if ruta else k
            if isinstance(v, (dict, list)):
                volcar(v, camino, salida, nivel + 1)
            else:
                salida.append((camino, v))
    elif isinstance(obj, list):
        if not obj:
            salida.append((f"{ruta}[]", "(vacia)"))
        for i, v in enumerate(obj[:1]):
            volcar(v, f"{ruta}[{i}]", salida, nivel + 1)
    return salida


def main():
    print("=" * 74)
    print("  SONDA - listado de prefacturas")
    print("=" * 74)
    print()
    print("  Busca la API que lista las prefacturas, para poder elegir")
    print("  mes y Q en vez de saberse el numero.")
    print()

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get("https://envios.adminml.com/logistics/billing/invoices")
        print("-" * 74)
        print("  Inicia sesion si hace falta y presiona ENTER.")
        print("-" * 74)
        input("\n>>> ENTER... ")

        peticiones(driver)                    # vaciar el log
        log("Recargando el listado para capturar todo...")
        driver.get(LISTADO)
        time.sleep(9)

        urls = peticiones(driver)
        log(f"Peticiones XHR/Fetch: {len(urls)}")

        print()
        print("=" * 74)
        print("  REVISANDO RESPUESTAS")
        print("=" * 74)

        hallazgos = []
        for url, datos in urls:
            try:
                r = pedir(driver, url, datos["metodo"], datos["cuerpo"] or None)
            except Exception:
                continue
            if r.get("status") != 200:
                continue
            cuerpo = r.get("body") or ""
            try:
                obj = json.loads(cuerpo)
            except json.JSONDecodeError:
                continue

            campos = volcar(obj)
            texto = cuerpo.lower()
            # Una respuesta util menciona el periodo y el tipo
            util = ("202" in cuerpo and
                    ("regular" in texto or "period" in texto))
            corta = url.replace("https://envios.adminml.com", "")
            marca = "  <-- LISTA PREFACTURAS" if util else ""
            print(f"  {datos['metodo']:<5} {corta[:60]}  ({len(campos)}){marca}")
            if util:
                hallazgos.append((url, datos, obj, campos))
            time.sleep(0.2)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = os.path.join(os.path.dirname(BASE_DIR), "diagnosticos")
        os.makedirs(carpeta, exist_ok=True)
        rep = os.path.join(carpeta, f"lista_prefacturas_{sello}.txt")

        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("LISTADO DE PREFACTURAS\n")
            f.write(f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write("Periodos y tipos sin enmascarar; nombres si.\n")
            f.write("=" * 74 + "\n\n")

            if hallazgos:
                hallazgos.sort(key=lambda h: -len(h[3]))
                for url, datos, obj, campos in hallazgos:
                    f.write(f"{datos['metodo']} {url}\n")
                    if datos["cuerpo"]:
                        f.write(f"  cuerpo: {datos['cuerpo']}\n")
                    f.write(f"  {len(campos)} campos\n\n")
                    for camino, valor in campos:
                        f.write(f"    {camino} = {tapar(valor)}\n")
                    f.write("\n")

                    # Cuantas prefacturas trae y de que periodos
                    for clave in ("results", "result", "data", "invoices",
                                  "preInvoices", "content"):
                        lista = obj.get(clave) if isinstance(obj, dict) else None
                        if isinstance(lista, list) and lista:
                            f.write(f"  '{clave}': {len(lista)} prefacturas\n")
                            periodos = set()
                            for item in lista:
                                if isinstance(item, dict):
                                    for k, v in item.items():
                                        if "period" in k.lower() and v:
                                            periodos.add(str(v))
                            if periodos:
                                f.write(f"  periodos: {sorted(periodos)}\n")
                            f.write("\n")
                            break

                print()
                print("=" * 74)
                print("  CAMPOS PARA FILTRAR")
                print("=" * 74)
                url, datos, obj, campos = hallazgos[0]
                for camino, valor in campos:
                    if any(p in camino.lower() for p in
                           ("period", "type", "mile", "step", "status",
                            "id", "product", "sub")):
                        linea = f"  {camino:<44} = {tapar(valor)}"
                        print(linea)
                        f.write(linea + "\n")
            else:
                f.write("No se hallo la lista de prefacturas.\n")

            f.write("\n" + "=" * 74 + "\nTODAS LAS PETICIONES\n" + "=" * 74 + "\n")
            for url, datos in urls:
                f.write(f"{datos['metodo']}  {url}\n")
                if datos["cuerpo"]:
                    f.write(f"    cuerpo: {datos['cuerpo']}\n")

        print()
        print("=" * 74)
        print(f"  Reporte: {rep}")
        print("=" * 74)

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

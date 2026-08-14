# -*- coding: utf-8 -*-
"""
Comprueba si el nombre de la ruta viene en el HTML del servidor.

La busqueda anterior leyo "C1_AM1" de la pantalla pero no lo hallo en
ninguna respuesta JSON. Eso significa que la pagina llega ya con el nombre
puesto desde el servidor.

Si es asi, se puede leer igual de rapido: se pide el HTML de la ficha y se
extrae con una expresion regular, sin abrir la pagina en el navegador. Este
script lo verifica y mide cuanto tarda por ruta.
"""

import os
import re
import sys
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

DETALLE = "https://envios.adminml.com/logistics/monitoring-distribution/detail/{ruta}?site=MLM"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# "Ruta C1_AM1", "C1_AM1", "SP50_11_AM8"
RE_NOMBRE = re.compile(r"\b([A-Z]{1,4}\d{0,3}_[A-Z0-9_]{2,14})\b")


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
    return webdriver.Chrome(options=opts)


def pedir_html(driver, url):
    """Trae el HTML de una pagina sin abrirla en el navegador."""
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials: 'include'})
      .then(r => r.text().then(t => done({status: r.status, body: t})))
      .catch(e => done({status: 0, body: String(e)}));
    """
    driver.set_script_timeout(60)
    return driver.execute_async_script(script, url)


def nombre_del_html(html):
    """Saca el nombre de la ruta del HTML servido.

    Se buscan varias formas porque el marcado puede cambiar:
      <h1>Ruta C1_AM1</h1>, "routeName":"C1_AM1", >C1_AM1<
    """
    # 1) Junto a la palabra Ruta
    m = re.search(r"Ruta\s+([A-Z0-9]{1,4}_[A-Z0-9_]{2,14})", html)
    if m:
        return m.group(1), "texto 'Ruta X'"

    # 2) En un campo JSON incrustado en la pagina
    for clave in ("routeName", "route_name", "name", "plannedRouteName"):
        m = re.search(rf'"{clave}"\s*:\s*"([A-Z0-9]{{1,4}}_[A-Z0-9_]{{2,14}})"', html)
        if m:
            return m.group(1), f'json "{clave}"'

    # 3) Entre etiquetas
    m = re.search(r">\s*([A-Z]{1,4}\d{0,3}_[A-Z0-9_]{2,14})\s*<", html)
    if m:
        return m.group(1), "entre etiquetas"

    return "", ""


def main():
    print("=" * 74)
    print("  EL NOMBRE DE LA RUTA, DESDE EL HTML")
    print("=" * 74)
    print()
    print("  El nombre no viene por API: la pagina llega con el ya puesto.")
    print("  Aqui se comprueba si se puede leer del HTML, y cuanto tarda.")
    print()

    rutas = sys.argv[1:] if len(sys.argv) > 1 else []
    if not rutas:
        entrada = input(">>> IDs de ruta separados por coma "
                        "(ENTER para 151255890): ").strip()
        rutas = [r.strip() for r in entrada.split(",") if r.strip()] or ["151255890"]

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get("https://envios.adminml.com/logistics/monitoring-distribution")
        print("-" * 74)
        print("  Inicia sesion si hace falta y presiona ENTER.")
        print("-" * 74)
        input("\n>>> ENTER... ")

        # 1) Comprobar que el nombre esta en el HTML
        print()
        print("=" * 74)
        print("  PRUEBA 1: el nombre viene en el HTML?")
        print("=" * 74)

        resultados = []
        for ruta in rutas:
            url = DETALLE.format(ruta=ruta)
            inicio = time.time()
            r = pedir_html(driver, url)
            tardo = time.time() - inicio

            estado = r.get("status")
            html = r.get("body") or ""
            nombre, donde = nombre_del_html(html)

            print(f"\n  Ruta {ruta}:")
            print(f"    status {estado}, {len(html)} caracteres, {tardo:.1f} s")
            if nombre:
                print(f"    NOMBRE: '{nombre}'  (hallado en {donde})")
            else:
                print("    no se encontro el nombre en el HTML")
                # Ver si al menos el HTML trae contenido util
                if "monitoring" in html.lower():
                    print("    (el HTML si es de la pagina, pero sin el nombre)")
                else:
                    print("    (el HTML no parece ser el de la ficha)")
            resultados.append((ruta, nombre, tardo, len(html)))

        # 2) Si no vino en el HTML, leerlo del DOM ya renderizado
        if not any(n for _, n, _, _ in resultados):
            print()
            print("=" * 74)
            print("  PRUEBA 2: leerlo del DOM (abriendo la pagina)")
            print("=" * 74)
            ruta = rutas[0]
            inicio = time.time()
            driver.get(DETALLE.format(ruta=ruta))
            time.sleep(6)
            texto = ""
            try:
                texto = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass
            tardo = time.time() - inicio
            m = re.search(r"Ruta\s+([A-Z0-9]{1,4}_[A-Z0-9_]{2,14})", texto)
            if m:
                print(f"  Ruta {ruta}: '{m.group(1)}'  en {tardo:.1f} s")
                print()
                print(f"  Proyeccion a 168 rutas: ~{168 * tardo / 60:.0f} minutos")
                print("  (hay que abrir cada pagina; no se puede paralelizar)")
            else:
                print(f"  No se hallo el nombre ni en el DOM.")

        # --- Resumen ---
        print()
        print("=" * 74)
        ok = [r for r in resultados if r[1]]
        if ok:
            media = sum(r[2] for r in ok) / len(ok)
            print(f"  El nombre SI se puede leer del HTML ({len(ok)}/{len(rutas)})")
            print(f"  Tarda {media:.1f} s por ruta")
            print(f"  Proyeccion a 168 rutas en lotes de 12: "
                  f"~{168 * media / 12 / 60:.1f} minutos")
        else:
            print("  El nombre NO esta en el HTML servido.")
            print("  La pagina lo pinta con JavaScript despues de cargar.")
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

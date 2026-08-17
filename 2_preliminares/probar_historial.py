# -*- coding: utf-8 -*-
"""
Hasta que fecha guarda MELI el reporte de operacion?

La sospecha: el portal no conserva historial indefinido, y al pedir fechas
muy viejas falla. Este script lo comprueba pidiendo dias sueltos hacia
atras y viendo que responde.

Interesa saber:
  - Como se ve un dia SIN datos: error, XLSX vacio, o pocas filas?
  - Cual es el dia mas viejo que todavia responde?
"""

import os
import re
import io
import sys
import time
import base64
import zipfile
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PANEL = "https://envios.adminml.com/logistics/monitoring-distribution"
API = "https://envios.adminml.com/api/carriers/reports"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
    return webdriver.Chrome(options=opts)


def pedir_binario(driver, url):
    script = """
    const url = arguments[0];
    const done = arguments[arguments.length - 1];
    fetch(url, {credentials: 'include'}).then(r => r.blob().then(b => {
      const lector = new FileReader();
      lector.onloadend = () => done({status: r.status, tam: b.size,
                                     tipo: b.type,
                                     b64: lector.result.split(',')[1] || ''});
      lector.onerror = () => done({status: r.status, tam: 0, b64: ''});
      lector.readAsDataURL(b);
    })).catch(e => done({status: 0, tam: 0, b64: '', error: String(e)}));
    """
    driver.set_script_timeout(90)
    return driver.execute_async_script(script, url)


def contar_filas(datos):
    """Cuantas filas trae el XLSX, sin depender de openpyxl."""
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            hojas = [n for n in z.namelist()
                     if n.startswith("xl/worksheets/sheet")]
            if not hojas:
                return 0
            xml = z.read(sorted(hojas)[0]).decode("utf-8", "replace")
        return max(0, len(re.findall(r"<row[^>]*>", xml)) - 1)
    except Exception:
        return -1        # ni siquiera es un XLSX valido


def probar_dia(driver, dia):
    """Pide un dia suelto y devuelve (status, bytes, filas)."""
    url = (f"{API}?mile=LM&init_date={dia}&end_date={dia}"
           f"&report_type=carrier")
    try:
        r = pedir_binario(driver, url)
    except Exception as e:
        return 0, 0, -1, str(e)[:60]

    estado = r.get("status")
    tam = r.get("tam", 0)
    filas = -1
    if estado == 200 and r.get("b64"):
        filas = contar_filas(base64.b64decode(r["b64"]))
    return estado, tam, filas, ""


def main():
    print("=" * 74)
    print("  HASTA CUANDO GUARDA MELI EL REPORTE?")
    print("=" * 74)
    print()
    print("  Pide dias sueltos hacia atras para ver desde cuando hay datos.")
    print()

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(PANEL)
        print("-" * 74)
        print("  Inicia sesion si hace falta y presiona ENTER.")
        print("-" * 74)
        input("\n>>> ENTER... ")

        hoy = datetime.now().date()
        print()
        print("=" * 74)
        print(f"  {'DIA':<12} {'ATRAS':>6} {'STATUS':>7} {'BYTES':>9} {'FILAS':>7}")
        print("=" * 74)

        # Primero los dias recientes, luego saltos mas grandes
        atras = ([1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 75, 90, 120, 150,
                  180, 240, 300, 365])
        resultados = []
        for d in atras:
            dia = (hoy - timedelta(days=d)).strftime("%Y-%m-%d")
            estado, tam, filas, err = probar_dia(driver, dia)
            marca = ""
            if estado != 200:
                marca = "  <-- no responde"
            elif filas <= 0:
                marca = "  <-- vacio"
            print(f"  {dia:<12} {d:>5}d {str(estado):>7} {tam:>9} "
                  f"{filas if filas >= 0 else '?':>7}{marca}")
            resultados.append((dia, d, estado, tam, filas))
            if err:
                print(f"       {err}")
            time.sleep(0.4)

        # El corte: el ultimo con datos
        con_datos = [r for r in resultados if r[2] == 200 and r[4] > 0]
        sin_datos = [r for r in resultados if r[2] != 200 or r[4] <= 0]

        print()
        print("=" * 74)
        if con_datos:
            mas_viejo = max(con_datos, key=lambda r: r[1])
            print(f"  El dia mas viejo CON datos: {mas_viejo[0]} "
                  f"({mas_viejo[1]} dias atras, {mas_viejo[4]} rutas)")
        if sin_datos:
            mas_nuevo_sin = min(sin_datos, key=lambda r: r[1])
            print(f"  El dia mas reciente SIN datos: {mas_nuevo_sin[0]} "
                  f"({mas_nuevo_sin[1]} dias atras)")
            print()
            print("  -> el limite esta entre esos dos")
        print("=" * 74)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = os.path.join(os.path.dirname(BASE_DIR), "diagnosticos")
        os.makedirs(carpeta, exist_ok=True)
        rep = os.path.join(carpeta, f"historial_{sello}.txt")
        with open(rep, "w", encoding="utf-8-sig") as f:
            f.write("HASTA CUANDO GUARDA MELI EL REPORTE\n")
            f.write(f"Fecha de la prueba: {datetime.now():%Y-%m-%d %H:%M}\n")
            f.write("=" * 74 + "\n\n")
            f.write(f"{'DIA':<12} {'ATRAS':>6} {'STATUS':>7} {'BYTES':>9} {'FILAS':>7}\n")
            for dia, d, estado, tam, filas in resultados:
                f.write(f"{dia:<12} {d:>5}d {str(estado):>7} {tam:>9} "
                        f"{filas if filas >= 0 else '?':>7}\n")
            f.write("\n")
            if con_datos:
                mv = max(con_datos, key=lambda r: r[1])
                f.write(f"Mas viejo con datos: {mv[0]} ({mv[1]} dias)\n")
            if sin_datos:
                mn = min(sin_datos, key=lambda r: r[1])
                f.write(f"Mas reciente sin datos: {mn[0]} ({mn[1]} dias)\n")

        print(f"  Reporte: {rep}")

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

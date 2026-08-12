# -*- coding: utf-8 -*-
"""
Extractor de drivers de Mercado Libre (envios.adminml.com)

Abre Chrome, espera a que TU inicies sesion manualmente, y cuando presiones ENTER
en la consola empieza a extraer: Nombre, CURP, Tipo, Fecha de creacion y Estatus.

Presiona "Mostrar mas" de forma persistente hasta que ya no queden mas registros,
y guarda todo en un .txt separado por TABS (se pega/abre directo en Excel sin
problemas de acentos, gracias a UTF-8 con BOM).
"""

import os
import re
import sys
import time
import csv
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
)

URL = "https://envios.adminml.com/logistics/provider-management/drivers"

# Carpeta donde se guardan los resultados.
# Si corre como .exe, usa la carpeta del ejecutable; si no, la del script.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Perfil de Chrome persistente: si ya iniciaste sesion una vez, la proxima
# probablemente ya no te pida login.
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")

# Cuantas veces seguidas puede fallar el "Mostrar mas" antes de darnos por vencidos
MAX_INTENTOS_SIN_CAMBIO = 4
# Segundos maximos de espera a que carguen filas nuevas tras cada clic
ESPERA_CARGA = 25


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def limpiar(texto):
    """Normaliza el texto: quita saltos de linea, tabs y espacios sobrantes."""
    if not texto:
        return ""
    texto = texto.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(texto.split()).strip()


def crear_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-MX")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def contar_filas(driver):
    try:
        return len(driver.find_elements(By.CSS_SELECTOR, "li.list__row"))
    except Exception:
        return 0


def buscar_boton_mostrar_mas(driver):
    """Devuelve el boton 'Mostrar mas' si existe y esta visible, si no None."""
    # 1) El contenedor especifico que se ve en el DOM de la pagina
    for sel in ("div.show-more-btn button", "div.show-more-btn .andes-button"):
        for b in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if b.is_displayed() and b.is_enabled():
                    return b
            except StaleElementReferenceException:
                continue

    # 2) Respaldo: cualquier boton cuyo texto diga "Mostrar mas"
    try:
        botones = driver.find_elements(
            By.XPATH,
            "//button[contains(translate(., 'ÁÉÍÓÚáéíóúÑñ', 'AEIOUaeiouNn'), 'Mostrar mas')]",
        )
        for b in botones:
            try:
                if b.is_displayed() and b.is_enabled():
                    return b
            except StaleElementReferenceException:
                continue
    except Exception:
        pass
    return None


def clic_seguro(driver, boton):
    """Hace scroll al boton y lo clickea; si algo lo tapa, usa clic por JS."""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', behavior:'instant'});", boton
        )
    except Exception:
        pass
    time.sleep(0.4)
    try:
        boton.click()
        return True
    except (ElementClickInterceptedException, StaleElementReferenceException, Exception):
        try:
            driver.execute_script("arguments[0].click();", boton)
            return True
        except Exception:
            return False


def cargar_todo(driver):
    """Presiona 'Mostrar mas' hasta que ya no aparezcan mas registros."""
    total = contar_filas(driver)
    log(f"Filas iniciales: {total}")

    sin_cambio = 0
    clics = 0

    while True:
        boton = buscar_boton_mostrar_mas(driver)

        if boton is None:
            # Puede que el boton solo no este renderizado aun: bajamos al fondo
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            boton = buscar_boton_mostrar_mas(driver)

        if boton is None:
            sin_cambio += 1
            if sin_cambio >= MAX_INTENTOS_SIN_CAMBIO:
                log("Ya no hay boton 'Mostrar mas'. Carga completa.")
                break
            log(f"No se encontro el boton (intento {sin_cambio}/{MAX_INTENTOS_SIN_CAMBIO}). Reintentando...")
            time.sleep(2)
            continue

        antes = contar_filas(driver)
        if not clic_seguro(driver, boton):
            sin_cambio += 1
            log(f"No se pudo hacer clic (intento {sin_cambio}/{MAX_INTENTOS_SIN_CAMBIO}).")
            time.sleep(2)
            continue

        clics += 1

        # Esperar a que aumenten las filas
        inicio = time.time()
        nuevo = antes
        while time.time() - inicio < ESPERA_CARGA:
            time.sleep(0.7)
            nuevo = contar_filas(driver)
            if nuevo > antes:
                break

        if nuevo > antes:
            sin_cambio = 0
            log(f"Clic #{clics}: {antes} -> {nuevo} filas (+{nuevo - antes})")
        else:
            sin_cambio += 1
            log(f"Clic #{clics}: sin filas nuevas ({nuevo}). Intento {sin_cambio}/{MAX_INTENTOS_SIN_CAMBIO}")
            if sin_cambio >= MAX_INTENTOS_SIN_CAMBIO:
                log("Sin cambios tras varios intentos. Se asume que ya se cargo todo.")
                break
            time.sleep(2)

    total = contar_filas(driver)
    log(f"TOTAL de filas cargadas: {total}")
    return total


def texto_de(fila, selector):
    try:
        return limpiar(fila.find_element(By.CSS_SELECTOR, selector).text)
    except NoSuchElementException:
        return ""
    except StaleElementReferenceException:
        return ""


# CURP: 4 letras + 6 digitos + H/M + 5 letras + 2 alfanumericos
RE_CURP = re.compile(r"^[A-ZÑ&]{4}\d{6}[HM][A-ZÑ]{5}[A-Z0-9]{2}$", re.IGNORECASE)


def quitar_prefijo_fecha(texto):
    """'Creado el 30/jun/2026' -> '30/jun/2026'"""
    t = limpiar(texto)
    bajo = t.lower()
    for prefijo in ("creado el ", "creado "):
        if bajo.startswith(prefijo):
            return t[len(prefijo):].strip()
    return t


def extraer_datos(driver):
    """Recorre las filas y saca nombre, curp, tipo, fecha y estatus.

    Las filas bloqueadas (li.list__row--disable) usan clases distintas:
    description--name-disabled y description--disabled en lugar de
    description--name / description--secondary / description--bold / description.
    Por eso no nos casamos con una clase concreta: leemos TODOS los textos de
    cada bloque y los clasificamos por su contenido.
    """
    filas = driver.find_elements(By.CSS_SELECTOR, "li.list__row")
    registros = []
    bloqueados = 0

    for i, fila in enumerate(filas, start=1):
        try:
            # ---- Estatus: sale de su propia columna, sirva o no la fila ----
            estatus = texto_de(fila, "div.row-data__deactivated-column")
            if not estatus:
                estatus = texto_de(fila, "p.row-data__deactivated-column__text-status")
            estatus = limpiar(estatus)

            # El estatus puede traer una nota extra: "Activo Falta leve".
            # Separamos el estado principal de la observacion.
            estado, observacion = estatus, ""
            for palabra in ("Activo", "Bloqueado", "Inactivo", "Pendiente", "Suspendido"):
                if estatus.startswith(palabra):
                    estado = palabra
                    observacion = limpiar(estatus[len(palabra):])
                    break

            # ---- Nombre y CURP: viven en el primer bloque de descripcion ----
            # Aceptamos las dos variantes de clase (normal y -disabled)
            nombre = ""
            for sel in (
                "div.description--name span",
                "div.description--name-disabled span",
                "div.description--name",
                "div.description--name-disabled",
            ):
                nombre = texto_de(fila, sel)
                if nombre:
                    break

            curp = ""
            for sel in ("p.description--secondary", "p.description--disabled"):
                for p in fila.find_elements(By.CSS_SELECTOR, sel):
                    t = limpiar(p.text)
                    if RE_CURP.match(t):
                        curp = t.upper()
                        break
                if curp:
                    break

            # ---- Tipo y fecha: segundo bloque de descripcion ----
            tipo, fecha = "", ""
            for sel in (
                "p.description--bold",
                "p.description",
                "p.description--disabled",
            ):
                for p in fila.find_elements(By.CSS_SELECTOR, sel):
                    t = limpiar(p.text)
                    if not t:
                        continue
                    if t.lower().startswith("creado"):
                        if not fecha:
                            fecha = quitar_prefijo_fecha(t)
                    elif not RE_CURP.match(t) and t != nombre and not tipo:
                        # Lo que no es CURP, ni nombre, ni fecha, es el tipo
                        # ("Transportista")
                        tipo = t

            # ---- Red de seguridad ----
            # Si algo falto, barremos TODOS los <p>/<span> de la fila y
            # clasificamos por contenido. Cubre variantes de clase futuras.
            if not (nombre and curp and fecha):
                textos = []
                for el in fila.find_elements(By.CSS_SELECTOR, "p, span"):
                    t = limpiar(el.text)
                    if t and t not in textos:
                        textos.append(t)

                for t in textos:
                    if not curp and RE_CURP.match(t):
                        curp = t.upper()
                    elif not fecha and t.lower().startswith("creado"):
                        fecha = quitar_prefijo_fecha(t)

                if not nombre:
                    # El nombre es el primer texto que no es CURP, ni fecha,
                    # ni tipo, ni estatus
                    descartar = {tipo, estatus, estado, observacion, curp}
                    for t in textos:
                        if (
                            t not in descartar
                            and not RE_CURP.match(t)
                            and not t.lower().startswith("creado")
                            and t.lower() != "transportista"
                        ):
                            nombre = t
                            break

                if not tipo:
                    for t in textos:
                        if t.lower() in ("transportista", "conductor", "chofer"):
                            tipo = t
                            break

            # Solo descartamos la fila si esta completamente vacia
            if not (nombre or curp or estatus):
                continue

            if estado.lower() == "bloqueado":
                bloqueados += 1

            registros.append(
                {
                    "n": len(registros) + 1,
                    "nombre": nombre,
                    "curp": curp,
                    "tipo": tipo,
                    "fecha": fecha,
                    "estatus": estado,
                    "observacion": observacion,
                }
            )
        except StaleElementReferenceException:
            log(f"Fila {i} se volvio obsoleta, se omite.")
            continue

    # Diagnostico util: avisar si quedaron campos vacios
    sin_nombre = sum(1 for r in registros if not r["nombre"])
    sin_curp = sum(1 for r in registros if not r["curp"])
    log(f"Bloqueados detectados: {bloqueados}")
    if sin_nombre or sin_curp:
        log(f"ADVERTENCIA: {sin_nombre} sin nombre, {sin_curp} sin CURP.")

    return registros


def guardar(registros):
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_txt = os.path.join(BASE_DIR, f"drivers_meli_{sello}.txt")
    ruta_csv = os.path.join(BASE_DIR, f"drivers_meli_{sello}.csv")

    encabezados = [
        "#",
        "Nombre",
        "CURP",
        "Tipo",
        "Fecha creacion",
        "Estatus",
        "Observacion",
    ]

    def campos(r):
        return [
            str(r["n"]),
            r["nombre"],
            r["curp"],
            r["tipo"],
            r["fecha"],
            r["estatus"],
            r.get("observacion", ""),
        ]

    # TXT separado por tabuladores -> se pega directo en Excel
    # utf-8-sig = UTF-8 con BOM, para que Excel respete acentos y enies
    with open(ruta_txt, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(encabezados) + "\n")
        for r in registros:
            f.write("\t".join(campos(r)) + "\n")

    # CSV con punto y coma (Excel en espanol lo abre con doble clic)
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(encabezados)
        for r in registros:
            w.writerow(campos(r))

    return ruta_txt, ruta_csv


def main():
    print("=" * 70)
    print("  EXTRACTOR DE DRIVERS - MERCADO LIBRE ENVIOS")
    print("=" * 70)

    log("Abriendo Chrome...")
    driver = crear_driver()

    try:
        driver.get(URL)

        print()
        print("-" * 70)
        print("  1) Inicia sesion en la ventana de Chrome que se abrio.")
        print("  2) Asegurate de ver la LISTA DE DRIVERS en pantalla.")
        print("  3) Regresa aqui y presiona ENTER para comenzar la extraccion.")
        print("-" * 70)
        input("\n>>> Presiona ENTER cuando estes listo... ")

        # Por si el login te dejo en otra ruta, volvemos a la lista
        if "provider-management/drivers" not in driver.current_url:
            log("Navegando de nuevo a la lista de drivers...")
            driver.get(URL)

        log("Esperando que carguen las filas...")
        try:
            WebDriverWait(driver, 40).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
        except TimeoutException:
            log("ADVERTENCIA: no se detectaron filas. Verifica que la lista este visible.")
            input(">>> Acomoda la pantalla y presiona ENTER para intentar otra vez... ")

        log("Cargando todos los registros (esto puede tardar varios minutos)...")
        cargar_todo(driver)

        log("Extrayendo datos...")
        registros = extraer_datos(driver)
        log(f"Registros extraidos: {len(registros)}")

        if not registros:
            log("No se extrajo nada. Revisa que la lista este visible en pantalla.")
            input(">>> ENTER para cerrar... ")
            return

        txt, csv_path = guardar(registros)

        # Resumen por estatus
        conteo = {}
        for r in registros:
            clave = r["estatus"] or "(sin estatus)"
            conteo[clave] = conteo.get(clave, 0) + 1

        print()
        print("=" * 70)
        print(f"  LISTO. {len(registros)} drivers extraidos.")
        print()
        for clave in sorted(conteo, key=lambda k: -conteo[k]):
            print(f"    {clave:<20} {conteo[clave]}")
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
        input("\n>>> Presiona ENTER para cerrar el navegador... ")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

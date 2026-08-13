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


def resumir_error(e):
    """Selenium escupe stacktraces enormes; nos quedamos con lo util."""
    texto = str(e).split("Stacktrace:")[0].strip()
    texto = " ".join(texto.split())
    if not texto:
        texto = type(e).__name__
    return texto[:160]


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


# El ID vive en la URL del perfil: /drivers/edit/5196349
RE_ID_URL = re.compile(r"/drivers/edit/(\d+)")


def quitar_prefijo_fecha(texto):
    """'Creado el 30/jun/2026' -> '30/jun/2026'"""
    t = limpiar(texto)
    bajo = t.lower()
    for prefijo in ("creado el ", "creado "):
        if bajo.startswith(prefijo):
            return t[len(prefijo):].strip()
    return t


def id_desde_fila(fila):
    """Intenta sacar el ID del driver sin abrir su perfil.

    El ID aparece en la URL del perfil (/drivers/edit/5196349). Si la fila trae
    un <a> a esa ruta, o algun atributo con el id, lo tomamos gratis.
    Devuelve "" si no esta disponible en el listado.
    """
    # 1) Un enlace directo al perfil
    try:
        for a in fila.find_elements(By.CSS_SELECTOR, "a[href]"):
            m = RE_ID_URL.search(a.get_attribute("href") or "")
            if m:
                return m.group(1)
    except Exception:
        pass

    # 2) Algun atributo de datos en la fila o sus hijos
    try:
        for attr in ("data-id", "data-driver-id", "data-testid", "id"):
            valor = fila.get_attribute(attr) or ""
            m = re.search(r"(\d{4,})", valor)
            if m:
                return m.group(1)
    except Exception:
        pass

    return ""


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
                    "id": id_desde_fila(fila),
                    "nombre": nombre,
                    "curp": curp,
                    "tipo": tipo,
                    "fecha": fecha,
                    "estatus": estado,
                    "observacion": observacion,
                    "telefono": "",
                    "email": "",
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


URL_PERFIL = "https://envios.adminml.com/logistics/provider-management/drivers/edit/"


def valor_de_campo(driver, nombre_input):
    """Lee el value de un <input name="..."> del formulario de perfil."""
    for sel in (
        f"input[name='{nombre_input}']",
        f"input#{nombre_input}",
        f"[data-testid='{nombre_input}'] input",
    ):
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            v = limpiar(el.get_attribute("value") or el.text)
            if v:
                return v
        except NoSuchElementException:
            continue
        except Exception:
            continue
    return ""


def leer_perfil(driver):
    """Estando ya en la pagina de perfil, lee ID, telefono y e-mail."""
    datos = {"id": "", "telefono": "", "email": ""}

    # El ID mas confiable es el de la propia URL
    m = RE_ID_URL.search(driver.current_url or "")
    if m:
        datos["id"] = m.group(1)

    if not datos["id"]:
        datos["id"] = valor_de_campo(driver, "id")

    datos["telefono"] = valor_de_campo(driver, "phone")
    datos["email"] = valor_de_campo(driver, "email")

    # Respaldo: barrer todos los inputs y clasificar por su etiqueta/atributo
    if not (datos["telefono"] and datos["email"]):
        try:
            for inp in driver.find_elements(By.CSS_SELECTOR, "input"):
                nombre_attr = (inp.get_attribute("name") or "").lower()
                valor = limpiar(inp.get_attribute("value") or "")
                if not valor:
                    continue
                if not datos["email"] and "@" in valor:
                    datos["email"] = valor
                elif not datos["telefono"] and "phone" in nombre_attr:
                    datos["telefono"] = valor
        except Exception:
            pass

    return datos


def abrir_perfiles(driver, registros, solo_faltantes=True):
    """Abre el perfil de cada driver para completar ID, telefono y e-mail.

    Navega directo por URL (mas rapido y estable que usar el menu de 3 puntos).
    Para los que no tenemos ID todavia, hay que pasar por el menu.
    """
    con_id = [r for r in registros if r["id"]]
    sin_id = [r for r in registros if not r["id"]]

    if sin_id and not con_id:
        log(
            "No se encontro ningun ID en el listado; hay que abrir los perfiles "
            "desde el menu de 3 puntos."
        )
        return abrir_perfiles_por_menu(driver, registros)

    if sin_id:
        log(f"ADVERTENCIA: {len(sin_id)} registros sin ID en el listado.")

    pendientes = con_id if not solo_faltantes else [
        r for r in con_id if not (r["telefono"] and r["email"])
    ]

    total = len(pendientes)
    log(f"Abriendo {total} perfiles para obtener telefono y e-mail...")

    for i, r in enumerate(pendientes, start=1):
        try:
            driver.get(URL_PERFIL + r["id"])
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input"))
            )
            time.sleep(0.5)
            datos = leer_perfil(driver)
            r["telefono"] = datos["telefono"]
            r["email"] = datos["email"]
            if datos["id"]:
                r["id"] = datos["id"]
        except Exception as e:
            log(f"  No se pudo leer el perfil {r['id']} ({r['nombre']}): {e}")

        if i % 10 == 0 or i == total:
            log(f"  Perfiles leidos: {i}/{total}")

    return registros


def buscar_opcion_menu(driver, texto):
    """Encuentra la opcion clickeable de un menu flotante por su texto.

    El markup de Andes pone el <button> vacio y el texto en un <div> hermano:
        <li class="andes-list__item">
          <button class="andes-list__item-actionable"></button>
          <div class="andes-list__item-first-column">Ver Perfil</div>
        </li>
    Asi que localizamos el <li> por su texto y devolvemos su boton (o el <li>
    mismo, que tambien recibe el clic).
    """
    texto_bajo = texto.lower()

    for li in driver.find_elements(By.CSS_SELECTOR, "li.andes-list__item"):
        try:
            if not li.is_displayed():
                continue
            if texto_bajo not in (li.text or "").lower():
                continue
            botones = li.find_elements(
                By.CSS_SELECTOR, "button.andes-list__item-actionable"
            )
            if botones:
                return botones[0]
            return li
        except StaleElementReferenceException:
            continue

    # Respaldo: cualquier elemento visible del menu que contenga el texto
    try:
        for el in driver.find_elements(
            By.XPATH,
            f"//*[contains(@class,'andes-list__item') and contains(., '{texto}')]",
        ):
            if el.is_displayed():
                return el
    except Exception:
        pass

    return None


def abrir_perfiles_por_menu(driver, registros):
    """Plan B: si el listado no expone el ID, entra por el menu de 3 puntos.

    Por cada fila: clic en los 3 puntos -> "Ver Perfil" -> leer -> volver atras.
    Es mas lento y fragil, pero funciona cuando no hay enlace en el listado.
    """
    log("Modo menu: se abrira el perfil fila por fila (mas lento).")

    # OJO: al volver atras se pierde la paginacion y solo quedan las filas de
    # la primera tanda. Por eso este modo solo cubre las que sigan visibles.
    disponibles = len(driver.find_elements(By.CSS_SELECTOR, "li.list__row"))
    if disponibles < len(registros):
        log(
            f"AVISO: tras volver a la lista solo hay {disponibles} filas visibles "
            f"de {len(registros)}. Solo esas obtendran ID/telefono/e-mail."
        )

    total = min(disponibles, len(registros))

    for i, r in enumerate(registros[:total], start=1):
        try:
            # Hay que reubicar la fila en cada vuelta, porque al navegar se
            # pierden las referencias del DOM.
            filas = driver.find_elements(By.CSS_SELECTOR, "li.list__row")
            if i - 1 >= len(filas):
                log(f"  Fila {i} ya no esta disponible; se omite.")
                continue
            fila = filas[i - 1]

            boton = fila.find_element(By.CSS_SELECTOR, "button.menu__button")
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", boton
            )
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", boton)
            time.sleep(0.6)

            # "Ver Perfil" es la primera opcion del menu flotante.
            # OJO: el <button class="andes-list__item-actionable"> viene VACIO;
            # el texto vive en un <div> hermano dentro del mismo <li>. Por eso
            # buscamos el <li> por su texto y de ahi sacamos su boton.
            opcion = WebDriverWait(driver, 10).until(
                lambda d: buscar_opcion_menu(d, "Ver Perfil")
            )
            driver.execute_script("arguments[0].click();", opcion)

            WebDriverWait(driver, 20).until(
                lambda d: "/drivers/edit/" in d.current_url
            )
            time.sleep(0.5)

            datos = leer_perfil(driver)
            r["id"] = datos["id"] or r["id"]
            r["telefono"] = datos["telefono"]
            r["email"] = datos["email"]

            driver.back()
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.list__row"))
            )
            time.sleep(0.5)
        except Exception as e:
            log(f"  Fila {i} ({r['nombre']}): no se pudo abrir el perfil - {resumir_error(e)}")
            # Intentar volver a la lista si nos quedamos en el perfil
            try:
                if "/drivers/edit/" in driver.current_url:
                    driver.get(URL)
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "li.list__row")
                        )
                    )
            except Exception:
                pass

        if i % 10 == 0 or i == total:
            log(f"  Perfiles leidos: {i}/{total}")

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
            str(r["n"]),
            r.get("id", ""),
            r["nombre"],
            r["curp"],
            r["estatus"],
            r.get("observacion", ""),
            r.get("telefono", ""),
            r.get("email", ""),
            r["tipo"],
            r["fecha"],
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

        con_id = sum(1 for r in registros if r["id"])
        log(f"IDs obtenidos del listado: {con_id}/{len(registros)}")

        # Guardamos ya mismo lo del listado: si el paso de perfiles falla o se
        # interrumpe, no perdemos lo que ya costo trabajo cargar.
        txt, csv_path = guardar(registros)
        log(f"Respaldo del listado guardado: {os.path.basename(txt)}")

        # --- Paso opcional: abrir perfiles ---
        print()
        print("-" * 70)
        if con_id == len(registros):
            print("  Ya tenemos el ID de todos los drivers.")
            print("  Abrir los perfiles solo agregaria TELEFONO y E-MAIL,")
            print(f"  y tomaria unos {len(registros) * 3 // 60 + 1} minutos aprox.")
        else:
            print(f"  Faltan IDs de {len(registros) - con_id} drivers.")
            print("  Para obtenerlos hay que abrir su perfil uno por uno,")
            print(f"  lo que tomaria unos {len(registros) * 4 // 60 + 1} minutos aprox.")
            print("  De paso se obtienen tambien telefono y e-mail.")
        print("-" * 70)
        resp = input("\n>>> Abrir los perfiles? (s/n): ").strip().lower()

        if resp.startswith("s"):
            try:
                abrir_perfiles(driver, registros)
            except KeyboardInterrupt:
                log("Lectura de perfiles interrumpida; se guarda lo obtenido.")
            except Exception as e:
                log(f"Fallo la lectura de perfiles: {e}")
                log("Se guarda de todos modos lo que se alcanzo a obtener.")
            txt, csv_path = guardar(registros)

        # Resumen por estatus
        conteo = {}
        for r in registros:
            clave = r["estatus"] or "(sin estatus)"
            conteo[clave] = conteo.get(clave, 0) + 1

        n_id = sum(1 for r in registros if r.get("id"))
        n_tel = sum(1 for r in registros if r.get("telefono"))
        n_mail = sum(1 for r in registros if r.get("email"))

        print()
        print("=" * 70)
        print(f"  LISTO. {len(registros)} drivers extraidos.")
        print()
        for clave in sorted(conteo, key=lambda k: -conteo[k]):
            print(f"    {clave:<20} {conteo[clave]}")
        print()
        print(f"    Con ID               {n_id}/{len(registros)}")
        if n_tel or n_mail:
            print(f"    Con telefono         {n_tel}/{len(registros)}")
            print(f"    Con e-mail           {n_mail}/{len(registros)}")
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

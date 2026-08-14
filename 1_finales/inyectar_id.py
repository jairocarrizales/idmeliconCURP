# -*- coding: utf-8 -*-
"""
Descarga la prefactura TAL CUAL y le inserta el ID del conductor.

Lo unico que cambia respecto del archivo que descarga el panel es una
columna nueva, 'ID usuario', justo despues de 'Conductor'. Todo lo demas
-cabecera, subtotales, totales, orden de las filas, separadores- queda
exactamente igual.

De donde sale el ID:
    el CSV trae 'ID de ruta'; el reporte de operacion dice que conductor
    hizo esa ruta. Se cruza por numero, nunca por nombre.
"""

import io
import os
import re
import csv
import time
import shutil
from datetime import datetime

# El CSV de la prefactura, tal como lo baja el panel
API_CSV = ("https://envios.adminml.com/logistics/billing/api/pre-invoices/"
           "{id}/reports/details/csv")
API_DETALLE = ("https://envios.adminml.com/logistics/billing/api/pre-invoices/"
               "{id}/reports/details")
API_REPORTE = "https://envios.adminml.com/api/carriers/reports"

# La columna despues de la cual se inserta el ID
COL_CONDUCTOR = "conductor"
COL_RUTA = "id de ruta"


def limpiar(v):
    if v is None:
        return ""
    return " ".join(str(v).split()).strip()


def sin_tildes(t):
    t = limpiar(t).lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("ü", "u")):
        t = t.replace(a, b)
    return t


def bajar_csv(driver, id_pref, carpeta, log=print):
    """Descarga el CSV presionando el boton, como lo haria una persona.

    No hay endpoint que copiar: el navegador arma el CSV con JavaScript a
    partir del JSON. Por eso se presiona 'Descargar' y se elige CSV, y asi
    el archivo lo genera MELI y sale identico al que se baja a mano.

    Devuelve la ruta del archivo descargado.
    """
    from selenium.webdriver.common.by import By

    antes = set(os.listdir(carpeta)) if os.path.isdir(carpeta) else set()

    # 1) El enlace azul 'Descargar' de la seccion, que abre el dialogo
    if not _abrir_dialogo(driver, log):
        raise RuntimeError(
            "No se encontro el enlace 'Descargar' en la pagina. "
            "Revisa que se vea el detalle de la prefactura."
        )
    time.sleep(1.5)

    # 2) Elegir CSV. Es un radio <input value="GENERATE_CSV">, no un boton:
    #    hay que marcarlo y avisar a la pagina para que habilite Descargar.
    if not _marcar_csv(driver, log):
        log("  No se pudo marcar CSV; se intenta descargar de todos modos.")
    time.sleep(0.8)

    # 3) El boton 'Descargar' del dialogo, que estaba gris hasta ahora
    if not _clic_descargar_final(driver, log):
        raise RuntimeError(
            "No se pudo presionar 'Descargar' en el dialogo de formato."
        )

    # 4) Esperar a que el archivo aparezca en la carpeta
    ruta = _esperar_descarga(carpeta, antes, log=log)
    if not ruta:
        raise RuntimeError(
            "La descarga no llego. Revisa la carpeta de descargas de Chrome."
        )
    log(f"  Descargado: {os.path.basename(ruta)}")
    return ruta


def _marcar_csv(driver, log=print):
    """Marca la opcion CSV del dialogo.

    El componente de Andes no reacciona a un clic sintetico sobre el
    <input>: al hacerlo por JS el atributo queda en data-andes-state="true"
    en vez de "checked", y el boton Descargar sigue gris.

    La solucion es hacer clic REAL (de Selenium, no de JS) sobre la caja
    que envuelve al radio, que es donde haria clic una persona. Se
    comprueba con data-andes-state que de verdad quedo marcado.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    def quedo_marcado():
        try:
            for el in driver.find_elements(
                    By.CSS_SELECTOR, "input[value='GENERATE_CSV']"):
                estado = (el.get_attribute("data-andes-state") or "").lower()
                if estado == "checked" or el.is_selected():
                    return True
        except Exception:
            pass
        return False

    # La caja clickeable: el contenedor del radio, o su texto 'CSV'
    objetivos = []
    try:
        for inp in driver.find_elements(
                By.CSS_SELECTOR, "input[value='GENERATE_CSV']"):
            # El div que envuelve al input es el que recibe el clic
            for xp in ("./ancestor::div[@data-andes-box-selector-item][1]",
                       "./following-sibling::div[1]",
                       "./parent::*"):
                try:
                    objetivos.append(inp.find_element(By.XPATH, xp))
                except Exception:
                    continue
            objetivos.append(inp)
    except Exception:
        pass

    # Respaldo: cualquier cosa visible que diga exactamente CSV
    try:
        objetivos += driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='CSV']")
    except Exception:
        pass

    for el in objetivos:
        try:
            if not el.is_displayed():
                continue
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            # Clic REAL, no execute_script: es lo que el componente escucha
            try:
                el.click()
            except Exception:
                ActionChains(driver).move_to_element(el).click().perform()
            time.sleep(0.5)
            if quedo_marcado():
                log("  Marcado: CSV")
                return True
        except Exception:
            continue

    return quedo_marcado()


def _clic_descargar_final(driver, log=print):
    """Presiona el 'Descargar' del dialogo, el que estaba gris.

    Hay dos botones con ese texto: el enlace azul de la seccion
    (andes-button--mute, el que abrio el dialogo) y el del dialogo
    (andes-modal__actions, andes-button--loud). Se busca el segundo.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    # Del mas especifico al mas general
    selectores = (
        ".andes-modal__actions button",
        "[class*='modal'] button.andes-button--loud",
        "[role='dialog'] button",
    )
    candidatos = []
    for sel in selectores:
        try:
            candidatos += driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue

    # Respaldo: cualquier boton con ese texto, de atras hacia adelante
    # (el del dialogo se dibuja despues del que lo abrio)
    if not candidatos:
        try:
            candidatos = list(reversed(driver.find_elements(
                By.XPATH,
                "//button[contains(translate(., 'DESCARGAR', 'descargar'),"
                " 'descargar')]")))
        except Exception:
            pass

    for el in candidatos:
        try:
            if not el.is_displayed():
                continue
            texto = sin_tildes(el.text)
            if texto and "descargar" not in texto:
                continue
            if not el.is_enabled() or el.get_attribute("disabled"):
                continue

            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            try:
                el.click()
            except Exception:
                ActionChains(driver).move_to_element(el).click().perform()
            log("  Presionado: 'Descargar' del dialogo")
            return True
        except Exception:
            continue

    log("  El boton 'Descargar' del dialogo sigue deshabilitado.")
    return False


def _abrir_dialogo(driver, log=print):
    """Presiona el enlace 'Descargar' de la seccion, que abre el dialogo.

    Es el <button class="andes-button--mute"> dentro de
    'pre-invoice-detail-card__download'. Se usa clic real porque el clic
    por JS no siempre lo abre.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    selectores = (
        ".pre-invoice-detail-card__download button",
        "[class*='card__download'] button",
        "button.andes-button--mute",
    )
    candidatos = []
    for sel in selectores:
        try:
            candidatos += driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue

    if not candidatos:
        try:
            candidatos = driver.find_elements(
                By.XPATH,
                "//button[contains(translate(., 'DESCARGAR', 'descargar'),"
                " 'descargar')] | //a[contains(translate(., 'DESCARGAR',"
                " 'descargar'), 'descargar')]")
        except Exception:
            pass

    for el in candidatos:
        try:
            if not el.is_displayed():
                continue
            texto = sin_tildes(el.text)
            if texto and "descargar" not in texto:
                continue
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            try:
                el.click()
            except Exception:
                ActionChains(driver).move_to_element(el).click().perform()
            log("  Presionado: 'Descargar' de la seccion")
            time.sleep(1)
            # Comprobar que el dialogo abrio de verdad
            if driver.find_elements(By.CSS_SELECTOR,
                                    "[role='dialog'], .andes-modal__content"):
                return True
        except Exception:
            continue
    return False


def _esperar_descarga(carpeta, antes, segundos=60, log=print):
    """Espera a que aparezca un archivo nuevo y termine de bajarse."""
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            ahora = set(os.listdir(carpeta))
        except OSError:
            time.sleep(0.5)
            continue

        nuevos = [n for n in ahora - antes
                  if not n.endswith((".crdownload", ".tmp"))]
        # .crdownload significa que Chrome sigue escribiendo
        if nuevos and not any(n.endswith(".crdownload") for n in ahora - antes):
            candidatos = [os.path.join(carpeta, n) for n in nuevos]
            csvs = [c for c in candidatos if c.lower().endswith(".csv")]
            elegido = (csvs or candidatos)[0]
            # Que el tamaño se estabilice antes de leerlo
            tam = -1
            for _ in range(10):
                nuevo_tam = os.path.getsize(elegido)
                if nuevo_tam == tam and nuevo_tam > 0:
                    return elegido
                tam = nuevo_tam
                time.sleep(0.4)
            return elegido
        time.sleep(0.5)
    return ""


def leer_archivo(ruta):
    """Lee el CSV descargado, tolerando la codificacion que traiga."""
    for codificacion in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with io.open(ruta, encoding=codificacion) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with io.open(ruta, encoding="utf-8", errors="replace") as f:
        return f.read()


def leer_csv(texto):
    """Parte el CSV en filas, conservando todo tal cual."""
    return list(csv.reader(io.StringIO(texto), delimiter=";"))


def indice_cabecera(filas):
    """Ubica la fila de encabezado del detalle y las columnas que importan.

    El archivo tiene dos bloques: dos filas de metadatos arriba, y luego el
    detalle con su propio encabezado. Hay que encontrar el segundo.
    """
    for i, fila in enumerate(filas):
        normal = [sin_tildes(c) for c in fila]
        if COL_CONDUCTOR in normal:
            return i, {
                "conductor": normal.index(COL_CONDUCTOR),
                "ruta": (normal.index(COL_RUTA)
                         if COL_RUTA in normal else None),
            }
    return None, {}


def insertar_id(filas, mapa_rutas, log=print):
    """Inserta la columna 'ID usuario' despues de 'Conductor'.

    mapa_rutas: {id_ruta: {"id": ..., "nombre": ...}}
    Devuelve (filas_nuevas, cuantas_con_id, cuantas_sin_id).
    """
    i_cab, cols = indice_cabecera(filas)
    if i_cab is None:
        raise RuntimeError(
            "No se encontro la columna 'Conductor' en el CSV. "
            "Quiza MELI cambio el formato."
        )

    i_cond = cols["conductor"]
    i_ruta = cols["ruta"]
    log(f"  Encabezado en la linea {i_cab + 1}, "
        f"Conductor en la columna {i_cond + 1}")

    if i_ruta is None:
        raise RuntimeError("El CSV no trae 'ID de ruta'; sin eso no hay cruce.")

    nuevas = []
    con_id = sin_id = 0

    for i, fila in enumerate(filas):
        if not fila:                       # linea en blanco: se conserva
            nuevas.append(fila)
            continue

        # Solo se toca el bloque del detalle, de su encabezado hacia abajo
        if i < i_cab or len(fila) <= i_cond:
            nuevas.append(fila)
            continue

        nueva = list(fila)
        if i == i_cab:
            valor = "ID usuario"
        else:
            ruta = limpiar(fila[i_ruta]) if i_ruta < len(fila) else ""
            info = mapa_rutas.get(ruta) if ruta else None
            valor = info["id"] if info else ""
            # Las filas de subtotal y total no tienen ruta: no cuentan
            if ruta:
                if valor:
                    con_id += 1
                else:
                    sin_id += 1

        nueva.insert(i_cond + 1, valor)
        nuevas.append(nueva)

    log(f"  {con_id} filas con ID de usuario"
        + (f", {sin_id} sin encontrar su ruta" if sin_id else ""))
    return nuevas, con_id, sin_id


def escribir_csv(filas, ruta):
    """Escribe el CSV con el mismo formato del original: ';' y UTF-8 BOM."""
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        for fila in filas:
            w.writerow(fila)
    return ruta


def rango_de_fechas(filas):
    """El rango real que cubren las rutas del archivo.

    La prefactura de una quincena incluye rutas de fuera de ella: cargos
    rezagados de semanas anteriores. En un caso real, la de 202607Q2 (16 al
    31 de julio) traia rutas desde el 6 de junio, y pedir el reporte solo
    del periodo nominal dejaba 144 filas sin id.

    Devuelve (desde, hasta) en formato aaaa-mm-dd.
    """
    i_cab, cols = indice_cabecera(filas)
    if i_cab is None:
        return "", ""

    # Buscar la columna de fecha de inicio
    normal = [sin_tildes(c) for c in filas[i_cab]]
    i_fecha = None
    for j, c in enumerate(normal):
        if "fecha de inicio" in c or c == "fecha":
            i_fecha = j
            break
    if i_fecha is None:
        return "", ""

    fechas = []
    for fila in filas[i_cab + 1:]:
        if len(fila) <= i_fecha:
            continue
        d = limpiar(fila[i_fecha])
        # dd/mm/aaaa
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", d)
        if m:
            fechas.append(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")

    if not fechas:
        return "", ""
    return min(fechas), max(fechas)


def periodo_del_csv(filas):
    """Saca el periodo (202607Q1) de la cabecera del archivo."""
    for i, fila in enumerate(filas[:6]):
        normal = [sin_tildes(c) for c in fila]
        if "periodo" in normal and i + 1 < len(filas):
            j = normal.index("periodo")
            siguiente = filas[i + 1]
            if j < len(siguiente):
                return limpiar(siguiente[j])
    # Respaldo: buscar algo con forma de periodo
    for fila in filas[:6]:
        for c in fila:
            if re.fullmatch(r"\d{6}Q\d", limpiar(c)):
                return limpiar(c)
    return ""


def id_prefactura_del_csv(filas):
    """Saca el ID de prefactura de la cabecera."""
    for i, fila in enumerate(filas[:6]):
        normal = [sin_tildes(c) for c in fila]
        if "id prefactura" in normal and i + 1 < len(filas):
            j = normal.index("id prefactura")
            siguiente = filas[i + 1]
            if j < len(siguiente):
                return limpiar(siguiente[j])
    return ""

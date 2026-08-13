# -*- coding: utf-8 -*-
"""
Leer un XLSX sin openpyxl.

Un XLSX es un ZIP con XML adentro. Parsearlo a mano evita meter openpyxl al
ejecutable (unos 5 MB) cuando lo unico que se necesita es leer una tabla.

Verificado contra openpyxl con archivos reales: mismas filas, mismos valores.

Uso:
    encabezados, filas = leer_xlsx(datos_en_bytes)
"""

import io
import re
import zipfile


def leer_xlsx(datos):
    """Devuelve (encabezados, filas) de la primera hoja.

    datos: bytes del archivo .xlsx
    """
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        # Las celdas de texto no guardan el texto: guardan un indice a esta
        # tabla compartida.
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S):
                # Un <si> puede tener varios <t> si el texto tiene formato
                texto = "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
                compartidas.append(_desescapar(texto))

        hojas = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        if not hojas:
            return [], []
        xml = z.read(sorted(hojas)[0]).decode("utf-8", "replace")

    filas = []
    for fila_xml in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
        celdas = {}
        # Dos formas: <c ...>contenido</c> y <c ... /> (celda vacia)
        for celda in re.findall(r"<c\s+([^>]*)>(.*?)</c>|<c\s+([^>]*)/>",
                                fila_xml, re.S):
            attrs = celda[0] or celda[2] or ""
            contenido = celda[1] or ""

            ref = re.search(r'r="([A-Z]+)\d+"', attrs)
            if not ref:
                continue
            col = _columna_a_indice(ref.group(1))

            valor = ""
            v = re.search(r"<v>(.*?)</v>", contenido, re.S)
            if v:
                valor = v.group(1)
                if 't="s"' in attrs:          # es un indice a compartidas
                    try:
                        valor = compartidas[int(valor)]
                    except (ValueError, IndexError):
                        pass
                else:
                    valor = _desescapar(valor)
            else:
                # Texto en linea (t="inlineStr")
                t = re.search(r"<t[^>]*>(.*?)</t>", contenido, re.S)
                if t:
                    valor = _desescapar(t.group(1))
            celdas[col] = valor

        if celdas:
            ancho = max(celdas) + 1
            filas.append([celdas.get(i, "") for i in range(ancho)])

    if not filas:
        return [], []
    return filas[0], filas[1:]


def _columna_a_indice(letras):
    """'A' -> 0, 'B' -> 1, 'AA' -> 26"""
    n = 0
    for ch in letras:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _desescapar(t):
    return (t.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#39;", "'").replace("&apos;", "'"))


def a_diccionarios(encabezados, filas):
    """Convierte a lista de dicts, util para cruzar por columna."""
    salida = []
    for f in filas:
        d = {}
        for i, cab in enumerate(encabezados):
            d[str(cab).strip()] = f[i] if i < len(f) else ""
        salida.append(d)
    return salida


def indice_de(encabezados, *nombres):
    """Busca una columna por nombre exacto o parcial, sin distinguir mayusculas.

    Util cuando el archivo puede venir con encabezados ligeramente distintos.
    """
    normal = {str(c).strip().lower(): i for i, c in enumerate(encabezados)}
    for n in nombres:
        if n.lower() in normal:
            return normal[n.lower()]
    for clave, i in normal.items():
        if any(n.lower() in clave for n in nombres):
            return i
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python leer_xlsx.py archivo.xlsx")
        sys.exit(1)

    cab, filas = leer_xlsx(open(sys.argv[1], "rb").read())
    print(f"{len(cab)} columnas, {len(filas)} filas")
    print("Encabezados:", ", ".join(str(c) for c in cab[:12]))
    for f in filas[:3]:
        print("  ", [str(c)[:20] for c in f[:8]])

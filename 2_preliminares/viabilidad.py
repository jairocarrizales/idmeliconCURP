# -*- coding: utf-8 -*-
"""
Tres preguntas antes de prometer nada sobre prediccion y asignacion:

  1. Cuanto historial guarda Mercado Libre?  -> decide si se puede entrenar
  2. Las paradas traen hora de visita?       -> tiempos reales o solo distancias
  3. Que trae una ruta ANTES de arrancar?    -> si el pronostico es posible

No supone nada: vuelca lo que hay y lo cuenta.
"""
import os
import re
import sys
import json
import time
import base64
from datetime import datetime, timedelta

PROY = r"C:\ProyectosBDB\meliusuarios"
sys.path.insert(0, os.path.join(PROY, "1_finales"))
os.chdir(os.path.join(PROY, "1_finales"))

import extraer_paradas as pa
from extraer_rutas import leer_xlsx, indice_de

BASE_DIR = os.path.join(PROY, "2_preliminares")


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def rutas_de(d, dia):
    """Cuantas rutas tiene un dia. -1 si ni siquiera responde."""
    url = (pa.API_REPORTE + "?mile=LM&init_date=%s&end_date=%s"
           "&report_type=carrier" % (dia, dia))
    try:
        r = pa.llamar(d, url, binario=True)
    except Exception:
        return -1
    if r.get("status") != 200 or not r.get("b64"):
        return -1
    try:
        cab, filas = leer_xlsx(base64.b64decode(r["b64"]))
        return len(filas) if cab else 0
    except Exception:
        return -1


def main():
    d = pa.crear_driver()
    try:
        d.get(pa.RAIZ + "/logistics/monitoring-distribution")
        log("Esperando que entres...")
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                if "login" not in u and "adminml.com/logistics" in u:
                    if rutas_de(d, pa.ayer()) >= 0:
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion.")
            return
        log("Sesion lista.")
        hallazgos = {}

        # ------------------------------------------------ 1) HISTORIAL
        print("\n" + "=" * 68)
        print("  1) CUANTO HISTORIAL HAY")
        print("=" * 68)
        hoy = datetime.now().date()
        # Por biseccion, como en capacidad: unas 10 consultas, no cientos
        alto = hoy - timedelta(days=1)
        bajo = hoy - timedelta(days=400)
        n_alto = rutas_de(d, alto.isoformat())
        print("     ayer (%s): %s rutas" % (alto, n_alto))
        n_bajo = rutas_de(d, bajo.isoformat())
        print("     hace 400 dias (%s): %s rutas" % (bajo, n_bajo))

        if n_bajo > 0:
            limite = bajo
            print("     hay mas de 400 dias de historial")
        else:
            consultas = 0
            while (alto - bajo).days > 1:
                medio = bajo + (alto - bajo) / 2
                consultas += 1
                n = rutas_de(d, medio.isoformat())
                if n > 0:
                    alto = medio
                else:
                    bajo = medio
            limite = alto
            print("     dia mas antiguo con datos: %s (%d consultas)"
                  % (limite, consultas))
        dias = (hoy - limite).days
        print("\n     >>> %d dias de historial" % dias)
        print("     >>> entrenar un modelo pide 30-60 dias minimo: %s"
              % ("ALCANZA" if dias >= 30 else "NO ALCANZA"))
        hallazgos["dias_historial"] = dias
        hallazgos["desde"] = str(limite)

        # ------------------------------------- 2) HORA DE CADA PARADA
        print("\n" + "=" * 68)
        print("  2) LAS PARADAS TRAEN HORA?")
        print("=" * 68)
        rutas = pa.rutas_del_dia(d, pa.ayer())
        print("     %d rutas ayer" % len(rutas))
        if rutas:
            rid = rutas[0]["id_ruta"]
            fichas = pa.pedir_lote(d, [rid])
            f = fichas.get(rid)
            if f and f["paradas"]:
                p0 = f["paradas"][0]
                print("     ruta %s, %d paradas" % (rid, len(f["paradas"])))
                print("\n     campos con pinta de tiempo:")
                encontrados = []
                for k, v in p0.items():
                    if re.search(r"time|hora|date|fecha|visit|arriv|eta",
                                 k, re.I):
                        encontrados.append(k)
                        print("       %-26s %s"
                              % (k, json.dumps(v, ensure_ascii=False)[:70]))
                # Dentro de orders tambien
                ords = p0.get("orders") or []
                if ords and isinstance(ords[0], dict):
                    print("\n     dentro de orders:")
                    for k, v in ords[0].items():
                        if re.search(r"time|hora|date|fecha|visit|arriv",
                                     k, re.I):
                            encontrados.append("orders." + k)
                            print("       %-26s %s"
                                  % (k, json.dumps(v, ensure_ascii=False)[:70]))
                if not encontrados:
                    print("       (ninguno)")
                print("\n     >>> %s" % ("HAY tiempos: se pueden medir "
                                         "minutos entre paradas"
                                         if encontrados else
                                         "NO hay: solo distancias"))
                hallazgos["campos_tiempo"] = encontrados
                # Todos los campos, para no perder nada
                hallazgos["campos_parada"] = sorted(p0.keys())
                print("\n     todos los campos de una parada:")
                print("       %s" % ", ".join(sorted(p0.keys())))

        # -------------------------- 3) QUE HAY ANTES DE QUE ARRANQUE
        print("\n" + "=" * 68)
        print("  3) QUE TRAE UNA RUTA DE HOY (antes de terminar)")
        print("=" * 68)
        hoy_str = hoy.isoformat()
        n_hoy = rutas_de(d, hoy_str)
        print("     hoy (%s): %s rutas en el reporte" % (hoy_str, n_hoy))
        if n_hoy > 0:
            rutas_hoy = pa.rutas_del_dia(d, hoy_str)
            print("     %d rutas" % len(rutas_hoy))
            if rutas_hoy:
                rid = rutas_hoy[0]["id_ruta"]
                fichas = pa.pedir_lote(d, [rid])
                f = fichas.get(rid)
                if f:
                    ps = f["paradas"]
                    est = {}
                    for p in ps:
                        e = p.get("status")
                        est[e] = est.get(e, 0) + 1
                    con_seq = sum(1 for p in ps
                                  if str(p.get("sequence") or "").isdigit())
                    print("     ruta %s: %d paradas" % (rid, len(ps)))
                    print("     estados: %s" % est)
                    print("     con secuencia: %d/%d" % (con_seq, len(ps)))
                    print("\n     >>> %s" % (
                        "La ruta del dia YA trae sus paradas: el pronostico "
                        "es posible por la manana"
                        if ps and con_seq else
                        "Las paradas aun no estan completas"))
                    hallazgos["ruta_hoy"] = {
                        "paradas": len(ps), "estados": est,
                        "con_secuencia": con_seq}
        else:
            print("     >>> El reporte de HOY aun no existe.")
            print("     >>> Habria que mirar el monitoreo en vivo, no el")
            print("         reporte, para pronosticar por la manana.")
            hallazgos["ruta_hoy"] = None

        arch = os.path.join(BASE_DIR, "viabilidad.json")
        with open(arch, "w", encoding="utf-8") as fh:
            json.dump(hallazgos, fh, ensure_ascii=False, indent=2)
        log("Guardado en %s" % arch)
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

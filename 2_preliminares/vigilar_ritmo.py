# -*- coding: utf-8 -*-
"""
Vigila la operacion y mide el ritmo de entrega por hora.

Las paradas NO traen hora de visita, pero si traen su estado. Comparando
una muestra con la anterior, las paradas que pasaron de 'pending' a
'complete' se entregaron en ese intervalo. No da la hora exacta de cada
entrega, pero si el ritmo, que es lo que sirve para ver que una ruta
perdio el paso.

Como se usa:

    python vigilar_ritmo.py                 empieza a las 09:00
    python vigilar_ritmo.py 10:30           empieza a esa hora
    python vigilar_ritmo.py ahora           empieza de inmediato

Se queda esperando hasta la hora indicada, avisa con un sonido cuando la
operacion arranca, y toma 5 muestras separadas una hora. Chrome queda
abierto todo el tiempo: no se cierra al terminar.
"""
import os
import re
import sys
import csv
import json
import time
from datetime import datetime, timedelta

PROY = r"C:\ProyectosBDB\meliusuarios"
sys.path.insert(0, os.path.join(PROY, "1_finales"))
os.chdir(os.path.join(PROY, "1_finales"))

import extraer_paradas as pa

BASE_DIR = os.path.join(PROY, "2_preliminares")

HORA_INICIO = "09:00"      # a que hora empieza a vigilar
MUESTRAS = 5               # cuantas tomas
INTERVALO_MIN = 60         # cada cuanto
REVISAR_CADA = 5 * 60      # cada cuanto se pregunta si ya arranco


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def alerta(veces=3):
    """Un sonido para avisar que la operacion arranco.

    winsound viene con Windows; si no esta, se usa la campana del
    terminal, que suena en cualquier sistema.
    """
    try:
        import winsound
        for _ in range(veces):
            winsound.Beep(880, 350)
            time.sleep(0.15)
            winsound.Beep(1320, 350)
            time.sleep(0.25)
    except Exception:
        for _ in range(veces * 2):
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(0.4)


def esperar_hasta(hhmm):
    """Duerme hasta esa hora de hoy. Si ya paso, sigue de inmediato."""
    if not hhmm or hhmm.lower() in ("ahora", "ya", "now"):
        return
    try:
        h, m = [int(x) for x in hhmm.split(":")]
    except ValueError:
        log("Hora no entendida (%r); se empieza ahora." % hhmm)
        return
    ahora = datetime.now()
    objetivo = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if objetivo <= ahora:
        log("Las %s ya pasaron; se empieza ahora." % hhmm)
        return
    faltan = (objetivo - ahora).total_seconds()
    log("Esperando hasta las %s (%.0f min)..." % (hhmm, faltan / 60))
    # En tramos, para poder avisar por pantalla de vez en cuando
    while True:
        restan = (objetivo - datetime.now()).total_seconds()
        if restan <= 0:
            break
        time.sleep(min(300, restan))
        restan = (objetivo - datetime.now()).total_seconds()
        if restan > 300:
            log("  faltan %.0f min" % (restan / 60))


def muestra(d, dia):
    """El estado de cada parada de cada ruta, ahora mismo."""
    t0 = time.time()
    rutas = pa.rutas_del_dia(d, dia)
    estado = {}
    ids = [r["id_ruta"] for r in rutas]
    info = {r["id_ruta"]: r for r in rutas}

    for i in range(0, len(ids), pa.LOTE):
        lote = ids[i:i + pa.LOTE]
        try:
            fichas = pa.pedir_lote(d, lote)
        except Exception as e:
            texto = str(e)
            log("  fallo un lote: %s" % texto[:90])
            if "out of memory" in texto.lower() or "frame detached" in texto.lower():
                pa._liberar_memoria(d)
            continue
        for rid, f in fichas.items():
            estado[rid] = {
                "paradas": {str(p.get("id")): p.get("status")
                            for p in f["paradas"] if p.get("id")},
                "zonas": {str(p.get("id")): p.get("zoneLabel")
                          for p in f["paradas"] if p.get("id")},
                "nombre": f.get("nombre") or info.get(rid, {}).get("ruta", ""),
                "driver": f.get("driver") or info.get(rid, {}).get("driver", ""),
                "cedis": info.get(rid, {}).get("cedis", ""),
            }
        # Cada tantos lotes, soltar la memoria acumulada
        if i and (i // pa.LOTE) % 60 == 0:
            pa._liberar_memoria(d)

    return estado, time.time() - t0


def comparar(antes, ahora):
    """Que se entrego entre dos muestras, ruta por ruta."""
    filas = []
    for rid, datos in ahora.items():
        previo = (antes.get(rid) or {}).get("paradas") or {}
        nuevas = 0
        for pid, est in datos["paradas"].items():
            if est == "complete" and previo.get(pid) not in (None, "complete"):
                nuevas += 1
        hechas = sum(1 for e in datos["paradas"].values() if e == "complete")
        total = len(datos["paradas"])
        filas.append({
            "id_ruta": rid,
            "ruta": datos["nombre"],
            "driver": datos["driver"],
            "cedis": datos["cedis"],
            "entregas": nuevas,
            "completas": hechas,
            "total": total,
            "avance": round(hechas * 100.0 / total, 1) if total else 0,
            "primera_vez": not previo,
        })
    return filas


def guardar(historial, comparaciones):
    """Un CSV con el ritmo por ruta y por intervalo."""
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(BASE_DIR, "ritmo_%s.csv" % sello)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["DESDE", "HASTA", "CEDIS", "RUTA", "ID RUTA", "DRIVER",
                    "ENTREGAS EN EL INTERVALO", "COMPLETAS", "TOTAL",
                    "AVANCE %"])
        for c in comparaciones:
            for x in c["filas"]:
                if x["primera_vez"]:
                    continue          # sin muestra previa no hay ritmo
                w.writerow([c["desde"], c["hasta"], x["cedis"], x["ruta"],
                            x["id_ruta"], x["driver"], x["entregas"],
                            x["completas"], x["total"], x["avance"]])
    return ruta


def main():
    hora = sys.argv[1] if len(sys.argv) > 1 else HORA_INICIO
    print("=" * 68)
    print("  VIGILANCIA DE RITMO")
    print("  Empieza: %s   ·   %d muestras cada %d min"
          % (hora, MUESTRAS, INTERVALO_MIN))
    print("=" * 68)

    d = pa.crear_driver()
    # Chrome NO se cierra al terminar: queda abierto para poder mirar el
    # panel, y porque cerrarlo a mitad de una vigilancia larga obligaria
    # a volver a entrar.
    try:
        d.get(pa.RAIZ + "/logistics/monitoring-distribution")
        log("Entra en Chrome si te lo pide.")
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                if "login" not in u and "adminml.com/logistics" in u:
                    if pa.rutas_del_dia(d, pa.ayer()):
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion. Chrome queda abierto.")
            return
        log("Sesion lista.")

        esperar_hasta(hora)

        # Esperar a que la operacion arranque de verdad
        dia = datetime.now().strftime("%Y-%m-%d")
        log("Vigilando si arranca la operacion...")
        arranco = False
        t0 = time.time()
        while time.time() - t0 < 6 * 3600:
            try:
                rutas = pa.rutas_del_dia(d, dia)
                if rutas:
                    log("")
                    log(">>> ARRANCO: %d rutas publicadas <<<" % len(rutas))
                    alerta()
                    arranco = True
                    break
            except RuntimeError as e:
                if "todavia no publica" not in str(e):
                    raise
            time.sleep(REVISAR_CADA)
        if not arranco:
            log("Pasaron 6 horas sin rutas. Chrome queda abierto.")
            return

        historial, comparaciones, tiempos = [], [], []

        for n in range(MUESTRAS):
            log("Muestra %d de %d..." % (n + 1, MUESTRAS))
            actual, tardo = muestra(d, dia)
            tiempos.append(tardo)
            if not actual:
                log("  no se obtuvo ninguna ruta.")
                break

            total = sum(len(x["paradas"]) for x in actual.values())
            hechas = sum(sum(1 for e in x["paradas"].values() if e == "complete")
                         for x in actual.values())
            ahora = datetime.now().strftime("%H:%M")
            log("  %d rutas · %d paradas · %d completas (%.1f%%) · %.0f s"
                % (len(actual), total, hechas,
                   hechas * 100.0 / total if total else 0, tardo))

            if historial:
                filas = comparar(historial[-1]["estado"], actual)
                movidas = [x for x in filas
                           if x["entregas"] and not x["primera_vez"]]
                nuevas = sum(x["entregas"] for x in movidas)
                comparaciones.append({"desde": historial[-1]["hora"],
                                      "hasta": ahora, "filas": filas})
                log("  >>> %d entregas entre %s y %s, en %d rutas"
                    % (nuevas, historial[-1]["hora"], ahora, len(movidas)))
                if movidas:
                    for x in sorted(movidas, key=lambda y: -y["entregas"])[:5]:
                        log("      %-9s %-20s +%-3d (%d/%d · %.0f%%)"
                            % (x["ruta"] or x["id_ruta"],
                               (x["driver"] or "")[:20], x["entregas"],
                               x["completas"], x["total"], x["avance"]))
                    # Las que no se movieron pese a tener pendientes
                    quietas = [x for x in filas
                               if not x["entregas"] and not x["primera_vez"]
                               and x["completas"] < x["total"]]
                    if quietas:
                        log("      -- %d rutas sin una sola entrega en la hora"
                            % len(quietas))

            historial.append({"hora": ahora, "estado": actual})

            if n < MUESTRAS - 1:
                falta = INTERVALO_MIN * 60 - tardo
                if falta > 0:
                    log("  siguiente muestra en %.0f min" % (falta / 60))
                    time.sleep(falta)

        # ------------------------------------------------ resultado
        print("\n" + "=" * 68)
        print("  RESULTADO")
        print("=" * 68)
        if tiempos:
            print("\n  Cada muestra tardo: %s"
                  % ", ".join("%.0f s" % t for t in tiempos))
            print("  La mas lenta: %.0f s de un intervalo de %d min"
                  % (max(tiempos), INTERVALO_MIN))

        if comparaciones:
            print("\n  Entregas por intervalo:")
            for c in comparaciones:
                n = sum(x["entregas"] for x in c["filas"]
                        if not x["primera_vez"])
                print("     %s -> %s   %5d entregas" % (c["desde"],
                                                        c["hasta"], n))
            archivo = guardar(historial, comparaciones)
            print("\n  %s" % archivo)
            print("  Una fila por ruta y por intervalo, con su ritmo.")
        else:
            print("\n  No hubo dos muestras que comparar.")

        log("Listo. Chrome queda abierto.")
    except KeyboardInterrupt:
        log("Interrumpido. Chrome queda abierto.")
    except Exception as e:
        log("ERROR: %s" % str(e)[:200])
        log("Chrome queda abierto para revisar.")
        raise


if __name__ == "__main__":
    main()

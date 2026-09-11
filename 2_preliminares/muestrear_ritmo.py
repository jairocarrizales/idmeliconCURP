# -*- coding: utf-8 -*-
"""
Mide el ritmo de entrega tomando fotos del panel cada pocos minutos.

Las paradas NO traen hora de visita, pero si traen su estado. Si se
compara una foto con la anterior, las paradas que pasaron de 'pending' a
'complete' se entregaron en ese intervalo. No da la hora exacta de cada
entrega, pero si el ritmo por intervalo, que es lo que sirve para
detectar que una ruta perdio el paso.

Esta corrida responde tres preguntas antes de construir nada:

  1. Cuanto tarda una foto?        -> si cabe en el intervalo elegido
  2. El panel refleja los cambios? -> si el estado se actualiza en vivo
  3. Aguanta la sesion?            -> si puede correr solo todo el dia
"""
import os
import sys
import json
import time
from datetime import datetime

PROY = r"C:\ProyectosBDB\meliusuarios"
sys.path.insert(0, os.path.join(PROY, "1_finales"))
os.chdir(os.path.join(PROY, "1_finales"))

import extraer_paradas as pa

BASE_DIR = os.path.join(PROY, "2_preliminares")

# Cada cuanto se toma una foto, y cuantas. Para la prueba: 4 fotos
# separadas 12 minutos = 36 minutos de observacion.
INTERVALO_MIN = 12
FOTOS = 4


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def foto(d, dia):
    """Una foto: el estado de cada parada de cada ruta, ahora mismo.

    Devuelve {id_ruta: {id_parada: estado}} y cuanto tardo.
    """
    t0 = time.time()
    rutas = pa.rutas_del_dia(d, dia)
    estado = {}
    ids = [r["id_ruta"] for r in rutas]
    nombres = {r["id_ruta"]: r for r in rutas}

    for i in range(0, len(ids), pa.LOTE):
        lote = ids[i:i + pa.LOTE]
        try:
            fichas = pa.pedir_lote(d, lote)
        except Exception as e:
            log("  fallo un lote: %s" % str(e)[:100])
            continue
        for rid, f in fichas.items():
            estado[rid] = {
                "paradas": {str(p.get("id")): p.get("status")
                            for p in f["paradas"] if p.get("id")},
                "nombre": f.get("nombre") or nombres.get(rid, {}).get("ruta", ""),
                "driver": f.get("driver") or nombres.get(rid, {}).get("driver", ""),
                "cedis": nombres.get(rid, {}).get("cedis", ""),
            }
        if i and i % (pa.LOTE * 15) == 0:
            time.sleep(0.3)

    return estado, time.time() - t0


def comparar(antes, ahora):
    """Que cambio entre dos fotos, ruta por ruta."""
    cambios = []
    for rid, datos in ahora.items():
        previo = (antes.get(rid) or {}).get("paradas") or {}
        if not previo:
            continue
        nuevas = 0
        for pid, est in datos["paradas"].items():
            if previo.get(pid) != est and est == "complete":
                nuevas += 1
        hechas = sum(1 for e in datos["paradas"].values() if e == "complete")
        total = len(datos["paradas"])
        cambios.append({
            "id_ruta": rid,
            "ruta": datos["nombre"],
            "driver": datos["driver"],
            "cedis": datos["cedis"],
            "entregas_intervalo": nuevas,
            "completas": hechas,
            "total": total,
            "avance": round(hechas * 100.0 / total, 1) if total else 0,
        })
    return cambios


def main():
    print("=" * 68)
    print("  MUESTREO DE RITMO  ·  %d fotos cada %d minutos"
          % (FOTOS, INTERVALO_MIN))
    print("=" * 68)

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
                    if pa.rutas_del_dia(d, pa.ayer()):
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion.")
            return
        log("Sesion lista.")

        dia = datetime.now().strftime("%Y-%m-%d")

        # De madrugada el reporte del dia aun no existe. En vez de
        # fallar, esperar a que MELI lo publique: asi se puede lanzar
        # temprano y que arranque solo cuando la operacion empiece.
        espera = 0
        while espera < 6 * 3600:
            try:
                rutas = pa.rutas_del_dia(d, dia)
                if rutas:
                    log("El reporte de hoy ya tiene %d rutas." % len(rutas))
                    break
            except RuntimeError as e:
                if "todavia no publica" not in str(e):
                    raise
            if espera == 0:
                log("Aun no hay reporte de hoy. Esperando a que arranque")
                log("la operacion (se revisa cada 10 minutos)...")
            time.sleep(600)
            espera += 600
        else:
            log("Pasaron 6 horas sin reporte. Se detiene.")
            return

        historial, tiempos = [], []

        for n in range(FOTOS):
            log("Foto %d de %d..." % (n + 1, FOTOS))
            actual, tardo = foto(d, dia)
            tiempos.append(tardo)
            if not actual:
                log("  no se obtuvo ninguna ruta; se detiene.")
                break
            total_paradas = sum(len(x["paradas"]) for x in actual.values())
            hechas = sum(sum(1 for e in x["paradas"].values() if e == "complete")
                         for x in actual.values())
            log("  %d rutas, %d paradas, %d completas (%.1f%%) en %.0f s"
                % (len(actual), total_paradas, hechas,
                   hechas * 100.0 / total_paradas if total_paradas else 0,
                   tardo))

            if historial:
                cambios = comparar(historial[-1]["estado"], actual)
                movidas = [c for c in cambios if c["entregas_intervalo"]]
                nuevas = sum(c["entregas_intervalo"] for c in cambios)
                log("  >>> %d entregas nuevas en %d rutas distintas"
                    % (nuevas, len(movidas)))
                if movidas:
                    top = sorted(movidas,
                                 key=lambda c: -c["entregas_intervalo"])[:5]
                    for c in top:
                        log("      %-10s %-22s +%d  (%d/%d, %.0f%%)"
                            % (c["ruta"] or c["id_ruta"],
                               (c["driver"] or "")[:22],
                               c["entregas_intervalo"], c["completas"],
                               c["total"], c["avance"]))

            historial.append({"hora": datetime.now().strftime("%H:%M:%S"),
                              "estado": actual})

            if n < FOTOS - 1:
                espera = INTERVALO_MIN * 60 - tiempos[-1]
                if espera > 0:
                    log("  esperando %.0f min hasta la siguiente..."
                        % (espera / 60))
                    time.sleep(espera)

        # ------------------------------------------------ conclusiones
        print("\n" + "=" * 68)
        print("  LO QUE SE MIDIO")
        print("=" * 68)
        if tiempos:
            print("\n  1) CUANTO TARDA UNA FOTO")
            print("     %s" % ", ".join("%.0f s" % t for t in tiempos))
            peor = max(tiempos)
            print("     la mas lenta: %.0f s de un intervalo de %d min"
                  % (peor, INTERVALO_MIN))
            print("     >>> %s" % (
                "CABE: se puede muestrear a este ritmo"
                if peor < INTERVALO_MIN * 60 * 0.5 else
                "AJUSTADO: conviene espaciar mas las fotos"))

        if len(historial) >= 2:
            print("\n  2) EL PANEL REFLEJA LOS CAMBIOS?")
            total_nuevas = 0
            for i in range(1, len(historial)):
                c = comparar(historial[i - 1]["estado"], historial[i]["estado"])
                n = sum(x["entregas_intervalo"] for x in c)
                total_nuevas += n
                print("     %s -> %s: %d entregas"
                      % (historial[i - 1]["hora"], historial[i]["hora"], n))
            print("     >>> %s" % (
                "SI: el estado cambia entre fotos, el ritmo se puede medir"
                if total_nuevas else
                "NO se vio ningun cambio. Puede ser que la operacion este "
                "detenida, o que el panel no actualice en vivo."))

            print("\n  3) AGUANTO LA SESION?")
            print("     %d fotos seguidas sin reconectar" % len(historial))
            print("     >>> %s" % ("SI" if len(historial) == FOTOS
                                   else "se corto antes de tiempo"))

        arch = os.path.join(BASE_DIR, "ritmo.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump({"fotos": [{"hora": h["hora"],
                                  "rutas": len(h["estado"])}
                                 for h in historial],
                       "segundos_por_foto": tiempos,
                       "intervalo_min": INTERVALO_MIN}, f,
                      ensure_ascii=False, indent=2)
        log("Guardado en %s" % arch)
    finally:
        try:
            d.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

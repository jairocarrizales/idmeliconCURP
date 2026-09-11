# -*- coding: utf-8 -*-
"""
Vigila la operacion EN VIVO y mide el ritmo por hora.

A diferencia del intento anterior, que preguntaba por el reporte de
cierre del dia -y por eso esperaba en balde hasta la noche-, este usa la
API que alimenta la pantalla de monitoreo:

    POST /logistics/api/monitoring/get-routes-list
    {"serviceCenterId":"SMT1","page":1,"pageSize":50,
     "siteId":"MLM","order_by":"performance"}

Esa API trae, ademas de los contadores, las alertas que MELI YA calcula:
ruta demorada, primer beep tarde, login tarde, vehiculo inactivo. Asi que
no hay que deducir el atraso: viene marcado. Las muestras sirven para el
ritmo por hora y para ver quien no avanza.

Como se usa:

    python vigilar_vivo.py            5 muestras cada 60 min
    python vigilar_vivo.py 15         5 muestras cada 15 min
"""
import os
import sys
import csv
import json
import time
from datetime import datetime

PROY = r"C:\ProyectosBDB\meliusuarios"
sys.path.insert(0, os.path.join(PROY, "1_finales"))
os.chdir(os.path.join(PROY, "1_finales"))

BASE_DIR = os.path.join(PROY, "2_preliminares")
PERFIL = os.path.join(BASE_DIR, "chrome_vigilante")
RAIZ = "https://envios.adminml.com"
PANEL = RAIZ + "/logistics/monitoring-distribution"
API_RUTAS = RAIZ + "/logistics/api/monitoring/get-routes-list"

# Los ocho centros de la operacion. Salieron del catalogo de filtros del
# panel; si aparece uno nuevo, el propio programa lo dira.
CEDIS = ["SMT1", "SMT2", "SMT3", "SQR1", "SQR2", "SGD1", "SGD3", "SCQ1",
         "SDG1", "STR1", "STL1", "SZL1", "EQR2", "EZL1", "SGD2"]

# Doce muestras cada 15 minutos cubren tres horas de operacion. Cada
# muestra cuesta unos 9 segundos -medido con 123 rutas en 12 centros-
# asi que muestrear seguido sale practicamente gratis.
MUESTRAS = 12
INTERVALO_MIN = 15

SCRIPT_POST = """
const url = arguments[0], cuerpo = arguments[1];
const done = arguments[arguments.length - 1];
fetch(url, {method: 'POST', credentials: 'include',
            headers: {'Content-Type': 'application/json',
                      'Accept': 'application/json'},
            body: cuerpo})
  .then(r => r.text().then(t => done({ok: r.ok, status: r.status, body: t})))
  .catch(e => done({ok: false, status: 0, body: String(e)}));
"""


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def alerta(veces=3):
    """Un sonido para avisar que la operacion arranco."""
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


def preparar_perfil():
    """Perfil propio, copiado del normal para heredar la sesion.

    Compartirlo con los demas extractores costo una corrida entera: cada
    uno cierra Chrome al terminar y mata la sesion del que espera.
    """
    if os.path.isdir(PERFIL):
        return
    from extraer_rutas import PROFILE_DIR
    if not os.path.isdir(PROFILE_DIR):
        return
    import shutil
    log("Creando el perfil del vigilante...")
    try:
        shutil.copytree(PROFILE_DIR, PERFIL,
                        ignore=shutil.ignore_patterns(
                            "Singleton*", "lockfile", "LOCK",
                            "DevToolsActivePort", "*.tmp"))
    except Exception as e:
        log("No se pudo copiar (%s); se usara uno nuevo." % str(e)[:70])


def cerrar_huerfanos():
    """Cierra los Chrome que quedaron agarrados a ESTE perfil.

    Si una corrida se corta a la fuerza, sus Chrome siguen vivos y el
    siguiente arranque falla con "Chrome instance exited". Borrar el
    lockfile no basta: los procesos vivos lo vuelven a crear.
    """
    if os.name != "nt":
        return
    marca = os.path.basename(PERFIL)
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
          "-ErrorAction SilentlyContinue; $_.ProcessId }" % marca)
    try:
        import subprocess
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        n = len([x for x in (res.stdout or "").split() if x.strip().isdigit()])
        if n:
            log("Se cerraron %d Chrome huerfanos del perfil." % n)
            time.sleep(2)
    except Exception:
        pass


def crear_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    preparar_perfil()
    # Primero los procesos, luego los locks: al reves no sirve de nada
    cerrar_huerfanos()
    for n in ("lockfile", "LOCK", "SingletonLock", "SingletonCookie",
              "SingletonSocket", "DevToolsActivePort"):
        for c in (PERFIL, os.path.join(PERFIL, "Default")):
            ruta = os.path.join(c, n)
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
            except Exception:
                pass
    o = Options()
    o.add_argument("--user-data-dir=%s" % PERFIL)
    o.add_argument("--profile-directory=Default")
    o.add_argument("--start-maximized")
    o.add_argument("--disable-blink-features=AutomationControlled")
    o.add_argument("--lang=es-MX")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=o)


def sesion_viva(d):
    try:
        _ = d.current_url
        return True
    except Exception:
        return False


# El tamano de pagina que manda la web. Subirlo a 200 para ahorrarse
# paginar da 422 "Invalid values in body object": la API solo acepta
# este valor. Se usan los parametros capturados tal cual.
TAM_PAGINA = 50


def rutas_de(d, cedis):
    """Las rutas en curso de un centro, con sus contadores y alertas.

    Pagina hasta agotar: la respuesta trae pagination.hasNext.
    """
    todas = []
    pagina = 1
    while pagina <= 40:
        cuerpo = json.dumps({"serviceCenterId": cedis, "page": pagina,
                             "pageSize": TAM_PAGINA, "siteId": "MLM",
                             "order_by": "performance"})
        d.set_script_timeout(90)
        r = d.execute_async_script(SCRIPT_POST, API_RUTAS, cuerpo)
        # Devolver [] ante un fallo lo haria indistinguible de "no hay
        # rutas", y un centro caido se leeria como uno tranquilo.
        if not r or not r.get("ok"):
            raise RuntimeError("%s respondio %s: %s"
                               % (cedis, (r or {}).get("status", "?"),
                                  str((r or {}).get("body", ""))[:140]))
        try:
            datos = json.loads(r["body"]) or {}
        except ValueError:
            raise RuntimeError("%s devolvio algo que no es JSON: %s"
                               % (cedis, str(r.get("body", ""))[:140]))
        lote = datos.get("routes") or []
        todas.extend(lote)
        pag = datos.get("pagination") or {}
        if not pag.get("hasNext") or not lote:
            break
        pagina += 1
        time.sleep(0.2)
    return todas


def normalizar(r, cedis):
    """Una ruta en vivo, con lo que importa para vigilarla."""
    c = r.get("counters") or {}
    drv = r.get("driver") or {}
    plan = r.get("plannedRoute") or {}
    t = r.get("timingData") or {}

    # Las alertas que MELI ya calcula: no hay que deducirlas
    avisos = []
    for clave, etiqueta in (("delayedRoute", "ruta demorada"),
                            ("firstBeepDelayed", "primer beep tarde"),
                            ("loginDelayed", "login tarde"),
                            ("inactivityVehicle", "vehiculo inactivo"),
                            ("delayedStemout", "salida tarde"),
                            ("pendingSackDelivery", "sacas pendientes")):
        a = r.get(clave) or {}
        if isinstance(a, dict) and a.get("alert"):
            avisos.append(etiqueta)

    total = c.get("total") or 0
    hechas = c.get("delivered") or 0
    return {
        "cedis": cedis,
        "id_ruta": str(r.get("id") or ""),
        "ruta": r.get("cluster") or "",
        "id_driver": str(drv.get("driverId") or ""),
        "driver": drv.get("driverName") or "",
        "estado": r.get("substatus") or r.get("status") or "",
        "total": total,
        "entregados": hechas,
        "pendientes": c.get("pending") or 0,
        "fallidos": c.get("notDelivered") or 0,
        "avance": round(hechas * 100.0 / total, 1) if total else 0,
        "avance_plan": (plan.get("progressPercent") or "").replace(",", "."),
        "desempeno": r.get("routePerformanceScore") or "",
        "orh": t.get("orh") or 0,
        "reclamos_driver": drv.get("driverClaims") or 0,
        "vehiculo": (r.get("vehicle") or {}).get("description") or "",
        "alertas": ", ".join(avisos),
    }


def muestra(d):
    """Todas las rutas en curso de todos los centros."""
    t0 = time.time()
    filas, sin_rutas = [], []
    for cedis in CEDIS:
        try:
            rutas = rutas_de(d, cedis)
        except Exception as e:
            log("  %s fallo: %s" % (cedis, str(e)[:70]))
            continue
        if not rutas:
            sin_rutas.append(cedis)
            continue
        for r in rutas:
            filas.append(normalizar(r, cedis))
        time.sleep(0.2)
    return filas, time.time() - t0, sin_rutas


def comparar(antes, ahora):
    """Cuantas entregas hubo entre dos muestras, por ruta."""
    previo = {f["id_ruta"]: f["entregados"] for f in antes}
    for f in ahora:
        anterior = previo.get(f["id_ruta"])
        f["entregas_intervalo"] = (f["entregados"] - anterior
                                   if anterior is not None else None)
    return ahora


def guardar(historial):
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(BASE_DIR, "ritmo_vivo_%s.csv" % sello)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["HORA", "CEDIS", "RUTA", "ID RUTA", "ID DRIVER",
                    "DRIVER", "ESTADO", "ENTREGADOS", "PENDIENTES",
                    "FALLIDOS", "TOTAL", "AVANCE %", "AVANCE PLAN %",
                    "DESEMPENO", "ENTREGAS EN EL INTERVALO", "HORAS EN RUTA",
                    "RECLAMOS DEL DRIVER", "VEHICULO", "ALERTAS"])
        for h in historial:
            for x in h["filas"]:
                w.writerow([h["hora"], x["cedis"], x["ruta"], x["id_ruta"],
                            x["id_driver"], x["driver"], x["estado"],
                            x["entregados"], x["pendientes"], x["fallidos"],
                            x["total"], x["avance"], x["avance_plan"],
                            x["desempeno"],
                            x.get("entregas_intervalo", ""),
                            round((x["orh"] or 0) / 60.0, 1),
                            x["reclamos_driver"], x["vehiculo"],
                            x["alertas"]])
    return ruta


def main():
    intervalo = INTERVALO_MIN
    muestras = MUESTRAS
    if len(sys.argv) > 1:
        try:
            intervalo = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            muestras = int(sys.argv[2])
        except ValueError:
            pass

    print("=" * 70)
    print("  VIGILANCIA EN VIVO  ·  %d muestras cada %d min  ·  %d centros"
          % (muestras, intervalo, len(CEDIS)))
    print("=" * 70)

    d = crear_driver()
    # Chrome NO se cierra al terminar: cerrarlo obligaria a entrar de nuevo
    try:
        d.get(PANEL)
        log("Entra en Chrome si te lo pide.")
        t0 = time.time()
        dentro = False
        while time.time() - t0 < 3600:
            try:
                u = d.current_url or ""
                if "login" not in u and "monitoring" in u:
                    # La senal fiable: que la API responda
                    if rutas_de(d, CEDIS[0]) is not None:
                        dentro = True
                        break
            except Exception:
                pass
            time.sleep(3)
        if not dentro:
            log("No se detecto la sesion. Chrome queda abierto.")
            return
        log("Sesion lista.")

        historial = []
        for n in range(muestras):
            if not sesion_viva(d):
                log("Sesion caida; reabriendo...")
                try:
                    d.quit()
                except Exception:
                    pass
                d = crear_driver()
                d.get(PANEL)
                time.sleep(8)

            log("Muestra %d de %d..." % (n + 1, muestras))
            filas, tardo, sin_rutas = muestra(d)
            hora = datetime.now().strftime("%H:%M")

            if not filas:
                log("  ningun centro tiene rutas en curso (%.0f s)" % tardo)
                if n == 0:
                    log("  la operacion aun no arranca; se sigue mirando")
                time.sleep(min(300, intervalo * 60))
                continue

            if n == 0:
                alerta()

            if historial:
                filas = comparar(historial[-1]["filas"], filas)

            total = sum(f["total"] for f in filas)
            hechas = sum(f["entregados"] for f in filas)
            con_alerta = [f for f in filas if f["alertas"]]
            log("  %d rutas · %d de %d paquetes (%.1f%%) · %.0f s"
                % (len(filas), hechas, total,
                   hechas * 100.0 / total if total else 0, tardo))

            if historial:
                nuevas = sum(f.get("entregas_intervalo") or 0 for f in filas)
                movidas = [f for f in filas
                           if (f.get("entregas_intervalo") or 0) > 0]
                log("  >>> %d entregas desde %s, en %d rutas"
                    % (nuevas, historial[-1]["hora"], len(movidas)))
                quietas = [f for f in filas
                           if f.get("entregas_intervalo") == 0
                           and f["pendientes"] > 0]
                if quietas:
                    log("  >>> %d rutas SIN una sola entrega en el intervalo:"
                        % len(quietas))
                    for f in quietas[:6]:
                        log("        %-9s %-22s %d pendientes"
                            % (f["ruta"], (f["driver"] or "")[:22],
                               f["pendientes"]))

            if con_alerta:
                log("  >>> %d rutas con alerta de Mercado Libre:"
                    % len(con_alerta))
                for f in con_alerta[:6]:
                    log("        %-9s %-20s %s"
                        % (f["ruta"], (f["driver"] or "")[:20], f["alertas"]))

            historial.append({"hora": hora, "filas": filas})

            if n < muestras - 1:
                falta = intervalo * 60 - tardo
                if falta > 0:
                    log("  siguiente muestra en %.0f min" % (falta / 60))
                    time.sleep(falta)

        print("\n" + "=" * 70)
        print("  RESULTADO")
        print("=" * 70)
        if historial:
            print("\n  Entregas por intervalo:")
            for i in range(1, len(historial)):
                n = sum(f.get("entregas_intervalo") or 0
                        for f in historial[i]["filas"])
                print("     %s -> %s   %5d entregas"
                      % (historial[i - 1]["hora"], historial[i]["hora"], n))
            archivo = guardar(historial)
            print("\n  %s" % archivo)
            print("  Una fila por ruta y por muestra, con su ritmo y alertas.")
        else:
            print("\n  No se tomo ninguna muestra con rutas.")
        log("Listo. Chrome queda abierto.")
    except KeyboardInterrupt:
        log("Interrumpido. Chrome queda abierto.")
    except Exception as e:
        log("ERROR: %s" % str(e)[:200])
        raise


if __name__ == "__main__":
    main()

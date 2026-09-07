# -*- coding: utf-8 -*-
"""
Busca la API que descarga el CSV de casos PNR.

En los permisos del usuario aparece 'pnr-feed-download-csv', asi que la
plataforma sabe generar ese archivo. Si existe, es mucho mejor que abrir
la ficha de cada caso: son 23 columnas ya armadas por Mercado Libre.
"""
import os, sys, json, time, re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

PROY = r"C:\ProyectosBDB\meliusuarios"
BASE_DIR = os.path.join(PROY, "2_preliminares")
PROFILE_DIR = os.path.join(PROY, "1_finales", "chrome_profile")
URL = "https://envios.adminml.com/logistics/case-center/cases"
DOM = "envios.adminml.com"

RUIDO = (".js", ".css", ".png", ".jpg", ".svg", ".woff", ".woff2", ".ico",
         ".gif", ".webp", ".map")
TELE = ("google-analytics", "googletagmanager", "newrelic", "datadog",
        "melidata", "/metrics", "kaspersky", "doubleclick", "hotjar")


def log(m):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), m), flush=True)


def dr():
    o = Options()
    o.add_argument("--user-data-dir=%s" % PROFILE_DIR)
    o.add_argument("--profile-directory=Default")
    o.add_argument("--start-maximized")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    o.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    return webdriver.Chrome(options=o)


def leer(d):
    pet = {}
    for e in d.get_log("performance"):
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        p = m.get("params", {}) or {}
        rid = p.get("requestId")
        if not rid:
            continue
        if m.get("method") == "Network.requestWillBeSent":
            rq = p.get("request", {}) or {}
            x = pet.setdefault(rid, {})
            x["url"] = rq.get("url", "")
            x["metodo"] = rq.get("method", "")
            x["postData"] = rq.get("postData")
        elif m.get("method") == "Network.responseReceived":
            rs = p.get("response", {}) or {}
            x = pet.setdefault(rid, {})
            x["status"] = rs.get("status")
            x["mime"] = rs.get("mimeType", "")
    return pet


def util(p):
    u = (p.get("url") or "").lower()
    if not u or DOM not in u:
        return False
    if any(u.split("?")[0].endswith(x) for x in RUIDO):
        return False
    return not any(x in u for x in TELE)


def recolectar(d, segundos):
    """El log se vacia en cada lectura: hay que leerlo varias veces."""
    todas = {}
    fin = time.time() + segundos
    while time.time() < fin:
        for rid, p in leer(d).items():
            if util(p):
                todas.setdefault(rid, p)
        time.sleep(1.0)
    return todas


def cuerpo(d, rid):
    try:
        return d.execute_cdp_cmd("Network.getResponseBody",
                                 {"requestId": rid}).get("body", "")
    except Exception as e:
        return "(no leido: %s)" % e


d = dr()
try:
    d.get(URL)
    log("Esperando la bandeja (entra si te lo pide)...")
    t0 = time.time()
    while time.time() - t0 < 3600:
        try:
            if "case-data" in d.page_source or "LOGISTICS_PNR" in d.page_source:
                break
        except Exception:
            pass
        time.sleep(2)
    time.sleep(3)
    try:
        tab = d.find_element(By.ID, "LOGISTICS_PNR")
        d.execute_script("arguments[0].scrollIntoView({block:'center'})", tab)
        tab.click()
        time.sleep(6)
        log("En la pestana PNR.")
    except Exception as e:
        log("no cambie a PNR: %s" % e)

    # 1) Que botones de descarga hay en la pantalla
    print("\n=== BOTONES QUE PARECEN DE DESCARGA ===")
    botones = d.execute_script("""
      const salida = [];
      document.querySelectorAll('button, a, [role=button]').forEach(b => {
        const t = (b.innerText || '').trim();
        const id = b.id || '';
        const test = b.getAttribute('data-testid') || '';
        if (/descarg|download|export|csv|excel/i.test(t + ' ' + id + ' ' + test)) {
          salida.push({texto: t.slice(0,50), id: id, testid: test,
                       tag: b.tagName});
        }
      });
      return salida;
    """)
    for b in botones:
        print("   %s" % json.dumps(b, ensure_ascii=False))
    if not botones:
        print("   (ninguno visible; puede estar en un menu)")

    # 2) Probar las rutas de descarga que encajan con el patron del panel
    print("\n=== PROBANDO RUTAS DE DESCARGA ===")
    per = "202608Q2"
    desde, hasta = "2026-08-16T00:00:00.000Z", "2026-08-31T23:59:59.999Z"
    busqueda = json.dumps({
        "date_from": desde, "date_to": hasta, "order": "desc",
        "sort": "priority_weight", "period": per, "billingPeriod": {},
        "size": 30, "page": 1, "searchFieldOption": "case_id"})
    cuerpo_post = json.dumps({"searchParams": busqueda, "userType": "3PL",
                              "application": "LOGISTICS_PNR"})

    RUTAS = [
        ("POST", "/logistics/case-center/api/feed/download-csv"),
        ("POST", "/logistics/case-center/api/feed/download"),
        ("POST", "/logistics/case-center/api/feed/export"),
        ("POST", "/logistics/case-center/api/feed/export-csv"),
        ("POST", "/logistics/case-center/api/feed/search-feed-cases-dec/csv"),
        ("GET",  "/logistics/case-center/api/feed/download-csv"),
        ("GET",  "/logistics/case-center/api/feed/export"),
        ("POST", "/logistics/case-center/api/cases/download"),
        ("POST", "/logistics/case-center/api/feed/csv"),
    ]
    SCRIPT = """
    const url = arguments[0], metodo = arguments[1], cuerpo = arguments[2];
    const done = arguments[arguments.length - 1];
    const opciones = {credentials: 'include', method: metodo,
                      headers: {'Accept': '*/*'}};
    if (metodo === 'POST') {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.body = cuerpo;
    }
    fetch(url, opciones)
      .then(r => r.text().then(t => done({status: r.status, largo: t.length,
              tipo: r.headers.get('content-type') || '',
              muestra: t.slice(0, 400)})))
      .catch(e => done({error: String(e)}));
    """
    d.set_script_timeout(120)
    for metodo, ruta in RUTAS:
        try:
            r = d.execute_async_script(SCRIPT, "https://" + DOM + ruta,
                                       metodo, cuerpo_post)
        except Exception as e:
            print("   %-4s %-52s EXCEPCION %s" % (metodo, ruta, str(e)[:60]))
            continue
        est = r.get("status")
        marca = ""
        if est == 200:
            m = (r.get("muestra") or "")
            if "ID DEL CASO" in m or "," in m[:200]:
                marca = "  <<<<< PARECE EL CSV"
            else:
                marca = "  <-- 200"
        print("   %-4s %-52s %s %s%s" % (
            metodo, ruta, est, (r.get("tipo") or "")[:26], marca))
        if est == 200:
            print("        %s" % (r.get("muestra") or "")[:300])

    # 3) Si hay boton, pulsarlo y espiar
    if botones:
        print("\n=== PULSANDO EL BOTON Y ESPIANDO ===")
        d.get_log("performance")
        pulsado = False
        for b in botones:
            try:
                if b.get("id"):
                    el = d.find_element(By.ID, b["id"])
                elif b.get("testid"):
                    el = d.find_element(
                        By.CSS_SELECTOR, "[data-testid='%s']" % b["testid"])
                else:
                    continue
                d.execute_script(
                    "arguments[0].scrollIntoView({block:'center'})", el)
                time.sleep(1)
                el.click()
                log("clic en %s" % (b.get("texto") or b.get("id")))
                pulsado = True
                break
            except Exception as e:
                log("no se pudo pulsar: %s" % str(e)[:90])
        if pulsado:
            todas = recolectar(d, 20)
            salida = []
            for rid, p in todas.items():
                print("\n   %s %s %s" % (p.get("metodo"), p.get("status"),
                                         (p.get("mime") or "")[:30]))
                print("     %s" % (p.get("url", "")[:230]))
                if p.get("postData"):
                    print("     BODY: %s" % str(p["postData"])[:400])
                b2 = cuerpo(d, rid)
                if b2 and len(b2) < 400000:
                    print("     RESP: %s" % b2[:600])
                salida.append({"url": p.get("url"), "metodo": p.get("metodo"),
                               "status": p.get("status"),
                               "postData": p.get("postData"),
                               "body": b2[:200000] if b2 else ""})
            with open(os.path.join(BASE_DIR, "red_csv_pnr.json"), "w",
                      encoding="utf-8") as f:
                json.dump(salida, f, ensure_ascii=False, indent=2)
            log("Guardado red_csv_pnr.json")
finally:
    try:
        d.quit()
    except Exception:
        pass

# -*- coding: utf-8 -*-
"""Igual que espiar_pnr.py pero sin ENTER: espera a la tabla y lee."""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espiar_pnr import (crear_driver, leer_red, interesante, puntuar,
                        cuerpo, log, URL, BASE_DIR)

ESPERA_LOGIN = 3600  # una hora: sin prisa para entrar

def main():
    driver = crear_driver()
    try:
        driver.get(URL)
        log("Si pide login, entra en la ventana de Chrome que se abrio.")
        log("Ve a la pestaña PNR. Detecto solo cuando cargue la tabla.")
        t0 = time.time()
        listo = False
        while time.time() - t0 < ESPERA_LOGIN:
            try:
                html = driver.page_source
                if "case-data" in html or "LOGISTICS_PNR" in html:
                    listo = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not listo:
            log("No aparecio la tabla en el tiempo de espera.")
            return
        log("Bandeja visible. Vaciando el log y provocando la carga PNR...")
        time.sleep(3)
        driver.get_log("performance")

        # Provocar: clic real en la pestaña PNR
        from selenium.webdriver.common.by import By
        try:
            tab = driver.find_element(By.ID, "LOGISTICS_PNR")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'})", tab)
            tab.click()
            log("Clic en la pestaña PNR.")
        except Exception as e:
            log(f"No se pudo hacer clic en PNR ({e}); recargando en su lugar.")
            driver.get(URL)
        time.sleep(6)

        peticiones = leer_red(driver)
        cands = sorted([(r, p) for r, p in peticiones.items() if interesante(p)],
                       key=lambda x: -puntuar(x[1]))
        log(f"{len(peticiones)} peticiones, {len(cands)} candidatas.")

        print("\n" + "=" * 70)
        for rid, p in cands[:15]:
            print(f"\n[{puntuar(p):>3}] {p.get('metodo','?')} "
                  f"{p.get('status','?')} {p.get('mime','')}")
            print(f"  {p.get('url','')[:240]}")
            if p.get("postData"):
                print(f"  BODY: {str(p['postData'])[:400]}")

        salida = []
        print("\n" + "=" * 70 + "\n  CUERPOS\n" + "=" * 70)
        for rid, p in cands[:6]:
            b = cuerpo(driver, rid)
            print(f"\n--- {p.get('url','')[:200]}")
            print(b[:2000])
            salida.append({"url": p.get("url"), "metodo": p.get("metodo"),
                           "status": p.get("status"),
                           "postData": p.get("postData"), "body": b})
        arch = os.path.join(BASE_DIR, "red_pnr.json")
        with open(arch, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2)
        log(f"Guardado en {arch}")
    finally:
        try: driver.quit()
        except Exception: pass

if __name__ == "__main__":
    main()

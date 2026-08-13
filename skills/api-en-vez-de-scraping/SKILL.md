---
name: api-en-vez-de-scraping
description: Reemplaza un scraper de Selenium por la API que ya usa el panel web, espiando el trafico del propio navegador con el performance log de Chrome. Sirve cuando el scraping es lento (paginacion por "Mostrar mas", abrir fichas una por una), fragil (se rompe al cambiar el CSS) o incompleto (la pantalla no muestra el id que hace falta). Cubre el descubrimiento del endpoint, la autenticacion sin tocar cookies, la paginacion por cursor, la descarga de binarios y el cruce entre dos fuentes por identificador numerico. Usar al escribir o arreglar cualquier extractor de un panel privado que requiera login.
---

# La API que ya esta ahi

Si una tabla web se llena **sin recargar la pagina**, el navegador le esta
pidiendo esos datos a algun lado. Ese "algun lado" casi siempre devuelve JSON
mas completo que lo que la pantalla muestra, y se puede pedir directo.

Un caso medido: un extractor de 2000 conductores pasó de **~30 minutos a 15
segundos** al cambiar de raspar HTML a llamar la API. Ademas empezo a traer el
`id` de cada persona, que la tabla no mostraba en ninguna parte.

Esta skill es el metodo completo, en el orden en que conviene aplicarlo.

---

## 1. Espiar el trafico (no adivinar URLs)

**Adivinar rutas no funciona.** En un caso real se probaron 30 combinaciones
(`/routes/{id}`, `/route/{id}`, `/routes/{id}/detail`…) y las 30 dieron 404.
El endpoint verdadero era `/logistics/monitoring-distribution/detail/{id}`,
que ninguna heuristica habria producido.

Lo que si funciona: pedirle a Chrome su propio registro de red.

```python
opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
opts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
```

Con eso, `driver.get_log("performance")` entrega los eventos crudos. Los dos
que importan:

| Evento | Aporta |
|---|---|
| `Network.requestWillBeSent` | URL, metodo, **postData** (el cuerpo del POST) |
| `Network.responseReceived` | status, MIME type, tipo de recurso |

Comparten `requestId`, asi que se emparejan para reconstruir cada peticion.

### El procedimiento

1. **Arrancar con el log activo** y esperar el login manual.
2. **Vaciar el log.** Una carga normal genera cientos de peticiones; solo
   interesan las que dispara la accion.
3. **Provocar la accion**: presionar "Mostrar mas", abrir una ficha, presionar
   "Descargar".
4. **Leer el log** y quedarse con lo posterior.
5. **Filtrar el ruido**: `.js`, `.css`, imagenes, fuentes, y telemetria
   (`google-analytics`, `newrelic`, `datadog`, `melidata`, `/metrics`,
   `kaspersky`).
6. **Puntuar las candidatas** en vez de elegir a ojo.
7. **Traer el cuerpo** de las mejores con `Network.getResponseBody`.

`scripts/espiar_red.py` implementa esto entero y sirve como punto de partida.

### Puntuar, no adivinar

```python
def puntuar(p):
    url = p["url"].lower()
    puntos = 0
    if "driver" in url:            puntos += 10   # el dominio del problema
    if any(k in url for k in ("offset","limit","page","cursor")): puntos += 8
    if "json" in (p.get("mime") or ""):  puntos += 4
    if "/api" in url or "/v1" in url:    puntos += 3
    return puntos
```

Sustituye `"driver"` por la palabra de tu dominio. La señal mas fuerte es la
de paginacion: una API de datos casi siempre la lleva.

### Cuidado con el falso positivo del menu

Un detector que acepte cualquier objeto con `{id, name}` reportara el **menu
de navegacion** del sitio como si fuera un hallazgo. Paso de verdad:

```
ENCONTRADO: id=15, name=Mercado Envios - Nueva arquitectura   <- es el menu
```

Exige que la clave mencione el concepto buscado (`driver`, `conductor`,
`carrier`), no solo que exista un `name`.

---

## 2. Autenticacion: no toques las cookies

El panel exige sesion. Hay tres caminos y solo uno es limpio:

| Enfoque | Problema |
|---|---|
| Copiar cookies a `requests` | Extrae y manipula credenciales; se rompe si rotan |
| Replicar el login | Fragil, y maneja credenciales que no hace falta manejar |
| **`fetch` dentro de la pagina** | El navegador adjunta todo solo ✅ |

```python
script = """
const url = arguments[0];
const done = arguments[arguments.length - 1];
fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}})
  .then(r => r.text().then(t => done({ok: r.ok, status: r.status, body: t})))
  .catch(e => done({ok: false, status: 0, body: String(e)}));
"""
resp = driver.execute_async_script(script, url)
```

`credentials: 'include'` hace que Chrome adjunte cookies, cabeceras y tokens
igual que en una peticion normal. **El script nunca lee ni almacena
credenciales.** `execute_async_script` con el callback `done` espera a que la
promesa se resuelva.

### El error que vas a ver: `TypeError: Failed to fetch` con status 0

Significa que el `fetch` corrio desde una pagina de **otro dominio**. La
politica de origen lo bloquea antes de salir a la red. Casi siempre es que
tras el login el navegador quedo en otra URL, o el panel esta en otra pestaña.

Antes de la primera llamada, asegura la ubicacion:

```python
# 1) Si hay varias pestañas, pasar a la del panel
for p in driver.window_handles:
    driver.switch_to.window(p)
    if DOMINIO in (driver.current_url or ""):
        break
# 2) Si no estamos en el dominio, navegar
if DOMINIO not in (driver.current_url or ""):
    driver.get(URL_PANEL)
# 3) Esperar a que cargue de verdad, no un sleep fijo
WebDriverWait(driver, 30).until(
    EC.presence_of_element_located((By.CSS_SELECTOR, SELECTOR_DE_LA_TABLA)))
```

Y traduce ese error para el usuario: "El navegador bloqueo la consulta.
Chrome debe estar en la pagina X" dice mucho mas que `TypeError`.

---

## 3. Paginacion por cursor

Muchas APIs modernas no usan `offset`/`limit` sino un cursor opaco:

```python
while pagina < MAX_PAGINAS:
    datos = llamar_api(driver, cursor)
    # ... procesar datos["result"] ...
    pag = datos.get("pagination") or {}
    if not pag.get("has_next"):
        break
    siguiente = pag.get("cursor")
    if not siguiente or siguiente == cursor:
        break                      # el cursor dejo de avanzar: cortar
    cursor = siguiente
    time.sleep(PAUSA)
```

Cuatro defensas, cada una contra un fallo concreto:

- **`quote(cursor, safe="")`** — un cursor base64 termina en `==`. Sin escapar
  a `%3D%3D` la URL se corrompe. Este bug es silencioso y dificil de ver.
- **Cortar si el cursor no cambia** — evita el bucle infinito si la API repite
  pagina.
- **Tope de paginas** — red de seguridad final.
- **Deduplicar por `id`** — si dos paginas se traslapan, no contar doble.

---

## 4. Cuando el listado no trae todo

Es comun que el listado sea un resumen y el detalle viva en otra llamada
(telefono, correo, motivo de bloqueo). Dos reglas:

**Guarda el listado ANTES de pedir los detalles.** Si el segundo paso falla o
lo interrumpen, no se pierde lo que ya costo traer.

**Pide los detalles en paralelo.** El tiempo lo domina la latencia, no el
computo. Medido con 120 fichas:

| Lote | Ritmo | Proyeccion a 2000 |
|---:|---:|---:|
| 1 (en serie) | 6/s | 5.4 min |
| 6 | 11/s | 3.2 min |
| **12** | **24/s** | **1.4 min** |
| 20 | 36/s | 0.9 min |

```javascript
Promise.all(ids.map(id =>
  fetch(base + id, {credentials:'include'})
    .then(r => r.ok ? r.json() : null)
    .then(j => ({id: id, ok: !!j, data: j}))
    .catch(() => ({id: id, ok: false, data: null}))
)).then(done);
```

Elige un lote intermedio, no el maximo: la mejora de 12 a 20 no compensa el
riesgo de que el servidor empiece a limitar peticiones.

Añade **reintentos** para las que fallen por intermitencia, en lotes mas
chicos y con pausas mayores.

---

## 5. Descargar binarios (XLSX, PDF)

Si el endpoint devuelve un archivo, **no lo pases como texto**: se corrompe.
Hay que traerlo en base64.

```javascript
fetch(url, {credentials:'include'}).then(r => r.blob().then(b => {
  const lector = new FileReader();
  lector.onloadend = () => done({status: r.status,
                                 b64: lector.result.split(',')[1] || ''});
  lector.readAsDataURL(b);
}));
```

```python
datos = base64.b64decode(resp["b64"])
```

Señal de que te paso: el contenido empieza con `PK` (firma de ZIP, y un XLSX
es un ZIP) o se ve como `����` en el reporte.

Para leer el XLSX sin añadir `openpyxl` al ejecutable, ver
`scripts/leer_xlsx.py`: descomprime el ZIP y parsea el XML. Verificado contra
openpyxl con archivos reales.

---

## 6. Cruzar dos fuentes: por numero, nunca por nombre

Caso tipico: la factura trae el **nombre** del trabajador pero no su id, y hay
homonimos. En un padron real habia **25 nombres repetidos** — dos personas
distintas llamadas igual. Cruzar por texto no distingue a cual pagarle.

La solucion es buscar un identificador comun, aunque haya que pasar por una
tercera fuente:

```
factura (id de ruta)
   ↓ el reporte de operacion dice quien hizo esa ruta
id de usuario
   ↓ el padron sabe quien es
nombre, documento, telefono
```

Antes de construirlo, **mide si el puente existe**:

```python
comunes = set(fuente_a) & set(fuente_b)
print(f"claves en ambos: {len(comunes)} de {len(fuente_a)}")
```

Si da cero, revisa la escala de los identificadores antes de concluir que no
sirven. Un caso real: `origin_resource_id` rondaba los 17 millones y el id de
ruta los 147 millones — parecian relacionados y no lo eran.

Otro caso: dos archivos con 0 rutas en comun porque uno era de **un dia** y el
otro de **una quincena distinta**. El periodo importa.

---

## 7. Ergonomia del extractor

Cosas que se aprendieron a golpes:

**No dependas de `input()` en consola.** Cuando el foco esta en Chrome, la
consola de Windows se traga las primeras pulsaciones de ENTER y el usuario
cree que se colgo. Una GUI con botones lo elimina; ver
`scripts/plantilla_gui.py`.

**El trabajo va en otro hilo.** Si corre en el de la interfaz, la ventana se
congela durante los minutos que tarda. En Qt, ademas, hay que invocarlo **por
señal**, no llamando al metodo: una llamada normal corre en el hilo de la
ventana.

**Cierra los Chrome huerfanos al arrancar.** Si el programa muere a la fuerza,
sus procesos siguen vivos agarrados al perfil, y la siguiente vez Chrome abre
**en blanco** sin explicar nada. Borrar el `lockfile` no basta: hay que cerrar
los procesos primero, o lo vuelven a crear. Ver `scripts/perfil_chrome.py`.

**Traduce los errores.** `SessionNotCreatedException: DevToolsActivePort file
doesn't exist` no le dice nada a nadie. "Chrome no pudo arrancar; cierra las
ventanas del programa y reintenta" si.

**Guarda en UTF-8 con BOM** (`utf-8-sig`) si el destino es Excel, o los
acentos salen rotos.

---

## 8. Verificar con datos reales

Todo lo de arriba se puede escribir mal en silencio. Antes de dar algo por
bueno:

- **Reproduce el bug** antes de arreglarlo. Un JSON recortado a 4000
  caracteres falla con `Unterminated string starting at char 3994`; escribir
  el caso lo confirma en segundos.
- **Compara contra una referencia.** El lector de XLSX propio se valido contra
  openpyxl: mismas 168 filas, mismas claves.
- **Prueba los casos raros**: `id=0` (que en Python es falso y rompe un
  `if not id`), registros vacios en el origen, nombres duplicados, respuestas
  404 en medio de un lote.
- **Cuenta lo que falta y explica por que.** Un `1648/2025` sin contexto se
  lee como perdida de datos. Separa "no tiene telefono cargado" de "la ficha
  no respondio": son cosas distintas y solo una es un error.

---

## 9. Aviso sobre datos personales

Los extractores de paneles privados suelen sacar nombres, documentos de
identidad, telefonos y correos. Tres reglas minimas:

1. **Excluye los resultados del repositorio** (`.gitignore`), junto con el
   perfil del navegador, que guarda la sesion.
2. **Enmascara los valores en los reportes de diagnostico**: muestra
   `driverName = Vic*********` pero deja los ids completos, que son los que
   interesan para depurar.
3. **Nunca guardes cookies ni tokens** en un archivo, ni siquiera temporal.

Y no automatices mas alla de lo que la persona ya puede ver con su propia
cuenta. Pausas entre llamadas (0.2-0.4 s) para no golpear el servidor mas
rapido de lo que lo haria un humano usando el panel.

---

## Archivos de apoyo

| Archivo | Para que |
|---|---|
| `scripts/espiar_red.py` | Descubridor generico: espia, filtra, puntua y reporta |
| `scripts/llamar_api.py` | `fetch` desde la pagina: JSON, binario y lotes en paralelo |
| `scripts/perfil_chrome.py` | Perfil persistente, cierre de huerfanos, limpieza de locks |
| `scripts/leer_xlsx.py` | XLSX sin openpyxl, descomprimiendo el ZIP |
| `scripts/plantilla_gui.py` | Ventana PySide6 con hilo de trabajo y registro |
| `references/errores.md` | Los fallos concretos que costaron tiempo, con su causa |

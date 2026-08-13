# Extractor de Drivers — Mercado Libre Envíos

Extrae la lista completa de transportistas de
`envios.adminml.com/logistics/provider-management/drivers`
y la guarda en un archivo listo para Excel.

Captura **ID, nombre, CURP, estatus, tipo y fecha de creación** — tanto de los
drivers **activos** como de los **bloqueados**. Opcionalmente también
**teléfono y e-mail**.

---

## Cuál usar

| Ejecutable | Qué hace | Tiempo |
|---|---|---|
| **`ExtraerDriversAPI.exe`** ⭐ | Consulta directo la API de la tabla. Trae ID, nombre, CURP y estatus. **Empieza por este.** | segundos |
| `ExtraerDriversMeli.exe` | Lee el HTML presionando "Mostrar más". Respaldo si la API cambia. | minutos |
| `DescubrirAPI.exe` | Diagnóstico: encuentra el endpoint si MELI lo mueve. | ~1 min |
| `ProbarPerfilAPI.exe` | Diagnóstico: busca una API de perfil que traiga teléfono/e-mail. | ~1 min |

### Rendimiento medido

Corrida real del 12/ago/2026:

```
2,025 drivers en 15 segundos
  Activo              1425
  Bloqueado            543
  Inactivo              56
  Registro pendiente     1

  ID     2025/2025 (100%)      Teléfono   0/2025  (no viene en el listado)
  CURP   2005/2025  (99%)      Fecha   2025/2025 (100%)
```

La versión HTML tardaba del orden de media hora para lo mismo — y de los 543
bloqueados solo rescataba el estatus.

---

## Uso rápido (versión API)

1. Ejecuta **`ExtraerDriversAPI.exe`** (doble clic).
2. Inicia sesión en la ventana de Chrome.
3. Cuando veas la lista, presiona **ENTER** en la ventana negra.
4. Listo — pagina la API completa en segundos y guarda los archivos.

La API es
`/logistics/provider-management/api/drivers/drivers-and-invites`,
con `status=active,inactive,blocked` y paginación por cursor. El `id` viene
en cada registro, así que **no hace falta abrir ningún perfil**.

Las llamadas salen del propio navegador (`fetch` con `credentials: 'include'`),
así que se reusa tu sesión sin extraer ni manipular tokens.

---

## Uso de la versión HTML (respaldo)

1. Ejecuta **`ExtraerDriversMeli.exe`** (doble clic).
2. Se abre Chrome en la página de drivers → **inicia sesión tú mismo**.
3. Cuando ya veas la lista en pantalla, regresa a la ventana negra y presiona **ENTER**.
4. El script presiona "Mostrar más" hasta agotar la lista, **guarda un primer archivo**
   y luego pregunta si quieres abrir los perfiles para obtener teléfono y e-mail.
   Puedes responder **n** y quedarte con lo del listado.

No necesitas Python instalado para usar el `.exe`.

---

## Qué hace

- **Espera tu login.** No automatiza credenciales; tú entras a mano y le dices cuándo empezar.
- **Paginación persistente.** Presiona "Mostrar más" una y otra vez, esperando hasta 25 s
  por cada carga. Solo se detiene tras 4 intentos seguidos sin filas nuevas.
- **Lee filas activas y bloqueadas.** Las bloqueadas usan clases CSS distintas
  (`description--name-disabled`, `description--disabled`); el extractor reconoce ambas
  variantes y, como red de seguridad, clasifica los textos por contenido
  (la CURP se valida con expresión regular).
- **Sesión recordada.** Guarda el perfil de Chrome en `chrome_profile/`, así la próxima
  vez normalmente ya no pide login.
- **ID sin costo cuando se puede.** El ID del driver es el número de la URL de su perfil
  (`/drivers/edit/5196349`). Si el listado trae ese enlace, el ID se obtiene al instante,
  sin abrir nada.
- **Guardado por etapas.** Los datos del listado se escriben a disco *antes* de empezar
  con los perfiles; si ese paso se interrumpe, no se pierde lo ya cargado.

---

## Salida

Se generan dos archivos junto al ejecutable, con fecha y hora en el nombre:

| Archivo | Formato | Cómo abrirlo |
|---|---|---|
| `drivers_meli_AAAAMMDD_HHMMSS.txt` | Separado por TABS | Ábrelo y pega en Excel, o arrástralo — cae en columnas solo |
| `drivers_meli_AAAAMMDD_HHMMSS.csv` | Separado por `;` | Doble clic (Excel en español) |

Ambos en **UTF-8 con BOM** (`utf-8-sig`) para que Excel muestre acentos y eñes
correctamente, sin signos raros.

### Columnas

```
# | ID | Nombre | CURP | Estatus | Observación | Teléfono | E-mail | Tipo | Fecha creación
```

`Estatus` trae el estado principal (`Activo`, `Bloqueado`, …) y `Observación`
la nota que a veces lo acompaña (`Falta leve`, `Rehacer capacitación`).

`Teléfono` y `E-mail` solo se llenan si aceptas el paso de abrir perfiles.

Al terminar, la consola imprime un resumen: conteo por estatus y cuántos
registros quedaron con ID, teléfono y e-mail.

---

## Sobre el ID, teléfono y e-mail

En la interfaz, estos campos viven en la ficha individual del driver
(*3 puntos → Ver Perfil*), no en el listado. Cómo los obtiene cada versión:

**Versión API** — el `id` **viene incluido** en cada registro del JSON, así que se
obtiene sin abrir nada: 100% de cobertura.

**El teléfono y el e-mail NO vienen en el listado.** Confirmado en una corrida de
2,025 registros: 0 con teléfono, 1 con e-mail. El JSON *sí incluye* una clave
`email` en su esquema, pero llega en `null` para los drivers reales; el único que
la trae es una invitación pendiente, y **enmascarada por el propio MELI**
(`ant****@gmail***`). No hay un campo `phone` en la respuesta.

Lo mismo pasa con `blockingReason`: llega vacío incluso en los 543 bloqueados —
el motivo solo aparece en la ficha individual.

### La ficha individual sí los trae

`ProbarPerfilAPI.exe` localizó la API del perfil:

```
GET /logistics/provider-management/api/drivers/<id>
→ 200  { id, firstName, lastName, email, phone, blockingReason,
         identificationValue, status, carrierId, siteId, ... }
```

Así que `ExtraerDriversAPI.exe` **pregunta al terminar** si quieres traerlos.
Si aceptas, consulta las fichas y llena Teléfono, E-mail y Observación.

**Cómo se hace rápido.** Una llamada por driver en serie tardaría demasiado; el
tiempo lo domina la latencia, no el cómputo. Se piden **12 fichas en paralelo**
por lote, con `Promise.all` dentro de la página. Medición con 120 fichas de
prueba:

| Lote | Ritmo | Proyección a 2,024 fichas |
|---:|---:|---:|
| 1 (en serie) | 6/s | 5.4 min |
| 6 | 11/s | 3.2 min |
| **12** | **24/s** | **1.4 min** |
| 20 | 36/s | 0.9 min |

Se eligió 12 y no el máximo: la mejora de 12 a 20 no compensa el riesgo de que
el servidor empiece a limitar peticiones.

El listado se guarda a disco **antes** de este paso, así que una interrupción no
cuesta lo ya obtenido.

**Versión HTML** — intenta sacar el ID del enlace de cada fila; si el listado no
los expone (que es el caso hoy), recurre al menú de 3 puntos, abriendo perfil por
perfil. Ese modo es lento y **solo alcanza las filas visibles tras volver a la
lista**, porque al navegar hacia atrás se pierde la paginación. La consola avisa
cuando ocurre. Es la razón principal por la que existe la versión API.

---

## Cómo se encontró la API

Esta sección documenta el método, porque sirve para cualquier tabla web que
cargue por partes — no solo para esta.

### El problema

La primera versión leía el HTML: presionaba "Mostrar más" y raspaba las filas.
Funcionaba, pero tenía tres costos:

1. **Lento.** Una espera de hasta 25 s por cada clic, decenas de veces.
2. **Frágil.** Cualquier cambio de clases CSS lo rompía — y pasó: las filas
   bloqueadas usaban `description--name-disabled` en lugar de `description--name`,
   así que de esos drivers solo se rescataba el estatus.
3. **Incompleto.** El ID no aparecía en el listado. Había que abrir el perfil de
   cada driver, uno por uno.

La observación clave: si la tabla se llena **sin recargar la página**, entonces
el navegador está pidiendo esos datos a algún lado. Ese "algún lado" es la API.

### La técnica: espiar el tráfico del propio navegador

Chrome expone su actividad de red mediante el **DevTools Protocol**. Selenium
puede pedir ese registro si se activa el log de rendimiento al arrancar:

```python
opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
opts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
```

Con eso, `driver.get_log("performance")` devuelve los eventos crudos. Los dos
que importan:

| Evento | Aporta |
|---|---|
| `Network.requestWillBeSent` | URL, método, cuerpo del POST |
| `Network.responseReceived`  | status, MIME type, tipo de recurso |

Ambos comparten un `requestId`, así que se emparejan para reconstruir cada
petición completa.

### El procedimiento

1. **Arrancar con el log activo** y esperar el login manual del usuario.
2. **Vaciar el log.** Una carga de página genera cientos de peticiones; solo
   interesan las que dispara el clic.
3. **Presionar "Mostrar más" una vez.**
4. **Leer el log** y quedarse con lo que apareció después del clic.
5. **Filtrar el ruido:** fuera `.js`, `.css`, imágenes, fuentes, y la telemetría
   (`google-analytics`, `newrelic`, `melidata`, `/metrics`, `/beacon`…).
6. **Puntuar las candidatas** en vez de adivinar. La heurística premia lo que
   caracteriza a una API de datos paginada:

   ```
   +10  la URL contiene "driver"
    +8  trae offset / limit / page / cursor   ← señal de paginación
    +5  contiene "provider-management"
    +4  responde application/json
    +3  la ruta incluye /api o /v1
   ```

7. **Traer el cuerpo de la respuesta** de las mejores, vía
   `Network.getResponseBody`, para confirmar que son los datos buscados.

### El resultado

Una sola candidata destacó, con **31 puntos**:

```
GET https://envios.adminml.com/logistics/provider-management/api/drivers/
    drivers-and-invites
    ?status=active,inactive,blocked
    &paginated=true
    &cursor=NDgwMzI5Mw%3D%3D
→ 200  application/json
```

Y su respuesta contenía justo lo que hacía falta:

```json
{
  "pagination": {"cursor": "NDQxNjE2OA==", "has_next": true},
  "result": [
    {"id": 4801590,
     "identificationType": "CURP",
     "identificationValue": "CULJ841021HGTRCN06",
     "firstName": "Juan Manuel", "lastName": "Cruz",
     "status": "active", "disabled": false,
     "creationDate": 1781640642,
     "blockingReason": {}, "isOnlyHelper": false}
  ]
}
```

Tres hallazgos que cambiaron el diseño:

- **El `id` viene en cada registro.** Desaparece la necesidad de abrir perfiles.
- **`status=active,inactive,blocked`** trae los bloqueados en la misma llamada,
  sin el problema de las clases CSS.
- **Campos que el HTML no mostraba:** `blockingReason` (el motivo del bloqueo) e
  `isOnlyHelper` (distingue Ayudante de Transportista).

---

## Cómo se construyó el extractor por API

### Autenticación: no tocar los tokens

El panel exige sesión iniciada. Había tres caminos:

| Enfoque | Problema |
|---|---|
| Copiar cookies a `requests` | Hay que extraer y manipular credenciales; se rompe si rotan |
| Replicar el login | Frágil, y trata credenciales que no hacen falta tratar |
| **Llamar desde la propia página** | El navegador adjunta todo solo ✅ |

Se eligió el tercero: ejecutar `fetch` **dentro** de la página ya autenticada.

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

`credentials: 'include'` hace que Chrome adjunte cookies, cabeceras y cualquier
token igual que en una petición normal de la página. **El script nunca lee, guarda
ni transmite credenciales** — solo recibe el JSON. `execute_async_script` con el
callback `done` espera a que la promesa se resuelva.

### Paginación por cursor

Esta API no usa `offset`/`limit`, sino un cursor opaco en base64. Se pide una
página, se lee el cursor que devuelve y se pasa a la siguiente:

```python
while pagina < MAX_PAGINAS:
    datos = llamar_api(driver, cursor)
    # ... procesar datos["result"] ...
    paginacion = datos.get("pagination") or {}
    if not paginacion.get("has_next"):
        break
    siguiente = paginacion.get("cursor")
    if not siguiente or siguiente == cursor:
        break          # el cursor dejó de avanzar: cortar
    cursor = siguiente
    time.sleep(PAUSA)
```

Cuatro decisiones defensivas, cada una contra un modo de falla concreto:

- **`quote(cursor, safe="")`** — el cursor termina en `==` (relleno base64). Sin
  escapar a `%3D%3D` la URL se corrompe.
- **Cortar si el cursor no cambia** — evita el bucle infinito si la API repite
  la misma página.
- **`MAX_PAGINAS = 500`** — tope duro, red de seguridad final.
- **Deduplicar por `id`** — si dos páginas se traslapan, no se cuentan dos veces.

Entre llamadas hay una pausa de 0.4 s. No es necesaria técnicamente; es para no
golpear el servidor más rápido de lo que lo haría una persona usando el panel.

### Normalizar la respuesta

El JSON no viene listo para Excel. `normalizar()` traduce:

| Campo API | Columna | Tratamiento |
|---|---|---|
| `firstName` + `lastName` | Nombre | Se concatenan; si vienen vacíos (invitación pendiente) se usa el e-mail |
| `identificationValue` | CURP | A mayúsculas |
| `status` | Estatus | `active`→Activo, `blocked`→Bloqueado, … |
| `disabled` | Estatus | Si es `true` con status `active` → "Activo (deshabilitado)" |
| `creationDate` | Fecha | Epoch en segundos → `dd/mm/aaaa` |
| `blockingReason` | Observación | Se extrae el motivo del objeto anidado |
| `isOnlyHelper` | Tipo | `true`→Ayudante, `false`→Transportista |

### Verificación

La lógica se probó contra el **JSON real capturado en el reporte**, más casos
límite construidos a mano (bloqueado con motivo, invitación sin nombre, ayudante):

```
4801590   Juan Manuel Cruz   CULJ841021HGTRCN06   Activo      16/06/2026
4700001   Jorge Isai Gil     GIFJ000910HTCLLRA1   Bloqueado   Documentacion vencida
4700003   pruebas@gmail.com                       Pendiente
4700004   Angel Piedra       PIEA730423HMCDSN02   Activo      Ayudante
```

También se verificó el escapado del cursor (`==` → `%3D%3D`), la conversión de
fechas epoch y la presencia del BOM que Excel necesita.

### Por qué se conservó la versión HTML

`ExtraerDriversMeli.exe` sigue en el repo a propósito. Una API interna no
documentada puede cambiar sin aviso; si eso pasa, el raspado de HTML sirve de
respaldo mientras `DescubrirAPI.exe` localiza el endpoint nuevo.

---

## `DescubrirAPI.exe` — volver a encontrar el endpoint

Herramienta de diagnóstico. **No extrae datos**: aplica el método descrito arriba
y reporta las URLs candidatas.

Úsala si `ExtraerDriversAPI.exe` empieza a fallar — probablemente MELI movió o
renombró el endpoint.

**Uso:** ejecútalo, inicia sesión, presiona ENTER. Genera un
`api_encontrada_AAAAMMDD_HHMMSS.txt` con las candidatas ordenadas por puntaje y
una muestra de cada respuesta.

El reporte **omite cookies y tokens** — solo URLs, método, tipo de contenido y un
fragmento del cuerpo. Aun así, revísalo antes de compartirlo: la muestra de la
respuesta **sí puede contener datos de drivers reales**. Por eso el `.gitignore`
excluye `api_encontrada_*.txt`.

---

## Correr desde el código fuente

```bash
pip install selenium
python extraer_api.py        # versión rápida (API)
python extraer_drivers.py    # versión HTML (respaldo)
python descubrir_api.py      # diagnóstico
```

O doble clic en `EXTRAER_DRIVERS.bat`.

Requiere Python 3.8+ y Google Chrome. Selenium 4.6+ descarga el chromedriver
automáticamente (Selenium Manager), no hay que instalarlo aparte.

### Recompilar los .exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --console --name ExtraerDriversAPI ^
  --collect-all selenium --distpath . --workpath build --specpath build ^
  --noconfirm extraer_api.py
```

Igual para `extraer_drivers.py` (→ `ExtraerDriversMeli`) y `descubrir_api.py`
(→ `DescubrirAPI`).

Si PyInstaller falla con `PermissionError: Acceso denegado`, es que el `.exe`
está abierto: ciérralo antes de recompilar.

### Archivos

| Archivo | Qué es |
|---|---|
| `extraer_api.py` | Extractor por API — el principal |
| `extraer_drivers.py` | Extractor por HTML — respaldo |
| `descubrir_api.py` | Detector del endpoint |
| `EXTRAER_DRIVERS.bat` | Lanzador de la versión HTML |

---

## Aviso sobre datos personales

Los archivos generados contienen **CURP, nombres completos y — si usas el paso de
perfiles — teléfono y correo electrónico**. Todo eso son datos personales bajo la
LFPDPPP, y los datos de contacto elevan bastante la sensibilidad del archivo. El `.gitignore` los excluye del repositorio a propósito, junto con
`chrome_profile/` (que guarda tu sesión). Trátalos con el cuidado que corresponde
y no los subas a ningún lado.

---

## Si algo falla

**Chrome abre en blanco.** El perfil quedó bloqueado por un cierre a la fuerza.
Los programas ya borran el `lockfile` solos al arrancar; si persiste, cierra las
ventanas de Chrome que abrió el programa, o borra la carpeta `chrome_profile/`
(solo pierdes la sesión guardada).

**La API responde 401 / 403, o no devuelve JSON.** La sesión caducó: inicia
sesión de nuevo. Si sigue, MELI cambió el endpoint → corre `DescubrirAPI.exe`
y compara la URL nueva con la de `extraer_api.py`.

**La API devuelve 0 registros.** Puede que cambiaran los nombres de campo del
JSON. Revisa la muestra en el reporte de `DescubrirAPI.exe` y ajusta
`normalizar()` en `extraer_api.py`.

**La versión HTML deja campos vacíos.** Cambiaron las clases CSS. La consola
lo avisa:

```
ADVERTENCIA: 3 sin nombre, 1 sin CURP.
```

Toca revisar los selectores en `extraer_datos()` de `extraer_drivers.py`.

**Windows bloquea el .exe.** No está firmado digitalmente: SmartScreen mostrará
"Windows protegió tu PC" → *Más información* → *Ejecutar de todas formas*. Algunos
antivirus marcan falsos positivos en ejecutables de PyInstaller. Gmail y varios
servicios rechazan adjuntos `.exe`; comparte el enlace del repo o un `.zip`.

### Requisitos para quien lo reciba

No necesita Python. Sí necesita **Windows 10/11 de 64 bits**, **Google Chrome**,
**internet** (la primera vez, para que Selenium Manager baje el chromedriver) y
**una cuenta de MELI con acceso al panel**.

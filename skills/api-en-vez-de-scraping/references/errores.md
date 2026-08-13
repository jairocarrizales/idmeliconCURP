# Los errores que costaron tiempo

Cada uno paso de verdad al construir un extractor real. Estan aqui para que
la proxima vez se reconozcan en segundos y no en media hora.

---

## `TypeError: Failed to fetch` con status 0

**Sintoma:** la API responde 0 y el cuerpo dice `Failed to fetch`.

**Causa:** el `fetch` se ejecuto desde una pagina de otro dominio. La politica
de origen del navegador lo bloquea antes de que salga a la red. Casi siempre
es que tras el login el navegador quedo en otra URL, o el panel esta abierto
en otra pestaña.

**Arreglo:** antes de la primera llamada, busca la pestaña correcta, navega al
panel si hace falta, y espera a que la tabla cargue de verdad. Ver
`preparar_pagina()` en `scripts/perfil_chrome.py`.

**Como se ve para el usuario:** traducelo. "El navegador bloqueo la consulta;
Chrome debe estar en la pagina X" en vez del `TypeError`.

---

## `Unterminated string starting at char 3994`

**Sintoma:** `json.loads` falla en un punto arbitrario del texto.

**Causa:** se recorto la respuesta antes de parsearla. Tipico:

```javascript
done({status: r.status, body: t.slice(0, 4000)})   // MAL
```

El recorte parte el JSON a la mitad.

**Arreglo:** devuelve el cuerpo completo y recorta **al imprimir**, nunca
antes de parsear.

**Como confirmarlo en 10 segundos:** toma un JSON largo, cortalo a 4000 y
parsealo. Reproduce el error exacto.

---

## La ventana de Chrome abre en blanco

**Sintoma:** Chrome arranca pero no muestra nada, sin mensaje de error.

**Causa:** quedaron procesos de Chrome vivos usando el perfil (de una corrida
que murio a la fuerza) mas un `lockfile`. Chrome no puede abrir un perfil que
cree en uso.

**Arreglo en dos partes, y la primera es la que suele faltar:**

1. **Cerrar los procesos huerfanos.** Borrar el lockfile no basta: con
   procesos vivos lo vuelven a crear.
2. Borrar los archivos de bloqueo, incluido **`Default/LOCK`** — el que
   provoca `DevToolsActivePort file doesn't exist` y suele olvidarse.

**Sub-error que lo hizo peor:** el filtro de PowerShell usaba la ruta completa
del perfil. Sus backslashes rompen el patron de `-like`, asi que contaba
**0 procesos cuando habia 8**, y la limpieza "funcionaba" contra una lista
vacia. Compara nombre de proyecto y de carpeta por separado.

---

## `PermissionError: Acceso denegado` al compilar

**Sintoma:** PyInstaller falla al escribir el `.exe`.

**Causa:** el ejecutable esta abierto. Cierra el proceso antes de recompilar.

---

## El detector reporta el menu del sitio como un hallazgo

**Sintoma:** "ENCONTRADO: `id=15, name=Mercado Envios`" cuando se buscaban
conductores.

**Causa:** el detector aceptaba cualquier objeto con `{id, name}`, y el menu
de navegacion cumple.

**Arreglo:** exige que la clave mencione el concepto buscado (`driver`,
`conductor`, `carrier`), no solo que exista un `name`.

---

## Un `id` valido que el codigo trata como ausente

**Sintoma:** "El primer registro no trae id", pero `id` si esta en las claves.

**Causa:** el id era **0** (un registro especial, como una invitacion
pendiente). En Python `if not id` es verdadero para 0.

**Arreglo:** recorre hasta encontrar un id utilizable en vez de rendirte con
el primero. Y en general, cuidado con `if not x` sobre numeros.

---

## El XLSX llega corrupto

**Sintoma:** el contenido empieza con `PK����` o se ve como caracteres raros.

**Causa:** se pidio como texto. Un binario no sobrevive el viaje.

**Arreglo:** traelo en base64 con `FileReader.readAsDataURL`. Ver
`llamar_binario()` en `scripts/llamar_api.py`.

(`PK` es la firma de un ZIP, y un XLSX es un ZIP.)

---

## Cero coincidencias al cruzar dos fuentes

**Sintoma:** dos archivos que deberian compartir claves no comparten ninguna.

**Dos causas vistas:**

1. **Periodos distintos.** Un reporte de un dia contra una factura de una
   quincena. Verifica el rango de fechas antes de concluir nada.
2. **Identificadores de escalas distintas.** `origin_resource_id` rondaba los
   17 millones y el id de ruta los 147 millones. Parecian relacionados y no
   lo eran.

**Como diagnosticarlo rapido:**

```python
print(f"rango A: {min(a)} .. {max(a)}")
print(f"rango B: {min(b)} .. {max(b)}")
```

---

## El usuario tiene que presionar ENTER varias veces

**Sintoma:** en la version de consola, el ENTER no responde a la primera.

**Causa:** cuando el foco esta en Chrome, la consola de Windows se traga las
primeras pulsaciones.

**Arreglo:** una GUI con botones. Ver `scripts/plantilla_gui.py`.

---

## La ventana de la GUI se congela

**Causa:** el trabajo corre en el hilo de la interfaz.

**Arreglo:** un `QThread` — pero ademas hay que invocarlo **por señal**:

```python
self.ordenes.trabajar.emit()          # bien
self.trabajador.trabajar()            # mal: corre en el hilo de la ventana
```

---

## Acentos rotos tras editar con PowerShell

**Sintoma:** `señales` queda como `seÃ±ales` despues de un reemplazo de texto.

**Causa:** PowerShell reescribio el archivo con otra codificacion.

**Arreglo:** haz los reemplazos con Python (`io.open(..., encoding="utf-8")`),
no con `Set-Content`. Y si ya paso, restaura desde git y rehaz el cambio.

---

## Un conteo bajo que parece perdida de datos

**Sintoma:** "1648 de 2025 con telefono" se lee como si faltaran 377.

**Causa real:** eran tres cosas distintas mezcladas — 357 personas sin
telefono cargado en el origen, 19 registros vacios en el sistema, y 1
invitacion pendiente. Solo un puñado eran fallos reales.

**Arreglo:** separa las categorias en el resumen. "357 no tienen telefono
cargado" y "20 fichas no respondieron" son cosas distintas, y solo la segunda
es un error que se puede reintentar.

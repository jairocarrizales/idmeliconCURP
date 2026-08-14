# Versiones anteriores

La primera generación del extractor de conductores, cuando todavía no
sabíamos que había una API detrás del panel.

**No los uses a diario** — `1_finales/DriversMeli.exe` hace lo mismo en 15
segundos en vez de 30 minutos, y trae el ID que estos no podían obtener.

## Qué hay aquí

| Archivo | Qué era |
|---|---|
| `ExtraerDriversMeli.exe` | Scraping del HTML: presionaba "Mostrar más" hasta agotar la lista |
| `ExtraerDriversAPI.exe` | Primera versión por API, en consola |
| `EXTRAER_DRIVERS.bat` | Lanzador del script de Python |

## Por qué se conservan

**Como respaldo.** Si MELI cambiara o cerrara la API, el raspado de HTML
seguiría funcionando mientras se busca el endpoint nuevo. Es lento y
frágil, pero no depende de que ningún JSON exista.

**Como documentación del problema.** El scraping tenía tres límites que
justificaron el cambio:

1. **Lento.** Hasta 25 s de espera por cada clic en "Mostrar más", decenas
   de veces.
2. **Frágil.** Se rompía al cambiar las clases CSS — y pasó: las filas
   bloqueadas usaban `description--name-disabled` en vez de
   `description--name`, así que de esos 543 conductores solo se rescataba
   el estatus.
3. **Incompleto.** El ID no aparecía en el listado. Había que abrir la
   ficha de cada persona, y al volver atrás se perdía la paginación.

La versión por API resolvió los tres de una vez: el `id` viene en cada
registro del JSON, y `status=active,inactive,blocked` trae los bloqueados
en la misma llamada.

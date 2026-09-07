# Los programas que se usan

Estos cinco son los definitivos. Todo lo demás en el repo es el camino que
llevó hasta ellos.

| Programa | Qué hace | Tiempo |
|---|---|---|
| **`DriversMeli.exe`** | Padrón de conductores: ID, nombre, CURP, estatus | ~15 s |
| **`PrefacturasMeli.exe`** | Prefactura con el ID del conductor en cada línea | ~1 min |
| **`RutasMeli.exe`** | Rutas diarias para el control, con calendarios | ~30 s |
| **`CasosPNR.exe`** | Reclamos PNR del período: driver, paquete, monto | ~10 s |
| **`CapacidadMeli.exe`** | Pedidos de vehículos por estación y tipo | ~1 s/día |

## `DriversMeli.exe` — el padrón

```
Estatus [ Todos ▾]   ☑ Registrados entre [01/09/2026] [17/09/2026]
```

**Estatus**: Todos, Activos o Bloqueados. Se filtra en la propia API, así
que pedir solo los bloqueados tarda menos que traerlos todos.

**Fechas**: viene puesto el **mes en curso**, del día 1 a hoy. Desmarca la
casilla para descargar el padrón completo sin filtrar.

Salida: `drivers_meli_AAAAMMDD_HHMMSS.txt` y `.csv`

```
ID | Nombre | CURP | Estatus
```

Cuatro columnas: quién es y si está activo o bloqueado.

## `CasosPNR.exe` — los reclamos

Los reclamos PNR (paquetes no recibidos) de la Bandeja de soporte, que la
web muestra de 30 en 30 y sin forma de exportar.

```
Periodo [ agosto 2026 · Q2 (16 al 31) ▾]   ☐ Con ruta y CEDIS
```

Viene puesto el **período en curso** —Q1 es del 1 al 15, Q2 del 16 al fin
de mes—, y la lista llega hasta un año atrás.

Salida: `pnr_<período>_<sello>.csv` (este no genera TXT)

```
Driver | ID paquete | Monto | Descripcion
```

`Descripcion` es el estado del caso tal como lo muestra la pantalla:
*Esperando comprobante*, *Anulado*, *Enviado a facturación*.

Marcando **Con ruta y CEDIS** se agregan siete columnas más —número de
caso, fecha, estado, motivo, ruta, ID de ruta y CEDIS—. No cuestan nada:
vienen en la misma respuesta, solo que la pantalla no las enseña todas.

### `Abrir cada caso` — lo que solo se ve al entrar

La segunda casilla entra a la ficha de cada reclamo y trae 26 columnas
más. **357 casos en 69 segundos**, medido.

```
ID conductor | Conductor | Telefono | ID vehiculo | Nombre ruta |
Transportadora | ID envio | Valor de la compra | Reclamante |
Designado para recibir | ID seguimiento | Mensaje del reclamo |
Productos | Precios | Cuantos productos | Fecha de entrega |
Quien recibio | Nombre de quien recibio | Documento | Geo de la foto |
Geo de la direccion | Distancia entre geos | Evidencias | Prefactura |
ID comprador | ID reclamo
```

Lo más útil de ahí es el **ID del conductor**: lo traen los 357 casos, y
es lo que cruza con el padrón de `DriversMeli.exe` sin depender del
nombre —que se repite entre personas distintas—.

También vienen los **productos con su precio** (útil cuando el reclamo
es por uno solo de varios), **quién firmó la entrega** y la
**geolocalización de la evidencia** con su distancia a la dirección: si
la foto se tomó a 300 metros del domicilio, ahí se ve.

Dos columnas se omiten solas porque MELI las manda vacías: *Periodo de
facturación* (el que vale es el que pediste) y *Voluminoso*. El programa
solo escribe las columnas que tienen dato en al menos una fila.

### `Formato del control` — el CSV que daba la plataforma

La tercera casilla genera **un archivo aparte** con las mismas 23
columnas, el mismo orden, el mismo nombre y el mismo formato que el CSV
que la plataforma dejaba descargar antes de quitar el botón:

```
LOGISTICS_PNR - 202608Q2_<sello>.csv
```

```
ID DEL CASO | FECHA DEL CASO | TIPO DE PNR | ESTADO |
PERIODO DE FACTURACION | FECHA PEDIDO DE REVISION | PEDIDO DE REVISION |
FECHA DE CIERRE DE CASO | REP - ASISTENTE | COMENTARIO DE CIERRE |
Nº DE PREFACTURA | ID DE ENVIO | PRODUCTOS | VALOR DE LA COMPRA |
REP TRANSPORTADORA | ID DE TRANSPORTADORA | TRANSPORTADORA |
ESTACION DE ORIGEN | RUTA | ID DEL CONDUCTOR | FECHA DE ENTREGA |
ID DE RECLAMO | FECHA DEL RECLAMO
```

Va con **separador coma y sin BOM**, y las fechas en ISO
(`2026-08-19T18:13:41`), igual que el original — así entra en el mismo
sitio donde entraba aquel.

Medido contra 448 casos reales, **21 de las 23 se llenan**:

```
ID DEL CASO                448/448     REP - ASISTENTE             82/448
FECHA DEL CASO             448/448     COMENTARIO DE CIERRE         0/448
TIPO DE PNR                448/448     Nº DE PREFACTURA            56/448
ESTADO                     448/448     REP TRANSPORTADORA          82/448
PERIODO DE FACTURACION     448/448     ID DE TRANSPORTADORA       448/448
FECHA PEDIDO DE REVISION    82/448     TRANSPORTADORA             448/448
PEDIDO DE REVISION          82/448     ESTACION DE ORIGEN         448/448
FECHA DE CIERRE DE CASO    448/448     RUTA                       448/448
ID DE ENVIO                448/448     ID DEL CONDUCTOR           448/448
PRODUCTOS                  448/448     FECHA DE ENTREGA           448/448
VALOR DE LA COMPRA         448/448     ID DE RECLAMO              448/448
                                       FECHA DEL RECLAMO            0/448
```

Las de revisión salen 82 porque solo 82 casos tuvieron una. Las dos que
salen en cero —*Comentario de cierre* y *Fecha del reclamo*— **también
venían vacías en el CSV original**: la primera en todas sus filas, la
segunda en todas menos dos de 2024.

Marcarla enciende sola *Abrir cada caso*: la mitad de las columnas salen
de la ficha. **Si marcas solo esta casilla, baja solo este archivo.**

### Por qué el detalle no usa una API

La ficha del caso **no pide datos a ninguna API**: la página
`/case-center/cases/<id>` viene armada desde el servidor con los datos
ya dentro, en un objeto `caseDetail`. El programa lo recorta del HTML en
vez de raspar la pantalla, contando llaves para saber dónde termina.

Ese recorte se hace **dentro del navegador**: cada página pesa cerca de
1 MB y traer 357 enteras a Python agotaría la memoria de Chrome. Lo que
cruza son unos 7 KB por caso.

### Los casos sin conductor

Algunos reclamos llegan con el nombre en blanco: Mercado Libre todavía no
asignó conductor. El programa los deja vacíos en vez de inventarlos, y al
terminar dice cuántos son. Como sí traen el **número de ruta**, se pueden
cruzar después con el reporte de rutas, igual que hace la prefactura.

### Por qué son 12 vueltas

La API acepta **30 casos por página y ni uno más** — con 50 responde 400.
Así que 351 casos son 12 consultas. Aun así tarda unos 10 segundos.

## `CapacidadMeli.exe` — los pedidos de vehículos

Lo que Mercado Libre pide cada día: cuántos vehículos, de qué tipo, en qué
estación, y qué se hizo con cada pedido.

```
Desde [ 01/09/2026 📅]  Hasta [ 01/09/2026 📅]  [Ayer] [7] [15] [30 días]
```

Viene puesto en **ayer**. La pantalla del panel agrupa por estación y hay
que desplegar cada grupo a mano; aquí sale todo de una vez.

Salida: **dos CSV** (este no genera TXT; el CSV se abre igual en Excel).

El detalle, una fila por vehículo pedido:

```
Fecha | Estacion | Nombre estacion | Tipo de vehiculo | Estado | Flota |
SDD | Ciclo | ETA | ETD | ID pedido | ID viaje | Creado
```

Y el resumen, una fila por estación y tipo con los estados en columnas:

```
Fecha | Estacion | Nombre estacion | Tipo de vehiculo | Flota | Total |
Para responder | Aceptado | Expirado | Rechazado | Cancelado por MELI
```

Ese segundo es el que sirve para planear: de un vistazo se ve que EQR2
pidió 50 Small Van y se aceptaron las 50.

### Sobre las fechas

El día del panel va de **06:00 Z a 06:00 Z**, que es la medianoche en
Ciudad de México. El programa usa esa misma hora de corte, así que un
rango de varios días no se corre ni pierde pedidos del borde.

Los días se consultan **uno por uno** —la API los devuelve así aunque le
pidas un rango—, a razón de medio segundo cada uno. Cinco días tardan
unos 3 segundos; un mes, unos 15. Si un día no tiene pedidos, lo dice y
sigue con los demás.

### Hasta cuándo hay historial

Mercado Libre no guarda esto para siempre. El botón **Hasta cuando hay
datos** lo averigua por bisección —9 consultas, no cientos— y ofrece
poner esa fecha en *Desde*. Medido el 2 de septiembre de 2026, el límite
estaba en el **5 de junio**: 88 días.

Si pides un rango completamente vacío, lo busca solo y te lo dice.

### Dos datos que a veces vienen en blanco

**El ciclo** (AM1, SD2…) lo traen algo más de la mitad de los pedidos: no
todos los viajes lo llevan. El programa dice cuántos son al terminar,
para que no se lea como dato perdido.

**El nombre largo de la estación** existe para todas menos `SQR2`, cuya
descripción en el panel es su propio código.

### Un detalle del panel

Las tarjetas de arriba muestran un total de 158 cuando en realidad hay
162 pedidos. No es un error de extracción: **el total de MELI se olvida
de los expirados**. Cada estado por separado sí cuadra exacto, y el
programa cuenta los 162.

## `PrefacturasMeli.exe` — facturación con ID

**No hay que saberse el número.** Al abrir Chrome, el programa consulta el
listado y llena tres desplegables:

```
Año [ 2026 ▼]   Mes [ Julio ▼]   Q [ Q2 ▼]

#6595499  ·  7,151,826.56 MXN  ·  Por pagar
```

Arranca en el **año en curso**, su **último mes con prefactura** y la
**última quincena**, así que normalmente solo hay que presionar
*Extraer TODO*.

Solo lista las **Regular · Last Mile** — por eso no aparecen en cada línea:
son el filtro fijo. Las Complementarias y las de Line Haul quedan fuera.
En el listado real, el mismo período `202607Q2` tiene las tres.

El CSV que descarga el panel trae el **nombre** del conductor pero no su
ID, y hay 25 nombres repetidos en el padrón — dos personas distintas
llamadas igual. Este programa cruza por **número de ruta**, no por texto:

```
prefactura (ruta 147326006)
   ↓ el reporte de operación dice quién hizo esa ruta
ID usuario 4965727
```

### Si la descarga automática falla

A veces la página no ofrece el enlace, o el diálogo cambia. Cuando pasa, el
programa **no se queda a medias**: avisa y ofrece la salida manual.

```
Cargar un CSV descargado a mano
```

Descargas el CSV desde Chrome como siempre (*Descargar → CSV*), presionas
ese botón y eliges el archivo. El resto es idéntico: lee sus fechas, pide
el reporte del rango correcto e inyecta los IDs.

Tu archivo no se toca — el resultado se guarda aparte.

Si eliges un archivo que no es una prefactura, lo detecta y lo dice, en vez
de escribir un resultado sin sentido.

Salida: **un solo archivo**, `JulioQ2.csv`. El nombre es el período, sin
el año. Si ya existe uno igual no lo pisa: escribe `JulioQ2 (2).csv`.

```
ID prefactura | Periodo | Estado | ID ruta | ID usuario | Nombre |
Placa | Concepto | Tipo | Fecha inicio | Fecha fin | Cantidad | Costo | Total
```

Las tres primeras columnas se repiten en cada fila a propósito: así el
archivo **se identifica solo** aunque lo renombren o lo bajen dos veces.

### Los totales, al final del mismo archivo

Cierra con los totales que declara MELI, en el mismo formato que traía la
prefactura original —etiqueta a la izquierda, monto a la derecha— más una
línea que comprueba contra la suma del detalle:

```
Total servicios:                                    +  6266264.00
Total adicionales:                                   +  235653.00
Total penalidades:                                    -  63461.52
Total prefactura:                                   +  6438455.48
Suma del detalle:                                      6438455.48
CUADRA                                                       0.00
```

Sin esto, el sistema puede sumar mal 2,600 filas y nadie se entera. Si los
números no coinciden, la última línea dice `NO CUADRA` y la diferencia.

Para quedarse solo con el detalle, basta filtrar por la columna `Tipo`
(`service`, `additional`, `penalty`): las filas de totales la traen vacía.

### El signo de las penalidades

Las penalidades salen **en negativo**, tal como MELI las declara en
`item_type.operation`. Así la columna Total se suma directo y da el total
de la prefactura, sin tener que decidir qué resta.

Antes venían en positivo y la diferencia era de $168,350 según cómo se
interpretara.

## `RutasMeli.exe` — el control diario

Ventana con dos calendarios. Viene puesto en **ayer**, y hay atajos para
7 y 15 días.

```
Desde [ 16/08/2026 📅]  Hasta [ 16/08/2026 📅]  [Ayer] [7 días] [15 días]
```

Los calendarios abren al hacer clic en cualquier parte del campo, y en su
barra se elige mes y año.

### Hasta cuándo hay datos

Mercado Libre **no guarda el reporte indefinidamente**. Pedir fechas
demasiado viejas devuelve un archivo vacío, y antes eso se descubría a
mitad de la extracción.

Ahora hay un botón que lo averigua:

```
Hasta cuando hay datos en Mercado Libre
```

Busca hacia atrás por bisección —unas 12 consultas, no cientos— y te dice
desde qué fecha se puede extraer. Ofrece ponerla directo en *Desde*.

Además, **antes de cada extracción** comprueba que el rango tenga datos:

- Si no hay nada, avisa y ofrece buscar el límite, sin gastar minutos.
- Si el rango está a medias (el final tiene datos pero el inicio no),
  avisa que el reporte saldrá incompleto y continúa.

Salida: `rutas_<desde>_a_<hasta>_<sello>.txt` y `.csv`

```
FECHA | CEDIS_MELI | ID_USUARIO | DRIVER | Vehiculo | Placas |
Tipo_de_servicio | ZONA_DE_RUTA | RUTA | ID_Ruta | SPR | ENTREGADOS |
FALLIDOS | KM | NO_VISITADOS | PROD_HORA | PERFORMANCE
```

**17 columnas, todas con dato.** `PERFORMANCE` sale como `96,84%`.

### Las rutas de Service Partner no llevan nombre

Comprobado con datos reales: de 48 Service Partner, **ninguna** trae
nombre de ruta, mientras las RD y SDD lo traen todas. Así que el programa
no consulta sus fichas —sería tiempo perdido— ni las cuenta como
faltantes:

```
Con nombre de ruta  113/113
  (48 de Service Partner no llevan nombre)
```

Si el número real no cuadra, entonces sí avisa y sugiere un rango más
corto.

`ExtraerRutas.exe` es la misma extracción en consola, por si la prefieres.

Dos cosas que sí deduce: el `Tipo_de_servicio` sale del vehículo (Media
Milla SP → Service Partner; MLP → RD; con sufijo SDD → SDD), y el nombre
de la `RUTA` (C1_AM1) se lee del HTML de cada ficha, en lotes paralelos.

---

## Requisitos

Windows 10/11 de 64 bits, Google Chrome, e internet la primera vez (para
que Selenium Manager baje el chromedriver). **No hace falta Python.**

Windows mostrará "Windows protegió tu PC" porque los ejecutables no están
firmados: *Más información* → *Ejecutar de todas formas*.

Los archivos que generan contienen **CURP y nombres** — datos
personales. Trátalos en consecuencia.

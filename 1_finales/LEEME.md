# Los programas que se usan

Estos tres son los definitivos. Todo lo demás en el repo es el camino que
llevó hasta ellos.

| Programa | Qué hace | Tiempo |
|---|---|---|
| **`DriversMeli.exe`** | Padrón de conductores: ID, nombre, CURP, estatus | ~15 s |
| **`PrefacturasMeli.exe`** | Prefactura con el ID del conductor en cada línea | ~1 min |
| **`RutasMeli.exe`** | Rutas diarias para el control, con calendarios | ~30 s |

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

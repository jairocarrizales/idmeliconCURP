# Los programas que se usan

Estos tres son los definitivos. Todo lo demás en el repo es el camino que
llevó hasta ellos.

| Programa | Qué hace | Tiempo |
|---|---|---|
| **`DriversMeli.exe`** | Padrón de conductores: ID, nombre, CURP, estatus, teléfono | ~15 s |
| **`PrefacturasMeli.exe`** | Prefactura con el ID del conductor en cada línea | ~1 min |
| **`ExtraerRutas.exe`** | Rutas diarias para el control, con rango de fechas | ~30 s |

## `DriversMeli.exe` — el padrón

Ventana con dos botones. Abre Chrome, inicias sesión, presionas **Extraer
TODO** y baja los ~2,000 conductores.

Salida: `drivers_meli_AAAAMMDD_HHMMSS.txt` y `.csv`

```
ID | Nombre | CURP | Estatus | Telefono | E-mail | Fecha creacion
```

Si respondes que sí a los teléfonos, consulta las fichas una por una
(~2 min). El listado se guarda antes, así que una interrupción no cuesta
lo ya bajado.

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

Salida: **`JulioQ2.csv`** — el nombre es el período, sin el año. Si ya
existe uno igual no lo pisa: escribe `JulioQ2 (2).csv`.

```
ID ruta | ID usuario | Nombre | Placa | Concepto | Tipo |
Fecha inicio | Fecha fin | Cantidad | Costo | Total
```

## `ExtraerRutas.exe` — el control diario

Le das un rango de fechas (por defecto **ayer**) y genera la tabla para
cargar al sistema.

Salida: `rutas_<desde>_a_<hasta>_<sello>.txt` y `.csv`

```
FECHA | CEDIS_MELI | ID_USUARIO | DRIVER | Vehiculo | Placas |
TIPO_DE_VEHICULO | Tipo_de_servicio | Tipo_de_ruta | ZONA_DE_RUTA |
CODIGO_POSTAL | RUTA | ID_Ruta | SPR | ENTREGADOS | FALLIDOS |
KM | NO_VISITADOS | PROD_HORA | PERFORMANCE
```

**Tres columnas quedan vacías a propósito** — no existen en ninguna fuente
de MELI y hay que capturarlas aparte:

- `TIPO_DE_VEHICULO` (Externo/Interno): depende del proveedor
- `Tipo_de_ruta` (Local/Foránea)
- `CODIGO_POSTAL`

El programa las lista al terminar para tenerlas presentes.

Dos cosas que sí deduce: el `Tipo_de_servicio` sale del vehículo (Media
Milla SP → Service Partner; MLP → RD; con sufijo SDD → SDD), y el nombre
de la `RUTA` (C1_AM1) se lee del HTML de cada ficha, en lotes paralelos.

---

## Requisitos

Windows 10/11 de 64 bits, Google Chrome, e internet la primera vez (para
que Selenium Manager baje el chromedriver). **No hace falta Python.**

Windows mostrará "Windows protegió tu PC" porque los ejecutables no están
firmados: *Más información* → *Ejecutar de todas formas*.

Los archivos que generan contienen **CURP, nombres y teléfonos** — datos
personales. Trátalos en consecuencia.

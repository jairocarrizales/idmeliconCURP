# Las sondas de diagnóstico

Estas herramientas no extraen datos para usar: **encuentran las APIs** que
los programas finales consumen.

Se conservan porque si Mercado Libre cambia un endpoint, volver a
encontrarlo es cuestión de correr la sonda correspondiente en vez de
empezar de cero.

Todas aplican la misma técnica: espiar el tráfico del propio navegador con
el performance log de Chrome, en lugar de adivinar URLs. Adivinar no
funciona — en un caso se probaron 30 combinaciones y las 30 dieron 404.

## Por dónde empezar si algo se rompe

| Falla | Corre esto |
|---|---|
| `DriversMeli.exe` no trae registros | `DescubrirAPI.exe` |
| Falta teléfono o e-mail | `ProbarPerfilAPI.exe` |
| `PrefacturasMeli.exe` falla | `DescubrirBilling.exe` → `ProbarEndpoints.exe` |
| Falta el ID en la prefactura | `SondearRuta.exe`, `SondearMonitoring.exe` |
| `ExtraerRutas.exe` sin datos | `SondearRutas.exe` → `VerRutaCompleta.exe` |
| Falta el nombre de ruta | `ProbarHtmlRuta.exe` |

## Qué encontró cada una

### Drivers

- **`DescubrirAPI`** — halló `/api/drivers/drivers-and-invites`, la que
  reemplazó al scraping. De 30 minutos a 15 segundos.
- **`ProbarPerfilAPI`** — halló `/api/drivers/<id>`, la única que devuelve
  teléfono y e-mail.

### Prefacturas

- **`DescubrirBilling`** — el endpoint del detalle.
- **`SondearBilling`**, **`VerItems`** — confirmaron que los items **no**
  traen `driver_id`: 0 de 416.
- **`SondearRuta`**, **`SondearMonitoring`** — buscaron el ID por el lado de
  las rutas. La primera falló (adivinaba URLs); la segunda encontró el
  camino real.
- **`SondearDescargas`**, **`SondearPost`** — los dos botones de descarga,
  incluido el cuerpo `{"tolls_items":null}` que hacía falta para
  reproducir el POST.
- **`ProbarEndpoints`** — comprobó que ambos responden antes de construir
  sobre ellos.

### Rutas

- **`SondearRutas`** — halló `POST /logistics/api/monitoring/get-routes-list`.
- **`VerRutaCompleta`** — volcó sus 124 campos por ruta, y mostró que solo
  devuelve las rutas activas del día, no un histórico.
- **`SondearDetalleRuta`**, **`BuscarNombreRuta`** — buscaron el nombre
  `C1_AM1`. No está en ninguna respuesta JSON.
- **`ProbarHtmlRuta`** — lo encontró: la ficha llega del servidor con el
  nombre ya puesto. 0.7 s por ruta, ~12 s para 168 en paralelo.

---

## Sobre los reportes que generan

Van a la carpeta `diagnosticos/` y **no se suben al repositorio**: aunque
enmascaran los nombres, pueden contener datos de conductores.

Ninguna sonda guarda cookies ni tokens.

## El método, documentado

Está destilado en la skill `skills/api-en-vez-de-scraping/`, escrita para
reutilizarse en cualquier panel web con login — no solo el de Mercado
Libre.

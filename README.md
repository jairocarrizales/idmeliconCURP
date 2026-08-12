# Extractor de Drivers — Mercado Libre Envíos

Extrae la lista completa de transportistas de
`envios.adminml.com/logistics/provider-management/drivers`
y la guarda en un archivo listo para Excel.

Captura **nombre, CURP, tipo, fecha de creación y estatus** — tanto de los
drivers **activos** como de los **bloqueados**.

---

## Uso rápido

1. Ejecuta **`ExtraerDriversMeli.exe`** (doble clic).
2. Se abre Chrome en la página de drivers → **inicia sesión tú mismo**.
3. Cuando ya veas la lista en pantalla, regresa a la ventana negra y presiona **ENTER**.
4. El script hace el resto: presiona "Mostrar más" hasta agotar la lista y guarda los archivos.

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
# | Nombre | CURP | Tipo | Fecha creación | Estatus | Observación
```

`Estatus` trae el estado principal (`Activo`, `Bloqueado`, …) y `Observación`
la nota que a veces lo acompaña (`Falta leve`, `Rehacer capacitación`).

Al terminar, la consola imprime un resumen del conteo por estatus.

---

## Correr desde el código fuente

```bash
pip install selenium
python extraer_drivers.py
```

O doble clic en `EXTRAER_DRIVERS.bat`.

Requiere Python 3.8+ y Google Chrome. Selenium 4.6+ descarga el chromedriver
automáticamente (Selenium Manager), no hay que instalarlo aparte.

### Recompilar el .exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --console --name ExtraerDriversMeli ^
  --collect-all selenium --distpath . --workpath build --specpath build ^
  extraer_drivers.py
```

---

## Aviso sobre datos personales

Los archivos generados contienen **CURP y nombres completos** — datos personales
bajo la LFPDPPP. El `.gitignore` los excluye del repositorio a propósito, junto con
`chrome_profile/` (que guarda tu sesión). Trátalos con el cuidado que corresponde
y no los subas a ningún lado.

---

## Si algo falla

Los selectores CSS están tomados del HTML actual del sitio. Si Mercado Libre
cambia el maquetado, hay que ajustarlos en `extraer_drivers.py`
(función `extraer_datos`) y recompilar.

La consola avisa si detecta registros sin nombre o sin CURP:

```
ADVERTENCIA: 3 sin nombre, 1 sin CURP.
```

Eso es señal de que el HTML cambió y toca revisar los selectores.

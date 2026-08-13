# Extractor de Drivers — Mercado Libre Envíos

Extrae la lista completa de transportistas de
`envios.adminml.com/logistics/provider-management/drivers`
y la guarda en un archivo listo para Excel.

Captura **ID, nombre, CURP, estatus, tipo y fecha de creación** — tanto de los
drivers **activos** como de los **bloqueados**. Opcionalmente también
**teléfono y e-mail**.

---

## Uso rápido

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

Estos tres campos viven en la ficha individual del driver
(*3 puntos → Ver Perfil*), no en el listado. El extractor los busca en dos niveles:

1. **Gratis.** El ID es el número de la URL del perfil. Si el listado ya incluye ese
   enlace en cada fila, se toma de ahí y no hay que abrir nada. Rapidísimo.
2. **Abriendo perfiles.** Si hace falta el teléfono/e-mail, o el listado no expone
   los enlaces, se visita cada ficha (~3 s por driver). Con muchos registros esto
   toma varios minutos, por eso el programa **pregunta antes** de hacerlo.

Si el listado no trae enlaces, se usa el menú de 3 puntos como plan B. Ese modo es
más lento y solo alcanza las filas visibles tras volver a la lista — la consola avisa
si ese es el caso.

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

Los archivos generados contienen **CURP, nombres completos y — si usas el paso de
perfiles — teléfono y correo electrónico**. Todo eso son datos personales bajo la
LFPDPPP, y los datos de contacto elevan bastante la sensibilidad del archivo. El `.gitignore` los excluye del repositorio a propósito, junto con
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

# Skills

## `api-en-vez-de-scraping`

El método que convirtió los extractores de este repo de scraping lento a
llamadas directas a la API — de ~30 minutos a 15 segundos, trayendo además
campos que la pantalla no muestra.

Está escrita para reutilizarse en **cualquier panel web con login**, no solo
en el de Mercado Libre.

### Qué cubre

| Tema | Dónde |
|---|---|
| Descubrir el endpoint espiando el tráfico de Chrome | `SKILL.md` §1 |
| Autenticarse sin tocar cookies ni tokens | §2 |
| Paginación por cursor, con sus cuatro defensas | §3 |
| Pedir detalles en paralelo (medido: 4× más rápido) | §4 |
| Descargar binarios (XLSX, PDF) sin corromperlos | §5 |
| Cruzar dos fuentes por número, no por nombre | §6 |
| Ergonomía: GUI, hilos, perfil de Chrome | §7 |
| Verificar con datos reales | §8 |
| Datos personales | §9 |

### Archivos de apoyo

```
scripts/espiar_red.py      descubridor genérico: espía, filtra, puntúa
scripts/llamar_api.py      fetch desde la página: JSON, binario, lotes
scripts/perfil_chrome.py   perfil persistente, cierre de huérfanos
scripts/leer_xlsx.py       XLSX sin openpyxl
scripts/plantilla_gui.py   ventana PySide6 con hilo de trabajo
references/errores.md      los fallos concretos que costaron tiempo
```

Los scripts son independientes: se pueden copiar sueltos a otro proyecto.

### Instalación

Para que Claude Code la use automáticamente, copia la carpeta a las skills
globales:

```powershell
Copy-Item skills\api-en-vez-de-scraping "$env:USERPROFILE\.claude\skills\" -Recurse
```

En macOS o Linux:

```bash
cp -r skills/api-en-vez-de-scraping ~/.claude/skills/
```

Después se activa sola cuando el trabajo lo amerite — al escribir un extractor,
al arreglar un scraper lento, o cuando aparezca uno de los errores del
catálogo.

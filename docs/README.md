# SortMedia — Clasificación VLM de una biblioteca multimedia

Pipeline en Python para organizar una biblioteca multimedia (~106.000
archivos, ~6 TB) con temática de culturismo/musculación: deduplicación,
clasificación por un **modelo de visión (VLM) en GPU remota** (gemma3:12b
vía Ollama), árbol temático, renombrado con títulos preservados y
metadatos EXIF en caliente.

> ⚠️ **Privacidad**: los datos locales (rutas, clasificaciones, logs) NO
> están en este repositorio (`estado/`, `salida/` y la BD están en
> `.gitignore`). Este repo contiene solo código y documentación.

## Estructura

```
SortMedia\
├── common.py              # prompt VLM, puntuación, formato de nombre, EXIF
├── 01_inventario.py       # escaneo -> SQLite (reanudable)
├── 02_duplicados.py       # dedup por hashes parciales (--pase N)
├── 03_metadatos.py        # ffprobe/EXIF (opcional, paralelo)
├── 04_clasificar.py       # mueve al árbol (tipo/época/categoría)
├── 05_informe.py          # informe de estado
├── 06_vision.py           # clasificación VLM masiva (--escribir-exif)
├── 07_sacar_raras.py      # miniaturas / errores / extrañas / no-interés
├── 08_indice.py           # índice CSV/JSON de la biblioteca
├── 09_comparativa.py      # clasificación de imágenes sueltas (pruebas)
├── 10_renombrar.py        # renombrado + EXIF por tandas (reanudable)
├── 11_temas.py            # árbol temático (--descubrir para ajustar)
├── 12_progreso.py         # progreso del batch con ejemplos
├── 13_aplicar.py          # aplica directorios a clasificaciones nuevas
├── nuevo.py               # bandeja de entrada (F:\Incoming)
├── despertar_legion.py    # Wake-on-LAN + verificación de la GPU remota
├── revertir_miniaturas.py # utilidad puntual (revertir falsos positivos)
└── docs\
    ├── GUION.md           # GUÍA COMPLETA: estado, infraestructura, comandos
    ├── LEGION_OLLAMA.md   # instrucciones para otra IA (GPU compartida)
    └── README.md          # este archivo
```

## Pipeline principal

```
02_duplicados --pase 2    # dedup en el árbol (antes de gastar GPU)
07_sacar_raras --solo-miniaturas   # miniaturas sin coste de VLM
06_vision --workers 6 --escribir-exif   # VLM ~20 h, reanudable
07_sacar_raras            # NoInteresante / Extranas / Errores
11_temas                  # Imagenes\<Tema>\<Epoca>
08_indice                 # índice CSV/JSON
10_renombrar --minutos 55 # renombrado + EXIF por tandas
```

Todos los scripts son **reanudables** (marcan lo hecho en SQLite) y se
ejecutan desde `F:\scripts` en la máquina local; la GPU es una máquina
remota (Legion) con Ollama compartido. Ver `docs/GUION.md` para el
estado actual, la infraestructura y los comandos de reanudación.

## Decisiones de diseño (resumen)

- **Modelo**: gemma3:12b vía Ollama (evaluado frente a qwen2.5vl,
  qwen3-vl y llama3.2-vision; ver GUION §3).
- **Puntuación 0-100 determinista** en código (`calcular_puntuacion`):
  el VLM solo responde hechos (fisico, guapo, joven, viril...); los pesos
  y techos son ajustables.
- **Nombres**: `<título_original_si_interesa> (<kw>;p<SCORE>;<sexo>).ext`
  con preservación de títulos interesantes y slug de la IA para hashes.
- **Metadatos**: EXIF sin pérdida (XPKeywords, UserComment JSON con
  descripción, UserComment contiene la descripción completa de la IA)
  escritos EN CALIENTE durante la clasificación.

## Requisitos

Python 3.10+, Pillow, piexif. Ollama 0.32+ en la máquina de GPU con
`gemma3:12b`. SSH con clave a la GPU remota (ver LEGION_OLLAMA.md).

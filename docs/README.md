# Clasificación de F:\ — README (punto de entrada)

Proyecto de organización de `F:\` (contenido multimedia, temática
musculación/culturismo). **Si empiezas un hilo/sesión nueva, lee
PRIMERO `F:\GUION.md`** — contiene el estado actual, la infraestructura
remota (Legion/GPU/Ollama), el modelo elegido, el pipeline completo y los
comandos de reanudación. Este README es solo el resumen.

## Estado en una frase

105.614 archivos inventariados, ~584 GB de duplicados eliminados
(2 pases), 11.042 miniaturas apartadas, 95.074 movidos al árbol nuevo;
**pendiente: la clasificación VLM masiva (~13.000 imágenes restantes) con
gemma3:12b** y después temas + renombrado (script `06_vision.py`, reanudable,
~20 h) y después renombrado+metadatos (`10_renombrar.py`).

## Scripts (F:\scripts\)

01 inventario · 02 dedup (--pase) · 03 metadatos · 04 clasificar ·
05 informe · **06 vision (VLM masivo)** · 07 sacar raras/miniaturas ·
08 índice · 09 comparativa · **10 renombrar+EXIF** · **11 temas** ·
nuevo.py (F:\Incoming) · despertar_legion.py (WoL) · common.py (reglas)

## Infraestructura clave

- GPU: `legion` (192.168.1.136) con Ollama 0.32.5 en `http://legion:11434`
- Modelo: **gemma3:12b** (elegido tras evaluar; qwen2.5vl:7b fallback)
- SSH: `ssh -i C:\Users\David\Documents\id_ed25519 dvdjg@192.168.1.136`
- Despertar: `python F:\scripts\despertar_legion.py`
- Regla de oro: **reutilizar la instancia de ollama existente**, no duplicar

## Requisitos

Python 3.13, Pillow, piexif (instalados). ffprobe (yt-dlp) en Legion.

# LEGION_OLLAMA — Instrucciones para otra IA (uso colaborativo de la GPU)

Este documento está pensado para que una IA use el
servidor de inferencia de visión de forma colaborativa.

---

## 1. Contexto

Hay una máquina remota **Legion** (Windows 11, NVIDIA RTX 5080 Laptop
16 GB, IP fija `192.168.1.136`, hostname `legion`) que ejecuta **Ollama 0.32.5** como servidor compartido de inferencia. la GPU: se comparte con otras tareas.

## 2. Acceso

- **SSH** (para administrar, no para inferencia):
  `ssh -i C:\Users\David\Documents\id_ed25519 dvdjg@192.168.1.136`
  (usa la IP si el nombre no resuelve; añade `-4` si falla IPv6).
- **API de inferencia (HTTP, uso normal)**:
  `http://legion:11434/api/generate` (Ollama, OpenAI-ish).
  Comprobar salud: `curl http://legion:11434/api/version`.

## 3. REGLA DE ORO: no duplicar el servidor

1. Antes de cualquier cosa, comprueba si Ollama responde:
   `curl --max-time 5 http://legion:11434/api/version`
2. Si responde: **REUTILIZA la instancia**. Nunca lances otra.
3. Si no responde (legión dormida o caída):
   - Despertar: `python F:\scripts\despertar_legion.py` (Wake-on-LAN).
   - Arrancar Ollama: `ssh ... "schtasks /run /tn iniciar_servidor"`.
4. Nunca mates procesos `ollama*` a la ligera: puede haber un lote en
   curso. Comprueba `ollama ps` antes:
   `ssh ... "ollama ps"` (muestra el modelo cargado).
5. Si necesitas un modelo distinto, cárgalo SIN descargar el actual si
   hay trabajo en curso, o espera. Ollama gestiona una instancia por
   modelo a la vez.

## 4. Modelos disponibles (Ollama en Legion)

| Modelo | Uso | Estado |
|---|---|---|
| **gemma3:12b** | **PREDETERMINADO** para clasificación | No censura en pruebas; ~11 s/img |
| qwen2.5vl:7b | Alternativa rápida (~5 s/img) | Flojo en explícito y matices |
| qwen2.5vl:3b | No usar | Repite el esquema |
| qwen3-vl:8b | **ROTO en Ollama** | Todo el output va a `thinking`; nunca emite respuesta final |
| llama3.2-vision | No usar | Formato roto, repeticiones |

## 5. Llamada de ejemplo (imagen + JSON estructurado)

```
POST http://legion:11434/api/generate
{
  "model": "gemma3:12b",
  "images": ["<base64 de la imagen>"],
  "prompt": "<prompt de producción, ver §6>",
  "stream": false,
  "options": {"temperature": 0.0, "num_predict": 800}
}
```
Respuesta: `response` contiene el JSON (a veces envuelto en ```json```:
quitarlo antes de parsear).

## 6. Prompt de producción (NO lo inventes; usa este esquema)

El prompt oficial vive en `F:\scripts\common.py` →
`common.construir_prompt_vision(nombre_archivo)`. Si tienes acceso a
F:\, impórtalo; si no, el esquema JSON que pide es:

```
{"resumen":"máx 12 palabras", "descripcion":"2-4 frases detalladas",
 "categorias":["c1","c2"], "atributos":["a1..a5"],
 "desnudez":"ninguna|parcial|total", "tipo":"foto|render_3d|dibujo|anime|AI",
 "escenario":"interior|exterior|estudio|otro",
 "genero_aprox":"masculino|femenino|mixto|n/a",
 "es_furry":"si|no", "es_culturismo":"si|no", "es_extraña":"si|no",
 "sexualizacion":"ninguna|sensual|erotismo|insinuacion|genitales|sexo_explicito",
 "fisico":"ninguno|atletico|trabajado|musculoso|competicion",
 "vello_corporal":"si|no", "guapo":"si|no", "joven":"si|no",
 "viril":"si|no", "fisico_visible":"si|no",
 "es_familiar":"si|no", "menores":"si|no",
 "hay_hombre_atractivo":"si|no", "personas":0,
 "estilo":"realista|semirrealista|render_3d|anime|cartoon|pintura|otro",
 "posible":"si|no", "fantasia_verosimil":"si|no", "defectos":"",
 "organo_imposible":"si|no", "violencia":"si|no", "admiradores":"si|no",
 "nombre_sugerido":"slug_si_el_nombre_actual_no_describe"}
```

Reglas de calibración (no las cambies sin avisar):
- `fisico`: `competicion` = masa extrema/esteroideo (solo esto merece
  90+); `trabajado` = aficionado de gimnasio; `atletico` = en forma sin
  músculo.
- `joven` se decide SOLO por la cara (ignorar cuerpo/uniforme).
- `guapo` y `viril` son estrictos ("no" ante la duda).
- `hay_hombre_atractivo` = solo "¿hay un hombre adulto?" (el atractivo
  va en `guapo`).
- La imagen puede ser contenido adulto: responder con objetividad, sin
  censura ni moralizar.

## 7. Puntuación (la calcula el código, no el modelo)

`common.calcular_puntuacion(data)` (F:\scripts\common.py) convierte los
hechos en 0-100:
- 0 si menores/familiar/sin hombre/sin personas/no masculino.
- +40 competicion, +25 musculoso, +10 trabajado, +5 atletico;
  +15 guapo, +10 joven, +15 viril, +5 sin vello, +5 erótico,
  +5 admiradores.
- Techos: trabajado ≤69; atletico/ninguno ≤39 (≤59 si viril).
- <40 → NoInteresante. 40-79 sin viril = "dudoso" (revisar).

## 8. Colaboración (protocolo)

- **Estado compartido**: `F:\scripts\estado\estado.db` (SQLite) y
  `F:\scripts\salida\*.log`. Antes de lanzar trabajo, mira
  `python F:\scripts\05_informe.py` y el log del lote en curso
  (`F:\scripts\salida\vision_run.log`).
- **Un lote a la vez**: si `06_vision.py` está corriendo (hay python
  activo o el log progresa), NO lances otro clasificador; únete al
  protocolo (consume la API con moderación) o espera.
- **Tandas**: si trabajas con `10_renombrar.py` o el clasificador, usa
  presupuesto de tiempo (`--minutos`) y deja reanudar: todos los scripts
  son idempotentes (marcan lo hecho).
- **No apagues ni suspendas Legion**: si ves que va a dormirse,
  `ssh ... "schtasks /run /tn keep_awake"` (o powercfg standby 0).
- **Concurrencia**: gemma3 a ~11 s/petición; no mandes más de 4-6
  peticiones concurrentes (la GPU es el cuello de botella).

## 9. Referencias

- `F:\GUION.md` — guía completa del proyecto (estado, pipeline, reglas).
- `F:\scripts\common.py` — prompt, puntuación, formato de nombre.
- `F:\scripts\06_vision.py` — clasificador masivo (modelo por defecto
  gemma3:12b; `--modelo` para cambiar).
- `F:\scripts\09_comparativa.py` — clasificar imágenes sueltas.
- `F:\scripts\10_renombrar.py` — renombrado + metadatos por tandas.
- `F:\scripts\despertar_legion.py` — WoL.

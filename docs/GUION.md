# GUION — Clasificación de F:\ (guía de ejecución y reanudación)

Este documento es la **fuente de verdad** del proyecto. Si empiezas un
hilo nuevo (sesión nueva de IA), LEE ESTE ARCHIVO COMPLETO antes de hacer
nada: contiene el estado, la infraestructura, los comandos y las reglas.

---

## 0. ESTADO ACTUAL (al día)

**Ejecutado:**
- Inventario de F:\ completo: **105.614 archivos** (~6,4 TB) en
  `F:\scripts\estado\estado.db` (SQLite).
- Deduplicación: **11.000 copias borradas, ~584 GB liberados** en 2 pases
  (pase 1: 10.538 copias/574 GB en el origen; pase 2 tras el movimiento:
  462 copias/10,3 GB más en Clasificado — `02_duplicados.py --pase 2`).
- Miniaturas apartadas: **11.042 imágenes** → `Raras\Miniaturas\`
  (`07_sacar_raras.py --solo-miniaturas`, sin coste de VLM).
- Clasificación en árbol nuevo: **95.074 archivos movidos** a
  `F:\Clasificado\` (Imagenes/Videos/Culturismo/Otros, épocas
  Clasico/IA/SinDeterminar). Carpetas de origen vacías eliminadas.
- `F:\David\` **NUNCA se toca** (ni se escanea). Tampoco Clasificado,
  scripts, System Volume Information, $RECYCLE.BIN, .Trash-1000,
  .wwebjs_cache, msdownld.tmp.

**Pendiente (el motivo de este proyecto):**
- **CLASIFICACIÓN VLM MASIVA NO LANZADA**: ~24.000 imágenes (Imagenes +
  Culturismo\Imagenes) esperan clasificación con **gemma3:12b**.
  El modelo está elegido y el prompt calibrado (ver sección 5 y 9).
  Comando: `python F:\scripts\06_vision.py --workers 6`
  (~11 s/img → ~20 h con 6 flujos; REANUDABLE: corta cuando quieras).
- Tras clasificar: `07_sacar_raras.py` (mueve NoInteresante/Raras),
  `08_indice.py` (índice CSV/JSON), `10_renombrar.py` (renombra + EXIF
  por tandas).
- `F:\Clasificado\Otros\*` (audio, PDF, HTML, incompletos...) pendientes
  de inspección humana.

**Estado de la BD:** tabla `vision` VACÍA (se limpia al cambiar el modelo;
el batch la rellena). Las tablas inventario/movidos/duplicados/
sospechosos/progreso tienen el historial completo.

---

## 1. ÁRBOL DESTINO

```
F:\Clasificado\
├── Incoming\                      ← copia aquí lo nuevo y ejecuta nuevo.py
├── NoInteresante\                 ← puntuación < 40 (fotos familiares, sin
│                                     hombre atractivo, sin físico...)
├── Raras\
│   ├── Errores\                   ← clasificación fallida (JSON inválido)
│   └── Extranas\                  ← es_extraña=si (screenshots, web...)
├── Otros\  (Audio\ Documentos\ Web\ Incompletos\ Ejecutables\ Varios\)
├── Imagenes\    Clasico\ IA\ SinDeterminar\
├── Videos\      Clasico\ IA\ SinDeterminar\
└── Culturismo\  Imagenes\ y Videos\  (Clasico\ IA\ SinDeterminar\)
```

Épocas por fecha de modificación: `< nov-2024` Clasico,
`nov-2024..jun-2025` SinDeterminar, `>= jul-2025` IA.
Los nombres DeviantArt se consideran IA (regla del usuario).

---

## 2. INFRAESTRUCTURA REMOTA (Legion, la GPU)

- **Host**: `legion` / `192.168.1.136` (Windows 11, RTX 5080 Laptop 16 GB).
- **SSH**: `ssh -i C:\Users\David\Documents\id_ed25519 dvdjg@192.168.1.136`
  (si falla el nombre, usar la IP; `-4` fuerza IPv4).
- **Ollama (servidor compartido)**: `http://legion:11434` — v0.32.5.
  REGLA: antes de lanzar instancias, comprobar si ya responde
  (`curl http://legion:11434/api/version`); reutilizar; arrancar con
  `schtasks /run /tn iniciar_servidor` solo si está caído.
- **Modelos en Ollama (Legion)**: `gemma3:12b` (ELEGIDO),
  `qwen2.5vl:7b` (rápido/fallback), `qwen2.5vl:3b`, `qwen3-vl:8b`
  (ROTO: piensa infinito, nunca emite respuesta), `llama3.2-vision`
  (formatos rotos), `gemma3` descartado por censura (veto del usuario —
  REVISADO: con el prompt actual NO censura y es el mejor; el veto era
  sobre pruebas anteriores).
- **Energía**: powercfg standby AC/DC = 0 (nunca suspende) + watchdog
  `keep_awake.ps1` (tarea al inicio de sesión; evita suspensión mientras
  ollama/llama-server/curl corren; si se mata el proceso powershell,
  relanzar `schtasks /run /tn keep_awake`).
- **Wake-on-LAN**: activado (Realtek 2.5GbE, MAC A8-2B-DD-C1-82-8F).
  Si Legion duerme: `python F:\scripts\despertar_legion.py`
  (magic packet + auto-descubrimiento de IP por MAC + verifica SSH).
  Nota: si está en Modern Standby (S0), los magic packets pueden no
  despertarla; un reinicio limpio la cura.
- **Tareas programadas en Legion** (schtasks, al inicio de sesión):
  `ollama_serve`, `llamacpp_serve`, `iniciar_servidor`, `keep_awake`,
  `dl_*` (descargas puntuales, se pueden borrar).
- **llama.cpp** (C:\Users\dvdjg\llama-cpp): probado como alternativa a
  ollama; requiere DLLs CUDA (cudart-llama-bin...zip, ya extraídas).
  ABANDONADO como backend: ollama + gemma3 es lo que funciona.
  Sirve en :8080 si se necesita.

---

## 3. MODELO ELEGIDO Y POR QUÉ

**gemma3:12b** (default en 06/09/10). Evaluado contra qwen2.5vl:7b,
qwen3-vl:8b, llama3.2-vision en 16 imágenes (incluidas temáticas
explícitas):

| Criterio | gemma3:12b | qwen2.5vl:7b |
|---|---|---|
| Distingue competicion/trabajado | ✓ (el aficionado no llega a 80) | ✗ (todo lo llama musculoso) |
| Edad facial (joven) | ✓ (soldado/policía = si) | ✗ oscila 55-85 |
| Contenido explícito | ✓ (glory hole = sexo_explicito) | ✗ (la llama "sensual") |
| Censura | No en 16 pruebas | No |
| Velocidad | ~11 s/img | ~5 s/img |
| Puntuación de la temática del usuario | 85-100 | 55-80 |

qwen3-vl:8b: roto en ollama (todo el output va a `thinking`, la respuesta
final nunca se emite; incluso con think=false).

---

## 4. FASES Y ORDEN (scripts en F:\scripts\)

| # | Script | Qué hace | Reanudable |
|---|--------|----------|------------|
| 1 | `01_inventario.py` | Escaneo → inventario SQLite | sí (INSERT OR IGNORE) |
| 2 | `02_duplicados.py` | Dedup 3 fases; borra exactos | sí (tabla progreso) |
| 3 | `03_metadatos.py` | ffprobe/EXIF (paralelo) — opcional | sí |
| 4 | `04_clasificar.py` | Mueve al árbol (tipo/época/categoría) | sí |
| 5 | `05_informe.py` | Informe de estado | siempre |
| 6 | `06_vision.py` | **Clasificación VLM masiva** (gemma3) | sí (tabla vision) |
| 7 | `07_sacar_raras.py` | Mueve Errores/Extranas/NoInteresante | sí |
| 8 | `08_indice.py` | Índice CSV/JSON de toda la biblioteca | siempre |
| 9 | `09_comparativa.py` | Clasifica imágenes sueltas (pruebas) | — |
| 10 | `10_renombrar.py` | Renombra + metadatos EXIF por tandas | sí (renombrado) |
| — | `nuevo.py` | Clasifica solo `Clasificado\Incoming\` | — |
| — | `despertar_legion.py` | WoL + verificación | — |
| — | `common.py` | Constantes, prompt VLM, puntuación, formato nombre | — |

**Pipeline principal pendiente:**
```
python F:\scripts\06_vision.py --workers 6        # ~20 h, reanudable
python F:\scripts\07_sacar_raras.py
python F:\scripts\08_indice.py
python F:\scripts\10_renombrar.py --minutos 55    # tandas de 1 h
```

---

## 5. PROMPT, PUNTUACIÓN Y REGLAS (ajustables en common.py)

- **Prompt**: `common.construir_prompt_vision(nombre_archivo)` — pide JSON
  factual: resumen, descripcion (2-4 frases), categorias (taxonomía
  `TAXONOMIA_VISION`), atributos, desnudez, tipo, escenario,
  genero_aprox, es_furry, es_culturismo, es_extraña, sexualizacion
  (ninguna|sensual|erotismo|insinuacion|genitales|sexo_explicito),
  **fisico** (ninguno|atletico|trabajado|musculoso|competicion — con
  anclas: competicion = masa extrema/ciclado, trabajado = aficionado de
  gimnasio), vello_corporal, guapo (estricto), joven (SOLO facial),
  viril, fisico_visible, es_familiar, menores, hay_hombre_atractivo
  (solo "hay un hombre adulto"), personas, estilo, posible,
  fantasia_verosimil, defectos, organo_imposible, violencia,
  admiradores, nombre_sugerido (solo si el nombre actual no describe).

- **Puntuación**: `common.calcular_puntuacion(data)` — determinista:
  - 0 si: menores, familiar/social, sin hombre, sin personas, no masculino.
  - Coherencia: si la descripción menciona un hombre y el gate dice "no",
    se corrige a "si".
  - +40 competicion / +25 musculoso / +10 trabajado / +5 atletico;
    +15 guapo, +10 joven, +15 viril, +5 sin vello, +5 erótico,
    +5 admiradores.
  - Techos: trabajado → máx 69; atletico/ninguno → 39 (59 si viril).
  - <40 → `NoInteresante\` (07). 40-79 sin viril = **dudoso** (se listan
    en `salida/para_revisar.csv`, no se renombran por defecto).

- **Formato de nombre final**: `common.nombre_final()` →
  `<slug_ia> (<kw1>;<kw2>;<kw3>;p<PUNT>;<sexualizacion>).ext`
  (slug = nombre_sugerido o resumen; sin acentos, 60 chars).

- **Metadatos**: JPEG → EXIF sin pérdida (piexif: XPKeywords,
  ImageDescription, UserComment JSON con todo + nombre original);
  PNG → tEXt; otros → solo renombrado.

---


### 5b. ÁRBOL TEMÁTICO (fase 11)

Las imágenes clasificadas se reorganizan de `Imagenes\<Epoca>` a
`Imagenes\<Tema>\<Epoca>` según las categorías del VLM (prioridad):
**Bondage > Furry > Fantasia > Erotico > Culturismo > Fitness > Otro**
(mapas editables en `common.TEMA_CATEGORIAS`). El culturismo conserva su
árbol propio. Tras cada batch, `11_temas.py --descubrir` genera
`salida/temas_descubiertos.csv` (frecuencia de categorías) para ajustar
o añadir temas nuevos.
## 6. REANUDACIÓN RÁPIDA

1. ¿Legion despierta? `python F:\scripts\despertar_legion.py` si no.
2. ¿Ollama arriba? `curl http://legion:11434/api/version`;
   si no, `ssh ... "schtasks /run /tn iniciar_servidor"`.
3. ¿Dónde estamos? `python F:\scripts\05_informe.py`.
4. Relanzar el script que se cortó — todos continúan donde iban:
   - 06: salta lo ya clasificado (tabla vision).
   - 10: salta lo ya renombrado (inventario.renombrado), orden mtime asc.
5. Nunca lanzar dos fases a la vez. Esperar a que termine una.

---

## 7. CONTENIDO NUEVO (bandeja de entrada)

```
1. Copiar a F:\Clasificado\Incoming\
2. python F:\scripts\nuevo.py   (= inventario + dedup + clasificar Incoming)
```

---

## 8. SEGURIDAD

- `F:\David\` intocable. GUION.md/README.md marcados 'fijo' en la BD.
- Duplicados borrados registrados en `salida/duplicados_borrados.csv`.
- Sospechosos (casi-duplicados) nunca se borran:
  `salida/sospechosos.csv`.
- `--dry-run` disponible en 02/04/07/10.
- Los archivos con nombres con surrogates UTF-16 se codifican lossless en
  la BD (common.ruta_a_db / ruta_de_db) — no romper esas funciones.
- GPU degradada tras mucha carga o suspensión → reiniciar Legion.

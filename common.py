# -*- coding: utf-8 -*-
r"""
common.py — Utilidades compartidas para la clasificación de F:\
================================================================

Este módulo centraliza TODAS las constantes y funciones comunes a los
scripts de clasificación (01..05, nuevo.py). Si quieres afinar el
comportamiento (palabras clave de culturismo, marcadores de IA, fechas
frontera, extensiones...), edita solo este archivo y vuelve a ejecutar
los scripts: son todos reanudables (idempotentes).

ARQUITECTURA
------------
  F:\scripts\01_inventario.py   -> escaneo -> SQLite (inventario)
  F:\scripts\02_duplicados.py   -> dedup en 3 fases (rápido)
  F:\scripts\03_metadatos.py    -> ffprobe/EXIF (paralelo, reanudable)
  F:\scripts\04_clasificar.py   -> mueve archivos al árbol nuevo
  F:\scripts\05_informe.py      -> informe de estado
  F:\scripts\nuevo.py           -> clasifica solo F:\Clasificado\Incoming\
  F:\scripts\estado\estado.db   -> base de datos de estado (checkpoint)
  F:\scripts\salida\            -> informes CSV/TXT

REANUDACIÓN
-----------
Cada script guarda su progreso en estado.db (tabla progreso). Si el
proceso se corta a mitad, basta con volver a lanzar el mismo comando:
continúa donde lo dejó. Consulta F:\GUION.md para el orden y los modos.
"""
import os
import re
import sys
import json
import sqlite3
import hashlib
import logging
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. RUTAS Y ÁMBITO
# ---------------------------------------------------------------------------

F = Path('F:/')
SCRIPTS = F / 'scripts'
ESTADO_DIR = SCRIPTS / 'estado'
SALIDA_DIR = SCRIPTS / 'salida'
DB_PATH = ESTADO_DIR / 'estado.db'
CLASIFICADO = F / 'Clasificado'
INCOMING = F / 'Incoming'

# Carpetas que JAMÁS se tocan (no se escanean, no se mueven, no se borran).
EXCLUIDOS = {
    'david',            # carpeta personal del usuario (intocable)
    'clasificado',      # árbol destino (se excluye del escaneo)
    'incoming',         # bandeja de entrada (la procesa nuevo.py)
    'scripts',          # nuestros scripts y estado
    'system volume information',
    '$recycle.bin',
    '.trash-1000',
    '.wwebjs_cache',
    'msdownld.tmp',     # temporales de descarga del navegador
}

# ---------------------------------------------------------------------------
# 2. FECHAS FRONTERA IA / CLÁSICO
# ---------------------------------------------------------------------------
# Explicación (según el usuario):
#   - Hasta finales de 2024  -> contenido clásico (descargas reales)
#   - Nov 2024 .. Jun 2025  -> zona gris: cada vez más IA (se decide por
#                              metadatos si es posible, si no queda
#                              clasificado como SinDeterminar)
#   - Desde Jul 2025        -> prácticamente todo es generado por IA
# La fecha que se mira es la de modificación del archivo (fecha de
# descarga), porque el contenido clásico re-descargado recientemente se
# detecta después con metadatos (EXIF/encoder) en la fase 03.
FRONTERA_IA = datetime.datetime(2024, 11, 1)    # empieza la IA
IA_FIJO_DESDE = datetime.datetime(2025, 7, 1)   # desde aquí: todo es IA

# ---------------------------------------------------------------------------
# 3. TIPOS DE ARCHIVO
# ---------------------------------------------------------------------------

EXT_IMAGEN = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.jfif', '.avif'}
EXT_VIDEO = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mpg',
             '.mpeg', '.vob', '.rmvb', '.3gp', '.m4v', '.ts', '.m2ts', '.mts'}
EXT_AUDIO = {'.m4a', '.mp3', '.aac', '.flac', '.wav', '.ogg', '.opus', '.wma', '.m4b'}
EXT_INCOMPLETO = {'.part', '.descargar', '.crdownload', '.download', '.tmp',
                  '.temp', '.ytdl', '.aria2'}
EXT_DOC = {'.pdf', '.doc', '.docx', '.txt', '.htm', '.html', '.js', '.css',
           '.xls', '.xlsx', '.epub', '.cbr', '.cbz', '.zip', '.rar', '.7z',
           '.exe', '.msi', '.dmg', '.json', '.xml', '.nfo', '.srt', '.vtt',
           '.md'}

# Archivos de la RAÍZ de F:\ que nunca se mueven (documentación del
# proyecto: GUION.md, README.md, scripts auxiliares...).
PROTEGIDOS_ROOT = {'.md', '.py', '.bat', '.cmd', '.db', '.pyc'}

# ---------------------------------------------------------------------------
# 4. CULTURISMO: palabras clave (AJUSTABLES)
# ---------------------------------------------------------------------------
# Un archivo se considera CULTURISMO si:
#   A) alguna carpeta de su ruta contiene una palabra de CULTURISMO_FOLDERS, o
#   B) su nombre contiene una palabra de CULTURISMO_TERMS,
# y NO contiene ningún marcador de la lista ADULT_MARKERS (ni en carpeta ni
# en nombre), que lo delata como contenido erótico.
CULTURISMO_FOLDERS = {
    'bb', 'bb1', 'bb2', 'bb aaa', 'bodybuilder', 'bodybuilding', 'fitness',
    'muscle', 'gym', 'physique', 'anabolic', 'anabolicos', 'esteroides',
    'steroids', 'aesthetics', 'beast', 'pump', 'pose', 'posing', 'lifting',
    'strongman', 'powerlifting', 'workout', 'titans', 'olympia', 'ifbb',
    'npc', 'grabado', 'mrolympia', 'bodyxtreme', 'pumpingmuscle', 'flexing',
    'body', 'culturismo', 'bbv',
}
CULTURISMO_TERMS = [
    'bodybuilding', 'bodybuilder', 'physique', 'posing', 'pose', 'flex',
    'flexing', 'ifbb', 'npc ', 'olympia', 'contest', 'championship',
    'backstage', 'pump room', 'workout', 'gym', 'bodyxtreme', 'pumpingmuscle',
    'guest posing', 'seminar', 'bodybuilder muscle', 'muscular', 'shredded',
    'ripped', 'strongman', 'powerlifting', 'deadlift', 'squat', 'bench press',
    'aesthetics', 'culturismo',
]
# Marcadores de contenido erótico (nombre de archivo O carpeta).
ADULT_MARKERS = [
    'pornhub', 'xvideos', 'xhamster', 'spankbang', 'youporn', 'redtube',
    'tube8', 'xnxx', 'brazzers', 'drtuber', 'myvidster', 'porn', 'sex',
    'hentai', 'studiofow', 'fow-', 'cock', 'cum', 'cumshot', 'jerk', 'jerkoff',
    'dick', 'suck', 'fuck', 'fucking', 'blowjob', 'nude', 'naked', 'anal',
    'camgirl', 'onlyfans', 'sextape', 'gangbang', 'creampie', 'tits', 'boobs',
    'milf', 'teen', 'twink', 'gay porn', 'muscle worship', 'muscleworship',
    'handjob', 'bukkake', 'threesome', 'orgy', 'striptease', 'erotic',
]
# Banderas de webs de descarga erótica (para no clasificar como culturismo)
PORN_SITE_MARKERS = ['pornhub.com', 'xvideos.com', 'xhamster.com',
                     'spankbang.com', 'youporn.com', 'redtube.com']

# ---------------------------------------------------------------------------
# 5. DETECCIÓN DE IA (metadatos)
# ---------------------------------------------------------------------------
# Firma en EXIF Software / comentarios de imagen (A1111, ComfyUI, NovelAI...)
AI_EXIF_HINTS = [
    'stable diffusion', 'comfyui', 'comfy ui', 'novelai', 'novel ai',
    'automatic1111', 'a1111', 'invokeai', 'fooocus', 'midjourney',
    'dall-e', 'dall e', 'gpt image', 'firefly', 'leonardo ai', 'krea',
    'flux', 'sdxl', 'sd xl', 'sd-xl', 'qwen-image', 'qwen image',
    'tensor.art', 'cutout', 'ideogram', 'playground ai', 'nightcafe',
    'dreamstudio', 'dream studio', 'bing image', 'adobe firefly',
    'photoleap', 'picsart ai', 'canva ai', 'artguru', 'fotor ai',
    'stablediffusion', 'sana', 'hunyuan image', 'gpt-image', 'imagen 3',
]
# Firma en metadatos de vídeo (encoder/software)
AI_VIDEO_HINTS = [
    'comfyui', 'svd', 'stable video', 'stablediffusion', 'animatediff',
    'wan', 'kling', 'hunyuan', 'pixverse', 'runway', 'gen-3', 'gen3',
    'sora', 'veo', 'luma', 'dreamina', 'haiper', 'pika', 'opendream',
    'libsvtav1', 'lavc61', 'vvc', 'h266', 'av1',  # códecs típicos de IA
]
# Señal CLÁSICA fuerte: EXIF de cámara real
CAMARA_MAKES = ['canon', 'nikon', 'sony', 'fujifilm', 'panasonic', 'olympus',
                'leica', 'pentax', 'samsung', 'kodak', 'casio', 'ricoh',
                'huawei', 'xiaomi', 'apple', 'google', 'motorola', 'oppo',
                'oneplus', 'vivo', 'lg', 'htc', 'blackberry', 'nokia']

# ---------------------------------------------------------------------------
# 6. HEURÍSTICA DE NOMBRE PARA IA (cuando no hay metadatos)
# ---------------------------------------------------------------------------
# Patrones típicos de nombres generados por IA (prompts largos, seed, steps).
RE_SEED = re.compile(r'(?:_|-|^)seed[_\-]?\d+', re.I)
RE_STEPS = re.compile(r'(?:_|-|^)steps[_\-]?\d+', re.I)
RE_SD_NUM = re.compile(r'_\d{4,}_\d{2,}_')          # estilo A1111: _seed_steps_
RE_FECHA_NOMBRE = re.compile(r'^\d{4}[-_]\d{2}[-_]\d{2}')  # 2024-01-01 (no IA)
RE_LARGO = re.compile(r'^.{60,}$')                  # nombre muy largo

# ---------------------------------------------------------------------------
# 6b. DEVIANTART = IA (regla del usuario)
# ---------------------------------------------------------------------------
# El usuario considera que TODO lo descargado de DeviantArt es IA. Señales
# en el nombre (nomenclatura de descarga de DA):
#   *  "00001_1154460837_perfectdeliberate_v20_512x512_by_autor_dfx75vy-375w-2x.jpg"
#   *  "*_by_<autor>_<id>..."  (lo más distintivo)
#   *  sufijos de miniatura:  -375w, -414w, -2x, -pre, -92s
RE_DA_BY = re.compile(r'_by_[a-z0-9]+', re.I)
RE_DA_NUM = re.compile(r'^\d{4,}_\d+_')
RE_DA_SUF = re.compile(r'-\d{2,4}w(-\d+x)?\.(jpg|jpeg|png|webp)$', re.I)
RE_DA_PRE = re.compile(r'-pre\.(jpg|jpeg|png|webp)$', re.I)


def es_deviantart(nombre):
    """True si el nombre tiene patrones de descarga de DeviantArt."""
    n = nombre
    if RE_DA_BY.search(n):
        return True
    if RE_DA_NUM.match(n) and RE_DA_SUF.search(n):
        return True
    if RE_DA_PRE.search(n):
        return True
    return False


# ---------------------------------------------------------------------------
# 6b2. NOMBRES "RAROS" (sin sentido) — candidatos a renombrado por IA
# ---------------------------------------------------------------------------
RE_NUM_SOLO = re.compile(r'^\d+$')
RE_HASH = re.compile(r'^[a-f0-9]{16,}$', re.I)
RE_TS = re.compile(r'^\d{8}_\d{3,}')          # 20240507_123456...
RE_TELEFONO = re.compile(r'^\d{9,}$')


def nombre_raro(base):
    """True si el nombre (sin extensión) no aporta información y conviene
    que la IA proponga uno nuevo: hashes, timestamps, nombres de descarga
    automática (DeviantArt), solo números, o tokens ilegibles."""
    if not base:
        return True
    if es_deviantart(base + '.jpg'):
        return True
    if (RE_NUM_SOLO.match(base) or RE_HASH.match(base)
            or RE_TS.match(base) or RE_TELEFONO.match(base)):
        return True
    digitos = sum(c.isdigit() for c in base)
    if len(base) >= 8 and digitos >= len(base) * 0.5:
        return True
    # token largo sin separadores (nombre corrupto o codificado)
    if len(base) > 30 and not re.search(r'[\s_-]', base):
        return True
    # códigos de serie (MD-AB-IX-5, BB-001, M05...)
    if re.match(r'^[a-z0-9]{1,4}[-_][a-z0-9]{1,4}[-_][a-z0-9-]*\d', base, re.I) \
            or re.match(r'^[a-z]\d{2,3}$', base, re.I):
        return True
    return False


# ---------------------------------------------------------------------------
# 6c. CODIFICACIÓN DE RUTAS PARA SQLITE
# ---------------------------------------------------------------------------
# Windows puede tener nombres de archivo con surrogates sueltos (UTF-16
# inválido, p. ej. descargas con emojis corruptos). SQLite exige UTF-8
# válido, así que guardamos la ruta en una codificación 1:1 (latin-1 sobre
# los bytes surrogateescaped) y la recuperamos al operar con el disco.
def ruta_a_db(s):
    """Ruta real -> texto almacenable (lossless). Usa surrogatepass para
    soportar high/low surrogates sueltos (UTF-16 rota) y latin-1 para
    que SQLite acepte el resultado como UTF-8 válido."""
    return s.encode('utf-8', 'surrogatepass').decode('latin-1')


def ruta_de_db(s):
    """Texto de la BD -> ruta real."""
    return s.encode('latin-1').decode('utf-8', 'surrogatepass')


# ---------------------------------------------------------------------------
# 7. BASE DE DATOS Y LOG
# ---------------------------------------------------------------------------

LOG = logging.getLogger('clasifica')
LOG.setLevel(logging.INFO)
if not LOG.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(message)s',
                                      '%H:%M:%S'))
    LOG.addHandler(_h)


def conectar():
    """Devuelve una conexión SQLite (row_factory incluida)."""
    ESTADO_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    crear_esquema(con)
    return con


def crear_esquema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS inventario(
        ruta TEXT PRIMARY KEY,
        tamano INTEGER, ext TEXT, mtime REAL,
        raiz TEXT, estado TEXT DEFAULT 'pendiente',
        hash_parcial TEXT, hash_full TEXT,
        meta TEXT, destino TEXT, renombrado TEXT
    );
    CREATE TABLE IF NOT EXISTS metadatos(
        ruta TEXT PRIMARY KEY,
        tipo TEXT, duracion REAL, ancho INTEGER, alto INTEGER,
        encoder TEXT, software TEXT, make TEXT, model TEXT,
        fecha_original TEXT, senal_ia INTEGER DEFAULT 0,
        senal_clasica INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS movidos(
        ruta_orig TEXT PRIMARY KEY, ruta_dest TEXT, fecha TEXT
    );
    CREATE TABLE IF NOT EXISTS duplicados(
        ruta_guardar TEXT, ruta_borrar TEXT, hash TEXT, metodo TEXT
    );
    CREATE TABLE IF NOT EXISTS sospechosos(
        ruta TEXT, pareja TEXT, motivo TEXT
    );
    CREATE TABLE IF NOT EXISTS vision(
        ruta TEXT PRIMARY KEY,
        modelo TEXT, json TEXT,
        categorias TEXT, atributos TEXT,
        desnudez TEXT, tipo TEXT, es_furry TEXT, es_culturismo TEXT,
        resumen TEXT, descripcion TEXT,
        nombre_original TEXT, nombre_sugerido TEXT,
        es_extrana TEXT, sexualizacion TEXT, preservar_titulo TEXT,
        fisico TEXT, vello_corporal TEXT, guapo TEXT, joven TEXT,
        viril TEXT, fisico_visible TEXT, es_familiar TEXT, menores TEXT,
        hay_hombre_atractivo TEXT, personas INTEGER,
        estilo TEXT, posible TEXT, fantasia_verosimil TEXT, defectos TEXT,
        organo_imposible TEXT, violencia TEXT, admiradores TEXT,
        puntuacion INTEGER
    );
    CREATE TABLE IF NOT EXISTS progreso(
        fase TEXT PRIMARY KEY, valor TEXT, fecha TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_inv_tamano ON inventario(tamano, ext);
    CREATE INDEX IF NOT EXISTS idx_inv_estado ON inventario(estado);
    CREATE INDEX IF NOT EXISTS idx_mov_dest ON movidos(ruta_dest);
    CREATE INDEX IF NOT EXISTS idx_mov_orig ON movidos(ruta_orig);
    ''')
    # migración: columnas añadidas en versiones posteriores
    try:
        con.execute('ALTER TABLE inventario ADD COLUMN renombrado TEXT')
    except Exception:
        pass
    try:
        con.execute('ALTER TABLE vision ADD COLUMN preservar_titulo TEXT')
    except Exception:
        pass


def marca_progreso(con, fase, valor):
    con.execute(
        'INSERT INTO progreso(fase, valor, fecha) VALUES(?,?,?) '
        'ON CONFLICT(fase) DO UPDATE SET valor=?, fecha=?',
        (fase, valor, datetime.datetime.now().isoformat(), valor,
         datetime.datetime.now().isoformat()))


def ya_procesado(con, fase):
    row = con.execute('SELECT 1 FROM progreso WHERE fase=?', (fase,)).fetchone()
    return row is not None


def leer_progreso(con, fase):
    row = con.execute('SELECT valor FROM progreso WHERE fase=?', (fase,)).fetchone()
    return row['valor'] if row else None


def es_raiz_excluida(nombre_carpeta):
    return nombre_carpeta.casefold() in EXCLUIDOS


def normaliza(nombre):
    """Normaliza un nombre para comparar 'casi-duplicados' (quita (1), copy...)."""
    n = re.sub(r'\s*\(\d+\)', '', nombre)
    n = re.sub(r'(?i)\s*(copy|copia|duplicado|duplicate)\s*(\d*)\s*$', '', n)
    n = re.sub(r'[_\-. ]+', '', n)
    return n.casefold()


# ---------------------------------------------------------------------------
# 8. HASHES
# ---------------------------------------------------------------------------

def hash_parcial(ruta, head=64 * 1024, tail=64 * 1024, chunks=64 * 1024):
    """Hash parcial rápido: cabecera + 3 muestras del medio + cola.

    Para filtrar candidatos leyendo solo ~320 KB en vez del archivo
    completo. Dos archivos del MISMO tamaño con la misma firma son, en
    la práctica, el mismo archivo (dos contenidos distintos que
    coincidieran en 5 muestras del mismo tamaño serían indistinguibles
    con cualquier método, salvo hash completo).
    Devuelve 'h|m1|m2|m3|t' (sha1 hex de cada muestra)."""
    try:
        tam = os.path.getsize(ruta)
    except OSError as e:
        LOG.warning('No se pudo leer %s: %s', ruta, e)
        return None
    if tam <= head + tail + 3 * 64 * 1024:
        return 'FULL|' + hash_full(ruta)
    muestras = []
    posiciones = [0, tam * 1 // 4, tam // 2, tam * 3 // 4, tam - tail]
    for i, pos in enumerate(posiciones):
        long = head if i == 0 else (tail if i == 4 else 64 * 1024)
        h = hashlib.sha1()
        try:
            with open(ruta, 'rb') as f:
                f.seek(pos)
                leido = 0
                while leido < long:
                    b = f.read(min(chunks, long - leido))
                    if not b:
                        break
                    h.update(b)
                    leido += len(b)
        except OSError as e:
            LOG.warning('No se pudo leer %s: %s', ruta, e)
            return None
        muestras.append(h.hexdigest())
    return '|'.join(muestras)


def hash_head(ruta, head=64 * 1024, chunks=64 * 1024):
    """Solo cabecera (primer nivel de filtrado, muy barato)."""
    h = hashlib.sha1()
    try:
        with open(ruta, 'rb') as f:
            leido = 0
            while leido < head:
                b = f.read(min(chunks, head - leido))
                if not b:
                    break
                h.update(b)
                leido += len(b)
    except OSError as e:
        LOG.warning('No se pudo leer %s: %s', ruta, e)
        return None
    return h.hexdigest()


def hash_full(ruta, chunks=1024 * 1024):
    """SHA-1 completo del archivo."""
    h = hashlib.sha1()
    try:
        with open(ruta, 'rb') as f:
            for b in iter(lambda: f.read(chunks), b''):
                h.update(b)
    except OSError as e:
        LOG.warning('No se pudo leer %s: %s', ruta, e)
        return None
    return h.hexdigest()


def ext_of(nombre):
    return os.path.splitext(nombre)[1].casefold()


def reconciliar(con, lote=20000):
    """Marca como 'faltante' las filas cuyo archivo ya no existe en disco.

    (Pueden desaparecer por limpieza manual, antivirus, descargas a
    medias...). Se ejecuta al inicio de las fases 2/3/4 para que las
    filas fantasma no den warnings ni se cuenten como duplicados."""
    rows = con.execute(
        'SELECT ruta FROM inventario WHERE estado=?', ('pendiente',)).fetchall()
    n_faltan = 0
    pend = []
    for i, r in enumerate(rows):
        ruta = ruta_de_db(r['ruta'])
        pend.append(ruta)
        if len(pend) >= lote or i == len(rows) - 1:
            faltan = [(ruta_a_db(p),) for p in pend
                      if not os.path.exists(p)]
            if faltan:
                con.executemany(
                    'UPDATE inventario SET estado=? WHERE ruta=?',
                    [('faltante', p[0]) for p in faltan])
                n_faltan += len(faltan)
            con.commit()
            pend = []
    if n_faltan:
        LOG.info('Reconciliación: %d archivos marcados como faltantes '
                 '(ya no existen en disco)', n_faltan)
    return n_faltan


def tipo_de(ext):
    """Devuelve 'imagen' | 'video' | 'audio' | 'incompleto' | 'otro'."""
    if ext in EXT_IMAGEN:
        return 'imagen'
    if ext in EXT_VIDEO:
        return 'video'
    if ext in EXT_AUDIO:
        return 'audio'
    if ext in EXT_INCOMPLETO:
        return 'incompleto'
    return 'otro'


# ---------------------------------------------------------------------------
# 9. CULTURISMO
# ---------------------------------------------------------------------------

def contiene_marcador(texto, marcadores):
    t = texto.casefold()
    return any(m.casefold() in t for m in marcadores)


def es_culturismo(ruta_rel, nombre):
    """Decide si un archivo es de culturismo (heurística, ver doc del módulo).

    ruta_rel: ruta con carpetas (solo para leer los nombres de carpeta).
    """
    partes = [p for p in Path(ruta_rel).parts[:-1]]  # carpetas, sin el archivo
    hay_hint_carpeta = any(contiene_marcador(p, CULTURISMO_FOLDERS) for p in partes)
    hay_hint_nombre = contiene_marcador(nombre, CULTURISMO_TERMS)
    es_adulto = (contiene_marcador(nombre, ADULT_MARKERS) or
                 any(contiene_marcador(p, ADULT_MARKERS) for p in partes))
    if es_adulto:
        return False
    return hay_hint_carpeta or hay_hint_nombre


# ---------------------------------------------------------------------------
# 10. DETECCIÓN DE IA POR METADATOS
# ---------------------------------------------------------------------------

def metadatos_a_senales(meta):
    """Convierte una fila de metadatos en (senal_ia, senal_clasica)."""
    if not meta:
        return 0, 0
    texto = ' '.join(str(x or '') for x in
                     [meta.get('software'), meta.get('encoder'),
                      meta.get('make'), meta.get('model')]).casefold()
    ia = 1 if contiene_marcador(texto, AI_EXIF_HINTS + AI_VIDEO_HINTS) else 0
    clasica = 0
    make = (meta.get('make') or '').casefold()
    if make and any(m in make for m in CAMARA_MAKES):
        clasica = 1
    fo = meta.get('fecha_original') or ''
    if re.match(r'^\d{4}', fo):
        try:
            anio = int(fo[:4])
            if anio <= 2021:
                clasica = 1
        except ValueError:
            pass
    return ia, clasica


def heuristica_nombre_ia(nombre):
    """Pistas de IA por el nombre (sin metadatos). Devuelve 0/1 (débil/fuerte)."""
    n = nombre
    if RE_FECHA_NOMBRE.match(n):
        return 0
    pistas = 0
    if RE_SEED.search(n) or RE_STEPS.search(n) or RE_SD_NUM.search(n):
        pistas += 2
    if RE_LARGO.match(n) and n.count('_') >= 5:
        pistas += 1
    if contiene_marcador(n, ['comfy', 'flux', 'sdxl', 'dalle', 'midjourney',
                             'firefly', 'veo', 'sora', 'wan', 'kling',
                             'hunyuan', 'pixverse', 'luma', 'stable diffusion',
                             'novelai', 'aicover', 'ai cover', 'aigenerated',
                             'generated']):
        pistas += 2
    return min(pistas, 2)


def decidir_epoca(mtime, meta, nombre):
    """Decide 'Clasico' | 'IA' | 'SinDeterminar' combinando:
    1) DeviantArt (regla del usuario: todo DA = IA)
    2) metadatos (señales fuertes) -> 3) fecha de modificación -> 4) nombre.
    Devuelve (epoca, razon)."""
    if es_deviantart(nombre):
        return 'IA', 'DeviantArt (regla del usuario)'
    ia_s, cl_s = metadatos_a_senales(meta)
    if ia_s and cl_s:
        return 'SinDeterminar', 'metadatos contradictorios'
    if ia_s:
        return 'IA', 'metadatos IA'
    if cl_s:
        return 'Clasico', 'metadatos clásico (cámara/fecha original)'

    fecha = datetime.datetime.fromtimestamp(mtime)
    if fecha >= IA_FIJO_DESDE:
        epoca, razon = 'IA', 'fecha >= ' + IA_FIJO_DESDE.strftime('%Y-%m-%d')
    elif fecha >= FRONTERA_IA:
        epoca, razon = 'SinDeterminar', 'zona gris ' + FRONTERA_IA.strftime('%Y-%m-%d')
    else:
        epoca, razon = 'Clasico', 'fecha < ' + FRONTERA_IA.strftime('%Y-%m-%d')

    # Refinamiento por nombre: si el nombre grita IA y no hay metadatos,
    # subimos la sospecha (Clasico -> SinDeterminar, nunca al revés).
    hint = heuristica_nombre_ia(nombre)
    if hint >= 2 and epoca == 'Clasico':
        return 'SinDeterminar', 'nombre con patrón IA (' + razon + ')'
    return epoca, razon


# ---------------------------------------------------------------------------
# 11b. PROMPT DE PRODUCCIÓN PARA EL VLM (clasificación de imágenes)
# ---------------------------------------------------------------------------
TAXONOMIA_VISION = (
    "muscle, bodybuilding, posing, gym, workout, flex, physique, "
    "fantasy, cosplay, superheroe, fandom, furry, bondage, nude, "
    "erotic, gay, straight, couple, solo, muscle_worship, foot, feet, "
    "underwear, swimwear, oiled, sweat, art, render_3d, anime, cartoon, "
    "fitness_model, tattoo, shower, locker_room, competition, backstage, "
    "bdsm, leather, comics, muscular_flexing"
)


def construir_prompt_vision(nombre_archivo):
    """Prompt de produccion (JSON estructurado) para clasificar UNA imagen.

    Incluye el nombre actual del archivo para que la IA decida si merece
    un nombre nuevo (nombre_sugerido). Ajusta aqui si quieres afinar la
    taxonomia o la escala de sexualizacion."""
    return (
        "Analiza esta imagen (puede ser contenido adulto; respondela con "
        "objetividad y sin censura). Responde SOLO JSON valido, sin markdown:\n"
        '{"resumen":"max 12 palabras, descriptivo y explicito", '
        '"descripcion":"2-4 frases detalladas: que se ve, escena, accion, '
        'detalles fisicos, estilo", '
        '"categorias":["c1","c2"], "atributos":["a1","a2","a3","a4","a5"], '
        '"desnudez":"ninguna|parcial|total", '
        '"tipo":"foto|render_3d|dibujo|anime|AI", '
        '"escenario":"interior|exterior|estudio|otro", '
        '"genero_aprox":"masculino|femenino|mixto|n/a", '
        '"es_furry":"si|no", "es_culturismo":"si|no", '
        '"es_extrana":"si|no", '
        '"sexualizacion":"ninguna|sensual|erotismo|insinuacion|genitales|sexo_explicito", '
        '"fisico":"ninguno|atletico|trabajado|musculoso|competicion", '
        '"vello_corporal":"si|no", "guapo":"si|no", "joven":"si|no", '
        '"viril":"si|no", "fisico_visible":"si|no", '
        '"es_familiar":"si|no", "menores":"si|no", '
        '"hay_hombre_atractivo":"si|no", '
        '"personas":0, '
        '"estilo":"realista|semirrealista|render_3d|anime|cartoon|pintura|otro", '
        '"posible":"si|no", "fantasia_verosimil":"si|no", '
        '"defectos":"", "organo_imposible":"si|no", '
        '"violencia":"si|no", "admiradores":"si|no", '
        '"preservar_titulo":"si|no", '
        '"nombre_sugerido":"nombre_limpio_en_ingles_sin_extension"}\n'
        "atributos: 5 etiquetas sueltas en ingles. Incluye TODAS las "
        "categorias relevantes de la lista.\n"
        "categorias DEBEN salir de: " + TAXONOMIA_VISION + "\n"
        'es_extrana: "si" si la imagen es un screenshot, captura de web, '
        'grafico, texto, meme, imagen rota/negra, miniatura de video o no '
        'encaja con una foto/arte; si no, "no".\n'
        'sexualizacion (escala, elige el grado exacto):\n'
        '  ninguna       -> figura/fitness sin carga sexual (culturista en pose) \n'
        '  sensual       -> atractivo/sensual pero vestido, sin intencion sexual clara \n'
        '  erotismo      -> erotismo suave: ropa interior, semidesnudo sugerente \n'
        '  insinuacion   -> pose insinuante con intencion sexual evidente, sin mostrar \n'
        '  genitales     -> desnudez con genitales visibles, sin acto explicito \n'
        '  sexo_explicito-> actos sexuales explicitos (oral, penetracion, masturbacion...) \n'
        'DEFINICIONES ESTRICTAS (se conservador, responde "no" ante la '
        'duda):\n'
        '  guapo: "si" SOLO si la cara es claramente atractiva (rasgos '
        'marcados, mandibula definida, simetria); no por defecto.\n'
        '  joven: "si" SOLO según la CARA (rasgos faciales, piel, '
        'estructura): apariencia facial de 18-30 años. IGNORA por completo '
        'el cuerpo, la musculatura, la vestimenta y el contexto: un '
        'culturista gigante puede tener cara de 25, un policía puede tener '
        'cara de 20, un soldado puede tener cara de adolescente. Si la '
        'piel es tersa y sin arrugas y los rasgos son juveniles -> "si", '
        'aunque el cuerpo sea enorme o lleve uniforme. Si la cara muestra '
        'signos de edad (arrugas, barba madura, piel madura) -> "no".\n'
        '  fisico (escala de desarrollo muscular; el nivel COMPETICION es '
        'el maximo):\n'
        '    ninguno     -> no se aprecia fisico trabajado\n'
        '    atletico    -> en forma, poca grasa, deportista ocasional, '
        'sin musculo desarrollado\n'
        '    trabajado   -> chico que va al gimnasio: tonificado con algo '
        'de musculo, pero SIN volumen ni definicion de competicion (el '
        'aficionado normal)\n'
        '    musculoso   -> musculos claramente desarrollados y '
        'voluminosos (culturista fuerte o muy entrenado)\n'
        '    competicion -> nivel competicion/ciclado: masa muscular '
        'extrema, definicion total (estriaciones, abdominales marcados), '
        'grasa corporal minima, aspecto de culturista profesional o '
        'esteroideo. Es el tipo de fisico que mas valora el coleccionista '
        'y el unico que merece la maxima puntuacion.\n'
        '  fisico_visible: "si" SOLO si el cuerpo se ve sin ropa holgada '
        '(torso desnudo, camiseta ajustada, ropa interior) y se aprecia '
        'claramente el fisico; con ropa normal u holgada -> "no".\n'
        '  viril: "si" SOLO si transmite masculinidad/vigor (contexto '
        'militar, policia, deporte, pose de poder); no por defecto.\n'
        '  es_familiar: "si" si parece foto personal/casual (selfies, '
        'reuniones, gente normal sonriendo a camara, cumpleanos, comidas, '
        'paseos) aunque los hombres sean guapos.\n'
        'PERFIL DEL COLECCIONISTA: le interesan hombres jovenes y guapos '
        '("cachas") con el fisico trabajado visible: mucho musculo, poca '
        'grasa, definicion, idealmente sin vello corporal, en contextos de '
        'culturismo, deporte, militar/policia viril o erotico. NO le '
        'interesan fotos familiares, gente mayor, paisajes, objetos u '
        'otros temas.\n'
        'menores: "si" si hay ninos o menores de edad en la imagen.\n'
        'hay_hombre_atractivo: "si" si hay al menos un hombre adulto '
        'presente en la imagen (aunque no sea guapo; el atractivo se valora '
        'en el campo guapo). "no" SOLO si no hay ningún hombre adulto '
        '(comida, objetos, paisajes, animales, solo mujeres, solo '
        'niños).\n'
        'personas: numero de personas visibles en la imagen (0 si no hay '
        'ninguna: objetos, comida, paisajes...).\n'
        'estilo: tecnica de la imagen (foto real, semirrealista, render 3D, '
        'anime, cartoon, pintura, otro).\n'
        'posible: "si" si la escena es fisicamente posible en la realidad; '
        '"no" si es fantasia/imposible (anatomia sobrenatural, gigantes, '
        'magia, criaturas).\n'
        'fantasia_verosimil: "si" si siendo fantasia, es creible/plausible; '
        '"no" si es absurda.\n'
        'defectos: lista corta separada por comas de defectos visibles '
        '(manos deformes, ojos raros, dedos extra, artefactos de IA, '
        'anatomia rara, calidad baja...); "" si ninguno.\n'
        'organo_imposible: "si" si hay organos/miembros anatomicamente '
        'imposibles en un humano (pene desproporcionado, extremidades '
        'extra, musculos irreales...).\n'
        'violencia: "si" si hay violencia, dano o imposicion de voluntad '
        'sin consentimiento aparente.\n'
        'admiradores: "si" si la escena incluye admiradores/fans, '
        'muscle worship, publico admirando al sujeto (colas de fans, '
        'personas tocando/admirando el musculo...).\n'
        'preservar_titulo: el archivo puede contener un titulo interesante '
        'entre el ruido (artista, webs, sufijos -fullview/-pre/-375w, '
        'numeros). preservar_titulo: "si" si ese titulo limpio describe '
        'la imagen (p. ej. "mighty_steelworkers", "sweet_sweat"); "no" si '
         'no queda ningun titulo con sentido.\n'
        f'El nombre ACTUAL del archivo es: "{nombre_archivo}". '
        'Si ese nombre NO describe el contenido (hashes, numeros, '
        'codigos), propone uno descriptivo en nombre_sugerido (solo '
        'minusculas, guiones bajos, sin espacios ni simbolos, max 40 '
        'caracteres). Si ya es descriptivo, devuelve "".'
    )


def calcular_puntuacion(data):
    """Puntuación de interés para el coleccionista según los hechos."""
    import re as _re
    if not isinstance(data, dict):
        return 0, 'sin datos'
    # Regla de coherencia: si la propia descripción menciona un hombre y el
    # gate dice "no", se contradice -> confiar en la descripción.
    if data.get('hay_hombre_atractivo') == 'no':
        texto = ' '.join(str(data.get(k) or '') for k in
                         ('resumen', 'descripcion'))
        if _re.search(r'hombre|culturist|bodybuild|muscul|militar|polic|'
                      r'soldad|marine|soldier', texto, _re.I):
            data['hay_hombre_atractivo'] = 'si'
    # Reglas duras (puntuación 0)
    if data.get('menores') == 'si':
        return 0, 'menores de edad'
    if data.get('es_familiar') == 'si':
        return 0, 'foto familiar/social'
    if data.get('hay_hombre_atractivo') == 'no':
        return 0, 'sin hombre atractivo protagonista'
    try:
        if int(data.get('personas', 1) or 1) == 0:
            return 0, 'sin personas (objeto/paisaje/comida)'
    except (ValueError, TypeError):
        pass
    if data.get('genero_aprox') not in ('masculino', 'mixto', None):
        return 0, 'no protagonista masculino'

    score = 10  # hay un hombre protagonista
    fisico = data.get('fisico')
    visible = data.get('fisico_visible') == 'si'
    if visible:
        if fisico == 'competicion':
            score += 40
        elif fisico == 'musculoso':
            score += 25
        elif fisico == 'trabajado':
            score += 10
        elif fisico == 'atletico':
            score += 5
    if data.get('guapo') == 'si':
        score += 15
    if data.get('joven') == 'si':
        score += 10
    if data.get('viril') == 'si':
        score += 15  # contexto militar/policía/deporte: alto valor
    if data.get('vello_corporal') == 'no':
        score += 5
    if data.get('sexualizacion') in ('erotismo', 'insinuacion',
                                     'genitales', 'sexo_explicito'):
        score += 5
    if data.get('admiradores') == 'si':
        score += 5  # muscle worship / escenas con fans
    if fisico == 'trabajado':
        score = min(score, 69)  # aficionado de gimnasio: nunca 80+
    elif fisico in ('atletico', 'ninguno'):
        if data.get('viril') == 'si':
            score = min(score, 59)
        else:
            score = min(score, 39)
    elif not visible:
        score = min(score, 59 if data.get('viril') == 'si' else 39)
    score = min(score, 100)
    return score, ('' if score >= 40 else 'poco físico visible o marginal')


# ---------------------------------------------------------------------------
# 11d. FORMATO DE NOMBRE FINAL (renombrado)
# ---------------------------------------------------------------------------
# <base> (<kw1>;<kw2>...;p<PUNTUACION>;<sexualizacion>).<ext>
# base = nombre_sugerido por la IA si el original es "raro"; si no, el
# original (saneado). Todo en minúsculas, sin símbolos raros.
def _slug(texto, maxlen=60):
    """Texto -> slug seguro: minúsculas, sin acentos, solo [a-z0-9_]. """
    import re as _re
    import unicodedata as _ud
    t = _ud.normalize('NFKD', texto or '')
    t = ''.join(c for c in t if not _ud.combining(c))  # quita acentos
    t = _re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')
    return t[:maxlen] or 'imagen'


# Ruido de nombres de descarga (DeviantArt y similares) para extraer el
# título real que el artista puso a la obra.
RE_RUIDO_NOMBRE = re.compile(
    r'(_by_[a-z0-9_]+|___+|_ai_art|ai art|_ai_generated|_generated|'
    r'[-_]?\d{2,4}w(?:[-_]?\d+x)?|[-_]?(?:pre|fullview|2x|92s)\b|'
    r'[-_]\d{6,}|^\d{4,}_|^\d+_|_dfx\w+|_di[a-z0-9]+|_dg[a-z0-9]+|'
    r'_dh[a-z0-9]+|_dk[a-z0-9]+)', re.I)
RE_SOLO_NUM = re.compile(r'^[\d_\-]+$')


def limpiar_titulo(nombre):
    """Extrae el título legible del nombre del archivo (sin extensión),
    quitando el ruido de artista/webs/sufijos. Devuelve '' si no queda
    nada con sentido (hash, código de serie, números...)."""
    base = os.path.splitext(nombre)[0]
    t = RE_RUIDO_NOMBRE.sub(' ', base)
    t = re.sub(r'[\s_\-]+', ' ', t).strip()
    palabras = [p for p in t.split() if re.search(r'[a-záéíóúñ]', p, re.I)]
    # descartar tokens cortos en los extremos (restos de artista: "wu", "ai")
    while palabras and len(palabras[0]) <= 2:
        palabras.pop(0)
    while palabras and len(palabras[-1]) <= 2:
        palabras.pop()
    # sobrantes de "ai art" / "generated"
    limpio = [w for w in palabras if w.lower() not in ('ai', 'art')]
    if limpio:
        palabras = limpio
    if not palabras:
        return ''
    # códigos de serie (MD AB IX 5, BB 001...) no son títulos
    if (sum(len(p) for p in palabras) / len(palabras)) < 4.5 and \
            any(c.isdigit() for c in ''.join(palabras)):
        return ''
    if RE_SOLO_NUM.match(''.join(palabras)):
        return ''
    if re.match(r'^[a-f0-9]{16,}$', ''.join(palabras), re.I):
        return ''  # hash
    return ' '.join(palabras)


def nombre_final(nombre_actual, data, puntuacion, max_kw=3):
    """Devuelve el nombre de archivo propuesto (sin extensión).

    Prioridad del nombre base:
      1) Título original interesante (preservar_titulo=si de la IA, o
         título limpio con sentido) — se conserva añadido.
      2) nombre_sugerido de la IA si el original es "raro".
      3) slug del resumen de la IA.
    Luego se añaden las etiquetas: (kw1;kw2;kw3;p<PUNT>;<sexualizacion>).
    """
    import re as _re
    original = nombre_actual
    titulo = limpiar_titulo(original)
    sugerido = (data or {}).get('nombre_sugerido') or ''
    preservar = ((data or {}).get('preservar_titulo') == 'si') or (
        titulo and len(titulo.split()) >= 2)
    if preservar and titulo:
        base = _slug(titulo, 70)
    elif nombre_raro(original):
        if sugerido:
            base = _slug(sugerido, 60)
        else:
            resumen = (data or {}).get('resumen') or \
                      ((data or {}).get('descripcion') or '')[:60]
            base = _slug(resumen, 60)
    else:
        base = _slug(original, 80)
    kws = []
    for c in ((data or {}).get('categorias') or [])[:max_kw]:
        kws.append(_slug(str(c), 20))
    etiquetas = kws + [f'p{int(puntuacion)}',
                       (data or {}).get('sexualizacion') or 'na']
    return f'{base} ({";".join(etiquetas)})'


# ---------------------------------------------------------------------------
# 11e. MINIATURAS (imágenes pequeñas/thumbnails)
# ---------------------------------------------------------------------------
# Señales: sufijos de descarga (DeviantArt -375w/-414w/-pre/-2x) o resolución
# baja (lado corto < 450 px). Se apartan a Raras\Miniaturas sin gastar VLM.
MINIATURA_LADO = 300
RE_DA_THUMB = re.compile(
    r'-(?:375w|414w|236w|92s|pre|2x)\.(?:jpg|jpeg|png|webp)$', re.I)


def es_miniatura(ruta, nombre):
    """True si la imagen parece una miniatura (sufijo o resolución baja)."""
    if RE_DA_THUMB.search(nombre):
        return True
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            w, h = im.size
            return min(w, h) < MINIATURA_LADO
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 11f. ÁRBOL TEMÁTICO (descubierto a partir de las categorías del VLM)
# ---------------------------------------------------------------------------
# El culturismo tiene su propio árbol (Culturismo\Imagenes|Videos). El resto
# de temas se organiza en Imagenes\<Tema>\<Epoca>. Orden de prioridad:
# Bondage > Furry > Fantasia > Erotico > Culturismo > Fitness > Otro.
TEMA_PRIORIDAD = ['Bondage', 'Furry', 'Fantasia', 'Erotico', 'Culturismo',
                  'Fitness', 'Otro']
TEMA_CATEGORIAS = {
    'Bondage': {'bondage', 'bdsm', 'leather', 'restraint'},
    'Furry': {'furry', 'fandom', 'anthro'},
    'Fantasia': {'fantasy', 'cosplay', 'superheroe', 'anime', 'cartoon',
                 'render_3d', 'comics', 'futuristic', 'sci-fi'},
    'Erotico': {'erotic', 'nude', 'underwear', 'swimwear', 'genitales',
                'gay', 'straight', 'couple', 'solo', 'muscle_worship',
                'foot', 'feet', 'erotismo'},
    'Culturismo': {'muscle', 'bodybuilding', 'posing', 'physique',
                   'competition', 'backstage', 'flex', 'muscular_flexing',
                   'gym', 'workout', 'fitness_model', 'sweat', 'oiled',
                   'strongman', 'powerlifting'},
    'Fitness': {'fitness', 'athletic', 'sport', 'calisthenics',
                'functional'},
}


def tema_principal(data):
    """Devuelve el tema dominante según las categorías del VLM."""
    cats = {str(c).lower() for c in (data.get('categorias') or [])}
    for tema in TEMA_PRIORIDAD:
        if tema == 'Otro':
            continue
        if cats & TEMA_CATEGORIAS.get(tema, set()):
            return tema
    return 'Otro'


def escribir_metadatos(ruta, data, punt, nombre_base, modelo='gemma3:12b'):
    """Escribe keywords + descripción en EXIF (JPEG) o tEXt (PNG).
    Devuelve True si escribió algo, False si solo renombró."""
    ext = ext_of(ruta)
    keywords = ';'.join(str(c) for c in (data.get('categorias') or [])[:6])
    desc = (data.get('descripcion') or '')[:1500]
    resumen = (data.get('resumen') or '')[:300]
    comentario = json.dumps({
        'nombre_original': os.path.basename(ruta),
        'nombre_nuevo': nombre_base,
        'resumen': resumen,
        'descripcion': desc,
        'puntuacion': punt,
        'sexualizacion': data.get('sexualizacion'),
        'categorias': data.get('categorias') or [],
        'atributos': data.get('atributos') or [],
        'modelo': modelo,
    }, ensure_ascii=False)
    try:
        if ext in ('.jpg', '.jpeg'):
            import piexif
            ex = piexif.load(ruta)
            ex['0th'][40094] = keywords.encode('utf-16le')  # XPKeywords
            ex['0th'][270] = (nombre_base + ' | ' + resumen).encode('utf-8',
                                                                    'replace')
            ex['Exif'][37510] = b'UNICODE\0' + comentario.encode('utf-16le')
            piexif.insert(piexif.dump(ex), ruta)
            return True
        if ext == '.png':
            from PIL import Image, PngImagePlugin
            meta = PngImagePlugin.PngInfo()
            meta.add_text('Keywords', keywords)
            meta.add_text('Title', nombre_base)
            meta.add_text('Description', desc)
            meta.add_text('Comment', comentario)
            tmp = ruta + '.tmp'
            with Image.open(ruta) as im:
                im.save(tmp, pnginfo=meta)
            os.replace(tmp, ruta)
            return True
    except Exception as e:
        LOG.warning('Metadatos fallidos en %s: %s', ruta, e)
    return False


# ---------------------------------------------------------------------------
# 12. ÁRBOL DESTINO
# ---------------------------------------------------------------------------

def destino_de(tipo, categoria, epoca, nombre):
    r"""Construye la ruta destino en F:\Clasificado y la devuelve (sin mover).

    - tipo:      imagen|video|audio|incompleto|otro
    - categoria: 'culturismo' | None
    - epoca:     Clasico|IA|SinDeterminar (solo para imagen/video)
    """
    if tipo in ('imagen', 'video'):
        sub = 'Imagenes' if tipo == 'imagen' else 'Videos'
        if categoria == 'culturismo':
            return CLASIFICADO / 'Culturismo' / sub / epoca
        return CLASIFICADO / sub / epoca
    # Contenido NO media: aparte, agrupado por extensión para su inspección
    ext = ext_of(nombre)
    if tipo == 'audio':
        grupo = 'Audio'
    elif tipo == 'incompleto':
        grupo = 'Incompletos'
    elif ext in {'.pdf', '.doc', '.docx', '.epub', '.cbr', '.cbz', '.txt'}:
        grupo = 'Documentos'
    elif ext in {'.htm', '.html', '.js', '.css', '.json', '.xml', '.nfo'}:
        grupo = 'Web'
    elif ext in {'.zip', '.rar', '.7z', '.exe', '.msi', '.dmg'}:
        grupo = 'Ejecutables'
    else:
        grupo = 'Varios'
    return CLASIFICADO / 'Otros' / grupo


def ruta_sin_colision(destino, nombre):
    """Devuelve una ruta destino única (añade ' (2)', ' (3)'... si existe)."""
    candidato = destino / nombre
    if not candidato.exists():
        return candidato
    base, ext = os.path.splitext(nombre)
    i = 2
    while True:
        c = destino / f'{base} ({i}){ext}'
        if not c.exists():
            return c
        i += 1

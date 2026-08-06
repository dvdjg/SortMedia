# -*- coding: utf-8 -*-
r"""
03_metadatos.py — FASE 3: Metadatos (ffprobe + EXIF) en paralelo
================================================================

Extrae metadatos de cada archivo para decidir mejor entre IA / clásico:

  - VÍDEOS : ffprobe -> duración, resolución (ancho x alto), códec,
             encoder/software (los generadores de IA suelen dejar su
             firma aquí: ComfyUI, SVD, Kling, Wan, Veo...).
  - IMÁGENES: Pillow -> EXIF Software, DateTimeOriginal, cámara
             (Make/Model) y comentarios (A1111/ComfyUI guardan el prompt
             en el propio PNG/JPG).

El resultado se guarda en la tabla metadatos y las señales
(senal_ia / senal_clasica) las consume 04_clasificar.py.

RENDIMIENTO: 8 trabajadores en paralelo; solo se lee la cabecera de cada
archivo. Aprox. 10-20 archivos/segundo -> 60.000 vídeos en ~1-2 h.
Se puede cortar cuando quieras: al relanzarlo continúa donde iba.

USO:
    python F:\\scripts\\03_metadatos.py                   # todo lo pendiente
    python F:\\scripts\\03_metadatos.py --solo-videos     # solo vídeos
    python F:\\scripts\\03_metadatos.py --solo-imagenes   # solo imágenes
    python F:\\scripts\\03_metadatos.py --solo-sin-determinar
                          # solo archivos actualmente en SinDeterminar
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar

FFPROBE = r'C:\Users\David\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin\ffprobe.exe'
TRABAJADORES = 8
LOTE = 200

AI_EXIF = common.AI_EXIF_HINTS
AI_VIDEO = common.AI_VIDEO_HINTS
CAMARAS = common.CAMARA_MAKES


def ffprobe_meta(ruta):
    """Metadatos de vídeo vía ffprobe (JSON). Devuelve dict o None."""
    try:
        out = subprocess.run(
            [FFPROBE, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'format=duration,format_name,tags:'
             'stream=codec_name,width,height',
             '-of', 'json', ruta],
            capture_output=True, timeout=60)
        if out.returncode != 0:
            return None
        d = json.loads(out.stdout or '{}')
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None
    fmt = d.get('format', {})
    tags = fmt.get('tags', {}) or {}
    st = (d.get('streams') or [{}])[0]
    return {
        'duracion': float(fmt['duration']) if fmt.get('duration') else None,
        'ancho': st.get('width'),
        'alto': st.get('height'),
        'encoder': tags.get('encoder') or tags.get('software') or
                   st.get('codec_name'),
        'software': tags.get('software'),
    }


def exif_meta(ruta):
    """Metadatos de imagen vía Pillow (EXIF + chunks PNG). dict o None."""
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            info = {}
            exif = im.getexif()
            if exif:
                info['software'] = exif.get(305)
                info['make'] = exif.get(271)
                info['model'] = exif.get(272)
                info['fecha_original'] = exif.get(36867)
            # Chunks de texto típicos de generadores (PNG)
            for k in ('Software', 'Comment', 'parameters', 'prompt',
                      'workflow', 'Description'):
                if k in im.info and im.info[k]:
                    info.setdefault('software', str(im.info[k])[:200])
            if not any(info.values()):
                return None
            return {
                'tipo': 'imagen',
                'duracion': None, 'ancho': im.width, 'alto': im.height,
                'encoder': None,
                'software': str(info.get('software') or '')[:200],
                'make': str(info.get('make') or '')[:100],
                'model': str(info.get('model') or '')[:100],
                'fecha_original': str(info.get('fecha_original') or '')[:30],
            }
    except Exception:
        return None


def señales_de(meta):
    ia = 0
    clasica = 0
    texto = ' '.join(str(meta.get(k) or '') for k in
                     ('software', 'encoder', 'make', 'model')).casefold()
    if common.contiene_marcador(texto, AI_EXIF + AI_VIDEO):
        ia = 1
    make = (meta.get('make') or '').casefold()
    if make and any(m in make for m in CAMARAS):
        clasica = 1
    fo = str(meta.get('fecha_original') or '')
    if fo[:4].isdigit() and int(fo[:4]) <= 2021:
        clasica = 1
    return ia, clasica


def extraer(ruta, tipo):
    if tipo == 'video':
        m = ffprobe_meta(ruta)
        if m is None:
            return None
        m['tipo'] = 'video'
        return m
    if tipo == 'imagen':
        return exif_meta(ruta)
    return None


def pendientes(con, filtro):
    """Archivos sin metadatos. Incluye pendientes (aún en origen) y ya
    movidos que estén en SinDeterminar (si filtro='sindet')."""
    rows = con.execute(
        'SELECT ruta, ext, estado, destino FROM inventario '
        'WHERE (meta IS NULL OR meta != ?) AND estado IN (?,?)',
        ('ok', 'pendiente', 'movido')).fetchall()
    res = []
    for r in rows:
        ruta = common.ruta_de_db(r['ruta'])
        tipo = common.tipo_de(r['ext'])
        if tipo not in ('video', 'imagen'):
            continue
        if filtro == 'video' and tipo != 'video':
            continue
        if filtro == 'imagen' and tipo != 'imagen':
            continue
        if filtro == 'sindet':
            en_sindet = (r['destino'] and 'SinDeterminar' in r['destino'])
            if not en_sindet:
                # pendientes aún sin mover no tienen destino: lo
                # decidimos por fecha como hace 04
                import datetime
                f = datetime.datetime.fromtimestamp(
                    con.execute('SELECT mtime FROM inventario WHERE ruta=?',
                                (r['ruta'],)).fetchone()['mtime'])
                if not (common.FRONTERA_IA <= f < common.IA_FIJO_DESDE):
                    continue
        res.append({'ruta': ruta, 'ext': r['ext']})
    return res


def main():
    ap = argparse.ArgumentParser(description='Metadatos ffprobe/EXIF (Fase 3)')
    ap.add_argument('--solo-videos', action='store_true')
    ap.add_argument('--solo-imagenes', action='store_true')
    ap.add_argument('--solo-sin-determinar', action='store_true')
    args = ap.parse_args()

    filtro = ('sindet' if args.solo_sin_determinar else
              'video' if args.solo_videos else
              'imagen' if args.solo_imagenes else None)

    con = conectar()
    common.reconciliar(con)
    pend = pendientes(con, filtro)
    LOG.info('%d archivos pendientes de metadatos', len(pend))

    t0 = time.time()
    hechos = 0
    lote = []
    with ThreadPoolExecutor(max_workers=TRABAJADORES) as pool:
        futuros = {pool.submit(extraer, r['ruta'], common.tipo_de(r['ext'])):
                   r for r in pend}
        for fut in as_completed(futuros):
            fila = futuros[fut]
            ruta = fila['ruta']
            ruta_db = common.ruta_a_db(ruta)
            try:
                meta = fut.result()
            except Exception as e:
                LOG.warning('Error en %s: %s', ruta, e)
                meta = None
            if meta:
                ia, cl = señales_de(meta)
                lote.append((ruta_db, meta.get('tipo'), meta.get('duracion'),
                             meta.get('ancho'), meta.get('alto'),
                             meta.get('encoder'), meta.get('software'),
                             meta.get('make'), meta.get('model'),
                             meta.get('fecha_original'), ia, cl))
            con.execute('UPDATE inventario SET meta=? WHERE ruta=?',
                        ('ok', ruta_db))
            hechos += 1
            if len(lote) >= LOTE:
                con.executemany(
                    'INSERT OR REPLACE INTO metadatos(ruta, tipo, duracion, '
                    'ancho, alto, encoder, software, make, model, '
                    'fecha_original, senal_ia, senal_clasica) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', lote)
                lote = []
                con.commit()
            if hechos % 500 == 0:
                LOG.info('%d/%d | %.1f/s', hechos, len(pend),
                         hechos / (time.time() - t0))
    if lote:
        con.executemany(
            'INSERT OR REPLACE INTO metadatos(ruta, tipo, duracion, ancho, '
            'alto, encoder, software, make, model, fecha_original, '
            'senal_ia, senal_clasica) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', lote)
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM metadatos').fetchone()[0]
    LOG.info('FIN: %d archivos con metadatos en %d filas (%.0fs)',
             hechos, n, time.time() - t0)
    con.close()


if __name__ == '__main__':
    main()

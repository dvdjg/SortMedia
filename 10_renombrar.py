# -*- coding: utf-8 -*-
"""
10_renombrar.py — Renombrado masivo + metadatos (reanudable, por lotes)
=======================================================================

Renombra las imágenes ya clasificadas por el VLM (fase 06) con el formato:
    <slug_ia> (<kw1>;<kw2>;<kw3>;p<PUNTUACION>;<sexualizacion>).ext
y escribe la clasificación en los METADATOS de la imagen:
  - JPEG : EXIF sin pérdida (piexif): XPKeywords, UserComment (JSON con
           descripción/resumen/original/score...), ImageDescription.
  - PNG  : chunks tEXt (Keywords, Title, Description, Comment).
  - Otros: solo renombrado (sin tocar el binario).

REANUDACIÓN Y LOTES (diseñado para parar y continuar):
  - Cada archivo procesado queda marcado (inventario.renombrado) y se
    commitea inmediatamente: si cortas el proceso (Ctrl+C, apagón, 1 hora
    de uso), al relanzar CONTINÚA por donde iba.
  - Orden: primero los archivos MÁS ANTIGUOS (mtime asc), para no tocar
    los que estés añadiendo/modificando ahora.
  - Los "dudosos" (puntuación 40-79 sin contexto viril) NO se renombran
    por defecto: se listan en salida/para_revisar.csv para re-clasificarlos
    después (--incluir-dudosos para procesarlos igualmente).

USO:
    python F:\\scripts\\10_renombrar.py --minutos 55     # presupuesto de tiempo
    python F:\\scripts\\10_renombrar.py --limite 100      # solo 100 archivos
    python F:\\scripts\\10_renombrar.py --carpeta F:\\Clasificado\\Imagenes\\IA
    python F:\\scripts\\10_renombrar.py --dry-run         # solo informa
    python F:\\scripts\\10_renombrar.py --incluir-dudosos
    python F:\\scripts\\10_renombrar.py --reiniciar       # ignora lo ya hecho
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar

UMBRAL_DUDOSO_INF = 40
UMBRAL_DUDOSO_SUP = 80  # [40, 80) sin viril = dudoso

EXT_CON_META = ('.jpg', '.jpeg', '.png')


def pendientes(con, carpeta, incluir_dudosos, reiniciar):
    """Imágenes clasificadas pendientes de renombrar (más antiguas primero)."""
    where = "i.estado='movido' AND i.destino LIKE '%Imagenes%' AND "
    where += "v.json IS NOT NULL"
    if not reiniciar:
        where += " AND (i.renombrado IS NULL OR i.renombrado='')"
    if carpeta:
        where += " AND i.destino LIKE ?"
    rows = con.execute(
        f"SELECT i.ruta, i.mtime, v.json, v.modelo FROM inventario i "
        f"JOIN vision v ON v.ruta = i.ruta WHERE {where} "
        f"ORDER BY i.mtime ASC",
        (carpeta + '%',) if carpeta else ()).fetchall()
    res = []
    for r in rows:
        ruta = common.ruta_de_db(r['ruta'])
        if not os.path.exists(ruta):
            continue
        try:
            data = json.loads(r['json'])
        except (json.JSONDecodeError, TypeError):
            continue
        punt, _ = common.calcular_puntuacion(data)
        dudoso = (UMBRAL_DUDOSO_INF <= punt < UMBRAL_DUDOSO_SUP
                  and data.get('viril') != 'si')
        if dudoso and not incluir_dudosos:
            continue
        res.append((ruta, data, punt, dudoso, r['modelo']))
    return res


def main():
    ap = argparse.ArgumentParser(description='Renombrado + metadatos (Fase 10)')
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--minutos', type=float, default=0, help='presupuesto de tiempo')
    ap.add_argument('--carpeta', default=None)
    ap.add_argument('--incluir-dudosos', action='store_true')
    ap.add_argument('--reiniciar', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    con = conectar()
    pend = pendientes(con, args.carpeta, args.incluir_dudosos, args.reiniciar)
    LOG.info('%d imágenes pendientes de renombrar%s', len(pend),
             f' (carpeta {args.carpeta})' if args.carpeta else '')
    t0 = time.time()
    hechos = 0
    dudosos_csv = []
    for ruta, data, punt, dudoso, modelo in pend:
        if args.limite and hechos >= args.limite:
            break
        if args.minutos and (time.time() - t0) / 60 >= args.minutos:
            LOG.info('Presupuesto de %s min agotado. Reanuda cuando quieras.',
                     args.minutos)
            break
        nombre = os.path.basename(ruta)
        base = os.path.splitext(nombre)[0]
        nuevo = common.nombre_final(base, data, punt) + os.path.splitext(nombre)[1]
        destino = common.ruta_sin_colision(Path(ruta).parent, nuevo)
        if dudoso:
            dudosos_csv.append((ruta, nuevo, punt))
        if args.dry_run:
            LOG.info('  %s -> %s', nombre[:40], nuevo)
            hechos += 1
            continue
        try:
            os.replace(ruta, destino)
        except OSError as e:
            LOG.error('No se pudo renombrar %s: %s', ruta, e)
            continue
        nueva_ruta = str(destino).replace('\\', '/')
        common.escribir_metadatos(nueva_ruta, data, punt,
                           os.path.splitext(os.path.basename(nueva_ruta))[0],
                           modelo)
        con.execute('UPDATE inventario SET ruta=?, renombrado=? WHERE ruta=?',
                    (common.ruta_a_db(nueva_ruta),
                     time.strftime('%Y-%m-%d %H:%M:%S'),
                     common.ruta_a_db(ruta)))
        con.execute('UPDATE vision SET ruta=? WHERE ruta=?',
                    (common.ruta_a_db(nueva_ruta), common.ruta_a_db(ruta)))
        con.execute('INSERT OR REPLACE INTO movidos(ruta_orig, ruta_dest, fecha) '
                    'VALUES(?,?,?)',
                    (common.ruta_a_db(ruta), common.ruta_a_db(nueva_ruta),
                     time.strftime('%Y-%m-%d %H:%M:%S')))
        con.commit()
        hechos += 1
        if hechos % 50 == 0:
            LOG.info('%d renombrados... (%.0fs)', hechos, time.time() - t0)
    with open(common.SALIDA_DIR / 'para_revisar.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['ruta', 'nombre_propuesto', 'puntuacion'])
        w.writerows(dudosos_csv)
    LOG.info('FIN: %d procesados en %.0fs | dudosos listados: %d',
             hechos, time.time() - t0, len(dudosos_csv))
    if args.dry_run:
        LOG.warning('MODO SIMULACIÓN: no se renombró nada.')
    con.close()


if __name__ == '__main__':
    main()

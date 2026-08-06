# -*- coding: utf-8 -*-
r"""
07_sacar_raras.py — Saca imágenes erróneas o extrañas a F:\Clasificado\Raras\
============================================================================

Mueve fuera del árbol principal las imágenes que:
  - dieron ERROR en la clasificación (JSON inválido, ilegibles, etc.),
  - el VLM marcó como es_extraña=si (screenshots, web, gráficos, texto,
    memes, imágenes rotas/negras, miniaturas de vídeo...),
  - obtuvieron puntuación < 40 (no interesan al coleccionista: fotos
    familiares, sin hombre atractivo, sin físico visible...).

Destino:
  F:\Clasificado\Raras\Errores\      -> clasificación fallida
  F:\Clasificado\Raras\Extranas\     -> es_extraña=si
  F:\Clasificado\NoInteresante\      -> puntuación < 40

Actualiza inventario (ruta/destino) y escribe salida/raras.csv con el
motivo. Reanudable e idempotente: las ya movidas se saltan.

USO:
    python F:\\scripts\\07_sacar_raras.py
    python F:\\scripts\\07_sacar_raras.py --dry-run
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar

RARAS = common.CLASIFICADO / 'Raras'


def mover(con, ruta, subcarpeta, motivo, dry_run):
    nombre = os.path.basename(ruta)
    if subcarpeta == 'NoInteresante':
        destino = common.CLASIFICADO / 'NoInteresante'
    else:
        destino = RARAS / subcarpeta
    dest = common.ruta_sin_colision(destino, nombre)
    if dry_run:
        LOG.info('  -> %s (%s)', dest, motivo)
        return False
    try:
        os.makedirs(destino, exist_ok=True)
        os.replace(ruta, dest)
    except OSError as e:
        LOG.error('Error moviendo %s: %s', ruta, e)
        return False
    nueva = str(dest).replace('\\', '/')
    con.execute('UPDATE inventario SET estado=?, ruta=?, destino=? '
                'WHERE ruta=?',
                ('movido', common.ruta_a_db(nueva), str(destino),
                 common.ruta_a_db(ruta)))
    con.execute('INSERT OR REPLACE INTO movidos(ruta_orig, ruta_dest, fecha) '
                'VALUES(?,?,?)',
                (common.ruta_a_db(ruta), common.ruta_a_db(nueva),
                 time.strftime('%Y-%m-%d %H:%M:%S')))
    con.execute('UPDATE metadatos SET ruta=? WHERE ruta=?',
                (common.ruta_a_db(nueva), common.ruta_a_db(ruta)))
    return True


def main():
    ap = argparse.ArgumentParser(description='Sacar imágenes raras/erróneas')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--solo-miniaturas', action='store_true',
                    help='pase previo a la visión: solo miniaturas '
                         '(sin coste de VLM)')
    args = ap.parse_args()

    con = conectar()
    rows = con.execute(
        "SELECT ruta, destino FROM inventario "
        "WHERE estado='movido' AND destino LIKE '%Imagenes%'").fetchall()
    # raras = errores + es_extraña=si + puntuación baja (no interesante)
    err = {r[0] for r in con.execute(
        'SELECT ruta FROM vision WHERE json IS NULL')}
    ext = {r[0] for r in con.execute(
        "SELECT ruta FROM vision WHERE es_extrana='si'")}
    nint = {r[0] for r in con.execute(
        "SELECT ruta FROM vision WHERE puntuacion IS NOT NULL "
        "AND puntuacion < 40")}
    movidos = 0
    filas_csv = []
    for r in rows:
        ruta_db = r['ruta']
        ruta = common.ruta_de_db(ruta_db)
        if not os.path.exists(ruta):
            continue
        if common.es_miniatura(ruta, os.path.basename(ruta)):
            sub, motivo = 'Miniaturas', 'miniatura (resolución o sufijo)'
        elif args.solo_miniaturas:
            continue
        elif ruta_db in err:
            sub, motivo = 'Errores', 'clasificación fallida'
        elif ruta_db in nint:
            sub, motivo = 'NoInteresante', 'puntuación < 40'
        elif ruta_db in ext:
            sub, motivo = 'Extranas', 'es_extraña=si'
        else:
            continue
        if mover(con, ruta, sub, motivo, args.dry_run):
            movidos += 1
            filas_csv.append((ruta, str(RARAS / sub / os.path.basename(ruta)),
                              motivo))
    con.commit()
    with open(common.SALIDA_DIR / 'raras.csv', 'w', newline='',
              encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ruta_original', 'ruta_destino', 'motivo'])
        w.writerows(filas_csv)
    LOG.info('FIN: %d imágenes movidas a Raras (Errores=%d, Extranas=%d)',
             movidos, len(err), len(ext))
    if args.dry_run:
        LOG.warning('MODO SIMULACIÓN: no se movió nada.')
    con.close()


if __name__ == '__main__':
    main()

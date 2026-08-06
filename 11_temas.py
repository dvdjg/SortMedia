# -*- coding: utf-8 -*-
"""
11_temas.py — Árbol temático a partir de las categorías del VLM
================================================================

Reorganiza las imágenes clasificadas de Imagenes\<Epoca> a
Imagenes\<Tema>\<Epoca> según el tema dominante (common.tema_principal):
Bondage, Furry, Fantasia, Erotico, Culturismo, Fitness u Otro.
El culturismo ya tiene su árbol propio (Culturismo\Imagenes) y no se
toca. Reanudable e idempotente (los ya movidos quedan con destino nuevo
y se saltan). --dry-run previsualiza.

Descubrimiento de temas: genera salida/temas_descubiertos.csv con el
recuento de categorías del corpus para proponer temas nuevos (edítalos
en common.TEMA_CATEGORIAS).

USO:
    python F:\\scripts\\11_temas.py               # reorganiza todo
    python F:\\scripts\\11_temas.py --dry-run     # previsualiza
    python F:\\scripts\\11_temas.py --carpeta F:\\Clasificado\\Imagenes\\IA
    python F:\\scripts\\11_temas.py --descubrir   # solo el informe de temas
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar


def mover(con, ruta, tema, epoca, dry_run):
    destino = common.CLASIFICADO / 'Imagenes' / tema / epoca
    nombre = os.path.basename(ruta)
    dest = common.ruta_sin_colision(destino, nombre)
    if dry_run:
        return dest, False
    try:
        os.makedirs(destino, exist_ok=True)
        os.replace(ruta, dest)
    except OSError as e:
        LOG.error('Error moviendo %s: %s', ruta, e)
        return None, False
    nueva = str(dest).replace('\\', '/')
    con.execute('UPDATE inventario SET ruta=?, destino=? WHERE ruta=?',
                ('movido', common.ruta_a_db(nueva), str(destino),
                 common.ruta_a_db(ruta)) if False else
                (common.ruta_a_db(nueva), str(destino),
                 common.ruta_a_db(ruta)))
    con.execute('UPDATE inventario SET estado=?, ruta=?, destino=? '
                'WHERE ruta=?',
                ('movido', common.ruta_a_db(nueva), str(destino),
                 common.ruta_a_db(ruta)))
    con.execute('INSERT OR REPLACE INTO movidos(ruta_orig, ruta_dest, fecha) '
                'VALUES(?,?,?)',
                (common.ruta_a_db(ruta), common.ruta_a_db(nueva),
                 time.strftime('%Y-%m-%d %H:%M:%S')))
    return dest, True


def main():
    ap = argparse.ArgumentParser(description='Árbol temático (Fase 11)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--carpeta', default=None)
    ap.add_argument('--descubrir', action='store_true',
                    help='solo genera el informe de temas descubiertos')
    args = ap.parse_args()

    con = conectar()

    # informe de descubrimiento: categorías usadas por el corpus
    contador = Counter()
    for r in con.execute(
            'SELECT categorias FROM vision WHERE categorias IS NOT NULL'):
        try:
            for c in json.loads(r['categorias']):
                contador[c] += 1
        except (json.JSONDecodeError, TypeError):
            pass
    with open(common.SALIDA_DIR / 'temas_descubiertos.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['categoria', 'archivos', 'tema_actual'])
        for c, n in contador.most_common(60):
            w.writerow([c, n, next(
                (t for t in common.TEMA_PRIORIDAD
                 if c.lower() in common.TEMA_CATEGORIAS.get(t, set())),
                'Otro')])
    if args.descubrir:
        LOG.info('Informe de temas en %s (top: %s)',
                 common.SALIDA_DIR / 'temas_descubiertos.csv',
                 [f'{c}:{n}' for c, n in contador.most_common(5)])
        con.close()
        return

    # mover imágenes clasificadas de Imagenes\<Epoca> a Imagenes\<Tema>\<Epoca>
    rows = con.execute(
        "SELECT i.ruta, v.json, v.puntuacion FROM inventario i "
        "JOIN vision v ON v.ruta = i.ruta "
        "WHERE i.estado='movido' AND i.destino LIKE 'F:%Clasificado%Imagenes%' AND i.destino NOT LIKE '%Raras%' AND i.destino NOT LIKE '%Culturismo%' "
        "AND v.json IS NOT NULL").fetchall()
    if args.carpeta:
        rows = [r for r in rows if args.carpeta in (r[0] or '')]
    movidos = 0
    for r in rows:
        ruta = common.ruta_de_db(r['ruta'])
        if not os.path.exists(ruta):
            continue
        try:
            data = json.loads(r['json'])
        except (json.JSONDecodeError, TypeError):
            continue
        tema = common.tema_principal(data)
        # extraer la época de la ruta actual (Imagenes\<Epoca>\ o ...\<Tema>\<Epoca>\)
        partes = Path(ruta).parts
        epoca = None
        for i, p in enumerate(partes):
            if p in ('Clasico', 'IA', 'SinDeterminar'):
                epoca = p
                break
        if not epoca:
            continue
        destino_actual = f'F:/Clasificado/Imagenes/{epoca}/'
        if tema != 'Otro' and (r[0] or '').startswith(destino_actual):
            dest, ok = mover(con, ruta, tema, epoca, args.dry_run)
            if ok:
                movidos += 1
                if not args.dry_run and movidos % 100 == 0:
                    con.commit()
                    LOG.info('%d movidos a temas...', movidos)
    con.commit()
    LOG.info('FIN: %d imágenes reorganizadas por tema%s', movidos,
             ' (SIMULACIÓN)' if args.dry_run else '')
    con.close()


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
12_progreso.py — Estado del batch de clasificación (para consulta rápida)
=========================================================================

Muestra: procesadas/restantes, velocidad, ETA, errores, y ejemplos de
clasificaciones con el nombre final que se generará (fase 10) y una
previsualización de la metadata que se escribirá en EXIF.

USO:
    python F:\\scripts\\12_progreso.py               # resumen + 5 ejemplos
    python F:\\scripts\\12_progreso.py --ejemplos 10
    python F:\\scripts\\12_progreso.py --errores     # últimos errores
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, 'F:/scripts')
import common


def main():
    ap = argparse.ArgumentParser(description='Progreso del batch VLM')
    ap.add_argument('--ejemplos', type=int, default=5)
    ap.add_argument('--errores', action='store_true')
    args = ap.parse_args()

    con = common.conectar()
    total = con.execute(
        "SELECT COUNT(*) FROM inventario WHERE estado='movido' "
        "AND destino LIKE '%Imagenes%' AND ext IN ('.jpg','.jpeg',"
        "'.png','.webp','.bmp')").fetchone()[0]
    ok = con.execute('SELECT COUNT(*) FROM vision WHERE json IS NOT NULL'
                     ).fetchone()[0]
    err = con.execute('SELECT COUNT(*) FROM vision WHERE json IS NULL'
                      ).fetchone()[0]
    pend = total - ok - err
    print('=' * 78)
    print('CLASIFICACIÓN VLM — progreso')
    print('=' * 78)
    print(f'  total imágenes      : {total}')
    print(f'  clasificadas OK     : {ok}  ({100*ok/max(total,1):.1f}%)')
    print(f'  errores             : {err}')
    print(f'  pendientes          : {pend}')
    log = 'F:/scripts/salida/vision_run.log'
    if os.path.exists(log):
        mtime = os.path.getmtime(log)
        print(f'  último cambio log   : {time.ctime(mtime)}')
        try:
            t0 = mtime - 600  # ventana aproximada
            if os.path.exists('F:/scripts/estado/estado.db-wal'):
                pass
        except Exception:
            pass
    if ok:
        # velocidad medida: inicio del run desde la primera línea del log
        vel = None
        try:
            with open(log, encoding='utf-8', errors='replace') as f:
                for linea in f:
                    if 'INFO' in linea and 'clasificar' in linea:
                        hh, mm, ss = linea.split()[0].split(':')
                        inicio = time.mktime(time.localtime()) - (
                            time.time() - time.mktime(
                                (time.localtime().tm_year,
                                 time.localtime().tm_mon,
                                 time.localtime().tm_mday,
                                 int(hh), int(mm), int(ss), 0, 0, -1)))
                        vel = ok / max(time.time() - inicio, 1)
                        break
        except Exception:
            pass
        if vel:
            eta = pend / vel / 3600
            print(f'  velocidad real      : {vel:.2f} img/s')
            print(f'  ETA estimada        : {eta:.1f} h')

    if args.errores:
        print('\n--- ÚLTIMOS ERRORES ---')
        for r in con.execute(
                'SELECT resumen, nombre_original FROM vision '
                'WHERE json IS NULL ORDER BY rowid DESC LIMIT 8'):
            print(' ', (r['nombre_original'] or '?')[:40], '|',
                  (r['resumen'] or '')[-100:].replace('\n', ' '))

    if ok and args.ejemplos:
        print(f'\n--- {args.ejemplos} EJEMPLOS (nombre generado + metadata) ---')
        rows = con.execute(
            'SELECT i.ruta, v.json, v.puntuacion FROM inventario i '
            'JOIN vision v ON v.ruta = i.ruta WHERE v.json IS NOT NULL '
            'ORDER BY RANDOM() LIMIT ?', (args.ejemplos,)).fetchall()
        for r in rows:
            ruta = common.ruta_de_db(r['ruta'])
            data = json.loads(r['json'])
            punt, motivo = common.calcular_puntuacion(data)
            nombre_final = common.nombre_final(
                os.path.splitext(os.path.basename(ruta))[0], data, punt)
            print('-' * 78)
            print('  RUTA     :', ruta)
            print('  NUEVO    :', nombre_final[:90])
            print('  PUNT     :', punt, '| SEX:', data.get('sexualizacion'),
                  '| fisico:', data.get('fisico'),
                  '| cult:', data.get('es_culturismo'),
                  '| tema:', common.tema_principal(data))
            print('  RESUMEN  :', (data.get('resumen') or '')[:100])
            print('  META JSON (se escribirá en EXIF):',
                  json.dumps({'nombre_nuevo': nombre_final,
                              'puntuacion': punt,
                              'sexualizacion': data.get('sexualizacion'),
                              'categorias': data.get('categorias'),
                              'resumen': (data.get('resumen') or '')[:80]},
                             ensure_ascii=False)[:180])
    con.close()


if __name__ == '__main__':
    main()

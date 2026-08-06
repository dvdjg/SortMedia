# -*- coding: utf-8 -*-
r"""
05_informe.py — Informe de estado del proceso
=============================================

Genera un resumen legible de todo el proceso en salida/informe.txt:
cuántos archivos hay, cuántos se movieron, duplicados borrados, espacio
liberado, sospechosos, etc. Útil para comprobar el progreso entre
ejecuciones.

USO:
    python F:\\scripts\\05_informe.py
"""
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import conectar


def main():
    con = conectar()
    salida = []
    def out(s=''):
        salida.append(s)

    out('=' * 72)
    out('INFORME DE CLASIFICACIÓN F:\\')
    out('=' * 72)
    out()
    total = con.execute('SELECT COUNT(*) FROM inventario').fetchone()[0]
    out(f'TOTAL archivos inventariados: {total}')
    out()
    out('--- Estado del inventario ---')
    for r in con.execute('SELECT estado, COUNT(*) n FROM inventario '
                         'GROUP BY estado ORDER BY n DESC'):
        out(f'  {r["estado"]:12s} {r["n"]:8d}')
    out()
    out('--- Duplicados borrados ---')
    n = con.execute('SELECT COUNT(*) FROM duplicados').fetchone()[0]
    gb = con.execute('SELECT SUM(CAST(tamano AS REAL))/1e9 FROM inventario '
                     'WHERE estado=?', ('borrado',)).fetchone()[0] or 0
    out(f'  copias borradas : {n}')
    out(f'  espacio liberado: {gb:.2f} GB')
    out()
    out('--- Sospechosos (casi-duplicados, NO tocados) ---')
    for r in con.execute('SELECT motivo, COUNT(*) n FROM sospechosos '
                         'GROUP BY motivo ORDER BY n DESC'):
        out(f'  {r["motivo"]:45s} {r["n"]}')
    out()
    out('--- Árbol destino (F:\\Clasificado) ---')
    for raiz, dirs, files in os.walk(common.CLASIFICADO):
        dirs.sort()
        n = len(files)
        if n:
            rel = os.path.relpath(raiz, common.CLASIFICADO)
            out(f'  {rel or ".":55s} {n:6d} archivos')
    out()
    out('--- Metadatos ---')
    nm = con.execute('SELECT COUNT(*) FROM metadatos').fetchone()[0]
    ni = con.execute('SELECT COUNT(*) FROM metadatos WHERE tipo=?',
                     ('imagen',)).fetchone()[0]
    nv = con.execute('SELECT COUNT(*) FROM metadatos WHERE tipo=?',
                     ('video',)).fetchone()[0]
    out(f'  imágenes con EXIF: {ni}')
    out(f'  vídeos con ffprobe: {nv}')
    out(f'  total: {nm}')
    out()
    out('--- Progreso por fase ---')
    for r in con.execute('SELECT fase, valor, fecha FROM progreso '
                         'ORDER BY fecha DESC LIMIT 20'):
        out(f'  {r["fase"]:30s} {r["valor"]}  ({r["fecha"]})')

    texto = '\n'.join(salida)
    ruta = common.SALIDA_DIR / 'informe.txt'
    ruta.write_text(texto, encoding='utf-8')
    print(texto)
    print()
    print('Guardado en:', ruta)

    # CSV de sospechosos (para revisarlos cómodamente)
    with open(common.SALIDA_DIR / 'sospechosos.csv', 'w', newline='',
              encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['archivo', 'pareja', 'motivo'])
        for r in con.execute('SELECT ruta, pareja, motivo FROM sospechosos '
                             'ORDER BY motivo'):
            w.writerow([common.ruta_de_db(r['ruta']),
                        common.ruta_de_db(r['pareja']), r['motivo']])
    con.close()


if __name__ == '__main__':
    main()

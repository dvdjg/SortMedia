# -*- coding: utf-8 -*-
"""Revierte de Raras\Miniaturas las imágenes sin sufijo de miniatura DA
(lado corto >= 300 px) — son falsos positivos del criterio antiguo.
Usa movidos.ruta_orig para devolverlas a su sitio. Idempotente."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, 'F:/scripts')
import common
from common import LOG, conectar


def main():
    con = conectar()
    rows = con.execute(
        "SELECT ruta FROM inventario WHERE estado='movido' "
        "AND destino LIKE '%Raras\\Miniaturas%'").fetchall()
    revertidas = 0
    for r in rows:
        ruta_db = r['ruta']
        ruta = common.ruta_de_db(ruta_db)
        nombre = os.path.basename(ruta)
        if common.RE_DA_THUMB.search(nombre):
            continue  # miniatura real (sufijo DA): se queda
        try:
            from PIL import Image
            with Image.open(ruta) as im:
                w, h = im.size
        except Exception:
            continue
        if min(w, h) < 300:
            continue  # realmente pequeña: se queda
        # falso positivo: devolver a su origen
        orig = con.execute(
            'SELECT ruta_orig FROM movidos WHERE ruta_dest=?',
            (ruta_db,)).fetchone()
        if not orig:
            continue
        destino_orig = common.ruta_de_db(orig[0])
        try:
            os.makedirs(os.path.dirname(destino_orig), exist_ok=True)
            os.replace(ruta, destino_orig)
        except OSError as e:
            LOG.warning('No se pudo revertir %s: %s', ruta, e)
            continue
        con.execute(
            'UPDATE inventario SET ruta=?, destino=? WHERE ruta=?',
            (common.ruta_a_db(destino_orig.replace('\\', '/')),
             os.path.dirname(destino_orig).replace('\\', '/'),
             ruta_db))
        con.execute('DELETE FROM movidos WHERE ruta_dest=?', (ruta_db,))
        con.execute('INSERT OR REPLACE INTO movidos(ruta_orig, ruta_dest, '
                    'fecha) VALUES(?,?,?)',
                    (ruta_db, common.ruta_a_db(destino_orig.replace('\\', '/')),
                     time.strftime('%Y-%m-%d %H:%M:%S')))
        revertidas += 1
    con.commit()
    LOG.info('Miniaturas revertidas al árbol: %d', revertidas)
    con.close()


if __name__ == '__main__':
    main()

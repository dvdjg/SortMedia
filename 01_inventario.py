# -*- coding: utf-8 -*-
r"""
01_inventario.py — FASE 1: Escaneo de F:\ (checkpoint)
=======================================================

Recorre todas las carpetas de F:\ (excepto las de EXCLUIDOS en common.py,
p. ej. David, Clasificado, scripts...) y guarda en estado.db una fila por
archivo con: ruta, tamaño, extensión y fecha de modificación.

REANUDABLE: ejecutar de nuevo NO duplica nada (INSERT OR IGNORE). Sirve
también para añadir archivos nuevos que hayas colocado después.

USO:
    python F:\\scripts\\01_inventario.py            # escaneo completo
    python F:\\scripts\\01_inventario.py --raiz F:\\Clasificado\\Incoming
                                                  # solo una carpeta nueva
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar, es_raiz_excluida

LOTE = 5000  # filas por transacción (velocidad/seguridad)


def escanear(con, raiz):
    """Camina `raiz` e inserta los archivos en el inventario."""
    raiz = Path(raiz)
    n_nuevos = 0
    n_skip = 0
    filas = []
    for dirpath, dirs, files in os.walk(raiz):
        # Podamos en el sitio las carpetas excluidas (más rápido que filtrar)
        dirs[:] = [d for d in dirs if not es_raiz_excluida(d)]
        for nombre in files:
            ruta = os.path.join(dirpath, nombre)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            filas.append((
                common.ruta_a_db(ruta.replace('\\', '/')),
                st.st_size,
                common.ext_of(nombre),
                st.st_mtime,
                common.ruta_a_db(str(raiz).replace('\\', '/')),
            ))
            if len(filas) >= LOTE:
                cur = con.executemany(
                    'INSERT OR IGNORE INTO inventario'
                    '(ruta, tamano, ext, mtime, raiz) VALUES(?,?,?,?,?)',
                    filas)
                n_nuevos += cur.rowcount
                n_skip += len(filas) - cur.rowcount
                con.commit()
                filas = []
    if filas:
        cur = con.executemany(
            'INSERT OR IGNORE INTO inventario'
            '(ruta, tamano, ext, mtime, raiz) VALUES(?,?,?,?,?)', filas)
        n_nuevos += cur.rowcount
        n_skip += len(filas) - cur.rowcount
        con.commit()
    return n_nuevos, n_skip


def main():
    ap = argparse.ArgumentParser(description='Escaneo del inventario (Fase 1)')
    ap.add_argument('--raiz', default='F:/',
                    help='Carpeta a escanear (por defecto F:/ completa)')
    args = ap.parse_args()

    con = conectar()
    t0 = time.time()
    LOG.info('Escaneando %s ...', args.raiz)
    nuevos, saltados = escanear(con, args.raiz)
    total = con.execute('SELECT COUNT(*) FROM inventario').fetchone()[0]
    LOG.info('Hecho en %.0fs | nuevos: %d | ya existían: %d | TOTAL inventario: %d',
             time.time() - t0, nuevos, saltados, total)
    con.close()


if __name__ == '__main__':
    main()

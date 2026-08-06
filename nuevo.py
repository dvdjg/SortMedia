# -*- coding: utf-8 -*-
r"""
nuevo.py — Clasifica SOLO el contenido nuevo de F:\Clasificado\Incoming\
======================================================================

Cuando quieras añadir contenido nuevo a la biblioteca:
  1. Copia los archivos/carpetas a F:\Clasificado\Incoming\
  2. Ejecuta este script
  3. El script: inventaría lo nuevo, busca duplicados (borrando las copias
     nuevas que ya existan en la biblioteca) y clasifica el resto en el
     árbol. F:\Clasificado\Incoming\ queda limpio al final.

USO:
    python F:\\scripts\\nuevo.py            # procesa Incoming
    python F:\\scripts\\nuevo.py --dry-run  # solo informa
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent
PY = sys.executable


def run(nombre, extra=()):
    print('\n' + '=' * 70)
    print(f'>>> Fase: {nombre}')
    print('=' * 70)
    cmd = [PY, str(SCRIPTS / nombre), *extra]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f'!!! {nombre} falló con código {r.returncode}')
        sys.exit(r.returncode)


def main():
    dry = '--dry-run' in sys.argv
    run('01_inventario.py', ['--raiz', 'F:/Incoming'])
    run('02_duplicados.py', ['--raiz', 'F:/Incoming'] +
        (['--dry-run'] if dry else []))
    run('04_clasificar.py', ['--raiz', 'F:/Incoming'] +
        (['--dry-run'] if dry else []))
    print('\nIncoming procesado. Revisa salida/sospechosos.csv si quieres.')


if __name__ == '__main__':
    main()

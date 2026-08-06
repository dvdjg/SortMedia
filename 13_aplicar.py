# -*- coding: utf-8 -*-
"""
13_aplicar.py — Aplica directorios e índice a las clasificaciones nuevas
========================================================================

Mientras el batch 06_vision corre, este script mueve periódicamente las
imágenes YA clasificadas a sus directorios adecuados y regenera el
índice. Es seguro ejecutarlo en paralelo con 06: solo toca filas que ya
tienen clasificación (06 nunca las vuelve a procesar).

Pasos:
  1. 07_sacar_raras.py      -> NoInteresante / Extranas / Errores
  2. 11_temas.py            -> Imagenes\<Tema>\<Epoca>
  3. 08_indice.py           -> regenera salida/indice.csv + .json

USO:
    python F:\\scripts\\13_aplicar.py
(programado cada 60 min con la tarea "aplicar_clasificadas")
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent
PY = sys.executable


def run(nombre):
    print('=' * 60)
    print('>>>', nombre)
    r = subprocess.run([PY, str(SCRIPTS / nombre)])
    if r.returncode != 0:
        print(f'!!! {nombre} falló ({r.returncode})')
        sys.exit(r.returncode)


if __name__ == '__main__':
    run('07_sacar_raras.py')
    run('11_temas.py')
    run('08_indice.py')
    print('Aplicación de directorios completada.')

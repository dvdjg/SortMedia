# -*- coding: utf-8 -*-
"""
14_watchdog.py — Vigilante del batch de clasificación (auto-reparación)
=======================================================================

Se programa cada 10 minutos (tarea "watchdog_vision"). Comprueba que el
batch 06_vision está avanzando; si lleva ~20 minutos sin clasificar nada
nuevo (GPU atascada o proceso muerto), reinicia automáticamente:
  1. mata el python local del batch,
  2. reinicia Ollama en Legion (limpia generaciones colgadas),
  3. borra las filas de error reintentables,
  4. relanza el batch (vision_run).

USO:
    python F:\\scripts\\14_watchdog.py
(programado cada 10 min con schtasks)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, 'F:/scripts')
import common
from common import conectar

MARCA = common.SALIDA_DIR / 'vision_progreso.txt'
UMBRAL_SEG = 20 * 60  # sin progreso durante 20 min -> reiniciar
CLAVE = r'C:\Users\David\Documents\id_ed25519'
LEGION = '192.168.1.136'
PY = sys.executable


def contar_ok():
    con = conectar()
    n = con.execute(
        'SELECT COUNT(*) FROM vision WHERE json IS NOT NULL').fetchone()[0]
    con.close()
    return n


def proceso_batch_vivo():
    out = subprocess.run(
        ['powershell', '-Command',
         '(Get-Process python -ErrorAction SilentlyContinue).Count'],
        capture_output=True, text=True, timeout=30)
    try:
        return int(out.stdout.strip() or 0) > 0
    except ValueError:
        return False


def reiniciar():
    print('>>> Reiniciando batch (estancamiento detectado)')
    subprocess.run(['powershell', '-Command',
                    'Get-Process python -ErrorAction SilentlyContinue | '
                    'Stop-Process -Force'], timeout=60)
    time.sleep(2)
    subprocess.run(['ssh', '-4', '-i', CLAVE, '-o', 'BatchMode=yes',
                    'dvdjg@' + LEGION,
                    'powershell -Command "Get-Process | Where-Object '
                    '{ $_.ProcessName -like \\"*ollama*\\" } | '
                    'Stop-Process -Force"'], timeout=90)
    time.sleep(3)
    subprocess.run(['ssh', '-4', '-i', CLAVE, '-o', 'BatchMode=yes',
                    'dvdjg@' + LEGION, 'schtasks /run /tn ollama_serve'],
                   timeout=90)
    time.sleep(15)
    # limpiar errores reintentables (archivos existentes)
    con = conectar()
    for r in con.execute('SELECT ruta FROM vision WHERE json IS NULL'):
        ruta = common.ruta_de_db(r['ruta'])
        if os.path.exists(ruta):
            con.execute('DELETE FROM vision WHERE ruta=?', (r['ruta'],))
    con.commit()
    con.close()
    subprocess.run(['schtasks', '/run', '/tn', 'vision_run'], timeout=60)
    print('>>> Batch relanzado')


def main():
    ahora = time.time()
    n = contar_ok()
    ultimo = 0.0
    anterior = None
    if MARCA.exists():
        try:
            lineas = MARCA.read_text(encoding='utf-8').strip().split('\n')
            anterior = int(lineas[-1].split('|')[1])
            ultimo = float(lineas[-1].split('|')[0])
        except (ValueError, IndexError):
            pass
    vivo = proceso_batch_vivo()
    if anterior is not None and n == anterior and \
            (ahora - ultimo) >= UMBRAL_SEG:
        print(f'Sin progreso desde hace {(ahora-ultimo)/60:.0f} min '
              f'({n} filas) -> reiniciando')
        reiniciar()
        n = contar_ok()
    with open(MARCA, 'a', encoding='utf-8') as f:
        f.write(f'{ahora:.0f}|{n}\n')
    print(f'ok={n} | proceso_vivo={vivo} | marca actualizada')


if __name__ == '__main__':
    main()

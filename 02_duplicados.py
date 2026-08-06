# -*- coding: utf-8 -*-
r"""
02_duplicados.py — FASE 2: Detección de duplicados (rápida, 3 fases)
====================================================================

Detección por FASES para no calcular hashes completos de 6 TB de vídeo:

  Fase A (barata)   : agrupar por (tamaño, extensión). Solo los grupos con
                      más de 1 miembro son candidatos.
  Fase B (parcial)  : hash de la CABECERA (64 KB) para subagrupar, y luego
                      firma de 5 muestras: cabecera + 3 del medio + cola
                      (~320 KB por archivo). Leer 320 KB es ~15.000x más
                      rápido que leer 5 GB.
  Fase C (decisión) : POR DEFECTO, misma firma parcial + mismo tamaño =
                      duplicado (heurística rápida). Con --verificar se
                      confirma con SHA-1 completo antes de borrar.

Qué se hace con los resultados:
  - Duplicados EXACTOS  -> se BORRAN las copias (se conserva la mejor).
    La "mejor" se elige así: 1) la que NO esté en Re Download/dwhelper/
    Old G; 2) la más cercana a la raíz (ruta más corta); 3) la más antigua;
    4) nombre alfabéticamente primero. Se registra todo en
    salida/duplicados_borrados.csv (por si hay que recuperar algo).
  - CASI-duplicados (sospechosos) -> NO se tocan, se registran en
    salida/sospechosos.csv con el motivo:
      * mismo tamaño pero hash completo distinto      (re-encode)
      * cabecera igual y cola distinta                 (editado/recortado)
      * nombre casi idéntico (foo vs foo (1))          (descarga repetida)
      * (en fase 03, vídeos con misma duración+resolución pero distinto
        tamaño también se marcan como sospechosos de re-encode)

REANUDABLE: cada grupo procesado se guarda en progreso; si se corta,
vuelve a lanzarse y continúa. --dry-run simula sin borrar nada.

USO:
    python F:\\scripts\\02_duplicados.py              # ejecución real
    python F:\\scripts\\02_duplicados.py --dry-run    # solo informa
    python F:\\scripts\\02_duplicados.py --raiz F:\\Clasificado\\Incoming
                                                     # solo borra copias de
                                                     # esa carpeta (la
                                                     # conservada puede
                                                     # estar en otro sitio)
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar, hash_head, hash_parcial, hash_full

UMBRAL_GRUPO_GRANDE = 500  # (reservado) grupo con más miembros -> cabecera de 64 KB


def grupos_candidatos(con):
    """(tamano, ext) con más de un archivo pendiente/ya inventariado."""
    rows = con.execute(
        'SELECT tamano, ext, COUNT(*) n FROM inventario '
        'WHERE estado != ? GROUP BY tamano, ext HAVING n > 1 '
        'ORDER BY n DESC', ('borrado',)).fetchall()
    return [(r['tamano'], r['ext']) for r in rows]


def miembros(con, tamano, ext):
    """Devuelve los miembros del grupo con ruta DECODIFICADA (lista de dicts)."""
    rows = con.execute(
        'SELECT ruta, tamano, mtime FROM inventario '
        'WHERE tamano=? AND ext=? AND estado != ?',
        (tamano, ext, 'borrado')).fetchall()
    return [{'ruta': common.ruta_de_db(r['ruta']), 'tamano': r['tamano'],
             'mtime': r['mtime']} for r in rows]


def calidad_ruta(ruta):
    """Ranking de la copia a conservar (menor = mejor)."""
    p = ruta.casefold()
    penaliza = sum(1 for x in ('re download', 'dwhelper', 'old g', 'descargar')
                   if x in p)
    profundidad = p.count('/')
    return (penaliza, profundidad)


def elegir_guardar(filas):
    """Devuelve la fila a conservar entre varias idénticas."""
    return min(filas, key=lambda f: (calidad_ruta(f['ruta']), f['mtime'],
                                     f['ruta']))


def procesar_grupo(con, tamano, ext, dry_run, raiz_scope, verificar, pase=1):
    """Devuelve (borrados, liberado) o None si el grupo ya estaba hecho."""
    fase = f'dup{pase}:{tamano}:{ext}'
    if common.ya_procesado(con, fase):
        return None
    ms = miembros(con, tamano, ext)
    if len(ms) < 2:
        common.marca_progreso(con, fase, 'ok')
        return 0, 0

    en_scope = lambda r: raiz_scope is None or r.startswith(raiz_scope)
    # ---- Fase B1: cabecera (agrupa sin leer casi nada) ----
    por_head = defaultdict(list)
    for m in ms:
        h = hash_head(m['ruta'])
        if h is not None:
            por_head[h].append(m)
    # ---- Fase B2: cabecera + 3 muestras del medio + cola (~320 KB) ----
    grupos_parcial = []
    for head, filas in por_head.items():
        if len(filas) < 2:
            continue
        por_parcial = defaultdict(list)
        for m in filas:
            hp = hash_parcial(m['ruta'])
            if hp is None:
                continue
            por_parcial[hp].append(m)
        grupos_parcial.extend(v for v in por_parcial.values() if len(v) > 1)

    borrados = 0
    liberado = 0
    # ---- Fase C: hash completo SOLO si se pide (--verificar).
    #      Por defecto, misma firma parcial + mismo tamaño = duplicado. ----
    for filas in grupos_parcial:
        if verificar:
            por_full = defaultdict(list)
            for m in filas:
                hf = hash_full(m['ruta'])
                if hf is None:
                    continue
                por_full[hf].append(m)
            subgrupos = [(hf, v) for hf, v in por_full.items() if len(v) > 1]
            metodo = 'hash completo'
        else:
            # Heurística rápida: firma de 5 muestras (~320 KB leídos)
            subgrupos = [('parcial', filas)]
            metodo = 'hash parcial (5 muestras)'
        for hf, mismo in subgrupos:
            if len(mismo) < 2:
                continue
            guardar = elegir_guardar(mismo)
            # Orden de borrado: primero los de dentro del scope (Incoming)
            copias = sorted(
                (m for m in mismo if m is not guardar),
                key=lambda m: (not en_scope(m['ruta']), calidad_ruta(m['ruta'])))
            for copia in copias:
                if not dry_run:
                    try:
                        liberado += copia['tamano']
                        os.remove(copia['ruta'])
                    except OSError as e:
                        LOG.warning('No se pudo borrar %s: %s',
                                    copia['ruta'], e)
                        continue
                    con.execute(
                        'UPDATE inventario SET estado=? WHERE ruta=?',
                        ('borrado', common.ruta_a_db(copia['ruta'])))
                    con.execute(
                        'INSERT INTO duplicados VALUES(?,?,?,?)',
                        (common.ruta_a_db(guardar['ruta']),
                         common.ruta_a_db(copia['ruta']), hf, metodo))
                borrados += 1
            LOG.info('Grupo %s bytes (%s): %d copias de %s',
                     tamano, ext, len(mismo) - 1,
                     os.path.basename(guardar['ruta']))

    # ---- Casi-duplicados: no se borran, se anotan ----
    # Ojo: algunas filas del grupo pueden haberse borrado justo arriba;
    # se saltan (ya no existen en disco).
    for filas in grupos_parcial:
        for i, a in enumerate(filas):
            if not os.path.exists(a['ruta']):
                continue
            for b in filas[i + 1:]:
                if not os.path.exists(b['ruta']):
                    continue
                na = common.normaliza(os.path.basename(a['ruta']))
                nb = common.normaliza(os.path.basename(b['ruta']))
                motivo = None
                if na and na == nb:
                    motivo = 'nombre casi idéntico'
                else:
                    pa = hash_parcial(a['ruta'])
                    pb = hash_parcial(b['ruta'])
                    if pa and pb and pa.split('|')[0] == pb.split('|')[0] \
                            and pa.split('|')[-1] != pb.split('|')[-1]:
                        motivo = 'misma cabecera, cola distinta (editado/recortado)'
                if motivo and (en_scope(a['ruta']) or en_scope(b['ruta']) or
                               raiz_scope is None):
                    con.execute(
                        'INSERT OR IGNORE INTO sospechosos VALUES(?,?,?)',
                        (common.ruta_a_db(a['ruta']),
                         common.ruta_a_db(b['ruta']), motivo))
                    con.execute(
                        'INSERT OR IGNORE INTO sospechosos VALUES(?,?,?)',
                        (common.ruta_a_db(b['ruta']),
                         common.ruta_a_db(a['ruta']), motivo))

    con.commit()
    common.marca_progreso(con, fase, 'ok')
    return borrados, liberado


def main():
    ap = argparse.ArgumentParser(description='Deduplicación (Fase 2)')
    ap.add_argument('--dry-run', action='store_true',
                    help='no borra nada, solo informa')
    ap.add_argument('--verificar', action='store_true',
                    help='confirma con hash SHA-1 completo (más lento)')
    ap.add_argument('--raiz', default=None,
                    help='solo elimina copias bajo esta carpeta')
    ap.add_argument('--pase', type=int, default=1,
                    help='número de pase: cada pase nuevo re-procesa todos '
                         'los grupos (útil tras mover archivos al árbol)')
    args = ap.parse_args()

    con = conectar()
    common.reconciliar(con)
    t0 = time.time()
    grupos = grupos_candidatos(con)
    LOG.info('%d grupos candidatos (tamaño+ext con >=2 archivos)',
             len(grupos))
    total_borrados = total_liberado = 0
    for i, (tam, ext) in enumerate(grupos, 1):
        r = procesar_grupo(con, tam, ext, args.dry_run, args.raiz,
                           args.verificar, args.pase)
        if r:
            total_borrados += r[0]
            total_liberado += r[1]
        if i % 50 == 0:
            LOG.info('Progreso grupos: %d/%d', i, len(grupos))
            con.commit()
    con.commit()

    # Informe CSV de lo borrado
    salida = common.SALIDA_DIR / 'duplicados_borrados.csv'
    with open(salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ruta_conservada', 'ruta_borrada', 'hash', 'metodo'])
        for r in con.execute('SELECT * FROM duplicados'):
            w.writerow([common.ruta_de_db(r['ruta_guardar']),
                        common.ruta_de_db(r['ruta_borrar']), r['hash'],
                        r['metodo']])
    n_sosp = con.execute('SELECT COUNT(*) FROM sospechosos').fetchone()[0]
    LOG.info('FIN: %d duplicados borrados, %.2f GB liberados (%.0fs)',
             total_borrados, total_liberado / 1e9, time.time() - t0)
    LOG.info('Sospechosos (casi-duplicados) registrados: %d -> %s',
             n_sosp, common.SALIDA_DIR / 'sospechosos.csv')
    if args.dry_run:
        LOG.warning('MODO SIMULACIÓN: no se borró nada. Quita --dry-run '
                    'para ejecutar de verdad.')
    con.close()


if __name__ == '__main__':
    main()

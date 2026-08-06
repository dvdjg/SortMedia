# -*- coding: utf-8 -*-
r"""
04_clasificar.py — FASE 4: Clasificación y movimiento al árbol nuevo
====================================================================

Para cada archivo pendiente del inventario decide:
  1. TIPO      -> imagen | video | audio | incompleto | otro (por extensión)
  2. CATEGORÍA -> culturismo | general (heurística en common.py)
  3. ÉPOCA     -> Clasico | IA | SinDeterminar (metadatos -> fecha -> nombre)

y lo MUEVE (mismo volumen: instantáneo) a su sitio en F:\Clasificado:

    Clasificado/
    ├── Incoming/                    <- nueva entrada (no se toca aquí)
    ├── Imagenes/  Clasico|IA|SinDeterminar
    ├── Videos/    Clasico|IA|SinDeterminar
    ├── Culturismo/Imagenes/... y Videos/...   <- árbol propio de culturismo
    └── Otros/     Audio|Documentos|Web|Incompletos|Ejecutables|Varios
                   <- contenido no media, aparte para que lo inspecciones

Al terminar limpia las carpetas vacías que quedaron en el origen
(nunca toca David ni Clasificado ni scripts).

MODOS:
    python F:\\scripts\\04_clasificar.py                    # clasifica todo
    python F:\\scripts\\04_clasificar.py --dry-run          # solo informa
    python F:\\scripts\\04_clasificar.py --reclasificar     # repasa TODO lo
        ya movido usando los metadatos (corrige errores de la 1ª pasada)
    python F:\\scripts\\04_clasificar.py --solo-categoria culturismo
    python F:\\scripts\\04_clasificar.py --solo-tipo video
    python F:\\scripts\\04_clasificar.py --raiz F:\\Clasificado\\Incoming
                                                        # solo esa carpeta

REANUDABLE: los archivos ya movidos quedan registrados y se saltan.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar


def decide(row, con):
    """Devuelve (tipo, categoria, epoca, destino, razon). row['ruta'] está
    DECODIFICADA (ruta real del disco)."""
    ruta, nombre = row['ruta'], os.path.basename(row['ruta'])
    tipo = common.tipo_de(row['ext'])
    categoria = 'culturismo' if common.es_culturismo(ruta, nombre) else None
    epoca = None
    razon = ''
    if tipo in ('imagen', 'video'):
        meta = con.execute('SELECT * FROM metadatos WHERE ruta=?',
                           (common.ruta_a_db(ruta),)).fetchone()
        if meta is None:
            # Fallback: la ruta cambió al reclasificar; buscar la ruta
            # anterior en movidos (la fila de metadatos conserva la clave
            # de cuando se extrajo).
            prev = con.execute(
                'SELECT ruta_orig FROM movidos WHERE ruta_dest=?',
                (common.ruta_a_db(ruta),)).fetchone()
            if prev:
                meta = con.execute('SELECT * FROM metadatos WHERE ruta=?',
                                   (prev['ruta_orig'],)).fetchone()
        if meta:
            epoca, razon = common.decidir_epoca(row['mtime'], dict(meta), nombre)
        else:
            epoca, razon = common.decidir_epoca(row['mtime'], None, nombre)
    destino = common.destino_de(tipo, categoria, epoca, nombre)
    return tipo, categoria, epoca, destino, razon


def mover(con, row, destino, dry_run, actualiza_ruta=True):
    ruta = row['ruta']
    nombre = os.path.basename(ruta)
    dest = common.ruta_sin_colision(destino, nombre)
    if dry_run:
        return dest, False
    try:
        os.makedirs(destino, exist_ok=True)
        os.replace(ruta, dest)
    except OSError as e:
        LOG.error('Error moviendo %s -> %s: %s', ruta, dest, e)
        return None, False
    # Registrar el movimiento y actualizar la ruta en el inventario
    nueva = str(dest).replace('\\', '/')
    con.execute('UPDATE inventario SET estado=?, ruta=?, destino=? '
                'WHERE ruta=?',
                ('movido', common.ruta_a_db(nueva), str(destino),
                 common.ruta_a_db(ruta)))
    con.execute('INSERT OR REPLACE INTO movidos(ruta_orig, ruta_dest, fecha) '
                'VALUES(?,?,?)',
                (common.ruta_a_db(ruta), common.ruta_a_db(nueva),
                 time.strftime('%Y-%m-%d %H:%M:%S')))
    # Mantener en sincronía las claves de metadatos (si no, en la
    # siguiente reclasificación se pierde la señal IA/clásico).
    con.execute('UPDATE metadatos SET ruta=? WHERE ruta=?',
                (common.ruta_a_db(nueva), common.ruta_a_db(ruta)))
    return dest, True


def pendientes(con, raiz, solo_categoria, solo_tipo, reclasificar):
    def dec(row):
        d = dict(row)
        d['ruta'] = common.ruta_de_db(row['ruta'])
        return d

    if reclasificar:
        # Repasa los ya movidos: si su época según metadatos cambió, se
        # vuelve a mover. Usamos destino actual para filtrar.
        rows = con.execute(
            'SELECT ruta, tamano, ext, mtime, destino FROM inventario '
            'WHERE estado=?', ('movido',)).fetchall()
    else:
        q = 'SELECT ruta, tamano, ext, mtime, destino FROM inventario WHERE estado=?'
        params = ['pendiente']
        if raiz:
            q += ' AND ruta LIKE ?'
            params.append(common.ruta_a_db(raiz.replace('\\', '/')) + '%')
        rows = con.execute(q, params).fetchall()
    res = []
    for r in rows:
        r = dec(r)
        if solo_categoria:
            cat = 'culturismo' if common.es_culturismo(r['ruta'],
                        os.path.basename(r['ruta'])) else None
            if cat != solo_categoria:
                continue
        t = common.tipo_de(r['ext'])
        if solo_tipo and t != solo_tipo:
            continue
        res.append(r)
    return res


def limpiar_vacios():
    """Elimina carpetas vacías del origen (nunca toca excluidos)."""
    eliminadas = 0
    for raiz in ['F:/']:
        for dirpath, dirs, files in os.walk(raiz, topdown=False):
            dirs[:] = [d for d in dirs if not common.es_raiz_excluida(d)]
            rel = Path(dirpath)
            if any(common.es_raiz_excluida(p) for p in rel.parts):
                continue
            try:
                os.rmdir(dirpath)
                eliminadas += 1
            except OSError:
                pass
    return eliminadas


def main():
    ap = argparse.ArgumentParser(description='Clasificación y movimiento (Fase 4)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--reclasificar', action='store_true')
    ap.add_argument('--solo-categoria', choices=['culturismo'])
    ap.add_argument('--solo-tipo', choices=['imagen', 'video', 'audio',
                                            'incompleto', 'otro'])
    ap.add_argument('--raiz', default=None)
    args = ap.parse_args()

    con = conectar()
    common.reconciliar(con)
    t0 = time.time()
    rows = pendientes(con, args.raiz, args.solo_categoria, args.solo_tipo,
                      args.reclasificar)
    LOG.info('%d archivos a procesar%s', len(rows),
             ' (RECLASIFICACIÓN)' if args.reclasificar else '')
    movidos = 0
    for i, row in enumerate(rows, 1):
        # Archivos de documentación en la raíz: nunca se mueven
        if (os.path.dirname(row['ruta']).replace('\\', '/') == 'F:/'
                and common.ext_of(os.path.basename(row['ruta']))
                in common.PROTEGIDOS_ROOT):
            con.execute('UPDATE inventario SET estado=? WHERE ruta=?',
                        ('fijo', common.ruta_a_db(row['ruta'])))
            continue
        tipo, cat, epoca, destino, razon = decide(row, con)
        if args.reclasificar:
            # destino actual -> si cambia la época, mover
            destino_previo = (common.ruta_de_db(row['destino'])
                              if row['destino'] else None)
            if destino_previo and str(destino_previo) == str(destino):
                continue
        dest, ok = mover(con, row, destino, args.dry_run)
        if ok:
            movidos += 1
            if not args.dry_run and movidos % 200 == 0:
                con.commit()
                LOG.info('%d movidos...', movidos)
        elif args.dry_run:
            LOG.info('  -> %s/%s (%s)  [%s]', destino, os.path.basename(row['ruta']),
                     epoca, razon)
    con.commit()
    if not args.dry_run:
        n = limpiar_vacios()
        LOG.info('Carpetas vacías eliminadas del origen: %d', n)
    LOG.info('FIN: %d archivos movidos en %.0fs', movidos, time.time() - t0)
    if args.dry_run:
        LOG.warning('MODO SIMULACIÓN: no se movió nada.')
    con.close()


if __name__ == '__main__':
    main()

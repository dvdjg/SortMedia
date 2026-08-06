# -*- coding: utf-8 -*-
"""
06_vision.py — Clasificación VLM masiva (reanudable, paralela)
==============================================================

Clasifica TODAS las imágenes de F:\\Clasificado con el modelo de visión
de Ollama (qwen2.5vl:7b) y guarda el resultado en la tabla `vision`
de estado.db. Cada imagen se procesa UNA vez (checkpoint por fila).

Por defecto procesa las carpetas de imágenes del árbol (Imagenes y
Culturismo\\Imagenes). Con --limite N procesa solo las N primeras
(piloto). Es reanudable: vuelve a ejecutarse y continúa.

USO:
    python F:\\scripts\\06_vision.py                 # todo (~24.000)
    python F:\\scripts\\06_vision.py --limite 200    # piloto
    python F:\\scripts\\06_vision.py --workers 6     # concurrencia
    python F:\\scripts\\06_vision.py --modelo qwen2.5vl:7b
    python F:\\scripts\\06_vision.py --reintentar-fallidos
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar

API = 'http://legion:11434/api/generate'
API_LLAMACPP = 'http://legion:8080/v1/chat/completions'
BACKEND = os.environ.get('VLM_BACKEND', 'ollama')  # ollama | llamacpp

EXT = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')


def pendientes(con, limite, reintentar=False):
    """Imágenes sin clasificar (o fallidas si --reintentar)."""
    rows = con.execute(
        "SELECT ruta FROM inventario WHERE estado='movido' AND "
        "destino LIKE '%Imagenes%' AND ext IN "
        "(SELECT value FROM json_each(?))", (json.dumps(list(EXT)),)).fetchall()
    if reintentar:
        done = {r[0] for r in con.execute(
            'SELECT ruta FROM vision WHERE json IS NOT NULL')}
    else:
        done = {r[0] for r in con.execute('SELECT ruta FROM vision')}
    res = [common.ruta_de_db(r['ruta']) for r in rows
           if r['ruta'] not in done]
    if limite:
        res = res[:limite]
    return res


def clasificar_una(ruta):
    """Devuelve (ruta, respuesta_dict|None, error|None)."""
    try:
        with open(ruta, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return ruta, None, f'no se pudo leer: {e}'
    if BACKEND == 'llamacpp':
        cuerpo = {
            'model': args.modelo,
            'messages': [{'role': 'user', 'content': [
                {'type': 'image_url',
                 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
                {'type': 'text',
                 'text': common.construir_prompt_vision(
                     os.path.basename(ruta))},
            ]}],
            'temperature': 0.0,
            'max_tokens': 800,
        }
        api = API_LLAMACPP
    else:
        cuerpo = {'model': args.modelo, 'images': [b64],
                  'prompt': common.construir_prompt_vision(
                      os.path.basename(ruta)),
                  'stream': False,
                  'options': {'temperature': 0.0, 'num_predict': 800}}
        api = API
    req = urllib.request.Request(
        api, data=json.dumps(cuerpo).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
    except Exception as e:
        return ruta, None, str(e)
    if BACKEND == 'llamacpp':
        try:
            resp = d['choices'][0]['message']['content']
        except (KeyError, IndexError):
            return ruta, None, f'respuesta sin contenido: {str(d)[:100]}'
    else:
        resp = (d.get('response') or '').strip()
    # quitar fences de markdown si los hay
    if resp.startswith('```'):
        resp = resp.strip('`')
        resp = resp[resp.find('{'):] if '{' in resp else resp
    # parse tolerante: primer { -> último } (el modelo añade ruido)
    i, j = resp.find('{'), resp.rfind('}')
    for intento in range(2):
        if i != -1 and j > i:
            try:
                data = json.loads(resp[i:j + 1])
                break
            except json.JSONDecodeError:
                data = None
        else:
            data = None
        if intento == 0:
            # reintento: el modelo a veces se equivoca; repetir petición
            resp2 = None
            if BACKEND == 'llamacpp':
                cuerpo['messages'][0]['content'][1]['text'] =                     common.construir_prompt_vision(os.path.basename(ruta))
                api2 = API_LLAMACPP
            else:
                cuerpo['prompt'] = common.construir_prompt_vision(
                    os.path.basename(ruta))
                api2 = API
            try:
                req2 = urllib.request.Request(
                    api2, data=json.dumps(cuerpo).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req2, timeout=300) as r2:
                    d2 = json.loads(r2.read())
                resp2 = (d2.get('response') or '').strip()                     if BACKEND != 'llamacpp' else                     d2['choices'][0]['message']['content'].strip()
                if resp2.startswith('```'):
                    resp2 = resp2.strip('`')
                i, j = resp2.find('{'), resp2.rfind('}')
                resp = resp2
            except Exception:
                resp2 = None
        else:
            return ruta, None, 'JSON inválido tras 2 intentos: ...' + resp[-150:]
    # nombre_sugerido se guarda solo si aplica (heurística del nombre)
    base = os.path.splitext(os.path.basename(ruta))[0]
    sug = (data.get('nombre_sugerido') or '').strip()
    if not common.nombre_raro(base):
        sug = ''
    if sug:
        # saneamos: solo [a-z0-9_-], máx 40
        import re
        sug = re.sub(r'[^a-z0-9_-]+', '_', sug.lower()).strip('_')[:40]
    data['_nombre_sugerido'] = sug
    return ruta, data, None


def main():
    global args
    ap = argparse.ArgumentParser(description='Clasificación VLM (Fase 6)')
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--modelo', default='gemma3:12b')
    ap.add_argument('--reintentar-fallidos', action='store_true')
    ap.add_argument('--escribir-exif', action='store_true',
                    help='escribe EXIF en caliente tras cada clasificación')
    args = ap.parse_args()

    con = conectar()
    pend = pendientes(con, args.limite, args.reintentar_fallidos)
    LOG.info('%d imágenes a clasificar con %s (%d workers)',
             len(pend), args.modelo, args.workers)
    t0 = time.time()
    hechos = 0
    ok = 0
    err = 0
    lote = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futuros = {pool.submit(clasificar_una, r): r for r in pend}
        for fut in as_completed(futuros):
            ruta, data, error = fut.result()
            hechos += 1
            if data:
                ok += 1
                punt, _ = common.calcular_puntuacion(data)
                lote.append((common.ruta_a_db(ruta), args.modelo,
                             json.dumps(data, ensure_ascii=False),
                             json.dumps(data.get('categorias', []),
                                        ensure_ascii=False),
                             json.dumps(data.get('atributos', []),
                                        ensure_ascii=False),
                             data.get('desnudez'), data.get('tipo'),
                             data.get('es_furry'), data.get('es_culturismo'),
                             data.get('resumen', '')[:500],
                             data.get('descripcion', '')[:1500],
                             os.path.basename(ruta)[:250],
                             data.get('_nombre_sugerido'),
                             data.get('es_extraña'),
                             data.get('sexualizacion'),
                             data.get('preservar_titulo'),
                             data.get('fisico'), data.get('vello_corporal'),
                             data.get('guapo'), data.get('joven'),
                             data.get('viril'), data.get('fisico_visible'),
                             data.get('es_familiar'), data.get('menores'),
                             data.get('hay_hombre_atractivo'),
                             data.get('personas'),
                             data.get('estilo'), data.get('posible'),
                             data.get('fantasia_verosimil'),
                             (data.get('defectos') or '')[:300],
                             data.get('organo_imposible'),
                             data.get('violencia'), data.get('admiradores'),
                             punt))
            else:
                err += 1
                lote.append((common.ruta_a_db(ruta), args.modelo,
                             None, None, None, None, None, None, None,
                             ('ERROR: ' + str(error))[:2000], None,
                             os.path.basename(ruta)[:250], None,
                             None, None, None, None, None, None, None,
                             None, None, None, None, None, None, None,
                             None, None, None, None, None, None, None))
            if len(lote) >= 50:
                con.executemany(
                    'INSERT OR REPLACE INTO vision(ruta, modelo, json, '
                    'categorias, atributos, desnudez, tipo, es_furry, '
                    'es_culturismo, resumen, descripcion, nombre_original, '
                    'nombre_sugerido, es_extrana, sexualizacion, preservar_titulo, fisico, '
                    'vello_corporal, guapo, joven, viril, fisico_visible, '
                    'es_familiar, menores, hay_hombre_atractivo, personas, '
                    'estilo, posible, fantasia_verosimil, defectos, '
                    'organo_imposible, violencia, admiradores, puntuacion) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', lote)
                lote = []
                con.commit()
            if data and args.escribir_exif:
                try:
                    common.escribir_metadatos(
                        ruta, data, common.calcular_puntuacion(data)[0],
                        common.nombre_final(os.path.splitext(
                            os.path.basename(ruta))[0], data,
                            common.calcular_puntuacion(data)[0]),
                        args.modelo)
                except Exception as e:
                    LOG.warning('EXIF fallido en %s: %s', ruta, e)
            if hechos % 100 == 0:
                LOG.info('%d/%d | ok=%d err=%d | %.1f s/img',
                         hechos, len(pend), ok, err,
                         (time.time() - t0) / hechos)
    if lote:
        con.executemany(
            'INSERT OR REPLACE INTO vision(ruta, modelo, json, categorias, '
            'atributos, desnudez, tipo, es_furry, es_culturismo, resumen, '
            'descripcion, nombre_original, nombre_sugerido, es_extrana, '
            'sexualizacion, preservar_titulo, fisico, vello_corporal, guapo, joven, viril, '
            'fisico_visible, es_familiar, menores, hay_hombre_atractivo, '
            'personas, estilo, posible, fantasia_verosimil, defectos, '
            'organo_imposible, violencia, admiradores, puntuacion) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', lote)
    con.commit()
    LOG.info('FIN: %d clasificadas (ok=%d err=%d) en %.0fs',
             hechos, ok, err, time.time() - t0)
    con.close()


if __name__ == '__main__':
    main()

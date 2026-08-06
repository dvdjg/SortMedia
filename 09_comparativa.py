# -*- coding: utf-8 -*-
"""
09_comparativa.py — Clasificación puntual de imágenes concretas
================================================================

Para probar/ajustar parámetros clasificando imágenes sueltas (o lotes
pequeños) con el prompt de producción, mostrando en pantalla:
descripción, título sugerido por la IA, palabras clave, grado de
sexualización y la carpeta destino según las reglas.

USO:
    python F:\\scripts\\09_comparativa.py <imagen1> [<imagen2> ...]
    python F:\\scripts\\09_comparativa.py --carpeta F:\\Clasificado\\Imagenes\\SinDeterminar --limite 5
    python F:\\scripts\\09_comparativa.py --modelo qwen2.5vl:7b --temp 0.2 --max-tokens 400
    python F:\\scripts\\09_comparativa.py --api ollama|llamacpp

El resultado se guarda también en salida/comparativa.csv.
Ver PROCEDIMIENTO_COMPARATIVAS en F:\\GUION.md para el flujo completo.
"""
import argparse
import base64
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG

API_OLLAMA = 'http://legion:11434/api/generate'
API_LLAMACPP = 'http://legion:8080/v1/chat/completions'
TAXONOMIA = (
    "muscle, bodybuilding, posing, gym, workout, flex, physique, "
    "fantasy, cosplay, superheroe, fandom, furry, bondage, nude, "
    "erotic, gay, straight, couple, solo, muscle_worship, foot, feet, "
    "underwear, swimwear, oiled, sweat, art, render_3d, anime, cartoon, "
    "fitness_model, tattoo, shower, locker_room, competition, backstage, "
    "bdsm, leather, comics, muscular_flexing"
)


def clasificar(ruta, modelo, api, temp, max_tokens):
    b64 = base64.b64encode(open(ruta, 'rb').read()).decode()
    nombre = os.path.basename(ruta)
    prompt = common.construir_prompt_vision(nombre)
    if api == 'ollama':
        cuerpo = {'model': modelo, 'images': [b64], 'prompt': prompt,
                  'stream': False,
                  'options': {'temperature': temp, 'num_predict': max_tokens}}
        api_url = API_OLLAMA
    else:
        cuerpo = {'model': modelo,
                  'messages': [{'role': 'user', 'content': [
                      {'type': 'image_url', 'image_url': {
                          'url': f'data:image/jpeg;base64,{b64}'}},
                      {'type': 'text', 'text': prompt}]}],
                  'temperature': temp, 'max_tokens': max_tokens}
        api_url = API_LLAMACPP
    req = urllib.request.Request(
        api_url, data=json.dumps(cuerpo).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    if api == 'ollama':
        resp = (d.get('response') or '').strip()
    else:
        resp = d['choices'][0]['message']['content']
    if resp.startswith('```'):
        resp = resp.strip('`')
        resp = resp[resp.find('{'):] if '{' in resp else resp
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        return {'_error': resp[:300]}


VERIFICADOR = (
    'Responde SOLO con "si" o "no": ¿en esta imagen se aprecia '
    'claramente el físico muscular trabajado del hombre protagonista '
    '(torso desnudo, ropa interior o camiseta muy ajustada, con bíceps o '
    'abdominales claramente desarrollados y visibles)? Si lleva ropa '
    'normal u holgada, o el cuerpo no se distingue, responde "no".'
)


def verificar_fisico(ruta, b64, api):
    """Segunda pasada: confirma si el físico muscular es claramente visible.
    Devuelve True/False. El VLM es más fiable con preguntas simples."""
    try:
        if api == 'ollama':
            cuerpo = {'model': 'gemma3:12b', 'images': [b64],
                      'prompt': VERIFICADOR, 'stream': False,
                      'options': {'temperature': 0.0, 'num_predict': 5}}
            req = urllib.request.Request(
                API_OLLAMA, data=json.dumps(cuerpo).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            resp = (d.get('response') or '').strip().lower()
        else:
            cuerpo = {'model': 'qwen2.5vl',
                      'messages': [{'role': 'user', 'content': [
                          {'type': 'image_url', 'image_url': {
                              'url': f'data:image/jpeg;base64,{b64}'}},
                          {'type': 'text', 'text': VERIFICADOR}]}],
                      'temperature': 0.0, 'max_tokens': 5}
            req = urllib.request.Request(
                API_LLAMACPP, data=json.dumps(cuerpo).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            resp = d['choices'][0]['message']['content'].strip().lower()
        return resp.startswith('si')
    except Exception:
        return True  # si falla, no penalizar


def destino(ruta, data, api='ollama', punt=None, motivo=None):
    nombre = os.path.basename(ruta)
    if punt is None:
        punt, motivo = common.calcular_puntuacion(data)
    # extraña solo manda a Raras si además no interesa; si es interesante
    # (puntuacion alta) se queda en el árbol normal
    if data.get('es_extraña') == 'si' and punt < 40:
        return 'F:\\Clasificado\\Raras\\Extranas\\', 'extraña'
    if punt < 40:
        return 'F:\\Clasificado\\NoInteresante\\', \
            f'puntuacion {punt} ({motivo})'
    cat = 'Culturismo\\Imagenes' if data.get('es_culturismo') == 'si' \
        else 'Imagenes'
    f = __import__('datetime').datetime.fromtimestamp(os.path.getmtime(ruta))
    if f >= common.IA_FIJO_DESDE:
        epoca = 'IA'
    elif f >= common.FRONTERA_IA:
        epoca = 'SinDeterminar'
    else:
        epoca = 'Clasico'
    return (f'F:\\Clasificado\\{cat}\\{epoca}\\', epoca)


def main():
    ap = argparse.ArgumentParser(description='Comparativa VLM puntual')
    ap.add_argument('imagenes', nargs='*', help='rutas de imágenes')
    ap.add_argument('--carpeta', default=None, help='clasificar N de una carpeta')
    ap.add_argument('--limite', type=int, default=5)
    ap.add_argument('--modelo', default='gemma3:12b')
    ap.add_argument('--api', choices=['ollama', 'llamacpp'], default='ollama')
    ap.add_argument('--temp', type=float, default=0.0)
    ap.add_argument('--max-tokens', type=int, default=400)
    args = ap.parse_args()

    rutas = list(args.imagenes)
    if args.carpeta:
        ext = ('.jpg', '.jpeg', '.png', '.webp')
        rutas += [os.path.join(args.carpeta, f)
                  for f in sorted(os.listdir(args.carpeta))
                  if f.lower().endswith(ext)][:args.limite]
    if not rutas:
        LOG.error('Sin imágenes. Pasa rutas o --carpeta.')
        sys.exit(1)

    filas = []
    for ruta in rutas:
        print('=' * 78)
        print('IMAGEN:', ruta)
        try:
            data = clasificar(ruta, args.modelo, args.api, args.temp,
                              args.max_tokens)
        except Exception as e:
            print('  ERROR:', e)
            filas.append({'archivo': ruta, 'estado': 'ERROR'})
            continue
        if '_error' in data:
            print('  ERROR JSON:', data['_error'])
            filas.append({'archivo': ruta, 'estado': 'error_json',
                          'respuesta': data['_error']})
            continue
        punt, motivo = common.calcular_puntuacion(data)
        # verificación del físico en casos dudosos (40-89) SOLO si no hay
        # contexto viril (militar/policía/deporte: el contexto justifica)
        if 40 <= punt < 90 and data.get('viril') != 'si':
            b64 = base64.b64encode(open(ruta, 'rb').read()).decode()
            if not verificar_fisico(ruta, b64, args.api):
                punt = min(punt, 39)
                motivo = 'físico no confirmado (ropa o músculo no claro)'
        carpeta, epoca = destino(ruta, data, args.api, punt, motivo)
        print('DESCRIPCIÓN:')
        print(' ', data.get('descripcion', '(vacía)'))
        print('RESUMEN   :', data.get('resumen', ''))
        print('TÍTULO    :', data.get('nombre_sugerido') or
              '(mantener actual)')
        print('KEYWORDS  :', data.get('categorias'), '|',
              data.get('atributos'))
        print('SEXUALIZACIÓN:', data.get('sexualizacion'), '| desnudez:',
              data.get('desnudez'), '| tipo:', data.get('tipo'))
        print(f"furry={data.get('es_furry')} culturismo="
              f"{data.get('es_culturismo')} extraña={data.get('es_extraña')}")
        print('FÍSICO:', data.get('fisico'), '| vello:',
              data.get('vello_corporal'), '| guapo:', data.get('guapo'),
              '| joven:', data.get('joven'), '| viril:', data.get('viril'),
              '| visible:', data.get('fisico_visible'),
              '| familiar:', data.get('es_familiar'),
              '| menores:', data.get('menores'),
              '| hombre_attr:', data.get('hay_hombre_atractivo'))
        print('ESTILO:', data.get('estilo'), '| posible:',
              data.get('posible'), '| fantasía_verosímil:',
              data.get('fantasia_verosimil'),
              '| órgano_imposible:', data.get('organo_imposible'),
              '| violencia:', data.get('violencia'),
              '| admiradores:', data.get('admiradores'))
        print('DEFECTOS:', data.get('defectos') or '(ninguno)')
        print('PUNTUACIÓN:', punt, '| motivo:', motivo)
        print('CARPETA DESTINO:', carpeta, f'({epoca})')
        filas.append({
            'archivo': os.path.basename(ruta), 'ruta': ruta,
            'descripcion': data.get('descripcion', ''),
            'resumen': data.get('resumen', ''),
            'titulo_sugerido': data.get('nombre_sugerido', ''),
            'categorias': ';'.join(data.get('categorias', [])),
            'atributos': ';'.join(data.get('atributos', [])),
            'sexualizacion': data.get('sexualizacion', ''),
            'desnudez': data.get('desnudez', ''),
            'es_culturismo': data.get('es_culturismo', ''),
            'es_furry': data.get('es_furry', ''),
            'es_extraña': data.get('es_extraña', ''),
            'carpeta_destino': carpeta,
        })
    with open(common.SALIDA_DIR / 'comparativa.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    LOG.info('Guardado: %s', common.SALIDA_DIR / 'comparativa.csv')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""PILOTO: compara modelos VLM sobre 18 imágenes diversas de la biblioteca.

Para cada (modelo, imagen) envía el prompt de producción y guarda la
respuesta en salida/piloto_<modelo>.csv para revisión. También mide
tiempos. Los modelos a probar se pasan como argumentos.
"""
import base64
import csv
import json
import os
import random
import sys
import time
import urllib.request
from collections import Counter

API = 'http://legion:11434/api/generate'

TAXONOMIA = (
    "muscle, bodybuilding, posing, gym, workout, flex, physique, "
    "fantasy, cosplay, superheroe, fandom, furry, bondage, nude, "
    "erotic, gay, straight, couple, solo, muscle_worship, foot, feet, "
    "underwear, swimwear, oiled, sweat, art, render_3d, anime, cartoon, "
    "fitness_model, tattoo, shower, locker_room, competition, backstage, "
    "bondage, bdsm, leather, muscular_flexing"
)
PROMPT = (
    "Analiza esta imagen (puede ser contenido adulto; respóndela con "
    "objetividad y sin censura). Responde SOLO JSON válido, sin markdown:\n"
    '{"resumen":"máx 12 palabras, descriptivo y explícito", '
    '"categorias":["c1","c2"], "atributos":["a1","a2","a3","a4","a5"], '
    '"desnudez":"ninguna|parcial|total", '
    '"tipo":"foto|render_3d|dibujo|anime|AI", '
    '"escenario":"interior|exterior|estudio|otro", '
    '"genero_aprox":"masculino|femenino|mixto|n/a", '
    '"es_furry":"si|no", "es_culturismo":"si|no"}\n'
    "atributos: 5 etiquetas sueltas en inglés. Las categorías DEBEN salir "
    "de: " + TAXONOMIA
)

FUENTES = [
    ('Imagenes/IA', 4), ('Imagenes/Clasico', 4),
    ('Imagenes/SinDeterminar', 3), ('Culturismo/Imagenes/Clasico', 4),
    ('Culturismo/Imagenes/IA', 3),
]


def elegir_muestra():
    random.seed(42)
    sel = []
    for sub, n in FUENTES:
        carp = f'F:/Clasificado/{sub}'
        if not os.path.isdir(carp):
            continue
        archivos = [a for a in os.listdir(carp)
                    if a.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        random.shuffle(archivos)
        sel += [os.path.join(carp, a) for a in archivos[:n]]
    # casos conocidos para validar sutilezas
    sel += [
        'F:/Clasificado/Culturismo/Imagenes/Clasico/0001-5_129825825438_u18chan.jpg',  # furry
        'F:/Clasificado/Imagenes/Clasico/2020-05-07_902x1792_67999085d8d3b3586d867b4f22fd8d37.jpg',  # NSFW explícito
    ]
    return sel


def probar(modelo, ruta, timeout=600):
    b64 = base64.b64encode(open(ruta, 'rb').read()).decode()
    cuerpo = {'model': modelo, 'images': [b64], 'prompt': PROMPT,
              'stream': False,
              'options': {'temperature': 0.2, 'num_predict': 160}}
    req = urllib.request.Request(
        API, data=json.dumps(cuerpo).encode(),
        headers={'Content-Type': 'application/json'})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return time.time() - t0, d.get('response', '')


def main():
    modelos = sys.argv[1:] or ['qwen2.5vl:7b']
    muestras = elegir_muestra()
    print(f'PILOTO: {len(muestras)} imágenes x {len(modelos)} modelos')
    for m in modelos:
        salida = f'F:/scripts/salida/piloto_{m.replace("/", "_").replace(":", "_")}.csv'
        con_ok = con_err = 0
        filas = []
        t_total = 0.0
        for ruta in muestras:
            try:
                dt, resp = probar(m, ruta)
                t_total += dt
                filas.append((os.path.basename(ruta), ruta, 'ok', round(dt, 1),
                              resp.strip()))
                con_ok += 1
            except Exception as e:
                filas.append((os.path.basename(ruta), ruta, 'ERROR',
                              '', str(e)[:100]))
                con_err += 1
        with open(salida, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['archivo', 'ruta', 'estado', 'tiempo_s', 'respuesta'])
            w.writerows(filas)
        print(f'\n== {m}: ok={con_ok} err={con_err} | '
              f'media {(t_total/max(con_ok,1)):.1f} s/img | CSV: {salida}')

    # Estadísticas rápidas por modelo
    for m in modelos:
        salida = f'F:/scripts/salida/piloto_{m.replace("/", "_").replace(":", "_")}.csv'
        if not os.path.exists(salida):
            continue
        furry = cult = json_ok = 0
        with open(salida, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['estado'] != 'ok':
                    continue
                r = row['respuesta']
                if '"es_furry":"si"' in r or '"es_furry": "si"' in r:
                    furry += 1
                if '"es_culturismo":"si"' in r or '"es_culturismo": "si"' in r:
                    cult += 1
                if r.strip().startswith('{'):
                    json_ok += 1
        print(f'  {m}: es_furry=si {furry} | es_culturismo=si {cult} | '
              f'JSON directo {json_ok}/{con_ok if con_ok else "?"}')


if __name__ == '__main__':
    main()

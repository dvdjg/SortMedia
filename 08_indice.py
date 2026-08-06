# -*- coding: utf-8 -*-
"""
08_indice.py — Genera el índice de toda la biblioteca
=====================================================

Exporta desde la BD a F:\scripts\salida\:
  indice.csv   -> 1 fila por imagen (compatible Excel/hojas de cálculo)
  indice.json  -> misma información estructurada

Columnas: ubicación (ruta actual), nombre_original, nombre_sugerido,
categorias, atributos, desnudez, tipo, es_furry, es_culturismo, es_extraña,
resumen, descripción, modelo, estado (clasificada/error/pendiente).

Incluye TODAS las imágenes del árbol (clasificadas o no). Se puede volver
a ejecutar en cualquier momento (sobrescribe los ficheros).

USO:
    python F:\\scripts\\08_indice.py
"""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
from common import LOG, conectar


def main():
    con = conectar()
    rows = con.execute(
        "SELECT i.ruta, i.destino, v.json, v.categorias, v.atributos, "
        "v.desnudez, v.tipo, v.es_furry, v.es_culturismo, v.es_extrana, "
        "v.sexualizacion, v.resumen, v.descripcion, v.nombre_original, "
        "v.nombre_sugerido, v.modelo "
        "FROM inventario i LEFT JOIN vision v ON v.ruta = i.ruta "
        "WHERE i.estado='movido' AND i.ext IN "
        "(SELECT value FROM json_each(?)) AND i.destino LIKE '%Imagenes%' "
        "ORDER BY i.destino, i.ruta",
        (json.dumps(list(common.EXT_IMAGEN)),)).fetchall()

    cabecera = ['ubicacion', 'nombre_original', 'nombre_sugerido',
                'categorias', 'atributos', 'desnudez', 'tipo',
                'es_furry', 'es_culturismo', 'es_extraña', 'sexualizacion',
                'resumen', 'descripcion', 'modelo', 'estado']
    filas = []
    for r in rows:
        if r['json'] is None:
            estado = 'pendiente' if r['destino'] and 'Imagenes' in r['destino']                 else 'error'
        else:
            estado = 'clasificada'
        filas.append({
            'ubicacion': common.ruta_de_db(r['ruta']),
            'nombre_original': r['nombre_original'] or
                               os.path.basename(common.ruta_de_db(r['ruta'])),
            'nombre_sugerido': r['nombre_sugerido'] or '',
            'categorias': r['categorias'] or '',
            'atributos': r['atributos'] or '',
            'desnudez': r['desnudez'] or '',
            'tipo': r['tipo'] or '',
            'es_furry': r['es_furry'] or '',
            'es_culturismo': r['es_culturismo'] or '',
            'es_extraña': r['es_extrana'] or '',
            'sexualizacion': r['sexualizacion'] or '',
            'resumen': r['resumen'] or '',
            'descripcion': r['descripcion'] or '',
            'modelo': r['modelo'] or '',
            'estado': estado,
        })

    csv_path = common.SALIDA_DIR / 'indice.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cabecera)
        w.writeheader()
        w.writerows(filas)

    json_path = common.SALIDA_DIR / 'indice.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(filas, f, ensure_ascii=False, indent=1)

    n_clas = sum(1 for x in filas if x['estado'] == 'clasificada')
    n_err = sum(1 for x in filas if x['estado'] == 'error')
    n_pend = sum(1 for x in filas if x['estado'] == 'pendiente')
    n_sug = sum(1 for x in filas if x['nombre_sugerido'])
    LOG.info('Índice: %d imágenes (clasificadas=%d, errores=%d, '
             'pendientes=%d) | con nombre sugerido: %d',
             len(filas), n_clas, n_err, n_pend, n_sug)
    LOG.info('CSV: %s | JSON: %s', csv_path, json_path)
    con.close()


if __name__ == '__main__':
    main()

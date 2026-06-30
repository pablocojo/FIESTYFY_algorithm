import sys
import os
import json
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datos_ine import cargar_datos_ine, limpiar_nombre_ine, _normalizar
from parte1_municipios.municipios import procesar_municipio_base

MUNICIPIOS_JSON = "municipios.json"

with open(MUNICIPIOS_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)
    lugares_actuales = data.get('lugares', [])

nuevos_lugares = []

def agregar_si_falta(nombre, prov, url):
    print(f"-> Procesando manual: {nombre} ({prov})")
    lugar, _ = procesar_municipio_base({'nombre': nombre, 'article_url': url})
    if lugar:
        lugar['provincia'] = prov
        nuevos_lugares.append(lugar)
        print("   OK")
    else:
        print("   FALLO")

# Ceuta y Melilla a mano
agregar_si_falta("Ceuta", "Ceuta", "https://es.wikipedia.org/wiki/Ceuta")
agregar_si_falta("Melilla", "Melilla", "https://es.wikipedia.org/wiki/Melilla")

if nuevos_lugares:
    data['lugares'].extend(nuevos_lugares)
    with open(MUNICIPIOS_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Se han añadido {len(nuevos_lugares)} municipios. Total ahora: {len(data['lugares'])}")

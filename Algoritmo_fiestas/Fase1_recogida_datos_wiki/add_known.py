import sys
import os
import json
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from parte1_municipios.municipios import procesar_municipio_base
from scraper import get_soup, fetch_url
from urllib.parse import urljoin

MUNICIPIOS_JSON = "municipios.json"

with open(MUNICIPIOS_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)

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

faltantes_conocidos = [
    ("El Campillo", "Valladolid", "https://es.wikipedia.org/wiki/El_Campillo_(Valladolid)"),
    ("La Seca", "Valladolid", "https://es.wikipedia.org/wiki/La_Seca_(Valladolid)"),
    ("La Zarza", "Valladolid", "https://es.wikipedia.org/wiki/La_Zarza_(Valladolid)"),
    ("La Guardia", "Toledo", "https://es.wikipedia.org/wiki/La_Guardia_(Toledo)"),
    ("La Mata", "Toledo", "https://es.wikipedia.org/wiki/La_Mata_(Toledo)"),
    ("Fonfría", "Zamora", "https://es.wikipedia.org/wiki/Fonfr%C3%ADa_(Zamora)"),
    ("El Pego", "Zamora", "https://es.wikipedia.org/wiki/El_Pego_(Zamora)"),
    ("Sancti-Spíritus", "Salamanca", "https://es.wikipedia.org/wiki/Sancti-Sp%C3%ADritus_(Salamanca)"),
    ("Arroyomolinos", "Madrid", "https://es.wikipedia.org/wiki/Arroyomolinos_(Madrid)"),
    ("El Álamo", "Madrid", "https://es.wikipedia.org/wiki/El_%C3%81lamo_(Madrid)"),
    ("El Boalo", "Madrid", "https://es.wikipedia.org/wiki/El_Boalo"),
]

for nombre, prov, url in faltantes_conocidos:
    agregar_si_falta(nombre, prov, url)
    time.sleep(1)

if nuevos_lugares:
    data['lugares'].extend(nuevos_lugares)
    with open(MUNICIPIOS_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Se han añadido {len(nuevos_lugares)} municipios.")

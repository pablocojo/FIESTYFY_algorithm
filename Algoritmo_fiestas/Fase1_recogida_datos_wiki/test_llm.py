import sys
sys.stdout.reconfigure(encoding='utf-8')

from config import MUNICIPIOS_JSON
from main2 import cargar_json_lugares
from datos_ine import cargar_datos_ine, buscar_municipio_ine
from scraper import fetch_url

datos_ine = cargar_datos_ine()
m = cargar_json_lugares(MUNICIPIOS_JSON)[0]
print(f"Procesando: {m['nombre']}")

# Sin HTML
info = buscar_municipio_ine(m['nombre'], m['provincia'], datos_ine)
print(f"Info exacta: {bool(info)}")

# Con HTML (LLM fallback con lista de candidatos)
wiki_url = m.get('wikipedia_url')
print(f"URL: {wiki_url}")
html = fetch_url(wiki_url)
info = buscar_municipio_ine(m['nombre'], m['provincia'], datos_ine, html)
print(f"Info con LLM: {bool(info)}")
if info:
    print(f"  nombre_ine: {info['nombre_ine']}")
    print(f"  clave: {info['clave']}")

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from parte2_distritos_pedanias.distritos_pedanias import procesar_pedanias_ine, DATOS_INE_GLOBAL
from datos_ine import cargar_datos_ine
import parte2_distritos_pedanias.distritos_pedanias as dp_module

datos_ine = cargar_datos_ine()
dp_module.DATOS_INE_GLOBAL = datos_ine

lugar = {
    "id": "asparrena",
    "nombre": "Aspárrena",
    "provincia": "Álava",
    "tipo": "municipio_compuesto",
    "cpro": "01",
    "cmun": "009",
    "wikipedia_url": "https://es.wikipedia.org/wiki/Asp%C3%A1rrena"
}

from scraper import fetch_url
html_municipio = fetch_url(lugar["wikipedia_url"])

print("Iniciando prueba de Aspárrena...")
resultados = procesar_pedanias_ine(lugar, html_municipio)

print(f"\nResultados ({len(resultados)}):")
for r in resultados:
    wiki = "CON WIKI" if r.get('wikipedia_url') else "SOLO INE"
    print(f" - {r.get('nombre')}: {wiki} -> {r.get('wikipedia_url', '')}")

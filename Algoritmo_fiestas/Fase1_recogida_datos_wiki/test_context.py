import os
import sys

from parte2_distritos_pedanias.distritos_pedanias import _contexto_articulo_para_verificacion, _validar_url_pedania_llm
from scraper import fetch_url

for url, pedania_nombre, municipio_nombre in [('https://es.wikipedia.org/wiki/Gordoa', 'GORDOA', 'Aspárrena'), ('https://es.wikipedia.org/wiki/Ibarguren', 'IBARGUREN', 'Aspárrena')]:
    html = fetch_url(url)
    print(f"\n--- {pedania_nombre} ---")
    ctx = _contexto_articulo_para_verificacion(html)
    print("CONTEXT LENGTH:", len(ctx))
    res = _validar_url_pedania_llm(url, html, municipio_nombre, pedania_nombre)
    print("VALIDATION RESULT:", res)

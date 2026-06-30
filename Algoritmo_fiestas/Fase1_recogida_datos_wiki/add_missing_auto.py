import sys
import os
import json
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datos_ine import cargar_datos_ine, limpiar_nombre_ine, _normalizar
from parte1_municipios.municipios import procesar_municipio_base

MUNICIPIOS_JSON = "municipios.json"

datos_ine = cargar_datos_ine()
municipios_ine = datos_ine.get("municipios", {})

with open('municipios.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    municipios_wiki = data.get('lugares', [])

# Map of prov -> set of normalized names
wiki_map = {}
for m in municipios_wiki:
    prov = _normalizar(m.get('provincia', ''))
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    elif 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    elif 'coruna' in prov: prov = 'acoruna'
    elif 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    elif 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    elif 'valencia' in prov: prov = 'valencia'
    elif 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    elif 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    elif 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    elif 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    elif 'rioja' in prov: prov = 'larioja'
    elif 'asturias' in prov: prov = 'asturias'
    elif 'palmas' in prov: prov = 'laspalmas'
    elif 'tenerife' in prov: prov = 'santacruzdetenerife'
    elif 'madrid' in prov: prov = 'madrid'
    elif 'murcia' in prov: prov = 'murcia'
    elif 'girona' in prov or 'gerona' in prov: prov = 'gerona'
    elif 'lleida' in prov or 'lerida' in prov: prov = 'lerida'
    
    if prov not in wiki_map: wiki_map[prov] = set()
    wiki_map[prov].add(_normalizar(m['nombre']))
    # Add tokens just to be safe
    for tok in _normalizar(m['nombre']).split():
        if len(tok) > 4: wiki_map[prov].add(tok)

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

# Provincias donde sabemos que hay faltantes:
provincias_objetivo = ['valladolid', 'toledo', 'zamora', 'cuenca', 'salamanca', 'madrid', 'murcia', 'navarra', 'leon', 'tarragona', 'asturias', 'soria', 'laspalmas', 'santacruzdetenerife']

procesados = 0
for (cpro, cmun), m_ine in municipios_ine.items():
    prov = _normalizar(m_ine.get('provincia', ''))
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    elif 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    elif 'coruna' in prov: prov = 'acoruna'
    elif 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    elif 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    elif 'valencia' in prov: prov = 'valencia'
    elif 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    elif 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    elif 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    elif 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    elif 'rioja' in prov: prov = 'larioja'
    elif 'asturias' in prov: prov = 'asturias'
    elif 'palmas' in prov: prov = 'laspalmas'
    elif 'tenerife' in prov: prov = 'santacruzdetenerife'
    elif 'madrid' in prov: prov = 'madrid'
    elif 'murcia' in prov: prov = 'murcia'
    elif 'girona' in prov or 'gerona' in prov: prov = 'gerona'
    elif 'lleida' in prov or 'lerida' in prov: prov = 'lerida'
    
    if prov not in provincias_objetivo:
        continue
        
    nombre_ine = m_ine.get('nombre', '')
    if not nombre_ine: continue
    
    nombres_limpios = limpiar_nombre_ine(nombre_ine)
    wset = wiki_map.get(prov, set())
    
    encontrado = False
    # Exact match
    for n in nombres_limpios:
        if _normalizar(n) in wset:
            encontrado = True
            break
            
    # Substring match if name is long
    if not encontrado:
        main_word = _normalizar(nombres_limpios[0])
        if len(main_word) > 5 and main_word in wset:
            encontrado = True
            
    if not encontrado:
        print(f"Detectado FALTANTE: {nombre_ine} ({prov})")
        import requests
        from urllib.parse import urljoin
        
        nombre_buscar = nombres_limpios[0]
        url_api = f"https://es.wikipedia.org/w/api.php?action=query&list=search&format=json&srsearch={nombre_buscar} provincia de {prov}"
        try:
            headers = {'User-Agent': 'fiestyfy/1.0 (sainzmartinp@gmail.com)'}
            r = requests.get(url_api, headers=headers, timeout=10)
            res = r.json().get('query', {}).get('search', [])
            if res:
                title = res[0]['title']
                url = urljoin("https://es.wikipedia.org/wiki/", title.replace(" ", "_"))
                agregar_si_falta(nombre_buscar, m_ine.get('provincia'), url)
                procesados += 1
                if procesados >= 18:
                    break
            else:
                print("   No encontrado en Wiki API")
        except Exception as e:
            print("Error buscando:", e)

if nuevos_lugares:
    data['lugares'].extend(nuevos_lugares)
    with open('municipios.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Se han añadido {len(nuevos_lugares)} municipios. Total ahora: {len(data['lugares'])}")

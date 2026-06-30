import sys
import os
import json
import difflib

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datos_ine import cargar_datos_ine, _normalizar

datos_ine = cargar_datos_ine()
municipios_ine = datos_ine.get("municipios", {})

with open('municipios.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    municipios_wiki = data.get('lugares', [])

# Agrupar wiki por provincia
wiki_por_prov = {}
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
    
    if prov not in wiki_por_prov: wiki_por_prov[prov] = []
    wiki_por_prov[prov].append(_normalizar(m['nombre']))

faltantes = []
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

    nombre_ine = m_ine.get('nombre', '')
    if not nombre_ine: continue
    nombre_norm = _normalizar(nombre_ine)
    
    w_list = wiki_por_prov.get(prov, [])
    
    # Fuzzy match
    matches = difflib.get_close_matches(nombre_norm, w_list, n=1, cutoff=0.75)
    
    if not matches:
        # Intenta partiendo por slash
        nombres_ine = [n.strip() for n in nombre_ine.split('/')]
        encontrado = False
        for ni in nombres_ine:
            if difflib.get_close_matches(_normalizar(ni), w_list, n=1, cutoff=0.85):
                encontrado = True
                break
        
        if not encontrado:
            faltantes.append(f"{nombre_ine} ({m_ine.get('provincia', '')})")

print(f"Total faltantes: {len(faltantes)}")
for f in faltantes:
    print(f)

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datos_ine import cargar_datos_ine, _normalizar

datos_ine = cargar_datos_ine()
municipios_ine = datos_ine.get("municipios", {})

with open('municipios.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    municipios_wiki = data.get('lugares', [])

# Agrupar por provincia normalizada en INE
count_ine = {}
for m_ine in municipios_ine.values():
    prov = _normalizar(m_ine.get('provincia', ''))
    # Normalizar para juntar Álava/Araba, etc
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    if 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    if 'coruna' in prov: prov = 'a coruna'
    if 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    if 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    if 'valencia' in prov: prov = 'valencia'
    if 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    if 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    if 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    if 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    
    count_ine[prov] = count_ine.get(prov, 0) + 1

# Agrupar por provincia normalizada en Wiki
count_wiki = {}
for m in municipios_wiki:
    prov = _normalizar(m.get('provincia', ''))
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    if 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    if 'coruna' in prov: prov = 'a coruna'
    if 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    if 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    if 'valencia' in prov: prov = 'valencia'
    if 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    if 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    if 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    if 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    
    count_wiki[prov] = count_wiki.get(prov, 0) + 1

print("Provincias con diferencias:")
for prov in set(list(count_ine.keys()) + list(count_wiki.keys())):
    c_ine = count_ine.get(prov, 0)
    c_wiki = count_wiki.get(prov, 0)
    if c_ine != c_wiki:
        print(f" - {prov}: INE={c_ine}, WIKI={c_wiki} (Dif: {c_ine - c_wiki})")

import sys
import os
import json
import re
import unicodedata

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datos_ine import cargar_datos_ine

def _normalizar(texto):
    if not texto: return ""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "", t.lower())
    return t

datos_ine = cargar_datos_ine()
municipios_ine = datos_ine.get("municipios", {})

with open('municipios.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    municipios_wiki = data.get('lugares', [])

# Agrupar wiki por provincia normalizada
wiki_por_prov = {}
for m in municipios_wiki:
    prov = _normalizar(m.get('provincia', ''))
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    if 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    if 'coruna' in prov: prov = 'acoruna'
    if 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    if 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    if 'valencia' in prov: prov = 'valencia'
    if 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    if 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    if 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    if 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    if 'rioja' in prov: prov = 'larioja'
    if 'asturias' in prov: prov = 'asturias'
    if 'palmas' in prov: prov = 'laspalmas'
    if 'tenerife' in prov: prov = 'santacruzdetenerife'
    if 'madrid' in prov: prov = 'madrid'
    if 'murcia' in prov: prov = 'murcia'
    if 'girona' in prov or 'gerona' in prov: prov = 'gerona'
    if 'lleida' in prov or 'lerida' in prov: prov = 'lerida'
    
    if prov not in wiki_por_prov:
        wiki_por_prov[prov] = []
    
    wiki_por_prov[prov].append({
        'nombre_norm': _normalizar(m['nombre']),
        'nombre': m['nombre']
    })

faltantes = []
for (cpro, cmun), m_ine in municipios_ine.items():
    prov = _normalizar(m_ine.get('provincia', ''))
    if 'alava' in prov or 'araba' in prov: prov = 'alava'
    if 'alicante' in prov or 'alacant' in prov: prov = 'alicante'
    if 'coruna' in prov: prov = 'acoruna'
    if 'baleares' in prov or 'balears' in prov: prov = 'baleares'
    if 'castellon' in prov or 'castello' in prov: prov = 'castellon'
    if 'valencia' in prov: prov = 'valencia'
    if 'gipuzkoa' in prov or 'guipuzcoa' in prov: prov = 'guipuzcoa'
    if 'bizkaia' in prov or 'vizcaya' in prov: prov = 'vizcaya'
    if 'navarra' in prov or 'nafarroa' in prov: prov = 'navarra'
    if 'ourense' in prov or 'orense' in prov: prov = 'ourense'
    if 'rioja' in prov: prov = 'larioja'
    if 'asturias' in prov: prov = 'asturias'
    if 'palmas' in prov: prov = 'laspalmas'
    if 'tenerife' in prov: prov = 'santacruzdetenerife'
    if 'madrid' in prov: prov = 'madrid'
    if 'murcia' in prov: prov = 'murcia'
    if 'girona' in prov or 'gerona' in prov: prov = 'gerona'
    if 'lleida' in prov or 'lerida' in prov: prov = 'lerida'

    nombre_ine = m_ine.get('nombre', '')
    if not nombre_ine: continue
    nombre_norm = _normalizar(nombre_ine)
    
    # Extraer parte en castellano si hay slash
    nombres_separados = [n.strip() for n in nombre_ine.split('/')]
    nombres_norm = [_normalizar(n) for n in nombres_separados]
    
    wiki_list = wiki_por_prov.get(prov, [])
    
    encontrado = False
    for wk in wiki_list:
        wk_norm = wk['nombre_norm']
        if wk_norm in nombres_norm or any(n in wk_norm for n in nombres_norm if len(n)>3):
            encontrado = True
            break
            
    if not encontrado:
        faltantes.append(f"{nombre_ine} ({m_ine.get('provincia', '')})")

print(f"Total faltantes: {len(faltantes)}")
for f in faltantes:
    print(" - " + f)

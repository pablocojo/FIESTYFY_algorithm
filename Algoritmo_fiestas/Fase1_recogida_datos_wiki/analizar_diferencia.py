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

wiki_nombres = set()
for m in municipios_wiki:
    wiki_nombres.add(_normalizar(m['nombre']))

faltantes = []
for (cpro, cmun), m_ine in municipios_ine.items():
    nombre_ine = m_ine.get('nombre', '')
    if not nombre_ine: continue
    nombre_norm = _normalizar(nombre_ine)
    
    encontrado = False
    for wk in wiki_nombres:
        if nombre_norm == wk or (len(nombre_norm)>5 and nombre_norm in wk) or (len(wk)>5 and wk in nombre_norm):
            encontrado = True
            break
            
    if not encontrado:
        faltantes.append(f"{nombre_ine} ({m_ine.get('provincia', '')})")

print(f"Total en INE: {len(municipios_ine)}")
print(f"Total en Wiki JSON: {len(municipios_wiki)}")
print(f"Faltantes estimados por nombre ({len(faltantes)}):")
for f in faltantes[:30]:
    print(" - " + f)

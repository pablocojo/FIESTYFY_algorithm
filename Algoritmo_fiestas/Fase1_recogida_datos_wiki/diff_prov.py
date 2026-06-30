import json
import difflib
from datos_ine import cargar_datos_ine, _normalizar

ine = cargar_datos_ine()["municipios"]
with open('municipios.json', 'r', encoding='utf-8') as f:
    wiki = json.load(f)["lugares"]

def get_prov(m):
    return _normalizar(m.get('provincia', ''))

for prov_target in ['valladolid', 'toledo', 'zamora', 'cuenca', 'salamanca', 'madrid']:
    ine_prov = [m['nombre'] for m in ine.values() if get_prov(m) == prov_target]
    wiki_prov = [m['nombre'] for m in wiki if get_prov(m) == prov_target]
    
    ine_prov.sort()
    wiki_prov.sort()
    
    missing = []
    for n_ine in ine_prov:
        if not difflib.get_close_matches(n_ine, wiki_prov, n=1, cutoff=0.6):
            missing.append(n_ine)
    print(f"--- {prov_target} ---")
    for m in missing:
        print(m)

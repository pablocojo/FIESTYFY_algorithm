import json
from collections import defaultdict

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
    lugares_muni = data_muni.get('lugares', [])
    nombres_muni = [l.get('nombre') for l in lugares_muni]
    
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data_esp = json.load(f)
    lugares_esp = data_esp.get('lugares', [])
    
    nombres_esp = set(l.get('nombre') for l in lugares_esp if l.get('tipo') == 'municipio')
    
    last_processed_name = ""
    for l in reversed(lugares_esp):
        if l.get('tipo') == 'municipio':
            last_processed_name = l.get('nombre')
            break
            
    last_idx = nombres_muni.index(last_processed_name) if last_processed_name in nombres_muni else -1
    limit = last_idx + 1 if last_idx != -1 else len(nombres_muni)
    
    skipped = []
    skipped_by_prov = defaultdict(list)
    
    for i in range(limit):
        m = lugares_muni[i]
        nombre = m.get('nombre')
        if nombre not in nombres_esp:
            skipped.append(m)
            prov = m.get('provincia', 'Desconocida')
            skipped_by_prov[prov].append(nombre)
            
    with open('temp_grouped.txt', 'w', encoding='utf-8') as f:
        f.write(f"Total procesados (hasta {last_processed_name}): {limit}\n")
        f.write(f"Total saltados: {len(skipped)}\n\n")
        for prov, names in skipped_by_prov.items():
            f.write(f"=== {prov} ({len(names)}) ===\n")
            for n in names:
                f.write(f" - {n}\n")
                
except Exception as e:
    print('Error:', e)

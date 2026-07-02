import json

try:
    # 1. Load municipios.json (source)
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
    nombres_muni = [l.get('nombre') for l in data_muni.get('lugares', [])]
    
    # 2. Load lugares_espana.json (destination)
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data_esp = json.load(f)
    lugares_esp = data_esp.get('lugares', [])
    
    # Extract names of root municipalities in lugares_espana
    # In lugares_espana, the root is always tipo="municipio" (or maybe we just get all names?)
    # Let's get ALL names of root elements. Wait, main2.py transforms the root to 'municipio'.
    nombres_esp = set(l.get('nombre') for l in lugares_esp if l.get('tipo') == 'municipio')
    
    # If the file hasn't finished, we should only compare up to the last processed element.
    # What was the last processed element?
    last_processed_name = ""
    for l in reversed(lugares_esp):
        if l.get('tipo') == 'municipio':
            last_processed_name = l.get('nombre')
            break
            
    # Find the index of this last processed element in municipios.json
    try:
        last_idx = nombres_muni.index(last_processed_name)
    except ValueError:
        last_idx = -1
        
    print(f"Total en municipios.json: {len(nombres_muni)}")
    print(f"Total 'municipio' en lugares_espana.json: {len(nombres_esp)}")
    print(f"Último procesado: {last_processed_name} (índice en municipios.json: {last_idx})")
    
    # Find skipped
    skipped = []
    # If the file is incomplete, we should probably only check up to last_idx
    limit = last_idx + 1 if last_idx != -1 else len(nombres_muni)
    
    for nombre in nombres_muni[:limit]:
        if nombre not in nombres_esp:
            skipped.append(nombre)
            
    print(f"Saltados (hasta el índice {limit}): {len(skipped)}")
    for s in skipped:
        print(f" - {s}")

except Exception as e:
    print('Error:', e)

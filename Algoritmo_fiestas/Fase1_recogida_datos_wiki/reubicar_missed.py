import json

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data_esp = json.load(f)
        
    nombres_procesados = set(l.get('nombre') for l in data_esp['lugares'] if l.get('tipo') == 'municipio')
    
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
        
    lugares_muni = data_muni.get('lugares', [])
    
    # Check what is the last processed name
    ultimos = [l for l in data_esp['lugares'] if l.get('tipo') == 'municipio']
    ultimo = ultimos[-1] if ultimos else None
    
    start_idx = len(lugares_muni)
    if ultimo:
        for i, m in enumerate(lugares_muni):
            if m.get('nombre') == ultimo.get('nombre') or m.get('id') == ultimo.get('original_id'):
                start_idx = i + 1
                break
                
    # Now, take all elements before start_idx that are NOT in nombres_procesados, and move them to the end
    nuevos_lugares = []
    reubicados_extra = []
    
    for i, m in enumerate(lugares_muni):
        if i < start_idx:
            # Esta zona ya fue "pasada" por main2.py
            if m.get('nombre') not in nombres_procesados:
                reubicados_extra.append(m)
            else:
                nuevos_lugares.append(m)
        else:
            # Esta zona aun no ha sido pasada
            nuevos_lugares.append(m)
            
    # Add the ones we missed to the end
    data_muni['lugares'] = nuevos_lugares + reubicados_extra
    
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'w', encoding='utf-8') as f:
        json.dump(data_muni, f, ensure_ascii=False, indent=2)
        
    print(f"Hecho. Reubicados extra (saltados en la primera pasada): {len(reubicados_extra)}")
    if reubicados_extra:
        for r in reubicados_extra[:5]:
            print(f" - {r.get('nombre')}")

except Exception as e:
    print('Error:', e)

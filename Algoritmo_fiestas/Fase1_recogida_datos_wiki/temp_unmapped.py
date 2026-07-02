import json
import codecs

try:
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios_actualizado.json', 'r', 'utf-8') as f:
        data_wiki = json.load(f)
    lugares_wiki = data_wiki.get('lugares', [])
    
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', 'utf-8') as f:
        data_esp = json.load(f)
    lugares_espana = data_esp.get('lugares', [])
    
    # In lugares_espana, root municipalities have tipo == 'municipio' and original_id is the old id
    mapped_ids = set()
    mapped_names = set()
    for l in lugares_espana:
        if l.get('tipo') == 'municipio':
            if l.get('original_id'):
                mapped_ids.add(l.get('original_id'))
            elif l.get('id'): # some might just have id mapped differently?
                mapped_ids.add(l.get('id'))
            mapped_names.add(l.get('nombre'))
            
    # Which ones in wiki are not mapped?
    unmapped = []
    for w in lugares_wiki:
        wid = w.get('id')
        wn = w.get('nombre')
        # Check by id or by exact name
        if wid not in mapped_ids and wn not in mapped_names:
            unmapped.append(w)
            
    print(f'Total in wiki: {len(lugares_wiki)}')
    print(f'Total mapped (municipios): {len(mapped_ids)}')
    print(f'Total unmapped: {len(unmapped)}')
    
    # Print the unmapped ones
    for u in unmapped[:50]:
        print(f" - {u.get('nombre')} ({u.get('provincia')}) [id: {u.get('id')}]")
        
    if len(unmapped) > 50:
        print(f'... y {len(unmapped) - 50} mas.')
        
except Exception as e:
    print('Error:', e)

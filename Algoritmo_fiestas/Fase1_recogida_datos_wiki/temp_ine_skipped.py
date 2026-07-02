import json
import codecs

try:
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', 'utf-8') as f:
        data_esp = json.load(f)
    lugares_espana = data_esp.get('lugares', [])
    
    municipios = [l for l in lugares_espana if l.get('tipo') == 'municipio']
    if not municipios:
        print('No municipios in lugares_espana.json')
    else:
        last_m = municipios[-1]
        print(f"Last processed: {last_m.get('nombre')} ({last_m.get('original_id')})")
        print(f"Total municipios processed successfully: {len(municipios)}")
        
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios_actualizado.json', 'r', 'utf-8') as f:
        data_wiki = json.load(f)
    lugares_wiki = data_wiki.get('lugares', [])
    
    # Find index in wiki
    last_id = last_m.get('original_id') or last_m.get('id')
    last_idx = -1
    for i, w in enumerate(lugares_wiki):
        if w.get('id') == last_id or w.get('id') == last_m.get('original_id'):
            last_idx = i
            break
            
    print(f"Index of last processed in wiki: {last_idx}")
    if last_idx != -1:
        total_attempted = last_idx + 1
        success = len(municipios)
        skipped = total_attempted - success
        print(f"Total attempted: {total_attempted}")
        print(f"Total success: {success}")
        print(f"Total skipped (not found in INE): {skipped}")
        
except Exception as e:
    print('Error:', e)

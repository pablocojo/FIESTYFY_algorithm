import json
import codecs

try:
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', 'utf-8') as f:
        data_esp = json.load(f)
    lugares_espana = data_esp.get('lugares', [])
    
    mapped_ids = set([l.get('original_id') for l in lugares_espana if l.get('tipo') == 'municipio' and l.get('original_id')])
    
    with codecs.open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios_actualizado.json', 'r', 'utf-8') as f:
        data_wiki = json.load(f)
    lugares_wiki = data_wiki.get('lugares', [])
    
    skipped = []
    for i in range(386):
        w = lugares_wiki[i]
        if w.get('id') not in mapped_ids:
            skipped.append(w)
            
    for s in skipped:
        print(f" - {s.get('nombre')} ({s.get('provincia')})")
        
except Exception as e:
    print('Error:', e)

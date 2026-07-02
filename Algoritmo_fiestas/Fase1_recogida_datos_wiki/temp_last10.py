import json

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lugares = data.get('lugares', [])
    
    print('Last 10 elements in lugares_espana.json:')
    for l in lugares[-10:]:
        print(f" - {l.get('nombre')} | tipo: {l.get('tipo')} | id: {l.get('id')} | orig: {l.get('original_id')}")
        
except Exception as e:
    print('Error:', e)

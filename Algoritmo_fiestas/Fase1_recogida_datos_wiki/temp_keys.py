import json

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lugares = data.get('lugares', [])
    
    keys = set()
    for l in lugares:
        keys.update(l.keys())
        
    print(f'All keys in lugares_espana.json: {keys}')
    
    # check if any places have 'ine_id' = null, or something
    for l in lugares[:5]:
        print(l.get('nombre'), l.get('tipo'), l.get('padre_id'))
        
except Exception as e:
    print('Error:', e)

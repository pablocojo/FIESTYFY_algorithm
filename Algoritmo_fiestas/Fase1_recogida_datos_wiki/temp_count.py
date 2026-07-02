import json

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lugares = data.get('lugares', [])
    
    saltados = [l for l in lugares if l.get('tipo') in ('ciudad_grande', 'ciudad_pequena') and l.get('poblacion', 0) > 102986 and l.get('nombre') != 'Roquetas de Mar']
    
    print(f'Ciudades saltadas: {len(saltados)}')
    for c in saltados:
        print(f" - {c.get('nombre')} ({c.get('poblacion')} hab.)")
        
except Exception as e:
    print('Error:', e)

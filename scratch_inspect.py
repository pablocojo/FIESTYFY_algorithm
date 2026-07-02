import json

with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios_actualizado.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

lugares = data.get('lugares', [])
print('Total lugares:', len(lugares))
print('\nItems around index 8090-8105:')
for i in range(8090, min(8105, len(lugares))):
    item = lugares[i]
    print(f"Index {i}: {item.get('nombre')} - id: {item.get('id')} - tipo: {item.get('tipo')} - padre_id: {item.get('padre_id', 'N/A')}")

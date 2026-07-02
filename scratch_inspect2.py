import json

with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios_actualizado.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

lugares = data.get('lugares', [])
print('Items 8096 to end:')
for i in range(8096, min(len(lugares), 8110)):
    item = lugares[i]
    print(f"[{i}] {item.get('nombre')} | ID: {item.get('id')} | TIPO: {item.get('tipo')} | PADRE: {item.get('padre_id', 'N/A')}")

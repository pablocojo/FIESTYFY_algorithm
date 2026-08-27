import json

try:
    with open('fiestas_espana.json', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        if 'fiestas' in data: data = data['fiestas']
    print(f'Total fiestas: {len(data)}')
    for f in data:
        print(f"LugarID: {f.get('lugar_id', '')} - Fiesta: {f.get('nombre', '')} - Estimada: {f.get('es_estimada')}")
except Exception as e:
    print(e)

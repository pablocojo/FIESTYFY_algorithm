import json
from collections import defaultdict

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lugares = data.get('lugares', [])

    children_counts = defaultdict(int)
    for l in lugares:
        if l.get('padre_id'):
            children_counts[l['padre_id']] += 1

    no_children = [l for l in lugares if l.get('tipo') == 'municipio' and children_counts[l['id']] == 0]
    print(f'Municipios con 0 hijos: {len(no_children)}')
    for nc in no_children:
        print(f" - {nc.get('nombre')}")
except Exception as e:
    print('Error:', e)

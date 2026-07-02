import json
from collections import Counter

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lugares = data.get('lugares', [])
    
    tipos = Counter(l.get('tipo') for l in lugares)
    print('Tipos en lugares_espana.json:', tipos)
    
    # Check for any place that doesn't have an 11-digit ID, no matter the type
    non_11_digit = []
    for l in lugares:
        id_str = str(l.get('id', ''))
        if not id_str.isdigit() or len(id_str) != 11:
            non_11_digit.append(l)
    
    print(f'Lugares con ID que no es 11 dígitos: {len(non_11_digit)}')
    if non_11_digit:
        print('Ejemplos:')
        for l in non_11_digit[:5]:
            print(f" - {l.get('nombre')} | tipo: {l.get('tipo')} | id: {l.get('id')}")
            
except Exception as e:
    print('Error:', e)

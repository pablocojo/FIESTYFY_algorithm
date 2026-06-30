import json
from collections import defaultdict

# Cargar JSONs
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# Determinar si una localidad es municipio independiente según verpueblos
def es_pueblo_independiente(nombre, data_verpueblos):
    for m in data_verpueblos:
        # buscar en lista de municipios
        if m['municipio_nombre'].lower() == nombre.lower() and m['pueblos']:
            return True
        # buscar en pueblos anexos
        for p in m.get('pueblos', []):
            if p['nombre'].lower() == nombre.lower():
                return False
    return False

# Unir datos

def merge(data_wiki, data_verpueblos):
    # Diccionario por municipio
    merged = {}

    # Primero agregar municipios de verpueblos
    for m in data_verpueblos:
        key = m['municipio_nombre']
        merged[key] = {
            'municipio_nombre': key,
            'municipio_category_url': m.get('municipio_category_url', ''),
            'distritos': m.get('distritos', []),
            'barrios': [],
            'pueblos': m.get('pueblos', [])
        }

    # Luego procesar Wikipedia
    for m in data_wiki:
        nombre = m['municipio_nombre']
        if nombre not in merged:
            merged[nombre] = {
                'municipio_nombre': nombre,
                'municipio_category_url': m.get('municipio_category_url', ''),
                'distritos': m.get('distritos', []),
                'barrios': [],
                'pueblos': []
            }
        # iterar barrios de wiki
        for barrio in m.get('barrios', []):
            real = barrio['real_name']
            # Si verpueblos considera independiente => pueblo
            if es_pueblo_independiente(real, data_verpueblos):
                merged[nombre]['pueblos'].append(barrio)
            else:
                # evitamos duplicados
                if not any(b['real_name'] == real for b in merged[nombre]['barrios']):
                    merged[nombre]['barrios'].append(barrio)

    # Ordenar según número de subdivisiones
    def sort_key(item):
        b = len(item['barrios'])
        p = len(item['pueblos'])
        if b>0:
            return (-b, 0)
        if b==0 and p==0:
            return (0, 1)
        return (p, 2)

    sorted_list = sorted(merged.values(), key=sort_key)
    return sorted_list

# Uso
data_wiki = load_json('wiki.json')
data_ver = load_json('verpueblos.json')
merged = merge(data_wiki, data_ver)
with open('merged.json', 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)

print("Fichero 'merged.json' generado.")

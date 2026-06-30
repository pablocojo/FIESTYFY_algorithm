import json
import sys

f = 'c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/municipios.json'
with open(f, 'r', encoding='utf-8') as file:
    data = json.load(file)

lugares = data['lugares']
# Remove navarra
data['lugares'] = [m for m in lugares if m['id'] != 'navarra']

for m in data['lugares']:
    if m['id'] == 'llanera':
        m['poblacion'] = 14020
        m['provincia'] = 'Asturias'
        m['descripcion'] = 'Llanera es un concejo de la comunidad autónoma del Principado de Asturias, España.'
    elif m['id'] == 'liendo':
        m['poblacion'] = 1218
        m['provincia'] = 'Cantabria'
    elif m['id'] == 'berbinzana':
        m['provincia'] = 'Navarra'
    elif m['id'] == 'figuerola':
        m['id'] = 'figuerola_del_camp'
        m['nombre'] = 'Figuerola del Camp'
        m['provincia'] = 'Tarragona'
        m['comunidad'] = 'Cataluña'
        m['poblacion'] = 327
        m['wikipedia_url'] = 'https://es.wikipedia.org/wiki/Figuerola_del_Camp'
        m['descripcion'] = 'Figuerola del Camp es un municipio de Cataluña, España. Perteneciente a la provincia de Tarragona, en la comarca del Alto Campo.'
        m['descripcion_corta'] = 'Municipio de Cataluña, en la provincia de Tarragona.'

with open(f, 'w', encoding='utf-8') as file:
    json.dump(data, file, indent=2, ensure_ascii=False)

print("Actualizados los municipios correctamente.")

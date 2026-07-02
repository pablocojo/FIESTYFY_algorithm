import json
import difflib
import sys
import os
sys.path.append(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki')
from datos_ine import cargar_datos_ine, _normalizar

datos_ine = cargar_datos_ine()
ine_muns = datos_ine['municipios']

# Check keys for the first item
first_mun = list(ine_muns.values())[0]
print("Keys of INE municipio:", first_mun.keys())

alicante_ine = [m['nombre'] for m in ine_muns.values() if 'alicante' in _normalizar(m['provincia']) or 'alacant' in _normalizar(m['provincia'])]

test_names = ['Busot', 'Jalón', 'Muro de Alcoy', 'Planes', 'San Vicente del Raspeig']

print('--- ALICANTE MATCHES ---')
for t in test_names:
    matches = difflib.get_close_matches(t, alicante_ine, n=1, cutoff=0.3)
    print(f'{t} -> {matches}')

baleares_ine = [m['nombre'] for m in ine_muns.values() if 'balears' in _normalizar(m['provincia'])]
test_bal = ['Ibiza', 'Mahón', 'Alayor', 'Alcudia', 'San Antonio Abad']

print('--- BALEARES MATCHES ---')
for t in test_bal:
    matches = difflib.get_close_matches(t, baleares_ine, n=1, cutoff=0.3)
    print(f'{t} -> {matches}')

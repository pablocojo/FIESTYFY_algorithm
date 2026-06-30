import sys
import os

# Add the directory to sys.path to import modules
sys.path.append('c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki')

from datos_ine import cargar_datos_ine, buscar_municipio_ine

print("Cargando datos INE...")
datos = cargar_datos_ine()

print("\nProbando Cuartango en Álava (debería encontrar el de Álava, no Artà):")
res = buscar_municipio_ine("Cuartango", "Álava", datos)
print(res)

print("\nProbando Facheca en Alicante:")
res2 = buscar_municipio_ine("Facheca", "Alicante", datos)
print(res2)

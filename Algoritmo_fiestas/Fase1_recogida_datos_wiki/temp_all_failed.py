import json
import sys
import os
sys.path.append(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki')
from datos_ine import cargar_datos_ine, buscar_municipio_ine

try:
    datos_ine = cargar_datos_ine()
    
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
    lugares_muni = data_muni.get('lugares', [])
    
    skipped = []
    
    # We will simulate main2.py matching logic, but WITHOUT LLM
    # to see how many fail out of the 8132.
    # Note: buscar_municipio_ine does NOT use LLM by default if we don't pass html
    print("Test matching all 8132...")
    for i, m in enumerate(lugares_muni):
        nombre = m.get('nombre', '')
        prov = m.get('provincia', '')
        info_ine = buscar_municipio_ine(nombre, prov, datos_ine)
        if not info_ine:
            skipped.append(m)
            
    print(f"Total failed direct match: {len(skipped)}")
    with open('temp_all_skipped.json', 'w', encoding='utf-8') as f:
        json.dump(skipped, f, ensure_ascii=False, indent=2)
except Exception as e:
    print("Error:", e)

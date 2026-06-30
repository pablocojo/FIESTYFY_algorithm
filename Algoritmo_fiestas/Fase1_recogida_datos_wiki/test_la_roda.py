import sys
import requests
sys.path.append('c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki')
from parte2_distritos_pedanias.distritos_pedanias import _resumen_estructura_pagina

html = requests.get("https://es.wikipedia.org/wiki/La_Roda").text
resumen = _resumen_estructura_pagina(html)

print("RESUMEN GENERADO:")
if "Barrios de Albacete" in resumen:
    print("¡ENCONTRADO 'Barrios de Albacete' EN EL RESUMEN!")
else:
    print("NO ENCONTRADO.")

with open("resumen_la_roda.txt", "w", encoding="utf-8") as f:
    f.write(resumen)

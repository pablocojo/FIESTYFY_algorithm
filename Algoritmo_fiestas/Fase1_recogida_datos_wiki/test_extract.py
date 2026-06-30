import sys
sys.path.append('.')
from parte2_distritos_pedanias import distritos_pedanias as dp

print("Prueba de extraccion de distritos:")
distritos = dp._extraer_desde_categoria_o_anexo(
    "https://es.wikipedia.org/wiki/Categor%C3%ADa:Distritos_de_Alicante", 
    "distrito", 
    "Alicante"
)
print("Distritos:", distritos)

print("Prueba de extraccion de barrios:")
barrios = dp._extraer_desde_categoria_o_anexo(
    "https://es.wikipedia.org/wiki/Anexo:Barrios_de_Alicante", 
    "barrio", 
    "Alicante"
)
print("Barrios:", barrios)

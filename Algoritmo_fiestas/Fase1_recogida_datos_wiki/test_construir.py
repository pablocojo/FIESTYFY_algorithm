import json
from parte2_distritos_pedanias import distritos_pedanias as dp
from scraper import fetch_url

dp._parece_falso_positivo = lambda n,u: False
dp._limpiar_nombre = lambda n,t,c: n
dp._validar_poblacion_o_ine = lambda p,o,c: (True, 'Forzado')
dp._texto_no_contradice_parentesco = lambda h,c,p,ca: True
def b(c,p,ci,html_articulo=None,html_fuente=None):
    return True, {'motivo':'f', 'nombre_normalizado':c['nombre'], 'poblacion':c.get('population_hint')}, 'OK'
dp.verificar_candidato_llm = b

ci = {'id':'alicante', 'nombre':'Alicante'}
cand = dp._make_candidate('Benalua', 'https://es.wikipedia.org/wiki/Benal%C3%BAa_(Alicante)', 'barrio', 'Alicante', 'man', 'man', 'Alicante')
obj, m = dp._construir_si_supera_poblacion(cand, ci, ci)

print(m if not obj else f"SUCCESS: {obj['nombre']}")

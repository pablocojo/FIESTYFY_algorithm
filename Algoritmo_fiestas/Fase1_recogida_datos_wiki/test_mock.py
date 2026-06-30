from extractors import construir_lugar
import extractors

def mock_extract(html, nombre_lugar=None, tipo=None, **kwargs):
    return {'descripcion_corta': 'Test', 'descripcion': 'Test'}
extractors.extract_descripciones = mock_extract

from scraper import fetch_url
html = fetch_url('https://es.wikipedia.org/wiki/Albufereta')
obj = construir_lugar(nombre='Albufereta', html=html, tipo='barrio', padre_id='alicante_distrito-distrito4', padre_info={'comunidad':'C', 'provincia':'P'}, wikipedia_url='https://es.wikipedia.org/wiki/Albufereta')
print(obj['lat'])

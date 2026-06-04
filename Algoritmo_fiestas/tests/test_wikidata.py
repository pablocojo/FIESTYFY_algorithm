from SPARQLWrapper import SPARQLWrapper, JSON
import requests

def obtener_qid(nombre_municipio, idioma='es'):
    """Obtiene el QID de Wikidata a partir del nombre del municipio en Wikipedia."""
    params = {
        'action': 'query',
        'titles': nombre_municipio,
        'prop': 'pageprops',
        'format': 'json',
        'ppprop': 'wikibase_item'
    }
    r = requests.get(f"https://{idioma}.wikipedia.org/w/api.php", params=params)
    data = r.json()
    pages = data['query']['pages']
    for page in pages.values():
        return page.get('pageprops', {}).get('wikibase_item')
    return None

def listar_entidades_submunicipales(qid_municipio):
    """Consulta las entidades de tipo Q10854310 dentro del municipio dado."""
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
    query = f"""
    SELECT ?entidad ?entidadLabel WHERE {{
      ?entidad wdt:P31 wd:Q10854310;
               wdt:P131 wd:{qid_municipio}.
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es". }}
    }}
    ORDER BY ?entidadLabel
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    return [(binding["entidadLabel"]["value"], binding["entidad"]["value"].split("/")[-1])
            for binding in results["results"]["bindings"]]

if __name__ == "__main__":
    municipio_nombre = "Puentes Viejas"
    qid = obtener_qid(municipio_nombre)
    if not qid:
        print(f"No se encontró QID para '{municipio_nombre}'.")
    else:
        print(f"QID de '{municipio_nombre}': {qid}")
        entidades = listar_entidades_submunicipales(qid)
        if entidades:
            print(f"\nEntidades administrativas submunicipales en {municipio_nombre}:")
            for nombre, qid_entidad in entidades:
                print(f" - {nombre} ({qid_entidad})")
        else:
            print(f"No se encontraron entidades submunicipales en {municipio_nombre}.")

import json
from llm_client import call_llm
from scraper import fetch_url, get_soup

system_prompt = (
    "Eres un verificador experto. Lee el fragmento del articulo de Wikipedia y decide "
    "SI EL TEMA PRINCIPAL DEL ARTICULO es exactamente una localidad, aldea, pedania o barrio "
    "perteneciente al municipio indicado. Si el articulo es sobre un monumento (ermita, iglesia), accidente geografico, "
    "persona o edificio situado en esa pedania, debes responder aceptar: false. "
    "Responde SOLO JSON valido con: {\"aceptar\": bool, \"motivo\": \"explicacion corta\"}."
)

for url, lugar in [('https://es.wikipedia.org/wiki/Gordoa', 'Gordoa'), ('https://es.wikipedia.org/wiki/Ibarguren', 'Ibarguren')]:
    html = fetch_url(url)
    soup = get_soup(html)
    content = soup.find(id='mw-content-text')
    texto = content.get_text(' ', strip=True)[:2000] if content else ''
    user_prompt = f"Lugar: {lugar}\nMunicipio esperado: Aspárrena\n\nTexto del articulo:\n{texto}"
    resp = call_llm(system_prompt, user_prompt)
    print(f"{lugar} LLM:", resp)

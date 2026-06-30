# extractors_pueblos.py

import json
from bs4 import BeautifulSoup
from config import BASE_VER_PUEBLOS_URL, MAX_SNIPPET_TOKENS
from llm_client import call_llm, contar_tokens
from logger import log_error

def extract_autonomias(html: str) -> list:
    """Extrae lista de comunidades autónomas y sus URLs absolutas."""
    print("[DEBUG] extract_autonomias: iniciando extracción de autonomías")
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        # Filtrar rutas de comunidades (endswith '/'), evitar extensiones y parámetros
        if not href.startswith('/') or not href.endswith('/'):
            continue
        if any(ext in href for ext in ('.php', '.html', '.jpg', '.png', '.css', '.js')):
            continue
        if any(c in href for c in ('?', '#', '/usuario', '/fotografia', '/comercio')):
            continue
        if href in seen:
            continue
        seen.add(href)
        print(f"[DEBUG] Autonomía detectada: {text} -> {href}")
        items.append({'nombre': text, 'url': href})
    print(f"[DEBUG] extract_autonomias: total {len(items)} autonomías extraídas")
    return items

def extract_provincias_o_pueblos(html: str) -> list:
    """Extrae enlaces a provincias y pueblos según segmentos de la URL."""
    print("[DEBUG] extract_provincias_o_pueblos: iniciando extracción")
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        if not href.startswith('/') or not text:
            continue
        # Ignorar rutas a recursos y páginas estáticas
        if any(ext in href for ext in ('.php', '.jpg', '.png', '.css', '.js')):
            continue
        segments = href.strip('/').split('/')
        if len(segments) == 2:
            tipo = 'provincia'
        elif len(segments) == 3:
            tipo = 'pueblo'
        else:
            continue
        print(f"[DEBUG] Link tipo={tipo}: {text} -> {href}")
        results.append({'nombre': text, 'url': href, 'tipo': tipo})
    print(f"[DEBUG] extract_provincias_o_pueblos: total {len(results)} enlaces útiles")
    return results

def extract_pueblo_info_with_llm(nombre: str, html: str, region: str) -> dict:
    """Llama al LLM para extraer JSON con datos del pueblo y su ayuntamiento padre."""
    print(f"[DEBUG] extract_pueblo_info_with_llm: procesando pueblo '{nombre}' en región '{region}'")
    soup = BeautifulSoup(html, 'html.parser')
    # Extraer TODO el texto visible
    full_text = soup.get_text(separator=' ', strip=True)
    snippet = full_text
    print(f"[DEBUG] snippet length: {len(snippet)} caracteres")
    if contar_tokens(snippet) > MAX_SNIPPET_TOKENS:
        tokens = snippet.split()
        half = MAX_SNIPPET_TOKENS // 2
        snippet = ' '.join(tokens[:half] + ['...'] + tokens[-half:])
        print(f"[DEBUG] snippet truncado a {MAX_SNIPPET_TOKENS} tokens")

    system_prompt = (
        "Eres un extractor de datos de pueblos. RESPONDE SOLO JSON con campos en español: "
        "municipio_parent: nombre exacto del ayuntamiento al que pertenece; "
        "real_name: nombre real del pueblo; "
        "coordinates: 'lat,lon'; "
        "location: ubicación corta; "
        "population: número de habitantes; "
        "description: descripción de ~70 palabras; "
        "Si no aparece la información de ayuntamiento, municipio_parent debe ser 'Ayuntamiento no encontrado'."
    )
    print(f"[DEBUG] system_prompt: {system_prompt}")

    # Construir user_prompt correctamente en un solo f-string
    user_prompt = f"REGION: {region}\\nCONTENIDO: {snippet}"
    print(f"[DEBUG] user_prompt length: {len(user_prompt)} caracteres")

    resp = call_llm(system_prompt, user_prompt, context_info={'stage': 'extract_pueblo_info', 'pueblo': nombre})
    print(f"[DEBUG] LLM response: {resp!r}")
    if not resp or not resp.strip():
        print(f"[ERROR] LLM returned empty response for {nombre}")
        return {'error': 'model_down'}

    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        log_error(f"JSON inválido de LLM para {nombre}: {resp}")
        return {'error': 'invalid_json'}

    # Asegurar todos los campos
    data.setdefault('municipio_parent', 'Ayuntamiento no encontrado')
    for field in ('real_name', 'coordinates', 'location', 'population', 'description'):
        data.setdefault(field, None)
    print(f"[DEBUG] Datos extraídos: {data}")
    return data
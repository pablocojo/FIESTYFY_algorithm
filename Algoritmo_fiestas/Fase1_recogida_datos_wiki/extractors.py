# extractors.py (revisado completo)
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from config import BASE_WIKI_URL, MAX_SNIPPET_TOKENS
from llm_client import call_llm, contar_tokens
from scraper import get_snippet, get_soup
from logger import log_error


def extract_coordinates_from_html(html: str) -> str | None:
    """
    Extrae coordenadas de Wikipedia:
     - <span class="geo">lat;lon</span>
     - Texto con formato "40°28′35″N 3°39′29″O".
    """
    soup = BeautifulSoup(html, "html.parser")
    geo_tag = soup.find("span", class_="geo")
    if geo_tag:
        return geo_tag.get_text(strip=True)
    text = soup.get_text()
    pattern = r"\d{1,2}°\d{1,2}′\d{1,2}″[NS]\s+\d{1,2}°\d{1,2}′\d{1,2}″[EO]"
    m = re.search(pattern, text)
    return m.group(0) if m else None


def extract_municipios(html: str) -> list:
    """
    Extrae municipios de la categoría raíz.
    Intenta LLM, si falla o devuelve vacío, hace fallback con BeautifulSoup.
    """
    snippet = get_snippet(html, type='category')
    if contar_tokens(snippet) > MAX_SNIPPET_TOKENS:
        words = snippet.split()
        half = MAX_SNIPPET_TOKENS // 2
        snippet = " ".join(words[:half] + ["..."] + words[-half:])
        log_error("Snippet municipios recortado", context={"stage": "snippet_truncation"})

    system_prompt = (
        "Eres un experto en HTML de Wikipedia. "
        "RESPONDE SOLO con un JSON de lista de objetos en español: "
        "[{\"municipio_nombre\":\"...\",\"municipio_category_url\":\"...\"}, ...]"
    )
    resp = call_llm(system_prompt, snippet, context_info={'stage': 'extract_municipios'})
    if resp and resp.strip():
        try:
            data = json.loads(resp)
            if isinstance(data, list) and data:
                return data
        except json.JSONDecodeError:
            log_error("Error JSON extract_municipios", context={'raw': resp[:200]})
    # Fallback
    log_error("Falling back to HTML parsing for municipios")
    soup = BeautifulSoup(html, "html.parser")
    municipios = []
    for a in soup.select('.mw-category-group a'):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        if href.startswith('/wiki/Categor%C3%ADa:Barrios_de_'):
            municipios.append({
                'municipio_nombre': text.replace('Barrios de ', '').strip(),
                'municipio_category_url': urljoin(BASE_WIKI_URL, href)
            })
    return municipios


def extract_municipio_structure(html: str) -> dict:
    """
    Parsea HTML de categoría municipal, extrae distritos y barrios.
    """
    soup = get_soup(html)
    distritos, barrios = [], []
    for a in soup.select('.mw-category-group a'):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        if 'Barrios del distrito' in text or 'Barrios_del_distrito' in href:
            distritos.append({
                'nombre': text,
                'category_url': urljoin(BASE_WIKI_URL, href)
            })
        elif href.startswith('/wiki/') and not href.lower().startswith('/wiki/categor'):
            barrios.append({
                'nombre': text,
                'article_url': urljoin(BASE_WIKI_URL, href)
            })
    return {'distritos': distritos, 'barrios': barrios}


def extract_barrio_info_with_llm(barrio: str, html: str, municipio: str) -> dict:
    """
    Extrae detalles de barrio via LLM, usa truncado y coordenadas.
    Retorna {'error':'model_down'} si el modelo no responde.
    """
    if not html.strip():
        return {'error': 'not_a_barrio', 'reason': 'Descarga fallida'}
    soup = BeautifulSoup(html, 'html.parser')
    paras = soup.find(id='mw-content-text').find_all('p', limit=3)
    text_snippet = '\n\n'.join(p.get_text(' ', strip=True) for p in paras if p.get_text(strip=True))
    if not text_snippet:
        return {'error': 'not_a_barrio', 'reason': 'Sin contenido relevante'}
    if contar_tokens(text_snippet) > MAX_SNIPPET_TOKENS:
        words = text_snippet.split()
        half = MAX_SNIPPET_TOKENS // 2
        text_snippet = ' '.join(words[:half] + ['...'] + words[-half:])
        log_error(f"Snippet '{barrio}' recortado", context={'stage':'snippet_truncation','barrio':barrio})
    coords = extract_coordinates_from_html(html) or ''
    system_prompt = (
        "Asistente extrae JSON de barrio en español. "
        "Mantén nombres exactos. RESPONDE SOLO JSON. "
        "Si NO es barrio: {\"error\":\"not_a_barrio\",\"reason\":\"...\"}. "
        "Si sí: {\"real_name\":\"...\",\"coordinates\":\"lat,lon\",\"location\":\"...\",\"population\":123,\"description\":\"~70 palabras\"}"
    )
    user_prompt = text_snippet + (f"\n\nCOORDENADAS: {coords}" if coords else '')
    resp = call_llm(system_prompt, user_prompt, context_info={'stage':'extract_barrio_info','barrio':barrio})
    if not resp or not resp.strip():
        return {'error': 'model_down'}
    try:
        obj = json.loads(resp)
        if obj.get('error') == 'not_a_barrio':
            return obj
        for k in ('real_name','coordinates','location','population','description'):
            obj.setdefault(k, None)
        return obj
    except json.JSONDecodeError:
        return {'error':'not_a_barrio','reason':'JSON inválido'}

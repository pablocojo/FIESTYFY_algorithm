# scraper.py
import requests
from bs4 import BeautifulSoup
import urllib.parse
from config import REQUEST_TIMEOUT
from logger import log_error


def fetch_url(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log_error(f"Error fetching URL {url}: {e}")
        return ""


def get_soup(html: str) -> BeautifulSoup:
    """
    Convierte HTML plano a BeautifulSoup para facilitar parsing.
    """
    return BeautifulSoup(html, 'html.parser')


def get_snippet(html: str, type: str = 'category') -> str:
    """
    Extrae la parte relevante del HTML según 'category' o 'article'.
    """
    soup = get_soup(html)
    if type == 'category':
        links = []
        for grp in soup.find_all(class_='mw-category-group'):
            for a in grp.find_all('a'):
                links.append(str(a))
        if links:
            return "\n".join(links)
        # fallback
        div = soup.find(id='mw-content-text')
        if div:
            log_error("Fallback: sin grupos, usando contenido completo.")
            return str(div)
        log_error("No se encontró contenido en snippet 'category'.")
        return html
    elif type == 'article':
        div = soup.find(id='mw-content-text')
        if div:
            return str(div)
        log_error("No se encontró mw-content-text en artículo.")
        return html
    else:
        log_error(f"Tipo de snippet desconocido: {type}")
        return html


def get_wikidata_p18_url(wikipedia_url: str) -> str:
    """Extrae la URL de la imagen de la propiedad P18 de Wikidata dado un enlace a Wikipedia."""
    if not wikipedia_url or '/wiki/' not in wikipedia_url:
        return ""
    
    title = wikipedia_url.split('/wiki/')[-1]
    title = urllib.parse.unquote(title)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    }
    wd_url = f"https://www.wikidata.org/w/api.php?action=wbgetentities&sites=eswiki&titles={urllib.parse.quote(title)}&props=claims&format=json"
    
    try:
        resp = requests.get(wd_url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        entities = data.get("entities", {})
        for entity_id, entity_data in entities.items():
            if entity_id != "-1":
                p18_claims = entity_data.get("claims", {}).get("P18", [])
                if p18_claims:
                    image_name = p18_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
                    if image_name:
                        image_name_encoded = urllib.parse.quote(image_name.replace(" ", "_"))
                        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{image_name_encoded}"
        return ""
    except Exception as e:
        log_error(f"Error extrayendo Wikidata P18 para {title}: {e}")
        return ""
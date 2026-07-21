# scraper.py
import requests
from bs4 import BeautifulSoup
import urllib.parse
from config import REQUEST_TIMEOUT
from logger import log_error


def fetch_url(url: str) -> str:
    import time
    headers = {
        "User-Agent": "FiestyfyBot/1.0 (sainzmartinp@gmail.com) - Project Fiestyfy Data Collection"
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait_time = int(resp.headers.get("Retry-After", 2 ** attempt))
                log_error(f"429 Too Many Requests para {url}. Reintentando en {wait_time}s...")
                time.sleep(wait_time)
                continue
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == max_retries - 1:
                log_error(f"Error fetching URL {url}: {e}")
            else:
                time.sleep(2 ** attempt)
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
        "User-Agent": "FiestyfyBot/1.0 (sainzmartinp@gmail.com) - Project Fiestyfy Data Collection"
    }
    wd_url = f"https://www.wikidata.org/w/api.php?action=wbgetentities&sites=eswiki&titles={urllib.parse.quote(title)}&props=claims&format=json"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            import time
            resp = requests.get(wd_url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait_time = int(resp.headers.get("Retry-After", 2 ** attempt))
                log_error(f"429 Too Many Requests para Wikidata {title}. Reintentando en {wait_time}s...")
                time.sleep(wait_time)
                continue
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
            if attempt == max_retries - 1:
                log_error(f"Error extrayendo Wikidata P18 para {title}: {e}")
            else:
                time.sleep(2 ** attempt)
    return ""


def buscar_titulos_relacionados_api(ciudad: str) -> list[str]:
    """
    Consulta la API de Wikipedia para ver si existen páginas o categorías 
    maestras relacionadas con barrios/distritos/pedanías de una ciudad.
    """
    if not ciudad:
        return []

    url = "https://es.wikipedia.org/w/api.php"
    headers = {"User-Agent": "FiestyfyBot/1.0 (sainzmartinp@gmail.com) - Project Fiestyfy"}
    
    titulos_posibles = [
        f"Anexo:Barrios de {ciudad}",
        f"Categoría:Barrios de {ciudad}",
        f"Barrios de {ciudad}",
        f"Anexo:Distritos de {ciudad}",
        f"Categoría:Distritos de {ciudad}",
        f"Distritos de {ciudad}",
        f"Anexo:Pedanías de {ciudad}",
        f"Categoría:Pedanías de {ciudad}",
        f"Pedanías de {ciudad}",
        f"Organización territorial de {ciudad}"
    ]
    
    params = {
        "action": "query",
        "titles": "|".join(titulos_posibles),
        "format": "json"
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait_time = int(resp.headers.get("Retry-After", 2 ** attempt))
                log_error(f"429 Too Many Requests para API Wikipedia (relacionados). Reintentando en {wait_time}s...")
                time.sleep(wait_time)
                continue
            resp.raise_for_status()
            data = resp.json()
            
            results = []
            for page_id, page_info in data.get("query", {}).get("pages", {}).items():
                if "missing" not in page_info:
                    title = page_info["title"]
                    # Convert to full URL
                    title_encoded = urllib.parse.quote(title.replace(" ", "_"))
                    results.append(f"https://es.wikipedia.org/wiki/{title_encoded}")
                    
            return results
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                log_error(f"Error consultando API de Wikipedia para {ciudad}: {e}")
            else:
                time.sleep(2 ** attempt)
        except Exception as e:
            log_error(f"Error inesperado consultando API de Wikipedia para {ciudad}: {e}")
            break
            
    return []
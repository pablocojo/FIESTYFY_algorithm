# scraper.py
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT
from logger import log_error


def fetch_url(url: str) -> str:
    """
    Obtiene el contenido HTML de una URL con manejo de errores.
    """
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
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
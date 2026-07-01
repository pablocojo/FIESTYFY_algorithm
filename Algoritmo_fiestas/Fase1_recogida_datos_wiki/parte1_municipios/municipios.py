"""
Parte 1: descubrimiento y procesado de municipios base.

Esta fase obtiene la lista de municipios desde Wikipedia y construye el objeto
lugar raiz de cada municipio o ciudad.
"""

from config import MUNICIPIOS_CATEGORY_URL
from extractors import construir_lugar, extract_lugares_base
from logger import log_error
from scraper import fetch_url


def obtener_lugares_base() -> list[dict]:
    """
    Descarga la categoria raiz y devuelve los municipios/ciudades encontrados.
    """
    print("Extrayendo municipios y ciudades de Wikipedia...")
    root_html = fetch_url(MUNICIPIOS_CATEGORY_URL)
    if not root_html:
        print("ERROR: No se pudo descargar la categoria raiz.")
        return []

    return extract_lugares_base(root_html)


def procesar_municipio_base(lugar_base: dict) -> tuple[dict | None, str | None]:
    """
    Descarga y construye un lugar raiz a partir de un registro base.

    Returns:
        (lugar, html) si se pudo procesar, o (None, None) si hubo error.
    """
    nombre = lugar_base.get("nombre", "?")
    article_url = lugar_base.get("article_url", "")

    if not article_url:
        log_error(f"Sin URL de articulo para {nombre}")
        print("  ERROR: Sin URL de articulo.\n")
        return None, None

    html = fetch_url(article_url)
    if not html:
        log_error(f"Error descargando HTML para {nombre}")
        print("  ERROR: Error descargando HTML.\n")
        return None, None

    try:
        lugar = construir_lugar(nombre=nombre, html=html, wikipedia_url=article_url)
        print(f"  OK {lugar['tipo']}: {nombre} ({lugar['poblacion']} hab.)")
        return lugar, html
    except Exception as e:
        log_error(f"Error construyendo lugar {nombre}: {e}")
        print(f"  ERROR: {e}\n")
        return None, None

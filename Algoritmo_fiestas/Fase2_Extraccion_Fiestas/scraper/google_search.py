"""
Módulo de búsqueda externa — DuckDuckGo con múltiples queries y seguimiento de URLs.

Genera 3 variaciones de búsqueda por localidad, extrae snippets y
sigue las top N URLs para descargar contenido completo de noticias/webs.
"""

import asyncio
import urllib.parse
import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from config import (
    DDG_MAX_URLS_TO_FOLLOW,
    DDG_DELAY_BETWEEN_QUERIES,
    DDG_REQUEST_TIMEOUT,
    DDG_MAX_RETRIES,
    DDG_RETRY_BACKOFF,
    DDG_CONTENT_MAX_CHARS,
    USER_AGENT,
)
from fuentes import crear_documento, FUENTE_BUSQUEDA

logger = logging.getLogger("search")


def _build_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    """Genera múltiples variaciones de búsqueda para maximizar cobertura."""
    nombre_loc = localidad["nombre"]
    nombre_mun = municipio["nombre"]
    provincia = municipio.get("provincia", "")
    sitio_web_mun = municipio.get("sitio_web", "").strip()
    sitio_web_loc = localidad.get("sitio_web", "").strip()

    queries = [
        f"fiestas patronales {nombre_loc} {nombre_mun} {anno}",
        f"programa fiestas {nombre_loc} {anno}",
        f"fiestas {nombre_loc} {provincia} {anno}",
    ]
    
    sitios_site = []
    if sitio_web_mun:
        sitios_site.append(sitio_web_mun)
    
    if sitio_web_loc and sitio_web_loc != sitio_web_mun:
        sitio_mun_norm = sitio_web_mun.rstrip("/")
        sitio_loc_norm = sitio_web_loc.rstrip("/")
        if sitio_loc_norm != sitio_mun_norm:
            sitios_site.append(sitio_web_loc)

    for sitio in sitios_site:
        url_to_parse = sitio if sitio.startswith("http") else "http://" + sitio
        domain = urllib.parse.urlparse(url_to_parse).netloc
        if domain:
            queries.append(f"fiestas {nombre_loc} {anno} site:{domain}")

    return queries

import urllib.request
import urllib.parse
import time
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
]

def _get_random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

def _sync_fetch_ddg(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    
    req = urllib.request.Request(url, headers=_get_random_headers())
    try:
        with urllib.request.urlopen(req, timeout=DDG_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            html = resp.read()
    except Exception as e:
        logger.debug(f"DDG Error: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for div in soup.find_all("div", class_="result"):
        a_tag = div.find("a", class_="result__url")
        if not a_tag: continue
        titulo_tag = div.find("h2", class_="result__title")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""
        result_url = a_tag.get("href", "")
        if result_url.startswith("//duckduckgo.com/l/?uddg="):
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(result_url).query)
            if "uddg" in parsed: result_url = parsed["uddg"][0]
        snippet_a = div.find("a", class_="result__snippet")
        snippet = snippet_a.get_text(strip=True) if snippet_a else ""
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results

def _sync_fetch_yahoo(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://es.search.yahoo.com/search?p={encoded_query}"
    req = urllib.request.Request(url, headers=_get_random_headers())
    try:
        with urllib.request.urlopen(req, timeout=DDG_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            html = resp.read()
    except Exception as e:
        logger.debug(f"Yahoo Error: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for div in soup.find_all("div", class_="compTitle"):
        h3 = div.find("h3", class_="title")
        if not h3: continue
        a_tag = h3.find("a")
        if not a_tag: continue
        
        titulo = a_tag.get_text(strip=True)
        result_url = a_tag.get("href", "")
        
        parent = div.find_parent("div")
        snippet = ""
        if parent:
            text_div = parent.find("div", class_="compText")
            if text_div: snippet = text_div.get_text(strip=True)
            
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results

def _sync_fetch_bing(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/search?q={encoded_query}"
    req = urllib.request.Request(url, headers=_get_random_headers())
    try:
        with urllib.request.urlopen(req, timeout=DDG_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            html = resp.read()
    except Exception as e:
        logger.debug(f"Bing Error: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for li in soup.find_all("li", class_="b_algo"):
        h2 = li.find("h2")
        a_tag = h2.find("a") if h2 else None
        if not a_tag: continue
        titulo = a_tag.get_text(strip=True)
        result_url = a_tag.get("href", "")
        snippet_div = li.find("div", class_="b_caption")
        snippet = ""
        if snippet_div:
            p = snippet_div.find("p")
            if p: snippet = p.get_text(strip=True)
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results

async def _fetch_search_results(session: aiohttp.ClientSession, query: str) -> list[dict]:
    """Busca delegando en hilos síncronos rotando motores."""
    engines = [("DuckDuckGo", _sync_fetch_ddg), ("Yahoo", _sync_fetch_yahoo), ("Bing", _sync_fetch_bing)]
    
    for attempt in range(DDG_MAX_RETRIES):
        jitter = random.uniform(1.0, 3.5)
        await asyncio.sleep(jitter)
        
        engine_name, engine_func = random.choice(engines)
        
        results = await asyncio.to_thread(engine_func, query)
        if results:
            logger.info(f"  [{engine_name}] {len(results)} resultados para '{query[:50]}...'")
            return results
        
        logger.warning(f"  [{engine_name}] Vacío/Timeout (intento {attempt + 1}/{DDG_MAX_RETRIES}): {query}")
        await asyncio.sleep(DDG_RETRY_BACKOFF * (attempt + 1))
    
    return []


async def _fetch_page_content(session: aiohttp.ClientSession, url: str) -> str:
    """Descarga y extrae texto limpio de una URL de resultado."""
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=DDG_REQUEST_TIMEOUT),
            allow_redirects=True,
            ssl=False,
        ) as resp:
            if resp.status != 200:
                return ""
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return ""

            body = await resp.read()
            if len(body) > 2_000_000:
                return ""

            try:
                html = body.decode("utf-8", errors="replace")
            except Exception:
                html = body.decode("latin-1", errors="replace")

            soup = BeautifulSoup(html, "html.parser")

            # Eliminar elementos no útiles
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.extract()

            # Conservar saltos de línea (importantes para no partir programas al chunkear)
            text = soup.get_text(separator="\n", strip=True)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{2,}", "\n", text)

            # Limitar tamaño
            return text[:DDG_CONTENT_MAX_CHARS]

    except Exception as e:
        logger.debug(f"Error descargando contenido de {url}: {e}")
        return ""


async def search_locality_web(
    localidad: dict,
    municipio: dict,
    anno: int,
    visited_urls: set | None = None,
) -> list[dict]:
    """
    Busca información de fiestas de una localidad usando buscadores.
    - Lanza 3 queries distintas y extrae snippets
    - Sigue las top N URLs para obtener contenido completo
    - visited_urls: set compartido — NO se releen URLs ya leídas por pasos
      anteriores (webs oficiales), y las leídas aquí quedan registradas.

    Devuelve documentos etiquetados con fuente 'busqueda_web'.
    """
    queries = _build_queries(localidad, municipio, anno)
    documentos = []
    texto_snippets = ""
    all_urls_seen = set()
    urls_to_follow = []

    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=5, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        # 1. Ejecutar las queries secuencialmente (respetar rate limits)
        for query in queries:
            logger.info(f"  Buscando: {query}")
            results = await _fetch_search_results(session, query)

            for r in results:
                # Acumular snippets
                texto_snippets += f"TITULO: {r['titulo']} | CONTENIDO: {r['snippet']}\n"

                # Recopilar URLs únicas para seguir (saltando las ya leídas)
                result_url = r.get("url", "")
                if not result_url or not result_url.startswith("http"):
                    continue
                if result_url in all_urls_seen:
                    continue
                if visited_urls is not None and result_url in visited_urls:
                    logger.debug(f"  URL ya leída por una fuente anterior, se omite: {result_url}")
                    continue
                all_urls_seen.add(result_url)
                urls_to_follow.append(result_url)

            await asyncio.sleep(DDG_DELAY_BETWEEN_QUERIES)

        if texto_snippets.strip():
            documentos.append(
                crear_documento(FUENTE_BUSQUEDA, "buscadores:snippets", texto_snippets, tipo="snippets")
            )

        # 2. Seguir las top N URLs para obtener contenido completo
        urls_to_fetch = urls_to_follow[:DDG_MAX_URLS_TO_FOLLOW]
        if urls_to_fetch:
            logger.info(f"  Siguiendo {len(urls_to_fetch)} URLs de resultados...")
            if visited_urls is not None:
                visited_urls.update(urls_to_fetch)
            tasks = [_fetch_page_content(session, url) for url in urls_to_fetch]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)

            for url, content in zip(urls_to_fetch, page_contents):
                if isinstance(content, str) and content.strip():
                    documentos.append(crear_documento(FUENTE_BUSQUEDA, url, content, tipo="pagina"))

    return documentos

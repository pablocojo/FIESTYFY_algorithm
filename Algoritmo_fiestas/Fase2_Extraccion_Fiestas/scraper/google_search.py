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

logger = logging.getLogger("search")


def _build_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    """Genera múltiples variaciones de búsqueda para maximizar cobertura."""
    nombre_loc = localidad["nombre"]
    nombre_mun = municipio["nombre"]
    provincia = municipio.get("provincia", "")

    queries = [
        f"fiestas patronales {nombre_loc} {nombre_mun} {anno}",
        f"programa fiestas {nombre_loc} {anno}",
        f"fiestas {nombre_loc} {provincia} {anno}",
    ]
    return queries

import urllib.request
import urllib.parse
import time

def _sync_fetch_bing(query: str) -> list[dict]:
    """
    Realiza la llamada síncrona a Bing Search vía urllib.
    """
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/search?q={encoded_query}"
    
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9",
        }
    )
    
    try:
        time.sleep(1.5) # Espera obligatoria entre búsquedas para evitar bloqueos
        with urllib.request.urlopen(req, timeout=DDG_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                logger.warning(f"Buscador devolvió status {resp.status} para: {query}")
                return []
            html = resp.read()
    except Exception as e:
        logger.warning(f"Error urllib en Buscador: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    for li in soup.find_all("li", class_="b_algo"):
        h2 = li.find("h2")
        a_tag = h2.find("a") if h2 else None
        if not a_tag:
            continue
            
        titulo = a_tag.get_text(strip=True)
        result_url = a_tag.get("href", "")
        
        snippet_div = li.find("div", class_="b_caption")
        snippet = ""
        if snippet_div:
            p = snippet_div.find("p")
            if p:
                snippet = p.get_text(strip=True)
                
        results.append({
            "titulo": titulo,
            "snippet": snippet,
            "url": result_url,
        })

    logger.info(f"  Buscador: {len(results)} resultados para '{query[:50]}...'")
    return results


async def _fetch_ddg_results(session: aiohttp.ClientSession, query: str) -> list[dict]:
    """
    Busca delegando en un hilo síncrono.
    """
    for attempt in range(DDG_MAX_RETRIES):
        results = await asyncio.to_thread(_sync_fetch_bing, query)
        if results:
            return results
        
        # Fallback/retry si falló o retornó vacío
        logger.warning(f"Buscador vacío/timeout (intento {attempt + 1}/{DDG_MAX_RETRIES}): {query}")
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

            text = soup.get_text(separator=" ", strip=True)
            # Limpiar espacios múltiples
            text = re.sub(r"\s+", " ", text)

            # Limitar tamaño
            return text[:DDG_CONTENT_MAX_CHARS]

    except Exception as e:
        logger.debug(f"Error descargando contenido de {url}: {e}")
        return ""


async def search_locality_web(localidad: dict, municipio: dict, anno: int) -> str:
    """
    Busca información de fiestas de una localidad usando DuckDuckGo.
    - Lanza 3 queries distintas
    - Extrae snippets
    - Sigue las top N URLs para obtener contenido completo
    """
    queries = _build_queries(localidad, municipio, anno)
    texto_recolectado = ""
    all_urls_seen = set()
    urls_to_follow = []

    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=5, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        # 1. Ejecutar las 3 queries secuencialmente (respetar DDG rate limits)
        for query in queries:
            logger.info(f"  Buscando: {query}")
            results = await _fetch_ddg_results(session, query)

            for r in results:
                # Acumular snippets
                texto_recolectado += f"TITULO: {r['titulo']} | CONTENIDO: {r['snippet']}\n"

                # Recopilar URLs únicas para seguir
                result_url = r.get("url", "")
                if result_url and result_url.startswith("http") and result_url not in all_urls_seen:
                    all_urls_seen.add(result_url)
                    urls_to_follow.append(result_url)

            await asyncio.sleep(DDG_DELAY_BETWEEN_QUERIES)

        # 2. Seguir las top N URLs para obtener contenido completo
        urls_to_fetch = urls_to_follow[:DDG_MAX_URLS_TO_FOLLOW]
        if urls_to_fetch:
            logger.info(f"  Siguiendo {len(urls_to_fetch)} URLs de resultados...")
            tasks = [_fetch_page_content(session, url) for url in urls_to_fetch]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)

            for url, content in zip(urls_to_fetch, page_contents):
                if isinstance(content, str) and content.strip():
                    texto_recolectado += f"\n--- FUENTE EXTERNA: {url} ---\n{content}\n"

    return texto_recolectado

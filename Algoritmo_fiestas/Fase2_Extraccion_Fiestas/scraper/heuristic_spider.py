"""
Spider de Dos Pasadas (async) — Crawler heurístico para webs municipales.

Pasada 1: Mapeo rápido y concurrente de hasta N páginas, puntuando relevancia.
Pasada 2: Extracción profunda (OCR + PDFs) del Top M, con filtrado inteligente.
"""

import asyncio
import urllib.parse
import logging
import re
from collections import deque
from bs4 import BeautifulSoup

import aiohttp

from scraper.document_extractor import (
    is_promising_image,
    is_promising_pdf,
    extract_text_from_image,
    extract_text_from_pdf,
)
from config import (
    SPIDER_MAX_MAPPING_PAGES,
    SPIDER_MAX_EXTRACTION_PAGES,
    SPIDER_MAX_INTERNAL_DEPTH,
    SPIDER_MAX_EXTERNAL_DEPTH,
    SPIDER_CONCURRENCY,
    SPIDER_DELAY_SECONDS,
    SPIDER_REQUEST_TIMEOUT,
    SPIDER_RETRIES,
    SPIDER_RETRY_BACKOFF,
    USER_AGENT,
    IMAGE_MIN_SIZE_BYTES,
)

logger = logging.getLogger("spider")


class AsyncTwoPassSpider:
    """Crawler async de dos pasadas centrado en una localidad."""

    def __init__(
        self,
        max_mapping_pages=SPIDER_MAX_MAPPING_PAGES,
        max_extraction_pages=SPIDER_MAX_EXTRACTION_PAGES,
        max_internal_depth=SPIDER_MAX_INTERNAL_DEPTH,
        max_external_depth=SPIDER_MAX_EXTERNAL_DEPTH,
        concurrency=SPIDER_CONCURRENCY,
    ):
        self.max_mapping_pages = max_mapping_pages
        self.max_extraction_pages = max_extraction_pages
        self.max_internal_depth = max_internal_depth
        self.max_external_depth = max_external_depth
        self.concurrency = concurrency

    # ───── Utilidades ─────

    @staticmethod
    def _is_internal(base_url: str, url: str) -> bool:
        return urllib.parse.urlparse(base_url).netloc == urllib.parse.urlparse(url).netloc

    @staticmethod
    def _clean_url(url: str) -> str:
        """Normaliza la URL eliminando fragmentos y parámetros de tracking."""
        parsed = urllib.parse.urlparse(url)
        clean = parsed._replace(fragment="")
        return urllib.parse.urlunparse(clean)

    @staticmethod
    def _score_page(url: str, title: str, page_text: str, locality_names: list[str]) -> int:
        """Calcula la relevancia de la página para la localidad buscada."""
        score = 0
        text_lower = (url + " " + title + " " + page_text).lower()

        # 1. Mención explícita de la localidad → máxima prioridad
        for loc in locality_names:
            if loc.lower() in text_lower:
                score += 500

        # 2. Keywords fuertes de fiestas
        keywords_strong = [
            "programa de fiestas", "cartel de fiestas", "programacion festiva",
            "fiestas patronales", "feria", "programa de actos", "verbena",
            "fiestas mayores", "pregon", "chupinazo",
        ]
        keywords_weak = [
            "fiesta", "festejo", "cultura", "evento", "romeria",
            "orquesta", "concierto", "encierro", "procesion",
        ]

        for kw in keywords_strong:
            if kw in text_lower:
                score += 100
        for kw in keywords_weak:
            if kw in text_lower:
                score += 20

        # 3. Penalizaciones (contenido institucional irrelevante)
        penalties = [
            "pleno", "presupuesto", "transparencia", "urbanismo",
            "contratacion", "boe", "bop", "ordenanza", "licencia",
            "padron", "censo", "empleo publico", "subvencion",
        ]
        for p in penalties:
            if p in text_lower:
                score -= 100

        return score

    # ───── Petición HTTP resiliente ─────

    async def _fetch_html(self, session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore):
        """Descarga HTML con retries y rate-limiting."""
        for attempt in range(SPIDER_RETRIES):
            try:
                async with semaphore:
                    await asyncio.sleep(SPIDER_DELAY_SECONDS)
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=SPIDER_REQUEST_TIMEOUT),
                        allow_redirects=True,
                        ssl=False,
                    ) as resp:
                        if resp.status != 200:
                            return None
                        content_type = resp.headers.get("Content-Type", "")
                        if "text/html" not in content_type:
                            return None
                        # Limitar tamaño de descarga a 2 MB
                        body = await resp.read()
                        if len(body) > 2_000_000:
                            return None
                        try:
                            text = body.decode("utf-8", errors="replace")
                        except Exception:
                            text = body.decode("latin-1", errors="replace")
                        return text
            except asyncio.TimeoutError:
                if attempt < SPIDER_RETRIES - 1:
                    await asyncio.sleep(SPIDER_RETRY_BACKOFF * (attempt + 1))
            except Exception as e:
                logger.debug(f"Error fetching {url}: {e}")
                if attempt < SPIDER_RETRIES - 1:
                    await asyncio.sleep(SPIDER_RETRY_BACKOFF * (attempt + 1))
        return None

    async def _fetch_bytes(self, session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore, max_size: int = 10_000_000):
        """Descarga contenido binario (PDF/imagen) con límite de tamaño."""
        for attempt in range(SPIDER_RETRIES):
            try:
                async with semaphore:
                    await asyncio.sleep(SPIDER_DELAY_SECONDS)
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=30),
                        allow_redirects=True,
                        ssl=False,
                    ) as resp:
                        if resp.status != 200:
                            return None
                        # Verificar tamaño antes de descargar
                        content_length = resp.headers.get("Content-Length")
                        if content_length and int(content_length) > max_size:
                            logger.debug(f"Archivo demasiado grande ({content_length} bytes): {url}")
                            return None
                        body = await resp.read()
                        if len(body) > max_size:
                            return None
                        return body
            except asyncio.TimeoutError:
                if attempt < SPIDER_RETRIES - 1:
                    await asyncio.sleep(SPIDER_RETRY_BACKOFF * (attempt + 1))
            except Exception as e:
                logger.debug(f"Error descargando {url}: {e}")
                if attempt < SPIDER_RETRIES - 1:
                    await asyncio.sleep(SPIDER_RETRY_BACKOFF * (attempt + 1))
        return None

    # ───── Pasada 1: Mapeo y puntuación ─────

    async def pass_1_map_and_score(self, start_url: str, locality_names: list[str]) -> list:
        """Pasada 1: BFS concurrente, descarga HTML y puntúa relevancia."""
        logger.info(f"[Pasada 1] Mapeo desde: {start_url}")

        if not start_url.startswith("http"):
            start_url = "http://" + start_url

        visited = set()
        # Cola: (url, profundidad, es_interno)
        queue = deque([(start_url, 0, True)])
        scored_pages = []  # (score, url, html_text, pdf_links, img_infos)
        semaphore = asyncio.Semaphore(self.concurrency)

        headers = {"User-Agent": USER_AGENT}
        connector = aiohttp.TCPConnector(limit=self.concurrency, ssl=False)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            while queue and len(visited) < self.max_mapping_pages:
                # Procesar en batch: sacar hasta N URLs de la cola
                batch = []
                while queue and len(batch) < self.concurrency and len(visited) + len(batch) < self.max_mapping_pages:
                    url, depth, is_internal = queue.popleft()
                    url = self._clean_url(url)
                    if url in visited:
                        continue
                    if is_internal and depth > self.max_internal_depth:
                        continue
                    if not is_internal and depth > self.max_external_depth:
                        continue
                    visited.add(url)
                    batch.append((url, depth, is_internal))

                if not batch:
                    break

                # Mostrar progreso de vez en cuando (o al principio) para evitar sensación de congelamiento
                if len(visited) % (self.concurrency * 3) <= self.concurrency:
                    logger.info(f"    [Spider] Progreso: {len(visited)}/{self.max_mapping_pages} páginas escaneadas (En cola: {len(queue)})...")

                # Descargar en paralelo
                tasks = [self._fetch_html(session, url, semaphore) for url, _, _ in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (url, depth, is_internal), html_result in zip(batch, results):
                    if isinstance(html_result, Exception) or html_result is None:
                        continue

                    try:
                        soup = BeautifulSoup(html_result, "html.parser")
                        title = soup.title.string if soup.title else ""

                        # Extraer texto visible rápido
                        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                            tag.extract()
                        page_text = soup.get_text(separator=" ", strip=True)

                        score = self._score_page(url, title, page_text[:3000], locality_names)

                        # Recopilar enlaces a PDFs en esta página
                        pdf_links = []
                        for a in soup.find_all("a", href=True):
                            href = a["href"]
                            if href.lower().endswith(".pdf"):
                                pdf_url = urllib.parse.urljoin(url, href)
                                link_text = a.get_text(strip=True)
                                pdf_links.append((pdf_url, link_text))

                        # Recopilar información de imágenes
                        img_infos = []
                        for img in soup.find_all("img"):
                            src = img.get("src")
                            if src:
                                img_url = urllib.parse.urljoin(url, src)
                                alt_text = img.get("alt", "")
                                img_infos.append((img_url, alt_text))

                        scored_pages.append((score, url, page_text, pdf_links, img_infos))

                        # Extraer enlaces para continuar BFS
                        for a in soup.find_all("a", href=True):
                            link_href = a["href"]
                            if link_href.lower().endswith(".pdf"):
                                continue
                            link_url = self._clean_url(urllib.parse.urljoin(url, link_href))
                            # Filtrar enlaces inútiles
                            if link_url in visited:
                                continue
                            if any(skip in link_url.lower() for skip in ["mailto:", "tel:", "javascript:", "#"]):
                                continue

                            is_internal_next = self._is_internal(start_url, link_url)
                            # Solo añadir externos si la página actual tiene buen score
                            if is_internal_next or score > 100:
                                queue.append((link_url, depth + 1, is_internal_next))

                    except Exception as e:
                        logger.warning(f"Error procesando HTML de {url}: {e}")

        logger.info(f"  Páginas mapeadas: {len(scored_pages)}")
        scored_pages.sort(key=lambda x: x[0], reverse=True)
        return scored_pages

    # ───── Pasada 2: Extracción profunda ─────

    async def pass_2_heavy_extraction(self, scored_pages: list, locality_names: list[str]) -> str:
        """Pasada 2: OCR y PDFs del Top N, con filtrado inteligente."""
        logger.info(f"[Pasada 2] Extracción profunda del Top {self.max_extraction_pages}...")
        top_pages = scored_pages[: self.max_extraction_pages]

        extracted_content = ""
        semaphore = asyncio.Semaphore(self.concurrency)
        headers = {"User-Agent": USER_AGENT}
        connector = aiohttp.TCPConnector(limit=self.concurrency, ssl=False)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for rank, (score, url, page_text, pdf_links, img_infos) in enumerate(top_pages):
                if score < 0:
                    break  # Ignorar páginas irrelevantes

                logger.info(f"  [Top {rank + 1} / Score: {score}] {url[:70]}...")
                extracted_content += f"\n--- URL: {url} ---\n{page_text}\n"

                # ─── PDFs: filtrar por relevancia antes de descargar ───
                pdf_tasks = []
                for pdf_url, link_text in pdf_links:
                    if is_promising_pdf(pdf_url, link_text, page_text[:500]):
                        pdf_tasks.append(self._extract_pdf(session, pdf_url, semaphore))

                if pdf_tasks:
                    logger.info(f"    Descargando {len(pdf_tasks)} PDFs prometedores...")
                    pdf_results = await asyncio.gather(*pdf_tasks, return_exceptions=True)
                    for pdf_url_text in pdf_results:
                        if isinstance(pdf_url_text, str) and pdf_url_text:
                            extracted_content += f"\n[TEXTO PDF]:\n{pdf_url_text}\n"

                # ─── Imágenes: filtrar agresivamente antes de OCR ───
                img_tasks = []
                for img_url, alt_text in img_infos:
                    if is_promising_image(img_url, alt_text, locality_names):
                        img_tasks.append(self._extract_image(session, img_url, semaphore))

                if img_tasks:
                    logger.info(f"    OCR en {len(img_tasks)} imágenes prometedoras...")
                    img_results = await asyncio.gather(*img_tasks, return_exceptions=True)
                    for ocr_text in img_results:
                        if isinstance(ocr_text, str) and ocr_text.strip():
                            extracted_content += f"\n[TEXTO CARTEL]:\n{ocr_text}\n"

        return extracted_content

    async def _extract_pdf(self, session, pdf_url, semaphore):
        """Descarga y extrae texto de un PDF."""
        pdf_bytes = await self._fetch_bytes(session, pdf_url, semaphore)
        if pdf_bytes:
            # Ejecutar extracción CPU-intensiva en un thread
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, extract_text_from_pdf, pdf_bytes)
        return ""

    async def _extract_image(self, session, img_url, semaphore):
        """Descarga y extrae texto OCR de una imagen (si es grande)."""
        # Primero verificar tamaño con HEAD
        try:
            async with semaphore:
                async with session.head(img_url, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as resp:
                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) < IMAGE_MIN_SIZE_BYTES:
                        return ""
        except Exception:
            pass  # Si HEAD falla, intentar GET de todas formas

        img_bytes = await self._fetch_bytes(session, img_url, semaphore, max_size=15_000_000)
        if img_bytes and len(img_bytes) >= IMAGE_MIN_SIZE_BYTES:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, extract_text_from_image, img_bytes)
        return ""

    # ───── Interfaz pública ─────

    async def crawl(self, start_url: str, locality_names: list[str]) -> str:
        """Ejecuta el crawl completo de 2 pasadas para una localidad."""
        scored_pages = await self.pass_1_map_and_score(start_url, locality_names)
        if not scored_pages:
            logger.warning(f"No se encontraron páginas en {start_url}")
            return ""
        final_text = await self.pass_2_heavy_extraction(scored_pages, locality_names)
        return final_text

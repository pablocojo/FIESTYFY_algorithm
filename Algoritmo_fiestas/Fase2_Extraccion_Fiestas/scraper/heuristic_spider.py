"""
Spider de Dos Pasadas (async) — Crawler heurístico para webs municipales.

Pasada 1: Mapeo rápido y concurrente de hasta N páginas, puntuando relevancia.
Pasada 2: Extracción profunda (OCR + PDFs) del Top M, con filtrado inteligente.
"""

import asyncio
import urllib.parse
import logging
import re
import heapq
import itertools
from collections import deque, Counter
from bs4 import BeautifulSoup

import aiohttp

from scraper.social_finder import normalizar_link_social

from scraper.document_extractor import (
    is_promising_image,
    is_promising_pdf,
    extract_text_from_image,
    extract_text_from_pdf,
    ocr_executor,
)
from fuentes import crear_documento
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

URL_BLACKLIST = [
    "/transparencia", "/urbanismo", "/actas", "/plenos", "/perfil-contratante",
    "/sede-electronica", "/empleo", "/boe", "/bop", "/presupuestos",
    "/contratacion", "/ordenanzas", "/licencias", "/padron", "/censo",
    "mailto:", "javascript:", "tel:", "#"
]

class AsyncTwoPassSpider:
    """Crawler async de dos pasadas centrado en una localidad."""

    RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")

    def __init__(
        self,
        max_mapping_pages=SPIDER_MAX_MAPPING_PAGES,
        max_extraction_pages=SPIDER_MAX_EXTRACTION_PAGES,
        max_internal_depth=SPIDER_MAX_INTERNAL_DEPTH,
        max_external_depth=SPIDER_MAX_EXTERNAL_DEPTH,
        concurrency=SPIDER_CONCURRENCY,
        target_year: int = 2026,
    ):
        self.max_mapping_pages = max_mapping_pages
        self.max_extraction_pages = max_extraction_pages
        self.max_internal_depth = max_internal_depth
        self.max_external_depth = max_external_depth
        self.concurrency = concurrency
        self.target_year = target_year
        self.seen_calendar_dates: set[str] = set()
        # Perfiles sociales cosechados de las páginas INTERNAS del sitio:
        # Counter {(red, url_canonica): apariciones}
        self.social_links: Counter = Counter()

    @classmethod
    def _get_calendar_date_key(cls, url: str) -> str | None:
        match = cls.RE_CALENDAR_DATE_URL.search(url)
        if match:
            parsed = urllib.parse.urlparse(url)
            return f"{parsed.netloc.lower()}:{match.group(0).rstrip('/')}"
        return None

    # ───── Utilidades ─────

    @staticmethod
    def _is_internal(base_url: str, url: str) -> bool:
        return urllib.parse.urlparse(base_url).netloc == urllib.parse.urlparse(url).netloc

    @staticmethod
    async def resolver_url_final(url: str) -> str:
        """
        Sigue la cadena de redirecciones HTTP/HTTPS y devuelve la URL canónica
        final. Así el spider parte siempre del subdominio correcto (p.ej.
        amurrio.eus/cas → udala.amurrio.eus/cas) sin tener que re-rastrear.
        Si la resolución falla, devuelve la URL original sin modificar.
        """
        if not url.startswith("http"):
            url = "http://" + url
        try:
            headers = {"User-Agent": USER_AGENT}
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=8),
                    ssl=False,
                ) as resp:
                    final = str(resp.url)
                    if final != url:
                        logger.info(f"  [Spider] URL canónica: {url} → {final}")
                    return final
        except Exception as e:
            logger.debug(f"  [Spider] No se pudo resolver URL canónica de {url}: {e}")
            return url

    @staticmethod
    def _clean_url(url: str) -> str:
        """Normaliza la URL eliminando fragmentos y parámetros de tracking."""
        parsed = urllib.parse.urlparse(url)
        clean = parsed._replace(fragment="")
        return urllib.parse.urlunparse(clean)

    @staticmethod
    def _get_url_priority(url: str) -> int:
        url_lower = url.lower()
        strong_kws = [
            "fiesta", "festejo", "programa", "cartel", "evento", "feria", "cultura",
            "festes", "festa", "cartell", "jaiak", "egitaraua", "festak", "kartela", "festas", "hèsta",
        ]
        if any(kw in url_lower for kw in strong_kws):
            return 2
        return 4

    @staticmethod
    def _score_page(url: str, title: str, page_text: str, locality_names: list[str], target_year: int = 2026) -> int:
        """Calcula la relevancia de la página para la localidad buscada."""
        score = 0
        text_lower = (url + " " + title + " " + page_text).lower()
        url_lower = url.lower()

        # 1. Mención explícita de la localidad → máxima prioridad
        for loc in locality_names:
            if loc.lower() in text_lower:
                score += 500

        # 2. Keywords fuertes de fiestas (castellano y cooficiales)
        keywords_strong = [
            # Castellano
            "programa de fiestas", "cartel de fiestas", "programacion festiva",
            "fiestas patronales", "feria", "programa de actos", "verbena",
            "fiestas mayores", "pregon", "chupinazo",
            # Cooficiales
            "festa major", "festes patronals", "programa festes", "cartell festes", "revetlla", "correfoc",
            "jaiak", "jai egitaraua", "festak", "kartela", "txupinazoa",
            "festas patronais", "programa de festas", "cartel festas", "foliada",
            "hèsta major", "hèstes patronaus",
        ]
        keywords_weak = [
            "fiesta", "festejo", "cultura", "evento", "romeria",
            "orquesta", "concierto", "encierro", "procesion",
            "festes", "esdeveniment", "cercavila", "jaia", "kontzertua", "erromeria", "kalejira", "festas", "hèsta",
        ]

        has_festival_kw = False
        for kw in keywords_strong:
            if kw in text_lower:
                score += 100
                has_festival_kw = True
        for kw in keywords_weak:
            if kw in text_lower:
                score += 20
                has_festival_kw = True

        # 3. Priorización por año objetivo y penalizaciones temporales (R2)
        # 3.1 Penalización por años anteriores en URL (e.g. 2025, 2024) (-300 pts)
        years_in_url = [int(y) for y in re.findall(r"(?:19|20)\d{2}", url_lower)]
        if any(y < target_year for y in years_in_url):
            score -= 300

        # 3.2 Bonus por año objetivo (2026) en URL (+150 pts base, +350 pts si además hay palabras festivas)
        target_year_str = str(target_year)
        if target_year_str in url_lower:
            if has_festival_kw:
                score += 350
            else:
                score += 150

        # 4. Filtrado de eventos municipales individuales sin contenido festivo (R2) (-350 pts)
        unrelated_single_events = [
            "taller", "charla", "conferencia", "pleno", "exposicion", "expocision", "corte de agua"
        ]
        has_unrelated = any(ue in text_lower for ue in unrelated_single_events)
        if has_unrelated and not has_festival_kw:
            score -= 350

        # 5. Penalizaciones (contenido institucional irrelevante)
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
        """Descarga HTML con retries y rate-limiting. Incluye fallback a Playwright para SPA/Cloudflare."""
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
        
        # Fallback a Playwright si requests falló repetidamente o fue bloqueado
        logger.info(f"Fallback a Playwright (posible bloqueo JS/Cloudflare) para: {url}")
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=USER_AGENT)
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                # Scroll simple para forzar lazy loading
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(1.0)
                text = await page.content()
                await browser.close()
                return text
        except ImportError:
            logger.debug("Playwright no instalado. Omite el fallback.")
        except Exception as e:
            logger.debug(f"Error en fallback Playwright para {url}: {e}")
            
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

    async def pass_1_map_and_score(
        self,
        start_url: str,
        locality_names: list[str],
        visited_urls: set | None = None,
        target_year: int | None = None,
    ) -> list:
        """
        Pasada 1: Best-First Search concurrente, descarga HTML y puntúa relevancia.
        visited_urls (opcional) es un set COMPARTIDO entre fuentes: las URLs ya
        leídas por otro paso no se vuelven a descargar, y las leídas aquí quedan
        registradas para los pasos siguientes.
        """
        logger.info(f"[Pasada 1] Mapeo desde: {start_url}")

        year = target_year if target_year is not None else self.target_year
        if not start_url.startswith("http"):
            start_url = "http://" + start_url

        visited = visited_urls if visited_urls is not None else set()
        self.seen_calendar_dates = set()
        counter = itertools.count()
        # Cola: (prioridad, contador, url, profundidad, es_interno)
        queue = []
        heapq.heappush(queue, (3, next(counter), start_url, 0, True))
        scored_pages = []  # (score, url, html_text, pdf_links, img_infos)
        semaphore = asyncio.Semaphore(self.concurrency)
        early_stop_triggered = False

        headers = {"User-Agent": USER_AGENT}
        connector = aiohttp.TCPConnector(limit=self.concurrency, ssl=False)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            # 1. Intentar inyectar sitemap.xml
            sitemap_url = urllib.parse.urljoin(start_url, "/sitemap.xml")
            try:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as resp:
                    if resp.status == 200:
                        sitemap_text = await resp.text()
                        locs = re.findall(r"<loc>(.*?)</loc>", sitemap_text)
                        for loc in locs:
                            loc_clean = self._clean_url(loc)
                            if any(b in loc_clean.lower() for b in URL_BLACKLIST):
                                continue
                            if self._get_url_priority(loc_clean) <= 2:
                                heapq.heappush(queue, (1, next(counter), loc_clean, 0, True))
            except Exception as e:
                logger.debug(f"Sitemap no disponible o error: {e}")

            # Contador local: el set visited puede venir compartido (ya poblado)
            paginas_este_crawl = 0

            while queue and paginas_este_crawl < self.max_mapping_pages:
                # Procesar en batch: sacar hasta N URLs de la cola
                batch = []
                while queue and len(batch) < self.concurrency and paginas_este_crawl + len(batch) < self.max_mapping_pages:
                    priority, _, url, depth, is_internal = heapq.heappop(queue)
                    url = self._clean_url(url)
                    if url in visited:
                        continue

                    # Deduplicación de URLs de calendario por fecha (/YYYY/M/D/) DESACTIVADA
                    # cal_key = self._get_calendar_date_key(url)
                    # if cal_key:
                    #     if cal_key in self.seen_calendar_dates:
                    #         continue
                    #     self.seen_calendar_dates.add(cal_key)

                    if is_internal and depth > self.max_internal_depth:
                        continue
                    if not is_internal and depth > self.max_external_depth:
                        continue
                    visited.add(url)
                    batch.append((url, depth, is_internal))

                if not batch:
                    break
                paginas_este_crawl += len(batch)

                # Mostrar progreso de vez en cuando (o al principio) para evitar sensación de congelamiento
                if paginas_este_crawl % (self.concurrency * 3) <= self.concurrency:
                    logger.info(f"    [Spider] Progreso: {paginas_este_crawl}/{self.max_mapping_pages} páginas escaneadas (En cola: {len(queue)})...")

                # Descargar en paralelo
                tasks = [self._fetch_html(session, url, semaphore) for url, _, _ in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for (url, depth, is_internal), html_result in zip(batch, results):
                    if isinstance(html_result, Exception) or html_result is None:
                        continue

                    try:
                        soup = BeautifulSoup(html_result, "html.parser")
                        title = soup.title.string if soup.title else ""

                        # Extraer texto visible rápido, conservando saltos de línea
                        # (importantes para no partir programas de fiestas al chunkear)
                        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                            tag.extract()
                        page_text = soup.get_text(separator="\n", strip=True)
                        page_text = re.sub(r"[ \t]+", " ", page_text)
                        page_text = re.sub(r"\n{2,}", "\n", page_text)

                        score = self._score_page(url, title, page_text[:3000], locality_names, year)

                        if score > 800 and not early_stop_triggered:
                            logger.info(f"    [!] Early Stop Triggered: Página muy relevante encontrada ({score} pts): {url}")
                            early_stop_triggered = True
                            # Reducimos drásticamente el máximo de páginas para terminar pronto
                            self.max_mapping_pages = min(self.max_mapping_pages, paginas_este_crawl + self.concurrency * 3)

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

                        # Extraer enlaces para continuar
                        for a in soup.find_all("a", href=True):
                            link_href = a["href"]
                            if link_href.lower().endswith(".pdf"):
                                continue
                            link_url = self._clean_url(urllib.parse.urljoin(url, link_href))

                            # Cosechar perfiles sociales (solo desde páginas internas
                            # del sitio oficial → cero falsos positivos) y no rastrearlos
                            if is_internal:
                                perfil_social = normalizar_link_social(link_url)
                                if perfil_social:
                                    self.social_links[perfil_social] += 1
                                    continue

                            # Filtrar enlaces inútiles por Blacklist
                            if link_url in visited:
                                continue
                            if any(skip in link_url.lower() for skip in URL_BLACKLIST):
                                continue

                            # Deduplicación preventiva de enlaces de calendario por fecha DESACTIVADA
                            # cal_key = self._get_calendar_date_key(link_url)
                            # if cal_key and cal_key in self.seen_calendar_dates:
                            #     continue

                            is_internal_next = self._is_internal(start_url, link_url)
                            
                            if is_internal_next or score > 100:
                                # Prioridad absoluta si encontramos una página altísimamente relevante
                                if early_stop_triggered and score > 800:
                                    link_priority = 0
                                else:
                                    link_priority = self._get_url_priority(link_url)
                                
                                heapq.heappush(queue, (link_priority, next(counter), link_url, depth + 1, is_internal_next))

                    except Exception as e:
                        logger.warning(f"Error procesando HTML de {url}: {e}")

        logger.info(f"  Páginas mapeadas: {len(scored_pages)}")
        scored_pages.sort(key=lambda x: x[0], reverse=True)
        return scored_pages

    # ───── Pasada 2: Extracción profunda ─────

    async def pass_2_heavy_extraction(
        self,
        scored_pages: list,
        locality_names: list[str],
        fuente: str,
        visited_urls: set | None = None,
    ) -> list[dict]:
        """Pasada 2: OCR y PDFs del Top N. Devuelve documentos etiquetados con la fuente."""
        logger.info(f"[Pasada 2] Extracción profunda del Top {self.max_extraction_pages}...")
        top_pages = scored_pages[: self.max_extraction_pages]

        documentos = []
        semaphore = asyncio.Semaphore(self.concurrency)
        headers = {"User-Agent": USER_AGENT}
        connector = aiohttp.TCPConnector(limit=self.concurrency, ssl=False)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for rank, (score, url, page_text, pdf_links, img_infos) in enumerate(top_pages):
                if score < 0:
                    break  # Ignorar páginas irrelevantes

                logger.info(f"  [Top {rank + 1} / Score: {score}] {url[:70]}...")
                documentos.append(crear_documento(fuente, url, page_text, tipo="pagina"))

                # ─── PDFs: filtrar por relevancia antes de descargar ───
                pdf_tasks = []
                pdf_urls_pedidas = []
                for pdf_url, link_text in pdf_links:
                    if is_promising_pdf(pdf_url, link_text, page_text[:500], target_year=self.target_year):
                        pdf_tasks.append(self._extract_pdf(session, pdf_url, semaphore))
                        pdf_urls_pedidas.append(pdf_url)
                        if visited_urls is not None:
                            visited_urls.add(self._clean_url(pdf_url))

                if pdf_tasks:
                    logger.info(f"    Descargando {len(pdf_tasks)} PDFs prometedores...")
                    pdf_results = await asyncio.gather(*pdf_tasks, return_exceptions=True)
                    for pdf_url, pdf_text in zip(pdf_urls_pedidas, pdf_results):
                        if isinstance(pdf_text, str) and pdf_text:
                            documentos.append(crear_documento(fuente, pdf_url, pdf_text, tipo="pdf"))

                # ─── Imágenes: filtrar agresivamente antes de OCR ───
                img_tasks = []
                img_urls_pedidas = []
                for img_url, alt_text in img_infos:
                    if is_promising_image(img_url, alt_text, locality_names):
                        img_tasks.append(self._extract_image(session, img_url, semaphore))
                        img_urls_pedidas.append(img_url)

                if img_tasks:
                    logger.info(f"    OCR en {len(img_tasks)} imágenes prometedoras...")
                    img_results = await asyncio.gather(*img_tasks, return_exceptions=True)
                    for img_url, ocr_text in zip(img_urls_pedidas, img_results):
                        if isinstance(ocr_text, str) and ocr_text.strip():
                            documentos.append(crear_documento(fuente, img_url, ocr_text, tipo="cartel"))

        return documentos

    async def _extract_pdf(self, session, pdf_url, semaphore):
        """Descarga y extrae texto de un PDF."""
        pdf_bytes = await self._fetch_bytes(session, pdf_url, semaphore)
        if pdf_bytes:
            # Ejecutar extracción CPU-intensiva en el pool dedicado
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(ocr_executor, extract_text_from_pdf, pdf_bytes)
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
            return await loop.run_in_executor(ocr_executor, extract_text_from_image, img_bytes)
        return ""

    # ───── Interfaz pública ─────

    async def crawl(
        self,
        start_url: str,
        locality_names: list[str],
        fuente: str,
        visited_urls: set | None = None,
        target_year: int | None = None,
    ) -> list[dict]:
        """
        Ejecuta el crawl completo de 2 pasadas para una localidad.
        Devuelve una lista de documentos etiquetados: {fuente, url, texto, tipo, es_calendario}.
        visited_urls es un set compartido entre fuentes para no releer URLs.
        Los perfiles sociales cosechados quedan en self.social_links.
        """
        self.social_links = Counter()
        if target_year is not None:
            self.target_year = target_year
        # Fix 1: resolver redirecciones para partir del subdominio canónico correcto
        start_url = await self.resolver_url_final(start_url)
        scored_pages = await self.pass_1_map_and_score(start_url, locality_names, visited_urls, target_year=self.target_year)
        if not scored_pages:
            logger.warning(f"No se encontraron páginas en {start_url}")
            return []
        return await self.pass_2_heavy_extraction(scored_pages, locality_names, fuente, visited_urls)

"""
Spider de Dos Pasadas (async) — Crawler heurístico para webs municipales.

Pasada 1: Mapeo rápido y concurrente de hasta N páginas, puntuando relevancia.
Pasada 2: Extracción profunda (OCR + PDFs) del Top M, con filtrado inteligente.
"""

import asyncio
import io
import urllib.parse
import logging
import re
import heapq
import itertools
from collections import deque, Counter
from bs4 import BeautifulSoup

import aiohttp

from scraper.social_finder import normalizar_link_social

from concurrent.futures import ProcessPoolExecutor

from scraper.document_extractor import (
    is_promising_image,
    MARCA_VISION,
    is_promising_pdf,
)
from fuentes import crear_documento
from config import (
    VISION_MAX_IMAGES_SPIDER,
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
    PASS2_BATCH_SIZE,
    MAX_IMAGES_PER_PAGE,
)

logger = logging.getLogger("spider")

URL_BLACKLIST = [
    "/transparencia", "/urbanismo", "/actas", "/plenos", "/perfil-contratante",
    "/sede-electronica", "/empleo", "/boe", "/bop", "/presupuestos",
    "/contratacion", "/ordenanzas", "/licencias", "/padron", "/censo",
    "mailto:", "javascript:", "tel:", "#",

    # Sedes electrónicas. Hasta el 2026-09-02 aquí solo estaba la RUTA
    # "/sede-electronica", y la mayoría de los ayuntamientos españoles tienen la
    # suya en un SUBDOMINIO aparte, sobre una plataforma compartida de la
    # diputación. Medido ese día sobre la ejecución de Tobarra: de las 66 URLs
    # que la araña priorizó, 47 —el 71%— eran de `tobarra.sedipualba.es`, y las
    # diez primeras por puntuación eran el tablón de anuncios, la carpeta
    # ciudadana, el aviso legal y la página de accesibilidad. Solo 13 eran de
    # tobarra.es, que es donde está el calendario de fiestas. Una sede
    # electrónica publica licitaciones y ordenanzas; no publica programas de
    # fiestas nunca.
    "sedipualba.es",        # Diputación de Albacete
    "sedelectronica.es",    # esPublico / Dipulink, la más extendida
    "sedeelectronica.es",
    "/tablondeanuncios", "/tablon-de-anuncios",
    "/carpetaciudadana", "/carpeta-ciudadana",
    "/catalogoservicios", "/catalogo-servicios",
    "/perfilcontratante", "/tramite.aspx", "/incidencias.aspx",
    "/factura", "/portalfactura",

    # Páginas legales obligatorias. Son el falso positivo perfecto: vienen del
    # dominio del propio ayuntamiento, así que superan todos los filtros de
    # procedencia con nota máxima —son indiscutiblemente "de este pueblo"— y no
    # contienen una sola palabra sobre fiestas. Además son casi idénticas entre
    # municipios, de modo que no distinguen nada y solo diluyen.
    #
    # Medido el 2026-09-04 en El Fresno: 15 de los 60 chunks del contexto de
    # discovery —el 25%— salían de `proteccion-de-datos.html` y `aviso-legal.html`
    # de su propia web, y encabezaban el ranking.
    "/aviso-legal", "/avisolegal", "/aviso_legal",
    "/proteccion-de-datos", "/proteccion-datos", "/proteccion_de_datos",
    "/politica-de-privacidad", "/politica-privacidad", "/privacidad",
    "/politica-de-cookies", "/politica-cookies", "/cookies",
    "/accesibilidad", "/mapa-web", "/mapaweb",
]

# Dominios de RRSS que no se deben intentar scrapear en Pasada 2
# (requieren JS pesado, ya se procesan vía social_finder/social_content)
_EXTERNAL_DOMAIN_BLOCKLIST = {
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "tiktok.com", "linkedin.com",
}

# ───── Subprocess isolation para OCR/PDF (protege contra segfaults de Tesseract/Ghostscript) ─────

_ocr_process_pool: ProcessPoolExecutor | None = None

def _get_ocr_pool() -> ProcessPoolExecutor:
    """Devuelve un ProcessPoolExecutor, recreándolo si fue roto por un segfault."""
    global _ocr_process_pool
    if _ocr_process_pool is None:
        _ocr_process_pool = ProcessPoolExecutor(max_workers=2)
    return _ocr_process_pool

def _reset_ocr_pool():
    """Recrea el pool de procesos tras un error fatal (segfault en hijo)."""
    global _ocr_process_pool
    try:
        if _ocr_process_pool is not None:
            _ocr_process_pool.shutdown(wait=False)
    except Exception:
        pass
    _ocr_process_pool = None

def _subprocess_extract_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto de PDF en subproceso aislado. Solo retorna texto (sin imágenes PIL)."""
    try:
        from scraper.document_extractor import extract_text_from_pdf
        resultado = extract_text_from_pdf(pdf_bytes)
        if isinstance(resultado, tuple) and len(resultado) == 2:
            return resultado[0].strip()
        return str(resultado).strip() if resultado else ""
    except Exception:
        return ""

def _subprocess_extract_image(img_bytes: bytes) -> str:
    """OCR de imagen en subproceso aislado. Solo retorna texto (sin imágenes PIL)."""
    try:
        from scraper.document_extractor import extract_text_from_image
        resultado = extract_text_from_image(img_bytes)
        if isinstance(resultado, tuple) and len(resultado) == 2:
            return resultado[0].strip()
        return str(resultado).strip() if resultado else ""
    except Exception:
        return ""

class AsyncTwoPassSpider:
    """Crawler async de dos pasadas centrado en una localidad."""

    RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")

    # Formatos alternativos de fecha que usan otros calendarios municipales.
    # Cada patrón captura el año en el grupo 1. Se usan solo para decidir si una
    # página de calendario es del año objetivo, no para la identidad de
    # deduplicación (_get_calendar_date_key sigue siendo la única fuente de esa).
    _RE_FECHA_ANNO_ALT = (
        # /11/8/2026/ o /11-8-2026  (día/mes/año, orden que usan algunos CMS)
        re.compile(r"/[0-3]?\d[/-][0-1]?\d[/-]((?:19|20)\d{2})(?:/|$|[?&])"),
        # 2026-08-11, 2026_08_11, 2026.08.11 — en la ruta o en la query
        re.compile(
            r"((?:19|20)\d{2})[-_.](?:0?[1-9]|1[0-2])[-_.](?:0?[1-9]|[12]\d|3[01])(?:\b|/|$|[?&])"
        ),
        # ?fecha=2026-08-11 , ?date=2026/08/11
        re.compile(
            r"[?&](?:fecha|date)=((?:19|20)\d{2})[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b"
        ),
    )
    # ?anyo=2026&mes=8&dia=11 , ?year=2026&month=8&day=11 (parámetros sueltos:
    # el año solo cuenta si aparecen también mes y día en la misma query)
    _RE_ANNO_QUERY = re.compile(r"[?&](?:anyo|a[nñ]o|year)=((?:19|20)\d{2})\b")
    _RE_MES_QUERY = re.compile(r"[?&](?:mes|month)=(?:0?[1-9]|1[0-2])\b")
    _RE_DIA_QUERY = re.compile(r"[?&](?:dia|day)=(?:0?[1-9]|[12]\d|3[01])\b")

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

    @classmethod
    def _extraer_anno_calendario(cls, url: str) -> int | None:
        """
        Año de una página de calendario, probando varios esquemas de fecha.

        Ningún ayuntamiento escribe la fecha igual: unos usan /2026/8/11/, otros
        /11/8/2026/, otros 2026-08-11 en la ruta, otros la llevan en la query
        (?fecha=2026-08-11 o ?anyo=2026&mes=8&dia=11). Se prueban todos; el
        primero que reconozca la URL gana. Si no se reconoce ninguno, devuelve
        None y la URL no se trata como calendario a efectos de año.
        """
        match = cls.RE_CALENDAR_DATE_URL.search(url)
        if match:
            anno_str = match.group(0).strip("/").split("/")[0]
            try:
                return int(anno_str)
            except ValueError:
                pass

        for patron in cls._RE_FECHA_ANNO_ALT:
            m = patron.search(url)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue

        m_anno = cls._RE_ANNO_QUERY.search(url)
        if m_anno and cls._RE_MES_QUERY.search(url) and cls._RE_DIA_QUERY.search(url):
            try:
                return int(m_anno.group(1))
            except ValueError:
                pass

        return None

    # ───── Utilidades ─────

    @staticmethod
    def _is_internal(base_url: str, url: str) -> bool:
        return urllib.parse.urlparse(base_url).netloc == urllib.parse.urlparse(url).netloc

    @staticmethod
    def _nombre_de_dominio(url: str) -> str:
        """
        El nombre del dominio sin TLD ni `www`: de `www.tobarra.es` saca `tobarra`.

        Se compara por el NOMBRE y no por el dominio entero a propósito. En el
        histórico hay redirecciones legítimas que cambian de dominio registrable
        y siguen siendo el mismo ayuntamiento: `villagarciadelatorre.es →
        villagarciadelatorre.com` y `ayuntamientodeoyon.com →
        ayuntamientodeoyon.eus`. Compararlas enteras las daría por saltos ajenos.
        """
        host = urllib.parse.urlparse(url if url.startswith("http") else "http://" + url).netloc
        host = host.split(":")[0].lower().removeprefix("www.")
        # Punycode a texto: `xn--alfozdequintanadueas-l7b.es` y
        # `alfozdequintanadueñas.es` son el MISMO dominio, y sin decodificar
        # parecían un salto a otro sitio. Es una redirección real del histórico.
        partes = []
        for p in host.split("."):
            if not p:
                continue
            if p.startswith("xn--"):
                try:
                    p = p.encode("ascii").decode("idna")
                except (UnicodeError, UnicodeDecodeError):
                    pass
            partes.append(p)
        if not partes:
            return ""
        # Dominios de segundo nivel del tipo `.co.uk` o `.com.es`: el nombre está
        # una posición más a la izquierda.
        if len(partes) >= 3 and partes[-2] in ("co", "com", "org", "gob", "net"):
            return partes[-3]
        return partes[-2] if len(partes) >= 2 else partes[0]

    @classmethod
    def salta_a_otro_dominio(cls, url_original: str, url_final: str) -> bool:
        """
        ¿La redirección nos ha sacado de la web del municipio?

        Medido el 2026-09-04: `santamartadelosbarros.com` redirige a `badajoz.es`
        —el portal de la Diputación—, y la araña mapeó 77 páginas de la
        Diputación que entraron como 76 documentos `web_municipio` de Santa Marta.
        Ninguna hablaba de sus fiestas, y el contexto de discovery se llenó con
        ellas y con el pueblo homónimo de Colombia.

        Es el único caso de ~30 municipios del histórico, así que la regla es
        deliberadamente conservadora: solo salta cuando el nombre del dominio
        cambia por completo. Un falso positivo aquí cuesta el rastreo entero de
        un municipio, que es bastante peor que el ruido que evita.
        """
        a, b = cls._nombre_de_dominio(url_original), cls._nombre_de_dominio(url_final)
        if not a or not b or a == b:
            return False
        # Un nombre contenido en el otro es la misma entidad alargándose o
        # acortándose: `amurrio` → `udala.amurrio`, `oyon` → `ayuntamientodeoyon`.
        return not (a in b or b in a)

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

        # 6. Penalizar páginas de calendario vacío (e.g. /?date=20260801)
        RE_QUERY_DATE = re.compile(r"[?&]date=\d{6,8}", re.IGNORECASE)
        if RE_QUERY_DATE.search(url_lower):
            texto_util = page_text.strip()
            if len(texto_util) < 300:
                score -= 500  # página vacía de calendario, penalizar fuertemente
            else:
                score -= 100  # puede tener algo de contenido, penalizar moderadamente

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

                    # Filtro de calendario por AÑO, no por cantidad. El tope fijo
                    # (antes 3 páginas por dominio de calendario) descartaba los
                    # días de la fiesta real por orden de llegada: si las fiestas
                    # son del 11 al 17 de agosto, las primeras 3 páginas de
                    # calendario que encuentra el crawler casi nunca son esas.
                    # Ahora se acepta cualquier cantidad de páginas de calendario
                    # siempre que sean del año objetivo; solo se descartan las de
                    # otros años. Si no se reconoce el esquema de fecha de la URL,
                    # se deja pasar (no se penaliza lo que no se sabe leer).
                    anno_cal = self._extraer_anno_calendario(url)
                    if anno_cal is not None and anno_cal != year:
                        continue

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
                                # Contexto REAL del enlace: el bloque que lo contiene.
                                # Antes se usaba page_text[:500], que en una portada
                                # son los menús del sitio y hacía pasar el filtro a
                                # cualquier PDF colgado de un ayuntamiento.
                                contenedor = a.find_parent(["li", "p", "td", "h1", "h2", "h3", "article", "section", "div"])
                                contexto_enlace = contenedor.get_text(" ", strip=True)[:300] if contenedor else link_text
                                pdf_links.append((pdf_url, link_text, contexto_enlace))

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

                            # Filtro preventivo de enlaces de calendario por AÑO
                            # (ver comentario en el filtro equivalente más arriba).
                            anno_cal_link = self._extraer_anno_calendario(link_url)
                            if anno_cal_link is not None and anno_cal_link != year:
                                continue

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

    async def _process_single_page(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        rank: int,
        score: int,
        url: str,
        page_text: str,
        pdf_links: list,
        img_infos: list,
        locality_names: list[str],
        fuente: str,
        visited_urls: set | None,
    ) -> list[dict]:
        """Procesa una sola página del Top N: texto + PDFs + imágenes."""
        if score < 0:
            return []

        # Filtrar dominios de RRSS (no scrapeables por JS)
        parsed_domain = urllib.parse.urlparse(url).netloc.lower()
        if any(d in parsed_domain for d in _EXTERNAL_DOMAIN_BLOCKLIST):
            logger.debug(f"  [Skip] Dominio social no scrapeable: {url[:70]}")
            return []

        logger.info(f"  [Top {rank + 1} / Score: {score}] {url[:70]}...")
        docs = [crear_documento(fuente, url, page_text, tipo="pagina",
                                score_spider=score, rank_spider=rank)]

        # ─── PDFs: filtrar por relevancia antes de descargar ───
        # El mismo PDF suele estar enlazado desde varias páginas del sitio. Antes
        # se añadía a `visited_urls` pero nunca se comprobaba, así que las páginas
        # del mismo lote concurrente lo descargaban e indexaban por duplicado
        # (en Amurrio, tres copias del PDF de presupuestos coparon el contexto).
        # La comprobación y el alta van juntas y sin `await` entre medias, de modo
        # que son atómicas dentro del bucle de eventos.
        pdf_tasks = []
        pdf_urls_pedidas = []
        for pdf_url, link_text, contexto_enlace in pdf_links:
            pdf_limpia = self._clean_url(pdf_url)
            if visited_urls is not None and pdf_limpia in visited_urls:
                continue
            if is_promising_pdf(pdf_url, link_text, contexto_enlace, target_year=self.target_year):
                if visited_urls is not None:
                    visited_urls.add(pdf_limpia)
                pdf_tasks.append(self._extract_pdf(session, pdf_url, semaphore))
                pdf_urls_pedidas.append(pdf_url)

        if pdf_tasks:
            logger.info(f"    Descargando {len(pdf_tasks)} PDFs prometedores...")
            pdf_results = await asyncio.gather(*pdf_tasks, return_exceptions=True)
            for pdf_url, pdf_text in zip(pdf_urls_pedidas, pdf_results):
                if isinstance(pdf_text, str) and pdf_text:
                    docs.append(crear_documento(fuente, pdf_url, pdf_text, tipo="pdf",
                                                score_spider=score, rank_spider=rank))

        # ─── Imágenes: filtrar agresivamente antes de OCR ───
        # Misma dedup para las imágenes: un cartel enlazado desde la portada y desde
        # la noticia se OCRizaba dos veces, con el coste de OCR duplicado.
        img_tasks = []
        img_urls_pedidas = []
        for img_url, alt_text in img_infos:
            img_limpia = self._clean_url(img_url)
            if visited_urls is not None and img_limpia in visited_urls:
                continue
            if is_promising_image(img_url, alt_text, locality_names):
                if visited_urls is not None:
                    visited_urls.add(img_limpia)
                img_tasks.append(self._extract_image(session, img_url, semaphore))
                img_urls_pedidas.append(img_url)

        # Limitar OCR por página para evitar saturación (ej. webs turísticas con 26 fotos)
        if len(img_tasks) > MAX_IMAGES_PER_PAGE:
            logger.debug(f"    Limitando OCR de {len(img_tasks)} → {MAX_IMAGES_PER_PAGE} imágenes")
            # Cerrar las coroutines descartadas para evitar RuntimeWarning
            for discarded in img_tasks[MAX_IMAGES_PER_PAGE:]:
                discarded.close()
            img_tasks = img_tasks[:MAX_IMAGES_PER_PAGE]
            img_urls_pedidas = img_urls_pedidas[:MAX_IMAGES_PER_PAGE]

        if img_tasks:
            logger.info(f"    OCR en {len(img_tasks)} imágenes prometedoras...")
            img_results = await asyncio.gather(*img_tasks, return_exceptions=True)
            for img_url, ocr_text in zip(img_urls_pedidas, img_results):
                if isinstance(ocr_text, str) and ocr_text.strip():
                    docs.append(crear_documento(fuente, img_url, ocr_text, tipo="cartel",
                                                score_spider=score, rank_spider=rank))

        return docs

    async def pass_2_heavy_extraction(
        self,
        scored_pages: list,
        locality_names: list[str],
        fuente: str,
        visited_urls: set | None = None,
    ) -> list[dict]:
        """Pasada 2: OCR y PDFs del Top N en batches paralelos (PASS2_BATCH_SIZE páginas a la vez)."""
        logger.info(f"[Pasada 2] Extracción profunda del Top {self.max_extraction_pages} (batches de {PASS2_BATCH_SIZE})...")
        top_pages = scored_pages[: self.max_extraction_pages]

        documentos = []
        semaphore = asyncio.Semaphore(self.concurrency)
        headers = {"User-Agent": USER_AGENT}
        connector = aiohttp.TCPConnector(limit=self.concurrency, ssl=False)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            for batch_start in range(0, len(top_pages), PASS2_BATCH_SIZE):
                batch = top_pages[batch_start:batch_start + PASS2_BATCH_SIZE]
                tasks = [
                    self._process_single_page(
                        session, semaphore, batch_start + j,
                        score, url, page_text, pdf_links, img_infos,
                        locality_names, fuente, visited_urls,
                    )
                    for j, (score, url, page_text, pdf_links, img_infos) in enumerate(batch)
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in batch_results:
                    if isinstance(result, list):
                        documentos.extend(result)
                    elif isinstance(result, Exception):
                        logger.warning(f"Error en extracción de página: {result}")

        return documentos

    async def _extract_pdf(self, session, pdf_url, semaphore):
        """Descarga y extrae texto de un PDF (aislado en subproceso para evitar segfaults)."""
        pdf_bytes = await self._fetch_bytes(session, pdf_url, semaphore)
        if not pdf_bytes:
            return ""
        
        loop = asyncio.get_event_loop()
        try:
            pool = _get_ocr_pool()
            text = await loop.run_in_executor(pool, _subprocess_extract_pdf, pdf_bytes)
            return text
        except Exception as e:
            if "BrokenProcessPool" in type(e).__name__:
                logger.warning(f"  [Segfault/Crash] en subproceso al extraer PDF {pdf_url}. Reiniciando pool.")
                _reset_ocr_pool()
            else:
                logger.debug(f"  Error al extraer PDF {pdf_url}: {e}")
            return ""

    async def _extract_image(self, session, img_url, semaphore):
        """Descarga y extrae texto OCR de una imagen (aislado en subproceso para evitar segfaults)."""
        try:
            async with semaphore:
                async with session.head(img_url, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as resp:
                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) < IMAGE_MIN_SIZE_BYTES:
                        return ""
        except Exception:
            pass  # Si HEAD falla, intentar GET de todas formas

        img_bytes = await self._fetch_bytes(session, img_url, semaphore, max_size=15_000_000)
        if not img_bytes or len(img_bytes) < IMAGE_MIN_SIZE_BYTES:
            return ""
            
        loop = asyncio.get_event_loop()
        try:
            pool = _get_ocr_pool()
            text = await loop.run_in_executor(pool, _subprocess_extract_image, img_bytes)
            if not (text or "").strip():
                # El OCR no ha sacado nada de un cartel que `is_promising_image`
                # ya dio por probable. Es el caso que mas necesita al VLM: una
                # tipografia decorativa sobre un fondo con dibujos derrota a
                # Tesseract. Y medido sobre texto negro limpio en fuente
                # estandar, Tesseract leyo "2028" donde ponia 2026 y "20.00"
                # donde ponia 20:00, asi que aqui no se pierde gran cosa.
                #
                # La llamada se hace AQUI y no en el subproceso: este metodo es
                # async y ya tiene los bytes, mientras que el subproceso esta
                # aislado a proposito —el OCR segfaultea y por eso vive alli— y
                # las imagenes PIL no cruzan esa frontera.
                text = await self._leer_cartel_con_vlm(img_bytes, img_url)
            return text
        except Exception as e:
            if "BrokenProcessPool" in type(e).__name__:
                logger.warning(f"  [Segfault/Crash] en subproceso al procesar imagen {img_url}. Reiniciando pool.")
                _reset_ocr_pool()
            else:
                logger.debug(f"  Error al extraer imagen {img_url}: {e}")
            return ""

    async def _leer_cartel_con_vlm(self, img_bytes: bytes, img_url: str) -> str:
        """Lee como cartel una imagen que el OCR no ha conseguido descifrar.

        Solo llegan aqui las que `is_promising_image` ya considero probables
        carteles de fiestas, asi que el filtrado por relevancia esta hecho antes.

        El tope es por rastreo entero, no por imagen: una galeria de fotos de la
        fiesta del ano pasado puede traer cuarenta candidatas, y cada llamada al
        VLM tiene su timeout de 180 s.
        """
        if getattr(self, "_vlm_usados", 0) >= VISION_MAX_IMAGES_SPIDER:
            return ""
        try:
            from config import VISION_ENABLED
            if not VISION_ENABLED:
                return ""
            from PIL import Image
            from llm_processor.vision_analyzer import analizar_imagen_directa
        except Exception as e:
            logger.debug(f"  [VISION] no disponible ({type(e).__name__}); se omite.")
            return ""

        try:
            img = Image.open(io.BytesIO(img_bytes))
            img.load()
        except Exception as e:
            logger.debug(f"  [VISION] imagen ilegible {img_url[:60]}: {type(e).__name__}")
            return ""

        self._vlm_usados = getattr(self, "_vlm_usados", 0) + 1
        try:
            texto = await analizar_imagen_directa(img)
        except Exception as e:
            logger.warning(f"  [VISION] fallo leyendo {img_url[:60]}: {type(e).__name__}")
            return ""

        if not (texto or "").strip():
            return ""
        logger.info(
            f"  [VISION] cartel leido en {img_url[:70]} ({len(texto)} caracteres); "
            f"el OCR no habia sacado nada."
        )
        return MARCA_VISION + chr(10) + texto.strip()


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
        url_pedida = start_url
        start_url = await self.resolver_url_final(start_url)
        # …pero si la redirección nos ha sacado del municipio, no se rastrea:
        # lo que hay al otro lado es otra web, y sus páginas entrarían etiquetadas
        # como `web_municipio`. Ver `salta_a_otro_dominio`.
        if self.salta_a_otro_dominio(url_pedida, start_url):
            logger.warning(
                f"  [Spider] {url_pedida} redirige a {start_url}, que es otra web. "
                f"No se rastrea: se seguirá solo con la búsqueda web."
            )
            return []
        scored_pages = await self.pass_1_map_and_score(start_url, locality_names, visited_urls, target_year=self.target_year)
        if not scored_pages:
            logger.warning(f"No se encontraron páginas en {start_url}")
            return []
        return await self.pass_2_heavy_extraction(scored_pages, locality_names, fuente, visited_urls)

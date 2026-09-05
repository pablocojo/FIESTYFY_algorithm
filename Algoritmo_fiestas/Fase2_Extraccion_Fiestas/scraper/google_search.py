"""
Módulo de búsqueda externa — DuckDuckGo con múltiples queries y seguimiento de URLs.

Genera 3 variaciones de búsqueda por localidad, extrae snippets y
sigue las top N URLs para descargar contenido completo de noticias/webs.
"""

import asyncio
import urllib.parse
import logging
import re
import unicodedata
import json

import aiohttp
from bs4 import BeautifulSoup

from config import (
    DDG_MAX_URLS_TO_FOLLOW,
    DDG_DELAY_MIN,
    DDG_DELAY_MAX,
    DDG_DELAY_BETWEEN_QUERIES,
    DDG_REQUEST_TIMEOUT,
    DDG_MAX_RETRIES,
    DDG_RETRY_BACKOFF,
    DESCARGA_MAX_INTENTOS,
    DESCARGA_BACKOFF,
    DESCARGA_TIMEOUT_PDF,
    DESCARGA_TIMEOUT_MAX,
    DDG_CONTENT_MAX_CHARS,
    USER_AGENT,
    MIN_RESULTADOS_DESEADOS,
    MAX_MOTORES_POR_CONSULTA,
    SEARXNG_SEARCH_URL,
    SEARXNG_TIMEOUT,
    SEARXNG_IDIOMA,
    SEARXNG_MAX_RESULTADOS,
    DOMINIOS_AGREGADORES,
    BUSQUEDA_SEGUIR_PDFS,
    BUSQUEDA_MAX_PDFS_POR_PAGINA,
    BUSQUEDA_MAX_PDFS_TOTAL,
    BUSQUEDA_MIN_CHARS_PAGINA,
    BUSQUEDA_MAX_RENDERS_NAVEGADOR,
    BUSQUEDA_SEGUIR_ENLACES,
    BUSQUEDA_MAX_ENLACES_POR_PAGINA,
    BUSQUEDA_MAX_ENLACES_TOTAL,
)
from fuentes import (
    crear_documento,
    FUENTE_BUSQUEDA,
    FUENTE_PRENSA_REGIONAL,
    get_medios_prensa_por_provincia,
)
from config_idiomas import comunidad_de, get_language_profile, perfil_de_lugar
import cache_paginas

logger = logging.getLogger("search")

# Métricas de búsqueda (Requisito R6)
_SEARCH_METRICS = {
    "failed_searches": 0,
}


def get_failed_searches_count() -> int:
    """Devuelve el número total de búsquedas fallidas o bloqueadas."""
    return _SEARCH_METRICS["failed_searches"]


def reset_search_metrics() -> None:
    """Reinicia el contador de métricas de búsqueda."""
    _SEARCH_METRICS["failed_searches"] = 0


def registrar_busqueda_fallida() -> None:
    """Incrementa el contador de búsquedas fallidas/bloqueadas."""
    _SEARCH_METRICS["failed_searches"] += 1



def _mismo_nombre(a: str, b: str) -> str:
    """Compara dos topónimos sin tildes, mayúsculas ni puntuación."""
    def clave(s):
        s = unicodedata.normalize("NFKD", (s or "").lower())
        s = "".join(c for c in s if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9]+", "", s)
    return clave(a) == clave(b)


def _misma_web_simple(a: str, b: str) -> bool:
    """Misma web con distinta forma de escribirla (esquema, www., barra final)."""
    def clave(u):
        u = (u or "").strip().lower()
        u = re.sub(r"^https?://", "", u)
        return re.sub(r"^www\.", "", u).rstrip("/")
    return bool(clave(a)) and clave(a) == clave(b)


def _build_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    """Genera múltiples variaciones de búsqueda para maximizar cobertura."""
    if not isinstance(localidad, dict):
        localidad = {}
    if not isinstance(municipio, dict):
        municipio = {}

    nombre_loc = (localidad.get("nombre") or "").strip()
    nombre_mun = (municipio.get("nombre") or "").strip()

    if not nombre_loc and not nombre_mun:
        return []
    if not nombre_loc:
        nombre_loc = nombre_mun
    if not nombre_mun:
        nombre_mun = nombre_loc

    provincia = (municipio.get("provincia") or "").strip()
    comunidad = comunidad_de(municipio)
    sitio_web_mun = (municipio.get("sitio_web") or "").strip()
    sitio_web_loc = (localidad.get("sitio_web") or "").strip()

    perfil_data = get_language_profile(comunidad, provincia)
    kws = perfil_data["perfil_principal"]["keywords_busqueda"]
    kw1 = kws[0] if kws else "fiestas"
    kw2 = kws[1] if len(kws) > 1 else kw1
    kw3 = kws[2] if len(kws) > 2 else kw1

    # El municipio solo se añade si NO es el mismo nombre que la localidad. En una
    # capital lo era, y la consulta salía como "fiestas patronales Tobarra Tobarra
    # 2026": medido el 2026-08-23, ninguna de esas devolvió jamás un resultado, y
    # eran una de cada cinco consultas de la ejecución.
    donde = nombre_loc if _mismo_nombre(nombre_loc, nombre_mun) else f"{nombre_loc} {nombre_mun}"

    # TODA consulta lleva un desambiguador. Medido el 2026-09-04: de 113
    # consultas, 80 —el 71%— preguntaban el nombre del pueblo a secas, y con eso
    # "Santa Marta" devuelve la ciudad colombiana de 500.000 habitantes antes que
    # el pueblo pacense de 4.199. El contexto de discovery acabó encabezado por
    # Colombia (23 chunks) y Astorga (12), y la fiesta real nunca llegó al modelo.
    #
    # Pero NO todas llevan el mismo, y esto importa: hay fuentes legítimas que no
    # nombran la provincia jamás —la web del propio pueblo, la prensa comarcal—.
    # Si todas las consultas la exigieran, arreglaríamos Santa Marta y romperíamos
    # los municipios que hoy funcionan. Así que se reparten tres desambiguadores
    # distintos: provincia, nombre oficial completo y el operador site:.
    geo = provincia or comunidad

    # El nombre oficial completo del municipio, si `main.py` lo ha resuelto:
    # "Santa Marta" → "Santa Marta de los Barros". Para una pedanía se combina con
    # el suyo, que es como lo escriben las fuentes: "Aljubé, Tobarra".
    oficial_mun = (municipio.get("nombre_oficial") or "").strip() or nombre_mun
    if _mismo_nombre(nombre_loc, nombre_mun):
        donde_oficial = oficial_mun
    else:
        donde_oficial = f"{nombre_loc} {oficial_mun}"
    # La mayoría de municipios no tiene apellido —"Tobarra" es "Tobarra"— y ahí
    # esta consulta se quedaría sin desambiguar. Se le pone la COMUNIDAD, no la
    # provincia: es más ancha, estrecha menos, y así las tres primeras consultas
    # siguen usando tres criterios distintos en vez de repetir el mismo.
    if _mismo_nombre(donde_oficial, donde) and comunidad:
        donde_oficial = f"{donde_oficial} {comunidad}"

    queries = [
        f"{kw1} {donde} {geo} {anno}",
        # Esta va por el nombre oficial en vez de por la provincia: si el nombre
        # largo ya distingue al pueblo, exigir además la provincia estrecharía de
        # más y dejaría fuera a su propia web.
        f"{kw2} {donde_oficial} {anno}",
        f"{kw3} {nombre_loc} {provincia} {anno}",
    ]

    # El patrón es lo que de verdad identifica una fiesta patronal, y hasta ahora
    # no se usaba para buscar. Sin él dependíamos de que el snippet correcto
    # apareciese ese día: la patronal de mayo de Tobarra —el Santísimo Cristo de
    # la Antigua— entró en dos ejecuciones y se perdió en la tercera. Buscándola
    # por su nombre, se encuentra siempre.
    patron = (localidad.get("patron_nombre") or "").strip()
    if patron:
        queries.append(f"{kw1} {patron} {nombre_loc} {geo} {anno}")
        # Esta se queda ANCHA a propósito: sin año y sin geografía. La advocación
        # ("Stmo. Cristo de la Antigua") ya es muy específica, y encadenarle
        # provincia y comunidad producía trabalenguas como "Aljubé Tobarra
        # Castilla-La Mancha fiestas patronales San Isidro", que ningún motor
        # casa. Es la vía de escape para las fuentes que no nombran la provincia.
        queries.append(f"{donde} {kw1} {patron}")

    sitios_site = []
    if sitio_web_mun:
        sitios_site.append(sitio_web_mun)
    if sitio_web_loc and not _misma_web_simple(sitio_web_loc, sitio_web_mun):
        sitios_site.append(sitio_web_loc)

    for sitio in sitios_site:
        url_to_parse = sitio if sitio.startswith("http") else "http://" + sitio
        domain = urllib.parse.urlparse(url_to_parse).netloc
        if domain:
            queries.append(f"{kw1} {nombre_loc} {anno} site:{domain}")

    # Sin duplicados: dos plantillas distintas pueden producir la misma consulta.
    # El espaciado se normaliza aquí porque las plantillas interpolan campos que
    # pueden venir vacíos —provincia, comunidad— y dejan dobles espacios.
    vistas, unicas = set(), []
    for q in queries:
        q = " ".join(q.split())
        clave = q.lower()
        if q and clave not in vistas:
            vistas.add(clave)
            unicas.append(q)
    return unicas

import urllib.request
import urllib.parse
import time
import random
import base64
import gzip
import zlib
import urllib.error

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
]

def get_random_user_agent() -> str:
    """Devuelve un User-Agent aleatorio de la lista de navegadores realistas."""
    return random.choice(USER_AGENTS)

def _get_random_headers() -> dict:
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        # Sin Accept-Encoding varios motores (Brave entre ellos) responden 403.
        # La descompresión la hace _http_get.
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _http_get(url: str, timeout: float = None) -> tuple[int, bytes]:
    """
    GET con cabeceras de navegador y descompresión gzip/deflate.

    Devuelve (status, cuerpo). status 429/403 se propagan para que el motor
    entre en enfriamiento en vez de reintentarse en bucle.
    """
    timeout = DDG_REQUEST_TIMEOUT if timeout is None else timeout
    req = urllib.request.Request(url, headers=_get_random_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cuerpo = resp.read()
            codificacion = (resp.headers.get("Content-Encoding") or "").lower()
            if codificacion == "gzip":
                try:
                    cuerpo = gzip.decompress(cuerpo)
                except Exception:
                    pass
            elif codificacion == "deflate":
                try:
                    cuerpo = zlib.decompress(cuerpo, -zlib.MAX_WBITS)
                except Exception:
                    pass
            return resp.status, cuerpo
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        logger.debug(f"HTTP error en {url[:80]}: {e}")
        return 0, b""


# ── Enfriamiento por motor ────────────────────────────────────────────────────
# Brave y Mojeek responden 429/403 en cuanto se les insiste. Reintentarlos en el
# mismo minuto solo gasta tiempo y engorda el contador de búsquedas fallidas, así
# que un motor que rechaza queda apartado un rato.
_ENGINE_COOLDOWN: dict[str, float] = {}
# Respuestas incoherentes consecutivas por motor (ver _resultados_coherentes)
_INCOHERENTES_SEGUIDAS: dict[str, int] = {}
INCOHERENTES_PARA_ENFRIAR = 2
COOLDOWN_TRAS_BLOQUEO = 180.0  # segundos


def _motor_disponible(nombre: str) -> bool:
    hasta = _ENGINE_COOLDOWN.get(nombre, 0.0)
    return time.monotonic() >= hasta


def _enfriar_motor(nombre: str, segundos: float = COOLDOWN_TRAS_BLOQUEO) -> None:
    _ENGINE_COOLDOWN[nombre] = time.monotonic() + segundos
    logger.debug(f"  [{nombre}] en enfriamiento {segundos:.0f}s tras bloqueo")


# URLs que los buscadores mezclan con los resultados y no son resultados:
# anuncios, páginas de ayuda del propio buscador, redirecciones internas.
_PATRONES_URL_BASURA = (
    "duckduckgo.com/y.js",
    "duckduckgo.com/duckduckgo-help-pages",
    "duckduckgo.com/l/?",
    "bing.com/ck/a",
    "go.microsoft.com",
    "/aclk?",
    "googleadservices.com",
)


def _es_url_basura(url: str) -> bool:
    u = (url or "").lower()
    return any(p in u for p in _PATRONES_URL_BASURA)


_RE_PALABRA_CONSULTA = re.compile(r"[a-záéíóúüñ]{4,}", re.IGNORECASE)


def _terminos_significativos(query: str) -> set:
    """Palabras de la consulta que deberían dejar huella en un resultado legítimo."""
    limpia = re.sub(r"\bsite:\S+", " ", query or "")
    limpia = re.sub(r"\b20\d{2}\b", " ", limpia)
    limpia = _normalizar_basico(limpia)
    genericas = {
        "fiestas", "fiesta", "patronales", "programa", "programacion", "cartel",
        "festes", "festa", "major", "patronals", "jaiak", "egitaraua", "festak",
        "festas", "patronais", "actos", "eventos", "actividades",
    }
    return {p for p in _RE_PALABRA_CONSULTA.findall(limpia)} - genericas


def _normalizar_basico(texto: str) -> str:
    import unicodedata
    texto = (texto or "").lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _resultados_coherentes(query: str, results: list[dict]) -> bool:
    """
    ¿Tienen los resultados algo que ver con lo que se ha preguntado?

    Bing no bloquea cuando detecta scraping: ENVENENA. Medido el 2026-08-21, a
    la consulta "festa major Terrassa 2026" devolvió diez resultados con
    apariencia normal que eran Yandex Música, tiendas de impresoras y páginas de
    soporte de Microsoft en ruso. Un 403 se detecta solo; esto se colaba entero
    en el corpus y desplazaba material bueno.

    El criterio es NINGÚN resultado menciona ningún término distintivo de la
    consulta. Se exige solapamiento cero, no "poco solapamiento", porque el
    nombre del dataset y el que usa la web no siempre coinciden: el municipio
    08279000000 figura como "Tarrasa" y toda la web lo llama "Terrassa". Con un
    umbral por fracción, esas consultas se descartaban enteras siendo buenas.
    Cero coincidencias sobre diez resultados sí es inequívoco.
    """
    terminos = _terminos_significativos(query)
    if not terminos or not results:
        return True  # sin nada que comprobar, no se penaliza

    for r in results:
        campos = _normalizar_basico(
            f"{r.get('url','')} {r.get('titulo','')} {r.get('snippet','')}"
        )
        if any(t in campos for t in terminos):
            return True

    return False


_RE_PISTA_PROGRAMA = re.compile(
    r"programa|programacio|egitarau|kartel|cartel|jaiak|fiestas|festes|festa|"
    r"festas|agenda|actos|actes|ekitaldi",
    re.IGNORECASE,
)


def _priorizar_urls(urls: list[str], localidad: dict, municipio: dict) -> list[str]:
    """
    Ordena las URLs de resultado por probabilidad de llevar al programa.

    Criterios, de más a menos peso:
      1. Está en el dominio oficial del municipio o de la localidad.
      2. Es un PDF (el programa suele serlo).
      3. La URL menciona programa/cartel/fiestas/agenda.
      4. La URL menciona el nombre de la localidad.
      5. PENALIZACIÓN si es un directorio SEO conocido.

    El criterio 5 se añadió el 2026-09-06: de las 21 fiestas sin programa de la
    ejecución del 2026-09-05, 9 habían acabado señalando un agregador. Se hunde
    en vez de eliminarse porque en municipios sin web propia es lo único que hay,
    y un directorio con las fechas bien vale más que nada.

    Es una ordenación estable: a igualdad de puntuación se respeta el orden de
    llegada, que ya venía por calidad del motor.
    """
    dominios = set()
    for fuente in (municipio.get("sitio_web"), localidad.get("sitio_web")):
        fuente = (fuente or "").strip()
        if not fuente:
            continue
        if not fuente.startswith("http"):
            fuente = "https://" + fuente
        netloc = urllib.parse.urlparse(fuente).netloc.lower()
        if netloc:
            dominios.add(netloc)
            partes = netloc.split(".")
            if len(partes) >= 2:
                dominios.add(".".join(partes[-2:]))  # cubre subdominios (udala.amurrio.eus)

    nombre_loc = _normalizar_basico(localidad.get("nombre") or "")

    def puntuar(url: str) -> int:
        u = url.lower()
        un = _normalizar_basico(url)
        p = 0
        if any(d in u for d in dominios):
            p += 100
        if u.split("?")[0].endswith(".pdf"):
            p += 40
        if _RE_PISTA_PROGRAMA.search(u):
            p += 20
        if nombre_loc and len(nombre_loc) >= 4 and nombre_loc in un:
            p += 10
        if any(d in u for d in DOMINIOS_AGREGADORES):
            # -60 lo deja por debajo de cualquier pista de programa (+20) pero
            # sin poder superar al dominio oficial (+100): si la web del
            # ayuntamiento aparece, gana siempre.
            p -= 60
        return p

    return sorted(urls, key=lambda u: -puntuar(u))


def _limpiar_redireccion_yahoo(url: str) -> str:
    """Yahoo envuelve algunos resultados en r.search.yahoo.com/...;/RU=<urlencoded>/RK=..."""
    if "search.yahoo.com" not in url or "/RU=" not in url:
        return url
    try:
        trozo = url.split("/RU=", 1)[1].split("/", 1)[0]
        destino = urllib.parse.unquote(trozo)
        return destino if destino.startswith("http") else url
    except Exception:
        return url


def _decodificar_url_bing(url: str) -> str:
    """
    Devuelve la URL real que esconde un enlace de rastreo de Bing.

    Bing sirve casi todos sus resultados como
    `https://www.bing.com/ck/a?!&&p=<hash>&u=a1<base64url>&ntb=1`.
    Sin deshacer eso, lo que llegaba al pipeline era la URL de bing.com: medido
    el 2026-08-21, el 100% de los resultados de Bing eran inservibles (0 de 36
    consultas aportaron una URL utilizable) y 5 de esas redirecciones acabaron
    indexadas como documentos del corpus.
    """
    if "bing.com/ck/a" not in url:
        return url
    try:
        parametros = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        crudo = (parametros.get("u") or [""])[0]
        if not crudo.startswith("a1"):
            return url
        b64 = crudo[2:]
        b64 += "=" * (-len(b64) % 4)
        decodificada = base64.urlsafe_b64decode(b64).decode("utf-8", errors="replace")
        return decodificada if decodificada.startswith("http") else url
    except Exception:
        return url

def get_query_delay() -> float:
    """Devuelve un delay aleatorio entre DDG_DELAY_MIN y DDG_DELAY_MAX (2.0 a 4.5 segundos)."""
    return random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX)

def calculate_backoff_delay(attempt: int, base_backoff: float = DDG_RETRY_BACKOFF) -> float:
    """
    Calcula el tiempo de espera con backoff exponencial y jitter aleatorio.
    Fórmula: (base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)
    """
    return (base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)

def _sync_fetch_searxng(query: str) -> list[dict]:
    """Metabuscador propio. Es el motor primario.

    A diferencia de los demás no se scrapea HTML: SearXNG devuelve JSON, así que
    no hay que parsear ni deshacer redirecciones. Y como por dentro consulta
    varios motores y fusiona, un bloqueo puntual de uno de ellos ya no deja la
    consulta a ciegas, que era lo que producía los contextos de una sola URL.

    Se enfría igual que el resto si deja de responder, pero por otro motivo: aquí
    un fallo significa que el contenedor no está levantado, no que nos hayan
    detectado. El aviso lo dice para no mandar a nadie a buscar un bloqueo que no
    existe.
    """
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "language": SEARXNG_IDIOMA,
    })
    url = f"{SEARXNG_SEARCH_URL}?{params}"

    try:
        status, body = _http_get(url, timeout=SEARXNG_TIMEOUT)
    except Exception as e:
        _enfriar_motor("SearXNG")
        logger.warning(
            f"  [SearXNG] no responde ({type(e).__name__}). ¿Está levantado el "
            f"contenedor en {SEARXNG_SEARCH_URL}? Se sigue con los otros motores."
        )
        return []

    if status != 200 or not body:
        _enfriar_motor("SearXNG")
        logger.warning(
            f"  [SearXNG] HTTP {status} en {SEARXNG_SEARCH_URL}. Si es un 403, "
            f"revisar que `formats: [html, json]` sigue en su settings.yml."
        )
        return []

    try:
        datos = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        # Sin `json` en los formatos permitidos, SearXNG sirve HTML con un 200:
        # se detecta aquí y no como un fallo de red.
        _enfriar_motor("SearXNG")
        logger.warning(
            "  [SearXNG] respondió algo que no es JSON. Falta `formats: [html, "
            "json]` en settings.yml."
        )
        return []

    resultados = []
    for item in (datos.get("results") or [])[:SEARXNG_MAX_RESULTADOS]:
        u = (item.get("url") or "").strip()
        if not u:
            continue
        resultados.append({
            "titulo": (item.get("title") or "").strip(),
            "snippet": (item.get("content") or "").strip(),
            "url": u,
        })
    return resultados


def _sync_fetch_ddg(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

    status, html = _http_get(url)
    if status in (403, 429):
        _enfriar_motor("DuckDuckGo")
        return []
    if status != 200 or not html:
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


def _sync_fetch_ddg_lite(query: str) -> list[dict]:
    """Endpoint alternativo de DuckDuckGo.

    Sirve el mismo índice con otro HTML y otro perfil de rate-limit, así que
    rescata consultas que el endpoint /html/ deja vacías.
    """
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://lite.duckduckgo.com/lite/?q={encoded_query}"

    status, html = _http_get(url)
    if status in (403, 429):
        _enfriar_motor("DDG-lite")
        return []
    if status != 200 or not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a_tag in soup.find_all("a", class_="result-link"):
        result_url = a_tag.get("href", "")
        if result_url.startswith("//duckduckgo.com/l/?uddg="):
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(result_url).query)
            if "uddg" in parsed:
                result_url = parsed["uddg"][0]
        if not result_url.startswith("http"):
            continue
        titulo = a_tag.get_text(strip=True)
        # El snippet va en la fila siguiente de la tabla
        snippet = ""
        fila = a_tag.find_parent("tr")
        if fila is not None:
            siguiente = fila.find_next_sibling("tr")
            if siguiente is not None:
                celda = siguiente.find("td", class_="result-snippet")
                if celda is not None:
                    snippet = celda.get_text(strip=True)
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results


def _sync_fetch_yahoo(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://es.search.yahoo.com/search?p={encoded_query}"

    status, html = _http_get(url)
    if status in (403, 429):
        _enfriar_motor("Yahoo")
        return []
    if status != 200 or not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for div in soup.find_all("div", class_="compTitle"):
        h3 = div.find("h3", class_="title")
        if not h3: continue
        a_tag = h3.find("a")
        if not a_tag: continue

        titulo = a_tag.get_text(strip=True)
        result_url = _limpiar_redireccion_yahoo(a_tag.get("href", ""))

        parent = div.find_parent("div")
        snippet = ""
        if parent:
            text_div = parent.find("div", class_="compText")
            if text_div: snippet = text_div.get_text(strip=True)

        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results


def _sync_fetch_bing(query: str) -> list[dict]:
    encoded_query = urllib.parse.quote_plus(query)
    # setlang/cc fijan resultados en español; sin ellos Bing varía el mercado
    # entre peticiones y el ranking se vuelve inestable.
    url = f"https://www.bing.com/search?q={encoded_query}&setlang=es&cc=ES"

    status, html = _http_get(url)
    if status in (403, 429):
        _enfriar_motor("Bing")
        return []
    if status != 200 or not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for li in soup.find_all("li", class_="b_algo"):
        h2 = li.find("h2")
        a_tag = h2.find("a") if h2 else None
        if not a_tag: continue
        titulo = a_tag.get_text(strip=True)
        # Sin decodificar, esto sería una URL de bing.com/ck/a inservible.
        result_url = _decodificar_url_bing(a_tag.get("href", ""))
        snippet_div = li.find("div", class_="b_caption")
        snippet = ""
        if snippet_div:
            p = snippet_div.find("p")
            if p: snippet = p.get_text(strip=True)
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results


def _sync_fetch_brave(query: str) -> list[dict]:
    """Brave Search: índice propio, complementa bien a Bing/DDG.

    Limita con dureza (429 al segundo intento seguido), por eso depende del
    enfriamiento por motor para no malgastar reintentos.
    """
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://search.brave.com/search?q={encoded_query}"

    status, html = _http_get(url)
    if status in (403, 429):
        _enfriar_motor("Brave")
        return []
    if status != 200 or not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for bloque in soup.select("div.snippet"):
        a_tag = bloque.find("a", href=True)
        if not a_tag:
            continue
        result_url = a_tag["href"]
        if not result_url.startswith("http") or "brave.com" in result_url:
            continue
        titulo_tag = bloque.select_one(".title, .snippet-title")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else a_tag.get_text(strip=True)
        desc_tag = bloque.select_one(".snippet-description, .snippet-content")
        snippet = desc_tag.get_text(strip=True) if desc_tag else ""
        if any(r["url"] == result_url for r in results):
            continue
        results.append({"titulo": titulo, "snippet": snippet, "url": result_url})
    return results


async def _fetch_search_results(session: aiohttp.ClientSession, query: str) -> list[dict]:
    """
    Consulta los motores y FUSIONA resultados hasta reunir material suficiente.

    Antes se devolvía el primer motor que respondiese algo. Con Bing dando el
    100% de URLs de rastreo sin decodificar y Yahoo fallando casi siempre, eso
    significaba que la consulta con `site:` que en DuckDuckGo devolvía la página
    correcta en el puesto 1 se perdía en cuanto le tocaba otro motor en la
    rotación. Ahora se acumulan resultados de varios motores hasta llegar a
    MIN_RESULTADOS_DESEADOS, deduplicando por URL.

    El orden no es aleatorio: va por fiabilidad medida (Bing y DuckDuckGo
    responden casi siempre; Brave aporta un índice distinto pero limita
    enseguida; Yahoo es el más flojo). Los motores en enfriamiento se saltan.
    """
    # Orden por calidad medida el 2026-08-21, no por azar. DuckDuckGo devolvió
    # los resultados correctos de forma consistente; Bing va el último porque,
    # aunque responde siempre, envenena en cuanto detecta scraping.
    #
    # SearXNG va primero desde el 2026-09-06: consulta varios motores por dentro
    # y fusiona, así que aporta más dominios distintos por consulta que
    # cualquiera de los de abajo por separado. Los demás se quedan de reserva
    # hasta tener una ejecución comparada con la semilla 7.
    engines = [
        ("SearXNG", _sync_fetch_searxng),
        ("DuckDuckGo", _sync_fetch_ddg),
        ("DDG-lite", _sync_fetch_ddg_lite),
        ("Brave", _sync_fetch_brave),
        ("Bing", _sync_fetch_bing),
        ("Yahoo", _sync_fetch_yahoo),
    ]

    guardada = cache_paginas.leer_busqueda(query)
    if guardada is not None:
        logger.info(f"  [caché] {len(guardada)} resultados para '{query[:50]}...'")
        return guardada

    acumulados: list[dict] = []
    urls_vistas: set[str] = set()
    motores_usados: list[str] = []
    motores_probados = 0

    for engine_name, engine_func in engines:
        if len(acumulados) >= MIN_RESULTADOS_DESEADOS:
            break
        if motores_probados >= MAX_MOTORES_POR_CONSULTA:
            break
        if not _motor_disponible(engine_name):
            logger.debug(f"  [{engine_name}] en enfriamiento, se omite")
            continue

        motores_probados += 1
        results = await asyncio.to_thread(engine_func, query)
        if not results:
            logger.debug(f"  [{engine_name}] sin resultados para '{query[:50]}'")
            continue

        if not _resultados_coherentes(query, results):
            # Se descartan siempre, pero el motor solo se enfría si reincide:
            # una consulta suelta puede salir incoherente porque el nombre del
            # dataset no es el que usa la web (el municipio 08279000000 figura
            # como "Tarrasa" y todo el mundo escribe "Terrassa"), y castigar al
            # motor por eso deja sin buscador las consultas siguientes.
            seguidas = _INCOHERENTES_SEGUIDAS.get(engine_name, 0) + 1
            _INCOHERENTES_SEGUIDAS[engine_name] = seguidas
            if seguidas >= INCOHERENTES_PARA_ENFRIAR:
                logger.warning(
                    f"  [{engine_name}] {seguidas} respuestas incoherentes seguidas "
                    f"(envenenamiento anti-scraping); motor enfriado"
                )
                _enfriar_motor(engine_name)
            else:
                logger.info(
                    f"  [{engine_name}] resultados incoherentes con '{query[:40]}'; descartados"
                )
            continue

        _INCOHERENTES_SEGUIDAS[engine_name] = 0

        nuevos = 0
        for r in results:
            u = (r.get("url") or "").strip()
            # Anuncios, páginas de ayuda del buscador y redirecciones sin
            # decodificar no sirven aguas abajo: ni se filtran por dominio, ni
            # se deduplican, ni se clasifican geográficamente.
            if not u.startswith("http") or _es_url_basura(u):
                continue
            if u in urls_vistas:
                continue
            urls_vistas.add(u)
            acumulados.append(r)
            nuevos += 1

        if nuevos:
            motores_usados.append(f"{engine_name}:{nuevos}")

        if len(acumulados) < MIN_RESULTADOS_DESEADOS:
            await asyncio.sleep(calculate_backoff_delay(0) / 2)

    if acumulados:
        cache_paginas.guardar_busqueda(query, acumulados)
        logger.info(
            f"  [{'+'.join(motores_usados) or 'sin motor'}] "
            f"{len(acumulados)} resultados para '{query[:50]}...'"
        )
    else:
        logger.warning(f"  [BUSQUEDA] Ningún motor devolvió resultados para: {query}")
        registrar_busqueda_fallida()

    return acumulados


# Contenedores donde los gestores de contenido ponen el cuerpo del artículo.
_SELECTORES_CUERPO = ("article", "main", "[role=main]", ".entry-content",
                      ".post-content", ".article-body", "#content")

# Lo que nunca es contenido, pase lo que pase.
_ARMAZON_SIEMPRE = ["script", "style", "noscript", "iframe", "svg"]

# Lo que SUELE ser armazón. "Suele": los maquetadores de páginas envuelven
# secciones enteras en <header> y <footer> sin que eso signifique nada.
_ARMAZON_ESTRUCTURAL = ["nav", "header", "footer", "aside", "form"]


def _texto_del_html(soup) -> str:
    """
    El texto útil de una página: el cuerpo del artículo si se puede aislar, y si
    no la página limpia de armazón.

    Quitar `nav`, `footer` y `aside` no basta en las plantillas de prensa, que
    meten el menú, el formulario de acceso y la lista de "últimas noticias" en
    `div` corrientes. El 2026-08-27 la página que traía la programación completa
    de Sierra llegó al contexto como diez mil caracteres de menús y titulares de
    otros pueblos.

    Y quitarlos a ciegas es peor todavía. `comarcamonastrell.com` —el periódico
    que cubre las pedanías de Tobarra— está hecho con Elementor, que mete el
    artículo dentro de un `<footer>`: de sus 3.904 caracteres de texto, 3.678
    estaban ahí, y nos quedábamos con 105. Nueve páginas tituladas "programa de
    las fiestas de…" llevaban así desde el principio, y llegué a darlas por
    imposibles de leer. De ahí la regla: si las etiquetas de armazón se llevan
    la mayor parte del texto, no eran armazón.
    """
    for tag in soup(_ARMAZON_SIEMPRE):
        tag.extract()

    texto_total = len(soup.get_text(strip=True))
    estructurales = [n for t in _ARMAZON_ESTRUCTURAL for n in soup(t)]
    texto_estructural = sum(len(n.get_text(strip=True)) for n in estructurales)
    if texto_estructural < 0.5 * max(1, texto_total):
        for n in estructurales:
            n.extract()

    mejor = None
    for selector in _SELECTORES_CUERPO:
        for nodo in soup.select(selector):
            texto = nodo.get_text(separator="\n", strip=True)
            if len(texto) > len(mejor or ""):
                mejor = texto
        if mejor and len(mejor) >= BUSQUEDA_MIN_CHARS_PAGINA:
            break

    completo = soup.get_text(separator="\n", strip=True)
    # El cuerpo aislado solo gana si de verdad trae la sustancia de la página:
    # hay plantillas donde `main` envuelve un carrusel y el artículo va fuera.
    texto = mejor if (mejor and len(mejor) >= 0.25 * len(completo)) else completo

    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{2,}", "\n", texto)


# La frase que rodea a un enlace cuando ese enlace lleva al documento: "puedes
# obtener el documento PDF en la web oficial de…", "descarga el programa aquí",
# "disponible en…". No basta con que diga "programa": eso lo dice también el
# titular de la noticia de al lado.
_RE_PROMESA_DE_DOCUMENTO = re.compile(
    r"descarga|desc[aá]rgat?e|obtener\s+el|disponible\s+en|puedes\s+ver|"
    r"enlace\s+de\s+acceso|enlace\s+directo|web\s+oficial\s+de|"
    r"documento\s+pdf|en\s+pdf|consultar\s+(?:el|la)|p[ui]nch(?:a|ando)|"
    r"m[aá]s\s+informaci[oó]n\s+en|programa\s+completo|programa\s+oficial",
    re.IGNORECASE,
)

# Y, además, el bloque tiene que ir de una fiesta o de un programa.
_RE_TEMA_FESTIVO = re.compile(
    r"program|cartel|fiesta|festej|libro\s+de\s+fiestas|revista\s+de\s+fiestas|"
    r"actos|agenda",
    re.IGNORECASE,
)

# Dominios a los que no merece la pena saltar: no dan contenido sin sesión, o
# son plataformas de las que ya se ocupa otra parte del pipeline.
_NO_SALTAR = ("instagram.com", "facebook.com", "fb.com", "twitter.com", "x.com",
              "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "whatsapp.com",
              "t.me", "pinterest.", "flickr.com", "spotify.com")


def enlaces_al_programa(soup, base_url: str, limite: int) -> list[str]:
    """
    Enlaces de una página que prometen llevar al programa de fiestas.

    Existe porque el programa casi nunca está donde cae el buscador. El patrón
    se repite en toda España: el periódico comarcal publica la noticia, la
    noticia enlaza a la emisora o al ayuntamiento, y allí cuelga el PDF. El
    2026-08-27, `comarcamonastrell.com/programa-fiestas-san-roque-tobarra-2026`
    no traía el programa sino la frase «puedes obtener el documento PDF en la
    web oficial de Radio Tobarra», con el enlace a
    `radiotobarra.es/sanroque26/`, y el PDF estaba ahí detrás de una imagen.

    No es una regla para Tobarra: es un salto más para cualquier localidad, y el
    que ya se daba con los PDF cubre el último tramo.
    """
    def dominio(u: str) -> str:
        return re.sub(r"^www\.", "", urllib.parse.urlparse(u).netloc.lower())

    # El tema se juzga de la PÁGINA, no del bloque. El párrafo que llevaba al
    # programa de San Roque decía "Enlace de acceso: puedes obtener el documento
    # PDF en la web oficial de Radio Tobarra" y no nombraba ninguna fiesta: eso
    # estaba en su titular, "Cómo descargar el programa completo".
    titulo = soup.title.get_text(" ", strip=True) if soup.title else ""
    tema = f"{base_url} {titulo} {soup.get_text(' ', strip=True)[:3000]}"
    if not _RE_TEMA_FESTIVO.search(tema):
        return []

    base_dom = dominio(base_url)
    vistos, salida = set(), []
    for a in soup.find_all("a", href=True):
        if len(salida) >= limite:
            break
        href = urllib.parse.urljoin(base_url, a["href"]).split("#")[0]
        p = urllib.parse.urlparse(href)
        if p.scheme not in ("http", "https") or not p.netloc:
            continue
        if href in vistos or href.rstrip("/") == base_url.rstrip("/"):
            continue
        if href.lower().split("?")[0].endswith(".pdf"):
            continue        # de los PDF se ocupa el salto que ya existe
        if any(d in p.netloc.lower() for d in _NO_SALTAR):
            continue

        # Solo hacia FUERA. Un enlace al propio sitio es navegación o la noticia
        # de al lado: el 2026-08-27, con el mismo dominio permitido, se siguió
        # "hellin-programa-tandem-empleo-joven" —un titular con la palabra
        # "programa"— en vez del enlace bueno. El documento está siempre en otra
        # casa: la emisora, el ayuntamiento, el portal de la peña.
        if dominio(href) == base_dom:
            continue

        # La promesa está en el bloque que envuelve al enlace, no en el enlace:
        # el que llevaba al programa de San Roque decía solo "Radio Tobarra",
        # y era su frase —"puedes obtener el documento PDF en la web oficial
        # de…"— la que lo anunciaba.
        bloque = a
        for _ in range(3):
            if bloque.parent is None:
                break
            bloque = bloque.parent
            if bloque.name in ("li", "p", "figure", "div", "section", "article"):
                break
        contexto = bloque.get_text(" ", strip=True)[:400] if bloque else ""
        texto = f"{a.get_text(' ', strip=True)} {contexto}"
        if not _RE_PROMESA_DE_DOCUMENTO.search(texto):
            continue

        vistos.add(href)
        salida.append(href)
    return salida


_renders_hechos = 0

# Las redes sociales no dan su contenido a un navegador sin sesión: gastar en
# ellas los renders del run es tirarlos. De las RRSS se ocupa el servidor de
# apps de escritorio, que sí está identificado.
_SIN_NAVEGADOR = ("instagram.com", "facebook.com", "fb.com", "twitter.com",
                  "x.com", "tiktok.com", "youtube.com", "youtu.be", "linkedin.com")


async def _render_con_navegador(url: str) -> str | None:
    """
    HTML de una página tal y como lo deja el navegador, para las que solo
    existen después de ejecutar su JavaScript.

    Es el mismo respaldo que ya usaba la araña del municipio; aquí faltaba, y es
    por aquí por donde entran las noticias de prensa local, que son la única
    fuente que tienen muchas pedanías.
    """
    global _renders_hechos
    if any(d in url.lower() for d in _SIN_NAVEGADOR):
        return None
    if _renders_hechos >= BUSQUEDA_MAX_RENDERS_NAVEGADOR:
        return None
    _renders_hechos += 1
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            navegador = await p.chromium.launch(headless=True)
            try:
                pagina = await navegador.new_page()
                await pagina.goto(url, wait_until="domcontentloaded", timeout=15000)
                await pagina.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(1.0)
                return await pagina.content()
            finally:
                await navegador.close()
    except ImportError:
        logger.debug("Playwright no instalado; no hay respaldo de navegador.")
    except Exception as e:
        logger.debug(f"El navegador tampoco pudo con {url[:80]}: {e}")
    return None


def _anotar(registro: list | None, url: str, motivo: str) -> None:
    """
    Apunta por qué se ha perdido una URL, para poder contarlo luego.

    Hasta el 2026-08-24 este tramo era mudo: `_fetch_page_content` tenía seis
    salidas que devolvían vacío y ninguna dejaba rastro por encima de DEBUG, y
    quien la llamaba se tragaba las excepciones con un `continue` pelado. Medido
    ese día en Cordovilla: de 25 URLs seguidas solo 4 llegaron a documento, y no
    había forma de saber qué había pasado con las otras 21 —lanzadas en frío,
    las 25 se descargaban sin un fallo—. Sin esto no se puede arreglar lo que
    venga después, porque no se ve.
    """
    if registro is not None:
        registro.append((url, motivo))


def _resumen_descartes(registro: list, total: int) -> str:
    """Una línea con el recuento por motivo, de mayor a menor."""
    from collections import Counter
    cuenta = Counter(motivo for _, motivo in registro)
    detalle = ", ".join(f"{motivo}={n}" for motivo, n in cuenta.most_common())
    return f"{total - len(registro)}/{total} con texto" + (f" | perdidas: {detalle}" if detalle else "")


# Fallos que son del momento, no de la URL: reintentarlos tiene sentido. Un 404
# o un content-type raro no cambian por insistir, y gastar intentos en ellos
# solo retrasa al resto.
_MOTIVOS_REINTENTABLES = (
    "error_TimeoutError", "error_ClientConnectorError", "error_ServerDisconnectedError",
    "error_ClientOSError", "error_ClientPayloadError", "error_CancelledError",
    "http_429", "http_500", "http_502", "http_503", "http_504",
)


def _es_fallo_estable(motivo: str) -> bool:
    """
    Si este fallo es una propiedad del recurso, merece guardarse.

    Un 404 o un PDF de 30 MB van a seguir siéndolo mañana, y volver a pedirlos
    cada ejecución es tirar tiempo y ancho de banda. El 403 se queda fuera a
    propósito: puede ser un bloqueo temporal por haber insistido demasiado, y
    darlo por muerto un mes nos cerraría una fuente que quizá vuelve sola.
    """
    return motivo not in _MOTIVOS_REINTENTABLES and not motivo.startswith("http_403")


async def _fetch_page_content(
    session: aiohttp.ClientSession, url: str, registro: list | None = None,
) -> tuple[str, list[str]]:
    """
    Descarga una URL con reintentos y devuelve (texto, pdfs_enlazados).

    Los PDF salen con un timeout mayor y cada reintento lo amplía. Medido el
    2026-08-24 en Tobarra: de 33 PDF enlazados solo entraban 16, y las pérdidas
    eran casi todas por timeout —Aljubé perdió 10 de 15—. Diez segundos valen
    para una página y no para un programa de fiestas escaneado.
    """
    guardado = cache_paginas.leer(url)
    if guardado is not None:
        texto, pdfs, motivo, enlaces = guardado
        if motivo:
            _anotar(registro, url, motivo)
        return texto, pdfs, enlaces

    es_pdf = url.lower().split("?")[0].endswith(".pdf")
    timeout = DESCARGA_TIMEOUT_PDF if es_pdf else DDG_REQUEST_TIMEOUT

    for intento in range(DESCARGA_MAX_INTENTOS):
        fallos: list[tuple[str, str]] = []
        texto, pdfs, enlaces = await _descargar_una_vez(session, url, timeout, fallos)
        motivo = fallos[0][1] if fallos else ""

        if not motivo:
            if intento:
                logger.debug(f"    [DESCARGA] recuperada al intento {intento + 1}: {url[:90]}")
            cache_paginas.guardar(url, texto, pdfs, enlaces=enlaces)
            return texto, pdfs, enlaces

        if motivo not in _MOTIVOS_REINTENTABLES:
            # Ni insistiendo va a cambiar. Se devuelve lo que haya: una página
            # sin texto puede seguir enlazando el PDF que buscamos.
            _anotar(registro, url, motivo)
            if _es_fallo_estable(motivo):
                cache_paginas.guardar(url, texto, pdfs, motivo, enlaces)
            return texto, pdfs, enlaces

        if intento < DESCARGA_MAX_INTENTOS - 1:
            await asyncio.sleep(DESCARGA_BACKOFF * (2 ** intento))
            timeout = min(timeout * 2, DESCARGA_TIMEOUT_MAX)
        else:
            _anotar(registro, url, f"{motivo}_tras_{DESCARGA_MAX_INTENTOS}")

    return "", [], []


async def _descargar_una_vez(
    session: aiohttp.ClientSession, url: str, timeout_s: float, registro: list | None = None,
) -> tuple[str, list[str]]:
    """
    Un intento de descarga: devuelve (texto, pdfs_enlazados).

    Dos cambios respecto a la versión anterior, que devolvía "" para todo lo que
    no fuese text/html:

    1. Los PDF se leen. Medido el 2026-08-21 sobre 9 municipios, los únicos dos
       programas oficiales correctos que aparecían por buscador eran PDF; el
       filtro `if "text/html" not in content_type: return ""` los tiraba sin
       abrirlos.
    2. De las páginas HTML se devuelven además los PDF que cuelgan de ellas,
       para que el llamante pueda dar UN salto. En Amurrio el buscador devolvía
       la noticia de presentación del programa en el puesto 1 y el programa
       (44 actos con hora) estaba a un enlace de distancia; en Terrassa, igual.
    """
    try:
        async with session.get(
            url,
            headers=_get_random_headers(),
            timeout=aiohttp.ClientTimeout(total=timeout_s),
            allow_redirects=True,
            ssl=False,
        ) as resp:
            if resp.status != 200:
                _anotar(registro, url, f"http_{resp.status}")
                return "", [], []
            content_type = (resp.headers.get("Content-Type") or "").lower()

            es_pdf = "application/pdf" in content_type or url.lower().split("?")[0].endswith(".pdf")
            if not es_pdf and "text/html" not in content_type:
                _anotar(registro, url, f"tipo_{content_type.split(';')[0].strip() or 'desconocido'}")
                return "", [], []

            body = await resp.read()
            if len(body) > 25_000_000:
                _anotar(registro, url, "mayor_25mb")
                return "", [], []

            if es_pdf:
                try:
                    from scraper.document_extractor import extract_text_from_pdf
                    texto_pdf, _ = extract_text_from_pdf(body)
                except Exception as e:
                    logger.debug(f"No se pudo extraer texto del PDF {url[:80]}: {e}")
                    _anotar(registro, url, f"pdf_ilegible_{type(e).__name__}")
                    return "", [], []
                if not (texto_pdf or "").strip():
                    _anotar(registro, url, "pdf_sin_texto")
                return (texto_pdf or "")[:DDG_CONTENT_MAX_CHARS], [], []

            if len(body) > 2_000_000:
                _anotar(registro, url, "mayor_2mb")
                return "", [], []

            try:
                html = body.decode("utf-8", errors="replace")
            except Exception:
                html = body.decode("latin-1", errors="replace")

            def _leer(fuente_html: str) -> tuple[str, list]:
                sopa = BeautifulSoup(fuente_html, "html.parser")
                # Los PDF se recogen ANTES de limpiar la página: muchos
                # ayuntamientos cuelgan el programa en un bloque de adjuntos
                # dentro de <aside>.
                encontrados = []
                for a in sopa.find_all("a", href=True):
                    if ".pdf" not in a["href"].lower():
                        continue
                    pdf_url = urllib.parse.urljoin(str(resp.url), a["href"])
                    if pdf_url not in [p[0] for p in encontrados]:
                        encontrados.append((pdf_url, a.get_text(strip=True)))
                enlaces = enlaces_al_programa(
                    BeautifulSoup(fuente_html, "html.parser"), str(resp.url),
                    BUSQUEDA_MAX_ENLACES_POR_PAGINA,
                )
                return _texto_del_html(sopa), encontrados, enlaces

            text, pdfs, enlaces = _leer(html)

            # Página que llega sin cuerpo: casi siempre es que lo pinta
            # JavaScript. La noticia de las fiestas de Los Mardos dejaba 173
            # caracteres —el título y el pie de un plugin— y con esa única
            # fuente la localidad salía con un solo día y sin programa.
            if len(text) < BUSQUEDA_MIN_CHARS_PAGINA:
                renderizado = await _render_con_navegador(url)
                if renderizado:
                    texto_render, pdfs_render, enlaces_render = _leer(renderizado)
                    if len(texto_render) > len(text):
                        logger.info(
                            f"    [NAVEGADOR] {url[:70]}: {len(text)} → "
                            f"{len(texto_render)} caracteres."
                        )
                        text, pdfs, enlaces = texto_render, pdfs_render, enlaces_render

            # Filtrar los PDF por el mismo criterio que usa la araña, para no
            # arrastrar ordenanzas ni actas de pleno.
            pdfs_utiles = []
            try:
                from scraper.document_extractor import is_promising_pdf
                contexto = text[:2000]
                for pdf_url, texto_enlace in pdfs:
                    if is_promising_pdf(pdf_url, texto_enlace, contexto):
                        pdfs_utiles.append(pdf_url)
            except Exception:
                pdfs_utiles = [u for u, _ in pdfs]

            if not text.strip():
                _anotar(registro, url, "html_sin_texto")

            return (text[:DDG_CONTENT_MAX_CHARS],
                    pdfs_utiles[:BUSQUEDA_MAX_PDFS_POR_PAGINA], enlaces)

    except Exception as e:
        logger.debug(f"Error descargando contenido de {url}: {e}")
        _anotar(registro, url, f"error_{type(e).__name__}")
        return "", [], []


_MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def build_fiesta_queries(fiesta: dict, localidad: dict, municipio: dict, anno: int) -> list[str]:
    """
    Consultas para EL PROGRAMA de una fiesta concreta, ya descubierta.

    Las consultas de localidad se construyen a partir del patrón, y eso deja sin
    buscar a las demás fiestas del pueblo. Medido el 2026-08-26 en Tobarra, que
    tiene tres: las seis consultas lanzadas fueron todas sobre el Cristo de la
    Antigua, que es el patrón, y ninguna nombró a San Antón ni a San Roque. Las
    dos se quedaron sin programa —aunque el de San Roque está publicado en
    radiotobarra.es/sanroque26/— sencillamente porque nadie fue a buscarlo.

    El nombre de la fiesta va tal cual: es como lo escribe quien publica el
    programa. El mes ayuda a separar las fiestas de un mismo pueblo entre sí.
    """
    nombre_fiesta = (fiesta.get("nombre") or "").strip()
    nombre_loc = (localidad.get("nombre") or "").strip()
    if not nombre_fiesta or not nombre_loc:
        return []

    # "Fiestas de San Roque" y el pueblo ya dicen bastante; repetir "fiestas"
    # delante solo estorba.
    limpio = re.sub(r"^\s*(fiestas?\s+(patronales\s+)?(de\s+|en\s+honor\s+a\s+)?)", "",
                    nombre_fiesta, flags=re.IGNORECASE).strip() or nombre_fiesta

    # La provincia también aquí. El nombre de la fiesta suele ser específico,
    # pero no siempre basta: "programa Carnaval de Santa Marta Santa Marta 2026"
    # devolvió el carnaval de la ciudad colombiana, y de ahí salió una ficha.
    # Se deja UNA consulta sin geografía —la del mes— porque el nombre de la
    # fiesta más el mes ya acota mucho, y así queda una vía para las fuentes que
    # no nombran nunca la provincia.
    geo = (municipio.get("provincia") or comunidad_de(municipio) or "").strip()
    donde = f"{nombre_loc} {geo}".strip()

    queries = [
        f"programa {nombre_fiesta} {donde} {anno}",
        f"{donde} {limpio} {anno} programa de actos",
    ]

    mes = ""
    m = re.match(r"\d{4}-(\d{2})", fiesta.get("fecha_inicio") or "")
    if m:
        mes = _MESES_ES[int(m.group(1)) - 1] if 1 <= int(m.group(1)) <= 12 else ""
    if mes:
        queries.append(f"fiestas {nombre_loc} {limpio} {mes} {anno}")

    vistas, unicas = set(), []
    for q in queries:
        clave = " ".join(q.lower().split())
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(" ".join(q.split()))
    return unicas


async def search_fiesta_web(
    fiesta: dict,
    localidad: dict,
    municipio: dict,
    anno: int,
    visited_urls: set | list | None = None,
) -> list[dict]:
    """Busca el programa de UNA fiesta concreta. Devuelve documentos como search_locality_web."""
    queries = build_fiesta_queries(fiesta, localidad, municipio, anno)
    if not queries:
        return []
    return await _buscar_y_descargar(queries, localidad, municipio, visited_urls)


async def search_locality_web(
    localidad: dict,
    municipio: dict,
    anno: int,
    visited_urls: set | list | None = None,
) -> list[dict]:
    """
    Busca información de fiestas de una localidad usando buscadores.
    - Lanza 3 queries distintas y extrae snippets
    - Sigue las top N URLs para obtener contenido completo
    - visited_urls: set compartido — NO se releen URLs ya leídas por pasos
      anteriores (webs oficiales), y las leídas aquí quedan registradas.

    Devuelve documentos etiquetados con fuente 'busqueda_web'.
    """
    if not isinstance(localidad, dict):
        localidad = {}
    if not isinstance(municipio, dict):
        municipio = {}

    queries = _build_queries(localidad, municipio, anno)
    if not queries:
        return []
    return await _buscar_y_descargar(queries, localidad, municipio, visited_urls)


async def _buscar_y_descargar(
    queries: list[str],
    localidad: dict,
    municipio: dict,
    visited_urls: set | list | None = None,
) -> list[dict]:
    """
    Lanza unas consultas, sigue sus resultados y devuelve los documentos.

    Es el cuerpo que comparten la búsqueda por localidad y la búsqueda por
    fiesta: la única diferencia entre las dos es qué se pregunta.
    """
    original_visited_list = visited_urls if isinstance(visited_urls, list) else None
    if isinstance(visited_urls, list):
        visited_urls = set(visited_urls)

    documentos = []
    texto_snippets = ""
    all_urls_seen = set()
    urls_to_follow = []

    headers = {"User-Agent": USER_AGENT}
    # Concurrencia de descarga: con 25 URLs a seguir, un límite de 5 obligaba a
    # cinco tandas. 10 mantiene la cortesía con los servidores y reduce la espera.
    connector = aiohttp.TCPConnector(limit=10, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        # 1. Ejecutar las queries secuencialmente (respetar rate limits)
        lanzadas: set[str] = set()
        pendientes = list(queries)
        while pendientes:
            query = pendientes.pop(0)
            clave = " ".join(query.lower().split())
            if clave in lanzadas:
                continue
            lanzadas.add(clave)

            logger.info(f"  Buscando: {query}")
            results = await _fetch_search_results(session, query)

            # El operador `site:` es lo que más consultas tumba: los motores lo
            # rechazan o devuelven basura. Medido el 2026-08-23, 13 de 52
            # consultas volvían vacías y la mayoría lo llevaban. Si falla, se
            # reintenta la misma consulta sin el operador antes de darla por
            # perdida: el dominio deja de ser un filtro, pero el resultado
            # bueno suele salir igual entre los primeros.
            if not results and "site:" in query:
                sin_site = re.sub(r"\s*site:\S+", "", query).strip()
                # …pero al quitar el dominio, la consulta se queda sin nada que
                # la sitúe, y era el último agujero por el que entraba el pueblo
                # homónimo: el reintento de Santa Marta salía como "fiestas
                # patronales Santa Marta 2026", que devuelve la ciudad colombiana.
                # Se le pone la provincia, que es lo que el `site:` estaba
                # haciendo de otra manera.
                geo_reintento = (municipio.get("provincia") or comunidad_de(municipio) or "").strip()
                if geo_reintento and geo_reintento.lower() not in sin_site.lower():
                    sin_site = f"{sin_site} {geo_reintento}"
                if sin_site and " ".join(sin_site.lower().split()) not in lanzadas:
                    logger.info(f"  Reintento sin el operador site: {sin_site}")
                    pendientes.insert(0, sin_site)

            for r in results:
                # Acumular snippets. La URL va al final de la línea a propósito:
                # este documento es un revoltijo de resultados de sitios distintos
                # y sin ella no hay forma de quitar los de un pueblo homónimo
                # cuando su página se descarta. Medido el 2026-08-25 en Cordovilla:
                # las páginas de la Cendea de Galar salían descartadas en el log y
                # sus actos seguían llegando al modelo por este bloque.
                texto_snippets += (
                    f"TITULO: {r['titulo']} | CONTENIDO: {r['snippet']} "
                    f"| ORIGEN: {r.get('url', '')}\n"
                )

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

            await asyncio.sleep(get_query_delay())

        if texto_snippets.strip():
            documentos.append(
                crear_documento(FUENTE_BUSQUEDA, "buscadores:snippets", texto_snippets, tipo="snippets")
            )

        # 2. Seguir las top N URLs para obtener contenido completo.
        #    El orden importa: solo se siguen DDG_MAX_URLS_TO_FOLLOW y hasta
        #    ahora se cogían por orden de llegada. Como la consulta con `site:`
        #    es la ÚLTIMA que se lanza, sus resultados —los de la web oficial,
        #    justo los que llevan al programa— caían fuera del corte. En Amurrio
        #    eso dejaba fuera la noticia que enlaza el PDF de 44 actos.
        urls_to_follow = _priorizar_urls(urls_to_follow, localidad, municipio)
        urls_to_fetch = urls_to_follow[:DDG_MAX_URLS_TO_FOLLOW]
        if urls_to_fetch:
            logger.info(f"  Siguiendo {len(urls_to_fetch)} URLs de resultados...")
            if visited_urls is not None:
                visited_urls.update(urls_to_fetch)
            if original_visited_list is not None:
                original_visited_list.extend(u for u in urls_to_fetch if u not in original_visited_list)

            registro: list[tuple[str, str]] = []
            tasks = [_fetch_page_content(session, url, registro) for url in urls_to_fetch]
            resultados = await asyncio.gather(*tasks, return_exceptions=True)

            pdfs_pendientes: list[str] = []
            enlaces_pendientes: list[str] = []
            for url, resultado in zip(urls_to_fetch, resultados):
                if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                    _anotar(registro, url, f"excepcion_{type(resultado).__name__}")
                    continue
                content, pdfs, enlaces = resultado
                if content and content.strip():
                    es_pdf = url.lower().split("?")[0].endswith(".pdf")
                    documentos.append(
                        crear_documento(
                            FUENTE_BUSQUEDA, url, content,
                            tipo="pdf" if es_pdf else "pagina",
                        )
                    )
                for p in pdfs or []:
                    if p not in pdfs_pendientes and p not in all_urls_seen:
                        pdfs_pendientes.append(p)
                for e in enlaces or []:
                    if e not in enlaces_pendientes and e not in all_urls_seen:
                        enlaces_pendientes.append(e)

            # El desglose de por qué se pierden URLs, que es lo que antes no se
            # veía. A INFO va el recuento; el detalle por URL, a DEBUG.
            logger.info(
                f"  [DESCARGA] {_resumen_descartes(registro, len(urls_to_fetch))}"
                f" | {cache_paginas.resumen()}"
            )
            for u, motivo in registro:
                logger.debug(f"    [DESCARGA/perdida] {motivo}: {u[:110]}")

            # 3. UN salto por las páginas que PROMETEN el programa. Va antes
            #    que el de los PDF a propósito: el documento suele estar dos
            #    puertas más allá —la noticia del periódico comarcal enlaza a la
            #    emisora, y el PDF cuelga de la emisora— y así los PDF que
            #    aparezcan aquí entran en la misma cola y se siguen igual.
            if BUSQUEDA_SEGUIR_ENLACES and enlaces_pendientes:
                a_seguir = enlaces_pendientes[:BUSQUEDA_MAX_ENLACES_TOTAL]
                logger.info(
                    f"  Siguiendo {len(a_seguir)} páginas que prometen el programa..."
                )
                if visited_urls is not None:
                    visited_urls.update(a_seguir)
                if original_visited_list is not None:
                    original_visited_list.extend(
                        u for u in a_seguir if u not in original_visited_list
                    )
                reg_enl: list[tuple[str, str]] = []
                tareas_enl = [_fetch_page_content(session, u, reg_enl) for u in a_seguir]
                res_enl = await asyncio.gather(*tareas_enl, return_exceptions=True)
                for url, resultado in zip(a_seguir, res_enl):
                    if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                        _anotar(reg_enl, url, f"excepcion_{type(resultado).__name__}")
                        continue
                    content, pdfs_enl, _ = resultado
                    if content and content.strip():
                        documentos.append(
                            crear_documento(FUENTE_BUSQUEDA, url, content, tipo="pagina")
                        )
                    for p in pdfs_enl or []:
                        if p not in pdfs_pendientes and p not in all_urls_seen:
                            pdfs_pendientes.append(p)
                logger.info(
                    f"  [DESCARGA/enlaces] {_resumen_descartes(reg_enl, len(a_seguir))}"
                )
                for u, motivo in reg_enl:
                    logger.debug(f"    [DESCARGA/perdida] {motivo}: {u[:110]}")

            # 4. UN salto: los PDF que cuelgan de esos resultados.
            #    Es donde vive el programa de actos en la mayoría de los
            #    ayuntamientos: la búsqueda deja en la puerta (la noticia de
            #    presentación) y el documento está un enlace más allá.
            if BUSQUEDA_SEGUIR_PDFS and pdfs_pendientes:
                pdfs_a_seguir = pdfs_pendientes[:BUSQUEDA_MAX_PDFS_TOTAL]
                logger.info(f"  Siguiendo {len(pdfs_a_seguir)} PDFs enlazados desde los resultados...")
                if visited_urls is not None:
                    visited_urls.update(pdfs_a_seguir)
                if original_visited_list is not None:
                    original_visited_list.extend(
                        u for u in pdfs_a_seguir if u not in original_visited_list
                    )

                reg_pdf: list[tuple[str, str]] = []
                tareas_pdf = [_fetch_page_content(session, u, reg_pdf) for u in pdfs_a_seguir]
                res_pdf = await asyncio.gather(*tareas_pdf, return_exceptions=True)
                for url, resultado in zip(pdfs_a_seguir, res_pdf):
                    if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                        _anotar(reg_pdf, url, f"excepcion_{type(resultado).__name__}")
                        continue
                    content, _, _ = resultado
                    if content and content.strip():
                        documentos.append(
                            crear_documento(FUENTE_BUSQUEDA, url, content, tipo="pdf")
                        )
                logger.info(f"  [DESCARGA/pdf] {_resumen_descartes(reg_pdf, len(pdfs_a_seguir))}")
                for u, motivo in reg_pdf:
                    logger.debug(f"    [DESCARGA/perdida] {motivo}: {u[:110]}")

    return documentos


def build_media_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    """Genera queries de prensa regional con site:<dominio_prensa> para una localidad."""
    if not isinstance(localidad, dict):
        localidad = {}
    if not isinstance(municipio, dict):
        municipio = {}

    lugar_id = localidad.get("id") or municipio.get("id", "")
    provincia = (municipio.get("provincia") or "").strip()

    medios = get_medios_prensa_por_provincia(lugar_id)
    if not medios and provincia:
        medios = get_medios_prensa_por_provincia(provincia)

    if not medios:
        return []

    nombre_loc = (localidad.get("nombre") or "").strip()
    if not nombre_loc:
        nombre_loc = (municipio.get("nombre") or "").strip()
    if not nombre_loc:
        return []

    perfil_data = perfil_de_lugar(municipio)
    kws = perfil_data["perfil_principal"]["keywords_busqueda"]
    kw1 = kws[0] if kws else "fiestas"

    return [f"{kw1} {nombre_loc} {anno} site:{domain}" for domain in medios]


async def search_locality_media(
    localidad: dict,
    municipio: dict,
    anno: int,
    visited_urls: set | list | None = None,
) -> list[dict]:
    """
    Busca información de fiestas en prensa regional de la provincia.
    Genera queries con site:<dominio_prensa> para los medios de la provincia.
    Devuelve documentos etiquetados con fuente FUENTE_PRENSA_REGIONAL.
    """
    if not isinstance(localidad, dict):
        localidad = {}
    if not isinstance(municipio, dict):
        municipio = {}

    queries = build_media_queries(localidad, municipio, anno)
    if not queries:
        return []

    original_visited_list = visited_urls if isinstance(visited_urls, list) else None
    if isinstance(visited_urls, list):
        visited_urls = set(visited_urls)

    documentos = []
    texto_snippets = ""
    all_urls_seen = set()
    urls_to_follow = []

    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=5, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        for query in queries:
            logger.info(f"  [MEDIA_SEARCH] Buscando en prensa regional: {query}")
            results = await _fetch_search_results(session, query)

            for r in results:
                texto_snippets += (
                    f"TITULO: {r['titulo']} | CONTENIDO: {r['snippet']} "
                    f"| ORIGEN: {r.get('url', '')}\n"
                )
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

            await asyncio.sleep(get_query_delay())

        if texto_snippets.strip():
            documentos.append(
                crear_documento(FUENTE_PRENSA_REGIONAL, "prensa_regional:snippets", texto_snippets, tipo="snippets")
            )

        urls_to_fetch = urls_to_follow[:DDG_MAX_URLS_TO_FOLLOW]
        if urls_to_fetch:
            logger.info(f"  Siguiendo {len(urls_to_fetch)} URLs de prensa regional...")
            if visited_urls is not None:
                visited_urls.update(urls_to_fetch)
            if original_visited_list is not None:
                original_visited_list.extend(u for u in urls_to_fetch if u not in original_visited_list)

            registro: list[tuple[str, str]] = []
            tasks = [_fetch_page_content(session, url, registro) for url in urls_to_fetch]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)

            for url, resultado in zip(urls_to_fetch, page_contents):
                # _fetch_page_content devuelve (texto, pdfs_enlazados)
                if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                    _anotar(registro, url, f"excepcion_{type(resultado).__name__}")
                    continue
                content, _pdfs, _enl = resultado
                if content and content.strip():
                    documentos.append(crear_documento(FUENTE_PRENSA_REGIONAL, url, content, tipo="pagina"))
            logger.info(f"  [DESCARGA/prensa] {_resumen_descartes(registro, len(urls_to_fetch))}")
            for u, motivo in registro:
                logger.debug(f"    [DESCARGA/perdida] {motivo}: {u[:110]}")

    return documentos


async def descargar_urls_bajo_demanda(
    urls: list[str],
    fuente: str = FUENTE_BUSQUEDA,
    timeout: float = 15,
) -> list[dict]:
    """
    Descarga una lista de URLs bajo demanda y devuelve documentos etiquetados.

    Pensada para el Program Locator: el LLM señala URLs que no están en el
    contexto y hay que ir a buscarlas. Reutiliza la caché y la lógica de
    descarga de `_fetch_page_content` sin pasar por los buscadores.

    Sigue PDFs enlazados (un salto) y enlaces al programa, igual que
    `_buscar_y_descargar`, pero sin la fase de búsqueda en motores.
    """
    if not urls:
        return []

    documentos = []
    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=5, ssl=False)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        registro: list[tuple[str, str]] = []
        tasks = [_fetch_page_content(session, url, registro) for url in urls]
        resultados = await asyncio.gather(*tasks, return_exceptions=True)

        pdfs_pendientes: list[str] = []
        enlaces_pendientes: list[str] = []
        urls_vistas = set(urls)

        for url, resultado in zip(urls, resultados):
            if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                _anotar(registro, url, f"excepcion_{type(resultado).__name__}")
                continue
            content, pdfs, enlaces = resultado
            if content and content.strip():
                es_pdf = url.lower().split("?")[0].endswith(".pdf")
                documentos.append(
                    crear_documento(fuente, url, content,
                                    tipo="pdf" if es_pdf else "pagina")
                )
            for p in pdfs or []:
                if p not in urls_vistas:
                    pdfs_pendientes.append(p)
                    urls_vistas.add(p)
            for e in enlaces or []:
                if e not in urls_vistas:
                    enlaces_pendientes.append(e)
                    urls_vistas.add(e)

        # Un salto para enlaces que prometen el programa
        if BUSQUEDA_SEGUIR_ENLACES and enlaces_pendientes:
            a_seguir = enlaces_pendientes[:BUSQUEDA_MAX_ENLACES_POR_PAGINA]
            reg_enl: list[tuple[str, str]] = []
            tareas_enl = [_fetch_page_content(session, u, reg_enl) for u in a_seguir]
            res_enl = await asyncio.gather(*tareas_enl, return_exceptions=True)
            for url, resultado in zip(a_seguir, res_enl):
                if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                    continue
                content, pdfs_enl, _ = resultado
                if content and content.strip():
                    documentos.append(crear_documento(fuente, url, content, tipo="pagina"))
                for p in pdfs_enl or []:
                    if p not in urls_vistas:
                        pdfs_pendientes.append(p)
                        urls_vistas.add(p)

        # Un salto para PDFs enlazados
        if BUSQUEDA_SEGUIR_PDFS and pdfs_pendientes:
            pdfs_a_seguir = pdfs_pendientes[:BUSQUEDA_MAX_PDFS_POR_PAGINA]
            reg_pdf: list[tuple[str, str]] = []
            tareas_pdf = [_fetch_page_content(session, u, reg_pdf) for u in pdfs_a_seguir]
            res_pdf = await asyncio.gather(*tareas_pdf, return_exceptions=True)
            for url, resultado in zip(pdfs_a_seguir, res_pdf):
                if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                    continue
                content, _, _ = resultado
                if content and content.strip():
                    documentos.append(crear_documento(fuente, url, content, tipo="pdf"))

        if registro:
            logger.info(f"  [LOCATOR/DESCARGA] {_resumen_descartes(registro, len(urls))}")

    return documentos

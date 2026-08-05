"""
Búsqueda del santo patrón de una localidad.

Pipeline: caché → Wikipedia (infobox + texto) → buscadores web → LLM local (fallback).
La fecha del patrón es SIEMPRE un único día fijo del calendario:
- si el texto da una fecha explícita se usa esa;
- si no, se resuelve contra el SANTORAL estático;
- si ambas existen y discrepan, prevalece el SANTORAL (fecha fija de calendario).

También expone las funciones puras de integración con las fiestas extraídas:
- fecha_del_patron(): día del patrón en el año objetivo.
- integrar_patron(): marca las fiestas que incluyen el día del patrón y añade
  el registro estimado cuando ninguna fiesta lo cubre.
"""

import asyncio
import json
import os
import re
import logging
import unicodedata
from datetime import date

import aiohttp
from bs4 import BeautifulSoup

from config import (
    PATRON_SEARCH_ENABLED,
    PATRON_CACHE_FILE,
    PATRON_MAX_URLS,
    PATRON_LLM_MAX_TOKENS,
    DDG_REQUEST_TIMEOUT,
    USER_AGENT,
)
from llm_processor.festival_filter import normalizar_texto

logger = logging.getLogger("patron_finder")


# ──────────────────────────────────────────────────
# SANTORAL — fechas fijas de los patrones más comunes de España
# Claves normalizadas (minúsculas, sin tildes). Valor: (dia, mes).
# Festividades móviles (Corpus, Virgen del Rocío, San Vicente Ferrer...)
# NO se incluyen a propósito: sin fecha fija no se genera estimación.
# ──────────────────────────────────────────────────

SANTORAL: dict[str, tuple[int, int]] = {
    # Enero
    "san anton": (17, 1), "san antonio abad": (17, 1), "sant antoni": (17, 1),
    "san sebastian": (20, 1), "sant sebastia": (20, 1),
    "san vicente": (22, 1), "san vicente martir": (22, 1), "sant vicenc": (22, 1),
    "san ildefonso": (23, 1),
    "virgen de la paz": (24, 1),
    "san julian": (28, 1),
    "san valero": (29, 1),
    # Febrero
    "la candelaria": (2, 2), "virgen de la candelaria": (2, 2), "candelaria": (2, 2),
    "san blas": (3, 2), "sant blai": (3, 2), "san brais": (3, 2),
    "santa agueda": (5, 2), "santa agata": (5, 2),
    "virgen de lourdes": (11, 2),
    "santa eulalia": (12, 2), "santa eularia": (12, 2),
    "san valentin": (14, 2),
    # Marzo
    "san emeterio": (3, 3), "san celedonio": (3, 3),
    "san jose": (19, 3),
    # Abril
    "santa engracia": (16, 4),
    "san jorge": (23, 4), "sant jordi": (23, 4),
    "san marcos": (25, 4),
    "san isidoro": (26, 4),
    "virgen de montserrat": (27, 4),
    "san prudencio": (28, 4),
    # Mayo
    "santa cruz": (3, 5), "la santa cruz": (3, 5),
    "san gregorio": (9, 5),
    "santo domingo de la calzada": (12, 5),
    "virgen de fatima": (13, 5), "san pedro regalado": (13, 5),
    "san isidro": (15, 5), "san isidro labrador": (15, 5),
    "san pascual bailon": (17, 5),
    "santa rita": (22, 5),
    "san urbano": (25, 5),
    "san fernando": (30, 5),
    # Junio
    "san medardo": (8, 6),
    "san bernabe": (11, 6),
    "san juan de sahagun": (12, 6),
    "san antonio": (13, 6), "san antonio de padua": (13, 6),
    "san vito": (15, 6),
    "san juan": (24, 6), "san juan bautista": (24, 6), "sant joan": (24, 6), "san xoan": (24, 6),
    "santa orosia": (25, 6),
    "san pelayo": (26, 6),
    "san zoilo": (27, 6),
    "san pedro": (29, 6), "san pablo": (29, 6), "san pedro y san pablo": (29, 6), "sant pere": (29, 6),
    "san marcial": (30, 6),
    # Julio
    "san fermin": (7, 7),
    "san cristobal": (10, 7),
    "san benito": (11, 7), "san bieito": (11, 7),
    "san buenaventura": (15, 7),
    "virgen del carmen": (16, 7), "mare de deu del carme": (16, 7), "virxe do carme": (16, 7),
    "santa justa": (17, 7), "santa rufina": (17, 7),
    "santa marina": (18, 7),
    "san elias": (20, 7),
    "santa maria magdalena": (22, 7), "la magdalena": (22, 7), "magdalena": (22, 7),
    "santa brigida": (23, 7),
    "santiago": (25, 7), "santiago apostol": (25, 7), "sant jaume": (25, 7),
    "santa ana": (26, 7), "santa anna": (26, 7), "san joaquin": (26, 7),
    "san pantaleon": (27, 7),
    "santa marta": (29, 7),
    "san abdon": (30, 7), "san senen": (30, 7), "san abdon y san senen": (30, 7),
    "san ignacio": (31, 7), "san ignacio de loyola": (31, 7),
    # Agosto
    "virgen de los angeles": (2, 8),
    "virgen de las nieves": (5, 8), "virgen blanca": (5, 8), "mare de deu de les neus": (5, 8),
    "san salvador": (6, 8), "el salvador": (6, 8),
    "san justo": (6, 8), "san justo y pastor": (6, 8),
    "san cayetano": (7, 8), "san mames": (7, 8),
    "santo domingo": (8, 8), "santo domingo de guzman": (8, 8),
    "san lorenzo": (10, 8), "sant llorenc": (10, 8),
    "santa clara": (11, 8),
    "san hipolito": (13, 8),
    "asuncion": (15, 8), "la asuncion": (15, 8), "virgen de la asuncion": (15, 8),
    "virgen de agosto": (15, 8), "virgen del transito": (15, 8),
    "mare de deu d agost": (15, 8), "andra mari": (15, 8), "santa maria": (15, 8),
    "san roque": (16, 8), "sant roc": (16, 8),
    "san magin": (19, 8), "sant magi": (19, 8),
    "san bernardo": (20, 8),
    "san bartolome": (24, 8), "sant bartomeu": (24, 8), "san bartolomeu": (24, 8),
    "san luis": (25, 8), "san gines": (25, 8),
    "san agustin": (28, 8),
    "degollacion de san juan": (29, 8), "san juan degollado": (29, 8),
    "san ramon": (31, 8), "san ramon nonato": (31, 8),
    # Septiembre
    "san gil": (1, 9),
    "san antolin": (2, 9),
    "virgen de guadalupe": (8, 9), "virgen de covadonga": (8, 9), "la santina": (8, 9),
    "natividad de la virgen": (8, 9), "virgen de la natividad": (8, 9),
    "virgen de la vega": (8, 9), "virgen de la victoria": (8, 9),
    "virgen de gracia": (8, 9), "virgen de los remedios": (8, 9), "virxe dos remedios": (8, 9),
    "santa maria de la cabeza": (9, 9),
    "exaltacion de la cruz": (14, 9), "santo cristo": (14, 9), "santisimo cristo": (14, 9),
    "virgen de los dolores": (15, 9),
    "san cipriano": (16, 9),
    "santa eufemia": (16, 9),
    "san mateo": (21, 9),
    "santa tecla": (23, 9),
    "virgen de la merced": (24, 9), "la merce": (24, 9), "mare de deu de la merce": (24, 9),
    "san cosme": (26, 9), "san damian": (26, 9), "san cosme y san damian": (26, 9),
    "san miguel": (29, 9), "san miguel arcangel": (29, 9),
    "san jeronimo": (30, 9),
    # Octubre
    "san saturio": (2, 10),
    "san francisco": (4, 10), "san francisco de asis": (4, 10),
    "san froilan": (5, 10), "san atilano": (5, 10),
    "virgen del rosario": (7, 10), "mare de deu del roser": (7, 10), "virxe do rosario": (7, 10),
    "san dionisio": (9, 10),
    "virgen de begona": (11, 10),
    "virgen del pilar": (12, 10), "el pilar": (12, 10), "mare de deu del pilar": (12, 10),
    "santa teresa": (15, 10), "santa teresa de jesus": (15, 10),
    "san lucas": (18, 10),
    "santa ursula": (21, 10),
    "san rafael": (24, 10),
    "san frutos": (25, 10), "san crispin": (25, 10),
    "san judas tadeo": (28, 10), "san simon": (28, 10),
    "san narciso": (29, 10), "sant narcis": (29, 10),
    # Noviembre
    "todos los santos": (1, 11),
    "san roman": (18, 11),
    "san carlos borromeo": (4, 11),
    "virgen de la almudena": (9, 11),
    "san martin": (11, 11), "san martin de tours": (11, 11), "sant marti": (11, 11), "san martino": (11, 11),
    "san millan": (12, 11),
    "san diego": (13, 11), "san diego de alcala": (13, 11),
    "santa cecilia": (22, 11),
    "san clemente": (23, 11),
    "santa catalina": (25, 11), "santa catalina de alejandria": (25, 11),
    "la milagrosa": (27, 11), "virgen milagrosa": (27, 11),
    "san saturnino": (29, 11),
    "san andres": (30, 11), "sant andreu": (30, 11),
    # Diciembre
    "santa barbara": (4, 12),
    "san nicolas": (6, 12), "san nicolas de bari": (6, 12),
    "san ambrosio": (7, 12),
    "inmaculada": (8, 12), "inmaculada concepcion": (8, 12),
    "la purisima": (8, 12), "purisima concepcion": (8, 12),
    "santa lucia": (13, 12),
    "virgen de la esperanza": (18, 12),
    "santo tomas": (21, 12),
    "san esteban": (26, 12), "sant esteve": (26, 12),
    "san juan evangelista": (27, 12),
    "santos inocentes": (28, 12),
    "san silvestre": (31, 12),
}

# Claves ordenadas de más larga a más corta para el matching por contención
_SANTORAL_KEYS = sorted(SANTORAL.keys(), key=len, reverse=True)

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_NOMBRE_MES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

# Abreviaturas habituales antes de normalizar
_ABREVIATURAS = [
    (re.compile(r"\bntra\.?\s*sra\.?\b", re.IGNORECASE), "nuestra señora"),
    (re.compile(r"\bntro\.?\s*sr\.?\b", re.IGNORECASE), "nuestro señor"),
    (re.compile(r"\bstma\.?\b", re.IGNORECASE), "santisima"),
    (re.compile(r"\bstmo\.?\b", re.IGNORECASE), "santisimo"),
    (re.compile(r"\bsta\.?\b", re.IGNORECASE), "santa"),
    (re.compile(r"\bsto\.?\b", re.IGNORECASE), "santo"),
]


def _canonicalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre de santo/advocación para búsqueda en el santoral."""
    texto = nombre
    for patron, reemplazo in _ABREVIATURAS:
        texto = patron.sub(reemplazo, texto)
    texto = normalizar_texto(texto)
    # Advocaciones equivalentes de la Virgen
    texto = re.sub(r"\bnuestra senora\b", "virgen", texto)
    texto = re.sub(r"\bmaria santisima\b", "virgen", texto)
    texto = re.sub(r"\bsantisima virgen\b", "virgen", texto)
    texto = re.sub(r"\bvirgen maria\b", "virgen", texto)
    # Artículos iniciales
    texto = re.sub(r"^(el|la|los|las)\s+", "", texto)
    return texto.strip()


def buscar_en_santoral(nombre: str) -> tuple[int, int] | None:
    """Busca la fecha fija (dia, mes) de un santo/advocación en el santoral."""
    if not nombre:
        return None
    n = _canonicalizar_nombre(nombre)
    if n in SANTORAL:
        return SANTORAL[n]
    # Contención con límites de palabra, probando primero las claves más largas
    for key in _SANTORAL_KEYS:
        if re.search(rf"\b{re.escape(key)}\b", n):
            return SANTORAL[key]
    return None


# ──────────────────────────────────────────────────
# CACHÉ PERSISTENTE (el patrón no cambia entre años)
# ──────────────────────────────────────────────────

_CACHE_MISS = object()


def _write_patron_cache_sync(path: str, data: dict):
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(temp, path)
    except OSError as e:
        logger.error(f"Error guardando caché de patrones: {e}")


class _PatronCache:
    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def _cargar(self):
        if self._loaded:
            return
        self._loaded = True
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"Caché de patrones cargada: {len(self._data)} localidades")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"No se pudo leer la caché de patrones: {e}")
                self._data = {}

    async def get(self, lugar_id: str):
        async with self._lock:
            self._cargar()
            return self._data.get(lugar_id, _CACHE_MISS)

    async def set(self, lugar_id: str, valor: dict | None):
        async with self._lock:
            self._cargar()
            self._data[lugar_id] = valor
            await asyncio.to_thread(_write_patron_cache_sync, self.path, dict(self._data))


_FASE2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = _PatronCache(os.path.join(_FASE2_DIR, PATRON_CACHE_FILE))


# ──────────────────────────────────────────────────
# EXTRACCIÓN DE PATRÓN Y FECHA DE UN TEXTO
# ──────────────────────────────────────────────────

# Candidato a nombre de santo: empieza por un indicador religioso
_INICIO_SANTO = (
    r"(?:San|Sant|Santa|Santo|Santiago|Stma?\.?|Sta\.?|Sto\.?|"
    r"Virgen|Ntra\.?\s*Sra\.?|Nuestra\s+Señora|María\s+Santísima|"
    r"Cristo|Santísimo|Santísima|Inmaculada|Purísima|Asunción|Magdalena|Candelaria)"
)

# Nombre completo: indicador + hasta 5 palabras más (permitiendo de/del/la...)
_NOMBRE_SANTO = rf"({_INICIO_SANTO}[\wáéíóúüñÁÉÍÓÚÜÑ'.]*(?:\s+(?:de|del|la|las|los|el|d')?\s*[\wáéíóúüñÁÉÍÓÚÜÑ'.]+){{0,5}})"

_PATRONES_TEXTO = [
    re.compile(rf"en\s+honor\s+(?:a|de|del|de\s+la|de\s+los|de\s+las)\s+{_NOMBRE_SANTO}", re.IGNORECASE),
    re.compile(rf"patr[oó]n[a]?(?:\s+de[l]?(?:\s+\w+){{0,3}})?\s+es\s+{_NOMBRE_SANTO}", re.IGNORECASE),
    re.compile(rf"(?:su|el|la)\s+patr[oó]n[a]?\s*[,:]?\s+{_NOMBRE_SANTO}", re.IGNORECASE),
    re.compile(rf"festividad\s+de\s+{_NOMBRE_SANTO}", re.IGNORECASE),
    re.compile(rf"fiestas?\s+(?:patronales?\s+)?(?:de|del)\s+{_NOMBRE_SANTO}", re.IGNORECASE),
]

_RE_FECHA = re.compile(
    r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)",
    re.IGNORECASE,
)

# Palabras que delimitan el final de un nombre capturado de más
_CORTES_NOMBRE = re.compile(
    r"\s+(?:que|cuya?|donde|cuando|con|durante|para|entre|desde|hasta|celebrad\w+|patr[oó]n\w*)\b.*$",
    re.IGNORECASE,
)


def _limpiar_nombre(nombre: str) -> str:
    nombre = re.sub(r"\[\d+\]", "", nombre)          # referencias wiki [1]
    nombre = re.split(r"\.\s", nombre)[0]            # cortar en fin de frase ("San Andrés. Municipio...")
    nombre = _CORTES_NOMBRE.sub("", nombre)
    nombre = re.sub(r"[\s,.;:]+$", "", nombre.strip())
    return nombre


def _fecha_cercana(texto: str, posicion: int, radio: int = 120) -> tuple[int, int] | None:
    """Busca una fecha 'D de <mes>' cerca de una posición del texto."""
    ventana = texto[max(0, posicion - radio): posicion + radio]
    m = _RE_FECHA.search(ventana)
    if not m:
        return None
    dia, mes = int(m.group(1)), _MESES[m.group(2).lower()]
    if 1 <= dia <= 31:
        return (dia, mes)
    return None


def extraer_patron_de_texto(texto: str) -> dict | None:
    """
    Aplica regex deterministas sobre un texto para hallar el patrón.
    Recoge TODOS los candidatos y elige el mejor puntuado (menciones,
    presencia en el santoral, fecha explícita cercana), para ser robusto
    frente al ruido de los resultados de búsqueda.
    Devuelve {"nombre", "dia", "mes"} (dia/mes pueden ser None) o None.
    """
    if not texto:
        return None

    candidatos: dict[str, dict] = {}
    for patron_re in _PATRONES_TEXTO:
        for m in patron_re.finditer(texto):
            nombre = _limpiar_nombre(m.group(1))
            if len(nombre) < 4:
                continue
            # Debe parecer un santo real: o está en el santoral o empieza por indicador claro
            en_santoral = buscar_en_santoral(nombre) is not None
            canon = _canonicalizar_nombre(nombre)
            indicador = re.match(
                r"^(san|sant|santa|santo|santiago|virgen|cristo|santisim|inmaculada|purisima|asuncion|magdalena|candelaria)",
                canon,
            )
            if not en_santoral and not indicador:
                continue
            c = candidatos.setdefault(
                canon,
                {"nombre": nombre, "dia": None, "mes": None, "menciones": 0, "en_santoral": en_santoral},
            )
            c["menciones"] += 1
            if c["dia"] is None:
                fecha_texto = _fecha_cercana(texto, m.start())
                if fecha_texto:
                    c["dia"], c["mes"] = fecha_texto

    if not candidatos:
        return None

    def _puntuar(c: dict) -> int:
        return c["menciones"] + (3 if c["en_santoral"] else 0) + (1 if c["dia"] else 0)

    mejor = max(candidatos.values(), key=_puntuar)
    return {"nombre": mejor["nombre"], "dia": mejor["dia"], "mes": mejor["mes"]}


def _resolver_fecha(resultado: dict, fuente: str) -> dict:
    """Combina fecha explícita del texto con el santoral. El santoral prevalece."""
    nombre = resultado["nombre"]
    dia_texto, mes_texto = resultado.get("dia"), resultado.get("mes")
    santoral = buscar_en_santoral(nombre)

    if santoral and dia_texto and mes_texto:
        if santoral == (dia_texto, mes_texto):
            dia, mes, confianza = dia_texto, mes_texto, "alta"
        else:
            dia, mes = santoral
            confianza = "media"
            logger.info(
                f"  [PATRON] Fecha del texto ({dia_texto}/{mes_texto}) discrepa del "
                f"santoral ({santoral[0]}/{santoral[1]}) para '{nombre}'. Prevalece el santoral."
            )
    elif santoral:
        (dia, mes), confianza = santoral, "alta"
    elif dia_texto and mes_texto:
        dia, mes, confianza = dia_texto, mes_texto, "media"
    else:
        dia, mes, confianza = None, None, "baja"

    return {"nombre": nombre, "dia": dia, "mes": mes, "fuente": fuente, "confianza": confianza}


# ──────────────────────────────────────────────────
# FUENTES: WIKIPEDIA Y BUSCADORES
# ──────────────────────────────────────────────────

async def _descargar_wikipedia(session: aiohttp.ClientSession, url: str) -> tuple[dict, str]:
    """Devuelve (filas_infobox, texto_relevante) de una página de Wikipedia."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=DDG_REQUEST_TIMEOUT)) as resp:
            if resp.status != 200:
                return {}, ""
            html = await resp.text(errors="replace")
    except Exception as e:
        logger.debug(f"Error descargando Wikipedia {url}: {e}")
        return {}, ""

    soup = BeautifulSoup(html, "html.parser")

    filas = {}
    infobox = soup.find("table", class_="infobox")
    if infobox:
        for tr in infobox.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td:
                clave = normalizar_texto(th.get_text(" ", strip=True))
                filas[clave] = td.get_text(" ", strip=True)

    # Texto de párrafos que mencionen patrón/fiestas/festividad
    parrafos = []
    for p in soup.find_all("p"):
        texto_p = p.get_text(" ", strip=True)
        if re.search(r"patr[oó]n|patronal|festivid|fiestas?", texto_p, re.IGNORECASE):
            parrafos.append(texto_p)
    texto = "\n".join(parrafos)[:8000]
    return filas, texto


def _extraer_de_infobox(filas: dict) -> dict | None:
    """Extrae patrón (y fecha si aparece) de las filas del infobox de Wikipedia."""
    # Filas directas de patrón
    for clave, valor in filas.items():
        if re.search(r"\bpatron(a)?\b", clave):
            nombre = _limpiar_nombre(re.split(r"[,;(]", valor)[0])
            if len(nombre) >= 4:
                m = _RE_FECHA.search(valor)
                dia, mes = (int(m.group(1)), _MESES[m.group(2).lower()]) if m else (None, None)
                return {"nombre": nombre, "dia": dia, "mes": mes}
    # Filas de fiestas ("Fiesta mayor", "Fiestas") tipo "16 de agosto (San Roque)"
    for clave, valor in filas.items():
        if re.search(r"\bfiestas?\b|fiesta mayor|festividad", clave):
            resultado = extraer_patron_de_texto(valor)
            if resultado:
                if resultado["dia"] is None:
                    m = _RE_FECHA.search(valor)
                    if m:
                        resultado["dia"] = int(m.group(1))
                        resultado["mes"] = _MESES[m.group(2).lower()]
                return resultado
            # Solo fecha + nombre entre paréntesis: intentar el nombre crudo
            m = _RE_FECHA.search(valor)
            nombre_m = re.search(r"\(([^)]+)\)", valor)
            if m and nombre_m and buscar_en_santoral(nombre_m.group(1)):
                return {
                    "nombre": _limpiar_nombre(nombre_m.group(1)),
                    "dia": int(m.group(1)),
                    "mes": _MESES[m.group(2).lower()],
                }
    return None


def _ventanas_relevantes(texto: str, nombre_localidad: str, radio: int = 300, max_total: int = 6000) -> str:
    """Recorta ventanas alrededor de menciones de 'patrón/patronales' que citen la localidad."""
    ventanas = []
    total = 0
    loc_norm = normalizar_texto(nombre_localidad)
    for m in re.finditer(r"patr[oó]n\w*", texto, re.IGNORECASE):
        ini, fin = max(0, m.start() - radio), m.end() + radio
        ventana = texto[ini:fin]
        if loc_norm and loc_norm not in normalizar_texto(ventana):
            continue
        ventanas.append(ventana)
        total += len(ventana)
        if total > max_total:
            break
    return "\n...\n".join(ventanas)


async def _buscar_en_web(session: aiohttp.ClientSession, localidad: dict, municipio: dict) -> str:
    """Busca el patrón en buscadores (reutiliza el scraper multi-motor de google_search)."""
    from scraper.google_search import _fetch_search_results, _fetch_page_content

    nombre_loc = localidad["nombre"]
    queries = [
        f"santo patrón de {nombre_loc} {municipio['nombre']} {municipio.get('provincia', '')}",
        f"fiestas patronales {nombre_loc} {municipio['nombre']} en honor",
    ]

    texto = ""
    urls = []
    loc_norm = normalizar_texto(nombre_loc)
    for query in queries:
        resultados = await _fetch_search_results(session, query)
        for r in resultados:
            fragmento = f"{r['titulo']}. {r['snippet']}"
            # Solo snippets que mencionen la localidad (evita el patrón de otro pueblo)
            if loc_norm in normalizar_texto(fragmento):
                texto += fragmento + "\n"
                url = r.get("url", "")
                if url.startswith("http") and url not in urls:
                    urls.append(url)

    if urls:
        tareas = [_fetch_page_content(session, u) for u in urls[:PATRON_MAX_URLS]]
        contenidos = await asyncio.gather(*tareas, return_exceptions=True)
        for contenido in contenidos:
            if isinstance(contenido, str) and contenido.strip():
                texto += "\n" + _ventanas_relevantes(contenido, nombre_loc)

    return texto


async def _extraer_con_llm(texto: str, localidad: dict) -> dict | None:
    """Fallback: pide al LLM local que identifique el patrón en el texto recopilado."""
    from llm_processor.text_analyzer import llm_chat_json

    system_prompt = (
        "Eres una API estricta que identifica el santo patrón o la santa patrona de una localidad española.\n"
        'Responde SOLO con JSON: {"patron": "Nombre del santo o null", "dia": numero o null, "mes": numero o null}\n'
        "El día y mes son la fecha fija del calendario en que se celebra su festividad, solo si el texto la indica.\n"
        "Si el texto no menciona ningún patrón de esa localidad concreta, devuelve {\"patron\": null}."
    )
    user_prompt = (
        f"LOCALIDAD: {localidad['nombre']}\n\nTEXTO:\n{texto[:3500]}\n\n"
        "¿Cuál es el santo patrón de esta localidad? Responde SOLO con JSON:"
    )

    parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=PATRON_LLM_MAX_TOKENS)
    if not parsed or not parsed.get("patron"):
        return None

    nombre = _limpiar_nombre(str(parsed["patron"]))
    if len(nombre) < 4:
        return None
    dia = parsed.get("dia") if isinstance(parsed.get("dia"), int) else None
    mes = parsed.get("mes") if isinstance(parsed.get("mes"), int) else None
    if not (dia and mes and 1 <= dia <= 31 and 1 <= mes <= 12):
        dia, mes = None, None
    return {"nombre": nombre, "dia": dia, "mes": mes}


# ──────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ──────────────────────────────────────────────────

async def obtener_patron(localidad: dict, municipio: dict) -> dict | None:
    """
    Halla el santo patrón de una localidad y su día fijo del calendario.
    Devuelve {"nombre", "dia", "mes", "fuente", "confianza"} o None.
    Usa caché persistente: el patrón no cambia entre ejecuciones.
    """
    if not PATRON_SEARCH_ENABLED:
        return None

    lugar_id = localidad["id"]
    cacheado = await _cache.get(lugar_id)
    if cacheado is not _CACHE_MISS:
        return cacheado

    resultado = None
    fuente = None
    textos_acumulados = []

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
    connector = aiohttp.TCPConnector(limit=3, ssl=False)

    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            # Fuente 1: Wikipedia (localidad, luego municipio)
            urls_wiki = []
            for lugar in (localidad, municipio):
                url = (lugar.get("wikipedia_url") or "").strip()
                if url and url not in urls_wiki:
                    urls_wiki.append(url)

            for url in urls_wiki:
                filas, texto = await _descargar_wikipedia(session, url)
                textos_acumulados.append(texto)
                resultado = _extraer_de_infobox(filas) or extraer_patron_de_texto(texto)
                if resultado:
                    fuente = "wikipedia"
                    break

            # Fuente 2: buscadores
            if not resultado:
                texto_web = await _buscar_en_web(session, localidad, municipio)
                textos_acumulados.append(texto_web)
                resultado = extraer_patron_de_texto(texto_web)
                if resultado:
                    fuente = "busqueda"

        # Fuente 3 (fallback): LLM sobre todo lo acumulado
        if not resultado:
            texto_total = "\n".join(t for t in textos_acumulados if t).strip()
            if texto_total:
                resultado = await _extraer_con_llm(texto_total, localidad)
                if resultado:
                    fuente = "llm"

    except Exception as e:
        logger.warning(f"  [PATRON] Error buscando patrón de {localidad['nombre']}: {e}")

    if resultado:
        # Recortar coletilla "de/del/de la <localidad>" pegada al nombre del santo
        recortado = re.sub(
            rf"\s+(?:de|del|de\s+la|de\s+los|de\s+las)\s+{re.escape(localidad['nombre'])}$",
            "",
            resultado["nombre"],
            flags=re.IGNORECASE,
        ).strip()
        # No dejar el nombre vacío o sin sentido (p. ej. "Virgen del Mironcillo" → "Virgen")
        if len(recortado) >= 4 and _canonicalizar_nombre(recortado) not in {"virgen", "cristo", "santo", "santa", "san"}:
            resultado["nombre"] = recortado

    final = _resolver_fecha(resultado, fuente) if resultado else None
    if final:
        fecha_txt = f"{final['dia']} de {_NOMBRE_MES[final['mes']]}" if final["mes"] else "fecha desconocida"
        logger.info(
            f"  [PATRON] {localidad['nombre']}: {final['nombre']} ({fecha_txt}) "
            f"[{final['fuente']}, confianza {final['confianza']}]"
        )
    else:
        logger.info(f"  [PATRON] No se encontró patrón para {localidad['nombre']}.")

    await _cache.set(lugar_id, final)
    return final


# ──────────────────────────────────────────────────
# INTEGRACIÓN CON LAS FIESTAS EXTRAÍDAS (funciones puras)
# ──────────────────────────────────────────────────

def fecha_del_patron(patron: dict | None, anno: int) -> date | None:
    """Día del patrón en el año objetivo, o None si no hay fecha fiable. Si es 29 de febrero y el año no es bisiesto, cae a 28 de febrero."""
    if not patron or not patron.get("dia") or not patron.get("mes"):
        return None
    try:
        return date(anno, patron["mes"], patron["dia"])
    except ValueError:
        if patron.get("mes") == 2 and patron.get("dia") == 29:
            try:
                return date(anno, 2, 28)
            except ValueError:
                return None
        return None



def crear_fiesta_estimada(patron: dict, fecha: date, localidad: dict) -> dict:
    """Registro estimado de un día cuando ninguna fiesta extraída cubre el día del patrón."""
    slug = re.sub(r"[^a-z0-9]+", "-", normalizar_texto(patron["nombre"])).strip("-")[:40]
    fecha_iso = fecha.isoformat()
    return {
        "id": f"patron-{slug}-{localidad['id']}",
        "lugar_id": localidad["id"],
        "nombre": f"Fiestas de {patron['nombre']} (estimada)",
        "fecha_inicio": fecha_iso,
        "fecha_fin": fecha_iso,
        "tamano": "pequeña",
        "descripcion": (
            f"Fiesta anual estimada a partir del día del santo patrón de "
            f"{localidad['nombre']} ({patron['nombre']}, {patron['dia']} de {_NOMBRE_MES[patron['mes']]}). "
            f"No se encontró programa ni confirmación para este año."
        ),
        "confianza": "baja",
        "origen": "santo_patron",
        "es_estimada": True,
        "incluye_dia_patron": True,
        "fuentes": [],
        "solo_fuentes_no_oficiales": False,
        "patron": {
            "nombre": patron["nombre"],
            "dia": patron["dia"],
            "mes": patron["mes"],
            "fuente": patron.get("fuente"),
        },
        "programa": [],
    }


def integrar_patron(fiestas: list[dict], patron: dict | None, anno: int, localidad: dict) -> list[dict]:
    """
    Marca las fiestas que incluyen el día del patrón y, si ninguna lo cubre
    (incluido el caso de 0 fiestas), añade el registro estimado.
    """
    fecha = fecha_del_patron(patron, anno)
    if not fecha:
        return fiestas

    fecha_iso = fecha.isoformat()
    cubierto = False
    for f in fiestas:
        if f.get("fecha_inicio", "") <= fecha_iso <= f.get("fecha_fin", ""):
            f["incluye_dia_patron"] = True
            f["patron"] = {
                "nombre": patron["nombre"],
                "dia": patron["dia"],
                "mes": patron["mes"],
                "fuente": patron.get("fuente"),
            }
            cubierto = True

    if not cubierto:
        fiestas.append(crear_fiesta_estimada(patron, fecha, localidad))
        logger.info(
            f"  [PATRON] Añadida fiesta estimada de {patron['nombre']} ({fecha_iso}) "
            f"para {localidad['nombre']} (día del patrón no cubierto)."
        )

    return fiestas

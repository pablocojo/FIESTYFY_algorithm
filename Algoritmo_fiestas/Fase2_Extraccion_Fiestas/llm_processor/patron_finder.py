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
  el registro estimado cuando ninguna ficha ES la fiesta de ese patrón. Ojo a la
  diferencia: "ser la fiesta del patrón" no es "caer en el día del patrón", que
  es como se duplicaban las patronales trasladadas al verano.
"""

import asyncio
import json
import os
import re
import logging
import unicodedata
from datetime import date
from urllib.parse import unquote

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
    # Santos compuestos cuyo apellido NO empieza por "de": sin su entrada
    # propia, el santoral casa el prefijo y `recortar_coletilla_del_santo` tira
    # la palabra que los distingue. Medido el 2026-08-27: el patrón de Sierra,
    # San Francisco Javier (3 de diciembre), se guardaba como "San Francisco"
    # (4 de octubre) y con esa fecha equivocada se descartó dos veces su fiesta
    # buena. Son cuatro meses de diferencia y otro santo.
    "san francisco javier": (3, 12),
    "san vicente ferrer": (5, 4),
    "san juan bosco": (31, 1),
    "san jose obrero": (1, 5),
    "san antonio maria claret": (24, 10),
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


def _clave_toponimo(nombre: str) -> str:
    """
    Reduce un topónimo a una clave que iguala las grafías euskera y castellana
    del mismo pueblo.

    Wikipedia titula los concejos alaveses en castellano y el padrón los nombra
    en euskera, así que la URL de un pueblo real casi nunca coincide letra a
    letra con su nombre. Las diferencias son un puñado de dígrafos regulares:
    Saratxo/Saracho, Delika/Délica, Baranbio/Barambio, Larrinbe/Larrimbe.

    Medido sobre esos pares y sobre contraejemplos duros (Lezama/Lekamaña,
    Elorrio/Elorriaga, Berriz/Berriatua): con esta normalización los pares
    verdaderos caen en la MISMA clave y los falsos no. Por eso la comparación de
    arriba puede exigir igualdad exacta en vez de un umbral de parecido, que en
    estos nombres cortos no separa nada.
    """
    base = normalizar_texto(re.sub(r"\s*\(.*?\)\s*", " ", nombre or ""))
    base = re.sub(r"[^a-z0-9]+", "", base)
    for origen, destino in (("tx", "ch"), ("tz", "z"), ("k", "c"), ("nb", "mb"), ("v", "b")):
        base = base.replace(origen, destino)
    return base


def _wiki_es_de_la_localidad(url: str, nombre_localidad: str) -> bool:
    """
    ¿El artículo de Wikipedia trata de ESTA localidad, o es prestado?

    Fase 1 rellena `wikipedia_url` como puede y se equivoca a menudo: medido el
    2026-08-22 sobre Amurrio, Aloria y Amurrio-pueblo apuntaban al artículo de la
    PROVINCIA de Álava y Tertanga al de Délica, que es otro pueblo. Sacar el
    patrón de ahí es cómo Tertanga acabó con el patrón del vecino y media comarca
    con el del municipio.
    """
    if not url:
        return False
    slug = unquote(url.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ")
    return bool(slug) and _clave_toponimo(slug) == _clave_toponimo(nombre_localidad)


def clave_en_santoral(nombre: str) -> str | None:
    """Entrada del santoral que reconoce este nombre, o None."""
    if not nombre:
        return None
    n = _canonicalizar_nombre(nombre)
    if n in SANTORAL:
        return n
    # Contención con límites de palabra, probando primero las claves más largas
    for key in _SANTORAL_KEYS:
        if re.search(rf"\b{re.escape(key)}\b", n):
            return key
    return None


def buscar_en_santoral(nombre: str) -> tuple[int, int] | None:
    """Busca la fecha fija (dia, mes) de un santo/advocación en el santoral."""
    key = clave_en_santoral(nombre)
    return SANTORAL[key] if key else None


# Palabras que puede tener el complemento de una advocación ("de la Antigua",
# "del Amparo", "de los Remedios"). Por encima ya no es un nombre, es una frase.
_MAX_PALABRAS_ADVOCACION = 4
_PARTICULAS = {"de", "del", "la", "las", "los", "el", "y", "a"}


def capitalizar_advocacion(nombre: str) -> str:
    """
    Pone mayúsculas a un nombre de santo que venga todo en minúsculas.

    Los buscadores devuelven el patrón tal y como lo escribiera la fuente, y a
    veces llega "virgen del carmen". Si el nombre ya trae mayúsculas se deja como
    está: quien lo escribió sabía más que nosotros.
    """
    if not nombre or nombre != nombre.lower():
        return nombre
    palabras = nombre.split()
    return " ".join(
        p if i and p in _PARTICULAS else p.capitalize() for i, p in enumerate(palabras)
    )


def recortar_coletilla_del_santo(nombre: str) -> str:
    """
    Deja el nombre del santo en el nombre del santo.

    La ruta de buscadores devuelve trozos de titular, no nombres: medido el
    2026-08-22, el patrón de Artomaña se guardó como "San Jorge vuelven a incluir
    este", el de Larrinbe como "Santiago 2026 en Larrinbe" y el de Baranbio como
    "San Antón en la ermita de dicho santo". Las FECHAS salían bien —el santoral
    las resuelve igual—, pero el nombre acababa así en la salida.

    Si el santoral reconoce el principio del nombre, sobra todo lo que venga
    después. Cuando lo que reconoce no está al principio no se toca nada: en
    "Nuestra Señora de la Asunción" el santoral casa por su sinónimo "virgen de
    la asuncion", y recortar ahí estropearía un nombre que ya era correcto.

    Y lo que va detrás tampoco sobra siempre: la advocación concreta se forma
    justo así, con un complemento. El santoral reconoce "santísimo cristo" y de
    "Stmo. Cristo de la Antigua" —el patrón de Tobarra— dejaba "Stmo. Cristo",
    tirando lo único que lo distingue de cualquier otro Cristo. Una cola que
    empieza por "de" o "del" y es corta es parte del nombre; una que empieza por
    otra cosa ("2026 en Aloria", "vuelven a incluir este") o que se alarga, no.
    """
    if not nombre:
        return nombre
    key = clave_en_santoral(nombre)
    if not key:
        return nombre

    palabras = nombre.split()
    n_clave = len(key.split())
    if len(palabras) <= n_clave:
        return nombre

    prefijo = " ".join(palabras[:n_clave])
    if _canonicalizar_nombre(prefijo) != key:
        return nombre      # el santo no está al principio: no hay coletilla que quitar

    cola = palabras[n_clave:]
    if len(cola) <= _MAX_PALABRAS_ADVOCACION and normalizar_texto(cola[0]) in {"de", "del"}:
        return nombre      # "…de la Antigua", "…del Amparo": es la advocación entera

    # Una cola de UNA palabra en mayúscula es sospechosa: puede ser el apellido
    # que distingue a un santo de otro ("Javier", "Ferrer", "Bosco") y no una
    # coletilla de titular. Si lo es, su sitio está en el santoral, no aquí; se
    # deja constancia para que se vea al primer run en vez de descubrirse por
    # casualidad cuatro meses después.
    if len(cola) == 1 and cola[0][:1].isupper() and cola[0].isalpha():
        logger.warning(
            f"  [PATRON] Recortado '{nombre}' a '{prefijo}': el santoral no conoce "
            f"'{normalizar_texto(nombre)}'. Si son santos distintos, falta su entrada."
        )
    return prefijo


# ──────────────────────────────────────────────────
# CACHÉ PERSISTENTE (el patrón no cambia entre años)
# ──────────────────────────────────────────────────

_CACHE_MISS = object()


def _write_patron_cache_sync(path: str, data: dict):
    from state_manager import escribir_json_con_respaldo
    try:
        escribir_json_con_respaldo(path, data, indent=1)
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
            from state_manager import leer_json_con_respaldo
            datos = leer_json_con_respaldo(self.path, "La caché de patrones")
            if isinstance(datos, dict):
                self._data = datos
                logger.info(f"Caché de patrones cargada: {len(self._data)} localidades")

    async def get(self, lugar_id: str):
        async with self._lock:
            self._cargar()
            valor = self._data.get(lugar_id, _CACHE_MISS)
            # Las entradas escritas antes de que existiera `ambito` no distinguen
            # el patrón propio del heredado del municipio, y sobre esa distinción
            # se decide ahora qué fiestas se descartan. Se recalculan.
            if isinstance(valor, dict) and "ambito" not in valor:
                return _CACHE_MISS
            return valor

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


# Abreviaturas que llevan punto DENTRO del nombre de un santo. Cortar la frase en
# el primer "punto y espacio" las decapita: medido el 2026-08-25, el patrón de
# Tobarra —el Stmo. Cristo de la Antigua— quedaba guardado como "Stmo". Le pasa a
# cualquier pueblo cuyo patrón se escriba abreviado, que son muchísimos.
_ABREVIATURAS_SANTO = (
    "stmo", "stma", "smo", "sma", "sto", "sta", "s", "ntra", "ntro", "nta",
    "sr", "sra", "srta", "bto", "bta", "excmo", "ilmo", "vgen", "vg",
)
def _validar_patron(resultado: dict | None, localidad: dict, municipio: dict, fuente: str) -> dict | None:
    """
    Deja pasar el resultado solo si el nombre puede ser el de un santo.

    Cuando no lo es se devuelve None y la localidad sigue su camino: se prueba la
    siguiente fuente y, si ninguna da algo creíble, se queda SIN patrón. Es lo
    acordado el 2026-08-25: ninguno antes que uno equivocado, porque el patrón
    alimenta las consultas de búsqueda de las patronales y la guarda que impide
    mover sus fechas, así que uno malo no se queda quieto, propaga.
    """
    if not resultado:
        return None
    nombre = (resultado.get("nombre") or "").strip()
    if nombre_de_patron_creible(nombre, localidad.get("nombre", ""), municipio.get("nombre", "")):
        return resultado
    logger.info(
        f"  [PATRON] {localidad.get('nombre')}: se descarta '{nombre}' ({fuente}); "
        f"no parece el nombre de un santo."
    )
    return None


def nombre_de_patron_creible(nombre: str, localidad_nombre: str, municipio_nombre: str = "") -> bool:
    """
    ¿Esto que hemos extraído puede ser el nombre de un santo?

    Tres cosas que no lo son, las tres sacadas del caché del 2026-08-25:

    - El nombre del propio pueblo. A Santiago de Mora se le guardó como patrón
      «Santiago de Mora 2026», con confianza alta, porque su web dice «fiestas
      patronales de Santiago de Mora 2026» y el extractor se quedó con lo que
      venía detrás de «patronales de». La consulta que salía de ahí era
      «fiestas patronales Santiago de Mora 2026 Santiago de Mora 2026».
    - Un año pegado. Un santo no lleva año.
    - Una abreviatura suelta: «Stmo» era lo que quedaba del Cristo de la
      Antigua de Tobarra al cortar el nombre en el punto de la abreviatura.

    Ojo con el caso legítimo: hay pueblos que se llaman como su patrón —Santiago
    de Mora entre ellos—, así que lo que se rechaza es el topónimo COMPLETO, no
    que compartan una palabra. «Santiago» a secas sigue valiendo.
    """
    n = normalizar_texto(nombre or "").strip()
    if len(n) < 4:
        return False
    if re.search(r"\b(19|20)\d{2}\b", n):
        return False
    if n in _ABREVIATURAS_SANTO:
        return False
    for lugar in (localidad_nombre, municipio_nombre):
        if lugar and n == normalizar_texto(lugar).strip():
            return False
    return True


def _cortar_en_fin_de_frase(nombre: str) -> str:
    """
    Corta en el primer punto que cierra una frase, saltándose las abreviaturas.

    Se mira la palabra ANTERIOR al punto, no la siguiente. Con un lookahead sobre
    lo que viene detrás no funciona: en «Stmo. Cristo de la Antigua» la
    abreviatura está delante del punto, y el corte seguía dejando «Stmo».
    """
    for m in re.finditer(r"\.\s+", nombre):
        anterior = re.search(r"(\w+)$", nombre[:m.start()])
        if anterior and anterior.group(1).lower() in _ABREVIATURAS_SANTO:
            continue
        return nombre[:m.start()]
    return nombre


def _limpiar_nombre(nombre: str) -> str:
    nombre = re.sub(r"\[\d+\]", "", nombre)          # referencias wiki [1]
    # Un nombre de santo es UNA línea. El salto de línea colaba la ciudad de la
    # hermandad pegada detrás: a Sierra le quedó "Santísimo Cristo del
    # Consuelo\nSevilla" guardado como patrón, con el salto incluido.
    nombre = nombre.split("\n")[0]
    # Cortar en fin de frase ("San Andrés. Municipio de..."), pero no cuando el
    # punto es el de una abreviatura ("Stmo. Cristo de la Antigua").
    nombre = _cortar_en_fin_de_frase(nombre)
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


def _resolver_fecha(resultado: dict, fuente: str, ambito: str = "localidad") -> dict:
    """Combina fecha explícita del texto con el santoral. El santoral prevalece."""
    nombre = resultado["nombre"]
    celebra_del_texto = (None, None)
    dia_texto, mes_texto = resultado.get("dia"), resultado.get("mes")
    santoral = buscar_en_santoral(nombre)

    if santoral and dia_texto and mes_texto:
        if santoral == (dia_texto, mes_texto):
            dia, mes, confianza = dia_texto, mes_texto, "alta"
        else:
            dia, mes = santoral
            confianza = "media"
            # La fecha del texto no es un error que descartar: es CUANDO LO
            # CELEBRA EL PUEBLO. Garrucha, 2026-09-07: el texto decia 14/8 —las
            # patronales reales, del 14 al 18— y el santoral 26/7. Al quedarse
            # solo con el santoral, `_avales_de_patronal` comparaba contra una
            # fecha que ninguna ficha cubria, el desempate caia al nombre, y una
            # ficha de Cuaresma mal etiquetada expulsaba a fiestas verdaderas.
            # El santoral sigue mandando en `dia`/`mes`, que es el dato
            # liturgico; la del texto se guarda donde corresponde.
            celebra_del_texto = (dia_texto, mes_texto)
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

    # El patrón heredado del municipio nunca es de confianza alta, por muy bien
    # que el santoral fije su fecha: la fecha puede ser exacta y el santo, ajeno.
    if ambito != "localidad" and confianza == "alta":
        confianza = "media"

    # Los campos de la ficha se arrastran explicitamente. Este `return` monta un
    # dict NUEVO, asi que sin estas lineas `celebra_*` y `fiestas_habituales` se
    # perdian aqui aunque el LLM los hubiera extraido bien: el 2026-09-07 la
    # ficha llegaba vacia a todas las localidades por este motivo.
    #
    # `fiestas_habituales` se pone SIEMPRE, aunque sea lista vacia: es la clave
    # que mira la invalidacion de cache, y sin ella cada ejecucion volveria a
    # re-resolver la misma localidad sin converger nunca.
    return {
        "nombre": nombre, "dia": dia, "mes": mes,
        "fuente": fuente, "confianza": confianza, "ambito": ambito,
        "celebra_dia": resultado.get("celebra_dia") or celebra_del_texto[0],
        "celebra_mes": resultado.get("celebra_mes") or celebra_del_texto[1],
        "fiestas_habituales": resultado.get("fiestas_habituales") or [],
    }


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


def _pagina_anclada_al_municipio(texto: str, url: str, municipio: dict) -> bool:
    """
    ¿Esta página está atada a nuestro municipio, y no solo repite el nombre del pueblo?

    Aquí sí se exige el municipio o la provincia, al revés que en el filtro de
    documentos de fiestas, donde la provincia se descartó como aval por dejar
    entrar el material de la capital. La diferencia es qué se juega cada uno: allí
    un documento de más solo gasta contexto, aquí un patrón equivocado se queda en
    la caché y envenena las consultas de todas las ejecuciones siguientes.
    """
    aguja = normalizar_texto(f"{texto} {url}")
    for pista in (municipio.get("nombre", ""), municipio.get("provincia", "")):
        pista = normalizar_texto(pista or "").strip()
        if pista and pista in aguja:
            return True
    return False


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


async def _buscar_en_web(
    session: aiohttp.ClientSession, localidad: dict, municipio: dict,
    calendario: bool = False,
) -> str:
    """Busca en buscadores (reutiliza el scraper multi-motor de google_search).

    Con `calendario=True` cambia las consultas: en vez de preguntar por el santo
    patron, barre el calendario festivo entero del pueblo. La distincion importa
    y esta medida: con las dos consultas patronales de siempre, la fase 1 sacaba
    catalogos de dos o tres fiestas para pueblos que tienen seis o nueve, porque
    el material que veia el modelo no hablaba de carnavales ni de romerias. En la
    ejecucion del 2026-09-07, 8 de 23 localidades salieron con catalogo vacio.
    """
    from scraper.google_search import _fetch_search_results, _fetch_page_content

    nombre_loc = localidad["nombre"]
    prov = municipio.get("provincia", "")
    if calendario:
        # Se barre por TIPOS a proposito. Una consulta generica de "fiestas de X"
        # devuelve casi siempre la patronal y poco mas; nombrar carnaval, romeria
        # y feria es lo que saca a la superficie las que el pueblo celebra y
        # nadie destaca.
        queries = [
            f"fiestas de {nombre_loc} {prov} calendario festivo todo el año",
            f"{nombre_loc} {prov} carnaval semana santa romería feria tradiciones",
            f"{nombre_loc} {municipio['nombre']} fiestas populares que se celebran",
        ]
    else:
        queries = [
            f"santo patrón de {nombre_loc} {municipio['nombre']} {prov}",
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
        seguidas = urls[:PATRON_MAX_URLS]
        tareas = [_fetch_page_content(session, u) for u in seguidas]
        contenidos = await asyncio.gather(*tareas, return_exceptions=True)
        for url, resultado in zip(seguidas, contenidos):
            # _fetch_page_content devuelve ahora (texto, pdfs_enlazados)
            if isinstance(resultado, BaseException) or not isinstance(resultado, tuple):
                continue
            # `_fetch_page_content` devuelve TRES valores (texto, pdfs, enlaces).
            # Aqui se desempaquetaban dos, asi que esta fuente reventaba siempre
            # con 'too many values to unpack' y el except de `obtener_patron` lo
            # convertia en 'No se encontro patron'. El buscador de patrones
            # llevaba degradado a solo-Wikipedia sin que nada lo dijera.
            contenido, _pdfs, _enlaces = resultado
            if not (contenido and contenido.strip()):
                continue
            # La página entera tiene que estar anclada a nuestro sitio, no solo
            # nombrar al pueblo. Con nombres corrientes eso no filtra nada:
            # medido el 2026-08-25, a la pedanía "Sierra" de Tobarra le entró la
            # página de una hermandad sevillana porque decía "sierra", y se le
            # guardó como patrón «Santísimo Cristo del Consuelo\nSevilla».
            if not _pagina_anclada_al_municipio(contenido, url, municipio):
                logger.info(
                    f"  [PATRON] {nombre_loc}: se descarta '{url[:70]}'; no nombra a "
                    f"{municipio.get('nombre')} ni a su provincia."
                )
                continue
            texto += "\n" + _ventanas_relevantes(contenido, nombre_loc)

    return texto


async def _extraer_con_llm(texto: str, localidad: dict) -> dict | None:
    """Fallback: pide al LLM local que identifique el patrón en el texto recopilado."""
    from llm_processor.text_analyzer import llm_chat_json

    system_prompt = (
        "Eres una API estricta que describe el calendario festivo de una localidad espanola.\n"
        "Responde SOLO con JSON:\n"
        '{"patron": "Nombre del santo o null", "dia": numero o null, "mes": numero o null,\n'
        ' "celebra_dia": numero o null, "celebra_mes": numero o null,\n'
        ' "fiestas_habituales": ["nombre de fiesta con su epoca", ...]}\n'
        "\n"
        "DISTINCION CRITICA entre dos fechas que casi nunca coinciden:\n"
        "  - dia/mes: la fecha del SANTORAL, la del calendario liturgico.\n"
        "  - celebra_dia/celebra_mes: cuando el PUEBLO celebra de verdad sus\n"
        "    fiestas patronales, que suele desplazarse al verano o a un fin de\n"
        "    semana. San Joaquin es el 26 de julio en el santoral, pero Garrucha\n"
        "    lo celebra a mediados de agosto.\n"
        "  Si el texto solo da una de las dos, rellena esa y deja la otra a null.\n"
        "  NO copies la del santoral en celebra_* si el texto no la respalda.\n"
        "\n"
        "fiestas_habituales: celebraciones que este pueblo repite cada anno, con\n"
        "su epoca, en frases cortas. Incluye romerias, ferias, carnavales y\n"
        "patronales de barrios o pedanias si el texto las menciona. Ejemplo:\n"
        '["Virgen del Carmen, 16 de julio, procesion maritima", "Carnaval, febrero"].\n'
        "Lista vacia si el texto no dice ninguna.\n"
        "\n"
        "Solo lo que el TEXTO respalde. No completes con conocimiento general: una\n"
        "fiesta inventada aqui contamina todo lo que venga despues.\n"
        "Si el texto no menciona ningun patron de esa localidad, devuelve {\"patron\": null}."
    )
    user_prompt = (
        f"LOCALIDAD: {localidad['nombre']}\n\nTEXTO:\n{texto[:3500]}\n\n"
        "Patron, cuando lo celebra el pueblo y que otras fiestas tiene. SOLO JSON:"
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
    celebra_dia = parsed.get("celebra_dia") if isinstance(parsed.get("celebra_dia"), int) else None
    celebra_mes = parsed.get("celebra_mes") if isinstance(parsed.get("celebra_mes"), int) else None
    if not (celebra_dia and celebra_mes and 1 <= celebra_dia <= 31 and 1 <= celebra_mes <= 12):
        celebra_dia, celebra_mes = None, None

    # Las habituales son TEXTO para el contexto, no datos: se acotan de longitud y
    # de numero, pero no se validan contra nada. Quien decide si esas fiestas
    # existen es el modelo que despues vea los documentos.
    habituales = []
    for item in (parsed.get("fiestas_habituales") or [])[:14]:
        if isinstance(item, str) and 4 <= len(item.strip()) <= 120:
            habituales.append(item.strip())

    return {
        "nombre": nombre,
        "dia": dia,
        "mes": mes,
        "celebra_dia": celebra_dia,
        "celebra_mes": celebra_mes,
        "fiestas_habituales": habituales,
    }


# ──────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ──────────────────────────────────────────────────

# Cuanto texto ve el catalogador. Estuvo en 12.000 y era la causa de que el
# catalogo saliera corto: el 2026-09-08, Garrucha reunia 23.733 caracteres de
# material y se descartaba el 49%. Las seis menciones del Carnaval —una fiesta
# real, del 22 de febrero— caian ENTERAS en la mitad descartada, asi que ningun
# ajuste del prompt podia rescatarla. 40.000 caracteres son ~12.600 tokens, que
# caben de sobra en los modelos que se usan aqui.
PATRON_FICHA_MAX_CHARS = 40000


async def _extraer_ficha_con_llm(texto: str, localidad: dict, patron_nombre: str) -> dict:
    """
    Cuando celebra el pueblo y que otras fiestas tiene. SIEMPRE por LLM.

    Va aparte de `_extraer_con_llm` por un fallo medido el 2026-09-07: aquella
    es la Fuente 3, el fallback, y solo se ejecuta si Wikipedia y los buscadores
    fallan. Para Garrucha, Wikipedia respondio con confianza alta en 0 segundos,
    asi que al modelo no se le llego a preguntar y la ficha salio vacia
    —precisamente en el pueblo que motivo todo el cambio—.

    La identidad del patron la resuelve bien un infobox; CUANDO lo celebra el
    pueblo y que otras fiestas tiene, no: eso hay que leerlo. Por eso esta
    pregunta no es un fallback de nada.

    Devuelve siempre un dict con las tres claves, aunque vengan vacias: si
    faltase `fiestas_habituales`, la invalidacion de cache volveria a
    re-resolver esta localidad en cada ejecucion sin converger nunca.
    """
    vacia = {"celebra_dia": None, "celebra_mes": None, "fiestas_habituales": []}
    if not (texto or "").strip():
        return vacia

    from llm_processor.text_analyzer import llm_chat_json

    system_prompt = (
        "Eres una API estricta que cataloga TODAS las fiestas de un pueblo espanol.\n"
        "Responde SOLO con JSON:\n"
        '{"celebra_dia": numero o null, "celebra_mes": numero o null,\n'
        ' "fiestas_habituales": ["Tipo - Nombre, epoca (detalle)", ...]}\n'
        "\n"
        "CUANDO CELEBRA EL PUEBLO SUS PATRONALES\n"
        "`celebra_dia`/`celebra_mes` NO es la fecha del santoral: es cuando el\n"
        "pueblo las celebra de verdad, que suele desplazarse al verano o a un\n"
        "fin de semana. San Joaquin es el 26 de julio en el santoral, pero\n"
        "Garrucha lo celebra a mediados de agosto. Si el texto no lo dice,\n"
        "deja las dos a null; NO copies aqui la fecha liturgica.\n"
        "\n"
        "EL CATALOGO: BARRE POR TIPOS, UNO A UNO\n"
        "Recorre esta lista y por cada tipo mira si el texto menciona alguna\n"
        "en este pueblo. Si de un tipo no dice nada, SALTALO: la lista es una\n"
        "ayuda para no dejarte fiestas, no casillas que haya que rellenar.\n"
        "en este pueblo. Es un barrido, no un resumen: no te quedes en las dos\n"
        "mas famosas.\n"
        "\n"
        "CADA ENTRADA ES UNA SOLA FIESTA\n"
        "No juntes dos en una linea. Las Cruces de Mayo y la Noche de San\n"
        "Juan son fiestas distintas, en meses distintos: van en dos entradas\n"
        "o en ninguna. Y no inventes la fecha para que cuadren.\n"
        "\n"
        "UN PROGRAMA CULTURAL NO ES UNA FIESTA\n"
        "Si el texto describe una agenda municipal de actividades -talleres,\n"
        "aquagym, torneos, presentaciones de libros repartidos por semanas-,\n"
        "eso no es una fiesta y no va al catalogo. Una fiesta tiene nombre\n"
        "propio y la celebra el pueblo en unas fechas concretas.\n"
        "  - Patronales (en honor al patron o patrona)\n"
        "  - Fiestas mayores o fiestas de verano del pueblo\n"
        "  - Carnaval\n"
        "  - Semana Santa\n"
        "  - Romerias\n"
        "  - Ferias (ganado, artesania, gastronomia, medieval)\n"
        "  - Cruces de Mayo, San Juan, San Isidro y demas del calendario\n"
        "  - Fiestas de barrios, pedanias o aldeas del municipio\n"
        "  - Festivales o certamenes que se repitan cada anno\n"
        "\n"
        "FORMATO DE CADA ENTRADA\n"
        "\"Tipo - Nombre, epoca (detalle breve)\". Ejemplos:\n"
        '  "Patronales - San Joaquin, mediados de agosto (procesion y verbena)"\n'
        '  "Romeria - Virgen del Carmen, 16 de julio (procesion maritima)"\n'
        '  "Carnaval - Carnaval de Garrucha, febrero (desfile de comparsas)"\n'
        "La epoca puede ser un mes o una fecha; si el texto no la da, escribe\n"
        "el tipo y el nombre igualmente. Una fiesta sin fecha vale mas que una\n"
        "fiesta ausente: quien la busque despues ya encontrara cuando es.\n"
        "\n"
        "LIMITE\n"
        "Solo lo que el TEXTO respalde. No completes con conocimiento general\n"
        "ni supongas que un pueblo tiene carnaval porque casi todos lo tienen.\n"
        "Esto se pega al contexto de otros modelos: una fiesta inventada aqui\n"
        "contamina todo lo que venga despues. Lista vacia si no hay nada."
    )

    user_prompt = (
        f"PUEBLO: {localidad['nombre']}\n"
        f"PATRON/A: {patron_nombre or 'desconocido'}\n\n"
        f"TEXTO:\n{texto[:PATRON_FICHA_MAX_CHARS]}\n\n"
        "Cuando lo celebra el pueblo y que otras fiestas tiene. SOLO JSON:"
    )

    try:
        parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=PATRON_LLM_MAX_TOKENS)
    except Exception as e:
        logger.debug(f"  [PATRON/FICHA] {localidad.get('nombre')}: fallo el LLM ({e}).")
        return vacia
    if not isinstance(parsed, dict):
        return vacia

    dia = parsed.get("celebra_dia") if isinstance(parsed.get("celebra_dia"), int) else None
    mes = parsed.get("celebra_mes") if isinstance(parsed.get("celebra_mes"), int) else None
    if not (dia and mes and 1 <= dia <= 31 and 1 <= mes <= 12):
        dia, mes = None, None

    habituales = []
    for item in (parsed.get("fiestas_habituales") or [])[:14]:
        if isinstance(item, str) and 4 <= len(item.strip()) <= 120:
            habituales.append(item.strip())

    return {"celebra_dia": dia, "celebra_mes": mes, "fiestas_habituales": habituales}


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
        # Lo guardado antes de que existieran estas comprobaciones puede ser
        # basura: en la caché del 2026-08-25 había "Stmo" (el Cristo de Tobarra
        # decapitado en el punto de la abreviatura), "Santiago de Mora 2026" (el
        # nombre del pueblo con el año) y "Santísimo Cristo del Consuelo\nSevilla"
        # (una hermandad sevillana). Se vuelve a resolver en vez de arrastrarlo.
        # Y lo guardado antes del 2026-09-06 no trae `fiestas_habituales` ni la
        # fecha en que el pueblo celebra de verdad. Devolverlo tal cual dejaria
        # sin ficha justo a las 60 localidades ya resueltas —Garrucha entre
        # ellas—, que son las que motivaron el cambio. Se vuelven a resolver una
        # vez y quedan cacheadas con el esquema nuevo.
        completo = cacheado is None or (
            "fiestas_habituales" in cacheado
            and nombre_de_patron_creible(
                cacheado.get("nombre", ""), localidad.get("nombre", ""), municipio.get("nombre", "")
            )
        )
        if completo:
            return cacheado
        logger.info(
            f"  [PATRON] {localidad.get('nombre')}: se tira lo cacheado "
            f"({cacheado.get('nombre')!r}) y se vuelve a buscar."
        )

    resultado = None
    fuente = None
    # De dónde salió el patrón. "localidad" = de una fuente que trata de ESTE
    # pueblo; "municipio" = heredado del artículo del municipio, que es una
    # conjetura. Solo el primero sirve para descartar fiestas por el patrón: es
    # la diferencia entre saber el patrón del pueblo y suponerlo.
    ambito = "municipio"
    textos_acumulados = []

    # El núcleo que da nombre al municipio sí está descrito por el artículo del
    # municipio: para él no hay herencia que valga, es su propio artículo.
    es_nucleo_principal = bool(
        localidad.get("es_capital")
        or _clave_toponimo(localidad["nombre"]) == _clave_toponimo(municipio.get("nombre", ""))
    )

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"}
    connector = aiohttp.TCPConnector(limit=3, ssl=False)

    try:
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            # Fuente 1: Wikipedia. Se prueba primero el artículo propio de la
            # localidad y solo después el del municipio, y se anota cuál de los
            # dos dio el resultado.
            urls_wiki = []
            url_loc = (localidad.get("wikipedia_url") or "").strip()
            if url_loc and _wiki_es_de_la_localidad(url_loc, localidad["nombre"]):
                urls_wiki.append((url_loc, "localidad"))
            elif url_loc:
                logger.info(
                    f"  [PATRON] {localidad['nombre']}: se descarta '{url_loc}', "
                    f"el artículo no es de esta localidad."
                )
            # El artículo del municipio SOLO se lee para el núcleo que le da
            # nombre, porque entonces es su propio artículo. Para una pedanía no
            # se toca: el patrón de la villa no es el suyo, y heredarlo era la
            # causa de que siete de nueve localidades de Amurrio saliesen con
            # "San Roque". Si su artículo no dice nada, se pasa a buscadores.
            url_mun = (municipio.get("wikipedia_url") or "").strip()
            if es_nucleo_principal and url_mun and url_mun not in [u for u, _ in urls_wiki]:
                urls_wiki.append((url_mun, "localidad"))

            # Todo lo que hay en `urls_wiki` es, a estas alturas, un artículo de
            # la propia localidad: o el suyo verificado, o el del municipio
            # cuando la localidad ES el municipio.
            for url, _ in urls_wiki:
                filas, texto = await _descargar_wikipedia(session, url)
                textos_acumulados.append(texto)
                resultado = _extraer_de_infobox(filas) or extraer_patron_de_texto(texto)
                resultado = _validar_patron(resultado, localidad, municipio, "wikipedia")
                if resultado:
                    fuente = "wikipedia"
                    ambito = "localidad"
                    break

            # Fuente 2: buscadores. `_buscar_en_web` ya filtra los snippets a los
            # que nombran a la localidad, así que lo que salga de ahí es suyo.
            if not resultado:
                texto_web = await _buscar_en_web(session, localidad, municipio)
                textos_acumulados.append(texto_web)
                resultado = extraer_patron_de_texto(texto_web)
                resultado = _validar_patron(resultado, localidad, municipio, "busqueda")
                if resultado:
                    fuente = "busqueda"
                    ambito = "localidad"

            # La FICHA se pide siempre, la resuelva quien la resuelva. Si el
            # patron vino de Wikipedia o de un buscador, el modelo no ha
            # opinado todavia y faltan la fecha real de celebracion y las
            # fiestas habituales, que es lo unico que hace util a la ficha.
            # Medido el 2026-09-07: Garrucha se resolvio por Wikipedia en 0 s
            # con el 26 de julio del santoral, el LLM no llego a entrar y la
            # ficha habria salido vacia en el pueblo que motivo el cambio.
            if resultado and "fiestas_habituales" not in resultado:
                # El barrido de calendario se hace SIEMPRE, aunque Wikipedia ya
                # hubiera resuelto el patron. Un infobox identifica al santo pero
                # no dice cuando lo celebra el pueblo ni que otras fiestas tiene,
                # y las consultas patronales tampoco: por eso los catalogos
                # salian de dos o tres entradas. Las busquedas van cacheadas, asi
                # que repetir localidad no cuesta.
                textos_acumulados.append(
                    await _buscar_en_web(session, localidad, municipio, calendario=True)
                )
                # El barrido de calendario va DELANTE. Es el material que habla
                # de carnavales, romerias y ferias; el patronal repite sobre el
                # santo. Puesto detras se lo comia el recorte antes de que el
                # modelo lo viera.
                texto_ficha = "\n".join(
                    t for t in reversed(textos_acumulados) if t
                ).strip()
                resultado.update(
                    await _extraer_ficha_con_llm(
                        texto_ficha, localidad, resultado.get("nombre", "")
                    )
                )

        # Fuente 3 (fallback): LLM sobre todo lo acumulado. Desde que el artículo
        # del municipio ya no se lee para las pedanías, todo lo acumulado aquí es
        # de la propia localidad —su artículo y los snippets filtrados por su
        # nombre—, así que lo que salga es suyo y no una herencia.
        if not resultado:
            texto_total = "\n".join(t for t in textos_acumulados if t).strip()
            if texto_total:
                resultado = await _extraer_con_llm(texto_total, localidad)
                resultado = _validar_patron(resultado, localidad, municipio, "llm")
                if resultado:
                    fuente = "llm"
                    ambito = "localidad"

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
        # Y quitar la cola de titular que arrastra la ruta de buscadores.
        resultado["nombre"] = capitalizar_advocacion(recortar_coletilla_del_santo(resultado["nombre"]))

    final = _resolver_fecha(resultado, fuente, ambito) if resultado else None
    if final:
        fecha_txt = f"{final['dia']} de {_NOMBRE_MES[final['mes']]}" if final["mes"] else "fecha desconocida"
        sello = "propio" if final["ambito"] == "localidad" else "HEREDADO del municipio"
        logger.info(
            f"  [PATRON] {localidad['nombre']}: {final['nombre']} ({fecha_txt}) "
            f"[{final['fuente']}, confianza {final['confianza']}, {sello}]"
        )
    else:
        logger.info(f"  [PATRON] No se encontró patrón para {localidad['nombre']}.")

    await _cache.set(lugar_id, final)
    return final


# ──────────────────────────────────────────────────
# INTEGRACIÓN CON LAS FIESTAS EXTRAÍDAS (funciones puras)
# ──────────────────────────────────────────────────

def fecha_del_patron(patron: dict | None, anno: int) -> date | None:
    """
    Dia del patron en el anno objetivo, o None si no hay fecha fiable.

    Prefiere la fecha en que el PUEBLO celebra sobre la del santoral. La
    distincion no es academica: en la cache del 2026-09-06, Garrucha figuraba
    como "San Joaquin, dia 26, mes 7" —la liturgica— cuando el pueblo lo celebra
    del 14 al 18 de agosto. Como `_avales_de_patronal` usa esta fecha para su
    primer criterio de desempate, ninguna ficha lo cumplia, el desempate cayo al
    nombre, y una ficha de Cuaresma mal etiquetada como "Fiestas Patronales de
    San Joaquin" expulso a la Virgen del Carmen del 16 de julio y a las
    Patronales del 4 de septiembre. Dos fiestas reales perdidas por comparar
    contra el santoral.

    Si es 29 de febrero y el anno no es bisiesto, cae a 28 de febrero.
    """
    if not patron:
        return None
    for clave_dia, clave_mes in (("celebra_dia", "celebra_mes"), ("dia", "mes")):
        dia, mes = patron.get(clave_dia), patron.get(clave_mes)
        if not (dia and mes):
            continue
        try:
            return date(anno, mes, dia)
        except ValueError:
            if mes == 2 and dia == 29:
                try:
                    return date(anno, 2, 28)
                except ValueError:
                    pass
    return None


def ficha_del_pueblo(patron: dict | None) -> str:
    """
    Lo que se sabe del calendario festivo del pueblo, como TEXTO para el contexto.

    No la consume ninguna regla: se pega al contexto de discovery y del juez de
    pertenencia para que los modelos sepan que fiestas encajan en este pueblo y
    cuales son poco probables. Deliberadamente escrita como hipotesis y no como
    hecho: la escribio un modelo y puede equivocarse, asi que dice expresamente
    que los documentos mandan sobre ella. Cambiar una falsedad del codigo por una
    falsedad del contexto no seria progreso.

    Devuelve "" si no hay nada que decir, para no meter ruido.
    """
    if not patron:
        return ""
    lineas = []
    nombre = (patron.get("nombre") or "").strip()
    if nombre:
        lineas.append(f"  Patron/a: {nombre}")
    dia, mes = patron.get("dia"), patron.get("mes")
    if dia and mes:
        lineas.append(f"  Festividad en el santoral: {dia}/{mes}")
    cdia, cmes = patron.get("celebra_dia"), patron.get("celebra_mes")
    if cdia and cmes:
        lineas.append(
            f"  El pueblo lo celebra hacia el {cdia}/{cmes} (esta manda sobre la del santoral)"
        )
    habituales = patron.get("fiestas_habituales") or []
    if habituales:
        lineas.append("  Fiestas que este pueblo suele tener:")
        lineas.extend(f"    - {h}" for h in habituales)
    if not lineas:
        return ""
    return (
        "LO QUE SE SABE DE ESTE PUEBLO (orientacion, NO es la verdad)\n"
        + "\n".join(lineas)
        + "\n  Es una hipotesis armada desde la web y puede estar equivocada o"
          " incompleta.\n  Si un documento la contradice, MANDA EL DOCUMENTO."
          " Sirve para juzgar que encaja en este pueblo y que es poco\n"
          "  probable, no para dar nada por cierto ni para inventar fiestas\n"
          "  que los documentos no respalden.\n"
    )


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
    Marca las fiestas que incluyen el día del patrón y, si NINGUNA ficha es ya la
    fiesta de ese patrón, añade el registro estimado.

    "Ser la fiesta del patrón" no es lo mismo que "caer en el día del patrón".
    Cuando se confundían las dos cosas, cualquier pueblo que traslade sus
    patronales salía con la fiesta dos veces: el 2026-08-26 Tobarra llevaba su
    Cristo de la Antigua del 9 al 17 de agosto —extraído, con programa— y encima
    un "Fiestas de Stmo. Cristo de la Antigua (estimada)" el 14 de septiembre,
    que es el mismo Cristo. Igual en Sierra con San Francisco. La estimación
    existe para el pueblo del que no se ha encontrado NADA, no para duplicar lo
    que ya se encontró.
    """
    fecha = fecha_del_patron(patron, anno)
    if not fecha:
        return fiestas

    from llm_processor.text_analyzer import es_la_fiesta_del_patron

    fecha_iso = fecha.isoformat()
    cubierto = False
    ya_esta = False
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
        if f.get("origen") != "santo_patron" and es_la_fiesta_del_patron(f, patron, fecha):
            ya_esta = True
            f.setdefault("patron", {
                "nombre": patron["nombre"],
                "dia": patron["dia"],
                "mes": patron["mes"],
                "fuente": patron.get("fuente"),
            })

    if not cubierto and ya_esta:
        logger.info(
            f"  [PATRON] {localidad['nombre']}: el día de {patron['nombre']} ({fecha_iso}) "
            f"no cae dentro de ninguna ficha, pero la fiesta del patrón ya está extraída "
            f"(trasladada). No se estima nada."
        )
    elif not cubierto:
        fiestas.append(crear_fiesta_estimada(patron, fecha, localidad))
        logger.info(
            f"  [PATRON] Añadida fiesta estimada de {patron['nombre']} ({fecha_iso}) "
            f"para {localidad['nombre']} (día del patrón no cubierto)."
        )

    return fiestas

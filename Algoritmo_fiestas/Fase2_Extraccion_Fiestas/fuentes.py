from functools import lru_cache
"""
Modelo de fuentes de información — Fase 2 v3.

Cada pieza de texto recopilada se representa como un "documento" etiquetado
con su fuente, para que el RAG y el LLM sepan cuál es su fiabilidad.

Jerarquía (de más a menos fiable):
  1. web_localidad      Web oficial de la localidad
  2. web_municipio      Web oficial del municipio
  3. rrss_localidad     Red social oficial de la localidad (sufijo :instagram/:facebook/:twitter)
  4. rrss_municipio     Red social oficial del municipio
  5. busqueda_web       Resultados de buscador (la menos fiable)
"""

import re
from urllib.parse import urlparse
import unicodedata

# ──────────────────────────────────────────────────
# CONSTANTES DE FUENTE
# ──────────────────────────────────────────────────

FUENTE_WEB_LOCALIDAD = "web_localidad"
FUENTE_WEB_MUNICIPIO = "web_municipio"
FUENTE_RRSS_LOCALIDAD = "rrss_localidad"   # se usa con sufijo: "rrss_localidad:instagram"
FUENTE_RRSS_MUNICIPIO = "rrss_municipio"
FUENTE_PRENSA_REGIONAL = "prensa_regional"
FUENTE_BUSQUEDA = "busqueda_web"
FUENTE_HISTORICO = "busqueda_web_historico"

PRIORIDAD_FUENTE = {
    FUENTE_WEB_LOCALIDAD: 1,
    FUENTE_WEB_MUNICIPIO: 2,
    FUENTE_RRSS_LOCALIDAD: 3,
    FUENTE_RRSS_MUNICIPIO: 4,
    FUENTE_PRENSA_REGIONAL: 5,
    FUENTE_BUSQUEDA: 6,
    FUENTE_HISTORICO: 7,
}

_ROTULOS = {
    FUENTE_WEB_LOCALIDAD: "WEB OFICIAL DE LA LOCALIDAD (fiabilidad MÁXIMA)",
    FUENTE_WEB_MUNICIPIO: "WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA)",
    FUENTE_RRSS_LOCALIDAD: "RED SOCIAL OFICIAL DE LA LOCALIDAD (fiabilidad ALTA)",
    FUENTE_RRSS_MUNICIPIO: "RED SOCIAL OFICIAL DEL MUNICIPIO (fiabilidad ALTA)",
    FUENTE_PRENSA_REGIONAL: "PRENSA REGIONAL / MEDIOS DE COMUNICACIÓN (fiabilidad MEDIA)",
    FUENTE_BUSQUEDA: "RESULTADOS DE BUSCADOR (fiabilidad BAJA — verificar)",
    FUENTE_HISTORICO: "RESULTADOS DE BUSCADOR AÑO ANTERIOR (fiabilidad MUY BAJA — histórico referencial)",
}


def fuente_base(fuente: str) -> str:
    """'rrss_localidad:instagram' → 'rrss_localidad'."""
    if not isinstance(fuente, str):
        return ""
    return fuente.split(":")[0]


def prioridad_fuente(fuente: str) -> int:
    return PRIORIDAD_FUENTE.get(fuente_base(fuente), 9)


def es_fuente_valida(fuente: str) -> bool:
    return fuente_base(fuente) in PRIORIDAD_FUENTE


def es_fuente_oficial(fuente: str) -> bool:
    """Oficial = webs y redes sociales oficiales (no prensa ni resultados de buscador)."""
    base = fuente_base(fuente)
    return base in PRIORIDAD_FUENTE and base not in (FUENTE_BUSQUEDA, FUENTE_PRENSA_REGIONAL)


# ──────────────────────────────────────────────────
# MEDIOS DE PRENSA POR PROVINCIA
# ──────────────────────────────────────────────────

MEDIOS_PRENSA_POR_PROVINCIA: dict[str, list[str]] = {
    "01": ["radiollodio.com", "elcorreo.com", "noticiasdealava.com"],
    "02": ["eldigitaldealbacete.com", "latribunadealbacete.es"],
    "03": ["diarioinformacion.com", "alicanteplaza.es", "elcorreo.com"],
    "04": ["lavozdealmeria.com", "elalmeria.es"],
    "05": ["diariodeavila.es", "avilared.com"],
    "06": ["hoy.es", "lacronicabadajoz.com"],
    "07": ["diariodemallorca.es", "ultimahora.es"],
    "08": ["lavanguardia.com", "elperiodico.com"],
    "09": ["diariodeburgos.es", "burgosconecta.es"],
    "10": ["elperiodicoextremadura.com", "hoy.es"],
    "11": ["diariodecadiz.es", "lavozdigital.es"],
    "12": ["elperiodicomediterraneo.com", "castellonplaza.com"],
    "13": ["lanzadigital.com", "latribunadeciudadreal.es"],
    "14": ["diariocordoba.com", "eldiadecordoba.es"],
    "15": ["lavozdegalicia.es", "elidealgallego.com"],
    "16": ["lasnoticiasdecuenca.es", "eldiadigital.es"],
    "17": ["diaridegirona.cat", "elpuntavui.cat"],
    "18": ["ideal.es", "granadahoy.com"],
    "19": ["meguada.com", "nuevaalcarria.com"],
    "20": ["diariovasco.com", "noticiasdegipuzkoa.eus"],
    "21": ["huelvainformacion.es", "huelvayas.es"],
    "22": ["diariodelaltoaragon.es", "heraldo.es"],
    "23": ["diariojaen.es", "ideal.es"],
    "24": ["lanuevacronica.com", "diariodeleon.es"],
    "25": ["segre.com", "lamanyana.cat"],
    "26": ["larioja.com", "nuevecuatrouno.com"],
    "27": ["elprogreso.es", "lavozdegalicia.es"],
    "28": ["telemadrid.es", "elpais.com", "elmundo.es"],
    "29": ["diariosur.es", "malagahoy.es"],
    "30": ["laopiniondemurcia.es", "laverdad.es"],
    "31": ["diariodenavarra.es", "noticiasdenavarra.com"],
    "32": ["laregion.es", "lavozdegalicia.es"],
    "33": ["lne.es", "elcomercio.es"],
    "34": ["elnortedecastilla.es", "diariopalentino.es"],
    "35": ["laprovincia.es", "canarias7.es"],
    "36": ["farodevigo.es", "diariodedontevedra.es"],
    "37": ["lagacetadesalamanca.es", "salamancartvaldia.es"],
    "38": ["eldia.es", "diariodeavisos.elespanol.com"],
    "39": ["eldiariomontanes.es", "eldiariocantabria.es"],
    "40": ["eladelantado.com", "elnortedecastilla.es"],
    "41": ["diariodesevilla.es", "abcdesevilla.es"],
    "42": ["desdesoria.es", "heraldodiariodesoria.elmundo.es"],
    "43": ["diaridetarragona.com", "elpuntavui.cat"],
    "44": ["diariodeteruel.es", "heraldo.es"],
    "45": ["latribunadetoledo.es", "encastillalamancha.es"],
    "46": ["levante-emv.com", "lasprovincias.es"],
    "47": ["elnortedecastilla.es", "tribunavalladolid.com"],
    "48": ["deia.eus", "elcorreo.com"],
    "49": ["laopiniondezamora.es", "elnortedecastilla.es"],
    "50": ["heraldo.es", "elperiodicodearagon.com"],
    "51": ["elfarodeceuta.es", "elpueblodeceuta.es"],
    "52": ["elfarodemelilla.es", "melillahoy.es"],
}

_PROVINCIA_NOMBRE_A_CODIGO: dict[str, str] = {
    "alava": "01", "araba": "01", "araba/alava": "01", "alava/araba": "01",
    "albacete": "02",
    "alicante": "03", "alacant": "03", "alicante/alacant": "03",
    "almeria": "04",
    "avila": "05",
    "badajoz": "06",
    "baleares": "07", "balears": "07", "illes balears": "07",
    "barcelona": "08",
    "burgos": "09",
    "caceres": "10",
    "cadiz": "11",
    "castellon": "12", "castello": "12", "castellon/castello": "12",
    "ciudad real": "13",
    "cordoba": "14",
    "coruna": "15", "a coruna": "15", "la coruna": "15",
    "cuenca": "16",
    "girona": "17", "gerona": "17",
    "granada": "18",
    "guadalajara": "19",
    "gipuzkoa": "20", "guipuzcoa": "20",
    "huelva": "21",
    "huesca": "22",
    "jaen": "23",
    "leon": "24",
    "lleida": "25", "lerida": "25",
    "la rioja": "26", "rioja": "26",
    "lugo": "27",
    "madrid": "28",
    "malaga": "29",
    "murcia": "30",
    "navarra": "31", "nafarroa": "31",
    "ourense": "32", "orense": "32",
    "asturias": "33",
    "palencia": "34",
    "las palmas": "35",
    "pontevedra": "36",
    "salamanca": "37",
    "santa cruz de tenerife": "38", "tenerife": "38",
    "cantabria": "39",
    "segovia": "40",
    "sevilla": "41",
    "soria": "42",
    "tarragona": "43",
    "teruel": "44",
    "toledo": "45",
    "valencia": "46", "valencia/valencia": "46",
    "valladolid": "47",
    "bizkaia": "48", "vizcaya": "48",
    "zamora": "49",
    "zaragoza": "50",
    "ceuta": "51",
    "melilla": "52",
}


def _normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = str(texto).lower().strip()
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def get_codigo_provincia(lugar_id: str | int | None) -> str | None:
    """
    Extrae el código INE de provincia (2 dígitos) a partir del lugar_id (e.g. '01004000101', '1004')
    o de un nombre/código de provincia.
    """
    if lugar_id is None:
        return None
    val_str = str(lugar_id).strip()
    if not val_str:
        return None

    # Si val_str contiene solo dígitos, gestionar el formateo/padding INE
    if val_str.isdigit():
        num_str = val_str
        if len(num_str) == 1:
            num_str = num_str.zfill(2)
        elif len(num_str) == 4:
            num_str = num_str.zfill(5)
        elif len(num_str) == 10:
            num_str = num_str.zfill(11)

        if len(num_str) >= 2:
            code = num_str[:2]
            if code in MEDIOS_PRENSA_POR_PROVINCIA or (1 <= int(code) <= 52):
                return code

    # Si empieza con dígitos (por si tiene caracteres no numéricos tras los dígitos)
    if len(val_str) >= 2 and val_str[:2].isdigit():
        code = val_str[:2]
        if code in MEDIOS_PRENSA_POR_PROVINCIA or (1 <= int(code) <= 52):
            return code

    norm = _normalizar_texto(val_str)
    if norm in _PROVINCIA_NOMBRE_A_CODIGO:
        return _PROVINCIA_NOMBRE_A_CODIGO[norm]

    # Si es una clave registrada directamente o por nombre normalizado
    if val_str in MEDIOS_PRENSA_POR_PROVINCIA:
        return val_str

    if norm in MEDIOS_PRENSA_POR_PROVINCIA:
        return norm

    return None


def get_medios_prensa_por_provincia(lugar_id_o_provincia: str | None) -> list[str]:
    """
    Obtiene la lista de dominios de prensa regional para una provincia dada su ID,
    código INE o nombre.
    """
    if not lugar_id_o_provincia:
        return []

    val_str = str(lugar_id_o_provincia).strip()
    if not val_str:
        return []

    # 1. Búsqueda directa
    if val_str in MEDIOS_PRENSA_POR_PROVINCIA:
        return list(MEDIOS_PRENSA_POR_PROVINCIA[val_str])

    # 2. Por código de provincia
    codigo = get_codigo_provincia(val_str)
    if codigo and codigo in MEDIOS_PRENSA_POR_PROVINCIA:
        return list(MEDIOS_PRENSA_POR_PROVINCIA[codigo])

    # 3. Por nombre normalizado
    norm = _normalizar_texto(val_str)
    if norm in MEDIOS_PRENSA_POR_PROVINCIA:
        return list(MEDIOS_PRENSA_POR_PROVINCIA[norm])

    if norm in _PROVINCIA_NOMBRE_A_CODIGO:
        code = _PROVINCIA_NOMBRE_A_CODIGO[norm]
        if code in MEDIOS_PRENSA_POR_PROVINCIA:
            return list(MEDIOS_PRENSA_POR_PROVINCIA[code])

    return []


def register_provincia_medios(codigo_o_nombre: str, medios: list[str]) -> None:
    """
    Registra o actualiza dinámicamente los medios de prensa para una provincia.
    Soporta registro por código INE (e.g. "28", "01", "1") o por nombre ("madrid", "Álava").
    Actualiza sincrónicamente tanto la clave de código INE de 2 dígitos como las claves por nombre.
    """
    if not codigo_o_nombre:
        return
    key = str(codigo_o_nombre).strip()
    medios_list = list(medios)

    MEDIOS_PRENSA_POR_PROVINCIA[key] = medios_list
    norm = _normalizar_texto(key)
    if norm:
        MEDIOS_PRENSA_POR_PROVINCIA[norm] = medios_list

    code2 = get_codigo_provincia(key)
    if code2:
        MEDIOS_PRENSA_POR_PROVINCIA[code2] = medios_list
        for nombre_key, c in _PROVINCIA_NOMBRE_A_CODIGO.items():
            if c == code2:
                MEDIOS_PRENSA_POR_PROVINCIA[nombre_key] = medios_list

    if key.isdigit() and len(key) == 1:
        c2 = f"{int(key):02d}"
        MEDIOS_PRENSA_POR_PROVINCIA[c2] = medios_list



def rotulo_fuente(fuente: str, es_calendario: bool = False) -> str:
    """Rótulo de sección para el prompt del LLM."""
    base = fuente_base(fuente)
    rotulo = _ROTULOS.get(base, "FUENTE DESCONOCIDA")
    if ":" in (fuente or ""):
        red = fuente.split(":", 1)[1]
        rotulo = rotulo.replace("RED SOCIAL OFICIAL", f"RED SOCIAL OFICIAL ({red.upper()})")
    if es_calendario:
        rotulo += " [PÁGINA DE CALENDARIO LABORAL/ESCOLAR — NO es evidencia de celebración]"
    return rotulo


# ──────────────────────────────────────────────────
# DETECCIÓN DE PÁGINAS DE CALENDARIO LABORAL/ESCOLAR
# ──────────────────────────────────────────────────

_RE_CALENDARIO = re.compile(
    r"calendario\s+(laboral|escolar)"
    r"|dias?\s+festivos"
    r"|festivos\s+locales"
    r"|dias?\s+no\s+lectivos?"
    r"|calendario\s+de\s+dias\s+inhabiles",
    re.IGNORECASE,
)


def detectar_es_calendario(url: str, texto_inicial: str) -> bool:
    """Detecta si un documento es una página de calendario laboral/escolar."""
    # En URLs los separadores suelen ser guiones o barras
    muestra = re.sub(r"[-_/.]", " ", url or "") + " " + (texto_inicial or "")[:500]
    return bool(_RE_CALENDARIO.search(muestra))


# ──────────────────────────────────────────────────
# DOCUMENTO
# ──────────────────────────────────────────────────

def crear_documento(
    fuente: str,
    url: str,
    texto: str,
    tipo: str = "pagina",
    score_spider: int = 0,
    rank_spider: int | None = None,
) -> dict:
    """
    Crea un documento etiquetado. tipo ∈ {pagina, pdf, cartel, rrss, snippets}.
    es_calendario se autodetecta a partir de la URL y el inicio del texto.

    `score_spider` / `rank_spider` conservan la puntuación con la que la araña
    ordenó la página de la que procede el documento. La araña ya evalúa
    relevancia festiva y temporal (año objetivo +350, años anteriores -300,
    evento suelto -350) y hasta ahora ese trabajo se perdía al crear el
    documento, de modo que el RAG reordenaba desde cero.
    """
    return {
        "fuente": fuente,
        "url": url or "",
        "texto": texto or "",
        "tipo": tipo,
        "es_calendario": detectar_es_calendario(url, texto),
        "score_spider": int(score_spider or 0),
        "rank_spider": rank_spider,
    }


# ──────────────────────────────────────────────────
# CONTEXTUAL RETRIEVAL & LOCALITY FILTERING
# ──────────────────────────────────────────────────

try:
    from config import (
        RELEVANCIA_DOC_MIN_MENCIONES,
        RELEVANCIA_TITULO_CHARS,
        RELEVANCIA_ENUM_VENTANA,
        RELEVANCIA_ENUM_MIN_HERMANAS,
    )
except ImportError:  # utilizable en solitario
    RELEVANCIA_DOC_MIN_MENCIONES = 3
    RELEVANCIA_TITULO_CHARS = 250
    RELEVANCIA_ENUM_VENTANA = 140
    RELEVANCIA_ENUM_MIN_HERMANAS = 2


@lru_cache(maxsize=1024)
def normalize_text(text: str) -> str:
    """Convierte a minúsculas y elimina tildes."""
    text = text.lower()
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

def _aviso_de_anno(doc: dict) -> str:
    """
    Aviso de que el documento es de otro año, para la cabecera del fragmento.

    El modelo no puede saber de cuándo es lo que lee, y de ahí salían fechas
    equivocadas con toda la seguridad del mundo: el 2026-08-27 Aranda de Duero
    dató sus fiestas de 2026 en un solo día, el 15 de septiembre, porque el PDF
    que tenía delante era el programa de 2025 y nada se lo decía.

    No se descarta el documento —los patrones no cambian y las fechas se
    repiten—, se avisa de lo único que el texto no dice de sí mismo.
    """
    anno_doc = doc.get("anno_documento")
    anno_obj = doc.get("anno_objetivo")
    if not (anno_doc and anno_obj) or anno_doc == anno_obj:
        return ""
    return (f" | AVISO: este documento es de {anno_doc}, no de {anno_obj}. "
            f"Sirve de referencia, pero NO tomes de aquí las fechas de {anno_obj}")


def generar_cabecera_chunk(doc: dict, municipio_nombre: str, localidad_nombre: str) -> str:
    """Genera una cabecera de contexto para prepender al chunk antes del embedding."""
    fuente = doc.get("fuente", "busqueda_web")
    url = doc.get("url", "sin url")
    aviso_anno = _aviso_de_anno(doc)
    if aviso_anno:
        # El aviso va antes del cierre del corchete de la cabecera.
        base = _cabecera_base(doc, fuente, url, municipio_nombre, localidad_nombre)
        return base[:-1] + aviso_anno + "]"
    return _cabecera_base(doc, fuente, url, municipio_nombre, localidad_nombre)


def _cabecera_base(doc: dict, fuente: str, url: str,
                   municipio_nombre: str, localidad_nombre: str) -> str:

    if fuente_base(fuente) == FUENTE_WEB_LOCALIDAD:
        return f"[FUENTE: Web oficial de {localidad_nombre} ({url}) | AVISO: Este contenido es específico de esta localidad]"
    elif fuente_base(fuente) == FUENTE_WEB_MUNICIPIO:
        if municipio_nombre.lower() == localidad_nombre.lower():
            return f"[FUENTE: Web oficial del municipio de {municipio_nombre} ({url})]"
        else:
            return f"[FUENTE: Web oficial del municipio de {municipio_nombre} ({url}) | AVISO: Este contenido pertenece al MUNICIPIO en general, NO específicamente a la pedanía {localidad_nombre}]"
    elif fuente_base(fuente).startswith(FUENTE_RRSS_LOCALIDAD):
        return f"[FUENTE: Red social de {localidad_nombre} ({url}) | AVISO: Este contenido es específico de esta localidad]"
    elif fuente_base(fuente).startswith(FUENTE_RRSS_MUNICIPIO):
        if municipio_nombre.lower() != localidad_nombre.lower():
            return f"[FUENTE: Red social del municipio de {municipio_nombre} ({url}) | AVISO: Este contenido pertenece al MUNICIPIO en general, NO específicamente a la pedanía {localidad_nombre}]"
        return f"[FUENTE: Red social del municipio de {municipio_nombre} ({url})]"
    else:
        return f"[FUENTE: Búsqueda web / Externa ({url})]"

_RE_ARTICULO_INICIAL = re.compile(r"^(el|la|los|las|lo)\s+(.+)$")


def _patron_de_nombre(nombre: str) -> str | None:
    """
    Expresión que reconoce un topónimo, incluida su forma invertida.

    El INE y casi todo lo administrativo escriben los nombres con artículo al
    revés: "Parra, La", "Roda, La", "Aldea del Obispo, La", y en las URLs
    "parra-la" o "parra_(la)". Buscando solo "La Parra" esas fuentes se daban
    por AJENAS. Medido el 2026-09-04: a La Parra (Badajoz) se le descartaron
    documentos que SÍ eran suyos —`calendariosnacionales.com/.../badajoz/parra-la/`
    y `calendarios-laborales.es/laboral-parra_(la)-2026-ba`— mientras el contexto
    se llenaba con el La Parra de Ávila. Afecta a 1.786 lugares del dataset, el
    18% del total.
    """
    n = normalize_text(nombre or "").strip()
    if not n:
        return None
    directo = rf"(?<!\w){re.escape(n)}(?!\w)"
    m = _RE_ARTICULO_INICIAL.match(n)
    if not m:
        return directo
    articulo, resto = m.group(1), m.group(2)
    # "parra" + cualquier separador que no sea letra + "la": cubre la coma, el
    # paréntesis, el guion y el subrayado de las URLs.
    invertido = rf"(?<!\w){re.escape(resto)}\W{{1,3}}{re.escape(articulo)}(?!\w)"
    return f"(?:{directo}|{invertido})"


def _menciones(texto_norm: str, nombre: str) -> list[int]:
    """Posiciones en que `nombre` aparece como palabra completa en texto ya normalizado.

    El `in` de toda la vida era una subcadena: "Aloria" casaba dentro de
    "Caloria" y, peor, cualquier nombre corto de aldea casaba dentro de un
    apellido o de un topónimo mayor. Con frontera de palabra una mención es una
    mención.

    Cuenta también la forma invertida del INE —"Parra, La"—; ver `_patron_de_nombre`.
    """
    patron = _patron_de_nombre(nombre)
    if not patron:
        return []
    return [m.start() for m in re.finditer(patron, texto_norm)]


def _mencion_en_enumeracion(
    texto_norm: str,
    posicion: int,
    nombres_hermanas: list[str],
    ventana: int = RELEVANCIA_ENUM_VENTANA,
    min_hermanas: int = RELEVANCIA_ENUM_MIN_HERMANAS,
) -> bool:
    """True si alrededor de esa mención se nombra también a varias hermanas.

    Es el caso de Amurrio que rompía todo: "La ciudadanía del Valle de Arrastaria
    (Aloria, Artomaña, Tertanga y Delika), perteneciente a Amurrio, honra a su
    patrona...". Ahí "Aloria" no indica que la página trate de Aloria; indica que
    la página enumera las pedanías del municipio. Tratar esa mención como prueba
    de pertenencia es lo que hacía que el programa de fiestas de Amurrio se
    copiase a las cinco aldeas.
    """
    ini = max(0, posicion - ventana)
    fin = posicion + ventana
    entorno = texto_norm[ini:fin]
    distintas = sum(1 for h in nombres_hermanas if _menciones(entorno, h))
    return distintas >= min_hermanas


def _menciones_significativas(
    texto_norm: str, localidad_nombre: str, nombres_hermanas: list[str]
) -> int:
    """Menciones de la localidad que NO son parte de una enumeración de pedanías."""
    return sum(
        1
        for pos in _menciones(texto_norm, localidad_nombre)
        if not _mencion_en_enumeracion(texto_norm, pos, nombres_hermanas)
    )


def _trata_sobre(texto_norm: str, url: str, nombre: str) -> bool:
    """El documento va DE esta localidad: la nombra en la URL o en su encabezado."""
    if _menciones(normalize_text(url or ""), nombre):
        return True
    return bool(_menciones(texto_norm[:RELEVANCIA_TITULO_CHARS], nombre))


def clasificar_relevancia_chunk(chunk_text: str, localidad_nombre: str, nombres_hermanas: list[str]) -> str | None:
    """
    Evalúa si un texto genérico de municipio menciona la pedanía o a sus hermanas.
    Devuelve:
    - 'DIRECTA': si menciona la localidad objetivo por su nombre completo y esa
      mención no es parte de una enumeración de pedanías hermanas.
    - None (descarte): si menciona otra pedanía hermana explícitamente y NO la objetivo.
    - 'GENERAL': si no menciona a ninguna de forma clara, o si solo la nombra
      dentro de una lista de aldeas del municipio.

    A escala de chunk (~1.200 chars) una mención suelta sí es informativa: si el
    texto que rodea a un programa de actos nombra al pueblo, lo normal es que el
    programa sea suyo. Lo que ya no se acepta es la mención de listado.
    """
    text_norm = normalize_text(chunk_text)
    hermanas = [h for h in (nombres_hermanas or []) if h]

    posiciones = _menciones(text_norm, localidad_nombre)
    if posiciones:
        if any(
            not _mencion_en_enumeracion(text_norm, pos, hermanas) for pos in posiciones
        ):
            return "DIRECTA"
        return "GENERAL"  # solo aparece dentro de una enumeración de pedanías

    for hermana in hermanas:
        if _menciones(text_norm, hermana):
            # Menciona a otra pedanía hermana y no a la objetivo
            return None

    return "GENERAL"


def misma_web(a: str, b: str) -> bool:
    """
    ¿Dos URLs apuntan al mismo sitio?

    Comparadas como cadenas, no: Fase 1 guarda la web de unas localidades como
    "http://www.tobarra.es/" y la del municipio como "https://www.tobarra.es".
    Medido el 2026-08-23, eso hacía que Cordovilla y Los Mardos volvieran a
    rastrear entero el sitio del municipio —26 segundos cada una— para acabar
    con las mismas páginas que ya estaban en la caché municipal.
    """
    def clave(u: str) -> str:
        u = (u or "").strip().lower()
        u = re.sub(r"^https?://", "", u)
        u = re.sub(r"^www\.", "", u)
        return u.rstrip("/")

    ka, kb = clave(a), clave(b)
    return bool(ka) and ka == kb


_PREFIJOS_INSTITUCIONALES = (
    "ayuntamientode", "ayuntamiento", "aytode", "ayto",
    "concejode", "concejo", "villade", "villa", "turismode", "turismo",
)


def web_es_de_este_lugar(url: str, localidad_nombre: str, municipio_nombre: str) -> bool:
    """
    ¿El dominio corresponde a esta localidad o a su municipio?

    Fase 1 rellena `sitio_web` como puede y falla mucho: medido el 2026-08-23
    sobre el dataset entero, de 564 localidades con web "propia" 495 apuntaban a
    otro sitio. No a webs inútiles, a webs de OTROS: Oleta (Aramayona) tenía la
    de Donostia, Artaza la de Vitoria-Gasteiz, Bikuña la de un partido político y
    Fresneda la de EITB. Rastrearlas mete el pueblo equivocado en el corpus, que
    es de donde salían los homónimos.

    Se compara la etiqueta principal del dominio con el nombre de la localidad y
    con el del municipio, admitiendo los prefijos institucionales al uso
    ("aytosinovas" vale para Sinovas). Se exige igualdad y no contención: la web
    de "Elche de la Sierra" contiene "sierra" y no es la de la pedanía Sierra.
    """
    if not url:
        return False
    u = url if url.startswith("http") else "http://" + url
    host = re.sub(r"^www\.", "", urlparse(u).netloc.lower())
    etiqueta = normalize_text(host.split(".")[0]).replace(" ", "")
    if not etiqueta:
        return False

    candidatos = {etiqueta}
    for p in _PREFIJOS_INSTITUCIONALES:
        if etiqueta.startswith(p) and len(etiqueta) > len(p):
            candidatos.add(etiqueta[len(p):])

    propios = {
        normalize_text(localidad_nombre or "").replace(" ", ""),
        normalize_text(municipio_nombre or "").replace(" ", ""),
    }
    return bool(candidatos & (propios - {""}))


def documento_es_ajeno_al_municipio(
    texto_doc: str,
    url: str,
    localidad_nombre: str,
    municipio_nombre: str,
    nombres_hermanas: list[str] | None = None,
    otros_topinimos: list[str] | None = None,
) -> bool:
    """
    ¿Este documento habla de un sitio que no tiene nada que ver con el municipio?

    Un buscador devuelve, para "programa fiestas de X 2026", el programa de
    fiestas de cualquier otro pueblo de España que se le parezca. Medido el
    2026-08-22: el PDF de las Fiestas Mayores de ALMANSA (Albacete, a 600 km)
    aportaba 10 de los 19 chunks del contexto de enrichment de Artomaña, y el
    programa que salió publicado para Artomaña hablaba de traje manchego, bandos
    moro y cristiano y la Virgen de Belén.

    El criterio es el más simple que funciona: si en TODO el documento y en su
    URL no aparece ni la localidad, ni el municipio, ni la provincia, ni ninguna
    de las localidades hermanas, el documento no es de aquí. De los 109 chunks
    del PDF de Almansa, ninguno nombraba a Artomaña, Amurrio, Álava ni Araba.

    No se aplica a las fuentes oficiales: el cartel colgado en la web del
    ayuntamiento es del pueblo aunque su texto no repita el nombre.

    La PROVINCIA no vale como aval, y por eso no se le pasa. Media España tiene
    una capital que se llama igual que su provincia —Albacete, Burgos, Toledo,
    Murcia, Zaragoza—, así que aceptar por provincia dejaba entrar el material de
    la capital entero: al subir el techo de descarga, a Cordovilla le llegaban
    40.000 caracteres del registro de tratamientos del Ayuntamiento de Albacete y
    la Feria de Albacete completa. Un documento que no nombra ni al pueblo, ni a
    su municipio, ni a una hermana no tiene nada que decir de sus fiestas.
    """
    texto_norm = normalize_text(texto_doc or "")
    url_norm = normalize_text(url or "")
    candidatos = [localidad_nombre, municipio_nombre]
    candidatos += list(nombres_hermanas or [])
    candidatos += list(otros_topinimos or [])
    for nombre in candidatos:
        if not nombre:
            continue
        if _menciones(texto_norm, nombre) or _menciones(url_norm, nombre):
            return False
    return True


_RE_ENTIDAD = re.compile(
    r"\b(ayuntamiento|consorcio|mancomunidad|diputacion|entidad urbanistica|"
    r"fundacion|comunidad de regantes|asociacion para el desarrollo)\b",
    re.IGNORECASE,
)
_MIN_ENTIDADES_LISTADO = 5
_MAX_FRASES_LISTADO = 2


def parece_listado_institucional(texto: str) -> bool:
    """
    ¿Este trozo es un listado de organismos, y no prosa?

    Existe por un caso concreto. En Sierra, el contexto que se le pasó al modelo
    para pedirle el programa eran 6.073 caracteres del desplegable «cambiar de
    sede» de un portal administrativo —la lista de todos los ayuntamientos de
    Albacete—, rotulado «fiabilidad MUY ALTA | Relevancia: DIRECTA». Con ese aval
    el modelo devolvió 39 actos inventados con confianza alta.

    El test es NEGATIVO y no positivo, y eso importa. La primera versión
    preguntaba «¿habla de fiestas?» y degradaba el 61% de los chunks de la web de
    Tobarra —incluido el horario de misas del Santuario de la Encarnación, que
    salía en uno de los actos reales que se perdieron—. Preguntando en cambio
    «¿es un listado de organismos?» se degrada el 0% de esos 197 chunks y se sigue
    cazando el desplegable. Reconocer lo que sobra es más seguro que exigir que
    todo demuestre que sirve.
    """
    if not texto:
        return False
    entidades = len(_RE_ENTIDAD.findall(normalize_text(texto)))
    if entidades < _MIN_ENTIDADES_LISTADO:
        return False
    # Prosa de verdad tiene frases terminadas; un desplegable, ninguna.
    frases = len(re.findall(r"[.!?]\s", texto))
    return frases <= _MAX_FRASES_LISTADO


def _clave_lugar(nombre: str) -> str:
    """Normaliza un topónimo para comparar: sin tildes, sin artículo, sin muletilla administrativa."""
    n = normalize_text(nombre or "")
    for prefijo in ("ayuntamiento de ", "concejo de ", "cendea de ", "municipio de ",
                    "villa de ", "la ", "el ", "los ", "las "):
        if n.startswith(prefijo):
            n = n[len(prefijo):]
    return " ".join(n.split())


# La comunidad de cada provincia. El modelo responde a veces con la comunidad en
# vez de la provincia ("Castilla-La Mancha" por "Albacete"), y eso NO contradice
# a nuestro sitio: hay que reconocerlo o descartaríamos documentos buenos.
_COMUNIDAD_DE_PROVINCIA = {
    "albacete": ("castilla la mancha", "castilla-la mancha"),
    "ciudad real": ("castilla la mancha", "castilla-la mancha"),
    "cuenca": ("castilla la mancha", "castilla-la mancha"),
    "guadalajara": ("castilla la mancha", "castilla-la mancha"),
    "toledo": ("castilla la mancha", "castilla-la mancha"),
    "avila": ("castilla y leon",), "burgos": ("castilla y leon",),
    "leon": ("castilla y leon",), "palencia": ("castilla y leon",),
    "salamanca": ("castilla y leon",), "segovia": ("castilla y leon",),
    "soria": ("castilla y leon",), "valladolid": ("castilla y leon",),
    "zamora": ("castilla y leon",),
    "alava": ("pais vasco", "euskadi"), "araba": ("pais vasco", "euskadi"),
    "bizkaia": ("pais vasco", "euskadi"), "vizcaya": ("pais vasco", "euskadi"),
    "gipuzkoa": ("pais vasco", "euskadi"), "guipuzcoa": ("pais vasco", "euskadi"),
    "barcelona": ("cataluna", "catalunya"), "girona": ("cataluna", "catalunya"),
    "lleida": ("cataluna", "catalunya"), "tarragona": ("cataluna", "catalunya"),
    "a coruna": ("galicia",), "lugo": ("galicia",),
    "ourense": ("galicia",), "pontevedra": ("galicia",),
    "alicante": ("comunidad valenciana",), "castellon": ("comunidad valenciana",),
    "valencia": ("comunidad valenciana",),
    "huesca": ("aragon",), "teruel": ("aragon",), "zaragoza": ("aragon",),
    "almeria": ("andalucia",), "cadiz": ("andalucia",), "cordoba": ("andalucia",),
    "granada": ("andalucia",), "huelva": ("andalucia",), "jaen": ("andalucia",),
    "malaga": ("andalucia",), "sevilla": ("andalucia",),
    "badajoz": ("extremadura",), "caceres": ("extremadura",),
}

# Palabras que solo aparecen en una lengua cooficial y que son habituales en un
# programa de fiestas. Se eligieron largas y sin parecido con el castellano: una
# palabra corta como "eta" o "els" saldría por accidente en cualquier texto.
_MARCAS_LENGUA = {
    "eu": ("jaiak", "jaiegun", "egitaraua", "antolatzailea", "kontzejua", "udala",
           "herriko", "haurrentzako", "larunbata", "igandea", "ostirala", "osteguna",
           "ekainak", "uztailak", "abuztuak", "irailak", "bazkaria", "kalejira",
           "sagardotegi", "txupinazoa", "erraldoiak", "dantzariak", "suziria"),
    "ca": ("festa major", "festes majors", "dissabte", "diumenge", "divendres",
           "dijous", "dimecres", "correfoc", "castellers", "gegants", "cercavila",
           "espectacle", "infantil i", "ajuntament de", "programacio"),
    "gl": ("festas patronais", "concello", "xoves", "venres", "sabado e", "unha",
           "xornada", "romaria", "orquestra", "verbena popular", "actuacion de"),
}

# Con dos marcas distintas basta para saber que el documento está en esa lengua;
# con una sola no, porque un programa en castellano puede citar «kalejira» o
# «correfoc» como nombre propio de un acto.
_MIN_MARCAS_LENGUA = 2


def lengua_cooficial_detectada(texto: str) -> str:
    """
    Código ISO de la lengua cooficial en la que está el texto, o "" si es castellano.

    Se hace aquí y no con el modelo porque el modelo no lo hace. Medido el
    2026-08-24 sobre el PDF de Cordovilla Bajo, que empieza literalmente con
    «ANTOLATZAILEA: CORDOBILLAKO KONTZEJUA»: qwen2.5-7b devolvía `lengua: null`.
    Reconocer un idioma por sus palabras es determinista y no necesita un modelo.

    Solo mira la cabecera: es donde está el título y el encabezado bilingüe, y
    evita que un programa largo en castellano dispare por una cita suelta.
    """
    t = normalize_text((texto or "")[:_CHARS_LENGUA])
    if not t:
        return ""
    mejor, mejor_n = "", 0
    for iso, marcas in _MARCAS_LENGUA.items():
        n = sum(1 for m in marcas if m in t)
        if n > mejor_n:
            mejor, mejor_n = iso, n
    return mejor if mejor_n >= _MIN_MARCAS_LENGUA else ""


_CHARS_LENGUA = 3000

# Lo que el modelo puede llamar "lengua" y que no delata otra región.
_LENGUAS_NEUTRAS = {"castellano", "espanol", "es", "spanish", "mixto", "bilingue", ""}

# Cómo nombra el modelo cada lengua cooficial, frente al código ISO que usa
# config_idiomas en `idiomas_a_detectar`.
_LENGUA_A_ISO = {
    "euskera": "eu", "euskara": "eu", "vasco": "eu", "basque": "eu",
    "catalan": "ca", "valenciano": "ca", "catala": "ca",
    "gallego": "gl", "galego": "gl", "galician": "gl",
}


def procedencia_contradice_al_lugar(
    procedencia: dict,
    localidad_nombre: str,
    municipio_nombre: str,
    provincia: str,
    nombres_hermanas: list[str] | None = None,
    idiomas_de_la_provincia: list[str] | None = None,
) -> str:
    """
    ¿Lo que el texto dice de sí mismo desmiente que sea de nuestro pueblo?

    Recibe lo que el modelo ha EXTRAÍDO del documento —dónde se sitúa y en qué
    lengua está— y decide aquí, en código. El reparto no es casual: pedirle al
    modelo un veredicto sí/no falla estrepitosamente. Medido el 2026-08-24 con
    qwen2.5-7b sobre cuatro documentos reales de Cordovilla, la pregunta binaria
    rechazó tres, incluida la web oficial del ayuntamiento; al insistirle en que
    nombrara el sitio en conflicto rechazó los cuatro, devolviendo `null` como
    nombre y contradiciéndose. Extrayendo un dato y decidiendo aquí: 4 de 4.

    Devuelve el motivo del descarte, o "" si no hay contradicción. El sesgo es a
    conservar: un dato ausente nunca descarta, porque la mayoría de las webs
    locales no dicen en qué provincia están.
    """
    propios = {_clave_lugar(localidad_nombre), _clave_lugar(municipio_nombre)}
    propios |= {_clave_lugar(h) for h in (nombres_hermanas or [])}
    propios.discard("")

    municipio_dicho = _clave_lugar(procedencia.get("municipio") or "")
    if municipio_dicho and municipio_dicho not in propios:
        return f"el texto lo sitúa en {procedencia.get('municipio')}"

    provincia_dicha = _clave_lugar(procedencia.get("provincia") or "")
    if provincia_dicha and provincia_dicha != _clave_lugar(provincia):
        # La comunidad autónoma también vale como respuesta ("Castilla-La Mancha"),
        # y no contradice a la provincia que hay dentro de ella.
        if provincia_dicha not in _COMUNIDAD_DE_PROVINCIA.get(_clave_lugar(provincia), ()):
            return f"el texto lo sitúa en {procedencia.get('provincia')}"

    # La lengua entra ya como código ISO cuando la ha detectado el código; si solo
    # está lo que dijo el modelo, se traduce. Lo primero es lo fiable.
    iso = (procedencia.get("lengua_iso") or "").strip()
    if not iso:
        iso = _LENGUA_A_ISO.get(_clave_lugar(procedencia.get("lengua") or ""), "")
    # Solo descarta una lengua cooficial CONOCIDA y ajena a la provincia. Una
    # lengua que no sepamos mapear no descarta nada: en Amurrio el euskera es la
    # lengua propia y descartar por ahí sería catastrófico.
    if iso and iso != "es" and iso not in (idiomas_de_la_provincia or []):
        return f"está en {iso}, que no es lengua de {provincia}"

    return ""


def documento_avalado_solo_por_la_localidad(
    texto_doc: str,
    url: str,
    localidad_nombre: str,
    municipio_nombre: str,
    nombres_hermanas: list[str] | None = None,
) -> bool:
    """
    ¿Este documento entra ÚNICAMENTE porque repite el nombre del pueblo?

    Es el perfil exacto del homónimo. Un documento que además nombra al
    municipio o a una pedanía hermana está anclado a nuestro sitio; uno que solo
    dice «Cordovilla» puede ser de cualquiera de las Cordovillas de España.

    Medido el 2026-08-24 sobre los 262 documentos en caché de las 12 localidades:
    solo 44 de 890 pares (documento, localidad) caen aquí, un 5%. Y se concentran
    justo donde hubo daño —Sierra 30%, Cordovilla 10%— mientras que los nombres
    distintivos se quedan a cero: Tobarra, Santiago de Mora y Aranda de Duero no
    tienen ni uno. Sirve para no gastar una llamada al modelo en el 95% restante.
    """
    if not localidad_nombre:
        return False

    texto_norm = normalize_text(texto_doc or "")
    url_norm = normalize_text(url or "")

    def nombra(nombre: str) -> bool:
        return bool(nombre) and (
            _menciones(texto_norm, nombre) or _menciones(url_norm, nombre)
        )

    if not nombra(localidad_nombre):
        return False
    if nombra(municipio_nombre):
        return False
    return not any(nombra(h) for h in (nombres_hermanas or []))


def clasificar_relevancia_documento(
    texto_doc: str,
    url: str,
    localidad_nombre: str,
    nombres_hermanas: list[str],
) -> str:
    """
    Relevancia geográfica de una PÁGINA ENTERA, para que sus chunks la hereden.

    El criterio no puede ser el mismo que el del chunk. Una página municipal de
    20.000 caracteres nombra de pasada a casi todas las aldeas del término, y con
    el criterio de "la menciona una vez" acababa marcada como DIRECTA para todas
    ellas: la agenda de Amurrio se declaraba DIRECTA para Aloria por una única
    aparición dentro de "(Aloria, Artomaña, Tertanga y Delika)", y con ella
    entraba el programa de San Roque etiquetado como propio de Aloria.

    Aquí se exige que el documento TRATE de la localidad:
      - la nombra en la URL o en su encabezado, o
      - la nombra varias veces fuera de enumeraciones.

    Devuelve 'DIRECTA', 'GENERAL' o 'DESCARTAR'. Nunca None: el llamante necesita
    distinguir "clasificado como ajeno" de "sin clasificar", y con None ambos
    casos se confundían y el descarte se perdía.
    """
    text_norm = normalize_text(texto_doc or "")
    hermanas = [h for h in (nombres_hermanas or []) if h]

    if _trata_sobre(text_norm, url, localidad_nombre):
        return "DIRECTA"

    significativas = _menciones_significativas(text_norm, localidad_nombre, hermanas)
    if significativas >= RELEVANCIA_DOC_MIN_MENCIONES:
        return "DIRECTA"

    # Descartar solo si la página va DE una hermana. Que la nombre no basta: la
    # página general del ayuntamiento las nombra a todas, y tirarla dejaría a la
    # pedanía sin ningún material del municipio.
    if not significativas:
        for hermana in hermanas:
            if _trata_sobre(text_norm, url, hermana):
                return "DESCARTAR"

    return "GENERAL"

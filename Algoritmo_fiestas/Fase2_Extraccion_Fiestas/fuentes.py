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

PRIORIDAD_FUENTE = {
    FUENTE_WEB_LOCALIDAD: 1,
    FUENTE_WEB_MUNICIPIO: 2,
    FUENTE_RRSS_LOCALIDAD: 3,
    FUENTE_RRSS_MUNICIPIO: 4,
    FUENTE_PRENSA_REGIONAL: 5,
    FUENTE_BUSQUEDA: 6,
}

_ROTULOS = {
    FUENTE_WEB_LOCALIDAD: "WEB OFICIAL DE LA LOCALIDAD (fiabilidad MÁXIMA)",
    FUENTE_WEB_MUNICIPIO: "WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA)",
    FUENTE_RRSS_LOCALIDAD: "RED SOCIAL OFICIAL DE LA LOCALIDAD (fiabilidad ALTA)",
    FUENTE_RRSS_MUNICIPIO: "RED SOCIAL OFICIAL DEL MUNICIPIO (fiabilidad ALTA)",
    FUENTE_PRENSA_REGIONAL: "PRENSA REGIONAL / MEDIOS DE COMUNICACIÓN (fiabilidad MEDIA)",
    FUENTE_BUSQUEDA: "RESULTADOS DE BUSCADOR (fiabilidad BAJA — verificar)",
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

def crear_documento(fuente: str, url: str, texto: str, tipo: str = "pagina") -> dict:
    """
    Crea un documento etiquetado. tipo ∈ {pagina, pdf, cartel, rrss, snippets}.
    es_calendario se autodetecta a partir de la URL y el inicio del texto.
    """
    return {
        "fuente": fuente,
        "url": url or "",
        "texto": texto or "",
        "tipo": tipo,
        "es_calendario": detectar_es_calendario(url, texto),
    }

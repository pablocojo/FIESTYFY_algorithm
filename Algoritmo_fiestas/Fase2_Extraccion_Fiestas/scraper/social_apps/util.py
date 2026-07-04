"""
Utilidades sin dependencias de GUI para el runner de apps:
validación de candidatos, parsing de fechas de posts y manejo de handles.
"""

import re
import unicodedata
from datetime import date, timedelta
import urllib.parse

# Marcadores institucionales: un perfil hallado buscando en la app solo se
# acepta si su nombre/handle contiene el nombre de la localidad Y uno de estos
# marcadores (cero falsos positivos: mejor null que un perfil equivocado).
MARCADORES_INSTITUCIONALES = [
    "ayuntamiento", "ayto", "concello", "udala", "ajuntament", "concejo",
    "villa de", "ciudad de", "fiestas", "oficial",
]


def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\s@._]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def validar_candidato_perfil(texto_candidato: str, nombre_localidad: str, handle_esperado: str | None = None) -> tuple[bool, str]:
    """
    Valida un candidato hallado en el buscador interno de una app.
    - Con handle_esperado (tarea "leer"): basta que el handle aparezca.
    - Sin handle (tarea "buscar"): debe contener el nombre COMPLETO normalizado
      de la localidad Y un marcador institucional. Estricto a propósito.
    """
    cand = normalizar(texto_candidato)
    # Los handles suelen ir pegados: comparar también sin espacios ni signos
    cand_compacto = re.sub(r"[\s._@]", "", cand)

    if handle_esperado:
        handle = re.sub(r"[\s._@]", "", normalizar(handle_esperado))
        if handle and handle in cand_compacto:
            return True, "handle coincide"
        return False, f"no aparece el handle '{handle_esperado}'"

    loc = normalizar(nombre_localidad)
    loc_compacta = re.sub(r"\s", "", loc)
    if loc not in cand and loc_compacta not in cand_compacto:
        return False, "no contiene el nombre completo de la localidad"

    for marcador in MARCADORES_INSTITUCIONALES:
        marcador_compacto = marcador.replace(" ", "")
        if marcador in cand or marcador_compacto in cand_compacto:
            return True, f"localidad + marcador '{marcador}'"
    return False, "sin marcador institucional (ayuntamiento/ayto/concello/udala...)"


# ──────────────────────────────────────────────────
# FECHAS DE POSTS ("12 de junio", "3 jul", "hace 2 días", "ayer"...)
# ──────────────────────────────────────────────────

_MESES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9, "sept": 9,
    "sep": 9, "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

_RE_FECHA_ABS = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?([a-z]{3,10})\.?(?:\s+(?:de\s+)?(\d{4}))?\b"
)
_RE_HACE = re.compile(r"\bhace\s+(\d+)\s+(minuto|min|hora|h|dia|d|semana|sem)\w*\b")


def parsear_fecha_post(texto: str, hoy: date | None = None) -> date | None:
    """Intenta extraer la fecha de publicación de un post del texto visible."""
    if not texto:
        return None
    hoy = hoy or date.today()
    t = normalizar(texto)

    if re.search(r"\bayer\b", t):
        return hoy - timedelta(days=1)
    if re.search(r"\bhoy\b", t):
        return hoy

    m = _RE_HACE.search(t)
    if m:
        n, unidad = int(m.group(1)), m.group(2)
        if unidad in ("minuto", "min", "hora", "h"):
            return hoy
        if unidad in ("dia", "d"):
            return hoy - timedelta(days=n)
        if unidad in ("semana", "sem"):
            return hoy - timedelta(weeks=n)

    for m in _RE_FECHA_ABS.finditer(t):
        dia, mes_txt, anno_txt = int(m.group(1)), m.group(2), m.group(3)
        mes = _MESES.get(mes_txt)
        if not mes or not (1 <= dia <= 31):
            continue
        anno = int(anno_txt) if anno_txt else hoy.year
        try:
            fecha = date(anno, mes, dia)
        except ValueError:
            continue
        # Sin año explícito, las apps solo lo omiten si es el año en curso;
        # si queda en el futuro, era del año pasado.
        if not anno_txt and fecha > hoy:
            fecha = date(anno - 1, mes, dia)
        return fecha
    return None


def handle_de_url(url: str) -> str | None:
    """Extrae el handle de una URL canónica de perfil (o el id de profile.php)."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    segmentos = [s for s in parsed.path.split("/") if s]
    if not segmentos:
        return None
    if segmentos[0] == "profile.php":
        query = urllib.parse.parse_qs(parsed.query)
        return (query.get("id") or [None])[0]
    if segmentos[0] in ("pages", "people") and len(segmentos) >= 2:
        return segmentos[1]
    return segmentos[0]


def url_de_handle(red: str, handle: str) -> str:
    base = {
        "instagram": "https://www.instagram.com/",
        "facebook": "https://www.facebook.com/",
        "twitter": "https://x.com/",
    }[red]
    return base + handle

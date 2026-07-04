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
    # catalán (normalizado sin tildes)
    "gener": 1, "febrer": 2, "marc": 3, "maig": 5, "juny": 6, "juliol": 7,
    "agost": 8, "setembre": 9, "novembre": 11, "desembre": 12,
    # gallego
    "xaneiro": 1, "febreiro": 2, "maio": 5, "xuno": 6, "xullo": 7,
    "setembro": 9, "outubro": 10, "novembro": 11, "decembro": 12,
}

# Euskera: el mes va DELANTE ("ekainak 27" = 27 de junio)
_MESES_EUS = {
    "urtarril": 1, "otsail": 2, "martxo": 3, "apiril": 4, "maiatz": 5,
    "ekain": 6, "uztail": 7, "abuztu": 8, "irail": 9, "urri": 10,
    "azaro": 11, "abendu": 12,
}
_RE_FECHA_EUS = re.compile(
    r"\b(urtarril|otsail|martxo|apiril|maiatz|ekain|uztail|abuztu|irail|urri|azaro|abendu)\w*\s+(\d{1,2})\b"
)

_RE_FECHA_ABS = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?([a-z]{3,10})\.?(?:\s+(?:de\s+)?(\d{4}))?\b"
)
_RE_HACE = re.compile(r"\bhace\s+(\d+)\s+(minuto|min|hora|h|dia|d|semana|sem)\w*\b")
# Formato corto de Instagram/X: "1 sem", "3 d", "5 h", "22 min"
_RE_RELATIVA_CORTA = re.compile(r"\b(\d{1,3})\s*(sem|min|h|d)\b")


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

    # Euskera: mes delante ("ekainak 27")
    m = _RE_FECHA_EUS.search(t)
    if m:
        mes, dia = _MESES_EUS[m.group(1)], int(m.group(2))
        if 1 <= dia <= 31:
            try:
                fecha = date(hoy.year, mes, dia)
                return date(hoy.year - 1, mes, dia) if fecha > hoy else fecha
            except ValueError:
                pass

    # Formato corto de Instagram/X ("1 sem", "3 d") — al final para no robar
    # coincidencias a las fechas absolutas
    m = _RE_RELATIVA_CORTA.search(t)
    if m:
        n, unidad = int(m.group(1)), m.group(2)
        if unidad in ("min", "h"):
            return hoy
        if unidad == "d":
            return hoy - timedelta(days=n)
        if unidad == "sem":
            return hoy - timedelta(weeks=n)
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


# ──────────────────────────────────────────────────
# CLUSTERING DE TEXTOS EN POSTS (M1 — puro, sin GUI)
# ──────────────────────────────────────────────────

def agrupar_posts(items: list[dict], hueco_max: int = 90, solape_min: float = 0.3) -> list[dict]:
    """
    Agrupa textos visibles en POSTS individuales.
    items: {texto, left, top, right, bottom, clave (opcional: id del contenedor UIA)}
    1º agrupa por `clave` (mismo contenedor = mismo post);
    2º los sueltos, por banda: deben solapar horizontalmente (misma columna)
       y estar a menos de `hueco_max` px verticales (paneles laterales y posts
       contiguos quedan separados).
    Devuelve [{texto, top}] ordenado de arriba a abajo.
    """
    con_clave: dict = {}
    sueltos = []
    for it in items:
        if it.get("clave"):
            con_clave.setdefault(it["clave"], []).append(it)
        else:
            sueltos.append(it)

    grupos = list(con_clave.values())

    abiertos = []  # {items, left, right, bottom}
    for it in sorted(sueltos, key=lambda x: (x["top"], x["left"])):
        elegido = None
        for c in abiertos:
            solape = min(it["right"], c["right"]) - max(it["left"], c["left"])
            ancho_min = max(1, min(it["right"] - it["left"], c["right"] - c["left"]))
            if solape / ancho_min >= solape_min and (it["top"] - c["bottom"]) <= hueco_max:
                elegido = c
                break
        if elegido is None:
            abiertos.append({
                "items": [it],
                "left": it["left"], "right": it["right"], "bottom": it["bottom"],
            })
        else:
            elegido["items"].append(it)
            elegido["left"] = min(elegido["left"], it["left"])
            elegido["right"] = max(elegido["right"], it["right"])
            elegido["bottom"] = max(elegido["bottom"], it["bottom"])
    grupos += [c["items"] for c in abiertos]

    clusters = []
    for lista in grupos:
        lista.sort(key=lambda x: (x["top"], x["left"]))
        clusters.append({
            "texto": "\n".join(x["texto"] for x in lista),
            "top": min(x["top"] for x in lista),
        })
    clusters.sort(key=lambda c: c["top"])
    return clusters


# ──────────────────────────────────────────────────
# HASH PERCEPTUAL DE CAPTURAS (M4 — fin de galería y dedupe)
# ──────────────────────────────────────────────────

def hash_perceptual(ruta: str) -> str | None:
    """aHash 16x16 en escala de grises. None si la imagen no se puede leer."""
    try:
        from PIL import Image
        with Image.open(ruta) as img:
            pixeles = list(img.convert("L").resize((16, 16)).getdata())
    except Exception:
        return None
    media = sum(pixeles) / len(pixeles)
    bits = 0
    for p in pixeles:
        bits = (bits << 1) | (1 if p > media else 0)
    return f"{bits:064x}"


# ──────────────────────────────────────────────────
# FICHA DEL PERFIL (M2 — puro, sin GUI)
# ──────────────────────────────────────────────────

_RE_DOMINIO_TXT = re.compile(
    r"\b((?:[\w-]+\.)+(?:es|com|eus|org|net|cat|gal|info|edu|eu))\b", re.IGNORECASE
)
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_RE_SEGUIDORES = re.compile(r"([\d.,]+)\s*(mil|k|m)?\s*(seguidores|followers)", re.IGNORECASE)


def dominio_base(url_o_dominio: str) -> str | None:
    """'https://www.donostia.eus/Gazteria' → 'donostia.eus'."""
    s = (url_o_dominio or "").strip().lower()
    if not s:
        return None
    if "://" in s:
        s = urllib.parse.urlparse(s).netloc or s.split("://", 1)[1]
    s = s.split("/")[0].split(":")[0]
    if s.startswith("www."):
        s = s[4:]
    etiquetas = [e for e in s.split(".") if e]
    if len(etiquetas) < 2:
        return None
    return ".".join(etiquetas[-2:])


def extraer_datos_ficha(textos: list[str], titulo: str = "") -> dict:
    """
    Extrae la ficha del perfil de los textos visibles (panel Detalles de FB,
    bio de IG/X): webs, emails y seguidores. Puro: testeable sin GUI.
    """
    webs, emails = set(), set()
    seguidores = None
    for t in textos[:150]:
        for m in _RE_EMAIL.findall(t):
            emails.add(m.lower())
        # Los dominios se extraen del texto SIN los emails (el dominio de un
        # email no es una "web", salvo que aparezca también por separado)
        t_sin_emails = _RE_EMAIL.sub(" ", t)
        for m in _RE_DOMINIO_TXT.findall(t_sin_emails):
            webs.add(m.lower())
        if seguidores is None:
            m = _RE_SEGUIDORES.search(t)
            if m:
                seguidores = m.group(0)
    return {
        "titulo": titulo,
        "webs": sorted(webs),
        "emails": sorted(emails),
        "seguidores": seguidores,
    }

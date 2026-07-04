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

# ──────────────────────────────────────────────────
# CONSTANTES DE FUENTE
# ──────────────────────────────────────────────────

FUENTE_WEB_LOCALIDAD = "web_localidad"
FUENTE_WEB_MUNICIPIO = "web_municipio"
FUENTE_RRSS_LOCALIDAD = "rrss_localidad"   # se usa con sufijo: "rrss_localidad:instagram"
FUENTE_RRSS_MUNICIPIO = "rrss_municipio"
FUENTE_BUSQUEDA = "busqueda_web"

PRIORIDAD_FUENTE = {
    FUENTE_WEB_LOCALIDAD: 1,
    FUENTE_WEB_MUNICIPIO: 2,
    FUENTE_RRSS_LOCALIDAD: 3,
    FUENTE_RRSS_MUNICIPIO: 4,
    FUENTE_BUSQUEDA: 5,
}

_ROTULOS = {
    FUENTE_WEB_LOCALIDAD: "WEB OFICIAL DE LA LOCALIDAD (fiabilidad MÁXIMA)",
    FUENTE_WEB_MUNICIPIO: "WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA)",
    FUENTE_RRSS_LOCALIDAD: "RED SOCIAL OFICIAL DE LA LOCALIDAD (fiabilidad ALTA)",
    FUENTE_RRSS_MUNICIPIO: "RED SOCIAL OFICIAL DEL MUNICIPIO (fiabilidad ALTA)",
    FUENTE_BUSQUEDA: "RESULTADOS DE BUSCADOR (fiabilidad BAJA — verificar)",
}


def fuente_base(fuente: str) -> str:
    """'rrss_localidad:instagram' → 'rrss_localidad'."""
    return (fuente or "").split(":")[0]


def prioridad_fuente(fuente: str) -> int:
    return PRIORIDAD_FUENTE.get(fuente_base(fuente), 9)


def es_fuente_valida(fuente: str) -> bool:
    return fuente_base(fuente) in PRIORIDAD_FUENTE


def es_fuente_oficial(fuente: str) -> bool:
    """Oficial = todo menos los resultados de buscador."""
    base = fuente_base(fuente)
    return base in PRIORIDAD_FUENTE and base != FUENTE_BUSQUEDA


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

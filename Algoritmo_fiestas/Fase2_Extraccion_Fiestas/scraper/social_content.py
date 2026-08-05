"""
Lector de la caché de contenido de redes sociales.

La caché (`rrss_contenido_cache.json`) la produce el runner de apps de escritorio
(social_apps_runner.py, Etapa C) en sesiones dedicadas. Este módulo solo LEE:
si la caché no existe o no tiene datos para un lugar, la fuente RRSS se omite
y el pipeline continúa con el resto de fuentes.

Formato de la caché (el que produce el runner):
{
  "<lugar_id>": {
    "instagram": {
      "leido_en": "2026-07-04",
      "posts": [
        {"texto": "caption del post", "fecha": "2026-08-01", "captura": "rrss_capturas/...",
         "es_programa": true, "texto_programa": "FIESTAS...", "url_post": "..."}
      ]
    }
  }
}
También se acepta el formato simple con la lista de posts directamente.
"""

import json
import os
import logging
import re
from datetime import datetime, date

from config import SOCIAL_CONTENT_CACHE_FILE
from fuentes import crear_documento, FUENTE_RRSS_LOCALIDAD, FUENTE_RRSS_MUNICIPIO

logger = logging.getLogger("social_content")


def es_fecha_en_ventana(
    fecha_str: str | None,
    anno: int = 2026,
    mes_inicio_previo: int = 11,
) -> bool:
    """
    Verifica si una fecha de publicación de post está dentro de la ventana aceptable para el año objetivo (anno).
    Ventana por defecto: desde 1 de noviembre de (anno - 1) hasta 31 de enero de (anno + 1).
    Si la fecha no es especificada o no se puede parsear, se mantiene el post.
    """
    if not fecha_str:
        return True
    
    fecha_str_clean = str(fecha_str).strip()
    dt = None
    try:
        dt = datetime.fromisoformat(fecha_str_clean.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(fecha_str_clean[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return True

    inicio_ventana = date(anno - 1, mes_inicio_previo, 1)
    fin_ventana = date(anno + 1, 1, 31)
    return inicio_ventana <= dt <= fin_ventana

# Patrones de ruido de UI de las apps — jamás son contenido de un post real
_RUIDO_UI_TEXTOS = re.compile(
    r"^("
    # Controles de ventana y navegación
    r"minimizar|restaurar|cerrar|maximize|minimize|close"
    r"|home \(new|search and explore|direct messages"
    r"|notifications? \(|grok|bookmarks|creator studio|premium"
    r"|view keyboard shortcuts|press question mark"
    # Sidebar / chrome de las apps
    r"|you might like|who to follow|show more|trending now"
    r"|what.s happening|terms\b.*privacy.*cookies"
    r"|© \d{4} (x|meta|instagram)|ads info"
    # Textos de solo una palabra que son UI
    r"|image|video"
    r")$",
    re.IGNORECASE,
)

_RUIDO_UI_PARCIAL = re.compile(
    r"(trending in|sports · trending|view post analytics"
    r"|new unread posts|unread notification"
    r"|opens profile photo|not followed by anyone"
    r"|verified account)",
    re.IGNORECASE,
)


def _es_ruido_ui(texto: str) -> bool:
    """True si el texto es claramente ruido de la interfaz de la app, no contenido."""
    t = texto.strip()
    if len(t) < 4:
        return True
    if _RUIDO_UI_TEXTOS.match(t):
        return True
    # Textos cortos con señales parciales de UI
    if len(t) < 80 and _RUIDO_UI_PARCIAL.search(t):
        return True
    return False

_FASE2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_FASE2_DIR, SOCIAL_CONTENT_CACHE_FILE)

_cache: dict | None = None


def invalidar_cache():
    """Fuerza la re-lectura de la caché desde disco en la próxima llamada."""
    global _cache
    _cache = None


def _cargar_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"Caché de contenido RRSS cargada: {len(_cache)} lugares")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"No se pudo leer la caché de contenido RRSS: {e}")
    return _cache


def _documentos_de_lugar(lugar: dict, fuente_base: str, anno: int = 2026) -> list[dict]:
    cache = _cargar_cache()
    entrada = cache.get(lugar["id"]) or {}
    documentos = []

    for red, valor in entrada.items():
        # Formato del runner: {"leido_en": ..., "posts": [...]}; también lista directa
        posts = valor.get("posts") if isinstance(valor, dict) else valor
        if not isinstance(posts, list):
            continue
        textos = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            texto = (post.get("texto") or "").strip()
            if _es_ruido_ui(texto):
                continue
            # Limpiar artefactos de UI pegados al final de posts reales
            texto = re.sub(r'\n*\d+ views?\.\s*View post analytics$', '', texto).strip()
            if post.get("es_programa") and (post.get("texto_programa") or "").strip():
                texto += "\n[PROGRAMA EXTRAÍDO DE IMAGEN]:\n" + post["texto_programa"].strip()
            if not texto.strip():
                continue

            # R4: Asegurar fecha_publicacion preservada en el diccionario del post
            fecha_pub = post.get("fecha_publicacion") or post.get("fecha")
            if fecha_pub:
                post["fecha_publicacion"] = fecha_pub

            # R4: Filtrar posts fuera de la ventana aceptable para el año objetivo
            if not es_fecha_en_ventana(fecha_pub, anno=anno):
                logger.info(f"  [RRSS] Post con fecha {fecha_pub} fuera de ventana para {anno}. Descartado.")
                continue

            textos.append(f"[POST {fecha_pub}] {texto}" if fecha_pub else texto)

        if textos:
            documentos.append(
                crear_documento(
                    f"{fuente_base}:{red}",
                    url=f"{red}:{lugar['id']}",
                    texto="\n\n".join(textos),
                    tipo="rrss",
                )
            )
    return documentos


def cargar_documentos_rrss(localidad: dict, municipio: dict, anno: int = 2026) -> list[dict]:
    """
    Documentos RRSS para una localidad: primero los de la localidad (prioridad 3)
    y después los del municipio (prioridad 4). Si la localidad ES la capital y
    comparte id con la entrada del municipio en caché, no se duplican.
    """
    documentos = _documentos_de_lugar(localidad, FUENTE_RRSS_LOCALIDAD, anno=anno)
    if municipio["id"] != localidad["id"]:
        documentos += _documentos_de_lugar(municipio, FUENTE_RRSS_MUNICIPIO, anno=anno)
    if documentos:
        logger.info(f"  RRSS: {len(documentos)} documentos desde caché para {localidad['nombre']}")
    return documentos


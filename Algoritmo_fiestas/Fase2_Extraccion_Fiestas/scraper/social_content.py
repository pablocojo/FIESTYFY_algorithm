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

from config import SOCIAL_CONTENT_CACHE_FILE
from fuentes import crear_documento, FUENTE_RRSS_LOCALIDAD, FUENTE_RRSS_MUNICIPIO

logger = logging.getLogger("social_content")

_FASE2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_FASE2_DIR, SOCIAL_CONTENT_CACHE_FILE)

_cache: dict | None = None


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


def _documentos_de_lugar(lugar: dict, fuente_base: str) -> list[dict]:
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
            if post.get("es_programa") and (post.get("texto_programa") or "").strip():
                texto += "\n[PROGRAMA EXTRAÍDO DE IMAGEN]:\n" + post["texto_programa"].strip()
            if not texto.strip():
                continue
            fecha = post.get("fecha")
            textos.append(f"[POST {fecha}] {texto}" if fecha else texto)

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


def cargar_documentos_rrss(localidad: dict, municipio: dict) -> list[dict]:
    """
    Documentos RRSS para una localidad: primero los de la localidad (prioridad 3)
    y después los del municipio (prioridad 4). Si la localidad ES la capital y
    comparte id con la entrada del municipio en caché, no se duplican.
    """
    documentos = _documentos_de_lugar(localidad, FUENTE_RRSS_LOCALIDAD)
    if municipio["id"] != localidad["id"]:
        documentos += _documentos_de_lugar(municipio, FUENTE_RRSS_MUNICIPIO)
    if documentos:
        logger.info(f"  RRSS: {len(documentos)} documentos desde caché para {localidad['nombre']}")
    return documentos

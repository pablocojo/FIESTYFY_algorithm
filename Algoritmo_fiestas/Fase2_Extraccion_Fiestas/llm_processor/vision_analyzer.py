"""
Analizador de visión (Etapa D) — VLM local sobre capturas de RRSS.

ÁMBITO (decisión del usuario): SOLO las imágenes procedentes de las apps de
redes sociales pasan por el VLM; las imágenes de webs y PDFs siguen con Tesseract.

Doble filtro anti-falsos-positivos:
1. PREFILTRO SIN GPU: el texto/caption del post debe contener alguna palabra
   festiva (programa, fiestas, cartel, verbena, orquesta...). Sin keywords,
   la captura ni siquiera se envía al VLM.
2. El VLM clasifica ("¿es un cartel/programa de fiestas?") Y transcribe en una
   sola llamada; si `es_programa_fiestas` es false, la imagen se descarta.

El resultado se escribe en la propia caché de contenido (`rrss_contenido_cache.json`):
cada post gana `es_programa`, `texto_programa` y `vision_procesada`, y el
pipeline principal (scraper/social_content.py) ya los inyecta al contexto.
"""

import asyncio
import base64
import io
import logging
import os
import re

import aiohttp
from PIL import Image

from config import (
    LMSTUDIO_SEED,
    LMSTUDIO_CHAT_URL,
    VISION_ENABLED,
    VISION_MODEL,
    VISION_TIMEOUT,
    VISION_MAX_TOKENS,
    VISION_MAX_IMAGES_PER_PROFILE,
    VISION_MAX_DIM,
    IMAGE_MIN_WIDTH,
    IMAGE_MIN_HEIGHT,
)
from llm_processor.text_analyzer import LLM_SEMAPHORE, _parse_json_llm
from llm_processor.festival_filter import (
    normalizar_texto,
    SENALES_NOCTURNAS,
    SENALES_TIPO_FIESTA,
)

logger = logging.getLogger("vision_analyzer")

from config_idiomas import PERFILES_IDIOMA

_KEYWORDS_BASE = set(SENALES_NOCTURNAS + SENALES_TIPO_FIESTA + [
    "programa", "programacion", "cartel", "actos", "agenda", "patronales"
])

for perfil in PERFILES_IDIOMA.values():
    if "keywords_busqueda" in perfil:
        for kw in perfil["keywords_busqueda"]:
            _KEYWORDS_BASE.add(normalizar_texto(kw))

# En euskera los nombres de fiesta se aglutinan (Intxaurjaiak, Sanjuanak...):
# estas keywords casan también como SUFIJO de palabra
_KEYWORDS_SUFIJO = {"jaiak", "jaia"}

# Palabras que habilitan el envío de una captura al VLM (prefiltro por OCR)
PALABRAS_CLAVE_VISION = sorted(
    list(_KEYWORDS_BASE),
    key=len,
    reverse=True,
)
_RE_KEYWORDS = [
    (kw, re.compile(rf"{re.escape(kw)}\b" if kw in _KEYWORDS_SUFIJO else rf"\b{re.escape(kw)}\b"))
    for kw in PALABRAS_CLAVE_VISION
]


def texto_indica_fiesta(texto: str) -> str | None:
    """Devuelve la keyword festiva hallada en el texto del post, o None."""
    norm = normalizar_texto(texto or "")
    if not norm:
        return None
    for kw, patron in _RE_KEYWORDS:
        if patron.search(norm):
            return kw
    return None


async def _keyword_por_ocr(ruta: str) -> str | None:
    """
    OCR-lite (Tesseract, CPU): rescata carteles cuyo texto festivo está EN la
    imagen y no en el caption (típico en la sección Fotos, y en euskera/catalán/
    gallego). Mantiene la regla del usuario: ninguna imagen llega al VLM sin
    indicio festivo — pero el indicio puede venir del propio cartel.
    """
    try:
        from scraper.document_extractor import extract_text_from_image
        with open(ruta, "rb") as f:
            datos = f.read()
        texto = await asyncio.to_thread(extract_text_from_image, datos)
    except Exception as e:
        logger.debug(f"OCR-lite falló en {ruta}: {e}")
        return None
    return texto_indica_fiesta(texto or "")


def pil_a_data_uri(img: Image.Image, max_dim: int = VISION_MAX_DIM) -> str | None:
    """Valida dimensiones, redimensiona y codifica una imagen PIL en base64."""
    try:
        ancho, alto = img.size
        if ancho < IMAGE_MIN_WIDTH or alto < IMAGE_MIN_HEIGHT:
            logger.debug(f"Imagen descartada por dimensiones: {ancho}x{alto}")
            return None
        img = img.copy().convert("RGB")
        img.thumbnail((max_dim, max_dim))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        codificada = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{codificada}"
    except Exception as e:
        logger.warning(f"Error procesando PIL Image a Data URI: {e}")
        return None

def imagen_a_data_uri(ruta: str, max_dim: int = VISION_MAX_DIM) -> str | None:
    """Carga una imagen desde disco y la codifica."""
    try:
        with Image.open(ruta) as img:
            return pil_a_data_uri(img, max_dim)
    except Exception as e:
        logger.warning(f"No se pudo procesar la imagen {ruta}: {e}")
        return None

_SYSTEM_VISION = """Eres una API estricta que analiza capturas de redes sociales o carteles de ayuntamientos españoles.
Tu única tarea: decidir si la imagen contiene un CARTEL o PROGRAMA DE FIESTAS de una localidad
(programa de actos, cartel anunciador con fechas/horarios, agenda festiva) y, si lo es, transcribirlo.

NO son programas de fiestas: fotos de eventos ya celebrados, paisajes, obras, plenos, anuncios
de servicios municipales, bandos, esquelas, carteles de cursos o actividades no festivas.

Responde SOLO con JSON estricto:
{"es_programa_fiestas": true o false, "texto_extraido": "transcripción fiel con fechas, horas y actos (vacío si false)"}"""

async def analizar_imagen_directa(img: Image.Image) -> str:
    """
    Analiza una imagen PIL directamente. Devuelve el texto estructurado si es un programa, o "" si no.
    """
    data_uri = pil_a_data_uri(img)
    if data_uri is None:
        return ""
    
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_VISION},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "¿Contiene esta imagen un cartel o programa de fiestas? Responde SOLO con el JSON.",
                    },
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
        "temperature": 0.0,
        "seed": LMSTUDIO_SEED,
        "max_tokens": VISION_MAX_TOKENS,
    }

    try:
        async with LLM_SEMAPHORE:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    LMSTUDIO_CHAT_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=VISION_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.json()
                    contenido = data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Error VLM en analizar_imagen_directa: {e}")
        return ""

    parsed = _parse_json_llm(contenido)
    if isinstance(parsed, dict) and parsed.get("es_programa_fiestas"):
        return str(parsed.get("texto_extraido") or "").strip()
    return ""

async def analizar_imagen(ruta: str) -> dict | None:
    """
    Clasifica y transcribe una captura desde ruta en disco.
    """
    data_uri = imagen_a_data_uri(ruta)
    if data_uri is None:
        return {"es_programa_fiestas": False, "texto_extraido": ""}

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_VISION},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "¿Contiene esta imagen un cartel o programa de fiestas? Responde SOLO con el JSON.",
                    },
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
        "temperature": 0.0,
        "seed": LMSTUDIO_SEED,
        "max_tokens": VISION_MAX_TOKENS,
    }

    try:
        async with LLM_SEMAPHORE:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    LMSTUDIO_CHAT_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=VISION_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        cuerpo = await resp.text()
                        logger.error(f"Error VLM: status {resp.status} — {cuerpo[:200]}")
                        return None
                    data = await resp.json()
                    contenido = data["choices"][0]["message"]["content"]
    except asyncio.TimeoutError:
        logger.error(f"Timeout del VLM tras {VISION_TIMEOUT}s: {ruta}")
        return None
    except Exception as e:
        logger.error(f"Error VLM: {e}")
        return None

    parsed = _parse_json_llm(contenido)
    if not isinstance(parsed, dict) or "es_programa_fiestas" not in parsed:
        logger.warning(f"Respuesta del VLM sin el esquema esperado: {str(parsed)[:150]}")
        return None
    return {
        "es_programa_fiestas": bool(parsed.get("es_programa_fiestas")),
        "texto_extraido": str(parsed.get("texto_extraido") or "").strip(),
    }


# ──────────────────────────────────────────────────
# POST-PROCESO DE LA CACHÉ DE CONTENIDO
# ──────────────────────────────────────────────────

async def procesar_cache_contenido(
    data: dict,
    analizador=analizar_imagen,
    max_imagenes: int | None = None,
    max_por_perfil: int = VISION_MAX_IMAGES_PER_PROFILE,
) -> dict:
    """
    Recorre la caché de contenido y procesa con el VLM los posts con captura
    pendiente. Muta `data` in situ y devuelve un resumen.

    Prefiltro estricto (pedido por el usuario): sin keyword festiva en el texto
    del post, la captura NO se envía al VLM (se marca procesada, es_programa=False).
    """
    if not VISION_ENABLED:
        return {"procesadas": 0, "programas": 0, "sin_keywords": 0, "errores": 0,
                "duplicadas": 0, "ocr_rescatadas": 0, "deshabilitado": True}

    from scraper.social_apps.util import hash_perceptual

    resumen = {"procesadas": 0, "programas": 0, "sin_keywords": 0, "errores": 0,
               "duplicadas": 0, "ocr_rescatadas": 0}

    for lugar_id, redes in (data or {}).items():
        if not isinstance(redes, dict):
            continue

        # Dedupe por lugar: mismas capturas compartidas entre posts (viewport
        # del timeline) o repetidas entre feed y sección Fotos
        rutas_analizadas: set[str] = set()
        hashes_analizados: set[str] = set()
        for valor in redes.values():
            posts_previos = valor.get("posts") if isinstance(valor, dict) else valor
            for p in posts_previos or []:
                if isinstance(p, dict) and p.get("vision_procesada"):
                    if p.get("captura"):
                        rutas_analizadas.add(p["captura"])
                    if p.get("hash_captura"):
                        hashes_analizados.add(p["hash_captura"])

        for red, valor in redes.items():
            posts = valor.get("posts") if isinstance(valor, dict) else valor
            if not isinstance(posts, list):
                continue
            enviadas_perfil = 0
            for post in posts:
                if not isinstance(post, dict) or post.get("vision_procesada"):
                    continue
                captura = post.get("captura")
                if not captura or not os.path.exists(captura):
                    continue
                if max_imagenes is not None and resumen["procesadas"] >= max_imagenes:
                    return resumen

                # Dedupe: la misma imagen no se analiza dos veces
                hash_c = post.get("hash_captura") or hash_perceptual(captura)
                post["hash_captura"] = hash_c
                if captura in rutas_analizadas or (hash_c and hash_c in hashes_analizados):
                    post["vision_procesada"] = True
                    post["es_programa"] = False
                    post["duplicada"] = True
                    resumen["duplicadas"] += 1
                    continue

                # Prefiltro: keyword en el caption, o rescate por OCR del cartel
                keyword = texto_indica_fiesta(post.get("texto", ""))
                origen_keyword = "caption"
                if not keyword:
                    keyword = await _keyword_por_ocr(captura)
                    origen_keyword = "ocr"
                if not keyword:
                    post["vision_procesada"] = True
                    post["es_programa"] = False
                    resumen["sin_keywords"] += 1
                    continue

                if enviadas_perfil >= max_por_perfil:
                    continue
                enviadas_perfil += 1

                resultado = await analizador(captura)
                if resultado is None:
                    resumen["errores"] += 1
                    continue  # sin marcar: se reintentará en la próxima ejecución

                post["vision_procesada"] = True
                post["es_programa"] = resultado["es_programa_fiestas"]
                rutas_analizadas.add(captura)
                if hash_c:
                    hashes_analizados.add(hash_c)
                if origen_keyword == "ocr":
                    resumen["ocr_rescatadas"] += 1
                if resultado["es_programa_fiestas"] and resultado["texto_extraido"]:
                    post["texto_programa"] = resultado["texto_extraido"]
                    resumen["programas"] += 1
                    logger.info(
                        f"  [VLM] PROGRAMA detectado ({lugar_id}/{red}, "
                        f"keyword '{keyword}' vía {origen_keyword}): {captura}"
                    )
                resumen["procesadas"] += 1

    return resumen

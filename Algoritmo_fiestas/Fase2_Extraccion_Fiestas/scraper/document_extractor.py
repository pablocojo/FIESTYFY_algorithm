"""
Módulo de extracción de documentos (PDFs e imágenes/carteles).
Incluye filtrado inteligente pre-descarga/OCR para evitar procesar
logos, iconos y documentos irrelevantes.
"""

import io
import re
import logging

try:
    from PIL import Image
    import os
    os.environ["TESSDATA_PREFIX"] = r'C:\Program Files\Tesseract-OCR\tessdata'
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    pass  # Dependencias que el usuario debe instalar

try:
    import pdfplumber
except ImportError:
    pass

from config import (
    IMAGE_MIN_SIZE_BYTES,
    IMAGE_MIN_WIDTH,
    IMAGE_MIN_HEIGHT,
    IMAGE_EXCLUDED_PATTERNS,
    IMAGE_VALID_EXTENSIONS,
    PDF_MAX_PAGES_OCR,
)

logger = logging.getLogger("document_extractor")

# ─────────────────────────────────────────────
# Filtros de relevancia (pre-descarga)
# ─────────────────────────────────────────────

# Keywords que indican contenido de fiestas
_FIESTA_KEYWORDS = [
    "fiesta", "festejo", "programa", "cartel", "feria", "carnaval",
    "romeria", "patronal", "navidad", "semana santa", "programacion",
    "verbena", "pregon", "encierro", "orquesta", "concierto",
    "fiestas", "festividad", "actos", "taurino",
]


def is_promising_pdf(url: str, link_text: str, context_text: str) -> bool:
    """
    Evalúa heurísticamente si un PDF parece contener información de fiestas.
    Se llama ANTES de descargar el archivo.
    """
    text_to_check = f"{url} {link_text} {context_text}".lower()

    for kw in _FIESTA_KEYWORDS:
        if kw in text_to_check:
            return True

    # También aceptar PDFs con año en el nombre (programa-2026.pdf)
    if re.search(r"20\d{2}", url):
        # Si tiene año en la URL, es más probable que sea un programa
        for kw in ["programa", "cartel", "fiesta", "feria", "actos"]:
            if kw in url.lower():
                return True

    return False


def is_promising_image(url: str, alt_text: str, locality_names: list[str]) -> bool:
    """
    Evalúa heurísticamente si una imagen puede ser un cartel de fiestas.
    Filtra logos, iconos, favicons y banners conocidos.
    Se llama ANTES de descargar la imagen.
    """
    url_lower = url.lower()

    # 1. Verificar extensión válida
    has_valid_ext = False
    for ext in IMAGE_VALID_EXTENSIONS:
        if ext in url_lower:
            has_valid_ext = True
            break
    if not has_valid_ext:
        # SVGs, GIFs pequeños, etc. → no son carteles
        return False

    # 2. Excluir patrones conocidos de no-carteles
    url_and_alt = url_lower + " " + alt_text.lower()
    for pattern in IMAGE_EXCLUDED_PATTERNS:
        if pattern in url_and_alt:
            return False

    # 3. Bonus: si el alt text o URL mencionan fiestas o la localidad → sí
    for kw in _FIESTA_KEYWORDS:
        if kw in url_and_alt:
            return True

    for loc in locality_names:
        if loc.lower() in url_and_alt:
            return True

    # 4. Si pasó los filtros negativos pero no tiene keywords positivos,
    #    aceptar igualmente (puede ser un cartel sin texto descriptivo en el alt)
    return True


# ─────────────────────────────────────────────
# Extracción de texto
# ─────────────────────────────────────────────

def extract_text_from_image(image_bytes: bytes) -> str:
    """Extrae texto de una imagen usando Tesseract OCR, con filtrado por dimensiones."""
    try:
        image = Image.open(io.BytesIO(image_bytes))

        # Filtrar por dimensiones mínimas
        width, height = image.size
        if width < IMAGE_MIN_WIDTH or height < IMAGE_MIN_HEIGHT:
            logger.debug(f"Imagen descartada por dimensiones: {width}x{height}")
            return ""

        # Aplicar OCR
        text = pytesseract.image_to_string(image, lang="spa")
        text = text.strip()

        # Si el OCR no extrajo texto significativo, descartar
        if len(text) < 20:
            return ""

        logger.debug(f"OCR extraído ({len(text)} chars) de imagen {width}x{height}")
        return text

    except Exception as e:
        logger.warning(f"Error OCR en imagen: {e}")
        return ""


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extrae texto de un PDF. Si es escaneado, usa OCR (hasta N páginas)."""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            ocr_pages_count = 0
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text and len(page_text.strip()) > 50:
                    text += page_text + "\n"
                else:
                    # PDF escaneado — aplicar OCR con límite
                    if ocr_pages_count >= PDF_MAX_PAGES_OCR:
                        logger.debug(f"Límite de OCR alcanzado en página {page_num}")
                        continue
                    try:
                        im = page.to_image(resolution=150)
                        pil_img = im.original
                        page_text_ocr = pytesseract.image_to_string(pil_img, lang="spa")
                        if page_text_ocr and len(page_text_ocr.strip()) > 20:
                            text += page_text_ocr + "\n"
                            ocr_pages_count += 1
                    except Exception as e:
                        logger.warning(f"Error OCR en página {page_num} del PDF: {e}")

        result = text.strip()
        if result:
            logger.debug(f"PDF extraído: {len(result)} caracteres")
        return result

    except Exception as e:
        logger.warning(f"Error procesando PDF: {e}")
        return ""

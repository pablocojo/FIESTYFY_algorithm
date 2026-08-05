"""
Módulo de extracción de documentos (PDFs e imágenes/carteles).
Incluye filtrado inteligente pre-descarga/OCR para evitar procesar
logos, iconos y documentos irrelevantes.
"""

import io
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger("document_extractor")

# Pool dedicado para tareas OCR para no saturar CPU global
ocr_executor = ThreadPoolExecutor(max_workers=4)


def _discover_tesseract_path() -> str | None:
    """Busca un ejecutable de Tesseract en rutas locales del proyecto, PATH y ubicaciones comunes."""
    import sys
    
    env_path = os.environ.get("TESSERACT_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 1. Priorizar el binario nativo del SO (ej. /usr/bin/tesseract en Linux/WSL)
    # Esto evita problemas de rutas (/tmp/...) al llamar un .exe desde Linux
    native_bin = shutil.which("tesseract")
    if native_bin:
        return native_bin

    # 2. Si estamos en Windows, buscar en lugares comunes
    candidates: list[str] = []
    
    current_file = Path(__file__).resolve()
    project_roots = [
        current_file.parent.parent,
        current_file.parent.parent.parent,
        current_file.parents[2],
    ]

    for project_root in project_roots:
        for relative_path in [
            Path("tools/tesseract/tesseract.exe"),
            Path("tools/Tesseract-OCR/tesseract.exe"),
            Path("Tesseract-OCR/tesseract.exe"),
        ]:
            candidates.append(str(project_root / relative_path))

    for path_entry in os.environ.get("PATH", "").split(os.pathsep):
        if path_entry:
            candidates.append(os.path.join(path_entry, "tesseract.exe"))

    for common_path in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ]:
        candidates.append(os.path.expandvars(common_path))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.normpath(candidate)

    return shutil.which("tesseract.exe")


def _discover_tessdata_prefix(tesseract_cmd: str | None) -> str | None:
    """Intenta localizar la carpeta tessdata cercana al ejecutable de Tesseract."""
    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix and os.path.isdir(env_prefix):
        return env_prefix

    if not tesseract_cmd:
        return None

    tesseract_dir = Path(tesseract_cmd).resolve().parent
    for candidate_dir in [
        tesseract_dir / "tessdata",
        tesseract_dir.parent / "tessdata",
        Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
        Path(r"C:\Users\%USERNAME%\AppData\Local\Programs\Tesseract-OCR\tessdata"),
    ]:
        resolved = os.path.expandvars(str(candidate_dir))
        if os.path.isdir(resolved):
            return resolved

    return None


try:
    from PIL import Image

    tesseract_cmd = _discover_tesseract_path()
    if tesseract_cmd:
        tessdata_prefix = _discover_tessdata_prefix(tesseract_cmd)
        if tessdata_prefix:
            os.environ["TESSDATA_PREFIX"] = tessdata_prefix

        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    else:
        pytesseract = None
except ImportError:
    Image = None
    pytesseract = None  # Dependencias que el usuario debe instalar

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from config import (
    IMAGE_MIN_SIZE_BYTES,
    IMAGE_MIN_WIDTH,
    IMAGE_MIN_HEIGHT,
    IMAGE_EXCLUDED_PATTERNS,
    IMAGE_VALID_EXTENSIONS,
    PDF_MAX_PAGES_OCR,
)

# ─────────────────────────────────────────────
# Filtros de relevancia (pre-descarga)
# ─────────────────────────────────────────────

# Keywords que indican contenido de fiestas (castellano y cooficiales)
_FIESTA_KEYWORDS = [
    # Castellano
    "fiesta", "festejo", "programa", "cartel", "feria", "carnaval",
    "romeria", "patronal", "navidad", "semana santa", "programacion",
    "verbena", "pregon", "encierro", "orquesta", "concierto",
    "fiestas", "festividad", "actos", "taurino",
    # Catalán / Valenciano / Balear
    "festes", "festa major", "cartell", "programacio", "revetlla", "correfoc", "cercavila",
    # Euskera
    "jaiak", "jaia", "jai", "egitaraua", "festak", "kartela", "txosna", "txosnak", "kontzertua", "erromeria", "kalejira",
    # Gallego
    "festas", "romaria", "foliada", "verbenas", "patronais",
    # Aranés
    "hèsta", "hèstes", "patronaus",
]


def is_promising_pdf(url: str, link_text: str, context_text: str, target_year: int = 2026) -> bool:
    """
    Evalúa heurísticamente si un PDF parece contener información de fiestas.
    Verifica explícitamente el año objetivo (2026 por defecto) y el año anterior (2025)
    en lugar de aceptar cualquier año 20xx arbitrario.
    Se llama ANTES de descargar el archivo.
    """
    text_to_check = f"{url} {link_text} {context_text}".lower()

    valid_years = {str(target_year), str(target_year - 1)}
    years_found = set(re.findall(r"20\d{2}", text_to_check))

    # Si contiene años 20xx, debe incluir al menos el año objetivo o el anterior
    if years_found and not years_found.intersection(valid_years):
        return False

    for kw in _FIESTA_KEYWORDS:
        if kw in text_to_check:
            return True

    # También aceptar si contiene un año válido en la URL con keywords secundarias
    if any(y in url for y in valid_years):
        for kw in ["programa", "cartel", "fiesta", "feria", "actos", "festes", "cartell", "jaiak", "egitaraua", "festas", "hèsta"]:
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

def _run_ocr(image) -> str:
    """Intenta ejecutar OCR multilingüe, con fallback al idioma por defecto si falta el paquete."""
    if not pytesseract:
        logger.warning("pytesseract no disponible: Tesseract OCR no está configurado correctamente.")
        return ""

    try:
        return pytesseract.image_to_string(image, lang="spa+eus+cat+glg")
    except Exception as e:
        if "Failed loading language" in str(e) or "TESSDATA_PREFIX" in str(e):
            logger.debug("Idiomas solicitados no encontrados en Tesseract. Usando idioma por defecto.")
            return pytesseract.image_to_string(image)
        raise e


def extract_text_from_image(image_bytes: bytes) -> str:
    """Extrae texto de una imagen usando Tesseract OCR, con filtrado por dimensiones."""
    if Image is None:
        logger.warning("No se puede extraer texto de la imagen porque PIL (Pillow) no está instalado.")
        return ""
    try:
        image = Image.open(io.BytesIO(image_bytes))

        # Filtrar por dimensiones mínimas
        width, height = image.size
        if width < IMAGE_MIN_WIDTH or height < IMAGE_MIN_HEIGHT:
            logger.debug(f"Imagen descartada por dimensiones: {width}x{height}")
            return ""

        # Aplicar OCR
        text = _run_ocr(image)
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
    if pdfplumber is None:
        logger.warning("No se puede extraer texto del PDF porque pdfplumber no está instalado.")
        return ""
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
                        page_text_ocr = _run_ocr(pil_img)
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

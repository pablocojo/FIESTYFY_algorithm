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
    DISPOSICION_ENABLED,
    PDF_MAX_PAGES_VLM,
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


# Documentos administrativos: nunca contienen programas de fiestas, pero suelen
# llevar un año válido y colgar de páginas cuyo menú menciona "fiestas". El PDF
# ANEXO_3_Ppto_2025.pdf del Ayuntamiento de Amurrio (tablas de partidas
# presupuestarias) llegó así a copar el 100% del contexto del LLM.
_PDF_ADMINISTRATIVO = re.compile(
    r"(?:^|[/_\-.])"
    r"(?:ppto|presupuesto|presupuestos|anexo|anexos|ordenanza|ordenanzas|"
    r"acta|actas|pleno|plenos|padron|licitacion|licitaciones|contrato|contratos|"
    r"contratacion|subvencion|subvenciones|convenio|convenios|memoria|"
    r"cuenta|cuentas|balance|liquidacion|tasa|tasas|impuesto|impuestos|"
    r"bop|boe|bopv|edicto|edictos|reglamento|estatuto|estatutos|"
    r"pgou|urbanismo|catastro|nomina|nominas|factura|facturas|"
    r"auditoria|interventor|tesoreria|rpt|organigrama|"
    r"instancia|solicitud|formulario|declaracion|modelo)"
    r"(?:$|[/_\-.0-9])",
    re.IGNORECASE,
)

# Términos festivos FUERTES: si uno de estos aparece en la URL o en el texto del
# enlace, el PDF es candidato aunque el nombre suene administrativo.
_FIESTA_KEYWORDS_FUERTES = [
    "fiesta", "fiestas", "festejo", "patronal", "patronales", "cartel", "carnaval",
    "romeria", "verbena", "pregon", "chupinazo", "encierro",
    "festes", "festa major", "cartell", "revetlla", "correfoc", "cercavila",
    "jaiak", "jaia", "egitaraua", "festak", "kartela", "txosna", "erromeria",
    "festas", "romaria", "foliada", "patronais", "hèsta", "hèstes", "patronaus",
]


def _normalizar_ascii(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def is_promising_pdf(url: str, link_text: str, context_text: str, target_year: int = 2026) -> bool:
    """
    Evalúa heurísticamente si un PDF parece contener información de fiestas.
    Se llama ANTES de descargar el archivo.

    El orden de las reglas importa. Antes, un PDF administrativo pasaba el filtro
    con solo contener un año válido y colgar de una página cuyo menú mencionase
    "fiestas", porque `context_text` eran los primeros caracteres de la portada
    del ayuntamiento. Ahora:

      1. Nombre de fichero administrativo sin término festivo -> se rechaza.
      2. Si menciona años y ninguno es el objetivo ni el anterior -> se rechaza.
      3. Término festivo fuerte en la URL o en el texto del enlace -> se acepta.
      4. Término festivo en el contexto del enlace MÁS un año válido -> se acepta.
      5. Año válido en la URL con una palabra secundaria -> se acepta.
    """
    url_l = _normalizar_ascii(url)
    enlace_l = _normalizar_ascii(link_text)
    contexto_l = _normalizar_ascii(context_text)
    url_y_enlace = f"{url_l} {enlace_l}"

    valid_years = {str(target_year), str(target_year - 1)}

    # 1. Documento administrativo (se juzga por el nombre del fichero, no por la
    #    página que lo enlaza), salvo que él mismo se anuncie como festivo.
    nombre_fichero = url_l.rsplit("/", 1)[-1]
    if _PDF_ADMINISTRATIVO.search(nombre_fichero) and not any(
        kw in url_y_enlace for kw in _FIESTA_KEYWORDS_FUERTES
    ):
        return False

    # 2. Coherencia temporal.
    years_found = set(re.findall(r"20\d{2}", f"{url_l} {enlace_l} {contexto_l}"))
    if years_found and not years_found.intersection(valid_years):
        return False

    # 3. Evidencia fuerte: el propio enlace se anuncia como festivo.
    if any(kw in url_y_enlace for kw in _FIESTA_KEYWORDS_FUERTES):
        return True

    # 4. Evidencia débil (el contexto alrededor del enlace) solo cuenta si además
    #    hay un año válido: evita aceptar cualquier PDF de una página de fiestas.
    if any(kw in contexto_l for kw in _FIESTA_KEYWORDS):
        if any(y in f"{url_l} {enlace_l} {contexto_l}" for y in valid_years):
            return True
        return False

    # 5. Año válido en la URL más una palabra secundaria en la URL.
    if any(y in url_l for y in valid_years):
        for kw in ["programa", "cartel", "fiesta", "feria", "actos", "festes",
                   "cartell", "jaiak", "egitaraua", "festas", "hesta", "agenda"]:
            if kw in url_l:
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


def extract_text_from_image(image_bytes: bytes) -> tuple[str, list]:
    """Extrae texto de una imagen usando Tesseract OCR, con filtrado por dimensiones."""
    if Image is None:
        logger.warning("No se puede extraer texto de la imagen porque PIL (Pillow) no está instalado.")
        return "", []
    try:
        image = Image.open(io.BytesIO(image_bytes))

        width, height = image.size
        if width < IMAGE_MIN_WIDTH or height < IMAGE_MIN_HEIGHT:
            return "", []

        text = _run_ocr(image)
        text = text.strip()

        if len(text) < 20:
            return "", []
            
        images_for_vlm = []
        text_lower = text.lower()
        if any(kw in text_lower for kw in _FIESTA_KEYWORDS):
            images_for_vlm.append(image.copy())

        return text, images_for_vlm

    except Exception as e:
        logger.warning(f"Error OCR en imagen: {e}")
        return "", []


def _reconstruir_si_multicolumna(page, page_text: str, page_num: int) -> str:
    """
    Devuelve la página reconstruida por columnas si lo es, o el texto tal cual.

    La reconstrucción solo se aplica cuando se detectan varias columnas: en un
    documento lineal el texto plano ya está en orden de lectura y tocarlo no
    aportaría nada. Si algo falla se devuelve el texto original: esta mejora
    nunca debe poder dejar una página sin extraer.
    """
    if not DISPOSICION_ENABLED:
        return page_text
    try:
        from disposicion_pdf import extraer_pagina_estructurada, merece_reconstruccion

        estructurado, metricas = extraer_pagina_estructurada(page)
        if estructurado and merece_reconstruccion(metricas):
            logger.info(
                f"    [DISPOSICIÓN] Página {page_num + 1}: {metricas['columnas']} columnas, "
                f"{metricas['cabeceras_dia']} días; reconstruida en orden de lectura."
            )
            return estructurado
    except Exception as e:
        logger.debug(f"No se pudo reconstruir la disposición de la página {page_num}: {e}")
    return page_text


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, list]:
    """Extrae texto de un PDF. Si es escaneado, usa OCR (hasta N páginas)."""
    if pdfplumber is None:
        logger.warning("No se puede extraer texto del PDF porque pdfplumber no está instalado.")
        return "", []
    text = ""
    images_for_vlm = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            ocr_pages_count = 0
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()

                if page_text and len(page_text.strip()) > 50:
                    # ── Página con texto extraíble: NO invocar Ghostscript ──
                    # `extract_text()` lee por filas horizontales. En un cartel de
                    # varias columnas eso pega en la misma línea actos de columnas
                    # y días distintos, y el modelo los atribuye al día que no es.
                    # Si la página resulta ser multicolumna se sustituye por la
                    # versión reconstruida en orden de lectura.
                    page_text = _reconstruir_si_multicolumna(page, page_text, page_num)
                    text += page_text + "\n"
                    if len(images_for_vlm) < PDF_MAX_PAGES_VLM and any(kw in page_text.lower() for kw in _FIESTA_KEYWORDS):
                        try:
                            im = page.to_image(resolution=150)
                            images_for_vlm.append(im.original.copy())
                        except Exception as e:
                            logger.debug(f"No se pudo renderizar página {page_num} para VLM: {e}")
                else:
                    # ── Página sin texto (escaneada): renderizar para OCR ──
                    if ocr_pages_count >= PDF_MAX_PAGES_OCR:
                        continue
                    try:
                        im = page.to_image(resolution=150)
                        page_image = im.original.copy()
                    except Exception as e:
                        logger.debug(f"No se pudo renderizar página {page_num} para OCR: {e}")
                        continue
                    try:
                        page_text_ocr = _run_ocr(page_image)
                        if page_text_ocr and len(page_text_ocr.strip()) > 20:
                            text += page_text_ocr + "\n"
                            ocr_pages_count += 1
                            if any(kw in page_text_ocr.lower() for kw in _FIESTA_KEYWORDS):
                                if len(images_for_vlm) < PDF_MAX_PAGES_VLM:
                                    images_for_vlm.append(page_image)
                    except Exception as e:
                        logger.warning(f"Error OCR en página {page_num} del PDF: {e}")

        result = text.strip()
        return result, images_for_vlm

    except Exception as e:
        logger.warning(f"Error procesando PDF: {e}")
        return "", []

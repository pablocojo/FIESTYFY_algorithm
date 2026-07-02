# config.py
"""
Configuración global para scraper de lugares españoles (FASE 1).
Incluye URLs, parámetros LLM, timeouts y rutas de salida.
"""

# ============================================================================
# ENDPOINT Y CABECERAS PARA LLM (Local via LM Studio)
# ============================================================================
LMSTUDIO_API = "http://localhost:1234/v1/chat/completions"
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 1800  # Segundos para timeouts de llamadas al LLM

# ============================================================================
# URLs DE WIKIPEDIA - NUEVAS CATEGORÍAS RAÍZ (LUGAR-CÉNTRICO)
# ============================================================================
BASE_WIKI_URL = "https://es.wikipedia.org/wiki/"
BASE_COMMONS_URL = "https://commons.wikimedia.org/"
BASE_COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Categorías raíz para extraer lugares base
MUNICIPIOS_CATEGORY_URL = (
    "https://es.wikipedia.org/wiki/Categor%C3%ADa:Municipios_de_Espa%C3%B1a_por_provincia"
)
DISTRITOS_CATEGORY_URL = (
    "https://es.wikipedia.org/wiki/Categor%C3%ADa:Distritos_de_Espa%C3%B1a"
)
PEDANIAS_CATEGORY_URL = (
    "https://es.wikipedia.org/wiki/Categor%C3%ADa:Pedan%C3%ADas_de_Espa%C3%B1a_por_provincia"
)

# Antiguos (para legacy, si es necesario)
ROOT_CATEGORY_URL = (
    "https://es.wikipedia.org/wiki/Categor%C3%ADa:Barrios_de_Espa%C3%B1a_por_localidad"
)

# ============================================================================
# PARÁMETROS DE LLM
# ============================================================================
LLM_MODEL_NAME = "qwen2.5-14b-instruct"
LLM_TEMPERATURE = 0.4
# Máximo tokens de snippet que enviamos al LLM para evitar overflow de contexto
MAX_SNIPPET_TOKENS = 7800


# ============================================================================
# PARÁMETROS DE SCRAPING Y BÚSQUEDA DE IMÁGENES
# ============================================================================
REQUEST_TIMEOUT = 30  # Segundos para peticiones HTTP a Wikipedia

# Parámetros para búsqueda de imágenes en Wikimedia Commons
COMMONS_SEARCH_IMAGE_TYPE = "photo"  # or "drawing"
COMMONS_SEARCH_TIMEOUT = 20  # Segundos para API de Commons
COMMONS_FALLBACK_IMAGE = "https://picsum.photos/seed/{id}/1200/400"  # Placeholder para banners
COMMONS_FALLBACK_LOGO = "https://picsum.photos/seed/{id}-logo/160/160"  # Placeholder para logos

# Patrones de búsqueda para escudos en Commons (por provincia/municipio)
ESCUDO_SEARCH_PATTERN = "Escudo de {nombre}"
BANNER_SEARCH_KEYWORDS = ["panorama", "vista", "ciudad", "pueblo"]

# ============================================================================
# PARÁMETROS DE CLASIFICACIÓN Y ESTRUCTURA
# ============================================================================
# Umbrales de población (definen pueblo/ciudad_pequena/ciudad_grande)
POBLACION_PUEBLO_MAX = 10000
POBLACION_CIUDAD_PEQUENA_MAX = 40000
# > 40000 es ciudad_grande

# Umbral mínimo de confianza del LLM para clasificar como municipio_compuesto
# Deliberadamente alto: ante la duda, NO es compuesto
COMPUESTO_MIN_CONFIDENCE = 0.90

# Umbral mínimo de población para considerar un lugar válido
POBLACION_MINIMA = 100

# Parametros para validaciones
MIN_POBLACION_BARRIO = 20
MIN_WIKIPEDIA_HTML_LENGTH = 100

DESC_CORTA_MIN_WORDS = 10
DESC_CORTA_MAX_WORDS = 15
DESC_LARGA_MIN_WORDS = 40
DESC_LARGA_MAX_WORDS = 50

# ============================================================================
# PATHS DE SALIDA
# ============================================================================
MUNICIPIOS_JSON = "municipios.json"
OUTPUT_JSON = "lugares_espana.json"  # Dataset final con municipios y subdivisiones
ERROR_LOG_FILE = "lugares_espana_error_log.txt"
MUNICIPIOS_COMPUESTOS_REF = "municipios_compuestos_referencia.json"  # Tabla de referencia (opcional)

# API de Wikipedia y logs para Fase 1.5 (validación de compuestos)
WIKIPEDIA_API_URL = "https://es.wikipedia.org/w/api.php"
VALIDACION_COMPUESTOS_LOG = "validacion_compuestos_log.txt"
INFORME_CAMBIOS_COMPUESTOS = "cambios_municipios_compuestos.md"

# ============================================================================
# PARÁMETROS DE CONTROL DE EJECUCIÓN
# ============================================================================
# Delay entre peticiones (en segundos) para no sobrecargar Wikipedia
DELAY_BETWEEN_REQUESTS = 2

# Número máximo de reintentos para LLM si falla
MAX_LLM_RETRIES = 3

# Verbosity
DEBUG_MODE = False  # Si True, imprime más detalles
SAVE_INTERMEDIATE = False  # Si True, guarda snapshots cada N lugares

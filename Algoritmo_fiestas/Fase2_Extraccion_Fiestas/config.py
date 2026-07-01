"""
Configuración centralizada para la Fase 2 del Algoritmo Fiestyfy.
Todas las constantes y parámetros ajustables se definen aquí.
"""

# ─────────────────────────────────────────────
# SPIDER (Crawler de Dos Pasadas)
# ─────────────────────────────────────────────
SPIDER_MAX_MAPPING_PAGES = 1000       # Páginas a mapear en Pasada 1
SPIDER_MAX_EXTRACTION_PAGES = 70      # Top N páginas para extracción pesada
SPIDER_MAX_INTERNAL_DEPTH = 8         # Profundidad máxima de enlaces internos
SPIDER_MAX_EXTERNAL_DEPTH = 3         # Profundidad máxima de enlaces externos
SPIDER_CONCURRENCY = 10               # Peticiones HTTP concurrentes dentro del spider
SPIDER_DELAY_SECONDS = 0.15           # Delay entre peticiones al mismo dominio
SPIDER_REQUEST_TIMEOUT = 8            # Timeout por petición HTTP (segundos)
SPIDER_RETRIES = 3                    # Reintentos para errores transitorios
SPIDER_RETRY_BACKOFF = 1.5            # Factor de backoff para reintentos

# ─────────────────────────────────────────────
# FILTRADO DE DOCUMENTOS (Pre-OCR)
# ─────────────────────────────────────────────
IMAGE_MIN_SIZE_BYTES = 30_000         # Tamaño mínimo de imagen para OCR (30 KB)
IMAGE_MIN_WIDTH = 300                 # Ancho mínimo en píxeles
IMAGE_MIN_HEIGHT = 200                # Alto mínimo en píxeles
IMAGE_EXCLUDED_PATTERNS = [           # Patrones en URL/nombre a excluir
    "logo", "icon", "favicon", "banner", "header", "sprite",
    "thumb", "avatar", "footer", "widget", "button", "arrow",
    "bullet", "social", "share", "flag", "badge", "pixel",
    "tracking", "analytics", "1x1", "spacer", "blank",
]
IMAGE_VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
PDF_MAX_PAGES_OCR = 20                # Máximo de páginas a OCR en un PDF escaneado

# ─────────────────────────────────────────────
# BÚSQUEDA EXTERNA (DuckDuckGo)
# ─────────────────────────────────────────────
DDG_DELAY_BETWEEN_QUERIES = 2.0       # Delay entre queries (segundos)

# ─────────────────────────────────────────────
# Configuración de Extracción Web y RAG
# ─────────────────────────────────────────────
RAG_MAX_TOKENS = 8000                 # Balance ideal: rápido para un 7B, pero suficiente contexto
RAG_CHARS_PER_TOKEN = 3.3             # Aproximación de caracteres por token
RAG_CHUNK_SIZE = 1200
RAG_CHUNK_OVERLAP = 200
RAG_EMBEDDING_BATCH_SIZE = 20

# Configuración DuckDuckGo / Yahoo Scraper
DDG_MAX_RESULTS = 7
DDG_MAX_URLS_TO_FOLLOW = 5
DDG_CONTENT_MAX_CHARS = 15000         # Límite de texto por página
DDG_REQUEST_TIMEOUT = 10
DDG_MAX_RETRIES = 3
DDG_RETRY_BACKOFF = 3.0

# ─────────────────────────────────────────────
# LM STUDIO
# ─────────────────────────────────────────────
LMSTUDIO_BASE_URL = "http://localhost:1234"
LMSTUDIO_EMBEDDING_URL = f"{LMSTUDIO_BASE_URL}/v1/embeddings"
LMSTUDIO_CHAT_URL = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"

LMSTUDIO_EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"
LMSTUDIO_CHAT_MODEL = "qwen2.5-7b-instruct"
LMSTUDIO_CHAT_TIMEOUT = 900           # Timeout para peticiones de chat (segundos)
LMSTUDIO_EMBEDDING_TIMEOUT = 30       # Timeout para embeddings (segundos)
LMSTUDIO_CHAT_TEMPERATURE = 0.0       # Temperatura 0.0 para evitar alucinaciones
LMSTUDIO_CHAT_MAX_TOKENS = 1500       # Límite duro para truncar bucles

# ─────────────────────────────────────────────
# ORQUESTADOR
# ─────────────────────────────────────────────
PARALLEL_MUNICIPALITIES = 2           # Municipios procesados en paralelo
MAX_LOCALITY_CONCURRENCY = 8          # Máximo de localidades en vuelo simultáneo

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)-20s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL = "INFO"

# ─────────────────────────────────────────────
# USER-AGENT
# ─────────────────────────────────────────────
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

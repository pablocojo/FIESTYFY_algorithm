"""
Configuración centralizada para la Fase 2 del Algoritmo Fiestyfy.
Todas las constantes y parámetros ajustables se definen aquí.
"""

import os

# ─────────────────────────────────────────────
# SPIDER (Crawler de Dos Pasadas)
# ─────────────────────────────────────────────
SPIDER_MAX_MAPPING_PAGES = 1000       # Páginas a mapear en Pasada 1
SPIDER_MAX_EXTRACTION_PAGES = 70      # Top N páginas para extracción pesada
SPIDER_MAX_INTERNAL_DEPTH = 8         # Profundidad máxima de enlaces internos
SPIDER_MAX_EXTERNAL_DEPTH = 3         # Profundidad máxima de enlaces externos
SPIDER_CONCURRENCY = 30               # Aprovechar los 16 hilos del equipo para peticiones concurrentes
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
DDG_DELAY_MIN = 2.0                   # Delay mínimo entre queries (segundos)
DDG_DELAY_MAX = 4.5                   # Delay máximo entre queries (segundos)
DDG_DELAY_BETWEEN_QUERIES = 2.0       # Delay entre queries (mantenido por compatibilidad)

# ─────────────────────────────────────────────
# Configuración de Extracción Web y RAG
# ─────────────────────────────────────────────
RAG_MAX_TOKENS = 30000                # Aprovecha al máximo la ventana de 32k del modelo
RAG_CHARS_PER_TOKEN = 2.6             # Ratio real medido con texto web scrapeado (URLs y números tokenizan mal)
RAG_CHUNK_SIZE = 1200                 # Tamaño objetivo de chunk (los cortes respetan frases/líneas)
RAG_CHUNK_OVERLAP = 200               # (ya no se usa para cortar a ciegas; se mantiene por compatibilidad)
RAG_EMBEDDING_BATCH_SIZE = 50
RAG_PROGRAMA_MAX_CHARS = 8000
RAG_UMBRAL_SIMILITUD = 0.35           # Similitud mínima para considerar relevante un chunk
RAG_MIN_OFICIALES_SIN_UMBRAL = 5      # Si ningún chunk oficial supera el umbral, incluir al menos los N mejores

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

LMSTUDIO_EMBEDDING_MODEL = "text-embedding-baai-bge-m3-568m"
LMSTUDIO_CHAT_MODEL = "qwen2.5-7b-instruct"
LMSTUDIO_CHAT_TIMEOUT = 900           # Timeout para peticiones de chat (segundos)
LMSTUDIO_EMBEDDING_TIMEOUT = 30       # Timeout para embeddings (segundos)
LMSTUDIO_CHAT_TEMPERATURE = 0.0       # Temperatura 0.0 para evitar alucinaciones
LMSTUDIO_CHAT_MAX_TOKENS = -1         # Sin límite: el modelo para cuando completa el JSON (evita truncamiento)

# ─────────────────────────────────────────────
# SANTO PATRÓN
# ─────────────────────────────────────────────
PATRON_SEARCH_ENABLED = True          # Buscar el santo patrón de cada localidad
PATRON_CACHE_FILE = "patrones_cache.json"  # Caché de patrones (en la carpeta Fase2)
PATRON_MAX_URLS = 3                   # URLs de buscadores a seguir para hallar el patrón
PATRON_LLM_MAX_TOKENS = 200           # Tokens máximos para la extracción LLM del patrón

# ─────────────────────────────────────────────
# FILTRO ADAPTATIVO DE FIESTAS
# ─────────────────────────────────────────────
FIESTA_MAX_DURACION_DIAS = 30         # Duración máxima razonable de una fiesta (días)
FILTRO_MIN_EVENTOS_PROGRAMA = 2       # Eventos mínimos del programa para aceptar multi-día sin señales

# ─────────────────────────────────────────────
# REDES SOCIALES
# ─────────────────────────────────────────────
SOCIAL_CONTENT_CACHE_FILE = "rrss_contenido_cache.json"      # Caché de posts leídos de las apps (Etapa C)
SOCIAL_PROFILE_DISCOVERY_ENABLED = True                      # Cosechar perfiles oficiales desde las webs
SOCIAL_PROFILE_CACHE_FILE = "redes_sociales_cache.json"      # Caché de perfiles (fuente de verdad; se
                                                             # vuelca a lugares_espana.json con sync_redes_a_lugares.py)

# ─────────────────────────────────────────────
# RUNNER DE APPS DE ESCRITORIO (social_apps_runner.py — PC dedicado)
# ─────────────────────────────────────────────
# Localización de las ventanas de las apps YA ABIERTAS (el runner nunca lanza
# ni cierra aplicaciones). Ajustar con `py social_apps_runner.py --modo diagnostico`.
# NOTA: las 3 redes (Instagram, Facebook, X) corren como pestañas/ventanas de Chrome.
# Cada red debe estar en una ventana Chrome distinta con su nombre visible en el título.
SOCIAL_APPS_VENTANAS = {
    "instagram": {
        "titulo_re": r"(?i)instagram",
        "procesos": ["msedge.exe", "chrome.exe", "instagram.exe", "applicationframehost.exe"],
    },
    "facebook": {
        "titulo_re": r"(?i)facebook",
        "procesos": ["msedge.exe", "chrome.exe", "facebook.exe", "fbwin32.exe", "applicationframehost.exe"],
    },
    "twitter": {  # X instalada como app web o en pestaña de Edge/Chrome
        "titulo_re": r"(?i)(^x$|[\s/]x($|[\s\-])|x\.com|twitter)",
        "procesos": ["msedge.exe", "chrome.exe", "msedgewebview2.exe"],
    },
}
SOCIAL_MAX_POSTS_PER_PROFILE = 30     # Posts máximos a leer por perfil
SOCIAL_MAX_SCROLLS = 15               # Scrolls máximos por perfil
SOCIAL_MAX_MINUTES_PER_PROFILE = 3    # Tiempo máximo por perfil (minutos)
SOCIAL_POST_MONTHS_BACK = 12          # Ventana temporal de posts: NADA de hace 1 año o más
SOCIAL_CONTENT_TTL_DIAS = 30          # No releer un perfil leído hace menos de N días
SOCIAL_CAPTURAS_DIR = "rrss_capturas" # Carpeta de capturas de posts (para el VLM de la Etapa D)
SOCIAL_GUARD_MAX_ANOMALIAS = 8        # Cambios de foco tolerados antes de abortar la fase
SOCIAL_GUARD_MAX_ESPERA_FOCO = 120    # Segundos máximos en pausa esperando recuperar el foco

# ─────────────────────────────────────────────
# VISIÓN (VLM local para capturas de RRSS — Etapa D)
# Solo interpreta imágenes procedentes de las apps de RRSS; las webs siguen con Tesseract.
# ─────────────────────────────────────────────
VISION_ENABLED = True
VISION_MODEL = "qwen_qwen2.5-vl-7b-instruct"   # Identificador del modelo de visión en LM Studio
VISION_TIMEOUT = 180                  # Timeout por imagen (segundos)
VISION_MAX_TOKENS = 1200              # Respuesta máxima (los programas largos necesitan espacio)
VISION_MAX_IMAGES_PER_PROFILE = 10    # Tope de imágenes por perfil y red
VISION_MAX_DIM = 1280                 # Redimensionado máximo antes de enviar al VLM

# ─────────────────────────────────────────────
# ORQUESTADOR
# ─────────────────────────────────────────────
PARALLEL_MUNICIPALITIES = 5           # Municipios procesados en paralelo
MAX_LOCALITY_CONCURRENCY = 16         # Empatar con los 16 hilos lógicos del procesador

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

# ─────────────────────────────────────────────
# SERVIDOR RRSS (comunicación WSL ↔ Windows)
# ─────────────────────────────────────────────
RRSS_SERVER_ENABLED = True                    # Activar comunicación con el servidor RRSS
RRSS_SERVER_PORT = 8787                       # Puerto del servidor en Windows
RRSS_SERVER_TIMEOUT = 300                     # Timeout por petición (seg; un perfil ≈ 1-2 min)

# ─────────────────────────────────────────────
# AUTO-DETECCIÓN WSL → WINDOWS
# Desde WSL, LM Studio y el servidor RRSS corren en el host Windows.
# Se usa la IP de la red local (LAN) para evitar los bloqueos del Firewall de Windows en la red de WSL.
# ─────────────────────────────────────────────
import platform as _platform
if _platform.system() == "Linux":
    import subprocess as _sp
    
    # 1. Intentar obtener la IP LAN de Windows ejecutando ipconfig.exe (interoperabilidad WSL)
    try:
        import re
        _ipconfig = _sp.check_output("ipconfig.exe", shell=True, text=True, stderr=_sp.DEVNULL)
        # Buscar la típica IP de red local (192.168.x.x o 10.x.x.x)
        _match = re.search(r"IPv4.*?:\s*(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)", _ipconfig)
        if _match:
            _win_ip = _match.group(1)
        else:
            _win_ip = "192.168.1.234"  # Fallback directo a la IP conocida
    except Exception:
        _win_ip = "192.168.1.234"
        
    # Permitir override por variable de entorno
    _win_ip = os.environ.get("WIN_HOST_IP", _win_ip)
    
    LMSTUDIO_BASE_URL = f"http://{_win_ip}:1234"
    LMSTUDIO_EMBEDDING_URL = f"{LMSTUDIO_BASE_URL}/v1/embeddings"
    LMSTUDIO_CHAT_URL = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"
    RRSS_SERVER_URL = f"http://{_win_ip}:{RRSS_SERVER_PORT}"
else:
    RRSS_SERVER_URL = f"http://localhost:{RRSS_SERVER_PORT}"


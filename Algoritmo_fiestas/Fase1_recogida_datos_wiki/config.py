# config.py

# Endpoint y cabeceras para LLM
LMSTUDIO_API = "http://localhost:1234/v1/chat/completions"
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 1800  # Segundos para timeouts de llamadas al LLM

# URLs de Wikipedia
BASE_WIKI_URL = "https://es.wikipedia.org/wiki/"
ROOT_CATEGORY_URL = (
    "https://es.wikipedia.org/wiki/"
    "Categor%C3%ADa:Barrios_de_Espa%C3%B1a_por_localidad"
)

# Parámetros de LLM
LLM_MODEL_NAME = "your/exact/model-name-from-lmstudio"
LLM_TEMPERATURE = 0.4
# Máximo tokens de snippet que enviamos al LLM para evitar overflow de contexto
MAX_SNIPPET_TOKENS = 6000

# Parámetros de scraping
REQUEST_TIMEOUT = 30  # Segundos para peticiones HTTP a Wikipedia

# Paths de salida
OUTPUT_JSON = "barrios_espana.json"
ERROR_LOG_FILE = "barrios_espana_error_log.txt"

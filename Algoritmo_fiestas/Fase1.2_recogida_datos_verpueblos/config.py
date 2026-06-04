# config.py
BASE_VER_PUEBLOS_URL = "https://www.verpueblos.com/"
ROOT_REGION_URL = BASE_VER_PUEBLOS_URL  # Página inicial con comunidad autónomas
OUTPUT_PUEBLOS_JSON = "pueblos.json"
ERROR_LOG_FILE = "errors_pueblos.log"
REQUEST_TIMEOUT = 30 
MAX_SNIPPET_TOKENS = 6000
LMSTUDIO_API = "http://localhost:1234/v1/chat/completions"
HEADERS = {"Content-Type": "application/json"}
LLM_MODEL_NAME = "your/exact/model-name-from-lmstudio"
LLM_TEMPERATURE = 0.4
TIMEOUT = 1800
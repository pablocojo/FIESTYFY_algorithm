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
PASS2_BATCH_SIZE = 5                  # Páginas procesadas en paralelo en la Pasada 2 (evita I/O idle)
MAX_IMAGES_PER_PAGE = 5               # Máximo de imágenes a OCR por página (evita webs turísticas)
# MAX_CALENDAR_SAME_BASE eliminado: tapaba las páginas de calendario a las 3
# primeras por orden de llegada, sin mirar la fecha, y eso descartaba los días
# reales de la fiesta. El spider ahora filtra por AÑO objetivo (sin límite de
# cantidad) en AsyncTwoPassSpider._extraer_anno_calendario.

# ─────────────────────────────────────────────
# FILTRADO DE DOCUMENTOS (Pre-OCR)
# ─────────────────────────────────────────────
IMAGE_MIN_WIDTH = 400
IMAGE_MIN_HEIGHT = 400
IMAGE_MIN_SIZE_BYTES = 50 * 1024  # 50 KB

# Configuración de PDFs
PDF_MAX_PAGES_OCR = 20  # Límite absoluto de páginas para extraer (texto plano o OCR ligero)
PDF_MAX_PAGES_VLM = 3   # Límite estricto de páginas enviadas al VLM (ahorro de GPU)

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
DDG_MAX_RESULTS = 7                   # (sin uso: el que manda es MIN_RESULTADOS_DESEADOS)
# Páginas que se descargan de entre los resultados de búsqueda, por localidad.
#
# Estaba en 5 y era el cuello de botella de todo el algoritmo: medido el
# 2026-08-23 sobre doce localidades, los buscadores devolvían 386 resultados y se
# descargaban 60 páginas, el 16%. El otro 84% existía solo como una línea de
# snippet, y de ahí venían casi todas las fiestas que no se encontraban.
#
# Descargar es lo más barato del proceso: bajar 5 URLs y 2 PDFs tardaba 7
# segundos, frente a los 122 que se van en RRSS y los 26 del rastreo de la web.
# Indexar lo descargado cuesta 39 segundos por cada 1000 chunks.
DDG_MAX_URLS_TO_FOLLOW = 25
DDG_CONTENT_MAX_CHARS = 40000         # Límite de texto por página. Con 15.000 se
                                      # cortaba por la mitad el PDF de un programa
                                      # de fiestas de cien actos.
DDG_REQUEST_TIMEOUT = 10
DDG_MAX_RETRIES = 3
DDG_RETRY_BACKOFF = 3.0

# Páginas que llegan sin cuerpo. Medido el 2026-08-27: la noticia que anunciaba
# las fiestas de Los Mardos se descargó entera y dejó 173 caracteres —el título
# y el pie de un plugin—, porque el cuerpo lo pinta JavaScript. La araña del
# municipio ya reintentaba con navegador; la ruta de búsqueda, no, y es por
# donde entran las noticias de prensa local, que son la fuente de las pedanías.
#
# El umbral va holgado a propósito: una página de programa nunca baja de 600
# caracteres, y renderizar cuesta unos dos segundos, así que conviene que salte
# poco. El tope por ejecución evita que una web rota se lleve el run entero.
BUSQUEDA_MIN_CHARS_PAGINA = 600
BUSQUEDA_MAX_RENDERS_NAVEGADOR = 15

# Un salto más: las páginas que PROMETEN el programa sin traerlo. Es el patrón
# de media España —el periódico comarcal publica la noticia, la noticia enlaza a
# la emisora o al ayuntamiento, y allí cuelga el PDF—. Medido el 2026-08-27 en
# `comarcamonastrell.com/programa-fiestas-san-roque-tobarra-2026`: la página no
# traía el programa sino «puedes obtener el documento PDF en la web oficial de
# Radio Tobarra», y el PDF estaba en `radiotobarra.es/sanroque26/`, dos puertas
# más allá de donde cayó el buscador.
#
# Los topes son bajos a propósito: es un salto, no un rastreo. El de los PDF,
# que ya existía, cubre el último tramo.
BUSQUEDA_SEGUIR_ENLACES = True
BUSQUEDA_MAX_ENLACES_POR_PAGINA = 3
BUSQUEDA_MAX_ENLACES_TOTAL = 8

# Descarga de las URLs de resultados. Medido el 2026-08-24 sobre las 7
# localidades de Tobarra, ya con el desglose por motivo: las páginas entraban
# bien (127 de 150, 85%) pero los PDF se perdían a la mitad (16 de 33), y casi
# todas las pérdidas eran `error_TimeoutError` —10 de las 10 de Aljubé, 4 de las
# 4 de Santiago de Mora—. Un PDF de programa pesa megas y no cabe en los 10
# segundos que valen para una página, y no había reintento ninguno. Duele
# porque el programa de actos vive justo ahí.
DESCARGA_MAX_INTENTOS = 3             # Intentos por URL antes de darla por perdida
DESCARGA_BACKOFF = 1.5                # Segundos de espera; se dobla en cada intento
DESCARGA_TIMEOUT_PDF = 30             # Los PDF necesitan más que una página
DESCARGA_TIMEOUT_MAX = 60             # Techo al ampliar el timeout entre intentos

# Caché en disco del texto ya extraído de cada URL. Existe por la varianza: con
# el mismo código, Cordovilla dio 25 documentos el 2026-08-23 y 4 el 2026-08-24.
# Sin un suelo estable no se puede medir si un cambio mejora las cosas.
CACHE_PAGINAS_ACTIVA = True
CACHE_PAGINAS_DIR = "caches/paginas"
CACHE_PAGINAS_TTL_DIAS = 7            # Lo descargado bien se reaprovecha una semana
CACHE_PAGINAS_TTL_MUERTAS_DIAS = 30   # Un 404 o un PDF sin texto no se arreglan solos
CACHE_BUSQUEDAS_TTL_DIAS = 3          # Los motores no devuelven dos veces la misma lista

# Comprobación de procedencia contra pueblos homónimos. Se le pide al modelo que
# extraiga dónde sitúa el texto al pueblo y en qué lengua está; decide el código.
# Solo se aplica a los documentos avalados únicamente por el nombre de la
# localidad: el 5% del total, donde se concentra todo el riesgo.
PROCEDENCIA_CHARS = 1200              # Trozo de cabecera que se examina (un chunk)
PROCEDENCIA_MAX_TOKENS = 90           # La respuesta es un JSON de tres campos

# Material mínimo para pedirle a un modelo el programa de una fiesta: que alguna
# página del contexto traiga al menos estos actos con hora de reloj.
#
# Medido el 2026-08-25 sobre los contextos reales de Tobarra. Cordovilla tenía 14
# en elfarodehellin.com y su ficha salió con 15 de 16 actos rastreables hasta su
# documento. Sierra tenía CERO en todas sus páginas, y produjo 39 actos
# inventados con confianza alta; Los Mardos, también cero, produjo 5 de los que
# no se pudo rastrear ninguno. Sin material el modelo no da datos flojos, da
# datos falsos, así que no se pierde nada por no preguntar.
#
# El umbral es bajo a propósito: no bloquea a Aljubé, Mora ni Santiago de Mora
# —6 a 9 actos con hora—, que sí tienen programa publicado aunque el modelo lo
# aproveche mal. Eso es otro problema y no se arregla filtrando.
ENRICHMENT_MIN_ACTOS_EN_PAGINA = 3

# ── Localizador de programa guiado por LLM (Program Locator Pass) ────────────
# Antes del enrichment, el LLM ve un resumen de las páginas candidatas y decide
# cuáles contienen el programa real. Si dice que la información no está completa
# y que hay que seguir un enlace, se descarga esa página y se vuelve a preguntar.
#
# Medido el 2026-08-27: los 4 fallos recuperables de la última ejecución
# (portada genérica, advocación cruzada, agregador SEO, URL externa no seguida)
# se deben todos a que `mejor_pagina_con_programa()` elige por regex sin
# comprensión semántica. Este paso pone al LLM a decidir ANTES de extraer actos.
PROGRAM_LOCATOR_ENABLED = True
PROGRAM_LOCATOR_SNIPPET_CHARS = 400    # Caracteres del extracto por candidata
PROGRAM_LOCATOR_MAX_CANDIDATES = 12    # Máximo de páginas a presentar al LLM
PROGRAM_LOCATOR_MAX_ITERATIONS = 2     # Máximo de rondas LLM (1ª selección + 1 profundización)
PROGRAM_LOCATOR_MAX_URLS_PER_ROUND = 5 # URLs a seguir por ronda si el LLM dice que faltan
PROGRAM_LOCATOR_MAX_TOKENS = 400       # Reserva de salida para la respuesta del localizador
PROGRAM_LOCATOR_DOWNLOAD_TIMEOUT = 15  # Timeout de descarga de URLs señaladas (segundos)

# Descubrimiento por meses. Antes se preguntaba una vez por localidad sobre
# 20.000 caracteres, que en Tobarra son 23 chunks de 189 (12%) y en Aranda 23 de
# 415 (6%): el paso que decide qué fiestas existen era el que menos material
# veía. Con un corte tan estrecho, cualquier reordenación pequeña cambiaba lo que
# entraba —entre dos ejecuciones del 2026-08-26 con el mismo material, Tobarra
# pasó de 4 fiestas a 2 y perdió la del Cristo, que tiene 50 actos—.
DISCOVERY_MIN_CHUNKS_MES_PROPIO = 3   # Con menos, el mes va en la tanda común
DISCOVERY_MAX_LLAMADAS_LOCALIDAD = 10 # Tope de seguridad por localidad

# ─────────────────────────────────────────────
# LM STUDIO
# ─────────────────────────────────────────────
LMSTUDIO_HOST = "172.19.96.1"         # Host donde escucha LM Studio (y el servidor RRSS)
LMSTUDIO_BASE_URL = f"http://{LMSTUDIO_HOST}:1234"
LMSTUDIO_EMBEDDING_URL = f"{LMSTUDIO_BASE_URL}/v1/embeddings"
LMSTUDIO_CHAT_URL = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"

LMSTUDIO_EMBEDDING_MODEL = "text-embedding-baai-bge-m3-568m"
LMSTUDIO_CHAT_MODEL = "qwen2.5-7b-instruct"
LMSTUDIO_CHAT_TIMEOUT = 900           # Timeout para peticiones de chat (segundos)
LMSTUDIO_EMBEDDING_TIMEOUT = 30       # Timeout para embeddings (segundos)
LMSTUDIO_CHAT_TEMPERATURE = 0.0       # Temperatura 0.0 para evitar alucinaciones
LMSTUDIO_CHAT_MAX_TOKENS = -1         # Sin límite: el modelo para cuando completa el JSON (evita truncamiento)

# Semilla fija. Sin esto el modelo NO es determinista ni con temperatura 0:
# medido el 2026-08-25 repitiendo la misma petición tres veces, las respuestas
# fueron de 327, 327 y 904 caracteres. Esa varianza se propagaba hasta el
# resultado final —con los mismos 1.224 documentos recogidos, el programa del
# Cristo de la Antigua salió con 29 actos en una ejecución y 17 en la siguiente—
# y hacía imposible medir si un cambio mejoraba algo. Con la semilla fija, tres
# de tres respuestas idénticas. (top_k=1 por sí solo NO basta: se probó.)
LMSTUDIO_SEED = 42

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
# WSL → WINDOWS
# Desde WSL, LM Studio y el servidor RRSS corren en el host Windows, así que hay
# que apuntar a la IP del host y no a localhost.
#
# Antes esto se adivinaba leyendo ipconfig.exe y quedándose con la primera IPv4
# de la LAN (192.168.x.x o 10.x.x.x). Ya no: la dirección buena es la de la
# interfaz vEthernet de WSL (172.19.96.1), que ese patrón ni siquiera reconoce,
# de modo que la autodetección se quedaba con la IP de la LAN y machacaba lo
# configurado aquí arriba. Manda LMSTUDIO_HOST, y WIN_HOST_IP lo sobreescribe
# si algún día el host cambia de sitio.
# ─────────────────────────────────────────────
import platform as _platform
if _platform.system() == "Linux":
    _win_ip = os.environ.get("WIN_HOST_IP", LMSTUDIO_HOST)


    LMSTUDIO_BASE_URL = f"http://{_win_ip}:1234"
    LMSTUDIO_EMBEDDING_URL = f"{LMSTUDIO_BASE_URL}/v1/embeddings"
    LMSTUDIO_CHAT_URL = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"
    RRSS_SERVER_URL = f"http://{_win_ip}:{RRSS_SERVER_PORT}"
else:
    RRSS_SERVER_URL = f"http://localhost:{RRSS_SERVER_PORT}"


# ─────────────────────────────────────────────
# HIGIENE DE DOCUMENTOS (Fase 1 — previa al RAG)
# Quita duplicados, tablas de cifras y boilerplate ANTES de trocear, para que el
# presupuesto de contexto no se gaste en copias del mismo documento.
# ─────────────────────────────────────────────
HIGIENE_DEDUP_ENABLED = True          # Dedup por URL canónica, hash de texto y casi-duplicados
HIGIENE_JACCARD_UMBRAL = 0.90         # Similitud a partir de la cual dos documentos son el mismo
HIGIENE_BOILERPLATE_ENABLED = True    # Quitar menús/cookies/pie repetidos en un mismo dominio
HIGIENE_BOILERPLATE_UMBRAL = 0.40     # Línea presente en >40% de las páginas del dominio
HIGIENE_BOILERPLATE_MIN_DOCS = 8      # Mínimo de páginas del dominio para que la frecuencia signifique algo
HIGIENE_TABULAR_ENABLED = True        # Descartar presupuestos, padrones y listados contables
HIGIENE_TABULAR_DENSIDAD = 0.25       # Densidad de dígitos a partir de la cual sospechar
HIGIENE_TABULAR_RATIO = 0.80          # Palabras/números por debajo del cual es tabla, no prosa

# ─────────────────────────────────────────────
# RANKING DE CHUNKS (Fase 2 — fusión de señales)
# Todas las señales viven en 0..1 y los pesos suman 1, de modo que ninguna pueda
# dominar por accidente como hacía el antiguo "+0.30" sumado sobre el coseno.
# ─────────────────────────────────────────────
# El reparto premia las señales deterministas por encima de la difusa: el coseno
# es lo único que sabe qué se está preguntando, pero es también lo que falló en
# Amurrio. Con estos pesos, aunque el embedding se equivoque por completo, la
# agenda de fiestas le saca 0.21 al PDF de presupuestos.
RANKING_PESO_SIMILITUD = 0.35         # Coseno con la query, normalizado dentro del conjunto
RANKING_PESO_SPIDER = 0.25            # Puntuación con que la araña ordenó la página de origen
RANKING_PESO_PROGRAMA = 0.28          # Horas distintas en líneas que describen actos + léxico festivo
RANKING_PESO_TEMPORAL = 0.12          # Coherencia con el año objetivo
RANKING_UMBRAL_RELATIVO = 0.55        # Se admite lo que llegue al 55% del mejor chunk de la localidad
RANKING_UMBRAL_MINIMO = 0.25          # Suelo absoluto del umbral
RANKING_DOCS_GARANTIZADOS = 3         # Mejores documentos de la araña con plaza asegurada en el contexto
RANKING_CHUNKS_POR_DOC_GARANTIZADO = 1

# ══════════════════════════════════════════════════════════════════════════════
# RELEVANCIA GEOGRÁFICA (anti-contaminación municipio → pedanía)
# ══════════════════════════════════════════════════════════════════════════════
# Una página municipal larga nombra de pasada a casi todas las aldeas del término.
# Con el criterio anterior ("la menciona una vez") toda esa página se declaraba
# DIRECTA para cada aldea y su programa de fiestas se copiaba a todas.
RELEVANCIA_DOC_MIN_MENCIONES = 3      # Menciones fuera de enumeración para que un DOC sea DIRECTA
RELEVANCIA_TITULO_CHARS = 250         # Ventana inicial que se considera "encabezado" del documento
RELEVANCIA_ENUM_VENTANA = 140         # Radio en chars para juzgar si una mención está en una lista
RELEVANCIA_ENUM_MIN_HERMANAS = 2      # Hermanas distintas en esa ventana para llamarlo enumeración

# ── Buscadores: fusión de motores ────────────────────────────────────────────
# Antes se devolvía el primer motor con resultados. Bing servía el 100% de sus
# URLs como redirecciones bing.com/ck/a (inservibles) y Yahoo fallaba casi
# siempre, así que la consulta se perdía según a quién le tocase el turno.
MIN_RESULTADOS_DESEADOS = 8           # Se consultan motores hasta reunir estos resultados
MAX_MOTORES_POR_CONSULTA = 3          # Tope de motores por consulta (coste/tiempo)
BUSQUEDA_SEGUIR_PDFS = True           # Descargar los PDF que cuelgan de los resultados
BUSQUEDA_MAX_PDFS_POR_PAGINA = 3      # PDFs a seguir desde una misma página
BUSQUEDA_MAX_PDFS_TOTAL = 15          # Tope de PDFs por localidad. El programa
                                      # de actos casi siempre vive en un PDF, así
                                      # que este tope es de los que más duelen.

# Ventaja de las fuentes oficiales en el enrichment, en la escala del score.
# Antes la prioridad de fuente era clave de orden PRIMARIA, lo que vetaba a
# busqueda_web por completo: en Amurrio entraron 37 chunks municipales (el peor
# con 0.531) y quedó fuera el PDF del programa oficial, que puntuaba 0.675.
ENRICHMENT_BONUS_OFICIAL = 0.15
# Chunks mejor puntuados que entran al contexto de enrichment sea cual sea su
# fuente. La jerarquía de fuentes ordena, pero no puede vetar: el PDF del
# programa oficial de Amurrio era el 9º de 105 por score y no entraba.
ENRICHMENT_TOP_GARANTIZADOS = 12

# ══════════════════════════════════════════════════════════════════════════════
# DISPOSICIÓN DE PDF (reconstrucción del orden de lectura)
# ══════════════════════════════════════════════════════════════════════════════
# `extract_text()` lee por filas horizontales y en un cartel de varias columnas
# eso pega actos de columnas y días distintos en la misma línea. Medido sobre el
# cartel de Amurrio 2026: 13 de 118 actos extraídos (11%) con el texto plano,
# 118 de 118 (100%) reconstruyendo por columnas.
DISPOSICION_ENABLED = True
DISPOSICION_FACTOR_HUECO_COLUMNA = 3.0   # DETECTAR columna: solo separadores evidentes
DISPOSICION_FACTOR_CORTE_LIMITE = 0.6    # CORTAR en un límite ya detectado
DISPOSICION_FACTOR_FILA = 0.6            # misma fila si el top dista < N × altura de letra
DISPOSICION_MIN_COLUMNAS_PARA_APLICAR = 2
# Días que se piden al LLM en cada llamada de enrichment. Con 118 actos en el
# contexto, pedir el programa entero de una vez hacía que el modelo devolviese 83
# y se dejara el día más cargado completo. Troceando, ninguna llamada se satura.
ENRICHMENT_DIAS_POR_LLAMADA = 3

# ── Guarda anti-copia del programa de la capital ─────────────────────────────
# Medido el 2026-08-21: con el escape en "≥1 chunk DIRECTA" la guarda no se
# disparó nunca, porque 'buscadores:snippets' es un único chunk con ~30
# resultados y basta que uno mencione el pueblo para marcarlo directo entero.
ANTICOPIA_MIN_DOCS_DIRECTOS = 2    # documentos DISTINTOS (sin contar snippets) que nombran la localidad
ANTICOPIA_MIN_ACTOS_COMUNES = 4    # actos compartidos con la capital para sospechar
ANTICOPIA_FRACCION_COPIA = 0.45    # fracción del programa que basta para declararlo copia
# Calibrado el 2026-08-21 sobre los datos reales de Amurrio: con 0.45 se cazan las
# 5 copias (Delika 100%, Artomaña 95%, Baranbio 62%, Lekamaña 52%, Larrinbe 46%)
# y se respetan las 3 fiestas propias (San Jorge 0%, San Nicolás 38%, Aloria 0%).

# Palabras seguidas que la descripción de una pedanía puede compartir con la de
# la capital antes de considerarla copiada.
#
# Es la señal que sobrevive cuando las demás fallan. Las dos guardas anteriores
# comparan PROGRAMAS, y eso se cae si la capital se extrajo a medias: medido el
# 2026-08-21, Amurrio sacó 21 actos (solo los titulares de cada jornada) y
# Saratxo 83 (el programa entero), así que compartían 2 actos = 2%, muy por
# debajo de ANTICOPIA_FRACCION_COPIA. La descripción, en cambio, la redacta el
# modelo a partir del mismo párrafo de cabecera del cartel, y sale casi calcada.
#
# Calibrado sobre las 13 fichas reales de Amurrio, tramo verbatim más largo
# contra la descripción de la capital:
#   copias  -> Artomaña 12, Aloria 11, Saratxo 5 palabras
#   propias -> Artomaña/San Jorge 3, el resto 1
# Con 5 se cazan las tres y queda margen por ambos lados.
ANTICOPIA_MIN_PALABRAS_VERBATIM = 5
# Actos compartidos entre dos fiestas de LA MISMA localidad para tratarlas como
# la misma fiesta re-fechada. Medido el 2026-08-21: a Artomaña se le asignó su
# propio programa de San Jorge (17-23 abr) por segunda vez con las fechas y el
# nombre de la fiesta de la capital (12-17 ago); 9 actos idénticos, el 75%.
ANTICOPIA_MIN_ACTOS_DUP_INTERNO = 4
ANTICOPIA_FRACCION_DUP_INTERNO = 0.45

# ── Rescate de fiestas por anclaje de fechas en el contexto ──────────────────
# Respaldo mínimo para dar por buena una fecha leída del contexto cuando la
# localidad se ha quedado sin ninguna fiesta. Cada fuente que la repite suma 1,
# +1 si nombra el año y +1 más si lo escribe en posesivo ("fiestas de X").
# Medido el 2026-08-22 sobre las 9 localidades de Amurrio, el respaldo del rango
# correcto va de 2 (Saratxo) a 34 (Amurrio); con 2 se recuperan todas las que
# tienen la fecha publicada.
ANCLA_PESO_MINIMO = 2
# Para CORREGIR una fecha que el modelo ya dio se exige más respaldo que para
# rescatar una fiesta inexistente: si el modelo dijo algo, hay que estar más
# seguro para enmendarlo. Amurrio tenía dos rangos en su contexto, "del 11 al 17"
# (respaldo 2) y "del 12 al 17" (respaldo 34, y el bueno); el umbral evita que
# un rango citado de pasada corrija al que repiten todas las fuentes.
ANCLA_PESO_MINIMO_CORRECCION = 4
# Con 3 bastaba UNA sola mención para enmendar al modelo: el peso se compone de
# 2 por escribirlo en posesivo ("fiestas de X") más 1 por nombrar el año, así que
# 3 lo alcanza una frase suelta. Medido el 2026-08-22 sobre Tobarra y Aranda, las
# dos correcciones que se dispararon a peso 3 estropearon fechas que el modelo
# tenía BIEN: Tobarra San Roque 14-21 de agosto (la fecha real) movida a 9-17, y
# La Aguilera 12-17 de mayo movida a 5-12, que además dejaba fuera el 13, día de
# San Pedro Regalado. Con 4 hacen falta dos menciones independientes; las
# correcciones acertadas que se midieron antes (Aloria 4, Baranbio 6) siguen
# pasando.
# Ninguna fiesta de pueblo dura más de dos semanas. Por encima de esto la frase
# es un rango de temporada ("del 1 de junio al 30 de septiembre"), no una fiesta.
ANCLA_MAX_DIAS = 15
# Respaldo para AÑADIR una fiesta sobre las que ya dio el modelo, en fechas donde
# no hay ninguna. Más exigente que el rescate a secas: allí se suple un vacío y
# aquí se añade, así que equivocarse cuesta una ficha inventada. Medido el
# 2026-08-22 sobre 21 localidades, con 3 se emite exactamente una: las patronales
# de mayo de Tobarra, que son reales y el modelo se había dejado.
ANCLA_PESO_MINIMO_EXTRA = 3
ANCLA_MAX_FIESTAS_EXTRA = 2
# Trozo de la frase que se guarda como prueba del anclaje. De ahí sale también el
# nombre de la fiesta rescatada, y con 200 se quedaba corto: la evidencia de las
# patronales de mayo de Tobarra cortaba justo antes de "en honor al Santísimo
# Cristo de la Antigua", así que la ficha salía como "Fiestas de Tobarra".
ANCLA_EVIDENCIA_CHARS = 420
# Rangos de fecha que puede enumerar un segmento antes de considerarlo un listado
# de actividades en vez del anuncio de una fiesta. Medido el 2026-08-23: los
# siete anclajes coincidentes con fechas verificadas salen de segmentos con UN
# rango; el listado de ocio alternativo de Aranda traía cinco.
ANCLA_MAX_RANGOS_POR_SEGMENTO = 2
# Días que tiene que haber entre una fiesta ya conocida y otra que se quiera
# añadir desde el contexto. Pegadas o casi, son la misma fiesta contada por dos
# fuentes que no coinciden, no dos fiestas distintas.
ANCLA_DIAS_DE_SEPARACION = 3

# ── Saneado del programa ─────────────────────────────────────────────────────
# Longitud a partir de la cual un acto se considera CONCRETO y, por tanto, no
# puede repetirse en varios días de las mismas fiestas. Por debajo se deja pasar:
# "misa", "dianas", "hinchables" o "romería" sí se celebran cada día y no son
# una repetición del modelo. Medido el 2026-08-22, los actos reciclados eran
# largos y específicos ("Maratón de DJs de Cuadrillas", "concursos de tortillas
# y paellas"); los legítimamente diarios, cortos.
PROGRAMA_MIN_CHARS_ACTO_UNICO = 12
# Chunks mejor puntuados con plaza asegurada en el contexto de DISCOVERY, sea
# cual sea su fuente. Sin esto, el PDF del cartel de Amurrio quedaba fuera y el
# modelo recortaba las fiestas a 2 días por no ver el rango real.
DISCOVERY_TOP_GARANTIZADOS = 8

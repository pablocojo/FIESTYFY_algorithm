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
# VÍA MUERTA: solo lo lee `AsyncRAGProcessor.saturate_context_docs`, y a esa
# función no llega nadie —el pipeline vivo pasa por `analyze_festivals_multipass`
# y, desde el 2026-09-03, reparte con `reparto_contexto.repartir_en_lotes`—.
# Comprobado con grep: sus únicas referencias fuera de su propia definición están
# en los tests. Tocar este número no cambia nada de lo que ve el modelo.
RAG_MAX_TOKENS = 30000
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
# Subido de 90 a 1200 el 2026-09-03, al pasar a qwen3-32b. La respuesta sigue
# siendo un JSON de tres campos —90 tokens le sobran—, pero los modelos que
# RAZONAN gastan el razonamiento de este mismo presupuesto, y con 90 se acababa
# antes de escribir el primer carácter del JSON. Medido en esa ejecución: 15 de
# las 20 llamadas cortadas por longitud, exactamente en 90; las 5 que sí
# terminaron necesitaron 275, 368, 385, 607 y 749 tokens.
#
# Importa más de lo que parece: una comprobación de procedencia fallida CONSERVA
# el documento (el sesgo es a conservar), así que cada corte apagaba en silencio
# el filtro de homónimos justo donde está el riesgo. Es el filtro que evita que
# el programa de Cordovilla de Salamanca entre como si fuera el de Cordovilla de
# Tobarra, a 600 km.
#
# Es un TOPE, no un objetivo: un modelo que no razona sigue parando en cuanto
# cierra el JSON, así que subirlo no cuesta nada con LM Studio.
PROCEDENCIA_MAX_TOKENS = 1200

# ── Veredicto de pertenencia (última puerta antes de guardar) ──────────────
#
# El de arriba juzga DOCUMENTOS, uno a uno, sin saber a quién buscamos. Este
# juzga la FICHA ya montada —nombre, fechas, programa y fuentes— diciéndole al
# modelo quiénes somos: municipio, provincia, comunidad, población y pedanías
# hermanas, que el dataset de Fase 1 trae para las 8.199 localidades.
#
# Existe por el peor registro del 2026-09-04: Santa Marta (La Roda, Albacete) se
# quedó con los 64 actos de las fiestas de Astorga (León) DESPUÉS de que el
# filtro de homónimos hubiera descartado bien catorce documentos de Astorga. El
# agujero no estaba en el juez, sino en que nadie preguntaba por la ficha final.
PERTENENCIA_ENABLED = True
PERTENENCIA_MAX_TOKENS = 1500         # Mismo motivo que arriba: los que razonan gastan de aquí

# Delimitar el nucleo de una fiesta es una respuesta de dos fechas: 200 tokens
# sobran. Va aparte del enriquecimiento porque se pregunta UNA vez por fiesta,
# sobre el programa ya montado, y no por tramos de dias como aquel.
NUCLEO_MAX_TOKENS = 200

# Agrupar fichas repetidas devuelve listas de indices, no texto: con 400 tokens
# sobra hasta para una localidad con muchas fiestas. Se pregunta UNA vez por
# localidad, al final, cuando ya estan todas montadas.
DEDUP_MAX_TOKENS = 400

# Cuánto texto de las fuentes se le enseña. La medida del 2026-09-04: al juez de
# procedencia se le daban entre 27 y 422 tokens con 130.000 libres en la ventana.
# Aquí se va al otro extremo a propósito —decidir de dónde es una fiesta es
# exactamente el problema que necesita el texto de alrededor, no la cabecera—.
PERTENENCIA_CONTEXTO_TOKENS = 12000

# Ante la duda, fuera. Buscamos realismo: en la tirada del 2026-09-04 el pipeline
# no devolvió ni una sola localidad vacía, pero un tercio de las fichas eran de
# otro sitio. Un hueco es honesto; una ficha falsa contamina la base de datos y
# nadie la revisa después.
PERTENENCIA_DESCARTAR_SI_DUDA = True

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

# Verificacion de cobertura: fraccion de los DIAS que el documento nombra que la
# ficha tiene que llegar a cubrir con actos para darla por completa.
#
# Se mide por dias y no por actos a proposito. `contar_actos_horarios()` cuenta
# horas de reloj DISTINTAS en lineas con pinta de acto: es una senal de «esto
# parece un programa» —y buena, por eso decide si se pregunta— pero no un
# recuento de actos. Un programa de diez dias con cien actos puede tener veinte
# horas distintas, asi que usarlo de denominador daria coberturas del 500%.
#
# Los dias, en cambio, se leen del propio documento con el mismo detector que ya
# usa la guarda de «dias no mencionados». En Aranda de Duero el documento
# nombraba los 10 dias de la fiesta y la ficha salio con 4: cobertura 0,4.
COBERTURA_DIAS_MINIMA = 0.6

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
# Páginas que se le presentan al localizador, ordenadas por horas de reloj
# distintas. Subido de 12 a 20 el 2026-09-03.
#
# El número no cambió de sentido, cambió el denominador: antes el localizador
# elegía entre las páginas que el presupuesto había dejado entrar —8 a 17 por
# localidad— y ahora ve el pool entero, que en Aranda de Duero son 83 documentos
# distintos. Doce plazas sobre diecisiete es una preselección; sobre ochenta y
# tres es un embudo nuevo justo donde acabamos de quitar uno.
#
# Cuesta poco: cada candidata son 400 caracteres de extracto, así que 20 son
# 8.000 caracteres de un prompt que tiene 131.072 tokens de sitio.
PROGRAM_LOCATOR_MAX_CANDIDATES = 20
# Rondas del localizador. Subido de 2 a 6 el 2026-09-03, al empezar a hacerle
# caso a `informacion_suficiente`.
#
# El motivo es medido: en la ejecución del 2026-09-03, 4 de las 8 rondas del
# localizador devolvieron `suficiente=False`, y en las 4 el pipeline siguió
# adelante sin hacer nada —dos porque el modelo no propuso ninguna URL (no había
# ninguna en el contexto que seguir) y dos porque las que propuso ya estaban
# descargadas—. Se tenía un modelo diciendo exactamente dónde faltaba
# información y esa señal se tiraba.
#
# El tope real no es este número: el bucle para en cuanto una ronda no aporta
# NINGÚN documento nuevo. 6 es la red de seguridad.
PROGRAM_LOCATOR_MAX_ITERATIONS = 6
PROGRAM_LOCATOR_MAX_URLS_PER_ROUND = 5 # URLs a seguir por ronda si el LLM dice que faltan

# Consultas de buscador que el localizador puede pedir por ronda. Va bajo porque
# las búsquedas son lo que se enfría por anti-scraping (180 s tras 2 respuestas
# incoherentes): multiplicar su ritmo es meterse en el problema que el resto del
# pipeline evita a propósito.
LOCATOR_MAX_CONSULTAS_POR_RONDA = 3
# Tope de consultas por fiesta sumando todas las rondas.
LOCATOR_MAX_CONSULTAS_POR_FIESTA = 6
# Reserva de salida para la respuesta del localizador. Estuvo en 400 y se
# quedaba corto: en la ejecución del 2026-08-28 cortó 16 respuestas, y con los
# modelos de OpenRouter —que aplican el tope a rajatabla, mientras que LM Studio
# lo dejaba pasar— fallaba el 100% de las veces (2 de 2 el 2026-09-01, ambas con
# finish_reason=length y JSON no parseable).
# Subido de 2000 a 4000 el 2026-09-03: con 2000 ya se vio truncar una llamada
# —el LOCATOR más caro de esa ejecución gastó 2612 tokens—, y el razonamiento
# del modelo sale de aquí. El reintento automático lo rescataba, pero pagando
# dos llamadas en vez de una.
PROGRAM_LOCATOR_MAX_TOKENS = 4000
PROGRAM_LOCATOR_DOWNLOAD_TIMEOUT = 15  # Timeout de descarga de URLs señaladas (segundos)

# Descubrimiento por meses. Antes se preguntaba una vez por localidad sobre
# 20.000 caracteres, que en Tobarra son 23 chunks de 189 (12%) y en Aranda 23 de
# 415 (6%): el paso que decide qué fiestas existen era el que menos material
# veía. Con un corte tan estrecho, cualquier reordenación pequeña cambiaba lo que
# entraba —entre dos ejecuciones del 2026-08-26 con el mismo material, Tobarra
# pasó de 4 fiestas a 2 y perdió la del Cristo, que tiene 50 actos—.
DISCOVERY_MIN_CHUNKS_MES_PROPIO = 3   # Con menos, el mes va en la tanda común
# Tope de SEGURIDAD, no de diseño. Estuvo en 10 y Aranda de Duero lo tocaba en la
# ejecución del 2026-09-03 —«12 meses con señal, 10 llamadas»—, así que dos meses
# con material se quedaban sin preguntar sin que nada lo señalara como pérdida.
# Sigue existiendo porque un topónimo corriente dispara el barrido: «Sierra»
# pedía 21 tandas y no tiene programa publicado. Ahora avisa a WARNING cuando
# recorta, que es lo que faltaba.
DISCOVERY_MAX_LLAMADAS_LOCALIDAD = 40

# ─────────────────────────────────────────────
# LM STUDIO
# ─────────────────────────────────────────────
LMSTUDIO_HOST = "172.19.96.1"         # Host donde escucha LM Studio (y el servidor RRSS)
LMSTUDIO_BASE_URL = f"http://{LMSTUDIO_HOST}:1234"
LMSTUDIO_EMBEDDING_URL = f"{LMSTUDIO_BASE_URL}/v1/embeddings"
LMSTUDIO_CHAT_URL = f"{LMSTUDIO_BASE_URL}/v1/chat/completions"

LMSTUDIO_EMBEDDING_MODEL = "text-embedding-baai-bge-m3-568m"

# ─────────────────────────────────────────────
# SEARXNG (buscador propio)
# ─────────────────────────────────────────────
# Metabuscador autoalojado. Sustituye al scrapeo de HTML de DuckDuckGo como
# motor primario por un motivo medido: en la ejecución del 2026-09-05 (semilla
# 7), 101 de 273 fiestas (36%) llegaron al localizador con UN dominio o menos en
# el contexto, y 21 de 35 fiestas quedaron sin programa. El caso testigo es El
# Barraco: 1037 caracteres de contexto, una sola URL —pueblus.com, un directorio
# SEO— y `elbarraco.org` ausente pese a existir. El modelo no elegía mal: no
# tenía nada que elegir.
#
# SearXNG consulta varios motores a la vez y fusiona, así que un bloqueo de
# DuckDuckGo deja de dejar la consulta a ciegas. Devuelve JSON, con lo que no
# hay HTML que parsear ni redirecciones bing.com/ck/a que deshacer.
#
# Corre en el mismo host que LM Studio (contenedor `searxng`, puerto 8888,
# --restart always).
SEARXNG_HOST = LMSTUDIO_HOST
SEARXNG_BASE_URL = f"http://{SEARXNG_HOST}:8888"
SEARXNG_SEARCH_URL = f"{SEARXNG_BASE_URL}/search"
SEARXNG_TIMEOUT = 20            # segundos
SEARXNG_IDIOMA = "es"
# Tope de resultados que se piden. Va alto a propósito: el localizador no
# responde preguntas, ELIGE URLs, y para eso necesita ancho de miras. Es el
# mismo criterio que PROGRAM_LOCATOR_MAX_CANDIDATES (20).
SEARXNG_MAX_RESULTADOS = 20

# Directorios y agregadores SEO. No se eliminan —en municipios sin web propia
# son lo único que hay—, se hunden en la ordenación para que no le tapen al
# localizador la fuente oficial. La lista sale de las 9 fiestas que en la
# ejecución del 2026-09-05 acabaron señalando uno de estos dominios y
# devolvieron cero actos.
DOMINIOS_AGREGADORES = (
    "festivalesdeespana.com",
    "pueblus.com",
    "defiestaenfiesta.es",
    "demercadosmedievales.es",
    "turismoalmanzora.com",
    "grada.es",
)

# Modelo de DESARROLLO (2026-09-01): a 26 tok/s en GPU (8GB, RTX 4060) frente a
# los ~2,5 tok/s del 27B en CPU — mismo contexto real de Tobarra que antes daba
# 0 actos, aquí dio 17 días y 20 actos en 69s con una sola llamada. Es un
# "model.yaml" propio (hub/models/lmstudio-community/qwen3.5-9b-nothink/) que
# envuelve el Qwen3.5-9B-GGUF suelto con enableThinking=false por defecto,
# porque enable_thinking vía API está roto en llama.cpp para toda la familia
# Qwen3.5 (https://github.com/ggml-org/llama.cpp/issues/20182, sin arreglo
# previsto). Sin ese wrapper, el modelo gasta miles de tokens "pensando" antes
# de escribir el JSON y hay que pagarlos igual.
#
# Cuando el pipeline esté maduro en 9B, la tirada de validación real vuelve a
# "qwen/qwen3.8-27b" (mismo arch "qwen35", solo que sin el wrapper porque ese sí
# trae el interruptor de fábrica al venir del catálogo propio de LM Studio).
LMSTUDIO_CHAT_MODEL = "lmstudio-community/qwen3.5-9b-nothink"
LMSTUDIO_CHAT_TIMEOUT = 10800           # Timeout para peticiones de chat (segundos)
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
# OPENROUTER — proveedor principal desde el 2026-09-02: qwen/qwen3-32b
#
# Historia, porque explica por qué la configuración es la que es:
#
# El 2026-09-01 se probó una cascada de ocho modelos GRATUITOS y falló por dos
# motivos: la cuota se agotó a media ejecución de solo 2 municipios, con lo que
# todo acabó dependiendo de un único modelo (minimax), y ese modelo dejaba
# `content` vacío y volcaba la salida en `reasoning`, lo que tiró la fiesta
# principal de Tobarra a 0 actos. Se apagó y se volvió al 9B local.
#
# Ahora se vuelve a la nube, pero con UN modelo de pago en vez de ocho gratuitos.
# Eso quita de raíz los dos problemas: no hay cuota que agotar a mitad de
# ejecución, y no hay que adivinar cuál de los ocho contestó. Comprobado contra
# la API el 2026-09-02 con un prompt de extracción real: `content` vuelve con el
# JSON limpio y bien formado, así que el fallback a `reasoning` —el que rompió
# Tobarra— no llega a dispararse.
#
# Lo que sí hay que tener en cuenta: Qwen3 razona antes de responder y ese
# razonamiento SE FACTURA como tokens de salida. Medido en esa misma prueba, con
# un prompt de 121 tokens: 407 y 675 tokens de salida para una respuesta de 111
# caracteres, con 1425 y 2526 caracteres de razonamiento por detrás. El
# parámetro `reasoning: {enabled: false}` no lo apaga —se probó y salió más
# razonamiento, no menos—. De ahí el tope de tokens de más abajo.
# ─────────────────────────────────────────────
OPENROUTER_ENABLED = True
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


def _leer_clave_openrouter() -> str:
    """
    La clave NUNCA se escribe en este fichero: config.py está en git y acabaría
    publicada. Se lee de la variable de entorno OPENROUTER_API_KEY y, si no
    está, de openrouter_key.txt en esta misma carpeta (ignorado por git).
    """
    clave = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if clave:
        return clave
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openrouter_key.txt")
    try:
        with open(ruta, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


OPENROUTER_API_KEY = _leer_clave_openrouter()

# Un solo modelo, de pago. La cascada de ocho gratuitos del 2026-09-01 hacía que
# cada llamada pudiera contestarla un modelo distinto —y de hecho así fue, según
# se iban agotando las cuotas—, con lo que la salida dejaba de ser comparable
# entre localidades de la misma ejecución. Con uno solo, lo que cambia entre dos
# ejecuciones es el código, no quién contestó.
#
# Ficha del modelo (consultada a la API el 2026-09-02):
#   contexto     131.072 tokens (el 9B local iba con 32.768)
#   precio       $0,08 por millón de tokens de entrada
#                $0,28 por millón de tokens de salida
#   coste estimado de una ejecución de 2 municipios / 12 localidades: céntimos.
OPENROUTER_MODELS = [
    "qwen/qwen3-32b",
]

# 5 min por llamada. Nada que ver con los 10800s de LM Studio: si un modelo en
# la nube no ha contestado en 5 minutos es que no va a contestar, y hay otros
# siete detrás esperando. Ese era justo el fallo de los timeouts de 3h.
OPENROUTER_CHAT_TIMEOUT = 300

# El timeout de arriba es el SUELO. Un prompt grande no tarda lo mismo que uno
# pequeño: antes de generar el primer token, el modelo tiene que leerse la
# entrada entera.
#
# Medido el 2026-09-03, la primera ejecución con el reparto en lotes: las cuatro
# llamadas de enrichment de Aranda de Duero enviaron 106.124 tokens y las cuatro
# se cortaron exactamente en 300 s sin devolver nada. Con 300 s fijos, cualquier
# prompt por encima de ~40.000 tokens es una llamada tirada.
#
# 4 s por cada 1.000 tokens es conservador (equivale a ~250 tok/s de lectura) y
# deja 300 + 425 = 725 s para un prompt de 106.000.
LLM_SEGUNDOS_POR_1K_TOKENS = 4.0

# Techo que se aplica a TODOS los proveedores, LM Studio incluido. Eso baja de
# hecho el timeout local de las 3 horas de `LMSTUDIO_CHAT_TIMEOUT` a 30 minutos,
# y es deliberado: en la ejecución del 2026-08-28 dos llamadas se quedaron
# colgadas exactamente 10.800 s sin producir un token y se tiraron 6 horas, el
# 17,8% del reloj de aquel run. Una llamada que no ha convergido en media hora
# no va a converger.
LLM_TIMEOUT_MAXIMO = 1800

# LM Studio entiende max_tokens=-1 como "sin límite"; OpenRouter lo rechaza.
# Cuando el llamador pide -1 se manda este tope en su lugar.
#
# Estuvo en 24000 y era demasiado alto: el 2026-09-01, dos de las seis llamadas
# de ENRICHMENT de Tobarra se fueron a 24001 y 24059 tokens con
# finish_reason=length —el modelo se enrolla, choca con el techo y devuelve un
# JSON que ni empieza por JSON—. Se tiraron 8m42s, el 45% del tiempo de la
# localidad, y la fiesta salió con 5 actos en vez de los 25 de la ejecución
# anterior. Las llamadas que SÍ funcionaron generaron 5916, 5668, 4483 y 2351
# tokens: ninguna legítima pasa de 6000.
#
# Subido de 10000 a 16000 el 2026-09-02 al pasar a Qwen3-32B. El motivo no es
# que las respuestas sean más largas, sino que este modelo RAZONA y su
# razonamiento sale del mismo presupuesto: en la prueba contra la API, un prompt
# de 121 tokens gastó 407 de salida para una respuesta de 111 caracteres, es
# decir que casi todo el gasto fue pensar. Con el tope en 10000, un razonamiento
# largo sobre un prompt de ENRICHMENT de verdad puede comerse el presupuesto
# antes de escribir el JSON, que es exactamente el finish_reason=length de
# arriba. 16000 deja sitio a ~6000 de respuesta y ~10000 de razonamiento, y aun
# así una respuesta desbocada se corta en 1-2 min en vez de 5.
OPENROUTER_MAX_TOKENS = 16000

# Ventana de contexto con la que se dimensionan los prompts cuando el chat va a
# OpenRouter. Existe porque hasta el 2026-09-02 el presupuesto salía SIEMPRE del
# modelo cargado en LM Studio, y eso deja de tener sentido cuando LM Studio ya no
# contesta: si no está levantado, `get_n_ctx()` cae al valor de seguridad de 8192
# y todos los prompts se construyen con la cuarta parte del material que
# deberían, sin que nada avise. Comprobado ese mismo día con LM Studio
# descargado.
#
# Subido de 32.768 a 131.072 —la ventana real del modelo— el 2026-09-03, con el
# reparto en lotes ya en su sitio.
#
# Estuvo en 32.768 a propósito, para poder cambiar de modelo tocando una sola
# variable. El motivo para subirlo es medido: con el tope anterior, al modelo
# llegaba el 5,7% de los chunks candidatos en discovery y el 23,8% en enrichment
# —10.060 descartados de 12.897 en la ejecución del 2026-09-03—, y el PDF del
# programa de Aranda de Duero entraba a razón de 14 fragmentos de 82.
#
# Ya no es el techo de lo que ve el modelo: con el repartidor, lo que no cabe en
# un lote va en el siguiente. Lo que esta variable decide ahora es cuántos lotes
# hacen falta, es decir cuántas llamadas. A 131.072 el PDF entero de Aranda
# —29.000 tokens— cabe en un solo lote.
OPENROUTER_N_CTX = 131072

# Reintento cuando la respuesta se corta por longitud. El presupuesto se
# multiplica por este factor y se vuelve a preguntar UNA vez, en vez de dar por
# perdido un JSON que llegó a medias. Protege a cualquier llamada de tope fino
# frente a un modelo que razone más de lo previsto, sin tener que adivinar el
# número exacto para cada una.
LLM_FACTOR_REINTENTO_TRUNCADO = 6
# Techo del reintento. Medido el 2026-09-03 sobre las llamadas que SÍ terminaron
# en esa ejecución, con qwen3-32b (razonamiento incluido en la cuenta):
#     DISCOVERY    max 1344   ENRICHMENT   max 3259
#     LOCATOR      max 2612   PROCEDENCIA  max  925
# Con 4000 el reintento de un ENRICHMENT difícil se quedaba al borde. 12000 da
# holgura real y sigue por debajo de OPENROUTER_MAX_TOKENS, y una respuesta
# desbocada cuesta menos de medio céntimo.
LLM_TOPE_REINTENTO = 12000

# En la nube no hay VRAM que desbordar, así que no hace falta serializar como
# en local. Lo que limita es el cupo por minuto de la clave.
#
# Subido de 3 a 8 el 2026-09-03, a la vez que se paralelizaron las tandas de
# DISCOVERY y los lotes de ENRICHMENT. Antes daba igual el número: los dos
# bucles encadenaban las llamadas con `await`, así que nunca había más de UNA en
# vuelo y el semáforo no llegaba ni a 2. Medido ese día, esas dos fases son el
# 48% del reloj de una ejecución.
#
# 8 y no más porque el cupo de OpenRouter es por minuto y no está medido: si
# aguanta sin 429, se puede subir. Las BÚSQUEDAS WEB no se tocan —siguen con su
# ritmo y sus delays—: son las que se enfrían por anti-scraping, y multiplicar su
# tasa es meterse en el problema que este cambio evita a propósito.
# Reintento ante 429 (cupo por minuto agotado) EN EL MISMO proveedor, antes de
# pasar al siguiente de la cadena.
#
# Existe por una trampa que hasta ahora no había saltado pero que el reparto en
# lotes hace mucho más probable: cualquier respuesta distinta de 200 hacía saltar
# al siguiente proveedor, y el siguiente es LM Studio, cargado con n_ctx = 8192.
# Un lote de 30.000 tokens no le cabe, así que devolvía error de contexto, se
# lanzaba ContextOverflowError y en `_descubrir_por_meses` esa tanda se convertía
# en una lista vacía SIN QUE NADA la registrara como pérdida.
#
# En la ejecución del 2026-09-03 hubo cero 429 reales. Con 3,6x más llamadas y
# lotes tres veces mayores, dejará de ser cero.
LLM_REINTENTOS_429 = 3
LLM_BACKOFF_429 = 6.0                 # Segundos; se dobla en cada intento

OPENROUTER_CONCURRENCY = 8
OPENROUTER_PAUSA_ENTRE_MODELOS = 0.4  # Respiro antes de saltar al siguiente modelo

# Cabeceras de cortesía que OpenRouter usa para atribuir el tráfico.
OPENROUTER_REFERER = "https://github.com/fiestyfy/algoritmo"
OPENROUTER_TITLE = "Fiestyfy Fase 2"

# ─────────────────────────────────────────────
# SANTO PATRÓN
# ─────────────────────────────────────────────
PATRON_SEARCH_ENABLED = True          # Buscar el santo patrón de cada localidad
PATRON_CACHE_FILE = "patrones_cache.json"  # Caché de patrones (en la carpeta Fase2)
PATRON_MAX_URLS = 3                   # URLs de buscadores a seguir para hallar el patrón
# Mismo motivo que PROCEDENCIA_MAX_TOKENS: 200 le sobran a la respuesta y no le
# llegan al razonamiento. No se vio fallar el 2026-09-03 porque la caché de
# patrones estaba caliente, pero con caché fría habría caído igual.
PATRON_LLM_MAX_TOKENS = 1200           # Tokens máximos para la extracción LLM del patrón

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
# VLM dedicado, en LM Studio. Hasta el 2026-09-02 apuntaba al mismo modelo que
# el chat, porque el chat también era local y traía su mmproj. Al llevarse el
# chat a OpenRouter (ver más arriba) eso deja de tener sentido: la visión no se
# va a la nube —son capturas de RRSS, y mandarlas fuera no aporta nada y cuesta
# dinero—, así que se le pone su propio modelo, más pequeño y suficiente para
# leer un cartel.
#
# Reparto que queda: chat en OpenRouter, embeddings y visión en LM Studio.
VISION_MODEL = "qwen_qwen2.5-vl-7b-instruct"   # Identificador del modelo de visión en LM Studio
VISION_TIMEOUT = 180                  # Timeout por imagen (segundos)
VISION_MAX_TOKENS = 1200              # Respuesta máxima (los programas largos necesitan espacio)
VISION_MAX_IMAGES_PER_PROFILE = 10    # Tope de imágenes por perfil y red
# Tope de paginas de un documento que se leen como cartel. Va bajo a proposito:
# es el ultimo recurso para un PDF que no ha soltado texto, y cada imagen es una
# llamada al VLM con su timeout de 180 s. Con dos se cubre el caso normal —un
# cartel de una cara, a veces dos— sin que una galeria se coma la ejecucion.
VISION_MAX_IMAGES_DOC = 2
VISION_MAX_DIM = 1280                 # Redimensionado máximo antes de enviar al VLM

# ─────────────────────────────────────────────
# ORQUESTADOR
# ─────────────────────────────────────────────
PARALLEL_MUNICIPALITIES = 2           # Municipios procesados en paralelo (reducido para modelo 27B)
MAX_LOCALITY_CONCURRENCY = 3          # Concurrencia de localidades (reducido para modelo 27B)

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
# Días que le tienen que quedar a una fiesta después de que el anclaje la
# recorte. Un anclaje afina dónde empieza y acaba una fiesta; no puede convertir
# una de varios días en una de un día, porque eso ya no es afinar, es afirmar
# otra cosa. Medido el 2026-09-02 sobre las ejecuciones del 27B (28-30 ago) y del
# 9B (1 sep): el anclaje se disparó 8 veces, las 8 sobre rangos del modelo que
# cubrían el 100% de las fechas reales, y no mejoró la cobertura ni una vez. Dos
# de esos disparos eran colapsos a un solo día y son los dos peores daños de todo
# el pipeline: Aranda de Duero, del 11 al 20 de septiembre (sus fiestas mayores,
# 33.000 habitantes) reducida al 15; y Los Mardos, del 16 al 19 de julio —lo que
# dice su programa oficial— reducida al 19.
ANCLA_MIN_DIAS_TRAS_RECORTE = 2
# Distancia máxima, en caracteres, entre la fecha y la mención del pueblo dentro
# del MISMO segmento. El segmento ya garantiza que las dos salen de la misma
# página, pero una página entera es una unidad demasiado grande: en el contexto
# de Mora de Santa Quiteria, el titular de sus fiestas y la fecha de un festival
# de narración oral de la Casa de la Cultura de Tobarra convivían a noventa
# líneas de distancia, y de ahí salió una ficha entera que no existe.
ANCLA_MAX_CHARS_A_LA_LOCALIDAD = 600
# Días que tiene que abarcar un programa para que sus fechas manden sobre el
# rango que declaró el modelo. Un programa de dos días no dice cuánto dura la
# fiesta, solo que esos dos días existen. Medido en la ejecución del 2026-09-02:
# con el recorte sin condición, Sierra pasó del 30 de julio al 2 de agosto —lo
# que anuncia su propia comisión de fiestas— a durar dos días, y Santiago de
# Mora de cinco a dos, cuando lo suyo son once. Los dos programas tenían dos
# días. Los dos recortes que sí acertaron —San Roque de Tobarra al 14 de agosto
# exacto y Aljubé al 18 de mayo— venían de programas de seis y cinco días.
RECORTE_PROGRAMA_MIN_DIAS = 3

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

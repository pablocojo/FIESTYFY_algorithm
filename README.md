# 🎊 FIESTYFY Algorithm

<p align="center">
  <em>Motor de recolección, estructuración y enriquecimiento de datos para la plataforma definitiva de fiestas locales de España.</em>
</p>

---

## 📖 Visión General

El **Algoritmo FIESTYFY** es el corazón tecnológico detrás de la plataforma Fiestyfy. Su propósito es orquestar la creación de una base de datos exhaustiva, estructurada y libre de errores, que documente todos los lugares de España susceptibles de albergar fiestas propias.

Este proyecto automatiza la recopilación de entidades territoriales, su enriquecimiento mediático y descriptivo, y la posterior extracción inteligente de programas festivos mediante técnicas de **Web Scraping**, **RAG (Retrieval-Augmented Generation)** y el uso de **Modelos de Lenguaje Locales (LLMs)**.

---

## 🎯 Objetivo Principal

Construir un archivo JSON estructurado, validado jerárquicamente y de alta fidelidad que actúe como el **esqueleto central** de toda la plataforma web, garantizando:
- Cobertura total del territorio español (0% omisiones).
- Cero clasificaciones erróneas.
- Alta fidelidad en la información cultural y descriptiva de las festividades.

---

## 🏗 Arquitectura de Datos (Enfoque *INE-First*)

Para garantizar la máxima fiabilidad, el sistema confía como fuente principal y absoluta en los datos oficiales del **Instituto Nacional de Estadística (INE)**:

1. **Base Municipal (`MUNICIPIOS.csv` / `pobmun25.xlsx`)**: Define el padrón y establece los nodos raíz de toda la geografía española.
2. **Entidades Poblacionales (`ENTIDADES.csv` / `nomdef2025.xlsx`)**: Proporciona el 100% de las entidades menores y pedanías oficiales. 

**Rol de Wikipedia**: Se relega a una función secundaria de *enriquecimiento*. Se utiliza para obtener URLs, generar descripciones mediante LLMs y extraer estructuras puramente urbanas (como **distritos** y **barrios**) que no constan en el INE.

---

## 🗂 Estructura Jerárquica y Tipología de Lugares

El algoritmo organiza el territorio en un árbol relacional estricto. (Nota: Se ha eliminado la figura de *municipio compuesto* y *pedanía* como tipos de datos; todo se estructura en base a población y jerarquía).

* **`municipio`**: Nodo raíz estructural (ID INE 11 dígitos). Actúa como contenedor logístico y administrativo. Contiene metadatos generales pero **no** tiene fiestas propias ni el campo `padre_id`.
* **`pueblo` / `ciudad_pequena` / `ciudad_grande`**: Entidades habitadas reales. Poseen fiestas propias y cuelgan directamente de un `municipio` a través del campo `padre_id`. Una de estas entidades en cada municipio se marca siempre con `es_capital: true`.
* **`distrito` / `barrio`**: Subdivisiones de nivel inferior (extraídas de Wikipedia). Sólo cuelgan de entidades urbanas (ciudades grandes o pequeñas). Siempre tienen `es_capital: false`. En el caso de los barrios que cuelgan de distritos, incluyen un `abuelo_id` que apunta a la ciudad principal.

---

## ⚙️ Fases del Algoritmo

El procesamiento se divide en dos fases secuenciales y altamente especializadas:

### 📍 Fase 1: Estructuración Territorial (`Fase1_recogida_datos_wiki`)
Construye el esqueleto relacional y poblacional completo.
* **Paso 1 (`main.py`)**: Inicialización y extracción de los municipios raíz.
* **Paso 2 (`main2.py`)**: Cruce masivo con los datos del INE (`ENTIDADES.csv`) para extraer todas las entidades menores. Posteriormente, un agente LLM extrae descripciones resumidas e identifica distritos y barrios desde Wikipedia.

### 🎊 Fase 2: Extracción y Procesamiento de Fiestas (`Fase2_Extraccion_Fiestas`)
Recorre el esqueleto generado en la Fase 1 para nutrir de contenido festivo a las entidades.
* Utiliza un orquestador asíncrono impulsado por **LLMs locales** y **RAG**.
* Realiza búsquedas inteligentes, procesa webs de ayuntamientos, filtra ruido y estructura en formato JSON las fechas, descripciones y programas de actos de cada festividad.

---

## 🧠 Configuración de Inteligencia Artificial

El sistema combina **un modelo remoto de pago** para el razonamiento y **LM Studio en local** para embeddings y visión.

| Pieza | Dónde corre | Modelo | Variable en `config.py` |
|---|---|---|---|
| Chat / razonamiento | OpenRouter | `qwen/qwen3-32b` | `OPENROUTER_MODELS` |
| Chat de reserva | LM Studio | `lmstudio-community/qwen3.5-9b-nothink` | `LMSTUDIO_CHAT_MODEL` |
| Embeddings (RAG) | LM Studio | `text-embedding-baai-bge-m3-568m` | `LMSTUDIO_EMBEDDING_MODEL` |
| Visión (carteles) | LM Studio | `lmstudio-community/qwen3.5-9b-nothink` | `VISION_MODEL` |

El chat sale por OpenRouter desde el 2026-09-02 y LM Studio queda de reserva: con la cascada anterior de modelos gratuitos, cada llamada podía contestarla uno distinto según se agotaban las cuotas, y la salida dejaba de ser comparable entre localidades de la misma ejecución.

> ⚠️ El identificador de cada variable debe coincidir **exactamente** con el que muestra LM Studio en su lista de modelos cargados.

Para ajustar la concurrencia al hardware disponible: `PARALLEL_MUNICIPALITIES` en `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/config.py`.

---

# 🛠 Puesta en marcha en un ordenador nuevo

## ¿Windows o Linux?

**Las dos valen para la Fase 2**, que es donde está el trabajo. El proyecto se ha desarrollado y ejecutado sobre Windows 11, pero no hay nada en el pipeline que dependa de Windows: la detección de Tesseract ya busca primero el binario nativo del sistema (`/usr/bin/tesseract`), y el resto es Python multiplataforma.

**Recomendación: Ubuntu**, por tres motivos concretos:

- **La consola de Windows usa cp1252** y revienta al escribir caracteres como `→`. No tumba la ejecución (el fichero de log va en UTF-8), pero llena la salida de `UnicodeEncodeError`.
- **Docker y Tesseract son nativos.** En Windows, SearXNG vive en un contenedor dentro de WSL, y eso arrastra el problema del paso 7.
- **Sin la IP fantasma de WSL.** En Linux todo es `127.0.0.1`.

**Lo único que se pierde en Linux** es el módulo de redes sociales (`rrss_server.py`), que automatiza aplicaciones de escritorio con `pywinauto` y `pyautogui`. Se desactiva con `--sin-rrss`, que es la opción que usan todas las ejecuciones desatendidas de todos modos.

---

## Paso 1 — Python 3.11

Se usa **Python 3.11.9**. Las versiones más nuevas no están probadas.

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip
```

En Windows, descargar desde [python.org](https://www.python.org/downloads/release/python-3119/) y marcar «Add python.exe to PATH».

## Paso 2 — Clonar y crear el entorno

```bash
git clone https://github.com/pablocojo/FIESTYFY_algorithm.git
cd FIESTYFY_algorithm
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

En Windows, el activador es `.venv\Scripts\activate`.

El dataset de Fase 1 (`lugares_espana_actualizado.json`, 10,8 MB, 9.752 lugares) y el modelo de idioma `lid.176.ftz` **ya vienen en el repositorio**. No hay que descargarlos aparte.

## Paso 3 — Tesseract OCR

El binario se instala aparte del paquete de Python. Hace falta el idioma **español**.

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-spa
tesseract --version
```

En Windows: instalar [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) marcando «Spanish» en los idiomas. Si no queda en el `PATH`, apuntarlo con la variable de entorno `TESSERACT_PATH`.

## Paso 4 — LM Studio y sus dos modelos

Descargar [LM Studio](https://lmstudio.ai/) (hay versión Linux en AppImage) y cargar desde su buscador:

- `lmstudio-community/qwen3.5-9b-nothink` — chat de reserva y visión
- `text-embedding-baai-bge-m3-568m` — embeddings del RAG

Después, en la pestaña **Developer**:

1. Arrancar el servidor en el **puerto 1234**.
2. Activar **«Serve on Local Network»** solo si el pipeline va a correr en otra máquina o dentro de WSL.
3. **Subir el `n_ctx` del modelo 9B.** Por defecto se carga con 30.976 tokens y admite 262.144. El pipeline lo avisa en cada arranque:
   ```
   [BUDGET] 'qwen3.5-9b-nothink' está cargado con n_ctx=30976 pero soporta
   hasta 262144. Subirlo en LM Studio multiplicaría el contexto disponible sin coste.
   ```

Comprobación: `curl http://127.0.0.1:1234/v1/models`

## Paso 5 — SearXNG (buscador primario)

Desde el 2026-09-06 SearXNG es el motor principal: devuelve JSON y no hay que parsear HTML ni deshacer redirecciones. Sin él, la búsqueda cae a DuckDuckGo y Bing, que se enfrían por envenenamiento anti-scraping.

```bash
docker run -d --name searxng --restart always \
  -p 8888:8080 \
  -v "$PWD/searxng-config:/etc/searxng" \
  searxng/searxng:latest
```

**Hay que habilitar la salida JSON a mano**, porque no viene activada por defecto. En `searxng-config/settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

Reiniciar con `docker restart searxng` y comprobar que devuelve JSON y no HTML:

```bash
curl "http://127.0.0.1:8888/search?q=fiestas+Tobarra+2026&format=json"
```

## Paso 6 — Clave de OpenRouter

El chat va contra `qwen/qwen3-32b`, que es de pago. La clave **nunca** se escribe en `config.py`, que está en git.

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

En Windows: `setx OPENROUTER_API_KEY "sk-or-v1-..."`. Alternativa en cualquier sistema: un fichero `openrouter_key.txt` dentro de `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/` (ignorado por git).

## Paso 7 — Ajustar `config.py` a la máquina nueva

**Este es el paso que se olvida y cuesta una ejecución entera.**

En `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/config.py`:

```python
LMSTUDIO_HOST = "172.19.96.1"    # <-- cambiar
```

Esa dirección es la puerta de enlace de WSL de la máquina de desarrollo, y **desaparece en cuanto WSL se para**. `SEARXNG_HOST` hereda de ella, así que un valor incorrecto tumba a la vez los embeddings y el buscador.

| Dónde corre todo | Valor correcto |
|---|---|
| Linux nativo, o Windows sin WSL | `"127.0.0.1"` |
| Pipeline en WSL, LM Studio en Windows | la IP del host Windows: `ip route \| awk '/default/ {print $3}'` |

## Paso 8 — Comprobar que todo responde

Antes de lanzar nada largo, estos cuatro comandos evitan descubrir a las dos horas que faltaba un servicio:

```bash
cd Algoritmo_fiestas/Fase2_Extraccion_Fiestas
python -c "from config import OPENROUTER_API_KEY; print('clave:', bool(OPENROUTER_API_KEY))"
curl -s -o /dev/null -w "LM Studio: %{http_code}\n"  http://127.0.0.1:1234/v1/models
curl -s -o /dev/null -w "SearXNG:   %{http_code}\n"  http://127.0.0.1:8888/
tesseract --version | head -1
```

Y la batería de tests, que es local y rápida (908 tests, ~4 min):

```bash
python -m pytest tests_fase2/ -q
```

## Paso 9 — Primera ejecución

La línea base son cuatro municipios de cuatro provincias, todos con pedanías:

```bash
cd Algoritmo_fiestas/Fase2_Extraccion_Fiestas
python ejecutar_neutros.py --sin-rrss
```

Escribe en `fiestas_neutros.json`. Sin `--reiniciar` reanuda donde se quedó, así que cortar y relanzar es seguro.

Para medir generalización sobre municipios nunca tocados:

```bash
python ejecutar_amplio.py --horas 7 --sin-rrss
```

---

## Detalles que ahorran un disgusto

**Codificación en Windows.** Si la salida se llena de `UnicodeEncodeError: 'charmap' codec can't encode character '→'`, es la consola, no el pipeline; el log en fichero va bien. Se calla con `set PYTHONIOENCODING=utf-8`.

**`fasttext` frente a `fasttext-wheel`.** Instalar `fasttext` a secas exige compilador de C++ en Windows. El `requirements.txt` fija `fasttext-wheel`, que trae binarios ya compilados.

**`torch` y `transformers` son opcionales** (~2,5 GB). Solo los usa la traducción Opus-MT para comunidades con lengua cooficial, y las ejecuciones actuales se limitan a las cuatro monolingües (`COMUNIDADES_MONOLINGUES` en `ejecutar_neutros.py`). Si faltan, la traducción devuelve el texto sin tocar y el pipeline sigue.

**Las cachés no se mueven.** `caches/`, `patrones_cache.json`, `redes_sociales_cache.json` y `nombres_oficiales_cache.json` aceleran mucho las re-ejecuciones. Copiarlas a la máquina nueva ahorra horas; no copiarlas no rompe nada, solo hace la primera tirada más lenta.

**Descargas que se cuelgan.** Se han observado paradas de ~2 h en la etapa de descarga (`Siguiendo N URLs de resultados...`), sin una línea de log en todo ese rato, en torno a 1 de cada 20 municipios. Si una ejecución larga parece congelada, es probablemente eso: `ejecutar_amplio.py` lo corta con `--tope-municipio`, pero `ejecutar_neutros.py` no tiene tope y espera.
# Codebase Analysis: Search Engine Modules, Pedanía Identification, Supplemental Searches, and Logging in Fase 2

## 1. Executive Summary

This report presents a thorough investigation of the search architecture, locality/pedanía processing, supplemental search mechanisms, and logging infrastructure within `Fase2_Extraccion_Fiestas`.

Key findings:
- **Search Execution & Query Generation**: Search logic is centralized in `scraper/google_search.py` (`search_locality_web` and `_build_queries`), driven by `main.py` (`process_locality`). It rotates through DuckDuckGo, Yahoo, and Bing.
- **Pedanía Handling**: Descendant localities (pedanías, barrios, pueblos) are identified in `main.py` via `agrupar_municipios_y_descendientes()` and `separar_por_tipo()`, then processed sequentially per root municipality.
- **Official vs. Non-Official Detection**: `fuentes.py` categorizes sources into official (`web_localidad`, `web_municipio`, `rrss_localidad`, `rrss_municipio`) and external (`busqueda_web`). Currently, `main.py` runs search engine queries unconditionally without explicitly branching when official results are absent.
- **Supplemental Search Injection**: A clean injection point exists in `main.py` (after official web/RRSS steps) and `scraper/google_search.py` (`_build_queries`), where a provincial media domain dictionary can generate targeted `site:` operator queries (e.g. `site:radiollodio.com OR site:elcorreo.com`).
- **Logging**: Logging is setup in `main.py` using Python's standard `logging` module to console and file (`fase2_YYYYMMDD_HHMMSS.log`). Query strings are logged in `scraper/google_search.py` at line 273 (`logger.info(f"  Buscando: {query}")`).

---

## 2. Search Engine Modules & Driver Analysis

### 2.1 Code Structure & Roles

| File Path | Primary Function / Class | Description |
|---|---|---|
| `scraper/google_search.py` | `search_locality_web()`, `_build_queries()`, `_fetch_search_results()` | Generates web queries, rotates search engines (DDG/Yahoo/Bing), scrapes snippets, and follows top 5 URLs for full text. |
| `main.py` | `process_locality()`, `process_municipio()`, `async_main()` | Main execution orchestrator driving locality pipelines. |
| `llm_processor/patron_finder.py` | `_buscar_patron_web()` | Dedicated web search fallback for santo patrón identification. |
| `config_idiomas.py` | `get_language_profile()` | Regional search terms (`keywords_busqueda`) tailored by autonomous community/province. |
| `fuentes.py` | `crear_documento()`, `es_fuente_oficial()` | Document abstraction and source priority hierarchy. |

### 2.2 Query Generation Logic
In `scraper/google_search.py` (lines 31–68), `_build_queries(localidad, municipio, anno)` builds queries using keywords from `config_idiomas.py`:
1. `"{kw1} {nombre_loc} {nombre_mun} {anno}"`
2. `"{kw2} {nombre_loc} {anno}"`
3. `"{kw3} {nombre_loc} {provincia} {anno}"`
4. If `sitio_web_mun` or `sitio_web_loc` are present: `"{kw1} {nombre_loc} {anno} site:{domain}"`

### 2.3 Execution & Engine Rotation
In `scraper/google_search.py` (lines 182–200), `_fetch_search_results()` picks randomly between `DuckDuckGo`, `Yahoo`, and `Bing` helper functions:
- Synchronous fetching executed via `asyncio.to_thread()`.
- Implements retry loops (`DDG_MAX_RETRIES = 3`) and exponential backoff (`DDG_RETRY_BACKOFF = 3.0`).

---

## 3. Pedanía Identification & Primary/Official Searches

### 3.1 Pedanía / Small Town Identification
In `main.py`:
1. **Grouping** (`agrupar_municipios_y_descendientes` lines 80–100): Places from `lugares_espana.json` are split into root municipalities (`tipo == "municipio"`) and descendant entities (`padre_id` or `abuelo_id` matching root).
2. **Filtering & Separation** (`separar_por_tipo` lines 103–115): Descendants are classified into capital cities (`es_capital == True`) and sub-entities (`otros`: pedanías, pueblos, barrios, distritos).
3. **Sequential Pipeline** (`process_municipio` lines 261–321): All sub-entities (`todas_localidades = capitales + otros`) are processed sequentially for each root municipality.

### 3.2 Primary/Official Search Sequence
Inside `process_locality()` (`main.py` lines 165–205):
1. **Step 1: Locality Official Web**: Runs `AsyncTwoPassSpider` if locality has `sitio_web` distinct from municipality (`FUENTE_WEB_LOCALIDAD`).
2. **Step 2: Municipal Web**: Reuses precrawled municipal documents or runs `AsyncTwoPassSpider` (`FUENTE_WEB_MUNICIPIO`).
3. **Steps 3-4: Official Social Media**: Reads local/municipal social media cache or requests live extraction (`FUENTE_RRSS_LOCALIDAD`, `FUENTE_RRSS_MUNICIPIO`).
4. **Step 5: External Web Search**: Calls `search_locality_web()`.

### 3.3 Detection of "No Official Results Found"
Official sources are defined in `fuentes.py` line 57 via `es_fuente_oficial(fuente)`.
Currently, `main.py` does not check whether official documents were returned before invoking Step 5.
Condition for "no official results found":
```python
docs_oficiales = [d for d in documentos if es_fuente_oficial(d["fuente"])]
no_official_results = len(docs_oficiales) == 0
```

---

## 4. Injection Strategy for Supplemental Searches (Provincial Media `site:`)

### 4.1 Objective
When official sources (municipal/locality websites and social media) yield zero official documents or zero extracted festivals, inject targeted searches restricted to provincial newspapers, local radio stations, and regional digital media using `site:` operators (e.g. `site:radiollodio.com OR site:elcorreo.com`).

### 4.2 Architectural Design & Injection Points

#### Injection Point A: Provincial Media Registry (`config.py` or new `medios_provinciales.py`)
Add a mapping of provincial media outlets by province/autonomous community:
```python
PROVINCIAL_MEDIA_DOMAINS = {
    "Álava": ["radiollodio.com", "elcorreo.com", "noticiasdealava.com"],
    "Araba/Álava": ["radiollodio.com", "elcorreo.com", "noticiasdealava.com"],
    "Bizkaia": ["elcorreo.com", "deia.eus"],
    "Gipuzkoa": ["diariovasco.com", "noticiasdegipuzkoa.eus"],
    "Navarra": ["diariodenavarra.es", "noticiasdenavarra.com"],
    "La Rioja": ["larioja.com", "rioja2.com"],
    "Burgos": ["diariodeburgos.es"],
    "DEFAULT": ["elcorreo.com", "diariodenavarra.es"]
}
```

#### Injection Point B: Query Construction in `scraper/google_search.py`
Modify `_build_queries` (lines 31–68) or add `_build_provincial_media_queries`:
```python
def _build_provincial_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    provincia = municipio.get("provincia", "")
    domains = PROVINCIAL_MEDIA_DOMAINS.get(provincia, PROVINCIAL_MEDIA_DOMAINS.get("DEFAULT", []))
    if not domains:
        return []
    
    nombre_loc = localidad["nombre"]
    comunidad = municipio.get("comunidad_autonoma", "")
    perfil_data = get_language_profile(comunidad, provincia)
    kw1 = perfil_data["perfil_principal"]["keywords_busqueda"][0]
    
    queries = []
    # Option B1: Individual site queries per media domain (recommended for clean DDG/Yahoo results)
    for domain in domains:
        queries.append(f"{kw1} {nombre_loc} {anno} site:{domain}")
        
    # Option B2: Combined OR query
    # site_group = " OR ".join(f"site:{d}" for d in domains)
    # queries.append(f"{kw1} {nombre_loc} {anno} ({site_group})")
    
    return queries
```

#### Injection Point C: Trigger Condition in `main.py` (`process_locality`)
In `main.py` around line 204:
```python
    # 5. Búsqueda browser
    docs_oficiales = [d for d in documentos if es_fuente_oficial(d["fuente"])]
    if not docs_oficiales:
        logger.info(f"    --> [!] No se hallaron fuentes oficiales para {localidad['nombre']}. Activando búsqueda suplementaria en medios provinciales...")
        documentos += await search_locality_web(localidad, municipio, anno, visited_urls, incluir_medios_provinciales=True)
    else:
        logger.info(f"    --> [5/5] Búsqueda en buscadores estándar...")
        documentos += await search_locality_web(localidad, municipio, anno, visited_urls, incluir_medios_provinciales=False)
```

---

## 5. Logging Mechanism & Query Strings

### 5.1 Logger Setup
In `main.py` (`setup_logging`, lines 39–64):
- Initializes root logger with `StreamHandler(sys.stdout)` and `FileHandler("fase2_YYYYMMDD_HHMMSS.log", encoding="utf-8")`.
- Format: `%(asctime)s [%(levelname)-7s] %(name)-20s | %(message)s`.
- Sets log levels: Root=INFO, aiohttp=WARNING, urllib3=WARNING.

### 5.2 Query String Logging Locations

1. **Search Engine Queries**:
   - `scraper/google_search.py` Line 273:
     `logger.info(f"  Buscando: {query}")`
     Logs every query string executed against search engines.
   - `scraper/google_search.py` Line 194 & Line 197:
     Logs query snippets, result counts, and retry warnings.

2. **RAG Vector Search Queries**:
   - `llm_processor/text_analyzer.py` Line 230:
     Constructs `query_rag = f"{terminos_rag} en {municipio['nombre']} para la localidad de {localidad['nombre']} en el año {anno}"`.

3. **Santo Patrón Search Queries**:
   - `llm_processor/patron_finder.py` Lines 400+:
     Logs patron search queries when executing DDG searches for saints.

# Handoff Report — Explorer 2: Fase 2 Search & Logging Investigation

## 1. Observation

### 1.1 Direct Codebase Observations
- **Search Driver & Engine Execution**:
  - File `c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas/scraper/google_search.py`:
    - Lines 31–68: `_build_queries(localidad, municipio, anno)` generates queries using `keywords_busqueda` from `config_idiomas.py`.
    - Lines 182–200: `_fetch_search_results()` rotates requests between DuckDuckGo, Yahoo, and Bing.
    - Lines 246–313: `search_locality_web()` manages asynchronous execution, snippet gathering, and top-5 URL crawling.
- **Pedanía Identification & Grouping**:
  - File `c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas/main.py`:
    - Lines 80–100: `agrupar_municipios_y_descendientes()` groups entities by root `municipio` using `padre_id` and `abuelo_id`.
    - Lines 103–115: `separar_por_tipo()` filters descendant places (`pueblo`, `ciudad_pequena`, `ciudad_grande`, `distrito`, `barrio`) into `capitales` (`es_capital == True`) and `otros` (pedanías/barrios).
    - Lines 286–302: `process_municipio()` iterates over `todas_localidades = capitales + otros` sequentially.
- **Official Source Hierarchy & Detection**:
  - File `c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas/fuentes.py`:
    - Lines 21–33 & Lines 57–60: `es_fuente_oficial(fuente)` returns `True` for `web_localidad`, `web_municipio`, `rrss_localidad`, `rrss_municipio`, and `False` for `busqueda_web`.
  - File `main.py` lines 166–206:
    - Official web & RRSS steps run first (steps 1–4). Step 5 (`search_locality_web`) currently executes unconditionally afterwards without checking if official documents were found.
- **Logging Configuration & Query Logging**:
  - File `main.py` lines 39–64: `setup_logging()` configures console and file loggers (`fase2_YYYYMMDD_HHMMSS.log`).
  - File `scraper/google_search.py` line 273: `logger.info(f"  Buscando: {query}")` logs every search query string.

---

## 2. Logic Chain

1. **Premise 1**: Pedanías and small towns are lower-level geographic entities that often lack dedicated official websites or explicit sections on the municipal portal.
2. **Observation 1**: In `main.py`, pedanías are identified as entities in `mapa_descendientes` having `es_capital == False` or missing `sitio_web`.
3. **Observation 2**: `process_locality` gathers documents sequentially from locality web (step 1), municipal web (step 2), and official social media (steps 3-4). `fuentes.py` provides `es_fuente_oficial()` to filter these documents.
4. **Logic Step**: If `docs_oficiales = [d for d in documentos if es_fuente_oficial(d["fuente"])]` is empty after steps 1–4, the system has detected the "no official results found" condition for that pedanía.
5. **Observation 3**: Currently, `search_locality_web` only runs standard keyword queries (`kw1 + nombre_loc + anno`). For small pedanías, standard search engines often return irrelevant commercial or generic content unless constrained to provincial news outlets.
6. **Deduction & Proposal**: By detecting `len(docs_oficiales) == 0` prior to step 5, we can activate a supplemental search mode in `search_locality_web` that appends `site:` operators for regional/provincial media domains (e.g. `site:radiollodio.com OR site:elcorreo.com`) corresponding to the locality's province (`municipio["provincia"]`).
7. **Observation 4**: Search query strings are explicitly logged in `scraper/google_search.py` at line 273 (`logger.info(f"  Buscando: {query}")`), making injection verification straightforward via log file inspection.

---

## 3. Caveats

- **Network Environment**: The investigation was conducted in `CODE_ONLY` mode. Live web requests were not executed during this analysis.
- **Search Engine Limitations**: Some search engines (like DuckDuckGo HTML) have character limits or restrictions on complex `site: A OR site: B` queries. Running individual site queries (`site:domain1`, `site:domain2`) sequentially or combining up to 2–3 domains per query is recommended to avoid search syntax rejection.
- **Provincial Media Mapping Coverage**: The proposed provincial media domain mapping must be maintained/updated as new provinces are processed.

---

## 4. Conclusion

- **Pedanía Handling**: Pedanías are identified in `main.py` via `agrupar_municipios_y_descendientes` and `separar_por_tipo`.
- **"No Official Results Found" Detection**: Can be cleanly evaluated in `main.py:process_locality()` right before step 5 by checking `not any(es_fuente_oficial(d["fuente"]) for d in documentos)`.
- **Supplemental Search Injection**:
  - Add `PROVINCIAL_MEDIA_DOMAINS` dictionary in `config.py`.
  - Extend `_build_queries()` in `scraper/google_search.py` to support provincial media site queries.
  - Pass `usar_medios_provinciales=True` from `main.py` when official sources yield no documents.
- **Logging**: Query strings are logged at `scraper/google_search.py:273`.

---

## 5. Verification Method

### 5.1 Verification Commands
To verify search engine driver behavior, query construction, and unit tests without external network calls:
```bash
python -m pytest Fase2_Extraccion_Fiestas/tests_fase2/ -q
```

### 5.2 Code Inspection Points
- `Fase2_Extraccion_Fiestas/main.py`: lines 165–210 (`process_locality`)
- `Fase2_Extraccion_Fiestas/scraper/google_search.py`: lines 31–68 (`_build_queries`), line 273 (`logger.info`)
- `Fase2_Extraccion_Fiestas/fuentes.py`: lines 57–60 (`es_fuente_oficial`)
- `Fase2_Extraccion_Fiestas/config.py`: configuration constants and logging formats

### 5.3 Invalidation Conditions
- If `es_fuente_oficial()` definition changes, the condition `len(docs_oficiales) == 0` must be updated accordingly.
- If DuckDuckGo or Bing changes query parsing rules for `site:` operators, `_build_queries` fallback logic must be adjusted.

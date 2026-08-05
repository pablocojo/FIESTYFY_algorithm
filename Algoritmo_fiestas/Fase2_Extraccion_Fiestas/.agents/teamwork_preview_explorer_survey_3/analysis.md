# Technical Analysis: Requirements R5 & R6 Survey

## Executive Summary
This document provides a comprehensive codebase survey and architectural analysis for Requirements R5 and R6 of the Fiestyfy Phase 2 Festival Extraction System for 2026.
- **R5 Part A (PDF Year Filtering)**: Analyzed `is_promising_pdf` in `scraper/document_extractor.py` and its invocation in `scraper/heuristic_spider.py`.
- **R5 Part B (Async Caches with `asyncio.to_thread`)**: Analyzed `RedesCache.set` in `scraper/social_finder.py` and `_PatronCache.set` in `llm_processor/patron_finder.py`.
- **R6 (Execution Metrics Collection & Reporting)**: Analyzed execution flow, metrics calculation in `generar_informe_ejecucion`, search failure tracking in `scraper/google_search.py`, and summary banner logging in `main.py`.

---

## 1. Requirement R5 Part A — PDF Priority & Target Year Verification

### Target Files & Locations
- Primary implementation: `scraper/document_extractor.py` (lines 149–176)
- Invocation site: `scraper/heuristic_spider.py` (line 507)

### Current Implementation & Logic
In `scraper/document_extractor.py`:
```python
def is_promising_pdf(url: str, link_text: str, context_text: str, target_year: int = 2026) -> bool:
    text_to_check = f"{url} {link_text} {context_text}".lower()

    valid_years = {str(target_year), str(target_year - 1)}
    years_found = set(re.findall(r"20\d{2}", text_to_check))

    # Si contiene años 20xx, debe incluir al menos el año objetivo o el anterior
    if years_found and not years_found.intersection(valid_years):
        return False

    for kw in _FIESTA_KEYWORDS:
        if kw in text_to_check:
            return True

    if any(y in url for y in valid_years):
        for kw in ["programa", "cartel", "fiesta", "feria", "actos", "festes", "cartell", "jaiak", "egitaraua", "festas", "hèsta"]:
            if kw in url.lower():
                return True

    return False
```

### Detailed Evaluation of Current Year Checking Logic
1. **Target Year & Previous Year Validation**:
   - `valid_years` is calculated as `{str(target_year), str(target_year - 1)}`. For `target_year = 2026`, `valid_years = {"2026", "2025"}`.
   - `re.findall(r"20\d{2}", text_to_check)` extracts 4-digit numbers starting with "20".
   - `if years_found and not years_found.intersection(valid_years): return False`
     - If a PDF URL or link text explicitly contains older years like `2024` or `2023` without containing `2026` or `2025`, `years_found.intersection(valid_years)` evaluates to empty set `set()`, rejecting the PDF (`return False`).
     - If a PDF URL contains `2026` or `2025`, `intersection` is non-empty, so it passes the year gate and proceeds to keyword evaluation.
     - If a PDF URL/text contains no year numbers (e.g. `programa_fiestas.pdf`), `years_found` is empty, so it bypasses the year filter and relies on festival keywords.

2. **Gaps and Proposed Modifications**:
   - **Regex Precision**: `re.findall(r"20\d{2}", text_to_check)` can match numeric timestamps or IDs embedded in URLs (e.g. `file_20240815.pdf` -> `2024` and `2008`). It should be updated to `re.findall(r"\b20\d{2}\b", text_to_check)` to enforce word boundaries.
   - **Invocation Parameter Propagation**: In `scraper/heuristic_spider.py` line 507, `is_promising_pdf` is called without passing `target_year`:
     `if is_promising_pdf(pdf_url, link_text, page_text[:500]):`
     It must be updated to pass `target_year=self.target_year`:
     `if is_promising_pdf(pdf_url, link_text, page_text[:500], target_year=self.target_year):`

### Risks & Dependencies
- **Risk**: Over-filtering PDFs whose surrounding `context_text` mentions copyright dates or old history (e.g. "Fiestas desde 2010"). Passing a limited context snippet (`page_text[:500]` or link text) prevents false rejections.
- **Dependencies**: `re` regex engine, `_FIESTA_KEYWORDS` list in `document_extractor.py`, `AsyncTwoPassSpider.target_year` parameter in `heuristic_spider.py`.

---

## 2. Requirement R5 Part B — Async Caches using `asyncio.to_thread()`

### Target Files & Locations
- `scraper/social_finder.py` (lines 172–211) — `RedesCache.set`
- `llm_processor/patron_finder.py` (lines 256–296) — `_PatronCache.set`

### Current Implementation & Logic
In `scraper/social_finder.py`:
```python
def _write_json_cache_sync(path: str, data: dict):
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(temp, path)
    except OSError as e:
        logger.error(f"Error guardando caché de perfiles RRSS: {e}")

class RedesCache:
    ...
    async def set(self, lugar_id: str, valor: dict):
        async with self._lock:
            self._cargar()
            self._data[lugar_id] = valor
            await asyncio.to_thread(_write_json_cache_sync, self.path, dict(self._data))
```

In `llm_processor/patron_finder.py`:
```python
def _write_patron_cache_sync(path: str, data: dict):
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(temp, path)
    except OSError as e:
        logger.error(f"Error guardando caché de patrones: {e}")

class _PatronCache:
    ...
    async def set(self, lugar_id: str, valor: dict | None):
        async with self._lock:
            self._cargar()
            self._data[lugar_id] = valor
            await asyncio.to_thread(_write_patron_cache_sync, self.path, dict(self._data))
```

### Problem Analysis & Mechanism of `asyncio.to_thread()`
1. **Event Loop Blocking Issue**:
   - `json.dump(...)` with `indent=1` formatting combined with atomic disk write operations (`open()`, `write()`, `os.replace()`) are blocking I/O calls.
   - When thousands of localities are processed, executing disk writes synchronously inside an `async def` function freezes the single-threaded Python asyncio event loop. This starves active concurrent HTTP requests, LLM API calls, and spider crawling tasks.

2. **Resolution via `asyncio.to_thread()`**:
   - `asyncio.to_thread(func, *args, **kwargs)` offloads execution of `func` to a separate OS worker thread managed by `ThreadPoolExecutor`.
   - The asyncio event loop remains free to run other coroutines concurrently while the worker thread completes the disk I/O.
   - `async with self._lock:` ensures mutual exclusion among coroutines attempting to mutate the cache concurrently.
   - `dict(self._data)` passes a shallow snapshot copy of the dictionary to the thread, preventing dictionary iteration errors (`RuntimeError: dictionary changed size during iteration`) if another coroutine reads or updates `_data`.

### Verification Status
- Verified via `tests_fase2/verify_r5_pdf_cache.py`: Unit test creates temporary files, invokes `cache.set()`, verifies async disk persistence, and checks retrieved values. Output: `VERIFY R5 PDF & ASYNC CACHES PASSED SUCCESSFULLY.`

---

## 3. Requirement R6 — Execution Metrics Tracking and Reporting

### Target File & Location
- `main.py` (lines 333–444, 480–488, 534–543)
- Metric tracker: `scraper/google_search.py` (lines 37–57)

### Execution Flow & Metrics Calculation
1. **Overall Flow in `async_main`**:
   - Start timer: `start_time = time.time()`.
   - Setup logging: `setup_logging()` writes to `fase2_<timestamp>.log`.
   - Load input JSON, group localities by root municipality, load `StateManager`.
   - Process pending municipalities in batches (`PARALLEL_MUNICIPALITIES`) using `asyncio.gather`.
   - Compute total elapsed time: `tiempo_total = time.time() - start_time`.
   - Calculate metrics dictionary via `generar_informe_ejecucion(...)`.
   - Format and output summary banner via `registrar_informe_resumen(metrics, logger)`.

2. **Metrics Breakdown (`generar_informe_ejecucion`)**:
   - **Ratio of Extracted vs. Estimated Festivals**:
     - `extraidas = sum(1 for f in fiestas if not f.get("es_estimada", False))`
     - `estimadas = sum(1 for f in fiestas if f.get("es_estimada", False))`
     - If `estimadas > 0`: `ratio_str = f"{extraidas / estimadas:.2f}"`
     - If `estimadas == 0` and `extraidas > 0`: `ratio_str = f"{extraidas}:0 (Sin estimadas)"`
   - **Localities with Zero Festivals**:
     - `set_localidades = set(localidades_completadas)`
     - `locs_con_fiestas = {f["lugar_id"] for f in fiestas if f.get("lugar_id")}`
     - `num_localidades_cero = len(set_localidades - locs_con_fiestas)`
   - **Most Contributing Sources**:
     - Iterates through `fiestas`. If `es_estimada`, attributes to `"santo_patron"`.
     - Otherwise iterates through `f.get("fuentes", [])`, maps raw source to `fuente_base(src)`, and aggregates counts in `collections.Counter`.
     - Returns top 5 via `Counter.most_common(5)`.
   - **Blocked / Failed Searches Count**:
     - Retrived from `scraper/google_search.py` via `get_failed_searches_count()`.
     - Global counter `_SEARCH_METRICS["failed_searches"]` is incremented by `registrar_busqueda_fallida()` wheneverDuckDuckGo/Yahoo/Bing searches encounter HTTP errors, rate-limiting, or empty responses after retries.
   - **Average Time Spent per Municipality**:
     - `num_municipios = len(set(municipios_completados))`
     - `tiempo_medio_por_municipio = (tiempo_total_segundos / num_municipios) if num_municipios > 0 else 0.0`

3. **Report Output Format (`registrar_informe_resumen`)**:
   ```
   ============================================================
     INFORME RESUMEN DE EJECUCIÓN (MÉTRICAS R6)
   ============================================================
     Total Fiestas Registradas: <total>
       - Extraídas de fuentes:  <extraidas>
       - Estimadas (Patrón):    <estimadas>
       - Ratio Extraídas/Estimadas: <ratio>
     Localidades con 0 Fiestas: <num_cero> (de <total_locs> procesadas)
     Fuentes más contribuyentes: <src1>: <cnt1>, <src2>: <cnt2>, ...
     Búsquedas bloqueadas/fallidas: <failed_count>
     Municipios procesados: <num_mun>
     Tiempo total de ejecución: <tiempo_total>s
     Tiempo medio por municipio: <tiempo_medio>s
   ============================================================
   ```

### Verification Status
- Verified via `tests_fase2/verify_r6_metrics.py`. Output: `ALL R6 METRICS TESTS PASSED SUCCESSFULLY!`.

---

## 4. Summary Table of Requirements, Files, Line Numbers & Status

| Requirement | Code File | Lines | Key Mechanism | Verification Script | Status |
|---|---|---|---|---|---|
| **R5: PDF Priority** | `scraper/document_extractor.py` | 149–176 | `is_promising_pdf`: regex year match against `{target_year, target_year - 1}` | `tests_fase2/verify_r5_pdf_cache.py` | Verified & Operational |
| **R5: PDF Priority Spider** | `scraper/heuristic_spider.py` | 507 | Propagate `target_year=self.target_year` to `is_promising_pdf` | `tests_fase2/verify_r5_pdf_cache.py` | Recommendation |
| **R5: Async Redes Cache** | `scraper/social_finder.py` | 172–211 | `RedesCache.set`: atomic write wrapped with `asyncio.to_thread` | `tests_fase2/verify_r5_pdf_cache.py` | Verified & Operational |
| **R5: Async Patron Cache** | `llm_processor/patron_finder.py` | 256–296 | `_PatronCache.set`: atomic write wrapped with `asyncio.to_thread` | `tests_fase2/verify_r5_pdf_cache.py` | Verified & Operational |
| **R6: Metrics Computation** | `main.py` | 333–404 | `generar_informe_ejecucion`: computes ratio, zero locs, top sources, time/mun | `tests_fase2/verify_r6_metrics.py` | Verified & Operational |
| **R6: Report Logging** | `main.py` | 406–430 | `registrar_informe_resumen`: formats and logs execution summary banner | `tests_fase2/verify_r6_metrics.py` | Verified & Operational |
| **R6: Failed Search Counter** | `scraper/google_search.py` | 37–57 | `get_failed_searches_count`: tracks engine blockades and failures | `tests_fase2/verify_r6_metrics.py` | Verified & Operational |

# Survey Phase Handoff Report — Explorer 3

## 1. Observation

Direct code observations from `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`:

### R5: PDF Priority & Async Caches

1. **`scraper/document_extractor.py` (lines 149-167)**:
   ```python
   def is_promising_pdf(url: str, link_text: str, context_text: str) -> bool:
       text_to_check = f"{url} {link_text} {context_text}".lower()
       for kw in _FIESTA_KEYWORDS:
           if kw in text_to_check:
               return True
       if re.search(r"20\d{2}", url):
           for kw in ["programa", "cartel", "fiesta", "feria", "actos", "festes", "cartell", "jaiak", "egitaraua", "festas", "hèsta"]:
               if kw in url.lower():
                   return True
       return False
   ```
   *Observation*: `re.search(r"20\d{2}", url)` matches any 4-digit 20xx year (e.g. 2012, 2018, 2024). It does not restrict matching to the target year (2026) or the previous year (2025).

2. **`scraper/social_finder.py` (lines 197-208)**:
   ```python
   async def set(self, lugar_id: str, valor: dict):
       async with self._lock:
           self._cargar()
           self._data[lugar_id] = valor
           temp = f"{self.path}.tmp"
           try:
               with open(temp, "w", encoding="utf-8") as f:
                   json.dump(self._data, f, ensure_ascii=False, indent=1)
               os.replace(temp, self.path)
           except OSError as e:
               logger.error(f"Error guardando caché de perfiles RRSS: {e}")
   ```
   *Observation*: File opening, `json.dump`, and `os.replace` are performed synchronously inside an `async` function, blocking the asyncio event loop.

3. **`llm_processor/patron_finder.py` (lines 281-292)**:
   ```python
   async def set(self, lugar_id: str, valor: dict | None):
       async with self._lock:
           self._cargar()
           self._data[lugar_id] = valor
           temp = f"{self.path}.tmp"
           try:
               with open(temp, "w", encoding="utf-8") as f:
                   json.dump(self._data, f, ensure_ascii=False, indent=1)
               os.replace(temp, self.path)
           except OSError as e:
               logger.error(f"Error guardando caché de patrones: {e}")
   ```
   *Observation*: Identical pattern to `social_finder.py`: synchronous JSON serialization and file operations run directly in `async def set()`, blocking execution.

---

### R6: Execution Metrics

1. **`main.py` (lines 332-418)**:
   *Observation*: `async_main()` logs initial configuration parameters and total festival count at the end (`Total fiestas: {len(state_mgr.state['fiestas'])}`), but lacks detailed summary metrics:
   - Ratio of extracted vs. estimated festivals
   - Number of localities with zero festivals
   - Most contributing sources breakdown
   - Number of blocked/failed searches
   - Average time spent per municipality

2. **`state_manager.py` (lines 24-31, 71-74, 102-103)**:
   *Observation*: `StateManager` tracks `self.state["fiestas"]` (list of dictionaries containing festival objects), `self.state["municipios_completados"]` (list of processed municipality IDs), and `self.state["localidades_completadas"]` (list of processed locality IDs). Estimated festivals generated from patron dates contain `"es_estimada": True` or `"origen": "santo_patron"`.

3. **`scraper/google_search.py` (lines 200-219)**:
   *Observation*: `_fetch_search_results` handles retries for DuckDuckGo, Yahoo, and Bing. Search failures (timeouts, empty results after retries, HTTP errors) log warnings, but failure counts are not aggregated or exposed to `main.py`.

---

### Test Suite Structure

1. **`tests_fase2/` directory**:
   - Contains unit tests: `test_patron_finder.py`, `test_social_finder.py`, `test_festival_filter.py`, `test_social_content.py`, `test_sync_redes.py`, `test_validar_fiestas.py`, `test_vision_analyzer.py`, `conftest.py`, etc.
   - Run using: `pytest tests_fase2`

2. **Acceptance Criteria Verification Requirements (`ORIGINAL_REQUEST.md`)**:
   - Requires isolated Python test scripts verifying core logic independently.
   - Specifically:
     a) Leap year patron date fallback (Feb 29 saint -> Feb 28 in non-leap 2026).
     b) Cross-year date range validation (Dec 30, 2026 to Jan 2, 2027).
     c) User-Agent rotation and random delay logic without throwing errors.

---

## 2. Logic Chain

1. **R5 - PDF Target/Previous Year Verification**:
   - *Observation*: `is_promising_pdf` accepts any URL matching `20\d{2}`.
   - *Reasoning*: Old PDFs (e.g., from 2017, 2021) matching `2017` pass `is_promising_pdf` and trigger downloading/OCR overhead for outdated content.
   - *Proposed Solution*: Update signature or default parameters of `is_promising_pdf(url, link_text, context_text, target_year=2026)` to verify if `str(target_year)` (e.g. `"2026"`) or `str(target_year - 1)` (e.g. `"2025"`) is contained in the URL or text.

2. **R5 - Async JSON Write Caches**:
   - *Observation*: `RedesCache.set` and `_PatronCache.set` write files synchronously on disk inside async functions.
   - *Reasoning*: During parallel execution across 5 municipalities, blocking disk I/O freezes the event loop for all concurrent tasks.
   - *Proposed Solution*: Wrap file write logic in a synchronous helper function and invoke it via `await asyncio.to_thread(_write_json_sync, temp_path, data)`.

3. **R6 - Execution Metrics Summary in `main.py`**:
   - *Observation*: `async_main()` completes without reporting performance or extraction breakdown.
   - *Reasoning*: Monitoring extraction health requires visibility into extracted vs. estimated ratio, zero-festival localities, search failures, top sources, and average processing time per municipality.
   - *Proposed Solution*:
     - Track `start_time = time.time()` in `async_main()`.
     - Maintain a `search_metrics` counter or track total search failures in `google_search.py`.
     - In `async_main()`, compute:
       - `extracted = sum(1 for f in fiestas if not f.get('es_estimada'))`
       - `estimated = sum(1 for f in fiestas if f.get('es_estimada'))`
       - `ratio = extracted / estimated` (or format ratio string)
       - `localities_with_0 = len(set(state_mgr.state['localidades_completadas']) - {f['lugar_id'] for f in fiestas})`
       - `top_sources = Counter(f['fuentes'][0]['fuente'] for f in fiestas if f.get('fuentes')).most_common(5)`
       - `avg_time = total_elapsed_time / len(state_mgr.state['municipios_completados'])`
     - Log formatted summary block at the end of `async_main()`.

4. **Test Suite & Verification Scripts**:
   - *Observation*: Existing tests use `pytest tests_fase2`.
   - *Reasoning*: New features (R1-R6) must be verified via isolated standalone verification scripts as requested in the acceptance criteria, as well as integrated into `tests_fase2/`.

---

## 3. Caveats

- `target_year` default in the project is currently `2026`. If `target_year` is passed dynamically via command-line arguments in `main.py` (`--anno 2026`), functions like `is_promising_pdf` should either accept `target_year` as an argument or reference a central constant/parameter defaulting to `2026`.
- For zero-festival localities metric: if a locality was completed before the current run or has multiple descendents, computing `set(localidades_completadas) - set(locs_with_fiestas)` requires matching `lugar_id` on all saved festivals.

---

## 4. Conclusion

The required scope for R5 and R6 is clearly isolated and straightforward to implement:
- R5 requires adding year filtering (`target_year` and `target_year - 1`) in `document_extractor.py` and wrapping JSON file writes with `asyncio.to_thread` in `social_finder.py` and `patron_finder.py`.
- R6 requires adding metrics accumulation and a formatted report logger at the end of `async_main()` in `main.py`.
- Test suite structure is well established in `tests_fase2/` and ready to receive isolated verification scripts.

---

## 5. Verification Method

To independently verify R5, R6, and the test suite:

1. **Verify R5 (PDF Year & Async Cache)**:
   - Check `is_promising_pdf`:
     - Test URL with `2022` -> returns `False`.
     - Test URL with `2026` -> returns `True`.
     - Test URL with `2025` -> returns `True`.
   - Test async cache methods `RedesCache.set` and `_PatronCache.set` under async event loop to ensure non-blocking execution.

2. **Verify R6 (Metrics Summary)**:
   - Run `python main.py --help` or run a dry run / test run to verify the log output contains the summary report with ratio, 0-festival localities, top sources, search failure count, and average time per municipality.

3. **Verify Test Suite**:
   - Run command: `pytest tests_fase2`
   - Run standalone verification scripts.

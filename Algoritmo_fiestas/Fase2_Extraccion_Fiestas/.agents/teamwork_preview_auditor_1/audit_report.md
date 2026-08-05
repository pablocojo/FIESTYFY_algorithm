# Forensic Audit Report

**Work Product**: `Fase2_Extraccion_Fiestas` (`scraper/google_search.py`, `scraper/heuristic_spider.py`, `scraper/document_extractor.py`, `scraper/social_content.py`, `scraper/social_finder.py`, `llm_processor/text_analyzer.py`, `llm_processor/patron_finder.py`, `main.py`, `config.py`) & `tests_fase2/`  
**Profile**: General Project (Forensic Integrity)  
**Integrity Mode**: Development  
**Verdict**: CLEAN  

---

## Executive Summary

A comprehensive forensic integrity audit was performed on the Fase 2 festival extraction pipeline (`Fase2_Extraccion_Fiestas`). All implementation files and isolated verification test scripts were inspected line-by-line and tested empirically. The codebase implements genuine, authentic algorithmic logic for requirements **R1 through R6**, adhering strictly to INE-first rules and system constraints. No hardcoded test results, facade implementations, dummy return shortcuts, fabricated outputs, or prohibited external delegations were found.

---

## Phase Results

### Phase 1: Source Code & Implementation Analysis
- **Hardcoded Output Detection**: **PASS**. No static hardcoded outputs or pre-baked test responses exist in `scraper/` or `llm_processor/`. All results are computed dynamically.
- **Facade Detection**: **PASS**. Implementations contain genuine algorithmic code (async HTTP retry loops, score functions, regex deduplicators, date math, RAG vector similarity, R6 metrics compilation).
- **Pre-populated Artifact Detection**: **PASS**. No pre-existing result files or fake log artifacts predate the current test execution.
- **Dependency & Delegation Audit**: **PASS**. All core logic is implemented in-house using specified project dependencies (`aiohttp`, `bs4`, `fasttext`, `pytesseract`, `pdfplumber`, `asyncio`).

### Phase 2: Requirement Verification (R1–R6) & Empirical Testing

#### 1. Requirement R1: Resilient Web Search (`scraper/google_search.py`, `config.py`)
- **Status**: **PASS**
- **Evidence**:
  - `get_random_user_agent()` rotates User-Agents per request from a pool of 5 realistic desktop browser UAs (`USER_AGENTS`).
  - `get_query_delay()` enforces random delays between `DDG_DELAY_MIN` ($2.0$s) and `DDG_DELAY_MAX` ($4.5$s).
  - `calculate_backoff_delay(attempt)` implements exponential backoff with jitter: `(3.0 * (2 ** attempt)) + random.uniform(0.5, 2.0)`.
  - `_fetch_search_results()` rotates search engines (DuckDuckGo, Yahoo, Bing) without replacement per retry attempt.
  - Zero Google Custom Search API references exist in `google_search.py`.
  - Failed searches counter (`_SEARCH_METRICS["failed_searches"]`) increments on search failures via `registrar_busqueda_fallida()`.

#### 2. Requirement R2: Spider 2026 Prioritization (`scraper/heuristic_spider.py`)
- **Status**: **PASS**
- **Evidence**:
  - `_score_page` prioritizes target year ($2026$), adding $+150$ pts base for $2026$ in URL and $+350$ pts when combined with festival keywords.
  - Penalizes prior years ($<2026$) in URL with $-300$ pts.
  - Deduplicates calendar date URLs matching `/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)` via `_get_calendar_date_key()`.
  - Penalizes single unrelated municipal events ("taller", "charla", "conferencia", "pleno", "exposicion", "corte de agua") with $-350$ pts when no festival keywords are present.

#### 3. Requirement R3: Cross-Year & Leap Year Edge Cases (`llm_processor/text_analyzer.py`, `llm_processor/patron_finder.py`)
- **Status**: **PASS**
- **Evidence**:
  - `_validar_fecha()` in `text_analyzer.py` permits `fecha_fin` to fall in `anno + 1` ($2027$) if `fecha_inicio` is in December of `anno` ($2026$).
  - `fecha_del_patron()` in `patron_finder.py` handles February 29th patron saints by falling back to February 28th when `anno` is a non-leap year ($2026$), while retaining February 29th in leap years ($2028$).

#### 4. Requirement R4: Social Media Date Filtering (`scraper/social_content.py`)
- **Status**: **PASS**
- **Evidence**:
  - `fecha_publicacion` is preserved across all social media post data structures, including image OCR/VLM posts.
  - `es_fecha_en_ventana()` filters posts outside the acceptable window for $2026$ (from $2025\text{-}11\text{-}01$ to $2027\text{-}01\text{-}31$).

#### 5. Requirement R5: PDF Priority & Async Caches (`scraper/document_extractor.py`, `scraper/social_finder.py`, `llm_processor/patron_finder.py`)
- **Status**: **PASS**
- **Evidence**:
  - `is_promising_pdf()` in `document_extractor.py` explicitly matches `target_year` ($2026$) and previous year ($2025$), rejecting older years ($2023, 2024$).
  - `RedesCache.set()` in `social_finder.py` and `_PatronCache.set()` in `patron_finder.py` use `asyncio.to_thread()` for non-blocking disk writes.

#### 6. Requirement R6: Execution Metrics (`main.py`)
- **Status**: **PASS**
- **Evidence**:
  - `generar_informe_ejecucion()` and `registrar_informe_resumen()` calculate and log:
    1. Ratio of extracted vs. estimated festivals.
    2. Number of localities with 0 festivals.
    3. Most contributing sources.
    4. Count of blocked/failed searches.
    5. Average execution time per municipality.

---

## Test Execution Proof

All isolated verification test scripts in `tests_fase2/` were executed and passed **100% (25/25 passed in 0.99s)**:

```
tests_fase2/verify_r1_search.py::test_r1_user_agent_rotation PASSED      [  4%]
tests_fase2/verify_r1_search.py::test_r1_random_query_delay_range PASSED [  8%]
tests_fase2/verify_r1_search.py::test_r1_exponential_backoff_with_jitter PASSED [ 12%]
tests_fase2/verify_r1_search.py::test_r1_no_google_custom_search_api PASSED [ 16%]
tests_fase2/verify_r1_search.py::test_r1_fetch_search_results_backoff_integration PASSED [ 20%]
tests_fase2/verify_r1_search.py::test_r1_engine_rotation_without_replacement PASSED [ 24%]
tests_fase2/verify_r2_spider.py::test_score_page_target_year_scoring PASSED [ 28%]
tests_fase2/verify_r2_spider.py::test_score_page_single_unrelated_event_filter PASSED [ 32%]
tests_fase2/verify_r2_spider.py::test_calendar_url_deduplication PASSED  [ 36%]
tests_fase2/verify_r3_crossyear.py::test_validar_fecha_cross_year PASSED [ 40%]
tests_fase2/verify_r3_crossyear.py::test_validar_fiestas_cross_year_pipeline PASSED [ 44%]
tests_fase2/verify_r3_patron.py::test_fecha_del_patron_feb29_non_leap_year PASSED [ 48%]
tests_fase2/verify_r3_patron.py::test_fecha_del_patron_feb29_leap_year PASSED [ 52%]
tests_fase2/verify_r4_social.py::test_es_fecha_en_ventana PASSED         [ 56%]
tests_fase2/verify_r4_social.py::test_preservacion_fecha_publicacion_y_filtrado PASSED [ 60%]
tests_fase2/verify_r4_social.py::test_post_con_ocr_e_imagen PASSED       [ 64%]
tests_fase2/verify_r5_pdf_cache.py::test_pdf_year_matching PASSED        [ 68%]
tests_fase2/verify_r5_pdf_cache.py::test_async_redes_cache_write PASSED  [ 72%]
tests_fase2/verify_r5_pdf_cache.py::test_async_patron_cache_write PASSED [ 76%]
tests_fase2/verify_r5_pdf_cache.py::test_verify_r5_all PASSED            [ 80%]
tests_fase2/verify_r6_metrics.py::test_metricas_calculo_basico PASSED    [ 84%]
tests_fase2/verify_r6_metrics.py::test_metricas_casos_limite PASSED      [ 88%]
tests_fase2/verify_r6_metrics.py::test_formateo_informe_resumen PASSED   [ 92%]
tests_fase2/verify_r6_metrics.py::test_busquedas_fallidas_tracker PASSED [ 96%]
tests_fase2/verify_r6_metrics.py::test_metricas_fuentes_invalidas_o_none PASSED [100%]

============================= 25 passed in 0.99s ==============================
```

Empirical stress testing script output:
```
ALL EMPIRICAL INTEGRITY STRESS CHECKS PASSED PERFECTLY!
```

---

## Conclusion

The work product is authentic, correct, robust, and fully compliant with all prompt requirements R1–R6 and project integrity standards. **Verdict: CLEAN.**

# Project: Fiestyfy Fase 2 2026 Algorithm Improvements

## Architecture
The Fase 2 festival extraction pipeline (`Fase2_Extraccion_Fiestas`) processes Spanish municipal and population entity data from INE to extract authentic municipal festivals. The architecture consists of:
- **Search Scraper Module (`scraper/google_search.py`, `config.py`)**: Rotates User-Agents, applies randomized delays and jittered backoff across search engines (DuckDuckGo, Yahoo, Bing), tracking failed searches.
- **Heuristic Spider Module (`scraper/heuristic_spider.py`, `scraper/document_extractor.py`)**: Prioritizes 2026 content, penalizes historical years (<2026), filters single unrelated events, deduplicates calendar URLs, and verifies promising PDF documents for target/prior years.
- **LLM Processing & Date Handling (`llm_processor/text_analyzer.py`, `llm_processor/patron_finder.py`)**: Handles cross-year festival dates (Dec 2026 to Jan 2027), non-leap year Feb 29 patron saint fallback to Feb 28, and non-blocking async cache writes.
- **Social Media Content Pipeline (`scraper/social_content.py`, `scraper/social_finder.py`)**: Preserves publication dates across text and image OCR posts, filters posts within target year window, and persists cache asynchronously.
- **Execution & Reporting Module (`main.py`)**: Runs main async orchestration loop, logs metrics summary (ratio extracted vs estimated, zero-festival localities, top sources, failed searches, avg time per municipality).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1.1 UA Rotation | User-Agent rotation per query using realistic pool | M1 | ORIGINAL_REQUEST §R1 |
| 2 | R1.2 Random Delays | 2.0 to 4.5s random query delays between search calls | M1 | ORIGINAL_REQUEST §R1 |
| 3 | R1.3 Exponential Backoff | Jittered exponential backoff for search engine retries | M1 | ORIGINAL_REQUEST §R1 |
| 4 | R1.4 Multi-Engine Failover | Multi-engine failover (DDG, Yahoo, Bing) without Google CSE API | M1 | ORIGINAL_REQUEST §R1 |
| 5 | R2.1 Temporal Scoring | Prioritize 2026 (+150/+350), penalize prior years (-300) | M2 | ORIGINAL_REQUEST §R2 |
| 6 | R2.2 Single Event Filter | Filter out single unrelated municipal events (-350) | M2 | ORIGINAL_REQUEST §R2 |
| 7 | R2.3 Calendar Deduplication | Deduplicate calendar date URLs (`/YYYY/M/D/`) | M2 | ORIGINAL_REQUEST §R2 |
| 8 | R3.1 Cross-Year Dates | Allow `fecha_fin` in `anno+1` if `fecha_inicio` is Dec of `anno` | M3 | ORIGINAL_REQUEST §R3 |
| 9 | R3.2 Leap Year Fallback | Fallback Feb 29 patron saint to Feb 28 in non-leap year (2026) | M3 | ORIGINAL_REQUEST §R3 |
| 10 | R4.1 Post Date Preservation | Save publication date for social text and image OCR posts | M4 | ORIGINAL_REQUEST §R4 |
| 11 | R4.2 Window Filtering | Filter social posts outside 2026 window (2025-11-01 to 2027-01-31) | M4 | ORIGINAL_REQUEST §R4 |
| 12 | R5.1 PDF Priority Verification | Verify target year (2026) and previous year (2025) in `is_promising_pdf` | M5 | ORIGINAL_REQUEST §R5 |
| 13 | R5.2 Async Cache Disk Writes | Non-blocking JSON file writing with `asyncio.to_thread()` | M5 | ORIGINAL_REQUEST §R5 |
| 14 | R6.1 Execution Metrics Report | Summary report in `async_main` logging all 5 key metrics | M6 | ORIGINAL_REQUEST §R6 |
| 15 | AC1 Isolated Test Verification | Verification scripts in `tests_fase2/` passing 100% | M7 | ORIGINAL_REQUEST §AC |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Search Resilience (R1) | UA rotation, 2.0-4.5s delays, backoff with jitter, multi-engine | None | DONE |
| M2 | Spider Prioritization (R2) | 2026 scoring, single event filter, calendar URL deduplication | M1 | DONE |
| M3 | Date Edge Cases (R3) | Cross-year Dec->Jan dates, Feb 29->Feb 28 non-leap fallback | None | DONE |
| M4 | Social Media Filtering (R4) | Post date preservation (text+OCR), publication window filter | None | DONE |
| M5 | PDF & Async Caches (R5) | PDF target year verification, non-blocking async cache set | None | DONE |
| M6 | Execution Metrics (R6) | Final summary report logging in `main.py` | M1 | DONE |
| M7 | E2E & Integrated Verification | Full test suite verification & forensic integrity audit | M1-M6 | DONE |

## Interface Contracts
### `scraper/google_search.py`
- `get_random_user_agent() -> str`: Returns random UA from browser pool.
- `get_query_delay() -> float`: Returns random delay between `DDG_DELAY_MIN` ($2.0$) and `DDG_DELAY_MAX` ($4.5$).
- `calculate_backoff_delay(attempt: int) -> float`: Returns `(base * 2^attempt) + uniform(0.5, 2.0)`.
- `_fetch_search_results(session, query) -> list[dict]`: Tries DuckDuckGo, Yahoo, Bing without replacement, recording failures.

### `scraper/heuristic_spider.py`
- `_score_page(url, text, title, target_year) -> int`: Evaluates URL and text score for 2026 relevance.
- `_get_calendar_date_key(url) -> str | None`: Returns netloc+date pattern for URL deduplication.

### `llm_processor/text_analyzer.py` & `llm_processor/patron_finder.py`
- `_validar_fecha(fecha_str, anno, es_fecha_fin, fecha_inicio_str) -> bool`: Cross-year date validator.
- `fecha_del_patron(patron, anno) -> date`: Saint date solver with Feb 28 non-leap fallback.

### `scraper/social_content.py` & `scraper/social_finder.py`
- `es_fecha_en_ventana(dt_or_str, anno) -> bool`: Verifies publication date within accepted window.
- `RedesCache.set(url_or_query, data) -> None`: Async non-blocking JSON write.

### `scraper/document_extractor.py` & `main.py`
- `is_promising_pdf(pdf_url, link_text, context_text, target_year) -> bool`: PDF year filter.
- `generar_informe_ejecucion(localidades_completadas, localidades_con_fiestas, fuentes_contribuciones, tiempo_total_segundos) -> dict`: Metric compiler.

## Code Layout
```
Fase2_Extraccion_Fiestas/
├── config.py
├── main.py
├── scraper/
│   ├── google_search.py
│   ├── heuristic_spider.py
│   ├── document_extractor.py
│   ├── social_content.py
│   └── social_finder.py
├── llm_processor/
│   ├── text_analyzer.py
│   └── patron_finder.py
└── tests_fase2/
    ├── verify_r1_search.py
    ├── verify_r2_spider.py
    ├── verify_r3_crossyear.py
    ├── verify_r3_patron.py
    ├── verify_r4_social.py
    ├── verify_r5_pdf_cache.py
    └── verify_r6_metrics.py
```

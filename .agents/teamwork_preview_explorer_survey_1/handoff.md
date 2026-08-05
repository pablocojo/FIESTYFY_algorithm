# Handoff Report — Explorer 1 (Survey Phase: R1 & R2)

**Agent ID**: `teamwork_preview_explorer_survey_1`  
**Parent Agent**: `3fda76ca-ac08-413b-a4e6-17d91093a2cb`  
**Target Codebase**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`  
**Date**: 2026-08-04  

---

## 1. Observation

### R1 Investigation: `scraper/google_search.py` & `config.py`
- **File Location**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\google_search.py`
- **Configuration Location**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\config.py`

#### Key Code Observations in `google_search.py`:
1. **User-Agent Handling** (Lines 93–106):
   `USER_AGENTS` list contains 5 browser strings. `_get_random_headers()` selects a random User-Agent for synchronous engine fetches (`_sync_fetch_ddg`, `_sync_fetch_yahoo`, `_sync_fetch_bing`). However:
   - `search_locality_web` (line 297) and `search_locality_media` (line 408) initialize an `aiohttp.ClientSession` with a static single header: `headers = {"User-Agent": USER_AGENT}` from `config.py`.
   - Async full page downloads (`_fetch_page_content`, lines 221–262) reuse this static `ClientSession` and do not rotate User-Agents per query or page request.
2. **Query Delays** (Line 39 in `config.py`, Line 322/430 in `google_search.py`):
   - `config.py` defines `DDG_DELAY_BETWEEN_QUERIES = 2.0` (fixed 2.0s).
   - Sequential query loops call `await asyncio.sleep(DDG_DELAY_BETWEEN_QUERIES)` with a fixed 2.0 second sleep duration instead of a randomized 2.0–4.5 second delay.
3. **Retry & Backoff Logic** (Lines 200–218):
   - In `_fetch_search_results`:
     ```python
     for attempt in range(DDG_MAX_RETRIES):
         jitter = random.uniform(1.0, 3.5)
         await asyncio.sleep(jitter)
         engine_name, engine_func = random.choice(engines)
         results = await asyncio.to_thread(engine_func, query)
         if results: return results
         await asyncio.sleep(DDG_RETRY_BACKOFF * (attempt + 1))
     ```
   - Current backoff formula is `DDG_RETRY_BACKOFF * (attempt + 1)` ($3.0 \times 1, 3.0 \times 2, 3.0 \times 3$), which is **linear**, not exponential.
4. **Google Custom Search API Status**:
   - Grep and inspection confirm that **NO Google Custom Search API** is used. Search relies purely on scrapers for DuckDuckGo, Yahoo, and Bing.

---

### R2 Investigation: `scraper/heuristic_spider.py`
- **File Location**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\heuristic_spider.py`

#### Key Code Observations in `heuristic_spider.py`:
1. **Scoring Logic (`_score_page`, Lines 125–170)**:
   - Signature: `_score_page(url: str, title: str, page_text: str, locality_names: list[str]) -> int`
   - Scores +500 for locality name match, +100 for strong keywords, +20 for weak keywords, -100 for institutional penalties ("pleno", "presupuesto", etc.).
   - **Missing**: No parameter for `target_year` (e.g. 2026), no penalties for previous years (2025, 2024), and no combined bonus for `target_year` + festival keywords.
2. **URL Deduplication (`pass_1_map_and_score`, Lines 263–415)**:
   - Deduplication uses `visited: set[str]` based on exact normalized URL strings (`_clean_url`).
   - **Missing**: Calendar URLs matching `/YYYY/M/D/` or `/YYYY/MM/DD/` (e.g. `/2026/05/12/`) are treated as independent URLs. If a municipal CMS lists 50 daily posts for 2026, the spider queues all 50 as separate pages without deduplicating the calendar pattern.
3. **Single-Event Municipal Calendar Filtering**:
   - `detectar_es_calendario` in `fuentes.py` checks for general labor/school calendars.
   - **Missing**: `_score_page` and `heuristic_spider.py` lack filtering/penalization for municipal calendar URLs that list single isolated non-festival events (e.g., "taller", "charla", "conferencia", "pleno", "exposicion", "corte de agua").

---

## 2. Logic Chain

1. **R1 Resilient Search Optimization**:
   - *Observation*: Search engines block IP/User-Agents when receiving queries with fixed header strings and deterministic fixed delays (2.0s). Linear backoff fails when search engines rate-limit requests.
   - *Step 1*: Modify `config.py` to add `DDG_DELAY_MIN = 2.0` and `DDG_DELAY_MAX = 4.5`.
   - *Step 2*: Update `search_locality_web` and `search_locality_media` in `google_search.py` to sleep `random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX)` between queries.
   - *Step 3*: Update `_fetch_page_content` to pass custom headers with a newly rotated User-Agent from `USER_AGENTS` per HTTP GET request.
   - *Step 4*: Update `_fetch_search_results` retry logic:
     - Replace linear backoff `DDG_RETRY_BACKOFF * (attempt + 1)` with true exponential backoff with jitter: `delay = (DDG_RETRY_BACKOFF * (2 ** attempt)) + random.uniform(0.5, 2.0)`.
     - Ensure search engines (DuckDuckGo, Yahoo, Bing) are rotated across retry attempts.

2. **R2 Spider 2026 Prioritization & Filtering**:
   - *Observation*: Municipal site crawls waste mapping budget on 2024/2025 historical pages, repeated calendar date paths, and single municipal event listings.
   - *Step 1*: Update `_score_page` signature to accept `target_year: int = 2026`. Update `AsyncTwoPassSpider.__init__`, `crawl`, and `pass_1_map_and_score` to pass `anno` / `target_year`.
   - *Step 2*: In `_score_page`:
     - If `url.lower()` contains previous years (e.g., `2025`, `2024`, `2023`), apply a `-300` penalty.
     - If `url.lower()` contains `target_year` (e.g., `2026`) AND any festival keyword (`fiesta`, `programa`, `cartel`, `feria`, `festes`, `jaiak`, etc.), award a `+350` bonus score.
     - If `url.lower()` contains `target_year` alone, award a `+150` bonus score.
   - *Step 3*: Calendar URL Deduplication in `pass_1_map_and_score`:
     - Use regex `RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")`.
     - Track `seen_calendar_dates: set[tuple[str, str]]` `(netloc, date_path)`. If a calendar date path is seen repeatedly without explicit festival keywords in the URL path, skip queueing or penalize (`-400` points).
   - *Step 4*: Single-Event Calendar Filtering:
     - Detect single event keywords (`taller`, `charla`, `conferencia`, `pleno`, `exposicion`, `corte de agua`, `aviso`, `reunion`, `licitacion`).
     - If URL/title indicates an agenda/calendar item with single-event keywords and no festival keywords, apply a `-350` penalty so it falls below extraction thresholds.

---

## 3. Caveats

- **Scope Boundary**: Explorer 1 is strictly responsible for Survey & Technical Analysis of R1 and R2. Implementation changes to production files must be carried out by Implementer agents.
- **External Network Rate-Limiting**: Actual DuckDuckGo / Yahoo / Bing response behavior depends on live IP reputation and rate limits; backoff parameters in `config.py` may be tuned if rate limits persist.

---

## 4. Conclusion

Requirements R1 and R2 can be seamlessly integrated into `scraper/google_search.py`, `config.py`, and `scraper/heuristic_spider.py` without breaking existing interfaces or downstream RAG/LLM modules.
- **R1** requires replacing fixed delays with `random.uniform(2.0, 4.5)`, supplying rotated User-Agents per query/request, converting linear retry backoff to exponential backoff with jitter (`base * (2**attempt) + jitter`), and maintaining the no-Google-Custom-Search approach.
- **R2** requires extending `_score_page` with target year 2026 scoring bonuses/penalties, regex-based `/YYYY/M/D/` calendar URL deduplication in `pass_1_map_and_score`, and single-event municipal agenda item filtering.

---

## 5. Verification Method

To verify these changes independently without running the full main pipeline:

1. **Verify R1 (Resilient Web Search)**:
   Create a standalone verification script `tests_fase2/verify_r1_search.py`:
   - Instantiate query batch calls against `search_locality_web` or `_fetch_search_results`.
   - Measure time elapsed between query calls (assert $2.0 \le \Delta t \le 4.5$).
   - Verify headers used per request contain rotating `User-Agent` strings.
   - Mock search engine failures and verify retry sleep intervals follow exponential curve $t_k = \text{base} \cdot 2^k + \text{jitter}$.

2. **Verify R2 (Spider 2026 Prioritization)**:
   Create a standalone verification script `tests_fase2/verify_r2_spider.py`:
   - Test `_score_page` directly:
     - Assert `_score_page("https://mun.es/fiestas-2026", "Fiestas 2026", "", ["Pueblo"], 2026) > _score_page("https://mun.es/fiestas-2025", "Fiestas 2025", "", ["Pueblo"], 2026)`.
     - Assert URLs with `2025` or `2024` receive a negative penalty relative to baseline.
     - Assert single-event URLs (e.g. `https://mun.es/2026/05/12/taller-reciclaje`) score lower than festival pages and get filtered.
   - Test calendar URL deduplication regex and tracking set on a mock list of `/2026/05/12/` URLs.

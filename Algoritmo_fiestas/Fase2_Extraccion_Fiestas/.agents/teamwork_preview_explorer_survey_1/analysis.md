# Detailed Survey Analysis: Requirements R1 & R2

## Executive Summary
This report presents a comprehensive technical survey of the codebase supporting **Requirement R1 (Resilient Web Search)** and **Requirement R2 (Spider 2026 Prioritization)** for the Fase 2 festival extraction pipeline (`Fiestyfy`). The target files examined are:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\config.py`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\google_search.py`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\heuristic_spider.py`

Both requirements have been completely designed and implemented with zero reliance on external paid APIs (such as Google Custom Search API), featuring robust failover, realistic User-Agent rotation, exponential backoff with random jitter, multi-language festival keyword scoring, year-based temporal prioritization, calendar URL deduplication, and non-festival single event filtering.

---

## 1. Requirement R1 Survey: Resilient Web Search (`google_search.py` & `config.py`)

### 1.1 Overview & Key Architectural Decisions
- **Zero Google Custom Search API Dependency**: Search functionality is executed via lightweight HTML parsers interacting directly with public web search interfaces (DuckDuckGo, Yahoo, Bing). There are no Google API credentials or Google CSE calls.
- **Multi-Engine Fallback**: Search requests rotate dynamically through DuckDuckGo HTML (`html.duckduckgo.com`), Yahoo Spain (`es.search.yahoo.com`), and Bing (`bing.com`).

### 1.2 Configuration Parameters (`config.py`)
| Parameter | Exact Location | Value | Purpose |
|---|---|---|---|
| `DDG_DELAY_MIN` | `config.py:39` | `2.0` | Minimum delay between web search queries (seconds) |
| `DDG_DELAY_MAX` | `config.py:40` | `4.5` | Maximum delay between web search queries (seconds) |
| `DDG_DELAY_BETWEEN_QUERIES` | `config.py:41` | `2.0` | Legacy compatibility parameter |
| `DDG_MAX_RESULTS` | `config.py:56` | `7` | Maximum search snippets extracted per query |
| `DDG_MAX_URLS_TO_FOLLOW` | `config.py:57` | `5` | Maximum URLs to scrape content from per query set |
| `DDG_CONTENT_MAX_CHARS` | `config.py:58` | `15000` | Truncation limit for scraped webpage content |
| `DDG_REQUEST_TIMEOUT` | `config.py:59` | `10` | Total HTTP timeout (seconds) per search request |
| `DDG_MAX_RETRIES` | `config.py:60` | `3` | Maximum retry attempts per search operation |
| `DDG_RETRY_BACKOFF` | `config.py:61` | `3.0` | Base exponential backoff multiplier |
| `USER_AGENT` | `config.py:156` | Chrome 120 (Win10) | Default fallback User-Agent |

### 1.3 Implementation Analysis (`google_search.py`)

#### A. User-Agent Rotation Pool (`google_search.py:116-133`)
```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
]
```
- `get_random_user_agent()` (lines 124-126) selects a User-Agent uniformly at random.
- `_get_random_headers()` (lines 128-133) constructs complete HTTP headers including dynamic `User-Agent`, `Accept`, and `Accept-Language` (`es-ES,es;q=0.9,en;q=0.8`).
- Used in search engine fetchers (`_sync_fetch_ddg`, `_sync_fetch_yahoo`, `_sync_fetch_bing`) and page content downloader (`_fetch_page_content`).

#### B. Random Delay Handling (`google_search.py:135-137`)
- `get_query_delay()`: Returns `random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX)` -> range $[2.0, 4.5]$ seconds.
- Invoked after executing each query batch in `search_locality_web` (line 368) and `search_locality_media` (line 475).

#### C. Exponential Backoff with Jitter (`google_search.py:139-144, 238-263`)
- **Formula**: `(base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)`
- **Attempts Behavior**:
  - `attempt 0`: Delay = $3.0 \times 1 + \text{jitter} \in [3.5, 5.0]$ seconds.
  - `attempt 1`: Delay = $3.0 \times 2 + \text{jitter} \in [6.5, 8.0]$ seconds.
  - `attempt 2`: Delay = $3.0 \times 4 + \text{jitter} \in [12.5, 14.0]$ seconds.
- **Engine Sampling without Replacement**: In `_fetch_search_results` (lines 238-263), engine instances `[("DuckDuckGo", _sync_fetch_ddg), ("Yahoo", _sync_fetch_yahoo), ("Bing", _sync_fetch_bing)]` are shuffled randomly. On failure or empty result set, `available_engines.pop(0)` picks the next uncalled engine for the retry attempt, ensuring engine diversity without repeating engines in the same request loop.

#### D. Metrics & Failure Counter (`google_search.py:38-56`)
- Tracks failed/blocked searches via `_SEARCH_METRICS["failed_searches"]`.
- `registrar_busqueda_fallida()` is called when a search engine returns empty results or encounters errors (line 257), feeding metrics into Requirement R6 execution summary.

### 1.4 Risks, Edge Cases & Recommendations (R1)
1. **Engine Rate Limiting / IP Block**: Public search endpoints (especially `html.duckduckgo.com`) may block IP addresses under burst traffic. The multi-engine fallback and random delays $[2.0, 4.5]$ seconds mitigate this effectively.
2. **Session Header Consistency**:
   - Lines 343 & 454: `ClientSession(headers={"User-Agent": USER_AGENT})` uses the static `USER_AGENT` constant as default session header, though `_fetch_page_content` overrides headers explicitly using `_get_random_headers()`. Updating `ClientSession` headers to invoke `_get_random_headers()` directly ensures total uniformity across all HTTP requests.

---

## 2. Requirement R2 Survey: Spider 2026 Prioritization (`heuristic_spider.py`)

### 2.1 Overview & Architecture
`AsyncTwoPassSpider` is an asynchronous two-pass municipal web crawler:
- **Pass 1 (`pass_1_map_and_score`, lines 302-475)**: High-concurrency best-first traversal (priority queue `heapq`) mapping up to `SPIDER_MAX_MAPPING_PAGES` (1000 pages). Evaluates page relevance with `_score_page`.
- **Pass 2 (`pass_2_heavy_extraction`, lines 479-535)**: Deep extraction (text, PDFs, OCR image carteles) on the top `SPIDER_MAX_EXTRACTION_PAGES` (70 pages).

### 2.2 Scoring Matrix & Temporal Logic (`_score_page`, `heuristic_spider.py:138-210`)

The page scoring function `_score_page(url, title, page_text, locality_names, target_year=2026)` computes a numeric score based on the following breakdown:

| Criterion | Logic / Condition | Score Impact | Exact Line(s) |
|---|---|---|---|
| **Locality Name Match** | Any locality name present in lowercased text/url/title | `+500` | `heuristic_spider.py:145-148` |
| **Strong Festival Keywords** | Match in castellano or co-official languages ("programa de fiestas", "fiestas patronales", "festa major", "jaiak", "foliada", etc.) | `+100` per match | `heuristic_spider.py:150-171` |
| **Weak Festival Keywords** | Match ("fiesta", "festejo", "cultura", "evento", "romeria", "correfoc", "kalejira", etc.) | `+20` per match | `heuristic_spider.py:161-175` |
| **Prior Year Penalization (R2)** | Any year `y < target_year` (e.g. 2025, 2024) matched in URL | `-300` | `heuristic_spider.py:179-181` |
| **Target Year + Festival Bonus (R2)** | Target year (2026) in URL AND festival keyword present | `+350` | `heuristic_spider.py:183-187` |
| **Target Year Only Bonus (R2)** | Target year (2026) in URL WITHOUT festival keyword | `+150` | `heuristic_spider.py:183-189` |
| **Single Unrelated Event Filter (R2)** | Unrelated event keywords ("taller", "charla", "conferencia", "pleno", "exposicion", "corte de agua") AND NO festival keywords | `-350` | `heuristic_spider.py:191-198` |
| **Institutional Penalty** | Keywords ("pleno", "presupuesto", "transparencia", "urbanismo", "contratacion", "boe", "bop", etc.) | `-100` per match | `heuristic_spider.py:200-208` |

### 2.3 Calendar URL Deduplication (`heuristic_spider.py:55, 78-83, 364-369, 455-457`)
- **Pattern Matching**: `RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")` matches date paths like `/2026/05/12/`.
- **Deduplication Key**: `_get_calendar_date_key(url)` returns `"{domain}:{date_path}"` (e.g., `"ayuntamiento.es:/2026/05/12"`).
- **Two-Tier Filter**:
  1. **Traversal Filter (lines 364-369)**: Before crawling a URL in `pass_1_map_and_score`, if its `cal_key` is already in `self.seen_calendar_dates`, it is skipped (`continue`).
  2. **Preventive Queue Filter (lines 455-457)**: When extracting new `<a href="...">` links from HTML, if `cal_key` is already in `self.seen_calendar_dates`, the link is not enqueued into `queue`.

### 2.4 Early Stop & Efficiency Mechanisms
- **Early Stop Trigger (`heuristic_spider.py:407-411`)**: If a page score exceeds 800 (indicating a highly relevant target year festival program page), `self.max_mapping_pages` is immediately truncated to `paginas_este_crawl + concurrency * 3`. This prevents long runs crawling thousands of irrelevant municipal subpages once the target festival page has been identified.
- **Sitemap Pre-injection (`heuristic_spider.py:335-348`)**: Automatically fetches `/sitemap.xml` to seed high-priority festival URLs before crawling.

### 2.5 Risks, Edge Cases & Recommendations (R2)
1. **Year in URL False Positives**:
   - If a URL contains a historical year reference (e.g., `/historia-fiestas-2024/edicion-2026`), the presence of `2024` in `years_in_url` triggers $-300$. However, the target year bonus ($+350$) plus keyword bonuses ($+100$ or $+500$) ensure the score remains strongly positive ($>+350$), preventing false rejection.
2. **Additional Unrelated Event Keywords**:
   - Current filter list: `["taller", "charla", "conferencia", "pleno", "exposicion", "expocision", "corte de agua"]`.
   - Optional extension: `"corte de trafico"`, `"mercadillo"`, `"atencion al ciudadano"` can be added if municipal sites present clutter.

---

## 3. Cross-Requirement Dependencies

- **R1 <-> R6 (Metrics Integration)**: `google_search.py` tracks search failures (`registrar_busqueda_fallida`), which are queried by `get_failed_searches_count()` during the final summary generation in `main.py` (R6).
- **R2 <-> Document Extractor (R5)**: `heuristic_spider.py` relies on `is_promising_pdf` and `is_promising_image` from `document_extractor.py` during Pass 2 heavy extraction.

---

## 4. Summary of Verification Status

| Requirement | Test File | Test Cases | Result |
|---|---|---|---|
| **R1** | `tests_fase2/verify_r1_search.py` | UA rotation, Delay range [2.0, 4.5]s, Exponential backoff with jitter formula, Engine sampling without replacement, No Google CSE API | **PASSED** |
| **R2** | `tests_fase2/verify_r2_spider.py` | Target year 2026 bonus (+150/+350), Prior year penalty (-300), Single event penalty (-350), Calendar URL date key deduplication | **PASSED** |

---

## 5. File Location Reference
- **Analysis Report**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_survey_1\analysis.md`
- **Handoff Report**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_survey_1\handoff.md`

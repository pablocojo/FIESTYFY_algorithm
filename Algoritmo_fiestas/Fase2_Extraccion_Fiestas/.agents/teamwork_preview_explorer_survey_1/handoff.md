# Handoff Report — Codebase Survey for Requirements R1 & R2

## 1. Observation

### 1.1 Files Inspected & Code Quotations
1. **`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\config.py`**:
   - Lines 39-41:
     ```python
     DDG_DELAY_MIN = 2.0                   # Delay mínimo entre queries (segundos)
     DDG_DELAY_MAX = 4.5                   # Delay máximo entre queries (segundos)
     ```
   - Lines 56-61:
     ```python
     DDG_MAX_RESULTS = 7
     DDG_MAX_URLS_TO_FOLLOW = 5
     DDG_CONTENT_MAX_CHARS = 15000         # Límite de texto por página
     DDG_REQUEST_TIMEOUT = 10
     DDG_MAX_RETRIES = 3
     DDG_RETRY_BACKOFF = 3.0
     ```

2. **`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\google_search.py`**:
   - Lines 116-126 (User-Agent Rotation):
     ```python
     USER_AGENTS = [
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
         "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36"
     ]

     def get_random_user_agent() -> str:
         return random.choice(USER_AGENTS)
     ```
   - Lines 135-144 (Query Delay & Exponential Backoff with Jitter):
     ```python
     def get_query_delay() -> float:
         return random.uniform(DDG_DELAY_MIN, DDG_DELAY_MAX)

     def calculate_backoff_delay(attempt: int, base_backoff: float = DDG_RETRY_BACKOFF) -> float:
         return (base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)
     ```
   - Lines 238-263 (Multi-Engine Engine Sampling Without Replacement):
     ```python
     async def _fetch_search_results(session: aiohttp.ClientSession, query: str) -> list[dict]:
         engines = [("DuckDuckGo", _sync_fetch_ddg), ("Yahoo", _sync_fetch_yahoo), ("Bing", _sync_fetch_bing)]
         available_engines = engines.copy()
         random.shuffle(available_engines)
         
         for attempt in range(DDG_MAX_RETRIES):
             if not available_engines:
                 available_engines = engines.copy()
                 random.shuffle(available_engines)
                 
             engine_name, engine_func = available_engines.pop(0)
             results = await asyncio.to_thread(engine_func, query)
             if results:
                 return results
             registrar_busqueda_fallida()
             if attempt < DDG_MAX_RETRIES - 1:
                 backoff_delay = calculate_backoff_delay(attempt)
                 await asyncio.sleep(backoff_delay)
         return []
     ```

3. **`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\heuristic_spider.py`**:
   - Lines 55, 78-83 (Calendar URL Deduplication Key):
     ```python
     RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")

     @classmethod
     def _get_calendar_date_key(cls, url: str) -> str | None:
         match = cls.RE_CALENDAR_DATE_URL.search(url)
         if match:
             parsed = urllib.parse.urlparse(url)
             return f"{parsed.netloc.lower()}:{match.group(0).rstrip('/')}"
         return None
     ```
   - Lines 177-198 (Temporal Scoring Matrix & Single Event Filter):
     ```python
     # 3.1 Penalización por años anteriores en URL (-300 pts)
     years_in_url = [int(y) for y in re.findall(r"(?:19|20)\d{2}", url_lower)]
     if any(y < target_year for y in years_in_url):
         score -= 300

     # 3.2 Bonus por año objetivo (2026) (+150 base, +350 con palabras festivas)
     if target_year_str in url_lower:
         if has_festival_kw:
             score += 350
         else:
             score += 150

     # 4. Filtrado de eventos municipales individuales (-350 pts)
     unrelated_single_events = [
         "taller", "charla", "conferencia", "pleno", "exposicion", "expocision", "corte de agua"
     ]
     has_unrelated = any(ue in text_lower for ue in unrelated_single_events)
     if has_unrelated and not has_festival_kw:
         score -= 350
     ```

### 1.2 Test Command Executed & Results
- **Command**: `python -m pytest tests_fase2/verify_r1_search.py tests_fase2/verify_r2_spider.py -v`
- **Output**:
  ```text
  tests_fase2/verify_r1_search.py::test_r1_user_agent_rotation PASSED      [ 11%]
  tests_fase2/verify_r1_search.py::test_r1_random_query_delay_range PASSED [ 22%]
  tests_fase2/verify_r1_search.py::test_r1_exponential_backoff_with_jitter PASSED [ 33%]
  tests_fase2/verify_r1_search.py::test_r1_no_google_custom_search_api PASSED [ 44%]
  tests_fase2/verify_r1_search.py::test_r1_fetch_search_results_backoff_integration PASSED [ 55%]
  tests_fase2/verify_r1_search.py::test_r1_engine_rotation_without_replacement PASSED [ 66%]
  tests_fase2/verify_r2_spider.py::test_score_page_target_year_scoring PASSED [ 77%]
  tests_fase2/verify_r2_spider.py::test_score_page_single_unrelated_event_filter PASSED [ 88%]
  tests_fase2/verify_r2_spider.py::test_calendar_url_deduplication PASSED  [100%]

  ============================== 9 passed in 8.38s ==============================
  ```

---

## 2. Logic Chain

1. **Step 1 (Requirement R1 Web Search Resilience)**:
   - *Observation*: `google_search.py` imports `DDG_DELAY_MIN` ($2.0$) and `DDG_DELAY_MAX` ($4.5$) from `config.py` and calculates dynamic query delays via `get_query_delay()`.
   - *Observation*: `get_random_user_agent()` samples from a 5-browser realistic User-Agent pool. `_fetch_search_results` shuffles search engines (`DuckDuckGo`, `Yahoo`, `Bing`) without replacement per request attempt and calculates backoff via `(base * 2^attempt) + jitter`. No Google CSE API endpoints or keys exist.
   - *Deduction*: Requirement R1 is fully satisfied and operational.

2. **Step 2 (Requirement R2 Spider Prioritization)**:
   - *Observation*: `heuristic_spider.py` `_score_page` penalizes prior years (`y < target_year`) with $-300$, awards $+350$ for target year ($2026$) when accompanied by festival keywords (or $+150$ base), and penalizes non-festival single events (`taller`, `charla`, `conferencia`, etc.) with $-350$.
   - *Observation*: `_get_calendar_date_key` matches calendar URL patterns `/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d` and deduplicates them using `self.seen_calendar_dates` both before fetching and during link discovery.
   - *Deduction*: Requirement R2 is fully satisfied and operational.

3. **Step 3 (Test Verification)**:
   - *Observation*: Running `pytest` on `tests_fase2/verify_r1_search.py` and `tests_fase2/verify_r2_spider.py` returned 9 passed out of 9 tests.
   - *Deduction*: Logic has been independently validated and verified.

---

## 3. Caveats

- **No Caveats**: The codebase survey and isolated unit verification for Requirements R1 and R2 were completed without blocking issues or ambiguities.

---

## 4. Conclusion

- **R1 Status**: Fully compliant. `google_search.py` and `config.py` implement UA rotation, random delays $[2.0, 4.5]$s, exponential backoff with jitter, multi-engine failover (DuckDuckGo, Yahoo, Bing), failure metric tracking, and zero Google CSE API dependency.
- **R2 Status**: Fully compliant. `heuristic_spider.py` implements target year 2026 prioritization ($+150/+350$), prior year penalties ($-300$), single unrelated event penalties ($-350$), early stopping ($>800$ score), and regex date-key calendar URL deduplication (`/YYYY/M/D/`).

---

## 5. Verification Method

To independently verify this report:

1. **Run Pytest Verification**:
   ```powershell
   python -m pytest tests_fase2/verify_r1_search.py tests_fase2/verify_r2_spider.py -v
   ```
   *Expected Result*: 9 passed in ~8-10 seconds.

2. **Inspect Files**:
   - Analysis file: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_survey_1\analysis.md`
   - Target files: `config.py`, `scraper/google_search.py`, `scraper/heuristic_spider.py`.

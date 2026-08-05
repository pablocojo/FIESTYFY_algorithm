# Handoff Report — M2 (Spider 2026 Prioritization - R2)

**Verdict**: APPROVE

## 1. Observation
- **Inspected Files**:
  - `scraper/heuristic_spider.py` (lines 52–210, 302–476): Async Two-Pass Spider implementation.
  - `tests_fase2/verify_r2_spider.py` (lines 17–137): Verification script for R2 requirements.
  - `tests_fase2/test_r2_stress_edgecases.py`: Created stress harness testing calendar URL keys, co-official languages, scoring matrix, and year penalties.
- **Key Mechanics Tested**:
  1. `_get_calendar_date_key`: Uses `RE_CALENDAR_DATE_URL` (`/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)`) and domain (`parsed.netloc.lower()`) to deduplicate `/YYYY/MM/DD/` calendar paths.
  2. `_score_page`: 
     - Year bonus/penalty: Past years (`< 2026`) incur `-300` penalty; target year `2026` in URL awards `+350` bonus if festival keywords are present (or `+150` if absent).
     - Unrelated event filtering: Non-festival single events (`taller`, `charla`, `conferencia`, `pleno`, `exposicion`, `corte de agua`) incur `-350` penalty unless festival keywords override it.
     - Locality matching: `+500` bonus for explicit municipality match.
     - Co-official language support: Castellano, Català/Valencià, Euskera, Galego, Aranese festival keywords supported.
  3. `pass_1_map_and_score`: Preventative deduplication via `seen_calendar_dates` during queue popping and link extraction. Best-first search with priority queue and early stopping (`score > 800`).

## 2. Logic Chain
- **Step 1**: Analyzed `AsyncTwoPassSpider._get_calendar_date_key`. Standard calendar URL paths (`/2026/05/12`, `/2026/5/3/`) correctly generate unique keys per domain (`ayuntamiento.es:/2026/05/12`), preventing crawl loop bloat on daily calendar pages.
- **Step 2**: Evaluated scoring differential in `_score_page`. A 2026 festival URL scores `+650` points higher than an identical 2025 URL (`+350` vs `-300`). This guarantees the spider prioritizes current 2026 festival content in best-first queue ordering.
- **Step 3**: Verified unrelated event filter logic. A single event URL/page with "taller" or "charla" without festival keywords receives `-350` penalty, while a workshop specifically for festival preparation ("taller de banderines para la fiesta patronal") avoids the penalty due to `has_festival_kw = True`.
- **Step 4**: Verified early stop mechanism (>800 pts), co-official language keywords (e.g. `jaiak`, `festes`, `foliada`), and institutional penalties (`-100` for plenos/presupuestos/contratacion).

## 3. Caveats
- URLs with dates in query parameters (e.g. `?date=2026-05-12`) are not matched by `RE_CALENDAR_DATE_URL`. This is acceptable as municipal sites overwhelmingly use path-based routing for calendar archives (`/agenda/YYYY/MM/DD/`).

## 4. Conclusion
The implementation of Requirement R2 in `scraper/heuristic_spider.py` is solid, correct, and robust against stress cases. The prioritization matrix strictly favors 2026 festival pages, deduplicates daily calendar URLs, filters out non-festive municipal noise, and supports co-official regional languages.

**Verdict**: APPROVE

## 5. Verification Method
- Code inspect of `scraper/heuristic_spider.py`.
- Execution of test files:
  - `python tests_fase2/verify_r2_spider.py`
  - `pytest tests_fase2/test_r2_stress_edgecases.py`

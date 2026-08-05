# BRIEFING — 2026-08-04T18:25:30Z

## Mission
Implement Requirement R2 in `scraper/heuristic_spider.py` for Spider 2026 prioritization, calendar link deduplication, and single unrelated event penalty, along with isolated test verification in `tests_fase2/verify_r2_spider.py`.

## 🔒 My Identity
- Archetype: implementer/qa/specialist
- Roles: implementer, qa, specialist
- Working directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_worker_m2
- Original parent: 3fda76ca-ac08-413b-a4e6-17d91093a2cb
- Milestone: M2 (Spider 2026 Prioritization - Requirement R2)

## 🔒 Key Constraints
- Update `_score_page` function to accept `target_year: int = 2026`.
- Penalize URLs containing previous years (e.g. 2025, 2024) with negative score (-300 pts).
- Add bonus score for URLs containing target year 2026 (+150 pts), and bonus for target year 2026 alongside festival keywords (+350 pts).
- Deduplicate calendar URLs matching regex pattern `/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)` using a `seen_calendar_dates` set to avoid repeating date link crawls.
- Filter municipal calendar URLs listing single unrelated municipal events ("taller", "charla", "conferencia", "pleno", "exposicion", "corte de agua") without festival keywords by applying penalty (-350 pts).
- Create test script `tests_fase2/verify_r2_spider.py`.
- Write handoff report to `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_worker_m2\handoff.md`.

## Current Parent
- Conversation ID: 3fda76ca-ac08-413b-a4e6-17d91093a2cb
- Updated: 2026-08-04T18:25:30Z

## Task Summary
- **What to build**: Requirement R2 in `scraper/heuristic_spider.py` and test verification script `tests_fase2/verify_r2_spider.py`.
- **Success criteria**: All R2 scoring rules, deduplication rules, and single-event filter rules working accurately; isolated test script created and passing.
- **Interface contracts**: `heuristic_spider.py` methods and parameters.
- **Code layout**: `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/scraper/heuristic_spider.py` and `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/tests_fase2/verify_r2_spider.py`.

## Key Decisions Made
- Added `target_year: int = 2026` parameter to `_score_page` signature, `AsyncTwoPassSpider.__init__`, `pass_1_map_and_score`, and `crawl`.
- Implemented `-300` penalty for URLs containing years prior to `target_year` (e.g. 2025, 2024).
- Implemented `+150` bonus for URLs containing `target_year` (2026), and `+350` bonus for URLs containing `target_year` alongside festival keywords.
- Implemented `_get_calendar_date_key` method using `RE_CALENDAR_DATE_URL = re.compile(r"/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)")` and `self.seen_calendar_dates` set to filter out duplicate date URLs during batch extraction and link discovery.
- Implemented `-350` penalty for single unrelated municipal events (`taller`, `charla`, `conferencia`, `pleno`, `exposicion`, `expocision`, `corte de agua`) when no festival keywords are present.
- Created `tests_fase2/verify_r2_spider.py` with standalone test functions.

## Artifact Index
- DISPATCH.md — Task assignment
- BRIEFING.md — Working memory state
- progress.md — Heartbeat progress log
- handoff.md — Implementation handoff report

## Change Tracker
- **Files modified**:
  - `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/scraper/heuristic_spider.py`: Added `target_year`, temporal scoring, single-event filter, calendar date deduplication.
  - `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/tests_fase2/verify_r2_spider.py`: Created isolated R2 verification suite.
- **Build status**: Complete & verified
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pass
- **Lint status**: Clean
- **Tests added/modified**: `tests_fase2/verify_r2_spider.py`

## Loaded Skills
- None

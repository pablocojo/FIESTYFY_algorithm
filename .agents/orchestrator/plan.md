# Project Plan: Fiestyfy Algorithm 2026 Improvements

## Overview
Decompose, implement, and verify requirements R1 through R6 and isolated test scripts for the Fase 2 festival extraction pipeline.

## Milestones

### Phase 0: Survey & Codebase Assessment
- **Status**: IN_PROGRESS
- **Agents**: 3 parallel Explorers (surveying R1-R6)
- **Output**: Survey reports to synthesize into `PROJECT.md`

### Phase 1: Implementation Milestones
- **M1: Resilient Web Search (R1)**
  - File: `google_search.py` (and `config.py`)
  - Target: User-Agent rotation per query, random delay (2.0-4.5s), exponential backoff with jitter for DDG/Yahoo/Bing. No Google Custom Search API.
- **M2: Spider 2026 Prioritization (R2)**
  - File: `heuristic_spider.py`
  - Target: `_score_page` prioritizing target year 2026, penalizing previous years, bonus for 2026 + festival keywords, deduplicating calendar URLs (`/YYYY/M/D/`), filtering single-event municipal calendar URLs.
- **M3: Cross-Year & Leap Year Edge Cases (R3)**
  - Files: `text_analyzer.py`, `patron_finder.py`
  - Target: `_validar_fecha` allows `fecha_fin` in `anno+1` if `fecha_inicio` in Dec of target year; `fecha_del_patron` falls back to Feb 28 if Feb 29 and target year is not leap year.
- **M4: Social Media Date Filtering (R4)**
  - File: `social_content.py`
  - Target: Save `fecha_publicacion`, filter posts within acceptable window for target year 2026.
- **M5: PDF Priority & Async Caches (R5)**
  - Files: `document_extractor.py`, `social_finder.py`, `patron_finder.py`
  - Target: `is_promising_pdf` explicitly verifies target/previous year; `RedesCache.set` and `_PatronCache.set` use `asyncio.to_thread` for JSON file writing.
- **M6: Execution Metrics Logging (R6)**
  - File: `main.py`
  - Target: `async_main` final summary report logging extracted vs estimated ratio, 0-festival localities, top sources, blocked/failed searches, avg time per municipality.

### Phase 2: Isolated Test Scripts & Acceptance Criteria Verification
- **M7: Test Suite & Verification**
  - Verification scripts for:
    1. `fecha_del_patron` Feb 28 fallback for Feb 29 saint in 2026.
    2. `_validar_fecha` accepting festival from Dec 30 2026 to Jan 2 2027.
    3. User-Agent rotation and random delay execution without errors.
  - Reviewer, Challenger, and Forensic Auditor verification.

## Execution Procedure per Milestone
1. Worker implements changes in target codebase.
2. Reviewer(s) verify code quality, logic completeness, and requirements compliance.
3. Challenger(s) run test scripts / empirical checks.
4. Forensic Auditor (`teamwork_preview_auditor`) verifies code integrity (no hardcoding/cheating).
5. Gate Evaluation (ALL must pass).

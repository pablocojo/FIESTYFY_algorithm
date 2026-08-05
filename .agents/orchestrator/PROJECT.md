# PROJECT: Fiestyfy Algorithm 2026 Improvements

## Architecture & Scope Summary
Improvements to the Fase 2 festival extraction pipeline for 2026 season:
1. Resilient search engine fallback & query throttling (`google_search.py`, `config.py`)
2. Target year 2026 & keyword scoring in web spider (`heuristic_spider.py`)
3. Cross-year & leap year date validation (`text_analyzer.py`, `patron_finder.py`)
4. Publication date tracking & window filtering in social scraper (`social_content.py`)
5. PDF year filtering (`document_extractor.py`) & non-blocking cache writes (`social_finder.py`, `patron_finder.py`)
6. Execution metrics logging & final summary reporting (`main.py`)
7. Independent test scripts for acceptance verification (`tests_fase2/`)

## Feature Inventory
| # | Requirement | Target File(s) | Description | Milestone | Source |
|---|-------------|----------------|-------------|-----------|--------|
| 1 | R1 Resilient Search | `google_search.py`, `config.py` | UA rotation, random delays (2.0-4.5s), exp backoff + jitter for DDG/Yahoo/Bing | M1 | ORIGINAL_REQUEST |
| 2 | R2 Spider Prioritization | `heuristic_spider.py` | 2026 bonus, previous year penalty, calendar URL deduplication, single-event filtering | M2 | ORIGINAL_REQUEST |
| 3 | R3 Edge Case Dates | `text_analyzer.py`, `patron_finder.py` | Cross-year (Dec 2026 -> Jan 2027) valid date; Feb 29 saint fallback to Feb 28 in non-leap year | M3 | ORIGINAL_REQUEST |
| 4 | R4 Social Date Filter | `social_content.py` | Save `fecha_publicacion`, filter posts within 2026 target window | M4 | ORIGINAL_REQUEST |
| 5 | R5 PDF & Async Caches | `document_extractor.py`, `social_finder.py`, `patron_finder.py` | `is_promising_pdf` target/prev year check; `asyncio.to_thread` for cache file IO | M5 | ORIGINAL_REQUEST |
| 6 | R6 Execution Metrics | `main.py` | Final summary report: extracted/estimated ratio, 0-festival count, top sources, search errors, avg time | M6 | ORIGINAL_REQUEST |
| 7 | Acceptance Verification | `tests_fase2/` | Standalone verification scripts for R1 (UA/delay), R3 (cross-year & Feb 28 patron), full test suite pass | M7 | ORIGINAL_REQUEST |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Resilient Web Search | R1 implementation in `google_search.py` & `config.py` | None | PLANNED |
| M2 | Spider 2026 Prioritization | R2 implementation in `heuristic_spider.py` | None | PLANNED |
| M3 | Cross-Year & Leap Year Dates | R3 implementation in `text_analyzer.py` & `patron_finder.py` | None | PLANNED |
| M4 | Social Media Date Filtering | R4 implementation in `social_content.py` | None | PLANNED |
| M5 | PDF Priority & Async Caches | R5 implementation in `document_extractor.py`, `social_finder.py`, `patron_finder.py` | M3 | PLANNED |
| M6 | Execution Metrics | R6 implementation in `main.py` | None | PLANNED |
| M7 | Test Suite & Gate Verification | Verification scripts + full unit test pass + Auditor check | M1-M6 | PLANNED |

## Code Layout
- Target project path: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`
  - `config.py`
  - `main.py`
  - `scraper/google_search.py`
  - `scraper/heuristic_spider.py`
  - `scraper/social_content.py`
  - `scraper/social_finder.py`
  - `scraper/document_extractor.py`
  - `llm_processor/text_analyzer.py`
  - `llm_processor/patron_finder.py`
  - `tests_fase2/`

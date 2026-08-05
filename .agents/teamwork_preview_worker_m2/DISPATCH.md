## 2026-08-04T16:19:49Z
You are Worker 2 for Milestone M2 (Spider 2026 Prioritization - Requirement R2).
Your working directory is: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_worker_m2
Target project directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas

Read ORIGINAL_REQUEST.md at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\ORIGINAL_REQUEST.md
Read user rules at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md
Read Explorer survey report at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_explorer_survey_1\handoff.md

Your Task:
Implement Requirement R2 in `scraper/heuristic_spider.py`:
1. Update `_score_page` function to accept `target_year: int = 2026`.
2. Penalize URLs containing previous years (e.g. 2025, 2024) with negative score (-300 pts).
3. Add bonus score for URLs containing the target year 2026 (+150 pts), and bonus for target year 2026 alongside festival keywords (+350 pts).
4. Deduplicate calendar URLs matching regex pattern `/(?:19|20)\d{2}/[0-1]?\d/[0-3]?\d(?:/|$)` using a `seen_calendar_dates` set to avoid repeating date link crawls.
5. Filter municipal calendar URLs that list single unrelated municipal events ("taller", "charla", "conferencia", "pleno", "exposicion", "corte de agua") without festival keywords by applying penalty (-350 pts).
6. Create an isolated verification test script at `tests_fase2/verify_r2_spider.py` testing page scoring, calendar deduplication, and single-event filtering.
7. Run python / pytest to verify that your implementation and test script run without errors.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write your implementation report to `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_worker_m2\handoff.md`.
Message your parent (conversation ID: 3fda76ca-ac08-413b-a4e6-17d91093a2cb) when done with build/test results.

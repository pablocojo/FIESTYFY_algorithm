## 2026-08-05T10:51:01Z
You are Explorer 1 (teamwork_preview_explorer).
Your working directory is `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_survey_1`. Create your directory first.

Read the following files carefully:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md`

Your focus area: Surveying codebase for Requirements R1 and R2.
Target code files in workspace:
- `google_search.py`
- `config.py`
- `heuristic_spider.py`

Tasks:
1. Examine `google_search.py` and `config.py`: Check current search engines, User-Agent usage, delay handling, and retry/backoff mechanisms. Detail what changes are needed to support User-Agent rotation per query, random delays (2.0 to 4.5s), and exponential backoff with jitter for DuckDuckGo, Yahoo, Bing without using Google Custom Search API.
2. Examine `heuristic_spider.py`: Check `_score_page` and URL handling. Detail what changes are needed to prioritize target year 2026, penalize previous years (e.g. 2025, 2024), add bonus scores for target year + festival keywords, deduplicate calendar URLs (`/YYYY/M/D/`), and filter out municipal calendar URLs listing single unrelated events.
3. Write your analysis and findings to `analysis.md` and `handoff.md` in your working directory. Include exact line numbers, current logic, proposed changes, risks, and dependencies.
4. When finished, send a message to parent with your handoff summary and file path.

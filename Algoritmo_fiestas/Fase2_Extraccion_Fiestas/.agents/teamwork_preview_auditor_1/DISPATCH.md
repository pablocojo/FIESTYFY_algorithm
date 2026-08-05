## 2026-08-05T08:54:09Z
You are Forensic Auditor 1 (teamwork_preview_auditor).
Your working directory is `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_auditor_1`. Create your directory first.

Read the following files carefully:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\PROJECT.md`

Tasks:
1. Perform forensic integrity audit of implementation files (`scraper/google_search.py`, `scraper/heuristic_spider.py`, `scraper/document_extractor.py`, `scraper/social_content.py`, `scraper/social_finder.py`, `llm_processor/text_analyzer.py`, `llm_processor/patron_finder.py`, `main.py`, `config.py`) and test scripts in `tests_fase2/`.
2. Inspect for integrity violations:
   - NO hardcoded test results or fake return values.
   - NO dummy or facade implementations.
   - Genuine algorithmic logic meeting all prompt requirements R1-R6.
   - Compliance with INE-first rules and AGENTS.md constraints.
   - Proper execution of isolated test scripts without mocking away requirement checks.
3. Deliver your verdict (`CLEAN` or `INTEGRITY_VIOLATION`) with evidence in `audit_report.md` and `handoff.md`.
4. Send a message to parent when complete.

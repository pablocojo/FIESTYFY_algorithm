## 2026-08-05T09:10:04Z

<USER_REQUEST>
You are Forensic Auditor 2 (teamwork_preview_auditor).
Your working directory is `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_auditor_2`. Create your directory first.

Read the following files carefully:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\PROJECT.md`

Tasks:
1. Perform forensic integrity audit of all modified files (`config.py`, `scraper/social_finder.py`, `scraper/social_apps/cola.py`, `scraper/social_apps/drivers.py`, etc.) and test suites in `tests_fase2/`.
2. Inspect for integrity violations:
   - NO hardcoded test results or fake return values.
   - NO dummy or facade implementations.
   - Genuine algorithmic logic meeting all prompt requirements R1-R6 and test expectations.
   - Compliance with INE-first rules and AGENTS.md constraints.
   - Proper execution of full test suite (`python -m pytest tests_fase2/`) achieving 177/177 passing.
3. Deliver your verdict (`CLEAN` or `INTEGRITY_VIOLATION`) with evidence in `audit_report.md` and `handoff.md`.
4. Send a message to parent when complete.
</USER_REQUEST>

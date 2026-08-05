## 2026-08-05T11:04:34Z
You are Worker 2 (teamwork_preview_worker).
Your working directory is `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_worker_remediation`. Create your directory first.

Read the following files carefully:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_remediation\handoff.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_remediation\analysis.md`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Assigned Tasks:
1. `config.py`: Set `RAG_PROGRAMA_MAX_CHARS = 8000` (restoring chunk limit from 80000 to 8000).
2. `scraper/social_finder.py`: Add `"pendiente_apps": any(not perfiles.get(red) for red in REDES)` to `entrada` dictionary returned in `registrar_perfiles_web`.
3. `scraper/social_apps/cola.py`: Implement `"buscar"` task generation and sorting in `construir_cola` so that locations with `pendiente_apps: True` build `buscar` tasks for unpopulated social networks (excluding networks in `apps_sin_resultado`), and `leer` tasks are ordered before `buscar` tasks.
4. `scraper/social_apps/drivers.py`: Add `_perfil_abierto(self, handle, title)` and `_verificar_perfil_con_handle(self, handle, title)` to `DriverBase` to enable profile detection and candidate title/handle verification.
5. Run the full pytest suite:
   `python -m pytest tests_fase2/ -v`
   Verify 100% pass rate (177/177 passing).
6. Also run isolated R1-R6 tests:
   `python -m pytest tests_fase2/verify_r1_search.py tests_fase2/verify_r2_spider.py tests_fase2/verify_r3_crossyear.py tests_fase2/verify_r3_patron.py tests_fase2/verify_r4_social.py tests_fase2/verify_r5_pdf_cache.py tests_fase2/verify_r6_metrics.py tests_fase2/test_adversarial_r1_r6.py`
   Verify 100% pass rate (35/35 passing).
7. Document all changes in `changes.md` and handoff report in `handoff.md` in your working directory.
8. Send a message to parent when complete.

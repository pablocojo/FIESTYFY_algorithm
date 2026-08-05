## 2026-08-05T09:00:55Z
You are Explorer 4 (teamwork_preview_explorer).
Your working directory is `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\teamwork_preview_explorer_remediation`. Create your directory first.

Read the following files carefully:
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\orchestrator\DISPATCH.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\victory_auditor\victory_audit_report.md` (if available)

Tasks:
1. Run `pytest tests_fase2/` to inspect all failing tests and capture exact tracebacks.
2. Investigate the 11 specific failing test cases:
   - `tests_fase2/test_fuentes_chunking.py::test_unidad_gigante_se_trocea_con_limite_duro` (`config.py` vs expected `RAG_PROGRAMA_MAX_CHARS`)
   - `tests_fase2/test_social_finder.py::test_registrar_y_cache`, `test_registrar_sin_perfiles_marca_pendiente`, `test_registrar_completo_no_pendiente` (`KeyError: 'pendiente_apps'` in `RedesCache` / `social_finder.py`)
   - `tests_fase2/test_social_apps.py::test_cola_leer_y_buscar`, `test_cola_no_repite_busquedas_sin_resultado` (AssertionError)
   - `tests_fase2/test_social_apps.py` & `tests_fase2/test_verificacion_por_nombre_de_pagina`: `test_perfil_abierto_facebook_por_nombre`, `test_resultados_de_busqueda_no_es_perfil`, `test_perfil_abierto_instagram_por_handle`, `test_otro_titulo_no_es_perfil`, `test_verificacion_por_nombre_de_pagina` (AttributeError in `scraper/social_apps.py`)
3. Determine the root causes and precise code fixes required in `config.py`, `scraper/social_finder.py`, `scraper/social_apps.py`, or tests so that ALL 177 tests in `tests_fase2/` pass 100% WITHOUT breaking any of the R1-R6 requirements.
4. Write your findings to `analysis.md` and `handoff.md` in your working directory.
5. Send a message to parent when complete.

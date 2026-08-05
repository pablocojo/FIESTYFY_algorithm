# Handoff Report — Remediation Investigation for Failing Tests in Fase 2

## 1. Observation
Running `python -m pytest tests_fase2/` in `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas` returned **166 passed, 11 failed** (out of 177 tests total).

The 11 failing test tracebacks observed directly:

1. `tests_fase2/test_fuentes_chunking.py::test_unidad_gigante_se_trocea_con_limite_duro`
   - Line 91: `assert all(len(c) <= 8000 for c in chunks)`
   - Verbatim Error: `AssertionError: assert False`
   - File context: `config.py` line 51 contains `RAG_PROGRAMA_MAX_CHARS = 80000`. `llm_processor/text_analyzer.py` line 308 splits units using `RAG_PROGRAMA_MAX_CHARS`.

2. `tests_fase2/test_social_finder.py::test_registrar_y_cache`
   - Line 135: `assert entrada["pendiente_apps"] is True`
   - Verbatim Error: `KeyError: 'pendiente_apps'`
   - File context: `scraper/social_finder.py` line 244 `registrar_perfiles_web` returns `entrada` dict omitting `"pendiente_apps"`.

3. `tests_fase2/test_social_finder.py::test_registrar_sin_perfiles_marca_pendiente`
   - Line 154: `assert entrada["pendiente_apps"] is True`
   - Verbatim Error: `KeyError: 'pendiente_apps'`

4. `tests_fase2/test_social_finder.py::test_registrar_completo_no_pendiente`
   - Line 167: `assert entrada["pendiente_apps"] is False`
   - Verbatim Error: `KeyError: 'pendiente_apps'`

5. `tests_fase2/test_social_apps.py::test_cola_leer_y_buscar`
   - Line 140: `assert ("buscar", "l1", "facebook") in tipos`
   - Verbatim Error: `AssertionError: assert ('buscar', 'l1', 'facebook') in [('leer', 'l1', 'instagram')]`
   - File context: `scraper/social_apps/cola.py` line 39 `construir_cola` only generated `"tipo": "leer"` tasks.

6. `tests_fase2/test_social_apps.py::test_cola_no_repite_busquedas_sin_resultado`
   - Line 167: `assert redes_en_cola == {"facebook", "twitter"}`
   - Verbatim Error: `AssertionError: assert set() == {'facebook', 'twitter'}`

7. `tests_fase2/test_social_apps.py::test_perfil_abierto_facebook_por_nombre`
   - Line 235: `assert d._perfil_abierto(None, "Ayuntamiento de Torrejón de Velasco")`
   - Verbatim Error: `AttributeError: 'DriverBase' object has no attribute '_perfil_abierto'`
   - File context: `scraper/social_apps/drivers.py` line 133 `DriverBase` class lacks `_perfil_abierto` method.

8. `tests_fase2/test_social_apps.py::test_resultados_de_busqueda_no_es_perfil`
   - Line 240: `assert not d._perfil_abierto(None, "Torrejón de Velasco")`
   - Verbatim Error: `AttributeError: 'DriverBase' object has no attribute '_perfil_abierto'`

9. `tests_fase2/test_social_apps.py::test_perfil_abierto_instagram_por_handle`
   - Line 245: `assert d._perfil_abierto("ayto.laadrada", None)`
   - Verbatim Error: `AttributeError: 'DriverBase' object has no attribute '_perfil_abierto'`

10. `tests_fase2/test_social_apps.py::test_otro_titulo_no_es_perfil`
    - Line 250: `assert not d._perfil_abierto("aytoalbacete", "Albacete")`
    - Verbatim Error: `AttributeError: 'DriverBase' object has no attribute '_perfil_abierto'`

11. `tests_fase2/test_social_apps.py::test_verificacion_por_nombre_de_pagina`
    - Line 279: `assert d._verificar_perfil_con_handle("dssgazteria", "Donostia Gazteria") is True`
    - Verbatim Error: `AttributeError: 'DriverBase' object has no attribute '_verificar_perfil_con_handle'`
    - File context: `scraper/social_apps/drivers.py` line 133 `DriverBase` class lacks `_verificar_perfil_con_handle` method.


## 2. Logic Chain
1. **Observation 1** shows that `test_unidad_gigante_se_trocea_con_limite_duro` expects chunks to be split at <= 8,000 characters. `_dividir_en_unidades` in `text_analyzer.py` relies on `RAG_PROGRAMA_MAX_CHARS` from `config.py`. Setting `RAG_PROGRAMA_MAX_CHARS = 8000` in `config.py` restores the maximum chunk limit so that `chunk_documento` limits oversized units to <= 8,000 chars, satisfying the assertion.

2. **Observations 2-4** show `KeyError: 'pendiente_apps'` when accessing `entrada["pendiente_apps"]` returned by `registrar_perfiles_web`. Including `"pendiente_apps": any(not perfiles.get(red) for red in REDES)` in `entrada` in `scraper/social_finder.py` ensures the dictionary contract matches expectations: `True` if any profile is unpopulated/None, `False` if all profiles exist.

3. **Observations 5-6** show `AssertionError` because `construir_cola` in `scraper/social_apps/cola.py` fails to build `"buscar"` tasks for locations with `pendiente_apps: True` and unpopulated network profiles. Updating `construir_cola` to construct `buscar` tasks (excluding networks present in `apps_sin_resultado` and locations without names) and ordering `leer` tasks before `buscar` tasks fixes both queue tests.

4. **Observations 7-11** show `AttributeError` because `DriverBase` in `scraper/social_apps/drivers.py` lacks helper methods `_perfil_abierto` and `_verificar_perfil_con_handle`. Adding these two methods to `DriverBase` enables title checking, search result page filtering (`_TITULO_RESULTADOS`), and candidate name/handle matching.


## 3. Caveats
- Read-only investigation: No production code or test files were directly modified during this step.
- All code changes are documented in `analysis.md` and this handoff report for the implementer agent to execute.


## 4. Conclusion
All 11 failures are fully accounted for by exact root causes across 4 target files:
- `config.py`: Set `RAG_PROGRAMA_MAX_CHARS = 8000`.
- `scraper/social_finder.py`: Add `"pendiente_apps": any(not perfiles.get(red) for red in REDES)` to `entrada` in `registrar_perfiles_web`.
- `scraper/social_apps/cola.py`: Implement `"buscar"` task generation and sorting in `construir_cola`.
- `scraper/social_apps/drivers.py`: Add `_perfil_abierto` and `_verificar_perfil_con_handle` to `DriverBase`.

Applying these precise changes will bring `pytest tests_fase2/` to **100% pass (177/177)** while maintaining full compliance with requirements R1-R6.


## 5. Verification Method
To verify the fixes once implemented:
1. Run standard test command in workspace:
   `python -m pytest tests_fase2/ -v`
   Expected result: 177 passed, 0 failed.

2. Run isolated R1-R6 test scripts:
   Expected result: 35/35 passed.

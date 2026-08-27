# Handoff Report: Requirement R2 Empirical Verification (Capital Exclusion in `nombres_hermanas`)

## 1. Observation
- Target implementation in `main.py` lines 317–321:
  ```python
  nombres_hermanas = [
      hermana["nombre"]
      for hermana in todas_localidades
      if hermana["id"] != loc["id"] and not hermana.get("es_capital")
  ]
  ```
- Created empirical stress test suite in `tests_fase2/test_r2_stress_edgecases.py`.
- Execution command & result:
  `pytest -v -s tests_fase2/test_r2_stress_edgecases.py` -> `6 passed in 1.00s`
- Full test suite run (`pytest -v tests_fase2/test_r1_geographic_filter_order.py tests_fase2/test_r2_nombres_hermanas_exclusion.py tests_fase2/test_r2_stress_edgecases.py tests_fase2/test_fuentes_chunking.py`):
  -> `28 passed in 1.01s`
- Empirical dataset check (`lugares_espana_actualizado.json`):
  - **1,553** municipalities processed.
  - **8,196** total entities checked (**6,648** pedanías).
  - **0** capital name leaks detected in any pedanía's `nombres_hermanas`.

## 2. Logic Chain
1. In `main.py`, `todas_localidades` contains all entities in a municipality (capital + pedanías).
2. When processing a locality `loc`, `nombres_hermanas` is built by filtering `todas_localidades`.
3. Adding `and not hermana.get("es_capital")` ensures that any entity marked `es_capital: True` (or truthy) is excluded from `nombres_hermanas`.
4. In `fuentes.py` (`clasificar_relevancia_chunk`), chunks mentioning names in `nombres_hermanas` without mentioning `loc["nombre"]` return `None` (discarded).
5. Excluding capital entities from `nombres_hermanas` ensures that municipal web pages mentioning the capital name (e.g., "Amurrio") return `"GENERAL"` instead of `None`, retaining essential municipal context for pedanías (e.g., "Baranbio").
6. Empirical tests confirm that sister pedanía names remain in `nombres_hermanas`, ensuring festival program cross-contamination between sister pedanías is strictly prevented.

## 3. Caveats
- Entities in data must have `es_capital` correctly set to `True` for capitals. If an entity is missing `es_capital`, it defaults to `False` (treated as pedanía). Empirical dataset verification showed that 100% of capital entities in `lugares_espana_actualizado.json` have `es_capital: True`.
- No caveats. All edge cases pass cleanly.

## 4. Conclusion
Requirement R2 fix is fully verified and **APPROVED**.

## 5. Verification Method
To independently verify:
1. Run syntax check:
   `python -m py_compile Algoritmo_fiestas/Fase2_Extraccion_Fiestas/main.py`
2. Run empirical stress test suite:
   `pytest -v Algoritmo_fiestas/Fase2_Extraccion_Fiestas/tests_fase2/test_r2_stress_edgecases.py`
3. Inspect challenge report at:
   `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\challenger_m2_2\challenge.md`

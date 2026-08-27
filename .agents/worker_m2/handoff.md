# Handoff Report: Requirement R2 Fix (`nombres_hermanas` Capital Exclusion)

## 1. Observation
- File modified: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py` (line 317)
- Before change in `main.py`:
  ```python
  nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
  ```
- After change in `main.py`:
  ```python
  nombres_hermanas = [
      hermana["nombre"]
      for hermana in todas_localidades
      if hermana["id"] != loc["id"] and not hermana.get("es_capital")
  ]
  ```
- Tool verification execution:
  - `python -m py_compile main.py` -> exit code `0`
  - `pytest -v tests_fase2/test_r2_nombres_hermanas_exclusion.py` -> `2 passed in 0.04s`
  - `pytest -v tests_fase2/test_r1_geographic_filter_order.py tests_fase2/test_r2_nombres_hermanas_exclusion.py tests_fase2/test_fuentes_chunking.py` -> `22 passed in 0.33s`
- Exact git diff output (`git diff main.py`):
  ```diff
  @@ -314,7 +314,11 @@ async def process_municipio(
               continue
               
           logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']}")
  -        nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
  +        nombres_hermanas = [
  +            hermana["nombre"]
  +            for hermana in todas_localidades
  +            if hermana["id"] != loc["id"] and not hermana.get("es_capital")
  +        ]
           try:
               fiestas_loc = await process_locality(
                   loc, municipio, anno, rag_processor, rrss_client, logger, docs_municipio_cache=docs_municipio_cache, nombres_hermanas=nombres_hermanas
  ```

## 2. Logic Chain
1. In `main.py`, `todas_localidades` is formed by concatenating `capitales + otros` (line 295).
2. Prior to the fix, when generating `nombres_hermanas` for any locality `loc`, all entities in `todas_localidades` with `hermana["id"] != loc["id"]` were included. For a pedanía (non-capital entity), `nombres_hermanas` contained the capital entity's name (e.g. `"Amurrio"`).
3. `clasificar_relevancia_chunk` in `fuentes.py` compares text in municipal chunks (`FUENTE_WEB_MUNICIPIO`) against `nombres_hermanas`. If a chunk contains a sister name from `nombres_hermanas` but does not mention the target pedanía's name, `clasificar_relevancia_chunk` returns `None`, causing the chunk to be discarded.
4. Because municipal website pages almost always mention the municipal capital's name ("Amurrio"), virtually all municipal web chunks were discarded for pedanías.
5. By adding `and not hermana.get("es_capital")` to the list comprehension on line 317, capital entities (`es_capital: True`) are explicitly excluded from `nombres_hermanas`.
6. Therefore, when evaluating a municipal chunk for a pedanía, mentioning the capital name no longer triggers chunk rejection (`None`). Instead, `clasificar_relevancia_chunk` classifies it as `"GENERAL"`, preserving municipal web context for pedanías.

## 3. Caveats
- `es_capital` must be set as a boolean (or truthy value) on capital dictionary objects. `separar_por_tipo` in `main.py` uses `d.get("es_capital")`, matching `hermana.get("es_capital")`.
- Sister pedanías (`es_capital: False` or `None`) remain in `nombres_hermanas`, which is the intended behavior to avoid cross-contaminating festival info between different pedanías.

## 4. Conclusion
Requirement R2 has been fully implemented and verified. The capital entity of a municipality is now explicitly excluded from `nombres_hermanas` in `main.py`, preventing false-positive chunk rejection in `fuentes.py` while adhering to the minimal change principle.

## 5. Verification Method
To independently verify this change:
1. Run syntax check:
   `python -m py_compile Algoritmo_fiestas/Fase2_Extraccion_Fiestas/main.py`
2. Run unit test suite:
   `pytest -v Algoritmo_fiestas/Fase2_Extraccion_Fiestas/tests_fase2/test_r2_nombres_hermanas_exclusion.py`
3. Inspect `main.py` lines 317-321 to verify that `and not hermana.get("es_capital")` is present in the list comprehension for `nombres_hermanas`.

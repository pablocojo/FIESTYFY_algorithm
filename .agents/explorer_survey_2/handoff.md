# Handoff Report: Requirement R2 Survey (`nombres_hermanas` Capital Exclusion)

## 1. Observation
- **File & Line**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`, line 317:
  ```python
  nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
  ```
- **Data Structures**:
  - `main.py` lines 104-115 (`separar_por_tipo`): Capital entities are identified by `d.get("es_capital") == True` and separated into `capitales`. Non-capital entities are placed in `otros`.
  - `main.py` line 295: `todas_localidades = capitales + otros`.
  - `main.py` line 317: `nombres_hermanas` is populated from `todas_localidades` excluding only `hermana["id"] != loc["id"]`.
- **Downstream Consumer**:
  - `main.py` line 319 calls `process_locality(..., nombres_hermanas=nombres_hermanas)`.
  - `main.py` line 243 calls `analyze_festivals_multipass(..., nombres_hermanas=nombres_hermanas)`.
  - `llm_processor/text_analyzer.py` line 377-378 (`filtrar_chunks_por_localidad`) calls `clasificar_relevancia_chunk(item["chunk"], localidad_nombre, nombres_hermanas)` for `FUENTE_WEB_MUNICIPIO` chunks.
  - `fuentes.py` lines 402-406 (`clasificar_relevancia_chunk`):
    ```python
    for hermana in nombres_hermanas:
        hermana_norm = normalize_text(hermana)
        if hermana_norm and hermana_norm in text_norm:
            # Menciona a otra pedanía hermana y no a la objetivo
            return None
    ```

## 2. Logic Chain
1. **Observation 1**: Line 317 in `main.py` builds `nombres_hermanas` by taking all items in `todas_localidades` except the current `loc["id"]`.
2. **Observation 2**: `todas_localidades` contains both `capitales` (`es_capital == True`) and `otros` (`es_capital == False`).
3. **Reasoning Step A**: For any non-capital pedanía (e.g. Baranbio), its `nombres_hermanas` includes the capital's name (e.g. `"Amurrio"`).
4. **Observation 3**: Municipal website documents (`FUENTE_WEB_MUNICIPIO`) frequently contain the name of the municipality / capital ("Amurrio").
5. **Reasoning Step B**: When `clasificar_relevancia_chunk` evaluates a municipal chunk for Baranbio, it checks if any sister name in `nombres_hermanas` appears in the chunk text. Because `"Amurrio"` is in `nombres_hermanas`, any chunk mentioning "Amurrio" (and not "Baranbio") triggers line 406 of `fuentes.py`, returning `None`.
6. **Reasoning Step C**: Returning `None` causes `filtrar_chunks_por_localidad` (line 380 of `text_analyzer.py`) to discard the chunk completely (`continue`).
7. **Conclusion**: Non-capital pedanías are starved of general municipal website chunks. Excluding capital entities (`es_capital == True`) from `nombres_hermanas` prevents this erroneous discarding.

## 3. Caveats
- Assumption: Capital entities in input JSON `lugares` are properly tagged with `"es_capital": true`. If a municipality has no entity with `es_capital: true`, `capitales` is empty and `not hermana.get("es_capital")` evaluates to True for all entities, which safely defaults to the existing behavior without crashing.

## 4. Conclusion
Requirement R2 requires changing line 317 in `main.py` from:
```python
nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
```
to:
```python
nombres_hermanas = [
    hermana["nombre"]
    for hermana in todas_localidades
    if hermana["id"] != loc["id"] and not hermana.get("es_capital")
]
```
(or using `otros`: `nombres_hermanas = [hermana["nombre"] for hermana in otros if hermana["id"] != loc["id"]]`).

## 5. Verification Method
1. **Inspection**:
   - Inspect `main.py` line 317 and verify `not hermana.get("es_capital")` or `hermana in otros` filter is present.
2. **Unit Test Verification**:
   - Run pytest: `pytest tests_fase2/test_fuentes_chunking.py` or a dedicated test verifying `nombres_hermanas` generation for sample data (e.g. Amurrio with capital Amurrio and pedanía Baranbio).
3. **Invalidation Condition**:
   - The fix is invalid if for a non-capital pedanía, `nombres_hermanas` still contains the capital municipality name.

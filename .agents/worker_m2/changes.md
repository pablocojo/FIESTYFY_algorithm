# Summary of Changes for Worker M2 (Requirement R2)

## Target File
`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`

## Objective
Fix `nombres_hermanas` capital exclusion logic so that the capital entity (`es_capital: True` or `hermana.get("es_capital")`) of a municipality is explicitly excluded from the list of sister localities (`nombres_hermanas`).

## Details of Code Modification
In `main.py` (lines 317-321), modified the list comprehension generating `nombres_hermanas`:

### Before:
```python
nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
```

### After:
```python
nombres_hermanas = [
    hermana["nombre"]
    for hermana in todas_localidades
    if hermana["id"] != loc["id"] and not hermana.get("es_capital")
]
```

## Rationale
- `nombres_hermanas` is passed downstream to `clasificar_relevancia_chunk` in `fuentes.py`.
- `clasificar_relevancia_chunk` filters out municipal website chunks (`FUENTE_WEB_MUNICIPIO`) if they mention any sister locality in `nombres_hermanas` without mentioning the target locality.
- Municipal website pages almost universally mention the municipal capital's name (e.g. "Amurrio"). Previously, because the capital entity was included in `nombres_hermanas` for pedanías, valid municipal website chunks were wrongly discarded (`return None`).
- With `and not hermana.get("es_capital")`, the capital name is excluded from `nombres_hermanas`. Consequently, municipal chunks mentioning the municipality capital are properly classified as `"GENERAL"` instead of being dropped, allowing pedanías to retain critical municipal web context.

## Added Tests
Created `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\tests_fase2\test_r2_nombres_hermanas_exclusion.py` to verify:
1. `nombres_hermanas` excludes capital entities for both pedanías and capital entities.
2. `clasificar_relevancia_chunk` classifies municipal chunks referencing the capital as `"GENERAL"` for pedanías rather than `None`.

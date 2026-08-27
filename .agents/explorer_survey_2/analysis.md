# Codebase Investigation Report: Requirement R2 (`nombres_hermanas` Capital Exclusion in `main.py`)

## Executive Summary
This report provides a detailed analysis of Requirement R2 for the Fiestyfy RAG Pipeline Fix project. The objective of R2 is to fix the construction of `nombres_hermanas` in `main.py` to ensure that the capital entity of a municipality is explicitly excluded from the list of sister localities (`nombres_hermanas`).

**Core Finding**: In `main.py` (line 317), `nombres_hermanas` is constructed by taking every entity in `todas_localidades` except the current locality `loc["id"]`. Because `todas_localidades` is formed by concatenating `capitales + otros` (line 295), `nombres_hermanas` for any non-capital pedanía includes the capital entity (e.g., `"Amurrio"`). Downstream in `fuentes.py` (`clasificar_relevancia_chunk`), any chunk from the municipal website (`FUENTE_WEB_MUNICIPIO`) that mentions any sister locality is discarded (`return None`). Since municipal web pages almost always mention the capital / municipality name ("Amurrio"), virtually all municipal website chunks are wrongly discarded for pedanías, starving them of valid context.

---

## 1. Problem Boundary & Scope
- **Target File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`
- **Related Files**:
  - `llm_processor/text_analyzer.py` (lines 365-394: `filtrar_chunks_por_localidad`)
  - `fuentes.py` (lines 387-410: `clasificar_relevancia_chunk`)
- **Question Answered**: Where and how is `nombres_hermanas` populated in `main.py`, how is capital identified, why does including the capital cause chunk drop-outs, and what exact line change fixes it?

---

## 2. Detailed Technical Investigation & Call Chain

### A. Data Structures & Capital Identification in `main.py`
In `main.py`, places loaded from JSON are grouped by root municipality:

1. **`separar_por_tipo(descendientes: list[dict]) -> tuple` (lines 104-116)**:
   ```python
   104: def separar_por_tipo(descendientes: list[dict]) -> tuple:
   105:     tipos_validos = {"pueblo", "ciudad_pequena", "ciudad_grande", "distrito", "barrio"}
   106:     capitales = []
   107:     otros = []
   108:     for d in descendientes:
   109:         if d.get("tipo") not in tipos_validos:
   110:             continue
   111:         if d.get("es_capital"):
   112:             capitales.append(d)
   113:         else:
   114:             otros.append(d)
   115:     return capitales, otros
   ```
   - **Capital Identification**: A descendant entity is identified as the municipality capital via `d.get("es_capital") == True` (or truthy).
   - `capitales`: List of entity dicts marked as `es_capital: true`.
   - `otros`: List of non-capital entity dicts (`es_capital: false` or omitted).

2. **`process_municipio` (lines 289-321)**:
   ```python
   289:     capitales, otros = separar_por_tipo(descendientes)
   ...
   295:     todas_localidades = capitales + otros
   ...
   316:     for j, loc in enumerate(todas_localidades):
   317:         nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
   318:         try:
   319:             fiestas_loc = await process_locality(
   320:                 loc, municipio, anno, rag_processor, rrss_client, logger, docs_municipio_cache=docs_municipio_cache, nombres_hermanas=nombres_hermanas
   321:             )
   ```

### B. Downstream Impact of Including Capital in `nombres_hermanas`

1. **Passing `nombres_hermanas`**:
   - `main.py:319`: `process_locality` receives `nombres_hermanas`.
   - `main.py:243`: `process_locality` passes `nombres_hermanas` to `analyze_festivals_multipass`.
   - `text_analyzer.py`: `analyze_festivals_multipass` calls `seleccionar_chunks(..., nombres_hermanas=nombres_hermanas)`.
   - `text_analyzer.py:413`: `seleccionar_chunks` calls `filtrar_chunks_por_localidad(items, localidad_nombre, nombres_hermanas)`.

2. **Geographic Chunk Classification in `fuentes.py`**:
   `text_analyzer.py` line 378 calls `clasificar_relevancia_chunk(item["chunk"], localidad_nombre, nombres_hermanas)` for chunks with `fuente_base == FUENTE_WEB_MUNICIPIO`.

   In `fuentes.py` (lines 387-410):
   ```python
   387: def clasificar_relevancia_chunk(chunk_text: str, localidad_nombre: str, nombres_hermanas: list[str]) -> str | None:
   395:     text_norm = normalize_text(chunk_text)
   396:     loc_norm = normalize_text(localidad_nombre)
   397:     
   398:     menciona_objetivo = loc_norm in text_norm
   399:     if menciona_objetivo:
   400:         return "DIRECTA"
   401:         
   402:     for hermana in nombres_hermanas:
   403:         hermana_norm = normalize_text(hermana)
   404:         if hermana_norm and hermana_norm in text_norm:
   405:             # Menciona a otra pedanía hermana y no a la objetivo
   406:             return None
   407:             
   408:     return "GENERAL"
   ```

3. **The Failure Mechanism**:
   - Consider municipality **Amurrio** with capital entity **Amurrio** (`es_capital: true`) and pedanías **Baranbio**, **Lezama**, etc. (`es_capital: false`).
   - When processing pedanía **Baranbio** (`loc`):
     - `todas_localidades` = `[Amurrio (capital), Baranbio, Lezama]`.
     - Current line 317 builds `nombres_hermanas` = `["Amurrio", "Lezama"]`.
     - When checking a chunk from `amurrio.eus` for Baranbio:
       - The chunk contains general festival text mentioning the municipality name "Amurrio", but not "Baranbio".
       - `clasificar_relevancia_chunk` checks `menciona_objetivo` ("baranbio" in text) -> False.
       - Next, it checks `nombres_hermanas`: "amurrio" is in `nombres_hermanas` and "amurrio" IS in text!
       - `clasificar_relevancia_chunk` assumes "Amurrio" is a sister pedanía, so it returns `None` (DISCARD CHUNK)!
     - **Consequence**: Non-capital pedanías lose almost all chunks from `FUENTE_WEB_MUNICIPIO` because municipal chunks inevitably mention the municipality capital's name.

---

## 3. Recommended Solution & Code Modification

To resolve Requirement R2, `nombres_hermanas` in `main.py` must explicitly exclude any entity where `es_capital` is `True`.

### Target Location
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`
- **Line**: 317

### Before (Current Implementation):
```python
nombres_hermanas = [hermana["nombre"] for hermana in todas_localidades if hermana["id"] != loc["id"]]
```

### After (Proposed Fix):
```python
nombres_hermanas = [
    hermana["nombre"]
    for hermana in todas_localidades
    if hermana["id"] != loc["id"] and not hermana.get("es_capital")
]
```
*(Or alternatively, using the already filtered `otros` list from line 289)*:
```python
nombres_hermanas = [
    hermana["nombre"]
    for hermana in otros
    if hermana["id"] != loc["id"]
]
```

### Behavioral Comparison After Fix
1. **For a Non-Capital Pedanía (e.g. Baranbio)**:
   - `nombres_hermanas` = `["Lezama", "Larrimbe", ...]` (capital `"Amurrio"` is excluded).
   - Chunks from `amurrio.eus` mentioning general municipal info or "Amurrio" are classified as `"GENERAL"` (score penalty -0.10) instead of being discarded (`None`). They remain available for RAG processing!
   - Chunks mentioning specifically another non-capital sister (e.g. "Lezama") are still properly discarded.

2. **For the Capital Entity (e.g. Amurrio capital pueblo)**:
   - `nombres_hermanas` = `["Baranbio", "Lezama", ...]` (capital `"Amurrio"` is excluded because `hermana["id"] == loc["id"]`).
   - Chunks mentioning specifically a non-capital pedanía (e.g. "Baranbio") without mentioning "Amurrio" are discarded for Amurrio capital, preventing pedanía festivals from contaminating the capital's extraction.

---

## 4. Verification Plan

The implementer can verify this fix using the following steps:

1. **Unit Test Verification**:
   Create or run a test in `tests_fase2/test_r2_nombres_hermanas.py` verifying that:
   - For a pedanía entity (`es_capital: false`), its `nombres_hermanas` list does not contain the capital's name.
   - For a capital entity (`es_capital: true`), its `nombres_hermanas` list contains only non-capital sisters and does not contain itself.
   - `clasificar_relevancia_chunk` with the fixed `nombres_hermanas` returns `"GENERAL"` (not `None`) for a municipal chunk mentioning the municipality capital when evaluating for a pedanía.

2. **Pipeline Integration Verification**:
   - Process Amurrio municipality (`01002000000`) and check that non-capital pedanías (e.g. Baranbio) receive municipal chunks and successfully extract festival data.

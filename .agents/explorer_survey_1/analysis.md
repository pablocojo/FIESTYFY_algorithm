# Investigation Report: Requirement R1 and Requirement R3 Analysis

**Project**: Fiestyfy RAG Pipeline Fix  
**Component**: `llm_processor/text_analyzer.py`  
**Explorer**: Codebase Explorer 1  
**Date**: 2026-08-08  

---

## Executive Summary

This report provides a detailed investigation of `llm_processor/text_analyzer.py` targeting **Requirement R1** (Geographic Filtering Execution Order) and **Requirement R3** (Embedding Vector Target: Raw `chunk` vs. `chunk_contextualizado`). 

Key discoveries:
1. **R1 Defect**: `filtrar_chunks_por_localidad` is currently called inside `seleccionar_chunks`. In `enrich_festival_program`, `filtrar_chunks_por_localidad` was erroneously called *before* cosine similarity was calculated, resulting in `item["score"]` adjustments (+0.15 / -0.10) being completely overwritten by cosine similarity calculation.
2. **R1 Remediation**: Decouple `filtrar_chunks_por_localidad` from `seleccionar_chunks`. Ensure all retrieval pipelines enforce the strict order: `Similarity Calculation -> Geographic Filtering (Score adjustment & locality exclusion) -> Budget & Priority Selection (seleccionar_chunks)`.
3. **R3 Defect**: In `index_document_chunks`, embeddings are currently computed on `chunk_contextualizado` (which includes source boilerplate warnings like `[FUENTE: Web oficial ... | AVISO: ...]`). This introduces significant vector noise.
4. **R3 Remediation**: Modify `index_document_chunks` to pass `item["chunk"]` (raw chunk text) to `get_embeddings_batch` instead of `chunk_contextualizado`.

---

## 1. Investigation of Requirement R1: Geographic Filtering Placement

### 1.1 Context & Function Definitions

In `llm_processor/text_analyzer.py`:
- `filtrar_chunks_por_localidad(items, localidad_nombre, nombres_hermanas)` (lines 365–394):
  Evaluates chunks from municipal sources (`web_municipio`). If the chunk explicitly mentions a sister pedanía, it is discarded (`relevancia is None`). If it mentions the target pedanía, `item["relevancia_geo"] = "DIRECTA"` and `item["score"] += 0.15`. If generic, `item["relevancia_geo"] = "GENERAL"` and `item["score"] -= 0.10`.
- `seleccionar_chunks(...)` (lines 396–440):
  Packs chunks into character budgets (`budget_chars`) based on source priority (official sources prioritized over search engines, similarity threshold `umbral`). Currently, line 413 calls `items = filtrar_chunks_por_localidad(items, localidad_nombre, nombres_hermanas)`.

### 1.2 Analysis of Current Flow Across Retrieval Pipeline Functions

#### 1. `discover_festivals_for_locality` & `retrieve_discovery_context` (lines 1218–1225 & 1439–1446):
- Similarity score `item["score"]` is calculated via `cosine_similarity`.
- `seleccionar_chunks(...)` is called with `localidad_nombre` and `nombres_hermanas`.
- `seleccionar_chunks` internally calls `filtrar_chunks_por_localidad`, which modifies `item["score"]` *after* similarity calculation.
- **Problem**: Calling `filtrar_chunks_por_localidad` inside `seleccionar_chunks` violates single-responsibility principle. `seleccionar_chunks` should be responsible only for budget packing and official vs external source prioritization, not geographic re-ranking.

#### 2. `enrich_festival_program` (lines 1309–1332):
- Line 1310 executes:
  ```python
  base_items = [dict(item) for item in indexed_chunks]
  base_items = filtrar_chunks_por_localidad(base_items, localidad["nombre"], nombres_hermanas or [])
  ```
- Then inside the loop for daily queries (line 1317):
  ```python
  for (fecha_str, query_str), query_emb in zip(consultas_dias, query_embs):
      items_copy = [dict(item) for item in base_items]
      if query_emb:
          for item in items_copy:
              item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
  ```
- **CRITICAL BUG**: Because `filtrar_chunks_por_localidad` ran *before* similarity computation, `item["score"]` was modified when `item.get("score", 0.0)` was `0.0`. Subsequently, line 1317 overwrites `item["score"]` with the raw cosine similarity value, **completely destroying** the +0.15 bonus for DIRECTA relevance and -0.10 penalty for GENERAL relevance!

### 1.3 Recommended Code Changes for R1

#### Change 1: Refactor `seleccionar_chunks`
Remove `filtrar_chunks_por_localidad` from inside `seleccionar_chunks`:
```python
# llm_processor/text_analyzer.py lines 396-415

def seleccionar_chunks(
    items: list[dict],
    budget_chars: int,
    umbral: float = RAG_UMBRAL_SIMILITUD,
    min_oficiales: int = RAG_MIN_OFICIALES_SIN_UMBRAL,
) -> list[dict]:
    """
    Selección por cuotas de prioridad sobre items PRE-FILTRADOS y PRE-PONDERADOS.
    1º entran los chunks relevantes de fuentes OFICIALES (por prioridad y score);
    la búsqueda web solo rellena el presupuesto restante.
    """
    oficiales = [i for i in items if es_fuente_oficial(i["fuente"])]
    externos = [i for i in items if not es_fuente_oficial(i["fuente"])]
    ...
```

#### Change 2: Update `discover_festivals_for_locality`
Explicitly apply `filtrar_chunks_por_localidad` AFTER similarity score calculation:
```python
# llm_processor/text_analyzer.py lines 1218-1226

    if query_emb:
        for item in items_copy:
            item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
    else:
        for item in items_copy:
            item["score"] = 0.0

    items_copy = filtrar_chunks_por_localidad(items_copy, localidad["nombre"], nombres_hermanas or [])
    seleccion = seleccionar_chunks(items_copy, DISCOVERY_MAX_CHARS, RAG_UMBRAL_SIMILITUD if query_emb else -1.0)
```

#### Change 3: Update `retrieve_discovery_context`
Explicitly apply `filtrar_chunks_por_localidad` AFTER similarity score calculation:
```python
# llm_processor/text_analyzer.py lines 1439-1447

    if query_emb:
        for item in items_copy:
            item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
    else:
        for item in items_copy:
            item["score"] = 0.0

    items_copy = filtrar_chunks_por_localidad(items_copy, localidad["nombre"], nombres_hermanas or [])
    seleccion = seleccionar_chunks(items_copy, max_chars, RAG_UMBRAL_SIMILITUD if query_emb else -1.0)
```

#### Change 4: Update `enrich_festival_program`
Remove premature `filtrar_chunks_por_localidad` call on `base_items`, and apply it inside the daily query loop AFTER computing `item["score"]`:
```python
# llm_processor/text_analyzer.py lines 1309-1333

    base_items = [dict(item) for item in indexed_chunks]

    for (fecha_str, query_str), query_emb in zip(consultas_dias, query_embs):
        items_copy = [dict(item) for item in base_items]
        if query_emb:
            for item in items_copy:
                item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
        else:
            for item in items_copy:
                txt = item["chunk"].lower()
                score = 0.0
                if fecha_str in txt:
                    score += 0.5
                if nombre_fiesta.lower() in txt:
                    score += 0.3
                item["score"] = score

        # Apply geographic filtering AFTER score calculation
        items_copy = filtrar_chunks_por_localidad(items_copy, localidad["nombre"], nombres_hermanas or [])

        chunks_dia = [i for i in items_copy if i.get("score", 0.0) >= RAG_UMBRAL_SIMILITUD]
        if not chunks_dia:
            chunks_dia = sorted(items_copy, key=lambda i: -i.get("score", 0.0))[:3]
        else:
            chunks_dia = sorted(chunks_dia, key=lambda i: (i["prioridad"], -i.get("score", 0.0)))[:3]

        for item in chunks_dia:
            chunk_key = (item["fuente"], item["chunk"])
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                chunks_seleccionados_dias.append(item)
```

---

## 2. Investigation of Requirement R3: Embedding Vector Target (`chunk` vs. `chunk_contextualizado`)

### 2.1 Context & Current Code Location

In `llm_processor/text_analyzer.py`, `index_document_chunks` (lines 1070–1122):
```python
async def index_document_chunks(
    rag_processor: AsyncRAGProcessor | None,
    documentos: list[dict],
    municipio_nombre: str = "",
    localidad_nombre: str = "",
) -> list[dict]:
    ...
    for doc in documentos:
        ...
        for chunk in chunk_documento(texto, chunk_size):
            cabecera = generar_cabecera_chunk(doc, municipio_nombre, localidad_nombre)
            chunk_contextualizado = f"{cabecera}\n{chunk}"
            items.append({
                "chunk": chunk,
                "chunk_contextualizado": chunk_contextualizado,
                ...
            })
    ...
    if rag_processor is not None:
        chunks_text = [i["chunk_contextualizado"] for i in items]
        batch_size = rag_processor.batch_size
        all_embeddings = []
        try:
            async with aiohttp.ClientSession() as session:
                for b in range(0, len(chunks_text), batch_size):
                    batch_embs = await rag_processor.get_embeddings_batch(
                        session, chunks_text[b : b + batch_size]
                    )
                    all_embeddings.extend(batch_embs)
            for item, emb in zip(items, all_embeddings):
                item["embedding"] = emb
```

### 2.2 Analysis of R3 Impact

- `generar_cabecera_chunk` (in `fuentes.py`, lines 366–385) produces headers like:
  `[FUENTE: Web oficial del municipio de Alicante (https://...) | AVISO: Este contenido pertenece al MUNICIPIO en general, NO específicamente a la pedanía T party]`
- When `chunks_text` uses `i["chunk_contextualizado"]`, dense embedding models vector-encode boilerplate text, URLs, warning labels, and administrative header phrasing.
- This introduces vector noise and skews cosine similarity matching between search queries (which look for festival events, dates, and activities) and chunks.
- Computing embeddings on raw `chunk` text ensures pure semantic representation of the actual festival data without header distortion.

### 2.3 Recommended Code Change for R3

In `index_document_chunks` (line 1106):
```python
# BEFORE (Line 1106):
chunks_text = [i["chunk_contextualizado"] for i in items]

# AFTER (Line 1106):
chunks_text = [i["chunk"] for i in items]
```

`chunk_contextualizado` remains in `item` if needed for prompt construction, but `get_embeddings_batch` receives `i["chunk"]`.

---

## Summary Table of Proposed Code Modifications

| Location in `text_analyzer.py` | Change Description | Requirement |
|---|---|---|
| Lines 396–415 (`seleccionar_chunks`) | Remove `filtrar_chunks_por_localidad` call from inside function; remove `localidad_nombre` and `nombres_hermanas` params | R1 |
| Lines 1218–1226 (`discover_festivals_for_locality`) | Add explicit `filtrar_chunks_por_localidad` AFTER similarity score computation | R1 |
| Lines 1439–1447 (`retrieve_discovery_context`) | Add explicit `filtrar_chunks_por_localidad` AFTER similarity score computation | R1 |
| Lines 1309–1333 (`enrich_festival_program`) | Move `filtrar_chunks_por_localidad` call inside daily loop AFTER score calculation | R1 |
| Line 1106 (`index_document_chunks`) | Change `chunks_text` source from `i["chunk_contextualizado"]` to `i["chunk"]` | R3 |

---

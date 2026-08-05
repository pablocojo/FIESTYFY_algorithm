# Technical Analysis: `process_locality` Pipeline Orchestration & Multi-Pass RAG Integration

## Executive Summary
This document provides a comprehensive technical analysis of `process_locality` in `main.py`, its interaction with `llm_processor/text_analyzer.py` and `AsyncRAGProcessor`, and the structural modifications required to transition from single-pass context saturation to a **Multi-Pass RAG Architecture** (Discovery Pass -> Enrichment Pass -> Final Validation).

---

## 1. Examination of `process_locality` in `main.py`

### 1.1 Signature & Input Parameters
`process_locality` is an asynchronous worker function in `main.py`:
```python
async def process_locality(
    localidad: dict,
    municipio: dict,
    anno: int,
    rag_processor: AsyncRAGProcessor,
    rrss_client: RRSSClient | None,
    logger: logging.Logger,
    docs_municipio_cache: list[dict] | None = None,
) -> list[dict]
```

| Parameter | Type | Description |
|---|---|---|
| `localidad` | `dict` | Target locality/sub-entity (contains `id`, `nombre`, `tipo`, `es_capital`, `sitio_web`, `lat`, `lng`). |
| `municipio` | `dict` | Parent municipality (contains `id`, `nombre`, `provincia`, `comunidad_autonoma`, `sitio_web`). |
| `anno` | `int` | Extraction target year (e.g., `2026`). |
| `rag_processor` | `AsyncRAGProcessor` | RAG processor handling document chunking, batch embeddings, similarity search, and context assembly. |
| `rrss_client` | `RRSSClient \| None` | Client interface to the Windows social scraping server. |
| `logger` | `logging.Logger` | Pipeline logger instance. |
| `docs_municipio_cache` | `list[dict] \| None` | Optional pre-crawled list of municipality web documents. |

### 1.2 Output Structure
Returns a `list[dict]` containing validated, deduplicated festival dictionaries. Each festival dictionary follows this schema:
```json
{
  "id": "san-roque-2026-03014000101",
  "lugar_id": "03014000101",
  "nombre": "Fiestas Patronales de San Roque",
  "fecha_inicio": "2026-08-14",
  "fecha_fin": "2026-08-16",
  "tamano": "grande",
  "descripcion": "Fiestas patronales en honor a San Roque con pasacalles, verbenas y procesiones.",
  "confianza": "alta",
  "fuentes": ["web_municipio", "rrss_localidad:facebook"],
  "solo_fuentes_no_oficiales": false,
  "programa": [
    {
      "dia": 1,
      "fecha": "2026-08-14",
      "eventos": [
        {"hora": "12:00", "descripcion": "Volteo de campanas y chupinazo de inicio de fiestas."},
        {"hora": "23:00", "descripcion": "Gran verbena a cargo de la Orquesta Panorama en la Plaza Mayor."}
      ]
    }
  ],
  "origen": "extraccion",
  "es_estimada": false,
  "incluye_dia_patron": true,
  "lat": 38.3452,
  "lng": -0.4815
}
```

### 1.3 Execution Sequence in `process_locality`
1. **Parallel Patron Search Task**:
   - Launches `obtener_patron(localidad, municipio)` via `asyncio.create_task` so web scraping and patron resolution run concurrently.
2. **Document Acquisition Cascade**:
   - **Step 1 (Web Localidad)**: Crawls `localidad["sitio_web"]` if custom and non-empty. Registers social profiles.
   - **Step 2 (Web Municipio)**: Reuses `docs_municipio_cache` or crawls `municipio["sitio_web"]`.
   - **Step 3-4 (RRSS)**: Loads social documents from disk cache or requests real-time extraction via `rrss_client`.
   - **Step 4.5 (Media Search)**: If zero official documents exist, queries regional press (`search_locality_media`).
   - **Step 5 (Web Search)**: Executes search engine queries (`search_locality_web`) for supplementary snippets/pages.
3. **Patron Await & Date Resolution**:
   - Awaits `patron_task` and calculates `fecha_patron = fecha_del_patron(patron, anno)`.
4. **Document Sanity Filter**:
   - Filters out documents with empty or whitespace-only text.
   - If `documentos` is empty, returns early with `integrar_patron([], patron, anno, localidad)`.
5. **Language Profile & Query Construction**:
   - Obtains regional terms: `perfil_data = get_language_profile(comunidad, provincia)`.
   - Constructs single RAG query string: `query_rag = f"{terminos_rag} en {municipio['nombre']} para la localidad de {localidad['nombre']} en el año {anno}"`.
6. **Single-Pass RAG Context Saturation**:
   - Calls `contexto, fuentes_contexto = await rag_processor.saturate_context_docs(documentos, query_rag)`.
7. **Single-Pass LLM Analysis & Post-LLM Validation**:
   - Calls `fiestas = await analyze_festivals_for_locality(municipio, localidad, contexto, anno, fecha_patron, fuentes_contexto)`.
8. **Patron Integration & Geo-Tagging**:
   - Calls `fiestas = integrar_patron(fiestas, patron, anno, localidad)`.
   - Attaches `lat` and `lng` to all festival dicts.
   - Logs result count and returns `fiestas`.

---

## 2. Data Mapping & Flow into `text_analyzer.py`

```
+-----------------------------------------------------------------------+
|                         process_locality()                            |
|  - Collects documentos: [{"texto", "fuente", "url", "es_calendario"}]  |
|  - Patron: patron, fecha_patron                                       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                         AsyncRAGProcessor                             |
|  1. chunk_documento(doc["texto"]) -> Chunks with preserved schedules  |
|  2. get_embeddings_batch(session, chunks) via nomic-embed-text-v1.5   |
|  3. Cosine similarity with query embedding                             |
|  4. seleccionar_chunks() -> Quota allocation (Official > Search)      |
|  5. ensamblar_contexto() -> Formatted text with source headers        |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                    analyze_festivals_for_locality()                   |
|  1. process_translation_pipeline() -> FastText + Opus-MT/Apertium     |
|  2. DICCIONARIO_FESTIVO static keyword replacements                   |
|  3. System Prompt injection: CRITERIO_FIESTAS, JERARQUIA_FUENTES,      |
|     regla_exclusividad                                                |
|  4. llm_chat_json() via Qwen 2.5 7B (under LLM_SEMAPHORE)             |
|  5. validar_fiestas() -> dates, strictly 1-day filter, source checks  |
+-----------------------------------------------------------------------+
```

### Key Parameters Passed to `text_analyzer.py`:
- `documentos`: List of raw text chunks with metadata (`fuente`, `url`, `es_calendario`).
- `query_rag`: Search query for chunk vector similarity.
- `municipio` & `localidad` metadata: Controls exclusivity rules (`es_capital` vs pedanía rules), slug formatting, and location scoping.
- `anno`: Enforces target year validation (`_validar_fecha`).
- `fecha_patron`: `datetime.date` object or `None` used for strict 1-day festival exception matching.
- `fuentes_contexto`: Set of active sources present in RAG selection used to validate LLM source declarations.

---

## 3. Required Updates for Multi-Pass RAG Architecture

### 3.1 Motivation & Rationale
Under the current single-pass architecture, `rag_processor.saturate_context_docs` fills up to `context_limit_chars` (~24K chars / ~6K tokens) with a mix of general festival chunks and daily event schedules. When a locality has multiple festivals or long daily event listings:
1. General chunks compete with granular daily schedules for context space.
2. The single LLM prompt must simultaneously discover all festivals AND extract full detailed schedules for every day of every festival in a single generation.
3. This frequently leads to incomplete event programs, dropped festivals, or context window overflow.

The **Multi-Pass RAG Architecture** decomposes this process into two focused passes:

```
+-----------------------------------------------------------------------+
|                         DISCOVERY PASS                                |
|  Query: "fiestas, festividades, programa de actos en {localidad}"     |
|  Retrieve: Top 10-15 general chunks (~5.8K tokens / ~23K chars)       |
|  LLM Call: Extracts list of basic festivals                           |
|    => [{"nombre", "fecha_inicio", "fecha_fin", "tamano", "desc"}]     |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                         ENRICHMENT PASS                               |
|  For each festival in discovered list:                                |
|    For each date in [fecha_inicio .. fecha_fin]:                      |
|      Query: "{nombre_fiesta} {fecha_dia} programa actos"              |
|      Retrieve: Top 1-3 chunks per day                                 |
|    Combine day chunks -> LLM Call for detailed "programa" array       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                    POST-LLM VALIDATION & PATRON                       |
|  - validar_fiestas() on enriched festivals                            |
|  - integrar_patron() & attach lat/lng                                 |
+-----------------------------------------------------------------------+
```

### 3.2 Required Updates in `text_analyzer.py`

1. **`AsyncRAGProcessor` Enhancement**:
   - Add parameter `top_k_chunks` or `max_chunks` to `saturate_context_docs` or add a dedicated method `retrieve_top_k_chunks(documentos, query, k=15)` for the Discovery Pass.
   - Add a method `retrieve_chunks_for_day(documentos, query_dia, max_chunks_per_day=3)` for retrieving specific day chunks in the Enrichment Pass.

2. **Discovery Pass Function (`analyze_festivals_discovery`)**:
   - Uses system prompt tailored for festival discovery.
   - Prompt explicitly asks for:
     ```json
     {
       "fiestas": [
         {
           "id": "slug",
           "lugar_id": "...",
           "nombre": "...",
           "fecha_inicio": "YYYY-MM-DD",
           "fecha_fin": "YYYY-MM-DD",
           "tamano": "pequeña" | "grande",
           "descripcion": "...",
           "confianza": "alta" | "media" | "baja",
           "fuentes": [...]
         }
       ]
     }
     ```
   - Does NOT request detailed `programa` array during Discovery.

3. **Enrichment Pass Function (`analyze_festivals_enrichment`)**:
   - Accepts a discovered festival dictionary and the aggregated day chunks.
   - Iterates day-by-day through `[fecha_inicio .. fecha_fin]`.
   - Constructs daily query: `f"{festival['nombre']} {fecha_dia} programa de actos"`.
   - Retrieves top 1-3 chunks per day.
   - Sends combined day chunks to LLM to extract the `"programa"` array (`dia`, `fecha`, `eventos`: `hora`, `descripcion`).

4. **Multi-Pass Coordinator (`analyze_festivals_multipass`)**:
   - High-level entry point that orchestrates Discovery Pass, Enrichment Pass, and final `validar_fiestas`.

### 3.3 Required Updates in `main.py` (`process_locality`)

In `process_locality`, replace the single-pass call sequence:
```python
# OLD SINGLE-PASS CALL:
contexto, fuentes_contexto = await rag_processor.saturate_context_docs(documentos, query_rag)
fiestas = await analyze_festivals_for_locality(
    municipio, localidad, contexto, anno, fecha_patron, fuentes_contexto
)
```

With the new multi-pass call:
```python
# NEW MULTI-PASS CALL:
fiestas = await analyze_festivals_multipass(
    municipio=municipio,
    localidad=localidad,
    documentos=documentos,
    anno=anno,
    fecha_patron=fecha_patron,
    rag_processor=rag_processor,
    logger=logger,
)
```

This ensures `process_locality` remains clean, modular, and focused on pipeline orchestration (document harvesting, patron execution, state persistence), delegating multi-pass RAG logic entirely to `text_analyzer.py`.

---

## 4. Error Handling, Return Structures, Logging & Integration Points

### 4.1 Error Handling Strategies

| Edge Case / Error Condition | Handling Strategy |
|---|---|
| **Zero Documents Harvested** | Return early with `integrar_patron([], patron, anno, localidad)` — no RAG or LLM calls. |
| **Discovery Pass Returns Zero Festivals** | Skip Enrichment Pass entirely; return early with `integrar_patron([], patron, anno, localidad)`. |
| **Invalid Date Range in Discovery** | If `fecha_inicio > fecha_fin` or unparseable date, swap dates or default to 1-day festival before day iteration. |
| **Excessively Long Festival Duration** | Cap day iteration at `FIESTA_MAX_DURACION_DIAS=15` (or 30) to prevent infinite loops or excessive day queries if LLM hallucinates an unrealistic duration. |
| **Enrichment LLM Call Failure / Timeout** | Retain the discovered festival metadata with `"programa": []` rather than discarding the festival. |
| **LM Studio VRAM Overflow / Concurrency** | All LLM calls pass through `LLM_SEMAPHORE = asyncio.Semaphore(1)` to guarantee single-threaded LLM execution. |

### 4.2 Return Structure Integrity
The return value of `process_locality` remains `list[dict]`, preserving full backwards compatibility with:
- `process_municipio`
- `StateManager.guardar_estado_localidad`
- `generar_informe_ejecucion` (R6 execution metrics)

### 4.3 Logging Enhancements
In corporate/production logs, multi-pass steps will output structured log lines:
```text
[DISCOVERY PASS] Locality: Alicante | Chunks: 12 (~4.8K tokens) -> Discovered 3 festivals
[ENRICHMENT PASS] Festival: "Fiestas de San Juan" (5 days: 2026-06-20 to 2026-06-24)
  -> Day 2026-06-20: 2 chunks retrieved
  -> Day 2026-06-21: 3 chunks retrieved
  -> Enriched festival with 42 events across 5 days.
```

### 4.4 Verification Scripts Required (Acceptance Criteria Compliance)
1. **`test_enrichment_query_construction.py`**:
   - Verifies daily query generation across multi-day festivals, including month boundaries (e.g. Aug 28 to Sep 2).
2. **`test_multipass_rag_tokens.py`**:
   - Simulates multi-pass RAG over mocked chunks to prove token count per LLM request stays well below 32K context limit (under 12K tokens).

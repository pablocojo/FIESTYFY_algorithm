# Analysis Report: Multi-Pass RAG Architecture for Fiestyfy (Fase 2)

**Author**: Explorer 1 (`teamwork_preview_explorer`)  
**Date**: 2026-08-05  
**Target Module**: `llm_processor/text_analyzer.py` & `main.py`  
**Workspace**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`

---

## 1. Executive Summary

This investigation analyzes the current single-pass RAG implementation in `llm_processor/text_analyzer.py` and details the architectural design for a **Multi-Pass RAG Pipeline** consisting of:
1. **Discovery Pass**: Retrieves general festival chunks (top 10–15 chunks, ~5.8K tokens / ~15,000 chars) across all scraped documents to extract a JSON list of basic festival metadata (`nombre`, `fecha_inicio`, `fecha_fin`, `tamano`, `descripcion`, `confianza`, `fuentes`).
2. **Enrichment Pass**: Iterates through discovered festivals, generates specific daily queries (`"{nombre_fiesta} {fecha_dia} programa actos"`) for each day in the festival's date range, retrieves top 1–3 targeted chunks per day, and prompts the LLM with the combined day-specific context to populate the detailed event program (`programa`).

This multi-pass approach resolves context overflow errors in local LLMs (e.g. Qwen 2.5 7B running in LM Studio), avoids output JSON truncation, improves vector search relevance for granular daily schedules, and keeps token usage safely below 12K tokens per LLM request.

---

## 2. Examination of Existing `text_analyzer.py` Implementation

### 2.1 Imports and External Dependencies
- **Standard Library**: `asyncio`, `math`, `json`, `re`, `logging`, `datetime`, `date`.
- **HTTP Client**: `aiohttp` for async communication with LM Studio endpoints (`LMSTUDIO_EMBEDDING_URL`, `LMSTUDIO_CHAT_URL`).
- **FastText / Translation**: `fasttext` (for language detection via `lid.176.ftz`), `transformers` (Opus-MT fallback), `subprocess` (Apertium fallback).
- **Project Modules**:
  - `config`: `RAG_MAX_TOKENS`, `RAG_CHARS_PER_TOKEN`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_EMBEDDING_BATCH_SIZE`, `RAG_PROGRAMA_MAX_CHARS`, `RAG_UMBRAL_SIMILITUD`, `RAG_MIN_OFICIALES_SIN_UMBRAL`, `LMSTUDIO_*`.
  - `llm_processor.festival_filter`: `sanear_fiesta`, `evaluar_fiesta`.
  - `fuentes`: `es_fuente_oficial`, `es_fuente_valida`, `fuente_base`, `prioridad_fuente`, `rotulo_fuente`.
  - `config_idiomas`: `get_language_profile`.

### 2.2 Core Functions in `text_analyzer.py`

#### A. Chunking & Text Preparation
- **`_dividir_en_unidades(texto: str) -> list[str]`**:
  Splits text by newline (`\n`) or sentence boundaries (`[.!?]`). Splits units larger than `RAG_PROGRAMA_MAX_CHARS` (8000 chars) as a safety measure.
- **`chunk_documento(texto: str, chunk_size: int = RAG_CHUNK_SIZE) -> list[str]`**:
  Fragments a single document respecting sentence boundaries. Detects schedule/program blocks (lines with timestamps `\b\d{1,2}[:.h]\d{2}\b`) and expands chunk limit up to `RAG_PROGRAMA_MAX_CHARS` (8000 chars) to prevent event schedules from being severed.

#### B. Chunk Selection & Context Assembly
- **`seleccionar_chunks(items: list[dict], budget_chars: int, umbral: float = RAG_UMBRAL_SIMILITUD, min_oficiales: int = RAG_MIN_OFICIALES_SIN_UMBRAL) -> list[dict]`**:
  Quota-based selection prioritizing official sources (`web_localidad`, `web_municipio`, `rrss_*`) over search results (`busqueda_web`). Official chunks with `score >= umbral` enter first. If no official chunk passes the threshold, includes top `min_oficiales`. Web search chunks only fill remaining budget.
- **`ensamblar_contexto(seleccion: list[dict]) -> str`**:
  Groups selected chunks by source in order of priority (non-calendar official sources first, calendar sources last) with source headers (`===== FUENTE: ... =====`) and URLs.

#### C. Vector Similarity & Embeddings Processor
- **`AsyncRAGProcessor` class**:
  - `cosine_similarity(v1, v2) -> float`: Calculates dot product over vector magnitudes.
  - `get_embeddings_batch(session, texts: list[str]) -> list`: Sends batch of texts to LM Studio `/v1/embeddings` (`LMSTUDIO_EMBEDDING_MODEL`), returning list of float vectors.
  - `saturate_context_docs(documentos: list[dict], query: str) -> tuple[str, set]`:
    Chunks all input documents, requests query embedding, requests chunk embeddings in batches of `RAG_EMBEDDING_BATCH_SIZE` (50), computes cosine similarity, calls `seleccionar_chunks` with `self.context_limit_chars` (~78,000 chars), and returns assembled context string + set of present sources.

#### D. Post-LLM Validation
- **`_validar_fecha(fecha_str: str, anno: int, es_fecha_fin: bool = False, fecha_inicio_str: str | None = None) -> bool`**:
  Verifies date string format `YYYY-MM-DD`. Validates that year equals `anno`. Special case for cross-year festivals: allows `fecha_fin` in `anno + 1` if `fecha_inicio` is in December of `anno`.
- **`_normalizar_nombre(nombre: str) -> str`**: Lowercases, strips punctuation and spaces.
- **`_deduplicar_fiestas(fiestas: list[dict]) -> list[dict]`**: Deduplicates by key `f"{nombre_norm}_{fecha_inicio}"`.
- **`_validar_fuentes_fiesta(f: dict, nombre: str, fuentes_contexto: set | None)`**: Verifies sources declared by LLM against `fuentes_contexto`. If no official source remains, sets `solo_fuentes_no_oficiales = True` and forces `confianza = "baja"`.
- **`validar_fiestas(fiestas_raw: list[dict], localidad: dict, anno: int, fecha_patron=None, fuentes_contexto: set | None = None) -> list[dict]`**:
  Applies required fields check, place ID match check, date validation, `sanear_fiesta`, `evaluar_fiesta`, source validation, slug generation, and deduplication.

#### E. LLM Communication
- **`LLM_SEMAPHORE = asyncio.Semaphore(1)`**: Global lock ensuring only 1 active LLM chat request at a time to protect local VRAM.
- **`ContextOverflowError(Exception)`**: Raised when LM Studio returns status 400 due to context length overflow (`n_keep` / `context length`).
- **`_parse_json_llm(content: str) -> dict | None`**: Strips markdown formatting (` ```json `), fixes trailing commas before `]` or `}`, and parses JSON.
- **`llm_chat_json(system_prompt, user_prompt, max_tokens) -> dict | None`**: Makes POST request to `LMSTUDIO_CHAT_URL`.
- **`analyze_festivals_for_locality(...)`**: Single-pass entry point that builds the monolithic system prompt, translates text, runs adaptive retry loop (1.0, 0.7, 0.5 context factor), calls `llm_chat_json`, and runs `validar_fiestas`.

---

## 3. Analysis of Current RAG Execution Flaws

Currently, RAG execution in `text_analyzer.py` is single-pass:
1. `saturate_context_docs` vectorizes all document chunks against a broad general query (`"fiestas, festividades en X..."`) and packs up to ~78,000 characters (~30,000 tokens) into a single context block.
2. `analyze_festivals_for_locality` sends this full context block to the LLM in a single request, instructing it to discover all festivals AND output complete day-by-day event programs for all days of every festival.

### Critical Problems:
1. **Context & Token Bloat**: Sending ~30,000 tokens of raw text causes frequent context overflow in LM Studio (`ContextOverflowError`) or forces heavy truncation (0.7 / 0.5 factors).
2. **LLM Output Truncation & Omissions**: Expecting the LLM to output massive JSON structures containing full event schedules for multiple festivals in a single generation leads to JSON truncation or missing festivals.
3. **Retrieval Dilution for Daily Schedules**: General vector search queries ("fiestas en X") rank general introductory text high, but miss specific daily schedule chunks (e.g. "Programa del 15 de agosto").

---

## 4. Discovery Pass Implementation Design

### 4.1 Objective & Requirements
- Query documents for general festival information in the locality.
- Select top 10–15 chunks (~5.8K tokens / ~15,000 characters).
- Prompt the LLM to return a lightweight JSON list of discovered festivals (metadata only: name, start/end dates, size, description).

### 4.2 Modular Vector Indexing Optimization
To avoid re-vectorizing document chunks multiple times during Discovery and Enrichment, document chunks and their vector embeddings must be computed **once** per locality.

Data structure for indexed document chunks:
```python
IndexedChunk = dict{
    "chunk": str,
    "fuente": str,
    "url": str,
    "es_calendario": bool,
    "prioridad": int,
    "embedding": list[float]  # Precomputed vector embedding
}
```

### 4.3 Proposed Functions for Discovery Pass

#### Signature 1: `prepare_document_chunks_and_embeddings`
```python
async def index_document_chunks(
    rag_processor: AsyncRAGProcessor,
    documentos: list[dict]
) -> list[dict]:
    """
    Chunks documents and computes vector embeddings for all chunks in batch.
    Returns a list of indexed chunk dictionaries with precomputed embeddings.
    """
```

#### Signature 2: `retrieve_top_chunks`
```python
async def retrieve_top_chunks(
    rag_processor: AsyncRAGProcessor,
    indexed_chunks: list[dict],
    query: str,
    max_chunks: int = 15,
    max_chars: int = 15000,
    umbral: float = RAG_UMBRAL_SIMILITUD,
) -> tuple[str, set]:
    """
    Retrieves top N chunks matching query based on cosine similarity and source priority.
    Limits output to max_chunks (e.g. 10-15 chunks) and max_chars (e.g. ~15,000 chars ~5.8K tokens).
    Returns (assembled_context, fuentes_presentes).
    """
```

#### Signature 3: `discover_festivals_for_locality`
```python
async def discover_festivals_for_locality(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor,
    fecha_patron: date | None = None,
) -> list[dict]:
    """
    Executes the Discovery Pass:
    1. Runs general query: "fiestas, festividades, programas de fiestas y ferias en {municipio} para {localidad} en {anno}"
    2. Retrieves top 10-15 chunks (~5.8K tokens / ~15,000 chars).
    3. Calls LLM with Discovery Prompt (metadata only, no detailed programa).
    4. Runs discovery-level validation (validar_fiestas_discovery).
    """
```

### 4.4 Discovery System Prompt & Schema
```python
DISCOVERY_SYSTEM_PROMPT = f"""Eres un API estricta especializada en identificar y catalogar las fiestas locales en España.
CONTEXTO: Municipio {municipio['nombre']} ({municipio.get('provincia', 'España')}), Localidad: {localidad['nombre']}.

{CRITERIO_FIESTAS}

{JERARQUIA_FUENTES}

OBJETIVO CRÍTICO:
{regla_exclusividad}
AÑO: {anno}. Identifica la lista de fiestas que se celebran en {anno}.

Devuelve SOLO JSON estricto con esta estructura (NO incluyas el programa detallado de actos en este paso):
{{
  "fiestas": [
    {{
      "id": "slug-unico",
      "lugar_id": "{localidad['id']}",
      "nombre": "Nombre de la Fiesta",
      "fecha_inicio": "YYYY-MM-DD",
      "fecha_fin": "YYYY-MM-DD",
      "tamano": "pequeña" o "grande",
      "descripcion": "Breve descripción general de la celebración",
      "confianza": "alta", "media" o "baja",
      "fuentes": ["web_municipio", "busqueda_web"],
      "solo_fuentes_no_oficiales": false
    }}
  ]
}}"""
```

---

## 5. Enrichment Pass Implementation Design

### 5.1 Objective & Requirements
- Iterate through each festival discovered in the Discovery Pass.
- For each day in the festival date range (`fecha_inicio` to `fecha_fin`), query vector embeddings explicitly for that specific day: `"{nombre_fiesta} {fecha_dia} programa actos"`.
- Select top 1–3 chunks per day (~1.5K–3K chars per day).
- Combine day chunks for the festival, deduplicate overlapping chunks, and prompt the LLM to construct the detailed `programa` array.

### 5.2 Helper Functions & Logic

#### Signature 1: `generate_daily_queries`
```python
def generate_daily_queries(
    nombre_fiesta: str,
    fecha_inicio_str: str,
    fecha_fin_str: str,
    localidad_nombre: str,
    anno: int,
) -> list[dict]:
    """
    Generates day-by-day query objects for a festival across its date range.
    Returns list of dicts:
    [
      {
        "dia_num": 1,
        "fecha_str": "2026-08-15",
        "fecha_date": date(2026, 8, 15),
        "query": "Fiestas de San Roque 2026-08-15 15 de agosto programa actos eventos Fiestas"
      },
      ...
    ]
    Handles edge cases: cross-month ranges, leap years (Feb 29), cross-year ranges (Dec 30 to Jan 2).
    """
```

#### Signature 2: `retrieve_chunks_for_festival_days`
```python
async def retrieve_chunks_for_festival_days(
    rag_processor: AsyncRAGProcessor,
    indexed_chunks: list[dict],
    daily_queries: list[dict],
    chunks_per_day: int = 3,
    max_total_chars: int = 25000,
) -> tuple[str, set]:
    """
    For each daily query, calculates similarity against pre-indexed chunks.
    Selects top 1-3 chunks per day. Deduplicates chunks selected across multiple days.
    Assembles combined context string and set of present sources.
    """
```

#### Signature 3: `enrich_festival_program`
```python
async def enrich_festival_program(
    municipio: dict,
    localidad: dict,
    fiesta: dict,
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor,
) -> dict:
    """
    Executes Enrichment Pass for a single discovered festival:
    1. Generates daily queries for the date range of `fiesta`.
    2. Retrieves top 1-3 chunks per day from pre-indexed chunks.
    3. Prompts LLM with Day-Enrichment prompt to output JSON with detailed `programa`.
    4. Merges `programa` into `fiesta` and runs post-LLM validation.
    """
```

#### Signature 4: `enrich_all_festivals`
```python
async def enrich_all_festivals(
    municipio: dict,
    localidad: dict,
    fiestas_discovered: list[dict],
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor,
) -> list[dict]:
    """
    Iterates through all discovered festivals, enriching each sequentially with daily programs.
    """
```

### 5.3 Enrichment System Prompt & Schema
```python
ENRICHMENT_SYSTEM_PROMPT = f"""Eres un API estricta especializada en estructurar el PROGRAMA DE ACTOS Y EVENTOS de una fiesta local en España.
CONTEXTO: Municipio {municipio['nombre']}, Localidad: {localidad['nombre']}.
FIESTA A ENRICHES: "{fiesta['nombre']}" ({fiesta['fecha_inicio']} a {fiesta['fecha_fin']}).

REGLAS DE PROGRAMA DE ACTOS:
1. Extrae todos los actos y eventos mencionados en el texto para los días comprendidos entre {fiesta['fecha_inicio']} y {fiesta['fecha_fin']}.
2. Organiza los actos día por día. "dia" es 1 para {fiesta['fecha_inicio']}, 2 para el siguiente día, etc.
3. Para cada acto, indica la hora si está disponible (formato HH:MM, ej. "12:00", "23:30"), o "" si no especifica hora.
4. Traduce descripciones al castellano.

Devuelve SOLO JSON estricto con esta estructura:
{{
  "programa": [
    {{
      "dia": 1,
      "fecha": "YYYY-MM-DD",
      "eventos": [
        {{ "hora": "HH:MM", "descripcion": "Descripción del acto o evento" }}
      ]
    }}
  ]
}}"""
```

---

## 6. Edge Case Handling Strategy

1. **Cross-Month Date Ranges**:
   - `generate_daily_queries` uses `datetime.strptime` and `timedelta(days=1)`. Python's `datetime` module automatically increments months and years correctly (e.g. Aug 30 -> Aug 31 -> Sep 1).
2. **Leap Years (Feb 29)**:
   - Python's `datetime.date(2026, 2, 29)` raises `ValueError`. `generate_daily_queries` catches `ValueError` and falls back to `date(anno, 2, 28)`.
3. **Cross-Year Date Ranges (Dec 30 to Jan 2)**:
   - Dec 30 of `anno` to Jan 2 of `anno + 1`. `_validar_fecha` already permits `fecha_fin` in `anno + 1` when `fecha_inicio` is in December of `anno`. `generate_daily_queries` iterates through years seamlessly.
4. **Festivals with No Specific Day Program Found**:
   - If vector search for daily chunks returns low similarity or no schedule text, the LLM enrichment returns `"programa": []`. The festival metadata remains valid.
5. **Token Count Control**:
   - Discovery Pass: ~15,000 chars context (~5.8K tokens). Prompt total ~7K tokens.
   - Enrichment Pass: 1–3 chunks per day (e.g. 5-day festival -> max ~15 chunks, ~15,000 chars / ~5.8K tokens). Prompt total < 10K tokens. Both remain well under 12K–32K limits.

---

## 7. Pipeline Integration Plan (`main.py`)

In `main.py`, update `process_locality`:

```python
# 1. Pre-index document chunks and compute vector embeddings once
indexed_chunks = await index_document_chunks(rag_processor, documentos)

# 2. Run Discovery Pass
fiestas_descubiertas = await discover_festivals_for_locality(
    municipio, localidad, documentos, indexed_chunks, anno, rag_processor, fecha_patron
)

# 3. Run Enrichment Pass for each discovered festival
fiestas_enriquecidas = await enrich_all_festivals(
    municipio, localidad, fiestas_descubiertas, indexed_chunks, anno, rag_processor
)

# 4. Final integration of Patron Saint estimation if not covered
fiestas_finales = integrar_patron(fiestas_enriquecidas, patron, anno, localidad)
```

---

## 8. Verification Strategy & Isolated Test Plan

As required by project instructions, implementation will be verified using isolated standalone test scripts:

1. **`test_daily_query_generation.py`**:
   - Verifies query generation across multi-day ranges, cross-month boundaries (e.g. Aug 28 to Sep 2), leap year edge cases, and cross-year boundaries (Dec 30 to Jan 2).
2. **`test_multipass_rag_tokens.py`**:
   - Simulates Discovery and Enrichment passes against mocked document chunks. Calculates token lengths to verify requests stay well under 12K tokens (well below the 32K context limit).

---

## 9. Conclusion

The design outlined in this report provides a clean, robust, multi-pass RAG framework that guarantees scalability, resolves context overflow issues in LM Studio, and enriches festival data day by day without missing events or truncating JSON output.

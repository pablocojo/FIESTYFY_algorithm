# Project: Fiestyfy Multi-Pass RAG Architecture Implementation

## Architecture
The Fiestyfy Phase 2 Festival Extraction pipeline extracts, structures, enriches, and validates festival data across Spanish localities.
The single-pass RAG approach (which stuffed ~30K tokens of text into a single LLM prompt) caused LM Studio `ContextOverflowError` and JSON truncation.
The Multi-Pass RAG Architecture splits extraction into two sequential phases:

```
[ Localidad Documents & Web Content ]
                │
                ▼
      ┌──────────────────┐
      │  Vector Indexing │  (Compute embeddings once per locality)
      └─────────┬────────┘
                │
                ▼
      ┌──────────────────┐
      │  Discovery Pass  │  (Top 10-15 chunks, ~5.8K tokens)
      └─────────┬────────┘  --> LLM extracts JSON list of festivals:
                │               {nombre, fecha_inicio, fecha_fin, tamano, ...}
                ▼
      ┌──────────────────┐
      │ Enrichment Pass  │  (Day-by-day query: "{nombre_fiesta} {fecha_dia} programa actos")
      └─────────┬────────┘  --> Select 1-3 chunks per day
                │           --> Send combined day chunks to LLM to enrich basic JSON
                ▼               with detailed event program (`programa`)
      ┌──────────────────┐
      │ Post-LLM & Patron│  (Validate schema, handle patrons, assign lat/lng, R6 metrics)
      └──────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1.1 Discovery Pass | Query documents for general festivals, top 10-15 chunks (~5.8K tokens), LLM extracts basic festival list | M1 | ORIGINAL_REQUEST §R1 |
| 2 | R1.2 Day-by-Day Query Construction | Generate queries per day (`"{nombre_fiesta} {fecha_dia} programa actos"`) handling intra-month, cross-month, cross-year, and leap year date ranges | M1 | ORIGINAL_REQUEST §R1 |
| 3 | R1.3 Enrichment Pass | Select 1-3 chunks per day, aggregate combined day chunks, send to LLM to enrich festival with detailed program | M1 | ORIGINAL_REQUEST §R1 |
| 4 | R2.1 Pipeline Integration | Update `process_locality` in `main.py` to use `analyze_festivals_multipass`, orchestrating Discovery -> Enrichment -> Post-LLM validation | M2 | ORIGINAL_REQUEST §R2 |
| 5 | R2.2 Exception & Edge Handling | Handle zero documents, zero discovered festivals, LLM timeouts, and VRAM safety with fallback mechanisms | M2 | ORIGINAL_REQUEST §R2 |
| 6 | Verification Test 1 | Isolated Python test script `test_enrichment_query_generation.py` for multi-day, cross-month, cross-year, and leap year date range queries | M3 | ORIGINAL_REQUEST §Acceptance Criteria |
| 7 | Verification Test 2 | Isolated Python test script `test_rag_token_limit_simulation.py` simulating RAG token counts under 32K context (under 12K tokens) | M3 | ORIGINAL_REQUEST §Acceptance Criteria |
| 8 | Quality & Integrity Audit | Full Reviewer, Challenger, and Forensic Auditor verification with zero placeholders and passing build/tests | M4 | System Instructions |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Multi-Pass RAG Engine | Implement `analyze_festivals_multipass`, Discovery Pass, date range query expansion, and Enrichment Pass in `llm_processor/text_analyzer.py` | None | DONE |
| M2 | Pipeline Integration | Update `process_locality` in `main.py` to invoke multi-pass RAG logic and handle post-LLM validation & metrics | M1 | DONE |
| M3 | Isolated Verification Test Suite | Implement `tests_fase2/test_enrichment_query_generation.py` and `tests_fase2/test_rag_token_limit_simulation.py` | M1, M2 | DONE |
| M4 | Gate & Forensic Audit | Reviewer verification, Challenger empirical test execution, and Forensic Auditor integrity verification | M1, M2, M3 | DONE |

## Interface Contracts
### `llm_processor/text_analyzer.py`

#### `generar_consultas_enriquecimiento`
```python
def generar_consultas_enriquecimiento(nombre_fiesta: str, fecha_inicio: str, fecha_fin: str, max_dias: int = 30) -> list[tuple[str, str]]:
    """
    Generates a list of tuples (fecha_str, query_str) for each day of a festival.
    Format: query_str = f"{nombre_fiesta} {fecha_str} programa actos"
    Handles cross-month, cross-year, leap-year, and caps at max_dias.
    """
```

#### `analyze_festivals_multipass`
```python
async def analyze_festivals_multipass(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    anno: int,
    fecha_patron: str | None = None,
    rag_processor: AsyncRAGProcessor | None = None,
    logger: logging.Logger | None = None
) -> list[dict]:
    """
    Executes Multi-Pass RAG extraction:
    1. Pre-indexes document chunks and calculates embeddings.
    2. Discovery Pass: retrieves top 10-15 chunks (~5.8K tokens) and calls LLM to discover basic festival list.
    3. Enrichment Pass: for each discovered festival, queries daily chunks (1-3 per day), aggregates them, and calls LLM to enrich with detailed event program (`programa`).
    4. Performs post-LLM validation and patron integration.
    """
```

### `main.py`

#### `process_locality`
```python
async def process_locality(
    localidad: dict,
    municipio: dict,
    anno: int,
    rag_processor: AsyncRAGProcessor,
    rrss_client,
    logger: logging.Logger,
    docs_municipio_cache: dict | None = None
) -> list[dict]:
    """
    Updates internal flow: calls document acquisition cascade, then delegates festival extraction to `analyze_festivals_multipass`.
    """
```

## Code Layout
- `llm_processor/text_analyzer.py`: Multi-Pass RAG implementation (`generar_consultas_enriquecimiento`, `analyze_festivals_multipass`, `discover_festivals_for_locality`, `enrich_festival_program`).
- `main.py`: `process_locality` pipeline integration.
- `tests_fase2/test_enrichment_query_generation.py`: Test 1 for date range query construction.
- `tests_fase2/test_rag_token_limit_simulation.py`: Test 2 for RAG token count simulation.
- `config.py`: System RAG configuration constants (`RAG_MAX_TOKENS`, `RAG_CHARS_PER_TOKEN`, `RAG_CHUNK_SIZE`, etc.).

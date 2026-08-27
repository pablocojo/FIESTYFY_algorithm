# Project: Fiestyfy Algorithm RAG Pipeline Fixes

## Working Directory
`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`

## Architecture
The RAG pipeline extracts local festival programs for Spanish municipalities and entities.
- `main.py`: Entry point orchestrating data loading, entity separation (capital vs sister localities), web searches, context building, and analyzer invocations.
- `llm_processor/text_analyzer.py`: Chunk indexing, vector store creation, similarity search, geographic filtering (`filtrar_chunks_por_localidad`), chunk budget selection (`seleccionar_chunks`), context assembly (`ensamblar_contexto`), and LLM extraction functions (`discover_festivals_for_locality`, `enrich_festival_program`, `saturate_context_docs`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1: Geographic Filtering Order | Move `filtrar_chunks_por_localidad` out of `seleccionar_chunks` and apply it AFTER cosine similarity calculation in all retrieval pipelines (`discover_festivals_for_locality`, `retrieve_discovery_context`, `enrich_festival_program`, `saturate_context_docs`). | M1 | ORIGINAL_REQUEST §R1 |
| 2 | R2: Capital Exclusion in Sister Localities | Modify `main.py` line 317 to exclude municipality capital (`es_capital: true`) when building `nombres_hermanas` list for sister localities. | M2 | ORIGINAL_REQUEST §R2 |
| 3 | R3: Contextual Embeddings Target Text | Modify `index_document_chunks` in `llm_processor/text_analyzer.py` line 1106 to compute embeddings on raw `chunk` text rather than `chunk_contextualizado`. | M3 | ORIGINAL_REQUEST §R3 |
| 4 | R4: E2E Verification on Sample Municipality | Run extraction test on sample municipality Amurrio (`01002000000`) and verify output JSON contains non-estimated festivals (`es_estimada: false`) with populated `programa` arrays. | M4 | ORIGINAL_REQUEST §R4 |

## Code Layout
- `llm_processor/text_analyzer.py`: Owned by M1 & M3
- `main.py`: Owned by M2
- Verification scripts / CLI execution: Owned by M4

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: R1 Fix (Geographic Filtering Order) | `llm_processor/text_analyzer.py` (decouple `filtrar_chunks_por_localidad` from `seleccionar_chunks`, apply after similarity score) | none | DONE |
| 2 | M2: R2 Fix (Capital Exclusion) | `main.py` (exclude `es_capital: true` from `nombres_hermanas`) | none | DONE |
| 3 | M3: R3 Fix (Raw Chunk Embeddings) | `llm_processor/text_analyzer.py` (line 1106 compute embeddings on `chunk` instead of `chunk_contextualizado`) | M1 | DONE |
| 4 | M4: R4 Verification (Amurrio Test) | Run test extraction on Amurrio, verify `fiestas_espana.json` output | M1, M2, M3 | IN_PROGRESS |

## Interface Contracts
- `seleccionar_chunks(chunks_con_score: List[Dict], max_tokens: int = 14000) -> List[Dict]`:
  Pure budget-packing helper. Must NOT invoke `filtrar_chunks_por_localidad` internally.
- `filtrar_chunks_por_localidad(chunks: List[Dict], localidad: Dict, nombres_hermanas: List[str]) -> List[Dict]`:
  Adjusts chunk `score` based on geographic relevance tags (+0.15 DIRECTA, -0.10 GENERAL, excludes HERMANA). Must be called after cosine similarity scoring.
- `index_document_chunks(doc_chunks: List[Dict]) -> Chroma`:
  Computes vector embeddings batch using `i["chunk"]`. Stores `chunk_contextualizado` in document metadata for LLM prompt context assembly.

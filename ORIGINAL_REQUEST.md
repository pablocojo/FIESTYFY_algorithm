# Original User Request

## 2026-08-08T14:59:00Z

Fix the three critical bugs in the RAG pipeline of the Fiestyfy extraction algorithm to ensure local festival programs are correctly retrieved and not discarded by the geographic filter.

Working directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas
Integrity mode: development

## Requirements

### R1. Fix `seleccionar_chunks` Geographic Filtering Order
In `llm_processor/text_analyzer.py`, ensure the geographic filter (`filtrar_chunks_por_localidad`) is applied **after** calculating the similarity scores, not before. The filter should only be applied in `retrieve_discovery_context` and `discover_festivals_for_locality`, removing it from inside `seleccionar_chunks`.

### R2. Fix `nombres_hermanas` Capital Exclusion
In `main.py`, modify the generation of the `nombres_hermanas` list so that the capital of the municipality is explicitly excluded from the list of sister localities. 

### R3. Fix Contextual Embeddings
In `llm_processor/text_analyzer.py` (`index_document_chunks`), calculate the embeddings using the raw `chunk` text rather than the `chunk_contextualizado` (which includes administrative headers that distort the vector space). The LLM should still receive the headers via `ensamblar_contexto`.

### R4. Verification
Run an extraction test (e.g. using `main.py` or a dedicated test script on a sample municipality like Amurrio) to verify that the LLM now correctly extracts festivals with their associated programs (i.e., `programa` is not an empty list).

## Acceptance Criteria

### Code Fixes
- [ ] `seleccionar_chunks` does not call `filtrar_chunks_por_localidad` internally.
- [ ] Chunks are scored before the geographic filter penalizes or boosts them.
- [ ] The `nombres_hermanas` list passed to the analyzer does not contain the name of the municipality capital.
- [ ] Embeddings are calculated on the `chunk` string, not `chunk_contextualizado`.

### Objective Verification
- [ ] A test execution runs successfully.
- [ ] The output JSON confirms that at least one non-estimated festival with a populated `programa` array is extracted.

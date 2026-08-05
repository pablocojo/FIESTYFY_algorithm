# Handoff Report: Pipeline Orchestration & Multi-Pass RAG Architecture Investigation

## 1. Observation
- **Pipeline Orchestrator File**: `main.py` lines 122-261 (`process_locality`).
  - Inputs: `localidad`, `municipio`, `anno`, `rag_processor`, `rrss_client`, `logger`, `docs_municipio_cache`.
  - Current RAG invocation (lines 240-249):
    ```python
    query_rag = (
        f"{terminos_rag} en {municipio['nombre']} "
        f"para la localidad de {localidad['nombre']} en el año {anno}"
    )
    contexto, fuentes_contexto = await rag_processor.saturate_context_docs(documentos, query_rag)
    fiestas = await analyze_festivals_for_locality(
        municipio, localidad, contexto, anno, fecha_patron, fuentes_contexto
    )
    ```
  - Outputs: `list[dict]` of validated festivals with patron integration and `lat`/`lng` coordinates assigned.
- **RAG & LLM Processor File**: `llm_processor/text_analyzer.py` lines 415-525 (`AsyncRAGProcessor`) and lines 797-913 (`analyze_festivals_for_locality`).
  - Single-pass chunking and selection retrieves up to `RAG_MAX_TOKENS = 6000` (~24,000 characters).
  - Single system prompt (`CRITERIO_FIESTAS`, `JERARQUIA_FUENTES`, `regla_exclusividad`) sends combined context to Qwen 2.5 7B via `llm_chat_json`.
- **Existing Test Suite**: `tests_fase2/test_fuentes_chunking.py`, `tests_fase2/test_validar_fiestas.py`, `tests_fase2/test_patron_finder.py`.

## 2. Logic Chain
1. **Observation 1**: `process_locality` in `main.py` performs document collection and immediately passes all documents to a single RAG query (`query_rag`) and a single LLM call (`analyze_festivals_for_locality`).
2. **Observation 2**: Requirements R1 and R2 specify replacing this single-pass sequence with a two-pass RAG mechanism (Discovery Pass for general festival JSON list, followed by Enrichment Pass for day-by-day program of events).
3. **Logic Step A**: Shifting multi-pass orchestration into `text_analyzer.py` via a main function `analyze_festivals_multipass(...)` encapsulates RAG chunk selection and LLM prompt generation while keeping `process_locality` clean and backward-compatible.
4. **Logic Step B**: In `process_locality`, replacing `rag_processor.saturate_context_docs` and `analyze_festivals_for_locality` with `analyze_festivals_multipass` ensures that `process_locality` seamlessly receives the enriched festival list without altering its inputs, state saving (`StateManager`), patron handling (`obtener_patron`), or return type (`list[dict]`).
5. **Logic Step C**: Safeguards for edge cases (0 documents, 0 discovered festivals, invalid date ranges, duration exceeding 15 days, LLM timeouts) prevent pipeline breakdown during day-by-day enrichment iterations.

## 3. Caveats
- FastText model (`lid.176.ftz`) and Apertium/Opus-MT translation tools in `text_analyzer.py` require local model dependencies if multi-language translation is triggered.
- LM Studio server must be running with embedding model (`text-embedding-nomic-embed-text-v1.5`) and LLM (`qwen2.5-7b-instruct`).

## 4. Conclusion
The pipeline orchestration around `process_locality` in `main.py` is ready for Multi-Pass RAG integration. By encapsulating Discovery and Enrichment passes inside `text_analyzer.py` (via `analyze_festivals_multipass`), `process_locality` can be updated cleanly in a single locus without breaking state management, patron finder, or R6 execution metrics logging.

## 5. Verification Method
- **Command**: Run `pytest tests_fase2/test_fuentes_chunking.py tests_fase2/test_validar_fiestas.py` to verify baseline RAG chunking and validation rules.
- **Verification Scripts**:
  - Run query construction test script for enrichment pass across date ranges (including cross-month boundaries).
  - Run mock RAG multi-pass token budget simulation script to verify token count stays well under 32K context limit (under 12K tokens).
- **Files to Inspect**:
  - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_2\analysis.md`
  - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_2\handoff.md`

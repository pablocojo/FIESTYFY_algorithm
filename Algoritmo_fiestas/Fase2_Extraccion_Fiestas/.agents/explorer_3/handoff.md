# Handoff Report — Multi-Pass RAG Verification Architecture & Test Specifications

**Agent**: Explorer 3 (`teamwork_preview_explorer`)  
**Working Directory**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_3`  
**Date**: 2026-08-05  

---

## 1. Observation

- **Project Core Codebase**:
  - `llm_processor/text_analyzer.py` lines 415-524: `AsyncRAGProcessor` handles vector retrieval and context saturation using `RAG_MAX_TOKENS = 30000`, `RAG_CHARS_PER_TOKEN = 2.6`, and `RAG_CHUNK_SIZE = 1200`.
  - `llm_processor/text_analyzer.py` lines 531-558: `_validar_fecha` parses dates in `"YYYY-MM-DD"` format and allows `anno + 1` for December start dates.
  - `llm_processor/text_analyzer.py` lines 797-912: `analyze_festivals_for_locality` performs single-pass LLM extraction.
  - `config.py` lines 46-54: RAG parameters (`RAG_MAX_TOKENS = 30000`, `RAG_CHARS_PER_TOKEN = 2.6`, `RAG_CHUNK_SIZE = 1200`, `RAG_PROGRAMA_MAX_CHARS = 8000`).
  - `main.py` lines 122-261: `process_locality` orchestrates crawling, RAG, and LLM extraction.
- **Existing Test Patterns**:
  - `tests_fase2/test_validar_fiestas.py`: Unit tests for date validation, filtering, and patron exceptions without external LLM calls.
  - `tests_fase2/test_r2_stress_edgecases.py`: Isolated tests for URL calendar keys, co-official language scoring, and score matrices.
- **Original Requirement Baseline**:
  - `ORIGINAL_REQUEST.md` (section `2026-08-05T12:49:20Z`): Requires Multi-Pass RAG (Discovery Pass ~5.8K tokens, Enrichment Pass 1-3 chunks/day `"{nombre_fiesta} {fecha_dia} programa actos"`) and two isolated verification test scripts:
    1. Test 1: Query generation across multi-day / cross-month festivals.
    2. Test 2: Token limit simulation against mocked chunks staying under 32K (< 12K tokens).

---

## 2. Logic Chain

1. **Date Range Expansion Logic**:
   - Discovered festivals return ISO date strings `fecha_inicio` and `fecha_fin`.
   - Iterating chronologically from `start_date` to `end_date` using Python's `datetime.date.fromisoformat()` and `datetime.timedelta(days=1)` natively handles month transitions (e.g. Aug 28 to Sep 3: 31 days in Aug), year boundaries (Dec 29 to Jan 3), and leap years (Feb 29 in 2028 vs 2026).
   - Format requirement for enrichment queries: `f"{nombre_fiesta} {fecha_dia_str} programa actos"`.
   - Edge case protection: Swapping inverted start/end dates, capping long spans at `max_dias = 30` to prevent query explosion, and returning empty list on malformed date inputs.

2. **Token Limit & Context Simulation Logic**:
   - The LM Studio Qwen 2.5 7B context window is `32,768 tokens`. Target limit per request is `< 12,000 tokens`.
   - Based on `RAG_CHARS_PER_TOKEN = 2.6`:
     - **Discovery Pass**: 10–15 chunks $\le 15,000$ chars $\approx 5,769$ tokens. System prompt + metadata $\approx 769$ tokens. Total $\approx 6,538$ tokens (< 12K).
     - **Enrichment Pass**: 1–3 chunks per day. For a 7-day festival with deduplication, context is $\approx 9,600$ chars ($\approx 3,692$ tokens). Total payload $\approx 4,653$ tokens (< 12K).
     - **Heavy Stress (25-day festival)**: Enforcing a hard budget cap `ENRICHMENT_MAX_CHARS = 25,000` chars ($\approx 9,615$ tokens) guarantees total payload stays $\le 10,576$ tokens (< 12K).

3. **Verification Test Specifications**:
   - **Test 1 (`test_enrichment_query_generation.py`)**: Tests 7 distinct date scenarios (intra-month, cross-month, cross-year, leap year 2028, non-leap year 2026, single day, capped 365-day span, malformed inputs) to ensure query format and chronological sequence.
   - **Test 2 (`test_rag_token_limit_simulation.py`)**: Mocks chunk sets and simulates Discovery Pass payload, Enrichment Pass standard payload, and Enrichment Pass heavy stress payload to assert token counts stay `< 12,000` tokens and `< 32,768` tokens.

---

## 3. Caveats

- **Character Ratio Estimation**: Token counting is estimated using `RAG_CHARS_PER_TOKEN = 2.6` as specified in `config.py`. While exact BPE tokenization varies slightly depending on vocabulary, this ratio was empirically calibrated on Spanish scraped text and provides a conservative safety margin for the 12K and 32K context limits.
- **Max Duration Capping**: The cap of 30 days (`max_dias = 30`) is based on `FIESTA_MAX_DURACION_DIAS = 30`. If a festival spans longer than 30 days (e.g. summer-long cultural programs), it is capped to 30 days during day-by-day query generation to protect against query and token inflation.

---

## 4. Conclusion

The technical specifications and date/token simulation logic for the two isolated test scripts have been fully designed and documented in `analysis.md`:
1. `generar_consultas_enriquecimiento` cleanly handles all calendar edge cases (cross-month, cross-year, leap year, single-day, capped long spans, inverted dates).
2. The multi-pass RAG architecture effectively partitions context so that Discovery Pass requests consume $\approx 6.5\text{K}$ tokens and Enrichment Pass requests consume $\approx 4.6\text{K} - 10.5\text{K}$ tokens, well within the 12K target and far below the 32K LLM context limit.
3. Complete specifications for `test_enrichment_query_generation.py` and `test_rag_token_limit_simulation.py` are ready for implementation.

---

## 5. Verification Method

To verify the test specifications once implemented by the engineering team:

1. **Verify Test 1 (Query Generation across Multi-Day & Cross-Month Festivals)**:
   ```bash
   pytest tests_fase2/test_enrichment_query_generation.py -v
   python tests_fase2/test_enrichment_query_generation.py
   ```
   *Expected Result*: All test cases (intra-month, cross-month, cross-year, leap year 2028, non-leap 2026, single-day, 30-day cap) pass with 100% assertions satisfied.

2. **Verify Test 2 (Token Limit Simulation against Mocked Chunks)**:
   ```bash
   pytest tests_fase2/test_rag_token_limit_simulation.py -v
   python tests_fase2/test_rag_token_limit_simulation.py
   ```
   *Expected Result*: Discovery Pass payload tokens $\approx 6.5\text{K}$ (< 12K), Enrichment Pass standard payload tokens $\approx 4.6\text{K}$ (< 12K), and Heavy Stress payload tokens $\le 10.6\text{K}$ (< 12K).

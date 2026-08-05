# Dispatch Instructions for Worker 2

## Mission
Implement Milestones 1, 2, and 3 for Fiestyfy Multi-Pass RAG Architecture:
1. **Milestone 1**: In `llm_processor/text_analyzer.py`:
   - Implement `generar_consultas_enriquecimiento(nombre_fiesta: str, fecha_inicio: str, fecha_fin: str, max_dias: int = 30) -> list[tuple[str, str]]` handling intra-month, cross-month, cross-year (Dec->Jan), leap years (Feb 29 fallback to Feb 28 in non-leap years), single day, capping at max_dias=30, inverted dates, malformed inputs. Format per day: `f"{nombre_fiesta} {fecha_dia_str} programa actos"`.
   - Implement `analyze_festivals_multipass` and helper functions (`discover_festivals_for_locality`, `enrich_festival_program`, etc.):
     - **Discovery Pass**: Query top 10-15 chunks (~5.8K tokens), send to LLM to extract JSON list of festivals with name, start date, end date, size, etc.
     - **Enrichment Pass**: For each discovered festival, query 1-3 chunks per day, aggregate combined day chunks, send to LLM to enrich basic JSON with detailed `programa` of events.
     - Robust error handling, zero document handling, zero festival handling, LLM timeout & VRAM protection with fallback.

2. **Milestone 2**: In `main.py`:
   - Update `process_locality` to invoke `analyze_festivals_multipass` instead of single-pass RAG.
   - Maintain seamless compatibility with document crawling, patron integration (`obtener_patron`), coordinates assignment (`lat`/`lng`), state manager, and R6 execution metrics.

3. **Milestone 3**: Implement isolated verification test suite:
   - `tests_fase2/test_enrichment_query_generation.py`: Unit test verifying query generation across multi-day, cross-month, cross-year, leap year (2028 vs 2026), single day, 30-day cap, and malformed inputs.
   - `tests_fase2/test_rag_token_limit_simulation.py`: Unit test simulating multi-pass RAG logic against mocked chunk sets, verifying token counts stay well under 32K context limit (under 12K tokens per request).

4. **Testing & Verification**:
   - Run `pytest tests_fase2/` to ensure all tests pass 100%.
   - Ensure zero placeholders or incomplete implementations anywhere in code.

5. **Handoff**:
   - Write handoff report in `.agents/worker_2/handoff.md` and send message to parent orchestrator.

## Reference Documents
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md` (specifically section `2026-08-05T12:49:20Z`)
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\orchestrator\PROJECT.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_1\analysis.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_2\analysis.md`
- `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\explorer_3\analysis.md`

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## 2026-08-05T15:51:50Z
You are Worker 2 (teamwork_preview_worker). Your working directory is c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\worker_2.

Please complete Milestones 1, 2, and 3 for Fiestyfy Multi-Pass RAG Architecture Implementation:
1. Read DISPATCH.md in your working directory, ORIGINAL_REQUEST.md, PROJECT.md, and the explorer analysis reports.
2. Implement Milestone 1 in `llm_processor/text_analyzer.py`.
3. Implement Milestone 2 in `main.py`.
4. Implement Milestone 3 isolated test suite.
5. Run pytest test suite `pytest tests_fase2/` and verify that all tests pass 100%.
6. Write handoff report in `handoff.md` and send completion message to parent.


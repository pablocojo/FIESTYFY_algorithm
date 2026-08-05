# Dispatch Instructions

## 2026-08-05T12:49:20Z
Project Orchestrator for Fiestyfy Multi-Pass RAG Architecture Implementation.

Working directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas
Metadata directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\orchestrator

Please read the user requirements in:
c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\ORIGINAL_REQUEST.md (specifically the latest section starting at 2026-08-05T12:49:20Z).

Key requirements to execute:
1. R1. RAG Multi-Pass Implementation:
   - Discovery Pass in `text_analyzer.py`: Query documents for general festivals in locality, select top 10-15 chunks (~5.8K tokens), send to LLM to extract JSON list of festivals (name, start date, end date, size).
   - Enrichment Pass in `text_analyzer.py`: Iterate through discovered festivals and each day in their date range, query embeddings per day ("{nombre_fiesta} {fecha_dia} programa actos"), select 1-3 chunks per day, send combined day chunks to LLM to enrich with detailed event program.
2. R2. Pipeline Integration:
   - Update `process_locality` in `main.py` to use new multi-pass RAG logic before final post-LLM validation.
3. Verification & Testing:
   - Write isolated test script for multi-day and cross-month enrichment query construction.
   - Write isolated test script for token count simulation under 32K (under 12K tokens).
   - Ensure zero placeholders and all verification tests pass.

## 2026-08-05T15:51:17Z
Resume and complete the mission as Project Orchestrator (Successor) for Fiestyfy Multi-Pass RAG Architecture Implementation:
1. Inspect `.agents/orchestrator/plan.md` and `progress.md` to pick up execution state.
2. Check `.agents/worker_1/` and inspect `llm_processor/text_analyzer.py`, `main.py`, and test files (`tests_fase2/test_enrichment_query_generation.py`, `tests_fase2/test_rag_token_limit_simulation.py`).
3. Verify that all requirements from `ORIGINAL_REQUEST.md` (section 2026-08-05T12:49:20Z) are met:
   - R1: Two-pass RAG & LLM process (Discovery & Enrichment passes in `text_analyzer.py`)
   - R2: Pipeline integration in `main.py` (`process_locality`)
   - Acceptance Criteria & Verification: Isolated test for multi-day/cross-month enrichment query generation; isolated test for token limit simulation (<32K, <12K tokens).
4. Run full review and testing/verification. When all tests pass and requirements are fully met, report victory to the Sentinel.


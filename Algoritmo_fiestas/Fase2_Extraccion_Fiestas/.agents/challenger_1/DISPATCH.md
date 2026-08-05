# Dispatch Instructions for Challenger 1

## Mission
Empirically test and stress test the date range query generation and Multi-Pass RAG token limits.

## Focus Area
- Write empirical stress test generators and oracles for `generar_consultas_enriquecimiento` and date edge cases (cross-month, cross-year, leap years, inverted dates, 365-day spans, empty inputs, non-string inputs).
- Stress test token budgeting for Discovery Pass and Enrichment Pass under heavy chunk loads (e.g. 50 chunks, 100 chunks, 30-day festivals).

## Instructions
1. Inspect `llm_processor/text_analyzer.py` and existing tests in `tests_fase2/`.
2. Run pytest suite:
   ```bash
   pytest tests_fase2/ -v
   ```
3. Execute empirical stress tests verifying edge cases and bounds.
4. Report findings and verdict (`APPROVE` or `REQUEST_CHANGES`) in `.agents/challenger_1/handoff.md` and send a summary message to parent.

## 2026-08-05T15:55:00Z
You are Challenger 1 (teamwork_preview_challenger). Your working directory is c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\.agents\challenger_1.

Please empirically test and stress test date range query generation and Multi-Pass RAG token limits:
1. Read DISPATCH.md in your working directory, ORIGINAL_REQUEST.md (section 2026-08-05T12:49:20Z), PROJECT.md, and worker_2's handoff.
2. Inspect `llm_processor/text_analyzer.py` and `tests_fase2/`.
3. Run pytest test suite `pytest tests_fase2/ -v`.
4. Execute empirical stress test cases (extreme date ranges, leap years, inverted dates, malformed inputs, dict inputs, multi-chunk RAG simulation under heavy loads).
5. Write your handoff report in `.agents/challenger_1/handoff.md` with your explicit verdict (APPROVE or REQUEST_CHANGES) and send a completion message to parent.

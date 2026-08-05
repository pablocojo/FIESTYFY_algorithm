# Dispatch Instructions for Reviewer 2

## Mission
Review the Multi-Pass RAG Architecture integration in `main.py` and token budget safety across the pipeline.

## Files to Review
- `main.py` (`process_locality`)
- `llm_processor/text_analyzer.py`
- `tests_fase2/test_rag_token_limit_simulation.py`
- `tests_fase2/test_enrichment_query_generation.py`

## Instructions
1. Inspect `process_locality` in `main.py` to ensure seamless integration with document acquisition, patron search/integration (`obtener_patron`, `integrar_patron`), coordinate tagging (`lat`/`lng`), and R6 metrics calculation.
2. Verify token budgets: ensure Discovery Pass context is capped at ~5.8K tokens (~15,000 chars) and Enrichment Pass payload is capped at <10.5K tokens (~25,000 chars), remaining well below the 32K LLM context limit.
3. Run test execution:
   ```bash
   pytest tests_fase2/ -v
   ```
4. Deliver your verdict (`APPROVE` or `REQUEST_CHANGES`) in `.agents/reviewer_2/handoff.md` and send a summary message to parent.

## 2026-08-05T13:55:12Z
Review the Multi-Pass RAG Architecture integration and token budgets:
1. Read DISPATCH.md, ORIGINAL_REQUEST.md (section 2026-08-05T12:49:20Z), PROJECT.md, and worker_2's handoff report.
2. Inspect `main.py` (`process_locality`) and token budgeting caps in `llm_processor/text_analyzer.py`.
3. Run pytest test suite `pytest tests_fase2/ -v`.
4. Verify Multi-Pass RAG integration, token budgets (<12K tokens per request), patron resolution, patron integration, coordinates tagging, and metrics logging.
5. Write handoff report in `.agents/reviewer_2/handoff.md` with verdict and send message to parent.

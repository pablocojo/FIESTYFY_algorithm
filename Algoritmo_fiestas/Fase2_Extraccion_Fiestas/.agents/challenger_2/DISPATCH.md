# Dispatch Instructions for Challenger 2

## Mission
Empirically stress test pipeline integration in `main.py` and regression safety across existing Phase 2 tests.

## Focus Area
- Verify that `process_locality` in `main.py` handles edge cases (0 documents retrieved, 0 festivals discovered by LLM, LLM timeouts, malformed JSON responses, patron integration failures).
- Verify zero regressions across the entire Fase 2 test suite (`pytest tests_fase2/`).

## Instructions
1. Run full test suite:
   ```bash
   pytest tests_fase2/ -v
   ```
2. Verify all test files in `tests_fase2/` pass 100%.
3. Stress test error paths in `process_locality` and `analyze_festivals_multipass`.
4. Report findings and verdict (`APPROVE` or `REQUEST_CHANGES`) in `.agents/challenger_2/handoff.md` and send a summary message to parent.

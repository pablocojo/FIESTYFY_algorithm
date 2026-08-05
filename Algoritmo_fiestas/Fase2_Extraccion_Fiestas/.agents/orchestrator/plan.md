# Plan — Fiestyfy Multi-Pass RAG Architecture Implementation

## Objective
Implement a multi-pass RAG architecture in `text_analyzer.py` and `main.py` to resolve context overflow issues and improve festival extraction quality by discovering festivals first and enriching them day-by-day.

## Milestones
1. **Survey & Architecture Mapping**:
   - Spawn 3 parallel Explorers to inspect `text_analyzer.py`, `main.py`, vector store / embedding usage, and existing pipeline structures.
   - Enumerate exact interfaces, data structures, and integration points.
   - Build `PROJECT.md`.

2. **Milestone 1: RAG Multi-Pass Engine (`text_analyzer.py`)**:
   - Discovery Pass: Query documents for general festivals in locality, select top 10-15 chunks (~5.8K tokens), send to LLM to extract JSON list of festivals (name, start date, end date, size).
   - Enrichment Pass: Iterate through discovered festivals and each day in their date range, query embeddings per day (`"{nombre_fiesta} {fecha_dia} programa actos"`), select 1-3 chunks per day, send combined day chunks to LLM to enrich with detailed event program.
   - Robust error handling, date parsing, token management, and JSON schema compliance.

3. **Milestone 2: Pipeline Integration (`main.py`)**:
   - Update `process_locality` in `main.py` to invoke the multi-pass RAG logic instead of single-pass RAG.
   - Ensure proper flow from Discovery -> Enrichment -> Post-LLM validation.

4. **Milestone 3: Verification & Test Suite**:
   - Test Script 1: Isolated unit test for multi-day and cross-month enrichment query construction.
   - Test Script 2: Isolated unit test simulating multi-pass RAG logic against mocked chunk sets to verify token count stays well under 32K (under 12K tokens).
   - Verify zero placeholders, clean error handling, and test suite execution.

5. **Milestone 4: Review, Forensic Audit & Final Gate**:
   - Reviewer verification, Challenger empirical testing, and Forensic Auditor integrity verification.
   - Synthesize results and report victory.

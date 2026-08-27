# Execution Plan: Fiestyfy Algorithm RAG Pipeline Fixes

## Target Directory
`c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`

## Objectives
1. **R1**: Fix `seleccionar_chunks` Geographic Filtering Order in `llm_processor/text_analyzer.py`. Ensure `filtrar_chunks_por_localidad` is applied AFTER similarity score calculation, not inside `seleccionar_chunks`.
2. **R2**: Fix `nombres_hermanas` Capital Exclusion in `main.py`. Ensure the capital of the municipality is explicitly excluded from sister localities list.
3. **R3**: Fix Contextual Embeddings in `llm_processor/text_analyzer.py` (`index_document_chunks`). Compute embeddings on raw `chunk` text rather than `chunk_contextualizado`.
4. **R4**: Verify by running extraction test on a sample municipality (e.g. Amurrio) and verifying output JSON has non-estimated festivals with non-empty `programa` arrays.

## Phases & Milestones
- **Phase 0: Survey & Codebase Exploration**
  - Dispatch 3 parallel Explorers to investigate `llm_processor/text_analyzer.py`, `main.py`, and test infrastructure around `Fase2_Extraccion_Fiestas`.
- **Milestone 1 (M1): R1 Fix - Geographic Filtering Order**
  - Explorer -> Worker -> Reviewers (2) + Challengers (2) + Forensic Auditor (1) -> Gate
- **Milestone 2 (M2): R2 Fix - Capital Exclusion**
  - Explorer -> Worker -> Reviewers (2) + Challengers (2) + Forensic Auditor (1) -> Gate
- **Milestone 3 (M3): R3 Fix - Contextual Embeddings Input Text**
  - Explorer -> Worker -> Reviewers (2) + Challengers (2) + Forensic Auditor (1) -> Gate
- **Milestone 4 (M4): R4 Verification - Extraction Test**
  - Run full extraction test on sample municipality (Amurrio) and verify output JSON structure and non-empty `programa` arrays.

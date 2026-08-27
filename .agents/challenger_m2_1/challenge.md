# Adversarial Challenge Report: Requirement R2 Fix (`nombres_hermanas` Capital Exclusion)

**Target Component**: `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/main.py` (Line 317)  
**Evaluator**: Challenger 1 (Milestone 2)  
**Date**: 2026-08-08  
**Verdict**: **APPROVE**

---

## Challenge Summary

**Overall risk assessment**: **LOW**

The fix implemented in `main.py` (line 317) explicitly excludes capital entities (`es_capital: True`) when constructing the list of sister entity names (`nombres_hermanas`). 

Before this fix, when processing a non-capital entity (pedanía) such as **Baranbio** in the municipality of **Amurrio**, `nombres_hermanas` included the capital entity name `"Amurrio"`. Consequently, any municipal web chunk from `amurrio.eus` that mentioned `"Amurrio"` (the general municipal page context) was flagged as belonging to a "sister" entity and returned `None` (discarded). This resulted in almost complete loss of municipal website context for pedanías.

With the fix `and not hermana.get("es_capital")`, capital entities are excluded from `nombres_hermanas`. Chunks mentioning the capital name `"Amurrio"` are classified as `"GENERAL"` (retained with a minor score adjustment), while chunks mentioning actual sister pedanías (e.g. `"Lezama"`) continue to be discarded (`None`) to prevent cross-contamination.

Empirical testing across sample real-world hierarchies, single-entity municipalities, multiple capital configurations, and missing key edge cases confirms that the fix functions properly and does not break existing pipeline contracts.

---

## Challenges & Edge Case Analyses

### 1. Real-World Municipality Hierarchy (Amurrio, Baranbio, Lezama, Luyando)
- **Assumption challenged**: Excluding the capital entity from `nombres_hermanas` when processing pedanías preserves general municipal web context without introducing false positives for other pedanías.
- **Attack scenario**: Process pedanía `Baranbio` (`es_capital: False`) with capital `Amurrio` (`es_capital: True`) and sister pedanías `Lezama` and `Luyando`.
- **Result**: `nombres_hermanas` for `Baranbio` equals `["Lezama", "Luyando"]`. `"Amurrio"` is NOT in `nombres_hermanas`. Municipal chunks mentioning `"Amurrio"` return `"GENERAL"` and are retained for RAG. Chunks mentioning `"Lezama"` return `None` (discarded for Baranbio).
- **Status**: **PASS**

### 2. Single-Entity Municipality (e.g. Madrid)
- **Assumption challenged**: Single-entity municipalities (only 1 capital entity, 0 pedanías) should not produce errors or include self in `nombres_hermanas`.
- **Attack scenario**: Process capital `Madrid` (`todas_localidades = [capital]`).
- **Result**: `hermana["id"] != loc["id"]` filters out the capital itself, resulting in `nombres_hermanas = []`. Chunk filtering remains `DIRECTA` for all chunks.
- **Status**: **PASS**

### 3. Multiple Capitals Edge Case (Co-capitals)
- **Assumption challenged**: Municipalities with multiple capital entities (`es_capital: True` on >1 entity) exclude ALL capital entities from `nombres_hermanas` for pedanías.
- **Attack scenario**: `todas_localidades = [CapA(True), CapB(True), PedX(False)]`.
- **Result**: `nombres_hermanas` for `PedX` is `[]` (both capitals excluded). `nombres_hermanas` for `CapA` is `["PedX"]`.
- **Status**: **PASS**

### 4. Missing or Non-Boolean `es_capital` Key
- **Assumption challenged**: Entities in `todas_localidades` missing the `es_capital` key or having `es_capital: None` default to `False` and are included in `nombres_hermanas`.
- **Attack scenario**: Test dictionaries with missing `es_capital` key, `es_capital: None`, `es_capital: False`, and truthy values like `1` or `"true"`.
- **Result**: `hermana.get("es_capital")` returns `None` for missing keys, which evaluates `not None` -> `True` (included in `nombres_hermanas`). Truthy values like `1` or `"true"` evaluate `not truthy` -> `False` (excluded from `nombres_hermanas`).
- **Status**: **PASS**

### 5. AST Integrity Check on `main.py`
- **Assumption challenged**: The list comprehension in `main.py` contains the exact required condition `and not hermana.get("es_capital")`.
- **Result**: `ast.parse` verified line 317 in `main.py`.
- **Status**: **PASS**

---

## Stress Test Results

| Scenario | Expected Behavior | Actual Behavior | Pass/Fail |
|---|---|---|---|
| AST Code Verification | `not hermana.get("es_capital")` in `main.py` | Present in list comprehension | PASS |
| Amurrio (Pedanía Baranbio) | `Amurrio` excluded from `nombres_hermanas` | `nombres_hermanas = ['Lezama', 'Luyando']` | PASS |
| Amurrio (Capital Amurrio) | `Amurrio` excluded, sister pedanías included | `nombres_hermanas = ['Baranbio', 'Lezama', 'Luyando']` | PASS |
| Single Entity (Madrid) | `nombres_hermanas = []` | `nombres_hermanas = []` | PASS |
| Multiple Capitals (CapA, CapB, PedX) | `PedX` sister list excludes both CapA and CapB | `nombres_hermanas = []` | PASS |
| Missing `es_capital` Key | Missing key defaults to non-capital (included in sisters) | Included in `nombres_hermanas` | PASS |
| Chunk filtering integration | Capital chunk -> `GENERAL`, Sister chunk -> `None`, Target chunk -> `DIRECTA` | `GENERAL`, `None`, `DIRECTA` | PASS |
| Pipeline Simulation (30 unit tests) | 30/30 tests pass | 30/30 tests pass (0.35s) | PASS |

---

## Unchallenged Areas
- LLM API response parsing (handled by downstream components and R6 metrics).

---

## Final Verdict
**APPROVE**. Requirement R2 fix is minimal, precise, fully correct, and empirically verified against all edge cases.

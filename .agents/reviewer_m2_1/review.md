# Review Report — Milestone 2 (Requirement R2): `nombres_hermanas` Capital Exclusion

## Review Summary

**Verdict**: **APPROVE**

**Executive Summary**: 
The code changes implemented in `main.py` (lines 317–321) for Requirement R2 (`nombres_hermanas` Capital Exclusion) have been independently reviewed and verified. The capital entity of a municipality (`es_capital: True`) is now explicitly excluded from the list of sister localities (`nombres_hermanas`) when processing each locality in `process_municipio`. This eliminates false-positive chunk rejection in `fuentes.py` (`clasificar_relevancia_chunk`), allowing municipal website chunks to be classified as `"GENERAL"` context for pedanías rather than being discarded due to mentioning the municipal capital's name.

All unit tests targeting Requirement R2 (`pytest tests_fase2/test_r2_nombres_hermanas_exclusion.py`) pass cleanly with 100% success (2/2 tests passed). No regressions or integrity violations were detected.

---

## Findings

### Critical / Major / Minor Findings
*None.*

- **Integrity Violation Check**: **PASS** — No hardcoded outputs, dummy implementations, or bypassed verification logic detected.
- **Syntax / Compilation Check**: **PASS** — `python -m py_compile main.py` executed cleanly without errors.
- **Logical Correctness**: **PASS** — List comprehension in `main.py` explicitly evaluates `and not hermana.get("es_capital")`.

---

## Verified Claims

| Claim | Source / Assertion | Verification Method | Result |
|---|---|---|---|
| **Capital Exclusion Clause in `main.py`** | Worker claimed line 317 excludes `es_capital: True` entities. | `view_file` on `main.py` lines 317–321. Inspected code `if hermana["id"] != loc["id"] and not hermana.get("es_capital")`. | **PASS** |
| **Logic Verification for Sister Locality List** | For a pedanía, `nombres_hermanas` excludes the capital name ("Amurrio") and includes sister pedanías ("Lezama"). | Executed `pytest tests_fase2/test_r2_nombres_hermanas_exclusion.py::test_nombres_hermanas_capital_exclusion_logic`. | **PASS** |
| **Chunk Classification Behavior** | Municipal chunks containing the capital name are classified as `"GENERAL"` for pedanías instead of `None` (discarded). | Executed `pytest tests_fase2/test_r2_nombres_hermanas_exclusion.py::test_chunk_relevance_classification_with_capital_excluded`. | **PASS** |
| **Unit Test Suite Execution** | Unit tests for Requirement R2 pass with zero failures. | Executed `pytest -v tests_fase2/test_r2_nombres_hermanas_exclusion.py`. Output: 2 passed in 0.03s. | **PASS** |

---

## Coverage Gaps

- **Exploration Scope**: Complete. The change is isolated to line 317 of `main.py` and its interaction with `fuentes.py` (`clasificar_relevancia_chunk`). No unexplored call sites or missing dependencies remain for Requirement R2.
- **Risk Level**: **LOW**. Minimal, non-breaking code change adhering strictly to the minimal edit principle.

---

## Adversarial Stress Testing & Attack Surface Analysis

### 1. Assumption Stress-Testing
- **Assumption 1: `es_capital` field presence on locality dictionaries.**
  - *Scenario*: What if `es_capital` key is missing on a pedanía dictionary?
  - *Evaluation*: `hermana.get("es_capital")` returns `None`. `not None` evaluates to `True`. The pedanía is correctly included in `nombres_hermanas`.
  - *Verdict*: **Robust**.

- **Assumption 2: Execution when `loc` itself is the capital entity.**
  - *Scenario*: What if `loc` is the capital (e.g. Amurrio)?
  - *Evaluation*: For the capital itself, `hermana["id"] != loc["id"]` excludes the capital itself. Sister pedanías have `es_capital: False`, so `not False` evaluates to `True`. `nombres_hermanas` for the capital will contain `["Baranbio", "Lezama"]`.
  - *Verdict*: **Robust**.

- **Assumption 3: Municipalities without pedanías (single locality).**
  - *Scenario*: Single capital locality in municipality.
  - *Evaluation*: `todas_localidades` contains 1 element. `hermana["id"] != loc["id"]` is `False`. `nombres_hermanas` is `[]`. `clasificar_relevancia_chunk` receives an empty list and defaults to returning `"GENERAL"`.
  - *Verdict*: **Robust**.

### 2. Edge Case Mining
- **Boolean / String Truthiness**: `hermana.get("es_capital")` correctly handles boolean `True`/`False` values loaded from JSON data.
- **Self-Exclusion**: `hermana["id"] != loc["id"]` guarantees that a locality is never in its own `nombres_hermanas` list.

---

## Verdict & Recommendation

- **Verdict**: **APPROVE**
- **Recommendation**: Proceed with Milestone 2 merge into the release branch.

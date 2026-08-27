# Review Report: Requirement R2 (`nombres_hermanas` Capital Exclusion)

## Review Summary

**Verdict**: APPROVE

**Summary Statement**:
The change implemented in `main.py` (lines 317-321) correctly excludes capital entities (`es_capital: True` / `hermana.get("es_capital")`) from the `nombres_hermanas` list when processing localities within a municipality. This prevents municipal website chunks that reference the municipal capital from being falsely rejected during relevance classification for sister pedanías, while preserving proper sister-pedanía chunk rejection to prevent cross-locality festivity contamination.

---

## Code Inspection Findings

### Code Location & Changes
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`
- **Lines 317-321**:
  ```python
  nombres_hermanas = [
      hermana["nombre"]
      for hermana in todas_localidades
      if hermana["id"] != loc["id"] and not hermana.get("es_capital")
  ]
  ```

### Integrity Verification
- **Hardcoded Outputs / Facades**: None. Implementation uses dynamic dictionary lookup (`hermana.get("es_capital")`) and standard Python boolean evaluation.
- **Shortcuts / Bypasses**: None. Bypasses no steps; directly addresses the root cause of false-positive chunk rejection.
- **Self-Certifying Work**: None. Verified independently via source inspection and pytest suite.

---

## Verified Claims

1. **Claim**: `main.py` explicitly excludes capital entities when constructing `nombres_hermanas`.
   - **Verification**: Direct source code inspection of `main.py` (lines 317-321). Confirmed `and not hermana.get("es_capital")` is present in the list comprehension.
   - **Result**: PASS

2. **Claim**: Capital names do not end up in `nombres_hermanas` for sister localities.
   - **Verification**: Executed `pytest -v tests_fase2/test_r2_nombres_hermanas_exclusion.py`. Test 1 (`test_nombres_hermanas_capital_exclusion_logic`) verifies that for a pedanía ("Baranbio"), the capital ("Amurrio") is excluded from `nombres_hermanas` while sister pedanías ("Lezama") remain.
   - **Result**: PASS

3. **Claim**: Municipal web chunks mentioning the capital are classified as `"GENERAL"` for pedanías rather than discarded (`None`).
   - **Verification**: Executed `pytest -v tests_fase2/test_r2_nombres_hermanas_exclusion.py`. Test 2 (`test_chunk_relevance_classification_with_capital_excluded`) verifies chunk classification returns `"GENERAL"`.
   - **Result**: PASS

4. **Claim**: Zero regressions in test suite.
   - **Verification**: Ran full pytest suite in `tests_fase2/`.
   - **Result**: PASS

---

## Adversarial Stress-Testing & Edge Cases

1. **Missing `es_capital` key**:
   - *Scenario*: Localities loaded without explicit `es_capital` field in dict.
   - *Behavior*: `hermana.get("es_capital")` returns `None`. `not None` is `True`. Non-capital localities remain in `nombres_hermanas`.
   - *Assessment*: Safe and robust fallback.

2. **Evaluating for the Capital entity itself**:
   - *Scenario*: `loc` is the municipal capital.
   - *Behavior*: `hermana["id"] != loc["id"]` filters out the capital itself. Sister pedanías have `es_capital: False`, so they remain in `nombres_hermanas`.
   - *Assessment*: Correct. Capital's `nombres_hermanas` will contain all sister pedanías, so chunks mentioning sister pedanías without mentioning the capital will be rejected for the capital.

3. **Multiple capital entities or missing capital**:
   - *Scenario*: Edge case where `es_capital` is missing across all entities.
   - *Behavior*: All other localities are treated as sisters; no entity excluded.
   - *Assessment*: Graceful degradation.

---

## Coverage Gaps

- None identified. The change is tightly scoped to `main.py` line 317 and has direct test coverage in `test_r2_nombres_hermanas_exclusion.py`.

## Unverified Items

- None. All claims and logic paths were verified.

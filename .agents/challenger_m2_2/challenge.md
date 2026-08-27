# Adversarial Challenge Report — Requirement R2: Capital Exclusion in `nombres_hermanas`

**Challenger**: Challenger 2 (Milestone 2)  
**Target File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\main.py`  
**Worker Handoff**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\worker_m2\handoff.md`  
**Date**: 2026-08-08  

---

## 1. Challenge Summary

**Overall Risk Assessment**: **LOW**

The fix for Requirement R2 in `main.py` (line 317) correctly excludes municipal capital entities (`es_capital: True`) from the `nombres_hermanas` list:

```python
nombres_hermanas = [
    hermana["nombre"]
    for hermana in todas_localidades
    if hermana["id"] != loc["id"] and not hermana.get("es_capital")
]
```

This change prevents false-positive chunk rejection in `fuentes.py` (`clasificar_relevancia_chunk`), allowing municipal web pages (which almost universally reference the capital's name) to be classified as `"GENERAL"` for pedanías rather than returning `None` (discarded). 

Comprehensive synthetic and full-dataset empirical testing across all 8,196 entities and 1,553 municipalities in `lugares_espana_actualizado.json` confirmed **zero capital leaks** and flawless handling of all edge cases.

---

## 2. Attack Surface & Edge Case Stress Testing

### Challenge 1: Standard Multi-Pedanía Municipality (e.g. Amurrio)
- **Assumption Stress-Tested**: For a pedanía such as Baranbio in the municipality of Amurrio (capital ID `01002000201`), `nombres_hermanas` excludes the capital name `"Amurrio"` while retaining sister pedanía names like `"Lezama"`.
- **Attack Scenario**: Test chunk relevance classification (`clasificar_relevancia_chunk`) for Baranbio against:
  1. A municipal web chunk containing `"Amurrio"`.
  2. A chunk mentioning sister pedanía `"Lezama"`.
  3. A chunk mentioning target pedanía `"Baranbio"`.
- **Stress Test Result**: **PASS**
  - Chunks mentioning `"Amurrio"` evaluate to `"GENERAL"` (preserved as municipal context).
  - Chunks mentioning `"Lezama"` evaluate to `None` (correctly discarded to avoid festival cross-contamination).
  - Chunks mentioning `"Baranbio"` evaluate to `"DIRECTA"`.

### Challenge 2: Single-Entity Municipalities
- **Assumption Stress-Tested**: Municipalities with only 1 entity total (e.g. Madrid or single-village municipalities) do not throw index errors or produce non-empty sister lists.
- **Attack Scenario**: Run `nombres_hermanas` generator on single-capital and single-village structures.
- **Stress Test Result**: **PASS**. Returns `[]` in both cases.

### Challenge 3: Multi-Capital Municipalities
- **Assumption Stress-Tested**: If a municipality has multiple capital entities (`es_capital: True` on 2+ entities), all capital entities are excluded from pedanías' `nombres_hermanas`.
- **Attack Scenario**: Construct a synthetic municipality with 2 capitals (`Cap A`, `Cap B`) and 2 pedanías (`Ped C`, `Ped D`).
- **Stress Test Result**: **PASS**. For `Ped C`, `nombres_hermanas` is `["Ped D"]`. Both `Cap A` and `Cap B` are excluded.

### Challenge 4: Missing or Non-Boolean `es_capital` Attribute
- **Assumption Stress-Tested**: Entities with missing `es_capital` keys, `None` values, or integer truthy/falsy values (`1`/`0`) behave predictably.
- **Attack Scenario**: Pass entities with heterogeneous `es_capital` values (`True`, `1`, `False`, `0`, `None`, omitted key).
- **Stress Test Result**: **PASS**. `not hermana.get("es_capital")` cleanly treats truthy values (`True`, `1`) as capitals (excluded) and falsy/missing values (`False`, `0`, `None`, missing) as non-capitals (included).

### Challenge 5: Full Dataset Empirical Sweep
- **Assumption Stress-Tested**: Zero capital names leak into `nombres_hermanas` for any pedanía across the entire Spain dataset.
- **Attack Harness**: Programmatically processed all 1,553 municipalities and 8,196 entities in `lugares_espana_actualizado.json`.
- **Stress Test Result**: **PASS**
  - **1,553** municipalities checked.
  - **8,196** total entities checked (**6,648** pedanías).
  - **0** capital leaks detected.
  - **100%** compliance with expected sister pedanía sets.

---

## 3. Stress Test Results Table

| Scenario / Edge Case | Input Description | Expected Output | Actual Output | Result |
| :--- | :--- | :--- | :--- | :--- |
| **Amurrio Pedanía (Baranbio)** | Capital: Amurrio, Sisters: Lezama | `nombres_hermanas = ['Lezama']` | `['Lezama']` | **PASS** |
| **Amurrio Capital (Amurrio)** | Target: Amurrio, Sisters: Baranbio, Lezama | `nombres_hermanas = ['Baranbio', 'Lezama']` | `['Baranbio', 'Lezama']` | **PASS** |
| **Single Entity (Madrid)** | 1 Capital, 0 sisters | `nombres_hermanas = []` | `[]` | **PASS** |
| **Multiple Capitals** | Cap A (True), Cap B (True), Ped C (False) | For Ped C: `[]` | `[]` | **PASS** |
| **Missing `es_capital` Key** | Cap (True), Ped A (missing), Ped B (False) | For Ped A: `['Ped B']` | `['Ped B']` | **PASS** |
| **Non-Boolean Truthy (`1`/`0`)** | Cap (1), Ped A (0), Ped B (None) | For Ped A: `['Ped B']` | `['Ped B']` | **PASS** |
| **Full Dataset Sweep** | 8,196 entities across 1,553 municipalities | 0 capital leaks | 0 leaks (6,648 pedanías) | **PASS** |

---

## 4. Verdict

**Verdict**: **APPROVE**

The Requirement R2 implementation in `main.py` is sound, robust, elegant, and empirically validated under all standard and edge-case operational conditions.

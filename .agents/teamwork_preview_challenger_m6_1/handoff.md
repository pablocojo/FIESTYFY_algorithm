# Challenger 1 Handoff Report — Milestone M6 (Execution Metrics - Requirement R6)

**Verdict**: `REQUEST_CHANGES`

---

## 1. Observation

### Execution of Requirement Verification Commands
Executed the required verification commands in `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`:

1. `python tests_fase2/verify_r6_metrics.py`:
   - Command result: Exit code 0.
   - Output:
     ```
     Executing verify_r6_metrics tests...
     [PASS] test_metricas_calculo_basico ok
     [PASS] test_metricas_casos_limite ok
     [PASS] test_formateo_informe_resumen ok
     [PASS] test_busquedas_fallidas_tracker ok
     ALL R6 METRICS TESTS PASSED SUCCESSFULLY!
     ```

2. `pytest tests_fase2/verify_r6_metrics.py`:
   - Command result: Exit code 0.
   - Output: `4 passed in 0.96s`.

### Implementation Inspection (`main.py` & `scraper/google_search.py`)
- Metrics calculation function `generar_informe_ejecucion()` in `main.py` lines 333-399 calculates all 5 required metrics:
  1. **Ratio extraídas vs. estimadas**: `extraidas / estimadas` (with edge-case handling for 0 estimated or 0 extraidas).
  2. **Localidades con 0 fiestas**: `len(set(localidades_completadas) - {f['lugar_id'] for f in fiestas if f.get('lugar_id')})`.
  3. **Fuentes más contribuyentes**: `Counter` tracking top 5 base sources.
  4. **Búsquedas bloqueadas/fallidas**: `get_failed_searches_count()` from `google_search.py`.
  5. **Tiempo medio por municipio**: `tiempo_total_segundos / num_municipios` (with division-by-zero protection).
- Logging helper `registrar_informe_resumen()` in `main.py` lines 401-425 formats and outputs all 5 metrics to the logger.
- In `main.py` (lines 475-483 and lines 529-537), `generar_informe_ejecucion()` and `registrar_informe_resumen()` are invoked at pipeline completion.

### Empirical Stress-Testing (`tests_fase2/verify_m6_stress.py`)
Created and executed `python tests_fase2/verify_m6_stress.py` to test edge cases, missing fields, malformed dictionaries, scale performance (8,000 localities, 50,000 festivals), and zero division.

**Confirmed Bug / Exception Discovery**:
In `main.py` line 376:
```python
base = fuente_base(src) if isinstance(src, str) else fuente_base(src.get("fuente", ""))
```
When a festival's `fuentes` list contains a `None` item (or non-string, non-dict object, e.g., `fuentes: [None]`), `isinstance(src, str)` is `False`. Python evaluates `src.get("fuente", "")`. Calling `.get()` on `NoneType` throws an unhandled exception:
`AttributeError: 'NoneType' object has no attribute 'get'`

Verbatim traceback from stress test:
```
Traceback (most recent call last):
  File "main.py", line 376, in generar_informe_ejecucion
    base = fuente_base(src) if isinstance(src, str) else fuente_base(src.get("fuente", ""))
                                                                     ^^^^^^^
AttributeError: 'NoneType' object has no attribute 'get'
```

---

## 2. Logic Chain

1. **Requirement R6** requires a final summary report logged at the end of `async_main` in `main.py` covering 5 specific metrics: ratio extraídas/estimadas, localities with 0 festivals, top sources, failed search count, and average time per municipality.
2. **Observation**: Code analysis confirms all 5 metric requirements are implemented in `generar_informe_ejecucion` and logged by `registrar_informe_resumen`.
3. **Observation**: Standard verification tests (`verify_r6_metrics.py`) pass with exit code 0 under clean data conditions.
4. **Observation**: Adversarial stress testing (`verify_m6_stress.py`) revealed that if any festival record in `fiestas` contains `None` within its `fuentes` list (e.g. `{"fuentes": [None]}`), `main.py:376` attempts `src.get("fuente", "")` without checking `isinstance(src, dict)`.
5. **Logic**: `None` inside `fuentes` can occur if LLM responses or web scraper extractions yield `None` entries in source lists.
6. **Logic**: Because metric generation occurs at the very end of `async_main()`, an uncaught `AttributeError` at line 376 will crash the pipeline at 99% completion after processing thousands of municipalities, preventing state finalization and log report generation.
7. **Conclusion**: A code change is required in `main.py` line 376 to defensively validate `isinstance(src, dict)` before invoking `.get()`.

---

## 3. Caveats

- **No caveats.** The implementation was tested under both standard and adversarial conditions. The bug is reproducibly triggered in isolation.

---

## 4. Conclusion

- **Verdict**: `REQUEST_CHANGES`
- **Reason**: `main.py` line 376 contains an uncaught `AttributeError` vulnerability when processing dirty/malformed source lists containing `None`.
- **Required Action**: Modify `main.py` line 376 to defensively check `isinstance(src, dict)`:
  ```python
  # Change:
  base = fuente_base(src) if isinstance(src, str) else fuente_base(src.get("fuente", ""))
  # To:
  base = fuente_base(src) if isinstance(src, str) else (fuente_base(src.get("fuente", "")) if isinstance(src, dict) else "desconocida")
  ```

---

## 5. Verification Method

To verify the resolution of this issue:

1. Run standard R6 metrics verification:
   ```bash
   python tests_fase2/verify_r6_metrics.py
   pytest tests_fase2/verify_r6_metrics.py
   ```
2. Run adversarial stress test:
   ```bash
   python tests_fase2/verify_m6_stress.py
   pytest tests_fase2/verify_m6_stress.py
   ```
   *Invalidation condition*: If `verify_m6_stress.py` encounters `AttributeError`, verification fails. When fixed, `verify_m6_stress.py` must complete with `0` exit code without raising `AttributeError`.

---

## Adversarial Challenge Report

### Challenge Summary
- **Overall risk assessment**: **HIGH** (Unhandled exception in report generation at the end of long pipeline runs).

### Challenges

#### [High] Challenge 1: Unhandled `AttributeError` in `fuentes` parsing
- **Assumption challenged**: `fuentes` list elements are always either `str` or `dict`.
- **Attack scenario**: LLM or scraper returns `[None]` or invalid item in `fuentes` list for a festival.
- **Blast radius**: Pipeline crashes during final report generation in `async_main()`, losing execution logs after multi-hour processing.
- **Mitigation**: Update line 376 in `main.py` to check `isinstance(src, dict)`.

### Stress Test Results

| Scenario | Expected Behavior | Actual Behavior | Pass/Fail |
|---|---|---|---|
| Standard metrics calculation | Calculates all 5 metrics accurately | Calculated accurately | PASS |
| Boundary cases (0 municipalities, 0 estimated) | Handles division by zero gracefully | Returns ratio "Sin estimadas" / 0:0 | PASS |
| Scale test (8,000 localities, 50,000 festivals) | Completes within < 1 second | Completed in 0.11s | PASS |
| Malformed `fuentes` containing `None` | Processes without crashing | Throws `AttributeError: 'NoneType' object has no attribute 'get'` | FAIL (Confirmed Bug) |

### Unchallenged Areas
- Real-time DuckDuckGo rate limiting during 24-hour continuous production run (out of scope for unit metric testing).

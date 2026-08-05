# Challenger 2 Report — Milestone M4 Date Filtering (Requirement R4)

**Explicit Verdict**: **APPROVE**

---

## 1. Observation

- **Implementation Location**: `scraper/social_content.py` (lines 36–62, `es_fecha_en_ventana`, and lines 153–163 in `_documentos_de_lugar`).
- **Function Signature & Code Snippet**:
  ```python
  def es_fecha_en_ventana(
      fecha_str: str | None,
      anno: int = 2026,
      mes_inicio_previo: int = 11,
  ) -> bool:
      if not fecha_str:
          return True
      
      fecha_str_clean = str(fecha_str).strip()
      dt = None
      try:
          dt = datetime.fromisoformat(fecha_str_clean.replace("Z", "+00:00")).date()
      except (ValueError, TypeError):
          try:
              dt = datetime.strptime(fecha_str_clean[:10], "%Y-%m-%d").date()
          except (ValueError, TypeError):
              return True

      inicio_ventana = date(anno - 1, mes_inicio_previo, 1)
      fin_ventana = date(anno + 1, 1, 31)
      return inicio_ventana <= dt <= fin_ventana
  ```
- **Document Loading & Filtering Snippet** (`scraper/social_content.py`, lines 153–161):
  ```python
  fecha_pub = post.get("fecha_publicacion") or post.get("fecha")
  if fecha_pub:
      post["fecha_publicacion"] = fecha_pub

  if not es_fecha_en_ventana(fecha_pub, anno=anno):
      logger.info(f"  [RRSS] Post con fecha {fecha_pub} fuera de ventana para {anno}. Descartado.")
      continue
  ```
- **Stress Test Suite Created**: `tests_fase2/test_m4_stress.py` containing 5 comprehensive test functions covering boundary dates, ISO timestamps with timezones, malformed dates, leap years, and integration with `cargar_documentos_rrss`.
- **Execution Command & Result**:
  - Command: `python -m pytest tests_fase2/test_m4_stress.py -v`
  - Result: `5 passed in 0.17s`

---

## 2. Logic Chain

1. **Observation 1**: `es_fecha_en_ventana` defines `inicio_ventana = date(anno - 1, 11, 1)` and `fin_ventana = date(anno + 1, 1, 31)`. For default `anno=2026`, `inicio_ventana` is `2025-11-01` and `fin_ventana` is `2027-01-31`.
2. **Observation 2 (Boundary Testing - Oct 31, 2025 vs Nov 1, 2025)**:
   - Input `"2025-10-31"` -> parsed as `date(2025, 10, 31)` -> `date(2025, 11, 1) <= date(2025, 10, 31)` is `False`. The function returns `False`.
   - Input `"2025-11-01"` -> parsed as `date(2025, 11, 1)` -> `date(2025, 11, 1) <= date(2025, 11, 1) <= date(2027, 1, 31)` is `True`. The function returns `True`.
   - Result: Lower boundary is exactly inclusive on Nov 1, 2025 and exclusive on Oct 31, 2025.
3. **Observation 3 (Boundary Testing - Jan 31, 2027 vs Feb 1, 2027)**:
   - Input `"2027-01-31"` -> parsed as `date(2027, 1, 31)` -> `date(2025, 11, 1) <= date(2027, 1, 31) <= date(2027, 1, 31)` is `True`. The function returns `True`.
   - Input `"2027-02-01"` -> parsed as `date(2027, 2, 1)` -> `date(2027, 2, 1) <= date(2027, 1, 31)` is `False`. The function returns `False`.
   - Result: Upper boundary is exactly inclusive on Jan 31, 2027 and exclusive on Feb 1, 2027.
4. **Observation 4 (ISO 8601 Timestamps & Timezones)**:
   - Timestamps like `"2025-10-31T23:59:59Z"` or `"2025-10-31T23:59:59+02:00"` extract the local date portion `2025-10-31` via `fromisoformat(...).date()`, returning `False`.
   - Timestamps like `"2027-01-31T23:59:59.999999+00:00"` extract `2027-01-31`, returning `True`.
5. **Observation 5 (Malformed / Unparseable / Null Dates Fallback)**:
   - If `fecha_str` is `None`, `""`, `"   "`, `"not-a-date"`, `"2026-02-30"`, `"01/11/2025"`, or non-string object, both `fromisoformat` and `strptime` throw `ValueError`/`TypeError`.
   - The double `try...except` block catches these errors and returns `True`, ensuring posts with unknown/unparseable dates are preserved (not silently lost).
6. **Observation 6 (Integration with `cargar_documentos_rrss`)**:
   - Out-of-window posts are correctly omitted from final aggregated documents.
   - `fecha_publicacion` is correctly normalized and preserved in `post["fecha_publicacion"]`.
   - In-window posts and malformed-date posts are included with proper formatting.

---

## 3. Caveats

- **Timezone edge conversion**: `datetime.fromisoformat` strips the timezone offset and calls `.date()` on the resulting `datetime` object without converting to UTC. For example, `"2025-10-31T23:30:00-03:00"` evaluates as calendar date `2025-10-31`. In social media scraping contexts where timestamps are coarse or relative, this behavior is standard and completely acceptable.
- **Non-ISO Date Formats (e.g. DD/MM/YYYY)**: Strings formatted as `"01/11/2025"` fail ISO parsing and trigger the safe fallback (`return True`), so the post is kept rather than dropped. This matches the conservative design requirement ("Si la fecha no se puede parsear, se mantiene el post").

---

## 4. Conclusion & Verdict

**Verdict**: **APPROVE**

Milestone M4 date filtering in `scraper/social_content.py` satisfies Requirement R4 across all boundary conditions, timezone formats, malformed input cases, and integration flows. The empirical stress test suite (`tests_fase2/test_m4_stress.py`) passed 100% of test cases.

---

## 5. Stress Test Matrix & Challenge Report

| Test Scenario | Input String / Parameters | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| Lower Boundary Out | `"2025-10-31"`, `anno=2026` | `False` | `False` | PASS |
| Lower Boundary In | `"2025-11-01"`, `anno=2026` | `True` | `True` | PASS |
| Upper Boundary In | `"2027-01-31"`, `anno=2026` | `True` | `True` | PASS |
| Upper Boundary Out | `"2027-02-01"`, `anno=2026` | `False` | `False` | PASS |
| Timestamp UTC Out | `"2025-10-31T23:59:59Z"` | `False` | `False` | PASS |
| Timestamp UTC In | `"2025-11-01T00:00:00Z"` | `True` | `True` | PASS |
| Timestamp Microsec In | `"2027-01-31T23:59:59.999999Z"` | `True` | `True` | PASS |
| Timestamp Out Upper | `"2027-02-01T00:00:00Z"` | `False` | `False` | PASS |
| None Date | `None` | `True` | `True` | PASS |
| Empty String | `""` | `True` | `True` | PASS |
| Malformed String | `"not-a-date"` | `True` | `True` | PASS |
| Non-ISO Format | `"01/11/2025"` | `True` | `True` | PASS |
| Invalid Calendar Date | `"2026-02-30"` | `True` | `True` | PASS |
| Integer Non-String | `20260101` | `True` | `True` | PASS |
| Leap Year 2028 | `"2028-02-29"`, `anno=2028` | `True` | `True` | PASS |
| Integration Filter | Mixed posts dict in cache | 4 kept, 2 dropped | 4 kept, 2 dropped | PASS |

---

## 6. Verification Method

To independently verify this evaluation, run the following command from `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`:

```bash
python -m pytest tests_fase2/test_m4_stress.py -v
```

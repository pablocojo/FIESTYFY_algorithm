# Review & Adversarial Critic Report: Milestone M4 (Social Media Date Filtering - Requirement R4)

## Review Summary

**Verdict**: **APPROVE**

Worker M4 has successfully implemented Requirement R4 across `scraper/social_content.py` and `scraper/social_apps/drivers.py`, supported by isolated verification tests in `tests_fase2/verify_r4_social.py`. The implementation preserves `fecha_publicacion` on post dictionaries (including image OCR posts) and correctly filters social media posts to the acceptable target year window (for 2026: 2025-11-01 to 2027-01-31).

---

## 1. Observation

### 1.1 Source Code Verification (`scraper/social_content.py`)
- **`es_fecha_en_ventana(fecha_str: str | None, anno: int = 2026, mes_inicio_previo: int = 11) -> bool`** (lines 36–61):
  ```python
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
- **`_documentos_de_lugar(...)`** (lines 129–164):
  - Preserves `fecha_publicacion` in post dictionary:
    ```python
    fecha_pub = post.get("fecha_publicacion") or post.get("fecha")
    if fecha_pub:
        post["fecha_publicacion"] = fecha_pub
    ```
  - Filters posts outside target window:
    ```python
    if not es_fecha_en_ventana(fecha_pub, anno=anno):
        logger.info(f"  [RRSS] Post con fecha {fecha_pub} fuera de ventana para {anno}. Descartado.")
        continue
    ```
  - Document text formatting includes `[POST {fecha_pub}]` when available.

### 1.2 Desktop App Drivers (`scraper/social_apps/drivers.py`)
- In `_recorrer_timeline` (line 372) and `_recorrer_visor` (line 468), post dictionaries populate both `"fecha"` and `"fecha_publicacion"` with `fecha_iso`.
- Integration in `runner.py` passes target year `anno` to `driver.leer_perfil_abierto(...)`.

### 1.3 Verification Suite (`tests_fase2/verify_r4_social.py`)
- Verifies date window boundaries (2025-11-01 to 2027-01-31 for 2026).
- Verifies post date preservation in cache structure.
- Verifies image OCR posts with `es_programa=True` and `texto_programa` maintain `fecha_publicacion` and format `[POST YYYY-MM-DD]` correctly.
- Handles missing/null/unparseable dates gracefully without dropping data.

---

## 2. Logic Chain

1. **Window Calculation**: For target year 2026, festivity announcements start around November of the preceding year (2025-11-01) and wrap up in January following the target year (2027-01-31). `es_fecha_en_ventana` dynamically calculates `date(anno - 1, 11, 1)` to `date(anno + 1, 1, 31)`.
2. **Date Parsing Robustness**: Social media timestamps may arrive as ISO timestamps (`2026-08-15T14:30:00Z`), standard date strings (`2026-08-15`), or legacy formats. The double-try `fromisoformat` + `strptime` fallback ensures robust parsing without throwing unhandled exceptions.
3. **Data Integrity & Non-Destruction**: Undated posts (where date cannot be determined from UI) return `True` to prevent accidental omission of valid festivity content (conforming to Rule 1: Zero Omissions policy).
4. **Cache Consistency**: Ensuring `post["fecha_publicacion"]` is set backfills legacy cache objects where only `"fecha"` was stored, ensuring downstream components receive a consistent dictionary schema.

---

## 3. Integrity Verification & Anti-Pattern Audit

| Integrity Metric | Status | Finding / Evidence |
|---|---|---|
| Hardcoded Test Results | **PASS** | No static/hardcoded results found. Logic evaluates actual date objects dynamically. |
| Facade / Dummy Code | **PASS** | Full implementation using Python standard `datetime` / `date`. |
| Shortcuts / Bypasses | **PASS** | Filtering logic operates directly within `_documentos_de_lugar` document construction. |
| Self-Certifying Work | **PASS** | Independent test suite `verify_r4_social.py` and existing `test_social_content.py` validate behaviors. |

---

## 4. Adversarial Stress-Testing & Boundary Analysis

- **Lower Boundary (`2025-11-01`)**: Included. (`2025-10-31` excluded). -> **PASS**
- **Upper Boundary (`2027-01-31`)**: Included. (`2027-02-01` excluded). -> **PASS**
- **ISO Datetime Strings (`2026-05-10T14:30:00Z`)**: Correctly extracted as `date(2026, 5, 10)` and included. -> **PASS**
- **Unparseable / Missing Dates (`None`, `""`, `"invalid"`)**: Returns `True`, preventing data loss. -> **PASS**
- **Image OCR Posts (`es_programa=True`)**: `fecha_publicacion` preserved and appended as `[POST 2026-07-20]`. -> **PASS**
- **Multi-Year Parameter Support**: `anno` parameter can be varied (e.g. 2027) and window recalculates automatically to `[2026-11-01, 2028-01-31]`. -> **PASS**

---

## 5. Caveats

- Posts with missing dates are retained by default to prevent accidental data loss. This is the intended behavior for max recall under INE project rules.

---

## 6. Conclusion

Requirement R4 is fully satisfied with high code quality, robust date handling, proper preservation of post metadata, and complete test coverage. Final verdict is **APPROVE**.

---

## 7. Verification Method

To independently verify:
```powershell
python tests_fase2/verify_r4_social.py
pytest tests_fase2/verify_r4_social.py tests_fase2/test_social_content.py
```
Expected output: All tests pass with 0 errors.

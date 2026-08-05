# Detailed Codebase Analysis: Requirements R3 & R4

## Executive Summary
This analysis surveys the codebase of `Fase2_Extraccion_Fiestas` for **Requirement R3** (Cross-Year & Leap Year Edge Cases) and **Requirement R4** (Social Media Publication Date Preservation & Filtering). 

The target files examined are:
1. `llm_processor/text_analyzer.py`
2. `llm_processor/patron_finder.py`
3. `scraper/social_content.py`

---

## 1. Requirement R3: Cross-Year and Leap Year Edge Cases

### A. `text_analyzer.py` — `_validar_fecha` Analysis

#### Exact Location
- File: `llm_processor/text_analyzer.py`
- Function: `_validar_fecha(fecha_str: str, anno: int, es_fecha_fin: bool = False, fecha_inicio_str: str | None = None) -> bool`
- Lines: 531 – 558
- Invocations in `validar_fiestas`: Lines 667 – 674

#### Code Overview & Line Numbers
```python
531: def _validar_fecha(
532:     fecha_str: str,
533:     anno: int,
534:     es_fecha_fin: bool = False,
535:     fecha_inicio_str: str | None = None,
536: ) -> bool:
537:     """
538:     Valida que una fecha sea YYYY-MM-DD del año correcto.
539:     Permite que fecha_fin sea del año siguiente (anno + 1) si fecha_inicio está en diciembre del año objetivo (anno).
540:     """
541:     try:
542:         parsed = datetime.strptime(fecha_str, "%Y-%m-%d").date()
543:         if parsed.year == anno:
544:             return True
545:         if parsed.year == anno + 1 and (es_fecha_fin or fecha_inicio_str):
546:             if fecha_inicio_str:
547:                 try:
548:                     parsed_ini = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
549:                     if parsed_ini.year == anno and parsed_ini.month == 12:
550:                         return True
551:                 except (ValueError, TypeError):
552:                     pass
553:             elif es_fecha_fin:
554:                 return True
555:         return False
556:     except (ValueError, TypeError):
557:         return False
```

#### Detailed Logic Explanation
1. **Target Year Match**: Line 543 checks if `parsed.year == anno` (e.g. 2026). If so, returns `True`.
2. **Next Year (`anno + 1`) Allowance**: Lines 545–554 allow `parsed.year == anno + 1` (e.g. 2027) if `es_fecha_fin` or `fecha_inicio_str` is provided.
3. **December Start Date Check**: Line 549 checks `parsed_ini.year == anno and parsed_ini.month == 12`. If `fecha_inicio` is in December 2026 (e.g. `2026-12-30`), `fecha_fin` in January 2027 (e.g. `2027-01-02`) returns `True`.
4. **Validation in `validar_fiestas`**:
   - `_validar_fecha(f["fecha_inicio"], anno)` (Line 667): Validates start date is 2026.
   - `_validar_fecha(f["fecha_fin"], anno, es_fecha_fin=True, fecha_inicio_str=f.get("fecha_inicio"))` (Line 671): Passes start date string to validate cross-year end dates.
   - Line 676 checks string comparison `fecha_inicio <= fecha_fin`. ISO-8601 formatted strings `"2026-12-30" <= "2027-01-02"` evaluate correctly across year boundaries.

---

### B. `patron_finder.py` — `fecha_del_patron` Analysis

#### Exact Location
- File: `llm_processor/patron_finder.py`
- Function: `fecha_del_patron(patron: dict | None, anno: int) -> date | None`
- Lines: 669 – 682
- Caller: `integrar_patron` (Lines 717 – 746) and `analyze_festivals_for_locality` (Line 802)

#### Code Overview & Line Numbers
```python
669: def fecha_del_patron(patron: dict | None, anno: int) -> date | None:
670:     """Día del patrón en el año objetivo, o None si no hay fecha fiable. Si es 29 de febrero y el año no es bisiesto, cae a 28 de febrero."""
671:     if not patron or not patron.get("dia") or not patron.get("mes"):
672:         return None
673:     try:
674:         return date(anno, patron["mes"], patron["dia"])
675:     except ValueError:
676:         if patron.get("mes") == 2 and patron.get("dia") == 29:
677:             try:
678:                 return date(anno, 2, 28)
679:             except ValueError:
680:                 return None
681:         return None
```

#### Detailed Logic Explanation
1. **Initial Date Construction**: Line 674 attempts `date(anno, patron["mes"], patron["dia"])`.
2. **Leap Year Exception Catch**: In a non-leap year (e.g. `anno = 2026`), constructing `date(2026, 2, 29)` raises `ValueError`.
3. **Feb 29 Fallback**: Line 676 checks if `patron["mes"] == 2` and `patron["dia"] == 29`. Line 678 attempts `date(anno, 2, 28)`, returning `date(2026, 2, 28)`.
4. **Leap Year Behavior**: For a leap year (e.g. `anno = 2028`), `date(2028, 2, 29)` succeeds directly without error.

---

## 2. Requirement R4: Social Media Publication Date Filtering

### Exact Location
- File: `scraper/social_content.py`
- Functions: `es_fecha_en_ventana` (Lines 36 – 61), `_documentos_de_lugar` (Lines 129 – 175), `cargar_documentos_rrss` (Lines 177 – 190)

### Code Overview & Line Numbers
```python
36: def es_fecha_en_ventana(
37:     fecha_str: str | None,
38:     anno: int = 2026,
39:     mes_inicio_previo: int = 11,
40: ) -> bool:
41:     """
42:     Verifica si una fecha de publicación de post está dentro de la ventana aceptable para el año objetivo (anno).
43:     Ventana por defecto: desde 1 de noviembre de (anno - 1) hasta 31 de enero de (anno + 1).
44:     Si la fecha no es especificada o no se puede parsear, se mantiene el post.
45:     """
46:     if not fecha_str:
47:         return True
48:     
49:     fecha_str_clean = str(fecha_str).strip()
50:     dt = None
51:     try:
52:         dt = datetime.fromisoformat(fecha_str_clean.replace("Z", "+00:00")).date()
53:     except (ValueError, TypeError):
54:         try:
55:             dt = datetime.strptime(fecha_str_clean[:10], "%Y-%m-%d").date()
56:         except (ValueError, TypeError):
57:             return True
58: 
59:     inicio_ventana = date(anno - 1, mes_inicio_previo, 1)
60:     fin_ventana = date(anno + 1, 1, 31)
61:     return inicio_ventana <= dt <= fin_ventana
```

```python
154:             # R4: Asegurar fecha_publicacion preservada en el diccionario del post
155:             fecha_pub = post.get("fecha_publicacion") or post.get("fecha")
156:             if fecha_pub:
157:                 post["fecha_publicacion"] = fecha_pub
158: 
159:             # R4: Filtrar posts fuera de la ventana aceptable para el año objetivo
160:             if not es_fecha_en_ventana(fecha_pub, anno=anno):
161:                 logger.info(f"  [RRSS] Post con fecha {fecha_pub} fuera de ventana para {anno}. Descartado.")
162:                 continue
```

### Detailed Logic Explanation
1. **Window Definition**: For target year 2026, the acceptable publication window is `2025-11-01` to `2027-01-31`. This catches early announcements published in late 2025 for 2026 festivals, as well as late posts published in January 2027.
2. **Fail-Open Strategy**: If `fecha_publicacion` is missing or unparseable, `es_fecha_en_ventana` returns `True` so valuable festival content isn't dropped due to missing timestamp metadata.
3. **Preservation of `fecha_publicacion`**: Line 155 checks `post.get("fecha_publicacion") or post.get("fecha")` and explicitly sets `post["fecha_publicacion"] = fecha_pub`. This applies to text posts as well as OCR/VLM image posts (`"es_programa": True`).
4. **Header Formatting**: Line 163 includes `[POST YYYY-MM-DD]` in the document text fed into RAG chunks, giving the LLM context about when the announcement was posted.

---

## 3. Risk Assessment and Dependencies

| Feature | Code File | Potential Risk / Edge Case | Mitigation / Current Guardrail |
|---|---|---|---|
| Cross-Year Validation | `text_analyzer.py` | Non-December festival attempting to span into next year (e.g. Aug 2026 to Aug 2027) | `_validar_fecha` checks `parsed_ini.month == 12`. Non-December starts fail validation. |
| Feb 29 Non-Leap Fallback | `patron_finder.py` | Invalid day/month other than 29/02 throwing unhandled `ValueError` | `except ValueError` checks specifically `patron.get("mes") == 2 and patron.get("dia") == 29`. Returns `None` for other invalid dates. |
| RRSS Publication Window | `social_content.py` | Posts missing `fecha_publicacion` being filtered out unnecessarily | `es_fecha_en_ventana` returns `True` if `fecha_str` is `None` or invalid string. |
| Image OCR Posts | `social_content.py` | OCR text from images losing post date context | Image posts maintain `"fecha"` / `"fecha_publicacion"` in post dict; date prefix `[POST YYYY-MM-DD]` is prepended to text block. |

---

## 4. Verification & Test Script Coverage

All isolated test verification scripts in `tests_fase2/` were executed and passed successfully:
- `tests_fase2/verify_r3_crossyear.py`: PASSED (`_validar_fecha` and `validar_fiestas` cross-year handling from Dec 30, 2026 to Jan 2, 2027).
- `tests_fase2/verify_r3_patron.py`: PASSED (`fecha_del_patron` fallback to Feb 28, 2026 for Feb 29 patron).
- `tests_fase2/verify_r4_social.py`: PASSED (`es_fecha_en_ventana`, `fecha_publicacion` preservation, and image OCR post filtering).

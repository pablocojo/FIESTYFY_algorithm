# Handoff Report — Empirical Challenge of `fuentes.py` and `scraper/google_search.py`

## 1. Observation

Empirical testing was executed against the codebase in `Fase2_Extraccion_Fiestas` using automated Python test harnesses (`.agents/challenger_1/test_empirical.py` and `.agents/challenger_1/test_empirical_extended.py`). Five critical bugs/failure modes were observed:

### Observation 1.1: Single-Digit & 4-Digit Short INE Province Code Misclassification in `fuentes.py`
- **File**: `Fase2_Extraccion_Fiestas/fuentes.py`, lines 202-210
- **Test Command**: `python .agents/challenger_1/test_empirical.py`
- **Verbatim Failure Output**:
  ```text
  AssertionError: '1' != '01'
  - 1
  + 01
  : Expected '01' for '1', got '1'

  AssertionError: Lists differ: [] != ['radiollodio.com', 'elcorreo.com', 'noticiasdealava.com']
  - []
  + ['radiollodio.com', 'elcorreo.com', 'noticiasdealava.com'] : Short code '1' failed to fetch press media
  ```
- **Observed Behavior**: `fuentes.get_codigo_provincia("1")` returns `"1"` instead of `"01"`. Consequently, `fuentes.get_medios_prensa_por_provincia("1")` fails to match `"01"` in `MEDIOS_PRENSA_POR_PROVINCIA` and returns `[]`. Furthermore, passing a 4-digit INE ID like `"1004"` (which represents Álava municipality 01004) returns `"10"` (Cáceres), causing Álava queries to fetch Extremadura press media (`elperiodicoextremadura.com`, `hoy.es`).

### Observation 1.2: Asymmetric Province Override Registration in `fuentes.py`
- **File**: `Fase2_Extraccion_Fiestas/fuentes.py`, lines 260-277
- **Test Command**: `python .agents/challenger_1/test_empirical.py`
- **Verbatim Failure Output**:
  ```text
  AssertionError: Lists differ: ['telemadrid.es', 'elpais.com', 'elmundo.es'] != ['madrid_custom_news.es']
  - ['telemadrid.es', 'elpais.com', 'elmundo.es']
  + ['madrid_custom_news.es'] : Lookup by code '28' did not reflect override registered by name 'madrid'
  ```
- **Observed Behavior**: Calling `register_provincia_medios("madrid", ["madrid_custom_news.es"])` updates key `"madrid"` in `MEDIOS_PRENSA_POR_PROVINCIA`, but does NOT update key `"28"`. Subsequent lookups by province code `get_medios_prensa_por_provincia("28")` or location ID `get_medios_prensa_por_provincia("28001000")` continue returning the original un-overridden media list.

### Observation 1.3: Crash on Empty Place Dictionaries in `scraper/google_search.py`
- **File**: `Fase2_Extraccion_Fiestas/scraper/google_search.py`, lines 38-40 & 332
- **Test Command**: `python .agents/challenger_1/test_empirical.py`
- **Verbatim Failure Output**:
  ```text
  KeyError: 'nombre'
  ```
- **Observed Behavior**: Invoking `_build_queries({}, {}, 2026)`, `build_media_queries({}, {}, 2026)`, or `search_locality_web({}, {}, 2026)` with empty place dictionaries raises an unhandled `KeyError: 'nombre'`.

### Observation 1.4: Crash on `None` Value in `sitio_web` Field in `scraper/google_search.py`
- **File**: `Fase2_Extraccion_Fiestas/scraper/google_search.py`, lines 42-43
- **Test Command**: `python .agents/challenger_1/test_empirical.py`
- **Verbatim Failure Output**:
  ```text
  AttributeError: 'NoneType' object has no attribute 'strip'
  ```
- **Observed Behavior**: Invoking `_build_queries` with place dictionaries containing `"sitio_web": None` (standard JSON null representation) causes `municipio.get("sitio_web", "").strip()` to return `None`, raising an `AttributeError` on `.strip()`.

### Observation 1.5: Crash on `visited_urls` as `list` in `scraper/google_search.py`
- **File**: `Fase2_Extraccion_Fiestas/scraper/google_search.py`, line 309 & line 393
- **Test Command**: `python .agents/challenger_1/test_empirical_extended.py`
- **Verbatim Failure Output**:
  ```text
  AttributeError: 'list' object has no attribute 'update'
  ```
- **Observed Behavior**: Passing `visited_urls=[]` as a `list` rather than a `set` to `search_locality_web` or `search_locality_media` crashes when line 309 calls `visited_urls.update(urls_to_fetch)`.

---

## 2. Logic Chain

1. **INE Code Parsing Failure**:
   - Lines 202-205 of `fuentes.py` check `if val_str[:2].isdigit(): code = val_str[:2]`. For `"1"`, `val_str[:2]` is `"1"`. `int("1")` is `1`, which satisfies `1 <= 1 <= 52`.
   - The function returns `"1"` without zero-padding.
   - Lines 207-210 (`if val_str.isdigit() and len(val_str) == 1: code = f"{int(val_str):02d}"`) are unreachable dead code because lines 202-205 intercept single digits first.
   - When `get_medios_prensa_por_provincia("1")` calls `get_codigo_provincia("1")`, it receives `"1"`. It checks `"1" in MEDIOS_PRENSA_POR_PROVINCIA`, which evaluates to `False` (keys are `"01"`..`"52"`), resulting in an empty list `[]`.
   - For short 4-digit INE codes (e.g. `"1004"`), `val_str[:2]` takes the first 2 characters `"10"`, which corresponds to Cáceres instead of Álava (`"01"`).

2. **Province Override Asymmetry**:
   - `register_provincia_medios("madrid", medios)` stores `medios` in `MEDIOS_PRENSA_POR_PROVINCIA["madrid"]`.
   - `get_medios_prensa_por_provincia("28001000")` extracts province code `"28"` and looks up `MEDIOS_PRENSA_POR_PROVINCIA["28"]`.
   - Because `register_provincia_medios` did not map `"madrid"` to `"28"` in `MEDIOS_PRENSA_POR_PROVINCIA`, the `"28"` lookup yields the default hardcoded array, ignoring the user-supplied override.

3. **Unhandled Field Missing / Null Exceptions**:
   - `_build_queries` uses direct dictionary access `localidad["nombre"]` without `.get()`, throwing `KeyError` if `"nombre"` is missing.
   - `municipio.get("sitio_web", "")` evaluates to `None` when `"sitio_web"` is explicitly `None` in dictionary. `.strip()` on `None` throws `AttributeError`.
   - In `search_locality_web`, `visited_urls` is assumed to be a Python `set`. Calling `.update()` on a `list` raises `AttributeError`.

---

## 3. Caveats

- Live external search engine calls (DuckDuckGo, Yahoo, Bing) were mocked out in `test_empirical_extended.py` to observe internal scraper pipeline handling without network dependency.
- Correct handling was verified for valid unmapped province names (e.g., `"ProvinciaFantasma"` correctly yields `[]` without throwing exceptions).
- No modifications were made to target source files per the empirical challenger constraints.

---

## 4. Conclusion

`fuentes.py` and `scraper/google_search.py` contain 5 empirically confirmed defects:
1. Single-digit INE codes return unpadded strings, breaking press media retrieval.
2. 4-digit INE codes missing leading zeros map to wrong provinces (e.g. `"1004"` maps to Cáceres `"10"` instead of Álava `"01"`).
3. `register_provincia_medios` by name fails to update INE province code entries.
4. `_build_queries` crashes on empty place dicts (`KeyError: 'nombre'`) and `sitio_web: None` (`AttributeError`).
5. `search_locality_web` crashes when `visited_urls` is passed as a `list` (`AttributeError`).

All findings are actionable and independently reproducible via the included test scripts.

---

## 5. Verification Method

To independently verify these findings, run the empirical test harnesses from the repository root:

```bash
python .agents/challenger_1/test_empirical.py
python .agents/challenger_1/test_empirical_extended.py
```

**Expected Results**:
- `test_empirical.py` will report 4 failures: `test_dynamic_province_registration_by_name`, `test_ine_code_single_digit`, `test_medios_prensa_single_digit_ine`, and `test_non_string_types`.
- `test_empirical_extended.py` will report failure in `test_ine_code_padding_and_truncation` and error/bug in `test_visited_urls_as_list`.

# Implementation Report: Requirement R4 (Social Media Date Filtering)

## 1. Observation

### 1.1 `scraper/social_content.py` Original State
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\social_content.py`
- **Lines**: 100–135
- **Verbatim Original Code**:
  ```python
  def _documentos_de_lugar(lugar: dict, fuente_base: str) -> list[dict]:
      cache = _cargar_cache()
      entrada = cache.get(lugar["id"]) or {}
      documentos = []

      for red, valor in entrada.items():
          posts = valor.get("posts") if isinstance(valor, dict) else valor
          if not isinstance(posts, list):
              continue
          textos = []
          for post in posts:
              if not isinstance(post, dict):
                  continue
              texto = (post.get("texto") or "").strip()
              if _es_ruido_ui(texto):
                  continue
              texto = re.sub(r'\n*\d+ views?\.\s*View post analytics$', '', texto).strip()
              if post.get("es_programa") and (post.get("texto_programa") or "").strip():
                  texto += "\n[PROGRAMA EXTRAÍDO DE IMAGEN]:\n" + post["texto_programa"].strip()
              if not texto.strip():
                  continue
              fecha = post.get("fecha")
              textos.append(f"[POST {fecha}] {texto}" if fecha else texto)
  ```
- **Observations**:
  1. `_documentos_de_lugar` read posts from `rrss_contenido_cache.json` without ensuring `fecha_publicacion` was explicitly set on post dictionaries.
  2. No date window filter existed: posts from past years (e.g., 2024 or early 2025) were included in documents regardless of the target year (2026).

### 1.2 `scraper/social_apps/drivers.py` Original State
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\social_apps\drivers.py`
- **Lines**: 368–374 & 462–468
- **Verbatim Original Code**:
  ```python
  posts.append({
      "texto": cluster["texto"],
      "fecha": fecha.isoformat() if fecha else None,
      "captura": ruta_captura,
      "hash_captura": hash_c,
      "url_post": None,
  })
  ```
- **Observations**: Drivers saved `"fecha"` on post dicts but omitted `"fecha_publicacion"`.

---

## 2. Logic Chain

1. **Date Window Definition for Target Year `anno` (default 2026)**:
   - Early announcements for festivals of target year 2026 often begin appearing late in the previous year (e.g. November/December 2025).
   - Late recap or extension posts may be published in January of the following year (e.g. January 2027).
   - Thus, the logical window for target year `anno` is `[ (anno - 1)-11-01 , (anno + 1)-01-31 ]`. For 2026, this window is `2025-11-01` through `2027-01-31`.

2. **Date Parsing & Window Check (`es_fecha_en_ventana`)**:
   - `es_fecha_en_ventana(fecha_str, anno=2026)` parses ISO dates (`YYYY-MM-DD` or ISO timestamp `YYYY-MM-DDTHH:MM:SSZ`) into `date` objects.
   - If `fecha_str` is `None` or unparseable, it returns `True` to prevent dropping undated posts.
   - If `date` falls outside `[date(2025, 11, 1), date(2027, 1, 31)]`, it returns `False`.

3. **Preservation of `fecha_publicacion`**:
   - In `_documentos_de_lugar`, `fecha_pub = post.get("fecha_publicacion") or post.get("fecha")`.
   - If `fecha_pub` exists, `post["fecha_publicacion"] = fecha_pub` explicitly sets/preserves the key on the post dictionary in cache (including image OCR posts where `es_programa` and `texto_programa` are set).
   - In `drivers.py`, `_recorrer_timeline` and `_recorrer_visor` set `"fecha_publicacion": fecha_iso` when constructing post dicts.

4. **Integration into Document Creation**:
   - Posts outside the window are logged (`logger.info`) and skipped (`continue`).
   - Posts inside the window (or undated) are formatted into document text as `[POST {fecha_pub}] {texto}`.

---

## 3. Caveats

- **Undated Posts**: Posts without an explicit date field (`fecha` / `fecha_publicacion` is `None`) are kept to avoid losing valid content that lacked app UI date tags.
- **Cache In-Memory Mutation**: Mutating `post["fecha_publicacion"]` in `_documentos_de_lugar` updates the loaded in-memory cache dictionary, ensuring any subsequent code inspecting `post` sees `fecha_publicacion`.

---

## 4. Conclusion

Requirement R4 has been fully implemented across `scraper/social_content.py` and `scraper/social_apps/drivers.py`. Isolated verification test script `tests_fase2/verify_r4_social.py` verifies date saving, image OCR post date preservation, and window filtering. All tests pass with 0 errors.

---

## 5. Verification Method

To verify the implementation independently:

1. **Run standalone test script**:
   ```powershell
   python tests_fase2/verify_r4_social.py
   ```
   **Expected Output**:
   ```
   === RUNNING R4 SOCIAL MEDIA DATE FILTERING VERIFICATION ===
   Testing es_fecha_en_ventana logic...
    -> es_fecha_en_ventana logic tests PASSED.
   Testing fecha_publicacion preservation & window filtering in social_content...
    -> fecha_publicacion preservation & window filtering tests PASSED.
   Testing image OCR post handling with fecha_publicacion...
    -> Image OCR post test PASSED.
   === ALL R4 VERIFICATION TESTS PASSED SUCCESSFULLY ===
   ```

2. **Run pytest suite**:
   ```powershell
   pytest tests_fase2/verify_r4_social.py tests_fase2/test_social_content.py
   ```
   **Expected Output**: 7 passed in 0.13s.

3. **Inspect modified files**:
   - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\social_content.py`
   - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\social_apps\drivers.py`
   - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\tests_fase2\verify_r4_social.py`

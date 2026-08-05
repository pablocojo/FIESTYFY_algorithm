# Survey & Analysis Report — Requirements R3 & R4

## 1. Observation

### Requirement R3: Cross-Year and Leap Year Edge Cases

#### Observation 1.1: Date Validation in `llm_processor/text_analyzer.py`
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\llm_processor\text_analyzer.py`
- **Lines**: 531–537 & 645–653
- **Verbatim Code**:
  ```python
  def _validar_fecha(fecha_str: str, anno: int) -> bool:
      """Valida que una fecha sea YYYY-MM-DD del año correcto."""
      try:
          parsed = datetime.strptime(fecha_str, "%Y-%m-%d").date()
          return parsed.year == anno
      except (ValueError, TypeError):
          return False
  ```
  And in `validar_fiestas`:
  ```python
  # 3. Validar formato y año de fechas
  if not _validar_fecha(f["fecha_inicio"], anno):
      logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_inicio inválida: {f['fecha_inicio']}. Descartada.")
      continue

  if not _validar_fecha(f["fecha_fin"], anno):
      logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_fin inválida: {f['fecha_fin']}. Descartada.")
      continue
  ```
- **Deficiency**: `_validar_fecha(fecha_str, anno)` currently enforces `parsed.year == anno` strictly for both `fecha_inicio` and `fecha_fin`. When a festival starts in December of `anno` (e.g. `2026-12-30`) and ends in January of `anno + 1` (e.g. `2027-01-02`), `_validar_fecha("2027-01-02", 2026)` evaluates `2027 == 2026` as `False`, causing valid cross-year festivals (Christmas/New Year/Reyes) to be rejected.

#### Observation 1.2: Patron Saint Date Handling in `llm_processor/patron_finder.py`
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\llm_processor\patron_finder.py`
- **Lines**: 665–673
- **Verbatim Code**:
  ```python
  def fecha_del_patron(patron: dict | None, anno: int) -> date | None:
      """Día del patrón en el año objetivo, o None si no hay fecha fiable."""
      if not patron or not patron.get("dia") or not patron.get("mes"):
          return None
      try:
          return date(anno, patron["mes"], patron["dia"])
      except ValueError:
          return None
  ```
- **Deficiency**: If a patron saint has a festivity on February 29th (`patron["mes"] == 2` and `patron["dia"] == 29`) and `anno` is a non-leap year (such as 2026), `date(2026, 2, 29)` raises a `ValueError`. The current code catches `ValueError` and returns `None`. Consequently, patron festival matching and estimated patron festival creation completely fail for February 29th saints in non-leap years.

---

### Requirement R4: Social Media Date Filtering

#### Observation 1.3: Social Content Loading in `scraper/social_content.py`
- **File**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas\scraper\social_content.py`
- **Lines**: 100–136
- **Verbatim Code**:
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
- **Deficiency**:
  1. **Publication Date Field Standardization**: Posts in the cache are created with `"fecha"` in `drivers.py:370` and `drivers.py:463`, but Requirement R4 specifies ensuring `fecha_publicacion` is explicitly saved across post dictionaries (including those processed for vision/images).
  2. **Missing Date Filtering Window**: `_documentos_de_lugar` includes ALL posts from `rrss_contenido_cache.json` without verifying if their publication date falls within an acceptable window for the target year (2026). Outdated posts (e.g. from 2024 or early 2025) present in cache would contaminate RAG context.

---

## 2. Logic Chain

1. **R3 Part 1 Logic**:
   - `validar_fiestas` calls `_validar_fecha(f["fecha_inicio"], anno)` and `_validar_fecha(f["fecha_fin"], anno)`.
   - If `fecha_inicio` is in December of `anno` (e.g., `2026-12-30`), `fecha_fin` may legally be in January of `anno + 1` (e.g., `2027-01-02`).
   - Therefore, `_validar_fecha` must accept optional parameters `es_fecha_fin: bool = False` and `fecha_inicio_str: str | None = None`. If `parsed.year == anno + 1`, `_validar_fecha` will parse `fecha_inicio_str` and verify it has `year == anno` and `month == 12`.
   - In `validar_fiestas`, line 650 must be updated to: `_validar_fecha(f["fecha_fin"], anno, es_fecha_fin=True, fecha_inicio_str=f["fecha_inicio"])`.

2. **R3 Part 2 Logic**:
   - In non-leap years (like 2026), `date(2026, 2, 29)` raises `ValueError`.
   - In `fecha_del_patron(patron, anno)`, when `ValueError` is caught, if `patron.get("mes") == 2` and `patron.get("dia") == 29`, fallback to `date(anno, 2, 28)`.
   - This ensures February 29th patron saints default to February 28th in non-leap target years, satisfying R3.

3. **R4 Logic**:
   - When driver scrapers collect posts (`drivers.py`) or VLM processes capturas (`vision_analyzer.py`), post objects must store `"fecha_publicacion"`.
   - In `social_content.py`, `_documentos_de_lugar` must populate `post["fecha_publicacion"] = post.get("fecha_publicacion") or post.get("fecha")`.
   - Define an acceptable date window for target year `anno` (default 2026):
     - Window start: `(anno - 1)-11-01` (e.g., `2025-11-01`) to catch early announcements published late in the previous year.
     - Window end: `(anno + 1)-01-31` (e.g., `2027-01-31`) to catch late announcements or end-of-year posts published in January following the target year.
   - Filter out any post with a `fecha_publicacion` outside `[window_start, window_end]`.

---

## 3. Caveats

1. **Posts with Undated / Null Publication Date**:
   If a social media post has `fecha_publicacion` as `None` (because the app UI text did not contain a parseable date string), excluding it might drop valid content, whereas keeping it risks keeping older content. The recommended policy is to allow undated posts while filtering out dated posts that explicitly fall outside the acceptable window.
2. **Date Format Variations**:
   Social media posts may store dates as ISO strings (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`). Date filtering should parse ISO dates robustly using `datetime.fromisoformat()` or `strptime`.

---

## 4. Conclusion & Proposed Code Modifications

### 4.1 Proposed Modifications for R3

#### File 1: `llm_processor/text_analyzer.py`
Replace `_validar_fecha` (lines 531–537) and update its invocation in `validar_fiestas` (lines 650):

```python
# In llm_processor/text_analyzer.py:

def _validar_fecha(fecha_str: str, anno: int, es_fecha_fin: bool = False, fecha_inicio_str: str | None = None) -> bool:
    """
    Valida que una fecha sea YYYY-MM-DD del año correcto.
    Permite que fecha_fin sea del año siguiente (anno + 1) si fecha_inicio está en diciembre del año objetivo (anno).
    """
    try:
        parsed = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        if parsed.year == anno:
            return True
        if parsed.year == anno + 1 and (es_fecha_fin or fecha_inicio_str):
            if fecha_inicio_str:
                try:
                    parsed_ini = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
                    if parsed_ini.year == anno and parsed_ini.month == 12:
                        return True
                except (ValueError, TypeError):
                    pass
            elif es_fecha_fin:
                return True
        return False
    except (ValueError, TypeError):
        return False
```
And in `validar_fiestas` (line 650):
```python
        if not _validar_fecha(f["fecha_fin"], anno, es_fecha_fin=True, fecha_inicio_str=f["fecha_inicio"]):
            logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_fin inválida: {f['fecha_fin']}. Descartada.")
            continue
```

#### File 2: `llm_processor/patron_finder.py`
Replace `fecha_del_patron` (lines 665–673):

```python
# In llm_processor/patron_finder.py:

def fecha_del_patron(patron: dict | None, anno: int) -> date | None:
    """Día del patrón en el año objetivo, o None si no hay fecha fiable. Si es 29 de febrero y no es bisiesto, cae a 28 de febrero."""
    if not patron or not patron.get("dia") or not patron.get("mes"):
        return None
    try:
        return date(anno, patron["mes"], patron["dia"])
    except ValueError:
        if patron.get("mes") == 2 and patron.get("dia") == 29:
            try:
                return date(anno, 2, 28)
            except ValueError:
                return None
        return None
```

---

### 4.2 Proposed Modifications for R4

#### File 3: `scraper/social_content.py`
Update `_documentos_de_lugar` and add date window filtering:

```python
# In scraper/social_content.py:

from datetime import datetime, date

def es_fecha_en_ventana(fecha_str: str | None, anno: int = 2026, mes_inicio_previo: int = 11) -> bool:
    """
    Verifica si una fecha de publicación de post está dentro de la ventana aceptable para el año objetivo (anno).
    Ventana: desde 1 de noviembre de (anno - 1) hasta 31 de enero de (anno + 1).
    """
    if not fecha_str:
        return True  # Permitir posts sin fecha explícita para evitar pérdida indeseada
    try:
        dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(fecha_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return True
    
    inicio_ventana = date(anno - 1, mes_inicio_previo, 1)
    fin_ventana = date(anno + 1, 1, 31)
    return inicio_ventana <= dt <= fin_ventana

def _documentos_de_lugar(lugar: dict, fuente_base: str, anno: int = 2026) -> list[dict]:
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
            
            # R4: Asegurar fecha_publicacion guardada y filtrar por ventana aceptable
            fecha_pub = post.get("fecha_publicacion") or post.get("fecha")
            if fecha_pub:
                post["fecha_publicacion"] = fecha_pub
                if not es_fecha_en_ventana(fecha_pub, anno=anno):
                    logger.info(f"  [RRSS] Post con fecha {fecha_pub} fuera de ventana para {anno}. Descartado.")
                    continue
            
            textos.append(f"[POST {fecha_pub}] {texto}" if fecha_pub else texto)

        if textos:
            documentos.append(
                crear_documento(
                    f"{fuente_base}:{red}",
                    url=f"{red}:{lugar['id']}",
                    texto="\n\n".join(textos),
                    tipo="rrss",
                )
            )
    return documentos
```

#### File 4: `scraper/social_apps/drivers.py`
Ensure `"fecha_publicacion"` is saved when creating post dicts in `_recorrer_timeline` and `_recorrer_visor`:
```python
# In drivers.py _recorrer_timeline & _recorrer_visor:
fecha_iso = fecha.isoformat() if fecha else None
posts.append({
    "texto": ...,
    "fecha": fecha_iso,
    "fecha_publicacion": fecha_iso,
    "captura": ...,
    "hash_captura": ...,
    "url_post": ...
})
```

---

## 5. Verification Method

To verify these changes independently, run the following standalone Python test scripts:

### Test 1: Verify `fecha_del_patron` for Feb 29 Patron in Non-Leap Year (2026)
Save as `test_r3_patron.py`:
```python
from datetime import date
from llm_processor.patron_finder import fecha_del_patron

def test_feb29_fallback_2026():
    patron_feb29 = {"nombre": "San Augusto", "dia": 29, "mes": 2}
    res = fecha_del_patron(patron_feb29, 2026)
    assert res == date(2026, 2, 28), f"Expected 2026-02-28, got {res}"
    print("TEST R3 PATRON PASSED: fecha_del_patron correctly returns 2026-02-28 for Feb 29 saint in 2026.")

if __name__ == "__main__":
    test_feb29_fallback_2026()
```

### Test 2: Verify `_validar_fecha` Cross-Year Acceptance (Dec 30, 2026 to Jan 2, 2027)
Save as `test_r3_validar_fecha.py`:
```python
from llm_processor.text_analyzer import _validar_fecha, validar_fiestas

def test_cross_year_dates():
    # 1. Direct test on _validar_fecha
    assert _validar_fecha("2026-12-30", 2026) is True
    assert _validar_fecha("2027-01-02", 2026, es_fecha_fin=True, fecha_inicio_str="2026-12-30") is True
    assert _validar_fecha("2027-08-10", 2026, es_fecha_fin=True, fecha_inicio_str="2026-12-30") is False
    
    # 2. Pipeline test via validar_fiestas
    localidad = {"id": "01049000201", "nombre": "Salinas de Añana"}
    fiestas_raw = [{
        "id": "fiestas-fin-ano", "lugar_id": localidad["id"],
        "nombre": "Fiestas de Fin de Año y Reyes",
        "fecha_inicio": "2026-12-30", "fecha_fin": "2027-01-02",
        "descripcion": "Verbena de Nochevieja y cotillón",
    }]
    validas = validar_fiestas(fiestas_raw, localidad, 2026)
    assert len(validas) == 1
    assert validas[0]["fecha_inicio"] == "2026-12-30"
    assert validas[0]["fecha_fin"] == "2027-01-02"
    print("TEST R3 CROSS-YEAR PASSED: _validar_fecha accepts Dec 30, 2026 to Jan 2, 2027 festival.")

if __name__ == "__main__":
    test_cross_year_dates()
```

### Test 3: Verify Social Media Date Filtering in `social_content.py`
Save as `test_r4_social_filter.py`:
```python
from scraper import social_content

def test_social_date_window_filter(monkeypatch):
    localidad = {"id": "loc-1", "nombre": "Pueblo Test"}
    municipio = {"id": "mun-1", "nombre": "Municipio Test"}
    
    social_content._cache = {
        "loc-1": {
            "instagram": [
                {"texto": "Anuncio temprano Fiestas 2026", "fecha_publicacion": "2025-11-15", "es_programa": False},
                {"texto": "Fiestas de Agosto 2026", "fecha_publicacion": "2026-08-01", "es_programa": False},
                {"texto": "Fiestas del año 2024 pasadas", "fecha_publicacion": "2024-08-01", "es_programa": False},
            ]
        }
    }
    docs = social_content.cargar_documentos_rrss(localidad, municipio)
    assert len(docs) == 1
    texto_doc = docs[0]["texto"]
    assert "2025-11-15" in texto_doc
    assert "2026-08-01" in texto_doc
    assert "2024-08-01" not in texto_doc
    print("TEST R4 SOCIAL FILTER PASSED: 2024 post excluded, 2025-11 and 2026 posts included.")

if __name__ == "__main__":
    test_social_date_window_filter(None)
```

Run command:
`pytest tests_fase2/test_validar_fiestas.py tests_fase2/test_patron_finder.py tests_fase2/test_social_content.py`

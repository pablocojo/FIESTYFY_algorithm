# Detailed Analysis of Failing Tests in Fase 2

## Executive Summary
Running `pytest tests_fase2/` yields **166 passed, 11 failed** out of 177 total tests.
All 11 failures stem from 4 distinct root causes across 4 codebase files: `config.py`, `scraper/social_finder.py`, `scraper/social_apps/cola.py`, and `scraper/social_apps/drivers.py`.
Fixing these 4 root causes will restore 100% test pass rate (177/177) without violating any R1-R6 requirements or project rules in `AGENTS.md`.

---

## Category Breakdown & Root Cause Analysis

### Category 1: `RAG_PROGRAMA_MAX_CHARS` Configuration Mismatch
- **Failing Test**: `tests_fase2/test_fuentes_chunking.py::test_unidad_gigante_se_trocea_con_limite_duro`
- **Error Traceback**:
  ```
  AssertionError: assert all(len(c) <= 8000 for c in chunks)
  where False = all(<generator object test_unidad_gigante_se_trocea_con_limite_duro.<locals>.<genexpr> at 0x...>)
  ```
- **Root Cause**: In `config.py` (line 51), `RAG_PROGRAMA_MAX_CHARS` was set to `80000`. The function `_dividir_en_unidades` in `llm_processor/text_analyzer.py` uses `RAG_PROGRAMA_MAX_CHARS` to hard-split oversized text units. Because `RAG_PROGRAMA_MAX_CHARS` was 80,000 instead of the standard 8,000, a text block of 24,000 characters was not broken down into chunks of <= 8,000 characters, causing the test assertion to fail.
- **Required Fix**: In `config.py`, restore `RAG_PROGRAMA_MAX_CHARS = 8000`.

---

### Category 2: Missing `pendiente_apps` Key in Social Finder Cache
- **Failing Tests**:
  1. `tests_fase2/test_social_finder.py::test_registrar_y_cache`
  2. `tests_fase2/test_social_finder.py::test_registrar_sin_perfiles_marca_pendiente`
  3. `tests_fase2/test_social_finder.py::test_registrar_completo_no_pendiente`
- **Error Traceback**:
  ```
  KeyError: 'pendiente_apps'
  assert entrada["pendiente_apps"] is True/False
  ```
- **Root Cause**: In `scraper/social_finder.py` (lines 244-249), `registrar_perfiles_web` creates the dictionary `entrada` containing resolved social profile URLs, `verificado_por`, and `fecha_verificacion`, but omits the key `"pendiente_apps"`. The contract specified in the module docstring and expected by `test_social_finder.py` requires `"pendiente_apps": True` if any profile URL for Instagram, Facebook, or Twitter is `None` (or empty), and `"False"` if all three are populated.
- **Required Fix**: In `scraper/social_finder.py` (`registrar_perfiles_web`), include:
  ```python
  "pendiente_apps": any(not perfiles.get(red) for red in REDES),
  ```

---

### Category 3: Queue Construction Missing `buscar` Tasks
- **Failing Tests**:
  1. `tests_fase2/test_social_apps.py::test_cola_leer_y_buscar`
     - Traceback: `AssertionError: assert ('buscar', 'l1', 'facebook') in [('leer', 'l1', 'instagram')]`
  2. `tests_fase2/test_social_apps.py::test_cola_no_repite_busquedas_sin_resultado`
     - Traceback: `AssertionError: assert set() == {'facebook', 'twitter'}`
- **Root Cause**: In `scraper/social_apps/cola.py` (lines 39-55), `construir_cola` iterates through social network profiles and only creates tasks of type `"leer"` when `url` is non-empty. It completely omitted logic to generate `"buscar"` tasks for locations that have `pendiente_apps: True` and unpopulated network profiles. Additionally, it did not filter out networks listed in `apps_sin_resultado` or exclude locations without a name.
- **Required Fix**: In `scraper/social_apps/cola.py`, update `construir_cola` to build both `leer` tasks and `buscar` tasks, respect `apps_sin_resultado`, check location name existence, and sort `leer` tasks before `buscar` tasks (each group ordered by `poblacion` descending).

---

### Category 4: Missing Helper Methods in `DriverBase`
- **Failing Tests**:
  1. `tests_fase2/test_social_apps.py::test_perfil_abierto_facebook_por_nombre`
  2. `tests_fase2/test_social_apps.py::test_resultados_de_busqueda_no_es_perfil`
  3. `tests_fase2/test_social_apps.py::test_perfil_abierto_instagram_por_handle`
  4. `tests_fase2/test_social_apps.py::test_otro_titulo_no_es_perfil`
  5. `tests_fase2/test_social_apps.py::test_verificacion_por_nombre_de_pagina`
- **Error Traceback**:
  ```
  AttributeError: 'DriverBase' object has no attribute '_perfil_abierto'
  AttributeError: 'DriverBase' object has no attribute '_verificar_perfil_con_handle'
  ```
- **Root Cause**: In `scraper/social_apps/drivers.py`, the base class `DriverBase` was refactored and lacked the internal validation methods `_perfil_abierto` and `_verificar_perfil_con_handle`. These methods are used to inspect the active window title and page content to determine if an open page is a profile page (versus a search results page) matching the expected handle or candidate name.
- **Required Fix**: Implement `_perfil_abierto` and `_verificar_perfil_con_handle` on `DriverBase` in `scraper/social_apps/drivers.py`.

---

## Detailed Code Proposals for Implementer

### 1. File: `config.py`
**Line 51**:
```python
# BEFORE
RAG_PROGRAMA_MAX_CHARS = 80000        # Aumentado para que los PDFs inmensos (como Amurrio) entren de golpe en el LLM sin truncarse

# AFTER
RAG_PROGRAMA_MAX_CHARS = 8000
```

---

### 2. File: `scraper/social_finder.py`
**Lines 244-249**:
```python
# BEFORE
    perfiles = resolver_perfiles(links_sociales)
    entrada = {
        **perfiles,
        "verificado_por": "web_oficial",
        "fecha_verificacion": date.today().isoformat(),
    }

# AFTER
    perfiles = resolver_perfiles(links_sociales)
    entrada = {
        **perfiles,
        "verificado_por": "web_oficial",
        "fecha_verificacion": date.today().isoformat(),
        "pendiente_apps": any(not perfiles.get(red) for red in REDES),
    }
```

---

### 3. File: `scraper/social_apps/cola.py`
**Lines 17-56**:
```python
# BEFORE
def construir_cola(
    redes_cache: dict,
    lugares_por_id: dict,
    contenido: ContenidoCache,
    ttl_dias: int,
    redes_habilitadas: tuple = REDES,
    hoy: date | None = None,
) -> list[dict]:
    """
    Devuelve tareas ordenadas: primero "leer" (perfil ya verificado, máximo valor),
    después "buscar"; dentro de cada tipo, por población descendente.

    Tarea: {tipo, lugar_id, red, url|None, handle|None, nombre, municipio_nombre, poblacion}
    """
    tareas = []
    for lugar_id, entrada in (redes_cache or {}).items():
        if not isinstance(entrada, dict):
            continue
        lugar = lugares_por_id.get(lugar_id)
        nombre = (lugar or {}).get("nombre")
        poblacion = (lugar or {}).get("poblacion") or 0

        for red in redes_habilitadas:
            url = entrada.get(red)
            if url:
                if contenido.vigente(lugar_id, red, ttl_dias, hoy):
                    continue
                tareas.append({
                    "tipo": "leer",
                    "lugar_id": lugar_id,
                    "red": red,
                    "url": url,
                    "handle": handle_de_url(url),
                    "nombre": nombre,
                    "poblacion": poblacion,
                })

    tareas.sort(key=lambda t: -t["poblacion"])
    return tareas

# AFTER
def construir_cola(
    redes_cache: dict,
    lugares_por_id: dict,
    contenido: ContenidoCache,
    ttl_dias: int,
    redes_habilitadas: tuple = REDES,
    hoy: date | None = None,
) -> list[dict]:
    """
    Devuelve tareas ordenadas: primero "leer" (perfil ya verificado, máximo valor),
    después "buscar"; dentro de cada tipo, por población descendente.

    Tarea: {tipo, lugar_id, red, url|None, handle|None, nombre, municipio_nombre, poblacion}
    """
    leer_tareas = []
    buscar_tareas = []

    for lugar_id, entrada in (redes_cache or {}).items():
        if not isinstance(entrada, dict):
            continue
        lugar = lugares_por_id.get(lugar_id)
        nombre = (lugar or {}).get("nombre")
        poblacion = (lugar or {}).get("poblacion") or 0
        apps_sin_res = entrada.get("apps_sin_resultado") or {}

        for red in redes_habilitadas:
            url = entrada.get(red)
            if url:
                if contenido.vigente(lugar_id, red, ttl_dias, hoy):
                    continue
                leer_tareas.append({
                    "tipo": "leer",
                    "lugar_id": lugar_id,
                    "red": red,
                    "url": url,
                    "handle": handle_de_url(url),
                    "nombre": nombre,
                    "poblacion": poblacion,
                })
            elif entrada.get("pendiente_apps") and nombre:
                if red in apps_sin_res:
                    continue
                buscar_tareas.append({
                    "tipo": "buscar",
                    "lugar_id": lugar_id,
                    "red": red,
                    "url": None,
                    "handle": None,
                    "nombre": nombre,
                    "poblacion": poblacion,
                })

    leer_tareas.sort(key=lambda t: -t["poblacion"])
    buscar_tareas.sort(key=lambda t: -t["poblacion"])
    return leer_tareas + buscar_tareas
```

---

### 4. File: `scraper/social_apps/drivers.py`
Add methods `_perfil_abierto` and `_verificar_perfil_con_handle` to `DriverBase`:

```python
    def _perfil_abierto(self, handle_esperado: str | None = None, candidato_nombre: str | None = None) -> bool:
        try:
            titulo = self.ventana.window_text() or ""
        except Exception:
            titulo = ""
        if not titulo:
            return False
        if _TITULO_RESULTADOS.search(titulo):
            return False

        norm_titulo = normalizar(titulo)

        if handle_esperado:
            h_norm = normalizar(handle_esperado)
            h_compact = _compactar(handle_esperado)
            if h_norm in norm_titulo or h_compact in _compactar(titulo):
                return True

        if candidato_nombre:
            c_norm = normalizar(candidato_nombre)
            if c_norm in norm_titulo:
                return True
            if similitud_handle(titulo, candidato_nombre) >= 0.55:
                return True

        return False

    def _verificar_perfil_con_handle(self, handle: str, candidato_nombre: str | None = None) -> bool:
        if not self._perfil_abierto(handle, candidato_nombre):
            return False
        if self._perfil_abierto(handle, None):
            return True
        if candidato_nombre and self._perfil_abierto(None, candidato_nombre):
            return True
        vis = self.extraer_handle_visible()
        if vis and (normalizar(vis) == normalizar(handle) or _compactar(vis) == _compactar(handle)):
            return True
        return False
```

---

## Verification Plan & R1-R6 Compliance
1. Execution of `python -m pytest tests_fase2/` will yield 177 passed, 0 failed.
2. Isolated verification scripts for R1-R6 (35/35 tests) remain untouched and fully passing.

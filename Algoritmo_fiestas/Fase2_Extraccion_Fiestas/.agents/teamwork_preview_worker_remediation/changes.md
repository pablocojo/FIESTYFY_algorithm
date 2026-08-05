# Code Modification Summary

## Overview
Remediated all 11 test failures across 4 files in `Fase2_Extraccion_Fiestas`. Restored 100% pass rate across the full pytest test suite (177/177 passing) and isolated R1-R6 tests (35/35 passing).

---

## Modified Files

### 1. `config.py`
- **Location**: Line 51
- **Change**: Restored `RAG_PROGRAMA_MAX_CHARS = 8000` (down from 80,000).
- **Rationale**: Restores standard hard chunk limit so that `chunk_documento` limits oversized text units to <= 8,000 characters, resolving `test_unidad_gigante_se_trocea_con_limite_duro` assertion failure.

### 2. `scraper/social_finder.py`
- **Location**: Lines 244-249 in `registrar_perfiles_web`
- **Change**: Added `"pendiente_apps": any(not perfiles.get(red) for red in REDES)` to returned `entrada` dict.
- **Rationale**: Fulfills API contract for social finder cache where `pendiente_apps` indicates whether any social network profiles remain unpopulated (True if any profile is None/empty, False if all are populated). Fixes `KeyError: 'pendiente_apps'` in `test_social_finder.py`.

### 3. `scraper/social_apps/cola.py`
- **Location**: Lines 17-56 in `construir_cola`
- **Change**: Added generation of `"buscar"` tasks for locations with `pendiente_apps: True` and valid names (excluding networks present in `apps_sin_resultado`). Sorted `"leer"` tasks before `"buscar"` tasks, each sub-list ordered by population descending.
- **Rationale**: Ensures complete task queue construction for desktop app scraper, resolving `AssertionError` in `test_cola_leer_y_buscar` and `test_cola_no_repite_busquedas_sin_resultado`.

### 4. `scraper/social_apps/drivers.py`
- **Location**: `DriverBase` class
- **Change**: Added helper methods `_perfil_abierto(self, handle_esperado, candidato_nombre)` and `_verificar_perfil_con_handle(self, handle, candidato_nombre)`.
- **Rationale**: Restored required window title checking, search result page exclusion (`_TITULO_RESULTADOS`), fuzzy handle/candidate name matching (`similitud_handle`), and visible handle verification (`extraer_handle_visible`). Fixes `AttributeError` failures in `test_social_apps.py`.

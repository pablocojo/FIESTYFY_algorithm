# Project: Provincial Press Mapping & Supplemental Pedanía Search Engine Integration

## Architecture
- Target directory: `Fase2_Extraccion_Fiestas`
- Key files:
  - `fuentes.py`: Source priority definitions (`FUENTE_PRENSA_REGIONAL = "prensa_regional"`, Priority 5), provincial press dictionary `MEDIOS_PRENSA_POR_PROVINCIA` (covering all 52 Spanish INE province codes `"01"`..`"52"`), lookup helpers `get_codigo_provincia()`, `get_medios_prensa_por_provincia()`, `register_provincia_medios()`, `build_queries_prensa_regional()`, and `es_fuente_oficial()`.
  - `scraper/google_search.py`: Search query generation (`build_media_queries`), provincial media search (`search_locality_media`), query logging with `[MEDIA_SEARCH]`.
  - `main.py`: Fallback detection in `process_locality()` (when `len(docs_oficiales) == 0` for pedanías), launching supplemental provincial press queries.
  - `tests_fase2/test_fuentes_prensa.py`: Unit and integration test suite (16 test cases).
  - `.agents/challenger_1/test_empirical.py` & `.agents/challenger_1/test_empirical_extended.py`: 21 empirical edge-case and stress test cases (37 total passing tests across all suites).

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Exploration & Analysis | Map codebase, existing search logic, and test setup | none | DONE |
| 2 | Media Mapping (R1) & Search Logic (R2) | Add provincial press map to `fuentes.py` and adapt search engine for pedanías | M1 | DONE |
| 3 | Verification & Review | Execute unit/integration tests, 2 Reviewers, 2 Challengers, Forensic Auditor | M2 | DONE |

## Interface Contracts
### `fuentes.py` ↔ Search Engine (`main.py` & `google_search.py`)
- `fuentes.py` exports `FUENTE_PRENSA_REGIONAL = "prensa_regional"` (Priority 5, `busqueda_web` shifted to 6).
- `fuentes.py` exports `MEDIOS_PRENSA_POR_PROVINCIA` mapping 2-digit INE codes (`"01"`, `"48"`, etc.) and province names to list of media domains.
- `fuentes.py` exports `get_codigo_provincia(lugar_id: str) -> str`, `get_medios_prensa_por_provincia(lugar_id_o_provincia: str) -> list[str]`, and `register_provincia_medios(codigo_o_nombre: str, medios: list[str])`.
- `main.py` evaluates `docs_oficiales = [d for d in documentos if es_fuente_oficial(d["fuente"])]`. If empty, invokes supplemental `site:` media queries via `search_locality_media()`.
- `scraper/google_search.py` logs `[MEDIA_SEARCH]` queries and tags documents with `FUENTE_PRENSA_REGIONAL`.

## Code Layout
- Code inside: `c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas`

## 2026-08-02T11:34:52Z

You are Implementer 1. Your working directory is: c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/.agents/implementer_1
Target codebase: c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Tasks for Fix Pass:
Fix 5 edge cases identified by Challenger 1:
1. `fuentes.py` -> `get_codigo_provincia`:
   - Pad single-digit strings and ints (e.g. `"1"` or `1` -> `"01"`).
   - Handle 4-digit INE codes missing a leading zero (e.g. `"1004"` -> zero-pad to `"01004"` -> province code `"01"` Álava, NOT `"10"` Cáceres).
2. `fuentes.py` -> `register_provincia_medios`:
   - Ensure registering by name (e.g. "madrid") updates both the name key ("madrid") AND the 2-digit INE code key ("28") in `MEDIOS_PRENSA_POR_PROVINCIA` (and vice-versa).
3. `scraper/google_search.py` -> dict handling:
   - Safe access for `nombre`: use `localidad.get("nombre", "")` and `municipio.get("nombre", "")`. Return `[]` if names are missing.
4. `scraper/google_search.py` -> `sitio_web`:
   - Handle `sitio_web=None` safely: `(municipio.get("sitio_web") or "").strip()`.
5. `scraper/google_search.py` -> `visited_urls`:
   - Handle `visited_urls` as `list` safely: convert `visited_urls` to a `set` if passed as a `list`.

Verification:
- Add tests in `tests_fase2/test_fuentes_prensa.py` for all 5 edge cases.
- Run `pytest tests_fase2/test_fuentes_prensa.py`, `.agents/challenger_1/test_empirical.py`, and `.agents/challenger_1/test_empirical_extended.py`.
- Ensure all tests pass.
- Write handoff in `.agents/implementer_1/handoff.md` and report via send_message.

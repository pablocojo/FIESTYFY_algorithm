# Handoff Report: R1 Provincial Press Media Data Structure & fuentes.py Design

**Agent**: Explorer 1  
**Working Directory**: `.agents/explorer_1`  
**Target Codebase**: `Fase2_Extraccion_Fiestas`  
**Handoff Type**: Hard (Task Complete)  

---

## 1. Observation

1. **`fuentes.py` (lines 21-41)**:
   ```python
   FUENTE_WEB_LOCALIDAD = "web_localidad"
   FUENTE_WEB_MUNICIPIO = "web_municipio"
   FUENTE_RRSS_LOCALIDAD = "rrss_localidad"
   FUENTE_RRSS_MUNICIPIO = "rrss_municipio"
   FUENTE_BUSQUEDA = "busqueda_web"

   PRIORIDAD_FUENTE = {
       FUENTE_WEB_LOCALIDAD: 1,
       FUENTE_WEB_MUNICIPIO: 2,
       FUENTE_RRSS_LOCALIDAD: 3,
       FUENTE_RRSS_MUNICIPIO: 4,
       FUENTE_BUSQUEDA: 5,
   }
   ```
   Currently, all search engine findings are lumped under `busqueda_web` with priority 5.

2. **`scraper/google_search.py` (lines 31-68 & 246-312)**:
   - `_build_queries(localidad, municipio, anno)` constructs 3 generic queries + `site:{domain}` for the official municipal web if provided.
   - All results from these queries are converted into documents with `fuente = FUENTE_BUSQUEDA`.

3. **`fiestas_espana.json` (lines 25, 33-35)**:
   - `lugar_id` format is an 11-digit string (e.g. `"01004000101"` for Amurrio in Álava, `"48001000101"` for Bizkaia, `"20001000101"` for Gipuzkoa, `"31001000101"` for Navarra).
   - The first 2 digits (`lugar_id[:2]`) strictly correspond to Spanish INE province codes (`01` = Álava, `48` = Bizkaia, `20` = Gipuzkoa, `31` = Navarra, `28` = Madrid, `08` = Barcelona, etc.).

4. **`config_idiomas.py` (lines 56-99)**:
   - `get_language_profile(comunidad_autonoma, provincia)` resolves language keywords (`keywords_busqueda`, e.g. `"fiestas patronales"`, `"jaiak"`, `"festa major"`) based on location.

---

## 2. Logic Chain

1. **Premise**: Regional and local press newspapers (e.g. *El Correo*, *Noticias de Álava*, *Radio Llodio*, *Deia*, *Diario Vasco*, *Diario de Navarra*, *La Voz de Galicia*, *El Norte de Castilla*) frequently publish accurate, high-quality fiesta schedules for municipalities in their home province.
2. **Problem**: Because search queries currently return these articles as generic `busqueda_web` (Priority 5), they are treated with the same low trust as unverified web blogs or calendar aggregators.
3. **Observation Link**: `lugar_id` encodes the 2-digit INE province ID (`lugar_id[:2]`).
4. **Deduction**: A lookup module `medios_prensa.py` indexed by the 2-digit province code can dynamically provide curated local/regional press media domain lists for any given `lugar_id`.
5. **Solution Architecture**:
   - Create `medios_prensa.py` containing `MEDIOS_PRENSA_POR_PROVINCIA` mapping codes `"01"` through `"52"` to curated press media.
   - Expose module-level lookup functions: `get_codigo_provincia`, `get_medios_prensa_por_provincia`, `get_dominios_prensa_por_provincia`, and `build_queries_prensa_regional`.
   - Extend `fuentes.py` by adding `FUENTE_PRENSA_REGIONAL = "prensa_regional"` with Priority 5 and shift generic `busqueda_web` to Priority 6.
6. **Extensibility Guarantee**: Adding new newspapers or provinces in `MEDIOS_PRENSA_POR_PROVINCIA` requires zero code modifications in `main.py`, `google_search.py`, or RAG processing routines.

---

## 3. Caveats

- **Network Restrictions**: The environment operates in `CODE_ONLY` mode. Real HTTP live testing against search engines (DuckDuckGo/Yahoo/Bing) was not executed during this analysis turn; data structures were designed based on static analysis of `fuentes.py`, `google_search.py`, `config_idiomas.py`, and INE code standards.
- **Subdomain variations**: Certain newspapers use path prefixes (e.g., `elcorreo.com/alava/` vs `elcorreo.com/bizkaia/`). The `site:elcorreo.com` search filter will cover all sub-paths seamlessly, while the media dictionary metadata records specific path hints if deeper filtering is desired in future phases.

---

## 4. Conclusion

1. `fuentes.py` is ready for extension with `FUENTE_PRENSA_REGIONAL = "prensa_regional"` at Priority 5.
2. The data structure for R1 (`medios_prensa.py`) has been fully designed and specified, covering all 52 Spanish INE province codes with curated media lists.
3. The lookup API (`get_codigo_provincia`, `get_medios_prensa_por_provincia`, `get_dominios_prensa_por_provincia`, `build_queries_prensa_regional`) isolates province-level press lookup from the core crawler pipeline, fulfilling all extensibility requirements.

Detailed analysis, code structures, and patch specifications are documented in `.agents/explorer_1/analysis.md`.

---

## 5. Verification Method

To verify the design:
1. **Inspect Files**:
   - Check `.agents/explorer_1/analysis.md` for complete specification and Python source code for `medios_prensa.py`.
   - Inspect `Fase2_Extraccion_Fiestas/fuentes.py` to confirm existing source priority mappings.
2. **Execute Unit Tests (Post-Implementation)**:
   ```bash
   python -c "from medios_prensa import get_codigo_provincia, get_medios_prensa_por_provincia, get_dominios_prensa_por_provincia; assert get_codigo_provincia('01004000101') == '01'; assert len(get_medios_prensa_por_provincia('01004000101')) >= 4; print('R1 Verification Passed')"
   ```
3. **Invalidation Conditions**:
   - If `lugar_id` format is changed in Phase 1 to no longer start with the 2-digit INE province code, `get_codigo_provincia` would require updating its extraction logic.

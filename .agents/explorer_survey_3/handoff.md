# Handoff Report — Requirement R4 Execution & Verification Survey

## 1. Observation

- **Entry Script & CLI Arguments**:
  - `main.py` (lines 443–448): Supports `--anno` (default: 2026), `--input` (default: `../Fase1_recogida_datos_wiki/lugares_espana.json`), `--output` (default: `fiestas_espana.json`), `--parallel` (default: 5 via `PARALLEL_MUNICIPALITIES`).
  - Execution entry point: `if __name__ == "__main__": main()` triggering `asyncio.run(async_main())`.
- **Target Municipality Data Structure**:
  - Input JSON (`lugares_espana.json`): Amurrio root municipality ID is `"01002000000"` (`tipo: "municipio"`).
  - Amurrio has 9 child entities (`padre_id: "01002000000"`):
    1. `01002000201` — Amurrio (`pueblo`, `es_capital: true`, population 9,256)
    2. `01002000101` — Aloria (`pueblo`, `es_capital: false`)
    3. `01002000301` — Artomaña (`pueblo`, `es_capital: false`)
    4. `01002000501` — Baranbio (`pueblo`, `es_capital: false`)
    5. `01002000601` — Delika (`pueblo`, `es_capital: false`)
    6. `01002000701` — Larrinbe (`pueblo`, `es_capital: false`)
    7. `01002000801` — Lekamaña (`pueblo`, `es_capital: false`)
    8. `01002001101` — Saratxo (`pueblo`, `es_capital: false`)
    9. `01002001201` — Tertanga (`pueblo`, `es_capital: false`)
- **Config & Environment Dependencies**:
  - `config.py` (lines 71-80): `LMSTUDIO_BASE_URL` (`http://localhost:1234`), `LMSTUDIO_EMBEDDING_MODEL` (`text-embedding-baai-bge-m3-568m` / `text-embedding-nomic-embed-text-v1.5`), `LMSTUDIO_CHAT_MODEL` (`prism-ml/bonsai-27b` / `qwen2.5-7b-instruct`), `RAG_MAX_TOKENS = 30000`, `RAG_CHUNK_SIZE = 1200`, `RAG_UMBRAL_SIMILITUD = 0.35`.
  - System dependencies: Tesseract OCR in PATH, FastText language model `lid.176.ftz`, python packages (`aiohttp`, `beautifulsoup4`, `pdfplumber`, `pytesseract`).
- **Output JSON Structure**:
  - Top-level object keys (`state_manager.py` lines 24–31): `version`, `anno`, `ultimo_municipio_procesado`, `municipios_completados`, `localidades_completadas`, `fiestas`.
  - Festival record keys: `id`, `lugar_id`, `nombre`, `fecha_inicio`, `fecha_fin`, `tamano`, `descripcion`, `confianza`, `origen`, `es_estimada`, `incluye_dia_patron`, `fuentes`, `solo_fuentes_no_oficiales`, `patron`, `lat`, `lng`, `programa`.
  - Non-estimated festivals (`es_estimada: false`, `origen: "extraccion"`) vs. Estimated fallback festivals (`es_estimada: true`, `origen: "santo_patron"`).
  - `programa` array schema (`text_analyzer.py` lines 1370–1380): List of objects containing `dia` (int), `fecha` (YYYY-MM-DD), `eventos` (list of `{ "hora": "HH:MM", "descripcion": "..." }`).

---

## 2. Logic Chain

1. **Observation**: `main.py` parses CLI arguments `--input`, `--output`, `--anno`, `--parallel` and invokes `process_municipio` for each uncompleted root municipality ID found in `lugares_espana.json`.
2. **Observation**: In `lugares_espana.json`, Amurrio is defined by root ID `"01002000000"` with 9 child entities, including capital `"01002000201"`.
3. **Logic Step**: To run a test extraction specifically for Amurrio without processing all 8,000+ municipalities or corrupting existing `fiestas_espana.json`, a Worker must construct an isolated input JSON containing only root ID `"01002000000"` and its 9 descendants, then launch `main.py --input test_amurrio_input.json --output test_amurrio_output.json --parallel 1`.
4. **Observation**: RAG pipeline fixes (R1, R2, R3) enable proper indexing, geographic filtering, and sister locality exclusion.
5. **Logic Step**: Successful verification of R4 requires inspecting `test_amurrio_output.json` to confirm that:
   - Amurrio capital (`01002000201`) has at least one extracted festival record where `es_estimada == False` and `origen == "extraccion"`.
   - The extracted festival record contains a non-empty `programa` list (`len(programa) > 0`) with valid daily event objects (`dia`, `fecha`, `eventos` containing `hora` and `descripcion`).

---

## 3. Caveats

- **LM Studio Server Requirement**: The test run requires an active local LM Studio instance listening at `http://localhost:1234` with the specified chat/reasoning and embedding models loaded. If LM Studio is not running or lacks VRAM, calls to `llm_chat_json` or embeddings will fail or fall back.
- **Web Network Access**: DuckDuckGo web searches and web spidering require active internet access. If search results are blocked, search failover or local cached fallbacks will execute.

---

## 4. Conclusion

The execution mechanism, input/output schemas, and worker verification procedures for Requirement R4 are fully specified and documented:
- Entry script: `main.py` with arguments `--anno`, `--input`, `--output`, `--parallel`.
- Isolated test input strategy: Construct `test_amurrio_input.json` containing municipality `"01002000000"` and its 9 child entities.
- Verification target: Output JSON `test_amurrio_output.json` must contain authentic festivals (`es_estimada: false`, `origen: "extraccion"`) with non-empty, structured `programa` arrays for Amurrio.

---

## 5. Verification Method

To verify this setup independently:

1. **Inspect Detailed Investigation File**:
   Read `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\explorer_survey_3\analysis.md`.

2. **Test Command Execution**:
   Run the following Python script to generate an isolated Amurrio input file and verify schema extraction readiness:
   ```bash
   python -c "import json; data = json.load(open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', encoding='utf-8-sig')); amurrio = [l for l in (data.get('lugares', data) if isinstance(data, dict) else data) if l.get('id') == '01002000000' or l.get('padre_id') == '01002000000']; print(f'Amurrio entities found: {len(amurrio)}')"
   ```
   **Expected Output**: `Amurrio entities found: 10`.

3. **Output File Verification Protocol**:
   After executing `main.py --input test_amurrio_input.json --output test_amurrio_output.json --parallel 1`, verify that:
   - `test_amurrio_output.json` exists.
   - At least one record has `"lugar_id": "01002000201"`, `"es_estimada": false`, `"origen": "extraccion"`.
   - `len(record["programa"]) > 0`.

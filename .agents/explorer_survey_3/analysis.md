# Detailed Technical Investigation: Execution & Verification Setup for Requirement R4

## 1. Executive Summary

This report presents a complete investigation of the execution, configuration, data structures, and verification setup for **Requirement R4** within the `Fase2_Extraccion_Fiestas` pipeline. 

Requirement R4 dictates that the festival extraction pipeline must be run on a sample municipality (e.g., **Amurrio**, INE ID `01002000000`) to verify that the RAG pipeline fixes (R1, R2, R3) successfully extract authentic, non-estimated festivals (`es_estimada: false`, `origen: "extraccion"`) with complete, populated `programa` arrays (`len(programa) > 0`).

---

## 2. Entry Scripts, CLI Arguments, Inputs/Outputs, and Config Settings

### 2.1 Entry Script
- **File Path**: `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/main.py`
- **Execution Engine**: Python 3.11+ using `asyncio.run(async_main())`.

### 2.2 CLI Arguments
`main.py` uses `argparse` with the following parameters:

| Argument | Type | Default Value | Description |
|---|---|---|---|
| `--anno` | `int` | `2026` | Target year for search and extraction. |
| `--input` | `str` | `../Fase1_recogida_datos_wiki/lugares_espana.json` | Path to input JSON containing INE place hierarchy. |
| `--output` | `str` | `fiestas_espana.json` | Destination path for extracted festival state JSON. |
| `--parallel` | `int` | `5` (via `PARALLEL_MUNICIPALITIES`) | Number of root municipalities processed concurrently. |

### 2.3 Input Data Structure (`lugares_espana.json`)
The input JSON can be formatted either as a top-level JSON array `[...]` or as a wrapper object `{"version": 2, "lugares": [...]}`. 

#### Hierarchy Rules (INE-First Architecture):
1. **Root Nodes (`tipo: "municipio"`)**: Represent the administrative container (11-digit INE ID, e.g., `"01002000000"` for Amurrio). Root nodes **never** have a `padre_id` and **never** store festivals directly.
2. **Child Population Entities (`tipo`: `"pueblo"`, `"ciudad_pequena"`, `"ciudad_grande"`)**: Always belong to a root municipality via `padre_id`. Exactly one child entity is designated as the capital (`es_capital: true`).
3. **Subdivisions (`tipo`: `"distrito"`, `"barrio"`)**: Secondary urban structures. Distritos belong to cities via `padre_id`. Barrios belong to distritos or cities; if belonging to a distrito, they contain `abuelo_id` referencing the capital city entity.

#### Sample Input Data: Amurrio (`01002000000`)
Amurrio consists of 1 root municipality node and 9 child population entities (`pueblo`):

- `01002000000`: Amurrio (`tipo`: `"municipio"`, root node)
- `01002000201`: Amurrio (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `true`) — Population: 9,256
- `01002000101`: Aloria (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002000301`: Artomaña (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002000501`: Baranbio (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002000601`: Delika (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002000701`: Larrinbe (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002000801`: Lekamaña (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002001101`: Saratxo (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)
- `01002001201`: Tertanga (`tipo`: `"pueblo"`, `padre_id`: `"01002000000"`, `es_capital`: `false`)

### 2.4 Environment & System Requirements
- **Python Runtime**: Python 3.11 or 3.12.
- **Python Libraries**: `aiohttp`, `beautifulsoup4`, `pytesseract`, `pdfplumber`, `Pillow`, `requests`, `fasttext` (`lid.176.ftz`).
- **System Software**:
  - **Tesseract OCR**: Binary installed and accessible in system `PATH`.
  - **LM Studio Local LLM Server**: Running on `http://localhost:1234` (or host IP if executing under WSL).
    - **Chat / Reasoning Model**: `qwen2.5-7b-instruct` or `prism-ml/bonsai-27b` (32k context window recommended).
    - **Embedding Model**: `text-embedding-nomic-embed-text-v1.5` or `text-embedding-baai-bge-m3-568m`.

### 2.5 Config Parameters (`config.py`)
- `LMSTUDIO_BASE_URL`: `"http://localhost:1234"` (Auto-detects Windows host IP if running under WSL).
- `LMSTUDIO_EMBEDDING_URL`: `"{LMSTUDIO_BASE_URL}/v1/embeddings"`.
- `LMSTUDIO_CHAT_URL`: `"{LMSTUDIO_BASE_URL}/v1/chat/completions"`.
- `RAG_MAX_TOKENS`: `30000` (~78,000 characters context budget).
- `RAG_CHUNK_SIZE`: `1200` characters.
- `RAG_UMBRAL_SIMILITUD`: `0.35` cosine similarity threshold.
- `RAG_EMBEDDING_BATCH_SIZE`: `20`.
- `PATRON_SEARCH_ENABLED`: `True`.
- `PATRON_CACHE_FILE`: `"patrones_cache.json"`.

---

## 3. Pipeline Execution & State Management Flow

### 3.1 Execution Workflow
1. `main.py` parses arguments and loads places from `--input`.
2. `agrupar_municipios_y_descendientes` groups child entities under their respective root municipality IDs.
3. `StateManager` loads pre-existing state from `--output` if present, identifying already completed municipalities (`municipios_completados`) and completed localities (`localidades_completadas`).
4. Municipalities are dispatched in parallel batches (`--parallel`).
5. For each municipality (`process_municipio`):
   - A single pre-crawl of the municipal official website is executed and cached (`docs_municipio_cache`).
   - Each child locality is processed sequentially (`process_locality`).
   - For each child locality:
     - Step 0: Patron saint lookup runs concurrently (`obtener_patron`).
     - Steps 1-5: Web crawling, official documents, social content, and DuckDuckGo search.
     - Multi-Pass RAG Architecture (`analyze_festivals_multipass`):
       1. `index_document_chunks`: Chunks documents and computes vector embeddings in batches once per locality.
       2. `retrieve_discovery_context`: Retrieves top 10-15 chunks (~15,000 chars) for Discovery Pass.
       3. `discover_festivals_for_locality`: LLM identifies basic festival metadata.
       4. `enrich_festival_program`: For each discovered festival, generates daily search queries, retrieves targeted chunks, and prompts LLM to generate the detailed `programa` array.
     - `integrar_patron`: Marks festivals covering patron day (`incluye_dia_patron: true`). If no festival covers patron day, inserts an estimated fallback festival (`es_estimada: true`, `origen: "santo_patron"`).
     - State saved atomically to `--output` via `guardar_estado_localidad`.

---

## 4. Output JSON Structure & Schema Definition

### 4.1 Root Output Schema (`fiestas_espana.json`)
```json
{
  "version": 2,
  "anno": 2026,
  "ultimo_municipio_procesado": "01002000000",
  "municipios_completados": [
    "01002000000"
  ],
  "localidades_completadas": [
    "01002000101",
    "01002000201",
    "01002000301",
    "01002000501",
    "01002000601",
    "01002000701",
    "01002000801",
    "01002001101",
    "01002001201"
  ],
  "fiestas": [
    /* Array of festival objects */
  ]
}
```

### 4.2 Non-Estimated Festival Object Schema (`es_estimada: false`)
When RAG successfully extracts an authentic festival, the object field structure is as follows:

```json
{
  "id": "fiestas-patronales-de-san-roque-01002000201",
  "lugar_id": "01002000201",
  "nombre": "Fiestas Patronales de San Roque",
  "fecha_inicio": "2026-08-12",
  "fecha_fin": "2026-08-16",
  "tamano": "grande",
  "descripcion": "Fiestas mayores de Amurrio en honor a San Roque y San Antonio con verbenas, chupinazo y actos tradicionales.",
  "confianza": "alta",
  "origen": "extraccion",
  "es_estimada": false,
  "incluye_dia_patron": true,
  "fuentes": [
    "web_municipio",
    "busqueda_web"
  ],
  "solo_fuentes_no_oficiales": false,
  "patron": {
    "nombre": "San Roque",
    "dia": 16,
    "mes": 8,
    "fuente": "wikipedia"
  },
  "lat": 43.05265767,
  "lng": -3.001015194,
  "programa": [
    {
      "dia": 1,
      "fecha": "2026-08-12",
      "eventos": [
        {
          "hora": "12:00",
          "descripcion": "Lanzamiento del chupinazo y pregón en la plaza del Ayuntamiento."
        },
        {
          "hora": "23:00",
          "descripcion": "Gran verbena a cargo de la Orquesta Pasarela."
        }
      ]
    },
    {
      "dia": 2,
      "fecha": "2026-08-13",
      "eventos": [
        {
          "hora": "11:00",
          "descripcion": "Pasacalles y alborada con trikitilaris."
        },
        {
          "hora": "18:00",
          "descripcion": "Concurso gastronómico de marmitako."
        }
      ]
    }
  ]
}
```

### 4.3 Estimated Fallback Festival Object Schema (`es_estimada: true`)
If no authentic festival is found for a locality, the patron saint integrator injects an estimated fallback record:

```json
{
  "id": "patron-san-roque-01002000201",
  "lugar_id": "01002000201",
  "nombre": "Fiestas de San Roque (estimada)",
  "fecha_inicio": "2026-08-16",
  "fecha_fin": "2026-08-16",
  "tamano": "pequeña",
  "descripcion": "Fiesta anual estimada a partir del día del santo patrón de Amurrio (San Roque, 16 de agosto). No se encontró programa ni confirmación para este año.",
  "confianza": "baja",
  "origen": "santo_patron",
  "es_estimada": true,
  "incluye_dia_patron": true,
  "fuentes": [],
  "solo_fuentes_no_oficiales": false,
  "patron": {
    "nombre": "San Roque",
    "dia": 16,
    "mes": 8,
    "fuente": "wikipedia"
  },
  "lat": 43.05265767,
  "lng": -3.001015194,
  "programa": []
}
```

---

## 5. Worker Test Run Initiation and Verification Guide

To allow a Worker agent to initiate and independently verify a test run for Requirement R4 (using Amurrio as the target municipality):

### Step 1: Create Isolated Input JSON (`test_amurrio_input.json`)
Extract Amurrio municipality (`"01002000000"`) and its 9 child entities from `lugares_espana.json`:

```python
import json

with open("../Fase1_recogida_datos_wiki/lugares_espana.json", "r", encoding="utf-8-sig") as f:
    data = json.load(f)

lugares = data.get("lugares", data) if isinstance(data, dict) else data

amurrio_nodes = [
    l for l in lugares 
    if l.get("id") == "01002000000" or l.get("padre_id") == "01002000000"
]

with open("test_amurrio_input.json", "w", encoding="utf-8") as f:
    json.dump({"version": 2, "lugares": amurrio_nodes}, f, ensure_ascii=False, indent=2)
```

### Step 2: Initiate Test Run Command
Execute `main.py` pointing to the isolated test input and test output files:

```bash
python main.py --anno 2026 --input test_amurrio_input.json --output test_amurrio_output.json --parallel 1
```

### Step 3: Worker Verification Protocol (6 Checks)

The Worker must verify all 6 criteria on `test_amurrio_output.json`:

1. **File Generation Check**: `test_amurrio_output.json` exists and parses cleanly as valid JSON.
2. **Completion State Check**: `"01002000000"` is in `municipios_completados` and all 9 child locality IDs are in `localidades_completadas`.
3. **Extraction Authenticity Check**: At least one festival object associated with Amurrio capital (`01002000201`) has:
   - `es_estimada == False`
   - `origen == "extraccion"`
4. **`programa` Array Population Check**:
   - `len(festival["programa"]) > 0`
   - Each day in `programa` contains valid `dia` (int), `fecha` (YYYY-MM-DD), and `eventos` (non-empty list).
   - Each event contains `hora` (HH:MM string) and `descripcion` (string).
5. **Geographical Exclusivity Check**:
   - Sister locality names (Aloria, Artomaña, Baranbio, Delika, Larrinbe, Lekamaña, Saratxo, Tertanga) do not leak into the capital's extracted festivals.
6. **Execution Metrics Check**:
   - Summary log shows `ratio_extraidas_vs_estimadas > 0` and total extracted festivals > 0.

---

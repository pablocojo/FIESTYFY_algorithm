# Fase 2: Extracción de Fiestas (Async, Paralelo)

Segunda fase del algoritmo Fiestyfy. Extrae fiestas de las subdivisiones (distritos, barrios, pedanías) de los municipios generados en la Fase 1, usando un pipeline de **Web Crawling → OCR → RAG → LLM**.

> **Nota Crítica:** Nunca se investigan los municipios raíz en busca de fiestas propias. Únicamente se extraen fiestas para sus localidades menores.

---

## 🚀 Arquitectura (v2 — Async + Paralelo)

```
                    ┌──────────────────────────────────────┐
                    │   main.py (Orquestador Async)        │
                    │   - Carga lugares_espana.json        │
                    │   - Agrupa por municipio              │
                    │   - Procesa N municipios en paralelo  │
                    └────────────┬─────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
     │ Municipio A  │    │ Municipio B  │    │ Municipio C  │  (en paralelo)
     │  Loc 1 → ... │    │  Loc 1 → ... │    │  Loc 1 → ... │
     │  Loc 2 → ... │    │  Loc 2 → ... │    │  Loc 2 → ... │
     └─────────────┘    └─────────────┘    └─────────────┘
              │
    Por cada localidad (secuencial dentro del municipio):
              │
              ▼
     ┌─────────────────────────────────────────────┐
     │  1. AsyncTwoPassSpider (aiohttp, sem=10)    │
     │     - Pasada 1: BFS concurrente, puntúa     │
     │     - Pasada 2: OCR/PDF con filtro smart    │
     ├─────────────────────────────────────────────┤
     │  2. DuckDuckGo Search (3 queries)           │
     │     - Sigue top 5 URLs → contenido completo │
     ├─────────────────────────────────────────────┤
     │  3. RAG (batch embeddings, ~27k tokens)     │
     │     - Chunks 1200 chars, overlap 200        │
     │     - Saturación por similitud coseno       │
     ├─────────────────────────────────────────────┤
     │  4. Qwen 2.5 7B (LM Studio)                │
     │     - Criterio de fiestas inyectado         │
     │     - JSON estructurado con programa        │
     ├─────────────────────────────────────────────┤
     │  5. Validación post-LLM                     │
     │     - lugar_id, fechas, año, slug           │
     │     - Deduplicación                         │
     └─────────────────────────────────────────────┘
```

---

## 🗂️ Estructura de Archivos

```
Fase2_Extraccion_Fiestas/
├── main.py                  # Orquestador async
├── config.py                # Constantes configurables
├── state_manager.py         # Persistencia thread-safe
├── scraper/
│   ├── heuristic_spider.py  # Spider async de 2 pasadas
│   ├── document_extractor.py # OCR + PDF con filtrado smart
│   └── google_search.py     # Búsqueda DDG multi-query
└── llm_processor/
    └── text_analyzer.py     # RAG + LLM + validación
```

---

## 🗂️ Estructura del JSON de Salida

```jsonc
{
  "id": "verbena-la-latina",
  "lugar_id": "madrid-la-latina",
  "nombre": "Verbena de La Paloma",
  "fecha_inicio": "2026-08-13",
  "fecha_fin": "2026-08-15",
  "tamano": "grande",
  "descripcion": "...",
  "confianza": "alta",
  "programa": [
    {
      "dia": 1,
      "fecha": "2026-08-13",
      "eventos": [
        { "hora": "20:00", "descripcion": "Pregón y chupinazo" },
        { "hora": "22:30", "descripcion": "Orquesta en la plaza" }
      ]
    }
  ]
}
```

---

## ⚙️ Requisitos e Instalación

**Dependencias Python:**
```bash
pip install aiohttp beautifulsoup4 pytesseract pdfplumber Pillow requests
```

**Software del sistema:**
- Tesseract-OCR instalado y en el PATH
- LM Studio ejecutándose en `http://localhost:1234` con:
  - Modelo de Embeddings: `text-embedding-nomic-embed-text-v1.5`
  - Modelo de Chat: `qwen2.5-7b-instruct`

---

## 🚀 Ejecución

```bash
python main.py --anno 2026 --input ../lugares_espana.json --output fiestas_espana.json --parallel 4
```

| Flag | Default | Descripción |
|------|---------|-------------|
| `--anno` | 2026 | Año de búsqueda de fiestas |
| `--input` | `../lugares_espana.json` | JSON de lugares (Fase 1) |
| `--output` | `fiestas_espana.json` | JSON de salida |
| `--parallel` | 4 | Municipios procesados en paralelo |

El orquestador reanuda automáticamente desde el último municipio procesado si el archivo de salida ya existe.

---

## 📈 Mejoras de Rendimiento vs v1

| Dimensión | v1 (anterior) | v2 (actual) |
|-----------|:------------:|:-----------:|
| Spider | Secuencial (requests) | Async (aiohttp, 10 concurrentes) |
| OCR | Todas las imágenes | Solo carteles >30KB, >300x200px |
| Búsqueda DDG | 1 query, solo snippets | 3 queries + sigue top 5 URLs |
| Embeddings | 1 petición por chunk | Batch de 20 chunks |
| Municipios | 1 a la vez | 4 en paralelo |
| Modelo | Llama 3.2 3B | Qwen 2.5 7B |
| Validación | Solo lugar_id | Fechas, schema, deduplicación |
| Logging | print() | logging a consola + archivo |

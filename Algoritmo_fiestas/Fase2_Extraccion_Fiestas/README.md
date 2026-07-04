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
     │  0. Santo Patrón (paralelo al scraping)     │
     │     - Caché → Wikipedia → buscadores → LLM  │
     │     - Fecha fija resuelta contra SANTORAL   │
     ├─────────────────────────────────────────────┤
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
     │  4. LLM local (LM Studio)                   │
     │     - Criterio de fiestas inyectado         │
     │     - JSON estructurado con programa        │
     ├─────────────────────────────────────────────┤
     │  5. Validación post-LLM                     │
     │     - lugar_id, fechas, año, slug           │
     │     - Saneado (nombre, duración, programa)  │
     │     - Filtro adaptativo por duración        │
     │     - Deduplicación                         │
     ├─────────────────────────────────────────────┤
     │  6. Integración del patrón                  │
     │     - Marca fiestas que incluyen su día     │
     │     - Fiesta estimada si no está cubierto   │
     └─────────────────────────────────────────────┘
```

---

## 🙏 Paso del Santo Patrón

Para cada localidad se busca su santo patrón (Wikipedia → buscadores → LLM local como
fallback) y se resuelve su **día fijo del calendario** contra un santoral estático de
+200 patrones comunes de España (`llm_processor/patron_finder.py`). Si la fecha del texto
discrepa del santoral, prevalece el santoral. El resultado se guarda en
`patrones_cache.json` (incluidos los "no encontrado") para no repetir búsquedas.

Con el día del patrón en el año objetivo:
- Toda fiesta extraída cuyo rango de fechas **incluya el día del patrón** se marca con
  `incluye_dia_patron: true` y el objeto `patron`.
- Si **ninguna** fiesta cubre ese día (incluido el caso de 0 fiestas), se añade una
  **fiesta estimada** de un día (`origen: "santo_patron"`, `es_estimada: true`,
  `confianza: "baja"`), garantizando que casi toda localidad tenga al menos la fecha
  en que suele celebrar sus fiestas.

---

## 🚦 Filtro adaptativo por duración (`llm_processor/festival_filter.py`)

- **Multi-día** (`fecha_inicio < fecha_fin`) — filtro regular: basta una señal de tipo
  fiesta (patronales, feria, carnaval...), una señal nocturna o un programa con ≥2 eventos.
- **Un solo día** — filtro estricto: requiere señal nocturna fuerte (orquesta, verbena,
  DJ, discomóvil, concierto...). Excepción: nombre claramente patronal o coincidencia
  con el día del patrón → se acepta con `confianza: "baja"`. Así se eliminan procesiones,
  misas y exposiciones sueltas.
- **Eventos privados** (discoteca, pub, sala de fiestas como local): rechazados. Solo
  celebraciones populares de la localidad abiertas a todo el mundo.
- **Saneado**: nombres genéricos ("Fiesta"), duraciones > 30 días y días de programa
  fuera del rango de la fiesta se corrigen o descartan.

---

## 🗂️ Estructura de Archivos

```
Fase2_Extraccion_Fiestas/
├── main.py                  # Orquestador async
├── config.py                # Constantes configurables
├── state_manager.py         # Persistencia thread-safe
├── patrones_cache.json      # Caché de santos patrones (autogenerado)
├── scraper/
│   ├── heuristic_spider.py  # Spider async de 2 pasadas
│   ├── document_extractor.py # OCR + PDF con filtrado smart
│   └── google_search.py     # Búsqueda DDG multi-query
├── llm_processor/
│   ├── text_analyzer.py     # RAG + LLM + validación
│   ├── festival_filter.py   # Filtro adaptativo + saneado de fiestas
│   └── patron_finder.py     # Santo patrón: santoral + Wikipedia + buscadores
└── tests_fase2/             # Tests unitarios (pytest)
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
  "origen": "extraccion",          // "extraccion" | "santo_patron"
  "es_estimada": false,            // true si es la fiesta estimada por el día del patrón
  "incluye_dia_patron": true,      // true si el día del patrón cae dentro del rango
  "patron": {                      // presente solo si se halló el patrón
    "nombre": "Virgen de la Paloma",
    "dia": 15, "mes": 8,
    "fuente": "wikipedia"          // "wikipedia" | "busqueda" | "llm"
  },
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

Cuando ninguna fiesta cubre el día del patrón, se añade un registro estimado de un día:
`nombre: "Fiestas de <Patrón> (estimada)"`, `fecha_inicio == fecha_fin`, `programa: []`,
`origen: "santo_patron"`, `es_estimada: true`, `confianza: "baja"`.

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
python main.py --anno 2026 --input ../Fase1_recogida_datos_wiki/lugares_espana.json --output fiestas_espana.json --parallel 4
```

| Flag | Default | Descripción |
|------|---------|-------------|
| `--anno` | 2026 | Año de búsqueda de fiestas |
| `--input` | `../lugares_espana.json` | JSON de lugares (Fase 1) |
| `--output` | `fiestas_espana.json` | JSON de salida |
| `--parallel` | 4 | Municipios procesados en paralelo |

El orquestador reanuda automáticamente desde el último municipio procesado si el archivo de salida ya existe.

**Tests unitarios** (filtro adaptativo, santoral, integración del patrón):
```bash
python -m pytest tests_fase2/ -q
```

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

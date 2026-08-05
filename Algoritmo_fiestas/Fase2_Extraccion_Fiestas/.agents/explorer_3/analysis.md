# Comprehensive Technical Analysis: Multi-Pass RAG Verification Architecture & Test Specifications

**Author**: Explorer 3 (teamwork_preview_explorer)  
**Date**: 2026-08-05  
**Target Architecture**: Fiestyfy Multi-Pass RAG Festival Extraction Engine (`text_analyzer.py`, `main.py`)  
**Working Directory**: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`

---

## 1. Executive Summary

This report provides the full architectural analysis and technical specifications for verifying the new **Multi-Pass RAG (Discovery Pass & Enrichment Pass)** architecture in the Fiestyfy festival extraction system.

The core motivation behind the Multi-Pass RAG architecture is to eliminate LLM context overflow errors (`ContextOverflowError`) when processing large document sets for Spanish municipalities while maintaining high festival extraction quality. 

- **Discovery Pass**: Queries general festival concepts for a locality, retrieving top 10–15 chunks (~15,000 characters ≈ 5.8K tokens) to generate an initial JSON list of festivals (name, start date, end date, size).
- **Enrichment Pass**: Iterates over each discovered festival and generates day-by-day search queries (`"{nombre_fiesta} {fecha_dia} programa actos"`). It retrieves 1–3 chunks per day, deduplicates them, and sends a focused context payload to the LLM to enrich the initial JSON with detailed event programs.

This document details:
1. Exact logic and edge cases for day-by-day query generation (cross-month, cross-year, leap years, single-day, and capped long spans).
2. Token counting dynamics, prompt overhead, and simulation parameters ensuring all LLM calls stay well under the 32K context window (targeting < 12K tokens per request).
3. Project test patterns and mock data structures.
4. Specifications for two isolated, runnable test scripts:
   - **Test 1**: `test_enrichment_query_generation.py` (Date range expansion & query format verification).
   - **Test 2**: `test_rag_token_limit_simulation.py` (Multi-pass token count simulation & budget cap verification).

---

## 2. Analysis of Day-by-Day Query Construction for Enrichment

### 2.1 Date Range Iteration Mechanics
In the Enrichment Pass, each festival returned by the Discovery Pass contains ISO 8601 date strings:
- `fecha_inicio`: `"YYYY-MM-DD"`
- `fecha_fin`: `"YYYY-MM-DD"`

To query embedding indices for each day of the festival, the system must parse these strings into `datetime.date` objects, iterate chronologically day by day using `datetime.timedelta(days=1)`, and format query strings.

```python
from datetime import datetime, timedelta

def date_range(start_date: datetime.date, end_date: datetime.date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)
```

### 2.2 Query String Format
Per Requirement R1, the query string for each day must incorporate the festival name, the specific day date, and keywords indicating an event program:
```python
query_str = f"{nombre_fiesta} {fecha_dia_str} programa actos"
```
Example output:
`"Fiestas de San Roque 2026-08-28 programa actos"`

### 2.3 Edge Case Analysis & Technical Requirements

| Edge Case Scenario | Inputs (`fecha_inicio`, `fecha_fin`) | Expected Day Sequence | Handling Logic |
| :--- | :--- | :--- | :--- |
| **1. Standard Intra-Month** | `2026-08-10` to `2026-08-14` | Aug 10, 11, 12, 13, 14 (5 days) | Standard loop within single month. |
| **2. Cross-Month Span** | `2026-08-28` to `2026-09-03` | Aug 28, 29, 30, 31, Sep 01, 02, 03 (7 days) | `timedelta(days=1)` handles month boundaries seamlessly (31 days in Aug). |
| **3. Cross-Year Span** | `2026-12-29` to `2027-01-03` | Dec 29, 30, 31, Jan 01, 02, 03 (6 days) | `timedelta(days=1)` advances year from 2026 to 2027 automatically. |
| **4. Leap Year (Feb 29)** | `2028-02-27` to `2028-03-02` (2028 is leap) | Feb 27, 28, 29, Mar 01, 02 (5 days) | Python `datetime.date` natively handles Feb 29 in leap years. |
| **5. Non-Leap Year (Feb)** | `2026-02-27` to `2026-03-02` (2026 non-leap) | Feb 27, 28, Mar 01, 02 (4 days) | Python `datetime.date` skips Feb 29 for non-leap year. |
| **6. Single-Day Festival** | `2026-08-15` to `2026-08-15` | Aug 15 (1 day) | `start == end` loop produces exactly 1 day query. |
| **7. Excessively Long Span** | `2026-01-01` to `2026-12-31` (365 days) | Capped at first 30 days (Aug 1 - Aug 30) | Safety cap rule: truncate span to `FIESTA_MAX_DURACION_DIAS` (30 days) to prevent query explosion. |
| **8. Inverted Dates** | `2026-08-15` to `2026-08-10` | Aug 10 to Aug 15 (after swap) | Swap `fecha_inicio` and `fecha_fin` if `fecha_inicio > fecha_fin`. |
| **9. Malformed Date Format** | `"2026/08/10"`, `None`, `""` | Fallback / Skip | Wrap parsing in `try/except ValueError` and return empty/safe query list. |

---

## 3. Analysis of Token Counting & Context Limit Simulation

### 3.1 Context Limit & Token Ratios
- **LM Studio Model Window**: Qwen 2.5 7B loaded with `n_ctx = 32,768 tokens` (32K tokens).
- **Target Context Budget**: All LLM requests must remain **well under 32K tokens** (specifically **< 12K tokens** per request).
- **Character-to-Token Ratio**: In `config.py`, `RAG_CHARS_PER_TOKEN = 2.6`.
  $$\text{Tokens} \approx \frac{\text{Character Count}}{2.6}$$

### 3.2 Token Budget Breakdown

#### Pass 1: Discovery Pass
- **Objective**: Identify general list of festivals in locality.
- **Context Selection**: Top 10–15 chunks from document pool.
- **Character Limit**: Capped at `15,000` chars (~5,769 tokens).
- **System + User Prompt Overhead**: ~2,000 chars (~769 tokens).
- **Total Discovery Pass Input Tokens**:
  $$\text{Discovery Tokens} = \frac{15000 + 2000}{2.6} \approx \mathbf{6,538\text{ tokens}} \quad (< 12\text{K tokens})$$
- **Expected LLM Output Tokens**: ~1,500 tokens (JSON list of 1–5 festivals).

#### Pass 2: Enrichment Pass
- **Objective**: Enrich a single discovered festival with day-by-day event programs.
- **Retrieval Strategy**: 1–3 chunks per day for each day in festival range.
- **Average Chunk Size**: `RAG_CHUNK_SIZE = 1200` chars (~461 tokens).
- **Scenario A (Standard 5-Day Festival)**:
  - 5 days $\times$ 2 chunks/day = 10 chunks.
  - Undeduplicated text size: $10 \times 1200 = 12,000$ chars.
  - After deduplication across overlapping days: ~9,600 chars (~3,692 tokens).
  - System Prompt + Initial Festival JSON Overhead: ~2,500 chars (~961 tokens).
  - Total Input Tokens: $\approx \mathbf{4,653\text{ tokens}} \quad (< 12\text{K tokens})$.
- **Scenario B (Heavy 15-Day Festival)**:
  - 15 days $\times$ 3 chunks/day = 45 chunks $\rightarrow$ Raw $45,000$ chars (~17,307 tokens).
  - **Enrichment Context Cap**: `ENRICHMENT_MAX_CHARS = 25,000` chars (~9,615 tokens).
  - Total Input Tokens: $\frac{25000 + 2500}{2.6} \approx \mathbf{10,576\text{ tokens}} \quad (< 12\text{K tokens})$.

### 3.3 Token Protection Mechanisms
To guarantee that the 12K target and 32K hard limit are never exceeded:
1. **Global Character Budget Cap**: Enforce `ENRICHMENT_MAX_CHARS = 25000` when assembling context for enrichment.
2. **Chunk Deduplication**: Use chunk content hashing (`hash(chunk["chunk"])` or exact text matching) so identical chunks retrieved across multiple days are only included once.
3. **Max Days Cap**: Limit date range iteration to a maximum of 30 days (`FIESTA_MAX_DURACION_DIAS`).
4. **Fallback Context Truncation**: Re-use `text_analyzer.py`'s line-boundary truncation loop `for factor in (1.0, 0.7, 0.5)` if `ContextOverflowError` is encountered.

---

## 4. Project Test Patterns & Data Structures

### 4.1 Test Suite Location & Conventions
- Unit and integration tests reside in `tests_fase2/`.
- Utility/empirical scripts reside in `scratch/`.
- Isolated test scripts must be self-contained, using `pytest` standard assertions, clean function names (`test_*`), and optional standalone execution support (`if __name__ == "__main__":`).

### 4.2 Standard Data Structures in `Fase2_Extraccion_Fiestas`

```python
# 1. Locality & Municipality Dicts
LOCALIDAD = {
    "id": "01049000201",
    "nombre": "Salinas de Añana",
    "tipo": "pueblo",
    "es_capital": True
}

MUNICIPIO = {
    "id": "01049",
    "nombre": "Añana",
    "provincia": "Araba/Álava",
    "comunidad_autonoma": "País Vasco"
}

# 2. Festival Dict (Discovery Pass Output)
FIESTA_DISCOVERED = {
    "id": "fiestas-de-san-roque-01049000201",
    "lugar_id": "01049000201",
    "nombre": "Fiestas de San Roque",
    "fecha_inicio": "2026-08-28",
    "fecha_fin": "2026-09-03",
    "tamano": "pequeña",
    "descripcion": "Fiestas patronales en honor a San Roque."
}

# 3. Document Chunk Dict (Vector Store / RAG Item)
CHUNK_ITEM = {
    "chunk": "El 28 de agosto comienzan las fiestas con el txupinazo a las 12:00h...",
    "fuente": "web_municipio",
    "url": "https://anana.eus/fiestas-2026",
    "es_calendario": False,
    "prioridad": 1,
    "score": 0.85
}
```

---

## 5. Detailed Specifications for Isolated Verification Test Scripts

The acceptance criteria require two isolated Python verification scripts. Below are their complete technical specifications.

---

### 5.1 Specification for Test 1: `test_enrichment_query_generation.py`

- **File Path**: `tests_fase2/test_enrichment_query_generation.py`
- **Objective**: Verify that date range expansion and enrichment query construction correctly generate day-by-day queries for standard, cross-month, cross-year, leap-year, and single-day festival ranges, adhering to safety caps and formatting rules.

#### Function Under Test Specification:
```python
def generar_consultas_enriquecimiento(
    fiesta: dict,
    municipio_nombre: str,
    localidad_nombre: str,
    max_dias: int = 30
) -> list[tuple[str, str]]:
    """
    Dada una fiesta descubierta, genera una lista de tuplas (fecha_iso, query_str)
    para cada día en el rango [fecha_inicio, fecha_fin].
    
    Retorna [] si las fechas son inválidas.
    Limita la iteración a max_dias.
    """
```

#### Test Suite Test Cases:

1. **`test_intra_month_query_generation()`**:
   - Input: `fecha_inicio = "2026-08-10"`, `fecha_fin = "2026-08-14"` (5 days).
   - Assert: Returns 5 tuples.
   - Assert dates: `2026-08-10` through `2026-08-14`.
   - Assert query format: `"Fiestas de Agosto 2026-08-10 programa actos"`.

2. **`test_cross_month_query_generation()`**:
   - Input: `fecha_inicio = "2026-08-28"`, `fecha_fin = "2026-09-03"` (7 days).
   - Assert: Returns 7 tuples.
   - Assert dates sequence: `["2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"]`.

3. **`test_cross_year_query_generation()`**:
   - Input: `fecha_inicio = "2026-12-29"`, `fecha_fin = "2027-01-03"` (6 days).
   - Assert: Returns 6 tuples.
   - Assert dates sequence: `["2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03"]`.

4. **`test_leap_year_february_query_generation()`**:
   - Input (Leap Year 2028): `fecha_inicio = "2028-02-27"`, `fecha_fin = "2028-03-02"`.
   - Assert: Returns 5 tuples, including `"2028-02-29"`.
   - Input (Non-Leap Year 2026): `fecha_inicio = "2026-02-27"`, `fecha_fin = "2026-03-02"`.
   - Assert: Returns 4 tuples, skipping Feb 29.

5. **`test_single_day_query_generation()`**:
   - Input: `fecha_inicio = "2026-08-15"`, `fecha_fin = "2026-08-15"`.
   - Assert: Returns exactly 1 tuple (`"2026-08-15"`).

6. **`test_excessive_duration_capping()`**:
   - Input: `fecha_inicio = "2026-01-01"`, `fecha_fin = "2026-12-31"` (365 days).
   - Assert: Length of returned list is capped at `max_dias` (30).
   - Assert first date is `"2026-01-01"` and 30th date is `"2026-01-30"`.

7. **`test_inverted_and_malformed_dates()`**:
   - Inverted: `fecha_inicio = "2026-08-15"`, `fecha_fin = "2026-08-10"` $\rightarrow$ Auto-swaps and generates 6 days.
   - Malformed: `fecha_inicio = "invalid-date"` $\rightarrow$ Returns `[]`.

---

### 5.2 Specification for Test 2: `test_rag_token_limit_simulation.py`

- **File Path**: `tests_fase2/test_rag_token_limit_simulation.py`
- **Objective**: Simulate the multi-pass RAG workflow against synthetic mocked chunks to prove that token counts for both Discovery Pass and Enrichment Pass LLM requests remain strictly under the 32K context limit (targeting < 12K tokens).

#### Simulation Function Specification:
```python
def calcular_tokens_estimados(texto: str, chars_per_token: float = 2.6) -> int:
    """Calcula la estimación de tokens basada en caracteres."""
    return int(len(texto) / chars_per_token)

def simular_discovery_pass_payload(
    documentos_mock: list[dict],
    localidad: dict,
    municipio: dict,
    anno: int,
    max_chunks: int = 15,
    max_chars: int = 15000
) -> dict:
    """
    Simula la selección de chunks y ensamblado de prompt para el Discovery Pass.
    Retorna dict con 'context_chars', 'total_chars', 'estimated_tokens', 'pass_name'.
    """

def simular_enrichment_pass_payload(
    fiesta: dict,
    chunks_por_dia: dict[str, list[dict]],
    localidad: dict,
    municipio: dict,
    anno: int,
    max_chars_cap: int = 25000
) -> dict:
    """
    Simula el enriquecimiento de una fiesta: deduplica chunks entre días,
    aplica el límite duro de caracteres y ensambla el prompt final.
    Retorna dict con 'context_chars', 'total_chars', 'estimated_tokens', 'pass_name'.
    """
```

#### Test Suite Test Cases:

1. **`test_discovery_pass_token_limit()`**:
   - Generate 100 synthetic mock chunks (each ~1,200 chars).
   - Run `simular_discovery_pass_payload`.
   - Assert selected context length $\le 15,000$ characters.
   - Assert `estimated_tokens < 12000` (typically ~5,800 to 6,600 tokens).
   - Assert `estimated_tokens < 32768`.

2. **`test_enrichment_pass_standard_festival_tokens()`**:
   - Create a 7-day cross-month festival (`2026-08-28` to `2026-09-03`).
   - Mock 3 chunks (1,000 chars each) for each of the 7 days (21 chunks total, with 30% duplicate overlap).
   - Run `simular_enrichment_pass_payload`.
   - Assert `estimated_tokens < 12000` (typically ~5,000 to 7,500 tokens).

3. **`test_enrichment_pass_heavy_stress_tokens()`**:
   - Create a 25-day festival (`2026-08-01` to `2026-08-25`).
   - Mock 3 unique chunks (1,200 chars each) for all 25 days ($25 \times 3 \times 1200 = 90,000$ chars raw).
   - Run `simular_enrichment_pass_payload` with budget cap `max_chars_cap = 25000`.
   - Assert selected context length is capped at $\le 25,000$ characters.
   - Assert total prompt `estimated_tokens < 12000` (typically ~10,500 tokens).
   - Assert `estimated_tokens < 32768`.

4. **`test_token_ratio_consistency()`**:
   - Verify that token calculation function handles Spanish accents, numbers, URLs, and markdown code blocks accurately using `RAG_CHARS_PER_TOKEN = 2.6`.

---

## 6. Implementation Guidance & Execution Checklist

1. **Standalone Execution**:
   Both test files in `tests_fase2/` must include `pytest` tests and `if __name__ == "__main__":` blocks that run all tests using standard assertions and log key metrics to stdout.

2. **Execution Commands**:
   ```bash
   # Run via pytest
   pytest tests_fase2/test_enrichment_query_generation.py -v
   pytest tests_fase2/test_rag_token_limit_simulation.py -v

   # Direct python execution
   python tests_fase2/test_enrichment_query_generation.py
   python tests_fase2/test_rag_token_limit_simulation.py
   ```

3. **Zero Placeholders**:
   The implementer must ensure no `TODO`, `pass`, or dummy placeholders exist in the verification scripts or pipeline updates.

---

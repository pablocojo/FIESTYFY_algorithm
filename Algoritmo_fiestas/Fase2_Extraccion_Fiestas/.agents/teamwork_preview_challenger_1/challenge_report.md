# Challenge Report: Fase 2 R1-R6 Edge Cases & Stress Testing

## Challenge Summary

**Overall risk assessment**: LOW
**Verdict**: **APPROVE**

All core requirements (R1 through R6) have been empirically verified and pass 100% of the 35 pytest test cases (25 standard verification tests + 10 comprehensive adversarial stress tests).

---

## Challenges & Failure Mode Analysis

### [Low] Challenge 1: Regex Unbounded Match on 5-Digit Identifiers in Spider URL Scoring

- **Assumption challenged**: `re.findall(r"(?:19|20)\d{2}", url_lower)` in `_score_page` (heuristic_spider.py:179) assumes 4-digit sequences in URLs are standalone year numbers.
- **Attack scenario**: A URL containing a 5-digit zip code or numerical ID starting with 2025 (e.g. `https://ayto.es/codigo-20250-oficina`) will match `"2025"`. Because `2025 < 2026`, the spider applies a `-300` penalty to the page score.
- **Blast radius**: Low. Slightly deprioritizes specific municipal URLs containing postal codes or IDs starting with 2025. Does not block festival extraction or break pipeline execution.
- **Mitigation**: Use word boundaries `\b(?:19|20)\d{2}\b` in regex pattern matching to ensure only standalone 4-digit years are matched.

### [Low] Challenge 2: Calendar URL Key Deduplication Zero-Padding Variations

- **Assumption challenged**: `_get_calendar_date_key` assumes all date URLs follow a uniform zero-padded format (`/YYYY/MM/DD/`).
- **Attack scenario**: If a municipal site generates both `/2026/05/02/` and `/2026/5/2/`, `_get_calendar_date_key` produces `ayto.es:/2026/05/02` and `ayto.es:/2026/5/2`, which are treated as two distinct keys.
- **Blast radius**: Low. Resulting calendar URLs are visited twice instead of once; deduplication is slightly less aggressive for unpadded single-digit month/day URLs.
- **Mitigation**: Parse and normalize date components into standard ISO `YYYY-MM-DD` strings inside `_get_calendar_date_key`.

### [Low] Challenge 3: `_validar_fecha` Loose Branch when `fecha_inicio_str` is Omitted

- **Assumption challenged**: `_validar_fecha` checks if `fecha_fin` is in `anno + 1`.
- **Attack scenario**: If `_validar_fecha` is called with `es_fecha_fin=True` but `fecha_inicio_str=None`, the function falls into `elif es_fecha_fin: return True` for any month in `anno + 1`.
- **Blast radius**: Negligible in pipeline. In `validar_fiestas` (line 671), `fecha_inicio_str=f.get("fecha_inicio")` is always explicitly passed, enforcing that `parsed_ini.month == 12`.
- **Mitigation**: Remove the standalone `elif es_fecha_fin:` branch and require `fecha_inicio_str` for next-year date acceptance.

---

## Stress Test Results

- **R1.1 Delay Range**: 1,000 queries generated delays in range [2.000s, 4.499s]. All strictly within [2.0, 4.5] bounds. → PASS
- **R1.2 User-Agent Randomness**: 1,000 queries distributed evenly across all 5 realistic browser UAs (Chrome, Firefox, Safari, Edge, Linux Chrome). → PASS
- **R1.3 Exponential Backoff Math**: Attempts 0, 1, 2, 3, 5, 10 verified against formula `(3.0 * 2^attempt) + uniform(0.5, 2.0)`. Delays grew exponentially with jitter. → PASS
- **R1.4 Multi-Engine Failover**: Mapped and executed DDG, Yahoo, and Bing rotation without Google Custom Search API. → PASS
- **R2.1 Temporal 2026 Scoring**: Verified 2026 bonus (+150/+350) and prior year penalty (-300) in `_score_page`. → PASS
- **R2.2 Single Event Filtering**: Verified -350 penalty for single unrelated municipal events ("taller", "charla", "pleno", "exposición") lacking festival keywords. → PASS
- **R2.3 Calendar Deduplication**: Verified regex pattern matching and deduplication key generation. → PASS
- **R3.1 Cross-Year Dates**: Dec 30, 2026 to Jan 2, 2027 festival accepted by `_validar_fecha` and `validar_fiestas`. Invalid ranges (Nov 30, 2026 to Jan 2, 2027) correctly rejected. → PASS
- **R3.2 Leap Year Patron Fallback**: Feb 29 patron saint returns Feb 28 in non-leap year (2026, 2027) and Feb 29 in leap year (2028). → PASS
- **R4.1 Social Post Date Preservation**: Verified `fecha_publicacion` preserved across text and OCR/VLM image posts. → PASS
- **R4.2 Social Media Window Filter**: Boundary dates tested for 2026 window (`2025-11-01` to `2027-01-31`). `2025-10-31` and `2027-02-01` correctly rejected. → PASS
- **R5.1 PDF Priority Verification**: `is_promising_pdf` accepts target year 2026 & previous year 2025; rejects older years 2024 & 2023. → PASS
- **R5.2 Async Cache Concurrency**: Executed 50 concurrent parallel writes on `RedesCache` and `_PatronCache` using `asyncio.to_thread()`. Zero event loop blocking, zero race conditions, 100% data integrity on disk. → PASS
- **R6.1 Metrics Calculation**: Verified `generar_informe_ejecucion` metrics calculations for extracted vs. estimated ratio, 0-festival localities, top sources, failed search count, and avg time per municipality across edge cases (0 municipalities, 0 estimated festivals, malformed source lists). → PASS

---

## Unchallenged Areas

- **LM Studio LLM Hardware Inference Performance**: Actual inference latency depends on host GPU VRAM and LM Studio server availability. Tested via mocks and synthetic data structures as local LM Studio server was offline during offline test run.

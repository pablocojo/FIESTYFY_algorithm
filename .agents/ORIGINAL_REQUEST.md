# Original User Request

## 2026-08-04T16:12:58Z

# Teamwork Project Prompt — Draft

> Status: Ready for launch — awaiting user approval.
> Goal: Get user approval → delegate to teamwork_preview

Implement specific improvements to the Fase 2 festival extraction algorithm (Fiestyfy) for the 2026 season. The focus is on search resilience, spider temporal scoring, edge-case date handling, and execution metrics, strictly focusing on the current year without falling back to previous years.

Working directory: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`
Integrity mode: development

## Requirements

### R1. Resilient Web Search
Modify `google_search.py` (and `config.py` if needed) to implement User-Agent rotation per query, random delays (2.0 to 4.5 seconds), and exponential backoff with jitter for DuckDuckGo, Yahoo, and Bing searches. Do not use Google Custom Search API.

### R2. Spider 2026 Prioritization
Update the `_score_page` function in `heuristic_spider.py` to prioritize the target year. Penalize URLs containing previous years (e.g., 2025, 2024). Add bonus score for URLs containing the target year alongside festival keywords. Deduplicate calendar URLs (e.g., `/YYYY/M/D/`) and filter out municipal calendar URLs that only list single unrelated events.

### R3. Cross-Year and Leap Year Edge Cases
Update `_validar_fecha` in `text_analyzer.py` to allow `fecha_fin` to be in the following year (`anno+1`) if `fecha_inicio` is in December of the target year. Update `fecha_del_patron` in `patron_finder.py` to fallback to February 28th if the patron saint date is February 29th and the target year is not a leap year.

### R4. Social Media Date Filtering
Ensure the publication date (`fecha_publicacion`) of social media posts (including those processed for images) is always saved. Filter these posts in `social_content.py` so that only those published within an acceptable window for the target year are processed. You may decide the best logical window (e.g., starting late in the previous year to catch early announcements).

### R5. PDF Priority & Async Caches
Update `is_promising_pdf` in `document_extractor.py` to explicitly verify the target year (and previous year) instead of any `20xx` year. Update `RedesCache.set` in `social_finder.py` and `_PatronCache.set` in `patron_finder.py` to use `asyncio.to_thread()` for JSON file writing to avoid blocking the event loop.

### R6. Execution Metrics
Add a final summary report to `async_main` in `main.py`. It should log: the ratio of extracted vs. estimated festivals, the number of localities with zero festivals, the most contributing sources, the number of blocked/failed searches, and the average time spent per municipality.

## Acceptance Criteria

### Verification & Testing
- [ ] You must write small, isolated Python test scripts to verify the core logic independently of the main pipeline.
- [ ] Write a script to verify that `fecha_del_patron` correctly returns February 28th for a February 29th saint in the year 2026.
- [ ] Write a script to verify that `_validar_fecha` accepts a festival from Dec 30, 2026 to Jan 2, 2027.
- [ ] Write a script to verify that the User-Agent rotation and random delay logic functions without throwing errors.
- [ ] All code modifications must be implemented completely (no placeholders) and the isolated verification scripts must pass.

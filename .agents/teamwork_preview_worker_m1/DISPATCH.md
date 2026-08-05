## 2026-08-04T16:19:45Z
You are Worker 1 for Milestone M1 (Resilient Web Search - Requirement R1).
Your working directory is: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_worker_m1
Target project directory: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas

Read ORIGINAL_REQUEST.md at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\ORIGINAL_REQUEST.md
Read user rules at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\AGENTS.md
Read Explorer survey report at: c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\teamwork_preview_explorer_survey_1\handoff.md

Your Task:
Implement Requirement R1 in `scraper/google_search.py` and `config.py`:
1. User-Agent rotation per search query / page fetch request using a pool of realistic user-agent strings.
2. Random delays between 2.0 and 4.5 seconds (`random.uniform(2.0, 4.5)`) between search engine queries/fetches.
3. True exponential backoff with random jitter for DuckDuckGo, Yahoo, and Bing retries (`(base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)`).
4. Ensure NO Google Custom Search API is used.
5. Write an isolated verification test script at `tests_fase2/verify_r1_search.py` verifying User-Agent rotation, random delay in [2.0, 4.5] range, and exponential backoff.
6. Run python / pytest to verify that your implementation and test script run without errors.

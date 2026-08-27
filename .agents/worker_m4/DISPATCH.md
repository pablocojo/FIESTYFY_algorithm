## 2026-08-08T15:28:37Z
Milestone 4 (Requirement R4 - E2E Verification on Amurrio sample municipality extraction).

Task Scope & Target Codebase:
- Target working directory for execution: `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas`
- Reference documents:
  - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\ORIGINAL_REQUEST.md`
  - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\explorer_survey_3\handoff.md`
  - `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\explorer_survey_3\analysis.md`

Step-by-Step Requirements:
1. Initialize your working directory `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\.agents\worker_m4` with `progress.md`.
2. Construct isolated test input JSON (`test_amurrio_input.json`) in `Algoritmo_fiestas/Fase2_Extraccion_Fiestas`:
   Extract root municipality ID `"01002000000"` (Amurrio) and all its 9 child entities (`padre_id: "01002000000"`) from `c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json`. Verify that 10 entities in total are included in `test_amurrio_input.json`.
3. Execute the extraction script:
   `python main.py --input test_amurrio_input.json --output test_amurrio_output.json --parallel 1`
4. Inspect and validate `test_amurrio_output.json`:
   - Confirm `test_amurrio_output.json` exists and is non-empty.
   - Verify Amurrio capital (`"01002000201"`) has at least one festival with `"es_estimada": false` and `"origen": "extraccion"`.
   - Verify `len(programa) > 0` for that festival, containing valid structured event entries.
5. Execute unit tests (`pytest tests/`) if present to ensure no regressions in fixed modules (`llm_processor/text_analyzer.py` and `main.py`).

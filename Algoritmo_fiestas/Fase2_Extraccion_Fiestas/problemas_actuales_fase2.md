# Problemas Detectados — Ejecución Fase 2

**Fuente:** `fase2_20260828_154633.log` (28 ago 15:46 → 30 ago 01:32) — modelo `qwen/qwen3.8-27b` vía LM Studio, 2 municipios / 12 localidades procesadas.

## Resumen rápido

| # | Problema | Severidad | Impacto medido | Estado |
|---|----------|-----------|-----------------|--------|
| 1 | Velocidad de inferencia del LLM (~2.5 tok/s) | P0 | Causa raíz de que 12 localidades tarden 33h46min | **RESUELTO** — cascada OpenRouter |
| 2 | Timeouts de 3h en llamadas ENRICHMENT (`max_tokens=-1`) | P0 | 2 timeouts × 10800s = 6h tiradas (17.8% del tiempo total) | **RESUELTO** — timeout 300s + tope de tokens |
| 3 | Respuestas JSON malformadas / cortadas por longitud | P1 | 73 JSON malformados + 74 respuestas truncadas | **RESUELTO** — los modelos remotos cierran el JSON |
| 4 | Servidor RRSS se desactiva a las ~14h de una ejecución de 34h | P1 | ~20h restantes sin contenido social en vivo (solo caché) | Pendiente |
| 5 | DuckDuckGo-lite se enfría por anti-scraping | P2 | 6 búsquedas bloqueadas/fallidas | Pendiente |
| 6 | Contexto del modelo infrautilizado en LM Studio | P2 | Usa 67328 de 262144 posibles (config, sin coste) | Irrelevante mientras el chat vaya por OpenRouter |

> **Cambio aplicado el 2026-09-01:** el chat de texto pasa por una cascada de 8 modelos
> gratuitos de OpenRouter, con LM Studio como último recurso. Los embeddings y el VLM de
> visión siguen en LM Studio. Detalles en la sección final.

---

## P0 — Críticos

### 1. Velocidad de inferencia del LLM (~2.5 tokens/segundo)
- **Síntoma:** las llamadas de ENRICHMENT tardan entre 40 minutos y casi 2 horas cada una.
- **Evidencia:** tasa medida en varias llamadas consecutivas (mismo prompt ≈12k tok):
  - 19:00→19:58 (8906 tok resp.) → 2.56 tok/s
  - 19:58→20:40 (6482 tok resp.) → 2.53 tok/s
  - 20:40→21:50 (10763 tok resp.) → 2.58 tok/s
  - 23:52→01:35 (15098 tok resp.) → 2.45 tok/s
- **Impacto:** es la causa raíz de que 12 localidades tarden 33h46min en total (media de 60765s/municipio, aunque muy irregular: 13 min a 13h44min por localidad).
- **Causa probable:** poco offload a GPU en LM Studio o VRAM insuficiente con fallback a CPU. 2.5 tok/s es muy bajo para un 27B con aceleración GPU real.
- **Recomendación:** revisar en LM Studio cuántas capas está offloadeando a GPU / si el modelo cabe entero en VRAM; considerar una cuantización más ligera si no cabe.

### 2. Timeouts de 3h en llamadas sin límite de tokens
- **Síntoma:** 2 llamadas ENRICHMENT se quedaron colgadas exactamente 10800s (3h) sin producir ni un token, y se descartaron por completo.
- **Evidencia:** `fase2_20260828_154633.log:259` y `:699` — `Timeout del LLM tras 10800s`. En ambos casos, la llamada anterior y la siguiente con el mismo prompt sí completaron con éxito (finish_reason=stop) en 30-100 min.
- **Impacto:** 6 horas completas perdidas (17.8% del tiempo total de la ejecución) sin ningún resultado aprovechable.
- **Causa probable:** combinación de `max_tokens=-1` (sin tope) + velocidad de generación baja (#1): si el modelo no converge a un stop natural dentro de las 3h, se pierde toda la respuesta en vez de aprovechar lo generado hasta ese punto.
- **Recomendación:** poner un `max_tokens` acotado en las llamadas de ENRICHMENT en vez de `-1`, para fallar más barato y rápido cuando el modelo no converge.

---

## P1 — Importantes

### 3. Respuestas JSON malformadas / cortadas por longitud
- **Síntoma:** el modelo no cierra el JSON antes de agotar el límite de tokens de salida, o directamente no devuelve JSON válido.
- **Evidencia:**
  - 73× `JSON malformado del LLM: Expecting value: line 1 column 1 (char 0)`
  - 58× corte por longitud en llamadas `[CTX/PROCEDENCIA]`
  - 16× corte por longitud en llamadas `[CTX/LOCATOR]`
- **Impacto:** reintentos adicionales y, en varios casos, fiestas que quedan "sin programa que estructurar" pese a haber material (p. ej. Monte Costaján).
- **Causa probable:** `max_tokens` demasiado ajustado para PROCEDENCIA/LOCATOR (p. ej. 400 tok en el caso de Monte Costaján), insuficiente para que el modelo termine el JSON.
- **Recomendación:** subir el `max_tokens` de estas dos llamadas específicas; hay margen de sobra de contexto (ver #6).

### 4. Servidor RRSS se desactiva muy pronto en la ejecución
- **Síntoma:** el servidor de automatización de Windows (controla apps de Instagram/Facebook/Twitter) abortó 2 fases seguidas sin leer ningún perfil y quedó descartado para el resto de la ejecución.
- **Evidencia:** `fase2_20260828_154633.log:136,285,286` — abortos a la 1/2 y 2/2, descarte definitivo a las **2026-08-29 05:33:05**, solo ~14h dentro de una ejecución de ~34h.
- **Impacto:** el 59% restante de la ejecución (~20h, desde Aljubé hasta Monte Costaján) usó únicamente caché antigua (1 documento por localidad) en vez de contenido social en tiempo real.
- **Causa probable:** la automatización depende de que las ventanas de las apps sigan en primer plano; probablemente se perdió el foco al dejar el equipo desatendido toda la noche.
- **Recomendación:** revisar la resiliencia del runner de RRSS para ejecuciones largas/desatendidas (reintento con más margen antes de descartar, o detección de pérdida de foco).

---

## P2 — Menores

### 5. DuckDuckGo-lite se enfría por anti-scraping
- **Síntoma:** respuestas incoherentes repetidas hacen que el motor se "enfríe" temporalmente.
- **Evidencia:** 3 incidentes (`:300`, `:868`, `:1455`) — "envenenamiento anti-scraping"; 6 búsquedas bloqueadas/fallidas en el informe final.
- **Impacto:** bajo — hay fallback a otras fuentes, pero añade fricción creciente con DDG.
- **Recomendación:** monitorizar si la frecuencia aumenta; valorar rotar user-agent/delay específicamente tras un enfriamiento.

### 6. Contexto del modelo infrautilizado
- **Síntoma:** aviso repetido al arrancar la ejecución.
- **Evidencia:** `fase2_20260828_154633.log:4` — *"'qwen/qwen3.8-27b' está cargado con n_ctx=67328 pero soporta hasta 262144. Subirlo en LM Studio multiplicaría el contexto disponible sin coste."*
- **Impacto:** ninguno directo todavía, pero es margen gratuito sin aprovechar que ayudaría a #3.
- **Recomendación:** subir `n_ctx` en LM Studio (config, no requiere cambios de código).

---

## Lo que sí funcionó bien (no son problemas, pero conviene no tocarlo)
- 0 localidades sin ninguna fiesta (12/12 con al menos una).
- Ratio extraídas/estimadas 16:1 — casi todo viene de fuentes reales, no de fallback.
- Las redes de seguridad heurísticas rescataron fiestas reales que el LLM se había dejado (Cordovilla, Tobarra) y limpiaron actos duplicados/inventados antes de guardarlos.

---

## Solución aplicada a los P0 y al P1 de truncamiento (2026-09-01)

El chat de texto ya no va contra LM Studio: `llm_chat_json` recorre una **cadena de
proveedores** y gana el primero que devuelva algo utilizable.

| Orden | Proveedor | Timeout |
|-------|-----------|---------|
| 1-8 | Modelos gratuitos de OpenRouter, de mayor a menor parecido con el Qwen 27B | 300s |
| 9 | LM Studio / `qwen/qwen3.8-27b` (red de seguridad) | 10800s |

**Lo que NO cambia:** los embeddings (`text-embedding-baai-bge-m3-568m`) y el VLM de
visión de las capturas de RRSS siguen yendo a LM Studio.

### Ficheros tocados
- `config.py` — sección OPENROUTER: cascada de modelos, timeouts, tope de tokens, concurrencia.
- `llm_processor/text_analyzer.py` — `_cadena_proveedores()`, `_pedir_a_proveedor()` y `llm_chat_json()` reescrito como bucle sobre la cadena.
- `main.py` — el banner de arranque dice qué proveedor manda.
- `.gitignore` — `openrouter_key.txt` y `.env` fuera del repositorio.

### Detalles que resuelven cada problema
- **#1 velocidad:** medido en la prueba, ~40 tok/s frente a los 2,5 tok/s del 27B local (×16).
- **#2 timeouts:** 300s por llamada en vez de 10800s, y `max_tokens=-1` se traduce a un tope
  explícito (24000) porque OpenRouter rechaza los valores negativos. Una llamada que no
  converge cuesta 5 minutos y salta al siguiente modelo, no 3 horas tiradas.
- **#3 truncamiento:** comprobado con el presupuesto más justo del pipeline
  (`PROCEDENCIA_MAX_TOKENS = 90`): el modelo devolvió 153 tok con `finish_reason=stop`,
  es decir cerró el JSON en vez de cortarlo. Los proveedores remotos no cortan en seco.

### Decisiones de implementación que conviene conocer
- **Memoria del modelo que funciona:** con 8 modelos en cascada y cientos de llamadas por
  ejecución, empezar siempre por el primero significa pagar el 429 del modelo saturado una y
  otra vez. Se recuerda el último que respondió y se prueba primero. Medido: 1ª llamada 66s
  (tres modelos caídos por delante), 2ª llamada 20s.
- **La calibración chars→tokens solo se alimenta de LM Studio.** `registrar_uso_real()` ajusta
  el presupuesto de contexto del modelo local; alimentarla con el tokenizador de otro modelo
  la falsearía.
- **Semáforo aparte para la nube.** El local está en 1 petición simultánea para no desbordar
  la VRAM; en la nube esa restricción no existe, así que va por `OPENROUTER_CONCURRENCY = 3`
  (bajo porque el nivel gratuito limita por minuto).
- **La clave de API no está en `config.py`**, que sí está en git. Se lee de la variable de
  entorno `OPENROUTER_API_KEY` o de `openrouter_key.txt`, ignorado por git.

### Verificación
- Los 8 IDs de modelo existen en el catálogo de OpenRouter (comprobado contra su API).
- Llamada real de extremo a extremo: los 3 primeros modelos dieron 429/saturación, el 4º
  (`cohere/north-mini-code:free`) devolvió el JSON correcto con las dos fiestas del texto.
- Batería de tests: 659 pasan, 9 fallan — los mismos 9 que ya fallaban en HEAD antes del
  cambio (cachés async, `social_finder`, `validar_fiestas`). Sin regresiones.

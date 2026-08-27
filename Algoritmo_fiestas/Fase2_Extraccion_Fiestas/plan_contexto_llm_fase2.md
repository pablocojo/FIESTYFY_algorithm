# Plan de mejora: gestión de contexto del LLM local (Fase 2)

**Fecha:** 2026-08-21 · **Estado:** propuesta, sin cambios aplicados
**Ámbito:** `Fase2_Extraccion_Fiestas` → obtener `fiestas_espana.json` con programas reales

---

## 1. Diagnóstico: el problema no es el tamaño del contexto

La hipótesis de partida era "no cabe la información en el contexto del LLM". Los datos dicen otra cosa.

Ejecución del 2026-08-21 09:11 (Amurrio, 9 localidades):

| Magnitud | Valor |
|---|---|
| Documentos recopilados por localidad | 90 |
| Caracteres recopilados | **5.565.083** |
| Presupuesto de discovery (`DISCOVERY_MAX_CHARS`) | 20.000 |
| Porcentaje que llega al LLM | **0,36 %** |
| Fiestas descubiertas | **0** (las 3 del JSON son estimadas por santo patrón) |

El cuello de botella no es el ancho de la ventana, sino **qué 0,36 % se elige**. Y ahora mismo se elige mal, de forma demostrable.

### 1.1 La prueba: `discovery_context_Amurrio.txt`

El contexto completo que recibió el LLM para Amurrio son **21.409 caracteres de un único documento**: el PDF del presupuesto municipal de 2025 (`ANEXO_3_Ppto_2025.pdf`), tablas de partidas contables.

```
===== FUENTE: WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA) =====
--- [https://udala.amurrio.eus/images/docs/pdf/ANEXO_3_Ppto_2025.pdf] | Relevancia: DIRECTA ---
TOTAL CONCEPTO 3.2.1. 581.580,00 0,00 581.580,00 1.358.729,64 200,00 ...
3.2.2.01. Entrada vehículos por aceras y reserva aparcamiento 56.000,00 ...
```

Peor: de los 14 bloques, **solo 6 son únicos**. Cada uno se repite 3 veces literalmente.

> **21.409 chars de presupuesto — 7.411 chars de información única (35 %). El 65 % del presupuesto de contexto se gastó en duplicados exactos de una tabla contable.**

Mientras tanto, la araña **sí había encontrado el oro** y lo había puntuado correctamente:

```
[Top  1 / Score: 3340] https://www.amurrioturismo.com/agenda-amurrio
[Top  2 / Score: 1650] https://udala.amurrio.eus/cas/calendario/eventospormes/2026/8/
[Top  3 / Score: 1650] https://udala.amurrio.eus/cas/calendario/eventosanual/2026/
[Top  8 / Score: 1570] .../berriak-jaiak/2200-amurrioko-uda...
[Top 10 / Score: 1390] .../noticias-fiestas/2199-el-ayunta...
```

Ninguna de estas páginas llegó al LLM. **El RAG descarta el ranking de la araña y re-ordena desde cero.**

---

## 2. Los seis defectos concretos

### D1 · El regex de horarios confunde códigos contables con programas de actos

`text_analyzer.py:1257` y `:1363`

```python
patron_horas = re.compile(r'\b\d{1,2}[:.]\d{2}\b')
...
if len(matches) >= 3:
    base_score += 0.30   # "¡Es casi seguro una agenda de eventos!"
```

Sobre el PDF de presupuestos: **154 coincidencias**, todas falsas — `3.2.2.01.` → `2.01`, `3.4.0.16.` → `0.16`.

Un `+0.30` sobre una similitud coseno (rango útil ~0,3–0,6) es un empujón brutal. **Este bug, por sí solo, es lo que colocó el presupuesto por encima de la agenda de fiestas.**

### D2 · El mismo PDF se descarga y se indexa 3 veces

`heuristic_spider.py:574-579`

```python
for pdf_url, link_text in pdf_links:
    if is_promising_pdf(pdf_url, link_text, page_text[:500], target_year=self.target_year):
        pdf_tasks.append(self._extract_pdf(session, pdf_url, semaphore))
        pdf_urls_pedidas.append(pdf_url)
        if visited_urls is not None:
            visited_urls.add(self._clean_url(pdf_url))   # ← añade, nunca comprueba
```

No hay `if url in visited_urls: continue`. Y los Top 12, 13 y 14 (`udala.amurrio.eus/`, `/eus`, `/eus/`) enlazan los **mismos 3 PDFs** y se procesan **en el mismo batch concurrente** de 5. Resultado: 3 copias idénticas. Tampoco hay dedup por hash de contenido en `main.py` ni en `seleccionar_chunks`.

### D3 · `is_promising_pdf` aprueba PDFs administrativos

`document_extractor.py:150-176`. `ANEXO_3_Ppto_2025.pdf` pasa porque:

1. contiene `2025` ∈ `valid_years` (la regla R5.1 "verificar año objetivo **y anterior**" juega en contra), y
2. `context_text = page_text[:500]` son los **menús de la home** de `udala.amurrio.eus`, que contienen "fiestas"/"jaiak".

El nombre del fichero (`ppto`, `anexo`, `presupuesto`) nunca se penaliza.

### D4 · La puntuación de la araña se tira a la basura

`heuristic_spider.py:569` → `crear_documento(fuente, url, page_text, tipo="pagina")`.
`fuentes.py:342-353` → el dict resultante no tiene campo `score`.

La araña invierte 5 minutos en puntuar 85 páginas por relevancia festiva y temporal (2026 +350, años previos −300, filtro de evento suelto −350) y ese trabajo **se descarta por completo** antes del RAG. El chunk de `agenda-amurrio` (3340 pts) compite en igualdad de condiciones con el chunk de una tabla de tasas.

### D5 · El *contextual retrieval* está implementado pero desconectado

`text_analyzer.py:1125-1129`

```python
cabecera = generar_cabecera_chunk(doc, municipio_nombre, localidad_nombre)
chunk_contextualizado = f"{cabecera}\n{chunk}"
items.append({"chunk": chunk, "chunk_contextualizado": chunk_contextualizado, ...})
```

`chunk_contextualizado` **no se usa jamás**. Se embebe `chunk` (`:1142`) y se ensambla `chunk` (`:469`). Es decir: un bloque de horarios sin nombre de pueblo se vectoriza desnudo, sin el "[FUENTE: Web oficial del municipio de Amurrio (…/agenda-amurrio)]" que lo haría rankear.

### D6 · El presupuesto de contexto es ficticio, incoherente y está infrautilizado

Coexisten **tres presupuestos distintos y contradictorios**:

| Constante | Valor | Equivalente | Ruta que la usa |
|---|---|---|---|
| `RAG_MAX_TOKENS` × `RAG_CHARS_PER_TOKEN` | 30.000 × 2,6 | **78.000 chars** | `saturate_context_docs` (desbordaría n_ctx) |
| `DISCOVERY_MAX_CHARS` | — | 20.000 chars | multipass discovery |
| `ENRICHMENT_MAX_CHARS` | — | 32.000 chars | multipass enrichment |

Además:

- **`RAG_CHARS_PER_TOKEN = 2,6` es una estimación, no una medida.** El tokenizador de Qwen2.5 sobre texto español da ~3,3–3,8 chars/token. Se está **sobreestimando el consumo en ~35 %**: 20.000 chars ≈ 5.500 tokens reales, no 7.700.
- **Nunca se consulta el `n_ctx` real** con el que LM Studio tiene cargado el modelo. Si son 32.768, hoy se usa **menos del 20 % de la ventana**.
- **`LMSTUDIO_CHAT_MAX_TOKENS = -1`** significa *sin reserva de salida*. Un programa de 5 días × 15 actos son ~3.000 tokens de JSON que pueden quedar cortados por `n_ctx`, no por el modelo.
- El reintento adaptativo `(1.0, 0.7, 0.5)` solo salta con un HTTP 400 explícito; LM Studio a menudo **trunca en silencio**.

### D7 · Coste desproporcionado en traducción

Log de Amurrio: `09:20:41` (contexto listo) → `09:22:34` (llamada al LLM). **113 segundos** de Opus-MT línea a línea sobre 20.000 chars — que además eran texto **español** (páginas `/cas`) traducido de español a español. Por localidad, sobre un contexto que resultó ser basura.

---

## 3. Plan de implementación

Ocho fases, ordenadas por *impacto ÷ riesgo*. Las fases 1–3 arreglan el fallo observado; la 4–5 responden a la pregunta de fondo ("cómo pasarle siempre lo necesario dentro del límite").

---

### Fase 0 · Instrumentación y línea base *(medio día · sin cambios funcionales)*

Sin esto no se puede medir si las demás fases funcionan.

**0.1 — Módulo `context_budget.py`**

- `get_n_ctx()`: consulta `GET {LMSTUDIO_BASE_URL}/api/v0/models` y lee `loaded_context_length` del modelo cargado. Cachear por ejecución; *fallback* conservador a 8192 con `logger.warning` si no responde.
- `contar_tokens(texto)`: `AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")` — `transformers` ya es dependencia (Opus-MT). Tokenizador cacheado en módulo. Fallback a `len(texto)/3.5` si no hay red.
- `presupuesto_contexto(system_prompt, reserva_salida)` →
  `n_ctx − tokens(system) − reserva_salida − 256 (margen)`.

**0.2 — Traza por llamada**

Log en cada `llm_chat_json`: `n_ctx`, tokens del system, tokens del contexto, reserva, tokens realmente generados, `finish_reason`. Si `finish_reason == "length"`, warning explícito — hoy eso pasa invisible.

**0.3 — Volcado de depuración**

Sustituir `discovery_context_{loc}.txt` por `discovery_debug_{loc}.json`, con por cada chunk candidato: `url`, `fuente`, `score_spider`, `sim`, `señal_programa`, `señal_temporal`, `score_final`, `tokens`, `seleccionado`. Es el instrumento con el que se validan las fases 1–5.

**0.4 — Conjunto dorado**

8–10 localidades con respuesta conocida (Amurrio → San Roque 16-ago + programa real; 2–3 pedanías sin fiestas documentadas; 2 municipios de otra CCAA con web en catalán/gallego). Dos métricas:

- `recall_fuente`: % de localidades en que **la página correcta aparece en el contexto de discovery**. ← la métrica que importa
- `precision_programa`: % de fiestas con `programa != []` y fechas correctas

Línea base actual medida: `recall_fuente = 0/9`.

---

### Fase 1 · Higiene de documentos *(1 día · riesgo bajo · impacto máximo)*

Ataca D2 y D3. Recupera el 65 % de presupuesto desperdiciado y elimina la fuente del ruido.

**1.1** — En `_process_single_page`, comprobar `visited_urls` **antes** de encolar cada PDF. Como el batch es concurrente, hacer *check-and-add* atómico (`asyncio.Lock` sobre el set, o `set.add()` con comprobación previa dentro del mismo bloque síncrono — Python garantiza atomicidad si no hay `await` entre medias).

**1.2** — Dedup global en `main.py`, antes de `analyze_festivals_multipass`:
- por URL canónica (`_clean_url`)
- por `sha1(texto.strip())`
- por *near-duplicate* (shingles de 5 palabras, Jaccard > 0,9) para PDFs re-extraídos con OCR ligeramente distinto

**1.3** — Lista negra de PDFs administrativos en `is_promising_pdf`, evaluada **sobre el nombre de fichero** y con prioridad sobre las keywords:

```
presupuesto|ppto|anexo|ordenanza|acta|pleno|padron|licitacion|
contrato|subvencion|convenio|memoria|cuenta|tasa|impuesto|bop
```

Y endurecer: `context_text` debe ser el texto **alrededor del enlace**, no `page_text[:500]` (que son los menús). Extraer del `<a>` padre y sus 200 chars vecinos.

**1.4** — Filtro de densidad numérica: descartar chunk/documento con `>30 %` de caracteres numéricos **y** menos de 3 verbos conjugados. Barato y letal contra tablas contables. Test unitario con las líneas reales de `ANEXO_3_Ppto_2025.pdf` como negativos.

**1.5** — Eliminación de *boilerplate*: para documentos del mismo `netloc`, contar frecuencia de líneas; descartar las que aparecen en `>40 %` de las páginas de ese sitio (menús, cookies, pie). Con 83 páginas del mismo CMS esto libera contexto real.

> **Efecto esperado en Amurrio:** el PDF de presupuestos desaparece por completo (1.3 + 1.4) y el duplicado ×3 por (1.1 + 1.2). El presupuesto de discovery queda libre para las páginas que la araña ya había puntuado arriba.

---

### Fase 2 · Propagar el ranking de la araña al RAG *(medio día · riesgo bajo · impacto alto)*

Ataca D4. Es el trabajo que ya se está haciendo y se tira.

**2.1** — `crear_documento(fuente, url, texto, tipo, score_spider=0, rank=None)`; `_process_single_page` pasa su `score` y su `rank`.

**2.2** — En `index_document_chunks`, normalizar: `prior_doc = min(score_spider / 2000.0, 1.0)`, propagado a todos los chunks del documento.

**2.3** — **Fusión de señales acotada**, sustituyendo los `+= 0.30` sueltos sobre el coseno:

```python
score_final = (0.45 * sim_normalizada      # coseno reescalado a 0..1
             + 0.25 * prior_doc            # ranking de la araña
             + 0.20 * señal_programa       # horas válidas + verbos de evento
             + 0.10 * señal_temporal)      # menciona el año objetivo
```

Todas las señales en `0..1`. Ningún sumando puede volver a dominar como el `+0.30` de D1.

**2.4** — **Cuota garantizada**: los chunks del **Top-3 de la araña** entran en el contexto *antes* de cualquier otra selección, con un mínimo de 1 chunk cada uno. Esto solo ya garantiza que `agenda-amurrio` (3340 pts) esté presente en cada ejecución, pase lo que pase con los embeddings.

---

### Fase 3 · Arreglar las señales de recuperación *(1 día · riesgo medio)*

Ataca D1 y D5.

**3.1 — Regex de horarios correcto**

```python
PATRON_HORA = re.compile(
    r'(?<![\d.,])(?:[01]?\d|2[0-3])[:.]([0-5]\d)(?:\s*h(?:oras)?)?(?![\d.,])'
)
```

Rechaza `3.2.2.01`, `56.408,63`, `1.358.729,64`. Acepta `18:00`, `9.30h`, `23:30`. **Test unitario obligatorio** con las líneas del presupuesto como casos negativos y un programa real como positivo. Añadir requisito de co-ocurrencia: la línea debe contener además un sustantivo de acto (`pasacalles|verbena|concierto|misa|txupinazo|romería|fuegos|encierro|degustación|actuación|desfile|…`).

**3.2 — Señal temporal a nivel de chunk**

`+1.0` si contiene el año objetivo o fechas resolubles a 2026; `−0.5` si solo contiene 2024/2025. Hoy la araña lo hace por página pero el chunk no hereda nada.

**3.3 — Activar el contextual retrieval (D5)**

Embeber `chunk_contextualizado` en lugar de `chunk` (`:1142`) y, en `ensamblar_contexto`, incluir el `<title>` de la página además de la URL. Coste: cero. Beneficio: los bloques de horarios sin topónimo dejan de ser huérfanos semánticos.

**3.4 — Discovery multi-query con fusión RRF**

Una sola query contra 5,5 M de caracteres es insuficiente. Lanzar en un solo batch de embeddings:

- la genérica actual
- `"programa de actos {patron} {localidad} {anno}"` — **el patrón ya se conoce** (`patron_finder` resolvió "San Roque, 16 de agosto" a las 09:16:26, antes del discovery; hoy esa información no se usa para recuperar)
- `"fiestas patronales {localidad} {mes_del_patron}"`
- `"agenda de eventos {localidad} {anno}"`
- las variantes en euskera/catalán/gallego de `config_idiomas`

Fusionar por **Reciprocal Rank Fusion** (`1/(60+rank)` sumado por chunk), no por máximo de similitud. Coste: +5 embeddings de query, milisegundos.

**3.5** — Dedup de chunks por `sha1` de texto normalizado dentro de `seleccionar_chunks` (segunda red de seguridad tras 1.2).

---

### Fase 4 · Presupuesto de contexto real *(1 día · riesgo medio)*

Ataca D6. **Esta es la respuesta directa a la pregunta planteada.**

**4.1** — Sustituir `budget_chars` por `budget_tokens` en `seleccionar_chunks`, `retrieve_discovery_context` y `enrich_festival_program`. Retirar `RAG_CHARS_PER_TOKEN` como mecanismo de selección (conservarlo solo como pre-estimación rápida para evitar tokenizar 4.000 chunks: tokenizar de verdad solo los candidatos finalistas).

**4.2** — Presupuesto derivado en tiempo de ejecución:

```python
RESERVA_SALIDA_DISCOVERY  = 1536   # lista de fiestas sin programa
RESERVA_SALIDA_ENRICHMENT = 4096   # programa completo de varios días
presupuesto = get_n_ctx() - contar_tokens(system_prompt) - reserva - 256
```

**4.3** — Fijar `max_tokens` **explícitamente** a la reserva en lugar de `-1`. Con `-1` no hay garantía de que quepa la respuesta.

**4.4** — **Llenar la ventana.** Con `n_ctx = 32768`: `32768 − ~1200 (system) − 1536 − 256 ≈ 29.700 tokens` ≈ **~100.000 caracteres** de contexto de discovery, frente a los 20.000 actuales. Es un **5×** sin tocar hardware.
→ *Acción de verificación previa:* confirmar el `loaded_context_length` real en LM Studio (4.1 lo automatiza). Si está en 4096 por defecto, subirlo es la mejora individual más barata de todo el plan.

**4.5** — **Cuotas de diversidad en el empaquetado** *(el arreglo estructural del fallo de Amurrio)*:

- máximo **3 chunks por URL**
- máximo **25 % del presupuesto por documento**
- mínimo **4 documentos distintos** en el contexto final

Con esta regla, un solo PDF **no puede volver a monopolizar el contexto** ni aunque todas sus señales fallen a favor.

**4.6** — Empaquetado *best-fit* consciente de tokens en lugar del `continue` codicioso actual (`:434`), que sesga hacia chunks pequeños en la cola y puede impedir que entre un chunk de programa legítimo de 8.000 chars (`RAG_PROGRAMA_MAX_CHARS`).

---

### Fase 5 · Map-reduce: qué hacer cuando de verdad no cabe *(2 días · riesgo medio-alto)*

Aunque las fases 1–4 reduzcan 5,5 M → ~300 K chars útiles, sigue sin caber en 30 K tokens. Aquí está el salto cualitativo.

**5.1 — Triaje por títulos (la idea de mayor valor del plan)**

En lugar de rankear 4.000 chunks a ciegas, hacer **una llamada barata al LLM sobre los metadatos**:

```
Prompt: 85 líneas de "rank | score | URL | <title> | primeras 15 palabras"  (~2.500 tokens)
Salida: los 8-12 documentos que probablemente contienen fiestas o programas  (~150 tokens)
```

Solo esos documentos se trocean e indexan. **5,5 M chars → ~150 K chars** antes de tocar embeddings. Beneficios colaterales: se ahorran ~4.000 embeddings por localidad, y la traducción (Fase 7) opera sobre 20× menos texto.

Un LLM de 7B acierta esto con altísima fiabilidad — distinguir `agenda-amurrio` de `ANEXO_3_Ppto_2025.pdf` por el título es trivial para un modelo, y es exactamente donde el coseno falla.

**5.2 — Discovery por ventanas cuando sigue sin caber**

Si tras el triaje los candidatos superan el presupuesto en más de 1,5×, ejecutar discovery en **K ventanas** (K = `ceil(tokens/presupuesto)`, tope 3), cada una con un corte diverso (round-robin por documento, no secuencial), y fusionar las listas de fiestas con `_deduplicar_fiestas` + `fusionar_fiestas_proximas`, que ya existen.

**5.3 — Cortocircuito por hallazgo fuerte**

En cuanto un chunk de fuente oficial contenga ≥8 actos con hora en ≥2 días distintos, marcarlo como *programa confirmado*, incluirlo íntegro y saltar las ventanas restantes. Ahorra tiempo en el caso frecuente en que la primera ventana ya trae el programa.

---

### Fase 6 · Enrichment por ventanas de días *(1 día · riesgo medio)*

**6.1** — Hoy `enrich_festival_program` lanza hasta 30 queries (una por día), acumula chunks en **orden de día** y luego los recorta a un único prompt de 32.000 chars (`:1413-1419`). Los chunks del día 1 agotan el presupuesto y **el día 15 se queda sin nada**. Sustituir por: agrupar los días en bloques que quepan en el presupuesto → **una llamada al LLM por bloque** → fusionar los `programa[]` resultantes.

**6.2** — Dar prioridad absoluta al **texto completo del documento que originó el hallazgo en discovery** (re-obtenerlo entero si hace falta) frente a chunks dispersos. Cuando ya se sabe qué fiesta y qué fechas, la mejor fuente es la página del programa, completa y sin trocear.

**6.3** — Aplicar `RESERVA_SALIDA_ENRICHMENT = 4096` (4.2), dimensionada al JSON de un programa multi-día real.

---

### Fase 7 · Coste de traducción *(medio día · riesgo bajo)*

Ataca D7 — 113 s por localidad.

**7.1** — Traducir **solo los chunks seleccionados** (ya es el caso) pero con caché por `sha1(chunk)` en disco, y **saltar el chunk si fastText lo clasifica como `es`** con confianza > 0,8. En Amurrio la mayoría del contexto venía de rutas `/cas`: se estaba traduciendo español a español.

**7.2** — Evaluar delegar euskera/catalán/gallego directamente en Qwen2.5 (es multilingüe y el system prompt ya ordena traducir), reservando Opus-MT para chunks con ≥80 % de texto no castellano. Medir ambas variantes sobre el conjunto dorado antes de decidir.

---

### Fase 8 · Verificación *(continua)*

**Tests unitarios** (`tests_fase2/`):

| Test | Contenido |
|---|---|
| `verify_c1_regex_horas.py` | Las líneas reales de `ANEXO_3_Ppto_2025.pdf` como negativos; un programa real como positivo |
| `verify_c2_dedup.py` | Mismo PDF desde 3 páginas → 1 documento |
| `verify_c3_budget.py` | `contar_tokens` vs. tokenizador real (±2 %); presupuesto nunca > `n_ctx` |
| `verify_c4_cuotas.py` | Ningún documento supera el 25 % del contexto; ≥4 documentos distintos |
| `verify_c5_pdf_filtro.py` | `is_promising_pdf` rechaza `ANEXO_3_Ppto_2025.pdf` y acepta `programa-fiestas-2026.pdf` |

**E2E sobre el conjunto dorado**, comparando `discovery_debug_*.json` antes/después.

**Criterios de aceptación:**

| Métrica | Hoy | Objetivo |
|---|---|---|
| `recall_fuente` (página correcta en el contexto) | 0/9 | ≥ 8/10 |
| Localidades con `programa != []` | 0 % | ≥ 60 % de las que tienen programa publicado |
| Chars únicos / chars de contexto | 35 % | ≥ 95 % |
| Documentos distintos en el contexto | 1 | ≥ 4 |
| Uso de la ventana del modelo | ~20 % | ≥ 85 % |

---

## 4. Orden recomendado y retorno esperado

| Fase | Esfuerzo | Riesgo | Impacto | Nota |
|---|---|---|---|---|
| **0 · Instrumentación** | 0,5 d | nulo | — | Prerrequisito: sin esto no se mide nada |
| **1 · Higiene de documentos** | 1 d | bajo | **muy alto** | Elimina la causa directa del fallo |
| **2 · Ranking de la araña** | 0,5 d | bajo | **muy alto** | Aprovecha trabajo ya hecho |
| **3 · Señales** | 1 d | medio | **alto** | Incluye el bug del regex |
| **4 · Presupuesto real** | 1 d | medio | **alto** | 5× de ventana útil |
| 5 · Map-reduce / triaje | 2 d | medio-alto | alto | El salto cualitativo |
| 6 · Enrichment por ventanas | 1 d | medio | medio | Solo importa si discovery ya funciona |
| 7 · Traducción | 0,5 d | bajo | medio (coste) | −100 s por localidad |
| 8 · Verificación | continua | — | — | |

**Solo con las fases 0–2 (2 días)** el contexto de Amurrio deja de ser un presupuesto municipal duplicado y pasa a contener `agenda-amurrio` y `calendario/eventosanual/2026`. Es muy probable que las fiestas de San Roque salgan ya ahí.

Las fases 3–4 lo consolidan y multiplican por 5 la ventana útil. La fase 5 es lo que permite escalar a municipios grandes con cientos de páginas.

---

## 5. Punto que requiere decisión

**El origen del problema está aguas arriba del LLM.** Las fases de mayor impacto (1 y 2) tocan `heuristic_spider.py`, `document_extractor.py`, `fuentes.py` y `main.py`, no `text_analyzer.py`. Limitar la intervención a la capa RAG/LLM dejaría intacta la causa directa del fallo observado: el contexto seguiría llenándose de duplicados y de PDFs administrativos, solo que ordenados de otra forma.

Antes de implementar conviene además verificar el `loaded_context_length` real de LM Studio (Fase 4.1 lo automatiza, pero el dato condiciona cuánto margen hay que ganar).

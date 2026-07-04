# Plan de implementación — Fase 2 v3: Jerarquía de fuentes, RRSS por apps de escritorio, procedencia del contexto y visión

**Fecha:** 03-07-2026 · **Revisión 2** (RRSS vía apps de escritorio, filtro de calendario laboral/escolar) · **Estado:** pendiente de aprobación

---

## 1. Contexto y objetivo

La Fase 2 actual mezcla todo el texto recopilado (web municipal + búsqueda browser) en un único string sin procedencia, lo trocea a 1200 caracteres (puede cortar un programa por la mitad) y el LLM no puede distinguir información fiable de ruido de internet. Además no se aprovechan las redes sociales oficiales, donde muchos ayuntamientos publican los programas de fiestas **como imágenes**, y se cuelan "fiestas" que en realidad son festivos del calendario laboral/escolar sin celebración.

Objetivos de esta versión:

1. **Perfiles oficiales** de Instagram, Facebook y X de cada localidad/municipio, **sin falsos positivos** (mejor `null` que un perfil equivocado), persistidos en el campo `redes_sociales` de cada lugar en `lugares_espana.json`.
2. **Jerarquía de fiabilidad de fuentes** (de más a menos):
   1. Web de la **localidad** — **se omite directamente si su `sitio_web` está vacío** o si es la misma que la del padre
   2. Web del **municipio** (como funciona ahora; también se omite si está vacía)
   3. RRSS de la **localidad** (IG, FB, X)
   4. RRSS del **municipio**
   5. Búsqueda **browser** (la menos fiable)
3. **Lectura de RRSS a través de las APPS de escritorio** (Facebook e Instagram de Microsoft Store, X instalada como app web), con sesión ya iniciada. **Aislamiento absoluto**: el algoritmo solo ve y toca las ventanas de esas apps, nada más del equipo (ver §M2-Seguridad).
4. **Contexto con procedencia**: cada chunk marcado con su fuente. Fiestas halladas **solo** en fuentes no oficiales → `solo_fuentes_no_oficiales: true` + confianza baja forzada.
5. **Chunking que no corta programas**: un programa de actos llega íntegro al modelo.
6. **Regla de fusión de eventos**: fiesta confirmada por fuente oficial + evento de fuente externa dentro de su rango → el evento se añade con la confianza de lo oficial.
7. **Filtro de calendario laboral/escolar**: un festivo del calendario (día no lectivo) NO es una fiesta; solo se aceptan celebraciones reales de la localidad, aunque coincidan en fecha con un festivo local.
8. **Visión (RTX 4080, 16 GB)**: solo las imágenes procedentes de RRSS pasan por el VLM; webs y PDFs siguen con Tesseract.
9. **Dedupe global de URLs**: el paso browser no relee enlaces ya leídos.

### Decisiones tomadas por el usuario
- RRSS **vía apps de escritorio** con sesión iniciada; el algoritmo no puede tocar nada fuera de las apps. FB+IG = apps de Microsoft Store; X = app web instalada (PWA).
- **Modo híbrido**: los perfiles se descubren primero gratis desde los enlaces de la web oficial; las apps se usan para (a) buscar perfiles que la web no enlaza y (b) leer contenido/imágenes de todos los perfiles descubiertos.
- **PC dedicado** durante la fase de apps (sesiones dedicadas, p. ej. nocturnas); el guardián pausa todo si la ventana activa deja de ser la app.
- VLM **solo para imágenes de RRSS** (capturas de las apps); webs/PDFs con Tesseract.
- Web de localidad vacía → se descarta ese paso directamente.

---

## 2. Módulos

### M1 — Descubrimiento de perfiles oficiales · `scraper/social_finder.py` (nuevo)

1. **Nivel 1 (gratis y máxima fiabilidad): enlaces salientes de la web oficial.** Durante la Pasada 1 del spider, cosechar los `<a href>` hacia `instagram.com`, `facebook.com`, `twitter.com`/`x.com` (header/footer). Perfil enlazado desde el dominio oficial = oficial → `verificado_por: "web_oficial"`.
2. **Nivel 2 (apps)**: las localidades sin perfil tras el nivel 1 entran en la **cola de búsqueda in-app** (ver M2): se busca el nombre en el buscador interno de cada app y se valida el candidato: el handle o el nombre del perfil debe contener el nombre normalizado de la localidad **y** un marcador institucional (`ayuntamiento|ayto|concello|udala|ajuntament|concejo|villa de|fiestas`). No concluyente → `null`. → `verificado_por: "app_validada"`.
3. **Pedanías**: se busca primero para la localidad; si no existe, las RRSS del municipio actúan como fuente de nivel 4 (no se copian como si fueran de la localidad).

**Persistencia:** caché `redes_sociales_cache.json` (clave `lugar_id`, guarda también los `null`) + script `sync_redes_a_lugares.py` que vuelca el campo a `lugares_espana.json` (escritura atómica + backup `.bak`). Si el lugar ya trae `redes_sociales`, no se vuelve a buscar.

```jsonc
// campo en cada lugar de lugares_espana.json
"redes_sociales": {
  "instagram": "https://instagram.com/aytoejemplo",  // o null = buscado y NO existe
  "facebook": "https://facebook.com/AytoEjemplo",
  "twitter": null,
  "verificado_por": "web_oficial",   // "web_oficial" | "app_validada"
  "fecha_verificacion": "2026-07-03"
}
```

### M2 — Lectura de RRSS por apps de escritorio · `scraper/social_apps/` (nuevo)

**Arquitectura desacoplada en dos procesos** (clave para que el pipeline normal no dependa del PC dedicado):

```
main.py (pipeline normal)                    social_apps_runner.py (PC dedicado)
  │ genera cola de trabajo RRSS                │ consume la cola conduciendo las apps
  │ (perfiles a leer + perfiles a buscar)      │ produce rrss_contenido_cache.json
  │ lee rrss_contenido_cache.json si existe ◄──┘   + capturas en rrss_capturas/
```

- El pipeline normal nunca toca las apps: si hay caché de contenido RRSS la usa; si no, esa fuente se omite y la localidad se completa con el resto (re-ejecutable después para enriquecer).
- `social_apps_runner.py` se lanza a mano en sesiones dedicadas (p. ej. de noche).

**Estructura:**
```
scraper/social_apps/
├── app_controller.py     # localización de ventanas + SafetyGuard (aislamiento)
├── instagram_app.py      # driver app Microsoft Store (proceso Instagram.exe bajo ApplicationFrameHost)
├── facebook_app.py       # driver app Microsoft Store
├── x_app.py              # driver PWA (ventana propia de msedge.exe/chrome.exe con título "X")
└── runner.py             # cola de trabajo, reintentos, volcado de caché
```

**Seguridad — garantía de no-escape (SafetyGuard), requisito duro del usuario:**
1. Al iniciar, el runner **localiza** las 3 ventanas (título + proceso: `Instagram.exe`/`Facebook.exe` vía ApplicationFrameHost para las de Store; ventana app de Edge/Chrome con título de X para la PWA). **Nunca lanza ni cierra aplicaciones**: si una app no está abierta, esa red se omite y se registra.
2. **Antes de CADA acción** (clic, tecla, scroll): verificar que la ventana objetivo existe, está visible y **es la ventana en primer plano** (`GetForegroundWindow`); si no → **pausa** y espera a que vuelva a serlo (nunca envía input a otra ventana).
3. Preferencia por **patrones UIA** (pywinauto backend `uia`): Invoke/Value/Scroll dirigidos al control concreto de la app — no hay movimiento de ratón global. Los clics de coordenadas, solo como fallback, **siempre recortados al rectángulo de la ventana** con margen interior.
4. Las capturas de pantalla son **solo del rectángulo de la ventana** (PrintWindow), jamás del escritorio completo.
5. Contador de anomalías: si el foco cambia N veces seguidas o aparece una ventana inesperada encima → **abortar la fase** limpiamente y dejar la cola donde estaba.
6. Sin acceso a archivos del usuario, sin lanzar procesos, sin navegador. Dependencias: `pywinauto`, `pywin32`, `mss`, `Pillow`.

**Flujo por perfil (cada app):**
1. Buscar (caja de búsqueda interna) el handle/nombre → validar (reglas M1-2) leyendo el árbol UIA del resultado.
2. Abrir perfil → capturar cabecera (handle, nombre, bio) → construir URL canónica (`instagram.com/<handle>`, etc.).
3. Scroll por los posts recientes (ventana temporal: ~6 meses antes del año objetivo → hoy). Por cada post: leer el texto por UIA si la app lo expone; si no, **captura del post → VLM** (M3) extrae caption + detecta si la imagen es un programa.
4. Límites por perfil: `SOCIAL_MAX_POSTS_PER_PROFILE` (p. ej. 30) y `SOCIAL_MAX_MINUTES_PER_PROFILE`.
5. Resultado → `rrss_contenido_cache.json`: `{lugar_id: {red: [{texto, fecha, es_programa, texto_programa, url_post}]}}`.

**Rendimiento esperado:** ~1–2 min por perfil. Con el modo híbrido, solo pasan por apps los perfiles descubiertos + las búsquedas fallidas del nivel 1. Priorizar en la cola los municipios grandes.

### M3 — Visión para imágenes de RRSS · `llm_processor/vision_analyzer.py` (nuevo)

- **Entrada**: exclusivamente capturas/imágenes procedentes de las apps de RRSS (decisión del usuario; webs y PDFs siguen con Tesseract).
- **Pre-filtro sin GPU**: el caption/texto del post debe contener keywords festivas (`programa|fiestas|cartel|actos|verbena|feria|patronales...`) — filtro anti-falsos-positivos pedido por el usuario — más dimensiones mínimas y tope de imágenes por perfil.
- **Una sola llamada VLM por imagen** (LM Studio, `image_url` base64): clasifica y transcribe a la vez:
  ```json
  { "es_programa_fiestas": true, "texto_extraido": "FIESTAS DE SAN ROQUE 2026\n14 agosto 23:00 Verbena..." }
  ```
  `es_programa_fiestas: false` → descartada, no entra al contexto.
- El texto entra al pipeline como documento `rrss_localidad:instagram` (etc.).
- Comparte el semáforo global del LLM (una petición a la vez).

### M4 — Orden de rastreo y dedupe global · `main.py` + `heuristic_spider.py`

```
1. Spider web LOCALIDAD   (SOLO si sitio_web no vacío Y ≠ sitio del padre)  → web_localidad
2. Spider web MUNICIPIO   (solo si no vacío)                                → web_municipio
3. RRSS localidad  (desde rrss_contenido_cache)                             → rrss_localidad:<red>
4. RRSS municipio  (desde rrss_contenido_cache)                             → rrss_municipio:<red>
5. Búsqueda browser (DDG/Bing/Yahoo)                                        → busqueda_web
```

- **`visited_urls` compartido por localidad**: el paso 5 no descarga URLs ya leídas en 1–4; el spider del municipio no repite las de la localidad.
- `AsyncTwoPassSpider.crawl()` devuelve `list[Documento {fuente, url, texto, es_calendario}]` en lugar de un string (PDF/cartel → documentos hijos con la misma fuente).

### M5 — Contexto con procedencia + chunking por documentos · `text_analyzer.py`

1. **Chunking que respeta documentos y programas**: se trocea por documento (nunca se mezclan fuentes); cortes solo en límites de párrafo/línea; un bloque con densidad de horarios/fechas (`\d{1,2}[:.]\d{2}`, "día D de <mes>") es **programa** y se mantiene íntegro (tope de seguridad `RAG_PROGRAMA_MAX_CHARS ≈ 8000`).
2. **Selección RAG por cuotas de prioridad**: primero TODOS los chunks relevantes (similitud > umbral) de fuentes 1–4; `busqueda_web` solo rellena lo que quede. Un chunk oficial nunca es expulsado por uno de browser.
3. **Ensamblado con rótulos**:
   ```
   ===== FUENTE: WEB OFICIAL DE LA LOCALIDAD (fiabilidad MÁXIMA) — https://... =====
   ===== FUENTE: RED SOCIAL OFICIAL (INSTAGRAM) DE LA LOCALIDAD (fiabilidad ALTA) =====
   ===== FUENTE: RESULTADOS DE BUSCADOR (fiabilidad BAJA — verificar) =====
   ===== FUENTE: PÁGINA DE CALENDARIO LABORAL/ESCOLAR (NO es evidencia de celebración) =====
   ```
4. **Prompt (reglas nuevas)**: jerarquía explicada; fiesta solo de `busqueda_web` → `solo_fuentes_no_oficiales: true` + confianza baja; regla de fusión de eventos; cada fiesta devuelve `fuentes: [...]`; **regla de calendario**: "una entrada de calendario laboral o escolar (festivo, día no lectivo) NO es una fiesta; extráela solo si hay evidencia de celebración (programa, actos, verbena, feria)".
5. **Validación post-LLM**: defaults `fuentes: []`, `solo_fuentes_no_oficiales: false`; coherencia (si declara fuente oficial que no estaba en contexto → corregir a true); true → confianza baja forzada.

### M6 — Filtro de festivos de calendario · `festival_filter.py` (ampliación)

- Nueva lista `FESTIVOS_CALENDARIO` con los festivos nacionales/autonómicos de fecha fija (Año Nuevo 1/1, Reyes 6/1, 1 Mayo, Santiago 25/7*, Asunción 15/8*, 12 Oct, 1 Nov, Constitución 6/12, Inmaculada 8/12, Navidad 25/12, días de las CC.AA.: 28-F, 23-A, 9-Oct...) y señales de calendario: `calendario laboral|calendario escolar|dia no lectivo|festivo local|dias festivos|puente|aula|lectivo`.
- **Regla determinista**: fiesta cuyo nombre es el de un festivo de calendario o cuyo texto solo contiene señales de calendario, **sin ninguna señal de celebración** (programa, verbena, actos, feria, orquesta...) → descartada, motivo `festivo_calendario_sin_celebracion`.
- *Los marcados con asterisco coinciden con patronales reales: si hay señales de celebración o coincide con el día del patrón → se mantiene. Coincidir en fecha con el festivo local del calendario **no penaliza**: esas suelen ser precisamente las fiestas de verdad.*
- **A nivel documento**: páginas cuyo título/URL contengan `calendario laboral|escolar|festivos` se marcan `es_calendario: true` y se rotulan en el prompt como NO-evidencia.

### M7 — Config nuevos · `config.py`

`SOCIAL_SEARCH_ENABLED`, `SOCIAL_CACHE_FILE`, `SOCIAL_CONTENT_CACHE_FILE`, `SOCIAL_MAX_POSTS_PER_PROFILE`, `SOCIAL_MAX_MINUTES_PER_PROFILE`, `SOCIAL_POST_MONTHS_BACK`, `VISION_ENABLED`, `VISION_MODEL`, `VISION_TIMEOUT`, `VISION_MAX_IMAGES_PER_PROFILE`, `RAG_PROGRAMA_MAX_CHARS`, `RAG_UMBRAL_SIMILITUD`, `RAG_MAX_TOKENS` (recalculado, ver §3).

### Cambios de esquema de salida (`fiestas_espana.json`)

```jsonc
{
  // ...campos actuales (origen, es_estimada, incluye_dia_patron, patron)...
  "fuentes": ["web_municipio", "rrss_localidad:facebook"],
  "solo_fuentes_no_oficiales": false
}
```

---

## 3. Modelos a cargar en LM Studio (RTX 4080, 16 GB)

| Rol | Modelo (buscar en LM Studio) | Quant | Configuración | VRAM aprox. |
|---|---|---|---|---|
| Chat/extracción | **Qwen2.5-14B-Instruct** (GGUF) | **Q4_K_M** | n_ctx **10240**, KV cache **Q8_0**, Flash Attention **ON**, GPU offload total, keep-loaded ON | ~10,0 GB |
| Visión (RRSS) | **Qwen2.5-VL-7B-Instruct** (GGUF) | **Q4_K_M** | n_ctx **4096**, KV Q8_0, FA ON, keep-loaded ON | ~6,0 GB (incl. mmproj) |
| Embeddings | **bge-m3** (el actual) | — | **GPU offload 0 (CPU)** | 0 GB |

**Total ≈ 16,0 GB — al límite.** Notas importantes:

- **Deja de usar `qwen2.5-14b @ Q8_0`**: ocupa ~15,7 GB él solo y además está provocando el error `400: n_keep > n_ctx 8192` detectado el 03-07. Q4_K_M pierde una calidad mínima y libera ~6,7 GB.
- Los embeddings en CPU (bge-m3 es pequeño y los batches de 20 chunks van sobrados en CPU) liberan ~1,2 GB.
- **Si aparece OOM** (Windows también consume VRAM del escritorio): primera palanca, bajar visión a **Qwen2.5-VL-3B-Instruct Q8_0** (~4 GB, calidad suficiente para carteles con texto grande); segunda, bajar n_ctx del 14B a 8192.
- En LM Studio: desactivar JIT/auto-unload para estos dos modelos (evitar swapping); servidor en `localhost:1234` como ahora.
- **`config.py` coherente con n_ctx 10240**: `RAG_MAX_TOKENS = 7000` con `RAG_CHARS_PER_TOKEN = 2.6` (ratio real medido: el texto web scrapeado tokeniza a ~2,1-2,5 chars/token, no 3,3). Además el pipeline tiene **reintento adaptativo**: si LM Studio devuelve error de contexto (`n_keep > n_ctx`), se recorta el texto al 70% y luego al 50% y se reintenta, así el proceso nunca pierde una localidad por el tamaño del prompt.

---

## 4. Mejoras extra propuestas (no pedidas, recomendadas)

1. **Caché de crawling por municipio**: la web municipal se re-rastrea entera para CADA pedanía; rastrearla una vez por municipio y re-puntuar por localidad (~10× menos crawling en municipios con muchas pedanías).
2. **Filtro de año en documentos**: descartar PDFs/carteles claramente de años anteriores salvo que no haya nada del año objetivo (entonces sirven para estimar, confianza baja).
3. **Métricas por localidad**: log JSON con documentos por fuente, imágenes VLM aceptadas/rechazadas y fiestas descartadas por el filtro de calendario — imprescindible para depurar.
4. **Cola de reintento RRSS con TTL**: perfil que falló hoy se reintenta en la siguiente sesión dedicada.
5. **`fuentes` a nivel de evento del programa** (v2): trazabilidad fina.

---

## 5. Orden de implementación

| Etapa | Contenido | Estado |
|---|---|---|
| **A** | M4 (orden + web localidad vacía + dedupe) + M5 (procedencia, chunking, cuotas, prompt) + M6 (filtro calendario) | ✅ **IMPLEMENTADA 03-07-2026** (72 tests pasan + E2E verificado) |
| **B** | M1 social_finder nivel 1 (web) + sync a `lugares_espana.json` | ✅ **IMPLEMENTADA 04-07-2026** (90 tests + cosecha en vivo verificada) |
| **C** | M2 social_apps (SafetyGuard → driver FB → IG → X) + runner + caché de contenido | ✅ **IMPLEMENTADA 04-07-2026** (107 tests; diagnóstico en vivo OK; falta la sesión supervisada de ejecución) |
| **D** | M3 vision_analyzer sobre capturas de apps | ✅ **IMPLEMENTADA 04-07-2026** (120 tests; VLM en vivo: cartel→transcripción perfecta, paisaje→false) |
| **E** | Tests + E2E + README + ajuste de modelos LM Studio | pendiente |

**Notas de la implementación de la Etapa A (03-07-2026):**
- Nuevo `fuentes.py` (constantes, prioridades, rótulos, detección de calendario) y `scraper/social_content.py` (lector de la caché RRSS que llenará la Etapa C).
- `AsyncTwoPassSpider.crawl()` y `search_locality_web()` devuelven documentos etiquetados y comparten `visited_urls`.
- `chunk_documento()` respeta líneas/frases y mantiene íntegros los bloques con ≥3 horarios; `seleccionar_chunks()` aplica las cuotas; `ensamblar_contexto()` rotula por fuente.
- `LMSTUDIO_CHAT_MODEL = "qwen2.5-14b-instruct@q4_k_m"` (el Q8 era demasiado lento y no cabe con el resto).
- E2E verificado: fiesta hallada solo en buscador → `solo_fuentes_no_oficiales: true` + confianza baja automática.

**Notas de la implementación de la Etapa B (04-07-2026):**
- `scraper/social_finder.py`: normaliza/clasifica enlaces (rechaza sharers, posts, grupos, eventos, redirectores), elige por frecuencia (los del footer aparecen en todas las páginas) y cachea en `redes_sociales_cache.json` con `pendiente_apps: true` para las redes no halladas → esa es la cola de la Etapa C.
- El spider cosecha perfiles SOLO desde páginas internas del dominio oficial (cero falsos positivos) durante la Pasada 1, sin coste extra.
- `sync_redes_a_lugares.py`: volcado idempotente y re-ejecutable. **lugares_espana.json aún no es definitivo**: la caché es la fuente de verdad, los ids que aún no existan en el JSON se conservan y se informan, y siempre se deja backup con timestamp.
- Prueba en vivo (homepages reales): Albacete y La Adrada → los 3 perfiles oficiales exactos, 0 falsos positivos.

**Notas de la implementación de la Etapa C (04-07-2026):**
- `scraper/social_apps/`: `app_controller.py` (localización de ventanas + SafetyGuard), `drivers.py` (base + IG/FB/X), `cola.py`, `contenido_cache.py`, `util.py` (validación estricta, fechas relativas), `runner.py`; CLI `social_apps_runner.py` con modos `diagnostico` (solo lectura) y `ejecutar` (exige `--confirmo-pc-dedicado`).
- HALLAZGO: las "apps de Store" de Instagram/Facebook son PWAs bajo `msedge.exe` (como X). La config de ventanas se ajustó; con varias candidatas se elige la de título más corto (la PWA pura, no una pestaña del navegador).
- Diagnóstico en vivo: las 3 ventanas localizadas ([OK] instagram/facebook/twitter). PENDIENTE: sesión de ejecución supervisada con el usuario delante (`--modo ejecutar --max-tareas 3`), que requiere la caché de perfiles poblada (correr la Fase 2 primero).
- Lectura de perfiles: texto accesible del árbol UIA + captura de ventana por posición de scroll → las capturas quedan en `rrss_capturas/<lugar_id>/` listas para el VLM de la Etapa D. Los drivers usan regex de controles configurables porque la UI de las apps cambia con actualizaciones: se afinarán en la sesión supervisada.
- **FIX tras la 1ª sesión supervisada (04-07-2026)**: el driver clicaba nodos de texto no navegables (el tipo UIA "Link" no existe — es "Hyperlink") y no verificaba la navegación, por lo que ignoraba el perfil del ayuntamiento y seguía scrolleando los resultados. Ahora: candidatos = filas clicables reales (ListItem/Hyperlink/Button o el ancestro clicable de un texto), se excluye el eco de la consulta, y tras cada clic se **verifica por el título de la ventana** que el perfil quedó abierto ("Resultados de búsqueda" nunca es un perfil); si no, Alt+← y siguiente candidato. Además, **filtro de fecha estricto**: ningún post de hace 1 año o más entra en la caché (el scroll se detiene al llegar a esa antigüedad).
- **FIX tras la 4ª sesión supervisada (04-07-2026)** — FB entró bien al perfil pero acabó en la web del ayuntamiento: la verificación dura por handle falló (FB no muestra el handle en la página) y al reintentar clicó el enlace "donostia.eus/Gazteria" del panel Detalles (pasaba el filtro difuso). Arreglos: (a) los candidatos que parecen URL/correo (`es_link_externo`) quedan VETADOS — el driver nunca sale del perfil; (b) verificación por NOMBRE de página: si el handle no es visible, se acepta que el título contenga el nombre del candidato clicado (ya pre-validado contra el handle); (c) lectura de FB en dos fases como pidió el usuario: feed de Publicaciones (scroll corto) + sección **Fotos** con visor (clic en la primera foto y avance con flecha derecha — ahí están los carteles); el visor de galería (abrir primera + flecha derecha + ESC) se generalizó en DriverBase y lo comparten IG y FB.
- **FIX tras la 3ª sesión supervisada (04-07-2026)** — con capturas del usuario:
  (a) *X* buscaba en la pestaña "Top" y arrastraba contenido de cualquier cuenta → ahora va SIEMPRE a la página de resultados y clica la pestaña **"Personas/People"** antes de evaluar candidatos (allí las filas muestran @handle y la validación es exacta).
  (b) *Facebook* mostraba el resultado pero no lo clicaba → en resultados se clica el filtro **"Páginas"**, la recolección de candidatos se hace en UN solo paseo del árbol UIA (los árboles de FB son enormes y multiplicar recorridos por tipo era lentísimo/frágil) y se loguea una muestra de candidatos cuando nada valida (diagnóstico de próximas sesiones).
  (c) *Instagram* entraba al perfil pero scrolleaba la cuadrícula sin abrir posts (la cuadrícula no expone captions) → driver propio: **clic en la primera publicación** (elemento clicable más arriba-izquierda bajo la cabecera) y avance **con flecha derecha** post a post leyendo el caption del modal + captura, ESC al terminar. El parser de fechas aprende el formato corto de IG/X ("1 sem", "3 d").
- **FIX tras la 2ª sesión supervisada (04-07-2026)** — tres fallos reales:
  (a) *Instagram* no tiene campo de búsqueda visible en la PWA (es un icono del carril) → `_abrir_buscador()` en dos pasos: si no hay Edit, clica el icono "Búsqueda/Search" y busca el Edit del panel.
  (b) *X* desistía en milisegundos → reintentos con espera (las sugerencias tardan) + segunda fase con ENTER hacia la página de resultados completa.
  (c) *Facebook* muestra el NOMBRE de la página, no el handle ("Donostiako Gazteria" vs `dssgazteria`) → pre-validación laxa con `similitud_handle()` (difflib, umbral 0.55) solo para INTENTAR el clic, y **verificación dura post-clic**: el handle debe aparecer en el título o el contenido del perfil (`@handle`, `facebook.com/handle`); sin confirmación no se lee nada (cero falsos positivos en la atribución).

**Notas de la implementación de la Etapa D (04-07-2026):**
- `llm_processor/vision_analyzer.py`: prefiltro sin GPU por caption (sin keyword festiva la captura NO va al VLM — regla anti-falsos-positivos del usuario), redimensionado a 1280px + JPEG base64, una sola llamada al VLM que clasifica y transcribe (`{"es_programa_fiestas", "texto_extraido"}`), tope por perfil, y actualización de `rrss_contenido_cache.json` (campos `es_programa`, `texto_programa`, `vision_procesada`; los errores no se marcan para reintentarse).
- CLI `procesar_capturas.py` (`--max N`): post-proceso que NO requiere PC dedicado; se lanza tras cada sesión del runner.
- Verificado en vivo con `qwen/qwen2.5-vl-7b` en LM Studio: cartel sintético de programa → `true` + transcripción fiel de todas las fechas/horas/actos; paisaje → `false`. La API de imágenes de LM Studio (data-URI base64) funciona.

---

## 6. Verificación

1. **Unitarios**: validador de perfiles (falsos positivos: peña privada, pueblo homónimo); chunker (programa de 30 líneas NO se parte); cuotas RAG (oficial nunca expulsado); `solo_fuentes_no_oficiales` fuerza confianza baja; filtro calendario (festivo sin celebración → fuera; patronal el 15/8 con verbena → dentro).
2. **SafetyGuard en vivo** (contigo delante): mover el ratón/cambiar de ventana durante una sesión → todo se pausa; cerrar la app → aborta limpio; verificar que jamás se envía input fuera de la ventana.
3. **Social finder nivel 1**: 8-10 municipios reales → precisión de los enlaces cosechados (objetivo: 0 falsos positivos).
4. **Runner de apps**: sesión corta supervisada con 3-5 perfiles reales; matriz de confusión del VLM con ~10 imágenes (programa sí/no).
5. **E2E**: `main.py` en 1-2 municipios con la caché RRSS ya poblada; revisar `fuentes`, `solo_fuentes_no_oficiales`, texto de carteles en contexto, dedupe de URLs en el log y que ninguna "fiesta" de calendario laboral haya entrado.

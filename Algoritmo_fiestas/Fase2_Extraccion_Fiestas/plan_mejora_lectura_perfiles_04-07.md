# Plan de mejora — Lectura de información de los perfiles de RRSS

**Fecha:** 04-07-2026 · **Estado:** M1-M6 IMPLEMENTADAS (04-07-2026, 140 tests pasan).
Pendiente: verificación en vivo (sesión supervisada del runner + `procesar_capturas.py`,
que requiere los modelos de LM Studio — el usuario pidió avisar antes de usarlos).
M7 (presupuesto guiado por el día del patrón) queda opcional, no implementada.
**Base:** análisis de las capturas reales de las sesiones supervisadas (perfil FB "Donostia Gazteria", sección Fotos, modal de post de IG, búsqueda de X).

---

## 1. Análisis de la situación actual

### Cómo lee hoy el driver
Por cada posición de scroll (o del visor), junta TODO el texto accesible nuevo en un
"bloque", le intenta sacar UNA fecha y guarda UNA captura. El VLM solo analiza la
captura si el texto del bloque contiene una keyword festiva en castellano.

### Problemas detectados (con evidencia de las capturas)

**P1 — CRÍTICO: bloques mezclados → fechas incorrectas y parada prematura.**
El perfil de FB muestra a la vez: panel *Detalles*, *Destacados* (¡con posts de
sept-2025 y **nov-2022**!), tarjeta *Fotos* y el feed de *Publicaciones*. El primer
"bloque" cosechado mezcla todo eso; `parsear_fecha_post` devuelve la primera fecha
que encuentra, que puede ser la del Destacado de 2022 → **el filtro de ≥1 año aborta
la lectura del perfil entero en el primer viewport**. Además, la fecha asignada a
cada bloque es arbitraria (no es la del post que aparece en la captura).

**P2 — Granularidad: bloque ≠ post.**
Los posts individuales tienen su propia fecha y su propio caption. Al mezclarlos, el
filtro de fecha por post es impreciso, el dedupe falla y el prefiltro del VLM evalúa
keywords de un post contra la captura de otro.

**P3 — El prefiltro por caption pierde los carteles más valiosos.**
La cuadrícula de Fotos de Donostia Gazteria lo demuestra: carteles "Intxaurjaiak
2026", "San Juan bezpera auzoan ospatzen", "Azken Jaia" — programas reales con
fechas y horarios EN LA IMAGEN, con caption mínimo o en euskera. El prefiltro
actual (keywords en castellano en el texto del post) los descartaría sin llegar
al VLM. Lo mismo pasará en Cataluña/Galicia.

**P4 — El visor no detecta el final de la galería ni deduplica.**
Tras la última foto, la flecha derecha no avanza: el driver seguiría capturando la
misma imagen hasta agotar el tope (30 capturas idénticas → 30 llamadas al VLM).
Y las mismas fotos aparecen en el feed y en Fotos → VLM duplicado.

**P5 — La ficha del perfil se ignora.**
El panel *Detalles* de FB (y la bio de IG/X) contiene oro: web oficial
(`donostia.eus/Gazteria`), email (`gazteria@donostia.eus`), teléfono, categoría
("Organización gubernamental"), dirección. Hoy no se extrae, y es además la señal
de validación más fuerte que existe: **si la web de la bio coincide con el
`sitio_web` del lugar, el perfil queda confirmado como oficial** (y al revés:
una discrepancia delata un falso positivo).

**P6 — Los Destacados no se procesan deliberadamente.**
Muchos ayuntamientos FIJAN el programa de fiestas en Destacados/highlights.
Hoy solo entran por accidente (mezclados en bloques) y con las fechas viejas
rompen la lectura (P1).

---

## 2. Mejoras propuestas

### M1 — Cosecha por POST (clustering), no por viewport · CRÍTICO
- Recoger los `Text` del árbol UIA CON su rectángulo y agruparlos por contenedor:
  subir al ancestro "artículo" (ListItem/Group con altura < viewport) o, en su
  defecto, clustering por bandas verticales solapadas de la columna principal.
- Resultado: lista de posts individuales `{texto, fecha, rect}` por viewport.
- **Nueva regla de parada**: parar solo tras **3 posts consecutivos** con fecha
  ≥ 1 año, y nunca en los 2 primeros viewports (zona de Destacados/cabecera).
  El filtro de ≥1 año se aplica post a post (los viejos se descartan
  individualmente sin abortar el resto).
- La captura del viewport se asocia a los posts visibles en él.

### M2 — Ficha del perfil + validación cruzada por web de la bio
- Al abrir un perfil (antes de leer posts): extraer nombre, handle, seguidores,
  bio/Detalles, web enlazada, email (todo texto ya visible; coste cero).
- Guardar como `ficha` en `redes_sociales_cache.json`.
- **Validación cruzada**: si la web de la bio coincide (dominio) con el
  `sitio_web` del lugar (o de su municipio padre) → `verificado_por:
  "bio_web_match"` (máxima confianza). Si contradice → marcar `sospechoso: true`
  y log para revisión (nunca leer contenido de un perfil sospechoso).
- Bonus: si el lugar NO tiene `sitio_web` en lugares_espana.json y la bio de un
  perfil verificado la aporta, se registra para enriquecer la Fase 1.

### M3 — Prefiltro del VLM multiidioma + OCR-lite para carteles sin caption
- Añadir a las keywords del prefiltro las variantes cooficiales que ya existen
  en `DICCIONARIO_FESTIVO` (jaiak, kontzertua, dantza, erromeria, txosna,
  festes, festa, correfoc, cercavila...) + "jaia", "bezpera", "eguna".
- Para capturas SIN caption o con caption corto (típico en la sección Fotos):
  **OCR-lite con Tesseract (CPU, ya instalado)** sobre la captura; si el OCR
  detecta keywords festivas (en cualquier idioma) → pasa al VLM.
  Así se mantiene el espíritu del filtro del usuario (ninguna imagen va al VLM
  sin indicio festivo) sin perder los carteles cuyo texto está EN la imagen.
  El VLM sigue siendo la puerta final anti-falsos-positivos.

### M4 — Dedupe de capturas + detección de fin de galería
- Hash perceptual barato (thumbnail 16×16 en escala de grises) de cada captura.
- Visor: si el hash no cambia tras 2 flechas → fin de la galería, parar.
- Antes del VLM: descartar capturas con hash ya visto en el mismo perfil
  (las fotos del feed repetidas en la sección Fotos).

### M5 — Leer los Destacados de FB deliberadamente
- Tras la ficha (M2) y antes del feed: si hay carrusel de Destacados, abrir el
  primero y recorrerlo con flecha derecha (mismo visor genérico), respetando el
  filtro de ≥1 año por elemento. Ahí suele estar el programa fijado.

### M6 — Timestamps precisos por post (FB/X)
- Los enlaces de fecha de cada post ("1 de julio a las 1:29 p. m.") son
  Hyperlinks en el árbol UIA: recolectarlos por cluster (M1) y usarlos como
  fecha del post con prioridad sobre el regex del texto general.
- Ampliar `parsear_fecha_post` con el formato "a las H:MM p. m." y meses
  cooficiales frecuentes (urtarrila... / gener... / xaneiro...) como bonus.

### M7 — (Opcional) Presupuesto de lectura guiado por el calendario festivo
- Si el lugar tiene día del patrón conocido (patrones_cache), no cortar el
  scroll hasta haber cubierto los 2 meses alrededor de esa fecha dentro de la
  ventana de 1 año (los programas se publican esas semanas).

---

## 3. Orden de implementación

| Paso | Contenido | Motivo |
|---|---|---|
| 1 | M1 (clustering + regla de parada) | corrige el bug crítico de parada prematura |
| 2 | M4 (hash + fin de galería) | evita 30 capturas idénticas y VLM duplicado |
| 3 | M2 (ficha + validación cruzada) | más fiabilidad con coste casi nulo |
| 4 | M3 (prefiltro multiidioma + OCR-lite) | recupera los carteles en euskera/catalán/gallego |
| 5 | M5 (Destacados) + M6 (timestamps) | más cobertura y fechas exactas |
| 6 | M7 opcional | afinado final |

Cada paso deja el runner funcional y se valida con una sesión supervisada corta
(`--max-tareas 3`) antes del siguiente.

## 4. Verificación

1. **Unitarios**: clustering con rects sintéticos (3 posts + panel lateral → 4
   clusters, fechas correctas); regla de parada (post viejo aislado no corta,
   3 consecutivos sí); hash perceptual (capturas iguales/distintas); OCR-lite
   prefiltro con imagen sintética en euskera ("JAIAK 2026" → pasa al VLM);
   validación cruzada bio-web (match, mismatch → sospechoso).
2. **Sesión supervisada** con el mismo perfil problemático (Donostia Gazteria):
   verificar que ya no aborta por los Destacados de 2022, que la galería de
   Fotos termina al llegar al final real, y que los carteles en euskera llegan
   al VLM y salen transcritos.
3. **procesar_capturas.py** sobre las capturas de esa sesión → medir cuántos
   programas detecta el VLM vs la versión anterior.

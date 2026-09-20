# Plan de implementación — fidelidad de la ficha y pérdidas silenciosas

**Fecha:** 2026-09-12
**Base de medición:** `fiestas_amplio_v2.json` (20 municipios, 82 fichas, 705 min)
**Comparación:** `fiestas_amplio_20muni.json` (mismos 20, misma semilla, 81 fichas, 578 min)
**Material de validación:** los 20 logs `fase2_20260910_231446` → `fase2_20260911_103743`
y los 1198 volcados de `debug_contexto/`.

**Objetivo:** que ninguna ficha afirme más de lo que sostiene su documento, y que las
pérdidas que hoy no se ven en ningún contador dejen de ser invisibles.

Casi todo lo que sigue se valida **sin ejecutar el pipeline**: los volcados de
`debug_contexto/` traen el contexto ensamblado y los chunks de cada enrichment, así que
las guardas se pueden pasar en frío sobre el material real de esta ejecución.

---

## Corrección de la medición anterior

El primer análisis dio por perdidas 38 fichas «con el programa delante». Al revisar los
volcados, la mayoría de esas páginas alternativas **son de otro pueblo**. Clasificadas las
42 discrepancias del localizador por dominio:

| Destino de la página determinista | Casos |
|---|---|
| Dominio del propio pueblo (`pozohondo.es`, `alcuescar.es`, `arevalo.es`, `zazuar.es`…) | 14 |
| Otro municipio o página ajena (`almeriaciudad.es`, `albacete.es`, `diario.madrid.es`, `festejos.ayto-alcaladehenares.es`, `paxinasgalegas.es`, `badajozdirecto.com/Zafra`, `aemet.es`…) | 28 |

«Manda el modelo» (`text_analyzer.py:4296`) no es un fallo: es lo que impide que a Viator
le entre el programa de la Feria de Almería y a Vianos el de Albacete capital. La Tanda 4
se recorta en consecuencia.

---

## Tanda 1 — El duplicado que sale con `confianza: alta`

### El problema, medido

Almansa tiene **dos** Fiestas Mayores en la salida:

```
2026-03-13 .. 2026-03-29  [alta]  Fiestas Mayores de Almansa 2026
2026-04-30 .. 2026-05-06  [alta]  Fiestas Mayores de Almansa en honor a la Virgen de Belén
```

Las reales son las de abril-mayo. La de marzo no existe. Es el peor tipo de error del
proyecto: no es una ficha pobre, es una ficha **inventada y marcada como fiable**.

### La causa

Las dos se enriquecieron **con el mismo documento**:
`almansaturistica.es/wp-content/uploads/2026/04/PROGRAMA-DE-FIESTAS-…`. El propio log lo
dice sin que nadie lo escuche:

```
[ENRICHMENT] 'Fiestas Mayores de Almansa 2026': el documento no menciona los días 2026-03-16 a 2026-03-18
[ENRICHMENT] 'Fiestas Mayores de Almansa 2026': el documento no menciona los días 2026-03-25 a 2026-03-27
```

Ninguna de las dos guardas la coge:

- **FUSION** (`festival_filter`) solo une fiestas **próximas en fecha**. Marzo y mayo no
  se tocan.
- **DEDUP** (`text_analyzer.py:3949-3961`) sí corrió, y falló porque las líneas que ve el
  modelo son solo nombre, rango, núcleo y días de programa. Los núcleos no se solapan (una
  se quedó sin núcleo, ver Tanda 3) y los rangos tampoco. **El `url_programa` compartido,
  que es la señal decisiva, no se le enseña.**

### El arreglo

1. **Añadir `url_programa` a las líneas del prompt de DEDUP.** Una línea más por ficha, en
   `text_analyzer.py:3955-3960`. Dos fichas cuyo programa se copió del mismo documento son
   casi siempre la misma fiesta, y el modelo hoy no puede saberlo.

2. **Una regla determinista para el caso estrecho**, aplicada antes del modelo: mismo
   `url_programa` **y** un nombre contenido en el otro tras normalizar. `"fiestas mayores
   almansa"` ⊂ `"fiestas mayores almansa en honor a la virgen de belen"`. Sobrevive la de
   más días de programa, que es el criterio de `_riqueza` que ya existe.

3. **Bajar la confianza cuando el programa contradice el rango.** El aviso «el documento no
   menciona los días X a Y» ya se emite (`text_analyzer.py:4563`). Si cubre la **mayoría**
   del rango de la ficha, la ficha no puede seguir siendo `alta`.

### Lo que NO se hace

**No fusionar por `url_programa` a secas.** En esta misma salida hay cuatro fichas de
Capilla y tres de Nava de Arriba compartiendo una URL genérica, y son fiestas distintas.
El propio prompt de DEDUP ya lo dice: perder una fiesta real es peor que dejar una
repetida. Por eso el punto 2 exige *además* contención de nombres.

**No tocar la FUSION por proximidad.** Ensancharla para que alcance de marzo a mayo
fusionaría patronales con romerías legítimas.

### Cómo se mide

Sobre `fiestas_amplio_v2.json`, en frío: pares de fichas de la misma localidad con el mismo
`url_programa` y contención de nombre. Hoy es **1** (Almansa). **Objetivo: 0.**

Contraprueba obligatoria, sobre la misma salida: los grupos de Capilla (4 fichas) y Nava de
Arriba (3) deben **seguir intactos**. Si la regla los toca, la regla está mal.

---

## Tanda 2 — La bitácora no distingue «no hay» de «no miré»

### El problema, medido

Piedrahíta murió por tope: `minutos: 97.6`, `cortado_por_tope: true`, `codigo_salida: -1`.
Murió en la localidad **[5/6] Pesquera**, con la [6/6] sin empezar. Y la bitácora lo
resume así:

```json
"localidades": 7, "localidades_con_fiesta": 4, "localidades_sin_fiesta": 3
```

Esas «3 sin fiesta» son 1 mirada sin resultado y **2 que nadie abrió**. En la ejecución
anterior esas dos localidades sí dieron ficha (`05186000401` San Blas, `05186000601` San
Juan Bautista con programa). El contador dice lo mismo en los dos casos.

### La causa

`ejecutar_amplio.py:309`:

```python
"localidades_sin_fiesta": n_loc - len(loc_con),
```

Una resta no sabe si el municipio se cortó a la mitad. Es el único sitio donde un run
truncado podría verse, y es justo donde se disimula.

### El arreglo

1. **Contar las localidades realmente procesadas** desde `localidades_completadas` de la
   salida, no restando. Tres campos en vez de uno:
   `localidades_procesadas`, `localidades_sin_fiesta` (procesadas y vacías) y
   `localidades_no_alcanzadas`.
2. **Que el resumen final lo enseñe.** La tabla de `ejecutar_amplio.py:342-347` suma
   `localidades_sin_fiesta` de todos los municipios; hoy ese total está inflado.
3. **Marcar la salida.** Un municipio cortado no debería entrar en
   `municipios_completados` —hoy no entra, bien— pero tampoco debería parecer completo en
   la bitácora.

### Lo que NO se hace

No subir el tope ni quitarlo. El tope hace su trabajo: impedir que un municipio atascado se
lleve la noche. El problema es que la pérdida no se contabiliza, no que exista.

Queda anotado, sin arreglar aquí: `minutos: 97.6` con `--tope-municipio 75` significa que
`subprocess.run(timeout=…)` (`ejecutar_amplio.py:291`) tardó ~22 min en cerrar el proceso
hijo. Merece medición propia antes de tocarlo.

### Cómo se mide

Regenerar la bitácora contra `fiestas_amplio_v2.json` ya existente. Piedrahíta debe pasar
de `sin_fiesta: 3` a `sin_fiesta: 1, no_alcanzadas: 2`. Los otros 19 municipios no deben
cambiar ni un número.

---

## Tanda 3 — Dos de cada tres llamadas de NÚCLEO se tiran

### El problema, medido

| Etapa | Llamadas | Cortadas en el primer intento | Tope inicial |
|---|---|---|---|
| NUCLEO | 30 | **20 (67%)** | 200 tok |
| DEDUP | 21 | **13 (62%)** | 400 tok |
| PROCEDENCIA | 242 | 10 (4%) | 1200 tok |

Cada corte es una ida y vuelta completa a OpenRouter tirada a la basura, más el reintento.
Es parte medible del +22% de reloj de esta ejecución. Y **tres se perdieron del todo**: el
reintento también se cortó y el JSON salió malformado. Una de ellas dejó a la «Feria del
Ganado» de Piedrahíta sin núcleo, y esa ficha sin núcleo es la que impide que DEDUP tenga
señal en casos como el de la Tanda 1.

### La causa

`config.py:177` `NUCLEO_MAX_TOKENS = 200` y `config.py:182` `DEDUP_MAX_TOKENS = 400`.
Son topes calibrados para un modelo que no razona. Toda la ejecución fue por
`qwen/qwen3-32b` (1086 llamadas de 1086), que gasta el presupuesto de salida pensando.
El comentario de `text_analyzer.py:2739-2747` documenta exactamente este efecto para
PROCEDENCIA — y ahí se corrigió subiendo el tope a 1200, que es por lo que PROCEDENCIA
falla el 4% y NUCLEO el 67%.

El reintento (`text_analyzer.py:2748`) es **de una sola vuelta**, así que un segundo corte
es pérdida definitiva.

### El arreglo

1. `NUCLEO_MAX_TOKENS: 200 → 1200` y `DEDUP_MAX_TOKENS: 400 → 2400`. Son los valores a los
   que el reintento ya sube (×6, `LLM_FACTOR_REINTENTO_TRUNCADO`), y con los que las
   llamadas terminan: las respuestas reales medidas van de 532 a 1043 tokens en NUCLEO y
   hasta 1790 en DEDUP.
2. **Permitir un segundo reintento** cuando el primero también se corta, hasta
   `LLM_TOPE_REINTENTO = 12000`. Hoy el bucle se rinde y devuelve JSON roto.

### Lo que NO se hace

No se sube el tope de todas las etapas «por si acaso». PROCEDENCIA son 242 llamadas y
falla el 4%: ahí el tope está bien y subirlo solo pagaría más tokens.

### Cómo se mide

Cuenta directa sobre los logs del siguiente run: `finish_reason=length` por etiqueta.
**Objetivo: NUCLEO y DEDUP por debajo del 10%, y cero `JSON malformado del LLM`.**
Y el reloj total, que debería recuperar parte de los 127 min de más.

---

## Tanda 4 — Respaldo del localizador, acotado al dominio del pueblo

### El problema, medido

48 fichas acaban en «sin programa que estructurar; no se pregunta». De las 42
discrepancias entre el localizador y el recuento determinista, **14 tienen la página
determinista en el dominio del propio pueblo** y aun así se descartan. Casos claros:

| Fiesta | Elige el modelo | Descarta (y tiene actos) |
|---|---|---|
| Fiestas Patronales de San Antonio (Nava de Arriba) | `orkestas.es` (agregador) | `pozohondo.es/fiestas` (6) |
| Fiestas Patronales Virgen del Rosario (Alcuéscar) | `alcuescar.es/…asset_publisher…` | `alcuescar.es/…asset_publisher…` (12) |
| Ferias y Fiestas de San Victorino (Arévalo) | — | `arevalo.es` (23) |

### La causa

`text_analyzer.py:4294-4302`. El determinista solo se usa **si el modelo no eligió nada**:

```python
if not urls_programa and url_deterministe:
    urls_programa = [url_deterministe]
```

Si el modelo eligió una página sin actos, la alternativa se registra en el log y se tira.
Después `hay_programa` (`text_analyzer.py:4364-4365`) se calcula solo sobre lo que el
modelo eligió, y la ficha se queda sin programa.

Y el mensaje del else (`text_analyzer.py:4426`) imprime `n_actos_det` —el recuento sobre
**todo** el contexto— mientras la decisión usa `n_actos_documento` —solo las páginas del
modelo—. Por eso el log dice «la mejor página trae 26 actos» justo antes de rendirse: son
dos números distintos con el mismo aspecto.

### El arreglo

1. **Añadir** —no sustituir— la página determinista a `urls_programa` cuando se cumplan
   las tres condiciones: el modelo eligió algo, su elección da menos de
   `ENRICHMENT_MIN_ACTOS_EN_PAGINA` actos, y la determinista está en un **dominio del
   propio pueblo o municipio**. `urls_programa` ya es una lista precisamente para poder
   llevar dos fuentes.
2. **La propiedad del dominio no se inventa**: cada documento ya trae su etiqueta `fuente`
   (`web_municipio`, `web_localidad`), que es la clasificación que el proyecto ya usa.
   Basta exigir que la página determinista venga de una de esas dos.
3. **Que el mensaje deje de mentir.** En el else, imprimir los dos números con su nombre:
   cuántos actos tiene la página elegida y cuántos la mejor del contexto.

### Lo que NO se hace

**No se toca «Manda el modelo».** En 28 de 42 casos el determinista apuntaba a otro pueblo,
y esa regla es lo único que impide que la Feria de Almería acabe en la ficha de Viator. El
respaldo solo entra con la etiqueta de fuente oficial delante.

**No se baja `ENRICHMENT_MIN_ACTOS_EN_PAGINA`.** El umbral de 3 es lo que evita los 39
actos inventados de Sierra.

### Cómo se mide

En frío, sobre los volcados de `debug_contexto/`: de las 14 fichas con determinista en
dominio propio, cuántas pasarían la nueva condición. Después, sobre la salida del run:
cuántas de esas 14 ganan programa, **y cuántos de esos actos son rastreables hasta su
documento**. La segunda mitad es la que evita el autoengaño.

---

## Tanda 5 — La visión sigue sin dispararse

### El problema, medido

**Cero** líneas `[VISION]` o `[VLM]` en las 12 horas de ejecución, después de cuatro
commits dedicados a conectarla (5740933, 7993995, 37252bc, f1c7cb5). Mientras tanto:

- `VISION_ENABLED = True` (`config.py:620`) y la cadena de imports funciona (comprobado).
- La araña rastreó en vivo en 17 de 20 municipios y pasó **1014 imágenes por OCR**.
- La cobertura de programa no se ha movido: **29/82 fichas (35%)** frente a 28/81 (35%).

### La causa

Las dos puertas de entrada exigen que el paso anterior devuelva **exactamente vacío**:

```python
# heuristic_spider.py:865-877
if not (text or "").strip():
    text = await self._leer_cartel_con_vlm(img_bytes, img_url)
```

```python
# google_search.py:1225-1229
if not (texto_pdf or "").strip():
    texto_pdf = await _leer_con_vision(_imgs_vlm, url)
```

Tesseract sobre un cartel casi nunca devuelve cadena vacía: devuelve basura. Una sola
letra suelta cierra la puerta. El comentario del propio código ya sabe que Tesseract lee
«2028» donde pone 2026 — pero ese caso **no llega** al VLM, porque no está vacío.

Y si fallara, no lo veríamos: `[VISION] no disponible` y `[VISION] imagen ilegible` son
`logger.debug` (`heuristic_spider.py:906,913`, `google_search.py:1103`) y el nivel del
run es INFO (`main.py:69`).

### El arreglo

1. **Cambiar la condición de vacío por condición de señal.** El VLM entra si el texto del
   OCR **no contiene ninguna hora ni ninguna fecha** — que es lo que el pipeline necesita
   de un cartel. `contar_actos_horarios` ya existe y es exactamente ese detector.
2. **Subir los avisos de `debug` a `warning`.** Una visión que no arranca tiene que verse
   en el log, no deducirse de su ausencia.
3. **Una línea de recuento por municipio**: imágenes candidatas, cuántas fueron al VLM,
   cuántas devolvieron texto. Sin esto no hay forma de saber si la tanda funcionó.

### Los frenos

`VISION_MAX_IMAGES_SPIDER = 3` por rastreo y `VISION_MAX_IMAGES_DOC = 2` ya existen y
siguen mandando. Con 1014 imágenes candidatas, aflojar la condición **sin** los topes
convertiría cada municipio en una sesión de VLM. Los topes son la parte del diseño que hay
que respetar, no la condición de vacío.

### Cómo se mide

Primero en frío, y esto es lo importante: **coger las imágenes ya cacheadas y contar
cuántas pasarían la nueva condición**. Si son 900 de 1014, la condición está mal puesta y
el tope se come la ejecución. Si son 30-60, tiene sentido seguir.

Después, sobre el run: fichas que ganan programa **y** actos que sobreviven al juez.
Recuperar 20 actos mal leídos de un cartel es peor que no recuperar ninguno.

---

## Tanda 6 — Arreglos pequeños y ciertos

### 6a. URLs crudas en `fuentes`

Dos fichas (`FestivArroyo 2026`, `Semana de las Personas Mayores`) traen una URL entera
donde debería ir una categoría. Rompe el esquema para quien consuma el JSON.

Causa exacta, `text_analyzer.py:4033-4034`:

```python
url = fiestas[i].get("url_programa")
if url and url not in (fiestas[gana].get("fuentes") or []):
    fiestas[gana].setdefault("fuentes", []).append(url)
```

El DEDUP quiere conservar la procedencia de la ficha descartada, y la mete en el campo
equivocado. Debe ir a un campo propio (`urls_programa_fusionadas`) y, si hay que tocar
`fuentes`, añadir la **etiqueta** del documento, que es lo que hace
`reconciliar_procedencia`.

**Medida:** cero valores que empiecen por `http` en `fuentes`. Comprobable en frío sobre
la salida actual.

### 6b. El homónimo que entra por RESCATE

En Pesquera (Ávila) el rescate fabricó «Fiestas de Virgen de Rubialejos» a partir de una
frase que dice literalmente *«pesquera de duero se prepara para seis días de fiestas»* —
Valladolid. Solo no llegó al JSON porque el tope mató el proceso antes.

`_mencion_es_cola_de_otro_toponimo` (`text_analyzer.py:5266`) cubre el caso **cola**
(«Miraflores de la **Sierra**») mirando hacia atrás. No existe el simétrico hacia delante:
«**Pesquera** de Duero».

El arreglo: en `text_analyzer.py:5402`, descartar la mención si al nombre le sigue un
complemento toponímico (`de X`, `de la X`, `del X`) que **no** forma parte del nombre
oficial de la localidad ni del municipio.

**El riesgo hay que decirlo:** el docstring de la función vecina documenta que, sin exigir
artículo, «el ayuntamiento de Aranda de Duero» tumbaba las cuatro menciones de Aranda. La
regla hacia delante tiene el mismo peligro por el otro lado.

**Medida, obligatoria antes de dar la regla por buena:** pasarla en frío sobre los 1198
volcados de `debug_contexto/` y contar cuántas anclas hoy válidas deja de producir. Si
pierde alguna ancla de las que hoy sostienen una ficha correcta, no entra.

---

## Orden

| # | Tanda | Coste | Riesgo | Validable en frío |
|---|---|---|---|---|
| 1 | 6a — URLs en `fuentes` | minutos | ninguno | sí, completo |
| 2 | 3 — presupuestos NUCLEO/DEDUP | minutos | ninguno | no (se ve en el run) |
| 3 | 2 — bitácora honesta | bajo | ninguno | sí, completo |
| 4 | 1 — duplicado `alta` | medio | medio (fusionar de más) | sí, completo |
| 5 | 4 — respaldo por dominio propio | medio | medio (importar otro pueblo) | sí, parcial |
| 6 | 5 — visión | alto | alto (actos inventados) | sí, la condición |
| 7 | 6b — homónimo por cabeza | bajo | alto (perder anclas buenas) | sí, completo |

Las tres primeras no tocan el camino de datos y se pueden meter juntas. Las tandas 1 y 4
tocan el contenido de la ficha y necesitan su contraprueba antes de entrar. Las tandas 5 y
6b son las que pueden empeorar la salida si se hacen mal, y por eso van al final y con su
medición en frío por delante.

**Piedrahíta se relanza solo**, después de la Tanda 2, para tener las dos localidades que
faltan sin repetir los otros 19 municipios.

---

## Lo que este plan deja fuera a propósito

- **Los rangos inverosímiles** (Carnaval de Alcuéscar 1-28 feb, San Juan de Pozohondo
  20 jun - 4 jul). Son 6 fichas y la causa está en discovery, no en una guarda; merecen
  medición propia antes de tocar nada.
- **Las 6 fichas sin ninguna fuente.** Son estimaciones declaradas (`es_estimada`), no un
  fallo.
- **Las regresiones de Tarazona y Cardeñajimeno.** Tarazona perdió un programa de 43 actos
  y bajó de `alta` a `baja`; Cardeñajimeno perdió una fiesta entera. Las dos vienen de que
  discovery encontró menos que la vez anterior con el mismo material cacheado, y eso es
  variabilidad del modelo, no una guarda mal puesta. Sin dos ejecuciones más de los mismos
  municipios no hay forma de separar la regresión del ruido, y arreglar ruido es la manera
  más cara de no arreglar nada.

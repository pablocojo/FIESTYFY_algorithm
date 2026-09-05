# Plan de implementación — recall y decisión del LLM

**Fecha:** 2026-09-04
**Problemas que ataca:** P0-1, P0-2, P1-3 y P2-6 de `problemas_actuales_20260904.md`
**Objetivo medible:** subir el recall en los 4 municipios trampa de 2 fiestas a ≥6, sin que
vuelva a colarse ninguna ficha de otra localidad.

## Decisiones ya tomadas

| Pregunta | Decisión |
|----------|----------|
| Nombre oficial completo del municipio | Preguntarlo al LLM una vez por municipio y cachearlo |
| Repregunta que vuelve a salir incoherente | Ante la duda, fuera |
| Ampliar `descartar_homonimos` a todos los documentos | No |
| Nombres de fiesta inestables (P1-5) | De momento nada |

## Orden y por qué

La tanda 1 va **antes** que la 2. Darle más poder de decisión al modelo sobre un contexto
dominado por Santa Marta de Colombia y Astorga traslada el fallo en vez de resolverlo; con
la consulta arreglada, ese poder rinde.

---

## Tanda 1 — cortar el ruido en origen

### 1.1 · Arreglar la comunidad, que nunca llega

**Dónde:** `scraper/google_search.py`, `_build_queries()` (línea 93).

```python
comunidad = (municipio.get("comunidad_autonoma") or "").strip()   # ← siempre ""
```

**Ningún lugar del dataset tiene la clave `comunidad_autonoma`**: los 9.752 la llaman
`comunidad`. Comprobado. La variable va vacía en todas las consultas y, peor, se le pasa
vacía a `get_language_profile(comunidad, provincia)`, que decide el perfil de idioma.

**Cambio:** leer `comunidad` con `comunidad_autonoma` como respaldo.

**Verificación:** una consulta de un municipio vasco debe elegir perfil bilingüe; hoy elige
el que salga con comunidad vacía.

### 1.2 · Desambiguar geográficamente TODAS las consultas

**Dónde:** mismo `_build_queries()`, y `build_fiesta_queries()` (línea 1120).

**Medido en la tirada del 2026-09-04:** de 113 consultas, **80 (71 %) no llevan ni
provincia ni `site:`**. Se pregunta "Santa Marta" a secas y el buscador devuelve la ciudad
colombiana de 500.000 habitantes antes que un pueblo pacense de 4.199.

**Cambio:** que toda consulta lleve al menos un desambiguador —provincia, comunidad o el
nombre oficial completo—. No añadir consultas nuevas: **reescribir las que ya hay**, para
no multiplicar el coste de búsqueda.

**Verificación:** repetir el recuento sobre el log de la siguiente tirada; el objetivo es
0 % de consultas sin desambiguación.

### 1.3 · Nombre oficial completo, resuelto por el LLM y cacheado

**Dónde:** módulo nuevo o junto a `patron_finder`, que ya tiene el patrón de caché por
localidad (`patrones_cache.json`).

**Por qué:** el dataset llama al municipio "Santa Marta"; su nombre real es "Santa Marta de
los Barros". Ninguna consulta lo usó, y ese mismo dato habría evitado que el veto matara la
ficha de Candelas.

**Cómo:** una llamada por municipio, con el nombre, la provincia, la comunidad y el
`sitio_web` delante —que en este caso es `santamartadelosbarros.com` y lleva el nombre
completo dentro—. Se cachea igual que los patrones y se reutiliza en:

* las consultas de búsqueda (1.2),
* el bloque de identidad del juez de pertenencia (tanda 2).

**Verificación:** para Santa Marta debe devolver "Santa Marta de los Barros"; para Tobarra,
"Tobarra" (no todos los municipios tienen nombre largo, y forzarlo sería peor).

### 1.4 · No confundir otro dominio con la web del municipio

**Dónde:** `scraper/heuristic_spider.py`, resolución de URL canónica (línea ~228).

```
[Spider] URL canónica: http://www.santamartadelosbarros.com → https://badajoz.es
```

Se mapearon 77 páginas de la Diputación de Badajoz y entraron como 76 documentos
`web_municipio`.

**Cambio:** si la URL canónica sale a un **dominio registrable distinto**, no es la web del
municipio: se descarta ese rastreo y se sigue **solo con la búsqueda web**.

**Cuidado con los falsos positivos.** En el histórico hay redirecciones legítimas entre
dominios: `villagarciadelatorre.es → villagarciadelatorre.com` (misma entidad, otro TLD) y
`ayuntamientodeoyon.com → ayuntamientodeoyon.eus`. La comparación debe ser por el nombre
del dominio sin el TLD, no por el dominio entero. Único caso real de salto en ~30
municipios, así que la regla debe ser conservadora: ante la duda, conservar el rastreo.

**Verificación:** las tres redirecciones citadas deben seguir aceptándose; solo
`santamartadelosbarros.com → badajoz.es` debe rechazarse.

### 1.5 · Aviso legal, cookies y protección de datos fuera del rastreo

**Dónde:** `scraper/heuristic_spider.py`, `URL_BLACKLIST` (línea 46).

Es una lista que ya existe y ya contiene `/transparencia`, `/plenos`, `/ordenanzas` y los
subdominios de sede electrónica. Se añaden los patrones de páginas legales.

**Medido:** El Fresno, 15 de 60 chunks (25 % del contexto de discovery) en
`proteccion-de-datos.html` y `aviso-legal.html` de su propia web.

**Para qué sirve:** son el falso positivo perfecto —vienen del dominio del ayuntamiento,
pasan todos los filtros de procedencia con nota máxima y no dicen nada de fiestas—, mandan
en el orden del primer lote y son casi idénticas entre municipios, así que no distinguen
nada. **Magnitud honesta:** es coste y orden, no pérdida dura; desde que el repartidor no
descarta, esos chunks retrasan y encarecen, no expulsan.

**Verificación:** el contexto de El Fresno no debe contener `aviso-legal` ni
`proteccion-de-datos`.

---

## Tanda 2 — el LLM decide los topónimos

### 2.1 · Retirar el veredicto del código

**Dónde:** `llm_processor/text_analyzer.py`, `lugar_real_contradice()` y su uso en
`filtrar_por_pertenencia()`.

Hoy compara por palabras el sitio que nombra el modelo contra el nombre de la localidad y
descarta si sobra alguna. Mató 'Candelas 2026', la única ficha real de Santa Marta, porque
sobraba "barros".

**Cambio:** deja de ser veredicto. El código no decide si "Santa Marta de los Barros" es
nuestro pueblo.

### 2.2 · Darle al modelo lo que hoy compara el código

**Dónde:** `_bloque_identidad()`.

Añadir al bloque de identidad el **nombre oficial completo** (1.3) y el **`sitio_web`
oficial**. Con eso delante, el modelo resuelve solo que "de los Barros" somos nosotros.

### 2.3 · La incoherencia pasa a ser repregunta

**Dónde:** `filtrar_por_pertenencia()`.

Cuando el modelo responda "sí" y a la vez sitúe la fiesta en un sitio que no cuadra, en vez
de descartar **se le vuelve a preguntar señalándole la duda**: *"dices que es de X pero la
sitúas en Y; ¿es Y nuestro pueblo?"*. El código detecta la incoherencia; el modelo decide.

**Por qué hace falta y no basta con quitar el veto:** el veto nació de un fallo medido —el
modelo respondió `"es_de_la_localidad": "si"` y escribió a la vez
`lugar_real: "Arroyomolinos de la Vera"`, otro municipio—. Sin la repregunta, esa ficha
vuelve a entrar.

**Si la repregunta vuelve a salir incoherente: fuera.** Decisión tomada.

**Coste:** una llamada extra solo en los casos raros. En la tirada de 42 fichas habrían
sido 1 o 2.

---

## Tanda 3 — medir

Repetir `probar_juez.py` sobre los mismos 4 municipios trampa (Santa Marta, La Parra, El
Fresno, Corral-Rubio). Es el único conjunto con verdad establecida a mano.

| Métrica | Hoy | Objetivo |
|---------|-----|----------|
| Fiestas reales encontradas (de ~12 documentadas) | 2 | ≥ 6 |
| Fichas de otra localidad que sobreviven | 0 | 0 |
| Consultas sin desambiguación geográfica | 71 % | 0 % |
| Fichas con programa | 0 | ≥ 1 |

**Aviso:** es esperable que la precisión baje al subir el recall. Hoy no entra ninguna
ficha falsa en parte porque apenas entra nada; cuando el contexto traiga material real, el
juez volverá a tener trabajo. Si entra alguna falsa pero el recall sube, es un avance, no
una regresión.

---

## Riesgos

* **Añadir la provincia puede estrechar de más.** Hay fuentes legítimas que no nombran la
  provincia (la web del propio pueblo, la prensa comarcal). Por eso se reescriben las
  consultas existentes en vez de sustituirlas todas por variantes con provincia: debe
  quedar alguna vía sin ese filtro.
* **El nombre oficial largo puede ser peor que el corto** en buscadores, si nadie usa el
  nombre completo en la prensa local. Conviene conservar ambas variantes entre las
  consultas y no apostar todo al nombre largo.
* **La regla del salto de dominio es conservadora a propósito.** Un falso positivo aquí
  cuesta el rastreo entero de un municipio, que es mucho peor que el ruido que evita.

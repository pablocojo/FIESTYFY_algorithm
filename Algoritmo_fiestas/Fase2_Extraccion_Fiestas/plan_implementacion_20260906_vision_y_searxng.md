# Plan de implementación — buscador y visión en el localizador

**Fecha:** 2026-09-06
**Línea base:** ejecución del 2026-09-05, semilla 7 (`amplio_bitacora.json`, `fiestas_amplio.json`)
**Objetivo medible:** bajar las fiestas con `programa_estado = no_encontrado` de 21/35 (60%)
sin subir el tiempo por fiesta por encima de un 20%.

## Decisiones tomadas

| Pregunta | Decisión |
|---|---|
| Modelo | 9B (`lmstudio-community/qwen3.5-9b-nothink`) |
| ¿Sustituir o duplicar el localizador? | **Sustituir** |
| Orden de trabajo | Buscador primero, visión después (ver medición) |
| ¿Visión en todas las páginas? | No: solo cuando no hay texto útil y el modelo señaló la URL |

---

## La medición que reordena el plan

La versión anterior de este documento ponía la visión primero. **Los datos dicen lo
contrario.** Sobre la ejecución del 2026-09-05:

### Línea base

| Métrica | Valor |
|---|---|
| Municipios | 8 |
| Fiestas encontradas | 35 |
| Tiempo total | 283 min (4,7 h) |
| `programa_estado = completo` | 13 |
| `programa_estado = parcial` | 1 |
| **`programa_estado = no_encontrado`** | **21 (60%)** |
| Actos totales extraídos | 68 |

### Por qué fallan esas 21

| Motivo | Fiestas | % |
|---|---|---|
| Agregador / directorio (`festivalesdeespana.com`, `pueblus.com`…) | 9 | 43% |
| Web normal sin programa | 5 | 24% |
| Fichero PDF o imagen | 3 | 14% |
| Sin URL ninguna | 3 | 14% |
| Red social | 1 | 5% |

**La visión arreglaría 3 de 21.** No es donde está el problema.

### La causa raíz

Sobre los 273 volcados de `debug_contexto/`:

| Métrica | Valor |
|---|---|
| Mediana de contexto por fiesta | 18.178 caracteres |
| Mediana de dominios distintos | 2 |
| **Fiestas con ≤1 dominio en el contexto** | **101 de 273 (36%)** |

Caso testigo, El Barraco / Fiestas Patronales del Santísimo Cristo:

```
contexto: 1037 caracteres
URLs distintas: 1
dominio: pueblus.com
elbarraco.org presente: NO
```

El modelo no eligió mal: **no tenía nada que elegir**. Y `elbarraco.org` existe —otra
fiesta del mismo municipio sí sacó una URL de ese dominio—, simplemente no llegó al
contexto.

Conclusión: el cuello de botella está **antes** del localizador, en el paso que busca y
descarga fuentes. Mejorar el prompt del localizador o darle visión no cambia nada cuando lo
que recibe es un enlace a un directorio SEO.

---

## Tanda 1 — SearXNG en lugar del scrapeo de HTML

Va primera porque ataca el 36% de contextos pobres, que es lo que arrastra al 60% de
fiestas sin programa.

### 1.1 · Cliente nuevo

**Dónde:** `scraper/google_search.py`, junto a la función que monta la URL de
`html.duckduckgo.com` (línea 469).

SearXNG ya corre en el PC: contenedor `searxng`, puerto 8888, `--restart always`. Desde WSL
se alcanza en `http://172.19.96.1:8888`, el mismo host que ya se usa para LM Studio.

Petición: `GET /search` con `q`, `format=json`, `language=es`. Devuelve título, URL y
extracto por resultado. Comprobado: 38 resultados relevantes para "fiestas de Torrelaguna",
con la web del ayuntamiento entre los primeros.

Configuración en `config.py`, junto al bloque de LM Studio:

```
SEARXNG_HOST = LMSTUDIO_HOST          # mismo host
SEARXNG_BASE_URL = f"http://{SEARXNG_HOST}:8888"
SEARXNG_TIMEOUT = 20
SEARXNG_MAX_RESULTADOS = 20
```

### 1.2 · Preferir fuentes oficiales

**Dónde:** el mismo módulo, al ordenar los resultados.

El problema medido no es solo la cantidad de dominios, es cuáles. Con más resultados en
mano, subir los que huelen a oficial —dominios `.es` del propio municipio, `sede.`,
`ayuntamiento`, el topónimo en el dominio— y hundir los agregadores conocidos.

La lista de agregadores a hundir sale de los datos: `festivalesdeespana.com`,
`pueblus.com`, `defiestaenfiesta.es`, `demercadosmedievales.es`, `turismoalmanzora.com`,
`grada.es`.

Hundir, no eliminar: en municipios sin web propia, el directorio es lo único que hay.

### 1.3 · Qué se puede borrar

Con JSON limpio dejan de hacer falta el parseo de HTML de DuckDuckGo, el deshacer de
redirecciones `bing.com/ck/a` y los motores de reserva.

**No borrar todavía.** Dejar DuckDuckGo como reserva hasta tener una ejecución comparada.

### 1.4 · Dependencia nueva

Si el contenedor `searxng` no está arriba, las búsquedas fallan. Detectarlo al arrancar y
avisar claro, en vez de fallar consulta a consulta.

---

## Tanda 2 — Visión en el localizador

Va después: son 3 fiestas de 21, y solo tiene sentido cuando el localizador ya reciba
URLs decentes que apunten a ficheros reales.

### 2.1 · Detectar página sin texto pero con candidatos visuales

**Dónde:** `scraper/`, donde se guarda un documento descargado.

Si el texto extraído queda por debajo del mínimo del pipeline, marcar el documento con sus
candidatos: `<img>` de tamaño relevante y enlaces a `.pdf`. Solo dejar la señal, no llamar
a visión aquí.

### 2.2 · Puerta de entrada

**Dónde:** bucle del localizador, tras descargar las `urls_a_seguir`.

Solo se dispara si el documento viene marcado, si el modelo señaló esa URL explícitamente,
y si no se ha pasado el tope. Empezar con **2 imágenes por fiesta**: sin freno, una galería
de 40 fotos se come la ejecución.

### 2.3 · La llamada

**Dónde:** `llm_processor/`, junto a las que ya llaman a LM Studio.

Mismo endpoint (`LMSTUDIO_CHAT_URL`). Solo cambia el formato: `content` pasa de string a
lista con un bloque `text` y otro `image_url` en base64.

Verificado: el 9B leyó un cartel de prueba con tres actos y devolvió las tres fechas y
horas correctas, restituyendo tildes que la imagen no traía.

Para PDF, extraer páginas como imagen. Los PDF con texto ya se leen bien por la vía normal
—Semana Santa de Garrucha sacó 8 actos de uno—; esto es solo para escaneados.

### 2.4 · Marcar la procedencia

**Dónde:** en el documento que entra al contexto.

El texto salido de una imagen debe quedar identificado como tal, no mezclado con el
scrapeado. El juez necesita poder ser más severo con él.

**No es opcional.** El cartel de prueba era texto negro sobre blanco; los reales llevan
tipografías decorativas sobre fondos con dibujos, y un modelo de visión inventa fechas con
la misma seguridad con la que acierta.

---

## Cómo medir

Repetir la ejecución con **la misma semilla 7 y los mismos 8 municipios**, y comparar
contra `fiestas_amplio.json`:

| Métrica | Base | Objetivo |
|---|---|---|
| Fiestas `no_encontrado` | 21/35 | < 14/35 |
| Fiestas con ≤1 dominio en contexto | 36% | < 15% |
| Actos totales | 68 | > 100 |
| Actos que sobreviven al juez | por medir | no bajar |
| Minutos por fiesta | 8,1 | < 9,7 |

La cuarta fila es la que evita el autoengaño: recuperar 30 actos inventados de un cartel
mal leído es peor que no recuperar ninguno.

Sobre la última: **esto no va a ser más rápido**. Las llamadas de visión son más caras que
leer HTML. Lo que se gana es cobertura. Si el tiempo sube algo pero baja el `no_encontrado`,
el cambio ha salido bien.

---

## La prueba con la API de Open WebUI

Independiente del código de Fase 2, se puede hacer en cualquier momento.

`POST /api/chat/completions` contra `https://desktop-6q6ho55.tail009f04.ts.net`, con
`Authorization: Bearer <clave>` generada en `Ajustes` → `Cuenta`, y
`"features": {"web_search": true}` en el cuerpo (verificado en `middleware.py:2669`).

**Subir `top_k` no es el ajuste.** `top_k` gobierna cuántos fragmentos llegan tras trocear
las páginas en 1000 caracteres y vectorizarlas; sirve para *responder*. El localizador no
responde: **elige URLs**, y para eso quiere ver muchos resultados con su extracto.

| Ajuste | Valor | Por qué |
|---|---|---|
| `web.search.bypass_web_loader` | `true` | Extractos + URLs, sin descargar ni trocear |
| `web.search.result_count` | 15–20 | Ancho de miras, que es lo que hace falta |
| `rag.top_k` | irrelevante | No hay recuperación que gobernar |

**Límite:** sirve para tantear el prompt, no para medir el pipeline. Open WebUI no hace
OCR, no respeta el presupuesto de contexto de Fase 2 y no pasa por el juez.

---

## Orden

1. Tanda 1 completa
2. Ejecución con semilla 7 y comparación contra la tabla de arriba
3. Tanda 2 solo si la 1 deja el contexto sano
4. Segunda ejecución comparada

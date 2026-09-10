# Plan de implementación — procedencia y visión

**Fecha:** 2026-09-10
**Base de medición:** `fiestas_amplio_20muni.json` (20 municipios, 81 fiestas, 578 min)
**Objetivo:** que el campo de procedencia deje de mentir, y recuperar los programas
publicados como imagen que hoy se pierden.

Los `id` inestables quedan fuera a propósito: se abordan tras la ejecución completa de
2026, que servirá de referencia para las comparaciones posteriores.

---

## Tanda 1 — `solo_fuentes_no_oficiales` deja de mentir

### El problema, medido

**10 de 81 fichas** marcan `solo_fuentes_no_oficiales: True` teniendo su `url_programa`
en un dominio oficial. En la auditoría del 2026-09-06 eran 15 de 52. Es el campo con el
que un consumidor filtraría lo dudoso, así que equivocarse en el 12% de los casos hace
más daño que no existir.

### La causa

`_validar_fuentes_fiesta()` (`text_analyzer.py:1758`) calcula el campo **solo desde las
fuentes que el LLM declara**, filtradas contra el contexto:

```python
solo_no_oficiales = not any(es_fuente_oficial(s) for s in declaradas)
```

`url_programa` —la página que el localizador eligió como programa, que es la prueba más
directa de procedencia que tiene la ficha— no entra en la cuenta. Si el modelo no declara
esa fuente, o si se filtra por no estar en el contexto, la ficha queda marcada como no
oficial aunque su programa venga del ayuntamiento.

### El arreglo

No hacen falta heurísticas nuevas. **Cada documento ya lleva su etiqueta de fuente**:

```python
# fuentes.py:343, crear_documento()
{"fuente": fuente, "url": url, "texto": texto, "tipo": tipo, ...}
```

1. **Buscar el documento cuya `url` coincide con `url_programa`** y recuperar su `fuente`.
2. **Añadirla a `declaradas`** antes de calcular `solo_no_oficiales`, si no estaba.
3. Registrarlo en el log, porque es una corrección silenciosa de algo que el modelo dijo.

**Dónde:** `_validar_fuentes_fiesta` necesita acceso a los documentos. Hoy recibe
`fuentes_contexto` (un conjunto de etiquetas). Hay que pasarle también el mapa
`url -> fuente`, que se construye una vez por localidad.

### Lo que NO se hace

No inferir oficialidad por el dominio (`.es`, "ayuntamiento", el topónimo). Sería una
heurística nueva conviviendo con la clasificación que ya existe, y dos criterios que
pueden discrepar es peor que uno imperfecto. Si un documento está mal etiquetado, el
fallo está en quien lo etiquetó y ahí es donde hay que arreglarlo.

### Cómo se mide

Repetir el conteo sobre la salida: fichas con `url_programa` en dominio oficial y
`solo_fuentes_no_oficiales: True`. **Objetivo: 0 de 81.**

Y una comprobación de que no se ha invertido el error: fichas marcadas como oficiales
cuya `url_programa` sea un agregador o una red social. Hoy son 0 y deben seguir siéndolo.

---

## Tanda 2 — Conectar la visión que ya existe

### Lo que ya está construido

Esta tanda es mucho menor de lo que parecía, porque **las dos mitades ya existen**:

| Pieza | Dónde | Estado |
|---|---|---|
| VLM dedicado en LM Studio | `config.py:620` `VISION_ENABLED`, `VISION_MODEL` | funcionando |
| Lector de imagen suelta | `vision_analyzer.analizar_imagen_directa()` | **nadie lo llama** |
| OCR de PDF escaneado | `document_extractor`, `_run_ocr` | funcionando |
| Reconstrucción multicolumna | `document_extractor`, `_reconstruir_si_multicolumna` | funcionando |
| Render de páginas candidatas | `document_extractor`, `images_for_vlm` | **se devuelve y se tira** |

```python
# document_extractor.py:405
return result, images_for_vlm     # nadie consume el segundo valor
```

El trabajo no es construir visión. Es **enchufar dos cosas que ya funcionan**.

### El problema, medido

**6 fichas de 81** señalan un PDF o una imagen como `url_programa` y devuelven cero
actos. Son programas publicados, que el pipeline localiza correctamente, y de los que no
saca nada.

### El arreglo

1. **Consumir `images_for_vlm`.** Donde hoy se descarta el segundo valor de retorno,
   pasar esas imágenes por `analizar_imagen_directa()` y añadir su texto al documento,
   **marcado como procedente de visión**.

2. **Marcar la procedencia del texto.** Un acto leído de un cartel no tiene la misma
   fiabilidad que uno leído de HTML. El juez debe poder ser más severo con él, y al
   depurar hay que poder distinguirlos. Esto no es opcional: el cartel de prueba del
   2026-09-06 era texto negro sobre blanco, y los carteles reales llevan tipografías
   decorativas sobre fondos con dibujos.

3. **Imágenes sueltas, no solo PDF.** Hoy solo se renderizan páginas de PDF. Falta el
   caso del cartel colgado como `.jpg` enlazado desde la página del ayuntamiento.
   `_fetch_page_content` ya devuelve los enlaces de la página; hace falta filtrar los que
   apunten a imagen y tengan tamaño relevante.

### Los frenos

**Tope por fiesta.** Sin él, una galería de 40 fotos se come la ejecución. Empezar con
**2 imágenes por fiesta**, contando las que ya vengan de PDF.

**Solo cuando hace falta.** La visión se dispara si el documento no dio texto aprovechable
y el modelo señaló esa URL explícitamente. No en toda página que tenga imágenes.

`PDF_MAX_PAGES_VLM = 3` y `VISION_TIMEOUT = 180` ya existen y se respetan.

### Cómo se mide

Sobre los mismos 20 municipios: de las 6 fichas que hoy señalan PDF o imagen sin sacar
actos, **cuántas pasan a tener programa**. Y de esas, cuántos actos sobreviven al juez.

La segunda parte es la que evita el autoengaño: recuperar 20 actos inventados de un cartel
mal leído es peor que no recuperar ninguno.

---

## Orden

1. **Tanda 1 primero.** Es barata, no toca el camino de datos y arregla el campo que
   sostiene todo el criterio de honestidad del proyecto.
2. **Tanda 2 después**, midiendo antes y después sobre los mismos municipios.

Ninguna de las dos requiere ejecución completa para validarse: la primera se comprueba
sobre la salida que ya existe, y la segunda sobre las 6 fichas concretas que fallan.

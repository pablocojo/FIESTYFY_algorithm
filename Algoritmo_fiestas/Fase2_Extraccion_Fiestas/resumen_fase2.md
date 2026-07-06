# Resumen Completo: Fase 2 - Extracción de Fiestas

La **Fase 2** del algoritmo Fiestyfy tiene como objetivo localizar y extraer las fiestas de las **subdivisiones poblacionales** (pueblos, ciudades pequeñas/grandes, distritos, barrios, pedanías) de España. 

> [!IMPORTANT]
> **Regla de Oro**: Nunca se extraen fiestas propias de los "municipios raíz" directamente. Las fiestas pertenecen siempre a sus localidades menores (sus hijos en la jerarquía).

Esta fase cuenta con una arquitectura **asíncrona y paralelizada** (v2), apoyada en un pipeline avanzado que incluye Web Crawling, Automatización de Apps Nativas para RRSS, OCR, RAG (Retrieval-Augmented Generation) y análisis con Modelos de Lenguaje Locales (LLM / VLM).

---

## 🏗️ Arquitectura y Orquestación (`main.py`)

1. **Carga y Agrupación**: Carga el JSON de la Fase 1 (`lugares_espana.json`) y agrupa todas las localidades menores bajo sus respectivos municipios raíz.
2. **Ejecución en Paralelo**: Procesa múltiples municipios de forma concurrente (según la variable `PARALLEL_MUNICIPALITIES`).
3. **Ejecución Secuencial Interna**: Dentro de cada municipio, sus localidades se procesan de forma secuencial. Esto optimiza el uso de la caché (como la web del municipio compartido) y reduce la carga repetitiva.
4. **Persistencia de Estado**: Utiliza `state_manager.py` para ir guardando el progreso a nivel de localidad y municipio, permitiendo reanudar ejecuciones interrumpidas sin pérdida de datos.

---

## 🔍 Flujo de Extracción de una Localidad (`process_locality`)

Por cada localidad, el sistema ejecuta un flujo estructurado de captura de información, priorizando las fuentes más fiables:

### 0. Santo Patrón (Ejecución en paralelo al scraping)
Se busca el santo patrón de la localidad consultando Wikipedia, DuckDuckGo y un LLM de respaldo.
- Cruza la fecha fija del santo con un **santoral estático español** de más de 200 patrones (`llm_processor/patron_finder.py`).
- El resultado se almacena en `patrones_cache.json` para no repetir búsquedas.

### 1. Extracción de Contenido (Recopilación de Documentos)
El sistema extrae texto desde 4 orígenes distintos, en este orden de prioridad:

- **Web Oficial de la Localidad** (Si difiere de la del municipio): Usa `AsyncTwoPassSpider` para realizar un rastreo asíncrono (BFS), priorizando páginas relevantes. Incluye OCR y filtrado inteligente de PDFs.
- **Web Oficial del Municipio**: Mismo proceso de rastreo en el dominio raíz del municipio para buscar menciones a la pedanía/barrio.
- **Redes Sociales (RRSS)**: *[Ver sección de Flujo RRSS más abajo]* Se cargan los documentos de una caché pre-generada (`rrss_contenido_cache.json`). Prioriza RRSS de la localidad, seguido por RRSS del municipio.
- **Búsqueda Web (DuckDuckGo)**: Búsqueda abierta con 3 queries distintas. Entra a los 5 enlaces principales para raspar contenido a texto completo. Comparte un registro de URLs visitadas con los pasos anteriores para evitar redundancias.

### 2. Generación Aumentada por Recuperación (RAG)
Todo el texto recopilado pasa por `AsyncRAGProcessor`:
- Se divide en "chunks" (1200 caracteres con solapamiento).
- Se generan embeddings locales usando `text-embedding-nomic-embed-text-v1.5`.
- Se extraen únicamente los fragmentos más relevantes respecto a una query específica de fiestas de esa localidad y año, descartando el "ruido".

### 3. Extracción con LLM
El contexto filtrado por RAG se inyecta en el LLM local (`qwen2.5-7b-instruct` vía LM Studio).
- El modelo sigue un prompt estructurado para devolver un JSON predecible con las fiestas detectadas y sus respectivos programas (días y horas de eventos).

### 4. Validación y Filtro Adaptativo (`festival_filter.py`)
No todo lo que detecta el LLM se aprueba. Se aplica un sistema de reglas:
- **Eventos Multi-día**: Se aprueban si tienen señales festivas claras (patronales, feria, carnaval), señales nocturnas o un programa con ≥2 eventos.
- **Eventos de 1 solo día**: Se aplica un filtro **muy estricto**. Solo se aceptan si incluyen fuerte actividad nocturna (orquestas, verbenas, discomóviles) o coinciden exactamente con el nombre/fecha del patrón. Esto evita la captura de procesiones sueltas, misas y exposiciones.
- **Rechazo de eventos privados**: Se descartan eventos propios de discotecas, pubs o salas de fiesta privadas.

### 5. Integración Final del Patrón
Una vez validada la lista de fiestas:
- Si alguna de las fiestas extraídas cruza la **fecha del patrón**, se le asigna la etiqueta `incluye_dia_patron: true`.
- Si **ninguna fiesta** cubre la fecha del patrón (o se encontraron 0 fiestas), el sistema inyecta una **"Fiesta Estimada"** de duración de un día para asegurar que la localidad tenga constancia festiva de su fecha más importante (`es_estimada: true`, `confianza: "baja"`).

---

## 📱 Sub-Flujo de Redes Sociales (Novedad)

La recolección de redes sociales opera **por separado** del orquestador principal, dadas las restricciones anti-scraping severas. Consta de dos etapas (C y D) externas:

1. **Etapa C - Runner de Apps Nativas (`social_apps_runner.py`)**:
   - Requiere de un **PC Dedicado** (bloquea teclado y ratón).
   - Manipula directamente la interfaz de usuario de las aplicaciones nativas instaladas (Instagram, Facebook de la Microsoft Store, Twitter Web).
   - Navega por los perfiles buscando palabras clave festivas y toma **capturas de pantalla** (`rrss_capturas/`).
2. **Etapa D - Visión Computacional (`procesar_capturas.py`)**:
   - Lee las imágenes extraídas y utiliza un modelo VLM (Vision Language Model local) a través de `vision_analyzer.py`.
   - Analiza los carteles y extrae el programa de fiestas en formato texto estructurado.
   - Todo se consolida y vuelca en la caché `rrss_contenido_cache.json`.
3. **Integración**: Cuando el `main.py` principal necesita consultar las redes sociales (`scraper/social_content.py`), **únicamente lee** este JSON pre-generado. Si no hay datos cacheados, simplemente omite esta fuente y avanza.

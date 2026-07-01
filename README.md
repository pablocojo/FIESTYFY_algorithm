# FIESTYFY_algorithm

Este repositorio contiene el algoritmo de recolección y estructuración de datos para la base de datos de fiestas locales de España.

## Objetivo Principal
Elaborar un archivo JSON ordenado y libre de errores que contenga todos los lugares de España susceptibles de tener fiestas propias, sirviendo como esqueleto para el portal web.

## Arquitectura de Datos (INE-First)
El proyecto confía plenamente en los datos del Instituto Nacional de Estadística (INE):
- **Municipios (`pobmun25.xlsx`)**: El padrón sirve como base para definir los municipios raíz.
- **Pedanías (`nomdef2025.xlsx`)**: La extracción de pedanías y subdivisiones rurales se basa 100% en esta tabla. Wikipedia se utiliza únicamente para enriquecer estas pedanías con descripciones y URLs, validando los enlaces mediante un sistema combinado heurístico y LLM.

## Tipos de Lugar y Estructura
- `municipio`: Nodo raíz estructural que agrupa a sus entidades de población. Representa la demarcación administrativa (ID de 11 dígitos del INE) y contiene datos generales (imágenes, descripciones), pero no tiene `padre_id`.
- `pueblo` / `ciudad_pequena` / `ciudad_grande`: Entidades de población extraídas al 100% desde el INE (`ENTIDADES.csv`). Tienen fiestas propias y cuelgan siempre de un `municipio` (como `padre_id`). Una de estas entidades dentro de cada municipio se marca con `es_capital: true`.
- `distrito` / `barrio`: Divisiones de nivel inferior obtenidas de Wikipedia. Solo cuelgan de las ciudades (una ciudad grande puede tener distritos y barrios; una pequeña puede tener barrios). Todos los lugares, incluidos distritos y barrios, tienen el campo `es_capital` (los barrios/distritos siempre son `false`).

Nota: Ya no existe el concepto de "municipio_compuesto" ni el tipo "pedania". Todos los municipios se comportan como contenedores, y todas las antiguas pedanías ahora son entidades tipificadas por población (`pueblo`, etc.).

## Fases del Algoritmo
- **Fase 1 (Recogida de Lugares)**: Construye la estructura territorial completa. 
  - **Paso 1 (`main.py`)**: Extrae los municipios raíz desde Wikipedia.
  - **Paso 2 (`main2.py`)**: Cruza la información obtenida con los datos del INE (`ENTIDADES.csv`) para extraer el 100% de las entidades menores (pueblos, ciudades). Posteriormente usa un LLM para extraer su descripción y extraer posibles subdivisiones urbanas (distritos y barrios) desde Wikipedia.
- **Fase 2 (Extracción de Fiestas)**: Toma las entidades generadas en la Fase 1 y utiliza un orquestador asíncrono con un pipeline de Web Scraping, RAG y un LLM local para rastrear la web (búsquedas y web del ayuntamiento), identificar programas de actos y construir las fichas completas de las fiestas.

## Configuración y Rendimiento (LM Studio)

El algoritmo hace un uso intensivo de modelos de IA locales ejecutados a través de **LM Studio**. Dependiendo del hardware (CPU/GPU) donde se ejecute, es posible ajustar los modelos o parámetros de concurrencia:

### Modelos Utilizados
- **Modelo de Lenguaje Principal**: `qwen2.5-7b-instruct`. Se encarga tanto de resumir descripciones (Fase 1) como de extraer el programa estructurado de las fiestas (Fase 2).
- **Modelo de Embeddings**: `text-embedding-nomic-embed-text-v1.5`. Se usa exclusivamente en la Fase 2 (RAG) para buscar los fragmentos de texto más relevantes antes de enviarlos al LLM.

### Dónde cambiar los parámetros
Si la máquina tiene menor o mayor capacidad, puedes cambiar el nombre del modelo, el número de municipios en paralelo o el timeout de las peticiones en los siguientes archivos de configuración:
- **Fase 1 (Lugares)**: Los parámetros del LLM se definen en `Algoritmo_fiestas/Fase1_recogida_datos_wiki/config.py` (buscar `LLM_MODEL_NAME`).
- **Fase 2 (Fiestas)**: Los parámetros del LLM se definen en `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/config.py` (buscar `LLM_MODEL_NAME`, `EMBEDDING_MODEL_NAME` y `PARALLEL_MUNICIPALITIES`).

*Nota: Asegúrate de que los modelos que configures coincidan exactamente con el nombre de los modelos cargados en tu servidor local de LM Studio.*
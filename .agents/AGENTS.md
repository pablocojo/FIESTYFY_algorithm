# FIESTYFY_algorithm - Reglas del Proyecto y Objetivos

## Objetivo Principal
El objetivo fundamental del proyecto es elaborar un archivo JSON ordenado, validado y libre de errores que contenga la totalidad de los lugares de España susceptibles de tener fiestas propias. Este archivo es el **esqueleto estructural central** de la plataforma web de Fiestyfy.

## 1. Prioridades Absolutas y Calidad de los Datos
- **Tolerancia Cero a Omisiones**: Es crítico no dejar fuera a ninguna localidad real. Todas las pedanías, pueblos y subdivisiones deben estar mapeados.
- **Fuente de Verdad (Enfoque INE-First)**: El Instituto Nacional de Estadística (INE) es la máxima autoridad. El proyecto se basa obligatoriamente en dos tablas:
  1. **Municipios (`MUNICIPIOS.csv` / `pobmun25.xlsx`)**: Define el padrón base de todos los municipios raíz (nodos padre).
  2. **Unidades Poblacionales (`ENTIDADES.csv` / `nomdef2025.xlsx`)**: Proporciona todas las subdivisiones y núcleos. **CRÍTICO:** Esta tabla *solo* proporciona pedanías/núcleos poblacionales. No contiene ni distritos ni barrios.

## 2. Detección de Jerarquías y Nomenclaturas (Nuevas Reglas)
- **Eliminación de Tipos Obsoletos**: El sistema confía íntegramente en el INE. **Ya NO existe** el concepto de `municipio_compuesto` ni el tipo `pedania`.
- **Estructura del Municipio**: Todo `municipio` es ahora un contenedor raíz (con su ID del INE de 11 dígitos) que agrupa bajo sí entidades de población clasificadas por tamaño (`pueblo`, `ciudad_pequena`, `ciudad_grande`). Los municipios en sí **NO** tienen fiestas propias; las fiestas pertenecen a sus entidades hijas.
- **Capitalidad**: Una de las entidades dentro de cada municipio siempre debe estar marcada con `es_capital: true`.

## 3. Tipos de Lugar Permitidos e Hijos
- **`municipio`**: Nodo raíz. Tiene metadatos (descripciones, imágenes) pero NUNCA tiene el campo `padre_id`. Contiene: `pueblo`, `ciudad_pequena`, `ciudad_grande`.
- **`pueblo` / `ciudad_pequena` / `ciudad_grande`**: Tienen fiestas. Cuelgan siempre de un `municipio` mediante `padre_id`. 
- **`distrito` / `barrio`**: Extraídos secundariamente de Wikipedia. Cuelgan de ciudades o distritos. Siempre tienen `es_capital: false`.
  - *Ciudad grande*: Puede tener distritos y/o barrios.
  - *Ciudad pequeña*: Puede tener barrios.
  - *Distrito*: Tiene barrios.
- **Jerarquía de Abuelos**: Si un `barrio` pertenece a un `distrito`, obligatoriamente debe tener un campo `abuelo_id` que referencie directamente al ID de la entidad capital principal (ej. el ID de la ciudad de Alicante).

## 4. Reglas de Extracción y Filtros de Población
- **Garantía INE (Fase 1 - `main2.py`)**: Para asegurar el 100% de cobertura, las entidades se extraen íntegramente desde `ENTIDADES.csv`. Wikipedia se usa *solo* como apoyo para encontrar la URL, generar descripciones resumidas y localizar estructuras urbanas (distritos/barrios).
- **Filtro de 20 Habitantes**: Los barrios y distritos extraídos de Wikipedia deben superar los **20 habitantes** para registrarse.
- **Excepción INE para Pedanías**: Si un núcleo poblacional extraído del INE tiene `<= 20` habitantes pero `> 0`, NO se descarta. Si se logra validar con una URL de Wikipedia, se incorpora ignorando el umbral de los 20 habitantes.
- **Descarte Absoluto**: Cualquier lugar con **0 habitantes** se elimina, sin excepciones (esté o no en el INE).

## 5. Duplicados y Resoluciones
- **Mismo Nombre en el INE**: En `ENTIDADES.csv` pueden aparecer pedanías con el mismo nombre dentro del *mismo municipio*. Para resolverlo, se compara la población: **prevalece el de mayor población y se elimina el otro**. Si empatan, se elimina cualquiera. (Es normal que haya nombres repetidos en municipios distintos, eso no se elimina).
- **Prioridad Deduplicación**: Si hay un choque de nombre o URL de Wikipedia entre subdivisiones, prevalece el nivel administrativo más alto. El orden de prioridad es: `Pueblo/Entidad INE > Distrito > Barrio`.

## 6. Configuración de IA y Flujos
- El sistema utiliza **LM Studio** para interactuar con LLMs locales.
- Modelos por defecto:
  - LLM: `qwen2.5-7b-instruct` (Razonamiento, extracción de fiestas, parseo).
  - Embeddings: `text-embedding-nomic-embed-text-v1.5` (RAG en Fase 2).
- Estas configuraciones deben respetarse y ajustarse en los respectivos `config.py` si hay problemas de memoria/hardware.

## Instrucciones Especiales para el Asistente AI
1. Tratar la estructura de datos jerárquica con extremada precaución. Si dudas sobre cómo encajar un lugar, pregúntale al usuario.
2. Si detectas anomalías en los datos del INE o desajustes graves con Wikipedia, **no inventes jerarquías**. Reporta la anomalía al usuario para una revisión manual.
3. Valida estrictamente cada JSON generado contra las reglas de este documento. La consistencia de `padre_id` (y `abuelo_id` en barrios) es innegociable.

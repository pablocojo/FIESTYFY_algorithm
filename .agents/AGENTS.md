# FIESTYFY_algorithm - Reglas del Proyecto y Objetivos

## Objetivo Principal
El objetivo fundamental del proyecto es elaborar un archivo JSON ordenado y libre de errores que contenga todos los lugares de España susceptibles de tener fiestas propias. Este archivo será el **esqueleto estructural** de una página web dedicada a las fiestas de localidades en España.

## Prioridades y Calidad de los Datos
- **Sin errores de omisión o clasificación**: Es crítico no dejar fuera ninguna localidad, garantizar que las descripciones se generen correctamente, y evitar clasificar erróneamente un municipio como compuesto cuando no lo es.
- **Fuentes de Datos (Las dos tablas del INE)**: Los datos del **INE** son la fuente de mayor calidad y precisión ("los mejores datos"). El proyecto se basa en dos tablas fundamentales:
  1. **Tabla de Municipios (`pobmun25.xlsx`)**: Contiene el padrón base de todos los municipios raíz de España.
  2. **Tabla de Unidades Poblacionales (`nomdef2025.xlsx`)**: Contiene las subdivisiones y núcleos de los municipios. **Regla muy importante:** Las unidades de población que se obtienen de esta tabla **solo son pedanías**. Esta tabla **no** contiene ni trata sobre barrios ni distritos.

## Generación de IDs y Repeticiones
- **Repetición de pedanías en el INE**: En la tabla de unidades poblacionales, pueden aparecer pedanías con el mismo nombre (o nombres que se normalizan al mismo string) **dentro del mismo municipio**. 
- **Resolución de Repeticiones**: Si dentro de un mismo municipio hay pedanías con el mismo nombre, se debe resolver comparando la población: **se elimina la de menor población y se deja solo una**. Si la población es igual, se elimina cualquiera de ellas. Es perfectamente válido y normal que existan pedanías con el mismo nombre si pertenecen a municipios diferentes.

## Regla de Población Mínima (Subdivisiones)
- **Umbral de 20 habitantes**: Por regla general, los barrios, distritos y pedanías extraídos de Wikipedia deben superar los 20 habitantes para ser añadidos.
- **Excepción de Pedanías INE**: Si un lugar tiene `<= 20` habitantes (y su población es `>= 1`), NO se descarta. Si su nombre coincide con el de una pedanía en el INE y se consigue validar contra una URL de Wikipedia válida, se aceptará y registrará automáticamente saltándose el límite de los 20 habitantes.
- **Descarte absoluto**: Si tiene exactamente `0` habitantes, se elimina siempre, independientemente de si está o no en el INE.

## Deduplicación y Prioridades
- Si una subdivisión coincide en nombre o en URL de Wikipedia con otra, el sistema las deduplica y prevalece **siempre** la pedanía. El orden de prioridad en la puntuación es: `Pedanía > Distrito > Barrio`.
- La extracción en Fase 2 (para cualquier tipo de municipio) siempre arranca extrayendo primero las **pedanías del padrón INE**.

## Desafíos Conocidos a Resolver
1. **Detección de Jerarquías NGMEP**: El sistema ahora confía íntegramente en las tablas del INE (`pobmun25` y `nomdef2025` a través de `MUNICIPIOS.csv` y `ENTIDADES.csv`). Ya no existe el concepto de "municipio_compuesto" ni el tipo "pedania". Todo `municipio` raíz agrupa bajo sí entidades de población (`pueblo`, `ciudad_pequena`, `ciudad_grande`).
2. **Entidades extraídas del INE (Paso 2 de la Fase 1 / `main2.py`)**: Para garantizar el objetivo de no dejar fuera a ninguna entidad, **las unidades poblacionales se extraen siempre y en un 100% desde la tabla ENTIDADES.csv del INE**. Wikipedia se utiliza únicamente como un sistema secundario para intentar asignarles una URL, generar descripciones resumidas y extraer estructuras puramente urbanas (barrios/distritos).
3. **Uso de Modelos de IA (LM Studio)**: El proyecto hace un uso intensivo de LLMs locales. Se asume por defecto el uso del modelo de lenguaje **`qwen2.5-7b-instruct`** y el modelo de embeddings **`text-embedding-nomic-embed-text-v1.5`**. Estos pueden configurarse en los respectivos archivos `config.py` de cada fase si el hardware lo requiere.

## Tipos de Lugar y Reglas Clave
- **municipio**: Nodo raíz estructural (ID INE 11 dígitos). Contiene metadatos (descripciones, imágenes, urls) pero **NO** tiene el campo `padre_id`. No tiene fiestas propias.
- **pueblo / ciudad_pequena / ciudad_grande**: Tienen fiestas propias. Cuelgan siempre de un `municipio` (mediante `padre_id`). Una de las entidades dentro de cada municipio siempre es la capital (`es_capital: true`).
- **distrito / barrio**: Divisiones de nivel inferior obtenidas de Wikipedia. Tienen `es_capital: false`.
- **Hijos permitidos**:
  - *Municipio*: Tiene `pueblo`, `ciudad_pequena`, `ciudad_grande`.
  - *Ciudad grande*: Puede tener distritos y/o barrios.
  - *Ciudad pequeña*: Puede tener barrios.
  - *Distrito*: Tiene barrios.
- **Jerarquía de Barrios con Distritos**: Si un `barrio` pertenece a un `distrito`, debe tener un campo opcional `abuelo_id` que referencie directamente al ID de la entidad capital (ej. si el padre es un distrito de Alicante, el `abuelo_id` debe ser el id de Alicante).

## Instrucciones Especiales para el Asistente
- Tratar siempre de inferir de manera conservadora y reportar al usuario los casos anómalos o dudosos (municipios que podrían ser compuestos, desajustes con el INE) para que sean revisados manualmente, ya que es preferible derivar la decisión al usuario antes que generar datos erróneos en el JSON.
- Mantener la estructura del JSON estrictamente validada según las especificaciones del proyecto.

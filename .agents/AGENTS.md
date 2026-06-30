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
1. **Detección de Municipios Compuestos**: Es uno de los mayores retos descubrir si un municipio es de tipo compuesto (`municipio_compuesto`) o no. Para ello:
   - Se realiza una **detección al vuelo en la Fase 2**: al consultar la tabla del INE, si un municipio no cuenta con un núcleo o localidad con su mismo nombre, se clasifica automáticamente y de forma garantizada como municipio compuesto.
   - Ya no es estrictamente necesario depender de un script a posteriori, el proceso está integrado en la asignación de pedanías.
2. **Pedanías extraídas del INE**: Para garantizar el objetivo de no dejar fuera a ninguna pedanía, **las pedanías se extraen siempre y en un 100% desde la tabla del INE**. Wikipedia se utiliza únicamente como un sistema secundario para intentar asignarles una URL y extraer su descripción (validando este cruce mediante un sistema heurístico combinado con un LLM).

## Flujo de Trabajo y Revisión Humana
- **Intervención Humana (El Usuario)**: El usuario (tú) asume la responsabilidad de **revisar manualmente** los casos problemáticos detectados por el algoritmo.
- Esto incluye revisar:
  - Municipios a los que les falte alguna pedanía según la tabla del INE.
  - El informe generado por `revalidar_compuestos.py` (`municipios_revisados.json` e informe asociado), donde se listan los que el INE marca como compuestos porque no hay una localidad homónima exacta, revisando si se trata de un simple fallo ortográfico o si realmente no tienen núcleo propio.

## Tipos de Lugar y Reglas Clave (Resumen del README)
- **pueblo / ciudad_pequena / ciudad_grande**: Tienen fiestas propias.
- **municipio_compuesto**: Solo muestra sus pedanías y **no** tiene fiestas propias.
- **Hijos permitidos**:
  - *Ciudad grande*: Puede tener distritos y/o pedanías.
  - *Ciudad pequeña / Pueblo*: Pueden tener pedanías (y barrios en el caso de ciudad_pequeña).
  - *Municipio compuesto*: Tiene pedanías.
  - *Distrito*: Tiene barrios.
- **Jerarquía de Barrios con Distritos**: Si un `barrio` pertenece a un `distrito`, debe tener un campo opcional `abuelo_id` que referencie directamente al ID del municipio raíz (ej. si el padre es `alicante_distrito-distrito1`, el `abuelo_id` debe ser `alicante`).

## Instrucciones Especiales para el Asistente
- Tratar siempre de inferir de manera conservadora y reportar al usuario los casos anómalos o dudosos (municipios que podrían ser compuestos, desajustes con el INE) para que sean revisados manualmente, ya que es preferible derivar la decisión al usuario antes que generar datos erróneos en el JSON.
- Mantener la estructura del JSON estrictamente validada según las especificaciones del proyecto.

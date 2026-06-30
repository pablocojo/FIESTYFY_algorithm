# FIESTYFY_algorithm

Este repositorio contiene el algoritmo de recolección y estructuración de datos para la base de datos de fiestas locales de España.

## Objetivo Principal
Elaborar un archivo JSON ordenado y libre de errores que contenga todos los lugares de España susceptibles de tener fiestas propias, sirviendo como esqueleto para el portal web.

## Arquitectura de Datos (INE-First)
El proyecto confía plenamente en los datos del Instituto Nacional de Estadística (INE):
- **Municipios (`pobmun25.xlsx`)**: El padrón sirve como base para definir los municipios raíz.
- **Pedanías (`nomdef2025.xlsx`)**: La extracción de pedanías y subdivisiones rurales se basa 100% en esta tabla. Wikipedia se utiliza únicamente para enriquecer estas pedanías con descripciones y URLs, validando los enlaces mediante un sistema combinado heurístico y LLM.

## Tipos de Lugar
- `pueblo` / `ciudad_pequena` / `ciudad_grande`: Poseen fiestas propias y pueden tener subdivisiones (barrios/distritos para ciudades; pedanías para cualquier tipo).
- `municipio_compuesto`: Un agrupamiento puramente administrativo que carece de núcleo homónimo. No tiene fiestas propias, pero delega en sus pedanías hijas. Se detecta en tiempo real cruzando el nombre del municipio con el listado del INE.
- `distrito` / `barrio` / `pedania`: Divisiones de nivel inferior obtenidas de Wikipedia y del INE.

## Fases del Algoritmo
- **Fase 1**: Extrae los municipios desde Wikipedia.
- **Fase 2**: Añade la estructura territorial interna (Barrios y distritos desde Wikipedia; Pedanías directamente desde el INE).
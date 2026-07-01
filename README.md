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
- **Fase 1**: Extrae los municipios desde Wikipedia.
- **Fase 2**: Añade la estructura territorial interna (Barrios y distritos desde Wikipedia; Pedanías directamente desde el INE).
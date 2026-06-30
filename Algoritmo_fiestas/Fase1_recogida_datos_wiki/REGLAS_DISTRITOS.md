# Reglas de Extracción de Distritos y Barrios

**Umbral de Población:** 102.986 habitantes.

## 1. Municipios Menores a 102.986 hab.
- Se asume por regla general que NO pueden tener distritos administrativos.
- El algoritmo **salta la búsqueda de distritos** por completo.
- Extrae sus pedanías desde el INE/Wikipedia.
- Busca directamente **barrios** en la página principal del municipio.

## 2. Municipios Mayores o Iguales a 102.986 hab.
- Al detectar una población igual o superior al umbral en `procesar_ciudad_grande`, el algoritmo principal (`main2.py`) se detiene de emergencia mediante un `sys.exit()`.
- Esto evita que el LLM intente deducir los distritos leyendo la página gigante de la ciudad, lo que causaba saturación y falsos positivos (como confundir pueblos vecinos con distritos).
- Cuando se detiene, el objetivo es elaborar o ejecutar un código/script específico que navegue a `https://es.wikipedia.org/wiki/Categoría:Distritos_de_España` (o su equivalente directo `Categoría:Distritos de [Nombre_Ciudad]`) para extraer los distritos reales con exactitud.

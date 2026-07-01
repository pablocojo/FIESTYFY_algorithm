# Importación de datos a Fiestyfy (v2 · lugares)

Estructura crear un **único fichero JSON** compuesto de **lugares** que genera tu algoritmo.

Un **lugar** unifica municipio, distrito, barrio y pedanía (es el mismo perfil;
cambia la etiqueta y de quién cuelga). La jerarquía se expresa con `padre_id`.

## Ficheros

| Fichero | Para qué |
|---|---|
| `municipios.json` | Salida de `main.py`: contiene solo municipios raiz, sin distritos, barrios ni pedanias. |
| `lugares_espana.json` | Salida de `main2.py`: contiene los municipios de `municipios.json` mas las subdivisiones encontradas. |
| `ejemplo_completo.json` | Plantilla con los casos principales (pueblo, ciudad pequeña con barrios, ciudad grande con distritos y barrios, municipio compuesto + pedanías, ciudad grande sin distritos + pedanía). |

## Flujo
--Paso 1: obtener los municipios base de Wikipedia--
  1. Usuario ejecuta: python main.py
  2. Sistema descarga Categoría:Municipios de España
  3. Para cada municipio:
    ├─ Extrae información básica (provincia, comunidad, coords,...)
    ├─ Extrae sitio web y direccion en wikipedia
  4. Guardar municipios.json
  5. El programa termina sin analizar subdivisiones ni cruzar con el INE

--Paso 2: Completar estructura territorial con el INE y subdivisiones urbanas--
1. Usuario ejecuta: python main2.py
2. Se carga municipios.json como base y se cargan las tablas del INE (ENTIDADES.csv, MUNICIPIOS.csv)
3. Se inicia un bucle para procesar uno a uno los municipios base:
  ├─ 1º Obtiene su identificador INE real (11 dígitos) y población.
  ├─ 2º Extrae TODAS las unidades poblacionales (hijas) **directamente del INE**.
  ├─ 3º Por cada hija, busca en Wikipedia (usando un LLM local, por defecto `qwen2.5-7b-instruct`) para obtener descripciones e imágenes.
  ├─ 4º Si la hija es de tamaño `ciudad_grande` o `ciudad_pequena`, busca su estructura interna de distritos y barrios puramente en Wikipedia.
  ├─ 5º Se eliminan duplicados y se validan identificadores.
4. Guardar `lugares_espana.json` (o `municipios_actualizado.json`) con los lugares completos.
5. Validar estructura, relaciones e imágenes.

## Tipos de lugar

| `tipo` | Etiqueta | Cuelga de | Fiestas propias | Hijos |
|---|---|---|---|---|
| `municipio` | Municipio | — | **No** | `pueblo`, `ciudad_pequena`, `ciudad_grande` |
| `pueblo` | Pueblo | `municipio` | Sí | — |
| `ciudad_pequena` | Ciudad pequeña | `municipio` | Sí | Barrios (opcional) |
| `ciudad_grande` | Ciudad grande | `municipio` | Sí | Distritos y/o barrios (**opcional**) |
| `distrito` | Distrito | `ciudad_grande` | Sí | Barrios (opcional) |
| `barrio` | Barrio | `distrito` o `ciudad_pequena` | Sí | — |

> ℹ️ **Tener distritos es opcional.** No toda ciudad grande se divide en
> distritos: p. ej. **Torrevieja** es `ciudad_grande` y **no** tiene distritos
> (solo una entidad). Solo una `ciudad_grande` puede tener distritos.
>
> Los **barrios** se añaden en una segunda capa de detalle: si la ciudad grande
> tiene distritos, cada barrio cuelga de su `distrito`; si es una ciudad pequeña,
> el barrio cuelga directamente de la `ciudad_pequena`.

## Estructura del fichero

```jsonc
{
  "version": 3,
  "lugares": [
    {
      "id": "28079000000",
      "tipo": "municipio",
      "nombre": "Madrid",
      "provincia": "Madrid",
      "comunidad": "Comunidad de Madrid",
      "poblacion": 3332035,
      "lat": 40.4168,
      "lng": -3.7038,
      "es_capital": false
    },
    {
      "id": "28079000101",
      "tipo": "ciudad_grande",
      "padre_id": "28079000000",
      "nombre": "Madrid",
      "provincia": "Madrid",
      "comunidad": "Comunidad de Madrid",
      "poblacion": 3332035,
      "lat": 40.4168,
      "lng": -3.7038,
      "es_capital": true,
      "descripcion_corta": "...",
      "descripcion": "...",
      "imagenes": {
        "banner": "...",
        "logo": "..."
      }
    },
    {
      "id": "28079000101-centro",
      "tipo": "distrito",
      "padre_id": "28079000101",
      "nombre": "Centro",
      "descripcion_corta": "...",
      "descripcion": "...",
      "imagenes": {
        "banner": "...",
        "logo": "..."
      }
    },
    {
      "id": "28079000101-centro-sol",
      "tipo": "barrio",
      "padre_id": "28079000101-centro",
      "abuelo_id": "28079000101",
      "nombre": "Sol",
      "descripcion_corta": "...",
      "descripcion": "...",
      "imagenes": {
        "banner": "...",
        "logo": "..."
      }
    }
  ]
}
```

### Reglas
- **ids** = Código INE de 11 dígitos para el municipio y sus entidades base. Para distritos y barrios, se concatena un slug al ID de su entidad padre (`28079000101-centro`).
- `padre_id` solo en hijos y **debe existir** en el fichero. 
- **abuelo_id**: Opcional. Los barrios que cuelgan de un `distrito` deben incluir este campo con el ID de su entidad raíz (`ciudad_grande`).
- Un `distrito` solo cuelga de `ciudad_grande`.
- Un `barrio` cuelga de un `distrito` si pertenece a una ciudad grande con distritos, o directamente de una `ciudad_pequena` (o `ciudad_grande` sin distritos).
- Las entidades base (`pueblo`, `ciudad_pequena`, `ciudad_grande`) cuelgan siempre de un `municipio`.
- **Fechas** ISO `YYYY-MM-DD`; **horas** 24h `HH:MM`.
- **Imágenes** por URL. El escudo de la ficha de fiesta sale del `logo` del lugar.
- **Coordenadas** numéricas.

### Reglas de las paginas importantes para el algoritmo en wikipedia

MUNICIPIOS_CATEGORY_URL:

  Municipios_de_España_por_provincia
├─ Subcategorías: "Municipios de Córdoba", "Municipios de Almería" ❌ (NO usar)
└─ Páginas: "Anexo:Municipios de Córdoba", "Anexo:Municipios de Almería" ✅ (USAR)
    └─ Dentro de cada Anexo: listado de municipios

- Analizar solo enlaces de la A a la Z .
- Analizar solo Páginas en la categoría, no subcategorías, las subcategorías se deben saltar.
- Descargar Municipios_de_España_por_provincia → Provincias → Municipios.
- Los anexos tienen solamente como estructura común "Anexo:" y el resto varía.
- Dentro de cada anexo,hay una tabla donde aparecen todos los enlaces en la columna llamada "Municipio", "Nombre en castellano", "Nombre en español" o "Nombre".
- En el anexo, la columna deseada está en la tabla class="wikitable sortable jquery-tablesorter", encontrándose "Municipio", "Nombre en castellano", "Nombre en español" o "Nombre" como class="headerSort" en el thead, mientras que el tbody contiene la lista de municipios.

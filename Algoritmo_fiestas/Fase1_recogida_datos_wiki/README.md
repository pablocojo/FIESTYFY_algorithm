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
--Fase 1: obtener todos los municipios--
  1. Usuario ejecuta: python main.py
  2. Sistema descarga Categoría:Municipios de España
  3. Para cada municipio:
    ├─ Extrae información (población, provincia, comunidad, coords,...)
    ├─ Clasifica por tipo (pueblo/ciudad_pequeña/ciudad_grande,          municipio_compuesto)
    ├─ Extrae descripciones (corta y larga)
    ├─Extrae sitio web y direccion en wikipedia
    ├─ Obtiene imágenes (banner + logo)
  4. Guardar municipios.json
  5. El programa termina sin analizar subdivisiones
--Fase 1.5: Revalidación estricta de municipios compuestos--
1. Usuario ejecuta: python revalidar_compuestos.py
2. Carga `municipios.json` y cruza TODOS los lugares con las tablas del INE (`pobmun25` y `nomdef2025`).
3. Aplica regla estricta: Si el municipio NO tiene una localidad/pedanía con exactamente su mismo nombre en el padrón, lo reclasifica como `municipio_compuesto`. Si la tiene, lo marca como lugar físico.
4. Genera `municipios_revisados.json` y un informe detallado.
--Fase 2: añadir al json distritos, barrios y pedanías--
1. Usuario ejecuta: python main2.py
2. Se carga municipios.json como base
3. Se inicia un bucle para analizar uno a uno los municipios
4. Para cada municipio (sea del tipo que sea):
  ├─ 1º Extrae sus **pedanías directamente del INE** (Fuzzy matching con Wikipedia y API).
  ├─ 2º Si es `ciudad_grande`, busca distritos y luego barrios.
  ├─ 3º Si es `ciudad_pequena`, busca barrios adicionales.
  ├─ 4º Deduplica por ID, nombre y URL de Wikipedia priorizando **siempre** la Pedanía frente al Distrito o Barrio.
5. Guardar lugares_espana.json con los municipios y las subdivisiones
6. Validar estructura, relaciones e imágenes (El `banner` siempre se extrae de la propiedad P18 de Wikidata, y el `logo` de Wikipedia).

## Tipos de lugar

| `tipo` | Etiqueta | Cuelga de | Fiestas propias | Hijos |
|---|---|---|---|---|
| `pueblo` | Pueblo | — | Sí | — |
| `ciudad_pequena` | Ciudad pequeña | — | Sí | Barrios y/o pedanías (opcional) |
| `ciudad_grande` | Ciudad grande | — | Sí | Distritos y/o pedanías (**opcional**) |
| `municipio_compuesto` | Municipio compuesto | — | **No** (solo muestra sus pedanías) | Pedanías |
| `distrito` | Distrito | `ciudad_grande` | Sí | Barrios (opcional) |
| `barrio` | Barrio | `distrito` o `ciudad_pequena` | Sí | — |
| `pedania` | Pedanía | cualquier municipio o compuesto | Sí | — |

> ⚠️ **Tener distritos es opcional.** No toda ciudad grande se divide en
> distritos: p. ej. **Torrevieja** es `ciudad_grande` y **no** tiene distritos
> (solo una pedanía, La Mata). Solo una `ciudad_grande` puede tener distritos;
> las pedanías puede tenerlas cualquier municipio raíz.
>
> Los **barrios** se añaden en una segunda capa de detalle: si la ciudad grande
> tiene distritos, cada barrio cuelga de su `distrito`; si es una ciudad pequeña,
> el barrio cuelga directamente de la `ciudad_pequena`.

## Estructura del fichero

```jsonc
{
  "version": 2,
  "lugares": [
    {
      "id": "madrid",
      "tipo": "ciudad_grande",
      "nombre": "Madrid",
      "provincia": "Madrid",
      "comunidad": "Comunidad de Madrid",
      "poblacion": 3280000,
      "lat": 40.4168,
      "lng": -3.7038,
      "descripcion_corta": "...",
      "descripcion": "...",
      "imagenes": {
        "banner": "...",
        "logo": "..."
      }
    },
    {
      "id": "madrid-centro",
      "tipo": "distrito",
      "padre_id": "madrid",
      "nombre": "Centro",
      ...
    },
    {
      "id": "madrid-centro-sol",
      "tipo": "barrio",
      "padre_id": "madrid-centro",
      "abuelo_id": "madrid",
      "nombre": "Sol",
      ...
    }
  ]
}
```

### Reglas
- **ids** = slug (minúsculas, sin acentos, guiones); para hijos, **prefija con el padre** (`madrid-centro-sol`).
- `padre_id` solo en distritos/barrios/pedanías y **debe existir** en el fichero. Máx. 3 niveles cuando haya barrio (`ciudad_grande` → `distrito` → `barrio`).
- **abuelo_id**: Opcional. Los barrios que cuelgan de un `distrito` deben incluir este campo con el ID del municipio raíz.
- Un `distrito` solo cuelga de `ciudad_grande`.
- Un `barrio` cuelga de un `distrito` si pertenece a una ciudad grande con distritos, o directamente de una `ciudad_pequena` si no hay distrito intermedio.
- Una `pedania` cuelga de un municipio raíz (`pueblo`, `ciudad_pequena`, `ciudad_grande`) o de un `municipio_compuesto`.
- Un `municipio_compuesto` **no** puede tener fiestas propias.
- **Provincia/comunidad**: obligatorias en lugares raíz; los hijos las **heredan** del padre.
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

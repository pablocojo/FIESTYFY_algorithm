# Refactorización de Fase 1: Datos basados en NGMEP (MUNICIPIOS.csv + ENTIDADES.csv)

## Contexto y objetivo

Actualmente la **Fase 1** (`main.py`) obtiene los municipios raíz scrapeando Wikipedia categoría por categoría, y la **Fase 2** (`main2.py`) busca subdivisiones (pedanías, distritos, barrios) combinando Wikipedia + tablas INE en .xlsx.

El cambio propuesto es **radical**: la fuente de verdad para la estructura de lugares pasa a ser las tablas del NGMEP (Nomenclátor Geográfico de Municipios y Entidades de Población) del IGN:

- [MUNICIPIOS.csv](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/datos_municipios/MUNICIPIOS.csv) — 8.132 municipios con coordenadas, población, capital e ID INE
- [ENTIDADES.csv](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/datos_municipios/ENTIDADES.csv) — 153.950 filas con todas las entidades poblacionales (municipio, entidad singular, capital, diseminado, entidad colectiva, otras entidades)
- [PROVINCIAS.csv](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/datos_municipios/PROVINCIAS.csv) — Mapeo provincia → comunidad autónoma

## User Review Required

> [!IMPORTANT]
> **El concepto de "pedanía" desaparece como tipo.** Las localidades que antes se llamaban "pedanía" pasan a clasificarse por población como `pueblo`, `ciudad_pequena` o `ciudad_grande`. Se añade un campo booleano `es_capital` para distinguir la capital del municipio.

> [!IMPORTANT]
> **El tipo `municipio_compuesto` desaparece.** Solo habrá: `municipio`, `pueblo`, `ciudad_pequena`, `ciudad_grande`, `distrito`, `barrio`.

> [!WARNING]
> **Los IDs cambian completamente**: de slugs tipo `amurrio-aloria` a códigos INE tipo `01002000101`. Esto rompe toda compatibilidad con el `lugares_espana.json` actual y con cualquier sistema downstream que use los IDs antiguos.

## Open Questions

> [!IMPORTANT]
> **1. ¿Qué entidades del NGMEP se incluyen como "localidades" hijas de un municipio?**
> 
> En `ENTIDADES.csv` hay 6 tipos de fila:
> | Tipo | Cantidad | Descripción |
> |---|---|---|
> | `Municipio` | 8.132 | El propio municipio (raíz) |
> | `Capital de municipio` | 8.132 | El núcleo que es sede del ayuntamiento |
> | `Entidad singular` | 62.084 | Cualquier área habitable diferenciada (pueblos, aldeas...) |
> | `Otras entidades` | 29.459 | Núcleos de población del INE |
> | `Entidad colectiva` | 4.904 | Parroquias, hermandades, concejos, diputaciones... |
> | `Diseminado` | 41.239 | Viviendas dispersas de una entidad singular |
> 
> **Mi propuesta**: Incluir como localidades hijas solo las filas de tipo **`Capital de municipio`** y **`Otras entidades`** (los núcleos). Las `Entidad singular` son el nivel "intermedio" (agrupan el núcleo + su diseminado) y duplicarían información. Los `Diseminado` y `Entidad colectiva` no son localidades con fiestas propias.
> 
> ¿Es correcto? ¿O prefieres incluir también las `Entidad singular` en lugar de (o además de) las `Otras entidades`?

> [!IMPORTANT]
> **2. ¿Qué pasa con distritos y barrios?**
> 
> Las tablas del NGMEP **no contienen distritos ni barrios**. Solo tienen municipios y entidades de población (que son localidades/núcleos). 
> 
> - **Opción A**: Los distritos y barrios se siguen extrayendo de Wikipedia como en la Fase 2 actual (manteniendo `main2.py` para esa función).
> - **Opción B**: Se eliminan por ahora y se añaden en una fase posterior.
> - **Opción C**: Se buscan de otra fuente de datos.
> 
> ¿Cuál prefieres?

> [!IMPORTANT]
> **3. ¿El tipo `municipio` es para el registro raíz de cada municipio?**
> 
> Dices que ahora los tipos posibles son: `municipio`, `pueblo`, `ciudad_pequena`, `ciudad_grande`, `distrito`, `barrio`.
> 
> ¿Cuál es la lógica?:
> - **Opción A**: El registro raíz del municipio siempre tiene `tipo: "municipio"`. Sus localidades hijas se clasifican como `pueblo` / `ciudad_pequena` / `ciudad_grande` según su población individual.
> - **Opción B**: El registro raíz del municipio se clasifica como `pueblo` / `ciudad_pequena` / `ciudad_grande` según la **población total del municipio** (como antes), y sus localidades hijas tienen el tipo que les corresponda por su propia población.
> - **Opción C**: Otra lógica. ¿Cuál?

> [!IMPORTANT]
> **4. Regla de deduplicación de localidades repetidas.**
> 
> Dentro de cada municipio en `ENTIDADES.csv`, un mismo nombre aparece varias veces (una como `Entidad singular`, otra como `Capital de municipio` o `Otras entidades`, otra como `Diseminado`). Ejemplo de Amurrio:
> ```
> 01002000100  Aloria   Entidad singular   24 hab
> 01002000101  Aloria   Otras entidades    24 hab
> ```
> La regla actual de deduplicación es: si coinciden nombre normalizado dentro del mismo municipio, quitar la de menor población. **¿Se mantiene esta misma regla, o al seleccionar solo ciertos tipos (`Capital de municipio` + `Otras entidades`) ya no hará falta deduplicar?**

> [!IMPORTANT]
> **5. ¿Las descripciones, imágenes, sitio_web y wikipedia_url se siguen extrayendo de Wikipedia/LLM como hasta ahora?**
> 
> La nueva Fase 1 aportaría los datos estructurales del NGMEP (id, nombre, ubicación, población, tipo, es_capital). Los campos "enriquecidos" (descripción_corta, descripción, imágenes, sitio_web, wikipedia_url) siguen requiriendo Wikipedia y el LLM.
> 
> ¿Se generan en esta misma fase o en una fase posterior?

> [!IMPORTANT]
> **6. Sobre el campo `padre_id` para las localidades.**
> 
> El `padre_id` de una localidad hija sería el `CODIGOINE` del municipio al que pertenece (los 5 primeros dígitos del código + 000000, es decir el campo `INEMUNI` + `000000`). ¿Es correcto?

## Proposed Changes (pendiente resolución de dudas)

### Estructura JSON propuesta (nueva)

```jsonc
{
  "version": 3,
  "lugares": [
    {
      "id": "01002000000",           // CODIGOINE del NGMEP
      "tipo": "municipio",           // o pueblo/ciudad_pequena/ciudad_grande según decisión
      "nombre": "Amurrio",
      "provincia": "Araba/Álava",
      "comunidad": "País Vasco/Euskadi",
      "poblacion": 10346,            // POBLACION_MUNI del NGMEP
      "lat": 43.05265767,            // LATITUD_ETRS89_REGCAN95
      "lng": -3.001015194,           // LONGITUD_ETRS89_REGCAN95
      "es_capital": false,           // NUEVO: booleano
      "descripcion_corta": "",       // Se llenará después (Wikipedia/LLM)
      "descripcion": "",
      "imagenes": { "banner": "", "logo": "" },
      "sitio_web": "",
      "wikipedia_url": ""
    },
    {
      "id": "01002000201",           // CODIGOINE de la localidad
      "tipo": "pueblo",              // Clasificado por población
      "padre_id": "01002000000",     // CODIGOINE del municipio padre
      "nombre": "Amurrio",
      "provincia": "Araba/Álava",
      "comunidad": "País Vasco/Euskadi",
      "poblacion": 9256,             // Población del núcleo
      "lat": 43.05265767,
      "lng": -3.001015194,
      "es_capital": true,            // Es capital del municipio
      "descripcion_corta": "",
      "descripcion": "",
      "imagenes": { "banner": "", "logo": "" },
      "sitio_web": "",
      "wikipedia_url": ""
    }
  ]
}
```

### Cambios de ficheros (alto nivel, pendiente de tus respuestas)

---

#### Datos de entrada

Se reemplaza la fuente de datos:
- **Antes**: Wikipedia (scraping de categorías) + `pobmun25.xlsx` / `nomdef2025.xlsx`
- **Ahora**: `MUNICIPIOS.csv` + `ENTIDADES.csv` + `PROVINCIAS.csv` del NGMEP

---

#### [MODIFY] [datos_ine.py](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/datos_ine.py)

Refactorizar para leer los nuevos CSV del NGMEP en lugar de los .xlsx del INE. Nuevas funciones:
- `cargar_municipios_ngmep()`: Lee `MUNICIPIOS.csv` y devuelve todos los municipios.
- `cargar_entidades_ngmep()`: Lee `ENTIDADES.csv` y devuelve entidades filtradas por tipos relevantes.
- `cargar_provincias_ngmep()`: Lee `PROVINCIAS.csv` para el mapeo provincia → comunidad autónoma.

---

#### [MODIFY] [main.py](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/main.py)

Reescribir la Fase 1 para:
1. Cargar los 8.132 municipios desde `MUNICIPIOS.csv`
2. Para cada municipio, cargar sus entidades de `ENTIDADES.csv`
3. Generar el registro raíz del municipio con sus datos del NGMEP
4. Generar las localidades hijas con sus datos del NGMEP
5. Aplicar deduplicación y clasificación por tipo
6. Guardar `municipios.json` con la nueva estructura

---

#### [MODIFY] [place_types.py](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/place_types.py)

- Eliminar `pedania` y `municipio_compuesto` de los tipos válidos.
- Añadir `municipio` como tipo válido.
- Actualizar `valida_lugar()` para incluir el campo `es_capital`.
- Actualizar `valida_dataset()` para las nuevas reglas de relación padre-hijo.

---

#### [MODIFY] [config.py](file:///c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki/config.py)

Añadir constantes para los nuevos ficheros CSV y ajustar umbrales si es necesario.

---

## Verification Plan

### Automated Tests
- `python -c "..."` para verificar que el JSON de salida tiene los 8.132 municipios.
- Validar con `place_types.valida_dataset()` que la estructura es correcta.
- Verificar que no hay IDs duplicados.
- Comprobar que ningún lugar tiene `lat: 0.0, lng: 0.0`.
- Verificar que todas las localidades hijas tienen un `padre_id` que existe.

### Manual Verification
- Revisar un municipio ejemplo (Amurrio) para confirmar que la estructura y los datos son correctos.
- Comparar la cantidad total de localidades con las cifras esperadas del NGMEP.

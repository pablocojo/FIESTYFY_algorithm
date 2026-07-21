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
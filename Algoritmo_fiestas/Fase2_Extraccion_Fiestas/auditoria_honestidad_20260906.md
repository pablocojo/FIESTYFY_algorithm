# Auditoría de honestidad — ejecución del 2026-09-06

**Datos auditados:** `fiestas_amplio_searxng.json` (52 fiestas, 9 municipios)
**Método:** verificación contra fuentes reales de internet, incluida la descarga del PDF
oficial de un programa para comparar acto por acto.
**Pregunta:** ¿pone lo que hay en internet, ni más ni menos?

**Veredicto corto:** es honesto **extrayendo** y deshonesto **afirmando**. No se inventa
contenido, pero etiqueta mal, duplica, recorta rangos y su campo de procedencia miente.

---

## Lo que hace bien

### No inventa actos

Descargado el PDF oficial de Purchena (`turismoalmanzora.com/.../programa-San-Gines-purchena26.pdf`,
12,8 MB) y comparado con lo extraído:

| PDF oficial | Ficha generada |
|---|---|
| Sábado 22, 22:00 · Lectura del pregón a cargo de Carmen Cano | idéntico |
| Lunes 24, 23:00 · Verbena musical amenizada por Orquesta | idéntico |
| Martes 25, 19:30 · Misa y Procesión acompañada por la Banda | idéntico |
| Miércoles 26, 18:30 · Misa y romería de la Virgen del Carmen | idéntico |

Texto literal, fechas y horas correctas. **Sin alucinación.**

### Acierta las fechas cuando localiza bien la fuente

| Fiesta | Ficha | Realidad verificada |
|---|---|---|
| Feria Internacional Ganadera de Zafra | 1–6 oct 2026 | 1–6 oct 2026 ✓ |
| San Ginés de Purchena | 22–26 ago 2026 | 22–26 ago 2026 ✓ |
| Semana Santa de Garrucha | 29 mar – 5 abr 2026 | correcto ✓ |

### Se declara insegura

| Señal | Reparto |
|---|---|
| `confianza` | baja 38 · media 11 · alta 3 |
| `solo_fuentes_no_oficiales` | True 39 · False 13 |
| `programa_estado` | no_encontrado 32 · completo 19 · parcial 1 |

Solo 3 fichas de 52 se declaran de confianza alta, y la que verifiqué (San Ginés) era
correcta. El sistema no presume de lo que no sabe.

---

## Lo que sobra

### 1. Etiquetado falso — el fallo más grave

```
NOMBRE:  Fiestas Patronales de San Joaquín   (Garrucha)
FECHAS:  2026-02-20 → 2026-03-21
ACTOS:   "Triduo a Nuestro Padre Jesús", "Confesiones en el Templo
          Parroquial", "Santa Misa en recuerdo de nuestros difuntos"
```

Eso es Cuaresma. Las fiestas de San Joaquín de Garrucha son **del 14 al 18 de agosto**,
según la web del propio ayuntamiento ("Feria de San Joaquín, patrón de la localidad. Del 14
al 18 de Agosto"), La Voz de Almería y Es Radio Almería.

Los actos son reales; la afirmación no. Alguien que lea la base de datos concluirá que
Garrucha celebra a su patrón en febrero.

### 2. Duplicados: 7 pares en 52 fichas

| Ficha A | Ficha B |
|---|---|
| Fiestas Patronales de San Joaquín [02-20] 14d | Fiestas Patronales en Honor a San Joaquín [08-14] 3d |
| Fiesta de la Luna al Fuego [06-20] 5d | De la luna al fuego [06-28] 4d |
| Fiestas de Verano y Feria Agroalimentaria [06-20] 7d | Fiesta Verano El Barraco [07-13] 3d |
| Fiestas de San Ginés de Purchena [08-22] 5d | Fiestas de Purchena [07-30] 3d |
| Fiestas Patronales de Higuera de la Serena [08-10] | Fiestas de Higuera de la Serena [08-01] |
| Feria de Ganado de El Barraco [05-03] 2d | Fiestas de Verano y Feria Agroalimentaria [06-20] 7d |
| Fiesta de San Isidro Labrador [05-15] | Fiestas Patronales de Hinojosa del Valle [08-15] 2d |

La misma celebración aparece dos veces con fechas distintas y programas distintos. Es el
problema P1-5 (nombres inestables) manifestándose como duplicación en la salida, no solo
como ruido interno.

### 3. `solo_fuentes_no_oficiales` no es de fiar: 15 casos incoherentes

El campo dice `True` mientras la URL del programa está en un dominio oficial:

```
garrucha.es                   Fiestas Patronales de San Joaquín
garrucha.es                   Semana Santa Garrucha 2026
higueradelaserena.es          Semana Santa
sede.higueradelaserena.es     Ramos de la Virgen Inmaculada 2026
zafra.es                      Carnaval de Zafra 2026
```

Es el campo que un consumidor usaría precisamente para filtrar lo dudoso, y miente en 15 de
52 fichas. Peor que no tenerlo.

### 4. Dos fichas afirman programa con la lista de fuentes vacía

5 fichas tienen `fuentes: []`, y 2 de ellas presentan actos. Un acto sin fuente no es
verificable.

---

## Lo que falta

### Fiestas reales no reportadas

Comprobado solo en Garrucha, donde el algoritmo devuelve 6 fichas:

| Ausente | Evidencia |
|---|---|
| **Virgen del Carmen, 16 de julio** | Procesión marítima, descrita en la web del ayuntamiento: "la Virgen es portada en un barco". En un pueblo pesquero es de las principales. |
| **Carnaval, 22 de febrero de 2026** | "El Carnaval de Garrucha se celebrará el domingo 22 de febrero a las 11:30", con desfile comarcal de comparsas. |

Llamativo: la ficha falsa de San Joaquín empieza el 20 de febrero. Cogió material de esas
fechas y lo etiquetó como fiestas de agosto, mientras el Carnaval real del 22 se quedó fuera.

### Rangos recortados

| Fiesta | Ficha | Real |
|---|---|---|
| San Joaquín (Garrucha) | 14–16 ago | 14–18 ago |
| San Ginés (Purchena) | 22–26 ago | el PDF incluye "Viernes 21 de Agosto" |

No es inventar de más: es contar de menos. Para el objetivo de honestidad importa igual,
porque la ficha afirma un rango cerrado que no es el real.

---

## Qué haría, por orden de daño

1. **Cortar el etiquetado falso.** Si los actos extraídos caen fuera del rango de fechas
   plausible de la fiesta nombrada, la ficha no debe salir con ese nombre. Es preferible
   `no_encontrado` a una afirmación falsa.
2. **Deduplicar en la salida.** Dos fichas de la misma localidad con nombres solapados y
   fechas distintas son una señal, no dos datos.
3. **Arreglar o retirar `solo_fuentes_no_oficiales`.** Un campo de procedencia que se
   equivoca en el 29% de los casos hace más daño que no existir.
4. **Exigir fuente para afirmar programa.** Sin `fuentes`, `programa_estado` no debería
   poder valer `completo`.

Lo que **no** haría: perseguir el porcentaje de fiestas sin programa. Que 32 de 52 no tengan
programa publicado es probablemente cierto y honesto. El problema no es lo que falta, es lo
que afirma de más.

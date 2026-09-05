# Problemas actuales — Fase 2

**Fecha:** 2026-09-04
**Base:** tirada amplia de 9 municipios nuevos (`fiestas_amplio.json`, 42 fichas, 6,6 h) y
tirada corta de 4 municipios trampa (`fiestas_prueba_juez.json`, 3 fichas, 1,5 h).
**Sustituye a:** `problemas_actuales_fase2.md` (2026-09-01), cuyos P0 están resueltos.

> **Estado tras los arreglos de la tarde del 2026-09-04:** sobre los mismos 4 municipios
> trampa, las fichas reales pasan de 2 a 5, las que traen programa de 0 a 3 y los actos
> extraídos de 0 a 53, sin que se cuele ninguna ficha de otra localidad. La batería de
> tests pasa entera por primera vez (784, 0 fallos).
>
> Ocho de los once problemas están resueltos. Quedan abiertos: los programas de El Fresno
> y Corral-Rubio, los nombres de fiesta inestables (aplazado a petición) y el denominador
> de la métrica de cobertura.

---

## Resumen

| # | Problema | Sev. | Impacto medido | Estado |
|---|----------|------|----------------|--------|
| 1 | El contexto de discovery lo llenan los homónimos y las páginas legales del propio pueblo | **P0** | Santa Marta: 23 chunks de Colombia y 12 de Astorga en cabecera. El Fresno: 25 % del contexto es aviso legal | **RESUELTO** en los 4 municipios medidos |
| 2 | El código decide sobre topónimos en vez del LLM | **P0** | Mató la única ficha real de Santa Marta ('Candelas 2026') | **RESUELTO** |
| 3 | La araña sigue una redirección a otro dominio y lo cuenta como web municipal | **P1** | 76 documentos de la Diputación de Badajoz como `web_municipio` | **RESUELTO** |
| 4 | Cero programas en municipios pequeños | **P1** | 0 de 2 fichas correctas traen programa | **Parcial**: 3 fichas con programa y 53 actos donde antes había 0; El Fresno y Corral-Rubio siguen sin él |
| 5 | Nombres de fiesta inestables entre ejecuciones | **P1** | 20 nombres distintos para las fiestas de Tobarra | Abierto (aplazado a petición) |
| 6 | Páginas legales y de cookies en el ranking de discovery | **P2** | 15 de 60 chunks en El Fresno | **RESUELTO** |
| 7 | El denominador de `[ENRICHMENT/COBERTURA]` cuenta días que el documento no programa | **P2** | Aviso falso «0 de 4 días (0 %)» en Tobarra | Documentado en código como PENDIENTE |
| 8 | Datos de entrada de Fase 1 poco fiables | **P2** | 7 pueblos de interior con playas en su descripción; 1 URL municipal errónea | Fuera de alcance de Fase 2 |
| 9 | La comunidad autónoma nunca llegaba: se leía de una clave inexistente | **P0** | Perfil de idioma vacío en TODAS las ejecuciones, incluidas las 50 de Álava | **RESUELTO** |
| 10 | Los nombres con artículo no casaban en su forma invertida del INE | **P0** | 1.786 lugares (18 %); a La Parra se le descartaban como ajenos documentos que sí eran suyos | **RESUELTO** |
| 11 | Un lote de enrichment sin respuesta recortaba la fiesta en silencio | **P1** | Santa Marta perdió el 29 de julio, el día de su patrona | **RESUELTO** |

## Medición del 2026-09-04 (tarde), sobre los 4 municipios trampa

| | Antes | Después |
|---|---|---|
| Fichas reales (no estimadas) | 2 | **5** |
| Fichas con programa | 0 | **3** |
| Actos extraídos | 0 | **53** |
| Consultas con desambiguación geográfica | 29 % | **60 %** |
| Fichas de otra localidad que sobreviven | 0 | **0** |
| Batería de tests | 4 fallos | **784, 0 fallos** |

```
LOCALIDAD      FECHAS                  d  act  FIESTA
Santa Marta    2026-07-23~2026-07-28   6   20  Fiestas Patronales de Santa Marta de los Barros
La Parra       2026-08-14~2026-08-16   3   19  Fiestas Patronales a Ntra. Sra. de la Asunción
El Fresno      2026-07-15~2026-07-31  10   14  Verano Cultural 2026
El Fresno      2026-08-19~2026-08-23   0    0  Fiestas Patronales de El Fresno 2026
Corral-Rubio   2026-09-28~2026-09-30   0    0  Fiestas de San Miguel
```

Santa Marta pasa de no tener ninguna ficha real —seis descartadas, entre ellas las de
Astorga y las de Santa Marta de Colombia— a sus patronales con 20 actos, aceptadas por
la repregunta:

```
[PERTENENCIA] 'Fiestas Patronales de Santa Marta de los Bar': situaba la fiesta en
«Santa Marta de los Barros, provincia de Badajoz, Extremadura»; repreguntado,
confirma que es de aquí.
```

La Parra pasa de 0 a sus patronales de la Asunción con 19 actos, y el contenido lo
confirma: «Ronda **Parreña**», banda municipal y la procesión de Nuestra Señora de la
Asunción el 15 de agosto, que es su día patronal documentado.

**Lo que sigue sin resolverse:**

* El Fresno y Corral-Rubio siguen sin programa: sus fiestas patronales salen con fecha
  pero sin actos.
* La ficha de La Parra guarda como `url_programa` un dominio de Arenas de San Pedro,
  aunque el contexto y los actos son de Badajoz. Cabo suelto de trazabilidad.
* Las fechas de El Fresno (19-23 ago) no contienen el 15 de agosto, que es la Asunción.

---

## P0 — Críticos

### 1. El contexto de discovery lo llenan los homónimos y las páginas legales

**Síntoma:** en municipios pequeños, los documentos que más chunks aportan al contexto de
discovery no hablan de la localidad buscada.

**Evidencia** (tirada del 2026-09-04, documentos que encabezan cada contexto):

```
Santa Marta   23 chunks  malokal.com/es/COLOMBIA/santa-marta/calendario-de-eventos-2026
              12 chunks  eldescansodewendy.com/fiestas-de-ASTORGA-2026
La Parra      11 chunks  arenasdesanpedro.es/categoria/eventos            (Ávila)
               9 chunks  tietarteve.com/fiestas-asuncion-la-parra         (Ávila)
El Fresno      9 chunks  elfresno.es/…/proteccion-de-datos.html
               6 chunks  elfresno.es/…/aviso-legal.html
La Higuera     4 chunks  cookiedatabase.org/tcf/purposes
```

**Dos mecanismos distintos, misma consecuencia:**

* **Homónimos.** Cuanto menos publica un pueblo, más peso relativo gana el pueblo del
  mismo nombre que sí publica. Santa Marta (Badajoz, 4.199 hab) compite con Santa Marta
  de Colombia, Astorga y Santa Marta de Tormes.
* **Ruido del propio dominio.** El aviso legal y la protección de datos vienen de la web
  del ayuntamiento, así que superan todos los filtros geográficos con nota máxima y no
  dicen nada de fiestas. Ver el problema 6.

**Consecuencia:** la fiesta real nunca llega al modelo. No es un fallo del filtro —el juez
de pertenencia rechazó correctamente todo lo ajeno— sino que **no había nada bueno que
elegir**.

**Nota de honestidad sobre la muestra:** los cuatro municipios de la tirada corta se
eligieron *a propósito* por ser trampas de homonimia. El 17 % de recall es el peor caso
por construcción, no la media. Lo representativo es el mecanismo, no la cifra.

### 2. El código decide sobre topónimos en vez del LLM

**Síntoma:** `lugar_real_contradice()` compara por palabras el sitio que nombra el modelo
contra el nombre de la localidad, y descarta si sobra alguna.

**Evidencia:**

```
DESCARTADA 'Candelas 2026' de Santa Marta: el modelo dijo 'sí' pero sitúa la fiesta
en «Santa Marta de los Barros, Badajoz» … hogueras, concurso de candelas y verbena
```

El modelo acertó. El dataset llama al pueblo "Santa Marta"; su nombre real es "Santa Marta
**de los Barros**"; sobra "barros" y el veto la mató. Era la única ficha real que el
pipeline llegó a producir para ese municipio.

**Por qué no basta con quitar el veto:** nació de un fallo medido del modelo, que respondió
`"es_de_la_localidad": "si"` y escribió a la vez `lugar_real: "Arroyomolinos de la Vera"`
—otro municipio—. Se contradijo dentro de una sola respuesta.

**Dirección acordada:** la decisión pasa al LLM.

* Darle los datos que hoy compara el código —municipio, provincia, comunidad y **el
  `sitio_web` oficial**, que en este caso es `santamartadelosbarros.com` y lleva el nombre
  completo dentro— como contexto para que **él** decida.
* Cuando el código detecte una incoherencia, **repreguntar** señalándole la duda en vez de
  descartar. El código detecta; el modelo decide.

---

## P1 — Importantes

### 3. La araña sigue una redirección a otro dominio y lo cuenta como web municipal

**Evidencia:**

```
[Spider] URL canónica: http://www.santamartadelosbarros.com → https://badajoz.es
```

Se mapearon 77 páginas de la **Diputación de Badajoz** y entraron como 76 documentos
`web_municipio`. La web real del pueblo es `santamarta.es`.

**Frecuencia:** único caso en ~30 municipios del histórico. Raro, pero pérdida total
cuando ocurre.

**Acordado:** si la URL canónica sale a un dominio registrable distinto, no es la web del
municipio. Se descarta ese rastreo y **se sigue solo con la búsqueda web**.

### 4. Cero programas en municipios pequeños

Ninguna de las fichas correctas de la tirada corta trae programa de actos. En pueblos de
300–4.000 habitantes el programa suele publicarse solo como cartel en imagen, o no
publicarse en web.

Pendiente de decidir si es un límite real de la fuente o del pipeline.

### 5. Nombres de fiesta inestables entre ejecuciones

Acumulando los volcados, el pipeline ha dado **20 nombres distintos** a las fiestas de
Tobarra, 15 a las de Cordovilla y 14 a las de Aranda. Sin identidad estable no hay forma de
deduplicar entre años ni de actualizar registros en la base de datos.

---

## P2 — Menores

### 6. Páginas legales y de cookies en el ranking de discovery

**Evidencia:** El Fresno, 15 de 60 chunks (25 % del contexto) en `proteccion-de-datos.html`
y `aviso-legal.html` de su propia web.

**Para qué sirve filtrarlas:**

1. **Son el falso positivo perfecto:** vienen del dominio del propio ayuntamiento, pasan
   todos los filtros de procedencia con nota máxima y no contienen nada sobre fiestas.
2. **Mandan en el orden.** Desde el repartidor nada se descarta, pero el ranking decide qué
   entra en el primer lote; si la cabecera es la política de cookies, el material festivo
   cae al segundo o más allá, y cada lote es una llamada más.
3. **No distinguen nada:** el aviso legal de dos ayuntamientos distintos es casi idéntico.
   Aportan cero señal y diluyen la que hay.

**Magnitud real:** es coste y orden, no pérdida dura. Por eso es P2 y no P0.

### 7. El denominador de `[ENRICHMENT/COBERTURA]` cuenta días que el documento no programa

El aviso «el programa no se ha recogido entero» salta contando como día del documento
cualquier fecha que aparezca en el texto, aunque no tenga ni un acto. En Tobarra dio «0 de
4 días (0 %)» sobre un documento que no programaba ninguno de los cuatro —eran una ventana
de venta de entradas y la fecha del artículo—.

Se probó exigir una hora detrás de la fecha (ventana de 300 caracteres) y **no sirve**: en
un programa denso siempre hay una hora cerca. Haría falta detectar la *cabecera* de un día
("Sábado, 9 de mayo" a principio de línea). Documentado en el código como PENDIENTE.

### 8. Datos de entrada de Fase 1 poco fiables

* **Descripciones generadas desde el nombre del pueblo.** Siete localidades de provincias
  sin costa traen playas o acantilados: Santa Marta (Albacete) «con vistas al mar y ruinas
  romanas», Las Arenas y Santa Marina (Burgos) «playas de arena dorada», Batán del Puerto
  (Albacete) «acantilados». Ya excluidas del bloque de identidad del juez.
* **URLs municipales erróneas**, ver problema 3.

Fuera del alcance de Fase 2, pero condiciona sus resultados y acabará en la base de datos.

---

## Decidido y cerrado

* **Redes sociales:** no se construye captación propia. Los enlaces a redes que aparezcan
  en la búsqueda web se tratan como cualquier otra página. Descartado el plan de motores
  dedicados por red (2026-09-04).

## Resuelto la tarde del 2026-09-04

* **La comunidad autónoma no llegaba a ningún sitio.** El código la leía como
  `comunidad_autonoma` en cuatro puntos y ninguno de los 9.752 lugares del dataset tiene
  esa clave; se llama `comunidad`. Iba vacía en las consultas y en
  `get_language_profile`, que decide con qué idiomas se busca y se filtra: todas las
  ejecuciones de Álava trataron sus municipios como monolingües castellanos. Ahora hay una
  única función, `config_idiomas.comunidad_de`, para que el nombre del campo se decida en
  un solo sitio.
* **Consultas sin desambiguar**, del 71 % al 40 %. Se reparten tres criterios distintos
  —provincia, nombre oficial completo y `site:`— en vez de exigir el mismo a todas, para
  no dejar fuera a las fuentes que nunca nombran la provincia. Incluye el reintento que
  quita el operador `site:`, que era el último agujero por el que entraba Colombia.
* **Nombre oficial completo del municipio**, resuelto por el LLM una vez y cacheado en
  `nombres_oficiales_cache.json`. Comprobado contra el modelo real: alarga Santa Marta a
  "Santa Marta de los Barros" y deja Tobarra, Aranda de Duero y La Parra como están, sin
  inventar apellidos.
* **Salto de dominio en la araña.** Verificado contra las 12 redirecciones reales del
  histórico: solo rechaza `santamartadelosbarros.com → badajoz.es`. Distingue el punycode
  (`xn--alfozdequintanadueas-l7b.es` es `alfozdequintanadueñas.es`) y los cambios de TLD
  de la misma entidad. En producción eliminó los 76 documentos de la Diputación.
* **Páginas legales fuera del rastreo**: aviso legal, protección de datos, cookies,
  accesibilidad y mapa web.
* **El topónimo lo decide el LLM.** El veto del código deja de ser veredicto: cuando el
  modelo dice "sí" y a la vez nombra un sitio que no reconocemos, se le repregunta
  señalándole la duda. Si a la segunda tampoco lo tiene claro, fuera.
* **Dos tests que salían a internet** y fallaban según el día: `test_social_finder` traía
  un Instagram distinto en cada ejecución, y `test_fuentes_prensa` parcheaba
  `analyze_festivals_for_locality` cuando `process_locality` llama a
  `analyze_festivals_multipass`, así que corría el análisis real y hacía OCR de un PDF.
  **La batería completa pasa entera por primera vez: 774 tests, 0 fallos.**

### Un error propio, corregido a media medición

Al pasar el nombre oficial al juez lo puse como un campo aparte del nombre corto, y el
modelo los leyó como dos pueblos distintos: descartó la Semana Santa de Santa Marta
razonando «el texto la sitúa en Santa Marta de los Barros, pero el nombre oficial del
municipio es Santa Marta de los Barros, no Santa Marta». Cambiar el veto del código por el
mismo error dentro del modelo no es progreso. Ahora los dos nombres van en la misma línea
diciendo expresamente que son el mismo sitio.

## Resuelto antes, en esta misma sesión

* Rangos de trámite fabricando fichas fantasma (`_TRAMITE` ampliado y regla
  `rango_contradice_al_programa`): «Venta de tickets del 24 de abril al 4 de mayo» creaba
  unas "Fiestas de Tobarra" inexistentes que además se llevaban el mejor documento.
* `_RE_HORA_PROGRAMA` no reconocía `10:00h` —el formato español dominante—, de modo que el
  "modo programa" del troceador no arrancaba en el 18 % de las líneas de programa reales
  (2.491 de 13.739 sobre 159 contextos).
* El volcado de depuración medía el enrichment contra el pool entero y gritaba «N chunks no
  llegaron al modelo» en fichas correctas.
* **Juez de pertenencia (paso 8):** decide si una ficha es de la localidad y si es una
  fiesta. Validado contra 42 fichas reales (23/26 aciertos, 14/14 fiestas legítimas
  conservadas) y en producción rechazó Astorga, Santa Marta de Colombia y un evento
  municipal atribuido a tres pedanías.

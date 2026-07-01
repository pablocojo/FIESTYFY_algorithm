Vale, ahora centrate en la fase 2 del flujo en el readme. El mayor problema que yo veo es el como lograr analizar y sacar iniformacion organizada de wikipedia de los lugares. creo que la mejor opcion es crear tres procesos o funciones, estas seran (buscar_distritos, Buscar_barrios, Buscar_pedanias, Buscar_nucleo_de_municipio_compuesto), los cuales serviran para analizar las ciudades grandes, pequeñas y municipios compuestos, no obstante quiero que estas sean distintas para los tres lugares. para la cuidad grande quiero que se parta del enlace de wikipedia que está como dato del lugar, una vez dentro se debe buscar los distritos, dentro de ellos los barrios y despues las pedanias, sin embargo esto trae problemas, pues cada ciudad grande se organiza de una forma en wikipedia. con las ciudades pequeñas se parte tambien del enlace a wikipedia y a partir de este se buscan barrios y pedanias. despues, el municipio compuesto debe ser un municipio no fisico, y las subdivisiones, si los habitantes de cada una superan los 20 habitantes, se les considerará pedanías y tambien se debe buscar su nucleo, el cual es la pedania o lugar donde se encuentra el ayuntamiento. En el ultimo caso, si es un pueblo, se deberá pasar directamente al siguiente sin añadir nada al json.

### Regla: 
Todo barrio, distrito y pedanía debe superar los 20 habitantes para ser añadido al json. La **excepción** son las pedanías que constan en las tablas oficiales del INE: si su nombre coincide, tienen `>= 1` habitante, y se valida contra una página de Wikipedia existente, se añaden siempre (saltándose el límite de los 20 habitantes). Si tiene 0 habitantes, se elimina siempre.

### Deduplicación y Orden de Extracción:
En todas las opciones descritas abajo, el algoritmo **siempre empieza extrayendo las pedanías** (basadas estrictamente en el padrón del INE). Si un distrito o barrio coincide en nombre o comparte la misma URL de Wikipedia con una pedanía extraída, prevalece siempre la pedanía (orden de prioridad: `Pedanía > Distrito > Barrio`).

### Descripcón de lo que es una pedanía
la pedania es un lugar apartado de un municipio pero igualmente dentro de él legalmente, el cual se le puede encontrar tambien como pueblo (ejemplo cinco villas dentro de puentes viejas) o como urbanizacion. En las páginas de wikipedia se le describirá con alguna de estas formas, si el llm encuentra que se le describe como tal, es considerado pedanía del municipio, sin embargo, si el llm está seguro de que se trata de una localidad perteneciente al municipio y que no es un barrio/distrito, también se aceptará.
## Nombres que pueden significar pedanía
localidad del municipio
pueblo
aldea
caserío
pedanía
lugar del municipio
núcleo de población
núcleo poblacional
entidad singular de población
entidad local menor
entidad menor
EATIM
junta vecinal
parroquia
diputación
Anteiglesia
urbanización
poblado
anejo
agregado
### Descripcion de lo que es un distrito
Un distrito es un espacio el cual se usa en las ciudades grandes para dividirlas y oganizar los distintos barrios (cada distrito suele contener barrios).
## Nombres que pueden significar distrito
distrito
distrito municipal
distrito urbano
distrito administrativo
distrito de la ciudad
demarcación distrital
división distrital
circunscripción municipal
zona administrativa
unidad administrativa urbana

### Definicion de barrio 
Un barrio es una parte integrada físicamente dentro del continuo urbano de una ciudad o núcleo principal.
## Nombres que pueden significar barrio
barrio
barriada
barriada urbana
arrabal
colonia
vecindario
sector urbano
zona urbana
barrio histórico
barrio residencial
barrio tradicional
barrio obrero
barrio periférico
subbarrio
### Diferencia entre barrio y pedania
La diferencia principal es simplemente que el barrio es interno a la ciudad y la pedania es externa(siendo la pedania una especie de pueblo cercano)

### Comparativa para el LLM
Cuando aparezca un lugar, el LLM debería decidir según esta tabla:
| Tipo     | Dentro del continuo urbano | Separado físicamente | Puede contener barrios | Ejemplos                          |
| -------- | -------------------------- | -------------------- | ---------------------- | --------------------------------- |
| Distrito | Sí                         | No                   | Sí                     | Centro (Madrid), Latina           |
| Barrio   | Sí                         | No                   | No                     | Sol, Malasaña, Triana             |
| Pedanía  | No                         | Sí                   | No normalmente         | El Palmar, La Murta, Cinco Villas |

### Definicion de analizar algo como lugar
Lo que significa el analizar algo como un lugar es buscar sus parametros para añadirlo al json como un nuevo barrio, distrito, municipio_compuesto, pedania,...  Esto se debe ejecutar siempre en la pagina de wikipedia del lugar a analizar,por ejemplo: https://es.wikipedia.org/wiki/Madrid  siendo Madrid el objeto a convertir en lugar. el ejemplo de lugares para este cometido es el siguiente:
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
      "nombre": "Sol",
      ...
    }
  ]
}
```


# OPCION 1. EL MUNICIPIO ES UNA CIUDAD_GRANDE
## casos posibles de ciudad grande:
1. ciudad con distritos y barrios dentro con/sin pedanías
2. ciudad con distritos solo y con/sin pedanias
3. ciudad con barrios con/sin pedanias
4. ciudad sola con/sin pedanias
## Problema principal
Cada ciudad en wikipedia se organiza de un modo en cuanto al nombre de sus paginas o su esquema, no obstante todas cumplen uno de los casos mencionados como ciudad grande. 
SOLUCION AL PROBLEMA--> Usar el LLm de lmstudo con mucha fecuencia para validar y hacer preguntas sobre que informacion es la buena. 
## Flujo
1. se buscan las subdivisiones y paginas internas de la ciudad grande(el flujo parte de saber los datos en municipios.json, cargado por main2.py)
2. se pasa lo extraido sobre subdivisiones y paginas al llm y se le pregunta cuales de ellas son posibles distritos, barrios, pedanias o listas de distritos, barrios o pedanias.
3. se descargan las paginas que el llm ha dicho y por cada pagina se da el siguiente flujo (bucle)
4. Flujo cada pagina interna para obtener barrios, distritos y pedanías
    ├─ 4.1. primero se pregunta al llm que contiene la pagina, puede ser:
       ├─ lista de subpaginas, subcategorias o subdivisiones --> 4.1.1
           ├─1. Preguntar al llm cuales subpaginas son posibles distritos, barrios, pedanías o listas, como en la fase 2. 
           ├─2. por cada pagina se pregunta al llm  y se vuelve a ejecutar el 4.1.1 en bucle para el punto 1.
           ├─En este bucle, si en algun momento se encuentra tabla de distritos y/o barrios -->4.1.2 y si se encuentra una pagina directa a posible barrio, distrito o pedanía-->5.1.3
       ├─ tabla de distritos y/o barrios --> 4.1.2
           ├─1. pedir al llm que pase una lista con todos los distritos(si hay) y sus enlaces y/o barrios(si hay) y sus enlaces y diciendo cuales barrios engloba cada distrito para tenerlo en cuanta en el punto siguiente. 
           ├─2. por cada uno se analiza como un lugar con padre_id con/sin abuelo_id. primero se analizan todos los distritos(si hay) y luego todos los barrios(si hay), dejando claro cuál cuelga de cuál
           ├─3. subir los lugares obtenidos a lugares_españa.json 
       ├─ Directamente un posible barrio, distrito o pedanía --> 4.1.3
           ├─1. Preguntar al llm si es un barrio,distrito o pedanía
           ├─2. si no lo es o hay duda-->descartado   si lo es--> se analiza como un lugar, se buscan los parametros y se sube al json.

5. Recorrer todos los nuevos lugares añadidos para validar logica y eliminar repeticiones(tratando solo la ciudad_grande que se estudia actualmente), para esto no se usa el llm, solo se comprueba que no haya repeticiones de lugares en sus nombres o errores, si hay repeticion, uno de los dos se elimina, al azar.

# OPCION 2. EL MUNICIPIO ES UNA CIUDAD_PEQUENA
El flujo es igual al de la ciudad grande, solo que se elimina la busqueda de distritos, tan solo aparecerán posibles barrios y pedanias.
## Regla importante
Si en algun momento se tiene la duda de si un lugar es un barrio o una pedania pero si se sabe que es una de las dos con alta probabilidad, se elige pedania.
## Flujo
1. se buscan las subdivisiones y paginas internas de la ciudad pequena(el flujo parte de saber los datos en municipios.json, cargado por main2.py)
2. se pasa lo extraido sobre subdivisiones y paginas al llm y se le pregunta cuales de ellas son posibles barrios, pedanias o listas de barrios o pedanias.
3. se descargan las paginas que el llm ha dicho y por cada pagina se da el siguiente flujo (bucle)
4. Flujo cada pagina interna para obtener barrios y pedanías
    ├─ 4.1. primero se pregunta al llm qué contiene la pagina, puede ser:
       ├─ lista de subpaginas, subcategorias o subdivisiones --> 4.1.1
           ├─1. Preguntar al llm cuales subpaginas son posibles barrios, pedanías o listas, como en la fase 2. 
           ├─2. por cada pagina se pregunta al llm  y se vuelve a ejecutar el 4.1.1 en bucle para el punto 1.
           ├─En este bucle, si en algun momento se encuentra una pagina directa a posible barrio o pedanía--> 5.
       ├─ Directamente un posible barrio o pedanía --> 4.1.2
           ├─1. Preguntar al llm si es un barrio o pedanía
           ├─2. si no lo es o hay duda -->descartado   si lo es--> se analiza como un lugar, se buscan los parametros y se sube al json.

5. Recorrer todos los nuevos lugares añadidos para validar logica y eliminar repeticiones(tratando solo la ciudad_pequena que se estudia actualmente), para esto no se usa el llm, solo se comprueba que no haya repeticiones de lugares en sus nombres o errores, si hay repeticion, uno de los dos se elimina, al azar.

# OPCION 3. EL MUNICIPIO ES UN MUNICIPIO_COMPUESTO
Este tipo de municipio se trata de un conjunto de localidades, sin haber un padre físico y diferentes hijos también físicos, sino que  es un padre abstracto que no es una localidad como tal (el nombre del municipio es el padre abstracto), y como hijos la una unión entre distintas localidades(hijos).
Ejemplo: el municipio de Puentes Viejas (padre) no es un lugar, es la unión de las pedanías de Cinco villas, Mangiron, entre otras (hijos).
## Reglas importantes
1. Si se ve que existen barrios dentro de uno de los hijos o subdivisiones, esto no se estudiará. 
2. Si como subdivisiones del municipio se muestran una lista de barrios, se deberá  comprobar, pues se puede tratar de los hijos.
## Flujo 
1. se buscan las subdivisiones y paginas internas del municipio_compuesto (el flujo parte de saber los datos en municipios.json, cargado por main2.py)
2. se pasa lo extraido sobre subdivisiones y paginas al llm y se le pregunta cuales de ellas son posibles pedanias o listas de pedanias.
3. se descargan las paginas que el llm ha dicho y por cada pagina se da el siguiente flujo (bucle)
4. Flujo cada pagina interna para obtener pedanías
    ├─ 4.1. primero se pregunta al llm qué contiene la pagina, puede ser:
       ├─ lista de subpaginas, subcategorias o subdivisiones --> 4.1.1
           ├─1. Preguntar al llm cuales subpaginas son posibles pedanías o listas, como en la fase 2. 
           ├─2. por cada pagina se pregunta al llm  y se vuelve a ejecutar el 4.1.1 en bucle para el punto 1.
           ├─En este bucle, si en algun momento se encuentra una pagina directa a posible pedanía--> 5.
       ├─ Directamente una posible pedanía --> 4.1.2
           ├─1. Preguntar al llm si es una pedanía
           ├─2. si no lo es o hay duda -->descartado   si lo es--> se analiza como un lugar, se buscan los parametros y se sube al json.

5. Recorrer todos los nuevos lugares añadidos para validar logica y eliminar repeticiones(tratando solo el municipio_compuesto que se estudia actualmente), para esto no se usa el llm, solo se comprueba que no haya repeticiones de lugares en sus nombres o errores, si hay repeticion, uno de los dos se elimina, al azar.

# OPCION 4. EL MUNICIPIO ES UN PUEBLO
Si el municipio a estudiar es un pueblo, la únicas dos posibilidades son que esté solo o que tenga además pedanias. para comprobarlo, se deben buscar pedanias, si no se encuentran, no se añadirá nada al json. sin embargo, si tiene pedanias, se añaden estas como hijos del pueblo.
## Regla
1. Si se ve que existen barrios dentro de uno de los hijos o subdivisiones, esto no se estudiará. 
## Flujo 
1. se buscan las subdivisiones y paginas internas del pueblo (el flujo parte de saber los datos en municipios.json, cargado por main2.py)
2. se pasa lo extraido sobre subdivisiones y paginas al llm y se le pregunta cuales de ellas son posibles pedanias o listas de pedanias.
3. se descargan las paginas que el llm ha dicho y por cada pagina se da el siguiente flujo (bucle)
4. Flujo cada pagina interna para obtener pedanías
    ├─ 4.1. primero se pregunta al llm qué contiene la pagina, puede ser:
       ├─ lista de subpaginas, subcategorias o subdivisiones --> 4.1.1
           ├─1. Preguntar al llm cuales subpaginas son posibles pedanías o listas, como en la fase 2. 
           ├─2. por cada pagina se pregunta al llm  y se vuelve a ejecutar el 4.1.1 en bucle para el punto 1.
           ├─En este bucle, si en algun momento se encuentra una pagina directa a posible pedanía--> 5.
       ├─ Directamente una posible pedanía --> 4.1.2
           ├─1. Preguntar al llm si es una pedanía
           ├─2. si no lo es o hay duda -->descartado   si lo es--> se analiza como un lugar, se buscan los parametros y se sube al json.

5. Recorrer todos los nuevos lugares añadidos para validar logica y eliminar repeticiones(tratando solo el pueblo que se estudia actualmente), para esto no se usa el llm, solo se comprueba que no haya repeticiones de lugares en sus nombres o errores, si hay repeticion, uno de los dos se elimina, al azar.



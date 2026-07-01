# 🎊 FIESTYFY Algorithm

<p align="center">
  <em>Motor de recolección, estructuración y enriquecimiento de datos para la plataforma definitiva de fiestas locales de España.</em>
</p>

---

## 📖 Visión General

El **Algoritmo FIESTYFY** es el corazón tecnológico detrás de la plataforma Fiestyfy. Su propósito es orquestar la creación de una base de datos exhaustiva, estructurada y libre de errores, que documente todos los lugares de España susceptibles de albergar fiestas propias.

Este proyecto automatiza la recopilación de entidades territoriales, su enriquecimiento mediático y descriptivo, y la posterior extracción inteligente de programas festivos mediante técnicas de **Web Scraping**, **RAG (Retrieval-Augmented Generation)** y el uso de **Modelos de Lenguaje Locales (LLMs)**.

---

## 🎯 Objetivo Principal

Construir un archivo JSON estructurado, validado jerárquicamente y de alta fidelidad que actúe como el **esqueleto central** de toda la plataforma web, garantizando:
- Cobertura total del territorio español (0% omisiones).
- Cero clasificaciones erróneas.
- Alta fidelidad en la información cultural y descriptiva de las festividades.

---

## 🏗 Arquitectura de Datos (Enfoque *INE-First*)

Para garantizar la máxima fiabilidad, el sistema confía como fuente principal y absoluta en los datos oficiales del **Instituto Nacional de Estadística (INE)**:

1. **Base Municipal (`MUNICIPIOS.csv` / `pobmun25.xlsx`)**: Define el padrón y establece los nodos raíz de toda la geografía española.
2. **Entidades Poblacionales (`ENTIDADES.csv` / `nomdef2025.xlsx`)**: Proporciona el 100% de las entidades menores y pedanías oficiales. 

**Rol de Wikipedia**: Se relega a una función secundaria de *enriquecimiento*. Se utiliza para obtener URLs, generar descripciones mediante LLMs y extraer estructuras puramente urbanas (como **distritos** y **barrios**) que no constan en el INE.

---

## 🗂 Estructura Jerárquica y Tipología de Lugares

El algoritmo organiza el territorio en un árbol relacional estricto. (Nota: Se ha eliminado la figura de *municipio compuesto* y *pedanía* como tipos de datos; todo se estructura en base a población y jerarquía).

* **`municipio`**: Nodo raíz estructural (ID INE 11 dígitos). Actúa como contenedor logístico y administrativo. Contiene metadatos generales pero **no** tiene fiestas propias ni el campo `padre_id`.
* **`pueblo` / `ciudad_pequena` / `ciudad_grande`**: Entidades habitadas reales. Poseen fiestas propias y cuelgan directamente de un `municipio` a través del campo `padre_id`. Una de estas entidades en cada municipio se marca siempre con `es_capital: true`.
* **`distrito` / `barrio`**: Subdivisiones de nivel inferior (extraídas de Wikipedia). Sólo cuelgan de entidades urbanas (ciudades grandes o pequeñas). Siempre tienen `es_capital: false`. En el caso de los barrios que cuelgan de distritos, incluyen un `abuelo_id` que apunta a la ciudad principal.

---

## ⚙️ Fases del Algoritmo

El procesamiento se divide en dos fases secuenciales y altamente especializadas:

### 📍 Fase 1: Estructuración Territorial (`Fase1_recogida_datos_wiki`)
Construye el esqueleto relacional y poblacional completo.
* **Paso 1 (`main.py`)**: Inicialización y extracción de los municipios raíz.
* **Paso 2 (`main2.py`)**: Cruce masivo con los datos del INE (`ENTIDADES.csv`) para extraer todas las entidades menores. Posteriormente, un agente LLM extrae descripciones resumidas e identifica distritos y barrios desde Wikipedia.

### 🎊 Fase 2: Extracción y Procesamiento de Fiestas (`Fase2_Extraccion_Fiestas`)
Recorre el esqueleto generado en la Fase 1 para nutrir de contenido festivo a las entidades.
* Utiliza un orquestador asíncrono impulsado por **LLMs locales** y **RAG**.
* Realiza búsquedas inteligentes, procesa webs de ayuntamientos, filtra ruido y estructura en formato JSON las fechas, descripciones y programas de actos de cada festividad.

---

## 🧠 Configuración de Inteligencia Artificial (LM Studio)

El sistema está diseñado para ejecutarse de forma autónoma utilizando modelos de IA open-source alojados localmente mediante **LM Studio**, garantizando privacidad y control de costes.

### Modelos Recomendados
- **LLM Principal**: `qwen2.5-7b-instruct` (o superior). Encargado de tareas complejas de razonamiento: resumir contextos históricos, identificar relaciones territoriales y parsear programas de fiestas.
- **Modelo de Embeddings**: `text-embedding-nomic-embed-text-v1.5`. Utilizado en el sistema RAG de la Fase 2 para vectorizar documentos web y extraer los bloques de texto más relevantes antes del prompt final.

### 🔧 Ajuste de Rendimiento
Para adaptar el algoritmo al hardware disponible (CPU/GPU), se pueden modificar los parámetros de concurrencia y modelos en:
- **Fase 1**: `Algoritmo_fiestas/Fase1_recogida_datos_wiki/config.py` (`LLM_MODEL_NAME`)
- **Fase 2**: `Algoritmo_fiestas/Fase2_Extraccion_Fiestas/config.py` (`LLM_MODEL_NAME`, `EMBEDDING_MODEL_NAME`, `PARALLEL_MUNICIPALITIES`)

> ⚠️ **Importante**: El nombre asignado a las variables en `config.py` debe coincidir exactamente con el identificador del modelo cargado en el servidor local de LM Studio.
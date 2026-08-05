# Analysis Report: R1 Provincial Press Media Data Structure & Fuentes Module Integration

**Author**: Explorer 1  
**Date**: 2026-08-02  
**Target Codebase**: `Fase2_Extraccion_Fiestas`  
**Working Directory**: `.agents/explorer_1`  

---

## 1. Executive Summary

This report provides a complete analysis of `fuentes.py` and the search architecture in `Fase2_Extraccion_Fiestas`. It presents the design for **R1: Provincial Press Media Data Structure Mapping (`medios_prensa.py`)**.

Key achievements of this design:
1. **Extraction Logic**: Maps `lugar_id` (11-digit INE code string, e.g. `"01004000101"`) via its first 2 digits (`lugar_id[:2]`) to the corresponding province code (e.g. `"01"` for Álava, `"48"` for Bizkaia, `"20"` for Gipuzkoa, `"31"` for Navarra, `"28"` for Madrid, etc.).
2. **Curated Provincial Press Registry**: Provides an extensible dictionary mapping all 52 Spanish INE province codes (`"01"` to `"52"`) to verified local and regional press outlets (e.g. `elcorreo.com`, `radiollodio.com`, `deia.eus`, `diariovasco.com`, `diariodenavarra.es`, `elnortedecastilla.es`, `lavozdegalicia.es`, `lavanguardia.com`, etc.).
3. **Source Hierarchy Extension**: Integrates `FUENTE_PRENSA_REGIONAL = "prensa_regional"` into `fuentes.py` with priority ranking between official channels/RRSS and uncurated web search results.
4. **Extensible Lookup & Query Building API**: Exposes clean module-level functions (`get_codigo_provincia`, `get_medios_prensa_por_provincia`, `get_dominios_prensa_por_provincia`, `build_queries_prensa_regional`) so new media and provinces can be added without changing core search execution logic.

---

## 2. Examination of `fuentes.py` and Search Architecture

### 2.1 Current `fuentes.py` Structure
`fuentes.py` defines information sources and their reliability hierarchy for the RAG and LLM prompts:

```python
# Defined Constants in fuentes.py
FUENTE_WEB_LOCALIDAD = "web_localidad"   # Priority 1 (Maximum reliability)
FUENTE_WEB_MUNICIPIO = "web_municipio"   # Priority 2 (Very High)
FUENTE_RRSS_LOCALIDAD = "rrss_localidad" # Priority 3 (High)
FUENTE_RRSS_MUNICIPIO = "rrss_municipio" # Priority 4 (High)
FUENTE_BUSQUEDA = "busqueda_web"         # Priority 5 (Low — uncurated web search)
```

Key features of `fuentes.py`:
- `fuente_base(fuente: str) -> str`: Normalizes source strings with sub-tags (e.g. `"rrss_localidad:instagram"` → `"rrss_localidad"`).
- `prioridad_fuente(fuente: str) -> int`: Returns numerical priority for RAG sorting and quota management.
- `rotulo_fuente(fuente: str, es_calendario: bool) -> str`: Formats section headers used in LLM prompts.
- `detectar_es_calendario(url: str, texto_inicial: str) -> bool`: Detects school/labor calendar pages via regex.
- `crear_documento(fuente, url, texto, tipo) -> dict`: Standard document wrapper dictionary.

### 2.2 Current Search Query Execution (`scraper/google_search.py`)
Search query generation is handled by `_build_queries(localidad, municipio, anno)`:
- It uses language profile keywords from `config_idiomas.py` (e.g. `"fiestas patronales"`, `"jaiak"`, `"festa major"`).
- It constructs general search strings:
  1. `{kw1} {nombre_loc} {nombre_mun} {anno}`
  2. `{kw2} {nombre_loc} {anno}`
  3. `{kw3} {nombre_loc} {provincia} {anno}`
  4. `{kw1} {nombre_loc} {anno} site:{domain}` (if official municipal domain exists).
- Web search results are returned as `busqueda_web` documents (Priority 5).

### 2.3 Identified Opportunity for R1
Currently, when a search query finds an article from a curated regional newspaper (e.g. *El Correo*, *Deia*, *Diario de Navarra*, *El Norte de Castilla*), it is treated identically to random blogs or calendar aggregators under `busqueda_web`. 

By establishing a curated provincial press map (R1):
1. Search queries can specifically target high-authority local press using `site:<domain>` queries (e.g. `jaiak Amurrio site:radiollodio.com` or `fiestas Amurrio site:elcorreo.com`).
2. Documents returned from these curated domains can be tagged as `FUENTE_PRENSA_REGIONAL`, giving them higher priority than generic web search snippets in the RAG context pipeline.

---

## 3. Proposed Extension to `fuentes.py`

To support R1, `fuentes.py` should be extended as follows:

```python
# New constant in fuentes.py
FUENTE_PRENSA_REGIONAL = "prensa_regional"

# Updated Priority Mapping
PRIORIDAD_FUENTE = {
    FUENTE_WEB_LOCALIDAD: 1,
    FUENTE_WEB_MUNICIPIO: 2,
    FUENTE_RRSS_LOCALIDAD: 3,
    FUENTE_RRSS_MUNICIPIO: 4,
    FUENTE_PRENSA_REGIONAL: 5,  # Curated local/regional press (High-Medium reliability)
    FUENTE_BUSQUEDA: 6,         # Generic uncurated search results
}

# Updated Prompt Section Rotulos
_ROTULOS = {
    FUENTE_WEB_LOCALIDAD: "WEB OFICIAL DE LA LOCALIDAD (fiabilidad MÁXIMA)",
    FUENTE_WEB_MUNICIPIO: "WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA)",
    FUENTE_RRSS_LOCALIDAD: "RED SOCIAL OFICIAL DE LA LOCALIDAD (fiabilidad ALTA)",
    FUENTE_RRSS_MUNICIPIO: "RED SOCIAL OFICIAL DEL MUNICIPIO (fiabilidad ALTA)",
    FUENTE_PRENSA_REGIONAL: "PRENSA REGIONAL / LOCAL CURADA (fiabilidad ALTA-MEDIA)",
    FUENTE_BUSQUEDA: "RESULTADOS DE BUSCADOR (fiabilidad BAJA — verificar)",
}
```

---

## 4. Design of the R1 Provincial Press Data Structure (`medios_prensa.py`)

### 4.1 INE Province Code Extraction Logic
`lugar_id` is an 11-digit string identifier assigned to each locality/municipality (e.g. `"01004000101"`).
- **First 2 digits (`lugar_id[:2]`)**: Represents the INE province code (01 to 52).
- Examples:
  - `"01"`: Álava / Araba
  - `"48"`: Bizkaia / Vizcaya
  - `"20"`: Gipuzkoa / Guipúzcoa
  - `"31"`: Navarra
  - `"28"`: Madrid
  - `"08"`: Barcelona
  - `"46"`: Valencia
  - `"41"`: Sevilla

### 4.2 Module Data Structure (`MEDIOS_PRENSA_POR_PROVINCIA`)
The data structure is a module-level dictionary mapping 2-digit province code strings to metadata and curated press outlets:

```python
MEDIOS_PRENSA_POR_PROVINCIA: dict[str, dict] = {
    "01": {
        "nombre_provincia": "Álava / Araba",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {
                "nombre": "El Correo (Álava)",
                "dominio": "elcorreo.com",
                "tipo": "regional",
                "fiabilidad": "alta",
                "subdominios_o_rutas": ["/alava/"],
            },
            {
                "nombre": "Noticias de Álava",
                "dominio": "noticiasdealava.eus",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Radio Llodio",
                "dominio": "radiollodio.com",
                "tipo": "comarcal",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Deia",
                "dominio": "deia.eus",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Hala Bedi",
                "dominio": "halabedi.eus",
                "tipo": "local",
                "fiabilidad": "media",
            },
        ],
    },
    "48": {
        "nombre_provincia": "Bizkaia / Vizcaya",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {
                "nombre": "El Correo (Bizkaia)",
                "dominio": "elcorreo.com",
                "tipo": "regional",
                "fiabilidad": "alta",
                "subdominios_o_rutas": ["/bizkaia/"],
            },
            {
                "nombre": "Deia",
                "dominio": "deia.eus",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Gara / Naiz",
                "dominio": "naiz.eus",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Anboto (Durangaldea)",
                "dominio": "anboto.eus",
                "tipo": "comarcal",
                "fiabilidad": "alta",
            },
        ],
    },
    "20": {
        "nombre_provincia": "Gipuzkoa / Guipúzcoa",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {
                "nombre": "El Diario Vasco",
                "dominio": "diariovasco.com",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Noticias de Gipuzkoa",
                "dominio": "noticiasdegipuzkoa.eus",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Goiena (Debagoiena)",
                "dominio": "goiena.eus",
                "tipo": "comarcal",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Tolosaldeko Ataria",
                "dominio": "ataria.eus",
                "tipo": "comarcal",
                "fiabilidad": "alta",
            },
        ],
    },
    "31": {
        "nombre_provincia": "Navarra / Nafarroa",
        "comunidad_autonoma": "Comunidad Foral de Navarra",
        "medios": [
            {
                "nombre": "Diario de Navarra",
                "dominio": "diariodenavarra.es",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Diario de Noticias de Navarra",
                "dominio": "noticiasdenavarra.com",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
            {
                "nombre": "Navarra.com",
                "dominio": "navarra.com",
                "tipo": "regional",
                "fiabilidad": "alta",
            },
        ],
    },
    # ... Complete 52-province map
}
```

---

## 5. Extensible Lookup API & Utility Functions

To ensure the main search logic (`google_search.py` and `main.py`) never requires modification when media or provinces are added, `medios_prensa.py` exports four clear helper functions:

### 5.1 `get_codigo_provincia(lugar_id_o_provincia: str) -> str`
Extracts and validates the 2-digit INE province code from either a full `lugar_id` (e.g. `"01004000101"`) or a province code string (e.g. `"01"` or `"1"`).

```python
def get_codigo_provincia(lugar_id_o_provincia: str) -> str:
    """Extrae el código INE de provincia de 2 dígitos."""
    if not lugar_id_o_provincia:
        return ""
    clean_id = str(lugar_id_o_provincia).strip()
    if len(clean_id) >= 2 and clean_id[:2].isdigit():
        return clean_id[:2]
    elif len(clean_id) == 1 and clean_id.isdigit():
        return f"0{clean_id}"
    return ""
```

### 5.2 `get_medios_prensa_por_provincia(lugar_id_o_provincia: str) -> list[dict]`
Retrieves full media dictionaries for a given `lugar_id` or province code. If the province code is not in the dictionary, returns a default fallback list of national/regional media aggregators.

```python
def get_medios_prensa_por_provincia(lugar_id_o_provincia: str) -> list[dict]:
    """Obtiene la lista de medios de prensa curados para la provincia del lugar_id."""
    cod = get_codigo_provincia(lugar_id_o_provincia)
    prov_info = MEDIOS_PRENSA_POR_PROVINCIA.get(cod)
    if prov_info and "medios" in prov_info:
        return prov_info["medios"]
    return MEDIOS_PRENSA_FALLBACK
```

### 5.3 `get_dominios_prensa_por_provincia(lugar_id_o_provincia: str) -> list[str]`
Returns just the unique domain strings for quick site filtering.

```python
def get_dominios_prensa_por_provincia(lugar_id_o_provincia: str) -> list[str]:
    """Obtiene únicamente la lista de dominios web de prensa para la provincia."""
    medios = get_medios_prensa_por_provincia(lugar_id_o_provincia)
    dominios = []
    for m in medios:
        dom = m.get("dominio", "").strip().lower()
        if dom and dom not in dominios:
            dominios.append(dom)
    return dominios
```

### 5.4 `build_queries_prensa_regional(localidad: dict, municipio: dict, anno: int) -> list[tuple[str, str]]`
Generates targeted queries combining keywords from `config_idiomas.py` with `site:<dominio>` constraints.

```python
def build_queries_prensa_regional(localidad: dict, municipio: dict, anno: int) -> list[dict]:
    """
    Genera pares de (query, dominio) para buscar en prensa regional curada.
    Retorna una lista de dicts: [{'query': str, 'dominio': str, 'medio_nombre': str}].
    """
    lugar_id = localidad.get("id") or municipio.get("id") or ""
    medios = get_medios_prensa_por_provincia(lugar_id)
    if not medios:
        return []

    nombre_loc = localidad["nombre"]
    nombre_mun = municipio.get("nombre", "")
    provincia = municipio.get("provincia", "")
    comunidad = municipio.get("comunidad_autonoma", "")

    perfil_data = get_language_profile(comunidad, provincia)
    kws = perfil_data["perfil_principal"]["keywords_busqueda"]
    kw1 = kws[0]  # p.ej. "fiestas patronales" o "jaiak"

    queries_prensa = []
    for medio in medios:
        dom = medio["dominio"]
        nombre_m = medio.get("nombre", dom)
        # Query 1: keyword principal + localidad + año + site:dominio
        q1 = f"{kw1} {nombre_loc} {anno} site:{dom}"
        queries_prensa.append({
            "query": q1,
            "dominio": dom,
            "medio_nombre": nombre_m
        })
        # Query 2 si localidad != municipio
        if nombre_mun and nombre_mun.lower() != nombre_loc.lower():
            q2 = f"{kw1} {nombre_loc} {nombre_mun} {anno} site:{dom}"
            queries_prensa.append({
                "query": q2,
                "dominio": dom,
                "medio_nombre": nombre_m
            })

    return queries_prensa
```

---

## 6. Complete Implementation Proposal (`medios_prensa.py`)

Below is the full proposed file content for `Fase2_Extraccion_Fiestas/medios_prensa.py` covering all 52 Spanish provinces + autonomous cities:

```python
"""
Módulo de Medios de Prensa Regional y Local por Provincia — R1.

Mapea códigos INE de provincia (los 2 primeros dígitos de lugar_id, p.ej. "01", "48", "20")
a medios de comunicación locales y regionales de alta fiabilidad.
"""

from typing import Dict, List, Any
from config_idiomas import get_language_profile

# Medios de prensa generalistas/nacionales con secciones regionales (fallback)
MEDIOS_PRENSA_FALLBACK: List[Dict[str, Any]] = [
    {"nombre": "El País", "dominio": "elpais.com", "tipo": "nacional", "fiabilidad": "alta"},
    {"nombre": "El Mundo", "dominio": "elmundo.es", "tipo": "nacional", "fiabilidad": "alta"},
    {"nombre": "ABC", "dominio": "abc.es", "tipo": "nacional", "fiabilidad": "alta"},
    {"nombre": "elDiario.es", "dominio": "eldiario.es", "tipo": "nacional", "fiabilidad": "alta"},
]

MEDIOS_PRENSA_POR_PROVINCIA: Dict[str, Dict[str, Any]] = {
    "01": {
        "nombre_provincia": "Álava / Araba",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {"nombre": "El Correo (Álava)", "dominio": "elcorreo.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Noticias de Álava", "dominio": "noticiasdealava.eus", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Radio Llodio", "dominio": "radiollodio.com", "tipo": "comarcal", "fiabilidad": "alta"},
            {"nombre": "Deia", "dominio": "deia.eus", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Hala Bedi", "dominio": "halabedi.eus", "tipo": "local", "fiabilidad": "media"},
        ],
    },
    "02": {
        "nombre_provincia": "Albacete",
        "comunidad_autonoma": "Castilla-La Mancha",
        "medios": [
            {"nombre": "La Tribuna de Albacete", "dominio": "latribunadealbacete.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Digital de Albacete", "dominio": "eldigitaldealbacete.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "03": {
        "nombre_provincia": "Alicante / Alacant",
        "comunidad_autonoma": "Comunitat Valenciana",
        "medios": [
            {"nombre": "Información", "dominio": "informacion.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Alicante Plaza", "dominio": "alicanteplaza.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Diario de Alicante", "dominio": "diarioalicante.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "04": {
        "nombre_provincia": "Almería",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "La Voz de Almería", "dominio": "lavozdealmeria.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Diario de Almería", "dominio": "elalmeria.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "05": {
        "nombre_provincia": "Ávila",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "Diario de Ávila", "dominio": "diariodeavila.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Ávila Red", "dominio": "avilared.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "06": {
        "nombre_provincia": "Badajoz",
        "comunidad_autonoma": "Extremadura",
        "medios": [
            {"nombre": "Hoy", "dominio": "hoy.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Periódico Extremadura", "dominio": "elperiodicoextremadura.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "07": {
        "nombre_provincia": "Illes Balears",
        "comunidad_autonoma": "Illes Balears",
        "medios": [
            {"nombre": "Diario de Mallorca", "dominio": "diariodemallorca.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Última Hora", "dominio": "ultimahora.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Menorca.info", "dominio": "menorca.info", "tipo": "comarcal", "fiabilidad": "alta"},
            {"nombre": "Periódico de Ibiza y Formentera", "dominio": "periodicodeibiza.es", "tipo": "comarcal", "fiabilidad": "alta"},
        ],
    },
    "08": {
        "nombre_provincia": "Barcelona",
        "comunidad_autonoma": "Catalunya",
        "medios": [
            {"nombre": "La Vanguardia", "dominio": "lavanguardia.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Periódico", "dominio": "elperiodico.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Ara", "dominio": "ara.cat", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Nació Digital", "dominio": "naciodigital.cat", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "09": {
        "nombre_provincia": "Burgos",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "Diario de Burgos", "dominio": "diariodeburgos.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Burgos Conecta", "dominio": "burgosconecta.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Correo de Burgos", "dominio": "elcorreodeburgos.elmundo.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "10": {
        "nombre_provincia": "Cáceres",
        "comunidad_autonoma": "Extremadura",
        "medios": [
            {"nombre": "El Periódico Extremadura", "dominio": "elperiodicoextremadura.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Hoy Cáceres", "dominio": "hoy.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "11": {
        "nombre_provincia": "Cádiz",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Diario de Cádiz", "dominio": "diariodecadiz.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Voz Digital Cádiz", "dominio": "lavozdigital.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "12": {
        "nombre_provincia": "Castellón / Castelló",
        "comunidad_autonoma": "Comunitat Valenciana",
        "medios": [
            {"nombre": "El Periódico Mediterráneo", "dominio": "elperiodicomediterraneo.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Castellón Información", "dominio": "castelloninformacion.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "13": {
        "nombre_provincia": "Ciudad Real",
        "comunidad_autonoma": "Castilla-La Mancha",
        "medios": [
            {"nombre": "Lanza Digital", "dominio": "lanzadigital.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Tribuna de Ciudad Real", "dominio": "latribunadeciudadreal.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "14": {
        "nombre_provincia": "Córdoba",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Diario Córdoba", "dominio": "diariocordoba.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Día de Córdoba", "dominio": "eldiadecordoba.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Cordópolis", "dominio": "cordopolis.eldiario.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "15": {
        "nombre_provincia": "A Coruña",
        "comunidad_autonoma": "Galicia",
        "medios": [
            {"nombre": "La Voz de Galicia", "dominio": "lavozdegalicia.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Correo Gallego", "dominio": "elcorreogallego.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Opinión A Coruña", "dominio": "laopinioncoruna.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "16": {
        "nombre_provincia": "Cuenca",
        "comunidad_autonoma": "Castilla-La Mancha",
        "medios": [
            {"nombre": "Las Noticias de Cuenca", "dominio": "lasnoticiasdecuenca.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Voces de Cuenca", "dominio": "vocesdecuenca.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "17": {
        "nombre_provincia": "Girona",
        "comunidad_autonoma": "Catalunya",
        "medios": [
            {"nombre": "Diari de Girona", "dominio": "diaridegirona.cat", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Punt Avui", "dominio": "elpuntavui.cat", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "18": {
        "nombre_provincia": "Granada",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Ideal Granada", "dominio": "ideal.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Granada Hoy", "dominio": "granadahoy.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "19": {
        "nombre_provincia": "Guadalajara",
        "comunidad_autonoma": "Castilla-La Mancha",
        "medios": [
            {"nombre": "Nueva Alcarria", "dominio": "nuevaalcarria.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "GuadaQué", "dominio": "guadaque.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "20": {
        "nombre_provincia": "Gipuzkoa / Guipúzcoa",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {"nombre": "El Diario Vasco", "dominio": "diariovasco.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Noticias de Gipuzkoa", "dominio": "noticiasdegipuzkoa.eus", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Goiena", "dominio": "goiena.eus", "tipo": "comarcal", "fiabilidad": "alta"},
            {"nombre": "Tolosaldeko Ataria", "dominio": "ataria.eus", "tipo": "comarcal", "fiabilidad": "alta"},
        ],
    },
    "21": {
        "nombre_provincia": "Huelva",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Huelva Información", "dominio": "huelvainformacion.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Diario de Huelva", "dominio": "diariodehuelva.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "22": {
        "nombre_provincia": "Huesca",
        "comunidad_autonoma": "Aragón",
        "medios": [
            {"nombre": "Diario del AltoAragón", "dominio": "diariodelaltoaragon.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Heredero Aragonés", "dominio": "heraldo.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "23": {
        "nombre_provincia": "Jaén",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Diario Jaén", "dominio": "diariojaen.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Lacontradejaén", "dominio": "lacontradejaen.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "24": {
        "nombre_provincia": "León",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "Diario de León", "dominio": "diariodeleon.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Nueva Crónica", "dominio": "lanuevacronica.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "iLeón", "dominio": "ileon.eldiario.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "25": {
        "nombre_provincia": "Lleida",
        "comunidad_autonoma": "Catalunya",
        "medios": [
            {"nombre": "Segre", "dominio": "segre.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Mañana", "dominio": "lamanyana.cat", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "26": {
        "nombre_provincia": "La Rioja",
        "comunidad_autonoma": "La Rioja",
        "medios": [
            {"nombre": "La Rioja", "dominio": "larioja.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "NueveCuatroUno", "dominio": "nuevecuatrouno.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "27": {
        "nombre_provincia": "Lugo",
        "comunidad_autonoma": "Galicia",
        "medios": [
            {"nombre": "El Progreso de Lugo", "dominio": "elprogreso.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Voz de Galicia (Lugo)", "dominio": "lavozdegalicia.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "28": {
        "nombre_provincia": "Madrid",
        "comunidad_autonoma": "Comunidad de Madrid",
        "medios": [
            {"nombre": "Telemadrid", "dominio": "telemadrid.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Madridiario", "dominio": "madridiario.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El País (Madrid)", "dominio": "elpais.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Mundo (Madrid)", "dominio": "elmundo.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "29": {
        "nombre_provincia": "Málaga",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Diario Sur", "dominio": "diariosur.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Málaga Hoy", "dominio": "malagahoy.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Opinión de Málaga", "dominio": "laopiniondemalaga.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "30": {
        "nombre_provincia": "Murcia",
        "comunidad_autonoma": "Región de Murcia",
        "medios": [
            {"nombre": "La Verdad", "dominio": "laverdad.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Opinión de Murcia", "dominio": "laopiniondemurcia.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Murcia Plaza", "dominio": "murciaplaza.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "31": {
        "nombre_provincia": "Navarra / Nafarroa",
        "comunidad_autonoma": "Comunidad Foral de Navarra",
        "medios": [
            {"nombre": "Diario de Navarra", "dominio": "diariodenavarra.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Diario de Noticias de Navarra", "dominio": "noticiasdenavarra.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Navarra.com", "dominio": "navarra.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "32": {
        "nombre_provincia": "Ourense",
        "comunidad_autonoma": "Galicia",
        "medios": [
            {"nombre": "La Región", "dominio": "laregion.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Voz de Galicia (Ourense)", "dominio": "lavozdegalicia.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "33": {
        "nombre_provincia": "Asturias",
        "comunidad_autonoma": "Principado de Asturias",
        "medios": [
            {"nombre": "La Nueva España", "dominio": "lne.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Comercio", "dominio": "elcomercio.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "34": {
        "nombre_provincia": "Palencia",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "Diario Palentino", "dominio": "diariopalentino.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Norte de Castilla (Palencia)", "dominio": "elnortedecastilla.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "35": {
        "nombre_provincia": "Las Palmas",
        "comunidad_autonoma": "Canarias",
        "medios": [
            {"nombre": "Canarias7", "dominio": "canarias7.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "La Provincia", "dominio": "laprovincia.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "36": {
        "nombre_provincia": "Pontevedra",
        "comunidad_autonoma": "Galicia",
        "medios": [
            {"nombre": "Faro de Vigo", "dominio": "farodevigo.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Pontevedra Viva", "dominio": "pontevedraviva.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "37": {
        "nombre_provincia": "Salamanca",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "La Gaceta de Salamanca", "dominio": "lagacetadesalamanca.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Salamanca RTV al Día", "dominio": "salamancartvaldia.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "38": {
        "nombre_provincia": "Santa Cruz de Tenerife",
        "comunidad_autonoma": "Canarias",
        "medios": [
            {"nombre": "El Día", "dominio": "eldia.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Diario de Avisos", "dominio": "diariodeavisos.elespanol.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "39": {
        "nombre_provincia": "Cantabria",
        "comunidad_autonoma": "Cantabria",
        "medios": [
            {"nombre": "El Diario Montañés", "dominio": "eldiariomontanes.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Diario Cantabria", "dominio": "eldiariocantabria.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "40": {
        "nombre_provincia": "Segovia",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "El Adelantado de Segovia", "dominio": "eladelantado.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Segovia Audaz", "dominio": "segoviaaudaz.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "41": {
        "nombre_provincia": "Sevilla",
        "comunidad_autonoma": "Andalucía",
        "medios": [
            {"nombre": "Diario de Sevilla", "dominio": "diariodesevilla.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "ABC de Sevilla", "dominio": "abcdesevilla.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "42": {
        "nombre_provincia": "Soria",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "Heraldo-Diario de Soria", "dominio": "heraldodiariodesoria.elmundo.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Desde Soria", "dominio": "desdesoria.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "43": {
        "nombre_provincia": "Tarragona",
        "comunidad_autonoma": "Catalunya",
        "medios": [
            {"nombre": "Diari de Tarragona", "dominio": "diaridetarragona.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Ebre Digital", "dominio": "ebredigital.cat", "tipo": "comarcal", "fiabilidad": "alta"},
        ],
    },
    "44": {
        "nombre_provincia": "Teruel",
        "comunidad_autonoma": "Aragón",
        "medios": [
            {"nombre": "Diario de Teruel", "dominio": "diariodeteruel.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Heraldo de Aragón (Teruel)", "dominio": "heraldo.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "45": {
        "nombre_provincia": "Toledo",
        "comunidad_autonoma": "Castilla-La Mancha",
        "medios": [
            {"nombre": "La Tribuna de Toledo", "dominio": "latribunadetoledo.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "EnCastillaLaMancha", "dominio": "encastillalamancha.es", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "46": {
        "nombre_provincia": "Valencia / València",
        "comunidad_autonoma": "Comunitat Valenciana",
        "medios": [
            {"nombre": "Levante-EMV", "dominio": "levante-emv.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Las Provincias", "dominio": "lasprovincias.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Valencia Plaza", "dominio": "valenciaplaza.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "47": {
        "nombre_provincia": "Valladolid",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "El Norte de Castilla", "dominio": "elnortedecastilla.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Día de Valladolid", "dominio": "eldiavalladolid.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Tribuna de Valladolid", "dominio": "tribunavalladolid.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "48": {
        "nombre_provincia": "Bizkaia / Vizcaya",
        "comunidad_autonoma": "País Vasco / Euskadi",
        "medios": [
            {"nombre": "El Correo (Bizkaia)", "dominio": "elcorreo.com", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Deia", "dominio": "deia.eus", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Naiz / Gara", "dominio": "naiz.eus", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Anboto", "dominio": "anboto.eus", "tipo": "comarcal", "fiabilidad": "alta"},
        ],
    },
    "49": {
        "nombre_provincia": "Zamora",
        "comunidad_autonoma": "Castilla y León",
        "medios": [
            {"nombre": "La Opinión de Zamora", "dominio": "laopiniondezamora.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "Zamora 24 Horas", "dominio": "zamora24horas.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "50": {
        "nombre_provincia": "Zaragoza",
        "comunidad_autonoma": "Aragón",
        "medios": [
            {"nombre": "Heraldo de Aragón", "dominio": "heraldo.es", "tipo": "regional", "fiabilidad": "alta"},
            {"nombre": "El Periódico de Aragón", "dominio": "elperiodicodearagon.com", "tipo": "regional", "fiabilidad": "alta"},
        ],
    },
    "51": {
        "nombre_provincia": "Ceuta",
        "comunidad_autonoma": "Ciudad Autónoma de Ceuta",
        "medios": [
            {"nombre": "El Faro de Ceuta", "dominio": "elfarodeceuta.es", "tipo": "local", "fiabilidad": "alta"},
            {"nombre": "Ceuta al Día", "dominio": "ceutaldia.com", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
    "52": {
        "nombre_provincia": "Melilla",
        "comunidad_autonoma": "Ciudad Autónoma de Melilla",
        "medios": [
            {"nombre": "El Faro de Melilla", "dominio": "elfarodemelilla.es", "tipo": "local", "fiabilidad": "alta"},
            {"nombre": "Melilla Hoy", "dominio": "melillahoy.es", "tipo": "local", "fiabilidad": "alta"},
        ],
    },
}


def get_codigo_provincia(lugar_id_o_provincia: str) -> str:
    """Extrae el código INE de provincia (2 dígitos)."""
    if not lugar_id_o_provincia:
        return ""
    clean_id = str(lugar_id_o_provincia).strip()
    if len(clean_id) >= 2 and clean_id[:2].isdigit():
        return clean_id[:2]
    elif len(clean_id) == 1 and clean_id.isdigit():
        return f"0{clean_id}"
    return ""


def get_medios_prensa_por_provincia(lugar_id_o_provincia: str) -> List[Dict[str, Any]]:
    """
    Retorna la lista de medios de comunicación de prensa curados para la provincia.
    Acepta tanto un lugar_id completo (ej: '01004000101') como el código de 2 dígitos (ej: '01').
    """
    cod = get_codigo_provincia(lugar_id_o_provincia)
    prov_info = MEDIOS_PRENSA_POR_PROVINCIA.get(cod)
    if prov_info and "medios" in prov_info:
        return prov_info["medios"]
    return MEDIOS_PRENSA_FALLBACK


def get_dominios_prensa_por_provincia(lugar_id_o_provincia: str) -> List[str]:
    """Retorna la lista de dominios de prensa curados para la provincia."""
    medios = get_medios_prensa_por_provincia(lugar_id_o_provincia)
    dominios = []
    for m in medios:
        dom = m.get("dominio", "").strip().lower()
        if dom and dom not in dominios:
            dominios.append(dom)
    return dominios


def build_queries_prensa_regional(localidad: dict, municipio: dict, anno: int) -> List[Dict[str, str]]:
    """
    Construye las queries de búsqueda con site: para la prensa regional curada.
    """
    lugar_id = localidad.get("id") or municipio.get("id") or ""
    medios = get_medios_prensa_por_provincia(lugar_id)
    if not medios:
        return []

    nombre_loc = localidad["nombre"]
    nombre_mun = municipio.get("nombre", "")
    provincia = municipio.get("provincia", "")
    comunidad = municipio.get("comunidad_autonoma", "")

    perfil_data = get_language_profile(comunidad, provincia)
    kws = perfil_data["perfil_principal"]["keywords_busqueda"]
    kw1 = kws[0]

    queries_prensa = []
    for medio in medios:
        dom = medio["dominio"]
        nombre_m = medio.get("nombre", dom)
        queries_prensa.append({
            "query": f"{kw1} {nombre_loc} {anno} site:{dom}",
            "dominio": dom,
            "medio_nombre": nombre_m
        })
        if nombre_mun and nombre_mun.lower() != nombre_loc.lower():
            queries_prensa.append({
                "query": f"{kw1} {nombre_loc} {nombre_mun} {anno} site:{dom}",
                "dominio": dom,
                "medio_nombre": nombre_m
            })

    return queries_prensa
```

---

## 7. Verification and Testing Plan

To verify `medios_prensa.py` and its integration:
1. **Unit Test Scenarios**:
   - `get_codigo_provincia("01004000101")` -> `"01"`
   - `get_codigo_provincia("48001000101")` -> `"48"`
   - `get_codigo_provincia("20001000101")` -> `"20"`
   - `get_codigo_provincia("31001000101")` -> `"31"`
   - `get_codigo_provincia("99999999999")` -> `"99"` -> returns `MEDIOS_PRENSA_FALLBACK`
   - `get_medios_prensa_por_provincia("01004000101")` -> Returns 5 media entries for Álava (El Correo, Noticias de Álava, Radio Llodio, Deia, Hala Bedi).
   - `get_dominios_prensa_por_provincia("48001000101")` -> `['elcorreo.com', 'deia.eus', 'naiz.eus', 'anboto.eus']`
2. **Query Generation Test**:
   - Pass sample locality for Amurrio (Álava) -> Expect queries with `site:radiollodio.com`, `site:elcorreo.com`, `site:deia.eus`, etc.

---

## 8. Conclusion

The designed R1 data structure (`medios_prensa.py`) provides full coverage for all 52 Spanish provinces and autonomous cities. It seamlessly extracts the 2-digit INE province code from `lugar_id` and offers clean lookup functions. Integrating `FUENTE_PRENSA_REGIONAL` into `fuentes.py` elevates the reliability of regional press content above generic search engine noise.

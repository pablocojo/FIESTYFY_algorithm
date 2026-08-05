# Anális técnico: Framework de Pruebas y Construcción de Test Cases para Medios Locales y Extensibilidad de Provincias (Fase 2)

**Autor**: Explorer 3  
**Fecha**: 2026-08-02  
**Target Codebase**: `Fase2_Extraccion_Fiestas`  
**Directorio de trabajo**: `c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/.agents/explorer_3`

---

## 1. Descubrimiento del Entorno de Ejecución y Framework de Pruebas

### 1.1 Entorno de Ejecución y Herramientas de Test
- **Test Runner & Framework**: `pytest` versión **9.1.1** bajo entorno Python 3.11 / 3.12 (Windows 10 / WSL).
- **Comando de ejecución estándar**: `pytest tests_fase2` desde la raíz de `Fase2_Extraccion_Fiestas`.
- **Configuración (`conftest.py`)**: Ubicado en `Fase2_Extraccion_Fiestas/tests_fase2/conftest.py`.
  - Añade la carpeta raíz `Fase2_Extraccion_Fiestas` al `sys.path` (`sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`).
  - Esto permite importar directamente `config`, `config_idiomas`, `fuentes`, `main`, `state_manager`, `scraper`, y `llm_processor` dentro de cualquier test.

### 1.2 Catálogo Actual de Pruebas (143 Tests Recopilados)
El directorio `tests_fase2` alberga **143 tests unitarios e integrados** distribuidos en 11 módulos principales:

| Módulo de Test | Propósito y Cobertura Principales |
|---|---|
| `test_festival_filter.py` | Reglas de filtrado adaptativo (`festival_filter.py`), eventos de 1 día vs multi-día, verbenas vs procesiones, eventos privados de discotecas, saneado de programas. |
| `test_filtro_calendario.py` | Discriminación de festivos laborales/escolares vs fiestas patronales reales. |
| `test_fuentes_chunking.py` | Prioridades de fuentes (`fuentes.py`), autodetector de calendarios, troceado RAG por frases, cuotas de contexto y etiquetado de fiabilidad. |
| `test_lectura_perfiles.py` | Clustering de texto de redes sociales, extracción multiidioma de fechas (ES, EU, CA, GL) e imágenes de capturas. |
| `test_patron_finder.py` | Extracción de patrón santo (`patron_finder.py`), santoral estático, resolución de fechas e inyección de fiesta estimada. |
| `test_social_apps.py` | Controlador de apps nativas de redes sociales (`social_apps_runner.py`), emparejamiento de handles, fechas relativas/absolutas y caché con TTL. |
| `test_social_content.py` | Carga de documentos de redes sociales desde caché JSON para municipios y pedanías. |
| `test_social_finder.py` | Descubrimiento y normalización de perfiles oficiales de RRSS en sitios web de ayuntamientos (`social_finder.py`). |
| `test_sync_redes.py` | Sincronización e idempotencia de perfiles en `lugares_espana.json` vía `sync_redes_a_lugares.py`. |
| `test_validar_fiestas.py` | Test del pipeline completo de validación e intercalado de fechas invertidas. |
| `test_vision_analyzer.py` | Prefiltrado VLM de carteles, deduplicación por imagen e integración con LM Studio. |

Además, existe un script aislado `test_traduccion.py` en la raíz de `Fase2_Extraccion_Fiestas` para verificar el pipeline de traducción FastText + Apertium / Opus-MT.

### 1.3 Dependencias de Testing
- **Librerías estándar y de terceros**: `pytest`, `asyncio` (`asyncio.run`), `unittest.mock` (`monkeypatch`, `MagicMock`, `AsyncMock`), `tmp_path` fixture.
- **Otras dependencias del pipeline**: `aiohttp`, `bs4` (BeautifulSoup), `PIL` (Pillow), `fasttext` (`lid.176.ftz`).

---

## 2. Análisis del Estado Actual de Generación de Queries y Medios Locales

### 2.1 Mecánica Actual en `scraper/google_search.py`
En `google_search.py`, la función `_build_queries(localidad, municipio, anno)` construye 3 queries generales basadas en palabras clave idiomáticas (`config_idiomas.py`) más queries con restricción de dominio si la localidad o municipio poseen sitio web oficial:

```python
queries = [
    f"{kw1} {nombre_loc} {nombre_mun} {anno}",
    f"{kw2} {nombre_loc} {anno}",
    f"{kw3} {nombre_loc} {provincia} {anno}",
]
```

### 2.2 Limitación Detectada
Actualmente **no existe una asociación directa entre el prefijo INE de la provincia (ej. `01` para Álava, `48` para Bizkaia) o el nombre de la provincia y sus medios de comunicación locales** (`radiollodio.com`, `elcorreo.com`, `deia.eus`, etc.).

---

## 3. Propuesta de Arquitectura: Mapeo de Medios Locales por Provincia y Logging de Queries

Para permitir que localidades como **Retes de Tudela** (Álava, prefijo INE `01`) o municipios de **Bizkaia** (prefijo INE `48`) consulten periódicos y radios locales, se propone diseñar un módulo o diccionario de configuración `PROVINCE_MEDIA_MAP` y extender la generación de queries con su respectivo audit log.

### 3.1 Estructura del Mapa de Medios por Provincia (`config_medios.py`)
```python
PROVINCE_MEDIA_MAP = {
    "01": {
        "provincia_norm": "alava",
        "nombres": ["araba", "álava", "araba/álava"],
        "medios": [
            {"dominio": "radiollodio.com", "nombre": "Radio Llodio"},
            {"dominio": "elcorreo.com", "nombre": "El Correo Álava"},
            {"dominio": "noticiasdealava.eus", "nombre": "Noticias de Álava"},
        ]
    },
    "48": {
        "provincia_norm": "bizkaia",
        "nombres": ["bizkaia", "vizcaya"],
        "medios": [
            {"dominio": "deia.eus", "nombre": "Deia"},
            {"dominio": "elcorreo.com", "nombre": "El Correo Bizkaia"},
            {"dominio": "durangon.com", "nombre": "Durangon"},
        ]
    }
}
```

### 3.2 Extracción del Prefijo INE de Provincia y Resolución
Dado un objeto `localidad` o `municipio`, el id tiene el formato estándar del INE:
- `"01004000501"` → Prefijo provincial = `id[:2]` = `"01"` (Álava).
- `"48027000101"` → Prefijo provincial = `id[:2]` = `"48"` (Bizkaia).

Si el `id` no contiene el código INE (ej. IDs alfanuméricos), la resolución busca por el campo `provincia` normalizado (minúsculas, sin acentos ni espacios).

### 3.3 Extensión de `_build_queries` con Logging
```python
def get_province_media_domains(localidad: dict, municipio: dict) -> list[str]:
    # 1. Obtener código por ID
    code = (localidad.get("id") or municipio.get("id") or "")[:2]
    if code in PROVINCE_MEDIA_MAP:
        return [m["dominio"] for m in PROVINCE_MEDIA_MAP[code]["medios"]]
    
    # 2. Fallback por nombre de provincia
    prov_name = (municipio.get("provincia") or localidad.get("provincia") or "").lower()
    for entry in PROVINCE_MEDIA_MAP.values():
        if any(alias in prov_name for alias in entry["nombres"]):
            return [m["dominio"] for m in entry["medios"]]
            
    # 3. Sin mapeo específico (fallback seguro)
    return []

def _build_queries(localidad: dict, municipio: dict, anno: int) -> list[str]:
    # ... (queries base) ...
    media_domains = get_province_media_domains(localidad, municipio)
    if media_domains:
        logger.info(f"  [MEDIA_SEARCH] Registrando queries de medios locales para provincia ({localidad['nombre']}): {media_domains}")
        for domain in media_domains:
            queries.append(f"{kw1} {nombre_loc} {anno} site:{domain}")
    else:
        logger.info(f"  [MEDIA_SEARCH] Sin medios locales específicos para {localidad['nombre']} (fallback standard)")

    return queries
```

---

## 4. Diseño de Casos de Prueba Unitarios e Integrados

A continuación se detalla la especificación exacta de las pruebas unitarias e integradas a incorporar en `tests_fase2/test_google_search_media.py`.

### 4.1 Test Unitario 1: "Retes de Tudela" (Álava, prefijo 01)
- **Objetivo**: Verificar que una localidad del prefijo 01 (Álava) genera queries dirigidas a medios alaveses (`radiollodio.com`, `elcorreo.com`) y que esto queda registrado en los logs de la ejecución.
- **Datos de Prueba**:
  - `localidad = {"id": "01004000501", "nombre": "Retes de Tudela", "padre_id": "01004000000"}`
  - `municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Araba/Álava", "comunidad_autonoma": "País Vasco"}`
  - `anno = 2026`
- **Aserciones**:
  1. La lista de queries devuelta por `_build_queries` contiene al menos:
     - `"fiestas patronales Retes de Tudela 2026 site:radiollodio.com"`
     - `"fiestas patronales Retes de Tudela 2026 site:elcorreo.com"`
  2. `caplog` registra un mensaje INFO indicando: `[MEDIA_SEARCH] Registrando queries de medios locales para provincia (Retes de Tudela): ['radiollodio.com', 'elcorreo.com'...]`.

### 4.2 Test Unitario 2: Localidad en Bizkaia (prefijo 48)
- **Objetivo**: Verificar que una localidad del prefijo 48 (Bizkaia) genera queries dirigidas a medios vizcaínos (`deia.eus`, `elcorreo.com`) y emite el log correspondiente.
- **Datos de Prueba**:
  - `localidad = {"id": "48027000101", "nombre": "Durango", "padre_id": "48027000000"}`
  - `municipio = {"id": "48027000000", "nombre": "Durango", "provincia": "Bizkaia", "comunidad_autonoma": "País Vasco"}`
  - `anno = 2026`
- **Aserciones**:
  1. La lista de queries contiene:
     - `"fiestas patronales Durango 2026 site:deia.eus"`
     - `"fiestas patronales Durango 2026 site:elcorreo.com"`
  2. `caplog` registra la entrada de log con los dominios de Bizkaia.

### 4.3 Tests de Extensibilidad y Fallbacks
- **Test 3a: Provincia No Mapeada (Fallback Grácil)**
  - `localidad = {"id": "99001000101", "nombre": "Pueblo Desconocido"}`
  - `municipio = {"id": "99001000000", "nombre": "Municipio Desconocido", "provincia": "Provincia Nueva"}`
  - **Asert**: No produce excepciones (`KeyError`, `AttributeError`), genera las queries base sin errores, y registra un log de fallback sin medios locales específicos.
- **Test 3b: Inserción / Registro Dinámico de Nueva Provincia**
  - Probar la función helper `register_province_media("28", "madrid", ["telemadrid.es", "elmadrideno.es"])`.
  - Ejecutar `_build_queries` para una localidad de Madrid (`28001000101`).
  - **Asert**: Las nuevas queries incluyen `site:telemadrid.es` de forma dinámica.
- **Test 3c: Tolerancia en Formato de ID y Nombres Bilingües**
  - Probar variaciones de id/nombre: `id: "01001000101"`, `id: "1001"`, `provincia: "Araba/Álava"`, `provincia: "álava"`.
  - **Asert**: Todos resuelven correctamente los medios alaveses.

### 4.4 Test de Integración: Ejecución Async y Captura de Documentos
- **Objetivo**: Integrar `search_locality_web` simulando respuestas de búsqueda para queries con `site:radiollodio.com` usando `monkeypatch` / `unittest.mock.AsyncMock`.
- **Procedimiento**:
  1. Mockear `_fetch_search_results` para que devuelva snippets ficticios cuando la query contenga `site:radiollodio.com`.
  2. Invocar `asyncio.run(search_locality_web(localidad_retes, municipio_artziniega, 2026))`.
- **Aserciones**:
  1. La función realiza las llamadas asíncronas respetando la lista de queries ampliadas.
  2. Devuelve documentos etiquetados con `fuente: "busqueda_web"`.
  3. Los logs registran las búsquedas individuales y el seguimiento de URLs.

---

## 5. Resumen de Recomendaciones para la Fase de Implementación

1. **Ubicación del Módulo de Medios**: Crear `config_medios.py` en `Fase2_Extraccion_Fiestas/` (similar a `config_idiomas.py`) para aislar la matriz de medios por provincia.
2. **Ubicación de la Pruebas**: Crear `tests_fase2/test_google_search_media.py` con las 5 baterías de tests especificadas.
3. **Respeto a Rate Limits y Presupuesto de Consultas**: Al añadir queries tipo `site:medio`, ajustar `DDG_MAX_URLS_TO_FOLLOW` o filtrar resultados duplicados mediante el set `visited_urls` existente.

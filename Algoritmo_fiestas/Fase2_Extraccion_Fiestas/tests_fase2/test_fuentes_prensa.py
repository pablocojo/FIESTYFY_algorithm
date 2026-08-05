"""
Suite de tests unitarios e integración para Fuentes de Prensa Regional (R1 y R2).
"""

import logging
import pytest
from unittest.mock import AsyncMock, patch

from fuentes import (
    FUENTE_PRENSA_REGIONAL,
    FUENTE_BUSQUEDA,
    FUENTE_WEB_LOCALIDAD,
    FUENTE_WEB_MUNICIPIO,
    FUENTE_RRSS_LOCALIDAD,
    FUENTE_RRSS_MUNICIPIO,
    prioridad_fuente,
    es_fuente_oficial,
    get_codigo_provincia,
    get_medios_prensa_por_provincia,
    register_provincia_medios,
)
from scraper.google_search import (
    build_media_queries,
    search_locality_media,
)
from main import process_locality


@pytest.fixture
def anyio_backend():
    return 'asyncio'



# ─────────────────────────────────────────────────────────────
# 1. Tests de fuentes.py: códigos, medios y prioridades
# ─────────────────────────────────────────────────────────────

def test_fuentes_prensa_constantes_y_prioridades():
    assert FUENTE_PRENSA_REGIONAL == "prensa_regional"
    assert prioridad_fuente(FUENTE_PRENSA_REGIONAL) == 5
    assert prioridad_fuente(FUENTE_BUSQUEDA) == 6
    assert not es_fuente_oficial(FUENTE_PRENSA_REGIONAL)
    assert not es_fuente_oficial(FUENTE_BUSQUEDA)
    assert es_fuente_oficial(FUENTE_WEB_LOCALIDAD)
    assert es_fuente_oficial(FUENTE_WEB_MUNICIPIO)
    assert es_fuente_oficial(FUENTE_RRSS_LOCALIDAD)
    assert es_fuente_oficial(FUENTE_RRSS_MUNICIPIO)


def test_get_codigo_provincia_variados():
    # Código INE directo (11 dígitos)
    assert get_codigo_provincia("01004000101") == "01"
    assert get_codigo_provincia("48020000101") == "48"
    assert get_codigo_provincia("28079000101") == "28"

    # Código 2 dígitos directo
    assert get_codigo_provincia("01") == "01"
    assert get_codigo_provincia("48") == "48"

    # Nombres de provincias
    assert get_codigo_provincia("Álava") == "01"
    assert get_codigo_provincia("araba") == "01"
    assert get_codigo_provincia("Bizkaia") == "48"
    assert get_codigo_provincia("Vizcaya") == "48"
    assert get_codigo_provincia("Madrid") == "28"

    # Inválidos
    assert get_codigo_provincia("") is None
    assert get_codigo_provincia(None) is None
    assert get_codigo_provincia("invalid_province_xyz") is None


def test_get_medios_prensa_por_provincia():
    medios_alava = get_medios_prensa_por_provincia("01")
    assert "radiollodio.com" in medios_alava
    assert "elcorreo.com" in medios_alava
    assert "noticiasdealava.com" in medios_alava

    medios_bizkaia = get_medios_prensa_por_provincia("48")
    assert "deia.eus" in medios_bizkaia
    assert "elcorreo.com" in medios_bizkaia

    # Por nombre
    medios_by_name = get_medios_prensa_por_provincia("Álava")
    assert medios_by_name == medios_alava


# ─────────────────────────────────────────────────────────────
# 2. Test "Retes de Tudela" (Álava, 01) genera/registra queries con medios de Álava
# ─────────────────────────────────────────────────────────────

def test_retes_de_tudela_queries_prensa_alava():
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "comunidad_autonoma": "País Vasco"}

    queries = build_media_queries(localidad, municipio, 2026)
    assert len(queries) > 0
    assert any("radiollodio.com" in q for q in queries)
    assert any("elcorreo.com" in q for q in queries)
    assert any("noticiasdealava.com" in q for q in queries)
    assert any("site:radiollodio.com" in q for q in queries)


@pytest.mark.anyio
async def test_retes_de_tudela_logging_prensa_alava(caplog):
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "comunidad_autonoma": "País Vasco"}

    with caplog.at_level(logging.INFO), \
         patch("scraper.google_search._fetch_search_results", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []

        await search_locality_media(localidad, municipio, 2026)

        # Verificar que loguea explícitamente [MEDIA_SEARCH] Buscando en prensa regional: ...
        logs = caplog.text
        assert "[MEDIA_SEARCH] Buscando en prensa regional:" in logs
        assert "radiollodio.com" in logs
        assert "Retes de Tudela" in logs


# ─────────────────────────────────────────────────────────────
# 3. Test pueblo de Bizkaia (48) genera/registra queries con medios de Bizkaia
# ─────────────────────────────────────────────────────────────

def test_bizkaia_town_queries_prensa_bizkaia():
    localidad = {"id": "48020000101", "nombre": "Bermeo"}
    municipio = {"id": "48020000000", "nombre": "Bermeo", "provincia": "Bizkaia", "comunidad_autonoma": "País Vasco"}

    queries = build_media_queries(localidad, municipio, 2026)
    assert len(queries) > 0
    assert any("deia.eus" in q for q in queries)
    assert any("elcorreo.com" in q for q in queries)
    assert any("site:deia.eus" in q for q in queries)


@pytest.mark.anyio
async def test_bizkaia_town_logging_prensa_bizkaia(caplog):
    localidad = {"id": "48020000101", "nombre": "Bermeo"}
    municipio = {"id": "48020000000", "nombre": "Bermeo", "provincia": "Bizkaia", "comunidad_autonoma": "País Vasco"}

    with caplog.at_level(logging.INFO), \
         patch("scraper.google_search._fetch_search_results", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []

        await search_locality_media(localidad, municipio, 2026)

        logs = caplog.text
        assert "[MEDIA_SEARCH] Buscando en prensa regional:" in logs
        assert "deia.eus" in logs
        assert "Bermeo" in logs


# ─────────────────────────────────────────────────────────────
# 4. Test extensibilidad (registro dinámico de provincias & fallback)
# ─────────────────────────────────────────────────────────────

def test_provincia_extensibilidad_y_fallback():
    from fuentes import MEDIOS_PRENSA_POR_PROVINCIA
    try:
        # Registro dinámico por código
        register_provincia_medios("99", ["medionuevo.com", "diarionuevo.es"])
        medios = get_medios_prensa_por_provincia("99")
        assert medios == ["medionuevo.com", "diarionuevo.es"]

        # Acceso por lugar_id con código 99
        medios_id = get_medios_prensa_por_provincia("99001000101")
        assert medios_id == ["medionuevo.com", "diarionuevo.es"]

        # Registro dinámico por nombre
        register_provincia_medios("ProvinciaFicticia", ["ficticianews.com"])
        medios_nom = get_medios_prensa_por_provincia("ProvinciaFicticia")
        assert medios_nom == ["ficticianews.com"]

        # Fallback provincia desconocida
        medios_desconocida = get_medios_prensa_por_provincia("00")
        assert medios_desconocida == []
    finally:
        MEDIOS_PRENSA_POR_PROVINCIA.pop("99", None)
        MEDIOS_PRENSA_POR_PROVINCIA.pop("provinciaficticia", None)
        MEDIOS_PRENSA_POR_PROVINCIA.pop("ProvinciaFicticia", None)


@pytest.mark.anyio
async def test_search_locality_media_fallback_sin_medios():
    localidad = {"id": "00000000000", "nombre": "PuebloDesconocido"}
    municipio = {"id": "00000000000", "nombre": "MunicipioDesconocido", "provincia": "Desconocida"}

    docs = await search_locality_media(localidad, municipio, 2026)
    assert docs == []


# ─────────────────────────────────────────────────────────────
# 5. Test fallback de búsqueda cuando no se encuentran fuentes oficiales
# ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_process_locality_fallback_prensa_sin_fuentes_oficiales():
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": ""}

    doc_prensa_snippet = {
        "fuente": FUENTE_PRENSA_REGIONAL,
        "url": "prensa_regional:snippets",
        "texto": "Fiestas de San Vitores en Retes de Tudela septiembre",
        "tipo": "snippets",
        "es_calendario": False,
    }

    rag_mock = AsyncMock()
    rag_mock.saturate_context_docs.return_value = ("Texto contexto RAG", [doc_prensa_snippet])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = []
        mock_media_search.return_value = [doc_prensa_snippet]
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas de San Vitores", "fecha_inicio": "2026-09-01"}]

        logger_test = logging.getLogger("test")

        result = await process_locality(
            localidad=localidad,
            municipio=municipio,
            anno=2026,
            rag_processor=rag_mock,
            rrss_client=None,
            logger=logger_test,
        )

        # Confirmar que search_locality_media FUE ejecutado porque docs_oficiales estaba vacío
        assert mock_media_search.called
        assert len(result) > 0


@pytest.mark.anyio
async def test_process_locality_no_ejecuta_prensa_si_hay_fuentes_oficiales():
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": "http://artziniega.eus"}

    doc_oficial = {
        "fuente": FUENTE_WEB_MUNICIPIO,
        "url": "http://artziniega.eus/fiestas",
        "texto": "Programa de fiestas de San Vitores",
        "tipo": "pagina",
        "es_calendario": False,
    }

    rag_mock = AsyncMock()
    rag_mock.saturate_context_docs.return_value = ("Texto contexto", [doc_oficial])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = [doc_oficial]
        mock_media_search.return_value = []
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas de San Vitores"}]

        logger_test = logging.getLogger("test")

        result = await process_locality(
            localidad=localidad,
            municipio=municipio,
            anno=2026,
            rag_processor=rag_mock,
            rrss_client=None,
            logger=logger_test,
        )

        # Confirmar que search_locality_media NO fue ejecutado porque habia fuentes oficiales
        assert not mock_media_search.called


# ─────────────────────────────────────────────────────────────
# 6. Tests para los 5 Casos Límite (Challenger 1 Fix Pass)
# ─────────────────────────────────────────────────────────────

def test_edge_case_1_get_codigo_provincia_padding():
    """Caso Límite 1: Padding de códigos de provincia de 1 dígito y 4 dígitos sin cero inicial."""
    # Código de 1 dígito (string e int) debe formatearse a "01"
    assert get_codigo_provincia("1") == "01"
    assert get_codigo_provincia(1) == "01"
    assert get_codigo_provincia("2") == "02"

    # Código INE de 4 dígitos truncado (sin cero inicial) debe formatearse a 5 dígitos y extraer "01" (Álava)
    assert get_codigo_provincia("1004") == "01"
    assert get_codigo_provincia("1004000101") == "01"


def test_edge_case_2_register_provincia_medios_bidireccional():
    """Caso Límite 2: Registro por nombre/código actualiza de forma bidireccional MEDIOS_PRENSA_POR_PROVINCIA."""
    from fuentes import MEDIOS_PRENSA_POR_PROVINCIA
    orig_28 = list(MEDIOS_PRENSA_POR_PROVINCIA.get("28", []))
    orig_madrid = list(MEDIOS_PRENSA_POR_PROVINCIA.get("madrid", []))
    try:
        # Registrar por nombre actualiza clave nombre y clave INE 28
        test_medios = ["madrid_test_news.es"]
        register_provincia_medios("madrid", test_medios)
        assert get_medios_prensa_por_provincia("madrid") == test_medios
        assert get_medios_prensa_por_provincia("28") == test_medios
        assert get_medios_prensa_por_provincia("28001000") == test_medios

        # Registrar por código actualiza clave INE 28 y clave nombre
        test_medios_code = ["madrid_code_news.es"]
        register_provincia_medios("28", test_medios_code)
        assert get_medios_prensa_por_provincia("28") == test_medios_code
        assert get_medios_prensa_por_provincia("madrid") == test_medios_code
    finally:
        MEDIOS_PRENSA_POR_PROVINCIA["28"] = orig_28
        MEDIOS_PRENSA_POR_PROVINCIA["madrid"] = orig_madrid


def test_edge_case_3_google_search_dict_handling():
    """Caso Límite 3: Acceso seguro a 'nombre' en google_search y retorno de list vacía si faltan nombres."""
    from scraper.google_search import _build_queries, build_media_queries
    assert _build_queries({}, {}, 2026) == []
    assert _build_queries({"nombre": None}, {"nombre": None}, 2026) == []
    assert build_media_queries({}, {}, 2026) == []
    assert build_media_queries({"nombre": ""}, {"nombre": ""}, 2026) == []


def test_edge_case_4_google_search_sitio_web_none():
    """Caso Límite 4: Manejo seguro de sitio_web=None en google_search."""
    from scraper.google_search import _build_queries
    loc = {"nombre": "Toro", "sitio_web": None}
    mun = {"nombre": "Toro", "sitio_web": None, "provincia": "Zamora", "comunidad_autonoma": "Castilla y León"}
    queries = _build_queries(loc, mun, 2026)
    assert len(queries) >= 3


@pytest.mark.anyio
async def test_edge_case_5_google_search_visited_urls_as_list():
    """Caso Límite 5: visited_urls pasado como lista en vez de set."""
    from scraper.google_search import search_locality_web
    loc = {"nombre": "Toro"}
    mun = {"nombre": "Toro", "provincia": "Zamora", "comunidad_autonoma": "Castilla y León"}
    visited_urls_list = ["http://already-visited.com"]

    with patch("scraper.google_search._fetch_search_results", new_callable=AsyncMock) as mock_fetch, \
         patch("scraper.google_search._fetch_page_content", new_callable=AsyncMock) as mock_page:
        mock_fetch.return_value = [{"titulo": "T", "snippet": "S", "url": "http://new-page.com"}]
        mock_page.return_value = "Contenido test"

        docs = await search_locality_web(loc, mun, 2026, visited_urls=visited_urls_list)
        assert isinstance(docs, list)
        assert isinstance(visited_urls_list, list)
        assert "http://new-page.com" in visited_urls_list

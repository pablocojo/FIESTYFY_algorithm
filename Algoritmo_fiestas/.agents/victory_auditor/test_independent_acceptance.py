"""
Independent Victory Verification Test Suite
Created by VICTORY AUDITOR to independently test:
1. R1: Provincial press dictionary mapping 52 provinces in fuentes.py.
2. R2: Supplemental site: query injection for pedanías when official results are missing.
3. Acceptance Criteria:
   - Town "Retes de Tudela" (Álava, 01) logs query including Álava media.
   - Town in Bizkaia (48) uses Bizkaia media.
   - Sources structure is extensible without altering main search logic.
4. Anti-Cheating & Integrity checks:
   - Integrity of es_fuente_oficial classification.
   - Dynamic registration integrity.
"""

import sys
import os
import logging
import pytest
from unittest.mock import AsyncMock, patch

# Ensure target project directory is on sys.path
TARGET_DIR = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)

import fuentes
from fuentes import (
    MEDIOS_PRENSA_POR_PROVINCIA,
    FUENTE_PRENSA_REGIONAL,
    FUENTE_WEB_LOCALIDAD,
    FUENTE_WEB_MUNICIPIO,
    FUENTE_BUSQUEDA,
    get_codigo_provincia,
    get_medios_prensa_por_provincia,
    register_provincia_medios,
    es_fuente_oficial,
    prioridad_fuente,
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
# 1. R1 Verification: All 52 Spanish Provinces mapped
# ─────────────────────────────────────────────────────────────

def test_r1_all_52_provinces_mapped():
    """Verify that all 52 INE province codes ('01' to '52') exist and have valid media domains."""
    expected_codes = [f"{i:02d}" for i in range(1, 53)]
    for code in expected_codes:
        assert code in MEDIOS_PRENSA_POR_PROVINCIA, f"Missing province code {code} in MEDIOS_PRENSA_POR_PROVINCIA"
        medios = get_medios_prensa_por_provincia(code)
        assert len(medios) > 0, f"Province code {code} has empty media list"
        for domain in medios:
            assert "." in domain, f"Invalid domain {domain} in province {code}"


def test_r1_ine_code_extraction_variants():
    """Verify get_codigo_provincia extracts 2-digit codes across multiple format types."""
    test_cases = [
        ("01004000101", "01"),  # 11-digit pedanía ID Álava
        ("48020000101", "48"),  # 11-digit pedanía ID Bizkaia
        ("28079000101", "28"),  # 11-digit Madrid
        ("01", "01"),           # 2-digit string
        ("48", "48"),           # 2-digit string
        ("1", "01"),            # 1-digit string padded
        (1, "01"),              # int 1
        ("1004", "01"),         # 4-digit truncated INE padded to 5-digit -> "01"
        ("Álava", "01"),        # Name accent
        ("araba", "01"),        # Basque name
        ("Bizkaia", "48"),     # Basque name
        ("Vizcaya", "48"),     # Spanish name
        ("Madrid", "28"),       # Name
    ]
    for input_val, expected in test_cases:
        extracted = get_codigo_provincia(input_val)
        assert extracted == expected, f"Failed for {input_val!r}: got {extracted!r}, expected {expected!r}"


# ─────────────────────────────────────────────────────────────
# 2. Acceptance Criteria 1: Retes de Tudela (Álava, 01)
# ─────────────────────────────────────────────────────────────

def test_ac1_retes_de_tudela_queries():
    """Retes de Tudela (Álava, 01) generates site: queries including Álava media."""
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "comunidad_autonoma": "País Vasco"}

    queries = build_media_queries(localidad, municipio, 2026)
    assert len(queries) >= 3
    alava_media = ["radiollodio.com", "elcorreo.com", "noticiasdealava.com"]
    for media in alava_media:
        assert any(f"site:{media}" in q for q in queries), f"Query for site:{media} missing in Retes de Tudela queries"


@pytest.mark.anyio
async def test_ac1_retes_de_tudela_logging(caplog):
    """Retes de Tudela (Álava, 01) logs search query containing Álava media."""
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "comunidad_autonoma": "País Vasco"}

    with caplog.at_level(logging.INFO), \
         patch("scraper.google_search._fetch_search_results", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []

        await search_locality_media(localidad, municipio, 2026)

        logs = caplog.text
        assert "[MEDIA_SEARCH] Buscando en prensa regional:" in logs
        assert "radiollodio.com" in logs
        assert "Retes de Tudela" in logs


# ─────────────────────────────────────────────────────────────
# 3. Acceptance Criteria 2: Bizkaia Town (48)
# ─────────────────────────────────────────────────────────────

def test_ac2_bizkaia_town_queries():
    """Town in Bizkaia (48) generates site: queries including Bizkaia media."""
    localidad = {"id": "48020000101", "nombre": "Bermeo"}
    municipio = {"id": "48020000000", "nombre": "Bermeo", "provincia": "Bizkaia", "comunidad_autonoma": "País Vasco"}

    queries = build_media_queries(localidad, municipio, 2026)
    assert len(queries) >= 2
    bizkaia_media = ["deia.eus", "elcorreo.com"]
    for media in bizkaia_media:
        assert any(f"site:{media}" in q for q in queries), f"Query for site:{media} missing in Bizkaia queries"


@pytest.mark.anyio
async def test_ac2_bizkaia_town_logging(caplog):
    """Bizkaia town (48) logs search query containing Bizkaia media."""
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
# 4. Acceptance Criteria 3: Extensibility without altering search logic
# ─────────────────────────────────────────────────────────────

def test_ac3_extensibility():
    """Registering new province media via register_provincia_medios dynamically affects search query generation without code changes."""
    orig_99 = list(MEDIOS_PRENSA_POR_PROVINCIA.get("99", []))
    try:
        register_provincia_medios("99", ["diarioinnovador.com", "noticiasfuturo.es"])
        localidad = {"id": "99001000101", "nombre": "PuebloNuevo"}
        municipio = {"id": "99001000000", "nombre": "MunicipioNuevo", "provincia": "Provincia 99"}

        queries = build_media_queries(localidad, municipio, 2026)
        assert any("site:diarioinnovador.com" in q for q in queries)
        assert any("site:noticiasfuturo.es" in q for q in queries)
    finally:
        if orig_99:
            MEDIOS_PRENSA_POR_PROVINCIA["99"] = orig_99
        else:
            MEDIOS_PRENSA_POR_PROVINCIA.pop("99", None)


# ─────────────────────────────────────────────────────────────
# 5. R2 Verification: Fallback execution when docs_oficiales is empty
# ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_r2_fallback_when_no_official_docs():
    """process_locality triggers search_locality_media ONLY when len(docs_oficiales) == 0."""
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": ""}

    doc_prensa = {
        "fuente": FUENTE_PRENSA_REGIONAL,
        "url": "prensa_regional:snippets",
        "texto": "Fiestas de San Vitores en Retes de Tudela",
        "tipo": "snippets",
        "es_calendario": False,
    }

    rag_mock = AsyncMock()
    rag_mock.saturate_context_docs.return_value = ("Contexto RAG", [doc_prensa])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = []
        mock_media_search.return_value = [doc_prensa]
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas de San Vitores"}]

        logger_test = logging.getLogger("test")

        res = await process_locality(
            localidad=localidad,
            municipio=municipio,
            anno=2026,
            rag_processor=rag_mock,
            rrss_client=None,
            logger=logger_test,
        )

        assert mock_media_search.called, "search_locality_media should have been called when no official docs exist"
        assert len(res) > 0


# ─────────────────────────────────────────────────────────────
# 6. Anti-Cheating & Integrity Verifications
# ─────────────────────────────────────────────────────────────

def test_integrity_es_fuente_oficial_classification():
    """Verify that prensa_regional is NOT classified as official source (so it can't falsely satisfy official sources check)."""
    assert es_fuente_oficial(FUENTE_WEB_LOCALIDAD) is True
    assert es_fuente_oficial(FUENTE_WEB_MUNICIPIO) is True
    assert es_fuente_oficial(FUENTE_PRENSA_REGIONAL) is False
    assert es_fuente_oficial(FUENTE_BUSQUEDA) is False


def test_integrity_prioridad_fuente_ordering():
    """Verify press regional priority is 5 (between official sources 1-4 and general web search 6)."""
    assert prioridad_fuente(FUENTE_WEB_LOCALIDAD) == 1
    assert prioridad_fuente(FUENTE_WEB_MUNICIPIO) == 2
    assert prioridad_fuente(FUENTE_PRENSA_REGIONAL) == 5
    assert prioridad_fuente(FUENTE_BUSQUEDA) == 6

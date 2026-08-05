import sys
import os
import asyncio
import logging
from unittest.mock import AsyncMock, patch, MagicMock

# Add target codebase path
target_path = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_path not in sys.path:
    sys.path.insert(0, target_path)

from fuentes import (
    FUENTE_PRENSA_REGIONAL,
    FUENTE_BUSQUEDA,
    FUENTE_WEB_LOCALIDAD,
    FUENTE_WEB_MUNICIPIO,
    FUENTE_RRSS_LOCALIDAD,
    FUENTE_RRSS_MUNICIPIO,
    es_fuente_oficial,
    prioridad_fuente,
    get_medios_prensa_por_provincia,
)
from scraper.google_search import (
    build_media_queries,
    search_locality_media,
)
from main import process_locality


class RecordCapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()


class EmpiricalHarness:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def assert_true(self, condition: bool, test_name: str, details: str = ""):
        if condition:
            self.passed += 1
            print(f"[PASS] {test_name}")
            self.results.append((test_name, "PASS", details))
        else:
            self.failed += 1
            print(f"[FAIL] {test_name}: {details}")
            self.results.append((test_name, "FAIL", details))


async def run_empirical_tests():
    harness = EmpiricalHarness()
    print("=== STARTING EMPIRICAL VERIFICATION HARNESS ===")

    # -------------------------------------------------------------
    # Test 1: Verification of es_fuente_oficial classification
    # -------------------------------------------------------------
    harness.assert_true(
        es_fuente_oficial(FUENTE_WEB_LOCALIDAD) is True,
        "es_fuente_oficial(FUENTE_WEB_LOCALIDAD)",
        "FUENTE_WEB_LOCALIDAD must be official"
    )
    harness.assert_true(
        es_fuente_oficial(FUENTE_WEB_MUNICIPIO) is True,
        "es_fuente_oficial(FUENTE_WEB_MUNICIPIO)",
        "FUENTE_WEB_MUNICIPIO must be official"
    )
    harness.assert_true(
        es_fuente_oficial(FUENTE_RRSS_LOCALIDAD) is True,
        "es_fuente_oficial(FUENTE_RRSS_LOCALIDAD)",
        "FUENTE_RRSS_LOCALIDAD must be official"
    )
    harness.assert_true(
        es_fuente_oficial(FUENTE_RRSS_MUNICIPIO) is True,
        "es_fuente_oficial(FUENTE_RRSS_MUNICIPIO)",
        "FUENTE_RRSS_MUNICIPIO must be official"
    )
    harness.assert_true(
        es_fuente_oficial(FUENTE_PRENSA_REGIONAL) is False,
        "es_fuente_oficial(FUENTE_PRENSA_REGIONAL)",
        "FUENTE_PRENSA_REGIONAL must NOT be official"
    )
    harness.assert_true(
        es_fuente_oficial(FUENTE_BUSQUEDA) is False,
        "es_fuente_oficial(FUENTE_BUSQUEDA)",
        "FUENTE_BUSQUEDA must NOT be official"
    )

    # -------------------------------------------------------------
    # Test 2: Empirically verify log emission of [MEDIA_SEARCH] queries
    # -------------------------------------------------------------
    search_logger = logging.getLogger("search")
    handler_search = RecordCapturingHandler()
    search_logger.addHandler(handler_search)
    search_logger.setLevel(logging.INFO)

    localidad_alava = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio_alava = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "comunidad_autonoma": "País Vasco"}

    with patch("scraper.google_search._fetch_search_results", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [{"titulo": "Noticia 1", "snippet": "Fiestas 2026", "url": "https://radiollodio.com/fiestas"}]
        with patch("scraper.google_search._fetch_page_content", new_callable=AsyncMock) as mock_page:
            mock_page.return_value = "Contenido completo prensa"

            handler_search.clear()
            docs = await search_locality_media(localidad_alava, municipio_alava, 2026)

            media_search_logs = [r for r in handler_search.records if "[MEDIA_SEARCH]" in r.getMessage()]

            harness.assert_true(
                len(media_search_logs) > 0,
                "Log emission [MEDIA_SEARCH] presence",
                f"Found {len(media_search_logs)} [MEDIA_SEARCH] log entries"
            )

            # Check exact pattern in logs
            expected_prefix = "  [MEDIA_SEARCH] Buscando en prensa regional:"
            correct_format = any(r.getMessage().startswith(expected_prefix) for r in media_search_logs)
            harness.assert_true(
                correct_format,
                "Log emission [MEDIA_SEARCH] exact format",
                f"Log messages: {[r.getMessage() for r in media_search_logs]}"
            )

            # Check that queries mention regional media domains (radiollodio.com, elcorreo.com, noticiasdealava.com)
            radiollodio_logged = any("site:radiollodio.com" in r.getMessage() for r in media_search_logs)
            harness.assert_true(
                radiollodio_logged,
                "Log emission includes site:radiollodio.com",
                f"Logged queries: {[r.getMessage() for r in media_search_logs]}"
            )

    search_logger.removeHandler(handler_search)

    # -------------------------------------------------------------
    # Test 3: Empirically verify fallback behavior in process_locality
    # Scenario A: NO official docs exist -> Regional press search IS executed
    # -------------------------------------------------------------
    main_logger = logging.getLogger("main_test_harness")
    handler_main = RecordCapturingHandler()
    main_logger.addHandler(handler_main)
    main_logger.setLevel(logging.INFO)

    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio_no_web = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": ""}

    doc_prensa = {
        "fuente": FUENTE_PRENSA_REGIONAL,
        "url": "prensa_regional:snippets",
        "texto": "Programa de Fiestas de Retes de Tudela 2026",
        "tipo": "snippets",
        "es_calendario": False,
    }

    rag_mock = AsyncMock()
    rag_mock.saturate_context_docs.return_value = ("Texto contexto RAG prensa", [doc_prensa])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = [] # No official web docs
        mock_media_search.return_value = [doc_prensa]
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas de San Vitores", "fecha_inicio": "2026-09-01"}]

        handler_main.clear()
        res = await process_locality(
            localidad=localidad,
            municipio=municipio_no_web,
            anno=2026,
            rag_processor=rag_mock,
            rrss_client=None,
            logger=main_logger,
        )

        harness.assert_true(
            mock_media_search.called,
            "process_locality: search_locality_media EXECUTED when 0 official docs exist",
            f"mock_media_search call count: {mock_media_search.call_count}"
        )

        fallback_log = any("Sin fuentes oficiales. Búsqueda suplementaria en prensa regional" in r.getMessage() for r in handler_main.records)
        harness.assert_true(
            fallback_log,
            "process_locality: log emission for press fallback when 0 official docs",
            f"Main logs: {[r.getMessage() for r in handler_main.records]}"
        )

    # -------------------------------------------------------------
    # Test 4: Empirically verify skip behavior in process_locality
    # Scenario B: Official docs DO exist -> Regional press search IS SKIPPED
    # -------------------------------------------------------------
    doc_oficial_web = {
        "fuente": FUENTE_WEB_MUNICIPIO,
        "url": "http://artziniega.eus/fiestas",
        "texto": "Fiestas oficiales del Municipio de Artziniega",
        "tipo": "pagina",
        "es_calendario": False,
    }

    rag_mock_oficial = AsyncMock()
    rag_mock_oficial.saturate_context_docs.return_value = ("Texto contexto oficial", [doc_oficial_web])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = [doc_oficial_web] # Official web docs returned
        mock_media_search.return_value = []
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas de San Vitores"}]

        handler_main.clear()
        municipio_con_web = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": "http://artziniega.eus"}

        res = await process_locality(
            localidad=localidad,
            municipio=municipio_con_web,
            anno=2026,
            rag_processor=rag_mock_oficial,
            rrss_client=None,
            logger=main_logger,
        )

        harness.assert_true(
            not mock_media_search.called,
            "process_locality: search_locality_media SKIPPED when official docs exist",
            f"mock_media_search call count: {mock_media_search.call_count}"
        )

        fallback_log = any("Sin fuentes oficiales. Búsqueda suplementaria en prensa regional" in r.getMessage() for r in handler_main.records)
        harness.assert_true(
            not fallback_log,
            "process_locality: fallback log NOT emitted when official docs exist",
            f"Main logs: {[r.getMessage() for r in handler_main.records]}"
        )

    # -------------------------------------------------------------
    # Test 5: Scenario with official RRSS doc existing (web is empty)
    # -------------------------------------------------------------
    doc_oficial_rrss = {
        "fuente": FUENTE_RRSS_LOCALIDAD,
        "url": "facebook:RetesDeTudela",
        "texto": "Publicacion de Facebook sobre Fiestas Retes de Tudela",
        "tipo": "post",
        "es_calendario": False,
    }

    rag_mock_rrss = AsyncMock()
    rag_mock_rrss.saturate_context_docs.return_value = ("Texto contexto rrss", [doc_oficial_rrss])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[doc_oficial_rrss]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:

        mock_spider.return_value = []
        mock_media_search.return_value = []
        mock_web_search.return_value = []
        mock_llm.return_value = [{"nombre": "Fiestas Patronales"}]

        handler_main.clear()
        res = await process_locality(
            localidad=localidad,
            municipio=municipio_no_web,
            anno=2026,
            rag_processor=rag_mock_rrss,
            rrss_client=None,
            logger=main_logger,
        )

        harness.assert_true(
            not mock_media_search.called,
            "process_locality: search_locality_media SKIPPED when RRSS official doc exists",
            f"mock_media_search call count: {mock_media_search.call_count}"
        )

    main_logger.removeHandler(handler_main)

    print(f"\n=== HARNESS SUMMARY: {harness.passed} PASSED, {harness.failed} FAILED ===")
    return harness.passed, harness.failed, harness.results


if __name__ == "__main__":
    asyncio.run(run_empirical_tests())

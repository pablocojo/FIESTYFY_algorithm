import logging
import sys
sys.path.insert(0, r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas")
from main import process_locality
from fuentes import FUENTE_PRENSA_REGIONAL
from unittest.mock import AsyncMock, patch

log_records = []
class ListHandler(logging.Handler):
    def emit(self, record):
        log_records.append(record)

logger = logging.getLogger("test_diag")
logger.setLevel(logging.INFO)
handler = ListHandler()
handler.setLevel(logging.INFO)
logger.addHandler(handler)

import asyncio

async def test():
    localidad = {"id": "01004000101", "nombre": "Retes de Tudela"}
    municipio_no_web = {"id": "01004000000", "nombre": "Artziniega", "provincia": "Álava", "sitio_web": ""}
    rag_mock = AsyncMock()
    rag_mock.saturate_context_docs.return_value = ("ctx", [])

    with patch("main.AsyncTwoPassSpider.crawl", new_callable=AsyncMock) as mock_spider, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.search_locality_media", new_callable=AsyncMock) as mock_media_search, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web_search, \
         patch("main.analyze_festivals_for_locality", new_callable=AsyncMock) as mock_llm:
        
        mock_spider.return_value = []
        mock_media_search.return_value = []
        mock_web_search.return_value = []
        mock_llm.return_value = []

        await process_locality(localidad, municipio_no_web, 2026, rag_mock, None, logger)

    print(f"Logged {len(log_records)} records:")
    for r in log_records:
        print(f" - {r.getMessage()}")

asyncio.run(test())

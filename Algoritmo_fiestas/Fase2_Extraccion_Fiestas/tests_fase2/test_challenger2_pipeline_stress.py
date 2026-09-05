"""
Pipeline Edge Cases Stress Test Suite — Challenger 2
Tests process_locality, analyze_festivals_multipass, discover_festivals_for_locality,
enrich_festival_program, llm_chat_json, and patron integration under edge conditions.
"""

import sys
import os
import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from main import process_locality
from llm_processor.text_analyzer import (
    analyze_festivals_multipass,
    discover_festivals_for_locality,
    enrich_festival_program,
    llm_chat_json,
    _parse_json_llm,
    AsyncRAGProcessor,
)
from llm_processor.patron_finder import obtener_patron, integrar_patron, fecha_del_patron


@pytest.fixture
def mock_logger():
    return logging.getLogger("test_challenger2")


@pytest.fixture
def sample_locality():
    return {
        "id": "pueblo-1",
        "nombre": "Pueblo Test",
        "tipo": "pueblo",
        "padre_id": "mun-1",
        "lat": 40.0,
        "lng": -3.0,
    }


@pytest.fixture
def sample_municipio():
    return {
        "id": "mun-1",
        "nombre": "Municipio Test",
        "tipo": "municipio",
        "sitio_web": "",
    }


# ==============================================================================
# EDGE CASE 1: 0 Documents
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_case_zero_documents(sample_locality, sample_municipio, mock_logger):
    """Verify analyze_festivals_multipass and process_locality with 0 documents."""
    # 1. Direct call to analyze_festivals_multipass with empty docs
    res = await analyze_festivals_multipass(
        municipio=sample_municipio,
        localidad=sample_locality,
        documentos=[],
        anno=2026,
        logger=mock_logger,
    )
    assert res == []

    # 2. process_locality with empty scraping result
    with patch("main.search_locality_media", new_callable=AsyncMock) as mock_media, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.obtener_patron", new_callable=AsyncMock) as mock_patron:
        mock_media.return_value = []
        mock_web.return_value = []
        mock_patron.return_value = {"nombre": "San Test", "dia": 15, "mes": 8}

        fiestas = await process_locality(
            localidad=sample_locality,
            municipio=sample_municipio,
            anno=2026,
            rag_processor=AsyncRAGProcessor(),
            rrss_client=None,
            logger=mock_logger,
        )
        assert len(fiestas) == 1
        assert fiestas[0]["es_estimada"] is True
        assert fiestas[0]["nombre"] == "Fiestas de San Test (estimada)", (
        "el nombre de la fiesta estimada lo pone integrar_patron; si cambia, "
        "cambia también aquí"
    )


# ==============================================================================
# EDGE CASE 2: 0 Discovered Festivals
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_case_zero_discovered_festivals(sample_locality, sample_municipio, mock_logger):
    """Verify behavior when LLM/RAG discovers 0 festivals from valid documents."""
    docs = [{"fuente": "web_municipio", "texto": "El municipio celebra sus jornadas culturales en mayo."}]

    with patch("llm_processor.text_analyzer.discover_festivals_for_locality", new_callable=AsyncMock) as mock_disc:
        mock_disc.return_value = []

        res = await analyze_festivals_multipass(
            municipio=sample_municipio,
            localidad=sample_locality,
            documentos=docs,
            anno=2026,
            logger=mock_logger,
        )
        assert res == []


# ==============================================================================
# EDGE CASE 3: LLM Timeouts
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_case_llm_timeout(sample_locality, sample_municipio, mock_logger):
    """Verify handling when LLM calls throw asyncio.TimeoutError."""
    docs = [{"fuente": "web_municipio", "texto": "Fiesta Mayor del 10 al 15 de agosto con orquesta."}]

    # Mock llm_chat_json to raise TimeoutError
    with patch("llm_processor.text_analyzer.llm_chat_json", side_effect=asyncio.TimeoutError):
        res = await analyze_festivals_multipass(
            municipio=sample_municipio,
            localidad=sample_locality,
            documentos=docs,
            anno=2026,
            logger=mock_logger,
        )
        assert res == []

    # Test enrichment timeout fallback
    fiesta = {
        "id": "fiesta-test",
        "nombre": "Fiesta Mayor",
        "fecha_inicio": "2026-08-10",
        "fecha_fin": "2026-08-12",
        "lugar_id": sample_locality["id"],
    }
    chunks = [{"fuente": "web_municipio", "chunk": "Programa: 10:00 Diana", "url": "", "es_calendario": False, "prioridad": 1}]

    with patch("llm_processor.text_analyzer.llm_chat_json", side_effect=asyncio.TimeoutError):
        enriched = await enrich_festival_program(
            municipio=sample_municipio,
            localidad=sample_locality,
            fiesta=fiesta,
            indexed_chunks=chunks,
            anno=2026,
        )
        assert enriched["programa"] == []
        assert enriched["nombre"] == "Fiesta Mayor"


# ==============================================================================
# EDGE CASE 4: Malformed JSON Responses
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_case_malformed_json_responses(sample_locality, sample_municipio, mock_logger):
    """Verify handling of truncated, non-json, or invalid dict structures from LLM."""
    # 1. _parse_json_llm robustness
    assert _parse_json_llm("No es JSON") is None
    assert _parse_json_llm("```json\n{\"fiestas\": [}```") is None
    parsed_repaired = _parse_json_llm("```json\n{\"fiestas\": [{\"id\": \"f1\"},]}\n```")
    assert parsed_repaired == {"fiestas": [{"id": "f1"}]}

    # 2. llm_chat_json returning dict without 'fiestas' key
    docs = [{"fuente": "web_municipio", "texto": "Fiesta Mayor del 10 al 15 de agosto."}]
    with patch("llm_processor.text_analyzer.llm_chat_json", return_value={"unexpected": "data"}):
        res = await analyze_festivals_multipass(
            municipio=sample_municipio,
            localidad=sample_locality,
            documentos=docs,
            anno=2026,
            logger=mock_logger,
        )
        assert res == []

    # 3. llm_chat_json returning None
    with patch("llm_processor.text_analyzer.llm_chat_json", return_value=None):
        res = await analyze_festivals_multipass(
            municipio=sample_municipio,
            localidad=sample_locality,
            documentos=docs,
            anno=2026,
            logger=mock_logger,
        )
        assert res == []


# ==============================================================================
# EDGE CASE 5: Patron Integration Failures
# ==============================================================================

@pytest.mark.asyncio
async def test_edge_case_patron_integration_failures(sample_locality, sample_municipio, mock_logger):
    """Verify process_locality resilience when patron finder fails or returns invalid data."""
    docs = [{"fuente": "web_municipio", "texto": "Fiestas de Verano del 1 al 5 de agosto."}]

    # 1. Patron task raises Exception
    with patch("main.search_locality_media", new_callable=AsyncMock) as mock_media, \
         patch("main.search_locality_web", new_callable=AsyncMock) as mock_web, \
         patch("main.cargar_documentos_rrss", return_value=[]), \
         patch("main.obtener_patron", side_effect=RuntimeError("Patron DB offline")):
        mock_media.return_value = docs
        mock_web.return_value = []

        fiestas = await process_locality(
            localidad=sample_locality,
            municipio=sample_municipio,
            anno=2026,
            rag_processor=AsyncRAGProcessor(),
            rrss_client=None,
            logger=mock_logger,
        )
        # Should complete without crashing even if patron search failed
        assert isinstance(fiestas, list)

    # 2. fecha_del_patron returning None
    assert fecha_del_patron(None, 2026) is None
    assert fecha_del_patron({"dia": 31, "mes": 4}, 2026) is None

    # 3. integrar_patron with None patron
    res_patron_none = integrar_patron([], None, 2026, sample_locality)
    assert res_patron_none == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

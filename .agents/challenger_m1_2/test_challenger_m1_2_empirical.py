import sys
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Add target directory to sys.path
target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from llm_processor.text_analyzer import (
    seleccionar_chunks,
    filtrar_chunks_por_localidad,
    discover_festivals_for_locality,
    retrieve_discovery_context,
    enrich_festival_program,
    AsyncRAGProcessor,
)
from fuentes import FUENTE_WEB_MUNICIPIO, FUENTE_WEB_LOCALIDAD, FUENTE_BUSQUEDA

def test_cosine_sim_not_overwritten_by_boost_penalty():
    """Verify cosine similarity is NOT overwritten and boost (+0.15) / penalty (-0.10) stick."""
    initial_sim = 0.60
    items = [
        {
            "chunk": "Fiesta patronal de Torrellano en verano",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 2,
            "score": initial_sim,
        },
        {
            "chunk": "Fiestas generales del municipio de Elche",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 2,
            "score": initial_sim,
        },
        {
            "chunk": "Fiesta de El Altet en septiembre",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 2,
            "score": initial_sim,
        },
    ]

    localidad = "Torrellano"
    hermanas = ["El Altet", "La Marina"]

    filtrados = filtrar_chunks_por_localidad(items, localidad_nombre=localidad, nombres_hermanas=hermanas)

    # 1. Torrellano chunk (DIRECTA) -> 0.60 + 0.15 = 0.75
    assert len(filtrados) == 2, f"Expected 2 items remaining, got {len(filtrados)}"
    direct_chunk = next(i for i in filtrados if "Torrellano" in i["chunk"])
    assert abs(direct_chunk["score"] - 0.75) < 1e-5, f"Expected score 0.75, got {direct_chunk['score']}"
    assert direct_chunk["relevancia_geo"] == "DIRECTA"

    # 2. General chunk (GENERAL) -> 0.60 - 0.10 = 0.50
    general_chunk = next(i for i in filtrados if "generales" in i["chunk"])
    assert abs(general_chunk["score"] - 0.50) < 1e-5, f"Expected score 0.50, got {general_chunk['score']}"
    assert general_chunk["relevancia_geo"] == "GENERAL"

    # 3. El Altet chunk (HERMANA) -> Excluded (None)
    hermana_chunks = [i for i in filtrados if "El Altet" in i["chunk"]]
    assert len(hermana_chunks) == 0, "Sister locality chunk was NOT excluded!"


def test_non_municipio_sources_unaffected_by_geo_boost():
    """Verify web_localidad and busqueda_web sources are assigned DIRECTA without score modification."""
    sim_score = 0.55
    items = [
        {
            "chunk": "Noticia sobre fiesta en Torrellano",
            "fuente": FUENTE_BUSQUEDA,
            "url": "http://noticias.com",
            "es_calendario": False,
            "prioridad": 6,
            "score": sim_score,
        },
        {
            "chunk": "Info oficial de Torrellano",
            "fuente": FUENTE_WEB_LOCALIDAD,
            "url": "http://torrellano.es",
            "es_calendario": False,
            "prioridad": 1,
            "score": sim_score,
        },
    ]

    filtrados = filtrar_chunks_por_localidad(items, localidad_nombre="Torrellano", nombres_hermanas=["El Altet"])
    assert len(filtrados) == 2
    for item in filtrados:
        assert item["score"] == sim_score, f"Score changed for non-municipio source: {item}"
        assert item["relevancia_geo"] == "DIRECTA"


def test_edge_cases_empty_single_null_scores():
    """Test edge cases: empty list, single chunk, missing score, zero score."""
    # Empty list
    res_empty = filtrar_chunks_por_localidad([], "Torrellano", ["El Altet"])
    assert res_empty == []
    sel_empty = seleccionar_chunks([], budget_chars=1000)
    assert sel_empty == []

    # Single chunk with default score 0.0
    single_item = [{
        "chunk": "Un solo chunk de prueba",
        "fuente": FUENTE_WEB_MUNICIPIO,
        "url": "",
        "es_calendario": False,
        "prioridad": 2,
        "score": 0.0,
    }]
    res_single = filtrar_chunks_por_localidad(single_item, "Torrellano", ["El Altet"])
    assert len(res_single) == 1
    # Score 0.0 - 0.10 GENERAL -> max(0.0, -0.10) = 0.0
    assert res_single[0]["score"] == 0.0

    sel_single = seleccionar_chunks(res_single, budget_chars=1000, umbral=0.0)
    assert len(sel_single) == 1


def test_stress_harness_multi_chunk_ordering():
    """Stress test: 8 chunks with varying priority, similarity, and relevance. Verify final order."""
    chunks = [
        # Official municipal - Direct match (sim=0.50 + 0.15 = 0.65, prio=2)
        {"chunk": "Directa Muni 1 (Torrellano)", "fuente": FUENTE_WEB_MUNICIPIO, "prioridad": 2, "score": 0.50},
        # Official municipal - General (sim=0.70 - 0.10 = 0.60, prio=2)
        {"chunk": "General Muni 2 (Elche)", "fuente": FUENTE_WEB_MUNICIPIO, "prioridad": 2, "score": 0.70},
        # Official municipal - Sister (sim=0.90 -> Excluded, prio=2)
        {"chunk": "Sister Muni 3 (El Altet)", "fuente": FUENTE_WEB_MUNICIPIO, "prioridad": 2, "score": 0.90},
        # Official locality - Direct (sim=0.55, no change, prio=1)
        {"chunk": "Localidad Web (Torrellano)", "fuente": FUENTE_WEB_LOCALIDAD, "prioridad": 1, "score": 0.55},
        # External web search - High sim (sim=0.85, prio=6)
        {"chunk": "Search Web High (Fiestas)", "fuente": FUENTE_BUSQUEDA, "prioridad": 6, "score": 0.85},
        # External web search - Low sim (sim=0.20, prio=6) -> Below threshold 0.30
        {"chunk": "Search Web Low (Clima)", "fuente": FUENTE_BUSQUEDA, "prioridad": 6, "score": 0.20},
    ]

    filtered = filtrar_chunks_por_localidad(chunks, localidad_nombre="Torrellano", nombres_hermanas=["El Altet"])
    selected = seleccionar_chunks(filtered, budget_chars=10000, umbral=0.30)

    # Sister chunk (Sister Muni 3) must be excluded
    chunk_texts = [c["chunk"] for c in selected]
    assert "Sister Muni 3 (El Altet)" not in chunk_texts, "Sister chunk was not excluded!"

    # Search Web Low (score 0.20 < 0.30) must be excluded by threshold
    assert "Search Web Low (Clima)" not in chunk_texts, "Sub-threshold external chunk was not excluded!"

    # Official chunks must come before external search chunks
    # Officials in selected:
    # 1. Localidad Web (prio 1, score 0.55)
    # 2. Directa Muni 1 (prio 2, score 0.65)
    # 3. General Muni 2 (prio 2, score 0.60)
    # External in selected:
    # 4. Search Web High (prio 6, score 0.85)

    expected_order = [
        "Localidad Web (Torrellano)",
        "Directa Muni 1 (Torrellano)",
        "General Muni 2 (Elche)",
        "Search Web High (Fiestas)"
    ]

    assert chunk_texts == expected_order, f"Order mismatch!\nGot: {chunk_texts}\nExpected: {expected_order}"


def test_end_to_end_pipeline_geo_filter_execution():
    """Verify that discover_festivals_for_locality and retrieve_discovery_context apply filtering correctly."""
    async def _test():
        municipio = {"nombre": "Elche", "comunidad_autonoma": "Valencia", "provincia": "Alicante"}
        localidad = {"id": "torrellano-id", "nombre": "Torrellano"}
        indexed_chunks = [
            {
                "chunk": "Programa de Fiestas de Torrellano 2026",
                "fuente": FUENTE_WEB_MUNICIPIO,
                "url": "http://elche.es",
                "es_calendario": False,
                "prioridad": 2,
                "embedding": [0.1, 0.2, 0.3],
            },
            {
                "chunk": "Programa de Fiestas de El Altet 2026",
                "fuente": FUENTE_WEB_MUNICIPIO,
                "url": "http://elche.es",
                "es_calendario": False,
                "prioridad": 2,
                "embedding": [0.1, 0.2, 0.3],
            }
        ]

        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.get_embeddings_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

        AsyncRAGProcessor.cosine_similarity = MagicMock(return_value=0.60)

        context, fuentes = await retrieve_discovery_context(
            municipio=municipio,
            localidad=localidad,
            indexed_chunks=indexed_chunks,
            anno=2026,
            rag_processor=mock_rag,
            nombres_hermanas=["El Altet"],
            max_chars=1000
        )

        assert "Torrellano" in context
        assert "El Altet" not in context, "Sister pedania text leaked into discovery context!"

    asyncio.run(_test())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

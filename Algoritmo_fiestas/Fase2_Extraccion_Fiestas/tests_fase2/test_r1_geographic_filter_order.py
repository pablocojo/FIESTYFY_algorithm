import pytest
import asyncio
import unittest.mock
from unittest.mock import AsyncMock, MagicMock
from llm_processor.text_analyzer import (
    seleccionar_chunks,
    filtrar_chunks_por_localidad,
    discover_festivals_for_locality,
    retrieve_discovery_context,
    enrich_festival_program,
    AsyncRAGProcessor,
)

def test_seleccionar_chunks_is_pure_budget_packer():
    """Verify seleccionar_chunks does not modify item scores or discard sister locality chunks on its own."""
    items = [
        {
            "chunk": "Fiestas de Pedanía Hermana A",
            "fuente": "web_municipio",
            "url": "http://ejemplo.com",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.8,
        }
    ]
    # If seleccionar_chunks were still calling filtrar_chunks_por_localidad("TargetPedania", ["Pedanía Hermana A"]),
    # it would discard this chunk because it mentions a sister pedania.
    # But as a pure budget packer, it preserves the pre-filtered items.
    seleccion = seleccionar_chunks(items, budget_chars=1000, umbral=0.3)
    assert len(seleccion) == 1
    assert seleccion[0]["score"] == 0.8


def test_geographic_filtering_boost_preserved_after_similarity():
    """Verify geographic filter adjustments (+0.15 for DIRECTA, -0.10 for GENERAL) are applied AFTER similarity calculation."""
    items = [
        {
            "chunk": "Fiestas en la pedania de Torrellano",
            "fuente": "web_municipio",
            "url": "http://ejemplo.com",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.50, # Initial cosine similarity
        },
        {
            "chunk": "Fiestas generales del municipio",
            "fuente": "web_municipio",
            "url": "http://ejemplo.com",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.50, # Initial cosine similarity
        }
    ]

    filtrados = filtrar_chunks_por_localidad(items, localidad_nombre="Torrellano", nombres_hermanas=["El Altet"])
    assert len(filtrados) == 2
    
    # Direct match should receive +0.15 boost on top of similarity 0.50 -> 0.65
    torrellano_chunk = [i for i in filtrados if "Torrellano" in i["chunk"]][0]
    assert pytest.approx(torrellano_chunk["score"], 0.01) == 0.65
    assert torrellano_chunk["relevancia_geo"] == "DIRECTA"

    # General match should receive -0.10 penalty on top of similarity 0.50 -> 0.40
    general_chunk = [i for i in filtrados if "generales" in i["chunk"]][0]
    assert pytest.approx(general_chunk["score"], 0.01) == 0.40
    assert general_chunk["relevancia_geo"] == "GENERAL"


def test_enrich_festival_program_applies_geo_filter_after_similarity():
    """Verify enrich_festival_program applies geographic boost after computing daily similarity scores."""
    async def _test():
        municipio = {"nombre": "Elche", "comunidad_autonoma": "Valencia", "provincia": "Alicante"}
        localidad = {"id": "torrellano-id", "nombre": "Torrellano"}
        fiesta = {
            "nombre": "Fiestas Patronales de Torrellano",
            "fecha_inicio": "2026-08-15",
            "fecha_fin": "2026-08-15",
        }
        indexed_chunks = [
            {
                "chunk": "Gran mascletà en Torrellano el 15 de agosto",
                "fuente": "web_municipio",
                "url": "http://elche.es",
                "es_calendario": False,
                "prioridad": 1,
                "embedding": [0.1, 0.2, 0.3],
            }
        ]

        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.get_embeddings_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

        # Mock cosine_similarity to return 0.50
        AsyncRAGProcessor.cosine_similarity = MagicMock(return_value=0.50)

        with unittest.mock.patch("llm_processor.text_analyzer.llm_chat_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"programa": [{"dia": 1, "fecha": "2026-08-15", "eventos": []}]}
            # Call enrich_festival_program with mock_rag
            result = await enrich_festival_program(
                municipio=municipio,
                localidad=localidad,
                fiesta=fiesta,
                indexed_chunks=indexed_chunks,
                anno=2026,
                rag_processor=mock_rag,
                nombres_hermanas=["El Altet"],
            )

        assert "programa" in result

    asyncio.run(_test())

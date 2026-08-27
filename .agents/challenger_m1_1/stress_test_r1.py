"""
Stress Test Harness for Requirement R1 Verification
Tests geographic filtering order, score preservation, edge cases, ordering, and daily loop isolation.
"""

import sys
import os
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Add target directory to sys.path
sys.path.insert(0, os.path.abspath("Algoritmo_fiestas/Fase2_Extraccion_Fiestas"))

from llm_processor.text_analyzer import (
    seleccionar_chunks,
    filtrar_chunks_por_localidad,
    discover_festivals_for_locality,
    retrieve_discovery_context,
    enrich_festival_program,
    AsyncRAGProcessor,
)

def test_seleccionar_chunks_no_internal_geo_filter():
    """Verify seleccionar_chunks does not invoke geographic filter or modify scores."""
    items = [
        {
            "chunk": "Fiestas en la pedania hermana El Altet",
            "fuente": "web_municipio",
            "url": "http://ejemplo.com",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.85,
        }
    ]
    # If seleccionar_chunks ran geo filtering, it would remove this item.
    # It must NOT remove it or change its score.
    selected = seleccionar_chunks(items, budget_chars=1000, umbral=0.3)
    assert len(selected) == 1
    assert selected[0]["score"] == 0.85


def test_similarity_score_not_overwritten_by_geo_filter():
    """
    Verify pipeline order:
    Similarity calculation -> Geo Filter (+0.15 / -0.10) -> Budget selection.
    Check score flip: Chunk B (lower initial similarity, DIRECTA) beats Chunk A (higher initial similarity, GENERAL).
    """
    items = [
        {
            "chunk": "Noticias generales del municipio de Elche sin mencionar pedanias",
            "fuente": "web_municipio",
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.52,  # Higher base similarity
        },
        {
            "chunk": "Programa oficial de fiestas de Torrellano en Elche",
            "fuente": "web_municipio",
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.45,  # Lower base similarity
        },
        {
            "chunk": "Programa de fiestas de la pedania hermana El Altet",
            "fuente": "web_municipio",
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 1,
            "score": 0.90,  # High similarity but sister pedania
        }
    ]

    filtered = filtrar_chunks_por_localidad(
        items=items,
        localidad_nombre="Torrellano",
        nombres_hermanas=["El Altet", "La Marina"]
    )

    # Sister pedania chunk (El Altet) must be excluded completely
    chunks_text = [i["chunk"] for i in filtered]
    assert not any("El Altet" in t for t in chunks_text)
    assert len(filtered) == 2

    # Check scores after geo filter
    general_item = [i for i in filtered if "generales" in i["chunk"]][0]
    directa_item = [i for i in filtered if "Torrellano" in i["chunk"]][0]

    # GENERAL: 0.52 - 0.10 = 0.42
    assert pytest.approx(general_item["score"], 0.01) == 0.42
    # DIRECTA: 0.45 + 0.15 = 0.60
    assert pytest.approx(directa_item["score"], 0.01) == 0.60

    # Budget select with budget = 80 chars (Torrellano chunk is 50 chars, General chunk is 63 chars)
    # Directa item (score 0.60, length 50) MUST be selected.
    # General item (score 0.42, length 63) won't fit (50 + 63 = 113 > 80).
    selected = seleccionar_chunks(filtered, budget_chars=80, umbral=0.40)
    assert len(selected) == 1
    assert "Torrellano" in selected[0]["chunk"]
    assert selected[0]["score"] == 0.60


def test_edge_cases_matrix():
    """Verify robustness on edge cases: empty list, single chunk, missing score, embedding=None."""
    # 1. Empty list
    assert filtrar_chunks_por_localidad([], "Torrellano", ["El Altet"]) == []
    assert seleccionar_chunks([], budget_chars=1000) == []

    # 2. Single chunk
    single = [{
        "chunk": "Fiestas de Torrellano",
        "fuente": "web_municipio",
        "score": 0.5,
        "prioridad": 1,
        "es_calendario": False
    }]
    res_filt = filtrar_chunks_por_localidad(single, "Torrellano", ["El Altet"])
    assert len(res_filt) == 1
    assert res_filt[0]["score"] == 0.65

    # 3. Missing score key in dict
    no_score = [{
        "chunk": "Fiestas generales del municipio",
        "fuente": "web_municipio",
        "prioridad": 1,
        "es_calendario": False
    }]
    res_no_score = filtrar_chunks_por_localidad(no_score, "Torrellano", ["El Altet"])
    assert len(res_no_score) == 1
    # score defaults to 0.0 - 0.10 -> max(0.0, -0.10) = 0.0
    assert res_no_score[0]["score"] == 0.0

    # 4. Sister locality in web_localidad (should NOT be excluded because source is local, not web_municipio)
    web_local = [{
        "chunk": "Mención a El Altet en la propia web de Torrellano",
        "fuente": "web_localidad",
        "score": 0.7,
        "prioridad": 1,
        "es_calendario": False
    }]
    res_local = filtrar_chunks_por_localidad(web_local, "Torrellano", ["El Altet"])
    assert len(res_local) == 1
    assert res_local[0]["score"] == 0.7  # Score unchanged for non-web_municipio

    # 5. nombres_hermanas is None or []
    res_none_hermanas = filtrar_chunks_por_localidad(single, "Torrellano", None)
    assert len(res_none_hermanas) == 1


def test_score_none_handling():
    """Test behavior when score key is explicitly set to None."""
    item_score_none = [{
        "chunk": "Fiestas generales",
        "fuente": "web_municipio",
        "score": None,
        "prioridad": 1,
        "es_calendario": False
    }]
    
    # Check if filtrar_chunks_por_localidad handles score=None safely
    try:
        res = filtrar_chunks_por_localidad(item_score_none, "Torrellano", ["El Altet"])
        print("Score=None in filtrar_chunks_por_localidad result:", res)
    except TypeError as e:
        print(f"Observed TypeError with score=None: {e}")
        # Mark this as a known flaw/edge case finding
        pytest.fail(f"filtrar_chunks_por_localidad lacks None check for item['score']: {e}")


def test_enrich_festival_program_daily_isolation():
    """
    Verify enrich_festival_program creates per-day copies of items and applies geo boost AFTER daily similarity,
    without mutating the original indexed_chunks across iterations.
    """
    async def _run():
        municipio = {"nombre": "Elche", "comunidad_autonoma": "Valencia", "provincia": "Alicante"}
        localidad = {"id": "torrellano-id", "nombre": "Torrellano"}
        fiesta = {
            "nombre": "Fiestas Patronales de Torrellano",
            "fecha_inicio": "2026-08-15",
            "fecha_fin": "2026-08-16",
        }
        original_chunk = {
            "chunk": "Gran mascletà y verbena en Torrellano el 15 de agosto",
            "fuente": "web_municipio",
            "url": "http://elche.es",
            "es_calendario": False,
            "prioridad": 1,
            "embedding": [0.1, 0.2, 0.3],
        }
        indexed_chunks = [dict(original_chunk)]

        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.get_embeddings_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]])

        # Daily cosine similarities
        AsyncRAGProcessor.cosine_similarity = MagicMock(return_value=0.50)

        mock_llm = AsyncMock()
        mock_llm.return_value = {
            "programa": [
                {"dia": 1, "fecha": "2026-08-15", "eventos": [{"hora": "12:00", "descripcion": "Mascletà"}]},
                {"dia": 2, "fecha": "2026-08-16", "eventos": [{"hora": "23:00", "descripcion": "Verbena"}]}
            ]
        }

        with pytest.MonkeyPatch.context() as m:
            m.setattr("llm_processor.text_analyzer.llm_chat_json", mock_llm)

            res = await enrich_festival_program(
                municipio=municipio,
                localidad=localidad,
                fiesta=fiesta,
                indexed_chunks=indexed_chunks,
                anno=2026,
                rag_processor=mock_rag,
                nombres_hermanas=["El Altet"],
            )

            assert "programa" in res
            assert len(res["programa"]) == 2

        # Confirm original indexed_chunks item was NOT mutated with modified scores
        assert "score" not in indexed_chunks[0]

    asyncio.run(_run())


if __name__ == "__main__":
    pytest.main([__file__, "-vv"])

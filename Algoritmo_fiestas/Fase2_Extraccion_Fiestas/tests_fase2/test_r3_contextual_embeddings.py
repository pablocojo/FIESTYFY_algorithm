import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from llm_processor.text_analyzer import index_document_chunks, AsyncRAGProcessor

def test_index_document_chunks_uses_raw_chunk_for_embeddings():
    async def run():
        # Mock RAG processor
        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.chunk_size = 500
        mock_rag.batch_size = 10
        
        captured_texts = []
        
        async def fake_get_embeddings_batch(session, texts):
            captured_texts.extend(texts)
            return [[0.1, 0.2, 0.3] for _ in texts]
            
        mock_rag.get_embeddings_batch = AsyncMock(side_effect=fake_get_embeddings_batch)
        
        sample_doc = {
            "texto": "Programa de Fiestas 2026. Dia 15 de Agosto: Procesion y grandes fuegos artificiales.",
            "fuente": "web_oficial",
            "url": "https://municipio.es/fiestas"
        }
        
        results = await index_document_chunks(
            rag_processor=mock_rag,
            documentos=[sample_doc],
            municipio_nombre="Amurrio",
            localidad_nombre="Amurrio"
        )
        
        assert len(results) > 0
        assert len(captured_texts) == len(results)
        
        for item, captured_text in zip(results, captured_texts):
            # Verification 1: get_embeddings_batch received raw `chunk`, NOT `chunk_contextualizado`
            assert captured_text == item["chunk"]
            assert captured_text != item["chunk_contextualizado"]
            assert "[FUENTE:" not in captured_text
            
            # Verification 2: Item dictionary retains chunk_contextualizado
            assert "chunk_contextualizado" in item
            assert "[FUENTE:" in item["chunk_contextualizado"]
            assert item["embedding"] == [0.1, 0.2, 0.3]

    asyncio.run(run())

def test_index_document_chunks_empty_docs():
    async def run():
        res = await index_document_chunks(None, [])
        assert res == []

    asyncio.run(run())

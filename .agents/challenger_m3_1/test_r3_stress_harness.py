import sys
import os
import asyncio
import numpy as np

# Add target directory to sys.path
target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from llm_processor.text_analyzer import index_document_chunks, AsyncRAGProcessor, ensamblar_contexto
from unittest.mock import AsyncMock, MagicMock
import math

def cosine_similarity(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def dummy_text_embedding(text: str) -> list[float]:
    """
    Simple deterministic TF-IDF style vector generator for empirical vector space testing.
    Vocabulary dimension = 20.
    """
    vocab = [
        "procesion", "san", "roque", "fuegos", "artificiales", "fiestas", "programa",
        "empadronamiento", "certificado", "tasas", "administrativas", "padron",
        "oficial", "municipio", "amurrio", "aviso", "fuente", "pedania", "general", "saratxo"
    ]
    words = text.lower().replace(":", " ").replace("/", " ").replace("[", " ").replace("]", " ").replace("(", " ").replace(")", " ").split()
    vec = [float(words.count(w)) for w in vocab]
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = (vec / norm).tolist()
    return vec

async def test_r3_embedding_input_purity():
    print("=== STRESS TEST 1: Embedding Input Purity & Batching ===")
    mock_rag = MagicMock(spec=AsyncRAGProcessor)
    mock_rag.chunk_size = 200
    mock_rag.batch_size = 5

    captured_batches = []

    async def fake_get_embeddings_batch(session, texts):
        captured_batches.append(list(texts))
        return [dummy_text_embedding(t) for t in texts]

    mock_rag.get_embeddings_batch = AsyncMock(side_effect=fake_get_embeddings_batch)

    # Generate 12 sample documents
    docs = []
    for i in range(12):
        docs.append({
            "texto": f"Documento {i}: Este es el programa de fiestas de San Roque con eventos y actividades numero {i}.",
            "fuente": "web_municipio",
            "url": f"https://amurrio.org/doc{i}"
        })

    results = await index_document_chunks(
        rag_processor=mock_rag,
        documentos=docs,
        municipio_nombre="Amurrio",
        localidad_nombre="Saratxo"
    )

    assert len(results) >= 12, f"Expected at least 12 chunks, got {len(results)}"
    
    # Check total dispatches and batch size
    total_embedded_texts = sum(len(b) for b in captured_batches)
    assert total_embedded_texts == len(results), f"Mismatch: embedded {total_embedded_texts} vs results {len(results)}"
    
    # Verify each captured text is EXACTLY item['chunk'] and DOES NOT contain administrative header
    for item in results:
        # 1. Raw chunk in items
        raw_chunk = item["chunk"]
        context_chunk = item["chunk_contextualizado"]
        
        assert "[FUENTE:" not in raw_chunk, f"Header leaked into raw chunk: {raw_chunk}"
        assert "[AVISO:" not in raw_chunk, f"Header leaked into raw chunk: {raw_chunk}"
        assert "[FUENTE:" in context_chunk, f"Header missing from contextual chunk: {context_chunk}"
        assert raw_chunk in context_chunk, f"Raw chunk missing from contextual chunk"
        assert item["embedding"] is not None, "Embedding was not populated"
        assert len(item["embedding"]) == 20, "Embedding vector length invalid"

    # Flatten captured texts
    all_captured = [txt for b in captured_batches for txt in b]
    for idx, item in enumerate(results):
        assert all_captured[idx] == item["chunk"], f"Captured text at {idx} mismatch"
        assert all_captured[idx] != item["chunk_contextualizado"], f"Contextual text used for embedding at {idx}!"

    print("-> STRESS TEST 1 PASSED: Embeddings strictly use raw chunk, batching verified, chunk_contextualizado preserved in metadata.")

async def test_r3_vector_distortion_impact():
    print("\n=== STRESS TEST 2: Vector Space Distortion Mitigation ===")
    
    query = "programa de fiestas del municipio de amurrio"
    query_vec = dummy_text_embedding(query)
    
    raw_festival = "Programa de Fiestas: Procesión de San Roque y fuegos artificiales en la plaza."
    raw_admin = "Certificado de empadronamiento: Tasas administrativas de expedición y trámites."
    
    header = "[FUENTE: Web oficial del municipio de Amurrio (https://amurrio.org) | AVISO: Este contenido pertenece al MUNICIPIO en general, NO específicamente a la pedanía Saratxo]"
    
    contextual_festival = f"{header}\n{raw_festival}"
    contextual_admin = f"{header}\n{raw_admin}"

    # Embeddings WITH fix (raw chunks)
    emb_raw_fest = dummy_text_embedding(raw_festival)
    emb_raw_admin = dummy_text_embedding(raw_admin)
    
    sim_raw_fest = cosine_similarity(query_vec, emb_raw_fest)
    sim_raw_admin = cosine_similarity(query_vec, emb_raw_admin)
    
    # Embeddings WITHOUT fix (contextual chunks)
    emb_ctx_fest = dummy_text_embedding(contextual_festival)
    emb_ctx_admin = dummy_text_embedding(contextual_admin)
    
    sim_ctx_fest = cosine_similarity(query_vec, emb_ctx_fest)
    sim_ctx_admin = cosine_similarity(query_vec, emb_ctx_admin)

    print(f"  Query: '{query}'")
    print(f"  RAW chunk similarity (WITH FIX):")
    print(f"    - Festival chunk: {sim_raw_fest:.4f}")
    print(f"    - Admin chunk:    {sim_raw_admin:.4f}")
    print(f"    - Delta (Fest - Admin): {sim_raw_fest - sim_raw_admin:.4f}")

    print(f"  CONTEXTUAL chunk similarity (WITHOUT FIX):")
    print(f"    - Festival chunk: {sim_ctx_fest:.4f}")
    print(f"    - Admin chunk:    {sim_ctx_admin:.4f}")
    print(f"    - Delta (Fest - Admin): {sim_ctx_fest - sim_ctx_admin:.4f}")

    # Empirical validation:
    # 1. Similarity to raw admin chunk is 0.0 because raw admin contains no query terms.
    # 2. Contextual admin chunk receives false similarity > 0.0 because the header injected 'municipio' and 'amurrio'.
    # 3. Computing embeddings on raw chunk eliminates this false positive contamination.
    assert sim_raw_admin == 0.0, f"Raw admin chunk should have 0 similarity to query, got {sim_raw_admin}"
    assert sim_ctx_admin > 0.0, f"Contextual admin chunk erroneously received similarity {sim_ctx_admin} due to header noise!"
    assert (sim_raw_fest - sim_raw_admin) > (sim_ctx_fest - sim_ctx_admin), "Raw chunking did not provide better signal-to-noise ratio"

    print("-> STRESS TEST 2 PASSED: Pure raw chunk embedding eliminates false-positive header similarity noise.")

async def main():
    await test_r3_embedding_input_purity()
    await test_r3_vector_distortion_impact()
    print("\nALL EMPIRICAL STRESS TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())

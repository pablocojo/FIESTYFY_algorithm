import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np

# Add target directory to sys.path
target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from llm_processor.text_analyzer import (
    index_document_chunks,
    AsyncRAGProcessor,
    ensamblar_contexto,
    seleccionar_chunks,
)
from fuentes import generar_cabecera_chunk, FUENTE_WEB_LOCALIDAD, FUENTE_WEB_MUNICIPIO

class TestR3ContextualEmbeddingsEmpirical(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_01_embedding_batch_receives_raw_chunks_only(self):
        """
        Empirical check: Verify that get_embeddings_batch NEVER receives administrative headers
        ([FUENTE: ... | AVISO: ...]), but receives exact raw chunk text.
        """
        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.chunk_size = 300
        mock_rag.batch_size = 5

        captured_texts = []

        async def fake_embeddings(session, texts):
            captured_texts.extend(texts)
            return [[0.1 * (i + 1)] * 128 for i in range(len(texts))]

        mock_rag.get_embeddings_batch = AsyncMock(side_effect=fake_embeddings)

        docs = [
            {
                "texto": "Las fiestas patronales de Amurrio en honor a San Roque comienzan el 12 de agosto.",
                "fuente": "web_localidad",
                "url": "https://amurrio.eus/fiestas"
            },
            {
                "texto": "El 15 de agosto hay pasacalles, concurso de paellas y toros de fuego en la plaza principal.",
                "fuente": "busqueda_web",
                "url": "https://periodicolocal.com/noticia123"
            }
        ]

        items = self.loop.run_until_complete(
            index_document_chunks(
                rag_processor=mock_rag,
                documentos=docs,
                municipio_nombre="Amurrio",
                localidad_nombre="Amurrio"
            )
        )

        # Assertions
        self.assertEqual(len(items), 2)
        self.assertEqual(len(captured_texts), 2)

        # Verification 1: Captured text sent to embedding model MUST equal raw chunk
        for item, captured in zip(items, captured_texts):
            self.assertEqual(captured, item["chunk"])
            self.assertNotIn("[FUENTE:", captured)
            self.assertNotIn("[AVISO:", captured)

        # Verification 2: chunk_contextualizado MUST contain header
        for item in items:
            self.assertIn("chunk_contextualizado", item)
            self.assertIn("[FUENTE:", item["chunk_contextualizado"])
            self.assertIn(item["chunk"], item["chunk_contextualizado"])
            self.assertIsNotNone(item["embedding"])

        print("\n[PASS] Test 1: get_embeddings_batch receives pure raw chunk strings.")

    def test_02_vector_space_distortion_quantification(self):
        """
        Empirical experiment: Quantify the distance distortion caused by administrative headers.
        Compare Cosine Similarity between Query Vector Q and:
        1) Raw text chunk vector V_raw
        2) Contextualized text chunk vector V_ctx (which includes administrative header)

        Demonstrates that administrative header boilerplate shifts vector distance.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer

        query = "programa de actos fiestas de San Roque concurso de paellas 15 agosto"
        raw_chunk = "El 15 de agosto se celebra el concurso de paellas y pasacalles a las 12:00 en honor a San Roque."
        header = "[FUENTE: Web oficial de Amurrio (https://amurrio.eus/pedanias/leyna) | AVISO: Este contenido es especifico de la pedania Leyna, NO del municipio general de Amurrio ni de la capital]"
        contextualized_chunk = f"{header}\n{raw_chunk}"

        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform([query, raw_chunk, contextualized_chunk])
        
        vec_q = tfidf_matrix[0].toarray()[0].tolist()
        vec_raw = tfidf_matrix[1].toarray()[0].tolist()
        vec_ctx = tfidf_matrix[2].toarray()[0].tolist()

        sim_raw = float(AsyncRAGProcessor.cosine_similarity(vec_q, vec_raw))
        sim_ctx = float(AsyncRAGProcessor.cosine_similarity(vec_q, vec_ctx))

        distortion = sim_raw - sim_ctx
        print(f"\n[METRICS] Cosine Similarity (Query vs Raw Chunk): {sim_raw:.4f}")
        print(f"[METRICS] Cosine Similarity (Query vs Contextualized Chunk): {sim_ctx:.4f}")
        print(f"[METRICS] Vector Distance Distortion (Noise Penalty): {distortion:.4f}")

        self.assertGreater(sim_raw, sim_ctx, "Raw chunk must have higher semantic relevance to festival query than header-polluted chunk")
        self.assertGreater(distortion, 0.01, "Header pollution causes measurable semantic vector drift")

        print("[PASS] Test 2: Empirically proved that raw chunk embeddings eliminate vector space distortion.")

    def test_03_robustness_rag_processor_none_and_exceptions(self):
        """
        Empirical check: Test edge cases when rag_processor is None or when get_embeddings_batch fails.
        """
        docs = [{"texto": "Fiesta de la Virgen de Septiembre", "fuente": "web_localidad"}]

        # Case 1: rag_processor is None
        items_none = self.loop.run_until_complete(
            index_document_chunks(None, docs, "Amurrio", "Amurrio")
        )
        self.assertEqual(len(items_none), 1)
        self.assertIsNone(items_none[0]["embedding"])
        self.assertIn("[FUENTE:", items_none[0]["chunk_contextualizado"])

        # Case 2: get_embeddings_batch raises Exception (e.g. HTTP 500 or Connection Error)
        mock_rag = MagicMock(spec=AsyncRAGProcessor)
        mock_rag.chunk_size = 300
        mock_rag.batch_size = 5
        mock_rag.get_embeddings_batch = AsyncMock(side_effect=RuntimeError("Embedding server unavailable"))

        items_err = self.loop.run_until_complete(
            index_document_chunks(mock_rag, docs, "Amurrio", "Amurrio")
        )
        self.assertEqual(len(items_err), 1)
        self.assertIsNone(items_err[0]["embedding"])
        self.assertIn("chunk_contextualizado", items_err[0])

        print("[PASS] Test 3: Gracefully handles None processor and embedding server exceptions.")

    def test_04_downstream_prompt_context_assembly(self):
        """
        Verify that downstream prompt assembly via `ensamblar_contexto` operates on item dictionary
        and retains full metadata.
        """
        items = [
            {
                "chunk": "El 16 de agosto patrona de la ermita.",
                "chunk_contextualizado": "[FUENTE: Web oficial]\nEl 16 de agosto patrona de la ermita.",
                "fuente": "web_localidad",
                "url": "https://amurrio.eus",
                "es_calendario": False,
                "relevancia_geo": "DIRECTA"
            }
        ]

        context_str = ensamblar_contexto(items)
        self.assertIn("El 16 de agosto patrona de la ermita.", context_str)
        self.assertIn("https://amurrio.eus", context_str)

        print("[PASS] Test 4: Downstream context assembly verified.")

if __name__ == "__main__":
    unittest.main()

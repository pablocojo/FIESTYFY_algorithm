"""
Extended empirical test suite for fuentes.py and scraper/google_search.py
Written by Challenger 1 (.agents/challenger_1)
"""

import sys
import unittest
import unittest.mock
import asyncio

TARGET_DIR = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)

import fuentes
from scraper import google_search


class TestFuentesDeepEdgeCases(unittest.TestCase):

    def test_fuente_base_non_string(self):
        """Test fuente_base with integer, float, list, None."""
        self.assertEqual(fuentes.fuente_base(None), "")
        
        for invalid_input in [123, 45.6, ["web_localidad"], {"a": 1}]:
            with self.subTest(input=invalid_input):
                try:
                    res = fuentes.fuente_base(invalid_input)
                    print("[UNEXPECTED PASS] fuente_base(", invalid_input, ") ->", res)
                except Exception as e:
                    print("[EMPIRICAL BUG] fuente_base(", type(invalid_input).__name__, ") raised:", type(e).__name__, e)

    def test_rotulo_fuente_non_string(self):
        """Test rotulo_fuente with non-string inputs."""
        try:
            res = fuentes.rotulo_fuente(123)
            print("[UNEXPECTED PASS] rotulo_fuente(123) ->", res)
        except Exception as e:
            print("[EMPIRICAL BUG] rotulo_fuente(int) raised:", type(e).__name__, e)

    def test_detectar_es_calendario_non_string(self):
        """Test detectar_es_calendario with non-string url or texto."""
        try:
            res = fuentes.detectar_es_calendario(123, None)
            print("[UNEXPECTED PASS] detectar_es_calendario(123, None) ->", res)
        except Exception as e:
            print("[EMPIRICAL BUG] detectar_es_calendario(int, None) raised:", type(e).__name__, e)

    def test_crear_documento_none_values(self):
        """Test crear_documento with None url or None texto."""
        doc = fuentes.crear_documento("web_localidad", None, None)
        self.assertEqual(doc["url"], "")
        self.assertEqual(doc["texto"], "")
        self.assertFalse(doc["es_calendario"])

    def test_ine_code_padding_and_truncation(self):
        """Test 3-digit, 4-digit INE codes, padded & unpadded."""
        # INE code for Albacete is '02'
        # Single digit 2 -> returns '2' instead of '02'
        self.assertEqual(fuentes.get_codigo_provincia("2"), "02")
        # 4 digit INE code 2001 (02001 missing leading zero) -> returns '20' (Gipuzkoa) instead of '02' (Albacete)
        self.assertEqual(fuentes.get_codigo_provincia("2001"), "02")


class TestGoogleSearchDeepEdgeCases(unittest.TestCase):

    def test_visited_urls_as_list(self):
        """Test search_locality_web when visited_urls is passed as list instead of set."""
        async def run():
            loc = {"nombre": "Toro"}
            mun = {"nombre": "Toro", "provincia": "Zamora", "comunidad_autonoma": "Castilla y León"}
            visited_urls = [] # Passed a list instead of a set
            
            with unittest.mock.patch("scraper.google_search._fetch_search_results", return_value=[{"titulo": "t", "snippet": "s", "url": "http://test.com"}]):
                with unittest.mock.patch("scraper.google_search._fetch_page_content", return_value="content"):
                    try:
                        res = await google_search.search_locality_web(loc, mun, 2026, visited_urls=visited_urls)
                        print("[SUCCESS] search_locality_web with list visited_urls ->", len(res))
                    except Exception as e:
                        print("[EMPIRICAL BUG] search_locality_web with list visited_urls raised:", type(e).__name__, e)

        asyncio.run(run())

    def test_build_queries_keyword_fallback(self):
        """Test _build_queries when get_language_profile returns custom structure."""
        loc = {"nombre": "Toro"}
        mun = {"nombre": "Toro", "provincia": "Zamora", "comunidad_autonoma": "Castilla y León"}
        queries = google_search._build_queries(loc, mun, 2026)
        print("[DEBUG] Generated queries for Toro:", queries)
        self.assertEqual(len(queries), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

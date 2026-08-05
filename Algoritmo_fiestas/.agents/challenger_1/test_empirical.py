"""
Empirical test suite for fuentes.py and scraper/google_search.py
Written by Challenger 1 (.agents/challenger_1)
"""

import sys
import os
import unittest
import asyncio
from unittest.mock import patch, MagicMock

# Add target codebase directory to sys.path
TARGET_DIR = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if TARGET_DIR not in sys.path:
    sys.path.insert(0, TARGET_DIR)

import fuentes
from scraper.google_search import (
    _build_queries,
    build_media_queries,
    search_locality_web,
    search_locality_media,
)


class TestFuentesEdgeCases(unittest.TestCase):
    
    # --- 1. INE Code Parsing & Short Codes ---
    
    def test_ine_code_single_digit(self):
        """Test how get_codigo_provincia handles single-digit province code '1' vs '01'."""
        code_1 = fuentes.get_codigo_provincia("1")
        code_01 = fuentes.get_codigo_provincia("01")
        code_1004 = fuentes.get_codigo_provincia("1004")
        
        print(f"\n[DEBUG] get_codigo_provincia('1') -> {code_1!r}")
        print(f"[DEBUG] get_codigo_provincia('01') -> {code_01!r}")
        print(f"[DEBUG] get_codigo_provincia('1004') -> {code_1004!r}")
        
        # '1' should map to '01' (Álava), not '1'
        self.assertEqual(code_01, "01")
        # Bug check: get_codigo_provincia("1") returns "1" instead of "01"
        # and get_codigo_provincia("1004") returns "1" instead of "01"
        self.assertEqual(code_1, "01", f"Expected '01' for '1', got {code_1!r}")
        self.assertEqual(code_1004, "01", f"Expected '01' for '1004', got {code_1004!r}")

    def test_medios_prensa_single_digit_ine(self):
        """Test getting media for single digit or short INE code '1' or '1004'."""
        medios_01 = fuentes.get_medios_prensa_por_provincia("01")
        medios_1 = fuentes.get_medios_prensa_por_provincia("1")
        medios_1004 = fuentes.get_medios_prensa_por_provincia("1004")
        
        print(f"[DEBUG] get_medios_prensa('01') -> {medios_01}")
        print(f"[DEBUG] get_medios_prensa('1') -> {medios_1}")
        print(f"[DEBUG] get_medios_prensa('1004') -> {medios_1004}")
        
        self.assertTrue(len(medios_01) > 0, "Province 01 should have press media")
        self.assertEqual(medios_1, medios_01, "Short code '1' failed to fetch press media")
        self.assertEqual(medios_1004, medios_01, "Short INE ID '1004' failed to fetch press media")

    def test_ine_code_invalid(self):
        """Test invalid INE codes (out of 01-52 range, non-numeric, 00)."""
        self.assertIsNone(fuentes.get_codigo_provincia("00"))
        self.assertIsNone(fuentes.get_codigo_provincia("53"))
        self.assertIsNone(fuentes.get_codigo_provincia("99"))
        self.assertIsNone(fuentes.get_codigo_provincia("00101"))
        self.assertIsNone(fuentes.get_codigo_provincia("XYZ"))
        self.assertIsNone(fuentes.get_codigo_provincia(""))
        self.assertIsNone(fuentes.get_codigo_provincia(None))

    def test_non_string_types(self):
        """Test non-string inputs to fuentes functions."""
        # Integer INE code
        self.assertEqual(fuentes.get_codigo_provincia(1), "01")
        self.assertEqual(fuentes.get_codigo_provincia(28), "28")
        
        # Test fuente_base with int/None
        self.assertEqual(fuentes.fuente_base(None), "")
        try:
            res = fuentes.fuente_base(123)
            print(f"[DEBUG] fuente_base(123) -> {res}")
        except Exception as e:
            print(f"[FAIL] fuente_base(123) raised {type(e).__name__}: {e}")

    # --- 2. Unmapped Province IDs & Names ---

    def test_unmapped_province(self):
        """Test behavior with unmapped province IDs or names."""
        self.assertIsNone(fuentes.get_codigo_provincia("ProvinciaFantasma"))
        self.assertEqual(fuentes.get_medios_prensa_por_provincia("ProvinciaFantasma"), [])
        self.assertEqual(fuentes.get_medios_prensa_por_provincia("99"), [])

    # --- 3. Dynamic Province Registration Overrides ---

    def test_dynamic_province_registration_by_name(self):
        """Test register_provincia_medios when called with province name vs code."""
        # Backup original dict
        original_28 = list(fuentes.MEDIOS_PRENSA_POR_PROVINCIA.get("28", []))
        try:
            # Register override by name
            custom_medios = ["madrid_custom_news.es"]
            fuentes.register_provincia_medios("madrid", custom_medios)
            
            medios_by_name = fuentes.get_medios_prensa_por_provincia("madrid")
            medios_by_code = fuentes.get_medios_prensa_por_provincia("28")
            medios_by_lugar_id = fuentes.get_medios_prensa_por_provincia("28001000")
            
            print(f"[DEBUG] Registered by name 'madrid'.")
            print(f"[DEBUG] get_medios_prensa('madrid') -> {medios_by_name}")
            print(f"[DEBUG] get_medios_prensa('28') -> {medios_by_code}")
            print(f"[DEBUG] get_medios_prensa('28001000') -> {medios_by_lugar_id}")
            
            self.assertEqual(medios_by_name, custom_medios)
            self.assertEqual(medios_by_code, custom_medios, "Lookup by code '28' did not reflect override registered by name 'madrid'")
            self.assertEqual(medios_by_lugar_id, custom_medios, "Lookup by lugar_id '28001000' did not reflect override registered by name 'madrid'")
        finally:
            fuentes.MEDIOS_PRENSA_POR_PROVINCIA["28"] = original_28
            if "madrid" in fuentes.MEDIOS_PRENSA_POR_PROVINCIA:
                del fuentes.MEDIOS_PRENSA_POR_PROVINCIA["madrid"]

    def test_dynamic_province_registration_by_code(self):
        """Test register_provincia_medios when called with province code '28'."""
        original_28 = list(fuentes.MEDIOS_PRENSA_POR_PROVINCIA.get("28", []))
        try:
            custom_medios = ["madrid_code_override.es"]
            fuentes.register_provincia_medios("28", custom_medios)
            
            medios_by_code = fuentes.get_medios_prensa_por_provincia("28")
            medios_by_name = fuentes.get_medios_prensa_por_provincia("madrid")
            
            print(f"[DEBUG] Registered by code '28'.")
            print(f"[DEBUG] get_medios_prensa('28') -> {medios_by_code}")
            print(f"[DEBUG] get_medios_prensa('madrid') -> {medios_by_name}")
            
            self.assertEqual(medios_by_code, custom_medios)
            self.assertEqual(medios_by_name, custom_medios, "Lookup by name 'madrid' did not reflect override registered by code '28'")
        finally:
            fuentes.MEDIOS_PRENSA_POR_PROVINCIA["28"] = original_28

    def test_dynamic_province_registration_single_digit(self):
        """Test registering with single digit code '1'."""
        try:
            custom_medios = ["alava_single_digit.es"]
            fuentes.register_provincia_medios("1", custom_medios)
            
            medios_by_1 = fuentes.get_medios_prensa_por_provincia("1")
            medios_by_01 = fuentes.get_medios_prensa_por_provincia("01")
            
            print(f"[DEBUG] Registered by single digit '1'.")
            print(f"[DEBUG] get_medios_prensa('1') -> {medios_by_1}")
            print(f"[DEBUG] get_medios_prensa('01') -> {medios_by_01}")
            
            self.assertEqual(medios_by_01, custom_medios)
        finally:
            if "1" in fuentes.MEDIOS_PRENSA_POR_PROVINCIA:
                del fuentes.MEDIOS_PRENSA_POR_PROVINCIA["1"]


class TestGoogleSearchEdgeCases(unittest.TestCase):

    # --- 1. Empty Place Dictionaries ---

    def test_build_queries_empty_dicts(self):
        """Test _build_queries with empty dictionaries or missing keys."""
        print("\nTesting _build_queries with empty dicts:")
        
        # Test empty localidad and municipio
        try:
            queries = _build_queries({}, {}, 2026)
            print("[SUCCESS] _build_queries ->", queries)
        except Exception as e:
            print("[FAIL] _build_queries raised:", type(e).__name__, e)

    def test_build_queries_none_sitio_web(self):
        """Test _build_queries when sitio_web is None instead of string."""
        print("\nTesting _build_queries with sitio_web=None:")
        loc = {"nombre": "Toro", "sitio_web": None}
        mun = {"nombre": "Toro", "sitio_web": None, "provincia": "Zamora", "comunidad_autonoma": "Castilla y León"}
        
        try:
            queries = _build_queries(loc, mun, 2026)
            print("[SUCCESS] _build_queries with sitio_web=None ->", queries)
        except Exception as e:
            print("[FAIL] _build_queries with sitio_web=None raised:", type(e).__name__, e)

    def test_build_media_queries_empty_dicts(self):
        """Test build_media_queries with empty dictionaries."""
        print("\nTesting build_media_queries with empty dicts:")
        try:
            queries = build_media_queries({}, {}, 2026)
            print("[SUCCESS] build_media_queries ->", queries)
        except Exception as e:
            print("[FAIL] build_media_queries raised:", type(e).__name__, e)

    def test_build_media_queries_none_fields(self):
        """Test build_media_queries with None fields."""
        print("\nTesting build_media_queries with None fields:")
        loc = {"id": None, "nombre": "Toro"}
        mun = {"id": None, "nombre": "Toro", "provincia": None, "comunidad_autonoma": None}
        try:
            queries = build_media_queries(loc, mun, 2026)
            print("[SUCCESS] build_media_queries with None fields ->", queries)
        except Exception as e:
            print("[FAIL] build_media_queries with None fields raised:", type(e).__name__, e)

    def test_build_media_queries_unmapped_province(self):
        """Test build_media_queries with unmapped province ID/name."""
        print("\nTesting build_media_queries with unmapped province:")
        loc = {"id": "99999", "nombre": "PuebloFalso"}
        mun = {"id": "99999", "nombre": "PuebloFalso", "provincia": "ProvinciaFantasma"}
        queries = build_media_queries(loc, mun, 2026)
        print("[DEBUG] build_media_queries for unmapped province ->", queries)
        self.assertEqual(queries, [], "Should return empty list for unmapped province")

    def test_search_locality_web_async_empty_dicts(self):
        """Test async search_locality_web with empty dicts."""
        async def run():
            try:
                res = await search_locality_web({}, {}, 2026)
                print("[SUCCESS] search_locality_web ->", res)
            except Exception as e:
                print("[FAIL] search_locality_web raised:", type(e).__name__, e)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)

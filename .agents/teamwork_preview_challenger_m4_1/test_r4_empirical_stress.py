"""
Empirical Stress Test for Requirement R4 - Social Media Date Filtering
Executed by Challenger 1 for M4 verification.
"""

import sys
import os
import time
from datetime import date, datetime

# Add project directory to sys.path
PROJECT_DIR = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from scraper.social_content import es_fecha_en_ventana, cargar_documentos_rrss, invalidar_cache
import scraper.social_content as social_content


def run_boundary_tests():
    print("--- 1. Boundary & Date Format Tests ---")
    anno = 2026
    
    # Boundary dates for default window (2025-11-01 to 2027-01-31)
    test_cases = [
        ("2025-10-31", False, "One day before window start"),
        ("2025-11-01", True, "Window start date"),
        ("2025-11-02", True, "Day after window start"),
        ("2026-01-01", True, "New Year 2026"),
        ("2026-08-15", True, "Mid year 2026"),
        ("2026-12-31", True, "Year end 2026"),
        ("2027-01-01", True, "New Year 2027"),
        ("2027-01-31", True, "Window end date"),
        ("2027-02-01", False, "One day after window end"),
        ("2024-08-15", False, "Two years prior"),
        ("2028-01-01", False, "Two years future"),
    ]
    
    for dt_str, expected, desc in test_cases:
        res = es_fecha_en_ventana(dt_str, anno=anno)
        assert res == expected, f"FAILED: {desc} ({dt_str}) expected {expected}, got {res}"
        print(f" [PASS] {dt_str} -> {res} ({desc})")

    # Timezone & ISO variations
    iso_cases = [
        ("2025-11-01T00:00:00Z", True),
        ("2025-10-31T23:59:59+02:00", False),
        ("2027-01-31T23:59:59Z", True),
        ("2027-02-01T00:00:00+00:00", False),
        ("2026-06-15 12:00:00", True),
    ]
    for dt_str, expected in iso_cases:
        res = es_fecha_en_ventana(dt_str, anno=anno)
        assert res == expected, f"FAILED: ISO test ({dt_str}) expected {expected}, got {res}"
        print(f" [PASS] {dt_str} (ISO) -> {res}")

    # Fallback cases for malformed/missing dates
    fallback_cases = [
        None,
        "",
        "   ",
        "invalid-date",
        "2026/05/20",
        "15-08-2026",
        123456,
        True,
        [],
    ]
    for fb in fallback_cases:
        res = es_fecha_en_ventana(fb, anno=anno)
        assert res is True, f"FAILED: Fallback test for {fb} expected True, got {res}"
        print(f" [PASS] Fallback for {repr(fb)} -> {res}")


def run_mutation_and_isolation_tests():
    print("\n--- 2. Cache Mutation & Struct Isolation Tests ---")
    localidad = {"id": "loc-test-mut", "nombre": "Pueblo Mutacion"}
    municipio = {"id": "mun-test-mut", "nombre": "Municipio Mutacion"}

    original_post = {
        "texto": "Post festivo 2026",
        "fecha": "2026-07-20",
        "es_programa": True,
        "texto_programa": "Actos festivos de verano",
    }
    
    datos_cache = {
        "loc-test-mut": {
            "instagram": [original_post]
        }
    }
    
    social_content._cache = datos_cache
    docs = cargar_documentos_rrss(localidad, municipio, anno=2026)
    
    assert len(docs) == 1, "Expected 1 document"
    # Verify post dict in cache was mutated to include fecha_publicacion
    assert "fecha_publicacion" in original_post, "fecha_publicacion key must be populated"
    assert original_post["fecha_publicacion"] == "2026-07-20"
    print(" [PASS] fecha_publicacion field successfully preserved/backfilled in cache dictionary.")


def run_benchmark():
    print("\n--- 3. Performance Benchmark Test ---")
    dates = [
        "2026-08-15",
        "2025-11-01T10:00:00Z",
        "2024-05-10",
        "invalid_date",
        None,
    ] * 20000 # 100,000 items

    t0 = time.time()
    for d in dates:
        es_fecha_en_ventana(d, anno=2026)
    elapsed = time.time() - t0
    print(f" [PASS] Evaluated 100,000 date strings in {elapsed:.4f} seconds ({100000/elapsed:.0f} ops/sec)")
    assert elapsed < 5.0, "Benchmark failed: date filtering took too long!"


if __name__ == "__main__":
    print("Starting Empirical Challenger Tests for Requirement R4...")
    run_boundary_tests()
    run_mutation_and_isolation_tests()
    run_benchmark()
    print("\nALL EMPIRICAL CHALLENGER TESTS PASSED SUCCESSFULLY!")

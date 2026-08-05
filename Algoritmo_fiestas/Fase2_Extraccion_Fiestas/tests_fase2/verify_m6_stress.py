"""
Adversarial stress-test script for Milestone M6 Execution Metrics.
"""

import sys
import os
import time
import math
import logging

# Ensure project root is in sys.path
PROJECT_ROOT = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import generar_informe_ejecucion, registrar_informe_resumen
from scraper.google_search import (
    get_failed_searches_count,
    reset_search_metrics,
    registrar_busqueda_fallida,
)


def test_edge_case_zero_division_and_ratios():
    print("Testing ratio edge cases...")
    
    # 1. 0 extracted, 0 estimated
    m1 = generar_informe_ejecucion([], [], [], 0.0, 0)
    assert m1["ratio_extraidas_vs_estimadas"] == "0:0"
    assert m1["ratio_numerico"] == 0.0

    # 2. 5 extracted, 0 estimated
    f_ext_only = [{"id": f"f{i}", "lugar_id": "loc1", "es_estimada": False} for i in range(5)]
    m2 = generar_informe_ejecucion(f_ext_only, ["loc1"], ["mun1"], 10.0, 0)
    assert "Sin estimadas" in m2["ratio_extraidas_vs_estimadas"]
    assert math.isinf(m2["ratio_numerico"])

    # 3. 0 extracted, 5 estimated
    f_est_only = [{"id": f"f{i}", "lugar_id": "loc1", "es_estimada": True} for i in range(5)]
    m3 = generar_informe_ejecucion(f_est_only, ["loc1"], ["mun1"], 10.0, 0)
    assert m3["ratio_extraidas_vs_estimadas"] == "0.00"
    assert m3["ratio_numerico"] == 0.0

    # 4. 7 extracted, 2 estimated -> 3.50
    f_mixed = (
        [{"id": f"f{i}", "lugar_id": "loc1", "es_estimada": False} for i in range(7)] +
        [{"id": f"e{i}", "lugar_id": "loc1", "es_estimada": True} for i in range(2)]
    )
    m4 = generar_informe_ejecucion(f_mixed, ["loc1"], ["mun1"], 10.0, 0)
    assert m4["ratio_extraidas_vs_estimadas"] == "3.50"
    assert m4["ratio_numerico"] == 3.5

    print("[PASS] Ratio edge cases passed.")


def test_edge_case_malformed_fiestas_and_sources():
    print("Testing malformed fiesta dictionaries and source counting...")
    
    # Valid dict sources and string sources
    fiestas_valid = [
        {"id": "f1", "lugar_id": "loc1", "es_estimada": False, "fuentes": ["web_municipio"]},
        {"id": "f2", "lugar_id": "loc1", "es_estimada": False, "fuentes": [{"fuente": "web_localidad:sub"}]},
    ]
    m_valid = generar_informe_ejecucion(fiestas_valid, ["loc1"], ["mun1"], 10.0, 0)
    assert dict(m_valid["fuentes_mas_contribuyentes"]) == {"web_municipio": 1, "web_localidad": 1}

    # Malformed fuentes containing None
    fiestas_buggy = [
        {"id": "f5", "lugar_id": "loc2", "es_estimada": False, "fuentes": [None]},
    ]
    try:
        generar_informe_ejecucion(fiestas_buggy, ["loc2"], ["mun1"], 10.0, 0)
        print("[FAIL] Expected AttributeError when sources contain None, but none was raised!")
    except AttributeError as e:
        print(f"[CONFIRMED BUG] AttributeError correctly caught when fuentes contains None: {e}")

    print("[PASS] Malformed fuentes vulnerability test executed.")


def test_localities_zero_festivals_calculation():
    print("Testing localities zero festival calculation...")
    
    # Case A: duplicate localities in localidades_completadas
    locs = ["loc1", "loc1", "loc2", "loc3", "loc3", "loc4"] # 4 unique localities
    fiestas = [{"id": "f1", "lugar_id": "loc1"}, {"id": "f2", "lugar_id": "loc3"}]
    
    m = generar_informe_ejecucion(fiestas, locs, ["mun1"], 10.0, 0)
    assert m["total_localidades_procesadas"] == 4
    assert m["localidades_con_cero_fiestas"] == 2 # loc2 and loc4 have 0 festivals
    
    # Case B: fiesta has lugar_id not present in localidades_completadas
    fiestas_extra = [{"id": "f1", "lugar_id": "loc99"}]
    m_extra = generar_informe_ejecucion(fiestas_extra, ["loc1"], ["mun1"], 10.0, 0)
    assert m_extra["total_localidades_procesadas"] == 1
    assert m_extra["localidades_con_cero_fiestas"] == 1 # loc1 has 0 festivals
    
    print("[PASS] Zero festival calculation passed.")


def test_performance_large_dataset():
    print("Testing performance on large dataset (8,000 localities, 50,000 festivals)...")
    
    t0 = time.time()
    large_locs = [f"loc_{i}" for i in range(8000)]
    large_muns = [f"mun_{i}" for i in range(8131)]
    large_fiestas = []
    
    for i in range(50000):
        is_est = (i % 10 == 0) # 10% estimated
        loc_id = f"loc_{i % 6000}" # 2000 localities will have 0 festivals
        large_fiestas.append({
            "id": f"f_{i}",
            "lugar_id": loc_id,
            "es_estimada": is_est,
            "fuentes": ["web_municipio" if i % 2 == 0 else "busqueda_web"],
        })
        
    m = generar_informe_ejecucion(large_fiestas, large_locs, large_muns, 1234.56, 42)
    t1 = time.time()
    
    assert m["total_fiestas"] == 50000
    assert m["fiestas_extraidas"] == 45000
    assert m["fiestas_estimadas"] == 5000
    assert m["ratio_extraidas_vs_estimadas"] == "9.00"
    assert m["total_localidades_procesadas"] == 8000
    assert m["localidades_con_cero_fiestas"] == 2000
    assert m["municipios_procesados"] == 8131
    assert abs(m["tiempo_medio_por_municipio"] - (1234.56 / 8131)) < 1e-5
    
    print(f"[PASS] Large dataset processed in {t1 - t0:.4f}s.")


def test_informe_resumen_formatting():
    print("Testing registrar_informe_resumen formatting output...")
    
    logger = logging.getLogger("test_formatter")
    logger.setLevel(logging.INFO)
    
    # Formatter test with infinite ratio (sin estimadas)
    m_inf = {
        "total_fiestas": 100,
        "fiestas_extraidas": 100,
        "fiestas_estimadas": 0,
        "ratio_extraidas_vs_estimadas": "100:0 (Sin estimadas)",
        "total_localidades_procesadas": 50,
        "localidades_con_cero_fiestas": 5,
        "fuentes_mas_contribuyentes": [("web_municipio", 60), ("busqueda_web", 40)],
        "busquedas_bloqueadas_fallidas": 0,
        "municipios_procesados": 10,
        "tiempo_total_segundos": 200.0,
        "tiempo_medio_por_municipio": 20.0,
    }
    
    report_text = registrar_informe_resumen(m_inf, logger)
    assert "100:0 (Sin estimadas)" in report_text
    assert "web_municipio: 60, busqueda_web: 40" in report_text
    assert "Tiempo medio por municipio: 20.00s" in report_text
    assert "INFORME RESUMEN DE EJECUCIÓN (MÉTRICAS R6)" in report_text

    print("[PASS] Formatting test passed.")


if __name__ == "__main__":
    test_edge_case_zero_division_and_ratios()
    test_edge_case_malformed_fiestas_and_sources()
    test_localities_zero_festivals_calculation()
    test_performance_large_dataset()
    test_informe_resumen_formatting()
    print("\n>>> ALL STRESS TESTS COMPLETED! <<<")

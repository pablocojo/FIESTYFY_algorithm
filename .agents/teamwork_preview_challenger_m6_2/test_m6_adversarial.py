import sys
import os
import math
import logging

# Add Phase 2 target dir to sys.path
target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from main import generar_informe_ejecucion, registrar_informe_resumen

def run_tests():
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)

    test_results = []

    def log_test(name, passed, details, metrics=None, report_str=None):
        test_results.append({
            "name": name,
            "passed": passed,
            "details": details,
            "metrics": metrics,
            "report_str": report_str
        })
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {details}")

    # Case 1: Absolute Zero State (0 localities, 0 festivals, 0 municipalities, 0.0s time)
    try:
        m1 = generar_informe_ejecucion(
            fiestas=[],
            localidades_completadas=[],
            municipios_completados=[],
            tiempo_total_segundos=0.0,
            busquedas_fallidas=0
        )
        r1 = registrar_informe_resumen(m1, logger)
        assert m1["total_fiestas"] == 0
        assert m1["fiestas_extraidas"] == 0
        assert m1["fiestas_estimadas"] == 0
        assert m1["ratio_extraidas_vs_estimadas"] == "0:0"
        assert m1["ratio_numerico"] == 0.0
        assert m1["total_localidades_procesadas"] == 0
        assert m1["localidades_con_cero_fiestas"] == 0
        assert m1["municipios_procesados"] == 0
        assert m1["tiempo_medio_por_municipio"] == 0.0
        log_test("Case 1: Absolute Zero State", True, "Handled zero state without division by zero or errors.", m1, r1)
    except Exception as e:
        log_test("Case 1: Absolute Zero State", False, f"Exception raised: {e}")

    # Case 2: Zero Estimated Festivals (extraidas > 0, estimadas == 0)
    try:
        fiestas_c2 = [
            {"lugar_id": "loc1", "es_estimada": False, "fuentes": ["https://ejemplo.es/fiestas"]}
        ]
        m2 = generar_informe_ejecucion(
            fiestas=fiestas_c2,
            localidades_completadas=["loc1"],
            municipios_completados=["mun1"],
            tiempo_total_segundos=12.5,
            busquedas_fallidas=0
        )
        r2 = registrar_informe_resumen(m2, logger)
        assert m2["fiestas_extraidas"] == 1
        assert m2["fiestas_estimadas"] == 0
        assert m2["ratio_extraidas_vs_estimadas"] == "1:0 (Sin estimadas)"
        assert m2["ratio_numerico"] == float("inf")
        assert m2["tiempo_medio_por_municipio"] == 12.5
        log_test("Case 2: Zero Estimated Festivals", True, "Ratio string and numeric value infinity handled correctly.", m2, r2)
    except Exception as e:
        log_test("Case 2: Zero Estimated Festivals", False, f"Exception raised: {e}")

    # Case 3: Zero Extraidas, Only Estimadas (extraidas == 0, estimadas > 0)
    try:
        fiestas_c3 = [
            {"lugar_id": "loc1", "es_estimada": True},
            {"lugar_id": "loc2", "es_estimada": True}
        ]
        m3 = generar_informe_ejecucion(
            fiestas=fiestas_c3,
            localidades_completadas=["loc1", "loc2"],
            municipios_completados=["mun1"],
            tiempo_total_segundos=20.0,
            busquedas_fallidas=2
        )
        r3 = registrar_informe_resumen(m3, logger)
        assert m3["fiestas_extraidas"] == 0
        assert m3["fiestas_estimadas"] == 2
        assert m3["ratio_extraidas_vs_estimadas"] == "0.00"
        assert m3["ratio_numerico"] == 0.0
        log_test("Case 3: Zero Extraidas, Only Estimadas", True, "Handled 0 extraidas with estimadas > 0 without error.", m3, r3)
    except Exception as e:
        log_test("Case 3: Zero Extraidas, Only Estimadas", False, f"Exception raised: {e}")

    # Case 4: Extreme execution time (0 seconds, negative time, huge time)
    try:
        # Zero execution time with 5 municipalities
        m4_zero = generar_informe_ejecucion([], ["loc1"], ["m1", "m2", "m3", "m4", "m5"], 0.0)
        r4_zero = registrar_informe_resumen(m4_zero, logger)
        assert m4_zero["tiempo_medio_por_municipio"] == 0.0

        # Negative time
        m4_neg = generar_informe_ejecucion([], ["loc1"], ["m1"], -15.5)
        r4_neg = registrar_informe_resumen(m4_neg, logger)
        assert m4_neg["tiempo_medio_por_municipio"] == -15.5

        # Massive time (1e12 seconds)
        m4_huge = generar_informe_ejecucion([], ["loc1"], ["m1"], 1e12)
        r4_huge = registrar_informe_resumen(m4_huge, logger)
        assert m4_huge["tiempo_medio_por_municipio"] == 1e12

        log_test("Case 4: Extreme Execution Times", True, "Zero, negative, and huge execution times handled correctly.", m4_huge, r4_huge)
    except Exception as e:
        log_test("Case 4: Extreme Execution Times", False, f"Exception raised: {e}")

    # Case 5: 100% Localities with 0 Fiestas (All processed localities have no festivals)
    try:
        m5 = generar_informe_ejecucion(
            fiestas=[],
            localidades_completadas=["loc1", "loc2", "loc3", "loc4", "loc5"],
            municipios_completados=["mun1", "mun2"],
            tiempo_total_segundos=100.0,
            busquedas_fallidas=10
        )
        r5 = registrar_informe_resumen(m5, logger)
        assert m5["total_localidades_procesadas"] == 5
        assert m5["localidades_con_cero_fiestas"] == 5
        assert m5["municipios_procesados"] == 2
        assert m5["tiempo_medio_por_municipio"] == 50.0
        log_test("Case 5: 100% Localities with 0 Fiestas", True, "Calculated zero festival localities correctly.", m5, r5)
    except Exception as e:
        log_test("Case 5: 100% Localities with 0 Fiestas", False, f"Exception raised: {e}")

    # Case 6: Edge case - None/Empty/Missing sources or fields in fiestas
    try:
        fiestas_c6 = [
            {"lugar_id": "loc1", "es_estimada": False, "fuentes": None},
            {"lugar_id": "loc2", "es_estimada": False, "fuentes": []},
            {"lugar_id": "loc3", "es_estimada": False, "fuentes": [{"fuente": "web_oficial_localidad"}]},
            {"lugar_id": "loc4", "es_estimada": False}, # missing fuentes
            {"es_estimada": False} # missing lugar_id
        ]
        m6 = generar_informe_ejecucion(
            fiestas=fiestas_c6,
            localidades_completadas=["loc1", "loc2", "loc3", "loc4"],
            municipios_completados=["mun1"],
            tiempo_total_segundos=5.0
        )
        r6 = registrar_informe_resumen(m6, logger)
        log_test("Case 6: Missing/None Sources & Fields", True, "Handled missing fuentes/lugar_id fields without crash.", m6, r6)
    except Exception as e:
        log_test("Case 6: Missing/None Sources & Fields", False, f"Exception raised: {e}")

    # Case 7: Duplicate entries in localidades_completadas or municipios_completados
    try:
        m7 = generar_informe_ejecucion(
            fiestas=[{"lugar_id": "loc1", "es_estimada": False, "fuentes": ["web_oficial"]}],
            localidades_completadas=["loc1", "loc1", "loc2", "loc2"],
            municipios_completados=["mun1", "mun1", "mun2"],
            tiempo_total_segundos=30.0
        )
        r7 = registrar_informe_resumen(m7, logger)
        assert m7["total_localidades_procesadas"] == 2
        assert m7["localidades_con_cero_fiestas"] == 1
        assert m7["municipios_procesados"] == 2
        assert m7["tiempo_medio_por_municipio"] == 15.0
        log_test("Case 7: Duplicate Localities/Municipalities in set/list", True, "Deduplicated set structures accurately.", m7, r7)
    except Exception as e:
        log_test("Case 7: Duplicate Localities/Municipalities in set/list", False, f"Exception raised: {e}")

    return test_results

if __name__ == "__main__":
    results = run_tests()
    print("\n--- TEST SUMMARY ---")
    all_passed = all(r["passed"] for r in results)
    print(f"All tests passed: {all_passed}")

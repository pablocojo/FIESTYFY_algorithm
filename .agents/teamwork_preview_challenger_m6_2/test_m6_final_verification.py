import sys
import os
import logging
import json

target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from main import generar_informe_ejecucion, registrar_informe_resumen

def run_verification_suite():
    logger = logging.getLogger("m6_verification")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)

    test_runs = []

    # Scenario 1: Zero Localities & Zero Municipalities
    s1_metrics = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=[],
        municipios_completados=[],
        tiempo_total_segundos=0.0,
        busquedas_fallidas=0
    )
    s1_text = registrar_informe_resumen(s1_metrics, logger)
    test_runs.append(("Scenario 1: Zero Localities & Municipalities", s1_metrics, s1_text))

    # Scenario 2: Zero Estimated Festivals (100% Extracted)
    s2_fiestas = [
        {"lugar_id": "LOC_001", "es_estimada": False, "fuentes": ["web_localidad"]},
        {"lugar_id": "LOC_002", "es_estimada": False, "fuentes": ["web_municipio", "rrss_localidad:instagram"]}
    ]
    s2_metrics = generar_informe_ejecucion(
        fiestas=s2_fiestas,
        localidades_completadas=["LOC_001", "LOC_002"],
        municipios_completados=["MUN_001"],
        tiempo_total_segundos=45.2,
        busquedas_fallidas=0
    )
    s2_text = registrar_informe_resumen(s2_metrics, logger)
    test_runs.append(("Scenario 2: Zero Estimated Festivals", s2_metrics, s2_text))

    # Scenario 3: Zero Extracted Festivals (100% Estimated Patrón)
    s3_fiestas = [
        {"lugar_id": "LOC_001", "es_estimada": True},
        {"lugar_id": "LOC_002", "es_estimada": True}
    ]
    s3_metrics = generar_informe_ejecucion(
        fiestas=s3_fiestas,
        localidades_completadas=["LOC_001", "LOC_002"],
        municipios_completados=["MUN_001"],
        tiempo_total_segundos=18.7,
        busquedas_fallidas=1
    )
    s3_text = registrar_informe_resumen(s3_metrics, logger)
    test_runs.append(("Scenario 3: Zero Extracted Festivals", s3_metrics, s3_text))

    # Scenario 4: Extreme Execution Times (0s, Negative, Huge)
    s4_t0 = generar_informe_ejecucion([], ["LOC_001"], ["MUN_001"], 0.0)
    s4_tneg = generar_informe_ejecucion([], ["LOC_001"], ["MUN_001"], -12.34)
    s4_thuge = generar_informe_ejecucion([], ["LOC_001"], ["MUN_001"], 315360000.0)
    s4_text = registrar_informe_resumen(s4_thuge, logger)
    test_runs.append(("Scenario 4: Extreme Execution Times", s4_thuge, s4_text))

    # Scenario 5: High Locality Count with 0 Festivals
    s5_metrics = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=[f"LOC_{i:03d}" for i in range(1, 101)],
        municipios_completados=[f"MUN_{i:02d}" for i in range(1, 11)],
        tiempo_total_segundos=1200.0,
        busquedas_fallidas=5
    )
    s5_text = registrar_informe_resumen(s5_metrics, logger)
    test_runs.append(("Scenario 5: 100 Locs with 0 Festivals", s5_metrics, s5_text))

    print("\nSUITE COMPLETE.")

if __name__ == "__main__":
    run_verification_suite()

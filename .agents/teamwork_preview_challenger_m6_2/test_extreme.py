import sys
import os
import math
import logging

target_dir = r"c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase2_Extraccion_Fiestas"
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from main import generar_informe_ejecucion, registrar_informe_resumen

def test_extreme_floats_and_types():
    logger = logging.getLogger("test_extreme")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)

    print("--- TESTING EXTREME FLOATS AND TYPES ---")

    # 1. NaN execution time
    try:
        m_nan = generar_informe_ejecucion([], ["loc1"], ["m1"], float("nan"))
        r_nan = registrar_informe_resumen(m_nan, logger)
        print("[PASS] NaN time handled without crash.")
    except Exception as e:
        print(f"[FAIL] NaN time exception: {e}")

    # 2. Inf execution time
    try:
        m_inf = generar_informe_ejecucion([], ["loc1"], ["m1"], float("inf"))
        r_inf = registrar_informe_resumen(m_inf, logger)
        print("[PASS] Inf time handled without crash.")
    except Exception as e:
        print(f"[FAIL] Inf time exception: {e}")

    # 3. Tuple input for localidades/municipios
    try:
        m_tup = generar_informe_ejecucion([], ("loc1", "loc2"), ("m1", "m2"), 10.0)
        r_tup = registrar_informe_resumen(m_tup, logger)
        assert m_tup["total_localidades_procesadas"] == 2
        assert m_tup["municipios_procesados"] == 2
        print("[PASS] Tuple input handled successfully.")
    except Exception as e:
        print(f"[FAIL] Tuple input exception: {e}")

    # 4. Dictionary elements with odd/unexpected sources
    try:
        fiestas_odd = [
            {"lugar_id": "loc1", "es_estimada": False, "fuentes": [123, None, "web_localidad:custom"]},
            {"lugar_id": "loc1", "es_estimada": False, "fuentes": [{"fuente": None}, {"fuente": "rrss_municipio:facebook"}]}
        ]
        m_odd = generar_informe_ejecucion(fiestas_odd, ["loc1"], ["m1"], 5.0)
        r_odd = registrar_informe_resumen(m_odd, logger)
        print("[PASS] Odd sources handled successfully.")
    except Exception as e:
        print(f"[FAIL] Odd sources exception: {e}")

if __name__ == "__main__":
    test_extreme_floats_and_types()

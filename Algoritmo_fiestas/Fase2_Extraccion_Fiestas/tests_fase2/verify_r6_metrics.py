"""
Script de verificación aislado para el Requisito R6 (Métricas de Ejecución).
Verifica el cálculo de métricas y la generación/formateo del informe resumen.
"""

import sys
import os
import logging

# Asegurar que el directorio raíz del proyecto está en sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from main import generar_informe_ejecucion, registrar_informe_resumen
from scraper.google_search import (
    get_failed_searches_count,
    reset_search_metrics,
    registrar_busqueda_fallida,
)


def test_metricas_calculo_basico():
    """Verifica el cálculo correcto de métricas con un conjunto de datos estándar."""
    fiestas_mock = [
        # 3 Fiestas extraídas (1 de web_municipio, 1 de web_localidad, 1 de busqueda_web)
        {"id": "f1", "lugar_id": "loc1", "nombre": "Fiesta 1", "es_estimada": False, "fuentes": ["web_municipio"]},
        {"id": "f2", "lugar_id": "loc1", "nombre": "Fiesta 2", "es_estimada": False, "fuentes": ["web_localidad"]},
        {"id": "f3", "lugar_id": "loc2", "nombre": "Fiesta 3", "es_estimada": False, "fuentes": ["busqueda_web"]},
        # 1 Fiesta estimada (patrón)
        {"id": "patron-1", "lugar_id": "loc3", "nombre": "San Roque", "es_estimada": True, "origen": "santo_patron"},
    ]

    localidades_completadas = ["loc1", "loc2", "loc3", "loc4", "loc5"]  # loc4 y loc5 tienen 0 fiestas
    municipios_completados = ["mun1", "mun2"]
    tiempo_total = 120.0  # 120 segundos para 2 municipios => 60s/mun
    busquedas_fallidas = 3

    metrics = generar_informe_ejecucion(
        fiestas=fiestas_mock,
        localidades_completadas=localidades_completadas,
        municipios_completados=municipios_completados,
        tiempo_total_segundos=tiempo_total,
        busquedas_fallidas=busquedas_fallidas,
    )

    # 1. Ratio extraídas vs estimadas: 3 extraídas / 1 estimada = 3.00
    assert metrics["total_fiestas"] == 4
    assert metrics["fiestas_extraidas"] == 3
    assert metrics["fiestas_estimadas"] == 1
    assert metrics["ratio_extraidas_vs_estimadas"] == "3.00"
    assert metrics["ratio_numerico"] == 3.0

    # 2. Localidades con 0 fiestas: loc4 y loc5 (2 de 5)
    assert metrics["total_localidades_procesadas"] == 5
    assert metrics["localidades_con_cero_fiestas"] == 2

    # 3. Fuentes más contribuyentes: web_municipio (1), web_localidad (1), busqueda_web (1), santo_patron (1)
    fuentes_dict = dict(metrics["fuentes_mas_contribuyentes"])
    assert fuentes_dict.get("web_municipio") == 1
    assert fuentes_dict.get("web_localidad") == 1
    assert fuentes_dict.get("busqueda_web") == 1
    assert fuentes_dict.get("santo_patron") == 1

    # 4. Búsquedas bloqueadas/fallidas
    assert metrics["busquedas_bloqueadas_fallidas"] == 3

    # 5. Tiempo promedio por municipio: 120s / 2 mun = 60.0s
    assert metrics["municipios_procesados"] == 2
    assert metrics["tiempo_total_segundos"] == 120.0
    assert metrics["tiempo_medio_por_municipio"] == 60.0

    print("[PASS] test_metricas_calculo_basico ok")


def test_metricas_casos_limite():
    """Verifica el comportamiento con listas vacías y 0 estimadas/municipios."""
    # Caso A: Sin fiestas estimadas (solo extraídas)
    fiestas_extraidas_solo = [
        {"id": "f1", "lugar_id": "loc1", "nombre": "Fiesta 1", "es_estimada": False, "fuentes": ["web_municipio"]}
    ]
    m_ext = generar_informe_ejecucion(
        fiestas=fiestas_extraidas_solo,
        localidades_completadas=["loc1"],
        municipios_completados=["mun1"],
        tiempo_total_segundos=10.0,
    )
    assert m_ext["fiestas_estimadas"] == 0
    assert m_ext["fiestas_extraidas"] == 1
    assert "Sin estimadas" in m_ext["ratio_extraidas_vs_estimadas"]

    # Caso B: Sin datos (listas vacías)
    m_vacio = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=[],
        municipios_completados=[],
        tiempo_total_segundos=0.0,
    )
    assert m_vacio["total_fiestas"] == 0
    assert m_vacio["ratio_extraidas_vs_estimadas"] == "0:0"
    assert m_vacio["localidades_con_cero_fiestas"] == 0
    assert m_vacio["tiempo_medio_por_municipio"] == 0.0

    print("[PASS] test_metricas_casos_limite ok")


def test_formateo_informe_resumen():
    """Verifica que registrar_informe_resumen formatee correctamente el reporte."""
    metrics = {
        "total_fiestas": 10,
        "fiestas_extraidas": 8,
        "fiestas_estimadas": 2,
        "ratio_extraidas_vs_estimadas": "4.00",
        "total_localidades_procesadas": 6,
        "localidades_con_cero_fiestas": 1,
        "fuentes_mas_contribuyentes": [("web_municipio", 5), ("santo_patron", 2), ("busqueda_web", 1)],
        "busquedas_bloqueadas_fallidas": 2,
        "municipios_procesados": 3,
        "tiempo_total_segundos": 45.0,
        "tiempo_medio_por_municipio": 15.0,
    }

    logger = logging.getLogger("test_r6")
    reporte = registrar_informe_resumen(metrics, logger)

    assert "INFORME RESUMEN DE EJECUCIÓN (MÉTRICAS R6)" in reporte
    assert "Total Fiestas Registradas: 10" in reporte
    assert "Extraídas de fuentes:  8" in reporte
    assert "Estimadas (Patrón):    2" in reporte
    assert "Ratio Extraídas/Estimadas: 4.00" in reporte
    assert "Localidades con 0 Fiestas: 1 (de 6 procesadas)" in reporte
    assert "web_municipio: 5" in reporte
    assert "Búsquedas bloqueadas/fallidas: 2" in reporte
    assert "Tiempo medio por municipio: 15.00s" in reporte

    print("[PASS] test_formateo_informe_resumen ok")


def test_busquedas_fallidas_tracker():
    """Verifica el funcionamiento del contador global de búsquedas fallidas."""
    reset_search_metrics()
    assert get_failed_searches_count() == 0

    registrar_busqueda_fallida()
    registrar_busqueda_fallida()
    assert get_failed_searches_count() == 2

    reset_search_metrics()
    assert get_failed_searches_count() == 0

    print("[PASS] test_busquedas_fallidas_tracker ok")


def test_metricas_fuentes_invalidas_o_none():
    """Verifica que fuentes con elementos None o enteros no causen AttributeError."""
    fiestas_mock = [
        {
            "id": "f_dirty",
            "lugar_id": "loc1",
            "nombre": "Fiesta Fuentes Sucias",
            "es_estimada": False,
            "fuentes": [None, 123, {"fuente": "web_localidad"}, "busqueda_web"],
        }
    ]

    metrics = generar_informe_ejecucion(
        fiestas=fiestas_mock,
        localidades_completadas=["loc1"],
        municipios_completados=["mun1"],
        tiempo_total_segundos=5.0,
    )

    assert metrics["total_fiestas"] == 1
    assert metrics["fiestas_extraidas"] == 1
    fuentes_dict = dict(metrics["fuentes_mas_contribuyentes"])
    assert fuentes_dict.get("desconocida") == 2
    assert fuentes_dict.get("web_localidad") == 1
    assert fuentes_dict.get("busqueda_web") == 1

    print("[PASS] test_metricas_fuentes_invalidas_o_none ok")


def run_all_tests():
    print("Executing verify_r6_metrics tests...")
    test_metricas_calculo_basico()
    test_metricas_casos_limite()
    test_formateo_informe_resumen()
    test_busquedas_fallidas_tracker()
    test_metricas_fuentes_invalidas_o_none()
    print("ALL R6 METRICS TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_all_tests()


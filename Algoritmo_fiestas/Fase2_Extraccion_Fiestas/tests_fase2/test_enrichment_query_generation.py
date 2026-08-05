"""
Test aislado para la generación de consultas de enriquecimiento por día (Requisito R1 / M1 / M3).

Verifica la iteración cronológica de fechas y la generación de queries de enriquecimiento
para escenarios:
- Intra-mes (ej. 10 al 14 de agosto)
- Inter-mes (ej. 28 de agosto al 3 de septiembre)
- Inter-año (ej. 29 de diciembre al 3 de enero)
- Año bisiesto 2028 (29 de febrero) vs año no bisiesto 2026 (28 de febrero)
- Día único
- Cap máximo de 30 días
- Fechas invertidas, malformadas o vacías
- Soporte para dict de fiesta como entrada
"""

import pytest
from llm_processor.text_analyzer import generar_consultas_enriquecimiento


def test_intra_month_query_generation():
    nombre = "Fiestas de San Roque"
    fecha_ini = "2026-08-10"
    fecha_fin = "2026-08-14"

    consultas = generar_consultas_enriquecimiento(nombre, fecha_ini, fecha_fin)

    assert len(consultas) == 5
    fechas = [c[0] for c in consultas]
    queries = [c[1] for c in consultas]

    assert fechas == ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
    assert queries[0] == "Fiestas de San Roque 2026-08-10 programa actos"
    assert queries[-1] == "Fiestas de San Roque 2026-08-14 programa actos"


def test_cross_month_query_generation():
    nombre = "Fiestas de Verano"
    fecha_ini = "2026-08-28"
    fecha_fin = "2026-09-03"

    consultas = generar_consultas_enriquecimiento(nombre, fecha_ini, fecha_fin)

    assert len(consultas) == 7
    fechas = [c[0] for c in consultas]
    esperadas = [
        "2026-08-28",
        "2026-08-29",
        "2026-08-30",
        "2026-08-31",
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
    ]
    assert fechas == esperadas


def test_cross_year_query_generation():
    nombre = "Fiestas de Fin de Año"
    fecha_ini = "2026-12-29"
    fecha_fin = "2027-01-03"

    consultas = generar_consultas_enriquecimiento(nombre, fecha_ini, fecha_fin)

    assert len(consultas) == 6
    fechas = [c[0] for c in consultas]
    esperadas = [
        "2026-12-29",
        "2026-12-30",
        "2026-12-31",
        "2027-01-01",
        "2027-01-02",
        "2027-01-03",
    ]
    assert fechas == esperadas


def test_leap_year_february_query_generation():
    # 1. Año Bisiesto (2028): incluye el 29 de febrero
    consultas_2028 = generar_consultas_enriquecimiento("Carnaval", "2028-02-27", "2028-03-02")
    assert len(consultas_2028) == 5
    fechas_2028 = [c[0] for c in consultas_2028]
    assert fechas_2028 == ["2028-02-27", "2028-02-28", "2028-02-29", "2028-03-01", "2028-03-02"]

    # 2. Año No Bisiesto (2026): no incluye el 29 de febrero
    consultas_2026 = generar_consultas_enriquecimiento("Carnaval", "2026-02-27", "2026-03-02")
    assert len(consultas_2026) == 4
    fechas_2026 = [c[0] for c in consultas_2026]
    assert fechas_2026 == ["2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02"]


def test_single_day_query_generation():
    consultas = generar_consultas_enriquecimiento("Día de la Asunción", "2026-08-15", "2026-08-15")

    assert len(consultas) == 1
    assert consultas[0] == ("2026-08-15", "Día de la Asunción 2026-08-15 programa actos")


def test_excessive_duration_capping():
    consultas = generar_consultas_enriquecimiento(
        "Año Festivo Continuo", "2026-01-01", "2026-12-31", max_dias=30
    )

    assert len(consultas) == 30
    assert consultas[0][0] == "2026-01-01"
    assert consultas[-1][0] == "2026-01-30"


def test_inverted_and_malformed_dates():
    # Fechas invertidas -> auto intercambio
    consultas_inv = generar_consultas_enriquecimiento("Fiesta Invertida", "2026-08-15", "2026-08-10")
    assert len(consultas_inv) == 6
    assert consultas_inv[0][0] == "2026-08-10"
    assert consultas_inv[-1][0] == "2026-08-15"

    # Fecha malformada -> lista vacía
    assert generar_consultas_enriquecimiento("Fiesta Bad", "fecha-invalida", "2026-08-15") == []

    # Fecha vacía -> lista vacía
    assert generar_consultas_enriquecimiento("Fiesta Empty", "", "") == []

    # Nombre None -> lista vacía
    assert generar_consultas_enriquecimiento(None, "2026-08-10", "2026-08-15") == []


def test_dict_input_support():
    fiesta_dict = {
        "nombre": "Fiesta Mayor de Agosto",
        "fecha_inicio": "2026-08-10",
        "fecha_fin": "2026-08-12",
    }
    consultas = generar_consultas_enriquecimiento(fiesta_dict)

    assert len(consultas) == 3
    assert consultas[0] == ("2026-08-10", "Fiesta Mayor de Agosto 2026-08-10 programa actos")
    assert consultas[-1] == ("2026-08-12", "Fiesta Mayor de Agosto 2026-08-12 programa actos")


if __name__ == "__main__":
    test_intra_month_query_generation()
    test_cross_month_query_generation()
    test_cross_year_query_generation()
    test_leap_year_february_query_generation()
    test_single_day_query_generation()
    test_excessive_duration_capping()
    test_inverted_and_malformed_dates()
    test_dict_input_support()
    print("✅ Todos los tests de test_enrichment_query_generation.py pasaron exitosamente.")

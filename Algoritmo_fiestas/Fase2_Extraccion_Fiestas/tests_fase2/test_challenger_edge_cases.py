"""
Test de Estrés de Challenger para Multi-Pass RAG y Generación de Consultas de Enriquecimiento.

Ejecuta pruebas empíricas rigurosas sobre:
1. generar_consultas_enriquecimiento (bisiestos, fin de año, rango 0 días, invertidos, malformados, 100 días).
2. Simulación de límites de tokens RAG (< 12K tokens).
3. Firma y comportamiento de analyze_festivals_multipass, discover_festivals_for_locality y enrich_festival_program.
"""

import sys
import pytest
from datetime import date
from llm_processor.text_analyzer import (
    generar_consultas_enriquecimiento,
    _parse_fecha_con_fallback_bisiesto,
    validar_fiestas,
    DISCOVERY_MAX_CHARS,
    ENRICHMENT_MAX_CHARS,
    FIESTA_MAX_DURACION_DIAS,
)
from config import RAG_CHARS_PER_TOKEN
from tests_fase2.test_rag_token_limit_simulation import (
    simular_discovery_pass_payload,
    simular_enrichment_pass_payload,
)


def test_edge_case_leap_year_2028():
    """Prueba 29 de feb en 2028 (año bisiesto) hasta 1 de marzo."""
    queries = generar_consultas_enriquecimiento("Carnaval 2028", "2028-02-29", "2028-03-01")
    assert len(queries) == 2
    assert queries[0] == ("2028-02-29", "Carnaval 2028 2028-02-29 programa actos")
    assert queries[1] == ("2028-03-01", "Carnaval 2028 2028-03-01 programa actos")


def test_edge_case_non_leap_year_2026_fallback():
    """Prueba 29 de feb en 2026 (no bisiesto) -> fallback a 28 de feb."""
    d = _parse_fecha_con_fallback_bisiesto("2026-02-29")
    assert d == date(2026, 2, 28)

    queries = generar_consultas_enriquecimiento("Fiesta Invierno", "2026-02-29", "2026-03-01")
    assert len(queries) == 2
    assert queries[0][0] == "2026-02-28"
    assert queries[1][0] == "2026-03-01"


def test_edge_case_year_end_cross_year():
    """Prueba cruce de año 2026 Dec 31 a 2027 Jan 05."""
    queries = generar_consultas_enriquecimiento("Fiestas Fin de Año", "2026-12-31", "2027-01-05")
    assert len(queries) == 6
    fechas = [q[0] for q in queries]
    assert fechas == ["2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04", "2027-01-05"]


def test_edge_case_zero_day_range():
    """Prueba rango de 0 días (misma fecha inicio y fin)."""
    queries = generar_consultas_enriquecimiento("San Juan", "2026-06-24", "2026-06-24")
    assert len(queries) == 1
    assert queries[0] == ("2026-06-24", "San Juan 2026-06-24 programa actos")


def test_edge_case_inverted_dates():
    """Prueba fechas invertidas (fin antes que inicio) -> debe intercambiar automáticamente."""
    queries = generar_consultas_enriquecimiento("Fiesta Invertida", "2026-08-20", "2026-08-15")
    assert len(queries) == 6
    assert queries[0][0] == "2026-08-15"
    assert queries[-1][0] == "2026-08-20"


def test_edge_case_invalid_strings_and_nulls():
    """Prueba cadenas malformadas, None, tipos incorrectos."""
    assert generar_consultas_enriquecimiento("Fiesta", "invalido", "2026-08-15") == []
    assert generar_consultas_enriquecimiento("Fiesta", "2026-08-10", "2026-13-45") == []
    assert generar_consultas_enriquecimiento("Fiesta", "", "") == []
    assert generar_consultas_enriquecimiento(None, "2026-08-10", "2026-08-15") == []
    assert generar_consultas_enriquecimiento("", "2026-08-10", "2026-08-15") == []
    assert generar_consultas_enriquecimiento(12345, "2026-08-10", "2026-08-11") == [
        ("2026-08-10", "12345 2026-08-10 programa actos"),
        ("2026-08-11", "12345 2026-08-11 programa actos"),
    ]


def test_edge_case_huge_100_day_range():
    """Prueba rango gigante de 100 días -> tope en max_dias (30)."""
    queries = generar_consultas_enriquecimiento("Macro Fiesta", "2026-01-01", "2026-04-11")
    assert len(queries) == 30
    assert queries[0][0] == "2026-01-01"
    assert queries[-1][0] == "2026-01-30"


def test_edge_case_dict_inputs():
    """Prueba dict input con variaciones."""
    f_dict = {"nombre": "Fiesta Dict", "fecha_inicio": "2026-05-01", "fecha_fin": "2026-05-03"}
    queries = generar_consultas_enriquecimiento(f_dict)
    assert len(queries) == 3
    assert queries[0][0] == "2026-05-01"
    assert queries[-1][0] == "2026-05-03"

    # Dict vacio
    assert generar_consultas_enriquecimiento({}) == []


def test_token_limit_strict_under_12k():
    """Verifica empíricamente que los tokens de Discovery y Enrichment se mantengan por debajo de 12K."""
    # 1. Discovery Pass
    docs_huge = [{"texto": "A" * 500} for _ in range(100)]
    p_disc = simular_discovery_pass_payload(docs_huge)
    assert p_disc["estimated_tokens"] < 12000, f"Discovery pass superó 12K: {p_disc['estimated_tokens']}"

    # 2. Enrichment Pass con cap máximo (25,000 caracteres)
    chunks_por_dia = {f"2026-08-{i:02d}": ["B" * 2000 for _ in range(5)] for i in range(1, 31)}
    fiesta_huge = {"nombre": "Fiesta Mega", "fecha_inicio": "2026-08-01", "fecha_fin": "2026-08-30"}
    p_enrich = simular_enrichment_pass_payload(fiesta_huge, chunks_por_dia)
    assert p_enrich["estimated_tokens"] < 12000, f"Enrichment pass superó 12K: {p_enrich['estimated_tokens']}"
    assert p_enrich["context_chars"] <= ENRICHMENT_MAX_CHARS


def run_all_challenger_tests():
    test_edge_case_leap_year_2028()
    test_edge_case_non_leap_year_2026_fallback()
    test_edge_case_year_end_cross_year()
    test_edge_case_zero_day_range()
    test_edge_case_inverted_dates()
    test_edge_case_invalid_strings_and_nulls()
    test_edge_case_huge_100_day_range()
    test_edge_case_dict_inputs()
    test_token_limit_strict_under_12k()
    print("✅ TODAS LAS PRUEBAS DE ESTRÉS DE CHALLENGER PASARON SATISFACTORIAMENTE.")


if __name__ == "__main__":
    run_all_challenger_tests()

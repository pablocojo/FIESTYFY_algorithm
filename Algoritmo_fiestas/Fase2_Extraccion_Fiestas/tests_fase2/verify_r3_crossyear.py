"""
Verification script for Requirement R3 (Cross-Year Festival Edge Case).
Verifies that _validar_fecha and validar_fiestas accept a festival spanning from Dec 30, 2026 to Jan 2, 2027.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llm_processor.text_analyzer import _validar_fecha, validar_fiestas

LOCALIDAD = {"id": "01049000201", "nombre": "Salinas de Añana"}
ANNO = 2026


def test_validar_fecha_cross_year():
    """Direct verification of _validar_fecha supporting fecha_fin in anno+1 for December start dates."""
    # 1. Start date in December 2026
    assert _validar_fecha("2026-12-30", ANNO) is True

    # 2. End date in January 2027 when start date is in December 2026
    assert _validar_fecha("2027-01-02", ANNO, es_fecha_fin=True, fecha_inicio_str="2026-12-30") is True

    # 3. End date in 2027 should fail if start date was not in December 2026
    assert _validar_fecha("2027-01-02", ANNO, es_fecha_fin=True, fecha_inicio_str="2026-08-10") is False

    # 4. End date in 2028 should fail even with December 2026 start date
    assert _validar_fecha("2028-01-02", ANNO, es_fecha_fin=True, fecha_inicio_str="2026-12-30") is False


def test_validar_fiestas_cross_year_pipeline():
    """Pipeline verification of validar_fiestas accepting Dec 30, 2026 to Jan 2, 2027 festival."""
    fiestas_raw = [
        {
            "id": "fiestas-fin-ano",
            "lugar_id": LOCALIDAD["id"],
            "nombre": "Fiestas de Fin de Año y Reyes",
            "fecha_inicio": "2026-12-30",
            "fecha_fin": "2027-01-02",
            "descripcion": "Verbena de Nochevieja, orquesta y cotillón en la plaza mayor",
        }
    ]

    validas = validar_fiestas(fiestas_raw, LOCALIDAD, ANNO)
    assert len(validas) == 1, f"Expected 1 valid festival, got {len(validas)}"
    assert validas[0]["fecha_inicio"] == "2026-12-30"
    assert validas[0]["fecha_fin"] == "2027-01-02"


if __name__ == "__main__":
    test_validar_fecha_cross_year()
    test_validar_fiestas_cross_year_pipeline()
    print("VERIFY R3 CROSSYEAR PASSED: _validar_fecha and validar_fiestas accept Dec 30, 2026 to Jan 2, 2027 festival.")

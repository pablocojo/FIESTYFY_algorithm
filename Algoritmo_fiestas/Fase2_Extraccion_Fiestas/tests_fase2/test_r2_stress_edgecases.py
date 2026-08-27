"""
Empirical Stress Test Suite for Requirement R2: Capital Exclusion in nombres_hermanas.
Written by Challenger 2 for Milestone 2.
"""

import os
import json
import pytest
from main import agrupar_municipios_y_descendientes, separar_por_tipo
from fuentes import clasificar_relevancia_chunk


def generate_nombres_hermanas(todas_localidades: list[dict], loc: dict) -> list[str]:
    """Exact logic from main.py line 317-320."""
    return [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != loc["id"] and not hermana.get("es_capital")
    ]


def test_standard_municipality_amurrio_scenario():
    """
    Scenario: Amurrio (capital) + Baranbio (pedania) + Lezama (pedania).
    Verifies that for Baranbio:
    - nombres_hermanas contains 'Lezama'
    - nombres_hermanas does NOT contain 'Amurrio' (capital)
    - nombres_hermanas does NOT contain 'Baranbio' (self)
    """
    todas_localidades = [
        {"id": "01002000201", "nombre": "Amurrio", "tipo": "pueblo", "es_capital": True},
        {"id": "01002000202", "nombre": "Baranbio", "tipo": "pueblo", "es_capital": False},
        {"id": "01002000203", "nombre": "Lezama", "tipo": "pueblo", "es_capital": False},
    ]

    # Test for Baranbio
    baranbio = todas_localidades[1]
    hermanas_baranbio = generate_nombres_hermanas(todas_localidades, baranbio)
    assert hermanas_baranbio == ["Lezama"]
    assert "Amurrio" not in hermanas_baranbio
    assert "Baranbio" not in hermanas_baranbio

    # Test chunk classification for Baranbio with capital mention
    chunk_mun = "El Ayuntamiento de Amurrio organiza las fiestas de verano 2026."
    rel_mun = clasificar_relevancia_chunk(chunk_mun, baranbio["nombre"], hermanas_baranbio)
    assert rel_mun == "GENERAL", f"Expected GENERAL but got {rel_mun}"

    # Test chunk classification for Baranbio with sister pedania mention
    chunk_sister = "Las fiestas de Lezama comienzan el 15 de agosto."
    rel_sister = clasificar_relevancia_chunk(chunk_sister, baranbio["nombre"], hermanas_baranbio)
    assert rel_sister is None, f"Expected None (discard) but got {rel_sister}"

    # Test chunk classification for Baranbio with target pedania mention
    chunk_target = "Gran fiesta patronal en Baranbio 2026."
    rel_target = clasificar_relevancia_chunk(chunk_target, baranbio["nombre"], hermanas_baranbio)
    assert rel_target == "DIRECTA", f"Expected DIRECTA but got {rel_target}"


def test_edge_case_single_entity_municipality():
    """
    Scenario: Municipality with only 1 entity total (e.g. single capital or single village).
    nombres_hermanas must be empty [].
    """
    # 1. Single capital
    todas_single_capital = [
        {"id": "28079000101", "nombre": "Madrid", "tipo": "ciudad_grande", "es_capital": True}
    ]
    hermanas = generate_nombres_hermanas(todas_single_capital, todas_single_capital[0])
    assert hermanas == []

    # 2. Single non-capital entity
    todas_single_village = [
        {"id": "10001000101", "nombre": "Abadía", "tipo": "pueblo", "es_capital": False}
    ]
    hermanas_v = generate_nombres_hermanas(todas_single_village, todas_single_village[0])
    assert hermanas_v == []


def test_edge_case_multiple_capitals():
    """
    Scenario: Municipality with multiple capital entities (es_capital: True).
    E.g. co-capitals or compound admin structures.
    Verifies that all capital entities are excluded from pedanías' nombres_hermanas.
    """
    todas_localidades = [
        {"id": "001", "nombre": "Capital Alpha", "tipo": "ciudad_pequena", "es_capital": True},
        {"id": "002", "nombre": "Capital Beta", "tipo": "ciudad_pequena", "es_capital": True},
        {"id": "003", "nombre": "Pedanía Gamma", "tipo": "pueblo", "es_capital": False},
        {"id": "004", "nombre": "Pedanía Delta", "tipo": "pueblo", "es_capital": False},
    ]

    # For Pedanía Gamma
    ped_gamma = todas_localidades[2]
    hermanas_gamma = generate_nombres_hermanas(todas_localidades, ped_gamma)
    assert "Capital Alpha" not in hermanas_gamma
    assert "Capital Beta" not in hermanas_gamma
    assert "Pedanía Gamma" not in hermanas_gamma
    assert hermanas_gamma == ["Pedanía Delta"]

    # For Capital Alpha
    cap_alpha = todas_localidades[0]
    hermanas_alpha = generate_nombres_hermanas(todas_localidades, cap_alpha)
    assert "Capital Alpha" not in hermanas_alpha
    assert "Capital Beta" not in hermanas_alpha
    assert set(hermanas_alpha) == {"Pedanía Gamma", "Pedanía Delta"}


def test_edge_case_missing_es_capital_key():
    """
    Scenario: Entities missing 'es_capital' key (e.g. legacy data or secondary structures).
    hermana.get('es_capital') returns None, so 'not None' evaluates to True (treated as non-capital).
    """
    todas_localidades = [
        {"id": "101", "nombre": "Capital Center", "es_capital": True},
        {"id": "102", "nombre": "Village A"},  # no es_capital key
        {"id": "103", "nombre": "Village B", "es_capital": False},
    ]

    village_a = todas_localidades[1]
    hermanas_a = generate_nombres_hermanas(todas_localidades, village_a)
    assert "Capital Center" not in hermanas_a
    assert "Village A" not in hermanas_a
    assert "Village B" in hermanas_a
    assert hermanas_a == ["Village B"]


def test_edge_case_various_truthy_falsy_es_capital_values():
    """
    Scenario: 'es_capital' values of different types (bool, int, None, empty string).
    """
    todas_localidades = [
        {"id": "1", "nombre": "Cap1", "es_capital": True},
        {"id": "2", "nombre": "Cap2", "es_capital": 1},
        {"id": "3", "nombre": "Ped1", "es_capital": False},
        {"id": "4", "nombre": "Ped2", "es_capital": 0},
        {"id": "5", "nombre": "Ped3", "es_capital": None},
        {"id": "6", "nombre": "Ped4"},  # missing key
    ]

    ped1 = todas_localidades[2]
    hermanas = generate_nombres_hermanas(todas_localidades, ped1)

    # Capitals (True, 1) must be excluded
    assert "Cap1" not in hermanas
    assert "Cap2" not in hermanas

    # Non-capitals (False, 0, None, missing) must be included (except self)
    assert "Ped1" not in hermanas
    assert "Ped2" in hermanas
    assert "Ped3" in hermanas
    assert "Ped4" in hermanas
    assert set(hermanas) == {"Ped2", "Ped3", "Ped4"}


def test_full_dataset_nombres_hermanas_exclusion():
    """
    Empirical validation over real dataset (lugares_espana_actualizado.json).
    Processes all real municipalities and verifies capital exclusion rule across 100% of entities.
    """
    json_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "Fase1_recogida_datos_wiki",
        "lugares_espana_actualizado.json",
    )
    if not os.path.exists(json_path):
        pytest.skip(f"Dataset not found at {json_path}")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        lugares = json.load(f)
    if isinstance(lugares, dict) and "lugares" in lugares:
        lugares = lugares["lugares"]

    municipios, mapa_descendientes = agrupar_municipios_y_descendientes(lugares)
    
    total_localidades_checked = 0
    total_pedanias_checked = 0

    for mun in municipios:
        desc = mapa_descendientes.get(mun["id"], [])
        capitales, otros = separar_por_tipo(desc)
        todas = capitales + otros
        
        capital_names = {c["nombre"] for c in capitales}

        for loc in todas:
            total_localidades_checked += 1
            is_cap = loc.get("es_capital", False)
            hermanas = generate_nombres_hermanas(todas, loc)

            # Rule 1: No capital name of this municipality should be in hermanas
            for cap_name in capital_names:
                assert cap_name not in hermanas, (
                    f"Violation in municipality {mun['nombre']}: Capital '{cap_name}' "
                    f"found in nombres_hermanas of entity '{loc['nombre']}' (id: {loc['id']})"
                )

            # Rule 2: Self name must not be in hermanas
            assert loc["nombre"] not in hermanas, (
                f"Violation in municipality {mun['nombre']}: Self name '{loc['nombre']}' "
                f"found in nombres_hermanas of entity '{loc['nombre']}'"
            )

            if not is_cap:
                total_pedanias_checked += 1
                # Rule 3: For pedanias, all other pedanias in the municipality MUST be present in hermanas
                expected_other_pedanias = {
                    o["nombre"] for o in otros if o["id"] != loc["id"]
                }
                assert set(hermanas) == expected_other_pedanias, (
                    f"Mismatch in municipality {mun['nombre']} for pedania '{loc['nombre']}': "
                    f"Got {hermanas}, expected {expected_other_pedanias}"
                )

    print(f"\n[DATASET VERIFICATION PASSED] Verified {total_localidades_checked} entities across "
          f"{len(municipios)} municipalities ({total_pedanias_checked} pedanías checked). Zero capital leaks.")

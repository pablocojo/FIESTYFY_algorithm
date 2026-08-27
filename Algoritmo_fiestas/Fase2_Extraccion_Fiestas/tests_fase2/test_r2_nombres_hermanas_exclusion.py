"""
Unit tests for Requirement R2: nombres_hermanas Capital Exclusion in main.py.
Verifies that capital entities (es_capital: True) are explicitly excluded from
the list of sister localities (nombres_hermanas).
"""

import pytest
from fuentes import clasificar_relevancia_chunk, FUENTE_WEB_MUNICIPIO


def test_nombres_hermanas_capital_exclusion_logic():
    """
    Test the logic used in main.py to construct nombres_hermanas:
    nombres_hermanas = [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != loc["id"] and not hermana.get("es_capital")
    ]
    """
    capital = {
        "id": "010020001",
        "nombre": "Amurrio",
        "tipo": "pueblo",
        "es_capital": True,
    }
    pedania_1 = {
        "id": "010020002",
        "nombre": "Baranbio",
        "tipo": "pueblo",
        "es_capital": False,
    }
    pedania_2 = {
        "id": "010020003",
        "nombre": "Lezama",
        "tipo": "pueblo",
        "es_capital": False,
    }
    todas_localidades = [capital, pedania_1, pedania_2]

    # Test 1: For pedania_1 (Baranbio), nombres_hermanas must contain Lezama but NOT Amurrio (capital)
    loc = pedania_1
    nombres_hermanas_pedania1 = [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != loc["id"] and not hermana.get("es_capital")
    ]
    assert "Amurrio" not in nombres_hermanas_pedania1
    assert "Lezama" in nombres_hermanas_pedania1
    assert "Baranbio" not in nombres_hermanas_pedania1
    assert nombres_hermanas_pedania1 == ["Lezama"]

    # Test 2: For capital (Amurrio), nombres_hermanas must contain Baranbio and Lezama, but NOT Amurrio
    loc = capital
    nombres_hermanas_capital = [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != loc["id"] and not hermana.get("es_capital")
    ]
    assert "Amurrio" not in nombres_hermanas_capital
    assert "Baranbio" in nombres_hermanas_capital
    assert "Lezama" in nombres_hermanas_capital
    assert set(nombres_hermanas_capital) == {"Baranbio", "Lezama"}


def test_chunk_relevance_classification_with_capital_excluded():
    """
    Verify that with capital excluded from nombres_hermanas, a municipal website chunk
    mentioning the capital name ("Amurrio") is classified as 'GENERAL' for a pedanía ("Baranbio"),
    instead of returning None (discarded).
    """
    # Chunk from amurrio.eus mentioning general municipal festivity in Amurrio
    chunk_text = "El Ayuntamiento de Amurrio presenta el programa general de fiestas de verano 2026."

    # Target pedania is Baranbio.
    # With capital excluded, nombres_hermanas for Baranbio is ['Lezama'] (Amurrio is NOT in list)
    nombres_hermanas_fixed = ["Lezama"]

    relevancia = clasificar_relevancia_chunk(
        chunk_text=chunk_text,
        localidad_nombre="Baranbio",
        nombres_hermanas=nombres_hermanas_fixed,
    )
    # Must NOT be None (previously it returned None because "Amurrio" was in nombres_hermanas)
    assert relevancia == "GENERAL"

    # If chunk mentions another sister pedania ("Lezama"), it should be discarded (return None)
    chunk_sister = "Programa de fiestas patronales de Lezama 2026."
    relevancia_sister = clasificar_relevancia_chunk(
        chunk_text=chunk_sister,
        localidad_nombre="Baranbio",
        nombres_hermanas=nombres_hermanas_fixed,
    )
    assert relevancia_sister is None

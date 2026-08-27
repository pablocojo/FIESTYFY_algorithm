"""
Adversarial and Edge Case Test Suite for Requirement R2 (`nombres_hermanas` Capital Exclusion)
Written by Empirical Challenger 1.
"""

import ast
from pathlib import Path
import pytest
from fuentes import clasificar_relevancia_chunk, FUENTE_WEB_MUNICIPIO


def extract_nombres_hermanas(todas_localidades, target_loc):
    """
    Replicates the exact expression in main.py line 317:
    nombres_hermanas = [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != loc["id"] and not hermana.get("es_capital")
    ]
    """
    return [
        hermana["nombre"]
        for hermana in todas_localidades
        if hermana["id"] != target_loc["id"] and not hermana.get("es_capital")
    ]


def test_main_py_ast_contains_capital_exclusion():
    """Verify via AST parsing that main.py line contains 'not hermana.get("es_capital")'."""
    main_path = Path(__file__).parent.parent / "main.py"
    with open(main_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(main_path))

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ListComp):
            # Check if this listcomp references "es_capital"
            code_snippet = ast.unparse(node)
            if "es_capital" in code_snippet and "hermana" in code_snippet:
                found = True
                assert "not hermana.get('es_capital')" in code_snippet or 'not hermana.get("es_capital")' in code_snippet
                break
    assert found, "Could not find list comprehension with es_capital exclusion in main.py AST"


def test_amurrio_real_world_hierarchy():
    """
    Test Amurrio municipality hierarchy:
    Capital: Amurrio (es_capital: True)
    Pedanias: Baranbio, Lezama, Luyando (es_capital: False)
    """
    amurrio_capital = {"id": "01002000201", "nombre": "Amurrio", "es_capital": True}
    baranbio = {"id": "01002000101", "nombre": "Baranbio", "es_capital": False}
    lezama = {"id": "01002000301", "nombre": "Lezama", "es_capital": False}
    luyando = {"id": "01002000401", "nombre": "Luyando", "es_capital": False}

    todas = [amurrio_capital, baranbio, lezama, luyando]

    # For Baranbio:
    nombres_hermanas = extract_nombres_hermanas(todas, baranbio)
    assert "Amurrio" not in nombres_hermanas, "Capital Amurrio must NOT be in nombres_hermanas for Baranbio"
    assert "Baranbio" not in nombres_hermanas, "Target Baranbio must NOT be in its own nombres_hermanas"
    assert set(nombres_hermanas) == {"Lezama", "Luyando"}

    # For Capital (Amurrio):
    nombres_hermanas_cap = extract_nombres_hermanas(todas, amurrio_capital)
    assert "Amurrio" not in nombres_hermanas_cap
    assert set(nombres_hermanas_cap) == {"Baranbio", "Lezama", "Luyando"}


def test_single_entity_municipality():
    """Municipality with only 1 capital entity and no pedanías."""
    capital = {"id": "28079000101", "nombre": "Madrid", "es_capital": True}
    todas = [capital]

    nombres_hermanas = extract_nombres_hermanas(todas, capital)
    assert nombres_hermanas == [], "Single entity municipality must have empty nombres_hermanas"


def test_multiple_capitals_edge_case():
    """Edge case: municipality marked with multiple capital entities (co-capitals)."""
    cap1 = {"id": "001", "nombre": "CapitalA", "es_capital": True}
    cap2 = {"id": "002", "nombre": "CapitalB", "es_capital": True}
    ped1 = {"id": "003", "nombre": "PedaniaX", "es_capital": False}

    todas = [cap1, cap2, ped1]

    # For PedaniaX: both capitals should be excluded
    nombres_hermanas = extract_nombres_hermanas(todas, ped1)
    assert "CapitalA" not in nombres_hermanas
    assert "CapitalB" not in nombres_hermanas
    assert nombres_hermanas == []

    # For Cap1: Cap2 and Cap1 should be excluded, PedaniaX included
    nombres_hermanas_cap1 = extract_nombres_hermanas(todas, cap1)
    assert nombres_hermanas_cap1 == ["PedaniaX"]


def test_missing_es_capital_key():
    """
    Entities without 'es_capital' key in dictionary (or None) should default to False
    and be included as sister pedanías.
    """
    cap = {"id": "001", "nombre": "CapitalCity", "es_capital": True}
    ped_no_key = {"id": "002", "nombre": "PedaniaNoKey"}  # Missing key
    ped_none = {"id": "003", "nombre": "PedaniaNone", "es_capital": None}  # Key is None
    ped_false = {"id": "004", "nombre": "PedaniaFalse", "es_capital": False}

    todas = [cap, ped_no_key, ped_none, ped_false]

    nombres_hermanas = extract_nombres_hermanas(todas, ped_false)
    assert "CapitalCity" not in nombres_hermanas
    assert "PedaniaNoKey" in nombres_hermanas
    assert "PedaniaNone" in nombres_hermanas
    assert "PedaniaFalse" not in nombres_hermanas


def test_truthy_es_capital_values():
    """Test truthy values (e.g. 1 or 'true') for es_capital."""
    cap_int = {"id": "001", "nombre": "CapInt", "es_capital": 1}
    cap_str = {"id": "002", "nombre": "CapStr", "es_capital": "true"}
    ped = {"id": "003", "nombre": "Pedania", "es_capital": False}

    todas = [cap_int, cap_str, ped]

    nombres_hermanas = extract_nombres_hermanas(todas, ped)
    assert "CapInt" not in nombres_hermanas
    assert "CapStr" not in nombres_hermanas


def test_fuentes_integration_chunk_filtering():
    """
    Integration test verifying chunk classification behavior with R2 logic:
    - Municipal text referring to municipal capital ("Amurrio") is NOT discarded when target is Baranbio.
    - Municipal text referring to sister pedanía ("Lezama") IS discarded (returns None).
    - Text referring to target pedanía ("Baranbio") is kept as ESPECIFICO.
    """
    amurrio_capital = {"id": "01002000201", "nombre": "Amurrio", "es_capital": True}
    baranbio = {"id": "01002000101", "nombre": "Baranbio", "es_capital": False}
    lezama = {"id": "01002000301", "nombre": "Lezama", "es_capital": False}
    todas = [amurrio_capital, baranbio, lezama]

    hermanas_baranbio = extract_nombres_hermanas(todas, baranbio)
    # sisters for Baranbio = ['Lezama']

    # 1. Municipal web chunk mentioning Amurrio (Capital)
    chunk_capital = "El Ayuntamiento de Amurrio publica la guía cultural de fiestas patronales 2026."
    res_cap = clasificar_relevancia_chunk(chunk_capital, "Baranbio", hermanas_baranbio)
    assert res_cap == "GENERAL", f"Expected 'GENERAL', got {res_cap}"

    # 2. Municipal web chunk mentioning Lezama (Sister pedanía)
    chunk_sister = "Las fiestas de San Martin en Lezama contarán con pasacalles y chistularis."
    res_sis = clasificar_relevancia_chunk(chunk_sister, "Baranbio", hermanas_baranbio)
    assert res_sis is None, f"Expected None (discarded), got {res_sis}"

    # 3. Municipal web chunk mentioning Baranbio (Target pedanía)
    chunk_target = "En el barrio de Baranbio se celebran las tradicionales fiestas patronales."
    res_tar = clasificar_relevancia_chunk(chunk_target, "Baranbio", hermanas_baranbio)
    assert res_tar == "DIRECTA", f"Expected 'DIRECTA', got {res_tar}"


def test_full_pipeline_filtering_simulation():
    """
    Simulates filtrar_chunks_por_localidad with pre-fix vs post-fix nombres_hermanas.
    Demonstrates that capital chunks are now retained (GENERAL) instead of dropped (None).
    """
    from llm_processor.text_analyzer import filtrar_chunks_por_localidad

    amurrio_capital = {"id": "01002000201", "nombre": "Amurrio", "es_capital": True}
    baranbio = {"id": "01002000101", "nombre": "Baranbio", "es_capital": False}
    lezama = {"id": "01002000301", "nombre": "Lezama", "es_capital": False}
    todas = [amurrio_capital, baranbio, lezama]

    items = [
        {
            "chunk": "El Ayuntamiento de Amurrio organiza la feria estival de artesania.",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "score": 0.85,
        },
        {
            "chunk": "Fiesta patronal en la pedania de Lezama el proximo fin de semana.",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "score": 0.80,
        },
        {
            "chunk": "Baranbio celebrara sus tradicionales fiestas de San Miguel en Septiembre.",
            "fuente": FUENTE_WEB_MUNICIPIO,
            "score": 0.90,
        },
    ]

    # Pre-fix nombres_hermanas (included capital 'Amurrio')
    hermanas_prefix = [h["nombre"] for h in todas if h["id"] != baranbio["id"]]  # ['Amurrio', 'Lezama']

    # Post-fix nombres_hermanas (excludes capital 'Amurrio')
    hermanas_postfix = extract_nombres_hermanas(todas, baranbio)  # ['Lezama']

    # Pre-fix run: Amurrio chunk was DROPPED because Amurrio was in hermanas_prefix
    res_prefix = filtrar_chunks_por_localidad(items.copy(), "Baranbio", hermanas_prefix)
    # 2 items left (Lezama chunk dropped, Amurrio chunk dropped, Baranbio chunk kept)
    assert len(res_prefix) == 1, "Pre-fix wrongly dropped general municipal chunk mentioning Amurrio"
    assert res_prefix[0]["chunk"].startswith("Baranbio")

    # Post-fix run: Amurrio chunk is KEPT as GENERAL (score 0.85 -> 0.75)
    res_postfix = filtrar_chunks_por_localidad([dict(i) for i in items], "Baranbio", hermanas_postfix)
    assert len(res_postfix) == 2, "Post-fix must retain general municipal chunk and target chunk, dropping only sister chunk"
    relevancias = {item["chunk"].split()[0]: item["relevancia_geo"] for item in res_postfix}
    assert relevancias["El"] == "GENERAL"
    assert relevancias["Baranbio"] == "DIRECTA"


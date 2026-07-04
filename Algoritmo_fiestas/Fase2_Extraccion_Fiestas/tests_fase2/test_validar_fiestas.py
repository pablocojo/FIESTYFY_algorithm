"""Test de integración de validar_fiestas (sin LLM): validación + saneado + filtro."""

from datetime import date

from llm_processor.text_analyzer import validar_fiestas

LOCALIDAD = {"id": "01049000201", "nombre": "Salinas de Añana"}
ANNO = 2026


def test_validar_fiestas_pipeline_completo():
    fiestas_raw = [
        # Válida: multi-día con verbena
        {
            "id": "fiestas-agosto", "lugar_id": LOCALIDAD["id"],
            "nombre": "Fiestas de Agosto", "fecha_inicio": "2026-08-10",
            "fecha_fin": "2026-08-18", "descripcion": "Verbena y orquesta cada noche",
        },
        # Alucinación de lugar: descartada
        {
            "id": "otra", "lugar_id": "otro-lugar",
            "nombre": "Fiestas ajenas", "fecha_inicio": "2026-07-01",
            "fecha_fin": "2026-07-03",
        },
        # Procesión suelta de un día: descartada por filtro estricto
        {
            "id": "procesion", "lugar_id": LOCALIDAD["id"],
            "nombre": "Procesión del Rosario", "fecha_inicio": "2026-10-07",
            "fecha_fin": "2026-10-07", "descripcion": "Procesión y misa solemne",
        },
        # Año incorrecto: descartada
        {
            "id": "vieja", "lugar_id": LOCALIDAD["id"],
            "nombre": "Fiestas viejas", "fecha_inicio": "2025-08-10",
            "fecha_fin": "2025-08-12",
        },
        # Un día con DJ: aceptada
        {
            "id": "noche-joven", "lugar_id": LOCALIDAD["id"],
            "nombre": "Noche joven", "fecha_inicio": "2026-08-14",
            "fecha_fin": "2026-08-14", "descripcion": "DJ en la plaza",
        },
    ]

    validas = validar_fiestas(fiestas_raw, LOCALIDAD, ANNO)
    ids = {f["id"] for f in validas}
    assert ids == {"fiestas-agosto", "noche-joven"}

    for f in validas:
        assert f["origen"] == "extraccion"
        assert f["es_estimada"] is False
        assert f["incluye_dia_patron"] is False


def test_validar_fiestas_excepcion_patronal_un_dia():
    fiestas_raw = [{
        "id": "romeria", "lugar_id": LOCALIDAD["id"],
        "nombre": "Romería de la ermita", "fecha_inicio": "2026-08-16",
        "fecha_fin": "2026-08-16", "descripcion": "Subida a la ermita y comida campestre",
    }]
    # Sin fecha_patron: rechazada (un día sin música ni nombre patronal)
    assert validar_fiestas(fiestas_raw, LOCALIDAD, ANNO) == []

    # Con fecha_patron coincidente: aceptada con confianza baja
    fiestas_raw[0].pop("confianza", None)
    validas = validar_fiestas(fiestas_raw, LOCALIDAD, ANNO, fecha_patron=date(2026, 8, 16))
    assert len(validas) == 1
    assert validas[0]["confianza"] == "baja"


def test_validar_fiestas_intercambia_fechas_invertidas():
    fiestas_raw = [{
        "id": "invertida", "lugar_id": LOCALIDAD["id"],
        "nombre": "Fiestas de San Roque", "fecha_inicio": "2026-08-18",
        "fecha_fin": "2026-08-10", "descripcion": "Verbena nocturna",
    }]
    validas = validar_fiestas(fiestas_raw, LOCALIDAD, ANNO)
    assert len(validas) == 1
    assert validas[0]["fecha_inicio"] == "2026-08-10"
    assert validas[0]["fecha_fin"] == "2026-08-18"

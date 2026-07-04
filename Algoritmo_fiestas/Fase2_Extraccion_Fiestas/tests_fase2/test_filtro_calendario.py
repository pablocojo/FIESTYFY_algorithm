"""Tests del filtro de festivos de calendario laboral/escolar (M6)."""

from datetime import date

from llm_processor.festival_filter import evaluar_fiesta


def _fiesta(nombre, inicio, fin, descripcion="", programa=None):
    return {
        "nombre": nombre,
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "descripcion": descripcion,
        "programa": programa or [],
    }


def test_festivo_nacional_sin_celebracion_rechaza():
    f = _fiesta("Día de la Constitución", "2026-12-06", "2026-12-06",
                "Día festivo en toda España")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada
    assert "calendario" in motivo or "festivo" in motivo


def test_fiesta_del_trabajo_rechaza():
    f = _fiesta("Fiesta del Trabajo", "2026-05-01", "2026-05-01", "")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_dia_de_comunidad_rechaza():
    f = _fiesta("Día de Andalucía", "2026-02-28", "2026-02-28", "Festivo autonómico")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_festivo_con_verbena_se_mantiene():
    # El festivo local coincide con la fiesta real → hay celebración → se acepta
    f = _fiesta("Día de Reyes", "2026-01-06", "2026-01-06",
                "Cabalgata y verbena popular por la noche")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_festivo_con_programa_se_mantiene():
    # Nombre de festivo de calendario, pero con programa real de celebración
    # (multi-día: el filtro estricto de un solo día es un caso aparte)
    programa = [
        {"dia": 1, "fecha": "2026-05-01", "eventos": [
            {"hora": "12:00", "descripcion": "Romería al santuario"},
            {"hora": "15:00", "descripcion": "Comida popular en la pradera"},
        ]},
    ]
    f = _fiesta("Fiesta del Trabajo en la aldea", "2026-05-01", "2026-05-02", programa=programa)
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_texto_de_calendario_laboral_rechaza():
    f = _fiesta("Festivo local", "2026-09-08", "2026-09-08",
                "Según el calendario laboral 2026, día festivo local en el municipio")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_calendario_pero_coincide_con_patron_se_mantiene():
    # Coincidir con el día del patrón cuenta como evidencia de celebración
    f = _fiesta("Festivo local", "2026-09-08", "2026-09-08",
                "Día festivo local según el calendario laboral")
    aceptada, motivo, conf = evaluar_fiesta(f, fecha_patron=date(2026, 9, 8))
    assert aceptada, motivo


def test_patronal_multidia_no_afectada():
    f = _fiesta("Fiestas de la Inmaculada", "2026-12-05", "2026-12-08",
                "Verbena, hoguera y chocolatada")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo

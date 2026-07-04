"""Tests del filtro adaptativo y del saneado de fiestas mal formadas."""

from datetime import date

from llm_processor.festival_filter import evaluar_fiesta, sanear_fiesta


def _fiesta(nombre, inicio, fin, descripcion="", programa=None):
    return {
        "nombre": nombre,
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "descripcion": descripcion,
        "programa": programa or [],
    }


# ──────────────────────────────────────────────
# Multi-día (filtro regular)
# ──────────────────────────────────────────────

def test_multidia_con_verbena_acepta():
    f = _fiesta("Fiestas de Agosto", "2026-08-10", "2026-08-15", "Verbena en la plaza")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_multidia_nombre_fiesta_acepta():
    f = _fiesta("Fiestas de Salinas", "2026-10-03", "2026-10-07")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_multidia_solo_actos_religiosos_rechaza():
    f = _fiesta(
        "Triduo en la parroquia", "2026-04-01", "2026-04-03",
        "Novena, misa y procesion",
    )
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_multidia_programa_suficiente_acepta():
    programa = [
        {"dia": 1, "fecha": "2026-07-01", "eventos": [
            {"hora": "12:00", "descripcion": "Juegos infantiles"},
            {"hora": "20:00", "descripcion": "Cena de hermandad"},
        ]},
    ]
    f = _fiesta("Semana del pueblo", "2026-07-01", "2026-07-03", programa=programa)
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


# ──────────────────────────────────────────────
# Un solo día (filtro estricto)
# ──────────────────────────────────────────────

def test_un_dia_solo_procesion_rechaza():
    f = _fiesta("Procesión del Cristo", "2026-09-14", "2026-09-14", "Procesión por las calles")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_un_dia_con_dj_acepta():
    f = _fiesta("Noche joven", "2026-08-14", "2026-08-14", "Sesión de DJ en la plaza hasta la madrugada")
    aceptada, motivo, conf = evaluar_fiesta(f)
    assert aceptada, motivo
    assert conf is None


def test_un_dia_con_discomovil_acepta():
    f = _fiesta("Fin de fiestas", "2026-08-20", "2026-08-20", "Discoteca móvil en el frontón")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_un_dia_patronal_sin_musica_acepta_confianza_baja():
    f = _fiesta("Fiestas de San Roque", "2026-08-16", "2026-08-16", "Actos en honor al patrón")
    aceptada, motivo, conf = evaluar_fiesta(f)
    assert aceptada, motivo
    assert conf == "baja"


def test_un_dia_coincide_con_patron_acepta_confianza_baja():
    f = _fiesta("Romería anual", "2026-10-07", "2026-10-07", "Romería hasta la ermita")
    aceptada, motivo, conf = evaluar_fiesta(f, fecha_patron=date(2026, 10, 7))
    assert aceptada, motivo
    assert conf == "baja"


def test_un_dia_exposicion_rechaza():
    f = _fiesta("Exposición de fotografía", "2026-05-10", "2026-05-10", "Exposición en la casa de cultura")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


# ──────────────────────────────────────────────
# Eventos privados
# ──────────────────────────────────────────────

def test_evento_en_discoteca_privada_rechaza():
    f = _fiesta("Fiesta en Discoteca Luna", "2026-08-14", "2026-08-14", "Sesión con DJ invitado")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert not aceptada, motivo


def test_verbena_que_menciona_discoteca_en_programa_acepta():
    programa = [
        {"dia": 1, "fecha": "2026-08-13", "eventos": [
            {"hora": "23:00", "descripcion": "Verbena y después discoteca en la carpa"},
        ]},
    ]
    f = _fiesta("Fiestas de la Paloma", "2026-08-13", "2026-08-15", programa=programa)
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


def test_discoteca_movil_no_cuenta_como_privada():
    f = _fiesta("Fiesta de la pedanía", "2026-07-04", "2026-07-04", "Discoteca móvil y toro de fuego")
    aceptada, motivo, _ = evaluar_fiesta(f)
    assert aceptada, motivo


# ──────────────────────────────────────────────
# Saneado de fiestas mal formadas
# ──────────────────────────────────────────────

def test_saneado_nombre_generico_descarta():
    f = _fiesta("Fiesta", "2026-08-01", "2026-08-03")
    assert sanear_fiesta(f) is None


def test_saneado_nombre_corto_descarta():
    f = _fiesta("Fx", "2026-08-01", "2026-08-03")
    assert sanear_fiesta(f) is None


def test_saneado_duracion_absurda_descarta():
    f = _fiesta("Fiestas eternas", "2026-01-01", "2026-03-15")
    assert sanear_fiesta(f) is None


def test_saneado_programa_fuera_de_rango_se_limpia():
    programa = [
        {"dia": 1, "fecha": "2026-08-10", "eventos": [{"hora": "20:00", "descripcion": "Pregón"}]},
        {"dia": 2, "fecha": "2026-09-25", "eventos": [{"hora": "12:00", "descripcion": "Acto fuera de rango"}]},
    ]
    f = _fiesta("Fiestas de San Roque", "2026-08-10", "2026-08-16", programa=programa)
    saneada = sanear_fiesta(f)
    assert saneada is not None
    assert len(saneada["programa"]) == 1
    assert saneada["programa"][0]["fecha"] == "2026-08-10"


def test_saneado_renumera_dias():
    programa = [
        {"dia": 9, "fecha": "2026-08-12", "eventos": [{"hora": "23:00", "descripcion": "Orquesta"}]},
        {"dia": 1, "fecha": "2026-08-10", "eventos": [{"hora": "20:00", "descripcion": "Pregón"}]},
    ]
    f = _fiesta("Fiestas de San Roque", "2026-08-10", "2026-08-16", programa=programa)
    saneada = sanear_fiesta(f)
    dias = [d["dia"] for d in saneada["programa"]]
    fechas = [d["fecha"] for d in saneada["programa"]]
    assert fechas == ["2026-08-10", "2026-08-12"]
    assert dias == [1, 3]

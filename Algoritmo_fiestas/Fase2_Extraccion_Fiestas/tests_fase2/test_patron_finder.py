"""Tests del santoral, la extracción de patrón y la integración con las fiestas."""

from datetime import date

from llm_processor.patron_finder import (
    buscar_en_santoral,
    extraer_patron_de_texto,
    _resolver_fecha,
    fecha_del_patron,
    integrar_patron,
    crear_fiesta_estimada,
)

LOCALIDAD = {"id": "01049000201", "nombre": "Salinas de Añana"}


# ──────────────────────────────────────────────
# Santoral: normalización y alias
# ──────────────────────────────────────────────

def test_santoral_directo():
    assert buscar_en_santoral("San Roque") == (16, 8)


def test_santoral_abreviatura():
    assert buscar_en_santoral("Ntra. Sra. del Rosario") == (7, 10)


def test_santoral_advocacion_equivalente():
    assert buscar_en_santoral("Nuestra Señora de la Asunción") == (15, 8)
    assert buscar_en_santoral("Virgen de la Asunción") == (15, 8)


def test_santoral_por_contencion():
    # "Santísimo Cristo del Amparo" contiene la clave "santisimo cristo"
    assert buscar_en_santoral("Santísimo Cristo del Amparo") == (14, 9)


def test_santoral_mas_especifico_gana():
    # "San Juan de Sahagún" (12/6) no debe resolverse como "San Juan" (24/6)
    assert buscar_en_santoral("San Juan de Sahagún") == (12, 6)
    assert buscar_en_santoral("San Juan") == (24, 6)


def test_santoral_desconocido():
    assert buscar_en_santoral("San Inventado de Nunca") is None


# ──────────────────────────────────────────────
# Extracción de texto
# ──────────────────────────────────────────────

def test_extraer_en_honor_a():
    texto = (
        "Las fiestas patronales se celebran en honor a San Bartolomé "
        "el 24 de agosto con verbena y orquesta."
    )
    r = extraer_patron_de_texto(texto)
    assert r is not None
    assert "Bartolom" in r["nombre"]
    assert (r["dia"], r["mes"]) == (24, 8)


def test_extraer_patron_es():
    texto = "El patrón del municipio es San Sebastián, cuya festividad reúne a todos los vecinos."
    r = extraer_patron_de_texto(texto)
    assert r is not None
    assert "Sebasti" in r["nombre"]


def test_no_extrae_de_texto_irrelevante():
    texto = "El ayuntamiento aprobó los presupuestos municipales para el próximo ejercicio."
    assert extraer_patron_de_texto(texto) is None


def test_no_extrae_nombres_no_santos():
    # "fiestas de..." seguido de algo que no parece un santo no debe extraerse
    texto = "Las fiestas de agosto tienen lugar en el barrio de la estación."
    assert extraer_patron_de_texto(texto) is None


def test_nombre_no_arrastra_frase_siguiente():
    texto = "Fiestas en honor a San Andrés. Municipio de la Rioja Alavesa con gran tradición."
    r = extraer_patron_de_texto(texto)
    assert r is not None
    assert r["nombre"] == "San Andrés"


# ──────────────────────────────────────────────
# Resolución de fecha (santoral prevalece)
# ──────────────────────────────────────────────

def test_resolver_fecha_santoral_prevalece():
    r = _resolver_fecha({"nombre": "San Roque", "dia": 20, "mes": 8}, "wikipedia")
    assert (r["dia"], r["mes"]) == (16, 8)
    assert r["confianza"] == "media"


def test_resolver_fecha_coincide_alta():
    r = _resolver_fecha({"nombre": "San Roque", "dia": 16, "mes": 8}, "wikipedia")
    assert (r["dia"], r["mes"]) == (16, 8)
    assert r["confianza"] == "alta"


def test_resolver_fecha_solo_texto():
    r = _resolver_fecha({"nombre": "San Desconocido del Valle", "dia": 3, "mes": 5}, "busqueda")
    assert (r["dia"], r["mes"]) == (3, 5)
    assert r["confianza"] == "media"


def test_resolver_sin_fecha():
    r = _resolver_fecha({"nombre": "San Desconocido del Valle", "dia": None, "mes": None}, "llm")
    assert r["dia"] is None
    assert r["confianza"] == "baja"


# ──────────────────────────────────────────────
# fecha_del_patron
# ──────────────────────────────────────────────

def test_fecha_del_patron():
    patron = {"nombre": "San Roque", "dia": 16, "mes": 8}
    assert fecha_del_patron(patron, 2026) == date(2026, 8, 16)


def test_fecha_del_patron_sin_datos():
    assert fecha_del_patron(None, 2026) is None
    assert fecha_del_patron({"nombre": "X", "dia": None, "mes": None}, 2026) is None


# ──────────────────────────────────────────────
# Integración con fiestas extraídas
# ──────────────────────────────────────────────

def _patron_roque():
    return {"nombre": "San Roque", "dia": 16, "mes": 8, "fuente": "wikipedia", "confianza": "alta"}


def test_integrar_marca_fiesta_que_cubre_el_dia():
    fiestas = [{
        "id": "f1", "lugar_id": LOCALIDAD["id"], "nombre": "Fiestas de Agosto",
        "fecha_inicio": "2026-08-10", "fecha_fin": "2026-08-18",
    }]
    resultado = integrar_patron(fiestas, _patron_roque(), 2026, LOCALIDAD)
    assert len(resultado) == 1
    assert resultado[0]["incluye_dia_patron"] is True
    assert resultado[0]["patron"]["nombre"] == "San Roque"


def test_integrar_anade_estimada_si_no_cubierto():
    fiestas = [{
        "id": "f1", "lugar_id": LOCALIDAD["id"], "nombre": "Carnaval",
        "fecha_inicio": "2026-02-14", "fecha_fin": "2026-02-17",
    }]
    resultado = integrar_patron(fiestas, _patron_roque(), 2026, LOCALIDAD)
    assert len(resultado) == 2
    estimada = resultado[1]
    assert estimada["origen"] == "santo_patron"
    assert estimada["es_estimada"] is True
    assert estimada["confianza"] == "baja"
    assert estimada["fecha_inicio"] == estimada["fecha_fin"] == "2026-08-16"


def test_integrar_anade_estimada_sin_fiestas():
    resultado = integrar_patron([], _patron_roque(), 2026, LOCALIDAD)
    assert len(resultado) == 1
    assert resultado[0]["es_estimada"] is True
    assert resultado[0]["lugar_id"] == LOCALIDAD["id"]


def test_integrar_sin_patron_no_cambia_nada():
    fiestas = [{"id": "f1", "fecha_inicio": "2026-08-10", "fecha_fin": "2026-08-18"}]
    resultado = integrar_patron(fiestas, None, 2026, LOCALIDAD)
    assert resultado == fiestas
    assert "incluye_dia_patron" not in resultado[0]


def test_crear_fiesta_estimada_estructura():
    f = crear_fiesta_estimada(_patron_roque(), date(2026, 8, 16), LOCALIDAD)
    assert f["id"].startswith("patron-san-roque-")
    assert f["programa"] == []
    assert f["tamano"] == "pequeña"
    assert f["incluye_dia_patron"] is True

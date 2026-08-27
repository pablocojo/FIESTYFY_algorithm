"""
Guarda contra la copia del programa de la capital a sus pedanías.

Medido el 2026-08-21, tras arreglar la lectura de los carteles en PDF: Larrinbe
recibió una fiesta llamada "Fiestas Patronales de Amurrio" con 90 actos y Delika
otra que incluía "Finales Campeonato de Pelota 'Villa de Amurrio'". Mejorar la
extracción amplificó el daño de la contaminación: antes se copiaban tres líneas
vagas, después noventa actos con hora exacta que parecen ciertos.
"""
import pytest

from llm_processor.text_analyzer import descartar_copias_de_la_capital

MUNICIPIO = {"nombre": "Amurrio"}
PEDANIA = {"nombre": "Larrinbe", "id": "01002000701", "es_capital": False}
CAPITAL = {"nombre": "Amurrio", "id": "01002000201", "es_capital": True}

FIESTAS_CAPITAL = [{
    "nombre": "Fiestas de San Roque y Nuestra Señora de la Asunción",
    "fecha_inicio": "2026-08-11",
    "fecha_fin": "2026-08-17",
}]


def fiesta(nombre, ini, fin, origen="extraccion"):
    return {"nombre": nombre, "fecha_inicio": ini, "fecha_fin": fin, "origen": origen}


def test_descarta_la_copia_literal_sin_evidencia_propia():
    copia = fiesta("Fiestas de San Roque y Nuestra Señora de la Asunción",
                   "2026-08-11", "2026-08-17")
    salida = descartar_copias_de_la_capital(
        [copia], FIESTAS_CAPITAL, n_chunks_directa=0,
        localidad=PEDANIA, municipio=MUNICIPIO,
    )
    assert salida == []


def test_descarta_por_fechas_solapadas_aunque_cambie_el_nombre():
    """El modelo rebautiza la copia ("Fiestas Patronales de Delika") pero
    conserva las fechas del municipio."""
    copia = fiesta("Fiestas Patronales de Delika", "2026-08-12", "2026-08-17")
    salida = descartar_copias_de_la_capital(
        [copia], FIESTAS_CAPITAL, n_chunks_directa=0,
        localidad=PEDANIA, municipio=MUNICIPIO,
    )
    assert salida == []


def test_conserva_la_fiesta_propia_con_fechas_distintas():
    propia = fiesta("Fiestas de Santiago en Larrinbe", "2026-07-24", "2026-07-26")
    salida = descartar_copias_de_la_capital(
        [propia], FIESTAS_CAPITAL, n_chunks_directa=0,
        localidad=PEDANIA, municipio=MUNICIPIO,
    )
    assert salida == [propia]


def test_con_evidencia_directa_no_se_descarta_nada():
    """Dos pueblos del mismo valle pueden celebrar de verdad al mismo patrón las
    mismas fechas. Si el contexto nombraba a la localidad, se respeta."""
    coincide = fiesta("Fiestas de San Roque y Nuestra Señora de la Asunción",
                      "2026-08-11", "2026-08-17")
    salida = descartar_copias_de_la_capital(
        [coincide], FIESTAS_CAPITAL, n_chunks_directa=3,
        localidad=PEDANIA, municipio=MUNICIPIO,
    )
    assert salida == [coincide]


def test_la_capital_nunca_se_filtra_contra_si_misma():
    propia = fiesta("Fiestas de San Roque y Nuestra Señora de la Asunción",
                    "2026-08-11", "2026-08-17")
    salida = descartar_copias_de_la_capital(
        [propia], FIESTAS_CAPITAL, n_chunks_directa=0,
        localidad=CAPITAL, municipio=MUNICIPIO,
    )
    assert salida == [propia]


def test_las_estimadas_por_patron_sobreviven():
    """La fiesta estimada del santo patrón cae en las fechas del patrón, que
    suelen solapar con las de la capital. No es una copia: es un cálculo."""
    estimada = fiesta("Fiestas de San Roque (estimada)",
                      "2026-08-16", "2026-08-16", origen="santo_patron")
    salida = descartar_copias_de_la_capital(
        [estimada], FIESTAS_CAPITAL, n_chunks_directa=0,
        localidad=PEDANIA, municipio=MUNICIPIO,
    )
    assert salida == [estimada]


def test_sin_fiestas_de_capital_no_hace_nada():
    algo = fiesta("Fiestas de lo que sea", "2026-08-11", "2026-08-17")
    assert descartar_copias_de_la_capital(
        [algo], None, 0, PEDANIA, MUNICIPIO) == [algo]
    assert descartar_copias_de_la_capital(
        [algo], [], 0, PEDANIA, MUNICIPIO) == [algo]


def test_fechas_invalidas_no_revientan():
    rara = fiesta("Fiesta rara", "no-es-fecha", "tampoco")
    salida = descartar_copias_de_la_capital(
        [rara], FIESTAS_CAPITAL, 0, PEDANIA, MUNICIPIO)
    assert salida == [rara]


# ── Programa: recorte al rango y fusión de lotes ─────────────────────────────

from llm_processor.text_analyzer import _recortar_programa_al_rango, _fusionar_dias


def test_el_programa_se_recorta_al_rango_declarado():
    """El modelo devolvió 21 días para una fiesta de 7, hasta el 31 de agosto."""
    programa = [{"dia": i + 1, "fecha": f"2026-08-{11 + i:02d}", "eventos": []}
                for i in range(21)]
    recortado = _recortar_programa_al_rango(programa, "2026-08-11", "2026-08-17")
    assert len(recortado) == 7
    assert [d["fecha"] for d in recortado] == [f"2026-08-{d}" for d in range(11, 18)]
    assert [d["dia"] for d in recortado] == list(range(1, 8))


def test_la_fusion_de_lotes_quita_actos_repetidos():
    """Dos lotes pueden devolver el mismo día; el acto repetido no se duplica."""
    lote_a = [{"dia": 1, "fecha": "2026-08-11",
               "eventos": [{"hora": "11:00", "descripcion": "Misa"}]}]
    lote_b = [{"dia": 1, "fecha": "2026-08-11",
               "eventos": [{"hora": "11:00", "descripcion": "misa"},
                           {"hora": "20:00", "descripcion": "Verbena"}]}]
    fusionado = _fusionar_dias(lote_a + lote_b)
    assert len(fusionado) == 1
    assert len(fusionado[0]["eventos"]) == 2


def test_la_fusion_ordena_por_fecha():
    programa = [{"dia": 3, "fecha": "2026-08-13", "eventos": []},
                {"dia": 1, "fecha": "2026-08-11", "eventos": []}]
    assert [d["fecha"] for d in _fusionar_dias(programa)] == ["2026-08-11", "2026-08-13"]


# ── Guarda por PROGRAMA (la que detecta la copia disfrazada) ─────────────────

from llm_processor.text_analyzer import descartar_programas_copiados

# Actos reales del cartel de Amurrio 2026 (días 16-17).
ACTOS_AMURRIO = [
    "Subida del Santo", "Exposición de ganado", "Misa mayor",
    "Concurso de aurresku y jotas", "Teatro: The Return of Delirios",
    "Orquesta: Maran", "Desfile de carrozas", "Romería Zutik",
    "Mariachi México Lindo Sí Señor", "Entrega del Iguarrako de Oro",
]


def _con_programa(nombre, descripciones, origen="extraccion"):
    return {
        "nombre": nombre, "origen": origen,
        "fecha_inicio": "2026-08-16", "fecha_fin": "2026-08-17",
        "programa": [{"dia": 1, "fecha": "2026-08-16",
                      "eventos": [{"hora": "", "descripcion": d} for d in descripciones]}],
    }


CAPITAL_CON_PROGRAMA = [_con_programa("Fiestas de San Roque", ACTOS_AMURRIO)]


def test_descarta_el_programa_copiado_aunque_cambien_nombre_y_fechas():
    """Delika recibió el cartel de Amurrio bajo otro nombre y otras fechas.

    Los nombres y las fechas los disfraza el modelo; los actos concretos no:
    "Mariachi México Lindo" no se celebra en cinco pueblos a la vez.
    """
    copia = _con_programa("Fiestas Patronales de Delika", ACTOS_AMURRIO)
    copia["fecha_inicio"], copia["fecha_fin"] = "2026-08-12", "2026-08-17"
    salida = descartar_programas_copiados(
        [copia], CAPITAL_CON_PROGRAMA, {"nombre": "Delika", "es_capital": False})
    assert salida == []


def test_conserva_el_programa_propio():
    propia = _con_programa("Fiestas de Santiago en Larrinbe", [
        "Bendición de vehículos", "Comida popular en el frontón",
        "Campeonato de pelota a mano", "Romería con trikitilaris",
        "Concurso de tortillas de patata",
    ])
    salida = descartar_programas_copiados(
        [propia], CAPITAL_CON_PROGRAMA, {"nombre": "Larrinbe", "es_capital": False})
    assert salida == [propia]


def test_coincidir_en_pocos_actos_genericos_no_basta():
    """Misa y romería las hay en todos los pueblos: no prueban copia."""
    propia = _con_programa("Fiestas de San Nicolás", [
        "Misa mayor", "Romería con trikitilaris", "Comida de vecinos",
        "Campeonato de mus y briska", "Chocolatada para los niños",
        "Dantzas del grupo local", "Reparto de opilak",
    ])
    salida = descartar_programas_copiados(
        [propia], CAPITAL_CON_PROGRAMA, {"nombre": "Saratxo", "es_capital": False})
    assert salida == [propia]


def test_la_capital_no_se_filtra_contra_su_propio_programa():
    salida = descartar_programas_copiados(
        list(CAPITAL_CON_PROGRAMA), CAPITAL_CON_PROGRAMA,
        {"nombre": "Amurrio", "es_capital": True})
    assert len(salida) == 1


def test_la_estimada_por_patron_sobrevive_aunque_no_tenga_programa():
    estimada = {"nombre": "Fiestas de San Roque (estimada)", "origen": "santo_patron",
                "fecha_inicio": "2026-08-16", "fecha_fin": "2026-08-16", "programa": []}
    salida = descartar_programas_copiados(
        [estimada], CAPITAL_CON_PROGRAMA, {"nombre": "Tertanga", "es_capital": False})
    assert salida == [estimada]


def test_sin_programa_en_la_capital_no_se_descarta_nada():
    sin_prog = [{"nombre": "X", "fecha_inicio": "2026-08-16",
                 "fecha_fin": "2026-08-17", "programa": []}]
    algo = _con_programa("Fiestas de lo que sea", ACTOS_AMURRIO)
    salida = descartar_programas_copiados(
        [algo], sin_prog, {"nombre": "Delika", "es_capital": False})
    assert salida == [algo]


def test_detecta_la_copia_por_horarios_aunque_este_en_otro_idioma():
    """Delika tenía el 100% de sus horarios iguales a los de la capital y solo
    un 3% de coincidencia textual: había tomado el cartel en el otro idioma.

    Comparar descripciones no basta ("abereerakusketa" / "exposición de ganado"
    son el mismo acto); la hora sí es la misma en los dos idiomas.
    """
    capital = [{
        "nombre": "Fiestas de San Roque", "origen": "extraccion",
        "fecha_inicio": "2026-08-16", "fecha_fin": "2026-08-16",
        "programa": [{"dia": 1, "fecha": "2026-08-16", "eventos": [
            {"hora": h, "descripcion": d} for h, d in [
                ("10:00", "Subida del Santo"), ("10:30", "Exposición de ganado"),
                ("11:30", "Misa mayor"), ("12:30", "Concurso de aurresku"),
                ("19:30", "Teatro The Return of Delirios"), ("21:00", "Orquesta Maran"),
            ]]}],
    }]
    # misma fiesta, descripciones en euskera: 0% textual, 100% por horario
    copia = {
        "nombre": "Fiestas Patronales de Delika", "origen": "extraccion",
        "fecha_inicio": "2026-08-16", "fecha_fin": "2026-08-16",
        "programa": [{"dia": 1, "fecha": "2026-08-16", "eventos": [
            {"hora": h, "descripcion": d} for h, d in [
                ("10:00", "Santuaren igoera"), ("10:30", "Abereerakusketa"),
                ("11:30", "Meza nagusia"), ("12:30", "Aurresku lehiaketa"),
                ("19:30", "Antzerkia Delirios"), ("21:00", "Maran orkestra"),
            ]]}],
    }
    salida = descartar_programas_copiados(
        [copia], capital, {"nombre": "Delika", "es_capital": False})
    assert salida == [], "la copia en otro idioma debería detectarse por los horarios"


def test_horarios_distintos_no_se_consideran_copia():
    capital = [{
        "nombre": "Fiestas de San Roque", "origen": "extraccion",
        "fecha_inicio": "2026-08-16", "fecha_fin": "2026-08-16",
        "programa": [{"dia": 1, "fecha": "2026-08-16", "eventos": [
            {"hora": h, "descripcion": f"Acto {h}"} for h in
            ("10:00", "10:30", "11:30", "12:30", "19:30", "21:00")]}],
    }]
    propia = {
        "nombre": "Fiestas de Santiago", "origen": "extraccion",
        "fecha_inicio": "2026-07-24", "fecha_fin": "2026-07-24",
        "programa": [{"dia": 1, "fecha": "2026-07-24", "eventos": [
            {"hora": h, "descripcion": f"Otro acto {h}"} for h in
            ("09:00", "13:00", "17:00", "20:00", "23:00")]}],
    }
    salida = descartar_programas_copiados(
        [propia], capital, {"nombre": "Larrinbe", "es_capital": False})
    assert salida == [propia]

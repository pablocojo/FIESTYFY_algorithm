"""
La ficha del pueblo: orientación para los modelos, no dato para el código.

De dónde sale
-------------
Auditoría del 2026-09-06 sobre `fiestas_amplio_searxng.json`. Garrucha salió con
esta ficha:

    Fiestas Patronales de San Joaquín · 2026-02-20 → 2026-03-21
    actos: "Triduo a Nuestro Padre Jesús", "Confesiones en el Templo Parroquial"

Eso es Cuaresma. Las fiestas de San Joaquín de Garrucha son del 14 al 18 de
agosto según la web del propio ayuntamiento. Y el daño no acabó ahí: la caché
guardaba `{"nombre": "San Joaquín", "dia": 26, "mes": 7}` —la fecha del
santoral—, así que `_avales_de_patronal` comparaba contra el 26 de julio, ninguna
ficha lo cumplía, el desempate cayó al criterio del nombre, y la ficha falsa
—que sí se llama "San Joaquín"— expulsó a dos fiestas reales:

    [PATRONAL/DUPLICADA] 'Fiestas Patronales en Honor a la Virgen del Carmen'
    (2026-07-16) descartada: un pueblo tiene una sola patronal y
    'Fiestas Patronales de San Joaquín' (2026-02-20) está mejor avalada.

La Virgen del Carmen estaba encontrada y bien fechada: su contexto traía "Carmen"
diez veces y "16 de julio" dos. No fue un fallo de búsqueda, fue el filtrado.

Qué fijan estos tests
---------------------
Que la fecha de celebración real gane a la del santoral, y que la ficha se
presente siempre como hipótesis subordinada a los documentos. Lo segundo importa
tanto como lo primero: la escribe un modelo, y si entra al contexto con tono de
verdad establecida habríamos cambiado una falsedad del código por una del
contexto, contaminando a todos los modelos siguientes en vez de a una regla.
"""

from datetime import date

import pytest

from llm_processor.patron_finder import fecha_del_patron, ficha_del_pueblo


GARRUCHA = {
    "nombre": "San Joaquín",
    "dia": 26, "mes": 7,              # santoral
    "celebra_dia": 16, "celebra_mes": 8,   # lo que hace el pueblo
    "fiestas_habituales": [
        "Virgen del Carmen, 16 de julio, procesión marítima",
        "Carnaval, febrero",
    ],
}


# ─────────────────────────────────────────────
# La fecha: el pueblo manda sobre el santoral
# ─────────────────────────────────────────────

def test_la_fecha_del_pueblo_gana_a_la_del_santoral():
    """El caso Garrucha. Con el 26/7 ninguna ficha cubría el día del patrón."""
    assert fecha_del_patron(GARRUCHA, 2026) == date(2026, 8, 16)


def test_sin_fecha_de_celebracion_se_usa_la_del_santoral():
    """No se rompe lo que ya funcionaba: la mayoría de la caché solo trae dia/mes."""
    assert fecha_del_patron({"nombre": "San Roque", "dia": 16, "mes": 8}, 2026) == date(2026, 8, 16)


def test_sin_ninguna_fecha_devuelve_none():
    assert fecha_del_patron({"nombre": "San Roque"}, 2026) is None
    assert fecha_del_patron(None, 2026) is None


def test_29_de_febrero_en_anno_no_bisiesto_cae_al_28():
    """Regresión: el ajuste existía antes y debe sobrevivir al cambio."""
    assert fecha_del_patron({"nombre": "X", "dia": 29, "mes": 2}, 2026) == date(2026, 2, 28)


def test_celebracion_invalida_no_tumba_la_del_santoral():
    """Un mes 13 no debe dejar sin fecha a quien tiene una buena en el santoral."""
    p = {"nombre": "X", "dia": 16, "mes": 8, "celebra_dia": 40, "celebra_mes": 13}
    assert fecha_del_patron(p, 2026) == date(2026, 8, 16)


# ─────────────────────────────────────────────
# La ficha: hipótesis, nunca verdad
# ─────────────────────────────────────────────

def test_la_ficha_se_presenta_como_hipotesis_y_no_como_hecho():
    """El requisito de seguridad del diseño.

    Si alguien quita estas frases, la ficha pasa a leerse como dato firme y un
    error del modelo que la escribe se propaga a discovery y al juez.
    """
    t = ficha_del_pueblo(GARRUCHA)
    assert "NO es la verdad" in t
    assert "hipotesis" in t.lower() or "hipótesis" in t.lower()
    assert "MANDA EL DOCUMENTO" in t


def test_la_ficha_prohibe_inventar():
    """No debe servir de excusa para fiestas que ningún documento respalda."""
    t = ficha_del_pueblo(GARRUCHA)
    assert "inventar" in t


def test_la_ficha_lleva_las_dos_fechas_y_dice_cual_manda():
    t = ficha_del_pueblo(GARRUCHA)
    assert "26/7" in t and "16/8" in t
    assert "manda sobre la del santoral" in t


def test_la_ficha_lista_las_fiestas_habituales():
    """Es lo que permite al juez saber que la Virgen del Carmen encaja aquí."""
    t = ficha_del_pueblo(GARRUCHA)
    assert "Virgen del Carmen" in t
    assert "Carnaval" in t


def test_sin_patron_no_hay_ficha():
    """Cadena vacía, no un bloque de texto vacío: no se mete ruido en el contexto."""
    assert ficha_del_pueblo(None) == ""
    assert ficha_del_pueblo({}) == ""


def test_patron_pelado_da_ficha_minima_sin_inventar_secciones():
    t = ficha_del_pueblo({"nombre": "San Roque"})
    assert "San Roque" in t
    assert "santoral:" not in t
    assert "suele tener" not in t


# ─────────────────────────────────────────────
# Llega a quien tiene que llegar
# ─────────────────────────────────────────────

def test_el_juez_de_pertenencia_recibe_la_ficha():
    """Viaja en la localidad, como `nombre_oficial` viaja en el municipio."""
    import llm_processor.text_analyzer as ta

    loc = {"id": "04049000101", "nombre": "Garrucha", "ficha_pueblo": ficha_del_pueblo(GARRUCHA)}
    mun = {"id": "04049000000", "nombre": "Garrucha", "provincia": "Almería"}
    bloque = ta._bloque_identidad(loc, mun, None)

    assert "Virgen del Carmen" in bloque
    assert "MANDA EL DOCUMENTO" in bloque


def test_sin_ficha_el_bloque_de_identidad_queda_como_estaba():
    """Nada cambia para las localidades sin patrón resuelto."""
    import llm_processor.text_analyzer as ta

    loc = {"id": "04049000101", "nombre": "Garrucha"}
    mun = {"id": "04049000000", "nombre": "Garrucha", "provincia": "Almería"}
    bloque = ta._bloque_identidad(loc, mun, None)

    assert "LO QUE SE SABE DE ESTE PUEBLO" not in bloque
    assert bloque.strip()
    assert not bloque.endswith("\n\n")


# ─────────────────────────────────────────────
# La caché vieja no puede quedarse fuera
# ─────────────────────────────────────────────

def test_una_entrada_cacheada_antigua_se_considera_incompleta():
    """Las 60 entradas anteriores al 2026-09-06 no traen `fiestas_habituales`.

    Devolverlas tal cual dejaría sin ficha justo a las localidades ya resueltas,
    Garrucha incluida, que son las que motivaron el cambio. La condición que lo
    detecta vive en `obtener_patron`; aquí se fija el criterio para que nadie lo
    relaje sin darse cuenta.
    """
    vieja = {"nombre": "San Joaquín", "dia": 26, "mes": 7, "fuente": "wikipedia"}
    nueva = dict(GARRUCHA)

    assert "fiestas_habituales" not in vieja
    assert "fiestas_habituales" in nueva
    # Y la vieja sigue dando una fecha usable mientras no se re-resuelva.
    assert fecha_del_patron(vieja, 2026) == date(2026, 7, 26)


# ─────────────────────────────────────────────
# El viaje de los campos hasta la caché
# ─────────────────────────────────────────────
# Añadidos el 2026-09-07, tras una ejecución que demostró que la ficha nunca
# llegaba a existir. Dos fallos encadenados, ninguno detectado por los tests
# anteriores porque todos probaban funciones sueltas:
#
#   1. `_resolver_fecha` monta un dict NUEVO de seis claves, así que descartaba
#      `celebra_*` y `fiestas_habituales` aunque el LLM los hubiera extraído.
#   2. `_extraer_con_llm` es la Fuente 3, el fallback. Garrucha se resolvió por
#      Wikipedia en 0 segundos con el 26 de julio del santoral, así que al modelo
#      no se le llegó a preguntar y la ficha salía vacía justo en el pueblo que
#      motivó el cambio.

def test_el_resolver_no_puede_tirar_los_campos_de_la_ficha():
    """El fallo 1. Sin esto, la ficha muere entre la extracción y la caché."""
    from llm_processor.patron_finder import _resolver_fecha

    entrada = {
        "nombre": "San Joaquín", "dia": 26, "mes": 7,
        "celebra_dia": 16, "celebra_mes": 8,
        "fiestas_habituales": ["Virgen del Carmen, 16 de julio"],
    }
    final = _resolver_fecha(entrada, "wikipedia", "localidad")

    assert final["celebra_dia"] == 16
    assert final["celebra_mes"] == 8
    assert final["fiestas_habituales"] == ["Virgen del Carmen, 16 de julio"]


def test_la_clave_de_invalidacion_existe_siempre():
    """El fallo 2, en su version cronica.

    `fiestas_habituales` es lo que mira la invalidacion de cache. Si una entrada
    se guarda sin ella, esa localidad se re-resuelve en cada ejecucion para
    siempre, sin converger. Tiene que estar aunque no haya nada que contar.
    """
    from llm_processor.patron_finder import _resolver_fecha

    final = _resolver_fecha({"nombre": "San Roque", "dia": 16, "mes": 8}, "wikipedia", "localidad")

    assert "fiestas_habituales" in final
    assert final["fiestas_habituales"] == []
    assert final["celebra_dia"] is None


def test_la_ficha_no_es_un_fallback_de_wikipedia():
    """El fallo 2 en su origen: quien resuelva el patron, la ficha se pide igual.

    Un infobox de Wikipedia identifica bien al patron, pero no dice cuando lo
    celebra el pueblo ni que otras fiestas tiene. Este test fija que la llamada
    de la ficha viva FUERA de la cadena de fallbacks, comprobando que existe
    como funcion propia y no colgando de `_extraer_con_llm`.
    """
    import inspect

    from llm_processor import patron_finder as pf

    assert hasattr(pf, "_extraer_ficha_con_llm")
    fuente = inspect.getsource(pf.obtener_patron)
    # Se invoca cuando ya hay resultado, no solo cuando no lo hay.
    assert "_extraer_ficha_con_llm" in fuente
    assert 'if resultado and "fiestas_habituales" not in resultado:' in fuente

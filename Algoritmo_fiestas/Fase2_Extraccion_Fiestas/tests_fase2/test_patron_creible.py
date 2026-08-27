"""
El patrón que se guarda tiene que poder ser el nombre de un santo.

Los tres casos de aquí son lo que había literalmente en patrones_cache.json el
2026-08-25, los tres con confianza declarada y los tres inservibles. Importa
porque el patrón no se queda quieto: alimenta las consultas de búsqueda de las
patronales y la guarda que impide que el anclaje mueva sus fechas.
"""

import pytest

from llm_processor.patron_finder import (
    _limpiar_nombre,
    _pagina_anclada_al_municipio,
    nombre_de_patron_creible,
)

TOBARRA = {"nombre": "Tobarra", "provincia": "Albacete"}


# ──────────────────────────────────────────────────────────────
# El nombre no se corta en el punto de una abreviatura
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo, esperado", [
    # El patrón de Tobarra quedaba guardado como "Stmo".
    ("Stmo. Cristo de la Antigua", "Stmo. Cristo de la Antigua"),
    ("Ntra. Sra. de los Remedios", "Ntra. Sra. de los Remedios"),
    ("Sto. Domingo de Silos", "Sto. Domingo de Silos"),
    ("Sta. Quiteria", "Sta. Quiteria"),
    # Pero un punto que SÍ cierra frase sigue cortando.
    ("San Andres. Municipio de la provincia de Albacete", "San Andres"),
    ("San Roque. Es el patron desde 1750", "San Roque"),
    # Un nombre es UNA línea: el salto colaba la ciudad de la hermandad.
    ("Santisimo Cristo del Consuelo\nSevilla", "Santisimo Cristo del Consuelo"),
    ("Virgen del Carmen", "Virgen del Carmen"),
])
def test_limpiar_nombre(crudo, esperado):
    assert _limpiar_nombre(crudo) == esperado


# ──────────────────────────────────────────────────────────────
# Lo que no puede ser un santo
# ──────────────────────────────────────────────────────────────

def creible(nombre, loc="Santiago de Mora"):
    return nombre_de_patron_creible(nombre, loc, "Tobarra")


def test_el_nombre_del_pueblo_no_es_un_santo():
    """A Santiago de Mora se le guardó «Santiago de Mora 2026» con confianza alta."""
    assert not creible("Santiago de Mora 2026")
    assert not creible("Santiago de Mora")
    assert not creible("Sierra", loc="Sierra")


def test_pero_compartir_una_palabra_con_el_pueblo_si_vale():
    """Hay pueblos que se llaman como su patrón; se rechaza el topónimo entero, no la palabra."""
    assert creible("Santiago")
    assert creible("Santiago Apóstol")


def test_un_ano_pegado_lo_delata():
    assert not creible("Fiestas 2026")
    assert not creible("San Roque 2026")


def test_una_abreviatura_suelta_no_vale():
    assert not creible("Stmo", loc="Tobarra")
    assert not creible("Ntra", loc="Tobarra")
    assert creible("Stmo. Cristo de la Antigua", loc="Tobarra")


def test_los_patrones_buenos_pasan():
    for n in ("San Isidro", "San Diego de Alcalá", "Virgen del Carmen",
              "Santa Quiteria", "Santisimo Cristo del Consuelo", "San Pedro Regalado"):
        assert creible(n, loc="Un Pueblo"), n


# ──────────────────────────────────────────────────────────────
# La página tiene que estar atada a nuestro municipio
# ──────────────────────────────────────────────────────────────

def test_una_hermandad_sevillana_no_vale_para_una_sierra_de_albacete():
    """
    La página entró porque decía «sierra». Con un nombre corriente, exigir solo
    el nombre del pueblo no filtra nada.
    """
    texto = "La Hermandad del Santisimo Cristo del Consuelo de Sevilla celebra su funcion."
    assert not _pagina_anclada_al_municipio(texto, "https://hermandades-sevilla.es/x", TOBARRA)


def test_la_pagina_del_municipio_si_vale():
    assert _pagina_anclada_al_municipio("Programa de fiestas.", "https://www.tobarra.es/x", TOBARRA)
    assert _pagina_anclada_al_municipio("Fiestas en Tobarra este verano.", "https://x.es", TOBARRA)


def test_la_provincia_tambien_ancla():
    assert _pagina_anclada_al_municipio(
        "Las fiestas de la pedania, en la provincia de Albacete.", "https://x.es", TOBARRA
    )

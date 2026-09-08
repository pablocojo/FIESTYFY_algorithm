"""
La puerta del catálogo en discovery.

Qué cambia
----------
Discovery deja de descubrir en abierto. La fase 1 dice qué fiestas celebra el
pueblo y aquí solo se decide cuáles de ESAS sostiene el material, con sus fechas
reales.

Por qué
-------
Verificado contra internet sobre la ejecución del 2026-09-07:

  * El Barraco produjo unas "Fiestas de Verano 2026" de 29 días que salían de su
    `PROGRAMA-CULTURAL-VERANO-2026.pdf`: aquagym, torneos de petanca y
    presentaciones de libros. Sus fiestas de verdad son del 14 al 17 de
    septiembre, en honor al Santísimo Cristo de Gracia.
  * Garrucha produjo unas patronales de San Joaquín del 20 de febrero al 21 de
    marzo con actos de Cuaresma. Las reales son del 14 al 18 de agosto.

En los dos casos el contenido extraído era real y la etiqueta falsa. Con el
catálogo delante, ninguna de las dos tiene dónde encajar.

Estos tests no ejecutan discovery —es asíncrono y sale a la red—, sino que fijan
las invariantes del prompt que hacen que la puerta sea una puerta y no un muro.
"""

import inspect

import pytest

import llm_processor.text_analyzer as ta


@pytest.fixture(scope="module")
def fuente():
    return inspect.getsource(ta.discover_festivals_for_locality)


# ─────────────────────────────────────────────
# La puerta existe y llega al prompt
# ─────────────────────────────────────────────

def test_el_catalogo_se_construye_y_se_interpola(fuente):
    """De nada sirve armar el bloque si luego no entra en el prompt."""
    assert "bloque_catalogo = (" in fuente
    assert "{bloque_catalogo}" in fuente


def test_el_catalogo_sale_de_la_localidad(fuente):
    """Viaja en la localidad, como `nombre_oficial` viaja en el municipio."""
    assert 'localidad.get("ficha_pueblo")' in fuente


# ─────────────────────────────────────────────
# La invariante de seguridad
# ─────────────────────────────────────────────

def test_sin_catalogo_no_se_cierra_nada(fuente):
    """La condición más importante del cambio.

    Cerrar la puerta con el catálogo vacío equivale a afirmar que el pueblo no
    celebra nada, y eso es peor que devolver alguna fiesta de más: una es una
    ausencia de datos, la otra es una afirmación falsa. Con `_ficha` vacía el
    bloque queda a cadena vacía y el prompt se comporta como antes.
    """
    assert 'if _ficha else ""' in fuente


# ─────────────────────────────────────────────
# Emparejar, no copiar
# ─────────────────────────────────────────────

def test_las_fechas_del_catalogo_son_orientacion(fuente):
    """Las fiestas se mueven de un año a otro.

    Si el modelo copiase las fechas del catálogo en vez de leer las del
    material, la ficha diría lo que el pueblo suele hacer y no lo que hace este
    año, que es justo lo contrario de extraer.
    """
    assert "ORIENTACION" in fuente
    assert "pueden haber cambiado" in fuente
    assert "fechas REALES que trae el material" in fuente


def test_el_nombre_tambien_puede_cambiar(fuente):
    """Lo que empareja es de qué celebración se trata, no cómo se escribe."""
    assert "El nombre tambien puede cambiar" in fuente


# ─────────────────────────────────────────────
# No forzar el encaje
# ─────────────────────────────────────────────

def test_no_encajar_es_una_respuesta_valida(fuente):
    """El riesgo simétrico al de inventar: meter algo a la fuerza en una casilla.

    Sin esta salida, un concierto suelto o una feria de otro pueblo acabarían
    etiquetados como las patronales solo porque caen en las mismas fechas.
    """
    assert "SI NO ENCAJA CON NINGUNA, NO LA CREES" in fuente
    assert "NO fuerces el encaje" in fuente


def test_devolver_menos_que_el_catalogo_es_correcto(fuente):
    """El catálogo dice lo que el pueblo SUELE celebrar, no lo que este material
    demuestra. Sin material que la sostenga, la fiesta no sale: es la misma
    honestidad que ya aplica `programa_estado = no_encontrado`."""
    assert "no pasa nada por devolver menos fiestas" in fuente.lower()


# ─────────────────────────────────────────────
# Los dos casos que motivaron el cambio
# ─────────────────────────────────────────────

def test_el_prompt_nombra_los_casos_que_lo_motivaron(fuente):
    """La agenda cultural y el concierto suelto se nombran expresamente.

    No es decoración: son las dos formas concretas en que el pipeline fabricó
    fiestas inexistentes, y nombrarlas en el prompt es lo que las cierra.
    """
    assert "agenda cultural municipal" in fuente
    assert "concierto suelto" in fuente

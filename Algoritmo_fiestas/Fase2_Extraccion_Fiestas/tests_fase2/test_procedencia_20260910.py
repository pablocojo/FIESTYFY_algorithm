"""
La página de la que salió el programa cuenta como fuente.

El problema
-----------
`solo_fuentes_no_oficiales` se calcula en `_validar_fuentes_fiesta`, que corre en
discovery y solo mira las fuentes que el LLM declara. Pero `url_programa` —la
página que el localizador eligió como programa— se asigna después, en el
enriquecimiento. El campo se decidía antes de existir el dato que más dice sobre
él.

Medido:

    ejecución 20 municipios (2026-09-10)   10 de 81 fichas
    auditoría (2026-09-06)                 15 de 52 fichas

Todas marcaban `solo_fuentes_no_oficiales: True` teniendo su programa en un
dominio oficial: `garrucha.es`, `zafra.es`, `sede.higueradelaserena.es`. Es el
campo con el que un consumidor filtraría lo dudoso, así que equivocarse en el 12%
de los casos hace más daño que no tenerlo.

Qué fijan estos tests
---------------------
Que la corrección sea conservadora. Corregir de más —marcar como oficial algo que
no lo es— sería peor que el problema original: un campo que miente en una
dirección se aprende a ignorar; uno que miente en las dos no sirve para nada.
"""

import pytest

import llm_processor.text_analyzer as ta


URL = "https://garrucha.es/programa"


def _ficha(**kw):
    base = {
        "nombre": "Fiestas de Prueba",
        "url_programa": URL,
        "fuentes": ["busqueda_web"],
        "solo_fuentes_no_oficiales": True,
        "confianza": "baja",
    }
    base.update(kw)
    return base


def _chunks(fuente, url=URL):
    return [{"url": url, "fuente": fuente, "texto": "x"}]


# ─────────────────────────────────────────────
# El caso que lo motiva
# ─────────────────────────────────────────────

def test_un_programa_de_la_web_del_municipio_es_fuente_oficial():
    f = _ficha()
    ta.reconciliar_procedencia(f, _chunks("web_municipio"))
    assert f["solo_fuentes_no_oficiales"] is False
    assert "web_municipio" in f["fuentes"]


def test_la_fuente_no_se_duplica_si_ya_estaba():
    f = _ficha(fuentes=["web_municipio"], solo_fuentes_no_oficiales=False)
    ta.reconciliar_procedencia(f, _chunks("web_municipio"))
    assert f["fuentes"].count("web_municipio") == 1


# ─────────────────────────────────────────────
# Conservador: no corregir de más
# ─────────────────────────────────────────────

def test_un_resultado_de_buscador_no_convierte_nada_en_oficial():
    """El error simétrico, y sería peor que el original."""
    f = _ficha()
    ta.reconciliar_procedencia(f, _chunks("busqueda_web"))
    assert f["solo_fuentes_no_oficiales"] is True
    assert f["fuentes"] == ["busqueda_web"]


def test_la_prensa_regional_tampoco_es_oficial():
    """Que un periódico cuente las fiestas no las hace fuente oficial."""
    f = _ficha()
    ta.reconciliar_procedencia(f, _chunks("prensa_regional"))
    assert f["solo_fuentes_no_oficiales"] is True


def test_sin_url_de_programa_no_se_toca_nada():
    f = _ficha(url_programa=None)
    ta.reconciliar_procedencia(f, _chunks("web_municipio"))
    assert f["solo_fuentes_no_oficiales"] is True


def test_si_la_url_no_esta_entre_los_chunks_no_se_asume_nada():
    """El programa puede venir de una página que no llegó a indexarse. Sin
    etiqueta que consultar, no se inventa una."""
    f = _ficha()
    ta.reconciliar_procedencia(f, _chunks("web_municipio", url="https://otra.es/x"))
    assert f["solo_fuentes_no_oficiales"] is True


def test_sin_chunks_no_revienta():
    f = _ficha()
    ta.reconciliar_procedencia(f, [])
    ta.reconciliar_procedencia(f, None)
    assert f["solo_fuentes_no_oficiales"] is True


# ─────────────────────────────────────────────
# Lo que deliberadamente NO hace
# ─────────────────────────────────────────────

def test_la_confianza_no_se_sube():
    """`_validar_fuentes_fiesta` fuerza la confianza a baja cuando no hay fuente
    oficial, pero pudo bajarla también por otros motivos y aquí no hay forma de
    saberlo. Subirla a ciegas sería afirmar una seguridad que nadie ha
    comprobado."""
    f = _ficha(confianza="baja")
    ta.reconciliar_procedencia(f, _chunks("web_municipio"))
    assert f["solo_fuentes_no_oficiales"] is False
    assert f["confianza"] == "baja"


def test_no_se_deduce_la_oficialidad_del_dominio():
    """La etiqueta sale de los chunks, no del nombre del dominio.

    Un `.es` con pinta de ayuntamiento pero etiquetado como búsqueda sigue siendo
    búsqueda: dos criterios que pueden discrepar es peor que uno imperfecto, y si
    un documento está mal etiquetado el fallo está en quien lo etiquetó.
    """
    f = _ficha(url_programa="https://www.ayuntamiento-de-algo.es/fiestas")
    ta.reconciliar_procedencia(
        f, _chunks("busqueda_web", url="https://www.ayuntamiento-de-algo.es/fiestas")
    )
    assert f["solo_fuentes_no_oficiales"] is True

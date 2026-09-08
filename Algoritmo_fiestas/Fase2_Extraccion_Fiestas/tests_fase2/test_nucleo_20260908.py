"""
El núcleo de la fiesta: dos intervalos en vez de uno.

De dónde sale
-------------
Una fiesta patronal no es un bloque homogéneo. Tiene unos días centrales
—procesiones, desfiles, verbena— y una periferia de triduos, novenas y pregones
que puede empezar semanas antes.

Hasta ahora `fecha_inicio` y `fecha_fin` salían del primer y el último acto del
documento, así que la periferia estiraba el rango. La Semana Santa de Garrucha
2026 se declaraba del 18 de marzo al 6 de abril —diecisiete días, tres de ellos
sin un solo acto— cuando va del Domingo de Ramos, el 29, al de Resurrección, el
5. Sus tres primeros días eran esto:

    2026-03-18  Triduo a Ntro. Padre Jesús Nazareno
    2026-03-19  XXII Pregón de la Semana Santa
    2026-03-20  Triduo a Ntro. Padre Jesús Nazareno

Actos reales, de esa misma fiesta, pero preparatorios.

Qué se hace
-----------
No se descarta nada. El rango completo sigue en `fecha_inicio`/`fecha_fin` y el
programa entero se conserva. Se añade un segundo dato, `nucleo_inicio` y
`nucleo_fin`, que dice cuándo es la fiesta de verdad. Quien consuma la base de
datos elige cuál usa.

Qué fijan estos tests
---------------------
Sobre todo que el núcleo NO se invente. Es el riesgo del cambio: un núcleo
inventado sería peor que no tenerlo, porque el rango completo al menos está
respaldado por actos.
"""

import asyncio

import pytest

import llm_processor.text_analyzer as ta


def _fiesta(dias, nombre="Fiestas de Prueba"):
    return {
        "nombre": nombre,
        "fecha_inicio": dias[0][0] if dias else None,
        "fecha_fin": dias[-1][0] if dias else None,
        "programa": [
            {"dia": i + 1, "fecha": f, "eventos": ev}
            for i, (f, ev) in enumerate(dias)
        ],
    }


ACTO = [{"hora": "20:00", "descripcion": "Verbena con orquesta"}]


# ─────────────────────────────────────────────
# Sin material no hay núcleo
# ─────────────────────────────────────────────

def test_sin_programa_no_hay_nucleo():
    """El caso mayoritario: 33 de las 48 fichas del 2026-09-08 no tienen actos.

    Deducir el núcleo de la nada sería inventar, que es justo lo que llevamos
    quitando del pipeline.
    """
    f = {"nombre": "X", "fecha_inicio": "2026-08-01", "fecha_fin": "2026-08-05", "programa": []}
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] is None
    assert f["nucleo_fin"] is None


def test_dias_sin_actos_no_cuentan_como_programa():
    """Un programa con días vacíos es un programa vacío."""
    f = _fiesta([("2026-08-01", []), ("2026-08-02", [])])
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] is None


# ─────────────────────────────────────────────
# El caso trivial no gasta una llamada
# ─────────────────────────────────────────────

def test_un_solo_dia_con_actos_es_su_propio_nucleo(monkeypatch):
    """Preguntarle al modelo dónde está el núcleo de un día suelto es tirar una
    llamada. Se resuelve en código."""
    def _no_llamar(*a, **k):
        raise AssertionError("no debería preguntarse al modelo")

    monkeypatch.setattr(ta, "llm_chat_json", _no_llamar)
    f = _fiesta([("2026-06-23", ACTO)])
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] == f["nucleo_fin"] == "2026-06-23"


# ─────────────────────────────────────────────
# La validación: el núcleo no se inventa
# ─────────────────────────────────────────────

def _con_respuesta(monkeypatch, datos):
    async def _fake(*a, **k):
        return datos
    monkeypatch.setattr(ta, "llm_chat_json", _fake)


DIAS = [("2026-08-14", ACTO), ("2026-08-15", ACTO), ("2026-08-16", ACTO), ("2026-08-17", ACTO)]


def test_una_respuesta_valida_se_acepta(monkeypatch):
    _con_respuesta(monkeypatch, {"nucleo_inicio": "2026-08-15", "nucleo_fin": "2026-08-16"})
    f = _fiesta(DIAS)
    asyncio.run(ta.elegir_nucleo(f))
    assert (f["nucleo_inicio"], f["nucleo_fin"]) == ("2026-08-15", "2026-08-16")


def test_una_fecha_que_no_esta_en_el_programa_se_rechaza(monkeypatch):
    """El modelo no puede inventarse un día que no tiene actos.

    Si lo hace, el núcleo queda vacío: es preferible no tener el dato a tener
    uno que no sostiene ningún acto.
    """
    _con_respuesta(monkeypatch, {"nucleo_inicio": "2026-08-10", "nucleo_fin": "2026-08-16"})
    f = _fiesta(DIAS)
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] is None


def test_un_nucleo_al_reves_se_rechaza(monkeypatch):
    _con_respuesta(monkeypatch, {"nucleo_inicio": "2026-08-17", "nucleo_fin": "2026-08-14"})
    f = _fiesta(DIAS)
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] is None


def test_json_malformado_deja_el_nucleo_vacio(monkeypatch):
    """Pasó de verdad en la prueba del 2026-09-08 con las patronales de San
    Roque de Velefique: el modelo devolvió algo no parseable. La ficha se quedó
    sin núcleo, que es el comportamiento correcto."""
    _con_respuesta(monkeypatch, None)
    f = _fiesta(DIAS)
    asyncio.run(ta.elegir_nucleo(f))
    assert f["nucleo_inicio"] is None
    assert f["nucleo_fin"] is None


# ─────────────────────────────────────────────
# El rango completo no se toca
# ─────────────────────────────────────────────

def test_el_rango_completo_sobrevive_intacto(monkeypatch):
    """El núcleo AÑADE un dato, no sustituye al que había.

    Los actos preparatorios siguen en el programa y las fechas completas siguen
    siendo las del documento. Si alguien convierte esto en un recorte, se pierde
    información real.
    """
    _con_respuesta(monkeypatch, {"nucleo_inicio": "2026-08-15", "nucleo_fin": "2026-08-16"})
    f = _fiesta(DIAS)
    asyncio.run(ta.elegir_nucleo(f))
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-14", "2026-08-17")
    assert len(f["programa"]) == 4

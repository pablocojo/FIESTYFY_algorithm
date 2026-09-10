"""
La última puerta: la misma fiesta contada dos veces.

De dónde sale
-------------
Ejecución de 20 municipios del 2026-09-10: **9 pares duplicados**, frente a 1 en
la de siete municipios del día anterior. Dos casos testigo:

    Fuentespina (catálogo de 3, salida de 4)
      2026-05-29 → 06-02  5d  ...en honor al Padre Eterno
      2026-06-13 → 06-15  0d  ...en honor al Padre Eterno    <- la misma

    Arroyo de la Luz
      2026-07-31 → 08-30  12d  FestivArroyo Verano 2026
      2026-07-31 → 09-27  12d  Fiestas de Festivarroyo       <- la misma

Por qué salen más en estos pueblos: sus catálogos tienen dos o tres entradas, no
siete o diez. Con el catálogo corto casi cualquier ficha encaja en alguna
casilla, y encaja VARIAS veces. La puerta del catálogo protege bien cuando el
catálogo es rico y mal cuando es pobre.

Por qué va la última
--------------------
`descartar_duplicados_internos` mira fichas vacías y `descartar_patronales_duplicadas`
solo entiende de patronales. Ninguno ve la lista ENTERA de la localidad, que es
donde el duplicado se reconoce.

Qué fijan estos tests
---------------------
Sobre todo que no se pierdan fiestas reales. Fusionar de más es peor que dejar
una repetida: un duplicado se ve y se corrige; una fiesta borrada no vuelve.
"""

import asyncio

import pytest

import llm_processor.text_analyzer as ta


LOC = {"id": "09141000101", "nombre": "Fuentespina", "ficha_pueblo": ""}


def _f(nombre, ini, fin, dias=0, nucleo=None, url=None):
    return {
        "nombre": nombre,
        "fecha_inicio": ini,
        "fecha_fin": fin,
        "programa": [{"dia": i + 1, "fecha": ini, "eventos": [{"hora": "20:00", "descripcion": "x"}]}
                     for i in range(dias)],
        "nucleo_inicio": nucleo[0] if nucleo else None,
        "nucleo_fin": nucleo[1] if nucleo else None,
        "url_programa": url,
    }


def _responde(monkeypatch, datos):
    async def _fake(*a, **k):
        return datos
    monkeypatch.setattr(ta, "llm_chat_json", _fake)


# ─────────────────────────────────────────────
# No preguntar cuando no hace falta
# ─────────────────────────────────────────────

def test_con_menos_de_dos_fichas_no_se_pregunta(monkeypatch):
    """Es la mayoría de localidades. Preguntar sería tirar una llamada."""
    def _no_llamar(*a, **k):
        raise AssertionError("no debería preguntarse al modelo")

    monkeypatch.setattr(ta, "llm_chat_json", _no_llamar)
    una = [_f("Fiestas de X", "2026-08-01", "2026-08-04", 3)]
    assert asyncio.run(ta.unificar_duplicados(una, LOC)) == una
    assert asyncio.run(ta.unificar_duplicados([], LOC)) == []


# ─────────────────────────────────────────────
# El caso Fuentespina
# ─────────────────────────────────────────────

def test_sobrevive_la_ficha_con_mas_programa(monkeypatch):
    """El Padre Eterno por partida doble: 5 días de programa contra 0."""
    _responde(monkeypatch, {"grupos": [[0, 1]]})
    fs = [
        _f("Fiestas en honor al Padre Eterno", "2026-05-29", "2026-06-02", 5),
        _f("Fiestas en honor al Padre Eterno", "2026-06-13", "2026-06-15", 0),
    ]
    r = asyncio.run(ta.unificar_duplicados(fs, LOC))
    assert len(r) == 1
    assert r[0]["fecha_inicio"] == "2026-05-29"
    assert len(r[0]["programa"]) == 5


def test_a_igualdad_de_programa_gana_la_que_tiene_nucleo(monkeypatch):
    """El núcleo es señal de que la ficha se entendió mejor."""
    _responde(monkeypatch, {"grupos": [[0, 1]]})
    fs = [
        _f("A", "2026-08-01", "2026-08-04", 3),
        _f("B", "2026-08-02", "2026-08-05", 3, nucleo=("2026-08-02", "2026-08-04")),
    ]
    r = asyncio.run(ta.unificar_duplicados(fs, LOC))
    assert len(r) == 1 and r[0]["nombre"] == "B"


def test_la_fuente_de_la_descartada_se_conserva(monkeypatch):
    """No se fusionan los programas —produciría actos incompatibles— pero la
    URL sí se guarda: es la trazabilidad de dónde salió."""
    _responde(monkeypatch, {"grupos": [[0, 1]]})
    fs = [
        _f("A", "2026-08-01", "2026-08-04", 5, url="https://a.es/programa"),
        _f("B", "2026-08-02", "2026-08-05", 0, url="https://b.es/otro"),
    ]
    r = asyncio.run(ta.unificar_duplicados(fs, LOC))
    assert "https://b.es/otro" in r[0]["fuentes"]
    assert len(r[0]["programa"]) == 5


# ─────────────────────────────────────────────
# No perder fiestas reales
# ─────────────────────────────────────────────

def test_sin_grupos_no_se_toca_nada(monkeypatch):
    """La respuesta habitual: en la mayoría de localidades no hay duplicados."""
    _responde(monkeypatch, {"grupos": []})
    fs = [_f("A", "2026-08-01", "2026-08-04", 2), _f("B", "2026-09-01", "2026-09-03", 1)]
    assert len(asyncio.run(ta.unificar_duplicados(fs, LOC))) == 2


def test_si_el_modelo_falla_no_se_borra_nada(monkeypatch):
    """Un error nunca debe costar fiestas. Es la salvaguarda principal."""
    _responde(monkeypatch, None)
    fs = [_f("A", "2026-08-01", "2026-08-04", 2), _f("B", "2026-09-01", "2026-09-03", 1)]
    assert len(asyncio.run(ta.unificar_duplicados(fs, LOC))) == 2


def test_una_respuesta_con_forma_rara_no_borra_nada(monkeypatch):
    _responde(monkeypatch, {"grupos": "0,1"})
    fs = [_f("A", "2026-08-01", "2026-08-04", 2), _f("B", "2026-09-01", "2026-09-03", 1)]
    assert len(asyncio.run(ta.unificar_duplicados(fs, LOC))) == 2


def test_indices_inventados_se_ignoran(monkeypatch):
    """Si el modelo nombra una ficha que no existe, el grupo se queda en uno
    solo y no se descarta nada."""
    _responde(monkeypatch, {"grupos": [[0, 99]]})
    fs = [_f("A", "2026-08-01", "2026-08-04", 2), _f("B", "2026-09-01", "2026-09-03", 1)]
    assert len(asyncio.run(ta.unificar_duplicados(fs, LOC))) == 2


def test_un_grupo_de_uno_no_descarta(monkeypatch):
    _responde(monkeypatch, {"grupos": [[1]]})
    fs = [_f("A", "2026-08-01", "2026-08-04", 2), _f("B", "2026-09-01", "2026-09-03", 1)]
    assert len(asyncio.run(ta.unificar_duplicados(fs, LOC))) == 2


def test_tres_repetidas_dejan_una(monkeypatch):
    _responde(monkeypatch, {"grupos": [[0, 1, 2]]})
    fs = [
        _f("A", "2026-08-01", "2026-08-04", 1),
        _f("B", "2026-08-02", "2026-08-05", 7),
        _f("C", "2026-08-03", "2026-08-06", 3),
    ]
    r = asyncio.run(ta.unificar_duplicados(fs, LOC))
    assert len(r) == 1 and r[0]["nombre"] == "B"


# ─────────────────────────────────────────────
# El prompt tiene que dejar decir que no
# ─────────────────────────────────────────────

def test_el_prompt_distingue_solape_de_nucleo_y_de_periferia():
    """El riesgo simétrico: fusionar una romería con las patronales por caer
    dentro de su periodo. El núcleo es lo que permite distinguirlas, y el prompt
    tiene que decirlo."""
    import inspect

    fuente = inspect.getsource(ta.unificar_duplicados)
    assert "NUCLEOS se solapan" in fuente
    assert "NO basta" in fuente
    assert "QUE NO ES DUPLICADO" in fuente
    assert "peor que" in fuente

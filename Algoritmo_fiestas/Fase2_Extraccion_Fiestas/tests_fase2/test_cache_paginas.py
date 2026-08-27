"""
Caché en disco de páginas, añadida el 2026-08-24.

Existe por la varianza medida entre el 23 y el 24 de agosto: con el mismo
código, Cordovilla dio 25 documentos un día y 4 al siguiente. Sin un suelo
estable no se puede saber si un cambio mejora las cosas.
"""

import asyncio
import time

import pytest

import cache_paginas
import scraper.google_search as gs


@pytest.fixture(autouse=True)
def cache_temporal(tmp_path, monkeypatch):
    """Cada test con su carpeta: nada se filtra entre tests ni a la caché real."""
    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_DIR", str(tmp_path / "paginas"))
    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_ACTIVA", True)
    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_TTL_DIAS", 7)
    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_TTL_MUERTAS_DIAS", 30)
    monkeypatch.setattr(cache_paginas, "CACHE_BUSQUEDAS_TTL_DIAS", 3)
    cache_paginas.reiniciar_estadisticas()
    yield


def test_lo_guardado_se_recupera_igual():
    cache_paginas.guardar("https://a.es/programa", "el programa de fiestas", ["https://a.es/p.pdf"])
    assert cache_paginas.leer("https://a.es/programa") == (
        "el programa de fiestas", ["https://a.es/p.pdf"], "", [],
    )


def test_una_url_desconocida_no_devuelve_nada():
    assert cache_paginas.leer("https://nunca-vista.es") is None


def test_dos_urls_distintas_no_se_pisan():
    """El nombre del fichero sale de un hash; una colisión mezclaría dos webs."""
    cache_paginas.guardar("https://a.es/x", "texto A", [])
    cache_paginas.guardar("https://b.es/x", "texto B", [])
    assert cache_paginas.leer("https://a.es/x")[0] == "texto A"
    assert cache_paginas.leer("https://b.es/x")[0] == "texto B"


def test_una_entrada_caducada_se_ignora(monkeypatch):
    ahora = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: ahora)
    cache_paginas.guardar("https://a.es", "viejo", [])

    monkeypatch.setattr(time, "time", lambda: ahora + 8 * 86400)   # TTL de 7 días
    assert cache_paginas.leer("https://a.es") is None


def test_los_fallos_estables_duran_mas_que_lo_bueno(monkeypatch):
    """Un 404 no se arregla solo; un programa sí puede publicarse otra vez."""
    ahora = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: ahora)
    cache_paginas.guardar("https://viva.es", "texto", [])
    cache_paginas.guardar("https://muerta.es", "", [], "http_404")

    # A los 10 días: lo bueno ha caducado (TTL 7), el 404 aguanta (TTL 30).
    monkeypatch.setattr(time, "time", lambda: ahora + 10 * 86400)
    assert cache_paginas.leer("https://viva.es") is None
    assert cache_paginas.leer("https://muerta.es") == ("", [], "http_404", [])


def test_desactivada_no_lee_ni_escribe(monkeypatch):
    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_ACTIVA", False)
    cache_paginas.guardar("https://a.es", "texto", [])
    assert cache_paginas.leer("https://a.es") is None


def test_un_directorio_no_escribible_no_tumba_la_ejecucion(monkeypatch):
    """La caché es una ayuda; si falla, se sigue sin ella."""
    def revienta(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(cache_paginas.os, "makedirs", revienta)
    cache_paginas.guardar("https://a.es", "texto", [])   # no debe lanzar


# ──────────────────────────────────────────────────────────────
# Integración con la descarga
# ──────────────────────────────────────────────────────────────

def _sin_red(monkeypatch, contador):
    async def descarga(session, url, timeout, reg=None):
        contador["n"] += 1
        return "texto descargado", ["https://x.es/p.pdf"], []
    monkeypatch.setattr(gs, "_descargar_una_vez", descarga)
    monkeypatch.setattr(gs, "DESCARGA_BACKOFF", 0)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_DIR", cache_paginas.CACHE_PAGINAS_DIR)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_ACTIVA", True)


def test_la_segunda_vez_no_se_baja_de_la_red(monkeypatch):
    """Es lo que hace reproducible una ejecución."""
    n = {"n": 0}
    _sin_red(monkeypatch, n)
    primera = asyncio.run(gs._fetch_page_content(None, "https://x.es/noticia"))
    segunda = asyncio.run(gs._fetch_page_content(None, "https://x.es/noticia"))
    assert primera == segunda == ("texto descargado", ["https://x.es/p.pdf"], [])
    assert n["n"] == 1, "la segunda llamada volvió a la red"


def test_un_404_se_recuerda_y_no_se_vuelve_a_pedir(monkeypatch):
    n = {"n": 0}

    async def muerta(session, url, timeout, reg=None):
        n["n"] += 1
        gs._anotar(reg, url, "http_404")
        return "", [], []

    monkeypatch.setattr(gs, "_descargar_una_vez", muerta)
    monkeypatch.setattr(gs, "DESCARGA_BACKOFF", 0)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_DIR", cache_paginas.CACHE_PAGINAS_DIR)

    r1, r2 = [], []
    asyncio.run(gs._fetch_page_content(None, "https://muerta.es", r1))
    asyncio.run(gs._fetch_page_content(None, "https://muerta.es", r2))
    assert n["n"] == 1
    # Sigue contándose como pérdida las dos veces: el recuento no debe mentir.
    assert r1 == r2 == [("https://muerta.es", "http_404")]


def test_un_timeout_no_se_guarda(monkeypatch):
    """Congelar un fallo pasajero nos cerraría la fuente durante días."""
    n = {"n": 0}

    async def lenta(session, url, timeout, reg=None):
        n["n"] += 1
        gs._anotar(reg, url, "error_TimeoutError")
        return "", [], []

    monkeypatch.setattr(gs, "_descargar_una_vez", lenta)
    monkeypatch.setattr(gs, "DESCARGA_BACKOFF", 0)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_DIR", cache_paginas.CACHE_PAGINAS_DIR)

    asyncio.run(gs._fetch_page_content(None, "https://lenta.es", []))
    intentos_primera = n["n"]
    asyncio.run(gs._fetch_page_content(None, "https://lenta.es", []))
    assert n["n"] == intentos_primera * 2, "se guardó un timeout y no se reintentó"


def test_un_403_no_se_guarda(monkeypatch):
    """Puede ser un bloqueo temporal por insistir; darlo por muerto un mes sobra."""
    n = {"n": 0}

    async def bloqueada(session, url, timeout, reg=None):
        n["n"] += 1
        gs._anotar(reg, url, "http_403")
        return "", [], []

    monkeypatch.setattr(gs, "_descargar_una_vez", bloqueada)
    monkeypatch.setattr(gs, "DESCARGA_BACKOFF", 0)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_DIR", cache_paginas.CACHE_PAGINAS_DIR)

    asyncio.run(gs._fetch_page_content(None, "https://bloqueada.es", []))
    asyncio.run(gs._fetch_page_content(None, "https://bloqueada.es", []))
    assert n["n"] == 2


def test_el_resumen_cuenta_aciertos_y_fallos(monkeypatch):
    n = {"n": 0}
    _sin_red(monkeypatch, n)
    asyncio.run(gs._fetch_page_content(None, "https://x.es/1"))   # fallo de caché
    asyncio.run(gs._fetch_page_content(None, "https://x.es/1"))   # acierto
    resumen = cache_paginas.resumen()
    assert "1/2 URLs desde caché (50%)" in resumen
    assert "1 guardadas" in resumen


# ──────────────────────────────────────────────────────────────
# Caché de consultas
# ──────────────────────────────────────────────────────────────

def test_una_consulta_guardada_se_reaprovecha():
    """
    Sin esto la ejecución no es reproducible: cachear las páginas dejaba
    estable el NÚMERO de documentos (28 y 27 en Tobarra, donde antes hubo 25 y
    4) pero no CUÁLES, porque los motores no devuelven dos veces la misma lista.
    """
    resultados = [{"titulo": "t", "snippet": "s", "url": "https://a.es"}]
    cache_paginas.guardar_busqueda("Fiestas  de   Tobarra 2026", resultados)
    # La clave normaliza espacios y mayúsculas: es la misma consulta.
    assert cache_paginas.leer_busqueda("fiestas de tobarra 2026") == resultados


def test_una_consulta_sin_resultados_no_se_guarda():
    """Un motor que falla es un fallo, no un dato: congelarlo cerraría la fuente."""
    cache_paginas.guardar_busqueda("consulta que fallo", [])
    assert cache_paginas.leer_busqueda("consulta que fallo") is None


def test_las_consultas_caducan_antes_que_las_paginas(monkeypatch):
    ahora = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: ahora)
    cache_paginas.guardar_busqueda("q", [{"url": "https://a.es"}])
    cache_paginas.guardar("https://a.es", "texto", [])

    # A los 4 días la consulta ha caducado (TTL 3) y la página no (TTL 7).
    monkeypatch.setattr(time, "time", lambda: ahora + 4 * 86400)
    assert cache_paginas.leer_busqueda("q") is None
    assert cache_paginas.leer("https://a.es") is not None


def test_el_motor_no_se_toca_si_la_consulta_esta_guardada(monkeypatch):
    llamadas = {"n": 0}

    def motor(query):
        llamadas["n"] += 1
        return [{"titulo": "t", "snippet": "s", "url": "https://a.es/x"}]

    monkeypatch.setattr(gs, "_sync_fetch_ddg", motor)
    monkeypatch.setattr(gs, "_resultados_coherentes", lambda q, r: True)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_PAGINAS_DIR", cache_paginas.CACHE_PAGINAS_DIR)
    monkeypatch.setattr(gs.cache_paginas, "CACHE_BUSQUEDAS_TTL_DIAS", 3)

    primera = asyncio.run(gs._fetch_search_results(None, "fiestas de x 2026"))
    segunda = asyncio.run(gs._fetch_search_results(None, "fiestas de x 2026"))
    assert primera == segunda
    assert llamadas["n"] == 1, "la segunda consulta volvió a pegarle al motor"

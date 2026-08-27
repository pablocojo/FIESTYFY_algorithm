"""
Fase de RECOGIDA: que se descargue todo lo que está publicado.

Medido el 2026-08-23 sobre doce localidades de Tobarra y Aranda de Duero: los
buscadores devolvían 386 resultados y se descargaban 60 páginas, el 16%. El
resto existía solo como una línea de snippet, y de ahí venían casi todas las
fiestas que no se encontraban. Descargar es lo más barato del proceso —7
segundos frente a los 122 que se van en RRSS—, así que el techo estaba mal
puesto.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import scraper.google_search as gs
from fuentes import misma_web
from scraper.google_search import _build_queries, _mismo_nombre

MUNICIPIO = {
    "nombre": "Tobarra", "sitio_web": "https://www.tobarra.es",
    "provincia": "Albacete", "comunidad_autonoma": "Castilla-La Mancha",
}


# ──────────────────────────────────────────────────────────────
# D — no rastrear dos veces la misma web
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b, igual", [
    # El caso real: Fase 1 guarda la web de Cordovilla y Los Mardos con "http://"
    # y "www.", y la del municipio sin ellos. Eran 26 segundos por localidad.
    ("http://www.tobarra.es/", "https://www.tobarra.es", True),
    ("https://TOBARRA.es", "http://tobarra.es/", True),
    ("https://www.tobarra.es", "https://www.tobarra.es", True),
    # Webs de verdad distintas: hay que rastrearlas.
    ("http://www.quemada.es/", "https://www.arandadeduero.es/", False),
    ("https://www.elchedelasierra.es", "https://www.tobarra.es", False),
    ("", "https://www.tobarra.es", False),
])
def test_misma_web(a, b, igual):
    assert misma_web(a, b) is igual


# ──────────────────────────────────────────────────────────────
# C — no desperdiciar consultas
# ──────────────────────────────────────────────────────────────

def test_la_capital_no_repite_su_nombre_en_la_consulta():
    """
    "fiestas patronales Tobarra Tobarra 2026" no devolvió jamás un resultado, y
    era una de cada cinco consultas de la ejecución.
    """
    capital = {"nombre": "Tobarra", "sitio_web": "https://www.tobarra.es"}
    queries = _build_queries(capital, MUNICIPIO, 2026)
    assert not any("Tobarra Tobarra" in q for q in queries)
    assert "fiestas patronales Tobarra 2026" in queries


def test_la_pedania_si_lleva_el_municipio():
    """Ahí el municipio desambigua, que es para lo que está."""
    pedania = {"nombre": "Cordovilla"}
    queries = _build_queries(pedania, MUNICIPIO, 2026)
    assert "fiestas patronales Cordovilla Tobarra 2026" in queries


def test_no_se_repiten_consultas():
    capital = {"nombre": "Tobarra", "sitio_web": "https://www.tobarra.es"}
    queries = _build_queries(capital, MUNICIPIO, 2026)
    assert len(queries) == len({" ".join(q.lower().split()) for q in queries})


@pytest.mark.parametrize("a, b, igual", [
    ("Tobarra", "Tobarra", True),
    ("Aranda de Duero", "aranda de duero", True),
    ("Artomaña", "Artomana", True),
    ("Cordovilla", "Tobarra", False),
])
def test_mismo_nombre(a, b, igual):
    assert _mismo_nombre(a, b) is igual


def _correr_busqueda(loc, mun, respuesta):
    """Ejecuta search_locality_web con los motores simulados. Devuelve las queries."""
    lanzadas = []

    async def fake_search(session, q):
        lanzadas.append(q)
        return respuesta(q)

    async def main():
        with patch.object(gs, "_fetch_search_results", fake_search), \
             patch.object(gs, "_fetch_page_content", AsyncMock(return_value=("texto", [], []))), \
             patch.object(gs, "get_query_delay", lambda: 0):
            await gs.search_locality_web(loc, mun, 2026, set())

    asyncio.run(main())
    return lanzadas


def test_una_consulta_con_site_que_falla_se_reintenta_sin_el_operador():
    """
    13 de 52 consultas volvían vacías y la mayoría llevaban `site:`, que es lo
    que más rechazan los motores.
    """
    vacio_si_site = lambda q: [] if "site:" in q else [
        {"titulo": "t", "snippet": "s", "url": "https://ejemplo.es/a"}
    ]
    lanzadas = _correr_busqueda({"nombre": "Cordovilla"}, MUNICIPIO, vacio_si_site)

    con_site = [q for q in lanzadas if "site:" in q]
    assert con_site, "el escenario no llegó a probar el operador site:"
    for q in con_site:
        assert q.replace(f" site:www.tobarra.es", "") in lanzadas


def test_no_se_reintenta_si_la_consulta_con_site_funciona():
    todo_ok = lambda q: [{"titulo": "t", "snippet": "s", "url": "https://ejemplo.es/a"}]
    lanzadas = _correr_busqueda({"nombre": "Cordovilla"}, MUNICIPIO, todo_ok)
    assert len(lanzadas) == len(set(lanzadas))
    # La versión sin site: de la consulta con site: no debe haberse lanzado.
    assert "fiestas patronales Cordovilla 2026" not in lanzadas


# ──────────────────────────────────────────────────────────────
# B3 — buscar por el nombre del patrón
# ──────────────────────────────────────────────────────────────

def test_se_busca_por_el_patron_cuando_se_conoce():
    """
    Es lo que identifica una fiesta patronal. Sin esto dependíamos de que el
    snippet correcto apareciera ese día: la patronal de mayo de Tobarra entró en
    dos ejecuciones y se perdió en la tercera.
    """
    loc = {"nombre": "Tobarra", "sitio_web": "https://www.tobarra.es",
           "patron_nombre": "Stmo. Cristo de la Antigua"}
    queries = _build_queries(loc, MUNICIPIO, 2026)
    assert "fiestas patronales Stmo. Cristo de la Antigua Tobarra 2026" in queries
    assert "Tobarra fiestas patronales Stmo. Cristo de la Antigua" in queries


def test_sin_patron_no_se_inventan_consultas():
    queries = _build_queries({"nombre": "Tobarra"}, MUNICIPIO, 2026)
    assert len(queries) == 4


# ──────────────────────────────────────────────────────────────
# A — el techo de descarga
# ──────────────────────────────────────────────────────────────

def test_el_techo_de_descarga_deja_pasar_lo_que_encuentran_los_motores():
    """
    Con 5, de 386 resultados se descargaban 60 páginas. Los buscadores devuelven
    entre 26 y 40 resultados por localidad, así que el tope tiene que estar por
    encima de eso para no ser el que decide.
    """
    from config import DDG_MAX_URLS_TO_FOLLOW, DDG_CONTENT_MAX_CHARS, BUSQUEDA_MAX_PDFS_TOTAL
    assert DDG_MAX_URLS_TO_FOLLOW >= 25
    # 15.000 cortaba por la mitad el PDF de un programa de cien actos.
    assert DDG_CONTENT_MAX_CHARS >= 40000
    # El programa de actos casi siempre vive en un PDF.
    assert BUSQUEDA_MAX_PDFS_TOTAL >= 15


def test_se_descargan_todas_las_urls_hasta_el_tope():
    from config import DDG_MAX_URLS_TO_FOLLOW

    muchos = lambda q: [
        {"titulo": f"t{i}", "snippet": "s", "url": f"https://ejemplo{i}.es/{abs(hash(q))%97}"}
        for i in range(10)
    ]
    bajadas = []

    async def fake_page(session, url, registro=None):
        bajadas.append(url)
        return ("texto de la pagina", [], [])

    async def main():
        with patch.object(gs, "_fetch_search_results", AsyncMock(side_effect=lambda s, q: muchos(q))), \
             patch.object(gs, "_fetch_page_content", fake_page), \
             patch.object(gs, "get_query_delay", lambda: 0):
            return await gs.search_locality_web({"nombre": "Cordovilla"}, MUNICIPIO, 2026, set())

    docs = asyncio.run(main())
    assert len(bajadas) > 5, "sigue cortando en el tope viejo"
    assert len(bajadas) <= DDG_MAX_URLS_TO_FOLLOW
    assert len(docs) >= len(bajadas)     # + el bloque de snippets


def test_cada_url_perdida_deja_su_motivo():
    """
    El 2026-08-24, en Cordovilla, de 25 URLs seguidas solo 4 acabaron en
    documento y el log no decía nada de las otras 21: todas las salidas en vacío
    de _fetch_page_content callaban. Que cada pérdida deje su motivo es lo que
    permite saber si hay que reintentar, esperar o descartar.
    """
    registro: list[tuple[str, str]] = []
    gs._anotar(registro, "https://a.es", "error_TimeoutError")
    gs._anotar(registro, "https://b.es", "error_TimeoutError")
    gs._anotar(registro, "https://c.es", "http_403")

    resumen = gs._resumen_descartes(registro, 25)
    assert "22/25 con texto" in resumen
    assert "error_TimeoutError=2" in resumen
    assert "http_403=1" in resumen
    # El motivo más repetido va primero: es el que hay que atacar.
    assert resumen.index("error_TimeoutError") < resumen.index("http_403")

    # Sin pérdidas no se inventa una lista vacía de motivos.
    assert gs._resumen_descartes([], 25) == "25/25 con texto"
    # Y un registro None (llamada suelta, sin instrumentar) no revienta.
    gs._anotar(None, "https://d.es", "da_igual")


def _con_descarga(monkeypatch, fn):
    monkeypatch.setattr(gs, "_descargar_una_vez", fn)
    monkeypatch.setattr(gs, "DESCARGA_BACKOFF", 0)


def test_un_timeout_pasajero_se_reintenta(monkeypatch):
    """Aljubé perdió 10 de 15 PDFs por timeout el 2026-08-24. Un PDF tarda."""
    n = {"i": 0}

    async def flaky(session, url, timeout, reg=None):
        n["i"] += 1
        if n["i"] < 2:
            gs._anotar(reg, url, "error_TimeoutError")
            return "", [], []
        return "el programa", ["http://p.pdf"], []

    _con_descarga(monkeypatch, flaky)
    registro = []
    texto, pdfs, _ = asyncio.run(gs._fetch_page_content(None, "http://x.pdf", registro))
    assert texto == "el programa" and pdfs == ["http://p.pdf"]
    assert n["i"] == 2
    assert registro == [], "una URL recuperada no debe contarse como perdida"


def test_un_404_no_gasta_reintentos(monkeypatch):
    """Insistir en lo que no existe solo retrasa al resto de la tanda."""
    n = {"i": 0}

    async def muerta(session, url, timeout, reg=None):
        n["i"] += 1
        gs._anotar(reg, url, "http_404")
        return "", [], []

    _con_descarga(monkeypatch, muerta)
    registro = []
    asyncio.run(gs._fetch_page_content(None, "http://y", registro))
    assert n["i"] == 1
    assert registro == [("http://y", "http_404")]


def test_el_timeout_persistente_agota_intentos_y_queda_anotado(monkeypatch):
    n = {"i": 0}

    async def siempre(session, url, timeout, reg=None):
        n["i"] += 1
        gs._anotar(reg, url, "error_TimeoutError")
        return "", [], []

    _con_descarga(monkeypatch, siempre)
    registro = []
    asyncio.run(gs._fetch_page_content(None, "http://z.pdf", registro))
    assert n["i"] == gs.DESCARGA_MAX_INTENTOS
    assert registro == [("http://z.pdf", f"error_TimeoutError_tras_{gs.DESCARGA_MAX_INTENTOS}")]


def test_una_pagina_sin_texto_conserva_sus_pdfs(monkeypatch):
    """
    El programa suele estar UN salto más allá: si la página no tiene texto pero
    enlaza el PDF, tirar el enlace es perder justo lo que se buscaba.
    """
    async def vacia(session, url, timeout, reg=None):
        gs._anotar(reg, url, "html_sin_texto")
        return "", ["http://programa.pdf"], []

    _con_descarga(monkeypatch, vacia)
    registro = []
    texto, pdfs, _ = asyncio.run(gs._fetch_page_content(None, "http://w", registro))
    assert pdfs == ["http://programa.pdf"]
    assert registro == [("http://w", "html_sin_texto")]


def test_los_pdfs_salen_con_mas_timeout_que_las_paginas(monkeypatch):
    vistos = []

    async def anota(session, url, timeout, reg=None):
        vistos.append(timeout)
        return "ok", [], []

    _con_descarga(monkeypatch, anota)
    asyncio.run(gs._fetch_page_content(None, "http://x/programa.pdf"))
    asyncio.run(gs._fetch_page_content(None, "http://x/noticia.html"))
    assert vistos[0] == gs.DESCARGA_TIMEOUT_PDF
    assert vistos[1] == gs.DDG_REQUEST_TIMEOUT
    assert vistos[0] > vistos[1]


def test_se_anota_el_motivo_real_de_cada_descarte():
    """Recorre las salidas en vacío de verdad, no solo el contador."""
    class _Resp:
        def __init__(self, status=200, ct="text/html", body=b"<html><body>hola</body></html>"):
            self.status, self._ct, self._body = status, ct, body
            self.headers = {"Content-Type": ct}
            self.url = "https://x.es"
        async def read(self): return self._body
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Sesion:
        def __init__(self, resp): self._resp = resp
        def get(self, *a, **k): return self._resp

    # Una URL distinta por caso: comparten caché, y un fallo estable guardado
    # en el primero contestaría por el segundo.
    casos = [
        ("https://x.es/prohibida", _Resp(status=403), "http_403"),
        ("https://x.es/comprimido", _Resp(ct="application/zip"), "tipo_application/zip"),
        ("https://x.es/enorme", _Resp(body=b"x" * 2_000_001), "mayor_2mb"),
    ]
    for url, resp, esperado in casos:
        registro: list[tuple[str, str]] = []
        texto, _, _ = asyncio.run(gs._fetch_page_content(_Sesion(resp), url, registro))
        assert texto == ""
        assert [m for _, m in registro] == [esperado], f"esperaba {esperado}, salio {registro}"


# ──────────────────────────────────────────────────────────────
# B1/B2 — el patrón sale de su propia Wikipedia, nunca de la del municipio
# ──────────────────────────────────────────────────────────────

W = "https://es.wikipedia.org/wiki/"


@pytest.mark.parametrize("nombre, slug, es_suyo", [
    # Fase 1 le da a estas localidades el artículo de OTRO municipio, y de ahí
    # salían los homónimos que hubo que tapar con guardas aguas abajo.
    ("Sierra", "Elche_de_la_Sierra", False),
    ("La Calabaza", "Quemada", False),
    ("Monte Costaján", "Virgen_de_las_Viñas_(Aranda_de_Duero)", False),
    # Artículos correctos, con y sin desambiguador.
    ("Cordovilla", "Cordovilla_(Albacete)", True),
    ("La Aguilera", "La_Aguilera_(Burgos)", True),
    ("Mora de Santa Quiteria", "Mora_de_Santa_Quiteria", True),
    ("Sinovas", "Sinovas", True),
])
def test_solo_se_acepta_el_articulo_de_la_propia_localidad(nombre, slug, es_suyo):
    from llm_processor.patron_finder import _wiki_es_de_la_localidad
    assert _wiki_es_de_la_localidad(W + slug, nombre) is es_suyo


def _patron_con_red_simulada(localidad, municipio, paginas):
    """Ejecuta obtener_patron sirviendo `paginas` y devuelve (patron, urls leídas)."""
    import llm_processor.patron_finder as pf

    leidas = []

    async def fake_wiki(session, url):
        leidas.append(url)
        return {}, paginas.get(url, "")

    async def main():
        with patch.object(pf, "_descargar_wikipedia", fake_wiki), \
             patch.object(pf, "_buscar_en_web", AsyncMock(return_value="")), \
             patch.object(pf, "_extraer_con_llm", AsyncMock(return_value=None)), \
             patch.object(pf._cache, "get", AsyncMock(return_value=pf._CACHE_MISS)), \
             patch.object(pf._cache, "set", AsyncMock(return_value=None)):
            return await pf.obtener_patron(localidad, municipio)

    return asyncio.run(main()), leidas


def test_la_pedania_nunca_lee_el_articulo_del_municipio():
    """
    Heredar el patrón de la villa hacía que siete de las nueve localidades de
    Amurrio saliesen con "San Roque". Si su artículo no dice nada, se pasa a
    buscadores, no al del municipio.
    """
    pedania = {"id": "1", "nombre": "Larrinbe", "wikipedia_url": W + "Larrimbe"}
    municipio = {"nombre": "Amurrio", "wikipedia_url": W + "Amurrio"}
    paginas = {
        W + "Larrimbe": "Larrimbe es un concejo.",          # sin patrón
        W + "Amurrio": "El patrón de Amurrio es San Roque, 16 de agosto.",
    }
    patron, leidas = _patron_con_red_simulada(pedania, municipio, paginas)
    assert W + "Amurrio" not in leidas
    assert patron is None


def test_el_nucleo_que_da_nombre_al_municipio_si_usa_su_articulo():
    """Para la capital, el artículo del municipio ES el suyo."""
    capital = {"id": "2", "nombre": "Amurrio", "es_capital": True, "wikipedia_url": ""}
    municipio = {"nombre": "Amurrio", "wikipedia_url": W + "Amurrio"}
    paginas = {W + "Amurrio": "Sus fiestas patronales son en honor a San Roque, patrón de la villa."}
    patron, leidas = _patron_con_red_simulada(capital, municipio, paginas)
    assert W + "Amurrio" in leidas
    assert patron and patron["ambito"] == "localidad"


def test_un_articulo_prestado_no_se_lee_siquiera():
    """Sierra apunta al artículo de Elche de la Sierra, que es otro municipio."""
    sierra = {"id": "3", "nombre": "Sierra", "wikipedia_url": W + "Elche_de_la_Sierra"}
    municipio = {"nombre": "Tobarra", "wikipedia_url": W + "Tobarra"}
    paginas = {
        W + "Elche_de_la_Sierra": "El patrón de Elche de la Sierra es San Andrés.",
        W + "Tobarra": "El patrón de Tobarra es el Cristo de la Antigua.",
    }
    patron, leidas = _patron_con_red_simulada(sierra, municipio, paginas)
    assert leidas == []
    assert patron is None


# ──────────────────────────────────────────────────────────────
# E — webs que Fase 1 asigna y son de otro sitio
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, loc, mun, es_suya", [
    # Casos reales del dataset: de 564 localidades con web "propia", 495
    # apuntaban a otro sitio. No a webs inútiles, a webs de OTROS.
    ("https://www.elchedelasierra.es", "Sierra", "Tobarra", False),
    ("http://www.quemada.es/", "La Calabaza", "Aranda de Duero", False),
    ("https://www.donostia.eus", "Oleta", "Aramayona", False),        # San Sebastián
    ("https://www.eajpnv.eus", "Bikuña", "San Millán", False),        # un partido
    ("https://www.eitb.eus", "Fresneda", "Valdegovía", False),        # una televisión
    # Webs correctas, con y sin prefijo institucional.
    ("https://www.tobarra.es", "Cordovilla", "Tobarra", True),
    ("https://www.aytosinovas.es", "Sinovas", "Aranda de Duero", True),
    ("https://ayuntamientodehellin.es", "Cañada de Agra", "Hellín", True),
    ("https://www.aldeire.es", "Aldeire", "Aldeire", True),
    ("", "X", "Y", False),
])
def test_la_web_de_la_localidad_es_suya_o_de_su_municipio(url, loc, mun, es_suya):
    from fuentes import web_es_de_este_lugar
    assert web_es_de_este_lugar(url, loc, mun) is es_suya


def test_no_basta_con_que_el_dominio_contenga_el_nombre():
    """'elchedelasierra' contiene 'sierra' y no es la web de la pedanía Sierra."""
    from fuentes import web_es_de_este_lugar
    assert web_es_de_este_lugar("https://elchedelasierra.es", "Sierra", "Tobarra") is False

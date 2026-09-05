"""
SearXNG como motor primario, y el hundido de agregadores.

Por qué se cambió el buscador. Ejecución del 2026-09-05 (semilla 7, 8
municipios, 35 fiestas):

  - 21 fiestas de 35 acabaron con `programa_estado = no_encontrado`.
  - De esas 21, nueve señalaban un directorio SEO (festivalesdeespana.com,
    pueblus.com...) y solo tres un PDF o una imagen.
  - Sobre los 273 volcados de debug_contexto, 101 (36%) llegaron al localizador
    con UN dominio o menos en el contexto.

El caso testigo es El Barraco, «Fiestas Patronales del Santísimo Cristo»: 1037
caracteres de contexto, una única URL —pueblus.com— y `elbarraco.org` ausente
pese a existir, porque otra fiesta del mismo municipio sí sacó una URL de ese
dominio. El modelo no elegía mal: no tenía nada que elegir.

Estos tests fijan las dos piezas que atacan eso: que el cliente de SearXNG
traduzca bien y falle en silencio hacia los motores de reserva, y que un
agregador no pueda volver a tapar la web del ayuntamiento.
"""

import json

import pytest

import scraper.google_search as gs


@pytest.fixture(autouse=True)
def _sin_enfriamientos_previos():
    """Un motor enfriado por el test anterior falsearía al siguiente."""
    gs._ENGINE_COOLDOWN.clear()
    gs._INCOHERENTES_SEGUIDAS.clear()
    yield
    gs._ENGINE_COOLDOWN.clear()
    gs._INCOHERENTES_SEGUIDAS.clear()


def _respuesta(payload) -> tuple[int, bytes]:
    return 200, json.dumps(payload).encode("utf-8")


# ─────────────────────────────────────────────
# El cliente
# ─────────────────────────────────────────────

def test_traduce_el_json_al_contrato_de_los_demas_motores(monkeypatch):
    """Debe devolver titulo/snippet/url, igual que _sync_fetch_ddg y compañía.

    Si esto se desvía, el orquestador fusiona resultados con forma distinta y el
    fallo aparece mucho más tarde, al construir el contexto.
    """
    payload = {"results": [
        {"title": "Fiestas | Ayuntamiento de El Barraco",
         "url": "https://www.elbarraco.org/fiestas/",
         "content": "Programa de las fiestas patronales"},
        {"title": "El Barraco - Pueblus",
         "url": "https://pueblus.com/fiestas/el-barraco",
         "content": "Listado de fiestas"},
    ]}
    monkeypatch.setattr(gs, "_http_get", lambda url, timeout=None: _respuesta(payload))

    res = gs._sync_fetch_searxng("fiestas el barraco")

    assert len(res) == 2
    assert set(res[0]) == {"titulo", "snippet", "url"}
    assert res[0]["url"] == "https://www.elbarraco.org/fiestas/"
    assert res[0]["titulo"] == "Fiestas | Ayuntamiento de El Barraco"
    assert res[0]["snippet"] == "Programa de las fiestas patronales"


def test_respeta_el_tope_de_resultados(monkeypatch):
    payload = {"results": [
        {"title": f"r{i}", "url": f"https://ejemplo.test/{i}", "content": ""}
        for i in range(gs.SEARXNG_MAX_RESULTADOS + 15)
    ]}
    monkeypatch.setattr(gs, "_http_get", lambda url, timeout=None: _respuesta(payload))

    assert len(gs._sync_fetch_searxng("lo que sea")) == gs.SEARXNG_MAX_RESULTADOS


def test_descarta_resultados_sin_url(monkeypatch):
    """Una entrada sin URL no es un resultado: colarla rompe al priorizador."""
    payload = {"results": [
        {"title": "sin enlace", "url": "", "content": "x"},
        {"title": "sin campo", "content": "x"},
        {"title": "bueno", "url": "https://ejemplo.test/a", "content": "x"},
    ]}
    monkeypatch.setattr(gs, "_http_get", lambda url, timeout=None: _respuesta(payload))

    res = gs._sync_fetch_searxng("consulta")
    assert [r["url"] for r in res] == ["https://ejemplo.test/a"]


def test_pide_json_y_espanol_en_la_consulta(monkeypatch):
    """Sin format=json SearXNG sirve HTML, y sin language=es prioriza inglés."""
    visto = {}

    def _fake(url, timeout=None):
        visto["url"] = url
        visto["timeout"] = timeout
        return _respuesta({"results": []})

    monkeypatch.setattr(gs, "_http_get", _fake)
    gs._sync_fetch_searxng("fiestas de Torrelaguna")

    assert "format=json" in visto["url"]
    assert f"language={gs.SEARXNG_IDIOMA}" in visto["url"]
    assert "q=fiestas+de+Torrelaguna" in visto["url"]
    assert visto["timeout"] == gs.SEARXNG_TIMEOUT


# ─────────────────────────────────────────────
# Los tres modos de fallo
# ─────────────────────────────────────────────

def test_contenedor_caido_no_rompe_la_consulta(monkeypatch):
    """El fallo más probable: nadie ha arrancado Docker tras reiniciar el PC.

    Tiene que devolver vacío y enfriarse, para que el orquestador siga con
    DuckDuckGo en vez de propagar la excepción.
    """
    def _explota(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(gs, "_http_get", _explota)

    assert gs._sync_fetch_searxng("consulta") == []
    assert not gs._motor_disponible("SearXNG")


def test_html_con_200_se_detecta_como_configuracion_mala(monkeypatch):
    """El error clásico de SearXNG: `formats: [json]` ausente en settings.yml.

    Responde 200 con HTML, así que no se puede distinguir por código de estado.
    Si no se detecta aquí, el fallo se manifiesta como "no hay resultados" y se
    busca en el sitio equivocado.
    """
    monkeypatch.setattr(gs, "_http_get",
                        lambda url, timeout=None: (200, b"<!DOCTYPE html><html>..."))

    assert gs._sync_fetch_searxng("consulta") == []
    assert not gs._motor_disponible("SearXNG")


def test_error_http_enfria_el_motor(monkeypatch):
    monkeypatch.setattr(gs, "_http_get", lambda url, timeout=None: (403, b""))

    assert gs._sync_fetch_searxng("consulta") == []
    assert not gs._motor_disponible("SearXNG")


# ─────────────────────────────────────────────
# Orden de motores
# ─────────────────────────────────────────────

def test_searxng_es_el_primero_y_los_demas_siguen_de_reserva():
    """El orden importa: es lo que hace que aporte dominios antes que nadie.

    Y los de reserva no se borran hasta tener una ejecución comparada, así que
    este test también avisa si alguien los quita antes de tiempo.
    """
    fuente = gs._fetch_search_results.__code__.co_consts
    nombres = [c for c in fuente if isinstance(c, str)]
    assert "SearXNG" in nombres
    idx = nombres.index("SearXNG")
    assert nombres.index("DuckDuckGo") > idx
    for reserva in ("DDG-lite", "Brave", "Bing", "Yahoo"):
        assert reserva in nombres, f"{reserva} desapareció de los motores de reserva"


# ─────────────────────────────────────────────
# El hundido de agregadores
# ─────────────────────────────────────────────

LOCALIDAD = {"nombre": "El Barraco", "sitio_web": ""}
MUNICIPIO = {"nombre": "El Barraco", "sitio_web": "https://www.elbarraco.org"}


def test_el_ayuntamiento_gana_al_agregador():
    """El caso de El Barraco, invertido.

    Con el dominio oficial presente, ningún directorio puede quedar por delante:
    +100 del dominio oficial contra -60 del agregador.
    """
    urls = [
        "https://pueblus.com/fiestas/el-barraco",
        "https://www.elbarraco.org/fiestas/",
    ]
    assert gs._priorizar_urls(urls, LOCALIDAD, MUNICIPIO)[0] == "https://www.elbarraco.org/fiestas/"


def test_el_agregador_queda_por_debajo_de_una_web_cualquiera():
    """Aunque el agregador mencione 'fiestas' y la otra no diga nada."""
    urls = [
        "https://www.festivalesdeespana.com/festival/fiestas-patronales-de-el-barraco",
        "https://www.diariodeavila.es/noticia/12345/",
    ]
    orden = gs._priorizar_urls(urls, LOCALIDAD, MUNICIPIO)
    assert orden[0] == "https://www.diariodeavila.es/noticia/12345/"


def test_el_agregador_no_se_elimina():
    """Se hunde, no se borra: en municipios sin web propia es lo único que hay.

    Si alguien lo convierte en un filtro, este test lo detecta.
    """
    urls = ["https://pueblus.com/fiestas/el-barraco"]
    assert gs._priorizar_urls(urls, LOCALIDAD, MUNICIPIO) == urls


@pytest.mark.parametrize("dominio", gs.DOMINIOS_AGREGADORES)
def test_todos_los_agregadores_de_la_lista_se_hunden(dominio):
    """Los seis salen de las 9 fiestas que en la ejecución del 2026-09-05
    señalaron un directorio y devolvieron cero actos."""
    urls = [
        f"https://www.{dominio}/fiestas/el-barraco",
        "https://ejemplo-neutro.test/pagina",
    ]
    assert gs._priorizar_urls(urls, LOCALIDAD, MUNICIPIO)[0] == "https://ejemplo-neutro.test/pagina"


def test_el_pdf_oficial_sigue_ganando():
    """Regresión: la penalización no debe alterar el orden que ya funcionaba.

    El PDF del ayuntamiento es el caso que sí rinde hoy —Semana Santa de
    Garrucha sacó 8 actos de uno—, así que tiene que seguir arriba.
    """
    urls = [
        "https://pueblus.com/fiestas/el-barraco",
        "https://ejemplo-neutro.test/agenda",
        "https://www.elbarraco.org/wp-content/uploads/2026/07/programa.pdf",
    ]
    orden = gs._priorizar_urls(urls, LOCALIDAD, MUNICIPIO)
    assert orden[0].endswith("programa.pdf")
    assert orden[-1].startswith("https://pueblus.com")

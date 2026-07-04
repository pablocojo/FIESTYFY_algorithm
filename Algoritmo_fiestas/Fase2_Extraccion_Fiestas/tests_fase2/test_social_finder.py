"""Tests del descubrimiento de perfiles RRSS oficiales (Etapa B)."""

import asyncio
from collections import Counter

from scraper import social_finder
from scraper.social_finder import (
    normalizar_link_social,
    resolver_perfiles,
    registrar_perfiles_web,
    RedesCache,
)


# ──────────────────────────────────────────────
# Normalización / clasificación
# ──────────────────────────────────────────────

def test_instagram_perfil_valido():
    assert normalizar_link_social("https://www.instagram.com/aytoejemplo/") == (
        "instagram", "https://www.instagram.com/aytoejemplo",
    )
    # con parámetros de tracking
    assert normalizar_link_social("https://instagram.com/AytoEjemplo?igshid=abc123") == (
        "instagram", "https://www.instagram.com/aytoejemplo",
    )


def test_instagram_post_no_es_perfil():
    assert normalizar_link_social("https://www.instagram.com/p/Cxyz123/") is None
    assert normalizar_link_social("https://www.instagram.com/reel/Cxyz123/") is None
    assert normalizar_link_social("https://www.instagram.com/explore/tags/fiestas/") is None


def test_facebook_perfil_valido():
    assert normalizar_link_social("https://www.facebook.com/AytoEjemplo") == (
        "facebook", "https://www.facebook.com/aytoejemplo",
    )
    # profile.php conserva el id
    assert normalizar_link_social("https://facebook.com/profile.php?id=1234567") == (
        "facebook", "https://www.facebook.com/profile.php?id=1234567",
    )
    # formato pages/<nombre>/<id>
    assert normalizar_link_social("https://www.facebook.com/pages/Ayto-Ejemplo/123456") == (
        "facebook", "https://www.facebook.com/pages/ayto-ejemplo/123456",
    )
    # subdominio móvil y de idioma
    assert normalizar_link_social("https://m.facebook.com/aytoejemplo")[1].startswith("https://www.facebook.com/")
    assert normalizar_link_social("https://es-es.facebook.com/aytoejemplo") is not None


def test_facebook_no_perfiles():
    assert normalizar_link_social("https://www.facebook.com/sharer.php?u=https://ayto.es") is None
    assert normalizar_link_social("https://www.facebook.com/sharer/sharer.php?u=x") is None
    assert normalizar_link_social("https://www.facebook.com/groups/fiestasdelpueblo") is None
    assert normalizar_link_social("https://www.facebook.com/aytoejemplo/posts/123") is None
    assert normalizar_link_social("https://www.facebook.com/events/456") is None
    assert normalizar_link_social("https://www.facebook.com/watch/?v=1") is None
    assert normalizar_link_social("https://l.facebook.com/l.php?u=https://otro.com") is None
    assert normalizar_link_social("https://www.facebook.com/profile.php?id=noesnumero") is None


def test_twitter_x_perfil_valido():
    assert normalizar_link_social("https://twitter.com/AytoEjemplo") == (
        "twitter", "https://x.com/aytoejemplo",
    )
    assert normalizar_link_social("https://x.com/aytoejemplo?ref_src=twsrc") == (
        "twitter", "https://x.com/aytoejemplo",
    )


def test_twitter_no_perfiles():
    assert normalizar_link_social("https://twitter.com/intent/tweet?text=hola") is None
    assert normalizar_link_social("https://twitter.com/share?url=x") is None
    assert normalizar_link_social("https://x.com/hashtag/fiestas") is None
    assert normalizar_link_social("https://twitter.com/aytoejemplo/status/123") is None


def test_urls_no_sociales():
    assert normalizar_link_social("https://www.ayto-ejemplo.es/fiestas") is None
    assert normalizar_link_social("mailto:info@ayto.es") is None
    assert normalizar_link_social("") is None
    # subdominio técnico
    assert normalizar_link_social("https://developers.facebook.com/docs") is None


# ──────────────────────────────────────────────
# Resolución del mejor candidato
# ──────────────────────────────────────────────

def test_resolver_gana_el_mas_repetido():
    contador = Counter({
        ("facebook", "https://www.facebook.com/aytoejemplo"): 40,   # footer: en todas las páginas
        ("facebook", "https://www.facebook.com/turismoejemplo"): 2, # enlace puntual
        ("instagram", "https://www.instagram.com/aytoejemplo"): 40,
    })
    perfiles = resolver_perfiles(contador)
    assert perfiles["facebook"] == "https://www.facebook.com/aytoejemplo"
    assert perfiles["instagram"] == "https://www.instagram.com/aytoejemplo"
    assert perfiles["twitter"] is None


def test_resolver_empate_gana_url_corta():
    contador = Counter({
        ("twitter", "https://x.com/aytoejemplo"): 3,
        ("twitter", "https://x.com/aytoejemplodeportes"): 3,
    })
    assert resolver_perfiles(contador)["twitter"] == "https://x.com/aytoejemplo"


def test_resolver_vacio():
    perfiles = resolver_perfiles(Counter())
    assert perfiles == {"instagram": None, "facebook": None, "twitter": None}


# ──────────────────────────────────────────────
# Registro con caché
# ──────────────────────────────────────────────

def _con_cache_temporal(tmp_path, monkeypatch):
    cache = RedesCache(str(tmp_path / "redes_test.json"))
    monkeypatch.setattr(social_finder, "_cache", cache)
    return cache


def test_registrar_y_cache(tmp_path, monkeypatch):
    _con_cache_temporal(tmp_path, monkeypatch)
    lugar = {"id": "l1", "nombre": "Pueblo"}
    contador = Counter({("facebook", "https://www.facebook.com/aytopueblo"): 10})

    entrada = asyncio.run(registrar_perfiles_web(lugar, contador))
    assert entrada["facebook"] == "https://www.facebook.com/aytopueblo"
    assert entrada["instagram"] is None
    assert entrada["verificado_por"] == "web_oficial"
    assert entrada["pendiente_apps"] is True  # faltan instagram y twitter

    # Segunda llamada: cache hit, aunque el contador ahora esté vacío
    entrada2 = asyncio.run(registrar_perfiles_web(lugar, Counter()))
    assert entrada2 == entrada


def test_registrar_respeta_campo_previo(tmp_path, monkeypatch):
    _con_cache_temporal(tmp_path, monkeypatch)
    previo = {"instagram": "https://www.instagram.com/oficial", "facebook": None, "twitter": None}
    lugar = {"id": "l2", "nombre": "Pueblo", "redes_sociales": previo}
    entrada = asyncio.run(registrar_perfiles_web(lugar, Counter()))
    assert entrada == previo


def test_registrar_sin_perfiles_marca_pendiente(tmp_path, monkeypatch):
    _con_cache_temporal(tmp_path, monkeypatch)
    lugar = {"id": "l3", "nombre": "Aldea"}
    entrada = asyncio.run(registrar_perfiles_web(lugar, Counter()))
    assert entrada["pendiente_apps"] is True
    assert all(entrada[red] is None for red in ("instagram", "facebook", "twitter"))


def test_registrar_completo_no_pendiente(tmp_path, monkeypatch):
    _con_cache_temporal(tmp_path, monkeypatch)
    lugar = {"id": "l4", "nombre": "Villa"}
    contador = Counter({
        ("facebook", "https://www.facebook.com/villa"): 5,
        ("instagram", "https://www.instagram.com/villa"): 5,
        ("twitter", "https://x.com/villa"): 5,
    })
    entrada = asyncio.run(registrar_perfiles_web(lugar, contador))
    assert entrada["pendiente_apps"] is False

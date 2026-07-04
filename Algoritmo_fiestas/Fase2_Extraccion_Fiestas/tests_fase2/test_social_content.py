"""Tests del lector de caché de contenido RRSS (hook de la Etapa C)."""

import json

from scraper import social_content
from fuentes import fuente_base


LOCALIDAD = {"id": "loc-1", "nombre": "Pueblo Test"}
MUNICIPIO = {"id": "mun-1", "nombre": "Municipio Test"}


def _con_cache(monkeypatch, datos):
    monkeypatch.setattr(social_content, "_cache", datos)


def test_sin_cache_devuelve_vacio(monkeypatch):
    _con_cache(monkeypatch, {})
    assert social_content.cargar_documentos_rrss(LOCALIDAD, MUNICIPIO) == []


def test_posts_de_localidad_y_municipio(monkeypatch):
    _con_cache(monkeypatch, {
        "loc-1": {"instagram": [
            {"texto": "¡Fiestas este finde!", "fecha": "2026-08-01",
             "es_programa": True, "texto_programa": "23:00 Verbena"},
        ]},
        "mun-1": {"facebook": [
            {"texto": "Programa municipal", "fecha": "2026-07-15"},
        ]},
    })
    docs = social_content.cargar_documentos_rrss(LOCALIDAD, MUNICIPIO)
    assert len(docs) == 2
    fuentes = {d["fuente"] for d in docs}
    assert "rrss_localidad:instagram" in fuentes
    assert "rrss_municipio:facebook" in fuentes
    doc_ig = next(d for d in docs if d["fuente"].startswith("rrss_localidad"))
    assert "23:00 Verbena" in doc_ig["texto"]
    assert "[POST 2026-08-01]" in doc_ig["texto"]


def test_capital_no_duplica_municipio(monkeypatch):
    _con_cache(monkeypatch, {"loc-1": {"instagram": [{"texto": "hola"}]}})
    docs = social_content.cargar_documentos_rrss(LOCALIDAD, {"id": "loc-1", "nombre": "Pueblo Test"})
    assert len(docs) == 1
    assert fuente_base(docs[0]["fuente"]) == "rrss_localidad"


def test_posts_vacios_se_ignoran(monkeypatch):
    _con_cache(monkeypatch, {"loc-1": {"twitter": [{"texto": "  "}, "basura", {"otro": 1}]}})
    assert social_content.cargar_documentos_rrss(LOCALIDAD, MUNICIPIO) == []

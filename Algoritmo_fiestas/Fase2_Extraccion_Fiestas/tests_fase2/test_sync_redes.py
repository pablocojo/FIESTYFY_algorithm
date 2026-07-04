"""Tests del volcado de perfiles RRSS a lugares_espana.json (idempotente, JSON no final)."""

import glob
import json
import os

from sync_redes_a_lugares import sincronizar


ENTRADA = {
    "instagram": "https://www.instagram.com/aytopueblo",
    "facebook": None,
    "twitter": None,
    "verificado_por": "web_oficial",
    "fecha_verificacion": "2026-07-04",
    "pendiente_apps": True,
}


def _preparar(tmp_path, cache: dict, lugares):
    cache_path = tmp_path / "cache.json"
    lugares_path = tmp_path / "lugares.json"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    lugares_path.write_text(json.dumps(lugares, ensure_ascii=False), encoding="utf-8")
    return str(cache_path), str(lugares_path)


def test_sync_actualiza_y_hace_backup(tmp_path):
    lugares = {"version": 3, "lugares": [{"id": "l1", "nombre": "Pueblo"}]}
    cache_path, lugares_path = _preparar(tmp_path, {"l1": ENTRADA}, lugares)

    resumen = sincronizar(cache_path, lugares_path)
    assert resumen["actualizados"] == 1
    assert resumen["sin_lugar"] == []
    assert resumen["backup"] and os.path.exists(resumen["backup"])

    with open(lugares_path, encoding="utf-8") as f:
        data = json.load(f)
    # Conserva el formato wrapper y los campos existentes
    assert data["version"] == 3
    assert data["lugares"][0]["nombre"] == "Pueblo"
    assert data["lugares"][0]["redes_sociales"] == ENTRADA


def test_sync_ids_pendientes_no_fallan(tmp_path):
    # La caché tiene lugares que AÚN no existen en el JSON (Fase 1 incompleta)
    lugares = [{"id": "l1", "nombre": "Pueblo"}]
    cache = {"l1": ENTRADA, "l-futuro": ENTRADA}
    cache_path, lugares_path = _preparar(tmp_path, cache, lugares)

    resumen = sincronizar(cache_path, lugares_path)
    assert resumen["actualizados"] == 1
    assert resumen["sin_lugar"] == ["l-futuro"]
    # La caché NO se toca: el id pendiente sigue disponible para el futuro
    with open(cache_path, encoding="utf-8") as f:
        assert "l-futuro" in json.load(f)


def test_sync_idempotente(tmp_path):
    lugares = [{"id": "l1", "nombre": "Pueblo"}]
    cache_path, lugares_path = _preparar(tmp_path, {"l1": ENTRADA}, lugares)

    r1 = sincronizar(cache_path, lugares_path)
    r2 = sincronizar(cache_path, lugares_path)
    assert r1["actualizados"] == 1
    assert r2["actualizados"] == 0
    assert r2["sin_cambio"] == 1
    assert r2["backup"] is None  # sin cambios → sin backup ni escritura


def test_sync_dry_run_no_escribe(tmp_path):
    lugares = [{"id": "l1", "nombre": "Pueblo"}]
    cache_path, lugares_path = _preparar(tmp_path, {"l1": ENTRADA}, lugares)
    antes = open(lugares_path, encoding="utf-8").read()

    resumen = sincronizar(cache_path, lugares_path, dry_run=True)
    assert resumen["actualizados"] == 1
    assert open(lugares_path, encoding="utf-8").read() == antes
    assert glob.glob(lugares_path + ".bak-*") == []

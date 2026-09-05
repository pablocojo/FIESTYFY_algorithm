"""
La cadena de proveedores ante un 429 y ante un prompt que no cabe.

La trampa: cualquier respuesta distinta de 200 hacía saltar al siguiente
proveedor de la cadena, y el siguiente es LM Studio con su n_ctx de 8192. Un
lote de 30.000 tokens no le cabe, así que devolvía «no cabe en su ventana», se
lanzaba ContextOverflowError, y en `_descubrir_por_meses` esa tanda se
convertía en una lista vacía sin que nada la registrara como pérdida: un
problema de CUPO acababa disfrazado de problema de CONTEXTO, y perdiendo
material.

Con lotes de ~114.000 tokens en vez de 20.000 caracteres, esto pasa de ser un
riesgo teórico a uno probable.
"""

import asyncio

import pytest

import llm_processor.text_analyzer as ta


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    """Los backoffs de verdad harían el test de 20 segundos."""
    async def dormir(_s):
        return None
    monkeypatch.setattr(ta.asyncio, "sleep", dormir)


def _cadena(monkeypatch, proveedores):
    monkeypatch.setattr(ta, "_cadena_proveedores", lambda: proveedores)


REMOTO = {"nombre": "remoto/grande", "remoto": True, "url": "u", "modelo": "m",
          "n_ctx": 131072, "timeout": 10, "headers": {}}
LOCAL = {"nombre": "LM Studio/pequeño", "remoto": False, "url": "u", "modelo": "m",
         "n_ctx": 8192, "timeout": 10, "headers": {}}

RESPUESTA = {"fiestas": [{"nombre": "San Roque"}]}


def _llamar(prompt_largo=False):
    user = ("palabra " * 20000) if prompt_largo else "dame el JSON"
    return asyncio.run(ta.llm_chat_json("system corto", user, etiqueta="TEST"))


# ── 429 ──────────────────────────────────────────────────────────────────────

def test_el_429_se_reintenta_en_el_mismo_proveedor(monkeypatch):
    """No se cambia de modelo por un problema de cupo: se espera."""
    visitados = []
    intentos = {"n": 0}

    async def pedir(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        visitados.append(prov["nombre"])
        intentos["n"] += 1
        if intentos["n"] == 1:
            return "cupo", ""
        return "ok", '{"fiestas": []}'

    _cadena(monkeypatch, [REMOTO, LOCAL])
    monkeypatch.setattr(ta, "_pedir_a_proveedor", pedir)

    assert _llamar() == {"fiestas": []}
    assert visitados == ["remoto/grande", "remoto/grande"], (
        f"saltó de proveedor ante un 429: {visitados}"
    )


def test_tras_agotar_los_reintentos_de_cupo_pasa_al_siguiente(monkeypatch):
    visitados = []

    async def pedir(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        visitados.append(prov["nombre"])
        if prov["remoto"]:
            return "cupo", ""
        return "ok", '{"fiestas": []}'

    _cadena(monkeypatch, [REMOTO, LOCAL])
    monkeypatch.setattr(ta, "_pedir_a_proveedor", pedir)

    assert _llamar() == {"fiestas": []}
    assert visitados.count("remoto/grande") == ta.LLM_REINTENTOS_429 + 1
    assert visitados[-1] == "LM Studio/pequeño"


# ── Ventana del proveedor ────────────────────────────────────────────────────

def test_no_se_le_ofrece_al_local_un_prompt_que_no_le_cabe(monkeypatch):
    """
    Es la mitad que faltaba: aunque el remoto falle, ofrecerle a un modelo de
    8.192 tokens un prompt de 30.000 no es un respaldo, es una pérdida con otro
    nombre.
    """
    visitados = []

    async def pedir(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        visitados.append(prov["nombre"])
        return "siguiente", ""

    _cadena(monkeypatch, [REMOTO, LOCAL])
    monkeypatch.setattr(ta, "_pedir_a_proveedor", pedir)

    with pytest.raises(ta.ContextOverflowError):
        _llamar(prompt_largo=True)

    assert "LM Studio/pequeño" not in visitados, (
        "se le ofreció al local un prompt que no cabe en su ventana"
    )
    assert visitados == ["remoto/grande"]


def test_un_prompt_corto_si_llega_al_local(monkeypatch):
    """La red de seguridad tiene que seguir existiendo cuando de verdad sirve."""
    visitados = []

    async def pedir(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        visitados.append(prov["nombre"])
        if prov["remoto"]:
            return "siguiente", ""
        return "ok", '{"fiestas": []}'

    _cadena(monkeypatch, [REMOTO, LOCAL])
    monkeypatch.setattr(ta, "_pedir_a_proveedor", pedir)

    assert _llamar() == {"fiestas": []}
    assert visitados == ["remoto/grande", "LM Studio/pequeño"]


def test_si_nadie_puede_con_el_prompt_se_avisa_por_contexto(monkeypatch):
    """
    `ContextOverflowError` es lo que hace que el llamante recorte y reintente.
    Saltarse un proveedor por ventana pequeña tiene que contar como
    desbordamiento, no como silencio.
    """
    async def pedir(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        return "contexto", ""

    _cadena(monkeypatch, [REMOTO, LOCAL])
    monkeypatch.setattr(ta, "_pedir_a_proveedor", pedir)

    with pytest.raises(ta.ContextOverflowError):
        _llamar()

"""
Verificación de la Fase 0 (instrumentación del presupuesto de contexto).

Comprueba que:
  C0.1  El presupuesto nunca supera el n_ctx del modelo.
  C0.2  El presupuesto descuenta system prompt + reserva de salida + margen.
  C0.3  El conteo de tokens es coherente y monótono.
  C0.4  La autocalibración del ratio chars/token converge y respeta sus cotas.
  C0.5  `truncar_a_tokens` nunca devuelve algo que supere el límite.
  C0.6  El volcado de depuración detecta el fallo real observado en Amurrio:
        contexto de un solo documento y 65% de chunks duplicados.
  C0.7  Nada de esto lanza excepción aunque LM Studio no esté disponible.

No requiere LM Studio ni red: `get_n_ctx()` cae al fallback y eso también se prueba.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import context_budget as cb
from debug_contexto import volcar_contexto


SYSTEM_TIPICO = "Eres un API estricta especializada en catalogar fiestas locales. " * 60


def test_c0_1_presupuesto_no_supera_n_ctx():
    for n_ctx in (4096, 8192, 16384, 32768, 131072):
        p = cb.presupuesto_contexto(SYSTEM_TIPICO, cb.RESERVA_SALIDA_DISCOVERY, n_ctx=n_ctx)
        assert p <= n_ctx, f"presupuesto {p} > n_ctx {n_ctx}"
        assert p >= 512, f"presupuesto {p} por debajo del mínimo de seguridad"


def test_c0_2_presupuesto_descuenta_todo():
    n_ctx = 32768
    reserva = cb.RESERVA_SALIDA_ENRICHMENT
    p = cb.presupuesto_contexto(SYSTEM_TIPICO, reserva, n_ctx=n_ctx)
    tok_sys = cb.contar_tokens(SYSTEM_TIPICO) + cb.OVERHEAD_PLANTILLA_TOKENS
    esperado = n_ctx - tok_sys - reserva - cb.MARGEN_SEGURIDAD_TOKENS
    assert p == esperado, f"esperado {esperado}, obtenido {p}"
    # El contexto + el system + la reserva tienen que caber, con margen.
    assert p + tok_sys + reserva < n_ctx


def test_c0_2b_presupuesto_insuficiente_no_es_negativo():
    """Con un n_ctx ridículo el presupuesto se fuerza a 512, no a un negativo."""
    p = cb.presupuesto_contexto(SYSTEM_TIPICO, cb.RESERVA_SALIDA_ENRICHMENT, n_ctx=2048)
    assert p == 512, f"esperado el mínimo 512, obtenido {p}"


def test_c0_3_conteo_tokens_coherente():
    assert cb.contar_tokens("") == 0
    corto = "Fiestas de San Roque en Amurrio."
    largo = corto * 100
    assert 0 < cb.contar_tokens(corto) < cb.contar_tokens(largo)
    # Ningún texto español razonable debe salir a más de 1 token por carácter
    # ni a menos de 1 token cada 6 caracteres.
    n = cb.contar_tokens(largo)
    assert len(largo) / 6 < n < len(largo), f"conteo implausible: {n} tokens para {len(largo)} chars"


def test_c0_4_autocalibracion_converge_y_acota():
    ratio_inicial = cb._cargar_ratio()
    respaldo = cb.CALIBRACION_FILE.read_text(encoding="utf-8") if cb.CALIBRACION_FILE.exists() else None

    # Observación plausible: 35.000 chars consumieron 10.000 tokens -> 3.5 chars/tok
    cb.registrar_uso_real(35_000, 10_000)
    r1 = cb._cargar_ratio()
    assert cb.RATIO_MIN <= r1 <= cb.RATIO_MAX

    # Observaciones absurdas (1 char/token, 50 chars/token) deben ignorarse.
    cb.registrar_uso_real(1_000, 1_000)
    cb.registrar_uso_real(500_000, 10_000)
    r2 = cb._cargar_ratio()
    assert r2 == r1, "una observación fuera de rango ha contaminado el ratio"

    # Repetir la misma observación debe converger hacia ella.
    for _ in range(30):
        cb.registrar_uso_real(35_000, 10_000)
    objetivo = 35_000 / (10_000 - cb.OVERHEAD_PLANTILLA_TOKENS)
    assert abs(cb._cargar_ratio() - objetivo) < 0.05, (
        f"no converge: {cb._cargar_ratio():.3f} vs objetivo {objetivo:.3f}"
    )

    # Entradas degeneradas no deben lanzar.
    cb.registrar_uso_real(0, 0)
    cb.registrar_uso_real(-5, 100)
    cb.registrar_uso_real(100, 3)

    # Restaurar el estado previo: el test no debe dejar la calibración tocada.
    cb._ratio_cache = ratio_inicial
    if respaldo is not None:
        cb.CALIBRACION_FILE.write_text(respaldo, encoding="utf-8")
    elif cb.CALIBRACION_FILE.exists():
        cb.CALIBRACION_FILE.unlink()


def test_c0_5_truncar_respeta_el_limite():
    texto = "\n".join(f"{h:02d}:00 Acto número {h} de las fiestas patronales." for h in range(500))
    for limite in (64, 256, 1024):
        recorte = cb.truncar_a_tokens(texto, limite)
        assert cb.contar_tokens(recorte) <= limite, (
            f"truncado a {cb.contar_tokens(recorte)} tok, límite {limite}"
        )
    # Si ya cabe, se devuelve intacto.
    assert cb.truncar_a_tokens("18:00 Verbena", 10_000) == "18:00 Verbena"


def test_c0_6_debug_detecta_el_fallo_de_amurrio():
    """Reproduce el patrón real: un solo documento, cada chunk repetido 3 veces."""
    url_ppto = "https://udala.amurrio.eus/images/docs/pdf/ANEXO_3_Ppto_2025.pdf"
    unicos = [f"TOTAL CONCEPTO 3.2.{i}. 581.580,00 0,00 1.358.729,64" for i in range(6)]
    seleccion = [
        {"chunk": t, "url": url_ppto, "fuente": "web_municipio", "prioridad": 2, "score": 0.5}
        for t in unicos for _ in range(3)
    ]
    m = volcar_contexto(
        etapa="test", localidad_nombre="Amurrio_TEST", municipio_nombre="Amurrio",
        contexto="\n".join(i["chunk"] for i in seleccion),
        candidatos=seleccion, seleccion=seleccion, contar_tokens=cb.contar_tokens,
    )
    assert m["documentos_distintos"] == 1, "no ha detectado el contexto monodocumento"
    assert m["chunks_duplicados"] == 12, f"duplicados mal contados: {m['chunks_duplicados']}"
    assert m["pct_unico"] < 40, f"pct_unico deberia rondar 33%, es {m['pct_unico']}"

    # Y el caso sano debe salir limpio.
    sano = [
        {"chunk": f"18:00 Pasacalles el dia {i}", "url": f"https://x.eus/p{i}",
         "fuente": "web_municipio", "prioridad": 2, "score": 0.6}
        for i in range(5)
    ]
    m2 = volcar_contexto(
        etapa="test", localidad_nombre="Sano_TEST", municipio_nombre="Amurrio",
        contexto="\n".join(i["chunk"] for i in sano),
        candidatos=sano, seleccion=sano, contar_tokens=cb.contar_tokens,
    )
    assert m2["documentos_distintos"] == 5
    assert m2["chunks_duplicados"] == 0
    assert m2["pct_unico"] == 100.0


def test_c0_7_todo_es_tolerante_a_fallos():
    """Sin LM Studio, el módulo debe seguir dando un presupuesto utilizable."""
    info = cb.get_model_info(refrescar=True)
    assert isinstance(info["n_ctx"], int) and info["n_ctx"] > 0
    assert isinstance(info["detectado"], bool)
    assert cb.get_n_ctx() > 0
    r = cb.resumen_presupuesto(SYSTEM_TIPICO, cb.RESERVA_SALIDA_DISCOVERY)
    for clave in ("n_ctx", "tokens_system", "presupuesto_contexto_tokens", "ratio_chars_token"):
        assert clave in r, f"falta '{clave}' en el resumen"

    # El volcado tampoco debe lanzar con entradas corruptas.
    volcar_contexto("test", "Roto/\\:*?", "M", "", [], [], cb.contar_tokens)
    volcar_contexto("test", None, None, None, None, None, cb.contar_tokens)


def _limpiar_artefactos():
    """Los volcados que generan los tests no deben quedarse en debug_contexto/."""
    from debug_contexto import DIR_DEBUG
    if DIR_DEBUG.exists():
        for f in DIR_DEBUG.glob("*_test_*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            DIR_DEBUG.rmdir()  # solo si ha quedado vacía
        except OSError:
            pass


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(list(globals().items())):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK   {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  FALLO {nombre}: {e}")
    _limpiar_artefactos()
    if fallos:
        print(f"\nVERIFY C0 FALLIDO: {fallos} comprobaciones.")
        sys.exit(1)
    print("\nVERIFY C0 PASSED: presupuesto de contexto instrumentado y tolerante a fallos.")
    print(f"\nEstado actual -> {cb.resumen_presupuesto(SYSTEM_TIPICO, cb.RESERVA_SALIDA_DISCOVERY)}")

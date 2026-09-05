"""
El descubrimiento pregunta mes a mes, no de una vez sobre una muestra.

Medido el 2026-08-26: el paso que decide QUÉ FIESTAS EXISTEN veía 20.000
caracteres, que en Tobarra son 23 chunks de 189 (12%) y en Aranda 23 de 415
(6%). Con un corte tan estrecho, cualquier reordenación pequeña cambiaba lo que
entraba: entre dos ejecuciones con el mismo material, Tobarra pasó de 4 fiestas
a 2 y perdió la del Cristo, que tiene 50 actos y es la principal del municipio.
"""

from llm_processor.text_analyzer import (
    agrupar_meses_para_preguntar,
    barrer_meses_con_senal,
    repartir_en_llamadas,
)


def chunk(texto, score=0.5):
    return {"chunk": texto, "url": "https://x.es", "indice_chunk": 0, "score": score}


PROGRAMA_AGOSTO = ("Fiestas de San Roque en Tobarra, del 14 al 21 de agosto. "
                   "Procesion, verbena y comida popular.")
PROGRAMA_MAYO = ("Tobarra celebra al Cristo de la Antigua del 9 al 24 de mayo "
                 "con procesion y pujas.")


def test_agrupa_los_chunks_por_el_mes_que_citan():
    por_mes = barrer_meses_con_senal([chunk(PROGRAMA_AGOSTO), chunk(PROGRAMA_MAYO)], "Tobarra")
    assert set(por_mes) == {5, 8}
    assert len(por_mes[8]) == 1 and len(por_mes[5]) == 1


def test_un_chunk_que_no_nombra_la_localidad_no_cuenta():
    """
    No es un detalle. Pidiéndolo solo al documento, el mes correcto salía primero
    en 2 de 4 localidades: a Cordovilla, cuya fiesta es en noviembre, le salía
    julio, que es cuando celebran las otras pedanías del mismo municipio.
    Exigiéndolo al chunk, sale primero en 5 de 6.
    """
    ajeno = "Fiestas de Aljube del 13 al 17 de mayo con procesion y verbena."
    assert barrer_meses_con_senal([chunk(ajeno)], "Tobarra") == {}


def test_un_chunk_sin_termino_festivo_no_cuenta():
    burocracia = "Tobarra publica el 14 de agosto la lista provisional de admitidos."
    assert barrer_meses_con_senal([chunk(burocracia)], "Tobarra") == {}


def test_un_chunk_sin_mes_no_cuenta():
    sin_mes = "Tobarra celebra sus fiestas patronales con procesion y verbena."
    assert barrer_meses_con_senal([chunk(sin_mes)], "Tobarra") == {}


def test_los_meses_flojos_van_juntos_en_una_tanda():
    """
    En Sinovas, tres de sus cuatro llamadas se iban en meses de un solo chunk.
    Se siguen mirando —el corte es «todos los meses con señal»— pero comparten
    llamada.
    """
    por_mes = {8: [chunk("a"), chunk("b"), chunk("c")], 2: [chunk("d")], 6: [chunk("e")]}
    grupos = agrupar_meses_para_preguntar(por_mes, minimo_propio=3)
    assert grupos[0][0] == (8,), "el mes con material va solo"
    assert grupos[-1][0] == (2, 6), "los flojos comparten tanda"
    assert len(grupos[-1][1]) == 2


def test_el_mes_con_mas_material_va_primero():
    """Al recortar por el tope se pierde la cola, así que el orden importa."""
    por_mes = {1: [chunk("a")] * 3, 8: [chunk("b")] * 9, 5: [chunk("c")] * 5}
    assert [ms for ms, _ in agrupar_meses_para_preguntar(por_mes)] == [(8,), (5,), (1,)]


def test_solo_se_trocea_lo_que_no_cabe():
    cortos = [chunk("x" * 100) for _ in range(5)]
    assert len(repartir_en_llamadas(cortos, 20000)) == 1
    largos = [chunk("x" * 8000) for _ in range(5)]
    assert len(repartir_en_llamadas(largos, 20000)) == 3


def test_ningun_chunk_se_pierde_al_trocear():
    trozos = [chunk("x" * 7000, score=i / 10) for i in range(7)]
    tandas = repartir_en_llamadas(trozos, 20000)
    assert sum(len(t) for t in tandas) == 7


def test_un_chunk_mas_grande_que_el_presupuesto_no_bloquea():
    """Si no cabe ni solo, va en su propia tanda en vez de perderse."""
    tandas = repartir_en_llamadas([chunk("x" * 50000)], 20000)
    assert len(tandas) == 1 and len(tandas[0]) == 1


def test_sin_senal_no_hay_meses():
    """Devolver vacío es lo que hace que el llamante caiga a la llamada única."""
    assert barrer_meses_con_senal([], "Tobarra") == {}
    assert barrer_meses_con_senal([chunk("texto cualquiera")], "") == {}


# ── Ningún mes con señal se queda sin preguntar ──────────────────────────────

def test_todos_los_meses_con_senal_se_preguntan():
    """
    Aranda de Duero tocaba el tope en la ejecución del 2026-09-03: «12 meses con
    señal, 10 llamadas». Dos meses con material se quedaban sin preguntar y nada
    lo señalaba como pérdida —el log lo decía a INFO, entre otras mil líneas—.

    Se recorre la ruta de verdad, con el modelo fingido, y se comprueba que se
    pregunta por los doce.
    """
    import asyncio
    import llm_processor.text_analyzer as ta

    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    chunks = []
    for n, mes in enumerate(MESES):
        for k in range(3):        # ≥ DISCOVERY_MIN_CHUNKS_MES_PROPIO
            chunks.append({
                "chunk": f"Fiestas de Tobarra en {mes}, con procesion y verbena. "
                         f"Detalle {k}.",
                "url": f"https://x.es/{mes}", "indice_chunk": k,
                "score": 0.5, "fuente": "web_municipio", "es_calendario": False,
                "prioridad": 2,
            })

    preguntados = []

    async def falso_llm(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        preguntados.append(etiqueta)
        return {"fiestas": []}

    original = ta.llm_chat_json
    ta.llm_chat_json = falso_llm
    try:
        asyncio.run(ta._descubrir_por_meses(
            chunks, {"nombre": "Tobarra"}, {"nombre": "Tobarra"}, 2026,
            "system prompt de prueba",
        ))
    finally:
        ta.llm_chat_json = original

    assert len(preguntados) >= len(MESES), (
        f"solo {len(preguntados)} llamadas para {len(MESES)} meses con señal: "
        f"{preguntados}"
    )
    for mes in MESES:
        assert any(mes[:8] in e for e in preguntados), f"nadie preguntó por {mes}"

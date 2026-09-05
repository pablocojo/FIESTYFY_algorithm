"""
El repartidor: nada se descarta, las páginas no se despedazan y los lotes caben.

Se prueba contra el `ensamblar_contexto` REAL, no contra un doble: la razón de
ser del módulo es que el presupuesto anterior ignoraba los rótulos que ese
ensamblado añade, así que probarlo con un ensamblador de mentira no probaría
nada.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llm_processor.text_analyzer import ensamblar_contexto
from reparto_contexto import (
    agrupar_por_pagina,
    deduplicar_por_texto,
    repartir_en_lotes,
)


def contar(texto: str) -> int:
    """Contador determinista: 1 token cada 4 caracteres. No depende de la red."""
    return len(texto or "") // 4 + 1


def chunk(url, indice, texto, fuente="busqueda_web", score=0.5):
    return {
        "chunk": texto,
        "url": url,
        "indice_chunk": indice,
        "fuente": fuente,
        "es_calendario": False,
        "prioridad": 6,
        "score": score,
        "relevancia_geo": "DIRECTA",
    }


def pagina(url, n, largo=400, score=0.5, fuente="busqueda_web"):
    return [
        chunk(url, i, f"{url} fragmento {i} " + "x" * largo, fuente, score)
        for i in range(n)
    ]


def repartir(items, tope, fijos=None):
    return repartir_en_lotes(items, tope, ensamblar_contexto, contar, fijos=fijos)


# ── Lo que no puede pasar nunca ──────────────────────────────────────────────

def test_no_se_descarta_ningun_fragmento():
    items = pagina("http://a", 8) + pagina("http://b", 8) + pagina("http://c", 8)
    lotes = repartir(items, 400)
    repartidos = [i for l in lotes for i in l]
    assert len(repartidos) == len(items)
    assert {id(i) for i in repartidos} == {id(i) for i in items}


def test_cada_lote_cabe_en_el_tope_medido_de_verdad():
    items = pagina("http://a", 6) + pagina("http://b", 6) + pagina("http://c", 6)
    tope = 500
    for lote in repartir(items, tope):
        assert contar(ensamblar_contexto(lote)) <= tope


def test_lista_vacia():
    assert repartir([], 1000) == []


# ── Páginas: juntas y en orden ───────────────────────────────────────────────

def test_los_fragmentos_de_una_pagina_no_se_separan_si_caben():
    items = pagina("http://programa", 4, largo=100) + pagina("http://otra", 4, largo=100)
    lotes = repartir(items, 100000)
    assert len(lotes) == 1
    urls = [i["url"] for i in lotes[0]]
    # Cada página aparece en UN solo tramo contiguo: tantos tramos como páginas.
    tramos = sum(1 for n, u in enumerate(urls) if n == 0 or u != urls[n - 1])
    assert tramos == 2, f"las páginas llegan intercaladas: {urls}"


def test_una_pagina_repartida_conserva_el_orden_de_lectura():
    items = pagina("http://larga", 12, largo=400)
    lotes = repartir(items, 400)
    assert len(lotes) > 1
    indices = [i["indice_chunk"] for l in lotes for i in l]
    assert indices == sorted(indices), "una página partida debe seguir leyéndose en orden"


def test_pagina_mas_grande_que_un_lote_se_parte_en_vez_de_perderse():
    items = pagina("http://enorme", 20, largo=800)
    lotes = repartir(items, 600)
    assert sum(len(l) for l in lotes) == 20


# ── Fijos ────────────────────────────────────────────────────────────────────

def test_los_fijos_van_en_el_primer_lote():
    otras = pagina("http://ruido", 10, largo=400, score=0.9)
    prog = pagina("http://programa", 3, largo=400, score=0.1)
    lotes = repartir(otras + prog, 700, fijos=[prog[0]])
    assert {i["url"] for i in lotes[0]} == {"http://programa"}, \
        "la página fijada arrastra a su página entera al lote 1"


def test_sin_fijos_manda_el_score():
    baja = pagina("http://baja", 2, largo=400, score=0.1)
    alta = pagina("http://alta", 2, largo=400, score=0.9)
    lotes = repartir(baja + alta, 400)
    assert lotes[0][0]["url"] == "http://alta"


# ── Deduplicación ────────────────────────────────────────────────────────────

def test_dedup_quita_el_mismo_texto_llegado_por_dos_fuentes():
    a = chunk("http://a", 0, "MISMO TEXTO", fuente="web_municipio")
    b = chunk("http://b", 0, "MISMO TEXTO", fuente="busqueda_web")
    conservados, quitados = deduplicar_por_texto([a, b])
    assert quitados == 1
    assert len(conservados) == 1


def test_dedup_prefiere_la_pagina_real_al_bloque_de_snippets():
    """
    El snippet puntúa más, pero si gana él la página del programa pierde un
    fragmento por el medio y `ensamblar_contexto` marca un hueco que no existe.
    """
    doc = pagina("http://programa", 3, largo=50)
    snip = chunk("buscadores:snippets", 0, doc[1]["chunk"], score=0.99)
    conservados, quitados = deduplicar_por_texto(doc + [snip])
    assert quitados == 1
    del_doc = [i for i in conservados if i["url"] == "http://programa"]
    assert len(del_doc) == 3, "la página del programa se queda entera"
    assert [i["indice_chunk"] for i in del_doc] == [0, 1, 2]
    assert all(i["url"] != "buscadores:snippets" for i in conservados)


def test_dedup_no_toca_textos_distintos():
    items = pagina("http://a", 5, largo=30)
    conservados, quitados = deduplicar_por_texto(items)
    assert quitados == 0
    assert len(conservados) == 5


# ── Agrupación ───────────────────────────────────────────────────────────────

def test_agrupar_ordena_las_paginas_por_su_mejor_fragmento():
    a = pagina("http://a", 2, score=0.2)
    a[1]["score"] = 0.95           # un fragmento buenísimo en una página floja
    b = pagina("http://b", 2, score=0.6)
    paginas = agrupar_por_pagina(a + b)
    assert paginas[0][0]["url"] == "http://a"


def test_agrupar_devuelve_cada_pagina_en_orden_de_lectura():
    revuelta = [chunk("http://a", i, f"t{i}") for i in (3, 0, 2, 1)]
    paginas = agrupar_por_pagina(revuelta)
    assert [i["indice_chunk"] for i in paginas[0]] == [0, 1, 2, 3]


# ── El caso que motivó todo esto ─────────────────────────────────────────────

def test_el_pdf_de_aranda_entra_entero_en_vez_de_14_de_82():
    """
    82 fragmentos de un PDF de programa compitiendo con ruido. Con el
    empaquetado anterior entraban 14; el repartidor tiene que colocar los 82,
    en orden, sin perder ninguno.
    """
    pdf = pagina("http://ayto/PROGRAMA-2026.pdf", 82, largo=1000, score=0.8)
    ruido = pagina("http://agregador", 40, largo=1000, score=0.7)
    lotes = repartir(pdf + ruido, 30000, fijos=[pdf[0]])

    del_pdf = [i for l in lotes for i in l if i["url"].endswith("PROGRAMA-2026.pdf")]
    assert len(del_pdf) == 82, "no puede perderse ni un fragmento del programa"
    assert [i["indice_chunk"] for i in del_pdf] == list(range(82))
    assert lotes[0][0]["url"].endswith("PROGRAMA-2026.pdf")

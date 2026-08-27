"""
Verificación de la Fase 2 (fusión de señales y cuota garantizada).

El caso central reproduce el ranking que falló el 2026-08-21: el chunk del PDF de
presupuestos ganaba a la agenda de fiestas porque `\\b\\d{1,2}[:.]\\d{2}\\b`
encontraba 154 "horas" en códigos contables y sumaba +0.30 sobre el coseno.

  C2.1  Cada señal vive en 0..1 y ninguna puede dominar la fusión.
  C2.2  La señal de programa distingue agenda de tabla contable.
  C2.3  La señal temporal premia el año objetivo y castiga los caducados.
  C2.4  El prior de la araña se normaliza y los chunks sin dato quedan neutros.
  C2.5  El ranking real: la agenda gana al presupuesto, aunque el coseno mienta.
  C2.6  La cuota garantiza el Top-3 de la araña incluso sin embeddings.
  C2.7  `seleccionar_chunks` sigue siendo un empaquetador puro y sin repetidos.
  C2.8  El umbral adaptativo se ajusta al mejor chunk de cada localidad.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ranking_chunks as rk
from llm_processor.text_analyzer import seleccionar_chunks

CHUNK_PPTO = "\n".join([
    "TOTAL CONCEPTO 3.2.1. 581.580,00 0,00 581.580,00 1.358.729,64 200,00 0,00 1.358.529,64",
    "3.2.2.01. Entrada vehículos por aceras y reserva aparcamiento 56.000,00 0,00 56.408,63",
    "3.4.0.17. Ingreso teatro euskara 6.966,00 0,00 6.966,00 4.311,00 0,00 0,00 4.311,00",
    "3.4.0.21. Comida cuadrillas 70,00 0,00 70,00 0,00 0,00 0,00 0,00 0,00 0,00 -70,00",
    "Estado de ejecución del presupuesto de ingresos Impreso el 14/01/2025 a las 13:35",
])

CHUNK_AGENDA = "\n".join([
    "Fiestas de San Roque 2026 — programa de actos",
    "12:00 Chupinazo desde el balcón del Ayuntamiento",
    "13:00 Kalejira con la banda de música y los cabezudos",
    "18:30 Concurso de tortilla de patata en la plaza",
    "23:30 Verbena con la orquesta Panorama",
])


def _coseno_falso(q, e):
    """Simula el embedding: devuelve el valor que el propio item lleva preparado."""
    return e if isinstance(e, (int, float)) else 0.0


def _item(chunk, url, fuente="web_municipio", score_spider=0, emb=0.5, prioridad=2):
    return {"chunk": chunk, "url": url, "fuente": fuente, "prioridad": prioridad,
            "es_calendario": False, "score_spider": score_spider, "embedding": emb}


def test_c2_1_senales_acotadas():
    for chunk in [CHUNK_PPTO, CHUNK_AGENDA, "", "x" * 5000, "12:00 " * 500]:
        assert 0.0 <= rk.senal_programa(chunk) <= 1.0
        for anno in (2025, 2026, 2027):
            assert 0.0 <= rk.senal_temporal(chunk, anno) <= 1.0

    # Ninguna señal aislada puede llevar el score fuera de 0..1.
    items = [_item(CHUNK_AGENDA, "https://a/1", score_spider=3340, emb=1.0),
             _item(CHUNK_PPTO, "https://a/2", score_spider=1000, emb=0.0)]
    rk.puntuar_chunks(items, query_emb=[1.0], anno=2026, coseno=_coseno_falso)
    for i in items:
        assert 0.0 <= i["score"] <= 1.0, i["score"]
        assert set(i["score_detalle"]) == {"similitud", "spider", "programa", "temporal"}


def test_c2_2_senal_programa():
    assert rk.senal_programa(CHUNK_AGENDA) > 0.7, rk.senal_programa(CHUNK_AGENDA)
    assert rk.senal_programa(CHUNK_PPTO) < 0.2, rk.senal_programa(CHUNK_PPTO)
    # Un titular sin horarios todavía puntúa por léxico.
    solo_lexico = "Programa de las fiestas patronales de San Roque, con el cartel anunciador"
    assert 0.2 < rk.senal_programa(solo_lexico) < 0.5
    assert rk.senal_programa("Convocatoria de ayudas al alquiler de vivienda") == 0.0


def test_c2_3_senal_temporal():
    assert rk.senal_temporal("Fiestas de agosto de 2026", 2026) == 1.0
    assert rk.senal_temporal("Programa de fiestas 2024", 2026) == 0.0
    assert rk.senal_temporal("Presupuesto de 2025 y 2024", 2026) == 0.0
    # Sin año: neutro. Es esencial — la mayoría de líneas de un programa
    # ("23:30 Verbena") no repiten el año y penalizarlas expulsaría el programa.
    assert rk.senal_temporal("23:30 Verbena con la orquesta", 2026) == rk.NEUTRO
    # Mezcla con el año objetivo presente: gana el objetivo.
    assert rk.senal_temporal("Comparativa 2024 2025 2026", 2026) == 1.0


def test_c2_4_prior_spider():
    items = [_item("a", "https://a/1", score_spider=3340),
             _item("b", "https://a/2", score_spider=1000),
             _item("c", "https://a/3", score_spider=1650),
             _item("d", "https://a/4", score_spider=0)]  # sin dato (RRSS/buscador)
    priors = rk._priors_spider(items)
    assert priors[3340] == 1.0
    assert priors[1000] == rk.PRIOR_SPIDER_MINIMO
    assert rk.PRIOR_SPIDER_MINIMO < priors[1650] < 1.0
    # El que no tiene dato no se penaliza: queda neutro, por encima del mínimo.
    rk.puntuar_chunks(items, query_emb=None, anno=2026, coseno=_coseno_falso)
    sin_dato = [i for i in items if i["url"].endswith("/4")][0]
    peor_arana = [i for i in items if i["url"].endswith("/2")][0]
    assert sin_dato["score_detalle"]["spider"] == rk.NEUTRO
    assert sin_dato["score_detalle"]["spider"] > peor_arana["score_detalle"]["spider"]

    # Si todas las páginas empatan, ninguna se ve arbitrariamente favorecida.
    iguales = [_item("a", "https://a/1", score_spider=1000),
               _item("b", "https://a/2", score_spider=1000)]
    p2 = rk._priors_spider(iguales)
    assert p2[1000] == 1.0


def test_c2_5_la_agenda_gana_al_presupuesto():
    """El escenario exacto que falló: el coseno favorece al presupuesto."""
    # Se le pone al presupuesto MEJOR coseno que a la agenda, para comprobar que
    # el resto de señales corrigen el error del embedding.
    ppto = _item(CHUNK_PPTO, "https://udala.amurrio.eus/docs/ANEXO_3_Ppto_2025.pdf",
                 score_spider=1220, emb=0.62)
    agenda = _item(CHUNK_AGENDA, "https://www.amurrioturismo.com/agenda-amurrio",
                   score_spider=3340, emb=0.41)
    items = [ppto, agenda]
    rk.puntuar_chunks(items, query_emb=[1.0], anno=2026, coseno=_coseno_falso)

    assert agenda["score"] > ppto["score"], (
        f"el presupuesto sigue ganando: agenda={agenda['score']:.3f} "
        f"ppto={ppto['score']:.3f} | {agenda['score_detalle']} vs {ppto['score_detalle']}"
    )
    # Y con holgura, no por los pelos.
    assert agenda["score"] - ppto["score"] > 0.15


def test_c2_6_cuota_garantizada():
    """
    La cuota importa cuando la competencia también puntúa bien y encima tiene más
    prioridad de fuente. `seleccionar_chunks` sirve las fuentes oficiales por
    PRIORIDAD y solo después por score: decenas de páginas de la web de la
    localidad (prioridad 1) que hablan de actos y del año objetivo agotan el
    presupuesto antes de llegar a la agenda del municipio (prioridad 2), que es
    la página que la araña había colocado la primera con 3340 puntos.
    """
    # Competencia plausible: páginas de la web de la localidad con horarios y 2026.
    texto_relleno = ("Actividades culturales 2026 del centro cívico\n"
                     "18:00 Taller de manualidades\n19:00 Concierto de la coral\n"
                     "20:00 Teatro infantil en el salón de actos")
    relleno = [
        _item(texto_relleno, f"https://localidad/p{i}", fuente="web_localidad",
              prioridad=1, score_spider=1000, emb=0.9)
        for i in range(30)
    ]
    # Presupuesto justo para 20 chunks de relleno: se agota exactamente y no queda
    # hueco para nada más. Es el caso en que el orden de servicio decide.
    presupuesto = 20 * len(texto_relleno)
    agenda = _item(CHUNK_AGENDA, "https://turismo/agenda",
                   fuente="web_municipio", prioridad=2, score_spider=3340, emb=0.1)
    items = relleno + [agenda]
    rk.puntuar_chunks(items, query_emb=[1.0], anno=2026, coseno=_coseno_falso)
    umbral = rk.umbral_adaptativo(items)

    # La agenda supera el umbral: no es que sea mala, es que la sirven la última.
    assert agenda["score"] >= umbral, f"{agenda['score']:.3f} < {umbral:.3f}"

    sin_cuota = seleccionar_chunks(items, budget_chars=presupuesto, umbral=umbral)
    assert "https://turismo/agenda" not in {x["url"] for x in sin_cuota}, \
        "el escenario no reproduce el problema que la cuota debe evitar"

    # Con la cuota, entra la primera.
    garantizados = rk.chunks_garantizados(items)
    assert agenda in garantizados
    con_cuota = seleccionar_chunks(items, budget_chars=presupuesto, umbral=umbral,
                                   garantizados=garantizados)
    assert "https://turismo/agenda" in {x["url"] for x in con_cuota}, \
        "la agenda se ha quedado fuera del contexto pese a la cuota"

    # La cuota reserva sitio para los mejores documentos de la araña, no para
    # cualquiera: como mucho RANKING_DOCS_GARANTIZADOS documentos.
    urls_gar = {g["url"] for g in garantizados}
    assert len(urls_gar) <= rk.RANKING_DOCS_GARANTIZADOS
    assert "https://turismo/agenda" in urls_gar

    # Y no canibaliza el presupuesto: el resto del contexto sigue llenándose.
    assert len(con_cuota) > 1


def test_c2_7_seleccionar_chunks_sigue_siendo_puro():
    items = [_item(CHUNK_AGENDA, "https://a/1", score_spider=3340),
             _item(CHUNK_PPTO, "https://a/2", score_spider=1000)]
    for i in items:
        i["score"] = 0.8
    antes = [i["score"] for i in items]
    sel = seleccionar_chunks(items, budget_chars=100_000, umbral=0.1, garantizados=items[:1])
    assert [i["score"] for i in items] == antes, "ha modificado los scores"
    # Ningún chunk repetido aunque esté garantizado y además pase el umbral.
    assert len(sel) == len({id(s) for s in sel}) == 2

    # Un garantizado que no cabe no rompe nada ni desplaza al resto.
    sel2 = seleccionar_chunks(items, budget_chars=10, umbral=0.1, garantizados=items)
    assert sel2 == []


def test_c2_8_umbral_adaptativo():
    buenos = [{"score": 0.9}, {"score": 0.8}, {"score": 0.2}]
    u = rk.umbral_adaptativo(buenos, fraccion=0.55, minimo=0.25)
    assert abs(u - 0.495) < 1e-9
    assert [i for i in buenos if i["score"] >= u] == [{"score": 0.9}, {"score": 0.8}]

    # Localidad pobre: el suelo absoluto evita admitir cualquier cosa.
    malos = [{"score": 0.2}, {"score": 0.1}]
    assert rk.umbral_adaptativo(malos, fraccion=0.55, minimo=0.25) == 0.25
    assert rk.umbral_adaptativo([], fraccion=0.55, minimo=0.25) == 0.25


def test_c2_9_la_garantia_no_pasa_por_encima_del_veto_temporal():
    """
    Un programa CADUCADO es el peor material posible: se parece muchísimo a lo
    que se busca, pero con las fechas del año equivocado. Aunque la araña lo haya
    puntuado alto, no puede tener plaza garantizada.
    """
    programa_2024 = ("Fiestas de San Roque 2024. Programa de actos de las fiestas "
                     "patronales de 2024.\n12:00 Chupinazo\n19:00 Verbena\n23:00 Concierto")
    viejo = _item(programa_2024, "https://udala/noticias/fiestas-2024",
                  score_spider=3000, emb=0.9)
    agenda = _item(CHUNK_AGENDA, "https://turismo/agenda", score_spider=1200, emb=0.1)
    otro = _item("Calendario 2026\n15/08/2026 12:00 Txupinazoa en la plaza del pueblo",
                 "https://udala/calendario/2026", score_spider=900, emb=0.5)
    items = [viejo, agenda, otro]
    rk.puntuar_chunks(items, query_emb=[1.0], anno=2026, coseno=_coseno_falso)

    # Parece un programa, pero al ser de otro año esa señal deja de valerle.
    assert rk.senal_temporal(programa_2024, 2026) == 0.0
    assert viejo["score_detalle"]["programa"] < 0.35, viejo["score_detalle"]

    gar = rk.chunks_garantizados(items, anno=2026)
    urls = {g["url"] for g in gar}
    assert "https://udala/noticias/fiestas-2024" not in urls, \
        "un programa de 2024 ha conseguido plaza garantizada"
    # Y la plaza liberada pasa a los siguientes documentos, no se pierde.
    assert "https://turismo/agenda" in urls
    assert "https://udala/calendario/2026" in urls

    # Sin `anno` el veto no se aplica (compatibilidad hacia atrás).
    assert "https://udala/noticias/fiestas-2024" in {g["url"] for g in rk.chunks_garantizados(items)}


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK    {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  FALLO {nombre}: {e}")
    if fallos:
        print(f"\nVERIFY C2 FALLIDO: {fallos} comprobaciones.")
        sys.exit(1)
    print("\nVERIFY C2 PASSED: fusión de señales y cuota garantizada operativas.")

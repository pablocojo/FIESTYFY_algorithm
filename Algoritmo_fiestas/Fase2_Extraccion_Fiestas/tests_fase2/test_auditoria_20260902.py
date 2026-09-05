"""
Regresiones de la auditoría del 2026-09-02.

Cada caso de aquí sale de contrastar las dos ejecuciones completas de Tobarra y
Aranda de Duero contra los programas oficiales publicados:

    fase2_20260828_154633.log   qwen3.8-27B, 33 h 46 min, 17 fichas
    fase2_20260901_230006.log   qwen3.5-9B,  38 min,      16 fichas

El hallazgo que motiva el fichero: el 27B produjo salidas de LLM claramente
mejores y su JSON final salió PEOR (62% de cobertura media frente a 69%). Todo
lo que ganó se lo quitó la capa de heurísticas posteriores. El anclaje se disparó
8 veces entre las dos ejecuciones, las 8 sobre rangos del modelo que cubrían el
100% de las fechas reales, y no mejoró la cobertura ni una sola vez.

Las fechas reales están verificadas contra:
  - radiotobarra.es (programas oficiales 2026 en PDF de cada pedanía)
  - tobarra.es, arandadeduero.es, enaranda.es
"""

import pytest

from llm_processor.text_analyzer import (
    ajustar_fechas_con_anclas,
    recortar_rango_al_programa,
)

LOC = {"nombre": "X", "id": "09018000201", "es_capital": False}


def _loc(nombre, lid="09018000201"):
    return {"nombre": nombre, "id": lid, "es_capital": False}


def _fiesta(nombre, ini, fin, **extra):
    f = {"id": "x", "lugar_id": "09018000201", "nombre": nombre,
         "fecha_inicio": ini, "fecha_fin": fin, "descripcion": "", "programa": [],
         "origen": "extraccion"}
    f.update(extra)
    return f


def _ajustar(f, ctx, localidad, hermanas, patron=None):
    return ajustar_fechas_con_anclas([f], ctx, localidad, hermanas, 2026, patron)[0]


# ──────────────────────────────────────────────────────────────
# El anclaje no colapsa una fiesta de varios días en una de un día
# ──────────────────────────────────────────────────────────────

def test_aranda_no_se_queda_en_un_dia():
    """
    El peor daño medido de todo el pipeline, idéntico en las dos ejecuciones.

    Las fiestas mayores de Aranda de Duero son del 11 al 20 de septiembre de
    2026 y el ayuntamiento lo repite SEIS veces en el propio contexto. El 27B
    dio 09-11→09-20, exacto; el 9B dio 08-31→09-20 tras la fusión. En las dos,
    un anclaje de peso 6 sobre el 15 de septiembre —el día grande, que es el que
    citan los titulares— las dejó durando un día y sin programa.
    """
    ctx = ("titulo fiestas patronales de aranda de duero 2026 el dia grande es el 15 de "
           "septiembre de 2026. las fiestas de aranda de duero 2026 tienen su dia grande "
           "el 15 de septiembre. programa fiestas de aranda de duero 15 de septiembre "
           "2026. cartel fiestas de aranda de duero 2026 15 de septiembre. ") * 2

    for ini, fin in [("2026-09-11", "2026-09-20"), ("2026-08-31", "2026-09-20")]:
        f = _ajustar(
            _fiesta("Fiestas Patronales en honor a Nuestra Señora de las Viñas", ini, fin),
            ctx, _loc("Aranda de Duero"), ["Sinovas", "La Aguilera"],
        )
        assert (f["fecha_inicio"], f["fecha_fin"]) == (ini, fin)


def test_los_mardos_no_se_queda_en_el_ultimo_dia():
    """
    27B: el modelo dio 16-19 de julio, que es literalmente lo que pone la portada
    del programa oficial ("Del 16 al 19 de julio"), y el anclaje lo dejó en el 19.
    """
    ctx = ("titulo fiestas de los mardos 2026 el 19 de julio. las fiestas de los mardos "
           "2026 se celebran el 19 de julio. programa fiestas de los mardos 19 de julio "
           "2026. los mardos 2026 19 de julio virgen del carmen. ") * 2
    f = _ajustar(
        _fiesta("Fiestas Patronales de Los Mardos en honor a la Virgen del Carmen",
                "2026-07-16", "2026-07-19"),
        ctx, _loc("Los Mardos", "02074000701"), ["Aljubé", "Sierra"],
    )
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-07-16", "2026-07-19")


def test_el_ancla_frenada_queda_anotada_como_propuesta():
    """
    Frenar el anclaje no es tirar la información: la frase decía algo y se guarda
    para poder revisarla sin volver al log.
    """
    ctx = ("titulo fiestas de los mardos 2026 el 19 de julio. las fiestas de los mardos "
           "2026 se celebran el 19 de julio. programa fiestas de los mardos 19 de julio "
           "2026. los mardos 2026 19 de julio virgen del carmen. ") * 2
    f = _ajustar(
        _fiesta("Fiestas de Los Mardos", "2026-07-16", "2026-07-19"),
        ctx, _loc("Los Mardos", "02074000701"), ["Aljubé"],
    )
    prop = f.get("ancla_propuesta")
    assert prop and (prop["fecha_inicio"], prop["fecha_fin"]) == ("2026-07-19", "2026-07-19")
    assert prop["evidencia"]


# ──────────────────────────────────────────────────────────────
# El anclaje tampoco recorta un rango que ya cubre al santo
# ──────────────────────────────────────────────────────────────

def test_el_ancla_no_recorta_un_rango_que_ya_cubre_al_patron():
    """
    Hasta el 2026-09-02 la guarda del santo tenía una excepción: un anclaje
    METIDO dentro del rango del modelo se dejaba pasar. Por ahí se colaron los
    dos recortes que siguen.

    San Roque de Tobarra, 27B: el modelo dio 08-08→08-22, que contiene el 16 de
    agosto; el anclaje lo recortó a 08-09→08-17 y se perdieron los cuatro
    últimos días de fiesta, incluido el castillo de fuegos de fin de fiestas. Las
    fechas oficiales son 14-21 de agosto.
    """
    ctx = ("titulo fiestas patronales de tobarra de verano se celebran del 9 al 17 de "
           "agosto en la caseta de tobarra. ") * 4
    f = _ajustar(
        _fiesta("Feria y Fiestas de San Roque de Tobarra", "2026-08-08", "2026-08-22"),
        ctx, _loc("Tobarra", "02074000601"), ["Aljubé", "Sierra"],
        {"nombre": "Cristo de la Antigua", "dia": None, "mes": None},
    )
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-08", "2026-08-22")


def test_la_aguilera_conserva_el_dia_de_la_imposicion_de_bandas():
    """
    Las dos ejecuciones acertaron 12-17 de mayo —que es lo que publica
    enaranda.es— y las dos lo perdieron igual: el anclaje lo recortó a 13-17.
    El 12 es el día de la imposición de bandas a la reina, damas y galanes.
    """
    ctx = ("titulo fiestas de la aguilera 2026 del 13 al 17 de mayo. las fiestas de la "
           "aguilera 2026 se celebran del 13 al 17 de mayo. programa fiestas de la "
           "aguilera del 13 al 17 de mayo 2026. ") * 2
    patron = {"nombre": "San Pedro Regalado", "dia": 13, "mes": 5}
    f = _ajustar(
        _fiesta("Fiestas Patronales de La Aguilera en honor a San Pedro Regalado",
                "2026-05-12", "2026-05-17"),
        ctx, _loc("La Aguilera", "09018000101"), ["Sinovas"], patron,
    )
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-05-12", "2026-05-17")


def test_sierra_si_se_afina_porque_su_santo_no_cae_en_el_rango():
    """
    El único de los 8 disparos que no hizo daño, y sigue funcionando.

    Sierra celebra en verano en honor a San Francisco Javier, cuyo día es el 3 de
    diciembre: el rango del modelo (25 jul - 2 ago) no cubre al santo, así que no
    hay nada que proteger y el anclaje afina hasta el 30 de julio - 2 de agosto,
    que es lo que anuncia la propia comisión de fiestas.
    """
    ctx = ("titulo fiestas sierra verano 2026 sierra se viste de fiesta del 30 de julio "
           "al 2 de agosto celebramos las fiestas de sierra 2026. programa fiestas de "
           "sierra 2026 del 30 de julio al 2 de agosto. ") * 2
    patron = {"nombre": "San Francisco Javier", "dia": 3, "mes": 12}
    f = _ajustar(
        _fiesta("Fiestas de Sierra 2026 en honor a San Francisco Javier",
                "2026-07-25", "2026-08-02"),
        ctx, _loc("Sierra", "02074000501"), ["Aljubé", "Los Mardos"], patron,
    )
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-07-30", "2026-08-02")


# ──────────────────────────────────────────────────────────────
# El recorte por programa, que sustituye al del anclaje
# ──────────────────────────────────────────────────────────────

def test_aljube_pierde_la_cola_que_nadie_respalda():
    """
    9B: la ficha salió del 13 al 24 de mayo. Su programa oficial dice "Del 13 al
    17 de Mayo" —la frase está DOS veces en el contexto que se le dio al modelo—
    y el esqueleto del programa no pasa del 18. Los seis días siguientes no los
    miró nadie.

    El 13 se conserva aunque no tenga actos: está en el programa, solo que vacío.
    """
    f = recortar_rango_al_programa({
        "nombre": "Fiestas de Aljubé en honor a San Isidro Labrador",
        "fecha_inicio": "2026-05-13", "fecha_fin": "2026-05-24",
        "programa": [
            {"fecha": "2026-05-13", "eventos": []},
            {"fecha": "2026-05-14", "eventos": [{"hora": "11:00", "descripcion": "Ofrenda de flores"}]},
            {"fecha": "2026-05-16", "eventos": [{"hora": "18:00", "descripcion": "Talleres"}]},
            {"fecha": "2026-05-17", "eventos": [{"hora": "19:00", "descripcion": "Merienda popular"}]},
            {"fecha": "2026-05-18", "eventos": []},
        ],
    })
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-05-13", "2026-05-18")


def test_el_recorte_por_programa_no_toca_san_roque():
    """
    Tobarra tiene prefiestas desde el 8 de agosto y un día de cierre el 22: el
    programa cubre el rango entero y no hay nada que recortar.
    """
    dias = ["2026-08-08", "2026-08-09", "2026-08-10", "2026-08-14", "2026-08-15",
            "2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
            "2026-08-21", "2026-08-22"]
    f = recortar_rango_al_programa({
        "nombre": "Fiestas de San Roque y Feria de Tobarra 2026",
        "fecha_inicio": "2026-08-08", "fecha_fin": "2026-08-22",
        "programa": [{"fecha": d, "eventos": [{"hora": "20:00", "descripcion": f"Acto {d}"}]}
                     for d in dias],
    })
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-08", "2026-08-22")


@pytest.mark.parametrize("caso, programa, espera", [
    # Un programa de un solo día no convierte una fiesta de diez en una de uno:
    # es el mismo error que se le prohíbe al anclaje.
    ("suelo de dos días", [("2026-08-05", 1)], ("2026-08-01", "2026-08-10")),
    # Ampliar por esta vía sería inventar días de fiesta.
    ("solo encoge", [("2026-07-25", 1), ("2026-08-20", 1)], ("2026-08-01", "2026-08-10")),
    # Sin un solo acto no hay programa del que deducir nada.
    ("sin actos", [("2026-08-04", 0), ("2026-08-06", 0)], ("2026-08-01", "2026-08-10")),
    # Con dos días tampoco: no dicen cuánto dura la fiesta (Sierra, Santiago de Mora).
    ("dos días no bastan", [("2026-08-03", 1), ("2026-08-07", 1)], ("2026-08-01", "2026-08-10")),
    # Con actos y suficientes días, recorta.
    ("recorta", [("2026-08-03", 1), ("2026-08-05", 1), ("2026-08-07", 1)],
     ("2026-08-03", "2026-08-07")),
])
def test_frenos_del_recorte_por_programa(caso, programa, espera):
    f = recortar_rango_al_programa({
        "nombre": "Fiestas", "fecha_inicio": "2026-08-01", "fecha_fin": "2026-08-10",
        "programa": [
            {"fecha": d, "eventos": [{"hora": "12:00", "descripcion": "Acto concreto"}] if n else []}
            for d, n in programa
        ],
    })
    assert (f["fecha_inicio"], f["fecha_fin"]) == espera, caso


# ──────────────────────────────────────────────────────────────
# La fusión no se come eventos con marca propia
# ──────────────────────────────────────────────────────────────

def test_sonorama_sobrevive_a_la_fusion():
    """
    27B: 'Sonorama Ribera 2026' pasó el filtro —"multi-día con actividad nocturna
    (conciertos)"— y acto seguido la fusión lo absorbió dentro de 'Fiestas
    Patronales de Aranda de Duero 2026' (3-11 de agosto). El festival, con sus
    135 actos, desapareció como ficha.
    """
    from llm_processor.festival_filter import fusionar_fiestas_proximas

    def f(n, i, fin):
        return {"nombre": n, "fecha_inicio": i, "fecha_fin": fin, "programa": [], "fuentes": []}

    salida = fusionar_fiestas_proximas([
        f("Fiestas Patronales de Aranda de Duero 2026", "2026-08-03", "2026-08-11"),
        f("Sonorama Ribera 2026", "2026-08-05", "2026-08-09"),
    ])
    assert {x["nombre"] for x in salida} == {
        "Fiestas Patronales de Aranda de Duero 2026", "Sonorama Ribera 2026"}


def test_las_variantes_del_mismo_nombre_siguen_fusionando():
    """
    Lo que la fusión existe para arreglar no se toca: el modelo devuelve la misma
    fiesta con cuatro redacciones distintas y siguen siendo una.
    """
    from llm_processor.festival_filter import fusionar_fiestas_proximas

    def f(n, i, fin):
        return {"nombre": n, "fecha_inicio": i, "fecha_fin": fin, "programa": [], "fuentes": []}

    salida = fusionar_fiestas_proximas([
        f("Fiestas Patronales de Aranda de Duero 2026", "2026-09-11", "2026-09-16"),
        f("Fiestas Patronales de la Virgen de las Viñas", "2026-09-12", "2026-09-20"),
    ])
    assert len(salida) == 1
    assert (salida[0]["fecha_inicio"], salida[0]["fecha_fin"]) == ("2026-09-11", "2026-09-20")


@pytest.mark.parametrize("nombre, es_marca", [
    ("Sonorama Ribera 2026", True),
    ("Tobarrock", True),
    ("Semana Cultural Monte Costaján", True),
    ("Fiestas Patronales de Aranda de Duero 2026", False),
    ("Fiestas Patronales de la Virgen de las Viñas", False),
    ("IX Gran Fiesta de la Vendimia", False),
    ("Feria y Fiestas de San Roque de Tobarra", False),
    ("Romería de San Marcos", False),
    ("Fiestas del Barrio de La Calabaza", False),
])
def test_reconocer_evento_con_nombre_propio(nombre, es_marca):
    from llm_processor.festival_filter import es_evento_con_nombre_propio
    assert es_evento_con_nombre_propio(nombre) is es_marca


# ──────────────────────────────────────────────────────────────
# El anclaje exige que la fecha esté cerca del pueblo
# ──────────────────────────────────────────────────────────────

def test_la_fecha_lejana_del_pueblo_no_ancla():
    """
    La fiesta fantasma de Mora de Santa Quiteria. En su contexto, el titular
    «Mora de Santa Quiteria se prepara para un gran fin de semana de fiestas en
    honor a su patrona» y la frase «El festival se celebrará del 10 al 12 de
    septiembre en la Casa de la Cultura… tres referentes de la narración y la
    literatura oral» viven en el mismo segmento a noventa líneas de distancia.
    """
    from llm_processor.text_analyzer import anclas_de_fechas
    relleno = "texto de relleno sin ninguna fecha ni nombre de pueblo. " * 40
    ctx = ("titulo mora de santa quiteria se prepara para un gran fin de semana de "
           "fiestas en honor a su patrona\n" + relleno +
           "el festival se celebrara del 10 al 12 de septiembre en la casa de la cultura")
    anclas = anclas_de_fechas(ctx, {"nombre": "Mora de Santa Quiteria", "id": "x"},
                              ["Aljubé", "Sierra"], 2026, "Tobarra")
    assert not any(str(a["inicio"]) == "2026-09-10" for a in anclas)


def test_la_fecha_pegada_al_pueblo_si_ancla():
    """Y lo que está en la misma frase sigue anclando, que es para lo que existe."""
    from llm_processor.text_analyzer import anclas_de_fechas
    ctx = ("titulo las fiestas de mora de santa quiteria 2026 se celebran del 22 al 24 "
           "de mayo. programa fiestas de mora de santa quiteria del 22 al 24 de mayo 2026.")
    anclas = anclas_de_fechas(ctx, {"nombre": "Mora de Santa Quiteria", "id": "x"},
                              ["Aljubé", "Sierra"], 2026, "Tobarra")
    assert anclas and (str(anclas[0]["inicio"]), str(anclas[0]["fin"])) == ("2026-05-22", "2026-05-24")


# ──────────────────────────────────────────────────────────────
# Fiestas móviles: la Tamborada dejaba de existir por no citar un mes
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto, meses", [
    ("la tamborada suena desde el Miércoles Santo", {4}),      # Pascua 2026 = 5 abril
    ("Semana Santa en Tobarra", {3, 4}),
    ("el martes de carnaval hay desfile", {2}),
    ("procesión del Corpus Christi", {6}),
    ("las fiestas son en agosto", set()),
])
def test_meses_de_fiestas_moviles(texto, meses):
    from llm_processor.festival_filter import meses_de_fiestas_moviles
    assert meses_de_fiestas_moviles(texto, 2026) == meses


def test_el_barrido_mete_la_tamborada_en_abril():
    """
    Sin esto el chunk no entra en ningún cubo de mes, no se pregunta por él y la
    Tamborada de Tobarra —104 horas de tambor, inscrita por la UNESCO— no existe
    para el pipeline. Falta en las dos ejecuciones completas, con 9B y con 27B.
    """
    from llm_processor.text_analyzer import barrer_meses_con_senal
    chunks = [{"chunk": "La tamborada de Tobarra arranca el Miércoles Santo a las "
                        "16:00 y suena 104 horas seguidas hasta el Domingo de "
                        "Resurrección. Procesión y tambores por todo el pueblo."}]
    assert barrer_meses_con_senal(chunks, "Tobarra") == {}
    assert 4 in barrer_meses_con_senal(chunks, "Tobarra", 2026)


# ──────────────────────────────────────────────────────────────
# La araña no se gasta el presupuesto en la sede electrónica
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, bloqueada", [
    # De la ejecución real de Tobarra: 47 de las 66 URLs priorizadas eran estas.
    ("https://tobarra.sedipualba.es/tablondeanuncios/anuncio.aspx?id=72040", True),
    ("https://tobarra.sedipualba.es/carpetaciudadana.aspx", True),
    ("https://tobarra.sedipualba.es/catalogoservicios.aspx?area=&ambito=2", True),
    ("https://tobarra.sedipualba.es/incidencias.aspx", True),
    ("https://cualquiera.sedelectronica.es/info.0", True),
    # Y lo que tiene que seguir entrando.
    ("https://tobarra.es/fiestas/", False),
    ("https://tobarra.es/carnaval-adultos-2024/", False),
    ("https://www.radiotobarra.es/wp-content/uploads/sanroque26.pdf", False),
    ("https://www.enaranda.es/evento/fiestas-de-san-bartolome-sinovas-agosto-2026/", False),
])
def test_lista_negra_de_sedes_electronicas(url, bloqueada):
    from scraper.heuristic_spider import URL_BLACKLIST
    assert any(s in url.lower() for s in URL_BLACKLIST) is bloqueada


# ──────────────────────────────────────────────────────────────
# Frenos del recorte por programa, salidos de la ejecución del 2026-09-02
#
# El recorte se estrenó sin condiciones y en esa ejecución se disparó seis
# veces: acertó tres y estropeó tres. Los tres frenos de aquí separan unos de
# otros sin tocar los que acertaron.
# ──────────────────────────────────────────────────────────────

def _con_programa(ini, fin, dias, **extra):
    f = {"nombre": "Fiestas", "fecha_inicio": ini, "fecha_fin": fin,
         "programa": [{"fecha": d,
                       "eventos": [{"hora": "12:00", "descripcion": f"Acto {i}"}
                                   for i in range(n)]}
                      for d, n in dias]}
    f.update(extra)
    return f


def test_un_programa_de_dos_dias_no_recorta_sierra():
    """
    Sierra: el modelo dio del 30 de julio al 2 de agosto, que es lo que anuncia
    su comisión de fiestas, y el recorte lo dejó en dos días porque el programa
    que se encontró solo tenía dos. Un programa de dos días no dice cuánto dura
    la fiesta, solo que esos dos días existen.
    """
    f = recortar_rango_al_programa(_con_programa(
        "2026-07-30", "2026-08-02", [("2026-07-30", 1), ("2026-07-31", 1)]))
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-07-30", "2026-08-02")


def test_un_programa_de_dos_dias_no_recorta_santiago_de_mora():
    """Santiago de Mora: de cinco días a dos, cuando lo suyo son once (20-30 jul)."""
    f = recortar_rango_al_programa(_con_programa(
        "2026-07-21", "2026-07-25", [("2026-07-24", 6), ("2026-07-25", 6)]))
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-07-21", "2026-07-25")


def test_no_se_recorta_con_el_programa_de_otro_anno():
    """
    Aranda de Duero: el único programa publicado era el de 2025 —el enrichment
    lo dice y marca la ficha— y con él se recortaron las fechas de 2026 hasta el
    13 de septiembre. Sus fiestas acaban el 20.
    """
    f = recortar_rango_al_programa(_con_programa(
        "2026-09-02", "2026-09-20",
        [("2026-09-02", 2), ("2026-09-08", 5), ("2026-09-13", 4)],
        programa_de_otro_anno=2025))
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-09-02", "2026-09-20")


def test_no_se_recorta_con_un_programa_de_otra_fiesta():
    """
    Si el enrichment ya ha avisado de que la página elegida no nombra la
    advocación de esta fiesta, ese programa no puede mandar sobre las fechas.
    """
    f = recortar_rango_al_programa(_con_programa(
        "2026-07-30", "2026-08-02",
        [("2026-07-30", 1), ("2026-07-31", 1), ("2026-08-01", 1)],
        programa_advocacion_dudosa=True))
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-07-30", "2026-08-02")


@pytest.mark.parametrize("caso, ini, fin, dias, espera", [
    # Los tres recortes que SÍ acertaron en esa ejecución siguen funcionando.
    ("San Roque de Tobarra al 14 de agosto exacto", "2026-08-08", "2026-08-22",
     [("2026-08-14", 6), ("2026-08-15", 9), ("2026-08-16", 5),
      ("2026-08-17", 6), ("2026-08-21", 7), ("2026-08-22", 3)],
     ("2026-08-14", "2026-08-22")),
    ("Aljubé pierde la cola de siete días", "2026-05-13", "2026-05-24",
     [("2026-05-13", 0), ("2026-05-14", 3), ("2026-05-16", 5),
      ("2026-05-17", 3), ("2026-05-18", 0)],
     ("2026-05-13", "2026-05-18")),
    ("Tobarra Cristo pierde cinco días de más", "2026-05-03", "2026-05-17",
     [("2026-05-09", 3), ("2026-05-11", 2), ("2026-05-16", 1), ("2026-05-17", 2)],
     ("2026-05-09", "2026-05-17")),
])
def test_los_recortes_que_acertaron_siguen_funcionando(caso, ini, fin, dias, espera):
    f = recortar_rango_al_programa(_con_programa(ini, fin, dias))
    assert (f["fecha_inicio"], f["fecha_fin"]) == espera, caso


def test_un_programa_de_otra_fiesta_baja_la_confianza():
    """
    Aranda de Duero salió con unas 'Fiestas Patronales (San Roque)' de 29 días y
    166 actos, marcadas con `programa_advocacion_dudosa` —el enrichment ya había
    visto que su programa no nombra a San Roque por ningún sitio— y aun así con
    `confianza: alta`. El patrón de Aranda es la Virgen de las Viñas.

    El programa de otro AÑO ya bajaba la confianza; el de otra FIESTA no.
    """
    import llm_processor.text_analyzer as ta
    import inspect
    fuente = inspect.getsource(ta.enrich_festival_program)
    assert 'fiesta["programa_advocacion_dudosa"] = True' in fuente
    marca = fuente.split('fiesta["programa_advocacion_dudosa"] = True', 1)[1][:200]
    assert 'confianza' in marca and '"media"' in marca, (
        "la bandera de advocación dudosa debe bajar la confianza, como la de otro año")


# ──────────────────────────────────────────────────────────────
# El filtro ya no mata la Tamborada
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre, ini, fin, desc, aceptada", [
    # Lo que la ejecución del 2026-09-02 descubrió y el filtro tiró: con el
    # barrido de meses ya arreglado, el modelo propuso 'Semana Santa de Tobarra'
    # y el filtro la descartó por "multi-día sin ninguna señal festiva". La
    # palabra estaba en la lista de negativas y en ninguna de las positivas.
    ("Semana Santa de Tobarra", "2026-04-01", "2026-04-05",
     "Tamborada de 104 horas, procesiones y desfiles", True),
    ("Tamborada de Tobarra", "2026-04-01", "2026-04-05",
     "Redoble de tambores ininterrumpido", True),
    # Y lo que tiene que seguir cayendo: un día suelto de calendario o un acto
    # litúrgico aislado no son la fiesta de un pueblo.
    ("Semana Santa", "2026-04-03", "2026-04-03", "", False),
    ("Viernes Santo", "2026-04-03", "2026-04-03", "", False),
    ("Procesión del Rosario", "2026-10-07", "2026-10-07", "Procesión y misa solemne", False),
])
def test_la_semana_santa_multidia_es_una_fiesta(nombre, ini, fin, desc, aceptada):
    from llm_processor.festival_filter import evaluar_fiesta
    ok, motivo, _ = evaluar_fiesta(
        {"nombre": nombre, "fecha_inicio": ini, "fecha_fin": fin,
         "descripcion": desc, "programa": []}, None)
    assert ok is aceptada, motivo


# ──────────────────────────────────────────────────────────────
# Cambio de proveedor: qwen3-32b vía OpenRouter (2026-09-02)
# ──────────────────────────────────────────────────────────────

def test_el_presupuesto_no_se_ata_a_lm_studio_cuando_el_chat_es_remoto(monkeypatch):
    """
    Hasta el 2026-09-02 el presupuesto de contexto salía SIEMPRE del modelo
    cargado en LM Studio. Con el chat en OpenRouter eso deja de tener sentido, y
    además es peligroso: si LM Studio no está levantado —y no tiene por qué, ya
    no contesta— `get_model_info` cae a 8192 de seguridad y todos los prompts se
    construyen con la cuarta parte del material, sin que nada avise.

    Comprobado ese día con LM Studio descargado: get_n_ctx() devolvía 8192.
    """
    import context_budget as cb

    monkeypatch.setattr(cb, "get_model_info",
                        lambda refrescar=False: {"n_ctx": 8192, "detectado": False,
                                                 "id": "local"})
    import config
    monkeypatch.setattr(config, "OPENROUTER_ENABLED", True)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-v1-loquesea")
    monkeypatch.setattr(config, "OPENROUTER_N_CTX", 32768)
    assert cb.get_n_ctx() == 32768

    # Y con OpenRouter apagado se vuelve a mandar el modelo local.
    monkeypatch.setattr(config, "OPENROUTER_ENABLED", False)
    assert cb.get_n_ctx() == 8192


def test_la_cadena_pone_el_modelo_remoto_delante_de_lm_studio():
    """El remoto contesta y LM Studio queda de red de seguridad, no al revés."""
    from llm_processor.text_analyzer import _cadena_proveedores
    from config import OPENROUTER_ENABLED, OPENROUTER_API_KEY
    cadena = _cadena_proveedores()
    assert cadena[-1]["remoto"] is False, "LM Studio tiene que ser el último"
    if OPENROUTER_ENABLED and OPENROUTER_API_KEY:
        assert cadena[0]["remoto"] is True
        assert cadena[0]["modelo"] == "qwen/qwen3-32b"


# ──────────────────────────────────────────────────────────────
# El cliente de RRSS no puede colgar la ejecución entera
# ──────────────────────────────────────────────────────────────

def test_un_timeout_del_servidor_rrss_cuenta_como_aborto():
    """
    El 2026-09-03, con una ejecución en marcha: el servidor de RRSS se quedó
    'EN PAUSA hasta recuperarlo' porque la ventana de Instagram perdió el primer
    plano —su guarda de seguridad, que está bien— y el pipeline se quedó parado
    en '[3-4/5] Solicitando RRSS al servidor Windows...'.

    El fallo estaba en que un timeout caía en el `except Exception` genérico:
    se registraba como "error inesperado", no tocaba el contador de abortos y no
    marcaba el servidor como no disponible. Resultado: la siguiente localidad
    volvía a pedirlo y volvía a esperar los 300s enteros. Doce localidades = una
    hora de espera muerta.
    """
    import asyncio
    from scraper.rrss_client import RRSSClient

    cliente = RRSSClient()
    cliente._disponible = True

    async def _falla_por_timeout(*a, **k):
        raise asyncio.TimeoutError()

    # Se sustituye la petición real por un timeout, tantas veces como haga falta.
    import aiohttp
    class _SesionQueExpira:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def post(self, *a, **k): raise asyncio.TimeoutError()

    original = aiohttp.ClientSession
    aiohttp.ClientSession = _SesionQueExpira
    try:
        for intento in range(1, cliente.MAX_ABORTOS_SEGUIDOS + 1):
            asyncio.run(cliente.procesar_rrss(["02074000601"]))
            assert cliente._abortos_seguidos == intento, (
                "un timeout tiene que contar como aborto")
    finally:
        aiohttp.ClientSession = original

    assert cliente.disponible is False, (
        "tras MAX_ABORTOS_SEGUIDOS timeouts el servidor debe descartarse, "
        "para no perder el timeout entero en cada localidad restante")


def test_existe_la_bandera_para_ejecuciones_desatendidas():
    """
    La automatización de RRSS necesita las ventanas de las apps en primer plano.
    Si nadie está delante, eso no se puede cumplir, y hasta ahora la única forma
    de evitarlo era editar RRSS_SERVER_ENABLED en config.py.
    """
    import subprocess, sys, os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for script in ("main.py", "ejecutar_neutros.py"):
        r = subprocess.run([sys.executable, os.path.join(base, script), "--help"],
                           capture_output=True, text=True, cwd=base, timeout=120)
        assert "--sin-rrss" in r.stdout, f"{script} no ofrece --sin-rrss"


# ──────────────────────────────────────────────────────────────
# Respuestas cortadas por longitud (2026-09-03, con qwen3-32b)
# ──────────────────────────────────────────────────────────────

def test_los_topes_finos_dan_margen_al_razonamiento():
    """
    Con qwen3-32b, 15 de las 20 llamadas de PROCEDENCIA se cortaron en sus 90
    tokens: el razonamiento gasta del mismo presupuesto que la respuesta, y se
    acababa antes de escribir el primer carácter del JSON. Las 5 que sí
    terminaron necesitaron entre 275 y 749 tokens.

    No es solo ruido en el log: una comprobación de procedencia fallida CONSERVA
    el documento, así que cada corte apagaba en silencio el filtro de homónimos
    justo en los documentos donde está el riesgo.
    """
    from config import PROCEDENCIA_MAX_TOKENS, PATRON_LLM_MAX_TOKENS
    assert PROCEDENCIA_MAX_TOKENS >= 800, (
        "90 tokens no dan ni para el razonamiento; el máximo observado fue 749")
    assert PATRON_LLM_MAX_TOKENS >= 800, "mismo problema, aún sin manifestarse"


def test_una_respuesta_truncada_se_reintenta_con_mas_presupuesto():
    """
    El arreglo general: en vez de adivinar el tope exacto de cada llamada, una
    respuesta cortada se vuelve a pedir UNA vez con más presupuesto. Protege a
    cualquier tope fino frente a un modelo que razone más de lo previsto.
    """
    import asyncio
    import llm_processor.text_analyzer as ta

    intentos = []

    async def _fake(prov, sys_p, usr_p, max_tokens, etiqueta, chars):
        intentos.append(max_tokens)
        if len(intentos) == 1:
            return "truncado", '{"sitio": "Tobarra"'      # JSON a medias
        return "ok", '{"sitio": "Tobarra", "pais": "ES"}'

    original = ta._pedir_a_proveedor
    ta._pedir_a_proveedor = _fake
    try:
        r = asyncio.run(ta.llm_chat_json("sys", "usr", max_tokens=90, etiqueta="PROCEDENCIA"))
    finally:
        ta._pedir_a_proveedor = original

    assert len(intentos) == 2, "tenía que haber un segundo intento"
    assert intentos[0] == 90
    assert intentos[1] > intentos[0], "el reintento va con más presupuesto"
    assert r == {"sitio": "Tobarra", "pais": "ES"}, "y devuelve el JSON completo"


# ──────────────────────────────────────────────────────────────
# Paralelismo del LLM (2026-09-03)
# ──────────────────────────────────────────────────────────────

def test_las_tandas_de_discovery_se_piden_a_la_vez():
    """
    Hasta el 2026-09-03 las tandas se encadenaban con `await`: nunca había más de
    una llamada en vuelo y el semáforo remoto no llegaba ni a 2, por muy alto que
    estuviera. Discovery es el 22% del reloj de una ejecución.
    """
    import inspect
    import llm_processor.text_analyzer as ta
    fuente = inspect.getsource(ta._descubrir_por_meses)
    assert "asyncio.gather" in fuente, "las tandas tienen que pedirse a la vez"
    assert "for meses, tanda in tandas:" not in fuente, "quedó el bucle secuencial"


def test_los_lotes_de_enrichment_se_piden_a_la_vez():
    """Enrichment es el 26% del reloj y una fiesta larga se pide en cinco lotes."""
    import inspect
    import llm_processor.text_analyzer as ta
    fuente = inspect.getsource(ta.enrich_festival_program)
    assert "asyncio.gather" in fuente
    assert "for n_lote, lote in enumerate(lotes, 1):" not in fuente


def test_las_busquedas_web_no_se_aceleran():
    """
    El límite que NO se toca. Los buscadores se enfrían por anti-scraping —hay
    tres incidentes documentados de 'envenenamiento anti-scraping'— y multiplicar
    su tasa es justo el problema que el paralelismo del LLM evita a propósito.
    """
    from config import DDG_DELAY_MIN, DDG_DELAY_MAX, SPIDER_DELAY_SECONDS
    assert DDG_DELAY_MIN >= 2.0, "el delay entre búsquedas no debe bajar"
    assert DDG_DELAY_MAX >= 4.0
    assert SPIDER_DELAY_SECONDS >= 0.15, "ni el de la araña sobre un mismo dominio"


def test_el_llm_local_sigue_serializado():
    """
    LM Studio es la reserva y comparte una sola VRAM: su semáforo tiene que
    seguir en 1 aunque el remoto suba.
    """
    import llm_processor.text_analyzer as ta
    from config import OPENROUTER_CONCURRENCY
    assert ta.LLM_SEMAPHORE._value == 1
    assert OPENROUTER_CONCURRENCY > 1

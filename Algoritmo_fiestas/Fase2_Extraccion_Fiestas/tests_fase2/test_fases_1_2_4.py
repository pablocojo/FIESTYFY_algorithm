"""
Fases 1, 2 y 4 del plan del 2026-08-22, calibradas sobre la ejecución de Tobarra
y Aranda de Duero (municipios monolingües, usados como línea base sin la
variable idioma).

  Fase 1 — decir si el programa está, a medias o no está.
  Fase 2 — entender las fechas escritas como regla ("2.º domingo de mayo").
  Fase 4 — no confundir un plazo de inscripción con las fechas de la fiesta.
"""

from datetime import date

import pytest

from llm_processor.text_analyzer import (
    _nombre_desde_evidencia,
    _plano,
    anclas_de_fechas,
    fechas_relativas,
    marcar_estado_del_programa,
    recuperar_fiestas_desde_anclas,
)

PEDANIAS = ["Aljubé", "Cordovilla", "Los Mardos", "Mora de Santa Quiteria",
            "Santiago de Mora", "Sierra", "Sinovas", "La Aguilera"]


def loc(nombre, lid="02074000201"):
    return {"nombre": nombre, "id": lid}


def fiesta(dias_y_actos, **extra):
    """dias_y_actos: lista con el nº de actos de cada día."""
    prog = [{"dia": i + 1, "fecha": f"2026-09-{11 + i:02d}",
             "eventos": [{"hora": "", "descripcion": f"Acto {i}-{j}"} for j in range(n)]}
            for i, n in enumerate(dias_y_actos)]
    f = {"nombre": "Fiestas", "fecha_inicio": "2026-09-11", "fecha_fin": "2026-09-20",
         "confianza": "alta", "programa": prog, "origen": "extraccion"}
    f.update(extra)
    return f


# ──────────────────────────────────────────────────────────────
# Fase 1 — estado del programa
# ──────────────────────────────────────────────────────────────

def test_programa_completo_conserva_la_confianza():
    """Sinovas: 37 actos en 10 días. Sierra: 31 en 15."""
    f = marcar_estado_del_programa(fiesta([4, 4, 4, 4, 4]))
    assert f["programa_estado"] == "completo"
    assert f["confianza"] == "alta"


def test_programa_a_medias_baja_la_confianza():
    """Aranda: fechas exactas (11-20 sep, verificadas) y solo 3 actos en 10 días."""
    f = marcar_estado_del_programa(fiesta([1, 0, 1, 0, 1, 0, 0, 0, 0, 0]))
    assert f["programa_estado"] == "parcial"
    assert f["confianza"] == "media"


def test_programa_ausente_se_dice_con_todas_las_letras():
    f = marcar_estado_del_programa(fiesta([0, 0, 0]))
    assert f["programa_estado"] == "no_encontrado"
    assert f["confianza"] == "media"


def test_una_confianza_ya_baja_no_sube():
    f = marcar_estado_del_programa(fiesta([0, 0, 0], confianza="baja"))
    assert f["confianza"] == "baja"


def test_las_estimadas_no_llevan_estado_de_programa():
    f = marcar_estado_del_programa(fiesta([], origen="santo_patron", confianza="baja"))
    assert "programa_estado" not in f


# ──────────────────────────────────────────────────────────────
# Fase 2 — fechas escritas como regla
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto, rangos, sueltas", [
    # El caso de Tobarra. Mayo de 2026: domingos 3, 10, 17, 24 y 31.
    ("el 2.º, 3.º y 4.º domingo de mayo", [(date(2026, 5, 10), date(2026, 5, 24))], []),
    ("segundo y tercer domingo de mayo", [(date(2026, 5, 10), date(2026, 5, 17))], []),
    # Agosto de 2026: domingos 2, 9, 16, 23 y 30.
    ("fiestas el primer domingo de agosto", [], [date(2026, 8, 2)]),
    ("romería el último domingo de septiembre", [], [date(2026, 9, 27)]),
    ("el tercer sábado de julio", [], [date(2026, 7, 18)]),
    # El día grande de Aranda se anuncia justo así.
    ("el domingo siguiente al 8 de septiembre", [], [date(2026, 9, 13)]),
    # Relativas a una fecha concreta, en los dos sentidos. 24-jun-2026 es
    # miércoles; 8-sep-2026, martes.
    ("el sábado anterior al 24 de junio", [], [date(2026, 6, 20)]),
    ("el viernes previo al 15 de agosto", [], [date(2026, 8, 14)]),
    ("el sábado posterior al 20 de junio", [], [date(2026, 6, 27)]),
    # Sin día de la semana concreto no hay fecha que resolver.
    ("el último fin de semana de agosto", [], []),
    # "o" como conjunción, no como indicador ordinal.
    ("la fiesta es el 2 o 3 de mayo", [], []),
])
def test_fechas_relativas(texto, rangos, sueltas):
    assert fechas_relativas(_plano(texto), 2026) == (rangos, sueltas)


def test_la_fecha_relativa_llega_hasta_el_anclaje():
    ctx = ("titulo fiestas patronales de tobarra mayo 2026 contenido las fiestas "
           "patronales de tobarra de mayo se celebran durante el 2.º, 3.º y 4.º "
           "domingo de mayo en honor al santisimo cristo de la antigua")
    a = anclas_de_fechas(ctx, loc("Tobarra"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 5, 10), date(2026, 5, 24))


def test_se_anade_la_fiesta_que_el_modelo_no_vio():
    """
    Tobarra salía con San Antón y San Roque y se dejaba sus patronales de verdad,
    las de mayo, que estaban en su contexto con nombre, patronos y fecha.
    """
    ctx = ("titulo fiestas patronales de tobarra mayo 2026 contenido las fiestas "
           "patronales de tobarra de mayo se celebran durante el 2.º, 3.º y 4.º "
           "domingo de mayo en honor al santisimo cristo de la antigua")
    ya = [{"nombre": "Fiestas de San Roque", "fecha_inicio": "2026-08-14",
           "fecha_fin": "2026-08-21", "origen": "extraccion"}]
    out = recuperar_fiestas_desde_anclas(ya, ctx, loc("Tobarra"), PEDANIAS, 2026)
    assert len(out) == 2
    nueva = out[1]
    assert (nueva["fecha_inicio"], nueva["fecha_fin"]) == ("2026-05-10", "2026-05-24")
    assert nueva["origen"] == "ancla_contexto"


def test_no_se_anade_nada_si_ya_hay_ficha_en_esas_fechas():
    ctx = "titulo las fiestas de tobarra 2026 se celebran del 14 al 21 de agosto"
    ya = [{"nombre": "Fiestas de San Roque", "fecha_inicio": "2026-08-14",
           "fecha_fin": "2026-08-21", "origen": "extraccion"}]
    assert recuperar_fiestas_desde_anclas(ya, ctx, loc("Tobarra"), PEDANIAS, 2026) == ya


@pytest.mark.parametrize("evidencia, esperado", [
    ("fiestas de tobarra en honor al santisimo cristo de la antigua y a la virgen",
     "Fiestas de Santisimo Cristo de la Antigua"),
    ("las fiestas en honor a la virgen de las vinas de aranda", "Fiestas de Virgen de las Vinas"),
    ("fiestas en honor a san bartolome sinovas", "Fiestas de San Bartolome Sinovas"),
])
def test_el_nombre_sale_de_la_advocacion(evidencia, esperado):
    assert _nombre_desde_evidencia(evidencia, loc("X")) == esperado


# ──────────────────────────────────────────────────────────────
# Fase 4 — plazos que no son fiestas
# ──────────────────────────────────────────────────────────────

def test_el_plazo_de_inscripcion_no_es_la_fiesta():
    """Los Mardos: once días con cero actos salieron de esta frase."""
    ctx = ("titulo fiestas de los mardos. aquellos que se animen a participar "
           "deberan inscribirse del 20 al 30 de julio en la casa de la cultura")
    assert anclas_de_fechas(ctx, loc("Los Mardos"), PEDANIAS, 2026) == []


def test_la_evidencia_llega_hasta_la_advocacion():
    """
    La prueba del anclaje se recorta, y de ella sale el nombre. Con 200
    caracteres la de Tobarra cortaba justo antes de "en honor al Santísimo
    Cristo de la Antigua" y la ficha salía como "Fiestas de Tobarra".
    """
    relleno = "bajada ofrenda floral y pasacalles con la banda municipal de musica " * 3
    ctx = ("titulo fiestas patronales de tobarra mayo 2026 " + relleno +
           " contenido las fiestas patronales de tobarra de mayo se celebran durante "
           "el 2.º, 3.º y 4.º domingo de mayo en honor al santisimo cristo de la antigua")
    a = anclas_de_fechas(ctx, loc("Tobarra"), PEDANIAS, 2026)[0]
    assert (a["inicio"], a["fin"]) == (date(2026, 5, 10), date(2026, 5, 24))
    assert _nombre_desde_evidencia(a["evidencia"], loc("Tobarra")) == \
        "Fiestas de Santisimo Cristo de la Antigua"


# ──────────────────────────────────────────────────────────────
# Fase 2 — bordes del calendario
# ──────────────────────────────────────────────────────────────

def test_el_nesimo_dia_de_la_semana_coincide_con_el_calendario():
    """Exhaustivo: cuatro años, los doce meses, los siete días, del 1.º al 5.º y el último."""
    import calendar
    from llm_processor.text_analyzer import _nesimo_dia_semana

    for anno in (2024, 2025, 2026, 2027):
        for mes in range(1, 13):
            for dsem in range(7):
                reales = [d for d in range(1, calendar.monthrange(anno, mes)[1] + 1)
                          if date(anno, mes, d).weekday() == dsem]
                for n in range(1, 6):
                    esperado = date(anno, mes, reales[n - 1]) if n <= len(reales) else None
                    assert _nesimo_dia_semana(anno, mes, dsem, n) == esperado
                assert _nesimo_dia_semana(anno, mes, dsem, -1) == date(anno, mes, reales[-1])


def test_no_se_inventa_un_dia_que_no_existe():
    """Febrero de 2026 no tiene quinto domingo."""
    assert fechas_relativas(_plano("el quinto domingo de febrero"), 2026) == ([], [])


def test_febrero_bisiesto():
    assert fechas_relativas(_plano("el último domingo de febrero"), 2024)[1] == [date(2024, 2, 25)]


@pytest.mark.parametrize("basura", ["", "   ", "domingo de", "el 99 domingo de mayo",
                                    "primer domingo de mesinexistente"])
def test_no_revienta_con_entradas_rotas(basura):
    assert fechas_relativas(_plano(basura), 2026) == ([], [])


# ──────────────────────────────────────────────────────────────
# Lo que las guardas descartan no vuelve por la ventana
# ──────────────────────────────────────────────────────────────

def test_el_rescate_no_resucita_lo_que_una_guarda_descarto():
    """
    Medido el 2026-08-23 en Cordovilla: la regla del patrón descartó unas
    "Fiestas Patronales de San Cosme y San Damián" del 5 al 14 de septiembre
    —su patrón es San Diego de Alcalá— y el rescate volvió a emitir ese mismo
    rango acto seguido.
    """
    ctx = ("titulo fiestas de cordovilla 2026 contenido las fiestas de cordovilla "
           "se celebran del 5 al 14 de septiembre de 2026")
    l = loc("Cordovilla", "02074000401")
    quedan = [{"nombre": "Fiestas de Santiago Apóstol", "fecha_inicio": "2026-07-23",
               "fecha_fin": "2026-07-25", "origen": "extraccion"}]
    descartada = [{"nombre": "Fiestas Patronales de San Cosme y San Damián",
                   "fecha_inicio": "2026-09-05", "fecha_fin": "2026-09-14",
                   "origen": "extraccion"}]

    sin_veto = recuperar_fiestas_desde_anclas(list(quedan), ctx, l, PEDANIAS, 2026)
    assert len(sin_veto) == 2, "el escenario ya no reproduce el fallo"

    con_veto = recuperar_fiestas_desde_anclas(
        list(quedan), ctx, l, PEDANIAS, 2026, None, descartada
    )
    assert len(con_veto) == 1


# ──────────────────────────────────────────────────────────────
# Pueblos homónimos
# ──────────────────────────────────────────────────────────────

def test_la_fuente_que_situa_la_fiesta_en_otro_pueblo_homonimo():
    """
    A Cordovilla (Tobarra, Albacete) se le asignó el programa de Cordovilla de la
    Cendea de Galar (Navarra): el documento nombraba "Cordovilla" y el filtro de
    documentos ajenos lo daba por bueno. La ficha traía dentro "lugar galar 31".
    """
    from llm_processor.text_analyzer import _evidencia_situa_la_fiesta_en_otro_sitio as ajeno

    galar = ("fiestas de cordovilla 2026 san cosme y san damian en galar fechas "
             "05 sep 14 sep 2026 lugar galar 31 precios gratis")
    assert ajeno(galar, loc("Cordovilla"), "Tobarra") is True
    # El mismo campo, apuntando a donde debe.
    assert ajeno("fiestas fechas 10 jul 13 jul lugar tertanga amurrio",
                 loc("Tertanga"), "Amurrio") is False
    # "lugar" en prosa no es el campo de un portal de eventos.
    assert ajeno("la romeria se celebra en el lugar de la ermita del santo",
                 loc("Cordovilla"), "Tobarra") is False


def test_el_ancla_no_toma_la_fecha_del_homonimo():
    ctx = ("titulo fiestas de cordovilla 2026 san cosme y san damian en galar "
           "fechas 05 sep 14 sep 2026 lugar galar 31 precios gratis")
    assert anclas_de_fechas(ctx, loc("Cordovilla"), PEDANIAS, 2026, "Tobarra") == []


@pytest.mark.parametrize("texto, nombre, es_cola", [
    # Sierra (Tobarra, Albacete) recibió el programa de Miraflores de la Sierra
    # (Madrid). En su propia provincia está además Elche de la Sierra.
    ("fiestas de miraflores de la sierra 2026", "sierra", True),
    ("programa fiestas elche de la sierra 2026", "sierra", True),
    # El artículo es lo que forma el topónimo; el "de" a secas introduce
    # cualquier cosa y no puede bastar.
    ("el ayuntamiento de aranda de duero convoca", "aranda de duero", False),
    ("la localidad de aranda de duero celebra", "aranda de duero", False),
    ("las fiestas de la aguilera 2026", "la aguilera", False),
    # Menciones legítimas: detrás va una palabra de fiesta, no otro topónimo.
    ("fiestas de sierra 2026 tobarra", "sierra", False),
    ("sierra se viste de fiesta del 30 de julio", "sierra", False),
    ("fiestas de tertanga 2026", "tertanga", False),
    ("fiestas patronales de delika", "delika", False),
    ("en lezama-lekamana amurrio", "lekamana", False),
])
def test_el_nombre_del_pueblo_como_cola_de_otro_toponimo(texto, nombre, es_cola):
    from llm_processor.text_analyzer import _mencion_es_cola_de_otro_toponimo
    assert _mencion_es_cola_de_otro_toponimo(texto, texto.index(nombre), nombre) is es_cola


def test_el_ancla_ignora_la_fiesta_del_toponimo_compuesto():
    ctx = "titulo fiestas de miraflores de la sierra 2026 del 13 al 18 de agosto"
    assert anclas_de_fechas(ctx, loc("Sierra"), PEDANIAS, 2026, "Tobarra") == []


# ──────────────────────────────────────────────────────────────
# Calidad del segmento del que sale la fecha
# ──────────────────────────────────────────────────────────────

def test_un_listado_de_actividades_no_es_el_anuncio_de_una_fiesta():
    """
    Los siete anclajes que coinciden con fechas verificadas en fuentes reales
    salen de segmentos con UN solo rango. El de Aranda traía cinco —"actividades
    de ocio alternativo para el 24 y 25 de octubre…"— y le robaba el puesto a la
    fecha buena por caer antes en el calendario.
    """
    listado = ("titulo actividades de aranda de duero contenido actividades de ocio "
               "para el 24 y 25 de octubre para el 17 y 18 de octubre del 21 al 27 de "
               "julio del 3 al 4 de octubre del 10 al 11 de octubre")
    assert anclas_de_fechas(listado, loc("Aranda de Duero"), PEDANIAS, 2026) == []


def test_el_anuncio_de_una_sola_fiesta_si_vale():
    anuncio = ("titulo fiestas patronales de aranda de duero contenido las fiestas "
               "patronales se celebraran del 11 al 20 de septiembre de 2026")
    a = anclas_de_fechas(anuncio, loc("Aranda de Duero"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 9, 11), date(2026, 9, 20))


def test_el_segmento_patronal_pesa_mas_que_uno_cualquiera():
    """A igualdad de respaldo debe ganar el que habla de fiestas patronales."""
    ctx = ("titulo agenda de aranda de duero contenido concierto del 21 al 27 de julio\n\n"
           "titulo fiestas de aranda de duero contenido las fiestas patronales se "
           "celebraran del 11 al 20 de septiembre")
    a = anclas_de_fechas(ctx, loc("Aranda de Duero"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 9, 11), date(2026, 9, 20))


def test_no_se_anade_una_fiesta_pegada_a_otra_que_ya_existe():
    """
    A La Aguilera se le añadió "del 5 al 12 de mayo" junto a la que ya tenía del
    13 al 17: el deduplicador vio después que compartían el 88% de los actos.
    Dos fiestas contiguas del mismo pueblo son la misma con fuentes discrepantes.
    """
    ctx = ("titulo fiestas patronales de la aguilera contenido las fiestas de la "
           "aguilera se celebran del 5 al 12 de mayo de 2026")
    ya = [{"nombre": "Fiestas Patronales de La Aguilera", "fecha_inicio": "2026-05-13",
           "fecha_fin": "2026-05-17", "origen": "extraccion"}]
    assert recuperar_fiestas_desde_anclas(
        list(ya), ctx, loc("La Aguilera"), PEDANIAS, 2026
    ) == ya


def test_una_fiesta_en_otra_epoca_del_año_si_se_anade():
    ctx = ("titulo fiestas patronales de tobarra mayo contenido las fiestas de "
           "tobarra se celebran del 10 al 24 de mayo de 2026")
    ya = [{"nombre": "Fiestas de San Roque", "fecha_inicio": "2026-08-14",
           "fecha_fin": "2026-08-21", "origen": "extraccion"}]
    assert len(recuperar_fiestas_desde_anclas(
        list(ya), ctx, loc("Tobarra"), PEDANIAS, 2026
    )) == 2

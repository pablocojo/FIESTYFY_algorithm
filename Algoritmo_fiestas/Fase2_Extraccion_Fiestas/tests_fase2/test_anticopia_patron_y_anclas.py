"""
Guardas nuevas del 2026-08-22, todas calibradas sobre el run real de Amurrio
del 2026-08-21 (13 fichas, de las que 3 eran la fiesta de la capital copiada).

Cada caso de aquí se corresponde con un fallo medido en ese run, no inventado.
"""

from datetime import date

import pytest

from llm_processor.text_analyzer import (
    anclas_de_fechas,
    descartar_descripciones_copiadas,
    descartar_duplicados_internos,
    descartar_por_patron_ajeno,
    descartar_por_sede_ajena,
    fecha_de_url,
    filtrar_chunks_por_dias_de_la_fiesta,
    recuperar_fiestas_desde_anclas,
    _hay_atribucion_explicita,
)
from llm_processor.patron_finder import _clave_toponimo, _wiki_es_de_la_localidad

MUNICIPIO = {"nombre": "Amurrio", "id": "01002000000"}
PEDANIAS = ["Aloria", "Artomaña", "Baranbio", "Delika", "Larrinbe",
            "Lekamaña", "Saratxo", "Tertanga", "Lezama"]


def loc(nombre, capital=False, lid="01002009901"):
    return {"nombre": nombre, "id": lid, "es_capital": capital}


def fiesta(nombre, ini, fin, **extra):
    f = {"id": "x", "lugar_id": "01002009901", "nombre": nombre,
         "fecha_inicio": ini, "fecha_fin": fin, "descripcion": "", "programa": []}
    f.update(extra)
    return f


# ──────────────────────────────────────────────────────────────
# Procedencia del patrón (patron_finder)
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre, slug, es_suyo", [
    # Fase 1 rellenó estas mal: la provincia y el pueblo vecino.
    ("Aloria", "Álava", False),
    ("Amurrio", "Álava", False),
    ("Tertanga", "Délica", False),
    # Grafía euskera vs castellana del mismo pueblo: sí son suyas.
    ("Artomaña", "Artómaña", True),
    ("Baranbio", "Barambio", True),
    ("Delika", "Délica", True),
    ("Larrinbe", "Larrimbe", True),
    ("Saratxo", "Saracho", True),
    ("Saratxo", "Saracho_(Álava)", True),
    # Nombres parecidos que NO son el mismo pueblo.
    ("Lezama", "Lekamaña", False),
    ("Elorrio", "Elorriaga", False),
    ("Berriz", "Berriatua", False),
])
def test_wikipedia_solo_se_acepta_si_el_articulo_es_del_pueblo(nombre, slug, es_suyo):
    url = f"https://es.wikipedia.org/wiki/{slug}"
    assert _wiki_es_de_la_localidad(url, nombre) is es_suyo


def test_sin_url_no_se_da_por_propia():
    assert _wiki_es_de_la_localidad("", "Lekamaña") is False


def test_clave_toponimo_iguala_grafias():
    assert _clave_toponimo("Saratxo") == _clave_toponimo("Saracho")
    assert _clave_toponimo("Delika") == _clave_toponimo("Délica")
    assert _clave_toponimo("Lezama (Álava)") == _clave_toponimo("Lezama")


# ──────────────────────────────────────────────────────────────
# Regla del patrón: los patrones no cambian
# ──────────────────────────────────────────────────────────────

SAN_JORGE = {"nombre": "San Jorge", "dia": 23, "mes": 4, "ambito": "localidad"}
SAN_ROQUE_HEREDADO = {"nombre": "San Roque", "dia": 16, "mes": 8, "ambito": "municipio"}


def test_patronal_fuera_del_dia_del_patron_se_descarta():
    """Artomaña: patrón San Jorge (23 abr), le colaron la patronal del 12-17 ago."""
    f = fiesta("Fiestas Patronales de Nuestra Señora y San Roke", "2026-08-12", "2026-08-17")
    assert descartar_por_patron_ajeno([f], SAN_JORGE, loc("Artomaña"), "", 2026) == []


def test_patronal_sobre_el_dia_del_patron_se_conserva():
    f = fiesta("Fiestas Patronales de San Jorge", "2026-04-17", "2026-04-23")
    assert descartar_por_patron_ajeno([f], SAN_JORGE, loc("Artomaña"), "", 2026) == [f]


def test_fiesta_no_patronal_no_la_toca_la_regla():
    """Un pueblo tiene un patrón pero celebra varias fiestas al año."""
    f = fiesta("Fiestas de Andra Mari Txiki", "2026-09-07", "2026-09-10")
    assert descartar_por_patron_ajeno([f], SAN_JORGE, loc("Baranbio"), "", 2026) == [f]


def test_patron_heredado_no_sirve_para_descartar_por_fecha():
    """
    El caso peligroso. Con el patrón heredado del municipio, la regla fuerte
    borraría las fiestas reales de TODAS las pedanías: en el run del 2026-08-21
    siete de nueve tenían 'San Roque' copiado del artículo de Amurrio.
    """
    real = fiesta("Fiestas Patronales de Santiago", "2026-07-24", "2026-07-26")
    ctx = "titulo larrinbe celebra sus fiestas en honor a santiago del 24 al 26 de julio"
    assert descartar_por_patron_ajeno([real], SAN_ROQUE_HEREDADO, loc("Larrinbe"), ctx, 2026) == [real]


def test_patron_heredado_sin_atribucion_explicita_se_descarta():
    f = fiesta("Fiestas Patronales de Nuestra Señora y San Roke", "2026-08-12", "2026-08-17")
    ctx = "el ayuntamiento de amurrio presenta la programacion de sus fiestas patronales"
    assert descartar_por_patron_ajeno([f], SAN_ROQUE_HEREDADO, loc("Lekamaña"), ctx, 2026) == []


def test_la_capital_conserva_su_patronal_con_patron_heredado():
    f = fiesta("Fiestas Patronales de Amurrio", "2026-08-12", "2026-08-17")
    capital = loc("Amurrio", capital=True)
    assert descartar_por_patron_ajeno([f], SAN_ROQUE_HEREDADO, capital, "", 2026) == [f]


def test_las_estimadas_quedan_al_margen():
    est = fiesta("Fiestas Patronales de San Roque (estimada)", "2026-08-16", "2026-08-16",
                 origen="santo_patron")
    assert descartar_por_patron_ajeno([est], SAN_JORGE, loc("Tertanga"), "", 2026) == [est]


def test_sin_patron_o_sin_fecha_no_se_descarta_nada():
    f = fiesta("Fiestas Patronales de X", "2026-08-12", "2026-08-17")
    assert descartar_por_patron_ajeno([f], None, loc("X"), "", 2026) == [f]
    sin_fecha = {"nombre": "Virgen de la Antigua", "dia": None, "mes": None, "ambito": "localidad"}
    assert descartar_por_patron_ajeno([f], sin_fecha, loc("X"), "", 2026) == [f]


def test_atribucion_explicita_exige_construccion_locativa():
    assert _hay_atribucion_explicita("las fiestas de delika del 26 al 28 de junio", loc("Delika"))
    assert _hay_atribucion_explicita("larrinbe amurrio celebra sus fiestas", loc("Larrinbe"))
    # Mención suelta del pueblo cerca de "fiestas": no basta.
    assert not _hay_atribucion_explicita(
        "fiestas patronales de amurrio. concejos del municipio: delika, tertanga", loc("Tertanga")
    )


# ──────────────────────────────────────────────────────────────
# Copias de la capital por sede y por descripción
# ──────────────────────────────────────────────────────────────

def test_sede_ajena_descarta():
    f = fiesta("Fiestas Patronales de Nuestra Señora y San Roke", "2026-08-12", "2026-08-17",
               sede_segun_el_texto="Amurrio")
    assert descartar_por_sede_ajena([f], loc("Artomaña"), MUNICIPIO, PEDANIAS) == []


def test_sede_ajena_respeta_la_fiesta_que_se_nombra_a_si_misma():
    """'Fiestas de Tertanga 2026 en Amurrio' hace que el modelo ponga sede=Amurrio."""
    f = fiesta("Fiestas de San Cristóbal en Tertanga", "2026-07-10", "2026-07-13",
               sede_segun_el_texto="Amurrio")
    assert descartar_por_sede_ajena([f], loc("Tertanga"), MUNICIPIO, PEDANIAS) == [f]


def test_sede_desconocida_no_descarta():
    f = fiesta("Fiestas de la ermita", "2026-07-10", "2026-07-13",
               sede_segun_el_texto="Ermita de San Roque")
    assert descartar_por_sede_ajena([f], loc("Tertanga"), MUNICIPIO, PEDANIAS) == [f]


CAPITAL = [fiesta("Fiestas Patronales de Amurrio (San Roque)", "2026-08-12", "2026-08-17",
                  descripcion="Programa de Fiestas con más de 100 actos en una semana, "
                              "incluyendo música, gastronomía y medidas de inclusión y seguridad.")]


def test_descripcion_calcada_y_fechas_solapadas_se_descarta():
    f = fiesta("Fiestas Patronales de Aloria", "2026-08-11", "2026-08-17",
               descripcion="Programa de fiestas con más de 100 actos en una semana, "
                           "alrededor de la Festividad de Nuestra Señora de la Asunción.")
    assert descartar_descripciones_copiadas([f], CAPITAL, loc("Aloria")) == []


def test_descripcion_parecida_pero_en_otras_fechas_se_conserva():
    """Sin el requisito de solape, la plantilla del ayuntamiento tumbaría fiestas buenas."""
    f = fiesta("Fiestas de San Nicolás", "2026-12-05", "2026-12-08",
               descripcion="Programa de fiestas con más de 100 actos en una semana.")
    assert descartar_descripciones_copiadas([f], CAPITAL, loc("Saratxo")) == [f]


def test_descripcion_propia_se_conserva():
    f = fiesta("Fiestas de San Cristóbal en Tertanga", "2026-08-12", "2026-08-15",
               descripcion="Chupinazo, misa mayor, bendición de vehículos y romería.")
    assert descartar_descripciones_copiadas([f], CAPITAL, loc("Tertanga")) == [f]


# ──────────────────────────────────────────────────────────────
# Duplicado dentro de la misma localidad
# ──────────────────────────────────────────────────────────────

def _con_actos(nombre, ini, fin, actos, **extra):
    return fiesta(nombre, ini, fin, programa=[
        {"dia": 1, "fecha": ini, "eventos": [{"hora": "", "descripcion": a} for a in actos]}
    ], **extra)


ACTOS = ["Chupinazo y cena popular", "Concierto Kesonikete", "Inicio del asado de ternera",
         "Duelo entre los pueblos de Arrastaria", "Chocolatada y campeonato de brisca"]


def test_duplicado_interno_conserva_la_que_no_pisa_a_la_capital():
    buena = _con_actos("Fiestas en honor a San Jorge", "2026-04-17", "2026-04-23", ACTOS)
    copia = _con_actos("Fiestas Patronales de Ntra Sra y San Roke", "2026-08-12", "2026-08-17", ACTOS)
    out = descartar_duplicados_internos([buena, copia], CAPITAL, loc("Artomaña"))
    assert [f["fecha_inicio"] for f in out] == ["2026-04-17"]


def test_duplicado_interno_sin_forma_de_decidir_conserva_las_dos():
    """Antes ganaba 'la del programa más largo', que es justo la contaminada."""
    a = _con_actos("Fiestas A", "2026-04-17", "2026-04-23", ACTOS)
    b = _con_actos("Fiestas B", "2026-06-01", "2026-06-05", ACTOS + ["Romería", "Verbena"])
    assert len(descartar_duplicados_internos([a, b], None, loc("Artomaña"))) == 2


def test_dos_fiestas_distintas_de_un_pueblo_no_se_tocan():
    a = _con_actos("Fiestas de San Nicolás", "2026-12-05", "2026-12-08",
                   ["Misa mayor y chocolatada", "Dantzas infantiles"])
    b = _con_actos("Fiestas de agosto", "2026-08-20", "2026-08-22",
                   ["Concurso de paellas", "Toro de fuego nocturno"])
    assert len(descartar_duplicados_internos([a, b], CAPITAL, loc("Saratxo"))) == 2


# ──────────────────────────────────────────────────────────────
# Anclaje de fechas y rescate
# ──────────────────────────────────────────────────────────────

def test_ancla_lee_la_fecha_de_la_frase_que_la_anuncia():
    ctx = "titulo programa fiestas de delika 2026 amurrio contenido las fiestas de delika 2026 se celebraran del 26 al 28 de junio"
    a = anclas_de_fechas(ctx, loc("Delika"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 6, 26), date(2026, 6, 28))


def test_ancla_no_confunde_el_municipio_con_una_rival():
    """'fiestas de Tertanga 2026 en Amurrio' es la forma normal de escribirlo."""
    ctx = "titulo las fiestas de tertanga 2026 en amurrio se celebraran del 10 al 13 de julio"
    a = anclas_de_fechas(ctx, loc("Tertanga"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 7, 10), date(2026, 7, 13))


def test_ancla_admite_el_nombre_compuesto_del_concejo():
    ctx = "titulo fiestas de san miguel 2026 en lezama-lekamana amurrio alava fechas 26 sep - 29 sep 2026"
    a = anclas_de_fechas(ctx, loc("Lekamaña"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 9, 26), date(2026, 9, 29))


def test_ancla_ignora_la_fecha_de_otro_pueblo():
    ctx = ("titulo fiestas de lezama del 28 de abril al 1 de mayo\n\n"
           "titulo fiestas de san juan degollado en aloria del 29 al 30 de agosto")
    a = anclas_de_fechas(ctx, loc("Aloria"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 8, 29), date(2026, 8, 30))


def test_ancla_une_rangos_que_comparten_inicio():
    """Una fuente dice 'el 24 y 25', otra 'del 24 al 26'. La fiesta es 24-26."""
    ctx = ("titulo fiestas de larrinbe 2026 se celebraran el 24 y 25 de julio\n\n"
           "titulo fiestas de larrinbe 2026 misa dantzas y romeria del 24 al 26 de julio")
    a = anclas_de_fechas(ctx, loc("Larrinbe"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 7, 24), date(2026, 7, 26))


def test_ancla_rechaza_rangos_de_temporada():
    ctx = "titulo fiestas de delika programa del 1 de junio al 30 de septiembre"
    assert anclas_de_fechas(ctx, loc("Delika"), PEDANIAS, 2026) == []


def test_rescate_solo_actua_si_no_queda_nada():
    ctx = "titulo las fiestas de delika 2026 se celebraran del 26 al 28 de junio"
    l = loc("Delika", lid="01002000601")

    rescatadas = recuperar_fiestas_desde_anclas([], ctx, l, PEDANIAS, 2026)
    assert len(rescatadas) == 1
    assert rescatadas[0]["fecha_inicio"] == "2026-06-26"
    assert rescatadas[0]["origen"] == "ancla_contexto"

    ya_hay = [fiesta("Fiestas de San Pedro", "2026-06-26", "2026-06-28", origen="extraccion")]
    assert recuperar_fiestas_desde_anclas(ya_hay, ctx, l, PEDANIAS, 2026) == ya_hay

    solo_estimada = [fiesta("X (estimada)", "2026-08-16", "2026-08-16", origen="santo_patron")]
    assert len(recuperar_fiestas_desde_anclas(solo_estimada, ctx, l, PEDANIAS, 2026)) == 2


def test_rescate_no_inventa_si_el_contexto_no_dice_fechas():
    ctx = "titulo delika es un concejo del municipio de amurrio con 124 habitantes"
    assert recuperar_fiestas_desde_anclas([], ctx, loc("Delika"), PEDANIAS, 2026) == []


# ──────────────────────────────────────────────────────────────
# Programa: páginas fechadas del enrichment
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, esperado", [
    ("https://udala.amurrio.eus/cas/calendario/eventosdiarios/2026/8/14/-", date(2026, 8, 14)),
    ("https://udala.amurrio.eus/cas/calendario/eventospormes/2026/8/-", None),
    ("https://udala.amurrio.eus/cas/servicios/fiestas", None),
    ("https://x.eus/2026/2/30/", None),   # 30 de febrero no existe
    ("", None),
])
def test_fecha_de_url(url, esperado):
    assert fecha_de_url(url) == esperado


def test_enrichment_se_queda_con_los_dias_de_la_fiesta():
    """
    Medido el 2026-08-21: entraban las páginas del 1, 8, 10, 11, 18, 22 y 23 de
    agosto y se caía la del 14, que es el Día de las Cuadrillas.
    """
    # Cada página con actos propios: si fueran todas iguales serían el menú del
    # calendario y las descartaría la guarda de cascarón (ver test_saneado_programa).
    pool = [{"url": f"https://u.eus/cas/calendario/eventosdiarios/2026/8/{d}/-",
             "chunk": f"Menu\nActo propio del dia {d}\n", "score": 0.5} for d in range(1, 32)]
    pool.append({"url": "https://u.eus/cas/servicios/fiestas", "chunk": "y", "score": 0.9})

    utiles, del_rango = filtrar_chunks_por_dias_de_la_fiesta(
        pool, date(2026, 8, 12), date(2026, 8, 17)
    )
    dias = sorted(fecha_de_url(c["url"]).day for c in del_rango)
    assert dias == [12, 13, 14, 15, 16, 17]
    # La página sin fecha en la URL se conserva; las de días ajenos, no.
    assert any(c["url"].endswith("servicios/fiestas") for c in utiles)
    assert len(utiles) == 7


def test_enrichment_sin_fechas_de_fiesta_no_filtra():
    pool = [{"url": "https://u.eus/2026/8/1/", "chunk": "x", "score": 0.5}]
    assert filtrar_chunks_por_dias_de_la_fiesta(pool, None, None) == (pool, [])


# ──────────────────────────────────────────────────────────────
# Afinado de fechas con el anclaje
# ──────────────────────────────────────────────────────────────

def _ajustar(f, ctx, nombre="Aloria"):
    from llm_processor.text_analyzer import ajustar_fechas_con_anclas
    return ajustar_fechas_con_anclas([f], ctx, loc(nombre), PEDANIAS, 2026)[0]


def test_ancla_afina_las_fechas_del_modelo():
    """
    El anclaje afina cuando no hay nada más fiable con que hacerlo.

    Aloria: el modelo dijo 28-30 de agosto y el texto dice 29-30, que es lo
    correcto. Con un santo reconocible en el nombre —San Juan Degollado, 29 de
    agosto— el rango del modelo ya lo cubre y desde el 2026-09-02 manda el
    modelo: el recorte por una frase costaba más de lo que daba (ver
    `test_el_ancla_no_recorta_un_rango_que_ya_cubre_al_patron`). Sin santo que
    reconocer, el anclaje sigue siendo la mejor evidencia disponible y corrige.
    """
    ctx = ("titulo fiestas de verano en aloria 2026 del 29 al 30 de agosto\n\n"
           "titulo fiestas de aloria 2026 se celebran del 29 al 30 de agosto")
    f = _ajustar(fiesta("Fiestas de Verano", "2026-08-28", "2026-08-30"), ctx)
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-29", "2026-08-30")


def test_el_programa_recorta_cuando_tiene_dias_de_sobra_para_decirlo():
    """
    El recorte por programa es lo que sustituye al afinado del anclaje, pero pide
    al menos tres días de programa: uno de dos no dice cuánto dura la fiesta.

    Con seis días de programa dentro de un rango de nueve, el rango sobra por los
    dos extremos y se recorta a lo que el programa cubre.
    """
    from llm_processor.text_analyzer import recortar_rango_al_programa
    f = recortar_rango_al_programa({
        "nombre": "Fiestas de San Juan Degollado",
        "fecha_inicio": "2026-08-25", "fecha_fin": "2026-09-02",
        "programa": [
            {"fecha": f"2026-08-{d}", "eventos": [{"hora": "20:00", "descripcion": f"Acto {d}"}]}
            for d in (27, 28, 29, 30, 31)
        ],
    })
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-27", "2026-08-31")


def test_el_caso_de_aloria_se_queda_con_un_dia_de_mas_a_proposito():
    """
    Aloria es el precio del freno, y conviene que esté escrito.

    El modelo dio 28-30 de agosto y el texto decía 29-30, que era lo correcto.
    Hasta el 2026-09-02 el anclaje hacía ese recorte; ahora no lo hace —esa misma
    excepción le costaba a San Roque de Tobarra cuatro días de fiesta y a
    La Aguilera uno—, y el programa tampoco lo rescata porque solo tiene dos días.

    Resultado: Aloria arrastra un día de más. No pierde ni un día real, que es lo
    que importa; y a cambio, en la ejecución del 2026-09-02, no recortar con
    programas de dos días devolvió a Sierra sus cuatro días, a Santiago de Mora
    cinco y a Aranda de Duero los ocho últimos de sus fiestas mayores.
    """
    from llm_processor.text_analyzer import recortar_rango_al_programa
    f = recortar_rango_al_programa({
        "nombre": "Fiestas de San Juan Degollado",
        "fecha_inicio": "2026-08-28", "fecha_fin": "2026-08-30",
        "programa": [
            {"fecha": "2026-08-29", "eventos": [{"hora": "12:00", "descripcion": "Misa"}]},
            {"fecha": "2026-08-30", "eventos": [{"hora": "20:00", "descripcion": "Verbena"}]},
        ],
    })
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-28", "2026-08-30")


def test_ancla_no_toca_fechas_que_no_solapan():
    """Un anclaje en otras fechas habla de otra fiesta: no se usa para corregir."""
    ctx = "titulo fiestas de aloria 2026 se celebran del 29 al 30 de agosto y son muy buenas"
    f = _ajustar(fiesta("Fiestas de invierno", "2026-01-10", "2026-01-12"), ctx)
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-01-10", "2026-01-12")


def test_ancla_flojo_no_corrige():
    """Amurrio tenía 'del 11 al 17' citado una vez y 'del 12 al 17' en todas partes."""
    ctx = "titulo fiestas de amurrio del 11 al 17 de agosto"
    f = _ajustar(fiesta("Fiestas Patronales", "2026-08-12", "2026-08-17"), ctx, "Amurrio")
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-12", "2026-08-17")


def test_ancla_no_reescribe_lo_que_ella_misma_rescato():
    ctx = "titulo las fiestas de delika 2026 se celebraran del 26 al 28 de junio"
    f = _ajustar(fiesta("Fiestas de Delika", "2026-06-26", "2026-06-28",
                        origen="ancla_contexto"), ctx, "Delika")
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-06-26", "2026-06-28")


def test_fecha_suelta_rescata_cuando_no_hay_ningun_rango():
    """
    Medido el 2026-08-22: en esa ejecución los buscadores no devolvieron el
    portal que publica el rango de Saratxo y de Lekamaña, y ambas se quedaron
    sin fiesta. El día sí estaba en el contexto, suelto.
    """
    ctx = ("titulo fiestas de saratxo saratxo pais vasco 6 de diciembre de 2026 "
           "duracion 1 dia tipo patronal tradicional religiosa")
    a = anclas_de_fechas(ctx, loc("Saratxo"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 12, 6), date(2026, 12, 6))


def test_el_rango_manda_sobre_la_fecha_suelta():
    """La suelta es solo respaldo: si hay rango, gana el rango."""
    ctx = ("titulo fiestas de saratxo del 5 al 8 de diciembre de 2026\n\n"
           "titulo fiestas de saratxo el 6 de diciembre de 2026")
    a = anclas_de_fechas(ctx, loc("Saratxo"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 12, 5), date(2026, 12, 8))


def test_la_fecha_suelta_sigue_exigiendo_atribucion():
    """Una fecha de otro pueblo no vale aunque no haya ningún rango propio."""
    ctx = "titulo fiestas de lezama el 28 de abril de 2026"
    assert anclas_de_fechas(ctx, loc("Saratxo"), PEDANIAS, 2026) == []


def test_el_patron_solo_da_nombre_si_su_dia_cae_en_la_fiesta():
    """
    Delika tiene por patrona a la Virgen de la Antigua, del valle de Arrastaria y
    sin fecha fija; sus fiestas de junio salieron como "Fiestas de Virgen de la
    Antigua", que no las llama así nadie.
    """
    ctx = "titulo las fiestas de delika 2026 se celebraran del 26 al 28 de junio"
    l = loc("Delika", lid="01002000601")

    sin_fecha = {"nombre": "Virgen de la Antigua", "dia": None, "mes": None}
    r = recuperar_fiestas_desde_anclas([], ctx, l, PEDANIAS, 2026, sin_fecha)
    assert r[0]["nombre"] == "Fiestas de Delika"

    fuera = {"nombre": "San Nicolás", "dia": 6, "mes": 12}
    r = recuperar_fiestas_desde_anclas([], ctx, l, PEDANIAS, 2026, fuera)
    assert r[0]["nombre"] == "Fiestas de Delika"

    dentro = {"nombre": "San Pedro", "dia": 27, "mes": 6}
    r = recuperar_fiestas_desde_anclas([], ctx, l, PEDANIAS, 2026, dentro)
    assert r[0]["nombre"] == "Fiestas de San Pedro"


# ──────────────────────────────────────────────────────────────
# Frenos al ajuste por anclaje (medidos en Tobarra y Aranda, 2026-08-22)
# ──────────────────────────────────────────────────────────────

def test_una_mencion_suelta_no_enmienda_al_modelo():
    """
    Peso 3 = una sola frase (2 por posesivo + 1 por el año). Con el umbral en 3,
    eso movió las fiestas de San Roque de Tobarra del 14-21 de agosto —la fecha
    real— al 9-17.
    """
    from llm_processor.text_analyzer import ajustar_fechas_con_anclas
    ctx = "titulo fiestas de tobarra 2026 del 9 al 17 de agosto"
    f = fiesta("Fiestas de San Roque", "2026-08-14", "2026-08-21", origen="extraccion")
    out = ajustar_fechas_con_anclas([f], ctx, loc("Tobarra"), ["Aljubé", "Sierra"], 2026)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-08-14", "2026-08-21")


def test_el_ancla_no_toca_un_rango_que_ya_cubre_al_patron():
    """
    El día del patrón es el ancla real de una patronal: si el rango del modelo ya
    lo contiene, es coherente y no lo mueve una frase del contexto.

    Dos casos reales. La Aguilera: el modelo dio 12-17 de mayo, que incluye el 13,
    día de San Pedro Regalado —murió allí—, y el anclaje lo movía a 5-12. Y
    Tobarra, al subir el techo de descarga: entraron más copias de "las fiestas
    patronales de verano se celebran del 9 al 17 de agosto en La Caseta" —que es
    la temporada de conciertos, no San Roque— y con ese respaldo el anclaje movió
    San Roque del 14-21, su fecha real, al 9-17.
    """
    from llm_processor.text_analyzer import ajustar_fechas_con_anclas
    ctx = ("titulo fiestas de la aguilera 2026 del 5 al 12 de mayo. las fiestas de la "
           "aguilera 2026 se celebran del 5 al 12 de mayo. programa fiestas de la "
           "aguilera del 5 al 12 de mayo 2026")
    patron = {"nombre": "San Pedro Regalado", "dia": 13, "mes": 5}
    f = fiesta("Fiestas Patronales de La Aguilera", "2026-05-12", "2026-05-17", origen="extraccion")
    out = ajustar_fechas_con_anclas([f], ctx, loc("La Aguilera"), ["Sinovas"], 2026, patron)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-05-12", "2026-05-17")

    # Tobarra: la temporada de La Caseta no puede mover a San Roque. Aquí el
    # patrón que trae Wikipedia es el Cristo de la Antigua, una advocación sin
    # fecha fija, así que el día hay que sacarlo del nombre de la fiesta.
    ctx_caseta = ("titulo fiestas patronales de tobarra de verano se celebran del 9 al 17 "
                  "de agosto en la caseta de tobarra. ") * 4
    cristo = {"nombre": "Cristo de la Antigua", "dia": None, "mes": None, "ambito": "localidad"}
    h = fiesta("Fiestas Patronales de San Roque", "2026-08-14", "2026-08-21", origen="extraccion")
    out = ajustar_fechas_con_anclas([h], ctx_caseta, loc("Tobarra"), ["Sierra"], 2026, cristo)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-08-14", "2026-08-21")

    # Y sin santo que reconocer en ninguno de los dos sitios, el anclaje corrige.
    i = fiesta("Fiestas de Verano", "2026-08-15", "2026-08-16", origen="extraccion")
    out = ajustar_fechas_con_anclas([i], ctx_caseta, loc("Tobarra"), ["Sierra"], 2026, cristo)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-08-09", "2026-08-17")

    # Sin patrón conocido no hay nada que proteger: el anclaje fuerte sí corrige.
    g = fiesta("Fiestas Patronales de La Aguilera", "2026-05-12", "2026-05-17", origen="extraccion")
    out = ajustar_fechas_con_anclas([g], ctx, loc("La Aguilera"), ["Sinovas"], 2026, None)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-05-05", "2026-05-12")


def test_el_ancla_si_corrige_cuando_el_modelo_deja_fuera_al_patron():
    """Ahí el rango del modelo es el sospechoso, y el contexto manda."""
    from llm_processor.text_analyzer import ajustar_fechas_con_anclas
    ctx = "titulo las fiestas de pueblo 2026 se celebraran del 10 al 20 de septiembre. " * 4
    patron = {"nombre": "San X", "dia": 18, "mes": 9}
    f = fiesta("Fiestas Patronales de Pueblo", "2026-09-11", "2026-09-13", origen="extraccion")
    out = ajustar_fechas_con_anclas([f], ctx, loc("Pueblo"), ["Otra"], 2026, patron)[0]
    assert (out["fecha_inicio"], out["fecha_fin"]) == ("2026-09-10", "2026-09-20")


# ──────────────────────────────────────────────────────────────
# Fase 4 — rangos que son un trámite, no una fiesta
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctx", [
    # El caso real de Los Mardos: once días sin un solo acto salieron de aquí.
    "titulo fiestas de los mardos. aquellos que se animen a participar deberan "
    "inscribirse del 20 al 30 de julio en la casa de la cultura",
    "titulo fiestas de los mardos. el plazo va del 20 al 30 de julio",
    "titulo fiestas de los mardos. presentacion de obras del 20 al 30 de julio",
    "titulo fiestas de los mardos. votacion del 20 al 30 de julio",
    # También en la variante de fecha suelta.
    "titulo fiestas de los mardos. inscripciones el 20 de julio",
])
def test_un_plazo_no_es_la_fecha_de_la_fiesta(ctx):
    assert anclas_de_fechas(ctx, loc("Los Mardos"), PEDANIAS, 2026) == []


def test_una_inscripcion_de_pasada_no_invalida_el_rango_de_la_fiesta():
    """
    Se mira alrededor del rango, no el segmento entero: un programa legítimo
    menciona inscripciones a concursos sin dejar de ser un programa.
    """
    ctx = ("titulo las fiestas de delika 2026 se celebran del 26 al 28 de junio. "
           "inscripciones para el concurso de tortilla en el ayuntamiento")
    a = anclas_de_fechas(ctx, loc("Delika"), PEDANIAS, 2026)
    assert (a[0]["inicio"], a[0]["fin"]) == (date(2026, 6, 26), date(2026, 6, 28))

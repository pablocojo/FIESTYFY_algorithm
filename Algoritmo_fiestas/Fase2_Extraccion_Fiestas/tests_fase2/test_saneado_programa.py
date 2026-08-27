"""
Limpieza de programas y de fuentes ajenas, del 2026-08-22.

Calibrado sobre la segunda ejecución real de Amurrio (la del 12:38), en la que
la duplicación de fichas ya estaba resuelta y lo que quedaba roto eran los
programas: actos reciclados de un día a otro, actos del cartel de la capital
dentro de las pedanías y, en Artomaña, el programa entero de Almansa (Albacete).
"""

import pytest

from fuentes import documento_es_ajeno_al_municipio
from llm_processor.patron_finder import recortar_coletilla_del_santo
from llm_processor.text_analyzer import (
    _acto_es_concreto,
    _nombre_desde_evidencia,
    limpiar_actos_compartidos_del_municipio,
    sanear_programa,
)

PEDANIAS = ["Aloria", "Artomaña", "Baranbio", "Delika", "Larrinbe",
            "Lekamaña", "Saratxo", "Tertanga"]


def dia(fecha, *actos):
    """actos: cadenas, o pares (hora, descripción)."""
    eventos = [{"hora": a[0], "descripcion": a[1]} if isinstance(a, tuple)
               else {"hora": "", "descripcion": a} for a in actos]
    return {"dia": 1, "fecha": fecha, "eventos": eventos}


def fiesta(nombre, lugar_id, *dias, **extra):
    f = {"id": nombre, "lugar_id": lugar_id, "nombre": nombre,
         "fecha_inicio": dias[0]["fecha"] if dias else "2026-01-01",
         "fecha_fin": dias[-1]["fecha"] if dias else "2026-01-01",
         "programa": list(dias)}
    f.update(extra)
    return f


def actos_de(f):
    return [e["descripcion"] for d in f["programa"] for e in d["eventos"]]


# ──────────────────────────────────────────────────────────────
# B1 — documentos de otro sitio de España
# ──────────────────────────────────────────────────────────────

def test_pdf_de_otra_provincia_es_ajeno():
    """El PDF de Almansa daba 10 de los 19 chunks del enrichment de Artomaña."""
    texto = ("Fiestas Mayores 2026. PROGRAMA DE FIESTAS. Ofrenda a la Virgen de Belen. "
             "Entrada cristiana, bando moro. Traje manchego.")
    assert documento_es_ajeno_al_municipio(
        texto, "https://almansaturistica.es/uploads/PROGRAMA-DE-FIESTAS-2026.pdf",
        "Artomaña", "Amurrio", PEDANIAS,
    ) is True


@pytest.mark.parametrize("texto, url", [
    # Nombra la localidad en el texto.
    ("Las fiestas de Tertanga 2026 se celebraran del 10 al 13 de julio", "https://euskalplan.eus/x"),
    # Nombra el municipio solo en la URL.
    ("Programa completo. 10:00 pasacalles. 23:00 verbena.", "https://udala.amurrio.eus/cartel.pdf"),
    # Nombra una hermana: es del municipio, lo filtran otras guardas.
    ("Fiestas de Delika del 26 al 28 de junio", "https://x.eus/y"),
])
def test_documento_del_municipio_no_es_ajeno(texto, url):
    assert documento_es_ajeno_al_municipio(
        texto, url, "Tertanga", "Amurrio", PEDANIAS
    ) is False


def test_la_provincia_sola_no_avala_un_documento():
    """
    Media España tiene una capital que se llama igual que su provincia. Aceptar
    por provincia le metía a Cordovilla 40.000 caracteres del registro de
    tratamientos del Ayuntamiento de Albacete y la Feria de Albacete entera.
    """
    assert documento_es_ajeno_al_municipio(
        "Registro de actividades de tratamiento del Ayuntamiento de Albacete",
        "https://albacete.es/repositorio/RAT_AYTO_ALBACETE.pdf",
        "Cordovilla", "Tobarra", ["Sierra", "Aljubé"],
    ) is True


# ──────────────────────────────────────────────────────────────
# B2 — actos reciclados de un día a otro
# ──────────────────────────────────────────────────────────────

def test_quita_el_programa_reciclado_dia_tras_dia():
    """Tertanga repetía los mismos 7 actos el 10, 11 y 12 de julio."""
    f = fiesta("San Cristóbal", "01002001201",
               dia("2026-07-10", "Bendición de vehículos", "Comida popular en el frontón"),
               dia("2026-07-11", "Bendición de vehículos", "Comida popular en el frontón"),
               dia("2026-07-12", "Bendición de vehículos", "Campeonato de mus"))
    sanear_programa(f, None, {"nombre": "Tertanga"})
    assert actos_de(f) == ["Bendición de vehículos", "Comida popular en el frontón",
                           "Campeonato de mus"]


def test_conserva_los_actos_genericos_que_si_son_diarios():
    f = fiesta("Fiestas", "01002000601",
               dia("2026-06-26", "Misa", "Romería", "Hinchables"),
               dia("2026-06-27", "Misa", "Romería", "Hinchables"))
    sanear_programa(f, None, {"nombre": "Delika"})
    assert len(actos_de(f)) == 6


def test_el_mismo_acto_a_dos_horas_son_dos_pases():
    """Lekamaña tenía el maratón de DJs a las 00:00 y a las 02:00. Son dos."""
    f = fiesta("San Miguel", "01002000801",
               dia("2026-09-27", ("00:00", "Maratón de DJs de Cuadrillas"),
                                 ("02:00", "Maratón de DJs de Cuadrillas")))
    sanear_programa(f, None, {"nombre": "Lekamaña"})
    assert len(actos_de(f)) == 2


def test_las_fechas_no_se_tocan_aunque_queden_dias_vacios():
    """
    Recortar el rango a los días con actos rompía fechas correctas: Aloria
    29-30 de agosto quedaba en 29-29 y Artomaña perdía el 23 de abril, que es
    justamente el día de San Jorge.
    """
    f = fiesta("San Juan Degollado", "01002000101",
               dia("2026-08-29", "Misa mayor y procesión solemne"),
               dia("2026-08-30", "Misa mayor y procesión solemne"))
    sanear_programa(f, None, {"nombre": "Aloria"})
    assert (f["fecha_inicio"], f["fecha_fin"]) == ("2026-08-29", "2026-08-30")
    assert len(f["programa"]) == 2


# ──────────────────────────────────────────────────────────────
# B3 — actos de la capital dentro de las pedanías
# ──────────────────────────────────────────────────────────────

CAPITAL = [fiesta("Patronales de Amurrio", "01002000201",
                  dia("2026-08-15", "Concierto: Benito Kamelas", "Bajada de Iguarrako"))]


def test_quita_los_actos_que_estan_en_el_programa_de_la_capital():
    f = fiesta("Fiestas de Larrinbe", "01002000701",
               dia("2026-07-24", "Concierto: Benito Kamelas", "Romería Otegi"))
    sanear_programa(f, CAPITAL, {"nombre": "Larrinbe"})
    assert actos_de(f) == ["Romería Otegi"]


def test_la_capital_conserva_sus_propios_actos():
    f = fiesta("Patronales de Amurrio", "01002000201",
               dia("2026-08-15", "Concierto: Benito Kamelas"))
    sanear_programa(f, CAPITAL, {"nombre": "Amurrio", "es_capital": True})
    assert actos_de(f) == ["Concierto: Benito Kamelas"]


def test_barrido_municipal_quita_lo_que_sale_en_dos_pueblos():
    """
    La comparación contra la capital falla cuando la capital se extrajo a medias:
    'Benito Kamelas' no estaba entre sus 25 actos y sobrevivía a la vez en
    Larrinbe (julio) y Lekamaña (septiembre).
    """
    larrinbe = fiesta("Larrinbe", "01002000701",
                      dia("2026-07-24", "Concierto: Benito Kamelas", "Romería Otegi"))
    lekamana = fiesta("Lekamaña", "01002000801",
                      dia("2026-09-26", "Concierto: Benito Kamelas", "Bajada del santo txiki"))
    amurrio = fiesta("Amurrio", "01002000201",
                     dia("2026-08-15", "Concierto: Benito Kamelas"))

    limpiar_actos_compartidos_del_municipio([larrinbe, lekamana, amurrio], "01002000201")

    assert actos_de(larrinbe) == ["Romería Otegi"]
    assert actos_de(lekamana) == ["Bajada del santo txiki"]
    assert actos_de(amurrio) == ["Concierto: Benito Kamelas"]   # en la capital se queda


def test_barrido_municipal_respeta_lo_generico():
    a = fiesta("A", "01002000701", dia("2026-07-24", "Misa", "Romería"))
    b = fiesta("B", "01002000801", dia("2026-09-26", "Misa", "Romería"))
    limpiar_actos_compartidos_del_municipio([a, b], "01002000201")
    assert actos_de(a) == ["Misa", "Romería"]
    assert actos_de(b) == ["Misa", "Romería"]


@pytest.mark.parametrize("desc, concreto", [
    ("Concierto: NØT", True),          # nombre propio tras dos puntos, aunque sea corto
    ("MARIACHI MEXICO LINDO «SÍ SEÑOR»", True),
    ("Maratón de DJs de Cuadrillas", True),
    ("Misa", False),
    ("Romería", False),
    ("Hinchables", False),
])
def test_acto_concreto_vs_generico(desc, concreto):
    assert _acto_es_concreto(desc) is concreto


# ──────────────────────────────────────────────────────────────
# C1 y C2 — nombres
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sucio, limpio", [
    # Coletillas de titular que devolvía la ruta de buscadores.
    ("San Jorge vuelven a incluir este", "San Jorge"),
    ("San Juan Degollado 2026 en Aloria", "San Juan Degollado"),
    ("Santiago 2026 en Larrinbe", "Santiago"),
    ("San Miguel 2026 en Lezama", "San Miguel"),
    ("San Cristóbal 2026 en Tertanga", "San Cristóbal"),
    ("San Antón en la ermita de dicho santo", "San Antón"),
    # El complemento SÍ es parte de la advocación: el santoral reconoce
    # "santísimo cristo" y recortar ahí dejaba a Tobarra con "Stmo. Cristo",
    # tirando lo único que distingue a su patrón de cualquier otro Cristo.
    ("Stmo. Cristo de la Antigua", "Stmo. Cristo de la Antigua"),
    ("Santísimo Cristo de la Antigua", "Santísimo Cristo de la Antigua"),
    # Nombres ya correctos: no se tocan.
    ("San Roque", "San Roque"),
    ("Virgen de la Antigua", "Virgen de la Antigua"),
    ("Nuestra Señora de la Asunción", "Nuestra Señora de la Asunción"),
])
def test_nombre_del_patron_se_queda_en_el_santo(sucio, limpio):
    assert recortar_coletilla_del_santo(sucio) == limpio


@pytest.mark.parametrize("evidencia, patron, esperado", [
    # Santo de una sola palabra: Larrinbe salía como "Fiestas de Larrinbe".
    ("titulo fiestas de santiago 2026 en larrinbe amurrio", None, "Fiestas de Santiago"),
    ("fiestas de san miguel 2026 en lezama-lekamana", None, "Fiestas de San Miguel"),
    # Sin santo en la frase, se usa el del patrón.
    ("titulo programa fiestas de delika 2026", {"nombre": "San Pedro"}, "Fiestas de San Pedro"),
    # Sin santo por ningún lado.
    ("titulo programa fiestas de delika 2026", None, "Fiestas de Delika"),
])
def test_nombre_de_la_fiesta_rescatada(evidencia, patron, esperado):
    assert _nombre_desde_evidencia(evidencia, {"nombre": "Delika"}, patron) == esperado


# ──────────────────────────────────────────────────────────────
# B4 — páginas de calendario que solo traen el menú
# ──────────────────────────────────────────────────────────────

from datetime import date

from llm_processor.text_analyzer import fecha_de_url, filtrar_chunks_por_dias_de_la_fiesta

MENU = "Calendario\nCAS\nEUS\nInicio\nElija una categoria\nMusika - Musica\n"


def _pagina(dia_mes, extra=""):
    return {"url": f"https://u.eus/cas/calendario/eventosdiarios/2026/8/{dia_mes}/-",
            "chunk": MENU + extra, "score": 0.5}


def test_paginas_de_calendario_sin_contenido_propio_se_descartan():
    """
    El calendario del ayuntamiento se sirve por JavaScript: la araña se trajo 31
    páginas `eventosdiarios` con las mismas diez líneas de menú y ningún acto.
    Ocupaban ~26.000 chars del presupuesto de enrichment.
    """
    pool = [_pagina(d) for d in range(1, 32)]
    pool.append(_pagina("16", "10:00 SUBIDA DEL SANTO\n11:30 MISA MAYOR\n"))
    pool.append({"url": "https://u.eus/cas/servicios/fiestas",
                 "chunk": "Programa completo de fiestas", "score": 0.9})

    utiles, garantizados = filtrar_chunks_por_dias_de_la_fiesta(
        pool, date(2026, 8, 12), date(2026, 8, 17)
    )
    # Solo sobrevive la página del 16 (la que trae actos) y la que no lleva fecha.
    assert [fecha_de_url(c["url"]) for c in garantizados] == [date(2026, 8, 16)]
    assert len(utiles) == 2


def test_con_pocas_paginas_fechadas_no_se_descarta_nada():
    """Sin varias páginas que comparar no hay forma de saber qué es menú."""
    pool = [_pagina("14"), {"url": "https://u.eus/x", "chunk": "otra cosa", "score": 0.5}]
    utiles, garantizados = filtrar_chunks_por_dias_de_la_fiesta(
        pool, date(2026, 8, 12), date(2026, 8, 17)
    )
    assert len(garantizados) == 1 and len(utiles) == 2


MENU_LARGO = "\n".join([
    "Calendario", "CAS", "EUS", "Inicio", "Elija una categoria",
    "Todas las categorias", "Musika - Musica", "Kirola - Deporte",
    "Anual", "Mensual", "Semanal", "Hoy", "Buscar",
    "Enero", "Febrero", "Marzo", "2024", "2025", "2026", "2027",
])


def test_la_pagina_de_dia_entra_recortada_al_menu():
    """
    Estas páginas son 55 líneas de menú y 2 de contenido. Entrar enteras metía
    5.000 caracteres de navegación al principio del contexto de enrichment, y el
    modelo devolvió como programa los seis titulares de día y nada más: 6 actos
    donde antes sacaba 25. Se quedan solo con lo suyo.
    """
    pool = [{"url": f"https://u.eus/cas/calendario/eventosdiarios/2026/8/{d}/-",
             "chunk": f"{MENU_LARGO}\n{d} DE AGOSTO - DIA {d}\n", "score": 0.5}
            for d in range(12, 18)]
    antes = sum(len(c["chunk"]) for c in pool)

    _, del_rango = filtrar_chunks_por_dias_de_la_fiesta(
        pool, date(2026, 8, 12), date(2026, 8, 17)
    )
    assert len(del_rango) == 6
    despues = sum(len(c["chunk"]) for c in del_rango)
    assert despues < antes / 5, "el menú sigue ocupando el contexto"
    # Y lo que queda es exactamente el titular de cada día.
    assert sorted(c["chunk"].strip() for c in del_rango) == sorted(
        f"{d} DE AGOSTO - DIA {d}" for d in range(12, 18)
    )
    # No se toca el original: los embeddings ya estaban calculados sobre él.
    assert pool[0]["chunk"].startswith("Calendario")


def test_la_pagina_que_es_solo_menu_se_descarta():
    pool = [{"url": f"https://u.eus/cas/calendario/eventosdiarios/2026/8/{d}/-",
             "chunk": MENU_LARGO, "score": 0.5} for d in range(12, 18)]
    _, del_rango = filtrar_chunks_por_dias_de_la_fiesta(
        pool, date(2026, 8, 12), date(2026, 8, 17)
    )
    assert del_rango == []


def test_lineas_de_reconoce_los_dos_simbolos_de_salto():
    from llm_processor.text_analyzer import _lineas_de
    assert _lineas_de("a\nb") == _lineas_de("a⏎b") == _lineas_de("a↵b") == {"a", "b"}


# ──────────────────────────────────────────────────────────────
# El enrichment de una pedanía solo usa lo que la nombra
# ──────────────────────────────────────────────────────────────

from llm_processor.text_analyzer import solo_chunks_de_la_localidad


def _chunk(geo, n=1):
    return [{"chunk": "x", "relevancia_geo": geo} for _ in range(n)]


def test_enrichment_de_pedania_descarta_los_chunks_que_no_la_nombran():
    """
    Medido el 2026-08-22: el contexto de enrichment de Baranbio era 5 de 8 chunks
    GENERAL (78% del texto) y su programa salió siendo el de Amurrio entero,
    con "AUTOBUSES A SAN ROQUE" y "ENTREGA DEL IGUARRAKO DE ORO" en unas fiestas
    de septiembre. Artomaña, con 10 de 10 DIRECTA, salió correcta.
    """
    items = _chunk("DIRECTA", 3) + _chunk("GENERAL", 5)
    out = solo_chunks_de_la_localidad(items, {"nombre": "Baranbio"}, ["Tertanga", "Delika"])
    assert len(out) == 3
    assert all(c["relevancia_geo"] == "DIRECTA" for c in out)


def test_la_capital_usa_todo_su_material():
    items = _chunk("DIRECTA", 3) + _chunk("GENERAL", 5)
    out = solo_chunks_de_la_localidad(
        items, {"nombre": "Amurrio", "es_capital": True}, ["Tertanga"]
    )
    assert len(out) == 8


def test_sin_hermanas_no_se_filtra():
    """Un municipio sin pedanías: no hay de quién copiar."""
    items = _chunk("DIRECTA", 2) + _chunk("GENERAL", 2)
    assert len(solo_chunks_de_la_localidad(items, {"nombre": "X"}, [])) == 4


def test_sin_chunks_propios_la_fiesta_se_queda_sin_programa():
    """Preferible a rellenarla con el cartel del pueblo grande."""
    items = _chunk("GENERAL", 4)
    assert solo_chunks_de_la_localidad(items, {"nombre": "Baranbio"}, ["Delika"]) == []


@pytest.mark.parametrize("desc", [
    "No hay eventos especificados para este día.",
    "No hay eventos específicos mencionados para este día",
    "Romería hacia la ermita (si existe)",
    "Actividades por determinar",
])
def test_las_lineas_de_relleno_del_modelo_no_son_actos(desc):
    f = fiesta("X", "01002000701", dia("2026-07-25", desc, "Campeonato de mus de la peña"))
    sanear_programa(f, None, {"nombre": "Larrinbe"})
    assert actos_de(f) == ["Campeonato de mus de la peña"]


@pytest.mark.parametrize("crudo, esperado", [
    # Los buscadores devuelven el patrón como lo escribiera la fuente.
    ("virgen del carmen", "Virgen del Carmen"),
    ("san juan degollado", "San Juan Degollado"),
    # Si ya trae mayúsculas, quien lo escribió sabía más: no se toca.
    ("San Roque", "San Roque"),
    ("Stmo. Cristo de la Antigua", "Stmo. Cristo de la Antigua"),
    ("", ""),
])
def test_capitalizacion_del_nombre_del_patron(crudo, esperado):
    from llm_processor.patron_finder import capitalizar_advocacion
    assert capitalizar_advocacion(crudo) == esperado

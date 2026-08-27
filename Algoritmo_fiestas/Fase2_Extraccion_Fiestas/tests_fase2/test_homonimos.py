"""
Pueblos homónimos, medido el 2026-08-24.

Cordovilla, pedanía de Tobarra (Albacete), salió con dos fichas falsas —una de
25 actos y confianza alta— construidas con el programa de Cordovilla Bajo, en la
Cendea de Galar (Navarra), a 600 km. El filtro por nombre no puede verlo: ese
documento dice «Cordovilla» tantas veces como el bueno.

Los casos de aquí son los documentos reales de esa ejecución, no inventados.
"""

import asyncio

import pytest

from fuentes import (
    documento_avalado_solo_por_la_localidad,
    lengua_cooficial_detectada,
    procedencia_contradice_al_lugar,
)

TOBARRA = ["Tobarra", "Aljubé", "Cordovilla", "Mora de Santa Quiteria",
           "Santiago de Mora", "Sierra", "Los Mardos"]


def hermanas(loc, municipio=TOBARRA):
    return [x for x in municipio if x != loc]


# ──────────────────────────────────────────────────────────────
# El disparador: a quién se le pregunta
# ──────────────────────────────────────────────────────────────

def test_un_documento_que_solo_dice_el_nombre_del_pueblo_es_sospechoso():
    texto = "Fiestas de Cordovilla. Programa del sábado 13 de junio. Cohete de inicio."
    assert documento_avalado_solo_por_la_localidad(
        texto, "https://cendeadegalar.es/eventos/fiestas-cordovilla-bajo/",
        "Cordovilla", "Tobarra", hermanas("Cordovilla"),
    )


def test_si_nombra_al_municipio_no_se_pregunta():
    """Está anclado a nuestro sitio; preguntar sería pagar una llamada por nada."""
    texto = "Cordovilla, pedanía de Tobarra, celebra sus fiestas de San Diego."
    assert not documento_avalado_solo_por_la_localidad(
        texto, "https://tobarra.es/fiestas/", "Cordovilla", "Tobarra", hermanas("Cordovilla"),
    )


def test_si_nombra_a_una_hermana_tampoco():
    texto = "Las pedanías de Cordovilla y Aljubé preparan sus fiestas de verano."
    assert not documento_avalado_solo_por_la_localidad(
        texto, "https://ejemplo.es/x", "Cordovilla", "Tobarra", hermanas("Cordovilla"),
    )


def test_un_documento_que_ni_nombra_al_pueblo_no_llega_aqui():
    """De eso ya se encarga el filtro de ajenos, que es gratis."""
    texto = "El Ayuntamiento de Almassora ultima los preparativos de sus fiestas."
    assert not documento_avalado_solo_por_la_localidad(
        texto, "https://almassora.es/x", "Cordovilla", "Tobarra", hermanas("Cordovilla"),
    )


def test_la_url_tambien_avala():
    assert not documento_avalado_solo_por_la_localidad(
        "Programa de fiestas 2026.", "https://www.tobarra.es/cordovilla/",
        "Cordovilla", "Tobarra", hermanas("Cordovilla"),
    )


# ──────────────────────────────────────────────────────────────
# La decisión: qué se hace con lo extraído
# ──────────────────────────────────────────────────────────────

def contra(proc, loc="Cordovilla", mun="Tobarra", prov="Albacete", idiomas=("es",)):
    return procedencia_contradice_al_lugar(
        proc, loc, mun, prov, hermanas(loc), list(idiomas),
    )


def test_el_caso_real_de_cordovilla_bajo():
    """La página HTML de cendeadegalar.es: dice de qué cendea es, y no es la nuestra."""
    assert contra({"municipio": "La Cendea de Galar", "provincia": None, "lengua": "castellano"})


def test_el_pdf_bilingue_lo_caza_la_lengua():
    """
    El complemento del caso anterior. Del PDF de Cordovilla Bajo el modelo extrae
    municipio "Cordovilla" —porque el PDF dice «Cordovilla Bajo»—, así que por
    municipio se salva; lo delata el euskera, que no es lengua de Albacete.
    """
    assert contra({"municipio": "Cordovilla", "provincia": None, "lengua_iso": "eu"})
    # Y también si la lengua viene con nombre en vez de código ISO.
    assert contra({"municipio": "Cordovilla", "provincia": None, "lengua": "euskera"})


def test_el_tercer_documento_lo_caza_la_provincia():
    """
    festivalesdeespana.com/festival/fiestas-de-cordovilla, el que se escapó en la
    primera versión. Dice «Cordovilla, concejo de la Cendea de Galar a las puertas
    de Pamplona», pero el modelo se quedaba con el nombre del propio pueblo como
    municipio. Al pedirle explícitamente el sitio MAYOR y aceptar pistas
    geográficas, contesta provincia "Navarra", y con eso basta.
    """
    assert contra({"municipio": "Cordovilla", "provincia": "Navarra"})


def test_en_alava_el_euskera_no_descarta_nada():
    """Lo contrario sería catastrófico: en Amurrio es la lengua propia."""
    assert not procedencia_contradice_al_lugar(
        {"municipio": None, "provincia": None, "lengua": "euskera"},
        "Larrinbe", "Amurrio", "Álava", ["Delika", "Baranbio"], ["es", "eu"],
    )


def test_una_provincia_distinta_descarta():
    assert contra({"municipio": "Cordovilla", "provincia": "Salamanca", "lengua": "castellano"})


def test_la_comunidad_no_contradice_a_su_provincia():
    """El modelo responde a veces con la comunidad; no es una contradicción."""
    assert not contra({"municipio": None, "provincia": "Castilla-La Mancha", "lengua": "castellano"})
    assert not procedencia_contradice_al_lugar(
        {"municipio": None, "provincia": "Castilla y León", "lengua": None},
        "Sinovas", "Aranda de Duero", "Burgos", ["La Aguilera"], ["es"],
    )


def test_sin_datos_no_se_descarta():
    """
    El sesgo es conservar. La mayoría de las webs locales no dicen en qué
    provincia están, y perder informacion buena es peor que colar algun error.
    """
    assert not contra({"municipio": None, "provincia": None, "lengua": None})
    assert not contra({})


def test_el_propio_pueblo_como_municipio_no_descarta():
    """orkestas.es contesta 'Cordovilla' al preguntar por el municipio."""
    assert not contra({"municipio": "Cordovilla", "provincia": "Albacete", "lengua": "castellano"})


def test_el_articulo_y_la_muletilla_no_cuentan():
    assert not contra({"municipio": "Ayuntamiento de Tobarra"})
    assert not procedencia_contradice_al_lugar(
        {"municipio": "La Aguilera"}, "La Aguilera", "Aranda de Duero", "Burgos", [], ["es"],
    )


def test_una_lengua_desconocida_no_descarta():
    """Solo descartan las cooficiales que sabemos mapear; lo demás, se conserva."""
    assert not contra({"municipio": None, "provincia": None, "lengua": "bable"})
    assert not contra({"municipio": None, "provincia": None, "lengua": "mixto"})


@pytest.mark.parametrize("municipio_dicho", [
    "Moralzarzal", "Becerril de la Sierra", "Hoyo de Manzanares",
    "Miraflores de la Sierra", "Elche de La Sierra", "Briviesca",
])
def test_los_homonimos_de_sierra(municipio_dicho):
    """
    Sierra es el caso peor: 27 de sus 90 documentos entran solo por el nombre, y
    22 hablaban de otro sitio. «Sierra» aparece en media España.
    """
    assert procedencia_contradice_al_lugar(
        {"municipio": municipio_dicho}, "Sierra", "Tobarra", "Albacete",
        hermanas("Sierra"), ["es"],
    )


# ──────────────────────────────────────────────────────────────
# El filtro completo
# ──────────────────────────────────────────────────────────────

def test_descartar_homonimos_solo_toca_a_los_sospechosos(monkeypatch):
    import llm_processor.text_analyzer as ta

    preguntados = []

    async def falso(texto):
        preguntados.append(texto[:30])
        return {"municipio": "La Cendea de Galar"}

    monkeypatch.setattr(ta, "procedencia_declarada", falso)

    docs = [
        {"fuente": "busqueda_web", "url": "https://cendeadegalar.es/x",
         "texto": "Fiestas de Cordovilla. Cohete de inicio."},
        {"fuente": "busqueda_web", "url": "https://tobarra.es/x",
         "texto": "Cordovilla, pedanía de Tobarra, celebra sus fiestas."},
        {"fuente": "web_municipio", "url": "https://tobarra.es/y",
         "texto": "Fiestas de Cordovilla 2026."},
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    ))

    assert len(preguntados) == 1, "solo se pregunta por el avalado únicamente por el nombre"
    urls = [d["url"] for d in salida]
    assert "https://cendeadegalar.es/x" not in urls
    assert "https://tobarra.es/x" in urls
    # La web oficial no se examina aunque no nombre al municipio en el texto.
    assert "https://tobarra.es/y" in urls


def test_si_la_comprobacion_falla_el_documento_se_queda(monkeypatch):
    """La red es la red; un fallo de la comprobación no puede costarnos un documento."""
    import llm_processor.text_analyzer as ta

    async def revienta(texto):
        raise RuntimeError("LM Studio caído")

    monkeypatch.setattr(ta, "procedencia_declarada", revienta)
    docs = [{"fuente": "busqueda_web", "url": "https://x.es",
             "texto": "Fiestas de Cordovilla. Cohete de inicio."}]
    assert asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    )) == docs


def test_sin_sospechosos_no_se_llama_al_modelo(monkeypatch):
    import llm_processor.text_analyzer as ta

    async def no_deberia(texto):
        raise AssertionError("no debería preguntarse por ningún documento")

    monkeypatch.setattr(ta, "procedencia_declarada", no_deberia)
    docs = [{"fuente": "busqueda_web", "url": "https://tobarra.es/x",
             "texto": "Cordovilla, pedanía de Tobarra."}]
    assert asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    )) == docs


# ──────────────────────────────────────────────────────────────
# Detección de lengua (en código, no con el modelo)
# ──────────────────────────────────────────────────────────────

def test_la_cabecera_bilingue_del_pdf_real():
    """
    Primeras líneas literales del PDF de Cordovilla Bajo. A qwen2.5-7b se le
    preguntó por la lengua y devolvió null; por eso esto no lo hace el modelo.
    """
    texto = "\n".join([
        "## Columna 1 de 2",
        "6202",
        "ORGANIZA: CONCEJO DE CORDOVILLA",
        "ANTOLATZAILEA: CORDOBILLAKO KONTZEJUA",
        "",
        "## Columna 2 de 2",
        "fiestas de cordovilla (bajo)",
        "cordobilla KO",
        "jaiak (BEHEKO)",
        "13 y 14 de junio",
    ])
    assert lengua_cooficial_detectada(texto) == "eu"


def test_un_programa_en_castellano_no_es_otra_lengua():
    texto = ("Fiestas de San Roque en Tobarra. Programa del sábado: pasacalles, "
             "parque infantil, comida popular y verbena con orquesta.")
    assert lengua_cooficial_detectada(texto) == ""


def test_una_palabra_suelta_no_basta():
    """Un programa en castellano puede citar «kalejira» como nombre del acto."""
    assert lengua_cooficial_detectada("A las 12:00 kalejira por las calles del pueblo.") == ""


def test_catalan_y_gallego():
    assert lengua_cooficial_detectada(
        "Festa major de dissabte i diumenge, amb correfoc i gegants."
    ) == "ca"
    assert lengua_cooficial_detectada(
        "O concello organiza as festas patronais o xoves e o venres, cunha romaria."
    ) == "gl"


def test_solo_mira_la_cabecera():
    """Una cita en otra lengua enterrada en un programa largo no lo cambia de idioma."""
    largo = "Programa de fiestas en castellano. " * 200
    assert lengua_cooficial_detectada(largo + "jaiak egitaraua antolatzailea kontzejua") == ""


# ──────────────────────────────────────────────────────────────
# El bloque de snippets
# ──────────────────────────────────────────────────────────────

def test_los_snippets_de_una_url_descartada_tambien_se_van(monkeypatch):
    """
    El agujero que dejó la primera versión, medido el 2026-08-25. Las dos páginas
    de la Cendea de Galar salían descartadas en el log y sus actos seguían
    llegando al modelo: el bloque de snippets es UN documento que acumula el
    resumen de todos los resultados, y el de esas mismas URLs viajaba dentro.
    Descartar la página y dejar su resumen es no descartar nada.
    """
    import llm_processor.text_analyzer as ta

    async def de_navarra(texto):
        return {"municipio": "Cendea de Galar"}

    monkeypatch.setattr(ta, "procedencia_declarada", de_navarra)

    snippets = "\n".join([
        "TITULO: Fiestas de Cordovilla Bajo | CONTENIDO: Actuacion de sevillanas con la "
        "Escuela Belen Hervas. | ORIGEN: https://cendeadegalar.es/eventos/x",
        "TITULO: Cordovilla se prepara | CONTENIDO: La pedania celebra San Diego. "
        "| ORIGEN: https://elfarodehellin.com/cordovilla",
    ])
    docs = [
        {"fuente": "busqueda_web", "url": "https://cendeadegalar.es/eventos/x",
         "texto": "Fiestas de Cordovilla. Cohete de inicio."},
        {"fuente": "busqueda_web", "url": "buscadores:snippets",
         "tipo": "snippets", "texto": snippets},
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    ))

    bloque = [d for d in salida if d.get("tipo") == "snippets"]
    assert bloque, "el bloque de snippets no debe desaparecer entero"
    texto = bloque[0]["texto"]
    assert "Belen Hervas" not in texto, "quedó el snippet de la URL descartada"
    assert "elfarodehellin" in texto, "se llevó por delante un snippet bueno"


def test_el_bloque_de_snippets_desaparece_si_se_queda_vacio(monkeypatch):
    import llm_processor.text_analyzer as ta

    async def de_navarra(texto):
        return {"municipio": "Cendea de Galar"}

    monkeypatch.setattr(ta, "procedencia_declarada", de_navarra)
    docs = [
        {"fuente": "busqueda_web", "url": "https://cendeadegalar.es/x",
         "texto": "Fiestas de Cordovilla. Cohete."},
        {"fuente": "busqueda_web", "url": "buscadores:snippets", "tipo": "snippets",
         "texto": "TITULO: x | CONTENIDO: y | ORIGEN: https://cendeadegalar.es/x"},
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    ))
    assert salida == []


def test_sin_descartes_el_bloque_no_se_toca(monkeypatch):
    import llm_processor.text_analyzer as ta

    async def limpio(texto):
        return {}

    monkeypatch.setattr(ta, "procedencia_declarada", limpio)
    snippets = "TITULO: a | CONTENIDO: b | ORIGEN: https://x.es"
    docs = [
        {"fuente": "busqueda_web", "url": "https://x.es", "texto": "Fiestas de Cordovilla."},
        {"fuente": "busqueda_web", "url": "buscadores:snippets", "tipo": "snippets",
         "texto": snippets},
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Cordovilla", "Tobarra", "Albacete", hermanas("Cordovilla"), ["es"],
    ))
    assert len(salida) == 2
    assert salida[1]["texto"] == snippets


# ──────────────────────────────────────────────────────────────
# La etiqueta de relevancia no puede mentir
# ──────────────────────────────────────────────────────────────

def _item(texto):
    return {"chunk": texto, "fuente": "web_municipio", "doc_relevancia": "DIRECTA",
            "score": 0.50, "url": "https://tobarra.sedipualba.es/cambiar_sede.aspx"}


def test_un_chunk_sin_nada_de_fiestas_no_hereda_directa():
    """
    Medido el 2026-08-25 en Sierra. Su contexto de enriquecimiento eran 6.073
    caracteres del desplegable «cambiar de sede» de un portal administrativo
    —la lista de todos los ayuntamientos de Albacete—, rotulado «fiabilidad MUY
    ALTA | Relevancia: DIRECTA» porque «Sierra» aparecía suelta en el documento
    padre. Con ese aval el modelo devolvió 39 actos inventados, confianza alta.
    """
    from llm_processor.text_analyzer import filtrar_chunks_por_localidad

    admin = ("AYUNTAMIENTO DE PETROLA AYUNTAMIENTO DE POVEDILLA AYUNTAMIENTO DE "
             "POZOHONDO AYUNTAMIENTO DE RIOPAR AYUNTAMIENTO DE YESTE "
             "CONSORCIO DE MEDIO AMBIENTE")
    salida = filtrar_chunks_por_localidad([_item(admin)], "Sierra", ["Tobarra", "Cordovilla"])
    assert salida, "no se descarta, solo se deja de promocionar"
    assert salida[0]["score"] < 0.50, "un desplegable administrativo no puede subir de score"


@pytest.mark.parametrize("texto", [
    # El contrapeso, y es el que de verdad importa: la herencia existe porque un
    # programa de actos no repite el nombre del pueblo en cada línea. La primera
    # versión de esta guarda preguntaba «¿habla de fiestas?» y degradaba el 61%
    # de los chunks de tobarra.es, incluido el primero de aquí, que salía en un
    # acto real que se perdió.
    "12:00 Cohete de inicio de fiestas. 14:30 Comida popular. 20:00 Verbena.",
    "HORARIO SANTUARIO ENCARNACION TOBARRA MISAS Todos los viernes a las 19:00",
    "En los ultimos anios las fiestas han dado un giro hacia la modernidad. "
    "Se instala una carpa en la Calle Eras con obras de teatro y conciertos.",
    "Del 14 al 21 de agosto se celebran las fiestas patronales.",
])
def test_lo_que_no_es_un_listado_conserva_su_relevancia(texto):
    from llm_processor.text_analyzer import filtrar_chunks_por_localidad

    salida = filtrar_chunks_por_localidad([_item(texto)], "Sierra", ["Tobarra", "Cordovilla"])
    assert salida[0]["score"] > 0.50, f"degradado sin motivo: {texto[:40]}"


# ──────────────────────────────────────────────────────────────
# Un sitio ajeno cae entero; un agregador, no
# ──────────────────────────────────────────────────────────────

def _doc(url, texto, fuente="busqueda_web"):
    return {"fuente": fuente, "url": url, "texto": texto}


def test_un_sitio_de_otro_pueblo_cae_entero(monkeypatch):
    """
    El caso de Sierra, 2026-08-26. De festisierra.com se descartó la revista
    —dice «Fregenal de la Sierra»— y se aceptó /programacion/, que no dice de
    dónde es. De esa segunda salieron 12 actos del Festival Internacional de la
    Sierra, en Badajoz, como fiestas de una pedanía de Albacete.
    """
    import llm_processor.text_analyzer as ta

    async def procedencia(texto):
        # Solo la revista confiesa dónde está; la programación calla.
        return {"municipio": "Fregenal de la Sierra"} if "Fregenal" in texto else {}

    monkeypatch.setattr(ta, "procedencia_declarada", procedencia)

    docs = [
        _doc("https://festisierra.com/revista.pdf",
             "Festival Internacional de la Sierra. Fregenal de la Sierra, Extremadura."),
        _doc("https://festisierra.com/programacion/",
             "Programacion. Fiestas de la Sierra. Pregon oficial y verbena."),
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Sierra", "Tobarra", "Albacete", hermanas("Sierra"), ["es"],
    ))
    assert salida == [], "la pagina callada del mismo dominio tambien debe caer"


def test_un_agregador_conserva_sus_paginas_buenas(monkeypatch):
    """
    El contrapeso, y el que impide el arreglo fácil. enaranda.es tiene 12 páginas
    de Aranda de 14: tirar el dominio entero habría costado los programas de La
    Aguilera, Sinovas y La Calabaza por arreglar uno malo.
    """
    import llm_processor.text_analyzer as ta

    async def procedencia(texto):
        return {"municipio": "Trucios-Turtzioz"} if "Trucios" in texto else {}

    monkeypatch.setattr(ta, "procedencia_declarada", procedencia)

    docs = [
        # Nombra a Sinovas —por eso se examina— pero es de otro pueblo.
        _doc("https://enaranda.es/evento/fiestas-trucios",
             "Fiestas de San Roque en Trucios-Turtzioz, Bizkaia. Ver tambien Sinovas."),
        _doc("https://enaranda.es/evento/fiestas-sinovas",
             "Fiestas de San Bartolome en Sinovas, Aranda de Duero. Programa de actos."),
        _doc("https://enaranda.es/evento/semana-cultural",
             "Semana cultural en Monte Costajan. Programa."),
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Sinovas", "Aranda de Duero", "Burgos", ["La Aguilera"], ["es"],
    ))
    urls = [d["url"] for d in salida]
    assert "https://enaranda.es/evento/fiestas-trucios" not in urls, "la mala sigue fuera"
    assert len(urls) == 2, f"se llevo por delante paginas buenas: {urls}"


def test_la_provincia_tambien_ancla_el_dominio(monkeypatch):
    """Basta con que UNA página nombre el municipio O la provincia."""
    import llm_processor.text_analyzer as ta

    async def procedencia(texto):
        return {"municipio": "Moralzarzal"} if "Moralzarzal" in texto else {}

    monkeypatch.setattr(ta, "procedencia_declarada", procedencia)

    docs = [
        _doc("https://prensa.es/moralzarzal",
             "Fiestas de la Sierra en Moralzarzal, Madrid."),
        _doc("https://prensa.es/otra", "Las fiestas de Sierra, en la provincia de Albacete."),
    ]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Sierra", "Tobarra", "Albacete", hermanas("Sierra"), ["es"],
    ))
    assert [d["url"] for d in salida] == ["https://prensa.es/otra"]


def test_sin_descartes_no_se_toca_ningun_dominio(monkeypatch):
    """La regla solo añade descartes, y necesita uno previo para dispararse."""
    import llm_processor.text_analyzer as ta

    async def procedencia(texto):
        return {}

    monkeypatch.setattr(ta, "procedencia_declarada", procedencia)
    docs = [_doc("https://x.es/a", "Fiestas de Sierra."), _doc("https://x.es/b", "Mas de Sierra.")]
    salida = asyncio.run(ta.descartar_homonimos(
        docs, "Sierra", "Tobarra", "Albacete", hermanas("Sierra"), ["es"],
    ))
    assert len(salida) == 2

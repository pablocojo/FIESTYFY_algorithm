"""
Los fallos del run Tobarra + Aranda de Duero del 2026-08-26 (16 fichas, de las
que 6 estaban bien).

Cada caso de aquí sale de ese log y de esa salida, con los datos tal cual los
produjo la ejecución. No hay ninguno inventado: si alguno vuelve a fallar, es
que ha vuelto el fallo de aquel día.
"""

import json
from datetime import date

import pytest

from senales_festivas import contar_actos_horarios
from llm_processor.text_analyzer import (
    _parse_json_llm,
    anclas_de_fechas,
    descartar_patronales_duplicadas,
    descartar_por_patron_ajeno,
    es_la_fiesta_del_patron,
    marcar_estado_del_programa,
    nombra_al_patron,
    _ficha_desde_ancla,
)
from llm_processor.patron_finder import integrar_patron


TOBARRA = {"nombre": "Tobarra", "id": "02074000601", "es_capital": True}
SIERRA = {"nombre": "Sierra", "id": "02074000501", "es_capital": False}
ARANDA = {"nombre": "Aranda de Duero", "id": "09018000201", "es_capital": True}
LOS_MARDOS = {"nombre": "Los Mardos", "id": "02074000701", "es_capital": False}

PATRON_TOBARRA = {"nombre": "Stmo. Cristo de la Antigua", "dia": 14, "mes": 9,
                  "fuente": "wikipedia", "ambito": "localidad"}
PATRON_SIERRA = {"nombre": "San Francisco", "dia": 4, "mes": 10,
                 "fuente": "llm", "ambito": "localidad"}


def fiesta(nombre, ini, fin, **extra):
    f = {"nombre": nombre, "fecha_inicio": ini, "fecha_fin": fin,
         "origen": "extraccion", "confianza": "media", "fuentes": ["busqueda_web"],
         "programa": []}
    f.update(extra)
    return f


# ──────────────────────────────────────────────────────────────
# El patrón no fija la fecha: las patronales se trasladan
# ──────────────────────────────────────────────────────────────

def test_patronal_trasladada_al_verano_no_se_descarta():
    """
    Tobarra celebra al Stmo. Cristo de la Antigua del 9 al 17 de agosto; el
    santoral lo pone el 14 de septiembre. La regla exigía la coincidencia y le
    tiró las dos fiestas buenas —la de agosto y la bajada de mayo—, dejando al
    pueblo con un rescate degradado de 4 actos.
    """
    fiestas = [
        fiesta("Fiestas Patronales de Tobarra Verano 2026", "2026-08-09", "2026-08-17"),
        fiesta("Fiestas Patronales de Tobarra Mayo 2026 - Bajada, Ofrenda Floral",
               "2026-05-02", "2026-05-04"),
    ]
    quedan = descartar_por_patron_ajeno(
        list(fiestas), PATRON_TOBARRA, TOBARRA, "contexto cualquiera", 2026,
    )
    assert len(quedan) == 2
    assert all(f.get("patron_trasladado") for f in quedan)


def test_patronal_que_nombra_al_patron_sobrevive_aunque_la_fecha_no_cuadre():
    """
    A Sierra le tiraron sus fiestas de San Francisco Javier (31 jul - 3 ago)
    porque su patrón cacheado era "San Francisco" el 4 de octubre —el modelo
    truncó el nombre al guardarlo—. La fiesta nombra a su propio patrón: no
    puede ser la copia de otro pueblo.
    """
    quedan = descartar_por_patron_ajeno(
        [fiesta("Fiestas Patronales de Sierra en honor a San Francisco Javier",
                "2026-07-31", "2026-08-03")],
        PATRON_SIERRA, SIERRA, "", 2026,
    )
    assert len(quedan) == 1


def test_patronal_de_otra_advocacion_sin_atribucion_sigue_cayendo():
    """
    Lo que la regla sí tiene que seguir cazando: la patronal de OTRO santo que
    ningún texto sitúa en este pueblo. Es como se cuela la fiesta de la capital.
    """
    quedan = descartar_por_patron_ajeno(
        [fiesta("Fiestas Patronales de San Cosme y San Damián", "2026-09-05", "2026-09-14")],
        {"nombre": "San Diego de Alcalá", "dia": 13, "mes": 11, "ambito": "localidad"},
        {"nombre": "Cordovilla", "id": "02074000201", "es_capital": False},
        "texto que no atribuye nada", 2026,
    )
    assert quedan == []


@pytest.mark.parametrize("nombre_fiesta, patron, esperado", [
    ("Fiestas Patronales de Sierra en honor a San Francisco Javier", "San Francisco", True),
    ("Fiestas de Stmo. Cristo de la Antigua", "Santísimo Cristo de la Antigua", True),
    ("Fiestas Patronales en honor a Nuestra Señora de las Viñas", "Virgen de las Viñas", True),
    ("Fiestas de la Virgen de las Viñas", "Virgen de las Viñas", True),
    ("Fiestas Patronales de Aranda de Duero", "Virgen de las Viñas", False),
    ("Fiestas Patronales de Tobarra Verano 2026", "Stmo. Cristo de la Antigua", False),
    ("Fiestas de San Roque", "Virgen del Carmen", False),
])
def test_nombra_al_patron(nombre_fiesta, patron, esperado):
    """Las fuentes truncan y alargan los nombres de los santos sin criterio."""
    assert nombra_al_patron(nombre_fiesta, {"nombre": patron}) is esperado


# ──────────────────────────────────────────────────────────────
# La estimación del patrón no puede duplicar lo ya extraído
# ──────────────────────────────────────────────────────────────

def test_no_se_estima_el_patron_si_su_fiesta_ya_esta_extraida():
    """
    Tobarra salió con su Cristo de la Antigua del 9 al 17 de agosto Y con un
    "Fiestas de Stmo. Cristo de la Antigua (estimada)" el 14 de septiembre. Es
    el mismo Cristo dos veces.
    """
    fiestas = [fiesta("Fiestas de Santisimo Cristo de la Antigua", "2026-08-09", "2026-08-17")]
    salida = integrar_patron(list(fiestas), PATRON_TOBARRA, 2026, TOBARRA)
    assert len(salida) == 1
    assert not any(f.get("origen") == "santo_patron" for f in salida)


def test_se_sigue_estimando_cuando_no_hay_nada_del_patron():
    """La estimación existe para el pueblo del que no se encontró nada."""
    salida = integrar_patron(
        [fiesta("Fiesta de la Cerveza Artesanal", "2026-06-20", "2026-06-20")],
        PATRON_TOBARRA, 2026, TOBARRA,
    )
    assert any(f.get("origen") == "santo_patron" for f in salida)


def test_es_la_fiesta_del_patron_por_el_dia():
    assert es_la_fiesta_del_patron(
        fiesta("Fiestas de agosto", "2026-09-10", "2026-09-16"),
        PATRON_TOBARRA, date(2026, 9, 14),
    )


# ──────────────────────────────────────────────────────────────
# Un pueblo tiene UNA patronal
# ──────────────────────────────────────────────────────────────

def test_dos_patronales_vacias_en_la_capital_se_deduplican():
    """
    Aranda de Duero salió con "Fiestas Patronales de Aranda de Duero" del 17 al
    31 de agosto (fechas inventadas) y con las de Nuestra Señora de las Viñas
    del 11 al 20 de septiembre, que son las de verdad. Ninguna traía un acto,
    así que el deduplicador por programas no podía verlas.
    """
    fiestas = [
        fiesta("Fiestas Patronales de Aranda de Duero", "2026-08-17", "2026-08-31"),
        fiesta("Fiestas Patronales en honor a Nuestra Señora de las Viñas",
               "2026-09-11", "2026-09-20"),
    ]
    quedan = descartar_patronales_duplicadas(
        fiestas, {"nombre": "Virgen de las Viñas", "ambito": "localidad"}, ARANDA, 2026,
    )
    assert len(quedan) == 1
    assert quedan[0]["nombre"].startswith("Fiestas Patronales en honor a Nuestra")


def test_la_patronal_trasladada_y_la_del_dia_del_santo_no_son_un_duplicado():
    """
    Muchos pueblos con el patrón en invierno mueven la fiesta grande al verano,
    cuando hay gente, y mantienen aparte la celebración del día del santo.
    Sierra es el caso: San Francisco Javier es el 3 de diciembre y sus
    patronales son de finales de julio. Sin esta salvedad, la de diciembre
    —mejor avalada por cubrir el día del santo— borraba la de verano, que es la
    de verdad.
    """
    verano = fiesta("Fiestas Patronales de Sierra en honor a San Francisco Javier",
                    "2026-07-31", "2026-08-03")
    del_santo = fiesta("Fiestas Patronales de San Francisco Javier",
                       "2026-11-28", "2026-12-06")
    quedan = descartar_patronales_duplicadas(
        [verano, del_santo],
        {"nombre": "San Francisco Javier", "dia": 3, "mes": 12, "ambito": "localidad"},
        SIERRA, 2026,
    )
    assert len(quedan) == 2
    assert verano["patron_trasladado"] is True
    assert not del_santo.get("patron_trasladado")


def test_sin_dia_de_patron_dos_patronales_siguen_siendo_un_duplicado():
    """
    La excepción se apoya en que UNA de las dos caiga en el día del santo. El
    duplicado de Aranda no tiene por dónde: su patrona no tiene fecha fija en el
    santoral, así que ninguna de las dos lo cubre y sigue sobrando una.
    """
    quedan = descartar_patronales_duplicadas(
        [fiesta("Fiestas Patronales de Aranda de Duero", "2026-08-17", "2026-08-31"),
         fiesta("Fiestas Patronales en honor a Nuestra Señora de las Viñas",
                "2026-09-11", "2026-09-20")],
        {"nombre": "Virgen de las Viñas", "dia": None, "mes": None, "ambito": "localidad"},
        ARANDA, 2026,
    )
    assert len(quedan) == 1
    assert quedan[0]["nombre"].startswith("Fiestas Patronales en honor a Nuestra")


def test_no_se_tocan_las_fiestas_que_no_son_patronales():
    """Un pueblo celebra varias veces al año; solo la patronal es única."""
    fiestas = [
        fiesta("Fiestas Patronales de Aranda de Duero", "2026-09-11", "2026-09-20"),
        fiesta("Fiesta de la Cerveza Artesanal", "2026-06-20", "2026-06-20"),
        fiesta("Fiestas de San Roque", "2026-08-14", "2026-08-16"),
    ]
    assert len(descartar_patronales_duplicadas(fiestas, None, ARANDA, 2026)) == 3


# ──────────────────────────────────────────────────────────────
# Un horario de apertura no es un programa de fiestas
# ──────────────────────────────────────────────────────────────

PAGINA_DEL_ECLIPSE = """ESPECIAL: eclipse total de sol del 12 de agosto de 2026
Allendeduero – Asociación Vecinal Allendeduero
: todos los días, de 10:00 a 13:00 y de 18:00 a 20:00 horas.
La Calabaza – Asociación Vecinal Barrio La Calabaza
: viernes, de 20:00 a 21:00 horas.
La Estación – Asociación Vecinal Barrio La Estación
: todos los días, de 17:00 a 19:00 horas.
Polígono Residencial – Asociación Vecinal Polígono Residencial
: de lunes a viernes, de 18:30 a 21:00 horas."""

PROGRAMA_DE_VERDAD = """Sábado 15 de agosto
12:00 Misa en honor a San Diego de Alcalá y procesión
17:00 Campeonato de fútbol amenizado por DJ Mármol Sound
22:00 Música en directo con el grupo Aó Kompás
00:30 Disco móvil con DJ Nino"""


def test_el_horario_de_reparto_de_gafas_no_cuenta_como_programa():
    """
    Ocho "actos con hora" salían de esta página, ganaba a todas las demás y era
    la elegida como programa de las fiestas patronales de Aranda de Duero.
    """
    assert contar_actos_horarios(PAGINA_DEL_ECLIPSE) < 3


def test_un_programa_de_verdad_sigue_contando():
    assert contar_actos_horarios(PROGRAMA_DE_VERDAD) >= 4


def test_una_verbena_con_tramo_horario_sigue_contando():
    """El tramo solo se descuenta si la línea no dice qué ocurre."""
    assert contar_actos_horarios("Verbena popular de 23:00 a 04:00 en la plaza") >= 1


# ──────────────────────────────────────────────────────────────
# Entre dos programas del mismo mes manda la advocación
# ──────────────────────────────────────────────────────────────

def _pagina(url, cuerpo):
    return f"--- [{url}] | Relevancia: DIRECTA ---\n{cuerpo}\n"


def test_gana_el_programa_de_esta_fiesta_aunque_tenga_menos_actos():
    """
    Para el Cristo de la Antigua de Tobarra (9-17 de agosto) se eligió una
    página de agregador sobre el SAN ROQUE de Tobarra, con 22 actos, habiendo
    en el mismo contexto el programa del Cristo con 11. El mes no separa dos
    fiestas del mismo pueblo en el mismo mes; la advocación sí.
    """
    from llm_processor.text_analyzer import mejor_pagina_con_programa

    contexto = (
        _pagina("https://agregador.example/tobarra-san-roque", "\n".join(
            f"1{h}:00 Acto de San Roque número {h} con orquesta" for h in range(10))) +
        _pagina("https://radiotobarra.example/cristo26.pdf", "\n".join(
            [f"1{h}:00 Acto del Cristo de la Antigua número {h} con verbena" for h in range(5)]
            + ["Programa del Santísimo Cristo de la Antigua, agosto"]))
    )
    url, n = mejor_pagina_con_programa(
        contexto,
        {"nombre": "Fiestas de Santísimo Cristo de la Antigua",
         "fecha_inicio": "2026-08-09", "fecha_fin": "2026-08-17"},
    )
    assert "cristo26" in url
    assert n >= 3


def test_sin_advocacion_en_el_nombre_sigue_mandando_el_recuento():
    from llm_processor.text_analyzer import mejor_pagina_con_programa

    contexto = (
        _pagina("https://a.example/pocos", "10:00 Pasacalles con charanga\n11:00 Misa mayor\n"
                                           "12:00 Concurso de paellas popular") +
        _pagina("https://b.example/muchos", "\n".join(
            f"1{h}:00 Acto número {h} con orquesta en la plaza" for h in range(8)))
    )
    url, n = mejor_pagina_con_programa(
        contexto, {"nombre": "Fiestas de Agosto", "fecha_inicio": "2026-08-01",
                   "fecha_fin": "2026-08-05"},
    )
    assert "muchos" in url


# ──────────────────────────────────────────────────────────────
# Segunda vuelta: lo que destapó el run del 2026-08-27
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre_fiesta, localidad, esperado", [
    # Con advocación propia: hay con qué distinguir.
    ("Fiestas de Santísimo Cristo de la Antigua", "Tobarra", {"antigua"}),
    ("Fiestas en honor a San Diego de Alcalá", "Cordovilla", {"diego", "alcala"}),
    ("Fiestas de San Bartolomé Sinovas 2026", "Sinovas", {"bartolome"}),
    # Sin ella: vacío, que significa "no se puede decidir por aquí".
    ("Fiestas Patronales de Tobarra Verano 2026", "Tobarra", set()),
    ("Fiestas de Aranda de Duero", "Aranda de Duero", set()),
    # El santo que además es el nombre del pueblo no distingue nada.
    ("Fiestas de Santiago en Santiago de Mora", "Santiago de Mora", set()),
])
def test_tokens_distintivos(nombre_fiesta, localidad, esperado):
    """
    La primera versión comparaba la frase entera —"tobarra mayo 2026 bajada
    ofrenda floral"— contra el texto de la página, no casaba nunca, y avisó de
    advocación ajena en cuatro fichas que estaban bien.
    """
    from llm_processor.text_analyzer import tokens_distintivos

    assert tokens_distintivos(nombre_fiesta, localidad) == esperado


ARMAZON_MONTE_COSTAJAN = (
    "titulo fiestas monte costajan 2026 fechas y guia fiestas de pueblos de espana "
    "cargando fiestas command palette search del 30 al 30 de agosto"
)
ARMAZON_SINOVAS = (
    "titulo fiestas de san bartolome sinovas 2026 informacion mas fiestas y ferias "
    "mas eventos en sinovas 20 ago - 25 ago premios albillo"
)
NOTICIA_SINOVAS = (
    "titulo sinovas se viste de fiesta diez dias para honrar a san bartolome con "
    "contenido el barrio de sinovas en aranda de duero acogera del 22 al 31 de "
    "agosto sus fiestas patronales"
)


def test_el_armazon_de_un_portal_de_eventos_no_da_fechas():
    """
    Monte Costaján —un monte— se llevó una fiesta entera de «fiestas monte
    costajan 2026 fechas y guia … cargando fiestas command palette search».
    """
    anclas = anclas_de_fechas(
        ARMAZON_MONTE_COSTAJAN, {"nombre": "Monte Costaján", "id": "09018000501"},
        ["Sinovas"], 2026,
    )
    assert anclas == []


FICHA_DE_EVENTO_LEGITIMA = (
    "titulo patronales de la aguilera 2026 san pedro regalado contenido fiestas "
    "patronales de la aguilera del 13 al 17 de mayo proponer una correccion "
    "anadir a mi calendario"
)


def test_los_botones_de_una_ficha_de_evento_no_la_invalidan():
    """
    "Proponer una corrección" y "añadir a calendario" son botones de las fichas
    de evento LEGÍTIMAS. Al meterlos en la lista de armazón se tiró el segmento
    bueno de La Aguilera —el que dice "del 13 al 17 de mayo"— y sus fiestas
    pasaron de cinco días con 17 actos a un solo día sin programa.
    """
    anclas = anclas_de_fechas(
        FICHA_DE_EVENTO_LEGITIMA, {"nombre": "La Aguilera", "id": "09018000101"},
        ["Aranda de Duero"], 2026,
    )
    assert anclas
    assert (anclas[0]["inicio"], anclas[0]["fin"]) == (date(2026, 5, 13), date(2026, 5, 17))


def test_el_bloque_de_mas_eventos_no_le_roba_las_fechas_a_la_fiesta():
    """
    A Sinovas le cambiaron sus fiestas del 22-31 de agosto por el «20 ago - 25
    ago» de un listado de eventos vecinos, y con las fechas malas el programa
    se pidió día a día sobre la ventana equivocada: 4 actos en vez de 37.
    """
    anclas = anclas_de_fechas(
        ARMAZON_SINOVAS + "\n\n" + NOTICIA_SINOVAS,
        {"nombre": "Sinovas", "id": "09018000301"}, ["Aranda de Duero"], 2026,
    )
    assert anclas
    assert (anclas[0]["inicio"], anclas[0]["fin"]) == (date(2026, 8, 22), date(2026, 8, 31))


def test_un_festival_con_nombre_propio_no_son_las_fiestas_del_pueblo():
    """
    Aranda de Duero salió con unas "Fiestas de Aranda de Duero" del 5 al 9 de
    agosto que eran, literalmente, el festival Sonorama Ribera.
    """
    from llm_processor.text_analyzer import ancla_es_de_otro_evento

    a = {"inicio": date(2026, 8, 5), "fin": date(2026, 8, 9), "peso": 3,
         "evidencia": "con motivo de la celebracion del festival sonorama ribera que "
                      "tendra lugar del 5 al 9 de agosto el ayuntamiento"}
    assert ancla_es_de_otro_evento(a, ARANDA, "Fiestas de Aranda de Duero")
    # Pero si el texto da un santo, la ficha se llama por él y sí es una fiesta.
    assert not ancla_es_de_otro_evento(a, ARANDA, "Fiestas de San Bartolomé")


# ──────────────────────────────────────────────────────────────
# La hora en una línea y el acto en la siguiente
# ──────────────────────────────────────────────────────────────

PROGRAMA_EN_DOS_LINEAS = """Fiestas en honor a San Francisco Javier
Miércoles, 3 de diciembre
11:30 h
• Tradicional chocolate con churros, disparo de cohetes y repique de campanas.
12:00 h
• Santa Misa en honor a San Francisco Javier.
14:30 h
• Comida popular: asado de patatas y pollo.
16:30 h
• Tarde de bingo y convivencia."""


def test_un_programa_maquetado_en_dos_lineas_cuenta():
    """
    El programa de Sierra estaba descargado en caché, con sus horas y sus actos,
    y contaba cero: el detector exigía que la hora y el acto fuesen en la misma
    línea. Sobre las 882 páginas de la caché, 98 ganaban actos al unirlas y 50
    pasaban de no llegar al umbral a superarlo.
    """
    assert contar_actos_horarios(PROGRAMA_EN_DOS_LINEAS) >= 4


def test_unir_hora_con_acto_es_idempotente():
    from senales_festivas import unir_hora_con_acto

    una = unir_hora_con_acto(PROGRAMA_EN_DOS_LINEAS)
    assert unir_hora_con_acto(una) == una


def test_la_hora_no_se_pega_a_la_cabecera_del_dia_siguiente():
    """Si no, la última hora de un día describiría el día siguiente."""
    from senales_festivas import unir_hora_con_acto

    unido = unir_hora_con_acto(
        "23:00 h\nVerbena con orquesta\n01:00 h\nSábado, 16 de agosto\n12:00 h\nMisa mayor"
    )
    assert "23:00 h Verbena con orquesta" in unido
    assert "01:00 h Sábado" not in unido


def test_el_troceador_entrega_la_hora_junto_a_su_acto():
    """El modelo tiene que leer lo mismo que cuenta el detector."""
    from llm_processor.text_analyzer import chunk_documento

    texto = "\n".join(chunk_documento(PROGRAMA_EN_DOS_LINEAS))
    assert "12:00 h Santa Misa en honor a San Francisco Javier." in texto


# ──────────────────────────────────────────────────────────────
# Páginas que llegan sin cuerpo
# ──────────────────────────────────────────────────────────────

PLANTILLA_DE_PRENSA = """<html><body>
<nav>Política Deportes Noticias Cultura Local Opinión</nav>
<div class="login">Registrarse. Bienvenido, ingrese a su cuenta.
tu nombre de usuario. tu contraseña. ¿Olvidaste tu contraseña?
Recuperación de contraseña. Recupera tu contraseña.</div>
<article><h1>Sierra presenta la programación completa</h1>
<p>12:00 h</p><p>Santa Misa en honor a San Francisco Javier</p>
<p>14:30 h</p><p>Comida popular: asado de patatas y pollo</p>
<p>16:30 h</p><p>Tarde de bingo y convivencia con la charanga</p>
<p>23:00 h</p><p>Verbena con orquesta en la plaza</p></article>
<div class="ultimas">Últimas noticias: el PSOE denuncia silencio.
Paco Núñez destaca en Hellín la apuesta por el deporte.</div>
</body></html>"""


def test_se_extrae_el_cuerpo_del_articulo_y_no_el_armazon():
    """
    Quitar nav, footer y aside no basta en las plantillas de prensa, que meten
    el menú, el formulario de acceso y las "últimas noticias" en div corrientes.
    La página con la programación de Sierra llegó al contexto como diez mil
    caracteres de menús y titulares de otros pueblos.
    """
    from bs4 import BeautifulSoup

    from scraper.google_search import _texto_del_html

    texto = _texto_del_html(BeautifulSoup(PLANTILLA_DE_PRENSA, "html.parser"))
    assert "Santa Misa" in texto
    assert "contraseña" not in texto
    assert "PSOE" not in texto
    assert contar_actos_horarios(texto) >= 4


def test_sin_cuerpo_aislable_se_devuelve_la_pagina_limpia():
    """Hay plantillas sin article ni main; ahí se sigue como antes."""
    from bs4 import BeautifulSoup

    from scraper.google_search import _texto_del_html

    texto = _texto_del_html(BeautifulSoup(
        "<html><body><div><p>21:00 Pasacalles con la charanga</p>"
        "<p>23:00 Verbena en la plaza mayor</p></div></body></html>", "html.parser"))
    assert "Pasacalles" in texto and "Verbena" in texto


def test_no_se_gastan_renders_de_navegador_en_redes_sociales():
    """
    Sin sesión, Instagram y Facebook no dan nada tampoco a un navegador. De las
    RRSS se ocupa el servidor de apps, que sí está identificado.
    """
    import asyncio

    from scraper import google_search as gs

    antes = gs._renders_hechos
    assert asyncio.run(gs._render_con_navegador("https://www.instagram.com/p/abc/")) is None
    assert gs._renders_hechos == antes, "no debe consumir presupuesto de render"


# ──────────────────────────────────────────────────────────────
# Tercera vuelta: lo que destapó el run en frío del 2026-08-27
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, texto, esperado", [
    # El año de la URL manda sobre el del texto.
    ("https://www.arandadeduero.es/wp-content/uploads/2025/09/PROGRAMA-FIESTAS.pdf", "", 2025),
    ("https://www.enaranda.es/evento/fiestas-san-bartolome-2024-sinovas-agosto-2024/", "", 2024),
    ("https://www.enaranda.es/evento/fiestas-de-san-bartolome-sinovas-agosto-2026/", "", 2026),
    # Sin año en la URL, vale que el texto nombre uno solo.
    ("https://www.radiotobarra.es/wp-content/uploads/Mora26.pdf", "programa de 2026", 2026),
    # Varios años en el texto y ninguno en la URL: no se puede decir.
    ("https://elfarodehellin.com/cordovilla-se-prepara/", "en 2024, 2025 y 2026", None),
])
def test_anno_del_documento(url, texto, esperado):
    """
    Sin esto, el pipeline rellenaba fichas con programas viejos y las daba por
    buenas: Aranda de Duero salió con 21 actos y confianza alta sacados del
    programa de 2025 del propio ayuntamiento, y Sinovas con 39 del de 2024.
    """
    from llm_processor.text_analyzer import anno_del_documento

    assert anno_del_documento(url, texto) == esperado


def test_entre_dos_programas_gana_el_del_ano_de_la_fiesta():
    """
    Sinovas tenía en el mismo contexto su programa de 2026 y el de 2024, y se
    llevaba el de 2024 por traer más actos con hora.
    """
    from llm_processor.text_analyzer import mejor_pagina_con_programa

    viejo = "\n".join(f"1{h}:00 Acto de San Bartolomé con orquesta" for h in range(9))
    nuevo = "\n".join(f"1{h}:00 Acto de San Bartolomé con verbena" for h in range(4))
    contexto = (
        _pagina("https://www.enaranda.es/evento/fiestas-san-bartolome-2024-sinovas-agosto-2024/", viejo)
        + _pagina("https://www.enaranda.es/evento/fiestas-de-san-bartolome-sinovas-agosto-2026/", nuevo)
    )
    url, n = mejor_pagina_con_programa(contexto, {
        "nombre": "Fiestas de San Bartolomé Sinovas 2026",
        "fecha_inicio": "2026-08-22", "fecha_fin": "2026-08-31",
        "sede_segun_el_texto": "Sinovas",
    })
    assert "2026" in url and "2024" not in url


def test_la_cabecera_avisa_de_que_el_documento_es_de_otro_ano():
    """
    El modelo no puede saber de cuándo es lo que lee. Aranda dató sus fiestas de
    2026 en un solo día porque el PDF que tenía delante era el de 2025.
    """
    from fuentes import generar_cabecera_chunk

    doc = {"fuente": "web_municipio", "url": "https://x/uploads/2025/09/PROGRAMA.pdf",
           "anno_documento": 2025, "anno_objetivo": 2026}
    cabecera = generar_cabecera_chunk(doc, "Aranda de Duero", "Aranda de Duero")
    assert "es de 2025, no de 2026" in cabecera
    assert cabecera.endswith("]")

    doc_actual = dict(doc, anno_documento=2026)
    assert "AVISO: este documento es de" not in generar_cabecera_chunk(
        doc_actual, "Aranda de Duero", "Aranda de Duero")


def test_dos_patronales_con_programa_propio_son_dos_celebraciones():
    """
    Tobarra hace la Bajada del Cristo en mayo y sus fiestas grandes en agosto, y
    ninguna cae el 14 de septiembre, que es el día del santo. El 2026-08-27 la
    deduplicación le borró la de mayo con 19 actos ya extraídos.
    """
    def con_actos(nombre, ini, fin, actos):
        return fiesta(nombre, ini, fin, programa=[{
            "dia": 1, "fecha": ini,
            "eventos": [{"hora": f"1{i}:00", "descripcion": f"{a} en la plaza mayor"}
                        for i, a in enumerate(actos)],
        }])

    mayo = con_actos("Fiestas Patronales de Mayo", "2026-05-02", "2026-05-04",
                     ["Bajada del Cristo", "Ofrenda floral", "Procesión solemne"])
    agosto = con_actos("Fiestas Patronales de Tobarra Verano 2026", "2026-08-09", "2026-08-17",
                       ["Pasacalles de charangas", "Verbena con orquesta", "Fuegos artificiales"])
    quedan = descartar_patronales_duplicadas([mayo, agosto], PATRON_TOBARRA, TOBARRA, 2026)
    assert len(quedan) == 2


def test_dos_patronales_vacias_siguen_siendo_un_duplicado():
    """La salvedad se apoya en que cada una traiga SU programa."""
    quedan = descartar_patronales_duplicadas(
        [fiesta("Fiestas Patronales de Aranda de Duero", "2026-08-17", "2026-08-31"),
         fiesta("Fiestas Patronales en honor a Nuestra Señora de las Viñas",
                "2026-09-11", "2026-09-20")],
        {"nombre": "Virgen de las Viñas", "dia": None, "mes": None, "ambito": "localidad"},
        ARANDA, 2026,
    )
    assert len(quedan) == 1


@pytest.mark.parametrize("nombre, dia_mes", [
    ("San Francisco Javier", (3, 12)),      # el de Sierra: se guardaba como 4 de octubre
    ("San Vicente Ferrer", (5, 4)),
    ("San Juan Bosco", (31, 1)),
    ("San José Obrero", (1, 5)),
    # Los que ya funcionaban, para que no se rompan al añadir los de arriba.
    ("San Francisco de Asís", (4, 10)),
    ("Stmo. Cristo de la Antigua", (14, 9)),
    ("San Pedro Regalado", (13, 5)),
])
def test_santos_compuestos_no_se_recortan_al_santo_equivocado(nombre, dia_mes):
    """
    «San Francisco Javier» es el 3 de diciembre y «San Francisco» el 4 de
    octubre: son cuatro meses de diferencia y otro santo. Con el nombre
    recortado, la regla del patrón descartó dos veces la fiesta buena de Sierra.
    """
    from llm_processor.patron_finder import buscar_en_santoral, recortar_coletilla_del_santo

    assert buscar_en_santoral(nombre) == dia_mes
    assert recortar_coletilla_del_santo(nombre) == nombre


def test_la_coletilla_de_titular_se_sigue_recortando():
    """Lo que motivó el recorte: nombres sacados de titulares."""
    from llm_processor.patron_finder import recortar_coletilla_del_santo

    assert recortar_coletilla_del_santo("Santiago 2026 en Larrinbe") == "Santiago"


# ──────────────────────────────────────────────────────────────
# El programa está dos puertas más allá de donde cae el buscador
# ──────────────────────────────────────────────────────────────

# Reproduce la estructura real de comarcamonastrell.com: Elementor mete el
# artículo dentro de un <footer>, y el enlace al documento va en un <li> que
# nombra la descarga pero no la fiesta —eso está en el titular—.
NOTICIA_QUE_ENLAZA = """<html><head>
<title>Programa fiestas San Roque Tobarra 2026 | Comarca Monastrell</title></head><body>
<nav>Inicio Local Deportes Cultura</nav>
<footer><div class="elementor">
<h1>Programa de fiestas de San Roque, Tobarra 2026</h1>
<p>Las fiestas se celebran del 14 al 21 de agosto en honor a San Roque.</p>
<h5>Cómo descargar el programa completo</h5>
<p>Para facilitar el acceso a la programación se ha habilitado un enlace directo:</p>
<ul><li><strong>Enlace de acceso:</strong> Puedes obtener el documento PDF en la
web oficial de <a href="https://www.radiotobarra.es/sanroque26/">Radio Tobarra.</a></li></ul>
</div></footer>
<div class="relacionadas"><a href="https://www.comarcamonastrell.com/hellin-programa-tandem-empleo/">Hellín acogerá el programa TándEM para el empleo joven</a></div>
</body></html>"""


def test_el_cuerpo_dentro_de_un_footer_no_se_tira():
    """
    comarcamonastrell.com está hecho con Elementor, que mete el artículo dentro
    de un <footer>. De sus 3.904 caracteres de texto, 3.678 estaban ahí, y nos
    quedábamos con 105: nueve páginas tituladas «programa de las fiestas de…»
    llevaban así desde el principio.
    """
    from bs4 import BeautifulSoup

    from scraper.google_search import _texto_del_html

    texto = _texto_del_html(BeautifulSoup(NOTICIA_QUE_ENLAZA, "html.parser"))
    assert "del 14 al 21 de agosto" in texto
    assert "Radio Tobarra" in texto


def test_se_sigue_el_enlace_que_promete_el_documento():
    """
    El programa casi nunca está donde cae el buscador: el periódico comarcal
    publica la noticia, la noticia enlaza a la emisora, y el PDF cuelga de la
    emisora.
    """
    from bs4 import BeautifulSoup

    from scraper.google_search import enlaces_al_programa

    enlaces = enlaces_al_programa(
        BeautifulSoup(NOTICIA_QUE_ENLAZA, "html.parser"),
        "https://www.comarcamonastrell.com/programa-fiestas-san-roque-tobarra-2026/", 3)
    assert enlaces == ["https://www.radiotobarra.es/sanroque26/"]


def test_no_se_sigue_la_noticia_de_al_lado():
    """
    Con el mismo dominio permitido se seguía «hellin-programa-tandem-empleo»
    —un titular con la palabra "programa"— en vez del enlace bueno. El documento
    está siempre en otra casa.
    """
    from bs4 import BeautifulSoup

    from scraper.google_search import enlaces_al_programa

    enlaces = enlaces_al_programa(
        BeautifulSoup(NOTICIA_QUE_ENLAZA, "html.parser"),
        "https://www.comarcamonastrell.com/programa-fiestas-san-roque-tobarra-2026/", 3)
    assert not any("tandem" in e for e in enlaces)


def test_una_pagina_que_no_va_de_fiestas_no_dispara_saltos():
    """El salto vale para cualquier localidad, no para cualquier página."""
    from bs4 import BeautifulSoup

    from scraper.google_search import enlaces_al_programa

    html = ("<html><head><title>Ordenanza fiscal 2026</title></head><body><p>"
            "Puedes obtener el documento PDF en la "
            "<a href='https://otro.example/sede/'>sede electrónica</a>.</p></body></html>")
    assert enlaces_al_programa(BeautifulSoup(html, "html.parser"),
                               "https://ayto.example/ordenanza-fiscal/", 3) == []


def test_no_se_salta_a_redes_sociales():
    from bs4 import BeautifulSoup

    from scraper.google_search import enlaces_al_programa

    html = ("<html><head><title>Programa de fiestas 2026</title></head><body><p>"
            "Descarga el programa completo en nuestro "
            "<a href='https://www.facebook.com/pueblo/'>Facebook</a>.</p></body></html>")
    assert enlaces_al_programa(BeautifulSoup(html, "html.parser"),
                               "https://ayto.example/fiestas/", 3) == []


# ──────────────────────────────────────────────────────────────
# Por qué el programa llegaba a medias aunque la fuente lo tuviera entero
# ──────────────────────────────────────────────────────────────

# El corte real del programa de Sinovas: cuatro fragmentos, y el del medio
# —el que más actos trae— no nombra al pueblo por ningún sitio.
FRAGMENTOS_DE_SINOVAS = [
    "Fiestas de San Bartolomé Sinovas 2026. Sinovas, Aranda de Duero.\n"
    "Sábado 22 de agosto\n12:00h Pasacalles por el barrio con la charanga.\n"
    "19:00h Pregón de fiestas.",
    "Domingo 23 de agosto\n12:00h Misa de la fiesta principal con autoridades.\n"
    "13:30h Gigantes y cabezudos con dulzaineros.\n"
    "Lunes 24 de agosto\n11:30h Misa en honor a nuestro patrón.\n"
    "22:30h Cine bajo las estrellas.\n"
    "Martes 25 de agosto\n16:00h Primera fase del campeonato de mus.",
    "Jueves 27 de agosto\n17:30h Torneo de fútbol-sala en Sinovas.\n"
    "18:00h Campeonato de rana femenino.",
    "Lunes 31 de agosto\n14:00h Paella popular en Sinovas.\n21:00h Traca final.",
]

HERMANAS_DE_SINOVAS = ["Aranda de Duero", "La Aguilera", "La Calabaza", "Monte Costaján"]


def test_el_cuerpo_del_programa_hereda_el_aval_de_su_pagina():
    """
    El interior de un programa no repite el nombre del pueblo: dice «12:00h Misa
    de la fiesta principal» y nada más. El 2026-08-27 ese fragmento de Sinovas
    —14 de sus 58 actos— salió GENERAL (−0,10) mientras sus hermanos salían
    DIRECTA (+0,15), perdió el puesto frente a los snippets de buscador y fue el
    único que no llegó al modelo.
    """
    from llm_processor.text_analyzer import filtrar_chunks_por_localidad

    items = [{"chunk": c, "url": "https://enaranda.es/evento/sinovas-2026/",
              "fuente": "busqueda_web", "score": 0.5} for c in FRAGMENTOS_DE_SINOVAS]
    salida = filtrar_chunks_por_localidad(items, "Sinovas", HERMANAS_DE_SINOVAS)

    assert len(salida) == 4
    assert all(i["relevancia_geo"] == "DIRECTA" for i in salida)
    assert salida[1]["relevancia_heredada"] is True
    # Y ya no arrastra penalización frente a sus hermanos.
    assert len({round(i["score"], 4) for i in salida}) == 1


def test_una_pagina_sin_aval_no_reparte_avales():
    """La herencia se apoya en que ALGÚN fragmento sitúe la página aquí."""
    from llm_processor.text_analyzer import filtrar_chunks_por_localidad

    items = [{"chunk": "12:00h Misa mayor.\n18:00h Encierro de reses.",
              "url": "https://otro.example/programa/", "fuente": "busqueda_web",
              "score": 0.5}]
    salida = filtrar_chunks_por_localidad(items, "Sinovas", HERMANAS_DE_SINOVAS)
    assert salida[0]["relevancia_geo"] == "GENERAL"
    assert not salida[0].get("relevancia_heredada")


def test_la_pagina_del_programa_entra_entera():
    """
    Si el código ha decidido que el programa está en una página, el modelo tiene
    que ver esa página entera. El 2026-08-27 el programa de Sinovas se partió en
    cuatro y el trozo de los días 23 al 26 —14 de sus 58 actos— fue el único que
    no llegó, porque es el único que no repite el nombre del pueblo.
    """
    from llm_processor.text_analyzer import (_contexto_con_las_paginas_enteras,
                                             pagina_entera)

    URL = "https://enaranda.es/evento/sinovas-2026/"
    indexados = [{"chunk": f"trozo {n} " + "x" * 200, "url": URL, "indice_chunk": n}
                 for n in range(4)]
    # Lo que había quedado en el contexto: la página a medias y ruido de fuera.
    quedaron = [indexados[0], indexados[2], indexados[3],
                {"chunk": "y" * 300, "url": "buscadores:snippets", "indice_chunk": 0}]

    assert [i["indice_chunk"] for i in pagina_entera(indexados, URL)] == [0, 1, 2, 3]

    seleccion, entran, hay = _contexto_con_las_paginas_enteras(
        quedaron, indexados, [URL])
    assert (entran, hay) == (4, 4)
    # La página va delante y en orden de lectura, sin repetirse.
    assert [i["indice_chunk"] for i in seleccion[:4]] == [0, 1, 2, 3]
    assert sum(1 for i in seleccion if i.get("url") == URL) == 4
    # Y lo de fuera sigue detrás.
    assert seleccion[-1]["url"] == "buscadores:snippets"


def test_entran_enteras_todas_las_paginas_que_elija_el_modelo():
    """
    El programa puede estar repartido: una fiesta larga se publica a veces en
    dos entradas, o el cartel va en un PDF y los horarios en la noticia.
    """
    from llm_processor.text_analyzer import _contexto_con_las_paginas_enteras

    A, B = "https://ayto.example/programa/", "https://radio.example/cartel.pdf"
    indexados = ([{"chunk": "a" * 200, "url": A, "indice_chunk": n} for n in range(3)]
                 + [{"chunk": "b" * 200, "url": B, "indice_chunk": n} for n in range(2)])
    seleccion, entran, hay = _contexto_con_las_paginas_enteras([], indexados, [A, B])
    assert (entran, hay) == (5, 5)
    # En el orden que dio el localizador: primero A entera, luego B entera.
    assert [i["url"] for i in seleccion] == [A, A, A, B, B]


def test_una_pagina_que_no_cabe_se_corta_por_el_final():
    """Truncada, no agujereada: el ensamblador marca el salto y el modelo lo sabe."""
    from llm_processor.text_analyzer import (ENRICHMENT_MAX_CHARS,
                                             _contexto_con_las_paginas_enteras)

    URL = "https://ayto.example/cartel.pdf"
    enorme = [{"chunk": "z" * (ENRICHMENT_MAX_CHARS // 3), "url": URL, "indice_chunk": n}
              for n in range(5)]
    seleccion, entran, hay = _contexto_con_las_paginas_enteras([], enorme, [URL])
    assert (entran, hay) == (3, 5)
    assert [i["indice_chunk"] for i in seleccion] == [0, 1, 2]


# ── El localizador guiado por el modelo ────────────────────────

CANDIDATAS_ARANDA = (
    "--- [https://www.enaranda.es/] | Relevancia: DIRECTA ---\n"
    "Próximos eventos en Aranda: 20:00 Fiesta de la Cerveza. 22:00 Fiesta de Peñas.\n"
    "19:00 Patronales. 12:00 Semana Cultural.\n"
    "--- [https://www.arandadeduero.es/festejos/] | Relevancia: DIRECTA ---\n"
    "Concejalía de Festejos. El programa completo de las Fiestas Patronales en\n"
    "honor a la Virgen de las Viñas puede consultarse en www.arandahoy.com/programa\n"
)


def test_el_localizador_puede_elegir_varias_y_pedir_seguir():
    """
    El código elige contando horas de reloj, y eso confunde un índice con un
    programa: la portada de enaranda.es salió elegida como programa de las
    patronales de Aranda porque lista eventos de media docena de fiestas, cada
    uno con su hora.
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    import llm_processor.text_analyzer as ta

    respuestas = [
        {"paginas_elegidas": ["https://www.arandadeduero.es/festejos/"],
         "informacion_suficiente": False,
         "urls_a_seguir": ["https://www.arandahoy.com/programa"],
         "razon": "La portada es un índice; la de festejos remite a arandahoy"},
        {"paginas_elegidas": ["https://www.arandahoy.com/programa"],
         "informacion_suficiente": True, "urls_a_seguir": [],
         "razon": "Trae el programa por días"},
    ]
    docs = [{"url": "https://www.arandahoy.com/programa", "fuente": "busqueda_web",
             "texto": "Programa\n11 sep\n20:00 Chupinazo\n21:00 Pregón\n23:00 Verbena"}]

    with patch.object(ta, "llm_chat_json", AsyncMock(side_effect=respuestas)), \
         patch("scraper.google_search.descargar_urls_bajo_demanda",
               AsyncMock(return_value=docs)):
        indexados: list[dict] = []
        urls, nuevos = asyncio.run(ta.localizar_programa_con_llm(
            CANDIDATAS_ARANDA,
            {"nombre": "Fiestas Patronales", "fecha_inicio": "2026-09-11",
             "fecha_fin": "2026-09-20"},
            ARANDA, {"nombre": "Aranda de Duero", "provincia": "Burgos"}, 2026,
            indexados,
        ))

    assert "https://www.arandahoy.com/programa" in urls
    assert nuevos and nuevos[0]["url"] == "https://www.arandahoy.com/programa"
    # Lo descargado queda indexado para que el enriquecimiento pueda usarlo.
    assert any(c["url"] == "https://www.arandahoy.com/programa" for c in indexados)


def test_el_localizador_para_cuando_dice_que_tiene_suficiente():
    """El tope de rondas existe para no entrar en bucle, no para agotarlo."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    import llm_processor.text_analyzer as ta

    respuesta = AsyncMock(return_value={
        "paginas_elegidas": ["https://www.arandadeduero.es/festejos/"],
        "informacion_suficiente": True, "urls_a_seguir": [], "razon": "Está entero"})
    with patch.object(ta, "llm_chat_json", respuesta):
        urls, nuevos = asyncio.run(ta.localizar_programa_con_llm(
            CANDIDATAS_ARANDA, {"nombre": "Fiestas Patronales",
                                "fecha_inicio": "2026-09-11", "fecha_fin": "2026-09-20"},
            ARANDA, {"nombre": "Aranda de Duero"}, 2026, []))

    assert urls == ["https://www.arandadeduero.es/festejos/"]
    assert nuevos == []
    assert respuesta.await_count == 1, "una sola ronda si dice que basta"


def test_el_localizador_nunca_pasa_del_tope_de_rondas():
    import asyncio
    from unittest.mock import AsyncMock, patch

    import llm_processor.text_analyzer as ta
    from config import PROGRAM_LOCATOR_MAX_ITERATIONS

    # Siempre pide seguir: si no hubiera tope, no pararía nunca.
    respuesta = AsyncMock(return_value={
        "paginas_elegidas": [], "informacion_suficiente": False,
        "urls_a_seguir": ["https://otro.example/mas"], "razon": "sigue"})
    docs = [{"url": "https://otro.example/mas", "fuente": "busqueda_web",
             "texto": "12:00 Misa\n20:00 Verbena\n23:00 Concierto"}]
    with patch.object(ta, "llm_chat_json", respuesta), \
         patch("scraper.google_search.descargar_urls_bajo_demanda",
               AsyncMock(return_value=docs)):
        asyncio.run(ta.localizar_programa_con_llm(
            CANDIDATAS_ARANDA, {"nombre": "F", "fecha_inicio": "2026-09-11",
                                "fecha_fin": "2026-09-20"},
            ARANDA, {"nombre": "Aranda de Duero"}, 2026, []))

    assert respuesta.await_count == PROGRAM_LOCATOR_MAX_ITERATIONS


def test_los_snippets_no_le_quitan_el_sitio_al_programa():
    """
    Son dos líneas por sitio y siempre nombran el pueblo, así que puntúan alto:
    de los 31 fragmentos del contexto de Sinovas, 18 eran snippets y solo 3 su
    programa. Sirven para descubrir la fiesta, no para escribir sus actos.
    """
    from llm_processor.text_analyzer import _ordenar_para_el_presupuesto

    snippets = [{"chunk": "x" * 100, "url": "buscadores:snippets", "score": 0.99}
                for _ in range(5)]
    programa = [{"chunk": "y" * 100, "url": "https://enaranda.es/sinovas/", "score": 0.40}]
    orden = _ordenar_para_el_presupuesto(snippets + programa, [])
    assert orden[0]["url"] == "https://enaranda.es/sinovas/"
    assert all(i["url"] == "buscadores:snippets" for i in orden[1:])


# ──────────────────────────────────────────────────────────────
# El informe no puede marcar como copia a la banda que viene de fuera
# ──────────────────────────────────────────────────────────────

def test_el_informe_no_marca_la_banda_forastera_como_contaminacion(capsys, tmp_path):
    """
    «Misa en honor a San Diego de Alcalá y procesión con la Agrupación Musical
    Santa Mujer Verónica de Tobarra» es un acto legítimo de Cordovilla: las
    bandas tocan por todo el municipio y se las nombra por su pueblo. El informe
    marcaba así el programa MEJOR extraído del run.
    """
    import ejecutar_neutros

    salida = tmp_path / "out.json"
    salida.write_text(json.dumps({"fiestas": [{
        "lugar_id": "02074000201", "nombre": "Fiestas de San Diego",
        "fecha_inicio": "2026-11-13", "fecha_fin": "2026-11-16",
        "origen": "extraccion", "confianza": "alta", "programa_estado": "completo",
        "programa": [{"dia": 1, "fecha": "2026-11-15", "eventos": [
            {"hora": "11:30", "descripcion": "Misa y procesión con la Agrupación "
                                             "Musical Santa Mujer Verónica de Tobarra"}]}],
    }], "localidades_completadas": ["02074000201"]}, ensure_ascii=False), encoding="utf-8")

    elegidos = [({"id": "02074000000", "nombre": "Tobarra"},
                 [{"id": "02074000201", "nombre": "Cordovilla"},
                  {"id": "02074000601", "nombre": "Tobarra", "es_capital": True}])]
    ejecutar_neutros.informe(str(salida), elegidos)
    assert "nombra a" not in capsys.readouterr().out


def test_el_informe_sigue_marcando_la_copia_de_verdad(capsys, tmp_path):
    import ejecutar_neutros

    salida = tmp_path / "out.json"
    salida.write_text(json.dumps({"fiestas": [{
        "lugar_id": "02074000201", "nombre": "Fiestas de San Diego",
        "fecha_inicio": "2026-11-13", "fecha_fin": "2026-11-16",
        "origen": "extraccion", "confianza": "alta", "programa_estado": "completo",
        "programa": [{"dia": 1, "fecha": "2026-11-15", "eventos": [
            {"hora": "11:30", "descripcion": "Gran desfile por las calles de Tobarra"}]}],
    }], "localidades_completadas": ["02074000201"]}, ensure_ascii=False), encoding="utf-8")

    elegidos = [({"id": "02074000000", "nombre": "Tobarra"},
                 [{"id": "02074000201", "nombre": "Cordovilla"},
                  {"id": "02074000601", "nombre": "Tobarra", "es_capital": True}])]
    ejecutar_neutros.informe(str(salida), elegidos)
    assert "nombra a" in capsys.readouterr().out


# ──────────────────────────────────────────────────────────────
# Sin actos no hay programa
# ──────────────────────────────────────────────────────────────

def test_sin_actos_no_queda_esqueleto_de_dias_vacios():
    """
    Aranda salió con quince días numerados y ninguno con nada dentro, mientras
    las demás fichas sin programa llevaban la lista vacía.
    """
    f = marcar_estado_del_programa(fiesta(
        "Fiestas Patronales de Aranda de Duero", "2026-08-17", "2026-08-31",
        programa=[{"dia": i + 1, "fecha": f"2026-08-{17 + i}", "eventos": []} for i in range(15)],
    ))
    assert f["programa_estado"] == "no_encontrado"
    assert f["programa"] == []


# ──────────────────────────────────────────────────────────────
# Anclas: ni de otro pueblo ni de otro año
# ──────────────────────────────────────────────────────────────

CONTEXTO_LOS_MARDOS = (
    "titulo fiestas - tobarra fiestas caseta 2018 adjuntos caseta 2018 programa de "
    "fiestas de san roque 2017 del 14 al 21 de agosto se celebra las fiestas en honor "
    "a san roque en los mardos en este archivo adjunto encontraras el programa"
)


def test_no_se_fabrica_una_fiesta_de_2026_con_un_cartel_de_2017():
    """
    A Los Mardos se le fabricó "Fiestas de San Roque" del 14 al 21 de agosto de
    2026 a partir de un texto que dice 2017 y 2018 y ningún 2026.
    """
    anclas = anclas_de_fechas(CONTEXTO_LOS_MARDOS, LOS_MARDOS, ["Tobarra"], 2026)
    assert anclas == []


def test_un_cartel_sin_año_sigue_valiendo():
    """
    Los carteles suelen decir solo "del 22 al 31 de agosto". Que no nombren el
    año no puede descalificarlos: así se rescató Sinovas.
    """
    ctx = ("titulo sinovas se viste de fiesta diez dias para honrar a san bartolome "
           "con contenido el barrio de sinovas acogera sus fiestas patronales del 22 "
           "al 31 de agosto")
    anclas = anclas_de_fechas(ctx, {"nombre": "Sinovas", "id": "09018000301"}, [], 2026)
    assert anclas and anclas[0]["inicio"] == date(2026, 8, 22)


def test_la_descripcion_de_un_ancla_es_legible():
    """
    Antes salía a la base de datos la evidencia en bruto, con los andamios del
    scraper y las palabras pegadas del HTML: «titulo sinovas se viste de fiesta
    … con contenido el barrio desinovas en a».
    """
    a = {"inicio": date(2026, 8, 22), "fin": date(2026, 8, 31), "peso": 3,
         "evidencia": "titulo sinovas se viste de fiesta con contenido el barrio desinovas en a"}
    f = _ficha_desde_ancla(a, {"id": "09018000301", "nombre": "Sinovas"},
                           {"nombre": "San Bartolomé", "dia": 24, "mes": 8, "ambito": "localidad"})
    assert "titulo" not in f["descripcion"]
    assert "contenido" not in f["descripcion"]
    assert "desinovas" not in f["descripcion"]
    assert "del 22 al 31 de agosto de 2026" in f["descripcion"]
    # La evidencia no se pierde: se guarda donde sirve para depurar.
    assert f["evidencia"].startswith("titulo sinovas")


# ──────────────────────────────────────────────────────────────
# Un JSON roto no puede llevarse el programa entero
# ──────────────────────────────────────────────────────────────

def test_se_recupera_el_programa_hasta_el_punto_del_error():
    """
    En la tercera de las tres llamadas del programa de Tobarra, un fallo en la
    línea 20 tiró los 663 tokens enteros y la ficha se quedó con 4 actos de los
    22 que traía su página.
    """
    roto = ('{"programa": ['
            '{"dia":1,"fecha":"2026-08-09","eventos":['
            '{"hora":"20:00","descripcion":"Pasacalles"},'
            '{"hora":"23:00","descripcion":"Verbena"}]},'
            '{"dia":2,"fecha":"2026-08-10","eventos":['
            '{"hora":"12:00","descripcion":"Misa"},'
            '{"hora":"18:00" "descripcion":"Toros"}]}]}')
    datos = _parse_json_llm(roto)
    assert datos is not None
    actos = [e["descripcion"] for d in datos["programa"] for e in d["eventos"]]
    assert actos == ["Pasacalles", "Verbena", "Misa"]


def test_se_recupera_una_respuesta_cortada_por_el_limite_de_tokens():
    cortado = ('{"programa": [{"dia":1,"fecha":"2026-08-09","eventos":['
               '{"hora":"20:00","descripcion":"Pasacalles"},'
               '{"hora":"23:00","descripcion":"Verbena"},'
               '{"hora":"01:00","descrip')
    datos = _parse_json_llm(cortado)
    assert datos and len(datos["programa"][0]["eventos"]) == 2


def test_un_json_bueno_se_sigue_leyendo_igual():
    assert _parse_json_llm('```json\n{"fiestas": [1, 2]}\n```') == {"fiestas": [1, 2]}


def test_basura_sin_json_devuelve_none():
    assert _parse_json_llm("no hay nada que parsear aquí") is None


# ──────────────────────────────────────────────────────────────
# Estado y cachés: un fichero truncado no puede borrar el trabajo
# ──────────────────────────────────────────────────────────────

def test_el_estado_se_recupera_del_bak_si_la_salida_esta_truncada(tmp_path):
    """
    El 2026-08-26 `rrss_contenido_cache.json` pasó de 16 KB a 0 y su .bak
    intacto se quedó al lado sin que nadie lo leyera; `fiestas_neutros.json`
    llevaba desde el 2026-08-20 apareciendo vacío al arrancar, así que ninguna
    ejecución reanudaba nada.

    Lo que se recupera es la penúltima versión, no la última: la copia se hace
    ANTES de escribir, para que el .bak sea siempre un fichero completo. Se
    pierde un volcado —una localidad—, no la ejecución entera, que es lo que se
    perdía antes.
    """
    from state_manager import StateManager, escribir_json_con_respaldo

    salida = tmp_path / "fiestas.json"
    escribir_json_con_respaldo(str(salida), {
        "version": 2, "anno": 2026, "municipios_completados": ["02074000000"],
        "localidades_completadas": ["02074000601"], "fiestas": [{"id": "x"}],
    })
    # Segunda escritura: deja .bak con la primera.
    escribir_json_con_respaldo(str(salida), {
        "version": 2, "anno": 2026, "municipios_completados": ["02074000000"],
        "localidades_completadas": ["02074000601", "02074000101"],
        "fiestas": [{"id": "x"}, {"id": "y"}],
    })
    salida.write_text("", encoding="utf-8")  # truncado a cero, como en drvfs

    estado = StateManager(str(salida)).cargar_estado()
    assert [f["id"] for f in estado["fiestas"]] == ["x"]
    assert estado["municipios_completados"] == ["02074000000"]
    assert estado["localidades_completadas"] == ["02074000601"]


def test_sin_bak_no_se_inventa_nada(tmp_path):
    from state_manager import StateManager

    salida = tmp_path / "fiestas.json"
    salida.write_text("", encoding="utf-8")
    estado = StateManager(str(salida)).cargar_estado()
    assert estado["fiestas"] == []
    assert estado["municipios_completados"] == []


# ──────────────────────────────────────────────────────────────
# El servidor RRSS no puede costar dos minutos por localidad
# ──────────────────────────────────────────────────────────────

def test_el_cliente_rrss_se_rinde_tras_dos_fases_abortadas():
    """
    Doce localidades, doce abortos de dos minutos cada uno: 24 de los 52 minutos
    del run esperando un foco de ventana que nunca volvió, y cero contenido.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from scraper.rrss_client import RRSSClient

    cliente = RRSSClient()
    cliente._disponible = True

    respuesta = MagicMock()
    respuesta.status = 200
    respuesta.json = AsyncMock(return_value={
        "runner": {"completadas": 0, "fallidas": 0, "abortado": True},
        "vlm": {"procesadas": 0}, "contenido": {},
    })
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=respuesta)
    ctx.__aexit__ = AsyncMock(return_value=False)
    sesion = MagicMock()
    sesion.post = MagicMock(return_value=ctx)
    sesion_ctx = MagicMock()
    sesion_ctx.__aenter__ = AsyncMock(return_value=sesion)
    sesion_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", MagicMock(return_value=sesion_ctx)):
        asyncio.run(cliente.procesar_rrss(["a"]))
        assert cliente.disponible, "un aborto suelto no descarta el servidor"
        asyncio.run(cliente.procesar_rrss(["b"]))

    assert not cliente.disponible
    assert sesion.post.call_count == 2

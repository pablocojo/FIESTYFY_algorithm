"""
El contexto se agrupa por página, no se baraja por puntuación.

Medido el 2026-08-25 sobre la ejecución de Tobarra: el programa de una fiesta
está en UNA página y seguido —de los 16 actos de Cordovilla, 15 salían de un
único documento, y era la ficha de más calidad de la ejecución—, pero llegaba al
modelo despedazado. San Roque: 22 chunks de 8 páginas con 16 saltos entre ellas.

Con consecuencias visibles: la ficha de San Antón, de enero, llevaba «Concierto
en Plaza de España. Orquesta Señor Aliaga», que está en el programa del Cristo
de la Antigua, de mayo. Acto real, fiesta equivocada.
"""

from llm_processor.text_analyzer import ensamblar_contexto


def chunk(url, indice, texto, score, fuente="web_municipio"):
    return {"fuente": fuente, "es_calendario": False, "url": url,
            "chunk": texto, "indice_chunk": indice, "score": score}


def test_los_chunks_de_una_pagina_van_juntos_y_en_orden():
    """Por puntuación el orden sería A0, B5, A1: la página buena, partida en dos."""
    salida = ensamblar_contexto([
        chunk("https://a.es/prog", 0, "PROGRAMA dia 1", 0.9),
        chunk("https://b.es/otra", 5, "OTRA COSA", 0.8),
        chunk("https://a.es/prog", 1, "PROGRAMA dia 2", 0.7),
    ])
    assert salida.index("PROGRAMA dia 1") < salida.index("PROGRAMA dia 2") < salida.index("OTRA COSA")
    # Un solo rótulo por página, no uno por chunk.
    assert salida.count("[https://a.es/prog]") == 1


def test_un_hueco_entre_chunks_se_marca():
    """Pegar el chunk 1 con el 4 insinuaría una continuidad que no existe."""
    salida = ensamblar_contexto([
        chunk("https://a.es", 0, "PRIMERO", 0.9),
        chunk("https://a.es", 4, "CUARTO", 0.8),
    ])
    assert "[…]" in salida
    assert salida.index("PRIMERO") < salida.index("[…]") < salida.index("CUARTO")


def test_sin_huecos_no_se_marca_nada():
    salida = ensamblar_contexto([
        chunk("https://a.es", 0, "PRIMERO", 0.9),
        chunk("https://a.es", 1, "SEGUNDO", 0.8),
    ])
    assert "[…]" not in salida


def test_la_pagina_con_el_mejor_chunk_va_primero():
    """La selección la sigue haciendo la puntuación; solo cambia la presentación."""
    salida = ensamblar_contexto([
        chunk("https://floja.es", 0, "FLOJA", 0.40),
        chunk("https://buena.es", 9, "BUENA", 0.95),
    ])
    assert salida.index("BUENA") < salida.index("FLOJA")


def test_las_fuentes_siguen_ordenadas_por_fiabilidad():
    """La jerarquía de fuentes manda por encima de la agrupación por página."""
    salida = ensamblar_contexto([
        chunk("https://buscador.es", 0, "DE BUSCADOR", 0.99, fuente="busqueda_web"),
        chunk("https://oficial.es", 0, "OFICIAL", 0.10),
    ])
    assert salida.index("OFICIAL") < salida.index("DE BUSCADOR")


def test_los_snippets_no_llevan_rotulo_de_pagina():
    """Su url es ficticia; rotularla como página confundiría."""
    salida = ensamblar_contexto([
        chunk("buscadores:snippets", 0, "TITULO: x | CONTENIDO: y", 0.5, fuente="busqueda_web"),
    ])
    assert "buscadores:snippets" not in salida


def test_un_chunk_sin_indice_no_revienta():
    """Los items viejos o de otras rutas pueden no traer indice_chunk."""
    salida = ensamblar_contexto([
        {"fuente": "web_municipio", "es_calendario": False, "url": "https://a.es",
         "chunk": "SIN INDICE", "score": 0.5},
    ])
    assert "SIN INDICE" in salida


# ──────────────────────────────────────────────────────────────
# ¿Hay material para pedir un programa?
# ──────────────────────────────────────────────────────────────

from llm_processor.text_analyzer import (
    hay_material_para_un_programa,
    mejor_pagina_con_programa,
)


def contexto(*paginas):
    partes = ["===== FUENTE: WEB OFICIAL DEL MUNICIPIO (fiabilidad MUY ALTA) ====="]
    for url, texto in paginas:
        partes.append(f"--- [{url}] | Relevancia: DIRECTA ---")
        partes.append(texto)
    return "\n".join(partes)


PROGRAMA = ("12:00 Cohete de inicio de fiestas.\n14:30 Comida popular en el centro social.\n"
            "18:00 Pregon a cargo de Manuel Valero.\n23:00 Verbena con la orquesta Azabache.")
PROSA = ("Las fiestas de la localidad se celebran cada verano con gran participacion "
         "vecinal. Hay actos religiosos, musica y gastronomia para todos los publicos.")


def test_una_pagina_con_programa_da_luz_verde():
    assert hay_material_para_un_programa(contexto(("https://a.es/programa", PROGRAMA)))


def test_solo_prosa_no_basta():
    """
    El caso de Sierra: ninguna de sus páginas traía un acto con hora, y el modelo
    devolvió 39 actos inventados con confianza alta. No preguntar no pierde nada,
    porque de ahí no salían datos, salían invenciones.
    """
    assert not hay_material_para_un_programa(contexto(("https://a.es", PROSA)))


def test_un_listado_administrativo_no_basta():
    admin = "AYUNTAMIENTO DE PETROLA AYUNTAMIENTO DE POVEDILLA CONSORCIO DE MEDIO AMBIENTE"
    assert not hay_material_para_un_programa(contexto(("https://sede.es", admin)))


def test_basta_con_que_UNA_pagina_lo_traiga():
    """El programa está en una página; las demás pueden ser ruido."""
    ctx = contexto(("https://ruido.es", PROSA), ("https://buena.es/prog", PROGRAMA))
    assert hay_material_para_un_programa(ctx)
    assert mejor_pagina_con_programa(ctx)[0] == "https://buena.es/prog"


def test_un_contexto_vacio_no_da_luz_verde():
    assert not hay_material_para_un_programa("")
    assert mejor_pagina_con_programa("") == ("", 0)


# ──────────────────────────────────────────────────────────────
# El programa tiene que ser DE ESTA fiesta
# ──────────────────────────────────────────────────────────────

ENERO = {"fecha_inicio": "2026-01-17", "fecha_fin": "2026-01-31"}
MAYO = {"fecha_inicio": "2026-05-10", "fecha_fin": "2026-05-24"}

# Con líneas de verdad: contar_actos_horarios exige tres palabras por línea para
# no contar filas de tablas de importes, así que «20:00h. NOVENA.» no suma.
PROGRAMA_DE_MAYO = "\n".join([
    "Del 15 al 23 de mayo",
    "20:00 Novena en la parroquia de la Asuncion.",
    "12:00 Eucaristia en honor a nuestros patronos.",
    "23:50 Concierto en la Plaza de Espana con la Orquesta Senor Aliaga.",
])


def test_el_programa_de_otro_mes_no_cuenta():
    """
    Tobarra tiene tres fiestas y radiotobarra.es/cristo26-1.pdf es el programa de
    una: la de mayo. Sin mirar las fechas se señalaba como «el programa» de las
    tres, y de ahí salía que la ficha de enero llevara el concierto de la
    Orquesta Señor Aliaga, que es un acto real de la fiesta de mayo.
    """
    ctx = contexto(("https://radiotobarra.es/cristo26.pdf", PROGRAMA_DE_MAYO))
    assert hay_material_para_un_programa(ctx, MAYO)
    assert not hay_material_para_un_programa(ctx, ENERO)


def test_una_pagina_sin_mes_sigue_valiendo():
    """
    Muchos programas solo ponen «día 14, día 15» y el mes va en el cartel.
    La ausencia no descarta; solo descarta nombrar OTROS meses y no el nuestro.
    """
    sin_mes = "\n".join([
        "Dia 17",
        "12:00 Cohete de inicio de fiestas.",
        "14:30 Comida popular en el centro social.",
        "20:00 Verbena con la orquesta del pueblo.",
    ])
    assert hay_material_para_un_programa(contexto(("https://a.es", sin_mes)), ENERO)


def test_sin_fiesta_no_se_mira_el_mes():
    """Compatibilidad: quien no pase la fiesta obtiene el comportamiento de antes."""
    ctx = contexto(("https://a.es", PROGRAMA_DE_MAYO))
    assert hay_material_para_un_programa(ctx)


def test_mayo_esta_en_la_lista_de_meses():
    """
    Un filtro por longitud (`len(m) > 4`) dejaba fuera «mayo», de cuatro letras,
    y el programa del Cristo seguía pasando por el de enero.
    """
    from llm_processor.text_analyzer import _MESES_COMPLETOS
    for mes in ("enero", "mayo", "junio", "julio", "agosto", "diciembre"):
        assert mes in _MESES_COMPLETOS


def test_el_mar_no_es_marzo():
    """Las abreviaturas quedan fuera: «mar» es palabra corriente en castellano."""
    from llm_processor.text_analyzer import _habla_de_otro_mes
    assert not _habla_de_otro_mes("un paseo por el mar y la playa", {1})


def test_el_marcador_de_origen_no_llega_al_modelo():
    """
    El «| ORIGEN: url» de los snippets sirve para purgarlos cuando su URL se
    descarta; al modelo le estorba. Medido el 2026-08-26: a Sierra le salió una
    ficha llamada «Fiestas de San Francisco Javier Origen Https».
    """
    linea = ("TITULO: Fiestas de Sierra | CONTENIDO: Programa de actos. "
             "| ORIGEN: https://festisierra.com/programacion/")
    salida = ensamblar_contexto([chunk("buscadores:snippets", 0, linea, 0.5, fuente="busqueda_web")])
    assert "ORIGEN" not in salida
    assert "festisierra.com" not in salida
    assert "Fiestas de Sierra" in salida
    assert "Programa de actos" in salida

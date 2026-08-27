"""
Reconstrucción del orden de lectura de un PDF maquetado.

Cada test reproduce un fallo concreto medido sobre el cartel de fiestas de
Amurrio 2026 y el librito de la Festa Major de Terrassa 2026. No hacen falta los
PDF: se construyen las palabras con las coordenadas que provocaban el fallo.
"""
import pytest

from disposicion_pdf import (
    agrupar_filas,
    detectar_columnas,
    extraer_pagina_estructurada,
    merece_reconstruccion,
    RE_CABECERA_DIA,
    _altura_letra,
    _partir_en_segmentos,
)

ALTURA = 9.0


def palabra(texto, x0, top, ancho=None):
    ancho = ancho if ancho is not None else len(texto) * 4.5
    return {"text": texto, "x0": x0, "x1": x0 + ancho, "top": top, "bottom": top + ALTURA}


class PaginaFalsa:
    """Lo mínimo que `extraer_pagina_estructurada` usa de una página de pdfplumber."""

    def __init__(self, words, width):
        self._words = words
        self.width = width

    def extract_words(self):
        return list(self._words)


# ── Agrupado de filas ────────────────────────────────────────────────────────

def test_la_hora_no_se_separa_de_su_acto_por_la_linea_base():
    """La hora y su acto tienen líneas base distintas (1048.71 vs 1048.32).

    Con `round(top / tol)` caían en cubos diferentes y "21:30 ZINEMA KALEAN"
    se partía en dos entradas, dejando la hora huérfana.
    """
    words = [
        palabra("21:30", 34.0, 1048.71),
        palabra("ZINEMA", 59.3, 1048.32),
        palabra("KALEAN:", 92.3, 1048.32),
    ]
    filas = agrupar_filas(words, ALTURA)
    assert len(filas) == 1
    assert " ".join(w["text"] for w in filas[0]) == "21:30 ZINEMA KALEAN:"


def test_las_columnas_con_lineas_base_escalonadas_no_encadenan():
    """Con enlace simple, cuatro columnas escalonadas formaban una fila gigante.

    Cada palabra distaba menos de la tolerancia de la ANTERIOR, así que la
    cadena no se rompía nunca y acababan juntas líneas separadas por 20pt.
    """
    words = [
        palabra("A", 34.0, 1000.0),
        palabra("B", 240.0, 1003.0),
        palabra("C", 460.0, 1006.0),
        palabra("D", 670.0, 1009.0),
        palabra("E", 34.0, 1012.0),
    ]
    filas = agrupar_filas(words, ALTURA)
    assert len(filas) > 1, "las líneas escalonadas se encadenaron en una sola fila"
    assert all(f[-1]["top"] - f[0]["top"] <= ALTURA for f in filas)


# ── Detección de columnas ────────────────────────────────────────────────────

def test_detecta_columnas_aunque_algunas_lineas_invadan_la_vecina():
    """En el cartel de Amurrio hay líneas en euskera que desbordan su columna.

    Un detector por franjas de blanco veía UNA sola columna porque esas líneas
    cerraban el hueco al proyectar todas las extensiones juntas. Los COMIENZOS
    de línea, en cambio, siguen alineados en el origen de su columna.

    Premisa (que el documento real cumple): no TODAS las líneas desbordan. Basta
    con que algunas sean cortas para que el hueco aparezca y revele el origen de
    la columna siguiente. Aquí una de cada tres desborda, como en el cartel.
    """
    words = []
    for i, top in enumerate(range(1000, 1180, 12)):
        words.append(palabra("11:00", 34.0, top))
        ancho_izq = 175 if i % 3 == 0 else 60   # una de cada tres invade
        words.append(palabra("TEXTO_IZQUIERDA", 58.0, top, ancho=ancho_izq))
        words.append(palabra("13:00", 240.0, top))
        words.append(palabra("OTRO", 265.0, top))

    altura = _altura_letra(words)
    segmentos = []
    for fila in agrupar_filas(words, altura):
        segmentos.extend(_partir_en_segmentos(fila, altura))
    columnas = detectar_columnas(segmentos, 907.0, altura)
    assert len(columnas) == 2, f"esperadas 2 columnas, detectadas {len(columnas)}"


def test_documento_de_una_columna_no_se_parte():
    """La prosa corrida debe seguir siendo una sola columna."""
    words = []
    for top in range(100, 220, 12):
        x = 28.0
        for pal in ("El", "Raval", "Infernal", "és", "l'acte", "principal"):
            words.append(palabra(pal, x, top))
            x += len(pal) * 4.5 + 1.9
    altura = _altura_letra(words)
    segmentos = []
    for fila in agrupar_filas(words, altura):
        segmentos.extend(_partir_en_segmentos(fila, altura))
    columnas = detectar_columnas(segmentos, 420.0, altura)
    assert len(columnas) == 1
    assert not merece_reconstruccion({"columnas": len(columnas)})


# ── Corte en los límites ─────────────────────────────────────────────────────

def test_la_prosa_que_cruza_un_limite_no_se_trunca():
    """Terrassa: un párrafo ancho cruza el límite con 0.19x de hueco.

    Filtrar palabra a palabra por su x0 truncaba la frase a media palabra
    ("...de la Festa Major" en vez de "...de la Festa Major de Terrassa.").
    """
    words = []
    # dos columnas reales, para que se detecte el límite
    for top in range(100, 200, 12):
        words.append(palabra("11:00", 28.0, top))
        words.append(palabra("ACTO", 60.0, top))
        words.append(palabra("12:00", 217.0, top))
        words.append(palabra("OTRO", 250.0, top))
    # una fila de prosa que cruza el límite con espaciado normal
    x = 28.0
    for pal in ("frase", "larga", "que", "cruza", "el", "limite", "sin", "hueco", "grande",
                "y", "continua", "despues", "del", "corte", "hasta", "el", "final"):
        words.append(palabra(pal, x, 300.0))
        x += len(pal) * 4.5 + 1.9

    texto, _ = extraer_pagina_estructurada(PaginaFalsa(words, 420.0))
    assert "hasta el final" in texto, "la prosa que cruza el límite se truncó"


def test_las_columnas_de_verdad_si_se_cortan():
    """Amurrio: la fuga entre columnas tenía 1.00x de hueco y debe cortarse."""
    words = []
    for top in range(100, 220, 12):
        words.append(palabra("11:00", 34.0, top))
        words.append(palabra("ACTO_COLUMNA_UNO", 60.0, top, ancho=140))
        words.append(palabra("13:00", 241.0, top))  # hueco de 9pt = 1.0x altura
        words.append(palabra("ACTO_COLUMNA_DOS", 270.0, top, ancho=140))

    texto, metricas = extraer_pagina_estructurada(PaginaFalsa(words, 907.0))
    assert metricas["columnas"] == 2
    # ninguna línea debe mezclar actos de las dos columnas
    for linea in texto.split("\n"):
        assert not ("ACTO_COLUMNA_UNO" in linea and "ACTO_COLUMNA_DOS" in linea), linea


# ── Cabeceras de día ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cabecera", [
    "12 MIÉRCOLES",
    "12 ASTEAZKENA",
    "DIVENDRES, 3 DE JULIOL",
    "17 LUNES",
    "12 DE AGOSTO",
    "ABUZTUAK 12",
])
def test_reconoce_cabeceras_de_dia_en_las_lenguas_del_estado(cabecera):
    assert RE_CABECERA_DIA.match(cabecera), f"no reconocida: {cabecera}"


@pytest.mark.parametrize("no_cabecera", [
    "11:00 FINALES CAMPEONATO DE PELOTA",
    "CONCIERTO: NØT",
    "Plaça del Progrés",
])
def test_no_confunde_actos_con_cabeceras(no_cabecera):
    assert not RE_CABECERA_DIA.match(no_cabecera), f"falso positivo: {no_cabecera}"


# ── Continuación entre columnas ──────────────────────────────────────────────

def test_una_columna_sin_cabecera_continua_el_dia_de_la_anterior():
    """El día 14 de Amurrio empieza al final de una columna y sigue en la otra.

    Sin arrastrar la cabecera, 13 de sus 21 actos quedaban sin día asignado.
    """
    words = []
    words.append(palabra("14", 34.0, 100.0))
    words.append(palabra("VIERNES", 50.0, 100.0))
    for i, top in enumerate(range(115, 200, 12)):
        words.append(palabra(f"1{i}:00", 34.0, top))
        words.append(palabra("ACTO_IZQUIERDA", 60.0, top, ancho=140))
    # segunda columna, arranca directamente con actos (sin cabecera)
    for i, top in enumerate(range(100, 200, 12)):
        words.append(palabra(f"2{i}:00", 241.0, top))
        words.append(palabra("ACTO_DERECHA", 275.0, top, ancho=130))

    texto, _ = extraer_pagina_estructurada(PaginaFalsa(words, 907.0))
    assert "continúa de la columna anterior" in texto
    # el marcador debe aparecer ANTES de los actos de la segunda columna
    assert texto.index("continúa de la columna anterior") < texto.index("ACTO_DERECHA")


# ── Robustez ─────────────────────────────────────────────────────────────────

def test_pagina_vacia_no_revienta():
    texto, metricas = extraer_pagina_estructurada(PaginaFalsa([], 420.0))
    assert texto == ""
    assert metricas["columnas"] == 0
    assert not merece_reconstruccion(metricas)

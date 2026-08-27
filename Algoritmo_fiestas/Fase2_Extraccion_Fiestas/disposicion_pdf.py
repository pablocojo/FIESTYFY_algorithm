"""
Reconstrucción del orden de lectura de un PDF maquetado.

El problema que resuelve
------------------------
`page.extract_text()` recorre la página por filas horizontales. En un documento
de una sola columna eso es correcto; en un cartel de fiestas, no. El cartel de
Amurrio 2026 son cuatro columnas (euskera ×2, castellano ×2) y cada línea de
salida pegaba actos de columnas y días distintos:

    18:00 SANTUAREN JAITSIERA 13:30 APAR-FESTA 18:00 BAJADA DEL SANTO 15:00 COMIDA DE CUADRILLAS

Ahí hay cuatro actos de dos días diferentes. Medido el 2026-08-21 sobre ese
cartel: el modelo extraía 13 de 118 actos (11%) y atribuía mal 7 de esos 13, no
porque alucinase sino porque el texto que recibía ya venía descolocado.

Con la reconstrucción por columnas: 118 de 118 actos (100%) y 116 horas exactas
(98,3%).

Por qué no lo hace un modelo de visión
--------------------------------------
Se probó. Qwen2.5-VL-7B sobre un recorte del bloque del 12 de agosto transcribió
los 15 actos con sus nombres exactos y **falló las 15 horas** (11:00→08:00,
17:30→15:30, 23:45→21:45). Entiende la disposición y alucina los dígitos. La capa
de texto tiene los dígitos exactos y no sabe de disposición; por eso la
disposición se deduce de las coordenadas y el contenido se toma del texto.
"""

from __future__ import annotations

import logging
import re
import statistics

logger = logging.getLogger("disposicion")

try:
    from config import (
        DISPOSICION_FACTOR_HUECO_COLUMNA,
        DISPOSICION_FACTOR_CORTE_LIMITE,
        DISPOSICION_FACTOR_FILA,
        DISPOSICION_MIN_COLUMNAS_PARA_APLICAR,
    )
except ImportError:  # utilizable en solitario
    DISPOSICION_FACTOR_HUECO_COLUMNA = 3.0
    DISPOSICION_FACTOR_CORTE_LIMITE = 0.6
    DISPOSICION_FACTOR_FILA = 0.6
    DISPOSICION_MIN_COLUMNAS_PARA_APLICAR = 2

# ── Cabeceras de día, en las lenguas del Estado ──────────────────────────────
_DIAS = (
    r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo"
    r"|astelehena?|asteartea?|asteazkena?|osteguna?|ostirala?|larunbata?|igandea?"
    r"|dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge"
    r"|luns|m[eé]rcores|xoves|venres"
)
_MESES = (
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    r"|urtarril|otsail|martxo|apiril|maiatz|ekain|uztail|abuztu|irail|urri|azaro|abendu"
    r"|gener|febrer|mar[cç]|maig|juny|juliol|agost|setembre|octubre|novembre|desembre"
    r"|xaneiro|febreiro|maio|xu[nñ]o|xullo|setembro|outubro|novembro|decembro"
)
RE_CABECERA_DIA = re.compile(
    rf"^\s*(?:\d{{1,2}}\s*[.\-]?\s*(?:{_DIAS})\b"          # "12 MIÉRCOLES"
    rf"|(?:{_DIAS})\s*,?\s*\d{{1,2}}\b"                     # "DIVENDRES, 3 DE JULIOL"
    rf"|\d{{1,2}}\s+de\s+(?:{_MESES})\b"                    # "12 DE AGOSTO"
    rf"|(?:{_MESES})\w*\s+\d{{1,2}}\b)",                    # "ABUZTUAK 12"
    re.IGNORECASE,
)
RE_HORA_INICIAL = re.compile(r"^\s*\d{1,2}[:.]\d{2}(?:\s*-\s*\d{1,2}[:.]\d{2})?\s*h?\b")

MAX_CHARS_CABECERA = 60


def _altura_letra(words: list[dict]) -> float:
    alturas = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    return statistics.median(alturas) if alturas else 9.0


def agrupar_filas(words: list[dict], altura: float) -> list[list[dict]]:
    """
    Palabras agrupadas en filas por cercanía vertical.

    Se compara contra el PRIMER elemento de la fila, no contra el anterior. Con
    enlace simple, cuatro columnas de líneas base escalonadas encadenan
    (1163.32 → 1163.71 → 1166 → 1169…) y acaban formando una única fila que
    mezcla actos de columnas opuestas.

    Tampoco se usa `round(top / tol)`: la hora y su acto tienen líneas base
    ligeramente distintas (1048.71 frente a 1048.32) y el redondeo los mandaba a
    cubos diferentes, partiendo "21:30 ZINEMA KALEAN" en dos entradas sueltas.
    """
    if not words:
        return []
    tol = max(1.5, altura * DISPOSICION_FACTOR_FILA)
    ordenadas = sorted(words, key=lambda w: w["top"])
    filas, actual = [], [ordenadas[0]]
    for w in ordenadas[1:]:
        if w["top"] - actual[0]["top"] <= tol:
            actual.append(w)
        else:
            filas.append(actual)
            actual = [w]
    filas.append(actual)
    return [sorted(f, key=lambda w: w["x0"]) for f in filas]


def _partir_en_segmentos(fila: list[dict], altura: float) -> list[list[dict]]:
    """Trozos de una fila separados por huecos horizontales evidentes."""
    corte = altura * DISPOSICION_FACTOR_HUECO_COLUMNA
    segmentos, actual = [], [fila[0]]
    for w in fila[1:]:
        if w["x0"] - actual[-1]["x1"] >= corte:
            segmentos.append(actual)
            actual = [w]
        else:
            actual.append(w)
    segmentos.append(actual)
    return segmentos


def detectar_columnas(segmentos: list[list[dict]], ancho: float, altura: float) -> list[tuple]:
    """
    Orígenes de columna deducidos del COMIENZO de cada segmento.

    No sirve mirar la extensión de las líneas: en el cartel de Amurrio hay líneas
    largas en euskera que invaden la columna castellana y cierran el hueco, y un
    detector por franjas de blanco veía una sola columna. Lo que no cambia es
    dónde EMPIEZA cada línea.
    """
    inicios = sorted(s[0]["x0"] for s in segmentos)
    if not inicios:
        return [(0.0, ancho + 1)]
    separacion = max(altura * DISPOSICION_FACTOR_HUECO_COLUMNA, ancho * 0.04)

    grupos, actual = [], [inicios[0]]
    for x in inicios[1:]:
        if x - actual[-1] <= separacion:
            actual.append(x)
        else:
            grupos.append(actual)
            actual = [x]
    grupos.append(actual)

    minimo = max(2, len(segmentos) * 0.05)
    origenes = [min(g) for g in grupos if len(g) >= minimo]
    if not origenes:
        origenes = [min(inicios)]
    origenes[0] = min(origenes[0], min(inicios))
    return [
        (o, origenes[i + 1] if i + 1 < len(origenes) else ancho + 1)
        for i, o in enumerate(origenes)
    ]


def _trocear_por_limites(fila: list[dict], limites: list[float], altura: float) -> list[list[dict]]:
    """
    Parte una fila en los límites de columna ya detectados, pero solo si ahí hay
    de verdad un hueco.

    Dos umbrales distintos a propósito. Para DETECTAR una columna se exige un
    hueco enorme, porque un falso positivo parte el documento entero. Para CORTAR
    en un límite que ya se sabe que existe basta con mucho menos. Medido: la fuga
    entre columnas del cartel de Amurrio tenía un hueco de 1,00× la altura de
    letra (se corta), y la prosa del librito de Terrassa que cruza el límite
    tiene 0,19× (no se corta y la frase sobrevive entera).
    """
    if not limites:
        return [fila]
    corte = altura * DISPOSICION_FACTOR_CORTE_LIMITE
    trozos, actual = [], [fila[0]]
    for anterior, w in zip(fila, fila[1:]):
        hueco = w["x0"] - anterior["x1"]
        cruza_limite = any(anterior["x1"] <= b <= w["x0"] for b in limites)
        if cruza_limite and hueco >= corte:
            trozos.append(actual)
            actual = [w]
        else:
            actual.append(w)
    trozos.append(actual)
    return trozos


def _indice_columna(x: float, columnas: list[tuple]) -> int:
    for i, (a, b) in enumerate(columnas):
        if a - 0.5 <= x < b:
            return i
    return len(columnas) - 1


def extraer_pagina_estructurada(page) -> tuple[str, dict]:
    """
    Devuelve (markdown, métricas) para una página de pdfplumber.

    El Markdown conserva el orden de lectura humano: una sección por columna y un
    encabezado por día, de modo que un modelo pequeño no pueda confundir a qué
    jornada pertenece cada acto.
    """
    words = page.extract_words()
    if not words:
        return "", {"columnas": 0, "lineas": 0, "cabeceras_dia": 0}

    altura = _altura_letra(words)

    # Pasada 1: deducir las columnas con el umbral conservador.
    segmentos = []
    for fila in agrupar_filas(words, altura):
        segmentos.extend(_partir_en_segmentos(fila, altura))
    columnas = detectar_columnas(segmentos, page.width, altura)
    limites = [a for a, _ in columnas[1:]]

    # Pasada 2: trocear cada fila en esos límites y repartir por columna.
    por_columna: dict[int, list] = {i: [] for i in range(len(columnas))}
    for fila in agrupar_filas(words, altura):
        for trozo in _trocear_por_limites(fila, limites, altura):
            por_columna[_indice_columna(trozo[0]["x0"], columnas)].append(trozo)

    partes: list[str] = []
    dia_actual = None
    n_dias = n_lineas = 0

    for i in range(len(columnas)):
        if not por_columna[i]:
            continue
        # Re-agrupar DENTRO de la columna: el agrupado de la pasada 1 mezcla las
        # líneas base de todas las columnas y una fila puede cerrarse justo antes
        # de su propia hora.
        palabras_columna = [w for t in por_columna[i] for w in t]
        lineas = agrupar_filas(palabras_columna, altura)

        if len(columnas) > 1:
            partes.append("")
            partes.append(f"## Columna {i + 1} de {len(columnas)}")

        # Una columna que no arranca con cabecera CONTINÚA el último día de la
        # anterior, como en un periódico. En el cartel de Amurrio el día 14
        # empieza al final de una columna y sigue arriba de la siguiente: sin
        # arrastrar la cabecera se perdían 13 de sus 21 actos.
        primera = next(
            (" ".join(w["text"] for w in t).strip() for t in lineas
             if " ".join(w["text"] for w in t).strip()),
            "",
        )
        if dia_actual and not _es_cabecera(primera):
            partes.append("")
            partes.append(f"### {dia_actual} (continúa de la columna anterior)")

        for linea in lineas:
            texto = " ".join(w["text"] for w in linea).strip()
            if not texto:
                continue
            n_lineas += 1
            if _es_cabecera(texto):
                partes.append("")
                partes.append(f"### {texto}")
                dia_actual = texto
                n_dias += 1
            elif RE_HORA_INICIAL.match(texto):
                partes.append(f"- {texto}")
            else:
                partes.append(texto)

    return "\n".join(partes).strip(), {
        "columnas": len(columnas),
        "lineas": n_lineas,
        "cabeceras_dia": n_dias,
        "altura_letra": round(altura, 1),
    }


def _es_cabecera(texto: str) -> bool:
    return bool(texto) and len(texto) < MAX_CHARS_CABECERA and bool(RE_CABECERA_DIA.match(texto))


def merece_reconstruccion(metricas: dict) -> bool:
    """
    ¿Vale la pena usar la versión estructurada en vez del texto plano?

    Solo cuando hay varias columnas. En un documento de una sola columna el texto
    plano ya está en orden de lectura y reconstruirlo no aporta nada.
    """
    return metricas.get("columnas", 0) >= DISPOSICION_MIN_COLUMNAS_PARA_APLICAR

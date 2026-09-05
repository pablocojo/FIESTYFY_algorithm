"""
Señales léxicas compartidas para detectar contenido festivo.

Un único sitio para los patrones que hoy están repetidos e incorrectos por el
código. En particular, el patrón de horas: la versión anterior
(`\b\d{1,2}[:.]\d{2}\b`, en text_analyzer) daba 154 falsos positivos sobre el PDF
del presupuesto municipal de Amurrio, porque `3.2.2.01.` contiene `2.01`. Eso
otorgaba a una tabla contable el bonus de "casi seguro una agenda de eventos" y
la colocaba por encima del programa de fiestas real.

`PATRON_HORA` valida el rango (00-23 : 00-59) y exige que no haya dígitos,
puntos ni comas pegados a los lados.
"""

from __future__ import annotations

import re
import unicodedata

# ── Horas ────────────────────────────────────────────────────────────────────
# Acepta: 12:00, 23.30, 9:30h, 18.00 h, 00:30
# Rechaza: 3.2.2.01, 56.408,63, 1.358.729,64, 3.4.0.17
PATRON_HORA = re.compile(
    r"(?<![\d.,:])(?:[01]?\d|2[0-3])[:.][0-5]\d(?:\s*h(?:oras)?\b)?(?![\d.,:])",
    re.IGNORECASE,
)


def contar_horas(texto: str) -> int:
    """Número de horas de reloj plausibles en el texto."""
    return len(PATRON_HORA.findall(texto or ""))


# Una línea que no es más que una hora: "21:00", "· 12.00 h", "— 09:30 horas".
_SOLO_HORA = re.compile(
    r"^[\s•·\-–—*>|]*(?:[01]?\d|2[0-3])[:.][0-5]\d\s*(?:h(?:oras)?\.?)?[\s.:·•\-–—]*$",
    re.IGNORECASE,
)

# Encabezado de día dentro de un programa: "Sábado, 15 de agosto", "DÍA 14".
_CABECERA_DE_DIA = re.compile(
    r"^[\s•·\-–—*]*(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
    r"d[ií]a|jornada)\b",
    re.IGNORECASE,
)

_VINETA_INICIAL = re.compile(r"^[\s•·\-–—*>|]+")


def unir_hora_con_acto(texto: str) -> str:
    """
    Pega la línea que solo contiene una hora con el acto que viene debajo.

    Media web publica los programas en dos líneas —la hora sola y, debajo, lo que
    ocurre— y todo lo que mide "programa" en este proyecto exige que las dos
    cosas estén en la MISMA línea. El coste era enorme y estaba escondido: medido
    el 2026-08-27 sobre las 882 páginas de la caché, 98 ganan actos al unirlas y
    50 pasan de no llegar al umbral a superarlo. Cincuenta veces el pipeline
    decidía "aquí no hay programa" teniendo el programa delante, entre ellas el
    de Sierra —descargado entero, con sus horas y sus actos, contado como cero—
    y los PDF de San Fermín, Torrent y Huétor Vega.

    Se aplica antes de contar y antes de trocear, para que el modelo lea lo mismo
    que el detector. Es idempotente: una línea ya unida deja de ser "solo hora".
    """
    lineas = (texto or "").split("\n")
    salida: list[str] = []
    i = 0
    while i < len(lineas):
        actual = lineas[i].strip()
        if _SOLO_HORA.match(actual) and i + 1 < len(lineas):
            siguiente = lineas[i + 1].strip()
            # No se pega con otra hora ni con la cabecera del día siguiente: en
            # los dos casos la hora se quedaría describiendo lo que no es.
            if (siguiente and not _SOLO_HORA.match(siguiente)
                    and not _CABECERA_DE_DIA.match(siguiente)):
                salida.append(f"{actual} {_VINETA_INICIAL.sub('', siguiente)}")
                i += 2
                continue
        salida.append(lineas[i])
        i += 1
    return "\n".join(salida)


# ── Vocabulario festivo ──────────────────────────────────────────────────────
# Términos que identifican contenido de fiestas en las lenguas del Estado.
TERMINOS_FESTIVOS = frozenset({
    # Castellano
    "fiesta", "fiestas", "festejo", "festejos", "festividad", "patronal", "patronales",
    "programa", "programacion", "cartel", "feria", "ferias", "carnaval", "romeria",
    "verbena", "pregon", "chupinazo", "encierro", "orquesta", "concierto", "actos",
    "pasacalles", "charanga", "gigantes", "cabezudos", "procesion", "novillada",
    "degustacion", "hoguera", "falla", "fallas", "moros", "cristianos",
    # Catalán / Valenciano / Balear
    "festes", "festa", "cartell", "programacio", "revetlla", "correfoc", "cercavila",
    "castellers", "sardanes",
    # Euskera
    "jaiak", "jaia", "jai", "egitaraua", "festak", "kartela", "txosna", "txosnak",
    "kontzertua", "erromeria", "kalejira", "txupinazoa", "herriko",
    # Gallego
    "festas", "romaria", "foliada", "verbenas", "patronais",
    # Aranés / occitano
    "hesta", "hestes", "patronaus",
})

# Sustantivos que denotan un ACTO concreto de un programa. Sirven para exigir que
# una línea con hora describa además algo que ocurre, y no sea una cifra suelta.
NOMBRES_ACTO = frozenset({
    "pasacalles", "verbena", "concierto", "kontzertua", "misa", "meza", "procesion",
    "chupinazo", "txupinazoa", "txupinazo", "romeria", "erromeria", "romaria",
    "fuegos", "artificiales", "toro", "vaquilla", "novillada", "encierro", "corrida",
    "degustacion", "comida", "cena", "almuerzo", "merienda", "paella", "sardinada",
    "concurso", "campeonato", "torneo", "partido", "pelota", "frontón", "fronton",
    "baile", "danzas", "dantzak", "actuacion", "espectaculo", "teatro", "cine",
    "desfile", "cabalgata", "carroza", "carrozas", "kalejira", "cercavila",
    "hinchables", "talleres", "taller", "gymkana", "yincana", "disco", "dj",
    "orquesta", "charanga", "banda", "coral", "coro", "fanfarria", "txaranga",
    "pregon", "pregón", "inauguracion", "clausura", "traca", "castillo",
    # La Tamborada de Tobarra no la nombraba nadie: "tambor" no estaba aquí y
    # sus fuentes hablan de tambores, no de verbenas.
    "tamborada", "tamborrada", "tambor", "tambores",
    "herri", "kirolak", "sokatira", "aizkolari", "bertsolari",
})


def _normalizar(texto: str) -> str:
    texto = (texto or "").lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _palabras(texto: str) -> list[str]:
    return re.findall(r"[a-z]{3,}", _normalizar(texto))


def contar_terminos_festivos(texto: str) -> int:
    """Cuántos términos festivos DISTINTOS aparecen en el texto."""
    return len(TERMINOS_FESTIVOS.intersection(_palabras(texto)))


def contar_nombres_acto(texto: str) -> int:
    """Cuántos nombres de acto DISTINTOS aparecen en el texto."""
    return len(NOMBRES_ACTO.intersection(_palabras(texto)))


def tiene_termino_festivo(texto: str) -> bool:
    return contar_terminos_festivos(texto) > 0


# Frases de metadatos de documento: llevan hora, pero no son un acto.
_RE_METADATO_DOC = re.compile(
    r"impres[oa]\s+el|generad[oa]\s+el|fecha\s+de\s+(?:impresi|generaci|creaci)|"
    r"p[aá]gina\s+\d+\s+de\s+\d+|last\s+modified|actualizado\s+el|"
    r"copyright|todos\s+los\s+derechos",
    re.IGNORECASE,
)


# Un tramo "de 10:00 a 13:00" es un HORARIO —cuándo está abierto algo—, no un
# acto. La diferencia importaba poco hasta que de ella salió el programa de una
# fiesta: el 2026-08-26 la página del eclipse de Aranda de Duero («Allendeduero
# – Asociación Vecinal: todos los días, de 10:00 a 13:00 y de 18:00 a 20:00
# horas») aportó 8 "actos con hora", ganó a todas las demás y fue elegida como
# el programa de las fiestas patronales. Cinco llamadas al modelo después, la
# ficha salió con quince días y cero actos.
_RE_TRAMO_HORARIO = re.compile(
    r"(?:\bde\s+|\bentre\s+)?"
    r"(?<![\d.,:])(?:[01]?\d|2[0-3])[:.][0-5]\d(?:\s*h(?:oras)?\b)?"
    r"\s*(?:a|as|hasta|-|–|/)\s*"
    r"(?:[01]?\d|2[0-3])[:.][0-5]\d(?:\s*h(?:oras)?\b)?(?![\d.,:])",
    re.IGNORECASE,
)

# Fórmulas de horario de atención al público: llevan hora y prosa, y ninguna
# anuncia nada que ocurra.
_RE_LINEA_DE_HORARIO = re.compile(
    r"horario\s+de|de\s+lunes\s+a\s+|todos\s+los\s+d[ií]as\s*,?\s*de\b|"
    r"abiert[oa]\s+(?:de|al)\b|atenci[oó]n\s+al\s+p[uú]blico|cita\s+previa|"
    r"reparto\s+de|recogida\s+de",
    re.IGNORECASE,
)


def contar_actos_horarios(texto: str) -> int:
    """
    Número de horas de reloj DISTINTAS que aparecen en líneas con pinta de acto
    (una hora más algo que ocurre en la misma línea).

    Contar horas sueltas no basta, y contar líneas tampoco. El PDF del
    presupuesto de Amurrio repite en cada página "Impreso el 14/01/2025 a las
    13:35": son cuatro líneas con hora y prosa, pero solo dos horas distintas y
    todas son metadatos del documento. Un programa real tiene muchas horas
    distintas repartidas por el día.

    Y una hora sola tampoco basta: hay que distinguir la que anuncia un acto
    ("20:00 Pasacalles") de la que abre un horario ("de 20:00 a 21:00 horas").
    Los tramos se descuentan SOLO en las líneas sin vocabulario de acto, para no
    perder la verbena que de verdad va "de 23:00 a 04:00".

    Antes de nada se pegan las horas que están solas en su línea con el acto que
    llevan debajo (ver `unir_hora_con_acto`): sin eso, un programa maquetado en
    dos líneas —que son muchos— contaba cero.
    """
    horas = set()
    for linea in unir_hora_con_acto(texto).split("\n"):
        encontradas = PATRON_HORA.findall(linea)
        if not encontradas:
            continue
        if _RE_METADATO_DOC.search(linea):
            continue
        if contar_nombres_acto(linea) == 0:
            if _RE_LINEA_DE_HORARIO.search(linea):
                continue
            # Descontar los tramos y volver a mirar: si no queda ninguna hora
            # suelta, la línea entera era un horario de apertura.
            encontradas = PATRON_HORA.findall(_RE_TRAMO_HORARIO.sub(" ", linea))
            if not encontradas:
                continue
            # Sin vocabulario conocido: exigir prosa real y poca densidad numérica,
            # para no contar filas de una tabla de importes.
            palabras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}", linea)
            digitos = sum(c.isdigit() for c in linea)
            if len(palabras) < 3 or digitos / max(1, len(linea)) >= 0.25:
                continue
        for h in encontradas:
            horas.add(re.sub(r"[.\s]|h(?:oras)?$", ":", h.strip().lower()).rstrip(":"))
    return len(horas)


def parece_programa_de_actos(texto: str, min_actos: int = 3) -> bool:
    """
    True cuando el texto contiene varias entradas "hora + acto" con horas
    distintas. Es la firma de un programa de fiestas y lo que lo distingue de
    una tabla de importes con decimales o de una marca de impresión repetida.
    """
    return contar_actos_horarios(texto) >= min_actos

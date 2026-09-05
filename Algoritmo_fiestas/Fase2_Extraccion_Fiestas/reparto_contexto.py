"""
Reparto del material en lotes de contexto.

El problema que resuelve
-----------------------
Hasta ahora `seleccionar_chunks` era un FILTRO: ordenaba por prioridad de fuente
y score, llenaba un presupuesto en caracteres y lo que no cabía se perdía. Medido
sobre la ejecución del 2026-09-03, eso significaba que al modelo llegaba el 5,7 %
de los chunks candidatos en discovery y el 23,8 % en enrichment —10.060 chunks
descartados de 12.897—, y que 952 de los descartados puntuaban por encima del
peor chunk que sí entraba.

El ranking, con sus cuatro señales y su umbral adaptativo, decidía muy poco: el
que decidía era el presupuesto.

Cómo se resuelve
----------------
El ranking pasa a ORDENAR y no a filtrar. Nada se descarta: lo que no cabe en un
lote va en el siguiente, y se hace una llamada por lote. El coste crece con el
material en vez de truncarlo.

Tres cosas que este módulo hace y que el empaquetador anterior no hacía:

1. REPARTE POR PÁGINA, no por chunk. Los fragmentos de una misma página van
   juntos y en su orden de lectura, en el mismo lote. El programa de una fiesta
   está en una página y seguido; repartir chunk a chunk lo despedazaba entre
   llamadas, que es la versión peor del problema que `ensamblar_contexto` ya
   había arreglado dentro de un contexto.

2. MIDE EN TOKENS SOBRE EL TEXTO YA ENSAMBLADO. El presupuesto anterior sumaba
   `len(chunk)` e ignoraba los rótulos `===== FUENTE =====` y `--- [url] ---`
   que añade el ensamblado: por eso un presupuesto de 32.000 caracteres producía
   contextos de 33.039.

3. DEDUPLICA POR TEXTO. La clave anterior era `(fuente, chunk)`, así que el mismo
   texto llegado por dos fuentes ocupaba sitio dos veces: en Santiago de Mora,
   12 chunks repetidos de 30.

No decide QUÉ material hay —de eso siguen encargándose los filtros geográficos y
de homónimos— ni cómo se puntúa: solo en qué orden y en qué lote se pregunta.
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger("reparto")

# Se llena hasta esta fracción del lote con la estimación rápida y luego se
# comprueba el tamaño exacto. Deja sitio para los rótulos del ensamblado sin
# tener que ensamblar en cada paso, que sería cuadrático.
FRACCION_LLENADO = 0.94

# Suelo de seguridad: por debajo de esto un "lote" no cabe ni un chunk y el
# reparto entraría en bucle.
TOKENS_MINIMOS_LOTE = 512


def _hash(texto: str) -> str:
    return hashlib.sha1(" ".join((texto or "").split()).encode("utf-8")).hexdigest()[:16]


def deduplicar_por_texto(items: list[dict]) -> tuple[list[dict], int]:
    """
    Un texto, una vez. Devuelve (items, cuántos se quitaron).

    Ante dos copias del mismo texto gana la que viene de la página más completa
    y, en empate, la de más score. El criterio importa: si gana la copia que
    está dentro del bloque de snippets, la página real pierde un fragmento de su
    programa y `ensamblar_contexto` lo marcará como un hueco que no existe.
    """
    if not items:
        return [], 0

    tam_pagina: dict[str, int] = {}
    for i in items:
        url = i.get("url") or ""
        tam_pagina[url] = tam_pagina.get(url, 0) + 1

    def _preferencia(i: dict) -> tuple:
        url = i.get("url") or ""
        es_snippet = url.endswith(":snippets")
        return (es_snippet, -tam_pagina.get(url, 0), -float(i.get("score", 0.0)))

    mejor: dict[str, dict] = {}
    for i in sorted(items, key=_preferencia):
        h = _hash(i.get("chunk", ""))
        if h not in mejor:
            mejor[h] = i

    conservados = [i for i in items if mejor.get(_hash(i.get("chunk", ""))) is i]
    return conservados, len(items) - len(conservados)


def agrupar_por_pagina(items: list[dict]) -> list[list[dict]]:
    """
    Páginas, cada una con sus fragmentos en orden de lectura.

    Las páginas se devuelven ordenadas por su MEJOR fragmento: el ranking sigue
    mandando en el orden, pero la unidad que se reparte es la página.
    """
    grupos: dict[str, list[dict]] = {}
    for i in items:
        grupos.setdefault(i.get("url") or "", []).append(i)

    paginas = []
    for url, trozos in grupos.items():
        trozos.sort(key=lambda i: i.get("indice_chunk", 0))
        paginas.append(trozos)

    paginas.sort(key=lambda p: -max(float(i.get("score", 0.0)) for i in p))
    return paginas


def _tokens_de(items: list[dict], contar_tokens) -> int:
    """Estimación rápida: los fragmentos más el rótulo de su página."""
    if not items:
        return 0
    url = items[0].get("url") or ""
    rotulo = contar_tokens(f"\n--- [{url}] | Relevancia: DIRECTA ---")
    return rotulo + sum(contar_tokens(i.get("chunk", "")) for i in items)


def _partir_pagina(pagina: list[dict], tope: int, contar_tokens) -> list[list[dict]]:
    """
    Una página que no cabe entera se parte por su ORDEN DE LECTURA, nunca
    intercalada. Así cada trozo se sigue leyendo como se leía en el original y
    `ensamblar_contexto` puede marcar el corte con […].
    """
    trozos, actual, usados = [], [], 0
    for i in pagina:
        t = contar_tokens(i.get("chunk", ""))
        if actual and usados + t > tope:
            trozos.append(actual)
            actual, usados = [], 0
        actual.append(i)
        usados += t
    if actual:
        trozos.append(actual)
    return trozos


def repartir_en_lotes(
    items: list[dict],
    tokens_por_lote: int,
    ensamblar,
    contar_tokens,
    fijos: list[dict] | None = None,
) -> list[list[dict]]:
    """
    Reparte TODOS los `items` en lotes que quepan en `tokens_por_lote`.

    Nada se descarta. `fijos` son los fragmentos que tienen que ir en el primer
    lote pase lo que pase (las mejores páginas de la araña, la página que el
    localizador señaló como el programa): entran primero y arrastran a su página
    entera con ellos.

    `ensamblar` y `contar_tokens` se reciben por parámetro para no depender de
    text_analyzer ni de context_budget, y poder probar el módulo en solitario.
    """
    if not items:
        return []

    tope = max(TOKENS_MINIMOS_LOTE, int(tokens_por_lote * FRACCION_LLENADO))

    items, repetidos = deduplicar_por_texto(items)
    if repetidos:
        logger.info(f"  [REPARTO] {repetidos} fragmentos repetidos quitados antes de repartir.")

    paginas = agrupar_por_pagina(items)

    # Las páginas fijadas van delante, conservando entre ellas el orden en que
    # el llamante las pidió: el localizador devuelve las suyas de más a menos
    # parecidas al programa, y ese orden significa algo.
    urls_fijas = []
    for f in (fijos or []):
        u = f.get("url") or ""
        if u not in urls_fijas:
            urls_fijas.append(u)
    if urls_fijas:
        orden = {u: n for n, u in enumerate(urls_fijas)}
        paginas.sort(key=lambda p: orden.get(p[0].get("url") or "", len(orden)))

    # Empaquetado por estimación
    lotes: list[list[dict]] = []
    actual: list[dict] = []
    usados = 0
    for pagina in paginas:
        t = _tokens_de(pagina, contar_tokens)
        if t > tope:
            # Página más grande que un lote: se cierra lo que haya y se parte.
            if actual:
                lotes.append(actual)
                actual, usados = [], 0
            for trozo in _partir_pagina(pagina, tope, contar_tokens):
                lotes.append(trozo)
            continue
        if actual and usados + t > tope:
            lotes.append(actual)
            actual, usados = [], 0
        actual.extend(pagina)
        usados += t
    if actual:
        lotes.append(actual)

    return _ajustar_a_medida_exacta(lotes, tokens_por_lote, ensamblar, contar_tokens)


def _ajustar_a_medida_exacta(
    lotes: list[list[dict]], tokens_por_lote: int, ensamblar, contar_tokens,
) -> list[list[dict]]:
    """
    Comprobación final con el texto de verdad.

    La estimación no cuenta los rótulos `===== FUENTE =====` ni los separadores
    entre fuentes, así que un lote puede salir algo pasado. Aquí se mide el
    ensamblado real y, si se pasa, se empuja su última página al lote siguiente
    —nunca se recorta: recortar es lo que este módulo existe para no hacer—.
    """
    salida: list[list[dict]] = []
    pendiente: list[dict] = []

    for lote in lotes:
        actual = pendiente + lote
        pendiente = []
        # Mientras no quepa, la última página pasa al siguiente lote.
        while actual and contar_tokens(ensamblar(actual)) > tokens_por_lote:
            paginas = agrupar_por_pagina(actual)
            if len(paginas) <= 1:
                break  # una sola página que se pasa: se deja, ya se partió antes
            ultima = paginas[-1]
            claves = {id(i) for i in ultima}
            actual = [i for i in actual if id(i) not in claves]
            pendiente = ultima + pendiente
        if actual:
            salida.append(actual)

    if pendiente:
        salida.append(pendiente)
    return salida


def resumen_reparto(lotes: list[list[dict]], contar_tokens, ensamblar) -> str:
    """Una línea para el log: cuántos lotes, cuántos fragmentos y de qué tamaño."""
    if not lotes:
        return "0 lotes"
    tam = [contar_tokens(ensamblar(l)) for l in lotes]
    n = sum(len(l) for l in lotes)
    return (
        f"{len(lotes)} lote(s), {n} fragmentos, "
        f"{min(tam)}-{max(tam)} tok por lote ({sum(tam)} en total)"
    )

"""
Volcado de depuración del contexto que se envía al LLM (Fase 0 del plan de mejora).

Sustituye el `discovery_context_{localidad}.txt` suelto por un par de ficheros en
`debug_contexto/`:

  debug_contexto/{localidad}_contexto.txt   -> el texto exacto que ve el modelo
  debug_contexto/{localidad}_debug.json     -> por qué ese texto y no otro

El JSON es la herramienta con la que se validan las fases 1-5: permite responder,
sin volver a ejecutar el pipeline, a preguntas como "¿cuántos documentos distintos
hay en el contexto?", "¿qué porcentaje son duplicados?" o "¿qué puntuó por encima
de la página que la araña había puesto primera?".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger("debug_contexto")

DIR_DEBUG = Path(__file__).resolve().parent / "debug_contexto"

_RE_NO_SEGURO = re.compile(r"[^\w\-.]", re.UNICODE)

# Tope del volcado en texto plano. El .txt es para mirarlo con los ojos; el
# análisis serio sale del .json, que trae el detalle por fragmento.
#
# Desde que el contexto de discovery es TODO el material de la localidad, un
# volcado pasó de ~20 KB a 624 KB (Aranda de Duero). En una ejecución de 21
# localidades da igual —15 MB—, pero España son miles de localidades y serían
# gigabytes de depuración por ejecución. Con 300.000 caracteres se sigue viendo
# de sobra qué llegó al modelo y en qué orden.
MAX_CHARS_VOLCADO_TXT = 300_000


def _slug(nombre: str) -> str:
    return _RE_NO_SEGURO.sub("_", (nombre or "sin_nombre").strip())[:80] or "sin_nombre"


def _hash(texto: str) -> str:
    return hashlib.sha1(" ".join(texto.split()).encode("utf-8")).hexdigest()[:12]


def clave_item(item: dict) -> tuple:
    """
    Identidad de un chunk a efectos de depuración: su página y su texto.

    NO se usa `id()`. Los fragmentos que el enrichment inyecta con
    `_contexto_con_las_paginas_enteras` salen de `indexed_chunks`, mientras que
    los candidatos son copias hechas con `dict(item)`: son objetos distintos con
    el mismo contenido, así que comparar por identidad los marcaba como NO
    seleccionados aunque estuvieran en el contexto.

    Medido el 2026-09-03 en Aranda de Duero: el debug json daba los 20 chunks de
    `PROGRAMA-2026.pdf` con "seleccionado": false, y el contexto de esa misma
    llamada contenía la página. La herramienta con la que se juzgan los cambios
    mentía justo en el caso que peor salió.
    """
    return (item.get("url", ""), _hash(item.get("chunk", "")))


def _resumen_item(item: dict, seleccionado: bool, contar_tokens, lote=None) -> dict:
    chunk = item.get("chunk", "")
    return {
        "url": item.get("url", ""),
        "fuente": item.get("fuente", ""),
        "es_calendario": bool(item.get("es_calendario", False)),
        "prioridad": item.get("prioridad"),
        "relevancia_geo": item.get("relevancia_geo"),
        "score": round(float(item.get("score", 0.0)), 4),
        "score_detalle": item.get("score_detalle"),
        "score_spider": item.get("score_spider"),
        "rank_spider": item.get("rank_spider"),
        "chars": len(chunk),
        "tokens": contar_tokens(chunk),
        "hash": _hash(chunk),
        "seleccionado": seleccionado,
        # En qué lote del reparto cayó. None mientras el llamante no reparta.
        "lote": lote,
        "muestra": chunk[:180].replace("\n", " ⏎ "),
    }


def volcar_contexto(
    etapa: str,
    localidad_nombre: str,
    municipio_nombre: str,
    contexto: str,
    candidatos: list[dict],
    seleccion: list[dict],
    contar_tokens,
    presupuesto: dict | None = None,
    extra: dict | None = None,
    lotes: list[list[dict]] | None = None,
    universo: list[dict] | None = None,
) -> dict:
    """
    Escribe el contexto y su justificación. Devuelve el dict de métricas para que
    quien llame pueda loguearlo. Nunca lanza: la depuración no debe romper nada.

    `contar_tokens` se recibe por parámetro para no crear una dependencia circular
    con context_budget.

    `universo` es el material que SÍ debía llegar al modelo, cuando no coincide
    con `candidatos`. En discovery son la misma cosa y se deja a None. En
    enrichment no: el localizador elige un documento y el resto del pool deja de
    ser material a propósito —«su papel terminó cuando el localizador eligió la
    página»—, así que medir la pérdida contra el pool convierte la decisión en
    una alarma.

    Y no es una alarma inocua. En la ejecución del 2026-09-03 el volcado decía
    «29 chunks candidatos NO llegaron al modelo» y «¡TODO EL CONTEXTO VIENE DE UN
    SOLO DOCUMENTO!» en fichas que habían salido BIEN, y con esas dos líneas se
    diagnosticó un problema de reparto que no existía. Una herramienta de medida
    que grita en los casos correctos hace perder más tiempo del que ahorra.
    """
    metricas: dict = {}
    try:
        DIR_DEBUG.mkdir(exist_ok=True)
        slug = _slug(localidad_nombre)

        hashes_sel = [_hash(i.get("chunk", "")) for i in seleccion]
        cuenta_hashes = Counter(hashes_sel)
        chars_totales = sum(len(i.get("chunk", "")) for i in seleccion)
        chars_unicos = sum(
            len(i.get("chunk", ""))
            for h, i in {_hash(i.get("chunk", "")): i for i in seleccion}.items()
        )
        urls = [i.get("url", "") for i in seleccion]
        cuenta_urls = Counter(urls)

        claves_sel = {clave_item(i) for i in seleccion}
        # Cuántos candidatos no llegaron al modelo. Es LA métrica del reparto:
        # el objetivo declarado es que sea 0, porque lo que no cabe en un lote
        # debe ir en el siguiente y no desaparecer.
        #
        # Se compara por TEXTO, no por (página, texto): un fragmento repetido que
        # el reparto deduplica sí llegó al modelo —por su otra copia— y contarlo
        # como pérdida sería mentir en la dirección contraria a la de antes. Los
        # duplicados se cuentan aparte, que para eso se quitan.
        textos_sel = {h for _u, h in claves_sel}
        # Contra el universo declarado, no contra el pool: ver el docstring.
        dirigido = universo is not None
        material = universo if dirigido else candidatos
        descartados = sum(1 for i in material if _hash(i.get("chunk", "")) not in textos_sel)
        duplicados_quitados = sum(
            1 for i in material
            if clave_item(i) not in claves_sel and _hash(i.get("chunk", "")) in textos_sel
        )

        # A qué lote fue a parar cada chunk, cuando el llamante ha repartido.
        lote_por_clave: dict = {}
        if lotes:
            for n, lote in enumerate(lotes, 1):
                for i in lote:
                    lote_por_clave.setdefault(clave_item(i), n)

        metricas = {
            "etapa": etapa,
            "municipio": municipio_nombre,
            "localidad": localidad_nombre,
            "candidatos": len(candidatos),
            # Con qué se compara `descartados`. Igual a `candidatos` salvo que el
            # llamante haya acotado el material a propósito.
            "universo": len(material),
            "contexto_dirigido": dirigido,
            "seleccionados": len(seleccion),
            "descartados": descartados,
            "duplicados_quitados": duplicados_quitados,
            "n_lotes": len(lotes) if lotes else None,
            "documentos_distintos": len(cuenta_urls),
            "chunks_duplicados": sum(c - 1 for c in cuenta_hashes.values() if c > 1),
            "chars_contexto": len(contexto),
            "chars_unicos": chars_unicos,
            "pct_unico": round(100 * chars_unicos / chars_totales, 1) if chars_totales else 0.0,
            "tokens_contexto": contar_tokens(contexto),
            "top_documentos": cuenta_urls.most_common(6),
            "presupuesto": presupuesto or {},
        }
        if extra:
            metricas.update(extra)

        detalle = [
            _resumen_item(
                i, clave_item(i) in claves_sel, contar_tokens,
                lote=lote_por_clave.get(clave_item(i)),
            )
            for i in sorted(candidatos, key=lambda x: -float(x.get("score", 0.0)))[:200]
        ]

        texto_volcado = contexto
        if len(contexto) > MAX_CHARS_VOLCADO_TXT:
            texto_volcado = (
                contexto[:MAX_CHARS_VOLCADO_TXT]
                + "\n\n[... recortado para el disco: el contexto completo son "
                + f"{len(contexto)} caracteres. El detalle por fragmento, con "
                + "cuál entró y en qué lote, está en el .json de al lado ...]"
            )
        (DIR_DEBUG / f"{slug}_{etapa}_contexto.txt").write_text(texto_volcado, encoding="utf-8")
        (DIR_DEBUG / f"{slug}_{etapa}_debug.json").write_text(
            json.dumps({"metricas": metricas, "chunks": detalle}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        aviso = ""
        # Un solo documento es lo ESPERADO cuando el contexto va dirigido a un
        # documento; solo alarma cuando el material era todo el pool.
        if metricas["documentos_distintos"] <= 1 and not dirigido:
            aviso = "  <-- ¡TODO EL CONTEXTO VIENE DE UN SOLO DOCUMENTO!"
        elif metricas["pct_unico"] < 80:
            aviso = f"  <-- {100 - metricas['pct_unico']:.0f}% del contexto son DUPLICADOS"
        elif descartados:
            que = "del documento elegido" if dirigido else "candidatos"
            aviso = f"  <-- {descartados} chunks {que} NO llegaron al modelo"
        elif duplicados_quitados:
            aviso = f"  ({duplicados_quitados} repetidos quitados)"

        lotes_txt = f", {metricas['n_lotes']} lotes" if metricas["n_lotes"] else ""
        # El denominador es el universo, no el pool: decir "4/31" cuando 27 de
        # esos 31 se descartaron a propósito describe mal lo que pasó.
        de_pool = f" (de {metricas['candidatos']} del pool)" if dirigido else ""
        logger.info(
            f"  [DEBUG/{etapa}] {localidad_nombre}: {metricas['seleccionados']}/{metricas['universo']} chunks"
            f"{de_pool}{lotes_txt}, {metricas['documentos_distintos']} docs distintos, "
            f"{metricas['tokens_contexto']} tok, {metricas['pct_unico']}% único.{aviso}"
        )
    except Exception as e:
        logger.debug(f"  [DEBUG/{etapa}] No se pudo volcar la depuración: {e}")

    return metricas

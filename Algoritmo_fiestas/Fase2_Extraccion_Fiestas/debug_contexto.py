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


def _slug(nombre: str) -> str:
    return _RE_NO_SEGURO.sub("_", (nombre or "sin_nombre").strip())[:80] or "sin_nombre"


def _hash(texto: str) -> str:
    return hashlib.sha1(" ".join(texto.split()).encode("utf-8")).hexdigest()[:12]


def _resumen_item(item: dict, seleccionado: bool, contar_tokens) -> dict:
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
) -> dict:
    """
    Escribe el contexto y su justificación. Devuelve el dict de métricas para que
    quien llame pueda loguearlo. Nunca lanza: la depuración no debe romper nada.

    `contar_tokens` se recibe por parámetro para no crear una dependencia circular
    con context_budget.
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

        metricas = {
            "etapa": etapa,
            "municipio": municipio_nombre,
            "localidad": localidad_nombre,
            "candidatos": len(candidatos),
            "seleccionados": len(seleccion),
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

        ids_sel = {id(i) for i in seleccion}
        detalle = [
            _resumen_item(i, id(i) in ids_sel, contar_tokens)
            for i in sorted(candidatos, key=lambda x: -float(x.get("score", 0.0)))[:200]
        ]

        (DIR_DEBUG / f"{slug}_{etapa}_contexto.txt").write_text(contexto, encoding="utf-8")
        (DIR_DEBUG / f"{slug}_{etapa}_debug.json").write_text(
            json.dumps({"metricas": metricas, "chunks": detalle}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        aviso = ""
        if metricas["documentos_distintos"] <= 1:
            aviso = "  <-- ¡TODO EL CONTEXTO VIENE DE UN SOLO DOCUMENTO!"
        elif metricas["pct_unico"] < 80:
            aviso = f"  <-- {100 - metricas['pct_unico']:.0f}% del contexto son DUPLICADOS"

        logger.info(
            f"  [DEBUG/{etapa}] {localidad_nombre}: {metricas['seleccionados']}/{metricas['candidatos']} chunks, "
            f"{metricas['documentos_distintos']} docs distintos, "
            f"{metricas['tokens_contexto']} tok, {metricas['pct_unico']}% único.{aviso}"
        )
    except Exception as e:
        logger.debug(f"  [DEBUG/{etapa}] No se pudo volcar la depuración: {e}")

    return metricas

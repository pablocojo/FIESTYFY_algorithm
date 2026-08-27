"""
Puntuación y selección de chunks para el RAG (Fase 2 del plan de mejora).

El problema que resuelve
-----------------------
Hasta ahora el score de un chunk era la similitud coseno con la query más una
serie de bonus sueltos sumados directamente sobre ella:

    base_score = coseno(query, chunk)          # rango util ~0.30 - 0.65
    if len(patron_horas.findall(txt)) >= 3:
        base_score += 0.30                     # "casi seguro una agenda"

Dos defectos. Primero, `+0.30` sobre un coseno que se mueve en 0.35 puntos no es
un matiz: decide el ranking por sí solo. Segundo, el patrón de horas era
`\\b\\d{1,2}[:.]\\d{2}\\b`, que da 154 coincidencias sobre una tabla de partidas
presupuestarias (`3.2.2.01.` contiene `2.01`). El resultado medido en Amurrio el
2026-08-21: el PDF del presupuesto municipal de 2025 copó el 100% del contexto y
la agenda de fiestas, que la araña había puntuado la primera con 3340 puntos, no
llegó al modelo.

Cómo se resuelve
----------------
1. Todas las señales viven en 0..1 y se combinan con pesos que suman 1, de modo
   que ninguna puede dominar por accidente.
2. La similitud se normaliza dentro del conjunto de candidatos (min-max): lo que
   importa es cuál es el mejor chunk de ESTA localidad, no su coseno absoluto.
3. Se incorpora la puntuación de la araña, que ya evaluaba relevancia festiva y
   temporal a nivel de página y hasta ahora se descartaba.
4. La señal de programa usa `senales_festivas`, que exige horas distintas en
   líneas que además describan un acto.
5. Los mejores documentos según la araña tienen entrada garantizada al contexto,
   pase lo que pase con los embeddings.

Este módulo NO filtra por localidad: de eso sigue encargándose
`filtrar_chunks_por_localidad`, que se aplica después y ajusta el score según la
relevancia geográfica.
"""

from __future__ import annotations

import logging
import re

from senales_festivas import contar_actos_horarios, contar_terminos_festivos

logger = logging.getLogger("ranking")

try:
    from config import (
        RANKING_PESO_SIMILITUD,
        RANKING_PESO_SPIDER,
        RANKING_PESO_PROGRAMA,
        RANKING_PESO_TEMPORAL,
        RANKING_UMBRAL_RELATIVO,
        RANKING_UMBRAL_MINIMO,
        RANKING_DOCS_GARANTIZADOS,
        RANKING_CHUNKS_POR_DOC_GARANTIZADO,
    )
except ImportError:  # utilizable en solitario
    RANKING_PESO_SIMILITUD = 0.35
    RANKING_PESO_SPIDER = 0.25
    RANKING_PESO_PROGRAMA = 0.28
    RANKING_PESO_TEMPORAL = 0.12
    RANKING_UMBRAL_RELATIVO = 0.55
    RANKING_UMBRAL_MINIMO = 0.25
    RANKING_DOCS_GARANTIZADOS = 3
    RANKING_CHUNKS_POR_DOC_GARANTIZADO = 1

NEUTRO = 0.5          # valor de una señal cuando no hay información
FACTOR_PROGRAMA_CADUCADO = 0.30  # cuánto conserva la señal de programa si el texto es de otro año
PRIOR_SPIDER_MINIMO = 0.20  # ni la peor página de la araña baja de aquí


# ══════════════════════════════════════════════════════════════════════════════
# Señales individuales (todas devuelven 0..1)
# ══════════════════════════════════════════════════════════════════════════════

def senal_programa(chunk: str) -> float:
    """
    Cuánto se parece el chunk a un programa de actos.

    Se combina la evidencia fuerte (horas distintas en líneas que describen algo)
    con la débil (vocabulario festivo), para que un titular como "Programa de las
    fiestas de San Roque" puntúe aunque no lleve horarios.
    """
    actos = min(contar_actos_horarios(chunk) / 5.0, 1.0)
    lexico = min(contar_terminos_festivos(chunk) / 3.0, 1.0)
    return 0.70 * actos + 0.30 * lexico


_RE_ANNO = re.compile(r"\b(20\d{2})\b")


def senal_temporal(chunk: str, anno: int) -> float:
    """
    Coherencia temporal del chunk con el año objetivo.

      1.0  menciona el año objetivo
      0.0  solo menciona años anteriores (programa caducado)
      0.5  no menciona ningún año -> neutro

    El neutro importa: la mayoría de las líneas de un programa ("23:30 Verbena")
    no repiten el año, y penalizarlas expulsaría justo lo que se busca.
    """
    annos = {int(a) for a in _RE_ANNO.findall(chunk or "")}
    if not annos:
        return NEUTRO
    if anno in annos:
        return 1.0
    if any(a > anno for a in annos):
        return NEUTRO  # menciona años futuros: ni confirma ni desmiente
    return 0.0


def _priors_spider(items: list[dict]) -> dict:
    """
    Normaliza min-max las puntuaciones de la araña presentes en el conjunto,
    al rango [PRIOR_SPIDER_MINIMO, 1.0].

    Los chunks sin puntuación (redes sociales, resultados de buscador) reciben el
    valor neutro: no se les penaliza por no venir de la araña, ya que la jerarquía
    de fuentes se aplica aparte en `seleccionar_chunks`.
    """
    valores = [s for s in (i.get("score_spider") or 0 for i in items) if s > 0]
    if not valores:
        return {}
    lo, hi = min(valores), max(valores)
    if hi == lo:
        return {v: 1.0 for v in valores}
    rango = 1.0 - PRIOR_SPIDER_MINIMO
    return {v: PRIOR_SPIDER_MINIMO + rango * (v - lo) / (hi - lo) for v in set(valores)}


def _similitudes_normalizadas(items: list[dict], query_emb, coseno) -> list[float]:
    """
    Coseno reescalado min-max dentro del conjunto de candidatos.

    Se normaliza en relativo a propósito: el coseno absoluto de bge-m3 depende
    mucho del idioma y del tipo de página, y un umbral fijo (0.35) admitía tablas
    contables en unas localidades y descartaba programas en otras.
    """
    if not query_emb:
        return [NEUTRO] * len(items)
    brutos = [
        coseno(query_emb, i.get("embedding")) if i.get("embedding") else 0.0
        for i in items
    ]
    lo, hi = min(brutos), max(brutos)
    if hi - lo < 1e-9:
        return [NEUTRO] * len(items)
    return [(b - lo) / (hi - lo) for b in brutos]


# ══════════════════════════════════════════════════════════════════════════════
# Fusión
# ══════════════════════════════════════════════════════════════════════════════

def puntuar_chunks(
    items: list[dict],
    query_emb,
    anno: int,
    coseno,
    pesos: dict | None = None,
    señales_extra=None,
) -> list[dict]:
    """
    Escribe `score` (0..1) y `score_detalle` en cada item. Modifica los items
    recibidos y los devuelve.

    `coseno` se recibe por parámetro para no depender de AsyncRAGProcessor y poder
    probar el módulo en solitario.
    `señales_extra` es un callable opcional (item -> float en 0..1) que se mezcla
    con peso propio; lo usa el enrichment para el ajuste "menciona el día exacto".
    """
    if not items:
        return items

    p = {
        "similitud": RANKING_PESO_SIMILITUD,
        "spider": RANKING_PESO_SPIDER,
        "programa": RANKING_PESO_PROGRAMA,
        "temporal": RANKING_PESO_TEMPORAL,
    }
    if pesos:
        p.update(pesos)
    total = sum(p.values()) or 1.0

    priors = _priors_spider(items)
    sims = _similitudes_normalizadas(items, query_emb, coseno)

    for item, sim in zip(items, sims):
        chunk = item.get("chunk", "")
        s_spider = priors.get(item.get("score_spider") or 0, NEUTRO)
        s_prog = senal_programa(chunk)
        s_temp = senal_temporal(chunk, anno)

        # Un programa CADUCADO es el material más peligroso que puede llegar al
        # modelo: se parece muchísimo a lo que se busca (misma fiesta, mismos
        # actos, mismo vocabulario) pero con las fechas del año equivocado. Que
        # parezca un programa deja de ser un mérito cuando el propio texto dice
        # que es de otro año. No afecta a las líneas sin año, que son la mayoría
        # de un programa real y siguen valiendo lo mismo.
        if s_temp == 0.0:
            s_prog *= FACTOR_PROGRAMA_CADUCADO

        detalle = {
            "similitud": round(sim, 4),
            "spider": round(s_spider, 4),
            "programa": round(s_prog, 4),
            "temporal": round(s_temp, 4),
        }
        acumulado = (
            p["similitud"] * sim
            + p["spider"] * s_spider
            + p["programa"] * s_prog
            + p["temporal"] * s_temp
        )
        if señales_extra is not None:
            s_extra = max(0.0, min(1.0, float(señales_extra(item))))
            peso_extra = p.get("extra", 0.20)
            detalle["extra"] = round(s_extra, 4)
            acumulado += peso_extra * s_extra
            item["score"] = acumulado / (total + peso_extra)
        else:
            item["score"] = acumulado / total

        item["score_detalle"] = detalle
    return items


def umbral_adaptativo(
    items: list[dict],
    fraccion: float = None,
    minimo: float = None,
) -> float:
    """
    Umbral relativo al mejor chunk del conjunto, con un suelo absoluto.

    Un umbral fijo no funciona sobre una escala normalizada por conjunto: en una
    localidad con material excelente y en otra donde no hay nada, el mejor chunk
    puntúa parecido. Lo que se quiere es "quédate con lo que se acerca a lo mejor
    que hay aquí".
    """
    fraccion = RANKING_UMBRAL_RELATIVO if fraccion is None else fraccion
    minimo = RANKING_UMBRAL_MINIMO if minimo is None else minimo
    if not items:
        return minimo
    mejor = max((i.get("score", 0.0) for i in items), default=0.0)
    return max(minimo, fraccion * mejor)


def chunks_garantizados(
    items: list[dict],
    anno: int | None = None,
    top_docs: int = None,
    por_documento: int = None,
) -> list[dict]:
    """
    Reserva de plazas para los mejores documentos según la araña.

    La araña dedica varios minutos a puntuar las páginas por relevancia festiva y
    temporal, y acierta: en Amurrio colocó `amurrioturismo.com/agenda-amurrio` la
    primera con 3340 puntos y el calendario de eventos de 2026 con 1650. Que un
    fallo de embeddings pueda dejar fuera esas páginas es un riesgo que no merece
    la pena correr, así que entran al contexto por derecho propio.

    Con una excepción: la garantía NO pasa por encima de un veto temporal. Un
    chunk cuyo propio texto dice que es de un año anterior (el programa del año
    pasado, una noticia de hace dos) es justo el material que hace que el modelo
    extraiga fechas equivocadas. Si un documento no tiene ningún chunk utilizable,
    su plaza pasa al siguiente documento de la lista.
    """
    top_docs = RANKING_DOCS_GARANTIZADOS if top_docs is None else top_docs
    por_documento = RANKING_CHUNKS_POR_DOC_GARANTIZADO if por_documento is None else por_documento
    if not items or top_docs <= 0:
        return []

    mejor_por_url: dict[str, int] = {}
    for i in items:
        s = i.get("score_spider") or 0
        if s <= 0:
            continue
        url = i.get("url", "")
        if s > mejor_por_url.get(url, -1):
            mejor_por_url[url] = s
    if not mejor_por_url:
        return []

    orden = [u for u, _ in sorted(mejor_por_url.items(), key=lambda kv: -kv[1])]
    garantizados: list[dict] = []
    docs_cubiertos = 0
    for url in orden:
        if docs_cubiertos >= top_docs:
            break
        candidatos = sorted(
            (i for i in items if i.get("url", "") == url),
            key=lambda i: -i.get("score", 0.0),
        )
        if anno is not None:
            candidatos = [c for c in candidatos if senal_temporal(c.get("chunk", ""), anno) > 0.0]
        if not candidatos:
            continue  # documento caducado: su plaza pasa al siguiente
        garantizados.extend(candidatos[:por_documento])
        docs_cubiertos += 1
    return garantizados

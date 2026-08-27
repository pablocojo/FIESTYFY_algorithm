"""
Higiene de documentos previa al RAG (Fase 1 del plan de mejora del contexto).

Los documentos que recoge la Fase 2 llegan al RAG con tres problemas que
desperdician el presupuesto de contexto antes de que ningún ranking pueda
intervenir:

  1. DUPLICADOS. El mismo PDF enlazado desde tres páginas se descarga e indexa
     tres veces. En la ejecución de Amurrio del 2026-08-21, el contexto de
     discovery tenía 21.409 caracteres pero solo 7.411 de información única:
     el 65% eran copias literales de la misma tabla.
  2. BOILERPLATE. Ochenta y tres páginas del mismo gestor de contenidos comparten
     menús, avisos de cookies y pie de página.
  3. TABLAS DE CIFRAS. Presupuestos, padrones y listados contables no contienen
     fiestas, pero sí muchos números que confunden a las heurísticas.

Este módulo los quita antes de trocear. Es puro filtrado: no reordena ni puntúa.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from collections import Counter, defaultdict

from senales_festivas import parece_programa_de_actos, tiene_termino_festivo

logger = logging.getLogger("higiene")

# ── Parámetros (sobreescribibles desde config.py) ────────────────────────────
try:
    from config import (
        HIGIENE_DEDUP_ENABLED,
        HIGIENE_JACCARD_UMBRAL,
        HIGIENE_BOILERPLATE_ENABLED,
        HIGIENE_BOILERPLATE_UMBRAL,
        HIGIENE_BOILERPLATE_MIN_DOCS,
        HIGIENE_TABULAR_ENABLED,
        HIGIENE_TABULAR_DENSIDAD,
        HIGIENE_TABULAR_RATIO,
    )
except ImportError:  # el módulo debe seguir siendo usable/testable en solitario
    HIGIENE_DEDUP_ENABLED = True
    HIGIENE_JACCARD_UMBRAL = 0.90
    HIGIENE_BOILERPLATE_ENABLED = True
    HIGIENE_BOILERPLATE_UMBRAL = 0.40
    HIGIENE_BOILERPLATE_MIN_DOCS = 8
    HIGIENE_TABULAR_ENABLED = True
    HIGIENE_TABULAR_DENSIDAD = 0.25
    HIGIENE_TABULAR_RATIO = 0.80

_PARAMS_TRACKING = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "_ga", "ref", "referrer", "mc_cid", "mc_eid",
})


# ══════════════════════════════════════════════════════════════════════════════
# URLs
# ══════════════════════════════════════════════════════════════════════════════

def canonicalizar_url(url: str) -> str:
    """
    Forma canónica de una URL para comparar identidad: sin esquema, sin `www.`,
    sin fragmento, sin parámetros de tracking, sin barra final y en minúsculas
    salvo la ruta (que en algunos servidores sí distingue mayúsculas).
    """
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url.strip())
        netloc = p.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        consulta = [
            (k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in _PARAMS_TRACKING
        ]
        ruta = p.path.rstrip("/") or "/"
        return urllib.parse.urlunparse(
            ("", netloc, ruta, "", urllib.parse.urlencode(sorted(consulta)), "")
        ).lstrip("/") or netloc
    except Exception:
        return url.strip().lower()


def dominio(url: str) -> str:
    try:
        d = urllib.parse.urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# Duplicados y casi-duplicados
# ══════════════════════════════════════════════════════════════════════════════

def _normalizar_para_comparar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip().lower()


def hash_texto(texto: str) -> str:
    return hashlib.sha1(_normalizar_para_comparar(texto).encode("utf-8")).hexdigest()


# Para firmar no hace falta leer documentos enteros: dos casi-duplicados lo son
# ya en su primer tramo, y esto acota el coste en PDFs de cientos de miles de
# caracteres que se firman una vez por localidad.
MAX_CHARS_FIRMA = 200_000


def firma_documento(texto: str, k: int = 5, tamano: int = 64) -> frozenset:
    """
    Firma tipo MinHash: los `tamano` hashes más pequeños de los n-gramas de `k`
    palabras. Permite estimar el índice de Jaccard entre dos documentos sin
    comparar sus textos completos, que aquí pueden ser de cientos de miles de
    caracteres.
    """
    palabras = _normalizar_para_comparar(texto[:MAX_CHARS_FIRMA]).split()
    if len(palabras) < k:
        return frozenset({hash_texto(texto)})
    hashes = {
        hashlib.blake2b(" ".join(palabras[i:i + k]).encode("utf-8"), digest_size=8).digest()
        for i in range(len(palabras) - k + 1)
    }
    return frozenset(sorted(hashes)[:tamano])


# Los documentos de la web del municipio se reutilizan en todas sus pedanías, así
# que la misma firma se pediría una vez por localidad. Se cachea por hash del
# texto (y no en el propio documento, que no debe llevar campos no serializables).
_CACHE_FIRMAS: dict[str, frozenset] = {}
_MAX_CACHE_FIRMAS = 4096


def _firma_cacheada(texto: str) -> frozenset:
    clave = hash_texto(texto)
    firma = _CACHE_FIRMAS.get(clave)
    if firma is None:
        firma = firma_documento(texto)
        if len(_CACHE_FIRMAS) >= _MAX_CACHE_FIRMAS:
            _CACHE_FIRMAS.clear()
        _CACHE_FIRMAS[clave] = firma
    return firma


def similitud_jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ── Páginas fechadas: nunca son casi-duplicadas entre sí ─────────────────────
# Una agenda municipal publica una página por día. Todas comparten el mismo
# menú de navegación (categorías, meses, años) y se diferencian en una sola
# línea, así que su Jaccard sobre el documento COMPLETO supera de largo el 0.90
# y el dedup las colapsaba. Medido en Amurrio el 2026-08-21: la araña trajo las
# 31 páginas de agosto y la higiene borró 24 como "similares", entre ellas el
# día 11 (inicio de las fiestas) y el 16 (San Roque).
#
# Dos páginas cuya URL declara fechas DISTINTAS no son el mismo documento, por
# mucho texto de plantilla que compartan. Se comparan solo contra las de su
# misma fecha.
_RE_FECHAS_URL = (
    re.compile(r"/((?:19|20)\d{2})/([0-1]?\d)/([0-3]?\d)(?:/|$|\?)"),        # /2026/8/11/
    re.compile(r"/([0-3]?\d)[/-]([0-1]?\d)[/-]((?:19|20)\d{2})(?:/|$|\?)"),  # /11-8-2026/
    # Las alternativas van de más larga a más corta a propósito: con
    # (0?[1-9]|[12]\d|3[01]) el motor casa "1" dentro de "11" y devuelve día 1.
    re.compile(r"((?:19|20)\d{2})[-_.](1[0-2]|0?[1-9])[-_.](3[01]|[12]\d|0?[1-9])"),  # 2026-08-11
    re.compile(r"[?&](?:fecha|date)=((?:19|20)\d{2})[-/](1[0-2]|0?[1-9])[-/](3[01]|[12]\d|0?[1-9])"),
)


def clave_fecha_url(url: str) -> str | None:
    """
    Fecha declarada en la URL, normalizada a 'YYYY-MM-DD'. None si no la lleva.

    Se normaliza para que /2026/8/11/ y /2026/08/11/ den la misma clave: son la
    misma página del calendario y ahí sí queremos que el dedup actúe.
    """
    if not url:
        return None
    for i, patron in enumerate(_RE_FECHAS_URL):
        m = patron.search(url)
        if not m:
            continue
        if i == 1:  # día/mes/año
            dia, mes, anno = m.group(1), m.group(2), m.group(3)
        else:       # año/mes/día
            anno, mes, dia = m.group(1), m.group(2), m.group(3)
        try:
            return f"{int(anno):04d}-{int(mes):02d}-{int(dia):02d}"
        except ValueError:
            continue
    return None


def _valor_documento(doc: dict) -> tuple:
    """Criterio para quedarse con el mejor de un grupo de duplicados."""
    return (
        int(doc.get("score_spider") or 0),
        1 if parece_programa_de_actos(doc.get("texto", "")) else 0,
        len(doc.get("texto") or ""),
    )


def deduplicar_documentos(documentos: list[dict], umbral: float = None) -> tuple[list[dict], dict]:
    """
    Quita duplicados exactos (misma URL canónica o mismo texto) y casi-duplicados
    (Jaccard sobre firmas > `umbral`). De cada grupo conserva el documento más
    valioso: mayor puntuación de la araña, luego el que parezca un programa,
    luego el más largo.

    Devuelve (documentos, métricas).
    """
    umbral = HIGIENE_JACCARD_UMBRAL if umbral is None else umbral
    metricas = {"entrada": len(documentos), "por_url": 0, "por_hash": 0, "por_similitud": 0}
    if not documentos:
        return [], metricas

    # 1) Exactos: agrupar por URL canónica y por hash de texto.
    grupos: dict[str, list[dict]] = defaultdict(list)
    for doc in documentos:
        url_can = canonicalizar_url(doc.get("url", ""))
        clave = f"u:{url_can}" if url_can else f"h:{hash_texto(doc.get('texto', ''))}"
        grupos[clave].append(doc)

    tras_url = []
    for clave, grupo in grupos.items():
        if len(grupo) > 1:
            metricas["por_url" if clave.startswith("u:") else "por_hash"] += len(grupo) - 1
        tras_url.append(max(grupo, key=_valor_documento))

    por_hash: dict[str, dict] = {}
    for doc in tras_url:
        h = hash_texto(doc.get("texto", ""))
        if h in por_hash:
            metricas["por_hash"] += 1
            if _valor_documento(doc) > _valor_documento(por_hash[h]):
                por_hash[h] = doc
        else:
            por_hash[h] = doc
    tras_hash = list(por_hash.values())

    # 2) Casi-duplicados: comparar firmas solo contra los ya conservados.
    #    Las páginas con fecha en la URL se comparan únicamente contra las de su
    #    misma fecha: días distintos de una agenda comparten la plantilla pero no
    #    son el mismo documento (ver _RE_FECHAS_URL).
    conservados: list[tuple[frozenset, dict, str | None]] = []
    for doc in sorted(tras_hash, key=_valor_documento, reverse=True):
        firma = _firma_cacheada(doc.get("texto", ""))
        fecha_doc = clave_fecha_url(doc.get("url", ""))
        gemelo = None
        for firma_prev, doc_prev, fecha_prev in conservados:
            if fecha_doc != fecha_prev:
                continue  # fechas distintas (o una fechada y otra no): no comparables
            if similitud_jaccard(firma, firma_prev) >= umbral:
                gemelo = doc_prev
                break
        if gemelo is None:
            conservados.append((firma, doc, fecha_doc))
        else:
            metricas["por_similitud"] += 1

    salida = [doc for _, doc, _fecha in conservados]
    metricas["salida"] = len(salida)
    metricas["eliminados"] = metricas["entrada"] - metricas["salida"]
    return salida, metricas


# ══════════════════════════════════════════════════════════════════════════════
# Tablas de cifras
# ══════════════════════════════════════════════════════════════════════════════

_RE_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}")
_RE_NUMERO = re.compile(r"\d[\d.,]*")


def es_texto_tabular(
    texto: str,
    densidad_min: float = None,
    ratio_max: float = None,
) -> bool:
    """
    True si el texto parece una tabla de cifras (presupuesto, padrón, listado
    contable) y no prosa ni un programa.

    Calibrado sobre material real:
        presupuesto municipal   densidad 0.43, palabras/números 0.31 -> tabular
        padrón por edades       densidad 0.46, palabras/números 0.29 -> tabular
        programa de fiestas     densidad 0.07, palabras/números 2.52 -> NO
        programa en tabla       densidad 0.28, palabras/números 1.00 -> NO

    Un texto que contenga un programa de actos reconocible nunca se marca como
    tabular, por muchos números que lleve: hay programas maquetados como tabla.
    """
    densidad_min = HIGIENE_TABULAR_DENSIDAD if densidad_min is None else densidad_min
    ratio_max = HIGIENE_TABULAR_RATIO if ratio_max is None else ratio_max

    texto = texto or ""
    if len(texto) < 200:  # demasiado corto para juzgarlo con densidades
        return False
    if parece_programa_de_actos(texto):
        return False

    digitos = sum(c.isdigit() for c in texto)
    densidad = digitos / len(texto)
    if densidad < densidad_min:
        return False

    palabras = len(_RE_PALABRA.findall(texto))
    numeros = len(_RE_NUMERO.findall(texto))
    return (palabras / numeros if numeros else 99.0) <= ratio_max


# ══════════════════════════════════════════════════════════════════════════════
# Boilerplate
# ══════════════════════════════════════════════════════════════════════════════

def eliminar_boilerplate(
    documentos: list[dict],
    umbral: float = None,
    min_docs: int = None,
) -> tuple[list[dict], dict]:
    """
    Quita de cada página las líneas que se repiten en más del `umbral` de las
    páginas de su mismo dominio: menús de navegación, avisos de cookies, pies.

    Solo se aplica a documentos de tipo "pagina" (los PDFs y los carteles OCR no
    comparten plantilla) y solo cuando hay al menos `min_docs` páginas del mismo
    dominio, que es cuando la frecuencia es significativa.

    Nunca elimina una línea con contenido festivo, una fecha o una hora, y nunca
    deja un documento con menos del 40% de su texto original.
    """
    umbral = HIGIENE_BOILERPLATE_UMBRAL if umbral is None else umbral
    min_docs = HIGIENE_BOILERPLATE_MIN_DOCS if min_docs is None else min_docs
    metricas = {"lineas_eliminadas": 0, "dominios_tratados": 0, "docs_tratados": 0}
    if not documentos:
        return documentos, metricas

    por_dominio: dict[str, list[dict]] = defaultdict(list)
    for doc in documentos:
        if doc.get("tipo", "pagina") == "pagina":
            por_dominio[dominio(doc.get("url", ""))].append(doc)

    for dom, docs in por_dominio.items():
        if not dom or len(docs) < min_docs:
            continue

        frecuencia = Counter()
        for doc in docs:
            frecuencia.update({
                _normalizar_para_comparar(l) for l in (doc.get("texto") or "").split("\n") if l.strip()
            })

        corte = umbral * len(docs)
        comunes = {
            linea for linea, n in frecuencia.items()
            if n > corte
            and not tiene_termino_festivo(linea)
            and not re.search(r"\d{1,2}[:.][0-5]\d|\d{1,2}[/-]\d{1,2}|20\d{2}", linea)
        }
        if not comunes:
            continue

        metricas["dominios_tratados"] += 1
        for doc in docs:
            original = doc.get("texto") or ""
            lineas = original.split("\n")
            filtradas = [l for l in lineas if _normalizar_para_comparar(l) not in comunes]
            nuevo = "\n".join(filtradas)
            # Salvaguarda: no vaciar un documento por un exceso de coincidencias.
            if len(nuevo) < 0.4 * len(original):
                continue
            if len(lineas) != len(filtradas):
                metricas["lineas_eliminadas"] += len(lineas) - len(filtradas)
                metricas["docs_tratados"] += 1
                doc["texto"] = nuevo

    return documentos, metricas


# ══════════════════════════════════════════════════════════════════════════════
# Orquestador
# ══════════════════════════════════════════════════════════════════════════════

def limpiar_documentos(documentos: list[dict], etiqueta: str = "") -> tuple[list[dict], dict]:
    """
    Aplica toda la higiene y deja constancia en el log de cuánto se ha recuperado.
    Se llama una vez por localidad, justo antes de trocear e indexar.
    """
    if not documentos:
        return documentos, {}

    chars_inicio = sum(len(d.get("texto") or "") for d in documentos)
    n_inicio = len(documentos)
    metricas: dict = {"docs_entrada": n_inicio, "chars_entrada": chars_inicio}

    if HIGIENE_DEDUP_ENABLED:
        documentos, m_dedup = deduplicar_documentos(documentos)
        metricas["dedup"] = m_dedup

    if HIGIENE_TABULAR_ENABLED:
        antes = len(documentos)
        documentos = [d for d in documentos if not es_texto_tabular(d.get("texto", ""))]
        metricas["tablas_descartadas"] = antes - len(documentos)

    if HIGIENE_BOILERPLATE_ENABLED:
        documentos, m_boiler = eliminar_boilerplate(documentos)
        metricas["boilerplate"] = m_boiler

    chars_fin = sum(len(d.get("texto") or "") for d in documentos)
    metricas.update(
        docs_salida=len(documentos),
        chars_salida=chars_fin,
        pct_chars_recuperado=round(100 * (chars_inicio - chars_fin) / chars_inicio, 1) if chars_inicio else 0.0,
    )

    d = metricas.get("dedup", {})
    logger.info(
        f"    [HIGIENE{'/' + etiqueta if etiqueta else ''}] "
        f"{n_inicio} → {len(documentos)} docs "
        f"(dup url:{d.get('por_url', 0)} texto:{d.get('por_hash', 0)} similares:{d.get('por_similitud', 0)}, "
        f"tablas:{metricas.get('tablas_descartadas', 0)}) | "
        f"{chars_inicio:,} → {chars_fin:,} chars "
        f"(-{metricas['pct_chars_recuperado']}%), "
        f"boilerplate: {metricas.get('boilerplate', {}).get('lineas_eliminadas', 0)} líneas"
    )
    return documentos, metricas

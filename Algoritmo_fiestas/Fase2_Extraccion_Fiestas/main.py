"""
Orquestador Principal — Fase 2: Extracción de Fiestas (Async).

Procesa municipios en paralelo (batches de N), con cada localidad
ejecutando su pipeline completo: Spider → DDG → RAG → LLM → Validación.
"""

import json
import os
import sys
import asyncio
import argparse
import logging
from datetime import datetime

from state_manager import StateManager
from scraper.heuristic_spider import AsyncTwoPassSpider
from scraper.google_search import search_locality_web
from scraper.social_content import cargar_documentos_rrss
from scraper.social_finder import registrar_perfiles_web
from llm_processor.text_analyzer import AsyncRAGProcessor, analyze_festivals_for_locality
from llm_processor.patron_finder import obtener_patron, integrar_patron, fecha_del_patron
from fuentes import FUENTE_WEB_LOCALIDAD, FUENTE_WEB_MUNICIPIO, fuente_base
from config import (
    PARALLEL_MUNICIPALITIES,
    PATRON_SEARCH_ENABLED,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    LOG_LEVEL,
)

# ──────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────

def setup_logging():
    """Configura logging a consola + archivo."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"fase2_{timestamp}.log"

    # Crear handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Configurar root logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger("main")


# ──────────────────────────────────────────
# CARGA Y AGRUPACIÓN DE DATOS
# ──────────────────────────────────────────

def cargar_lugares(ruta_json: str) -> list[dict]:
    with open(ruta_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Soportar tanto formato wrapper {"version":N, "lugares":[...]} como array directo
    if isinstance(data, dict) and "lugares" in data:
        return data["lugares"]
    return data


def agrupar_municipios_y_descendientes(lugares: list[dict]) -> tuple:
    """Agrupa localidades por municipio raíz, contemplando padre_id y abuelo_id."""
    tipos_raiz = {"municipio"}
    municipios_raiz = []
    mapa_descendientes = {}

    for lugar in lugares:
        if lugar["tipo"] in tipos_raiz:
            municipios_raiz.append(lugar)
            mapa_descendientes[lugar["id"]] = []

    for lugar in lugares:
        padre = lugar.get("padre_id")
        abuelo = lugar.get("abuelo_id")

        if padre and padre in mapa_descendientes:
            mapa_descendientes[padre].append(lugar)
        elif abuelo and abuelo in mapa_descendientes:
            mapa_descendientes[abuelo].append(lugar)

    return municipios_raiz, mapa_descendientes


def separar_por_tipo(descendientes: list[dict]) -> tuple:
    tipos_validos = {"pueblo", "ciudad_pequena", "ciudad_grande", "distrito", "barrio"}
    capitales = []
    otros = []
    for d in descendientes:
        if d.get("tipo") not in tipos_validos:
            continue
        if d.get("es_capital"):
            capitales.append(d)
        else:
            otros.append(d)
    return capitales, otros


# ──────────────────────────────────────────
# PROCESAMIENTO DE UNA LOCALIDAD
# ──────────────────────────────────────────

async def process_locality(
    localidad: dict,
    municipio: dict,
    anno: int,
    rag_processor: AsyncRAGProcessor,
    logger: logging.Logger,
) -> list[dict]:
    """
    Pipeline completo para una localidad, en orden de fiabilidad de fuentes:
    web localidad → web municipio → RRSS (caché) → búsqueda browser → RAG → LLM.
    """
    logger.info(
        f"    --> Buscando fiestas para: {localidad['nombre']} "
        f"(Tipo: {localidad.get('tipo', 'localidad')})"
    )

    # 0. Santo patrón (en paralelo con el scraping)
    patron_task = None
    if PATRON_SEARCH_ENABLED:
        patron_task = asyncio.create_task(obtener_patron(localidad, municipio))

    async def _esperar_patron() -> dict | None:
        if patron_task is None:
            return None
        try:
            return await patron_task
        except Exception as e:
            logger.warning(f"    [!] Error buscando el patrón de {localidad['nombre']}: {e}")
            return None

    documentos: list[dict] = []
    visited_urls: set[str] = set()  # compartido entre TODAS las fuentes: nada se lee dos veces

    sitio_mun = municipio.get("sitio_web", "").strip()
    sitio_loc = localidad.get("sitio_web", "").strip()
    # La web de la localidad solo cuenta si NO está vacía y es distinta de la del padre
    loc_tiene_web_propia = bool(sitio_loc) and sitio_loc.rstrip("/") != sitio_mun.rstrip("/")

    # 1. Web oficial de la LOCALIDAD (fiabilidad máxima)
    if loc_tiene_web_propia:
        logger.info(f"    --> [1/5] Araña en web de la localidad: {sitio_loc}")
        spider = AsyncTwoPassSpider()
        documentos += await spider.crawl(
            sitio_loc, [localidad["nombre"]], FUENTE_WEB_LOCALIDAD, visited_urls
        )
        # Perfiles RRSS enlazados desde la web propia de la localidad
        await registrar_perfiles_web(localidad, spider.social_links)

    # 2. Web oficial del MUNICIPIO
    if sitio_mun:
        logger.info(f"    --> [2/5] Araña en web del municipio: {sitio_mun}")
        spider = AsyncTwoPassSpider()
        documentos += await spider.crawl(
            sitio_mun, [localidad["nombre"]], FUENTE_WEB_MUNICIPIO, visited_urls
        )
        # Perfiles RRSS del municipio (la caché evita repetir por cada pedanía)
        await registrar_perfiles_web(municipio, spider.social_links)

    # 3-4. RRSS de la localidad y del municipio (desde la caché del runner de apps)
    documentos += cargar_documentos_rrss(localidad, municipio)

    # 5. Búsqueda browser (la menos fiable; no relee URLs de los pasos anteriores)
    logger.info(f"    --> [5/5] Búsqueda en buscadores...")
    documentos += await search_locality_web(localidad, municipio, anno, visited_urls)

    # El patrón ya debería estar resuelto (corría en paralelo con el scraping)
    patron = await _esperar_patron()
    fecha_patron = fecha_del_patron(patron, anno)

    documentos = [d for d in documentos if (d.get("texto") or "").strip()]
    if not documentos:
        logger.warning(f"    [!] No se extrajo ningún texto para {localidad['nombre']}.")
        return integrar_patron([], patron, anno, localidad)

    # Métrica: documentos por fuente
    conteo_fuentes = {}
    for d in documentos:
        base = fuente_base(d["fuente"])
        conteo_fuentes[base] = conteo_fuentes.get(base, 0) + 1
    total_chars = sum(len(d["texto"]) for d in documentos)
    logger.info(f"    Recopilados {len(documentos)} documentos ({total_chars} chars): {conteo_fuentes}")

    # RAG: chunking por documento + selección por cuotas de fuente
    query_rag = (
        f"Fiestas, carteles y programas de actos en {municipio['nombre']} "
        f"para la localidad de {localidad['nombre']} en el año {anno}"
    )
    contexto, fuentes_contexto = await rag_processor.saturate_context_docs(documentos, query_rag)

    if not contexto.strip():
        logger.warning(f"    [!] RAG no seleccionó texto relevante para {localidad['nombre']}.")
        return integrar_patron([], patron, anno, localidad)

    # LLM + validación (filtro adaptativo con el día del patrón + fuentes)
    fiestas = await analyze_festivals_for_locality(
        municipio, localidad, contexto, anno, fecha_patron, fuentes_contexto
    )

    # Marcar fiestas que incluyen el día del patrón / añadir estimada si no está cubierto
    fiestas = integrar_patron(fiestas, patron, anno, localidad)

    for f in fiestas:
        if "lat" in localidad and "lng" in localidad:
            f["lat"] = localidad["lat"]
            f["lng"] = localidad["lng"]

    logger.info(f"    -- Resultado: {len(fiestas)} fiestas para {localidad['nombre']}")
    return fiestas


# ──────────────────────────────────────────
# PROCESAMIENTO DE UN MUNICIPIO COMPLETO
# ──────────────────────────────────────────

async def process_municipio(
    municipio: dict,
    descendientes: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor,
    state_mgr: StateManager,
    indice: int,
    total: int,
    logger: logging.Logger,
):
    """Procesa todas las localidades de un municipio secuencialmente."""
    logger.info(f"\n[{indice + 1}/{total}] === Procesando: {municipio['nombre']} ===")

    if not descendientes:
        logger.info(f"  -> Omitiendo: No tiene localidades hijas.")
        await state_mgr.guardar_estado([], municipio["id"])
        return

    capitales, otros = separar_por_tipo(descendientes)
    fiestas_municipio = []

    locs_completadas = state_mgr.state.get("localidades_completadas", [])

    # Procesar localidades secuencialmente (comparten el mismo sitio web municipal)
    todas_localidades = capitales + otros
    for j, loc in enumerate(todas_localidades):
        if loc["id"] in locs_completadas:
            logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']} (Omitiendo, ya procesada temporalmente)")
            continue
            
        logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']}")
        try:
            fiestas_loc = await process_locality(loc, municipio, anno, rag_processor, logger)
            fiestas_municipio.extend(fiestas_loc)
            # Volcado temporal tras finalizar esta localidad
            await state_mgr.guardar_estado_localidad(fiestas_loc, loc["id"])
        except Exception as e:
            logger.error(f"  [ERROR] Fallo procesando {loc['nombre']}: {e}")

    # Guardar progreso al finalizar el municipio completo
    # Se pasa lista vacía de fiestas porque ya se han guardado todas progresivamente
    await state_mgr.guardar_estado([], municipio["id"])


# ──────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ──────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(description="Fase 2: Extracción de Fiestas (Async)")
    parser.add_argument("--anno", type=int, default=2026, help="Año de búsqueda")
    parser.add_argument("--input", type=str, default="../lugares_espana.json", help="Ruta JSON de lugares")
    parser.add_argument("--output", type=str, default="fiestas_espana.json", help="Ruta JSON de salida")
    parser.add_argument("--parallel", type=int, default=PARALLEL_MUNICIPALITIES, help="Municipios en paralelo")
    args = parser.parse_args()

    logger = setup_logging()

    logger.info(f"{'=' * 60}")
    logger.info(f"  FASE 2: EXTRACCIÓN DE FIESTAS ({args.anno})")
    from config import LMSTUDIO_CHAT_MODEL
    logger.info(f"  Modelo: {LMSTUDIO_CHAT_MODEL} | Paralelismo: {args.parallel} municipios")
    logger.info(f"{'=' * 60}")

    if not os.path.exists(args.input):
        logger.error(f"No se encuentra el archivo de entrada: {args.input}")
        return

    # Cargar datos
    lugares = cargar_lugares(args.input)
    municipios_raiz, mapa_descendientes = agrupar_municipios_y_descendientes(lugares)

    logger.info(f"Municipios raíz encontrados: {len(municipios_raiz)}")

    # Estado y reanudación
    state_mgr = StateManager(args.output, anno=args.anno)
    state_mgr.cargar_estado()

    # Filtrar municipios ya completados
    pendientes = []
    for i, mun in enumerate(municipios_raiz):
        if not state_mgr.esta_completado(mun["id"]):
            desc = mapa_descendientes.get(mun["id"], [])
            pendientes.append((i, mun, desc))

    logger.info(f"Municipios pendientes: {len(pendientes)} (de {len(municipios_raiz)} totales)")

    if not pendientes:
        logger.info("¡Todos los municipios ya fueron procesados!")
        return

    # Inicializar RAG Processor
    rag_processor = AsyncRAGProcessor()

    # Procesar en batches paralelos
    total = len(municipios_raiz)
    batch_size = args.parallel

    for batch_start in range(0, len(pendientes), batch_size):
        batch = pendientes[batch_start : batch_start + batch_size]

        logger.info(
            f"\n{'-' * 50}\n"
            f"Batch {batch_start // batch_size + 1}: "
            f"Procesando {len(batch)} municipios en paralelo\n"
            f"{'-' * 50}"
        )

        tasks = [
            process_municipio(
                mun, desc, args.anno, rag_processor, state_mgr, idx, total, logger
            )
            for idx, mun, desc in batch
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  EXTRACCIÓN COMPLETADA")
    logger.info(f"  Total fiestas: {len(state_mgr.state['fiestas'])}")
    logger.info(f"{'=' * 60}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

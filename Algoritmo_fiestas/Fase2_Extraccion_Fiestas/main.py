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
from llm_processor.text_analyzer import AsyncRAGProcessor, analyze_festivals_for_locality
from config import (
    PARALLEL_MUNICIPALITIES,
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
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Configurar root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)

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
    tipos_raiz = {"pueblo", "ciudad_pequena", "ciudad_grande", "municipio_compuesto"}
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
    barrios_distritos = []
    pedanias = []
    for d in descendientes:
        tipo = d.get("tipo", "")
        if tipo in ("barrio", "distrito"):
            barrios_distritos.append(d)
        elif tipo == "pedania":
            pedanias.append(d)
    return barrios_distritos, pedanias


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
    """Pipeline completo para una localidad: Spider + DDG + RAG + LLM."""
    logger.info(
        f"    --> Buscando fiestas para: {localidad['nombre']} "
        f"(Tipo: {localidad.get('tipo', 'localidad')})"
    )

    # 1. Spider web municipal (centrado en la localidad)
    texto_municipal = ""
    if municipio.get("sitio_web"):
        spider = AsyncTwoPassSpider()
        texto_municipal = await spider.crawl(
            municipio["sitio_web"],
            [localidad["nombre"]],
        )

    # 2. Búsqueda externa DDG (en paralelo con spider ya terminado)
    texto_busquedas = await search_locality_web(localidad, municipio, anno)

    texto_total = texto_municipal + "\n" + texto_busquedas

    if not texto_total.strip():
        logger.warning(f"    [!] No se extrajo ningún texto para {localidad['nombre']}.")
        return []

    logger.info(f"    Texto total recopilado: {len(texto_total)} caracteres")

    # 3. RAG: Saturar contexto con límite para Qwen 2.5 7B
    query_rag = (
        f"Fiestas, carteles y programas de actos en {municipio['nombre']} "
        f"para la localidad de {localidad['nombre']} en el año {anno}"
    )
    texto_filtrado = await rag_processor.saturate_context(texto_total, query_rag)

    if not texto_filtrado.strip():
        logger.warning(f"    [!] RAG no seleccionó texto relevante para {localidad['nombre']}.")
        return []

    # 4. LLM Generation + Validación
    fiestas = await analyze_festivals_for_locality(municipio, localidad, texto_filtrado, anno)
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
    logger.info(f"\n[{indice + 1}/{total}] ═══ Procesando: {municipio['nombre']} ═══")

    if not descendientes:
        logger.info(f"  -> Omitiendo: No tiene localidades hijas.")
        await state_mgr.guardar_estado([], municipio["id"])
        return

    barrios_distritos, pedanias = separar_por_tipo(descendientes)
    fiestas_municipio = []

    # Procesar localidades secuencialmente (comparten el mismo sitio web municipal)
    todas_localidades = barrios_distritos + pedanias
    for j, loc in enumerate(todas_localidades):
        logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']}")
        try:
            fiestas_loc = await process_locality(loc, municipio, anno, rag_processor, logger)
            fiestas_municipio.extend(fiestas_loc)
        except Exception as e:
            logger.error(f"  [ERROR] Fallo procesando {loc['nombre']}: {e}")

    # Guardar progreso al finalizar el municipio completo
    await state_mgr.guardar_estado(fiestas_municipio, municipio["id"])


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

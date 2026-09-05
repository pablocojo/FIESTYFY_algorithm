"""
Orquestador Principal — Fase 2: Extracción de Fiestas (Async).

Procesa municipios en paralelo (batches de N), con cada localidad
ejecutando su pipeline completo: Spider → DDG → RAG → LLM → Validación.
"""

import json
import os
import sys
import time
import asyncio
import argparse
import logging
from datetime import datetime

from state_manager import StateManager
from scraper.heuristic_spider import AsyncTwoPassSpider
from scraper.google_search import search_locality_web, search_locality_media, get_failed_searches_count
from scraper.social_content import cargar_documentos_rrss, invalidar_cache as invalidar_cache_rrss
from scraper.social_finder import registrar_perfiles_web
from scraper.rrss_client import RRSSClient
from nombre_oficial import nombre_oficial_del_municipio
from llm_processor.text_analyzer import (
    AsyncRAGProcessor,
    llm_chat_json,
    analyze_festivals_for_locality,
    analyze_festivals_multipass,
    limpiar_actos_compartidos_del_municipio,
)
from llm_processor.patron_finder import obtener_patron, integrar_patron, fecha_del_patron
from fuentes import (
    FUENTE_WEB_LOCALIDAD, FUENTE_WEB_MUNICIPIO, FUENTE_HISTORICO,
    fuente_base, es_fuente_oficial, misma_web, web_es_de_este_lugar,
)
from higiene_documentos import limpiar_documentos
from config_idiomas import get_language_profile
from config import (
    PARALLEL_MUNICIPALITIES,
    PATRON_SEARCH_ENABLED,
    RRSS_SERVER_ENABLED,
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
    with open(ruta_json, "r", encoding="utf-8-sig") as f:
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
    rrss_client: RRSSClient | None,
    logger: logging.Logger,
    docs_municipio_cache: list[dict] | None = None,
    nombres_hermanas: list[str] = None,
    fiestas_capital: list[dict] | None = None,
) -> list[dict]:
    """
    Pipeline completo para una localidad, en orden de fiabilidad de fuentes:
    web localidad → web municipio → RRSS (caché/servidor) → búsqueda browser → RAG → LLM.
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
    # La web de la localidad solo cuenta si NO está vacía y es distinta de la del
    # padre. La comparación normaliza esquema, "www." y barra final: si no, la
    # misma web escrita de dos formas se rastrea dos veces.
    loc_tiene_web_propia = bool(sitio_loc) and not misma_web(sitio_loc, sitio_mun)
    # …y solo si el dominio es de este pueblo o de su municipio. Fase 1 asigna a
    # muchas pedanías la web de otro sitio —de la capital de provincia, de un
    # partido, de una televisión—, y rastrearla mete material de otro pueblo.
    if loc_tiene_web_propia and not web_es_de_este_lugar(
        sitio_loc, localidad.get("nombre", ""), municipio.get("nombre", "")
    ):
        logger.warning(
            f"    [!] La web de {localidad['nombre']} ({sitio_loc}) no es de esta "
            f"localidad ni de {municipio.get('nombre', '')}; no se rastrea. "
            f"Conviene corregirlo en Fase 1."
        )
        loc_tiene_web_propia = False

    # Guardar referencia a los spiders para extraer social_links
    spider_loc = None
    spider_mun = None

    # 1. Web oficial de la LOCALIDAD (fiabilidad máxima)
    if loc_tiene_web_propia:
        logger.info(f"    --> [1/5] Araña en web de la localidad: {sitio_loc}")
        spider_loc = AsyncTwoPassSpider()
        documentos += await spider_loc.crawl(
            sitio_loc, [localidad["nombre"]], FUENTE_WEB_LOCALIDAD, visited_urls
        )
        # Perfiles RRSS enlazados desde la web propia de la localidad
        await registrar_perfiles_web(localidad, spider_loc.social_links)

    # 2. Web oficial del MUNICIPIO
    if docs_municipio_cache is not None:
        logger.info(f"    --> [2/5] Araña en web del municipio (desde caché): {len(docs_municipio_cache)} docs")
        documentos += docs_municipio_cache
    elif sitio_mun:
        logger.info(f"    --> [2/5] Araña en web del municipio: {sitio_mun}")
        spider_mun = AsyncTwoPassSpider()
        documentos += await spider_mun.crawl(
            sitio_mun, [localidad["nombre"]], FUENTE_WEB_MUNICIPIO, visited_urls
        )
        # Perfiles RRSS del municipio (la caché evita repetir por cada pedanía)
        await registrar_perfiles_web(municipio, spider_mun.social_links)

    # 3-4. RRSS de la localidad y del municipio
    docs_rrss = cargar_documentos_rrss(localidad, municipio)
    if not docs_rrss and rrss_client and rrss_client.disponible:
        # No hay caché → pedir al servidor Windows que procese RRSS en tiempo real
        logger.info(f"    --> [3-4/5] Solicitando RRSS al servidor Windows...")
        lugar_ids = [localidad["id"]]
        if municipio["id"] != localidad["id"]:
            lugar_ids.append(municipio["id"])
        resultado_rrss = await rrss_client.procesar_rrss(lugar_ids)
        if resultado_rrss:
            # El servidor actualizó la caché en disco → forzar re-lectura
            invalidar_cache_rrss()
            docs_rrss = cargar_documentos_rrss(localidad, municipio)
    documentos += docs_rrss

    docs_oficiales = [d for d in documentos if es_fuente_oficial(d["fuente"])]
    if len(docs_oficiales) == 0:
        logger.info(f"    --> [4.5/5] Sin fuentes oficiales. Búsqueda suplementaria en prensa regional...")
        documentos += await search_locality_media(localidad, municipio, anno, visited_urls)

    # 5. Búsqueda browser (la menos fiable; no relee URLs de los pasos anteriores)
    # El patrón se resuelve ANTES de buscar, para poder buscar por su nombre. Es
    # lo que identifica una fiesta patronal, y sin él la encontrábamos solo si
    # aparecía por casualidad en los snippets de ese día. La tarea lleva corriendo
    # desde el paso 0, así que casi siempre está lista y no cuesta espera.
    patron = await _esperar_patron()
    if patron and patron.get("nombre"):
        localidad = dict(localidad, patron_nombre=patron["nombre"])

    logger.info(f"    --> [5/5] Búsqueda en buscadores...")
    docs_busqueda = await search_locality_web(localidad, municipio, anno, visited_urls)
        
    documentos += docs_busqueda

    fecha_patron = fecha_del_patron(patron, anno)

    documentos = [d for d in documentos if (d.get("texto") or "").strip()]
    if not documentos:
        logger.warning(f"    [!] No se extrajo ningún texto para {localidad['nombre']}.")
        return integrar_patron([], patron, anno, localidad)

    # Higiene: duplicados, tablas de cifras y boilerplate del gestor de contenidos.
    # Se hace ANTES de trocear para que el presupuesto de contexto no se gaste en
    # copias literales del mismo documento.
    documentos, _metricas_higiene = limpiar_documentos(documentos, etiqueta=localidad["nombre"])
    if not documentos:
        logger.warning(f"    [!] La higiene descartó todos los documentos de {localidad['nombre']}.")
        return integrar_patron([], patron, anno, localidad)

    # Métrica: documentos por fuente
    conteo_fuentes = {}
    for d in documentos:
        base = fuente_base(d["fuente"])
        conteo_fuentes[base] = conteo_fuentes.get(base, 0) + 1
    total_chars = sum(len(d["texto"]) for d in documentos)
    logger.info(f"    Recopilados {len(documentos)} documentos ({total_chars} chars): {conteo_fuentes}")

    # Multi-Pass RAG Architecture (Discovery Pass -> Enrichment Pass)
    fiestas = await analyze_festivals_multipass(
        municipio=municipio,
        localidad=localidad,
        documentos=documentos,
        anno=anno,
        fecha_patron=fecha_patron,
        rag_processor=rag_processor,
        logger=logger,
        nombres_hermanas=nombres_hermanas,
        fiestas_capital=fiestas_capital,
        patron=patron,
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
    rrss_client: RRSSClient | None,
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

    # El nombre oficial completo, una vez por municipio y cacheado para siempre.
    # Se deja en el propio dict porque de ahí lo leen tanto el constructor de
    # consultas como el bloque de identidad del juez de pertenencia, y así no hay
    # que pasarlo por media docena de firmas.
    municipio["nombre_oficial"] = await nombre_oficial_del_municipio(municipio, llm_chat_json)

    # Pre-crawl del sitio municipal una sola vez para reutilizar en todas las pedanías
    docs_municipio_cache = None
    sitio_mun = municipio.get("sitio_web", "").strip()
    if sitio_mun:
        logger.info(f"  [PRECRAWL] Araña única del municipio: {sitio_mun}")
        spider_mun = AsyncTwoPassSpider()
        todos_nombres = [municipio["nombre"]] + [loc["nombre"] for loc in todas_localidades]
        visited_mun = set()
        docs_municipio_cache = await spider_mun.crawl(
            sitio_mun, todos_nombres, FUENTE_WEB_MUNICIPIO, visited_mun
        )
        await registrar_perfiles_web(municipio, spider_mun.social_links)
        logger.info(f"  [PRECRAWL] {len(docs_municipio_cache)} docs municipales en caché")

    fiestas_capital: list[dict] = []
    for j, loc in enumerate(todas_localidades):
        if loc["id"] in locs_completadas:
            logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']} (Omitiendo, ya procesada temporalmente)")
            continue
            
        logger.info(f"  [{j + 1}/{len(todas_localidades)}] {loc['nombre']}")
        nombres_hermanas = [
            hermana["nombre"]
            for hermana in todas_localidades
            if hermana["id"] != loc["id"] and not hermana.get("es_capital")
        ]
        try:
            fiestas_loc = await process_locality(
                loc, municipio, anno, rag_processor, rrss_client, logger,
                docs_municipio_cache=docs_municipio_cache,
                nombres_hermanas=nombres_hermanas,
                fiestas_capital=fiestas_capital,
            )
            # El nucleo principal se procesa el primero (todas_localidades =
            # capitales + otros), asi que sus fiestas ya estan disponibles cuando
            # les toca a las pedanias y sirven de referencia anti-copia.
            if loc.get("es_capital"):
                fiestas_capital = list(fiestas_loc)
            fiestas_municipio.extend(fiestas_loc)
            # Volcado temporal tras finalizar esta localidad
            await state_mgr.guardar_estado_localidad(fiestas_loc, loc["id"])
        except Exception as e:
            logger.error(f"  [ERROR] Fallo procesando {loc['nombre']}: {e}")

    # Barrido final: el acto que sale en varios pueblos del municipio no puede
    # ser de todos. Solo se puede ver aquí, con todas las localidades hechas, y
    # atrapa lo que la comparación contra la capital no ve cuando la capital se
    # ha extraído a medias. Modifica los mismos dicts que guarda el estado.
    capital = next((l for l in todas_localidades if l.get("es_capital")), None)
    limpiar_actos_compartidos_del_municipio(
        fiestas_municipio, capital["id"] if capital else None
    )

    # Guardar progreso al finalizar el municipio completo
    # Se pasa lista vacía de fiestas porque ya se han guardado todas progresivamente
    await state_mgr.guardar_estado([], municipio["id"])


# ──────────────────────────────────────────
# INFORME DE EJECUCIÓN Y MÉTRICAS (REQUISITO R6)
# ──────────────────────────────────────────

def generar_informe_ejecucion(
    fiestas: list[dict],
    localidades_completadas: list | set,
    municipios_completados: list | set,
    tiempo_total_segundos: float,
    busquedas_fallidas: int = 0,
) -> dict:
    """
    Calcula las métricas de ejecución de la Fase 2 (Requisito R6):
    - Ratio de fiestas extraídas vs. estimadas
    - Número de localidades con 0 fiestas
    - Fuentes más contribuyentes
    - Número de búsquedas bloqueadas/fallidas
    - Tiempo medio de ejecución por municipio
    """
    extraidas = sum(1 for f in fiestas if not f.get("es_estimada", False))
    estimadas = sum(1 for f in fiestas if f.get("es_estimada", False))
    total_fiestas = len(fiestas)

    if estimadas > 0:
        ratio_val = extraidas / estimadas
        ratio_str = f"{ratio_val:.2f}"
    elif extraidas > 0:
        ratio_val = float("inf")
        ratio_str = f"{extraidas}:0 (Sin estimadas)"
    else:
        ratio_val = 0.0
        ratio_str = "0:0"

    set_localidades = set(localidades_completadas)
    locs_con_fiestas = {f["lugar_id"] for f in fiestas if f.get("lugar_id")}
    localidades_sin_fiestas = set_localidades - locs_con_fiestas
    num_localidades_cero = len(localidades_sin_fiestas)

    from collections import Counter
    conteo_fuentes = Counter()
    for f in fiestas:
        if f.get("es_estimada", False):
            conteo_fuentes["santo_patron"] += 1
        else:
            fuentes = f.get("fuentes", [])
            if fuentes:
                for src in fuentes:
                    if isinstance(src, str):
                        base = fuente_base(src)
                    elif isinstance(src, dict):
                        base = fuente_base(src.get("fuente", ""))
                    else:
                        base = "desconocida"
                    conteo_fuentes[base or "desconocida"] += 1
            else:
                conteo_fuentes["desconocida"] += 1
    top_fuentes = conteo_fuentes.most_common(5)

    num_municipios = len(set(municipios_completados))
    tiempo_medio_municipio = (tiempo_total_segundos / num_municipios) if num_municipios > 0 else 0.0

    return {
        "total_fiestas": total_fiestas,
        "fiestas_extraidas": extraidas,
        "fiestas_estimadas": estimadas,
        "ratio_extraidas_vs_estimadas": ratio_str,
        "ratio_numerico": ratio_val,
        "total_localidades_procesadas": len(set_localidades),
        "localidades_con_cero_fiestas": num_localidades_cero,
        "fuentes_mas_contribuyentes": top_fuentes,
        "busquedas_bloqueadas_fallidas": busquedas_fallidas,
        "tiempo_total_segundos": tiempo_total_segundos,
        "municipios_procesados": num_municipios,
        "tiempo_medio_por_municipio": tiempo_medio_municipio,
    }


def registrar_informe_resumen(metrics: dict, logger: logging.Logger) -> str:
    """Formatea y registra en el logger el informe resumen de ejecución R6."""
    top_fuentes_str = ", ".join([f"{src}: {cnt}" for src, cnt in metrics["fuentes_mas_contribuyentes"]]) or "Ninguna"

    informe_lines = [
        "=" * 60,
        "  INFORME RESUMEN DE EJECUCIÓN (MÉTRICAS R6)",
        "=" * 60,
        f"  Total Fiestas Registradas: {metrics['total_fiestas']}",
        f"    - Extraídas de fuentes:  {metrics['fiestas_extraidas']}",
        f"    - Estimadas (Patrón):    {metrics['fiestas_estimadas']}",
        f"    - Ratio Extraídas/Estimadas: {metrics['ratio_extraidas_vs_estimadas']}",
        f"  Localidades con 0 Fiestas: {metrics['localidades_con_cero_fiestas']} (de {metrics['total_localidades_procesadas']} procesadas)",
        f"  Fuentes más contribuyentes: {top_fuentes_str}",
        f"  Búsquedas bloqueadas/fallidas: {metrics['busquedas_bloqueadas_fallidas']}",
        f"  Municipios procesados: {metrics['municipios_procesados']}",
        f"  Tiempo total de ejecución: {metrics['tiempo_total_segundos']:.2f}s",
        f"  Tiempo medio por municipio: {metrics['tiempo_medio_por_municipio']:.2f}s",
        "=" * 60,
    ]

    report_text = "\n".join(informe_lines)
    logger.info("\n" + report_text)
    return report_text


# ──────────────────────────────────────────
# ORQUESTADOR PRINCIPAL
# ──────────────────────────────────────────

async def async_main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Fase 2: Extracción de Fiestas (Async)")
    parser.add_argument("--anno", type=int, default=2026, help="Año de búsqueda")
    parser.add_argument("--input", type=str, default="../Fase1_recogida_datos_wiki/lugares_espana.json", help="Ruta JSON de lugares")
    parser.add_argument("--output", type=str, default="fiestas_espana.json", help="Ruta JSON de salida")
    parser.add_argument("--parallel", type=int, default=PARALLEL_MUNICIPALITIES, help="Municipios en paralelo")
    parser.add_argument("--sin-rrss", action="store_true",
                        help="No usar el servidor de RRSS. Para ejecuciones desatendidas: "
                             "la automatización necesita las ventanas de las apps en primer "
                             "plano, y si nadie está delante cada localidad pierde el timeout "
                             "entero esperando.")
    args = parser.parse_args()

    logger = setup_logging()

    logger.info(f"{'=' * 60}")
    logger.info(f"  FASE 2: EXTRACCIÓN DE FIESTAS ({args.anno})")
    from config import (
        LMSTUDIO_CHAT_MODEL, OPENROUTER_ENABLED, OPENROUTER_API_KEY, OPENROUTER_MODELS,
    )
    if OPENROUTER_ENABLED and OPENROUTER_API_KEY:
        from config import OPENROUTER_N_CTX
        cuantos = len(OPENROUTER_MODELS)
        cuales = (f"{OPENROUTER_MODELS[0]}" if cuantos == 1
                  else f"{cuantos} modelos en cascada, 1º {OPENROUTER_MODELS[0]}")
        logger.info(
            f"  Chat: OpenRouter ({cuales}, n_ctx {OPENROUTER_N_CTX}) "
            f"→ LM Studio/{LMSTUDIO_CHAT_MODEL} de reserva"
        )
    else:
        motivo = "desactivado" if not OPENROUTER_ENABLED else "sin clave API"
        logger.warning(f"  Chat: OpenRouter {motivo} — se usa solo LM Studio/{LMSTUDIO_CHAT_MODEL}")
    logger.info(f"  Embeddings y visión: LM Studio | Paralelismo: {args.parallel} municipios")

    # Presupuesto de contexto real del modelo cargado en LM Studio.
    try:
        from context_budget import get_model_info, resumen_presupuesto, RESERVA_SALIDA_DISCOVERY
        from llm_processor.text_analyzer import DISCOVERY_MAX_CHARS
        info = get_model_info()
        r = resumen_presupuesto("x" * 4800, RESERVA_SALIDA_DISCOVERY)  # system prompt típico
        origen = "detectado" if info["detectado"] else "FALLBACK (LM Studio no respondió)"
        logger.info(
            f"  Contexto: n_ctx={info['n_ctx']} ({origen})"
            + (f", máximo del modelo={info['max_context_length']}" if info.get("max_context_length") else "")
        )
        logger.info(
            f"  Presupuesto disponible ≈ {r['presupuesto_contexto_tokens']} tok "
            f"(~{r['presupuesto_contexto_chars_aprox']} chars) | "
            f"hoy se usan {DISCOVERY_MAX_CHARS} chars en discovery "
            f"= {100 * DISCOVERY_MAX_CHARS / max(1, r['presupuesto_contexto_chars_aprox']):.0f}% del presupuesto"
        )
        logger.info(
            f"  Conteo de tokens: {'tokenizador exacto' if r['tokenizador_exacto'] else 'ratio autocalibrado'} "
            f"({r['ratio_chars_token']} chars/token)"
        )
    except Exception as e:
        logger.warning(f"  No se pudo calcular el presupuesto de contexto: {e}")

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
        tiempo_total = time.time() - start_time
        metrics = generar_informe_ejecucion(
            fiestas=state_mgr.state.get("fiestas", []),
            localidades_completadas=state_mgr.state.get("localidades_completadas", []),
            municipios_completados=state_mgr.state.get("municipios_completados", []),
            tiempo_total_segundos=tiempo_total,
            busquedas_fallidas=get_failed_searches_count(),
        )
        registrar_informe_resumen(metrics, logger)
        return

    # Inicializar RAG Processor
    rag_processor = AsyncRAGProcessor()

    # Inicializar cliente RRSS (servidor Windows)
    rrss_client = None
    if args.sin_rrss:
        logger.info("  RRSS: desactivadas por --sin-rrss (solo se usará la caché existente).")
    elif RRSS_SERVER_ENABLED:
        rrss_client = RRSSClient()
        if await rrss_client.verificar_servidor():
            logger.info(f"Servidor RRSS disponible — las RRSS se procesarán en tiempo real")
        else:
            logger.warning(
                "Servidor RRSS no disponible. Las RRSS se omitirán "
                "(solo se usará la caché existente si hay datos previos)."
            )
            rrss_client = None

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
                mun, desc, args.anno, rag_processor, rrss_client, state_mgr, idx, total, logger
            )
            for idx, mun, desc in batch
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  EXTRACCIÓN COMPLETADA")
    logger.info(f"  Total fiestas: {len(state_mgr.state['fiestas'])}")
    logger.info(f"{'=' * 60}")

    tiempo_total = time.time() - start_time
    metrics = generar_informe_ejecucion(
        fiestas=state_mgr.state.get("fiestas", []),
        localidades_completadas=state_mgr.state.get("localidades_completadas", []),
        municipios_completados=state_mgr.state.get("municipios_completados", []),
        tiempo_total_segundos=tiempo_total,
        busquedas_fallidas=get_failed_searches_count(),
    )
    registrar_informe_resumen(metrics, logger)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()


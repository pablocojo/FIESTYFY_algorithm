"""
Empirical Stress & Boundary Testing Suite for Fiestyfy Fase 2 (R1-R6).
Exhaustively tests edge cases, concurrency, bounds, and requirements.
"""

import asyncio
import os
import sys
import time
import math
import random
from datetime import date, datetime

# Ensure path imports work
FASE2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if FASE2_DIR not in sys.path:
    sys.path.insert(0, FASE2_DIR)

from config import DDG_DELAY_MIN, DDG_DELAY_MAX, DDG_RETRY_BACKOFF
from scraper.google_search import (
    get_random_user_agent,
    get_query_delay,
    calculate_backoff_delay,
    registrar_busqueda_fallida,
    get_failed_searches_count,
    reset_search_metrics,
    USER_AGENTS,
)
from scraper.heuristic_spider import AsyncTwoPassSpider
from scraper.document_extractor import is_promising_pdf, is_promising_image
from llm_processor.text_analyzer import _validar_fecha
from llm_processor.patron_finder import fecha_del_patron, integrar_patron, _PatronCache
from scraper.social_content import es_fecha_en_ventana, cargar_documentos_rrss
from scraper.social_finder import RedesCache, normalizar_link_social
from main import generar_informe_ejecucion, registrar_informe_resumen


def test_r1_user_agent_and_delays():
    """Verify User-Agent rotation and delay bounds."""
    uas = {get_random_user_agent() for _ in range(500)}
    assert len(uas) == len(USER_AGENTS), f"Expected all {len(USER_AGENTS)} UAs, got {len(uas)}"
    assert all(ua in USER_AGENTS for ua in uas)

    delays = [get_query_delay() for _ in range(1000)]
    assert all(DDG_DELAY_MIN <= d <= DDG_DELAY_MAX for d in delays)
    assert min(delays) >= 2.0 and max(delays) <= 4.5

    backoffs = [calculate_backoff_delay(attempt) for attempt in range(5)]
    for attempt, delay in enumerate(backoffs):
        min_expected = (DDG_RETRY_BACKOFF * (2 ** attempt)) + 0.5
        max_expected = (DDG_RETRY_BACKOFF * (2 ** attempt)) + 2.0
        assert min_expected <= delay <= max_expected

    reset_search_metrics()
    assert get_failed_searches_count() == 0
    registrar_busqueda_fallida()
    registrar_busqueda_fallida()
    assert get_failed_searches_count() == 2
    reset_search_metrics()


def test_r2_spider_prioritization_and_dedupe():
    """Verify temporal scoring and calendar deduplication in spider."""
    score_2026_kw = AsyncTwoPassSpider._score_page(
        "http://ejemplo.es/fiestas-2026/programa.html",
        "Programa Fiestas 2026",
        "programa de fiestas patronales verbena",
        ["pueblo"],
        target_year=2026
    )
    score_2026_nokw = AsyncTwoPassSpider._score_page(
        "http://ejemplo.es/2026/actas.html",
        "Actas 2026",
        "reunion del consejo",
        ["pueblo"],
        target_year=2026
    )
    score_2025_kw = AsyncTwoPassSpider._score_page(
        "http://ejemplo.es/fiestas-2025/programa.html",
        "Programa Fiestas 2025",
        "programa de fiestas patronales verbena",
        ["pueblo"],
        target_year=2026
    )
    # Single unrelated municipal event without weak festival keywords
    score_unrelated = AsyncTwoPassSpider._score_page(
        "http://ejemplo.es/noticia.html",
        "Conferencia Taller",
        "charla y taller de corte de agua",
        ["pueblo"],
        target_year=2026
    )

    assert score_2026_kw > score_2026_nokw
    assert score_2026_kw > score_2025_kw
    assert (score_2026_kw - score_2025_kw) >= 300
    assert score_unrelated == -350

    # Test edge case: 'evento' in URL acts as weak keyword in _score_page
    score_with_evento_in_url = AsyncTwoPassSpider._score_page(
        "http://ejemplo.es/evento.html",
        "Conferencia Taller",
        "charla y taller de corte de agua",
        ["pueblo"],
        target_year=2026
    )
    assert score_with_evento_in_url == 20

    # Calendar key regex deduplication test
    assert AsyncTwoPassSpider._get_calendar_date_key("http://ejemplo.es/2026/08/15/evento") == "ejemplo.es:/2026/08/15"
    assert AsyncTwoPassSpider._get_calendar_date_key("http://ejemplo.es/2026/8/5") == "ejemplo.es:/2026/8/5"
    assert AsyncTwoPassSpider._get_calendar_date_key("http://ejemplo.es/contacto.html") is None


def test_r3_cross_year_and_patron_leap_year():
    """Verify Dec->Jan cross-year dates and Feb 29 non-leap year fallback."""
    # Dec 2026 -> Jan 2027 valid
    assert _validar_fecha("2027-01-02", 2026, es_fecha_fin=True, fecha_inicio_str="2026-12-30") is True
    # Nov 2026 -> Jan 2027 invalid
    assert _validar_fecha("2027-01-02", 2026, es_fecha_fin=True, fecha_inicio_str="2026-11-30") is False
    # Normal target year date
    assert _validar_fecha("2026-08-15", 2026) is True
    # Malformed date
    assert _validar_fecha("invalid", 2026) is False

    # Patron Feb 29 leap year vs non-leap year
    patron_feb29 = {"nombre": "San Ciriaco", "dia": 29, "mes": 2}
    # 2026 is non-leap -> fallback to Feb 28
    assert fecha_del_patron(patron_feb29, 2026) == date(2026, 2, 28)
    # 2028 is leap -> Feb 29
    assert fecha_del_patron(patron_feb29, 2028) == date(2028, 2, 29)
    # 2027 is non-leap -> Feb 28
    assert fecha_del_patron(patron_feb29, 2027) == date(2027, 2, 28)


def test_r4_social_date_filtering_window():
    """Verify target year (2026) publication window filtering."""
    # Default window for 2026: 2025-11-01 to 2027-01-31
    assert es_fecha_en_ventana("2025-11-01", anno=2026) is True
    assert es_fecha_en_ventana("2026-06-15", anno=2026) is True
    assert es_fecha_en_ventana("2027-01-31", anno=2026) is True
    assert es_fecha_en_ventana("2025-10-31", anno=2026) is False
    assert es_fecha_en_ventana("2027-02-01", anno=2026) is False
    assert es_fecha_en_ventana("2024-08-15", anno=2026) is False
    assert es_fecha_en_ventana(None, anno=2026) is True


def test_r5_pdf_priority_and_async_cache():
    """Verify PDF 2026/2025 target year verification and async cache save."""
    assert is_promising_pdf("http://a.com/prog2026.pdf", "programa", "fiestas 2026", target_year=2026) is True
    assert is_promising_pdf("http://a.com/prog2025.pdf", "programa", "fiestas 2025", target_year=2026) is True
    assert is_promising_pdf("http://a.com/prog2024.pdf", "programa", "fiestas 2024", target_year=2026) is False
    assert is_promising_pdf("http://a.com/actas2023.pdf", "actas", "pleno ordinario", target_year=2026) is False

    # Async cache thread execution test
    async def _test_async_cache():
        test_file = "scratch/temp_test_cache.json"
        if os.path.exists(test_file):
            os.remove(test_file)
        rc = RedesCache(test_file)
        await rc.set("test_id", {"instagram": "http://ig.com/test", "pendiente_apps": False})
        val = await rc.get("test_id")
        assert val["instagram"] == "http://ig.com/test"
        if os.path.exists(test_file):
            os.remove(test_file)

    asyncio.run(_test_async_cache())


def test_r6_execution_metrics_formatting():
    """Verify execution metrics computation and report generation."""
    fiestas = [
        {"lugar_id": "L1", "nombre": "Fiesta 1", "es_estimada": False, "fuentes": ["web_localidad"]},
        {"lugar_id": "L1", "nombre": "Fiesta 2", "es_estimada": False, "fuentes": ["busqueda_web"]},
        {"lugar_id": "L2", "nombre": "Fiesta Estimada", "es_estimada": True, "fuentes": []},
    ]
    metrics = generar_informe_ejecucion(
        fiestas=fiestas,
        localidades_completadas=["L1", "L2", "L3"],
        municipios_completados=["M1"],
        tiempo_total_segundos=15.5,
        busquedas_fallidas=3,
    )
    assert metrics["total_fiestas"] == 3
    assert metrics["fiestas_extraidas"] == 2
    assert metrics["fiestas_estimadas"] == 1
    assert metrics["ratio_extraidas_vs_estimadas"] == "2.00"
    assert metrics["localidades_con_cero_fiestas"] == 1  # L3 has 0
    assert metrics["busquedas_bloqueadas_fallidas"] == 3
    assert metrics["tiempo_medio_por_municipio"] == 15.5

    class MockLogger:
        def __init__(self):
            self.lines = []
        def info(self, msg):
            self.lines.append(msg)

    logger = MockLogger()
    report = registrar_informe_resumen(metrics, logger)
    assert "INFORME RESUMEN DE EJECUCIÓN (MÉTRICAS R6)" in report
    assert "Ratio Extraídas/Estimadas: 2.00" in report
    assert "Búsquedas bloqueadas/fallidas: 3" in report


if __name__ == "__main__":
    test_r1_user_agent_and_delays()
    test_r2_spider_prioritization_and_dedupe()
    test_r3_cross_year_and_patron_leap_year()
    test_r4_social_date_filtering_window()
    test_r5_pdf_priority_and_async_cache()
    test_r6_execution_metrics_formatting()
    print("ALL EMPIRICAL STRESS TESTS PASSED SUCCESSFULLY!")

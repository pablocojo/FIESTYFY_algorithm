"""
Empirical Stress & Boundary Test Suite — Challenger 4
Executed to empirically challenge all remediated R1-R6 components.
"""

import sys
import os
import random
import pytest
import asyncio
import tempfile
import json
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    DDG_DELAY_MIN,
    DDG_DELAY_MAX,
    DDG_RETRY_BACKOFF,
    DDG_MAX_RETRIES,
)
from scraper.google_search import (
    USER_AGENTS,
    get_random_user_agent,
    get_query_delay,
    calculate_backoff_delay,
    reset_search_metrics,
    get_failed_searches_count,
    registrar_busqueda_fallida,
)
from scraper.heuristic_spider import AsyncTwoPassSpider
from llm_processor.text_analyzer import _validar_fecha, validar_fiestas
from llm_processor.patron_finder import fecha_del_patron, _PatronCache
from scraper.social_content import es_fecha_en_ventana
from scraper.social_finder import RedesCache
from scraper.document_extractor import is_promising_pdf
from main import generar_informe_ejecucion


# ==============================================================================
# R1 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r1_ua_distribution_large():
    """Verify UA rotation uniformity over 5000 iterations."""
    counts = {ua: 0 for ua in USER_AGENTS}
    for _ in range(5000):
        counts[get_random_user_agent()] += 1

    expected_avg = 5000 / len(USER_AGENTS) # 1000
    for ua, cnt in counts.items():
        assert abs(cnt - expected_avg) < 250, f"UA {ua} skewed: count={cnt}"


def test_challenger4_r1_delay_bounds_large():
    """Verify query delay limits over 5000 iterations."""
    delays = [get_query_delay() for _ in range(5000)]
    assert all(2.0 <= d <= 4.5 for d in delays)
    assert min(delays) >= 2.0
    assert max(delays) <= 4.5
    assert (max(delays) - min(delays)) > 2.4


def test_challenger4_r1_backoff_and_metrics():
    """Verify backoff math jitter range and search failure counter state."""
    reset_search_metrics()
    assert get_failed_searches_count() == 0
    registrar_busqueda_fallida()
    registrar_busqueda_fallida()
    assert get_failed_searches_count() == 2
    reset_search_metrics()
    assert get_failed_searches_count() == 0

    for attempt in range(6):
        min_expected = (3.0 * (2 ** attempt)) + 0.5
        max_expected = (3.0 * (2 ** attempt)) + 2.0
        for _ in range(200):
            val = calculate_backoff_delay(attempt, base_backoff=3.0)
            assert min_expected <= val <= max_expected, f"Attempt {attempt}: {val}"


# ==============================================================================
# R2 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r2_spider_scoring_matrix():
    """Test scoring variations for target year 2026, past years, and single events."""
    locality = ["Benidorm"]

    # 1. Past year penalization
    score_2025 = AsyncTwoPassSpider._score_page(
        url="https://benidorm.org/fiestas-2025",
        title="Fiestas 2025",
        page_text="Programa de fiestas de Benidorm",
        locality_names=locality,
        target_year=2026,
    )
    score_2026 = AsyncTwoPassSpider._score_page(
        url="https://benidorm.org/fiestas-2026",
        title="Fiestas 2026",
        page_text="Programa de fiestas de Benidorm",
        locality_names=locality,
        target_year=2026,
    )
    # 2026 gets +350 (target year + festival kw), 2025 gets -300 (past year). Difference = 650
    assert score_2026 - score_2025 == 650

    # 2. Single event penalization
    score_taller = AsyncTwoPassSpider._score_page(
        url="https://benidorm.org/noticias/taller-costura",
        title="Taller de Costura",
        page_text="Taller de costura en Benidorm",
        locality_names=locality,
        target_year=2026,
    )
    score_plain = AsyncTwoPassSpider._score_page(
        url="https://benidorm.org/noticias/informacion",
        title="Informacion",
        page_text="Noticias de Benidorm",
        locality_names=locality,
        target_year=2026,
    )
    assert score_taller == score_plain - 350


# ==============================================================================
# R3 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r3_crossyear_boundaries():
    """Verify all boundary conditions for cross-year date validator."""
    anno = 2026
    # Dec 31 2026 -> Jan 2 2027 (Valid)
    assert _validar_fecha("2026-12-31", anno) is True
    assert _validar_fecha("2027-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-31") is True

    # Dec 15 2026 -> Jan 10 2027 (Valid)
    assert _validar_fecha("2027-01-10", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-15") is True

    # Nov 30 2026 -> Jan 2 2027 (Invalid: Nov start)
    assert _validar_fecha("2027-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-11-30") is False

    # Dec 31 2026 -> Jan 2 2028 (Invalid: 2 years ahead)
    assert _validar_fecha("2028-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-31") is False


def test_challenger4_r3_patron_leap_fallbacks():
    """Test Feb 29 patron across leap/non-leap years including century non-leap years."""
    patron_feb29 = {"nombre": "San Augusto", "dia": 29, "mes": 2}

    # 2026 (non-leap) -> Feb 28
    assert fecha_del_patron(patron_feb29, 2026) == date(2026, 2, 28)
    # 2028 (leap year) -> Feb 29
    assert fecha_del_patron(patron_feb29, 2028) == date(2028, 2, 29)
    # 2100 (non-leap century) -> Feb 28
    assert fecha_del_patron(patron_feb29, 2100) == date(2100, 2, 28)
    # 2000 (leap century) -> Feb 29
    assert fecha_del_patron(patron_feb29, 2000) == date(2000, 2, 29)


# ==============================================================================
# R4 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r4_social_window_strict_iso():
    """Test precise ISO timestamps & timezone offsets for social posts."""
    # Target year 2026 window: 2025-11-01 to 2027-01-31
    assert es_fecha_en_ventana("2025-10-31T23:59:59Z", anno=2026) is False
    assert es_fecha_en_ventana("2025-11-01T00:00:00Z", anno=2026) is True
    assert es_fecha_en_ventana("2027-01-31T23:59:59+05:00", anno=2026) is True
    assert es_fecha_en_ventana("2027-02-01T00:00:01Z", anno=2026) is False
    assert es_fecha_en_ventana(None, anno=2026) is True
    assert es_fecha_en_ventana("invalid-date-string", anno=2026) is True


# ==============================================================================
# R5 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r5_pdf_filter_years():
    """Verify is_promising_pdf accepts 2026/2025 and rejects older years."""
    assert is_promising_pdf("https://ayto.es/programa-2026.pdf", "", "") is True
    assert is_promising_pdf("https://ayto.es/programa-2025.pdf", "", "") is True
    assert is_promising_pdf("https://ayto.es/programa-2024.pdf", "", "") is False
    assert is_promising_pdf("https://ayto.es/programa-2023.pdf", "", "") is False


def test_challenger4_r5_high_concurrency_async_caches():
    """Stress test 100 concurrent async writes to RedesCache and _PatronCache."""
    async def _stress_caches():
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t1, \
             tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t2:
            p1, p2 = t1.name, t2.name

        try:
            if os.path.exists(p1): os.remove(p1)
            if os.path.exists(p2): os.remove(p2)

            rc = RedesCache(p1)
            pc = _PatronCache(p2)

            async def do_write_r(idx):
                await rc.set(f"loc_{idx}", {"instagram": f"https://instagram.com/user{idx}"})

            async def do_write_p(idx):
                await pc.set(f"loc_{idx}", {"nombre": f"San {idx}", "dia": 15, "mes": 8})

            tasks = []
            for i in range(100):
                tasks.append(do_write_r(i))
                tasks.append(do_write_p(i))

            await asyncio.gather(*tasks)

            for i in range(100):
                val_r = await rc.get(f"loc_{i}")
                assert val_r == {"instagram": f"https://instagram.com/user{i}"}
                val_p = await pc.get(f"loc_{i}")
                assert val_p["nombre"] == f"San {i}"
        finally:
            for p in [p1, p2, f"{p1}.tmp", f"{p2}.tmp"]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except OSError: pass

    asyncio.run(_stress_caches())


# ==============================================================================
# R6 EMPIRICAL TESTS
# ==============================================================================

def test_challenger4_r6_metrics_edge_cases():
    """Verify execution metrics calculation under zero, empty, and infinite ratio conditions."""
    # Ratio infinite (only extracted, 0 estimated)
    m1 = generar_informe_ejecucion(
        fiestas=[{"id": "f1", "lugar_id": "l1", "es_estimada": False, "fuentes": ["web_localidad"]}],
        localidades_completadas=["l1"],
        municipios_completados=["m1"],
        tiempo_total_segundos=12.5,
        busquedas_fallidas=1,
    )
    assert m1["fiestas_extraidas"] == 1
    assert m1["fiestas_estimadas"] == 0
    assert "Sin estimadas" in m1["ratio_extraidas_vs_estimadas"]
    assert m1["tiempo_medio_por_municipio"] == 12.5
    assert m1["busquedas_bloqueadas_fallidas"] == 1

    # Ratio 0:0 (no festivals)
    m0 = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=["l1", "l2"],
        municipios_completados=["m1"],
        tiempo_total_segundos=10.0,
    )
    assert m0["ratio_extraidas_vs_estimadas"] == "0:0"
    assert m0["localidades_con_cero_fiestas"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

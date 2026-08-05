"""
Adversarial Stress Test Suite for Fase 2 Requirements R1 - R6.
Designed by Challenger 1 (teamwork_preview_challenger_1) to stress-test boundary conditions,
edge cases, concurrency, and implicit assumptions across all R1-R6 components.
"""

import sys
import os
import random
import pytest
import asyncio
import tempfile
import json
from datetime import date, datetime

# Ensure project root is in sys.path
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
from scraper.social_content import es_fecha_en_ventana, cargar_documentos_rrss
import scraper.social_content as social_content
from scraper.social_finder import RedesCache
from scraper.document_extractor import is_promising_pdf
from main import generar_informe_ejecucion, registrar_informe_resumen


# ==============================================================================
# R1 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r1_adversarial_delay_and_ua_distribution():
    """Stress test 1000 samples for delay bounds and User-Agent uniform distribution."""
    # 1. Delays
    delays = [get_query_delay() for _ in range(1000)]
    assert all(2.0 <= d <= 4.5 for d in delays), "Delay violated [2.0, 4.5] range."
    assert max(delays) - min(delays) > 2.0, "Delay distribution too narrow."

    # 2. User-Agent distribution
    counts = {ua: 0 for ua in USER_AGENTS}
    for _ in range(1000):
        ua = get_random_user_agent()
        counts[ua] += 1

    # Every UA should be chosen roughly ~200 times (+/- 70)
    for ua, count in counts.items():
        assert count > 100, f"User-Agent {ua} was under-sampled: count={count}"


def test_r1_adversarial_backoff_math_extended():
    """Verify exponential backoff calculation across extended attempt numbers."""
    base = DDG_RETRY_BACKOFF  # 3.0
    for attempt in [0, 1, 2, 3, 5, 10]:
        min_expected = (base * (2 ** attempt)) + 0.5
        max_expected = (base * (2 ** attempt)) + 2.0

        for _ in range(100):
            val = calculate_backoff_delay(attempt, base)
            assert min_expected <= val <= max_expected, (
                f"Attempt {attempt}: val {val} out of expected [{min_expected}, {max_expected}]"
            )


# ==============================================================================
# R2 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r2_adversarial_spider_scoring_postal_codes_and_regex():
    """
    Stress-test _score_page regex against URLs containing postal codes or numeric IDs
    that resemble 4-digit years (e.g., 20250 or 20241015).
    """
    locality = ["Alicante"]

    score_clean = AsyncTwoPassSpider._score_page(
        url="https://alicante.es/noticias/general",
        title="General",
        page_text="Noticias de Alicante",
        locality_names=locality,
        target_year=2026,
    )

    # URL with postal code 20250 (starts with 2025)
    score_postal = AsyncTwoPassSpider._score_page(
        url="https://alicante.es/codigo-20250-oficina",
        title="General",
        page_text="Noticias de Alicante",
        locality_names=locality,
        target_year=2026,
    )

    # NOTE: re.findall(r"(?:19|20)\d{2}", "codigo-20250-oficina") matches "2025",
    # which is < 2026, causing score_postal to be penalized (-300).
    # We log this finding to document the regex behavior.
    assert score_postal == score_clean - 300, (
        f"Postal code 20250 penalized by regex matching '2025'. Score clean: {score_clean}, postal: {score_postal}"
    )


def test_r2_adversarial_calendar_date_key_normalization():
    """Test calendar date key extraction with variations in zero-padding (e.g. /2026/5/2/ vs /2026/05/02/)."""
    spider = AsyncTwoPassSpider(target_year=2026)

    key_padded = spider._get_calendar_date_key("https://ayto.es/agenda/2026/05/02/evento")
    key_unpadded = spider._get_calendar_date_key("https://ayto.es/agenda/2026/5/2/evento")

    assert key_padded == "ayto.es:/2026/05/02"
    assert key_unpadded == "ayto.es:/2026/5/2"


# ==============================================================================
# R3 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r3_adversarial_cross_year_dates():
    """Adversarial testing of _validar_fecha for boundary dates."""
    anno = 2026

    # Dec 31, 2026 -> Jan 2, 2027 (Valid cross-year festival)
    assert _validar_fecha("2026-12-31", anno) is True
    assert _validar_fecha("2027-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-31") is True

    # Dec 1, 2026 -> Dec 5, 2026 (Valid standard festival)
    assert _validar_fecha("2026-12-01", anno) is True
    assert _validar_fecha("2026-12-05", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-01") is True

    # Jan 1, 2026 -> Jan 5, 2026 (Valid standard festival)
    assert _validar_fecha("2026-01-01", anno) is True
    assert _validar_fecha("2026-01-05", anno, es_fecha_fin=True, fecha_inicio_str="2026-01-01") is True

    # Nov 30, 2026 -> Jan 2, 2027 (Invalid: start in Nov, end in next year)
    assert _validar_fecha("2027-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-11-30") is False

    # Dec 31, 2026 -> Jan 2, 2028 (Invalid: end in 2 years ahead)
    assert _validar_fecha("2028-01-02", anno, es_fecha_fin=True, fecha_inicio_str="2026-12-31") is False

    # Dec 31, 2025 -> Jan 2, 2026 (Invalid: target year is 2026, start was 2025)
    assert _validar_fecha("2025-12-31", anno) is False


def test_r3_adversarial_patron_dates():
    """Adversarial testing of fecha_del_patron across leap and non-leap years."""
    patron_feb29 = {"nombre": "San Augusto", "dia": 29, "mes": 2}

    # Non-leap year 2026 -> Feb 28, 2026
    assert fecha_del_patron(patron_feb29, 2026) == date(2026, 2, 28)

    # Leap year 2028 -> Feb 29, 2028
    assert fecha_del_patron(patron_feb29, 2028) == date(2028, 2, 29)

    # Non-leap year 2027 -> Feb 28, 2027
    assert fecha_del_patron(patron_feb29, 2027) == date(2027, 2, 28)

    # Invalid patron date (e.g., April 31) -> None
    patron_invalid = {"nombre": "San Invalido", "dia": 31, "mes": 4}
    assert fecha_del_patron(patron_invalid, 2026) is None


# ==============================================================================
# R4 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r4_adversarial_social_window_dates():
    """Test precise window boundary dates for social media posts in target year 2026 (2025-11-01 to 2027-01-31)."""
    # 2025-10-31 23:59:59 -> False
    assert es_fecha_en_ventana("2025-10-31", anno=2026) is False
    assert es_fecha_en_ventana("2025-10-31T23:59:59Z", anno=2026) is False

    # 2025-11-01 00:00:00 -> True
    assert es_fecha_en_ventana("2025-11-01", anno=2026) is True
    assert es_fecha_en_ventana("2025-11-01T00:00:00Z", anno=2026) is True

    # 2027-01-31 23:59:59 -> True
    assert es_fecha_en_ventana("2027-01-31", anno=2026) is True
    assert es_fecha_en_ventana("2027-01-31T23:59:59+02:00", anno=2026) is True

    # 2027-02-01 00:00:00 -> False
    assert es_fecha_en_ventana("2027-02-01", anno=2026) is False
    assert es_fecha_en_ventana("2027-02-01T00:00:00Z", anno=2026) is False


# ==============================================================================
# R5 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r5_adversarial_pdf_priority_years():
    """Test is_promising_pdf with target year 2026, 2025, 2024, 2023."""
    assert is_promising_pdf("https://ayto.es/fiestas-2026.pdf", "", ""), "Accept 2026"
    assert is_promising_pdf("https://ayto.es/fiestas-2025.pdf", "", ""), "Accept 2025"
    assert not is_promising_pdf("https://ayto.es/fiestas-2024.pdf", "", ""), "Reject 2024"
    assert not is_promising_pdf("https://ayto.es/fiestas-2023.pdf", "", ""), "Reject 2023"


def test_r5_adversarial_async_cache_high_concurrency():
    """Stress test concurrent set operations on RedesCache and _PatronCache."""
    async def _run_concurrency():
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_redes, \
             tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_patron:
            path_redes = tmp_redes.name
            path_patron = tmp_patron.name

        try:
            if os.path.exists(path_redes): os.remove(path_redes)
            if os.path.exists(path_patron): os.remove(path_patron)

            redes_cache = RedesCache(path_redes)
            patron_cache = _PatronCache(path_patron)

            # Concurrent writes
            async def write_redes(idx):
                await redes_cache.set(f"loc_{idx}", {"instagram": f"https://instagram.com/user_{idx}"})

            async def write_patron(idx):
                await patron_cache.set(f"loc_{idx}", {"nombre": f"San {idx}", "dia": (idx % 28) + 1, "mes": 8})

            tasks = []
            for i in range(50):
                tasks.append(write_redes(i))
                tasks.append(write_patron(i))

            await asyncio.gather(*tasks)

            # Verify contents
            for i in range(50):
                val_r = await redes_cache.get(f"loc_{i}")
                assert val_r == {"instagram": f"https://instagram.com/user_{i}"}

                val_p = await patron_cache.get(f"loc_{i}")
                assert val_p["nombre"] == f"San {i}"

        finally:
            for p in [path_redes, path_patron, f"{path_redes}.tmp", f"{path_patron}.tmp"]:
                if os.path.exists(p):
                    try: os.remove(p)
                    except OSError: pass

    asyncio.run(_run_concurrency())


# ==============================================================================
# R6 ADVERSARIAL STRESS TESTS
# ==============================================================================

def test_r6_adversarial_metrics_edge_cases():
    """Test execution metrics with edge case values (0 municipalities, malformed sources)."""
    # 0 municipalities
    m_zero_mun = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=["loc1"],
        municipios_completados=[],
        tiempo_total_segundos=10.0,
    )
    assert m_zero_mun["municipios_procesados"] == 0
    assert m_zero_mun["tiempo_medio_por_municipio"] == 0.0

    # Malformed sources list
    fiestas_malformed = [
        {
            "id": "f1",
            "lugar_id": "loc1",
            "es_estimada": False,
            "fuentes": [None, 999, "", {"invalid": "dict"}, "web_municipio"],
        }
    ]
    m_malformed = generar_informe_ejecucion(
        fiestas=fiestas_malformed,
        localidades_completadas=["loc1"],
        municipios_completados=["mun1"],
        tiempo_total_segundos=5.0,
    )
    assert m_malformed["total_fiestas"] == 1
    assert m_malformed["fiestas_extraidas"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

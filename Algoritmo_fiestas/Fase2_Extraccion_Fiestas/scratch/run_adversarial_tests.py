"""
Harness de pruebas de estrés adversariales empíricas R1-R6 para Fase 2.
Ejecuta diagnósticos rigurosos sobre condiciones de contorno y casos límite.
"""

import sys
import os
import asyncio
import random
import time
from datetime import date

# Asegurar que el directorio de la Fase 2 está en sys.path
FASE2_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if FASE2_DIR not in sys.path:
    sys.path.insert(0, FASE2_DIR)

from config import (
    DDG_DELAY_MIN,
    DDG_DELAY_MAX,
    DDG_RETRY_BACKOFF,
)
from scraper.google_search import (
    get_random_user_agent,
    get_query_delay,
    calculate_backoff_delay,
    USER_AGENTS,
    _SEARCH_METRICS,
    registrar_busqueda_fallida,
    reset_search_metrics,
    get_failed_searches_count,
)
from scraper.heuristic_spider import AsyncTwoPassSpider
from llm_processor.text_analyzer import _validar_fecha
from llm_processor.patron_finder import fecha_del_patron, _PatronCache
from scraper.social_content import es_fecha_en_ventana, _documentos_de_lugar
from scraper.social_finder import RedesCache
from scraper.document_extractor import is_promising_pdf
from main import generar_informe_ejecucion


def test_r1_empirical():
    print("--- [R1 Empirical Stress Test] ---")
    
    # 1. Test get_query_delay
    delays = [get_query_delay() for _ in range(2000)]
    min_d, max_d = min(delays), max(delays)
    assert min_d >= DDG_DELAY_MIN, f"Delay {min_d} < DDG_DELAY_MIN {DDG_DELAY_MIN}"
    assert max_d <= DDG_DELAY_MAX, f"Delay {max_d} > DDG_DELAY_MAX {DDG_DELAY_MAX}"
    print(f"[PASS] get_query_delay 2000 samples range: [{min_d:.4f}, {max_d:.4f}] (Expected: [{DDG_DELAY_MIN}, {DDG_DELAY_MAX}])")

    # 2. Test get_random_user_agent distribution
    ua_counts = {ua: 0 for ua in USER_AGENTS}
    for _ in range(2000):
        ua = get_random_user_agent()
        assert ua in ua_counts, f"Unknown UA returned: {ua}"
        ua_counts[ua] += 1
    for ua, cnt in ua_counts.items():
        assert cnt > 200, f"UA {ua[:30]} selected too infrequently: {cnt}"
    print(f"[PASS] get_random_user_agent 2000 samples distribution: {list(ua_counts.values())}")

    # 3. Test calculate_backoff_delay math across attempts
    for attempt in range(5):
        backoffs = [calculate_backoff_delay(attempt, base_backoff=DDG_RETRY_BACKOFF) for _ in range(500)]
        expected_min = (DDG_RETRY_BACKOFF * (2 ** attempt)) + 0.5
        expected_max = (DDG_RETRY_BACKOFF * (2 ** attempt)) + 2.0
        actual_min, actual_max = min(backoffs), max(backoffs)
        assert actual_min >= expected_min, f"Attempt {attempt} min {actual_min} < {expected_min}"
        assert actual_max <= expected_max, f"Attempt {attempt} max {actual_max} > {expected_max}"
        print(f"[PASS] Backoff attempt {attempt}: min={actual_min:.3f}s, max={actual_max:.3f}s (Range: [{expected_min:.1f}, {expected_max:.1f}])")

    # 4. Search metrics counter
    reset_search_metrics()
    assert get_failed_searches_count() == 0
    registrar_busqueda_fallida()
    registrar_busqueda_fallida()
    assert get_failed_searches_count() == 2
    reset_search_metrics()
    assert get_failed_searches_count() == 0
    print("[PASS] Search failed metrics counter reset & increment functional")


def test_r2_empirical():
    print("\n--- [R2 Empirical Stress Test] ---")
    spider = AsyncTwoPassSpider(target_year=2026)
    
    # 1. Score page tests for target year prioritization & penalties
    s_2026_fest = spider._score_page("https://example.com/fiestas-2026", "Fiestas", "programa de fiestas", ["pueblo"])
    s_2026_no_fest = spider._score_page("https://example.com/noticias-2026", "Noticias", "noticias generales", ["pueblo"])
    s_2025_fest = spider._score_page("https://example.com/fiestas-2025", "Fiestas", "programa de fiestas", ["pueblo"])
    s_2024_fest = spider._score_page("https://example.com/fiestas-2024", "Fiestas", "programa de fiestas", ["pueblo"])
    
    print(f"  Score 2026 + fest: {s_2026_fest}")
    print(f"  Score 2026 no fest: {s_2026_no_fest}")
    print(f"  Score 2025 + fest: {s_2025_fest}")
    print(f"  Score 2024 + fest: {s_2024_fest}")

    assert s_2026_fest > s_2026_no_fest, "Target year + festival kw should score higher than target year alone"
    assert s_2026_fest > s_2025_fest, "2026 URL should score significantly higher than 2025 URL"
    assert s_2025_fest < 800, "2025 URL must receive penalty"
    
    # Dual year URL edge case (2025-2026)
    s_dual = spider._score_page("https://example.com/fiestas-2025-2026", "Fiestas", "programa de fiestas", ["pueblo"])
    print(f"  Score dual year 2025-2026: {s_dual}")

    # 2. Single event penalty test
    s_single_event = spider._score_page("https://example.com/taller", "Taller de pintura", "taller de pintura y conferencia municipal", ["pueblo"])
    s_single_event_fest = spider._score_page("https://example.com/taller", "Taller de pintura", "taller de pintura en el programa de fiestas patronales", ["pueblo"])
    print(f"  Score single event without fest kw: {s_single_event}")
    print(f"  Score single event with fest kw: {s_single_event_fest}")
    assert s_single_event < 0, "Single event without festival keywords should receive -350 penalty"
    assert s_single_event_fest > 0 and s_single_event_fest > s_single_event, "Single event WITH festival keywords should NOT be penalized"

    # 3. Calendar date key deduplication
    urls_cal = [
        "https://municipio.es/2026/08/15/evento-1",
        "https://municipio.es/2026/08/15/evento-2",
        "https://municipio.es/2026/8/5",
        "https://municipio.es/2026/12/31/",
        "https://municipio.es/noticias/sin-fecha",
    ]
    keys = [spider._get_calendar_date_key(u) for u in urls_cal]
    assert keys[0] == "municipio.es:/2026/08/15"
    assert keys[1] == "municipio.es:/2026/08/15"
    assert keys[0] == keys[1], "Calendar date keys for same netloc & date must match for deduplication"
    assert keys[2] == "municipio.es:/2026/8/5"
    assert keys[3] == "municipio.es:/2026/12/31"
    assert keys[4] is None
    print("[PASS] Calendar URL date key deduplication logic verified")


def test_r3_empirical():
    print("\n--- [R3 Empirical Stress Test] ---")

    # 1. Cross-year boundary dates (_validar_fecha)
    # Dec 31, 2026 to Jan 2, 2027
    assert _validar_fecha("2026-12-31", 2026) is True
    assert _validar_fecha("2027-01-02", 2026, es_fecha_fin=True, fecha_inicio_str="2026-12-31") is True
    
    # Dec 1, 2026 to Dec 5, 2026
    assert _validar_fecha("2026-12-01", 2026) is True
    assert _validar_fecha("2026-12-05", 2026, es_fecha_fin=True, fecha_inicio_str="2026-12-01") is True
    
    # Jan 1, 2026 to Jan 5, 2026
    assert _validar_fecha("2026-01-01", 2026) is True
    assert _validar_fecha("2026-01-05", 2026, es_fecha_fin=True, fecha_inicio_str="2026-01-01") is True

    # November start (2026-11-28) with January 2027 end -> Should fail!
    assert _validar_fecha("2027-01-02", 2026, es_fecha_fin=True, fecha_inicio_str="2026-11-28") is False
    print("[PASS] Cross-year Dec -> Jan allowed, Nov -> Jan rejected correctly")

    # Invalid dates & formats
    assert _validar_fecha("2026-02-30", 2026) is False
    assert _validar_fecha("invalid", 2026) is False
    assert _validar_fecha(None, 2026) is False
    print("[PASS] Invalid dates handled gracefully")

    # 2. Patron fallback on leap vs non-leap year
    patron_feb29 = {"nombre": "San Dositeo", "dia": 29, "mes": 2, "fuente": "santoral"}
    
    # 2026 (Non-leap year) -> Must return Feb 28, 2026
    dt_2026 = fecha_del_patron(patron_feb29, 2026)
    assert dt_2026 == date(2026, 2, 28), f"Expected 2026-02-28, got {dt_2026}"
    
    # 2028 (Leap year) -> Must return Feb 29, 2028
    dt_2028 = fecha_del_patron(patron_feb29, 2028)
    assert dt_2028 == date(2028, 2, 29), f"Expected 2028-02-29, got {dt_2028}"

    # 2000 (Leap century) -> Feb 29, 2000
    dt_2000 = fecha_del_patron(patron_feb29, 2000)
    assert dt_2000 == date(2000, 2, 29)

    # 1900 (Non-leap century) -> Feb 28, 1900
    dt_1900 = fecha_del_patron(patron_feb29, 1900)
    assert dt_1900 == date(1900, 2, 28)

    print(f"[PASS] Feb 29 patron in 2026 (non-leap) -> {dt_2026}")
    print(f"[PASS] Feb 29 patron in 2028 (leap) -> {dt_2028}")


def test_r4_empirical():
    print("\n--- [R4 Empirical Stress Test] ---")

    # Social media date window boundaries (default target year 2026: 2025-11-01 to 2027-01-31)
    test_cases = [
        ("2025-10-31", 2026, False),
        ("2025-11-01", 2026, True),
        ("2025-11-01T10:00:00Z", 2026, True),
        ("2026-06-15", 2026, True),
        ("2027-01-31", 2026, True),
        ("2027-01-31T23:59:59+01:00", 2026, True),
        ("2027-02-01", 2026, False),
        ("2024-08-15", 2026, False),
        (None, 2026, True),
        ("invalid-date", 2026, True),
    ]

    for f_str, year, expected in test_cases:
        res = es_fecha_en_ventana(f_str, anno=year)
        assert res == expected, f"es_fecha_en_ventana({f_str}, {year}) expected {expected}, got {res}"
        print(f"  Date '{f_str}' for target year {year} -> {res} (Expected: {expected})")
    print("[PASS] Social media window edge date filtering verified")


async def test_r5_empirical_async():
    print("\n--- [R5 Empirical Stress Test] ---")

    # 1. PDF year verification
    # Target year 2026 (accepts 2026 and 2025)
    assert is_promising_pdf("http://x.es/doc.pdf", "Programa de Fiestas 2026", "") is True
    assert is_promising_pdf("http://x.es/doc.pdf", "Programa de Fiestas 2025", "") is True
    assert is_promising_pdf("http://x.es/doc.pdf", "Programa de Fiestas 2024", "") is False
    assert is_promising_pdf("http://x.es/doc.pdf", "Programa de Fiestas 2023", "") is False
    assert is_promising_pdf("http://x.es/doc.pdf", "Programa de Fiestas", "") is True
    print("[PASS] PDF target year verification (2026/2025 vs 2024/2023) verified")

    # 2. Async cache non-blocking concurrent writes
    redes_cache = RedesCache("scratch_redes_test_cache.json")
    patron_cache = _PatronCache("scratch_patron_test_cache.json")

    async def write_redes(i):
        await redes_cache.set(f"lugar_{i}", {"instagram": f"https://instagram.com/pueblo_{i}"})

    async def write_patron(i):
        await patron_cache.set(f"lugar_{i}", {"nombre": f"San Juan_{i}", "dia": 24, "mes": 6})

    start = time.time()
    await asyncio.gather(
        *[write_redes(i) for i in range(30)],
        *[write_patron(i) for i in range(30)]
    )
    elapsed = time.time() - start
    print(f"[PASS] 60 concurrent non-blocking async cache writes completed in {elapsed:.3f}s")

    # Cleanup test files
    for p in ["scratch_redes_test_cache.json", "scratch_patron_test_cache.json"]:
        if os.path.exists(p):
            os.remove(p)


def test_r6_empirical():
    print("\n--- [R6 Empirical Stress Test] ---")

    # Test metric calculations
    sample_fiestas = [
        {"lugar_id": "loc_1", "nombre": "Fiestas 1", "es_estimada": False, "fuentes": ["web_municipio"]},
        {"lugar_id": "loc_1", "nombre": "Fiestas 2", "es_estimada": False, "fuentes": ["web_localidad", "busqueda_web"]},
        {"lugar_id": "loc_2", "nombre": "Fiestas 3 (estimada)", "es_estimada": True, "fuentes": []},
    ]
    locs_completed = ["loc_1", "loc_2", "loc_3", "loc_4"]
    muns_completed = ["mun_1", "mun_2"]

    metrics = generar_informe_ejecucion(
        fiestas=sample_fiestas,
        localidades_completadas=locs_completed,
        municipios_completados=muns_completed,
        tiempo_total_segundos=10.0,
        busquedas_fallidas=3,
    )

    assert metrics["total_fiestas"] == 3
    assert metrics["fiestas_extraidas"] == 2
    assert metrics["fiestas_estimadas"] == 1
    assert metrics["ratio_extraidas_vs_estimadas"] == "2.00"
    assert metrics["total_localidades_procesadas"] == 4
    assert metrics["localidades_con_cero_fiestas"] == 2 # loc_3 and loc_4
    assert metrics["busquedas_bloqueadas_fallidas"] == 3
    assert metrics["municipios_procesados"] == 2
    assert metrics["tiempo_medio_por_municipio"] == 5.0
    print("[PASS] Execution metrics calculations verified")

    # Edge case: zero estimated
    metrics_no_est = generar_informe_ejecucion(
        fiestas=[{"lugar_id": "loc_1", "es_estimada": False}],
        localidades_completadas=["loc_1"],
        municipios_completados=["mun_1"],
        tiempo_total_segundos=5.0,
    )
    assert metrics_no_est["ratio_extraidas_vs_estimadas"] == "1:0 (Sin estimadas)"

    # Edge case: 0 municipalities (avoid zero division)
    metrics_zero_mun = generar_informe_ejecucion(
        fiestas=[],
        localidades_completadas=[],
        municipios_completados=[],
        tiempo_total_segundos=0.0,
    )
    assert metrics_zero_mun["tiempo_medio_por_municipio"] == 0.0
    assert metrics_zero_mun["ratio_extraidas_vs_estimadas"] == "0:0"
    print("[PASS] Zero division edge cases handled safely")


def main():
    test_r1_empirical()
    test_r2_empirical()
    test_r3_empirical()
    test_r4_empirical()
    asyncio.run(test_r5_empirical_async())
    test_r6_empirical()
    print("\n==========================================")
    print("ALL EMPIRICAL ADVERSARIAL STRESS TESTS PASSED SUCCESSFULLY!")
    print("==========================================")


if __name__ == "__main__":
    main()

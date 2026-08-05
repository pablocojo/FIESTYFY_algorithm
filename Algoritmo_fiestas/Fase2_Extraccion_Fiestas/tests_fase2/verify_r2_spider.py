"""
Script de verificación aislado para el Requisito R2: Priorización de Spider 2026,
deduplicación de enlaces de calendario y filtrado de eventos municipales individuales.
"""

import sys
import os
import re
import pytest

# Asegurar que Fase2_Extraccion_Fiestas está en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.heuristic_spider import AsyncTwoPassSpider


def test_score_page_target_year_scoring():
    """Verifica que _score_page acepta target_year y aplica bonus/penalizaciones correspondientes."""
    locality = ["San Vicente"]

    # Baseline score para San Vicente sin años ni eventos
    score_base = AsyncTwoPassSpider._score_page(
        url="https://sanvicente.es/noticias/general",
        title="Información General",
        page_text="Página general del municipio San Vicente.",
        locality_names=locality,
        target_year=2026,
    )

    # 1. URL con año anterior (2025) -> Penalización -300 pts
    score_2025 = AsyncTwoPassSpider._score_page(
        url="https://sanvicente.es/noticias/2025/resumen",
        title="Información General",
        page_text="Página del municipio San Vicente.",
        locality_names=locality,
        target_year=2026,
    )
    assert score_2025 == score_base - 300, f"Expected {score_base - 300}, got {score_2025}"

    # 2. URL con año objetivo (2026) sin palabras festivas -> Bonus +150 pts
    score_2026_solo = AsyncTwoPassSpider._score_page(
        url="https://sanvicente.es/noticias/2026/resumen",
        title="Información General",
        page_text="Página del municipio San Vicente.",
        locality_names=locality,
        target_year=2026,
    )
    assert score_2026_solo == score_base + 150, f"Expected {score_base + 150}, got {score_2026_solo}"

    # 3. URL con año objetivo (2026) Y palabras clave festivas -> Bonus +350 pts + kw bonus
    score_2026_fiesta = AsyncTwoPassSpider._score_page(
        url="https://sanvicente.es/noticias/2026/programa-fiestas",
        title="Programa de Fiestas 2026",
        page_text="Fiestas Patronales de San Vicente 2026.",
        locality_names=locality,
        target_year=2026,
    )
    # Debe ser significativamente superior a la del 2025 y 2026 solo
    assert score_2026_fiesta > score_2026_solo
    assert score_2026_fiesta > score_2025 + 600


def test_score_page_single_unrelated_event_filter():
    """Verifica el filtrado de eventos municipales individuales sin contenido festivo (-350 pts)."""
    locality = ["Pueblo"]

    # Eventos individuales sin festival keywords
    eventos_irrelevantes = [
        "taller de cerámica para adultos",
        "charla sobre compostaje dométsico",
        "conferencia sobre historia local",
        "pleno extraordinario del ayuntamiento",
        "exposicion de pintura local",
        "corte de agua por obras en la red",
    ]

    for evento in eventos_irrelevantes:
        score = AsyncTwoPassSpider._score_page(
            url=f"https://pueblo.es/agenda/{evento.replace(' ', '-')}",
            title=evento,
            page_text=f"Aviso en el Municipio de Pueblo: {evento}",
            locality_names=locality,
            target_year=2026,
        )
        # El score debe incluir la penalización de -350 por evento no festivo
        score_sin_evento = AsyncTwoPassSpider._score_page(
            url="https://pueblo.es/agenda/aviso-general",
            title="Aviso general",
            page_text="Aviso en el Municipio de Pueblo",
            locality_names=locality,
            target_year=2026,
        )
        assert score <= score_sin_evento - 350, f"Error en filtrado de evento irrelevante '{evento}': score {score}"

    # Evento con palabra clave de festival -> NO debe recibir penalización de -350
    score_taller_fiesta = AsyncTwoPassSpider._score_page(
        url="https://pueblo.es/agenda/taller-banderines-fiesta-patronal",
        title="Taller de banderines para la fiesta patronal",
        page_text="Taller infantil de preparación para las fiestas patronales de Pueblo.",
        locality_names=locality,
        target_year=2026,
    )
    assert score_taller_fiesta > 500  # Score alto positivo


def test_calendar_url_deduplication():
    """Verifica la deduplicación de URLs de calendario que coinciden con el patrón regex."""
    spider = AsyncTwoPassSpider(target_year=2026)

    # Comprobar la extracción del date key por regex
    url1 = "https://ayuntamiento.es/agenda/2026/05/12/taller-reciclaje"
    url2 = "https://ayuntamiento.es/agenda/2026/05/12/charla-salud"
    url3 = "https://ayuntamiento.es/agenda/2026/05/13/conferencia"
    url_no_cal = "https://ayuntamiento.es/fiestas-patronales-2026"

    key1 = spider._get_calendar_date_key(url1)
    key2 = spider._get_calendar_date_key(url2)
    key3 = spider._get_calendar_date_key(url3)
    key_no_cal = spider._get_calendar_date_key(url_no_cal)

    assert key1 == "ayuntamiento.es:/2026/05/12"
    assert key2 == "ayuntamiento.es:/2026/05/12"
    assert key3 == "ayuntamiento.es:/2026/05/13"
    assert key_no_cal is None

    # Simular seguimiento en seen_calendar_dates
    seen = set()
    assert key1 not in seen
    seen.add(key1)

    assert key2 in seen  # Deduplicada
    assert key3 not in seen  # Nueva fecha

    seen.add(key3)
    assert len(seen) == 2


if __name__ == "__main__":
    print("Ejecutando verificaciones aisladas para R2 (heuristic_spider.py)...")
    test_score_page_target_year_scoring()
    print(" [OK] test_score_page_target_year_scoring")
    test_score_page_single_unrelated_event_filter()
    print(" [OK] test_score_page_single_unrelated_event_filter")
    test_calendar_url_deduplication()
    print(" [OK] test_calendar_url_deduplication")
    print("Todas las verificaciones de R2 se completaron con ÉXITO.")

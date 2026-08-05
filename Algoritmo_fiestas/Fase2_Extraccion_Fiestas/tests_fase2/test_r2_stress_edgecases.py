"""
Tests de estrés y casos límite adicionales para R2: Priorización de Spider 2026.
"""

import pytest
import urllib.parse
from scraper.heuristic_spider import AsyncTwoPassSpider


def test_calendar_date_key_variations():
    """Prueba variaciones de URLs con fechas en path."""
    spider = AsyncTwoPassSpider(target_year=2026)

    # 1. URLs con formato AAAA/MM/DD
    assert spider._get_calendar_date_key("https://madrid.es/agenda/2026/08/15/evento1") == "madrid.es:/2026/08/15"
    assert spider._get_calendar_date_key("https://MADRID.ES/agenda/2026/08/15/") == "madrid.es:/2026/08/15"

    # 2. URLs con formato AAAA/M/D (sin ceros a la izquierda)
    assert spider._get_calendar_date_key("https://valencia.es/noticias/2026/5/3") == "valencia.es:/2026/5/3"

    # 3. URLs del siglo XX (1999)
    assert spider._get_calendar_date_key("https://archivo.es/historico/1999/12/31/fiesta") == "archivo.es:/1999/12/31"

    # 4. URLs no de calendario (sin patrón /YYYY/MM/DD/)
    assert spider._get_calendar_date_key("https://madrid.es/fiestas-2026") is None
    assert spider._get_calendar_date_key("https://madrid.es/noticias?date=2026-08-15") is None


def test_score_page_coofficial_languages():
    """Verifica que las palabras clave en idiomas cooficiales reciben bonus de fiestas."""
    loc = ["Bilbao"]

    # Euskera
    score_euskera = AsyncTwoPassSpider._score_page(
        url="https://bilbao.eus/jaiak-2026",
        title="Aste Nagusia 2026",
        page_text="Bilboko jaiak eta egitaraua",
        locality_names=loc,
        target_year=2026,
    )
    # Debería tener bonus de localidad (+500), 2026 en URL con festival kw (+350), kw "jaiak", "egitaraua", "jaia"
    assert score_euskera >= 800

    # Català / Valencià
    score_cat = AsyncTwoPassSpider._score_page(
        url="https://gandia.org/festes-2026",
        title="Festa Major 2026",
        page_text="Programació de les festes patronals i revetlla",
        locality_names=["Gandia"],
        target_year=2026,
    )
    assert score_cat >= 800

    # Galego
    score_gal = AsyncTwoPassSpider._score_page(
        url="https://vigo.org/festas-2026",
        title="Festas Patronais 2026",
        page_text="Programa de festas e foliada en Vigo",
        locality_names=["Vigo"],
        target_year=2026,
    )
    assert score_gal >= 800


def test_score_page_prioritization_matrix():
    """Matriz de priorización: 2026 con Fiestas > 2026 Sin Fiestas > 2025 con Fiestas > 2025 sin Fiestas."""
    loc = ["Sevilla"]

    url_2026_fiesta = "https://sevilla.org/2026/feria-de-abril"
    url_2026_noticia = "https://sevilla.org/2026/noticia-obras"
    url_2025_fiesta = "https://sevilla.org/2025/feria-de-abril"
    url_2025_noticia = "https://sevilla.org/2025/noticia-obras"

    s_2026_f = AsyncTwoPassSpider._score_page(url_2026_fiesta, "Feria 2026", "Feria de abril en Sevilla", loc, 2026)
    s_2026_n = AsyncTwoPassSpider._score_page(url_2026_noticia, "Obras 2026", "Información de obras en Sevilla", loc, 2026)
    s_2025_f = AsyncTwoPassSpider._score_page(url_2025_fiesta, "Feria 2025", "Feria de abril en Sevilla", loc, 2026)
    s_2025_n = AsyncTwoPassSpider._score_page(url_2025_noticia, "Obras 2025", "Información de obras en Sevilla", loc, 2026)

    assert s_2026_f > s_2026_n
    assert s_2026_f > s_2025_f
    assert s_2025_f > s_2025_n
    assert s_2026_n > s_2025_n

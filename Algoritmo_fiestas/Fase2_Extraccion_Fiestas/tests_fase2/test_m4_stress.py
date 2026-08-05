"""
Adversarial Stress Test Suite for Milestone M4 Date Filtering in `scraper/social_content.py`
Created by Challenger 2 (Milestone M4)
"""

from scraper.social_content import es_fecha_en_ventana, cargar_documentos_rrss


def test_boundary_dates_2026_default_window():
    """
    Test exact boundaries for target year 2026:
    Window: 2025-11-01 to 2027-01-31.
    """
    # Lower boundary: Oct 31, 2025 vs Nov 1, 2025
    assert es_fecha_en_ventana("2025-10-31", anno=2026) is False, "Oct 31, 2025 should be outside window"
    assert es_fecha_en_ventana("2025-11-01", anno=2026) is True, "Nov 1, 2025 should be inside window"
    
    # Mid-range dates
    assert es_fecha_en_ventana("2025-12-15", anno=2026) is True
    assert es_fecha_en_ventana("2026-01-01", anno=2026) is True
    assert es_fecha_en_ventana("2026-06-30", anno=2026) is True
    assert es_fecha_en_ventana("2026-12-31", anno=2026) is True

    # Upper boundary: Jan 31, 2027 vs Feb 1, 2027
    assert es_fecha_en_ventana("2027-01-31", anno=2026) is True, "Jan 31, 2027 should be inside window"
    assert es_fecha_en_ventana("2027-02-01", anno=2026) is False, "Feb 1, 2027 should be outside window"


def test_iso_timestamps_and_timezones():
    """
    Test ISO 8601 timestamps with times, UTC 'Z', and timezone offsets.
    """
    # Lower boundary timestamps
    assert es_fecha_en_ventana("2025-10-31T23:59:59Z", anno=2026) is False
    assert es_fecha_en_ventana("2025-11-01T00:00:00Z", anno=2026) is True
    assert es_fecha_en_ventana("2025-11-01T00:00:00+02:00", anno=2026) is True
    assert es_fecha_en_ventana("2025-10-31T23:59:59+02:00", anno=2026) is False

    # Upper boundary timestamps
    assert es_fecha_en_ventana("2027-01-31T23:59:59Z", anno=2026) is True
    assert es_fecha_en_ventana("2027-01-31T23:59:59.999999+00:00", anno=2026) is True
    assert es_fecha_en_ventana("2027-02-01T00:00:00Z", anno=2026) is False
    assert es_fecha_en_ventana("2027-02-01T00:00:01+01:00", anno=2026) is False


def test_malformed_and_unparseable_dates():
    """
    Test fallback behavior for missing, malformed, or non-ISO dates.
    Fallback contract: unparseable dates should return True (keep post).
    """
    # None / Empty
    assert es_fecha_en_ventana(None, anno=2026) is True
    assert es_fecha_en_ventana("", anno=2026) is True
    assert es_fecha_en_ventana("   ", anno=2026) is True

    # Garbage strings
    assert es_fecha_en_ventana("not-a-date", anno=2026) is True
    assert es_fecha_en_ventana("01/11/2025", anno=2026) is True
    assert es_fecha_en_ventana("31-10-2025", anno=2026) is True
    assert es_fecha_en_ventana("2026/05/10", anno=2026) is True

    # Invalid calendar dates
    assert es_fecha_en_ventana("2026-13-01", anno=2026) is True
    assert es_fecha_en_ventana("2026-02-30", anno=2026) is True
    assert es_fecha_en_ventana("2026-00-00", anno=2026) is True

    # Non-string types passed
    assert es_fecha_en_ventana(20260101, anno=2026) is True
    assert es_fecha_en_ventana(123.45, anno=2026) is True


def test_leap_years_and_custom_years():
    """
    Test leap year (2028-02-29) and custom target year parameters.
    """
    # Leap year 2028
    assert es_fecha_en_ventana("2028-02-29", anno=2028) is True
    # Feb 29 2028 tested against 2026 target (window 2025-11-01 to 2027-01-31) -> False
    assert es_fecha_en_ventana("2028-02-29", anno=2026) is False

    # Custom target year 2025 (window 2024-11-01 to 2026-01-31)
    assert es_fecha_en_ventana("2024-10-31", anno=2025) is False
    assert es_fecha_en_ventana("2024-11-01", anno=2025) is True
    assert es_fecha_en_ventana("2026-01-31", anno=2025) is True
    assert es_fecha_en_ventana("2026-02-01", anno=2025) is False

    # Custom mes_inicio_previo=10 (October) for year 2026
    assert es_fecha_en_ventana("2025-09-30", anno=2026, mes_inicio_previo=10) is False
    assert es_fecha_en_ventana("2025-10-01", anno=2026, mes_inicio_previo=10) is True


def test_integration_in_cargar_documentos_rrss(monkeypatch):
    """
    Test filtering behavior integrated into document loading pipeline.
    """
    fake_cache = {
        "loc-1": {
            "instagram": [
                # In window
                {"texto": "Post 1 (valid)", "fecha": "2025-11-01"},
                {"texto": "Post 2 (valid)", "fecha_publicacion": "2026-08-15"},
                {"texto": "Post 3 (valid end)", "fecha": "2027-01-31"},
                # Out of window
                {"texto": "Post 4 (too old)", "fecha": "2025-10-31"},
                {"texto": "Post 5 (too new)", "fecha": "2027-02-01"},
                # Malformed (kept)
                {"texto": "Post 6 (malformed date)", "fecha": "fecha_invalida"},
            ]
        }
    }
    monkeypatch.setattr("scraper.social_content._cache", fake_cache)
    
    localidad = {"id": "loc-1", "nombre": "Pueblo Test"}
    municipio = {"id": "mun-1", "nombre": "Municipio Test"}
    
    docs = cargar_documentos_rrss(localidad, municipio, anno=2026)
    assert len(docs) == 1
    text = docs[0]["texto"]
    
    # Assert included posts
    assert "Post 1 (valid)" in text
    assert "[POST 2025-11-01]" in text
    assert "Post 2 (valid)" in text
    assert "[POST 2026-08-15]" in text
    assert "Post 3 (valid end)" in text
    assert "[POST 2027-01-31]" in text
    assert "Post 6 (malformed date)" in text
    
    # Assert excluded posts
    assert "Post 4 (too old)" not in text
    assert "Post 5 (too new)" not in text

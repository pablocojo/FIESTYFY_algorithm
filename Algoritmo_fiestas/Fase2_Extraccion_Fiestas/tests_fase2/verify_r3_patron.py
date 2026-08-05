"""
Verification script for Requirement R3 (Leap Year Patron Saint Edge Case).
Verifies that fecha_del_patron returns Feb 28, 2026 for a Feb 29 patron saint in target year 2026.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llm_processor.patron_finder import fecha_del_patron


def test_fecha_del_patron_feb29_non_leap_year():
    """Verify that a Feb 29 patron saint falls back to Feb 28 in non-leap year (2026)."""
    patron_feb29 = {"nombre": "San Augusto", "dia": 29, "mes": 2}
    result = fecha_del_patron(patron_feb29, 2026)
    assert result == date(2026, 2, 28), f"Expected 2026-02-28, got {result}"


def test_fecha_del_patron_feb29_leap_year():
    """Verify that a Feb 29 patron saint remains Feb 29 in leap year (2028)."""
    patron_feb29 = {"nombre": "San Augusto", "dia": 29, "mes": 2}
    result = fecha_del_patron(patron_feb29, 2028)
    assert result == date(2028, 2, 29), f"Expected 2028-02-29, got {result}"


if __name__ == "__main__":
    test_fecha_del_patron_feb29_non_leap_year()
    test_fecha_del_patron_feb29_leap_year()
    print("VERIFY R3 PATRON PASSED: fecha_del_patron handles Feb 29 correctly in non-leap and leap years.")

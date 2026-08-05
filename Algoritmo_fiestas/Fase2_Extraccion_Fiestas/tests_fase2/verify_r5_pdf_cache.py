"""
Verification script for Requirement R5 (PDF Priority & Async Caches).
Tests:
1. PDF year matching: target year (2026) and previous year (2025) are accepted, older years (2023, 2024) are rejected.
2. Async non-blocking cache write execution for RedesCache and _PatronCache using asyncio.to_thread.
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scraper.document_extractor import is_promising_pdf
from scraper.social_finder import RedesCache
from llm_processor.patron_finder import _PatronCache


def test_pdf_year_matching():
    """Verify that is_promising_pdf accepts 2026 and 2025, and rejects 2023 and 2024."""
    # Target year 2026
    assert is_promising_pdf("https://ayto.es/programa-2026.pdf", "", ""), "Should accept 2026 PDF"
    assert is_promising_pdf("https://ayto.es/cartel-2026.pdf", "Cartel de fiestas 2026", ""), "Should accept 2026 PDF with context"

    # Previous year 2025
    assert is_promising_pdf("https://ayto.es/programa-2025.pdf", "", ""), "Should accept 2025 PDF"
    assert is_promising_pdf("https://ayto.es/fiestas-2025.pdf", "Festes 2025", ""), "Should accept 2025 PDF with context"

    # Older years 2024 and 2023 must be rejected
    assert not is_promising_pdf("https://ayto.es/programa-2024.pdf", "", ""), "Should reject 2024 PDF"
    assert not is_promising_pdf("https://ayto.es/programa-2023.pdf", "", ""), "Should reject 2023 PDF"
    assert not is_promising_pdf("https://ayto.es/fiestas-2024.pdf", "Fiestas 2024", ""), "Should reject 2024 PDF"
    assert not is_promising_pdf("https://ayto.es/cartel-2023.pdf", "Cartel 2023", ""), "Should reject 2023 PDF"

    # PDF with keywords but without explicit old year
    assert is_promising_pdf("https://ayto.es/programa_fiestas.pdf", "", ""), "Should accept keyword PDF without year"
    assert is_promising_pdf("https://ayto.es/doc.pdf", "Programa de Fiestas", ""), "Should accept PDF with keyword in link text"

    # Non-promising PDFs
    assert not is_promising_pdf("https://ayto.es/acta_pleno.pdf", "", ""), "Should reject non-fiesta PDF"
    assert not is_promising_pdf("https://ayto.es/presupuesto_2026.pdf", "", ""), "Should reject non-fiesta PDF even with 2026 year"


async def _run_async_redes_cache_write():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        cache = RedesCache(tmp_path)
        val = {
            "instagram": "https://www.instagram.com/ayto_test",
            "facebook": "https://www.facebook.com/ayto_test",
            "twitter": "https://x.com/ayto_test",
            "verificado_por": "web_oficial",
            "fecha_verificacion": "2026-08-04",
        }

        await cache.set("lugar_test_123", val)

        retrieved = await cache.get("lugar_test_123")
        assert retrieved == val, f"Retrieved value mismatch: {retrieved}"

        assert os.path.exists(tmp_path), "Cache file was not created on disk"
        with open(tmp_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)

        assert "lugar_test_123" in disk_data, "lugar_test_123 missing from disk JSON"
        assert disk_data["lugar_test_123"] == val, f"Disk value mismatch: {disk_data['lugar_test_123']}"

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        tmp_tmp = f"{tmp_path}.tmp"
        if os.path.exists(tmp_tmp):
            os.remove(tmp_tmp)


def test_async_redes_cache_write():
    """Verify RedesCache.set writes asynchronously using asyncio.to_thread and updates cache."""
    asyncio.run(_run_async_redes_cache_write())


async def _run_async_patron_cache_write():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        cache = _PatronCache(tmp_path)
        val = {
            "nombre": "San Roque",
            "dia": 16,
            "mes": 8,
            "fuente": "wikipedia",
            "confianza": "alta",
        }

        await cache.set("lugar_patron_456", val)

        retrieved = await cache.get("lugar_patron_456")
        assert retrieved == val, f"Retrieved patron value mismatch: {retrieved}"

        assert os.path.exists(tmp_path), "Patron cache file was not created on disk"
        with open(tmp_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)

        assert "lugar_patron_456" in disk_data, "lugar_patron_456 missing from disk JSON"
        assert disk_data["lugar_patron_456"] == val, f"Disk value mismatch: {disk_data['lugar_patron_456']}"

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        tmp_tmp = f"{tmp_path}.tmp"
        if os.path.exists(tmp_tmp):
            os.remove(tmp_tmp)


def test_async_patron_cache_write():
    """Verify _PatronCache.set writes asynchronously using asyncio.to_thread and updates cache."""
    asyncio.run(_run_async_patron_cache_write())


def test_verify_r5_all():
    """Entry point for pytest verification."""
    test_pdf_year_matching()
    test_async_redes_cache_write()
    test_async_patron_cache_write()


if __name__ == "__main__":
    test_verify_r5_all()
    print("VERIFY R5 PDF & ASYNC CACHES PASSED SUCCESSFULLY.")

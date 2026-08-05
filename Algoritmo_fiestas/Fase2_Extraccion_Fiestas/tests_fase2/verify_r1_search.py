"""
Script de verificación aislado para el Requisito R1 (Resilient Web Search).
Verifica:
1. Rotación de User-Agents desde un pool realista.
2. Delays aleatorios en el rango [2.0, 4.5] segundos.
3. Backoff exponencial con jitter aleatorio para reintentos de búsqueda:
   (base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0).
4. Ausencia de Google Custom Search API.
"""

import sys
import os
import random
import pytest
import asyncio
from unittest.mock import patch, MagicMock

# Asegurar importación del paquete desde la raíz de Fase2_Extraccion_Fiestas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    DDG_DELAY_MIN,
    DDG_DELAY_MAX,
    DDG_RETRY_BACKOFF,
    DDG_MAX_RETRIES,
)
from scraper.google_search import (
    USER_AGENTS,
    get_random_user_agent,
    _get_random_headers,
    get_query_delay,
    calculate_backoff_delay,
    _fetch_search_results,
    get_failed_searches_count,
    reset_search_metrics,
)


def test_r1_user_agent_rotation():
    """Verifica que los User-Agents rotan correctamente desde una lista de navegadores realistas."""
    assert len(USER_AGENTS) >= 5, "El pool de User-Agents debe tener al menos 5 navegadores."
    
    # Probar que get_random_user_agent devuelve User-Agents del pool
    sampled_agents = set()
    for _ in range(100):
        ua = get_random_user_agent()
        assert ua in USER_AGENTS, f"User-Agent inesperado: {ua}"
        sampled_agents.add(ua)

    # Debe haber rotación (más de 1 User-Agent distinto seleccionado en 100 llamadas)
    assert len(sampled_agents) > 1, "No hay rotación de User-Agents; siempre devuelve el mismo."
    assert len(sampled_agents) == len(USER_AGENTS), "No se han rotado todos los User-Agents del pool."

    # Verificar que _get_random_headers incluye User-Agent rotado y cabeceras estándar
    headers = _get_random_headers()
    assert "User-Agent" in headers
    assert headers["User-Agent"] in USER_AGENTS
    assert "Accept" in headers
    assert "Accept-Language" in headers


def test_r1_random_query_delay_range():
    """Verifica que los delays entre queries están estrictamente en el rango [2.0, 4.5]s."""
    assert DDG_DELAY_MIN == 2.0, f"DDG_DELAY_MIN esperado 2.0, obtenido {DDG_DELAY_MIN}"
    assert DDG_DELAY_MAX == 4.5, f"DDG_DELAY_MAX esperado 4.5, obtenido {DDG_DELAY_MAX}"

    delays = [get_query_delay() for _ in range(200)]

    for d in delays:
        assert 2.0 <= d <= 4.5, f"Delay fuera de rango [2.0, 4.5]: {d}"

    # Verificar aleatoriedad (no constante)
    min_d = min(delays)
    max_d = max(delays)
    assert min_d < max_d, "Los delays no son aleatorios (min == max)."
    assert (max_d - min_d) > 1.5, f"El rango de variación es insuficiente: {max_d - min_d}"


def test_r1_exponential_backoff_with_jitter():
    """
    Verifica que el backoff exponencial sigue la fórmula:
    (base_backoff * (2 ** attempt)) + random.uniform(0.5, 2.0)
    """
    base = DDG_RETRY_BACKOFF  # 3.0 por defecto
    assert base == 3.0, f"Base backoff esperada 3.0, obtenida {base}"

    for attempt in range(4):
        expected_min = (base * (2 ** attempt)) + 0.5
        expected_max = (base * (2 ** attempt)) + 2.0

        samples = [calculate_backoff_delay(attempt, base) for _ in range(50)]

        for delay in samples:
            assert expected_min <= delay <= expected_max, (
                f"Attempt {attempt}: delay {delay:.3f}s fuera del rango [{expected_min}, {expected_max}]"
            )

        # Confirmar variación por jitter
        assert min(samples) != max(samples), f"Sin jitter en intento {attempt}"

    # Verificar comportamiento exponencial estricto entre intentos consecutivos
    delay_0 = calculate_backoff_delay(0, base)
    delay_1 = calculate_backoff_delay(1, base)
    delay_2 = calculate_backoff_delay(2, base)

    # Para attempt=0: [3.5, 5.0], attempt=1: [6.5, 8.0], attempt=2: [12.5, 14.0]
    assert delay_0 < delay_1 < delay_2, f"Falló crecimiento exponencial: {delay_0}, {delay_1}, {delay_2}"


def test_r1_no_google_custom_search_api():
    """Verifica que NO se utiliza Google Custom Search API en el scraper de búsqueda."""
    import scraper.google_search as gs_module

    with open(gs_module.__file__, "r", encoding="utf-8") as f:
        content = f.read()

    # Comprobar que no hay referencias a Google Custom Search API o claves API
    forbidden_terms = [
        "customsearch",
        "googleapis.com",
        "google_api_key",
        "GOOGLE_SEARCH_KEY",
        "developerKey",
    ]
    for term in forbidden_terms:
        assert term.lower() not in content.lower(), f"Se detectó referencia a Google Custom Search API: {term}"


def test_r1_fetch_search_results_backoff_integration():
    """Verifica la integración del backoff exponencial cuando los buscadores fallan."""
    async def _run():
        reset_search_metrics()
        
        mock_session = MagicMock()
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        # Simular que todas las búsquedas fallan (retornan lista vacía)
        with patch("scraper.google_search.asyncio.to_thread", side_effect=lambda func, q: []), \
             patch("scraper.google_search.asyncio.sleep", side_effect=mock_sleep):
            
            results = await _fetch_search_results(mock_session, "fiestas pueblo 2026")

            assert results == [], "Debe retornar lista vacía tras agotar reintentos."
            
            # Deben haberse registrado reintentos con backoff exponencial
            # Para DDG_MAX_RETRIES = 3, se hacen 2 esperas de reintento (tras intento 0 e intento 1)
            assert len(sleep_calls) == DDG_MAX_RETRIES - 1, f"Se esperaban {DDG_MAX_RETRIES - 1} sleeps, hubo {len(sleep_calls)}"

            # Verificar que los delays crecen exponencialmente
            # Intento 0: (3.0 * 2^0) + jitter -> [3.5, 5.0]
            # Intento 1: (3.0 * 2^1) + jitter -> [6.5, 8.0]
            assert 3.5 <= sleep_calls[0] <= 5.0, f"Primer backoff fuera de rango: {sleep_calls[0]}"
            assert 6.5 <= sleep_calls[1] <= 8.0, f"Segundo backoff fuera de rango: {sleep_calls[1]}"
            assert sleep_calls[0] < sleep_calls[1], "El backoff no es creciente."

    asyncio.run(_run())


def test_r1_engine_rotation_without_replacement():
    """
    Verifica que en los reintentos de búsqueda, los motores (DuckDuckGo, Yahoo, Bing)
    se muestrean SIN reemplazo (rotación/shuffling sin repetir motor en el mismo request).
    """
    async def _run():
        mock_session = MagicMock()
        
        # Probar 30 requests para comprobar muestreo sin reemplazo y aleatoriedad del shuffle
        first_engines = []
        for _ in range(30):
            called_funcs = []
            
            def mock_to_thread(func, q):
                called_funcs.append(func)
                return []
                
            with patch("scraper.google_search.asyncio.to_thread", side_effect=mock_to_thread), \
                 patch("scraper.google_search.asyncio.sleep", return_value=None):
                
                results = await _fetch_search_results(mock_session, "fiestas pueblo 2026")
                assert results == []
                assert len(called_funcs) == DDG_MAX_RETRIES, f"Se esperaban {DDG_MAX_RETRIES} intentos, hubo {len(called_funcs)}"
                
                # Para DDG_MAX_RETRIES == 3, los 3 motores deben ser únicos (muestreo sin reemplazo)
                unique_funcs = set(called_funcs)
                assert len(unique_funcs) == len(called_funcs), (
                    f"Se detectó repetición de motor en los reintentos: {[f.__name__ for f in called_funcs]}"
                )
                first_engines.append(called_funcs[0].__name__)

        # Confirmar que el primer motor varía a lo largo de las peticiones (aleatoriedad en el shuffle por request)
        assert len(set(first_engines)) > 1, "La ordenación de motores no está variando (shuffle no aleatorio)."

    asyncio.run(_run())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


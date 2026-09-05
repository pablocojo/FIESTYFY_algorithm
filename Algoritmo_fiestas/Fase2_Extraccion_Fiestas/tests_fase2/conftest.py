import os
import sys

import pytest

# Hacer importables config, llm_processor y scraper desde la carpeta Fase2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _cache_de_paginas_aislada(tmp_path, monkeypatch):
    """
    Ningún test toca la caché de verdad.

    Añadido el 2026-08-24, en cuanto la caché entró en juego: cuatro tests de
    descarga empezaron a fallar porque la ejecución anterior de la suite había
    dejado sus URLs guardadas, y en la siguiente ya no se bajaba nada. Un test
    que depende de lo que dejó el anterior no prueba nada.
    """
    import cache_paginas

    monkeypatch.setattr(cache_paginas, "CACHE_PAGINAS_DIR", str(tmp_path / "cache_paginas"))
    cache_paginas.reiniciar_estadisticas()


@pytest.fixture(autouse=True)
def _volcado_de_contexto_aislado(tmp_path, monkeypatch):
    """
    Ningún test escribe en `debug_contexto/`, que es donde vive la evidencia.

    Mismo motivo que la caché de páginas, y el daño es peor. Los volcados de esa
    carpeta son lo que lee `evaluar_dorado.py` para decir si un cambio ha
    mejorado las cosas, y los nombres de fichero salen de la localidad y la
    fiesta: un test que use «Aranda de Duero» y «Fiestas Patronales en Honor de
    la Virgen...» escribe EXACTAMENTE encima del volcado de la ejecución real.

    Descubierto el 2026-09-03: el volcado real de esa fiesta —el que documenta
    que entraron 14 de 82 fragmentos del PDF— quedó machacado por un test, y con
    él se movió el recuento de chunks descartados de la línea base. Había
    ficheros así de al menos tres tests anteriores (Torrellano, Retes de Tudela,
    Cordovilla/San Roque), contándose como datos reales.
    """
    from pathlib import Path

    import debug_contexto

    monkeypatch.setattr(debug_contexto, "DIR_DEBUG", Path(tmp_path) / "debug_contexto")


@pytest.fixture(autouse=True)
def _searxng_fuera_de_los_tests():
    """Ningún test sale a la red contra SearXNG.

    Añadido el 2026-09-06, al entrar SearXNG como motor primario. El host
    configurado (172.19.96.1) es alcanzable de verdad desde Windows, así que la
    suite empezó a pegarle al contenedor: `test_el_motor_no_se_toca_si_la_
    consulta_esta_guardada` falló porque SearXNG devolvió resultados suficientes
    y DuckDuckGo —el motor que ese test simula— ya no llegó a consultarse.

    Un test que pasa o falla según si Docker está arrancado no prueba nada. Se
    usa el enfriamiento que ya existe en vez de sustituir la función, para que el
    orquestador lo salte por el mismo camino que en producción. Los tests que sí
    quieren ejercitar SearXNG limpian `_ENGINE_COOLDOWN` en su propio fixture.
    """
    import scraper.google_search as gs

    gs._ENGINE_COOLDOWN["SearXNG"] = float("inf")
    yield
    gs._ENGINE_COOLDOWN.pop("SearXNG", None)

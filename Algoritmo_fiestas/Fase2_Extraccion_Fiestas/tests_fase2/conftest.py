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

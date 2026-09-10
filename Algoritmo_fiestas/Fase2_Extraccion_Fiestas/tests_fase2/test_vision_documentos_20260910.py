"""
Leer un cartel cuando el PDF no suelta texto.

Las dos mitades ya existían y no estaban conectadas
---------------------------------------------------
`extract_text_from_pdf` renderiza las páginas candidatas —filtrando por palabras
clave festivas y respetando `PDF_MAX_PAGES_VLM`— y las devuelve en el segundo
valor. En `_fetch_page_content` se hacía `texto_pdf, _ = ...` y se tiraban.
Enfrente, `vision_analyzer.analizar_imagen_directa()` sabía leerlas y no la
llamaba nadie.

Qué tamaño tiene esto en realidad
---------------------------------
Menor del que estimaba el plan del 2026-09-10. El OCR que ya existe cubre buena
parte del caso: el `PROGRAMA-CULTURAL-VERANO-2026.pdf` de El Barraco es una sola
página sin texto embebido y aun así devuelve 3.485 caracteres, y el programa del
Padre Eterno de Fuentespina da 20.667. De las 6 fichas que señalaban PDF o imagen
sin sacar actos, cuatro eran documentos equivocados —la Feria de Almería en otro
municipio, una nota informativa, un documento de una capilla repetido— y no
fallos de lectura.

Así que esto es una red de seguridad, no el arreglo de un agujero grande: cubre
el PDF que ni siquiera el OCR consigue leer.

Qué fijan estos tests
---------------------
Que sea el ÚLTIMO recurso y que no mienta sobre su procedencia.
"""

import asyncio

import pytest

import scraper.google_search as gs


class _Img:
    """Sustituto de una imagen PIL: al VLM se le pasa tal cual."""


def _vlm(monkeypatch, respuestas):
    llamadas = []

    async def _fake(img):
        llamadas.append(img)
        return respuestas.pop(0) if respuestas else ""

    import llm_processor.vision_analyzer as va
    monkeypatch.setattr(va, "analizar_imagen_directa", _fake)
    return llamadas


# ─────────────────────────────────────────────
# Cuándo se dispara
# ─────────────────────────────────────────────

def test_sin_imagenes_no_se_llama_al_modelo(monkeypatch):
    llamadas = _vlm(monkeypatch, [])
    assert asyncio.run(gs._leer_con_vision([], "https://x.es/p.pdf")) == ""
    assert llamadas == []


def test_lee_las_imagenes_y_devuelve_su_texto(monkeypatch):
    _vlm(monkeypatch, ["19:00 Procesión del Padre Eterno"])
    r = asyncio.run(gs._leer_con_vision([_Img()], "https://x.es/p.pdf"))
    assert "Procesión del Padre Eterno" in r


def test_respeta_el_tope_de_imagenes(monkeypatch):
    """Cada imagen es una llamada al VLM con su timeout de 180 s. Sin tope, una
    galería se come la ejecución."""
    from config import VISION_MAX_IMAGES_DOC

    llamadas = _vlm(monkeypatch, ["a", "b", "c", "d", "e"])
    asyncio.run(gs._leer_con_vision([_Img() for _ in range(5)], "https://x.es/p.pdf"))
    assert len(llamadas) == VISION_MAX_IMAGES_DOC


# ─────────────────────────────────────────────
# La procedencia se declara
# ─────────────────────────────────────────────

def test_el_texto_va_marcado_como_leido_de_imagen(monkeypatch):
    """No es decorativo. Un acto leído de un cartel no tiene la misma
    fiabilidad que uno leído de HTML, y el juez debe poder ser más severo con él.
    Los carteles reales llevan tipografías decorativas sobre fondos con dibujos,
    y un modelo de visión inventa fechas con la misma seguridad con la que
    acierta."""
    _vlm(monkeypatch, ["20:00 Verbena"])
    r = asyncio.run(gs._leer_con_vision([_Img()], "https://x.es/p.pdf"))
    assert gs.MARCA_VISION in r


def test_cada_trozo_lleva_su_marca(monkeypatch):
    """El texto se trocea después en chunks: un encabezado suelto al principio
    se perdería en el primer trozo y el resto viajaría sin procedencia."""
    _vlm(monkeypatch, ["pagina uno", "pagina dos"])
    r = asyncio.run(gs._leer_con_vision([_Img(), _Img()], "https://x.es/p.pdf"))
    assert r.count(gs.MARCA_VISION) == 2


# ─────────────────────────────────────────────
# Nunca romper la descarga
# ─────────────────────────────────────────────

def test_si_el_vlm_falla_se_devuelve_vacio(monkeypatch):
    """Un fallo del modelo no puede tumbar la descarga de una página."""
    async def _explota(img):
        raise RuntimeError("VLM caido")

    import llm_processor.vision_analyzer as va
    monkeypatch.setattr(va, "analizar_imagen_directa", _explota)
    assert asyncio.run(gs._leer_con_vision([_Img()], "https://x.es/p.pdf")) == ""


def test_respuestas_vacias_no_generan_marcas_huerfanas(monkeypatch):
    """Si el VLM no lee nada, no debe quedar una marca de procedencia sola: seria
    decir 'esto viene de una imagen' sin traer nada de ella."""
    _vlm(monkeypatch, ["", "   "])
    assert asyncio.run(gs._leer_con_vision([_Img(), _Img()], "https://x.es/p.pdf")) == ""


def test_con_la_vision_desactivada_no_hace_nada(monkeypatch):
    import config

    monkeypatch.setattr(config, "VISION_ENABLED", False)
    llamadas = _vlm(monkeypatch, ["texto"])
    assert asyncio.run(gs._leer_con_vision([_Img()], "https://x.es/p.pdf")) == ""
    assert llamadas == []


# ─────────────────────────────────────────────
# Es el último recurso, no el primero
# ─────────────────────────────────────────────

def test_solo_se_intenta_cuando_el_pdf_no_dio_texto():
    """El orden importa: OCR y texto embebido son más baratos y más fiables.

    Comprobado sobre el fuente porque `_descargar_una_vez` sale a la red. El
    OCR que ya existe resuelve la mayoría: el cartel de El Barraco, sin texto
    embebido, devuelve 3.485 caracteres por esa vía.
    """
    import inspect

    fuente = inspect.getsource(gs._descargar_una_vez)
    assert "_leer_con_vision(_imgs_vlm, url)" in fuente
    i_guarda = fuente.index('if not (texto_pdf or "").strip():')
    i_vision = fuente.index("_leer_con_vision(")
    assert i_guarda < i_vision, "la visión debe ir DENTRO de la guarda de texto vacío"

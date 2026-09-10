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


# ─────────────────────────────────────────────
# La imagen tiene que llegar al VLM
# ─────────────────────────────────────────────
# Añadidos el 2026-09-10, al descubrir que `_leer_con_vision` no podía ejecutarse
# nunca. Se dispara cuando el texto del PDF está vacío, pero `images_for_vlm`
# solo se llenaba si el OCR YA había leído más de 20 caracteres con palabras
# festivas. Texto vacío implicaba lista vacía: la caída a visión era código
# muerto.
#
# El filtro tenía sentido para su propósito original —recoger páginas que el OCR
# identificó como festivas para que un VLM las relea mejor, porque Tesseract en
# un cartel a tres columnas lee las palabras y las desordena— pero dejaba fuera
# justo el caso que más lo necesita.

def test_una_imagen_que_el_ocr_no_lee_se_devuelve_igual():
    """El caso que motivó el arreglo: un cartel con tipografía decorativa sobre
    fondo con dibujos derrota a Tesseract pero no a un modelo de visión."""
    import io as _io

    from PIL import Image

    from scraper.document_extractor import extract_text_from_image

    plana = Image.new("RGB", (900, 600), (120, 90, 160))
    buf = _io.BytesIO()
    plana.save(buf, "PNG")

    texto, imagenes = extract_text_from_image(buf.getvalue())
    assert texto == ""
    assert len(imagenes) == 1, "sin imagen, el VLM no tiene nada que leer"


def test_una_imagen_demasiado_pequena_sigue_descartandose():
    """El filtro de tamaño es anterior y debe sobrevivir: un icono de 40px no es
    un cartel, y mandarlo al VLM es gastar una llamada de 180 s en un adorno."""
    import io as _io

    from PIL import Image

    from scraper.document_extractor import extract_text_from_image

    icono = Image.new("RGB", (40, 40), "white")
    buf = _io.BytesIO()
    icono.save(buf, "PNG")

    texto, imagenes = extract_text_from_image(buf.getvalue())
    assert (texto, imagenes) == ("", [])


def test_el_pdf_recoge_la_pagina_aunque_el_ocr_falle():
    """Misma corrección en la rama de PDF escaneado.

    Comprobado sobre el fuente: construir un PDF ilegible en un test es frágil y
    lo que importa es que la rama exista, con su tope de páginas como único
    freno —sin texto no hay palabras clave que filtrar—.
    """
    import inspect

    from scraper import document_extractor as de

    fuente = inspect.getsource(de.extract_text_from_pdf)
    i_ok = fuente.index("if page_text_ocr and len(page_text_ocr.strip()) > 20:")
    resto = fuente[fuente.index("else:", i_ok):]
    # El `append` de la rama del fallo, que es el segundo del bloque: el primero
    # es el de la rama en que el OCR sí leyó.
    assert "images_for_vlm.append(page_image)" in resto
    assert "PDF_MAX_PAGES_VLM" in resto
    assert fuente.count("images_for_vlm.append(page_image)") == 2


# ─────────────────────────────────────────────
# El cartel .jpg suelto que encuentra la araña
# ─────────────────────────────────────────────
# El camino de imágenes del spider corre el OCR en un subproceso aislado —el OCR
# segfaultea, por eso vive allí— y las imágenes PIL no cruzan esa frontera. Pero
# el método que lo llama es async y YA TIENE los bytes, así que la llamada al VLM
# se hace ahí y el subproceso no se toca.
#
# Solo llegan imágenes que `is_promising_image` ya dio por probables carteles, así
# que el filtrado por relevancia está hecho antes.

import io as _io

from PIL import Image

import scraper.heuristic_spider as hs


def _png_bytes(color=(120, 90, 160)):
    buf = _io.BytesIO()
    Image.new("RGB", (900, 600), color).save(buf, "PNG")
    return buf.getvalue()


def _spider():
    return hs.AsyncTwoPassSpider.__new__(hs.AsyncTwoPassSpider)


def _vlm_spider(monkeypatch, respuesta="20:00 Verbena con orquesta"):
    llamadas = []

    async def _fake(img):
        llamadas.append(img)
        return respuesta

    import llm_processor.vision_analyzer as va
    monkeypatch.setattr(va, "analizar_imagen_directa", _fake)
    return llamadas


def test_el_cartel_ilegible_se_lee_con_el_vlm_y_va_marcado(monkeypatch):
    llamadas = _vlm_spider(monkeypatch)
    s = _spider()
    r = asyncio.run(s._leer_cartel_con_vlm(_png_bytes(), "https://x.es/cartel.jpg"))
    assert len(llamadas) == 1
    assert hs.MARCA_VISION in r
    assert "Verbena" in r


def test_el_tope_es_por_rastreo_entero(monkeypatch):
    """Una galería de la fiesta del año pasado puede traer cuarenta candidatas."""
    from config import VISION_MAX_IMAGES_SPIDER

    llamadas = _vlm_spider(monkeypatch)
    s = _spider()
    for _ in range(VISION_MAX_IMAGES_SPIDER + 4):
        asyncio.run(s._leer_cartel_con_vlm(_png_bytes(), "https://x.es/c.jpg"))
    assert len(llamadas) == VISION_MAX_IMAGES_SPIDER


def test_unos_bytes_que_no_son_imagen_no_revientan(monkeypatch):
    llamadas = _vlm_spider(monkeypatch)
    s = _spider()
    assert asyncio.run(s._leer_cartel_con_vlm(b"esto no es un png", "https://x.es/c.jpg")) == ""
    assert llamadas == []


def test_si_el_vlm_falla_el_rastreo_sigue(monkeypatch):
    async def _explota(img):
        raise RuntimeError("VLM caido")

    import llm_processor.vision_analyzer as va
    monkeypatch.setattr(va, "analizar_imagen_directa", _explota)
    s = _spider()
    assert asyncio.run(s._leer_cartel_con_vlm(_png_bytes(), "https://x.es/c.jpg")) == ""


def test_una_respuesta_vacia_no_deja_marca_huerfana(monkeypatch):
    _vlm_spider(monkeypatch, respuesta="   ")
    s = _spider()
    assert asyncio.run(s._leer_cartel_con_vlm(_png_bytes(), "https://x.es/c.jpg")) == ""


def test_el_vlm_solo_entra_si_el_ocr_no_saco_nada():
    """El orden importa: el OCR es más barato y no gasta 180 s por imagen."""
    import inspect

    fuente = inspect.getsource(hs.AsyncTwoPassSpider)
    i_ocr = fuente.index("_subprocess_extract_image, img_bytes")
    resto = fuente[i_ocr:i_ocr + 1200]
    assert 'if not (text or "").strip():' in resto
    assert "_leer_cartel_con_vlm(img_bytes, img_url)" in resto


def test_la_marca_es_la_misma_en_los_dos_caminos():
    """PDF e imagen suelta escriben la misma marca. Si no coincidieran, filtrar
    por procedencia dejaría fuera la mitad de los casos."""
    assert hs.MARCA_VISION == gs.MARCA_VISION

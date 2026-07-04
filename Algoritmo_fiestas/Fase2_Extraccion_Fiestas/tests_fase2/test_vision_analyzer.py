"""Tests de la Etapa D (visión) — sin llamadas reales al VLM ni a Tesseract."""

import asyncio

import pytest
from PIL import Image, ImageDraw

from llm_processor import vision_analyzer
from llm_processor.vision_analyzer import (
    texto_indica_fiesta,
    imagen_a_data_uri,
    procesar_cache_contenido,
)


@pytest.fixture(autouse=True)
def _sin_ocr_real(monkeypatch):
    """Los tests no llaman a Tesseract: el rescate por OCR se anula por defecto."""
    async def _nada(ruta):
        return None
    monkeypatch.setattr(vision_analyzer, "_keyword_por_ocr", _nada)


# ──────────────────────────────────────────────
# Prefiltro por caption
# ──────────────────────────────────────────────

def test_prefiltro_con_keywords():
    assert texto_indica_fiesta("¡Ya está aquí el programa de fiestas 2026!") is not None
    assert texto_indica_fiesta("Cartel anunciador de las patronales") is not None
    assert texto_indica_fiesta("Este sábado verbena en la plaza") is not None


def test_prefiltro_multiidioma():
    # Casos reales de las capturas: carteles en euskera
    assert texto_indica_fiesta("Intxaurjaiak 2026 ekainak 27") is not None  # jaiak
    assert texto_indica_fiesta("San Juan bezpera auzoan ospatzen") is not None
    assert texto_indica_fiesta("Festa major de la vila") is not None
    assert texto_indica_fiesta("Gran festa amb correfoc") is not None


def test_prefiltro_sin_keywords():
    assert texto_indica_fiesta("Corte de agua el martes en la calle Mayor") is None
    assert texto_indica_fiesta("") is None
    assert texto_indica_fiesta(None) is None


# ──────────────────────────────────────────────
# Codificación de imágenes
# ──────────────────────────────────────────────

def _crear_imagen(tmp_path, nombre, ancho, alto):
    """Imagen con patrón único por nombre (los hashes no deben colisionar)."""
    ruta = str(tmp_path / nombre)
    img = Image.new("RGB", (ancho, alto), (220, 220, 220))
    d = ImageDraw.Draw(img)
    despl = (sum(ord(c) for c in nombre) * 37) % max(1, ancho - 120)
    d.rectangle([despl, 40, despl + 100, alto - 40], fill=(30, 30, 30))
    img.save(ruta)
    return ruta


def test_data_uri_valido(tmp_path):
    ruta = _crear_imagen(tmp_path, "cartel.png", 800, 1000)
    uri = imagen_a_data_uri(ruta)
    assert uri and uri.startswith("data:image/jpeg;base64,")


def test_imagen_pequena_rechazada(tmp_path):
    ruta = _crear_imagen(tmp_path, "icono.png", 100, 100)
    assert imagen_a_data_uri(ruta) is None


def test_imagen_grande_se_redimensiona(tmp_path):
    ruta = _crear_imagen(tmp_path, "grande.png", 4000, 3000)
    uri = imagen_a_data_uri(ruta, max_dim=1280)
    assert uri and len(uri) < 1_000_000


# ──────────────────────────────────────────────
# Procesado de la caché con VLM falso
# ──────────────────────────────────────────────

async def _vlm_falso(ruta):
    if "programa" in ruta:
        return {"es_programa_fiestas": True, "texto_extraido": "FIESTAS 2026\n23:00 Verbena"}
    return {"es_programa_fiestas": False, "texto_extraido": ""}


def _cache_con_posts(tmp_path):
    captura_prog = _crear_imagen(tmp_path, "programa_01.png", 800, 1000)
    captura_foto = _crear_imagen(tmp_path, "paisaje_01.png", 800, 1000)
    captura_sin_kw = _crear_imagen(tmp_path, "obra_01.png", 800, 1000)
    return {
        "l1": {"facebook": {"leido_en": "2026-07-04", "posts": [
            {"texto": "Ya tenemos el programa de fiestas", "captura": captura_prog},
            {"texto": "Cartel de la verbena de agosto", "captura": captura_foto},
            {"texto": "Obras en la calle Mayor", "captura": captura_sin_kw},
            {"texto": "Programa del año pasado", "captura": str(tmp_path / "no_existe.png")},
        ]}},
    }


def test_procesar_cache(tmp_path):
    data = _cache_con_posts(tmp_path)
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))

    posts = data["l1"]["facebook"]["posts"]
    assert posts[0]["es_programa"] is True
    assert "Verbena" in posts[0]["texto_programa"]
    assert posts[1]["es_programa"] is False
    assert "texto_programa" not in posts[1]
    assert posts[2]["es_programa"] is False       # sin keyword → ni VLM
    assert posts[2]["vision_procesada"] is True
    assert "vision_procesada" not in posts[3]     # captura inexistente → intacto

    assert resumen["procesadas"] == 2
    assert resumen["programas"] == 1
    assert resumen["sin_keywords"] == 1


def test_procesar_no_repite_procesadas(tmp_path):
    data = _cache_con_posts(tmp_path)
    asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))
    resumen2 = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))
    assert resumen2["procesadas"] == 0
    assert resumen2["sin_keywords"] == 0


def test_procesar_respeta_max(tmp_path):
    data = _cache_con_posts(tmp_path)
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso, max_imagenes=1))
    assert resumen["procesadas"] == 1


def test_error_vlm_se_reintenta(tmp_path):
    async def _vlm_roto(ruta):
        return None

    data = _cache_con_posts(tmp_path)
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_roto))
    assert resumen["errores"] == 2
    assert "vision_procesada" not in data["l1"]["facebook"]["posts"][0]


# ──────────────────────────────────────────────
# M3 — Rescate por OCR (cartel sin caption)
# ──────────────────────────────────────────────

def test_ocr_rescata_cartel_sin_caption(tmp_path, monkeypatch):
    async def _ocr_detecta_jaiak(ruta):
        return "jaiak"
    monkeypatch.setattr(vision_analyzer, "_keyword_por_ocr", _ocr_detecta_jaiak)

    captura = _crear_imagen(tmp_path, "programa_eus.png", 800, 1000)
    data = {"l1": {"instagram": {"posts": [
        {"texto": "argazkiak", "captura": captura},  # caption sin keyword castellana
    ]}}}
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))
    post = data["l1"]["instagram"]["posts"][0]
    assert post["es_programa"] is True
    assert resumen["ocr_rescatadas"] == 1
    assert resumen["sin_keywords"] == 0


# ──────────────────────────────────────────────
# M4 — Dedupe de capturas
# ──────────────────────────────────────────────

def test_dedupe_misma_ruta_de_captura(tmp_path):
    # Los posts del timeline comparten la captura del viewport
    captura = _crear_imagen(tmp_path, "programa_viewport.png", 800, 1000)
    data = {"l1": {"facebook": {"posts": [
        {"texto": "programa de fiestas", "captura": captura},
        {"texto": "más info del programa", "captura": captura},
    ]}}}
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))
    assert resumen["procesadas"] == 1
    assert resumen["duplicadas"] == 1
    assert data["l1"]["facebook"]["posts"][1]["duplicada"] is True


def test_dedupe_mismo_hash_entre_redes(tmp_path):
    # La misma imagen aparece en el feed y en la sección Fotos (rutas distintas)
    c1 = _crear_imagen(tmp_path, "programa_a.png", 800, 1000)
    c2 = str(tmp_path / "programa_b.png")
    Image.open(c1).save(c2)  # copia exacta → mismo hash
    data = {"l1": {
        "facebook": {"posts": [{"texto": "programa de fiestas", "captura": c1}]},
        "instagram": {"posts": [{"texto": "programa de fiestas", "captura": c2}]},
    }}
    resumen = asyncio.run(procesar_cache_contenido(data, analizador=_vlm_falso))
    assert resumen["procesadas"] == 1
    assert resumen["duplicadas"] == 1

"""
Script de verificación aislado para el Requisito R4 (Filtrado por Fecha en RRSS).

Verifica:
1. La preservación de `fecha_publicacion` en los diccionarios de posts (incluyendo posts con OCR/VLM de imagen).
2. El filtrado correcto por ventana de fecha aceptable para el año objetivo 2026 (2025-11-01 a 2027-01-31).
"""

import sys
import os

# Asegurar import de los módulos de Fase2_Extraccion_Fiestas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import social_content
from scraper.social_content import es_fecha_en_ventana, cargar_documentos_rrss


def test_es_fecha_en_ventana():
    print("Testing es_fecha_en_ventana logic...")

    # Año objetivo: 2026 (Ventana: 2025-11-01 a 2027-01-31)
    # Dentro de ventana
    assert es_fecha_en_ventana("2026-08-15", anno=2026) is True
    assert es_fecha_en_ventana("2025-11-01", anno=2026) is True
    assert es_fecha_en_ventana("2025-12-31", anno=2026) is True
    assert es_fecha_en_ventana("2027-01-31", anno=2026) is True
    assert es_fecha_en_ventana("2026-05-10T14:30:00Z", anno=2026) is True

    # Fuera de ventana
    assert es_fecha_en_ventana("2024-08-15", anno=2026) is False
    assert es_fecha_en_ventana("2025-10-31", anno=2026) is False
    assert es_fecha_en_ventana("2027-02-01", anno=2026) is False
    assert es_fecha_en_ventana("2023-12-01", anno=2026) is False

    # Casos sin fecha o fecha no parseable
    assert es_fecha_en_ventana(None, anno=2026) is True
    assert es_fecha_en_ventana("", anno=2026) is True
    assert es_fecha_en_ventana("fecha_invalida", anno=2026) is True

    print(" -> es_fecha_en_ventana logic tests PASSED.")


def test_preservacion_fecha_publicacion_y_filtrado(monkeypatch=None):
    print("Testing fecha_publicacion preservation & window filtering in social_content...")

    localidad = {"id": "loc-test-1", "nombre": "Pueblo Test"}
    municipio = {"id": "mun-test-1", "nombre": "Municipio Test"}

    datos_cache = {
        "loc-test-1": {
            "instagram": [
                {
                    "texto": "Anuncio anticipado de fiestas 2026",
                    "fecha": "2025-11-15",
                    "es_programa": False,
                },
                {
                    "texto": "Gran Verbena de San Roque 2026",
                    "fecha_publicacion": "2026-08-14",
                    "es_programa": False,
                },
                {
                    "texto": "Publicación antigua de fiestas 2024",
                    "fecha": "2024-08-10",
                    "fecha_publicacion": "2024-08-10",
                    "es_programa": False,
                },
                {
                    "texto": "Cartel de fiestas de Reyes 2027",
                    "fecha": "2027-01-10",
                    "es_programa": True,
                    "texto_programa": "05 de Enero: Cabalgata de Reyes",
                },
                {
                    "texto": "Post fuera de ventana 2027 tardio",
                    "fecha_publicacion": "2027-03-15",
                    "es_programa": False,
                },
            ]
        }
    }

    # Inyectar la caché de prueba directamente en social_content._cache
    social_content._cache = datos_cache

    docs = cargar_documentos_rrss(localidad, municipio, anno=2026)
    assert len(docs) == 1, f"Se esperaba 1 documento RRSS, pero se obtuvieron {len(docs)}"

    doc = docs[0]
    texto_doc = doc["texto"]

    # Verificar que los posts dentro de ventana están presentes
    assert "Anuncio anticipado de fiestas 2026" in texto_doc
    assert "Gran Verbena de San Roque 2026" in texto_doc
    assert "Cabalgata de Reyes" in texto_doc

    # Verificar que los posts fuera de ventana fueron filtrados
    assert "Publicación antigua de fiestas 2024" not in texto_doc
    assert "Post fuera de ventana 2027 tardio" not in texto_doc

    # Verificar que fecha_publicacion se preservó en la estructura del post en caché
    posts_cache = datos_cache["loc-test-1"]["instagram"]
    for p in posts_cache:
        fecha_orig = p.get("fecha_publicacion") or p.get("fecha")
        if fecha_orig:
            assert "fecha_publicacion" in p, f"fecha_publicacion no preservada en post: {p}"
            assert p["fecha_publicacion"] == fecha_orig

    print(" -> fecha_publicacion preservation & window filtering tests PASSED.")


def test_post_con_ocr_e_imagen():
    print("Testing image OCR post handling with fecha_publicacion...")

    localidad = {"id": "loc-ocr-1", "nombre": "Pedanía OCR"}
    municipio = {"id": "mun-ocr-1", "nombre": "Municipio OCR"}

    datos_cache = {
        "loc-ocr-1": {
            "facebook": [
                {
                    "texto": "Programa oficial de fiestas",
                    "fecha": "2026-07-20",
                    "captura": "rrss_capturas/loc-ocr-1/facebook_01.png",
                    "es_programa": True,
                    "texto_programa": "Dia 15 de Agosto: Diana floreada y misa mayor",
                }
            ]
        }
    }

    social_content._cache = datos_cache
    docs = cargar_documentos_rrss(localidad, municipio, anno=2026)

    assert len(docs) == 1
    assert "PROGRAMA EXTRAÍDO DE IMAGEN" in docs[0]["texto"]
    assert "Diana floreada" in docs[0]["texto"]
    assert "[POST 2026-07-20]" in docs[0]["texto"]

    post_dict = datos_cache["loc-ocr-1"]["facebook"][0]
    assert post_dict.get("fecha_publicacion") == "2026-07-20"

    print(" -> Image OCR post test PASSED.")


def run_all_tests():
    print("=== RUNNING R4 SOCIAL MEDIA DATE FILTERING VERIFICATION ===")
    test_es_fecha_en_ventana()
    test_preservacion_fecha_publicacion_y_filtrado()
    test_post_con_ocr_e_imagen()
    print("=== ALL R4 VERIFICATION TESTS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    run_all_tests()

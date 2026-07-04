"""
CLI de la Etapa D: interpreta con el VLM local las capturas de RRSS pendientes.

A diferencia del runner de apps, este proceso NO necesita PC dedicado: solo lee
imágenes de `rrss_capturas/` y actualiza `rrss_contenido_cache.json`. Se puede
lanzar después de cada sesión del runner (o programado).

Requiere LM Studio con el modelo de visión cargado (config: VISION_MODEL).

Uso:
    py procesar_capturas.py [--max N]
"""

import argparse
import asyncio
import json
import logging
import os
import sys

from config import SOCIAL_CONTENT_CACHE_FILE
from llm_processor.vision_analyzer import procesar_cache_contenido

RUTA_FASE2 = os.path.dirname(os.path.abspath(__file__))
RUTA_CACHE = os.path.join(RUTA_FASE2, SOCIAL_CONTENT_CACHE_FILE)


def configurar_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)-16s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _guardar_atomico(path: str, data: dict):
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


async def async_main(max_imagenes: int | None):
    if not os.path.exists(RUTA_CACHE):
        print(f"No existe {RUTA_CACHE}: ejecuta antes el runner de apps (social_apps_runner.py).")
        sys.exit(1)

    with open(RUTA_CACHE, "r", encoding="utf-8") as f:
        data = json.load(f)

    resumen = await procesar_cache_contenido(data, max_imagenes=max_imagenes)

    _guardar_atomico(RUTA_CACHE, data)

    print("\nResumen del post-proceso VLM:")
    print(f"  Capturas analizadas por el VLM: {resumen['procesadas']}")
    print(f"  Programas de fiestas detectados: {resumen['programas']}")
    print(f"  Rescatadas por OCR (cartel sin caption): {resumen['ocr_rescatadas']}")
    print(f"  Duplicadas (misma imagen ya analizada): {resumen['duplicadas']}")
    print(f"  Descartadas por prefiltro (sin keywords festivas): {resumen['sin_keywords']}")
    print(f"  Errores (se reintentarán): {resumen['errores']}")
    if resumen.get("deshabilitado"):
        print("  (VISION_ENABLED = False: no se hizo nada)")


def main():
    parser = argparse.ArgumentParser(description="Post-proceso VLM de capturas de RRSS")
    parser.add_argument("--max", type=int, default=None, help="Máximo de imágenes a analizar en esta ejecución")
    args = parser.parse_args()

    configurar_logging()
    asyncio.run(async_main(args.max))


if __name__ == "__main__":
    main()

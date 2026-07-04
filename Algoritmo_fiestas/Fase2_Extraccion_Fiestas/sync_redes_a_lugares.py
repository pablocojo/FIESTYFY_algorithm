"""
Volcado de perfiles RRSS de la caché al campo `redes_sociales` de lugares_espana.json.

IMPORTANTE: lugares_espana.json AÚN NO ES DEFINITIVO (la Fase 1 sigue añadiendo
lugares). Por eso:
- La caché (`redes_sociales_cache.json`) es la FUENTE DE VERDAD.
- Este script es idempotente y re-ejecutable: se puede lanzar cada vez que la
  Fase 1 regenere o amplíe el JSON de lugares.
- Los lugar_id de la caché que todavía no existan en el JSON se conservan en la
  caché y se informan (se volcarán en una ejecución futura).
- Solo se escribe el campo `redes_sociales`; el resto del lugar no se toca.
- Siempre se deja un backup con timestamp antes de escribir.

Uso:
    py sync_redes_a_lugares.py [--lugares RUTA] [--cache RUTA] [--dry-run]
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

RUTA_FASE2 = os.path.dirname(os.path.abspath(__file__))
CACHE_DEFECTO = os.path.join(RUTA_FASE2, "redes_sociales_cache.json")
LUGARES_DEFECTO = os.path.normpath(
    os.path.join(RUTA_FASE2, "..", "Fase1_recogida_datos_wiki", "lugares_espana.json")
)


def sincronizar(cache_path: str, lugares_path: str, dry_run: bool = False) -> dict:
    """
    Vuelca las entradas de la caché al JSON de lugares.
    Devuelve un resumen: {actualizados, sin_cambio, sin_lugar, total_cache, backup}.
    """
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    with open(lugares_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Soportar tanto el formato wrapper {"version": N, "lugares": [...]} como array directo
    es_wrapper = isinstance(data, dict) and "lugares" in data
    lugares = data["lugares"] if es_wrapper else data

    indice = {l["id"]: l for l in lugares if isinstance(l, dict) and "id" in l}

    actualizados = 0
    sin_cambio = 0
    sin_lugar = []

    for lugar_id, entrada in cache.items():
        if not isinstance(entrada, dict):
            continue
        lugar = indice.get(lugar_id)
        if lugar is None:
            # Esperado mientras la Fase 1 no esté completa: se conserva en caché
            sin_lugar.append(lugar_id)
            continue
        if lugar.get("redes_sociales") == entrada:
            sin_cambio += 1
            continue
        lugar["redes_sociales"] = entrada
        actualizados += 1

    backup = None
    if actualizados and not dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{lugares_path}.bak-{timestamp}"
        shutil.copy2(lugares_path, backup)

        temp = f"{lugares_path}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(temp, lugares_path)

    return {
        "total_cache": len(cache),
        "actualizados": actualizados,
        "sin_cambio": sin_cambio,
        "sin_lugar": sin_lugar,
        "backup": backup,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="Volcar perfiles RRSS a lugares_espana.json")
    parser.add_argument("--lugares", default=LUGARES_DEFECTO, help="Ruta del JSON de lugares (Fase 1)")
    parser.add_argument("--cache", default=CACHE_DEFECTO, help="Ruta de la caché de perfiles")
    parser.add_argument("--dry-run", action="store_true", help="No escribe: solo muestra qué haría")
    args = parser.parse_args()

    if not os.path.exists(args.cache):
        print(f"No existe la caché de perfiles: {args.cache}")
        print("Ejecuta primero la Fase 2 para que el spider descubra perfiles.")
        sys.exit(1)
    if not os.path.exists(args.lugares):
        print(f"No existe el JSON de lugares: {args.lugares}")
        sys.exit(1)

    resumen = sincronizar(args.cache, args.lugares, args.dry_run)

    modo = "[DRY-RUN] " if resumen["dry_run"] else ""
    print(f"{modo}Entradas en caché:        {resumen['total_cache']}")
    print(f"{modo}Lugares actualizados:     {resumen['actualizados']}")
    print(f"{modo}Ya estaban al día:        {resumen['sin_cambio']}")
    print(f"{modo}Aún no en lugares (OK, la Fase 1 no está completa): {len(resumen['sin_lugar'])}")
    if resumen["sin_lugar"]:
        print(f"  ids pendientes: {', '.join(resumen['sin_lugar'][:10])}"
              + (" ..." if len(resumen["sin_lugar"]) > 10 else ""))
    if resumen["backup"]:
        print(f"Backup creado: {resumen['backup']}")


if __name__ == "__main__":
    main()

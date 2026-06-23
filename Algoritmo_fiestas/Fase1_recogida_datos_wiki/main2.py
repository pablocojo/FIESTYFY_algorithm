# main2.py
"""
Fase 2: enriquecimiento de municipios con subdivisiones.

Lee municipios.json, analiza distritos, barrios y pedanias segun el tipo de
municipio, y guarda lugares_espana.json con municipios y subdivisiones.
"""

import json
import os
import time

from config import (
    MUNICIPIOS_JSON,
    OUTPUT_JSON,
    ERROR_LOG_FILE,
    DELAY_BETWEEN_REQUESTS,
)
from extractors import inferir_comunidad_por_provincia
from logger import dump_error_log, log_error
from parte2_distritos_pedanias import procesar_estructura_ciudad
from place_types import valida_dataset
from scraper import fetch_url


def cargar_json_lugares(path: str) -> list[dict]:
    """
    Carga la lista de lugares desde un JSON con estructura version/lugares.
    """
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log_error(f"No se pudo cargar {path}: {e}")
        return []

    lugares = data.get("lugares", [])
    return lugares if isinstance(lugares, list) else []


def deduplicar_lugares(lugares: list[dict]) -> list[dict]:
    """
    Mantiene el primer lugar por id y evita duplicados al reanudar.
    """
    resultado = []
    ids_vistos = set()

    for lugar in lugares:
        lugar_id = lugar.get("id")
        if not lugar_id or lugar_id in ids_vistos:
            continue
        ids_vistos.add(lugar_id)
        resultado.append(lugar)

    return resultado


def guardar_lugares(resultados: list[dict]) -> dict:
    """
    Guarda lugares_espana.json con municipios y subdivisiones.
    """
    lugares = deduplicar_lugares(resultados)
    for lugar in lugares:
        if not lugar.get("comunidad"):
            lugar["comunidad"] = inferir_comunidad_por_provincia(lugar.get("provincia")) or ""
        lugar.setdefault("sitio_web", "")
        lugar.setdefault("wikipedia_url", "")

    output_data = {
        "version": 2,
        "lugares": lugares,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    return output_data


def main():
    """
    Procesa las subdivisiones de los municipios ya generados por main.py.
    """
    print("\n" + "=" * 70)
    print(" FASE 2: SUBDIVISIONES DE MUNICIPIOS")
    print("=" * 70 + "\n")

    municipios = cargar_json_lugares(MUNICIPIOS_JSON)
    total_municipios = len(municipios)

    if not municipios:
        print(f"ERROR: No se encontraron municipios en {MUNICIPIOS_JSON}.")
        print("Ejecuta primero: python main.py")
        return

    resume_input = input("Desde que municipio (indice) quieres reanudar? (ENTER para 1): ").strip()
    start_idx = int(resume_input) if resume_input.isdigit() and int(resume_input) > 0 else 1

    if start_idx > total_municipios:
        print(f"ERROR: El indice {start_idx} excede el total de municipios ({total_municipios}).")
        return

    resultados = cargar_json_lugares(OUTPUT_JSON) if start_idx > 1 else []
    if resultados:
        print(f"{len(resultados)} lugares cargados desde {OUTPUT_JSON}.")

    print(f"OK: {total_municipios} municipios cargados desde {MUNICIPIOS_JSON}.")
    print(f"Comenzando en indice {start_idx}.\n")

    try:
        for idx, municipio in enumerate(municipios[start_idx - 1 :], start=start_idx):
            nombre = municipio.get("nombre", "?")
            print(f"[{idx}/{total_municipios}] Analizando subdivisiones: {nombre}")

            lugares_resultado = [municipio]
            wikipedia_url = str(municipio.get("wikipedia_url") or "").strip()
            html = fetch_url(wikipedia_url) if wikipedia_url else None

            if not html:
                log_error("No se pudo descargar HTML para fase 2", context={"lugar": nombre, "url": wikipedia_url})
                print("   - Sin HTML; se conserva solo el municipio.")
            elif municipio.get("tipo") in ("pueblo", "ciudad_pequena", "ciudad_grande", "municipio_compuesto"):
                lugares_resultado.extend(procesar_estructura_ciudad(html, municipio))

            resultados.extend(lugares_resultado)
            output_data = guardar_lugares(resultados)

            print(f"OK Finalizado: {nombre} ({len(lugares_resultado)} lugar(es))")
            print(f"Progreso guardado en {OUTPUT_JSON} ({len(output_data['lugares'])} lugares)\n")

            time.sleep(DELAY_BETWEEN_REQUESTS)
    except KeyboardInterrupt:
        output_data = guardar_lugares(resultados)
        dump_error_log(ERROR_LOG_FILE)
        print("\n\nProceso interrumpido por el usuario.")
        print(f"Progreso guardado en {OUTPUT_JSON} ({len(output_data['lugares'])} lugares).")
        print(f"Log guardado en {ERROR_LOG_FILE}")
        return

    print("\n" + "=" * 70)
    print("Guardando JSON final...")

    output_data = guardar_lugares(resultados)

    print(f"Datos guardados en {OUTPUT_JSON}")
    print(f"Total de lugares: {len(output_data['lugares'])}")

    print("\nValidando estructura JSON...")
    es_valido, errores = valida_dataset(output_data)

    if es_valido:
        print("lugares_espana.json valido y bien estructurado")
    else:
        print(f"Errores encontrados ({len(errores)}):")
        for err in errores[:10]:
            print(f"   - {err}")
        if len(errores) > 10:
            print(f"   ... y {len(errores) - 10} mas")

    print("\nVolcando log de errores...")
    dump_error_log(ERROR_LOG_FILE)
    print(f"Log guardado en {ERROR_LOG_FILE}")

    print("\n" + "=" * 70)
    print(" FASE 2 FINALIZADA")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProceso interrumpido antes de poder guardar el progreso.")
    except Exception as e:
        print(f"\n\nError no esperado: {e}")
        log_error(f"Error no esperado en main2: {e}")
        dump_error_log(ERROR_LOG_FILE)

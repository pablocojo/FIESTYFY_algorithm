# main.py
"""
Fase 1: recopilacion de municipios espanoles desde Wikipedia.

Este programa solo construye los lugares raiz (municipios) y guarda
municipios.json. No analiza distritos, barrios ni pedanias.
"""

import json
import os
import shutil
import time

from config import (
    MUNICIPIOS_JSON,
    ERROR_LOG_FILE,
    DELAY_BETWEEN_REQUESTS,
)
from extractors import inferir_comunidad_por_provincia
from logger import dump_error_log, log_error, safe_print
from parte1_municipios import obtener_lugares_base, procesar_municipio_base
from place_types import valida_dataset


MIN_ITEMS_RESTORE = 10
RESPALDO_FUENTE = "munis_hasta1800_20_junio.json"


def cargar_municipios_previos() -> list[dict]:
    """
    Carga municipios ya guardados para poder reanudar la fase 1.
    """
    if not os.path.exists(MUNICIPIOS_JSON):
        return []

    try:
        with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log_error(f"No se pudo cargar {MUNICIPIOS_JSON}: {e}")
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


def guardar_municipios(resultados: list[dict]) -> dict:
    """
    Guarda municipios.json con los lugares raiz ya procesados.
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

    with open(MUNICIPIOS_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    return output_data


def restaurar_si_hace_falta() -> None:
    """
    Restaura un respaldo si municipios.json no existe o parece vacio/corrupto.
    """
    intentar_restaurar = False
    if not os.path.exists(MUNICIPIOS_JSON):
        intentar_restaurar = True
    else:
        try:
            with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
                data_test = json.load(f)
            if len(data_test.get("lugares", [])) < MIN_ITEMS_RESTORE:
                intentar_restaurar = True
        except Exception:
            intentar_restaurar = True

    if not intentar_restaurar:
        return

    if not os.path.exists(RESPALDO_FUENTE):
        return

    safe_print(f"Restaurando progreso desde {RESPALDO_FUENTE} a {MUNICIPIOS_JSON}...")
    shutil.copyfile(RESPALDO_FUENTE, MUNICIPIOS_JSON)
    safe_print("Restauracion completada.\n")


def imprimir_validacion(output_data: dict) -> None:
    """
    Valida y muestra un resumen final del JSON.
    """
    safe_print("\nValidando estructura JSON...")
    es_valido, errores = valida_dataset(output_data)

    if es_valido:
        safe_print("municipios.json valido y bien estructurado")
        return

    safe_print(f"Errores encontrados ({len(errores)}):")
    for err in errores[:10]:
        safe_print(f"   - {err}")
    if len(errores) > 10:
        safe_print(f"   ... y {len(errores) - 10} mas")


def main():
    """
    Descarga y procesa municipios raiz uno a uno usando el LLM local configurado.
    """
    safe_print("\n" + "=" * 70)
    safe_print(" FASE 1: RECOPILACION SECUENCIAL DE MUNICIPIOS")
    safe_print("=" * 70 + "\n")

    restaurar_si_hace_falta()

    lugares_base = obtener_lugares_base()
    total_lugares = len(lugares_base)

    if not lugares_base:
        safe_print("ERROR: No se encontraron municipios. Abortando.")
        return

    municipios_previos = cargar_municipios_previos()
    sugerencia_idx = len(municipios_previos) + 1 if municipios_previos else 1

    resume_input = input(
        f"Desde que municipio (indice) quieres reanudar? (Recomendado: {sugerencia_idx}): "
    ).strip()
    start_idx = int(resume_input) if resume_input.isdigit() and int(resume_input) > 0 else sugerencia_idx

    if start_idx > total_lugares:
        safe_print(f"ERROR: El indice {start_idx} excede el total de lugares ({total_lugares}).")
        return

    resultados = cargar_municipios_previos() if start_idx > 1 else []
    if resultados:
        safe_print(f"{len(resultados)} municipios cargados desde {MUNICIPIOS_JSON}.")

    safe_print(f"OK: {total_lugares} municipios encontrados. Comenzando en indice {start_idx}.")
    safe_print("Modo secuencial: se procesa y guarda un municipio antes de pasar al siguiente.\n")

    try:
        for idx, lugar_base in enumerate(lugares_base[start_idx - 1 :], start=start_idx):
            nombre = lugar_base.get("nombre", "?")
            safe_print(f"[{idx}/{total_lugares}] Procesando municipio: {nombre}")

            try:
                lugar, _html = procesar_municipio_base(lugar_base)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                safe_print(f"[{idx}/{total_lugares}] [ERROR] Procesando {nombre}: {e}")
                log_error(f"Error procesando {nombre}: {e}")
                continue

            if not lugar:
                safe_print(f"[{idx}/{total_lugares}] [ERROR] {nombre} saltado")
                continue

            resultados.append(lugar)
            output_data = guardar_municipios(resultados)
            safe_print(
                f"[{idx}/{total_lugares}] [OK] Guardado: {nombre} "
                f"({len(output_data['lugares'])} municipios en {MUNICIPIOS_JSON})\n"
            )

            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        output_data = guardar_municipios(resultados)
        dump_error_log(ERROR_LOG_FILE)
        safe_print("\n\nProceso interrumpido por el usuario.")
        safe_print(f"Progreso guardado en {MUNICIPIOS_JSON} ({len(output_data['lugares'])} municipios).")
        safe_print(f"Log guardado en {ERROR_LOG_FILE}")
        return

    safe_print("\n" + "=" * 70)
    safe_print("Guardando municipios finales...")

    output_data = guardar_municipios(resultados)

    safe_print(f"Datos guardados en {MUNICIPIOS_JSON}")
    safe_print(f"Total de municipios: {len(output_data['lugares'])}")

    imprimir_validacion(output_data)

    safe_print("\nVolcando log de errores...")
    dump_error_log(ERROR_LOG_FILE)
    safe_print(f"Log guardado en {ERROR_LOG_FILE}")

    safe_print("\n" + "=" * 70)
    safe_print(" FASE 1 FINALIZADA")
    safe_print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        safe_print("\n\nProceso interrumpido antes de poder guardar el progreso.")
    except Exception as e:
        safe_print(f"\n\nError no esperado: {e}")
        log_error(f"Error no esperado en main: {e}")
        dump_error_log(ERROR_LOG_FILE)

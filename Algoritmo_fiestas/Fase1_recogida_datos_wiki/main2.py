# main2.py
"""
Fase 2: enriquecimiento de municipios con subdivisiones.

Lee municipios.json, analiza distritos, barrios y pedanias segun el tipo de
municipio, y guarda lugares_espana.json con municipios y subdivisiones.
"""

import json
import os
import time
import urllib.parse
import threading

from config import (
    MUNICIPIOS_JSON,
    OUTPUT_JSON,
    ERROR_LOG_FILE,
    DELAY_BETWEEN_REQUESTS,
)
import config
config.LLM_MODEL_NAME = "llama-3.2-3b-instruct"
from extractors import inferir_comunidad_por_provincia
from logger import dump_error_log, log_error
from parte2_distritos_pedanias import procesar_estructura_ciudad
from place_types import valida_dataset
from scraper import fetch_url
from datos_ine import cargar_datos_ine


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

    resultados = cargar_json_lugares(OUTPUT_JSON)
    procesados = sum(1 for lugar in resultados if not lugar.get("padre_id"))
    sugerencia_idx = procesados + 1 if procesados else 1

    resume_input = input(f"Desde que municipio (indice) quieres reanudar? (Recomendado: {sugerencia_idx}): ").strip()
    start_idx = int(resume_input) if resume_input.isdigit() and int(resume_input) > 0 else sugerencia_idx

    if start_idx > total_municipios:
        print(f"ERROR: El indice {start_idx} excede el total de municipios ({total_municipios}).")
        return

    if start_idx == 1:
        resultados = []
        
    if resultados:
        print(f"{len(resultados)} lugares cargados desde {OUTPUT_JSON}.")

    print(f"OK: {total_municipios} municipios cargados desde {MUNICIPIOS_JSON}.")
    print(f"Comenzando en indice {start_idx}.\n")

    reclasificaciones = []
    if os.path.exists("informe_reclasificaciones.json") and start_idx > 1:
        try:
            with open("informe_reclasificaciones.json", "r", encoding="utf-8") as f:
                reclasificaciones = json.load(f)
        except Exception:
            pass
    datos_ine = cargar_datos_ine()
    import parte2_distritos_pedanias.distritos_pedanias as dp_module
    dp_module.DATOS_INE_GLOBAL = datos_ine

    try:
        for idx, municipio in enumerate(municipios[start_idx - 1 :], start=start_idx):
            nombre = municipio.get("nombre", "?")
            poblacion = municipio.get("poblacion", 0)
            
            print(f"[{idx}/{total_municipios}] Analizando subdivisiones: {nombre}")

            # Lógica para saltar municipios grandes y guardarlos para más tarde
            if (poblacion > 102986 and nombre != "Roquetas de Mar") or nombre == "Cáceres":
                if nombre == "Cáceres":
                    print(f"   -> [SKIPPED] {nombre} tiene VIP PASS. Se guarda para análisis posterior.")
                else:
                    print(f"   -> [SKIPPED] {nombre} tiene {poblacion} habitantes (>102.986). Se guarda para análisis posterior.")
                archivo_pendientes = "municipios_grandes_pendientes.json"
                try:
                    with open(archivo_pendientes, "r", encoding="utf-8") as f:
                        pendientes = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    pendientes = []
                
                if not any(m.get("id") == municipio.get("id") for m in pendientes):
                    pendientes.append(municipio)
                    with open(archivo_pendientes, "w", encoding="utf-8") as f:
                        json.dump(pendientes, f, indent=2, ensure_ascii=False)
                        
                    # Enviar mensaje de WhatsApp en segundo plano
                    def mandar_ws(n, p):
                        try:
                            import pyautogui
                            telefono = "+34682312869"
                            mensaje = f"Se ha saltado y guardado un municipio gigante: {n} ({p} habitantes)"
                            mensaje_codificado = urllib.parse.quote(mensaje)
                            url_whatsapp = f"whatsapp://send?phone={telefono}&text={mensaje_codificado}"
                            os.system(f'start "" "{url_whatsapp}"')
                            time.sleep(6) # Esperar a que WhatsApp se abra
                            pyautogui.press('enter')
                        except Exception:
                            pass
                            
                    threading.Thread(target=mandar_ws, args=(nombre, poblacion), daemon=True).start()
                    print(f"   -> (Lanzado envío de WhatsApp en segundo plano para {nombre})")
                
                # Se añade el municipio base sin analizar subdivisiones
                resultados.append(municipio)
                output_data = guardar_lugares(resultados)
                time.sleep(DELAY_BETWEEN_REQUESTS)
                continue

            lugares_resultado = [municipio]
            wikipedia_url = str(municipio.get("wikipedia_url") or "").strip()
            html = fetch_url(wikipedia_url) if wikipedia_url else None

            if not html:
                log_error("No se pudo descargar HTML para fase 2", context={"lugar": nombre, "url": wikipedia_url})
                print("   - Sin HTML; se conserva solo el municipio.")
            elif municipio.get("tipo") in ("pueblo", "ciudad_pequena", "ciudad_grande", "municipio_compuesto"):
                tipo_antes = municipio.get("tipo")
                lugares_resultado.extend(procesar_estructura_ciudad(html, municipio))
                if tipo_antes != municipio.get("tipo"):
                    reclasificaciones.append({
                        "id": municipio.get("id"),
                        "nombre": municipio.get("nombre"),
                        "provincia": municipio.get("provincia"),
                        "tipo_anterior": tipo_antes,
                        "nuevo_tipo": municipio.get("tipo")
                    })

            resultados.extend(lugares_resultado)
            output_data = guardar_lugares(resultados)

            if reclasificaciones:
                with open("informe_reclasificaciones.json", "w", encoding="utf-8") as f:
                    json.dump(reclasificaciones, f, indent=2, ensure_ascii=False)

            print(f"OK Finalizado: {nombre} ({len(lugares_resultado)} lugar(es))")
            print(f"Progreso guardado en {OUTPUT_JSON} ({len(output_data['lugares'])} lugares)\n")

            time.sleep(DELAY_BETWEEN_REQUESTS)
    except KeyboardInterrupt:
        output_data = guardar_lugares(resultados)
        dump_error_log(ERROR_LOG_FILE)
        print("\n\nProceso interrumpido por el usuario.")
        if reclasificaciones:
            with open("informe_reclasificaciones.json", "w", encoding="utf-8") as f:
                json.dump(reclasificaciones, f, indent=2, ensure_ascii=False)
            print(f"Informe de reclasificaciones guardado en informe_reclasificaciones.json")
        print(f"Progreso guardado en {OUTPUT_JSON} ({len(output_data['lugares'])} lugares).")
        print(f"Log guardado en {ERROR_LOG_FILE}")
        return

    print("\n" + "=" * 70)
    print("Guardando JSON final...")

    output_data = guardar_lugares(resultados)

    print(f"Datos guardados en {OUTPUT_JSON}")
    print(f"Total de lugares: {len(output_data['lugares'])}")

    if reclasificaciones:
        with open("informe_reclasificaciones.json", "w", encoding="utf-8") as f:
            json.dump(reclasificaciones, f, indent=2, ensure_ascii=False)
        print(f"Informe de reclasificaciones ({len(reclasificaciones)} items) guardado en informe_reclasificaciones.json")

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

import json
import time
import os
import shutil

from scraper import fetch_url
from extractors import extract_descripciones
from logger import log_error, safe_print

INPUT_JSON = "municipios.json"
OUTPUT_JSON = "municipios_actualizado.json"
DELAY_BETWEEN_REQUESTS = 1.0

def main():
    if not os.path.exists(INPUT_JSON):
        print(f"Error: No existe el archivo {INPUT_JSON}")
        return

    # Si ya existe un archivo de salida parcial, lo cargamos para reanudar
    if os.path.exists(OUTPUT_JSON) and os.path.getsize(OUTPUT_JSON) > 0:
        print(f"Reanudando desde {OUTPUT_JSON}...")
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        if os.path.exists(OUTPUT_JSON):
            print(f"Archivo {OUTPUT_JSON} está vacío. Iniciando proceso desde {INPUT_JSON}...")
        else:
            print(f"Iniciando proceso desde {INPUT_JSON}...")
        with open(INPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

    lugares = data.get("lugares", [])
    total = len(lugares)
    
    # Encontrar el primer lugar que no tenga el flag 'desc_actualizada'
    start_idx = 0
    for i, lugar in enumerate(lugares):
        if not lugar.get("desc_actualizada", False):
            start_idx = i
            break
    
    if start_idx == 0 and lugares and lugares[0].get("desc_actualizada", False):
        print("Todos los municipios ya han sido actualizados.")
        return

    print(f"Comenzando desde el índice {start_idx} de {total}...")

    try:
        for i in range(start_idx, total):
            lugar = lugares[i]
            
            if lugar.get("desc_actualizada", False):
                continue
                
            nombre = lugar.get("nombre", "?")
            url = lugar.get("wikipedia_url")

            safe_print(f"[{i+1}/{total}] Actualizando descripciones para: {nombre}")

            if not url:
                safe_print(f"  [WARN] No tiene wikipedia_url, se salta.")
                lugar["desc_actualizada"] = True
                continue

            html = fetch_url(url)
            if not html:
                safe_print(f"  [ERROR] No se pudo descargar el HTML de {url}")
                log_error(f"Error descargando HTML para {nombre}")
                # Lo marcamos para no quedarnos atascados, o lo dejamos sin marcar.
                # Lo dejamos sin marcar para reintentar luego, o lo marcamos como fallido.
                continue

            try:
                desc_info = extract_descripciones(html, nombre_lugar=nombre, tipo=lugar.get("tipo", "municipio"), model_name="llama-3.2-3b-instruct")
                lugar["descripcion_corta"] = desc_info.get("descripcion_corta", lugar.get("descripcion_corta", ""))
                lugar["descripcion"] = desc_info.get("descripcion", lugar.get("descripcion", ""))
                lugar["desc_actualizada"] = True
                safe_print("  [OK] Descripciones extraídas con éxito.")
            except Exception as e:
                safe_print(f"  [ERROR] Fallo al extraer descripciones: {e}")
                log_error(f"Fallo extrayendo {nombre}: {e}")

            # Guardamos cada 10 iteraciones para no perder progreso
            if (i + 1) % 10 == 0:
                temp_file = OUTPUT_JSON + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(temp_file, OUTPUT_JSON)
                safe_print(f"--- Progreso guardado temporalmente ---")

            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        safe_print("\nProceso interrumpido por el usuario.")
    finally:
        # Guardado final
        temp_file = OUTPUT_JSON + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, OUTPUT_JSON)
        safe_print(f"Progreso guardado en {OUTPUT_JSON}. Puedes reanudar ejecutando el script de nuevo.")

if __name__ == "__main__":
    main()

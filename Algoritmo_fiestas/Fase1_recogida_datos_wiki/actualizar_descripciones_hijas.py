import json
import time
import os

from scraper import fetch_url
from extractors import extract_descripciones
from logger import log_error, safe_print

INPUT_JSON = "lugares_espana.json"
OUTPUT_JSON = "lugares_espana_actualizado.json"
DELAY_BETWEEN_REQUESTS = 1.0

def main():
    # Usaremos OUTPUT_JSON si existe para reanudar, sino leemos de INPUT_JSON
    if os.path.exists(OUTPUT_JSON) and os.path.getsize(OUTPUT_JSON) > 0:
        print(f"Reanudando desde {OUTPUT_JSON}...")
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        if not os.path.exists(INPUT_JSON):
            print(f"Error: No existe el archivo {INPUT_JSON}")
            return
        print(f"Iniciando proceso desde {INPUT_JSON}...")
        with open(INPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

    lugares = data.get("lugares", [])
    
    # Crear diccionario para acceso rapido a los padres por ID
    lugares_dict = {loc["id"]: loc for loc in lugares if "id" in loc}

    total = len(lugares)
    
    try:
        procesados_en_esta_sesion = 0
        for i in range(total):
            lugar = lugares[i]
            
            # Solo procesar hijas
            if lugar.get("tipo") == "municipio":
                continue
                
            # Si ya se actualizo, saltar
            if lugar.get("desc_hija_actualizada", False):
                continue
                
            nombre = lugar.get("nombre", "?")
            url = lugar.get("wikipedia_url")
            padre_id = lugar.get("padre_id")
            
            padre = lugares_dict.get(padre_id)
            padre_nombre = padre.get("nombre", "su municipio") if padre else "su municipio"
            padre_url = padre.get("wikipedia_url") if padre else None
            
            safe_print(f"[{i+1}/{total}] Procesando hija: {nombre} (Tipo: {lugar.get('tipo')})")

            # Determinar si tiene pagina de wikipedia propia
            tiene_wiki_propia = True
            if not url or url == padre_url:
                tiene_wiki_propia = False
                
            if not tiene_wiki_propia:
                safe_print(f"  -> NO tiene Wikipedia propia. Asignando descripcion por defecto.")
                lugar["descripcion_corta"] = f"Entidad de población que forma parte integrante del municipio de {padre_nombre}."
                lugar["descripcion"] = f"Este lugar forma parte integral del municipio de {padre_nombre}. Al carecer de registros históricos independientes, comparte plenamente el entorno natural, la cultura y la administración del municipio principal."
                lugar["desc_hija_actualizada"] = True
            else:
                safe_print(f"  -> SÍ tiene Wikipedia propia. Descargando y llamando a LLM...")
                html = fetch_url(url)
                if not html:
                    safe_print(f"  [ERROR] No se pudo descargar el HTML de {url}")
                    log_error(f"Error descargando HTML para hija {nombre}")
                    continue

                try:
                    desc_info = extract_descripciones(html, nombre_lugar=nombre, tipo=lugar.get("tipo"))
                    lugar["descripcion_corta"] = desc_info.get("descripcion_corta", lugar.get("descripcion_corta", ""))
                    lugar["descripcion"] = desc_info.get("descripcion", lugar.get("descripcion", ""))
                    lugar["desc_hija_actualizada"] = True
                    safe_print("  [OK] Descripciones extraídas con éxito.")
                except Exception as e:
                    safe_print(f"  [ERROR] Fallo al extraer descripciones: {e}")
                    log_error(f"Fallo extrayendo {nombre}: {e}")

                time.sleep(DELAY_BETWEEN_REQUESTS)
                
            procesados_en_esta_sesion += 1
            
            # Guardamos cada 10 iteraciones
            if procesados_en_esta_sesion % 10 == 0:
                temp_file = OUTPUT_JSON + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(temp_file, OUTPUT_JSON)
                safe_print(f"--- Progreso guardado temporalmente ---")

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

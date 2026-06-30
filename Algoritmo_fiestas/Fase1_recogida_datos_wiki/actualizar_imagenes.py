import json
import time
import os
import sys

# Asegurar que las importaciones de la carpeta funcionen
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import MUNICIPIOS_JSON
from scraper import fetch_url
from extractors import extract_imagenes
from logger import safe_print, log_error

def main():
    safe_print("\n" + "="*70)
    safe_print(" SCRIPT DE ACTUALIZACIÓN DE IMÁGENES (P18 y Escudos)")
    safe_print("="*70 + "\n")
    
    if not os.path.exists(MUNICIPIOS_JSON):
        safe_print(f"Error: No se encontró el archivo {MUNICIPIOS_JSON}")
        return

    safe_print("Cargando municipios.json...")
    try:
        with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        safe_print(f"Error al cargar el JSON: {e}")
        return
        
    lugares = data.get("lugares", [])
    total = len(lugares)
    
    modificados = 0
    errores = 0
    
    for idx, lugar in enumerate(lugares):
        banner = lugar.get("imagenes", {}).get("banner", "")
        logo = lugar.get("imagenes", {}).get("logo", "")
        
        # Condicion para actualizar: si es el fallback de picsum o si se eligió una bandera
        necesita_actualizar = (
            "picsum.photos" in banner or 
            "picsum.photos" in logo or 
            "bandera" in logo.lower() or 
            "flag" in logo.lower()
        )
            
        if necesita_actualizar:
            wiki_url = lugar.get("wikipedia_url")
            if not wiki_url:
                safe_print(f"[{idx+1}/{total}] [SALTADO] {lugar['nombre']} no tiene wikipedia_url.")
                continue
                
            safe_print(f"[{idx+1}/{total}] Actualizando imágenes para {lugar['nombre']}...")
            try:
                html = fetch_url(wiki_url)
                if html:
                    nuevas_imagenes = extract_imagenes(html, lugar['id'], wiki_url)
                    lugar["imagenes"] = nuevas_imagenes
                    modificados += 1
                    
                    # Guardado periódico
                    if modificados % 10 == 0:
                        with open(MUNICIPIOS_JSON, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                            
                time.sleep(0.5)
            except Exception as e:
                safe_print(f"[{idx+1}/{total}] [ERROR] Falló la actualización de {lugar['nombre']}: {e}")
                errores += 1
            
    # Guardado final
    if modificados > 0:
        with open(MUNICIPIOS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        safe_print(f"\nCompletado. Se intentaron actualizar las imágenes de {modificados} municipios.")
        if errores > 0:
            safe_print(f"Hubo {errores} errores durante el proceso.")
    else:
        safe_print("\nCompletado. No se encontraron municipios que requieran actualización.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        safe_print("\nProceso interrumpido por el usuario.")

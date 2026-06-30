import os
import time

from config import MUNICIPIOS_JSON, DELAY_BETWEEN_REQUESTS
from parte1_municipios.municipios import obtener_lugares_base, procesar_municipio_base
from main import cargar_municipios_previos, guardar_municipios, imprimir_validacion
from logger import log_error

def main():
    print("Iniciando recuperacion de municipios faltantes (segunda pasada)...")
    lugares_base = obtener_lugares_base()
    
    municipios_existentes = cargar_municipios_previos()
    
    urls_existentes = {m.get("wikipedia_url") for m in municipios_existentes if m.get("wikipedia_url")}
    
    faltantes = [lb for lb in lugares_base if lb.get("article_url") not in urls_existentes]
    print(f"Faltan {len(faltantes)} municipios por procesar.")
    
    if not faltantes:
        print("No hay municipios faltantes. Terminando.")
        return
        
    for idx, lugar_base in enumerate(faltantes, 1):
        nombre = lugar_base.get("nombre", "?")
        print(f"[{idx}/{len(faltantes)}] Recuperando {nombre}...")
        
        try:
            lugar, _ = procesar_municipio_base(lugar_base)
            if lugar:
                municipios_existentes.append(lugar)
                guardar_municipios(municipios_existentes)
                print(f"   [OK] Guardado {nombre} ({len(municipios_existentes)} total)")
            else:
                print(f"   [ERROR] Fallo al procesar {nombre}")
        except Exception as e:
            print(f"   [ERROR] Excepcion en {nombre}: {e}")
            log_error(f"Error recuperando {nombre}: {e}")
            
        time.sleep(DELAY_BETWEEN_REQUESTS)
        
    print("\nRecuperacion terminada.")
    print(f"Total actual en json: {len(municipios_existentes)}")

if __name__ == "__main__":
    main()

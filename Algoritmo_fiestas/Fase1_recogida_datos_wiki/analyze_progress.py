import json
import os
from collections import Counter

JSON_FILE = "lugares_espana.json"
MUNICIPIOS_JSON = "municipios.json"

def analyze():
    print("=== ANÁLISIS DE lugares_espana.json ===")
    if not os.path.exists(JSON_FILE):
        print(f"No se encontró el archivo {JSON_FILE}")
        return

    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error al leer JSON: {e}")
        return

    lugares = data.get("lugares", [])
    total_lugares = len(lugares)
    print(f"Total de lugares procesados (raíces + hijas): {total_lugares}")

    tipos_count = Counter()
    datos_faltantes = Counter()
    municipios_procesados = []

    for lugar in lugares:
        tipo = lugar.get("tipo", "desconocido")
        tipos_count[tipo] += 1
        
        if tipo == "municipio":
            municipios_procesados.append(lugar.get("nombre"))

        # Check required data
        faltan = []
        if not lugar.get("descripcion"): faltan.append("descripcion")
        if not lugar.get("descripcion_corta"): faltan.append("descripcion_corta")
        if not lugar.get("lat") and lugar.get("lat") != 0.0: faltan.append("lat")
        if not lugar.get("lng") and lugar.get("lng") != 0.0: faltan.append("lng")
        imagenes = lugar.get("imagenes", {})
        if not imagenes.get("banner"): faltan.append("imagenes.banner")
        
        for f in faltan:
            datos_faltantes[f] += 1

    print("\n--- Desglose por Tipo ---")
    for t, c in tipos_count.items():
        print(f"- {t}: {c}")

    print("\n--- Calidad de Datos (Campos vacíos) ---")
    for f, c in datos_faltantes.items():
        print(f"- {f}: {c} lugares sin este dato")

    print("\n=== ANÁLISIS DE SALTOS ===")
    if os.path.exists(MUNICIPIOS_JSON):
        with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
            muni_data = json.load(f)
        
        muni_wiki = muni_data.get("lugares", []) if isinstance(muni_data, dict) else muni_data
        if isinstance(muni_wiki, list):
            # Asumimos que los procesados mantienen el mismo orden
            # Para ver los saltados, podemos ver la consola o tratar de inferirlo.
            # Solo como referencia, cuántos municipios hay en el padrón wiki
            print(f"Total municipios en padrón inicial (municipios.json): {len(muni_wiki)}")
            print(f"Municipios procesados hasta ahora: {tipos_count['municipio']}")
            
            # Vamos a ver los últimos 5 procesados para saber por dónde va
            print(f"\nÚltimos 5 municipios procesados:")
            for m in municipios_procesados[-5:]:
                print(f" - {m}")
                
if __name__ == '__main__':
    analyze()

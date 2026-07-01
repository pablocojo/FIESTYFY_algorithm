import json
import os
from collections import Counter

JSON_FILE = "lugares_espana.json"

def analyze_descriptions():
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
    
    fallback_corta = "Una localidad con encanto e historia por descubrir."
    
    count_llm = 0
    count_fallback = 0
    
    # Also separate by type to give a better overview
    fallback_por_tipo = Counter()

    for lugar in lugares:
        desc_corta = lugar.get("descripcion_corta", "").strip()
        tipo = lugar.get("tipo", "desconocido")
        
        # We can check the exact fallback short description
        if desc_corta == fallback_corta:
            count_fallback += 1
            fallback_por_tipo[tipo] += 1
        else:
            count_llm += 1

    print("=== ANÁLISIS DE DESCRIPCIONES ===")
    print(f"Total de descripciones procesadas: {total_lugares}")
    print(f"Extraídas reales (Wikipedia + LLM): {count_llm} ({round((count_llm/total_lugares)*100, 2)}%)")
    print(f"Generadas de relleno (Fallback): {count_fallback} ({round((count_fallback/total_lugares)*100, 2)}%)")
    
    if count_fallback > 0:
        print("\n--- Fallbacks por tipo de lugar ---")
        for t, c in fallback_por_tipo.items():
            print(f"- {t}: {c}")

if __name__ == '__main__':
    analyze_descriptions()

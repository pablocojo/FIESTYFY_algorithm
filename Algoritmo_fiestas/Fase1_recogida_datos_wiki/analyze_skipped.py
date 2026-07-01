import json
import os

MUNICIPIOS_JSON = "municipios.json"
OUTPUT_JSON = "lugares_espana.json"

def analyze_skipped():
    with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
        muni_wiki_data = json.load(f)
        muni_wiki = muni_wiki_data.get("lugares", []) if isinstance(muni_wiki_data, dict) else muni_wiki_data
        
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        output_data = json.load(f)
        procesados = output_data.get("lugares", [])
        
    municipios_procesados = [m for m in procesados if m.get("tipo") == "municipio"]
    
    # 1. Comprobar si los municipios procesados tienen todos los datos
    faltantes_en_municipios = 0
    for m in municipios_procesados:
        if not m.get("descripcion") or not m.get("descripcion_corta"):
            faltantes_en_municipios += 1
            
    print(f"Total municipios en output: {len(municipios_procesados)}")
    print(f"Municipios con datos incompletos (descripciones): {faltantes_en_municipios}")
    
    # 2. Comprobar si se ha saltado alguno
    if not municipios_procesados:
        print("No hay municipios procesados.")
        return
        
    # Obtener el nombre del primer y último municipio procesado
    primer_muni_proc = municipios_procesados[0]
    ultimo_muni_proc = municipios_procesados[-1]
    
    idx_inicio = -1
    idx_fin = -1
    
    for i, m in enumerate(muni_wiki):
        if (m.get("id") == primer_muni_proc.get("original_id")) or (m.get("nombre") == primer_muni_proc.get("nombre") and idx_inicio == -1):
            idx_inicio = i
        if (m.get("id") == ultimo_muni_proc.get("original_id")) or (m.get("nombre") == ultimo_muni_proc.get("nombre")):
            idx_fin = i
            
    print(f"\nRango en el padrón original: Índice {idx_inicio} a {idx_fin}")
    
    if idx_inicio == -1 or idx_fin == -1:
        print("Error: No se pudo localizar el inicio o fin en el JSON original.")
        return
        
    # Extraer la porción esperada
    rango_esperado = muni_wiki[idx_inicio:idx_fin+1]
    nombres_esperados = [m.get("nombre") for m in rango_esperado]
    nombres_procesados = [m.get("nombre") for m in municipios_procesados]
    
    # Encontrar los que faltan
    saltados = [nombre for nombre in nombres_esperados if nombre not in nombres_procesados]
    
    print(f"Total esperados en ese rango: {len(rango_esperado)}")
    print(f"Total realmente procesados: {len(municipios_procesados)}")
    print(f"Total SALTADOS: {len(saltados)}")
    
    if saltados:
        print("Municipios que el script NO pudo enlazar con el INE y saltó:")
        for s in saltados:
            print(f" - {s}")
            
if __name__ == '__main__':
    analyze_skipped()

import json
import re

FILE_PATH = "lugares_espana.json"

def main():
    print("Cargando JSON...")
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    lugares = data.get("lugares", [])
    
    corregidos = 0
    
    for loc in lugares:
        desc_c = loc.get("descripcion_corta")
        desc = loc.get("descripcion")
        
        necesita_cambio = False
        
        if desc_c:
            nuevo_desc_c = re.sub(r'\s+', ' ', desc_c.strip())
            if nuevo_desc_c:
                nuevo_desc_c = nuevo_desc_c[0].upper() + nuevo_desc_c[1:]
            if nuevo_desc_c != desc_c:
                loc["descripcion_corta"] = nuevo_desc_c
                necesita_cambio = True
                
        if desc:
            nuevo_desc = re.sub(r'\s+', ' ', desc.strip())
            if nuevo_desc:
                nuevo_desc = nuevo_desc[0].upper() + nuevo_desc[1:]
            if nuevo_desc != desc:
                loc["descripcion"] = nuevo_desc
                necesita_cambio = True
                
        if necesita_cambio:
            corregidos += 1
            
    if corregidos > 0:
        print(f"Se corrigieron {corregidos} lugares. Guardando...")
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Guardado exitoso.")
    else:
        print("No se encontraron lugares que necesitaran corrección ortográfica de minúsculas/espacios.")

if __name__ == "__main__":
    main()

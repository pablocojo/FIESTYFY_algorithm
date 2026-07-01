import json
import os

with open('lugares_espana.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

lugares = data.get("lugares", [])
munis = [l for l in lugares if l.get("tipo") == "municipio"]

print(f"Total lugares: {len(lugares)}")
print(f"Total municipios: {len(munis)}")

# We want to keep exactly 1430 municipios.
# Find the ID of the 1430th municipio.
if len(munis) > 1430:
    target_muni = munis[1430] # 0-indexed, so 1430 is the 1431st (Palacios de la Sierra)
    
    # Alternatively, just collect the IDs of the first 1430 municipios
    valid_muni_ids = set()
    for m in munis[:1430]:
        valid_muni_ids.add(m["id"])
    
    # Keep only places that are one of the valid municipios, or have a valid municipio as their ancestor
    new_lugares = []
    for l in lugares:
        if l.get("tipo") == "municipio":
            if l["id"] in valid_muni_ids:
                new_lugares.append(l)
        else:
            # Check if its root parent is in valid_muni_ids
            # We can find root by following padre_id. For pedanias, padre_id is the municipio.
            # But let's just do a simpler approach: 
            # In the list, places are ordered (municipio, then its children). 
            # So if we truncate at the index of the 1431st municipio, we are good!
            pass

    # Find the index of the 1431st municipio in the original lugares list
    idx_to_cut = -1
    muni_count = 0
    for i, l in enumerate(lugares):
        if l.get("tipo") == "municipio":
            muni_count += 1
            if muni_count == 1431:
                idx_to_cut = i
                break
    
    if idx_to_cut != -1:
        data["lugares"] = lugares[:idx_to_cut]
        print(f"Cutting at index {idx_to_cut}. New total lugares: {len(data['lugares'])}")
        
        with open('lugares_espana.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Done. Saved to lugares_espana.json.")
    else:
        print("Could not find the 1431st municipio. Nothing changed.")
else:
    print("There are not 1431 municipios in the file. Nothing to undo.")

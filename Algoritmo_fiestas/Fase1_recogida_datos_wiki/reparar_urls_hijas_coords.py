import json
import urllib.request
import urllib.parse
import math
import time
import os

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

wiki_coords_cache = {}
CACHE_FILE = "wiki_coords_cache.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def get_wiki_coords(url, cache):
    if url in cache:
        res = cache[url]
        return res[0], res[1]
    
    title = urllib.parse.unquote(url.split("/")[-1])
    query = urllib.parse.quote(title)
    api_url = f"https://es.wikipedia.org/w/api.php?action=query&prop=coordinates&titles={query}&format=json"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(api_url, headers={'User-Agent': 'FiestyfyDataCleaner/1.0 (sainzmartinp@gmail.com)'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                pages = data.get("query", {}).get("pages", {})
                for page_id, page_info in pages.items():
                    coords = page_info.get("coordinates")
                    if coords and len(coords) > 0:
                        res = (coords[0].get("lat"), coords[0].get("lon"))
                        cache[url] = res
                        time.sleep(0.1)
                        return res
                # Si no hay coordenadas
                cache[url] = (None, None)
                time.sleep(0.1)
                return (None, None)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = 2 ** attempt
                print(f"429 Too Many Requests for {title}. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"HTTP Error {e.code} for {title}")
                break
        except Exception as e:
            print(f"Error fetching coords for {title}: {e}")
            break
            
    cache[url] = (None, None)
    return (None, None)

def main():
    input_file = "lugares_espana.json"
    output_file = "lugares_espana_corregido_coords.json"
    
    cache = load_cache()
    
    print("Loading data...")
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    lugares = data.get("lugares", [])
    
    corregidos = 0
    total_hijas = 0
    total_hijas_con_wiki = 0
    
    for i, lugar in enumerate(lugares):
        if "padre_id" in lugar and lugar["padre_id"]:
            total_hijas += 1
            wiki_url = lugar.get("wikipedia_url")
            if wiki_url:
                total_hijas_con_wiki += 1
                lat_ine = lugar.get("lat")
                lng_ine = lugar.get("lng")
                
                if lat_ine is None or lng_ine is None:
                    continue
                    
                w_lat, w_lon = get_wiki_coords(wiki_url, cache)
                
                discard = False
                if w_lat is None:
                    discard = True
                    reason = "NO COORDS"
                else:
                    dist = haversine_distance(lat_ine, lng_ine, w_lat, w_lon)
                    if dist > 2.5:
                        discard = True
                        reason = f"DISTANCE {dist:.2f} km"
                        
                progreso_str = f"[{i+1}/{len(lugares)} | Quedan {len(lugares)-(i+1)}]"
                if discard:
                    print(f"{progreso_str} [-] Limpiando: {lugar['nombre']} | Razón: {reason} | URL: {wiki_url}")
                    lugar["wikipedia_url"] = ""
                    lugar["sitio_web"] = ""
                    lugar["imagenes"] = {"banner": "", "logo": ""}
                    lugar["descripcion_corta"] = "Una localidad con encanto e historia por descubrir."
                    lugar["descripcion"] = f"{lugar['nombre']} es un destino ideal para disfrutar del turismo, descubrir paisajes inolvidables y sumergirse en su riqueza cultural."
                    corregidos += 1
                else:
                    print(f"{progreso_str} [+] Validado: {lugar['nombre']} | URL: {wiki_url}")
                    
        if i % 100 == 0 and i > 0:
            print(f"--> Procesado {i}/{len(lugares)} (Limpiados hasta ahora: {corregidos})")
            save_cache(cache)
            
    save_cache(cache)
    print(f"Se han limpiado {corregidos} de {total_hijas_con_wiki} localidades hijas con URL de wiki ({total_hijas} localidades hijas en total).")
    
    print("Saving data...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Done!")

if __name__ == "__main__":
    main()

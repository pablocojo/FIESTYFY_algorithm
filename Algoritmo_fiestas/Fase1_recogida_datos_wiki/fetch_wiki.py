import json
import wikipedia
import re
import time

wikipedia.set_lang("es")
wikipedia.set_user_agent("FIESTYFY_Bot/1.0 (info@fiestyfy.com)")

with open('municipios_faltantes.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for m in data['lugares']:
    # skip if already found
    if m.get('wikipedia_url'):
        continue
        
    nombre = m['nombre']
    provincia = m['provincia']
    
    # Pre-process name (e.g. Berrioplano/Berriobeiti -> Berrioplano)
    if '/' in nombre:
        parts = nombre.split('/')
        search_query = f"{parts[0]} (municipio)"
    else:
        search_query = f"{nombre} {provincia}"
        
    print(f"Searching for: {nombre} ({search_query})")
    
    try:
        results = wikipedia.search(search_query, results=3)
        if results:
            best_match = results[0]
            page = None
            for r in results:
                try:
                    page = wikipedia.page(r, auto_suggest=False)
                    break 
                except wikipedia.exceptions.DisambiguationError as e:
                    try:
                        page = wikipedia.page(e.options[0], auto_suggest=False)
                        break
                    except:
                        pass
                except Exception:
                    continue
                    
            if page:
                m['wikipedia_url'] = page.url
                try:
                    summary = wikipedia.summary(page.title, sentences=2, auto_suggest=False)
                    m['descripcion_corta'] = summary
                    m['descripcion'] = summary
                except:
                    pass
                print(f"  [OK] Found: {page.url}")
            else:
                print(f"  [FAIL] Could not load page for: {nombre}")
        else:
            print(f"  [FAIL] No search results for: {nombre}")
            
    except Exception as e:
        print(f"  [WARN] Error with {nombre}: {e}")
        
    time.sleep(0.5) 

with open('municipios_faltantes.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("Done!")

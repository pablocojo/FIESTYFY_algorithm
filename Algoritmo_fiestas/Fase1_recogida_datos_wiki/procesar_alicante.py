import json
import re
from scraper import fetch_url, get_soup

OUTPUT_JSON = "lugares_espana.json"

def _slug(texto):
    if not texto: return ""
    t = texto.lower()
    for o, d in zip("áéíóúüñ", "aeiouun"):
        t = t.replace(o, d)
    return re.sub(r'[^a-z0-9]', '', t)

def main():
    print("Iniciando extracción manual para Alicante...")
    
    with open(OUTPUT_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
        lugares_global = data.get('lugares', [])
        
    alicante = next((l for l in lugares_global if l['id'] == 'alicante'), None)
    if not alicante:
        print("Error: No se encuentra alicante en el JSON.")
        return
        
    # Mantener alicante, pedanías y distritos existentes. Borrar barrios.
    nuevos_lugares = []
    pedanias_existentes = 0
    distritos_existentes = 0
    for l in lugares_global:
        es_hijo_alicante = l.get('padre_id') == 'alicante' or l.get('abuelo_id') == 'alicante'
        if l['id'] == 'alicante':
            nuevos_lugares.append(l)
        elif es_hijo_alicante:
            if l.get('tipo') == 'pedania':
                nuevos_lugares.append(l)
                pedanias_existentes += 1
            elif l.get('tipo') == 'distrito':
                nuevos_lugares.append(l)
                distritos_existentes += 1
            else:
                pass # Borramos barrios
        else:
            nuevos_lugares.append(l)
            
    print(f"Pedanías preservadas: {pedanias_existentes}")
    print(f"Distritos preservados: {distritos_existentes}")

    url_anexo = "https://es.wikipedia.org/wiki/Anexo:Organizaci%C3%B3n_pol%C3%ADtico-administrativa_de_Alicante"
    html = fetch_url(url_anexo)
    soup = get_soup(html)
    ts = soup.select('table.wikitable')
    
    t_barrios = ts[1]
    t_distritos = ts[2]
    
    lugares_hijos = []
    distritos_map = {} 
    
    print("Generando mapa de distritos...")
    for row in t_distritos.select('tr')[1:]:
        tds = row.select('td')
        if len(tds) < 2: continue
        
        raw_name = tds[0].text.strip()
        num_match = re.search(r'\d+', raw_name)
        if num_match:
            nombre = f"Distrito {num_match.group(0)}"
        else:
            nombre = raw_name
            
        lugar_id = f"alicante_distrito-{_slug(nombre)}"
        zonas_text = tds[1].text
        zonas = [z.strip() for z in re.split(r',| y ', zonas_text) if z.strip()]
        for z in zonas:
            distritos_map[_slug(z)] = lugar_id
            
    from extractors import construir_lugar
    import extractors
    
    # Bypass LLM para no bloquear al extraer el lugar
    def mock_extract(html, nombre_lugar=None, tipo=None, **kwargs):
        return {
            "descripcion_corta": f"Barrio de Alicante.",
            "descripcion": f"{nombre_lugar or 'El barrio'} es un barrio perteneciente a la ciudad de Alicante."
        }
    extractors.extract_descripciones = mock_extract
            
    print("Extrayendo barrios...")
    for row in t_barrios.select('tr')[1:]:
        tds = row.select('td')
        if len(tds) < 3: continue
        
        raw_name = tds[0].text.strip()
        nombre = re.sub(r'\s*\(\d+\)$', '', raw_name).strip()
        
        a_tag = tds[0].find('a')
        link = ""
        if a_tag:
            href = a_tag.get('href', '')
            if href.startswith('//'):
                link = "https:" + href
            elif href.startswith('/wiki/'):
                link = "https://es.wikipedia.org" + href
        
        pop_text = tds[2].text.replace('.', '').replace('\xa0', '').strip()
        poblacion = int(pop_text) if pop_text.isdigit() else 0
        
        b_slug = _slug(nombre)
        padre_id = "alicante"
        abuelo_id = None
        
        for z_slug, d_id in distritos_map.items():
            if b_slug in z_slug or z_slug in b_slug:
                padre_id = d_id
                abuelo_id = "alicante"
                break
                
        if link:
            # Construir con extractors
            html_barrio = fetch_url(link)
            if html_barrio:
                try:
                    obj = construir_lugar(
                        nombre=nombre,
                        html=html_barrio,
                        tipo="barrio",
                        padre_id=padre_id,
                        padre_info=alicante,
                        wikipedia_url=link
                    )
                    obj["poblacion"] = poblacion
                    if abuelo_id:
                        obj["abuelo_id"] = abuelo_id
                except Exception as e:
                    print(f"Fallo al construir {nombre}: {e}")
                    obj = None
            else:
                obj = None
        else:
            obj = None
            
        if not obj:
            lugar_id = f"{padre_id}_{_slug(nombre)}"
            obj = {
                "id": lugar_id,
                "tipo": "barrio",
                "nombre": nombre,
                "provincia": alicante.get("provincia", ""),
                "comunidad": alicante.get("comunidad", ""),
                "poblacion": poblacion,
                "lat": 0.0,
                "lng": 0.0,
                "descripcion_corta": f"Barrio de la ciudad de Alicante.",
                "descripcion": f"{nombre} es un barrio perteneciente a la ciudad de Alicante, España.",
                "imagenes": [],
                "sitio_web": None,
                "wikipedia_url": link,
                "padre_id": padre_id
            }
            if abuelo_id:
                obj["abuelo_id"] = abuelo_id
            
        if padre_id != "alicante":
            dist_obj = next((d for d in nuevos_lugares if d['id'] == padre_id), None)
            if dist_obj:
                dist_obj['poblacion'] += poblacion
                
        lugares_hijos.append(obj)

    nuevos_lugares.extend(lugares_hijos)
    data['lugares'] = nuevos_lugares
    
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Completado. Se añadieron {len(lugares_hijos)} barrios extraídos profundamente.")

if __name__ == "__main__":
    main()

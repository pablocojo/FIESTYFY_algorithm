import json
import os
import time
import urllib.parse
import threading

from config import MUNICIPIOS_JSON, OUTPUT_JSON, ERROR_LOG_FILE, DELAY_BETWEEN_REQUESTS
import config
config.LLM_MODEL_NAME = "qwen2.5-7b-instruct"
from extractors import inferir_comunidad_por_provincia, construir_lugar
from logger import dump_error_log, log_error
from parte2_distritos_pedanias.distritos_pedanias import procesar_estructura_ciudad
from place_types import valida_dataset, clasificar_por_poblacion
from scraper import fetch_url
from datos_ine import cargar_datos_ine, buscar_municipio_ine, cargar_municipios_ngmep, cargar_entidades_ngmep


def cargar_json_lugares(path: str) -> list[dict]:
    if not os.path.exists(path): return []
    try:
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
    except: return []
    lugares = data.get("lugares", [])
    return lugares if isinstance(lugares, list) else []

def deduplicar_lugares(lugares: list[dict]) -> list[dict]:
    resultado, ids_vistos = [], set()
    for lugar in lugares:
        lugar_id = lugar.get("id")
        if not lugar_id or lugar_id in ids_vistos: continue
        ids_vistos.add(lugar_id)
        resultado.append(lugar)
    return resultado

def guardar_lugares(resultados: list[dict]) -> dict:
    lugares = deduplicar_lugares(resultados)
    for lugar in lugares:
        if not lugar.get("comunidad"):
            lugar["comunidad"] = inferir_comunidad_por_provincia(lugar.get("provincia")) or ""
        lugar.setdefault("sitio_web", "")
        lugar.setdefault("wikipedia_url", "")
    output_data = {"version": 3, "lugares": lugares}
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    return output_data

def buscar_wikipedia_url_api(nombre: str, provincia: str, lat: float = None, lng: float = None) -> str:
    from urllib.parse import quote
    import urllib.request
    import math
    
    query = quote(f"{nombre} {provincia}")
    url = f"https://es.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch={query}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            results = data.get("query", {}).get("search", [])
            if results:
                title = results[0]["title"]
                title_encoded = title.replace(" ", "_")
                wiki_url = f"https://es.wikipedia.org/wiki/{title_encoded}"
                
                if lat is not None and lng is not None:
                    try:
                        t_query = quote(title)
                        c_url = f"https://es.wikipedia.org/w/api.php?action=query&prop=coordinates&titles={t_query}&format=json"
                        c_req = urllib.request.Request(c_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(c_req) as c_response:
                            c_data = json.loads(c_response.read().decode('utf-8'))
                            pages = c_data.get("query", {}).get("pages", {})
                            w_lat = None
                            w_lon = None
                            for _, page_info in pages.items():
                                coords = page_info.get("coordinates")
                                if coords and len(coords) > 0:
                                    w_lat = coords[0].get("lat")
                                    w_lon = coords[0].get("lon")
                                    
                            if w_lat is None:
                                return "" # Descartar si no hay coordenadas
                            
                            R = 6371.0
                            lat1_rad, lon1_rad = math.radians(lat), math.radians(lng)
                            lat2_rad, lon2_rad = math.radians(w_lat), math.radians(w_lon)
                            dlat = lat2_rad - lat1_rad
                            dlon = lon2_rad - lon1_rad
                            a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
                            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                            dist = R * c
                            
                            if dist > 2.5:
                                return "" # Descartar si excede distancia
                    except Exception as e:
                        return ""
                
                return wiki_url
    except Exception as e:
        log_error(f"Error en buscar_wikipedia_url_api para {nombre}: {e}")
    return ""

def mandar_ws(n, p):
    try:
        import pyautogui
        telefono = "+34682312869"
        mensaje = f"Se ha saltado y guardado un lugar gigante: {n} ({p} habitantes)"
        mensaje_codificado = urllib.parse.quote(mensaje)
        url_whatsapp = f"whatsapp://send?phone={telefono}&text={mensaje_codificado}"
        os.system(f'start "" "{url_whatsapp}"')
        time.sleep(6)
        pyautogui.press('enter')
    except: pass

def main():
    print("\n" + "=" * 70)
    print(" FASE 2: ENRIQUECIMIENTO CON NGMEP Y SUBDIVISIONES")
    print("=" * 70 + "\n")

    municipios_wiki = cargar_json_lugares(MUNICIPIOS_JSON)
    if not municipios_wiki:
        print(f"ERROR: No hay {MUNICIPIOS_JSON}.")
        return

    resultados = cargar_json_lugares(OUTPUT_JSON)
    ultimos_municipios = [l for l in resultados if l.get("tipo") == "municipio"]
    
    # Crear un set con los IDs de los municipios ya procesados en lugares_espana.json
    ids_procesados = set()
    if ultimos_municipios:
        for m in ultimos_municipios:
            m_id = m.get("original_id") or m.get("id")
            if m_id:
                ids_procesados.add(m_id)
                
    start_idx = 1 # Para mantener la compatibilidad con el print del idx


    datos_ine = cargar_datos_ine()
    muni_ngmep = cargar_municipios_ngmep()
    enti_ngmep = cargar_entidades_ngmep()
    
    import parte2_distritos_pedanias.distritos_pedanias as dp_module
    dp_module.DATOS_INE_GLOBAL = datos_ine

    for idx, municipio in enumerate(municipios_wiki, start=1):
        nombre_wiki = municipio.get("nombre", "?")
        
        # Saltar si ya está procesado
        m_id = municipio.get("id")
        if m_id in ids_procesados or (m_id and any(m_id == k for k in ids_procesados)):
            continue
            
        print(f"\n[{idx}/{len(municipios_wiki)}] Procesando: {nombre_wiki}")
        
        nombre_buscar = municipio.get("nombre_oficial", nombre_wiki)
        info_ine = buscar_municipio_ine(nombre_buscar, municipio.get("provincia", ""), datos_ine)
        if not info_ine:
            # Fallback con LLM si no se encuentra
            wiki_url = municipio.get("wikipedia_url")
            if wiki_url:
                print(f"   -> No encontrado por nombre exacto. Intentando LLM fallback con Wikipedia...")
                html_muni = fetch_url(wiki_url)
                if html_muni:
                    info_ine = buscar_municipio_ine(nombre_buscar, municipio.get("provincia", ""), datos_ine, html_muni)

        if not info_ine:
            print(f"   -> NO ENCONTRADO EN INE (ni con LLM). Saltando.")
            continue
            
        cpro, cmun = info_ine['clave']
        cod_ine_muni = f"{cpro}{cmun}000000"
        inemuni = f"{cpro}{cmun}"
        
        datos_muni_ng = muni_ngmep.get(cod_ine_muni)
        if not datos_muni_ng:
            print(f"   -> CODIGO {cod_ine_muni} no hallado en MUNICIPIOS.csv. Saltando.")
            continue
            
        # Actualizamos el municipio raiz
        provincia_ine = datos_ine['municipios'][(cpro, cmun)]['provincia']
        municipio["provincia"] = provincia_ine
        municipio["original_id"] = municipio.get("id")  # Guardamos el ID de Wikipedia para poder reanudar
        municipio["id"] = cod_ine_muni
        municipio["tipo"] = "municipio"
        municipio["poblacion"] = datos_muni_ng["poblacion"]
        municipio["lat"] = datos_muni_ng["lat"]
        municipio["lng"] = datos_muni_ng["lng"]
        municipio["es_capital"] = False
        
        lugares_resultado = [municipio]
        
        # Procesar entidades hijas
        entidades = enti_ngmep.get(inemuni, [])
        print(f"   -> Encontradas {len(entidades)} entidades validas en ENTIDADES.csv")
        
        for ent in entidades:
            tipo_hija = clasificar_por_poblacion(ent["poblacion"])
            if not tipo_hija: continue
            
            print(f"   -> Hija: {ent['nombre']} ({tipo_hija}, {ent['poblacion']} hab)")
            
            # Construir obj
            lugar_hija = {
                "id": ent["id"],
                "padre_id": cod_ine_muni,
                "nombre": ent["nombre"],
                "provincia": municipio.get("provincia", ""),
                "comunidad": municipio.get("comunidad", ""),
                "poblacion": ent["poblacion"],
                "lat": ent["lat"],
                "lng": ent["lng"],
                "es_capital": ent["es_capital"],
                "tipo": tipo_hija,
                "sitio_web": "",
                "wikipedia_url": "",
                "descripcion_corta": "",
                "descripcion": "",
                "imagenes": {"banner": "", "logo": ""}
            }
            
            wiki_url = buscar_wikipedia_url_api(ent["nombre"], municipio.get("provincia", ""), ent["lat"], ent["lng"])
            if wiki_url:
                lugar_hija["wikipedia_url"] = wiki_url
                html_hija = fetch_url(wiki_url)
                if html_hija:
                    try:
                        # Extraer info base (descripcion, imagenes)
                        lugar_base = construir_lugar(ent["nombre"], html_hija, tipo_hija, cod_ine_muni, municipio, wiki_url)
                        if lugar_base:
                            lugar_hija["descripcion_corta"] = lugar_base.get("descripcion_corta", "")
                            lugar_hija["descripcion"] = lugar_base.get("descripcion", "")
                            lugar_hija["imagenes"] = lugar_base.get("imagenes", {})
                            lugar_hija["sitio_web"] = lugar_base.get("sitio_web", "")
                    except Exception as e:
                        print(f"      - Error LLM extraccion: {e}")
            
            if not lugar_hija["descripcion"]:
                lugar_hija["descripcion_corta"] = "Una localidad con encanto e historia por descubrir."
                lugar_hija["descripcion"] = f"{ent['nombre']} es un destino ideal para disfrutar del turismo, descubrir paisajes inolvidables y sumergirse en su riqueza cultural."
            
            lugares_resultado.append(lugar_hija)
            
            # Buscar distritos y barrios si corresponde
            if tipo_hija in ("ciudad_grande", "ciudad_pequena"):
                if ent["poblacion"] > 102986 and ent["nombre"] != "Roquetas de Mar":
                    print(f"      - [SKIPPED] {ent['nombre']} supera limite poblacion. Mandando ws.")
                    threading.Thread(target=mandar_ws, args=(ent["nombre"], ent["poblacion"]), daemon=True).start()
                else:
                    if wiki_url and html_hija:
                        subs = procesar_estructura_ciudad(html_hija, lugar_hija)
                        lugares_resultado.extend(subs)

        resultados.extend(lugares_resultado)
        guardar_lugares(resultados)
        print(f"   -> Guardado {nombre_wiki} y {len(lugares_resultado)-1} entidades.")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    print("\n" + "=" * 70)
    print(" FASE 2 FINALIZADA")
    print("=" * 70 + "\n")
    
if __name__ == "__main__":
    main()

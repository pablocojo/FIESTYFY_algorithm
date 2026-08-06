import json
import os
import time
import urllib.parse
import threading

from config import (
    MUNICIPIOS_JSON, OUTPUT_JSON, ERROR_LOG_FILE, DELAY_BETWEEN_REQUESTS,
    WIKI_SEARCH_SRLIMIT, WIKI_SEARCH_MAX_RETRIES, WIKI_SEARCH_DELAY,
    WIKI_DISTANCIA_PUEBLOS_KM,
)
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
        with open(path, "r", encoding="utf-8-sig") as f: data = json.load(f)
    except Exception:
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        except Exception:
            return []
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

def _wiki_api_get(params: dict) -> dict | None:
    """Llamada GET a la API de Wikipedia con reintentos ante HTTP 429."""
    import urllib.request
    params["format"] = "json"
    query_string = urllib.parse.urlencode(params)
    url = f"https://es.wikipedia.org/w/api.php?{query_string}"
    ua = "FiestyfyBot/1.0 (sainzmartinp@gmail.com)"

    for attempt in range(WIKI_SEARCH_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                time.sleep(WIKI_SEARCH_DELAY)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"      [429] Rate limit. Esperando {wait}s...")
                time.sleep(wait)
            else:
                break
        except Exception:
            if attempt < WIKI_SEARCH_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    return None


def _es_desambiguacion(title: str) -> bool:
    """Comprueba si un artículo es una página de desambiguación."""
    data = _wiki_api_get({
        "action": "query", "prop": "pageprops",
        "ppprop": "disambiguation", "titles": title,
    })
    if not data:
        return False
    pages = data.get("query", {}).get("pages", {})
    for _, info in pages.items():
        if "pageprops" in info and "disambiguation" in info["pageprops"]:
            return True
    return False


def _obtener_coords_wiki(title: str) -> tuple:
    """Obtiene (lat, lon) de un artículo de Wikipedia, o (None, None)."""
    data = _wiki_api_get({"action": "query", "prop": "coordinates", "titles": title})
    if not data:
        return None, None
    pages = data.get("query", {}).get("pages", {})
    for _, info in pages.items():
        coords = info.get("coordinates")
        if coords and len(coords) > 0:
            return coords[0].get("lat"), coords[0].get("lon")
    return None, None


def _haversine(lat1, lon1, lat2, lon2) -> float:
    import math
    R = 6371.0
    la1, lo1 = math.radians(lat1), math.radians(lon1)
    la2, lo2 = math.radians(lat2), math.radians(lon2)
    dl, dn = la2 - la1, lo2 - lo1
    a = math.sin(dl/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dn/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _parte_castellana(nombre: str) -> str:
    """'Elx/Elche' → 'Elche'. Si no hay '/', devuelve el original."""
    if "/" not in nombre:
        return nombre
    partes = [p.strip() for p in nombre.split("/")]
    partes.sort(key=lambda s: sum(1 for c in s if c.isascii() and c.isalpha()) / max(len(s), 1), reverse=True)
    return partes[0]


def _generar_queries(nombre, provincia, comunidad=""):
    """Genera hasta 4 queries de búsqueda adaptativas."""
    queries = [f"{nombre} {provincia}"]
    cast = _parte_castellana(nombre)
    if cast != nombre:
        queries.append(f"{cast} {provincia}")
    q3 = f"{nombre} España"
    if q3 not in queries:
        queries.append(q3)
    if comunidad:
        q4 = f"{nombre} {comunidad} {provincia}"
        if q4 not in queries:
            queries.append(q4)
    return queries


def buscar_wikipedia_url_api(
    nombre: str, provincia: str, lat: float = None, lng: float = None,
    tipo: str = "pueblo", comunidad: str = ""
) -> str:
    """
    Busca la URL de Wikipedia para una entidad hija.
    - srlimit=3: evalúa los 3 primeros resultados por query.
    - Hasta 4 queries adaptativas.
    - Descarta desambiguaciones.
    - Ciudades: solo requiere coordenadas (sin validar distancia).
    - Pueblos/barrios/distritos: distancia <= WIKI_DISTANCIA_PUEBLOS_KM.
    - Reintentos con backoff ante HTTP 429.
    """
    es_ciudad = tipo in ("ciudad_grande", "ciudad_pequena")
    queries = _generar_queries(nombre, provincia, comunidad)

    mejor_url = None
    mejor_dist = float("inf")
    titulos_vistos = set()

    for query in queries:
        data = _wiki_api_get({
            "action": "query", "list": "search",
            "srsearch": query, "srlimit": WIKI_SEARCH_SRLIMIT,
        })
        if not data:
            continue

        results = data.get("query", {}).get("search", [])
        for r in results:
            title = r["title"]
            if title in titulos_vistos:
                continue
            titulos_vistos.add(title)

            if _es_desambiguacion(title):
                continue

            w_lat, w_lon = _obtener_coords_wiki(title)
            if w_lat is None:
                continue  # Sin coords → descartar

            candidate_url = f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}"

            if es_ciudad:
                # Solo requiere tener coordenadas; preferir la más cercana
                dist = _haversine(lat, lng, w_lat, w_lon) if (lat and lng) else 0.0
                if dist < mejor_dist:
                    mejor_dist = dist
                    mejor_url = candidate_url
                if dist < 2.5:
                    break
            else:
                # Pueblos/barrios: validar distancia
                if lat is None or lng is None:
                    continue
                dist = _haversine(lat, lng, w_lat, w_lon)
                if dist <= WIKI_DISTANCIA_PUEBLOS_KM and dist < mejor_dist:
                    mejor_dist = dist
                    mejor_url = candidate_url

        if mejor_url and mejor_dist < 1.0:
            break  # Resultado excelente, no probar más queries

    return mejor_url or ""

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


def municipio_ya_procesado(municipio: dict, ids_procesados: set) -> bool:
    m_id = municipio.get("id")
    return bool(m_id and m_id in ids_procesados)


def encontrar_inicio_pendiente(municipios_wiki: list[dict], ids_procesados: set) -> int | None:
    for idx, municipio in enumerate(municipios_wiki):
        if not municipio_ya_procesado(municipio, ids_procesados):
            return idx
    return None


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

    start_idx = encontrar_inicio_pendiente(municipios_wiki, ids_procesados)
    if start_idx is None:
        print("Todos los municipios ya están presentes en lugares_espana.json. No hay nada más por procesar.")
        return

    print(f"Reanudando desde el siguiente municipio pendiente: {municipios_wiki[start_idx].get('nombre', '?')}")

    datos_ine = cargar_datos_ine()
    muni_ngmep = cargar_municipios_ngmep()
    enti_ngmep = cargar_entidades_ngmep()
    
    import parte2_distritos_pedanias.distritos_pedanias as dp_module
    dp_module.DATOS_INE_GLOBAL = datos_ine

    for idx, municipio in enumerate(municipios_wiki[start_idx:], start=start_idx + 1):
        nombre_wiki = municipio.get("nombre", "?")
        
        # Saltar si ya está procesado
        if municipio_ya_procesado(municipio, ids_procesados):
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
            
            wiki_url = buscar_wikipedia_url_api(
                ent["nombre"], municipio.get("provincia", ""),
                ent["lat"], ent["lng"],
                tipo=tipo_hija, comunidad=municipio.get("comunidad", "")
            )
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

"""
Recuperador de URLs de Wikipedia para entidades hijas sin página.

Recorre lugares_espana.json buscando hijas (pueblo, ciudad_pequena,
ciudad_grande, distrito, barrio) que no tengan wikipedia_url y trata
de encontrar su artículo correcto en Wikipedia.

Estrategia de búsqueda:
  1. Genera hasta 4 queries adaptativas por lugar.
  2. Evalúa los top-3 resultados de cada query (srlimit=3).
  3. Descarta páginas de desambiguación.
  4. Para ciudades: solo requiere que el artículo tenga coordenadas.
  5. Para pueblos/barrios/distritos: valida distancia <= 2.5 km.
  6. Selecciona el candidato de menor distancia.
  7. Si encuentra URL, descarga HTML y genera descripciones/imágenes.

Reanudable: guarda progreso cada N lugares con flag "url_recuperada".

Uso:
  python recuperar_urls_hijas.py [--dry-run] [--solo-ciudades]
"""

import json
import math
import os
import re
import time
import argparse
import urllib.request
import urllib.parse
import unicodedata

from scraper import fetch_url
from extractors import extract_descripciones, extract_imagenes, extract_sitio_web
from logger import log_error, safe_print

from config import (
    WIKI_SEARCH_SRLIMIT,
    WIKI_SEARCH_MAX_RETRIES,
    WIKI_SEARCH_DELAY,
    WIKI_DISTANCIA_PUEBLOS_KM,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────
WIKI_API = "https://es.wikipedia.org/w/api.php"
USER_AGENT = "FiestyfyDataCleaner/1.0 (sainzmartinp@gmail.com)"
INPUT_FILE = "lugares_espana.json"
CACHE_COORDS_FILE = "wiki_coords_cache.json"
CACHE_SEARCH_FILE = "wiki_search_cache.json"
SAVE_EVERY_N = 30  # Guardar progreso cada N lugares procesados
DELAY_BETWEEN_LLM = 1.0  # Delay entre llamadas al LLM para descripciones

# Tipos que se consideran "ciudad" (no se valida distancia, solo existencia de coords)
TIPOS_CIUDAD = {"ciudad_grande", "ciudad_pequena"}


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def haversine_distance(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos geográficos."""
    R = 6371.0
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _normalizar(texto):
    """Elimina acentos y pasa a minúsculas para comparaciones."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _parte_castellana(nombre):
    """
    Extrae la parte castellana de un nombre bilingüe.
    Ej: "Elx/Elche" → "Elche", "Alacant/Alicante" → "Alicante"
    Para nombres con '/' se queda con la parte más larga (heurística).
    Si no hay '/', devuelve el nombre tal cual.
    """
    if "/" not in nombre:
        return nombre
    partes = [p.strip() for p in nombre.split("/")]
    # La parte castellana suele ser la más larga o la segunda
    # Heurística: devolver la que tenga más letras ASCII comunes
    def score_castellano(s):
        ascii_chars = sum(1 for c in s if c.isascii() and c.isalpha())
        return ascii_chars / max(len(s), 1)
    partes.sort(key=score_castellano, reverse=True)
    return partes[0]


# ─────────────────────────────────────────────────────────────────────────────
# CACHÉ
# ─────────────────────────────────────────────────────────────────────────────

def cargar_cache(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def guardar_cache(cache, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# LLAMADAS A LA API DE WIKIPEDIA CON REINTENTOS
# ─────────────────────────────────────────────────────────────────────────────

def _wiki_api_get(params):
    """
    Llamada GET a la API de Wikipedia con reintentos ante HTTP 429 y errores
    transitorios. Devuelve el JSON parseado o None.
    """
    params["format"] = "json"
    query_string = urllib.parse.urlencode(params)
    url = f"{WIKI_API}?{query_string}"

    for attempt in range(WIKI_SEARCH_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                time.sleep(WIKI_SEARCH_DELAY)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                safe_print(f"      [429] Rate limit. Esperando {wait}s...")
                time.sleep(wait)
            else:
                safe_print(f"      [HTTP {e.code}] Error en API Wikipedia")
                break
        except Exception as e:
            if attempt < WIKI_SEARCH_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                safe_print(f"      [ERROR] {e}")
    return None


def buscar_titulos(query, srlimit=WIKI_SEARCH_SRLIMIT):
    """Busca títulos en Wikipedia. Devuelve lista de títulos."""
    data = _wiki_api_get({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": srlimit,
    })
    if not data:
        return []
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def obtener_coordenadas(title, cache_coords):
    """
    Obtiene coordenadas de un artículo de Wikipedia.
    Devuelve (lat, lon) o (None, None).
    """
    url = f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}"
    if url in cache_coords:
        res = cache_coords[url]
        if res is None:
            return None, None
        return res[0], res[1]

    data = _wiki_api_get({
        "action": "query",
        "prop": "coordinates",
        "titles": title,
    })
    if not data:
        return None, None

    pages = data.get("query", {}).get("pages", {})
    for _, page_info in pages.items():
        coords = page_info.get("coordinates")
        if coords and len(coords) > 0:
            lat = coords[0].get("lat")
            lon = coords[0].get("lon")
            cache_coords[url] = (lat, lon)
            return lat, lon

    cache_coords[url] = None
    return None, None


def es_desambiguacion(title):
    """
    Comprueba si un artículo es una página de desambiguación.
    Usa prop=pageprops y busca la propiedad 'disambiguation'.
    """
    data = _wiki_api_get({
        "action": "query",
        "prop": "pageprops",
        "ppprop": "disambiguation",
        "titles": title,
    })
    if not data:
        return False

    pages = data.get("query", {}).get("pages", {})
    for _, page_info in pages.items():
        if "pageprops" in page_info and "disambiguation" in page_info["pageprops"]:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN DE QUERIES
# ─────────────────────────────────────────────────────────────────────────────

def generar_queries(nombre, provincia, comunidad):
    """
    Genera hasta 4 queries de búsqueda adaptativas.
    1. "{nombre} {provincia}"
    2. "{parte_castellana} {provincia}"        (solo si difiere del nombre)
    3. "{nombre} España"
    4. "{nombre} {comunidad} {provincia}"
    """
    queries = []

    # Query 1: nombre + provincia (la original)
    q1 = f"{nombre} {provincia}"
    queries.append(q1)

    # Query 2: parte castellana + provincia (si el nombre es bilingüe)
    castellano = _parte_castellana(nombre)
    if castellano != nombre:
        q2 = f"{castellano} {provincia}"
        queries.append(q2)

    # Query 3: nombre + España
    q3 = f"{nombre} España"
    if q3 not in queries:
        queries.append(q3)

    # Query 4: nombre + comunidad + provincia
    if comunidad:
        q4 = f"{nombre} {comunidad} {provincia}"
        if q4 not in queries:
            queries.append(q4)

    return queries


# ─────────────────────────────────────────────────────────────────────────────
# BÚSQUEDA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def buscar_mejor_url(nombre, provincia, comunidad, lat, lng, tipo, cache_coords, cache_search):
    """
    Intenta encontrar la URL de Wikipedia correcta para un lugar.

    Para ciudades (ciudad_grande, ciudad_pequena):
      Solo requiere que el artículo tenga coordenadas (no valida distancia).

    Para pueblos/barrios/distritos:
      Valida que la distancia sea <= WIKI_DISTANCIA_PUEBLOS_KM.

    Returns:
        (url, distancia) o (None, None)
    """
    es_ciudad = tipo in TIPOS_CIUDAD
    umbral_km = None if es_ciudad else WIKI_DISTANCIA_PUEBLOS_KM

    # Clave de caché para no repetir búsquedas
    cache_key = f"{nombre}|{provincia}|{tipo}"
    cached = cache_search.get(cache_key)
    if cached is not None:
        # cached puede ser "" (no encontrado) o una URL
        if cached == "":
            return None, None
        return cached, 0.0

    queries = generar_queries(nombre, provincia, comunidad)
    mejor_url = None
    mejor_dist = float("inf")

    titulos_vistos = set()

    for query in queries:
        titulos = buscar_titulos(query)
        for title in titulos:
            if title in titulos_vistos:
                continue
            titulos_vistos.add(title)

            # Descartar desambiguaciones
            if es_desambiguacion(title):
                continue

            # Obtener coordenadas
            w_lat, w_lon = obtener_coordenadas(title, cache_coords)

            if w_lat is None:
                # Sin coordenadas: para ciudades, descartar (necesitamos al menos
                # confirmar que tiene ubicación). Para pueblos, también descartar.
                continue

            # Para ciudades: basta con que tenga coordenadas
            if es_ciudad:
                url = f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}"
                # Aun así, preferimos el candidato más cercano
                if lat is not None and lng is not None:
                    dist = haversine_distance(lat, lng, w_lat, w_lon)
                else:
                    dist = 0.0
                if dist < mejor_dist:
                    mejor_dist = dist
                    mejor_url = url
                # Si encontramos uno muy cercano, no seguir buscando
                if dist < 2.5:
                    break
            else:
                # Para pueblos/barrios/distritos: validar distancia
                if lat is None or lng is None:
                    continue
                dist = haversine_distance(lat, lng, w_lat, w_lon)
                if dist <= umbral_km and dist < mejor_dist:
                    mejor_dist = dist
                    mejor_url = f"https://es.wikipedia.org/wiki/{title.replace(' ', '_')}"

        # Si ya tenemos un resultado muy bueno, no probar más queries
        if mejor_url and mejor_dist < 1.0:
            break

    # Guardar en caché
    cache_search[cache_key] = mejor_url or ""

    if mejor_url:
        return mejor_url, mejor_dist
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACCIÓN DE CONTENIDO (DESCRIPCIONES, IMÁGENES, SITIO WEB)
# ─────────────────────────────────────────────────────────────────────────────

def rellenar_contenido(lugar, wiki_url, padre_nombre):
    """
    Descarga el HTML de Wikipedia y extrae descripciones, imágenes y sitio web.
    Replica el comportamiento de actualizar_descripciones_hijas.py.
    """
    html = fetch_url(wiki_url)
    if not html:
        safe_print(f"      [WARN] No se pudo descargar HTML de {wiki_url}")
        return False

    try:
        desc_info = extract_descripciones(
            html,
            nombre_lugar=lugar.get("nombre", ""),
            tipo=lugar.get("tipo"),
        )
        if desc_info.get("descripcion_corta"):
            lugar["descripcion_corta"] = desc_info["descripcion_corta"]
        if desc_info.get("descripcion"):
            lugar["descripcion"] = desc_info["descripcion"]
    except Exception as e:
        safe_print(f"      [WARN] Error extrayendo descripciones: {e}")
        log_error(f"Error descripciones para {lugar.get('nombre')}: {e}")

    try:
        imagenes = extract_imagenes(html, lugar.get("id", ""), wiki_url)
        if imagenes:
            lugar["imagenes"] = imagenes
    except Exception as e:
        safe_print(f"      [WARN] Error extrayendo imágenes: {e}")

    try:
        sitio_web = extract_sitio_web(html)
        if sitio_web:
            lugar["sitio_web"] = sitio_web
    except Exception as e:
        safe_print(f"      [WARN] Error extrayendo sitio web: {e}")

    time.sleep(DELAY_BETWEEN_LLM)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Recuperar URLs de Wikipedia para entidades hijas sin página"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra qué haría, sin modificar el fichero",
    )
    parser.add_argument(
        "--solo-ciudades",
        action="store_true",
        help="Solo procesar ciudad_grande y ciudad_pequena",
    )
    parser.add_argument(
        "--input",
        default=INPUT_FILE,
        help=f"Ruta del JSON de entrada (default: {INPUT_FILE})",
    )
    args = parser.parse_args()

    modo = "[DRY-RUN] " if args.dry_run else ""

    # Cargar datos
    safe_print(f"{modo}Cargando {args.input}...")
    if not os.path.exists(args.input):
        safe_print(f"ERROR: No existe {args.input}")
        return

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    lugares = data.get("lugares", [])
    safe_print(f"Total lugares: {len(lugares)}")

    # Crear lookup de padres
    lugares_dict = {loc["id"]: loc for loc in lugares if "id" in loc}

    # Cargar cachés
    cache_coords = cargar_cache(CACHE_COORDS_FILE)
    cache_search = cargar_cache(CACHE_SEARCH_FILE)
    safe_print(f"Caché coords: {len(cache_coords)} entradas | Caché search: {len(cache_search)} entradas")

    # Filtrar hijas sin URL de Wikipedia
    candidatos = []
    for lugar in lugares:
        if lugar.get("tipo") == "municipio":
            continue
        if lugar.get("url_recuperada"):
            continue
        wiki_url = lugar.get("wikipedia_url", "").strip()
        if wiki_url:
            continue  # Ya tiene URL

        tipo = lugar.get("tipo", "pueblo")
        if args.solo_ciudades and tipo not in TIPOS_CIUDAD:
            continue

        candidatos.append(lugar)

    # Ordenar: ciudades grandes primero, luego pequeñas, luego pueblos
    prioridad = {"ciudad_grande": 0, "ciudad_pequena": 1, "distrito": 2, "barrio": 3, "pueblo": 4}
    candidatos.sort(key=lambda l: (prioridad.get(l.get("tipo", "pueblo"), 5), -(l.get("poblacion") or 0)))

    safe_print(f"\n{modo}Candidatos sin URL de Wikipedia: {len(candidatos)}")
    for tipo in ["ciudad_grande", "ciudad_pequena", "distrito", "barrio", "pueblo"]:
        cnt = sum(1 for c in candidatos if c.get("tipo") == tipo)
        if cnt > 0:
            safe_print(f"  {tipo}: {cnt}")

    safe_print(f"\n{'=' * 60}")
    safe_print(f"  {modo}INICIANDO RECUPERACIÓN DE URLs")
    safe_print(f"{'=' * 60}\n")

    recuperados = 0
    fallidos = 0
    total = len(candidatos)

    try:
        for i, lugar in enumerate(candidatos):
            nombre = lugar.get("nombre", "?")
            provincia = lugar.get("provincia", "")
            comunidad = lugar.get("comunidad", "")
            lat = lugar.get("lat")
            lng = lugar.get("lng")
            tipo = lugar.get("tipo", "pueblo")
            padre_id = lugar.get("padre_id", "")
            padre = lugares_dict.get(padre_id)
            padre_nombre = padre.get("nombre", "su municipio") if padre else "su municipio"

            safe_print(
                f"[{i + 1}/{total}] {nombre} ({tipo}, "
                f"{lugar.get('poblacion', 0)} hab) | {provincia}"
            )

            url, dist = buscar_mejor_url(
                nombre, provincia, comunidad, lat, lng, tipo,
                cache_coords, cache_search,
            )

            if url:
                dist_str = f"{dist:.2f} km" if dist is not None else "N/A"
                safe_print(f"  ✓ Encontrado: {url} (dist: {dist_str})")

                if not args.dry_run:
                    # Comprobar que la URL no sea la misma que la del padre
                    padre_url = padre.get("wikipedia_url", "") if padre else ""
                    if url == padre_url:
                        safe_print(f"  → Misma URL que el padre. Asignando descripción por defecto.")
                        lugar["wikipedia_url"] = url
                        lugar["descripcion_corta"] = (
                            f"Entidad de población que forma parte integrante "
                            f"del municipio de {padre_nombre}."
                        )
                        lugar["descripcion"] = (
                            f"Este lugar forma parte integral del municipio de "
                            f"{padre_nombre}. Al carecer de registros históricos "
                            f"independientes, comparte plenamente el entorno natural, "
                            f"la cultura y la administración del municipio principal."
                        )
                    else:
                        lugar["wikipedia_url"] = url
                        safe_print(f"  → Descargando contenido y generando descripciones...")
                        rellenar_contenido(lugar, url, padre_nombre)

                    lugar["url_recuperada"] = True

                recuperados += 1
            else:
                safe_print(f"  ✗ No encontrado")
                if not args.dry_run:
                    lugar["url_recuperada"] = True  # Marcar como procesado para no reintentar
                fallidos += 1

            # Guardar progreso periódicamente
            if not args.dry_run and (i + 1) % SAVE_EVERY_N == 0:
                _guardar_progreso(data, args.input, cache_coords, cache_search)
                safe_print(f"--- Progreso guardado ({i + 1}/{total}) ---")

    except KeyboardInterrupt:
        safe_print("\nInterrumpido por el usuario.")
    finally:
        if not args.dry_run:
            _guardar_progreso(data, args.input, cache_coords, cache_search)
            safe_print(f"\nProgreso final guardado.")

    safe_print(f"\n{'=' * 60}")
    safe_print(f"  {modo}RESUMEN")
    safe_print(f"{'=' * 60}")
    safe_print(f"  Procesados: {recuperados + fallidos}")
    safe_print(f"  URLs recuperadas: {recuperados}")
    safe_print(f"  Sin resultado: {fallidos}")
    if total > 0:
        safe_print(f"  Tasa de éxito: {recuperados / (recuperados + fallidos) * 100:.1f}%")


def _guardar_progreso(data, input_file, cache_coords, cache_search):
    """Guarda el JSON y las cachés de forma segura (escritura atómica)."""
    # Guardar JSON principal
    tmp = input_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, input_file)

    # Guardar cachés
    guardar_cache(cache_coords, CACHE_COORDS_FILE)
    guardar_cache(cache_search, CACHE_SEARCH_FILE)


if __name__ == "__main__":
    main()

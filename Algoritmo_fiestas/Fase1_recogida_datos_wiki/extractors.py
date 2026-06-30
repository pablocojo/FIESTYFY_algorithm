# extractors.py
"""
Módulo de extracción de lugares españoles desde Wikipedia.
Reescrito para modelo LUGAR-CÉNTRICO (no barrio-céntrico).
Funciones para extraer: municipios, ciudades, distritos, pedanías, info, descripciones, imágenes.
"""

import json
import re
import time
import unicodedata
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import Optional

from config import (
    BASE_WIKI_URL, MAX_SNIPPET_TOKENS, COMMONS_FALLBACK_IMAGE,
    COMMONS_FALLBACK_LOGO, DESC_CORTA_MAX_WORDS, DESC_LARGA_MAX_WORDS
)
from llm_client import call_llm, contar_tokens
from scraper import get_soup, fetch_url, get_wikidata_p18_url
from logger import log_error, safe_print
from place_types import clasificar_por_poblacion


# ============================================================================
# EXTRACCIÓN DE COORDENADAS
# ============================================================================

COMUNIDADES_AUTONOMAS = {
    'Andalucía': ['Almería', 'Cádiz', 'Córdoba', 'Granada', 'Huelva', 'Jaén', 'Málaga', 'Sevilla'],
    'Aragón': ['Huesca', 'Teruel', 'Zaragoza'],
    'Principado de Asturias': ['Asturias'],
    'Islas Baleares': ['Islas Baleares', 'Illes Balears'],
    'Canarias': ['Las Palmas', 'Santa Cruz de Tenerife'],
    'Cantabria': ['Cantabria'],
    'Castilla-La Mancha': ['Albacete', 'Ciudad Real', 'Cuenca', 'Guadalajara', 'Toledo'],
    'Castilla y León': ['Ávila', 'Burgos', 'León', 'Palencia', 'Salamanca', 'Segovia', 'Soria', 'Valladolid', 'Zamora'],
    'Cataluña': ['Barcelona', 'Gerona', 'Girona', 'Lérida', 'Lleida', 'Tarragona'],
    'Comunidad Valenciana': ['Alicante', 'Alacant', 'Castellón', 'Castelló', 'Valencia'],
    'Extremadura': ['Badajoz', 'Cáceres'],
    'Galicia': ['La Coruña', 'A Coruña', 'Lugo', 'Orense', 'Ourense', 'Pontevedra'],
    'Comunidad de Madrid': ['Madrid'],
    'Región de Murcia': ['Murcia'],
    'Comunidad Foral de Navarra': ['Navarra', 'Nafarroa'],
    'País Vasco': ['Álava', 'Araba', 'Guipúzcoa', 'Gipuzkoa', 'Vizcaya', 'Bizkaia'],
    'La Rioja': ['La Rioja'],
    'Ceuta': ['Ceuta'],
    'Melilla': ['Melilla'],
}


PROVINCIA_A_COMUNIDAD = {
    'alava': 'País Vasco',
    'araba': 'País Vasco',
    'albacete': 'Castilla-La Mancha',
    'alicante': 'Comunidad Valenciana',
    'alacant': 'Comunidad Valenciana',
    'almeria': 'Andalucía',
    'asturias': 'Principado de Asturias',
    'avila': 'Castilla y León',
    'badajoz': 'Extremadura',
    'barcelona': 'Cataluña',
    'burgos': 'Castilla y León',
    'caceres': 'Extremadura',
    'cadiz': 'Andalucía',
    'cantabria': 'Cantabria',
    'castellon': 'Comunidad Valenciana',
    'castello': 'Comunidad Valenciana',
    'ciudad real': 'Castilla-La Mancha',
    'cordoba': 'Andalucía',
    'la coruna': 'Galicia',
    'a coruna': 'Galicia',
    'cuenca': 'Castilla-La Mancha',
    'girona': 'Cataluña',
    'gerona': 'Cataluña',
    'granada': 'Andalucía',
    'guadalajara': 'Castilla-La Mancha',
    'gipuzkoa': 'País Vasco',
    'guipuzcoa': 'País Vasco',
    'huelva': 'Andalucía',
    'huesca': 'Aragón',
    'illes balears': 'Islas Baleares',
    'islas baleares': 'Islas Baleares',
    'jaen': 'Andalucía',
    'leon': 'Castilla y León',
    'lleida': 'Cataluña',
    'lerida': 'Cataluña',
    'lugo': 'Galicia',
    'madrid': 'Comunidad de Madrid',
    'malaga': 'Andalucía',
    'murcia': 'Región de Murcia',
    'navarra': 'Comunidad Foral de Navarra',
    'nafarroa': 'Comunidad Foral de Navarra',
    'ourense': 'Galicia',
    'orense': 'Galicia',
    'palencia': 'Castilla y León',
    'las palmas': 'Canarias',
    'pontevedra': 'Galicia',
    'la rioja': 'La Rioja',
    'salamanca': 'Castilla y León',
    'segovia': 'Castilla y León',
    'sevilla': 'Andalucía',
    'soria': 'Castilla y León',
    'tarragona': 'Cataluña',
    'santa cruz de tenerife': 'Canarias',
    'teruel': 'Aragón',
    'toledo': 'Castilla-La Mancha',
    'valencia': 'Comunidad Valenciana',
    'valencia/valencia': 'Comunidad Valenciana',
    'valladolid': 'Castilla y León',
    'bizkaia': 'País Vasco',
    'vizcaya': 'País Vasco',
    'zamora': 'Castilla y León',
    'zaragoza': 'Aragón',
    'ceuta': 'Ceuta',
    'melilla': 'Melilla',
}


def _normalizar_texto(texto: str) -> str:
    """
    Normaliza texto para comparaciones robustas de cabeceras de Wikipedia.
    """
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\[\d+\]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    return texto


def _crear_indice_provincia_comunidad() -> dict[str, str]:
    """
    Crea un indice provincia -> comunidad a partir de COMUNIDADES_AUTONOMAS.
    """
    indice = {}
    for comunidad, provincias in COMUNIDADES_AUTONOMAS.items():
        for provincia in provincias:
            indice[_normalizar_texto(provincia)] = comunidad
    return indice


PROVINCIA_A_COMUNIDAD = _crear_indice_provincia_comunidad()


def _limpiar_valor_infobox(texto: str) -> str:
    """
    Limpia referencias y espacios sobrantes de valores extraidos de infobox.
    """
    texto = re.sub(r"\[\d+\]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def inferir_comunidad_por_provincia(provincia: str | None) -> str | None:
    """
    Devuelve la comunidad autonoma a partir del nombre de provincia.
    """
    if not provincia:
        return None
    
    provincia_limpia = _normalizar_texto(provincia)
    provincia_limpia = re.sub(r"\b(provincia de|provincia|isla de|islas de)\b", "", provincia_limpia)
    provincia_limpia = re.sub(r"\s+", " ", provincia_limpia).strip()
    
    if provincia_limpia in PROVINCIA_A_COMUNIDAD:
        return PROVINCIA_A_COMUNIDAD[provincia_limpia]
    
    for nombre_provincia, comunidad in PROVINCIA_A_COMUNIDAD.items():
        if nombre_provincia in provincia_limpia:
            return comunidad
    
    return None


def extract_coordinates_from_html(html: str) -> tuple[Optional[float], Optional[float]]:
    """
    Extrae latitud/longitud de Wikipedia (geo tag o texto formato DMS).
    
    Returns:
        (lat, lng) como floats o (None, None) si no encuentra.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Intenta geo tag
    geo_tag = soup.find("span", class_="geo")
    if geo_tag:
        try:
            coords_text = geo_tag.get_text(strip=True)
            # Formato: "lat;lng" o "lat; lng"
            parts = coords_text.split(';')
            if len(parts) == 2:
                lat = float(parts[0].strip())
                lng = float(parts[1].strip())
                return lat, lng
        except ValueError:
            pass
    
    # Intenta buscar patrón DMS (40°28′35″N 3°39′29″O)
    text = soup.get_text()
    pattern = r"(\d{1,2})°(\d{1,2})′(\d{1,2})″([NS])\s+(\d{1,2})°(\d{1,2})′(\d{1,2})″([EO])"
    match = re.search(pattern, text)
    
    if match:
        try:
            deg_n, min_n, sec_n, dir_n, deg_e, min_e, sec_e, dir_e = match.groups()
            lat = int(deg_n) + int(min_n) / 60 + int(sec_n) / 3600
            if dir_n == 'S':
                lat = -lat
            lng = int(deg_e) + int(min_e) / 60 + int(sec_e) / 3600
            if dir_e == 'O':
                lng = -lng
            return lat, lng
        except ValueError:
            pass
    
    return None, None


# ============================================================================
# EXTRACCIÓN DE LUGARES BASE (MUNICIPIOS/CIUDADES) - JERÁRQUICO
# ============================================================================

def extract_provincias(html: str) -> list[dict]:
    """
    Extrae lista de páginas "Anexo:..." desde "Municipios de España por provincia".
    Solo extrae PÁGINAS (no categorías) que contengan "Anexo".
    
    Returns:
        Lista de dicts: {nombre_provincia, page_url}
    """
    soup = BeautifulSoup(html, 'html.parser')
    provincias = []
    
    for a in soup.select('.mw-category-group a'):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        
        # Filtrar: SOLO páginas (no categorías) con "Anexo"
        if 'Categor%C3%ADa' not in href and 'Anexo' in text:
            # Extraer nombre de provincia (ej: "Anexo:Municipios de Córdoba" -> "Córdoba")
            nombre_prov = text.replace('Anexo:', '').replace('Municipios de ', '').replace('Municipios del ', '').strip()
            provincias.append({
                'nombre_provincia': nombre_prov,
                'page_url': urljoin(BASE_WIKI_URL, href)
            })
    
    return provincias


def extract_municipios_from_anexo(html: str) -> list[dict]:
    """
    Extrae municipios desde una página "Anexo:Municipios de [Provincia]".
    Busca tabla y extrae enlaces de columna con título "nombre", "nombre en castellano" o "municipio".
    
    Returns:
        Lista de dicts: {nombre, article_url}
    """
    soup = BeautifulSoup(html, 'html.parser')
    municipios = []
    
    # Buscar todas las tablas
    for tabla in soup.find_all('table'):
        # Buscar filas de encabezado
        header_row = tabla.find('tr')
        if not header_row:
            continue
        
        headers = [_normalizar_texto(th.get_text(' ', strip=True)) for th in header_row.find_all(['th', 'td'])]
        
        # Verificar si hay columna "nombre", "nombre en castellano" o "municipio"
        nombre_col = None
        for idx, header in enumerate(headers):
            if (
                header in ('nombre', 'municipio', 'nombre en castellano', 'nombre castellano')
                or header.startswith('nombre en espa')
            ):
                nombre_col = idx
                break
        
        # Si encontró columna de nombre, extraer municipios
        if nombre_col is not None:
            for fila in tabla.find_all('tr')[1:]:  # Saltar encabezado
                celdas = fila.find_all(['td', 'th'])
                if nombre_col < len(celdas):
                    celda = celdas[nombre_col]
                    # Buscar enlace en la celda
                    enlace = celda.find('a')
                    if enlace:
                        href = enlace.get('href', '')
                        texto = enlace.get_text(strip=True)
                        if (
                            href.startswith('/wiki/')
                            or href.startswith('//es.wikipedia.org/wiki/')
                            or href.startswith('https://es.wikipedia.org/wiki/')
                        ) and 'Categor%C3%ADa' not in href:
                            municipios.append({
                                'nombre': texto,
                                'article_url': urljoin(BASE_WIKI_URL, href)
                            })
    
    return municipios


def extract_lugares_base(html: str) -> list[dict]:
    """
    Extrae lista completa de municipios navegando por Anexos de provincias.
    
    Flujo:
    1. Extrae páginas "Anexo:..." desde categoría raíz
    2. Para cada anexo de provincia, extrae municipios desde tabla
    
    Returns:
        Lista de dicts: {nombre, article_url}
    """
    safe_print("   (Extrayendo páginas Anexo de provincias...)")
    
    provincias = extract_provincias(html)
    if not provincias:
        log_error("No se encontraron Anexos de provincias en la categoría raíz")
        return []
    
    safe_print(f"   -> {len(provincias)} Anexos encontrados")
    
    todos_municipios = []
    
    for prov in provincias:
        nombre_prov = prov.get('nombre_provincia', '?')
        page_url = prov.get('page_url', '')
        
        if not page_url:
            log_error(f"Sin URL para Anexo de {nombre_prov}")
            continue
        
        # Descargar página Anexo
        html_anexo = fetch_url(page_url)
        if not html_anexo:
            log_error(f"Error descargando Anexo de {nombre_prov}")
            continue
        
        # Extraer municipios de la tabla
        municipios = extract_municipios_from_anexo(html_anexo)
        todos_municipios.extend(municipios)
        
        safe_print(f"     - {nombre_prov}: {len(municipios)} municipios")
        time.sleep(0.5)
    
    return todos_municipios


# ============================================================================
# EXTRACCIÓN DE ESTRUCTURA MUNICIPAL (DISTRITOS Y PEDANÍAS)
# ============================================================================

def extract_estructura_ciudad(html: str, ciudad_id: str) -> dict:
    """
    Para ciudades grandes, extrae distritos y pedanías subordinadas.
    Busca categorías como "Barrios del distrito X" o "Distritos de [ciudad]".
    
    Returns:
        {
            'distritos': [{'nombre': str, 'article_url': str}, ...],
            'pedanias': [{'nombre': str, 'article_url': str, 'padre_id': str}, ...]
        }
    """
    soup = get_soup(html)
    distritos = []
    pedanias = []
    
    # Buscar enlaces a categorías de distritos
    for a in soup.select('.mw-category-group a'):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        
        # Distritos: enlaces tipo "Barrios del distrito X" o "Distrito X"
        if ('Barrios del distrito' in text or 
            'Barrios_del_distrito' in href or
            ('Distrito' in text and href.startswith('/wiki/'))):
            
            # Extraer nombre del distrito
            distrito_nombre = re.sub(r'^[Bb]arrios del distrito |^[Dd]istrito ', '', text).strip()
            distritos.append({
                'nombre': distrito_nombre,
                'article_url': urljoin(BASE_WIKI_URL, href),
                'categoria': True if 'Categor%C3%ADa' in href else False
            })
        
        # Pedanías: enlaces con "pedanía" en el nombre
        elif 'pedan' in text.lower():
            pedania_nombre = text.replace('Pedanía de', '').replace('Pedan\u00eda de', '').strip()
            pedanias.append({
                'nombre': pedania_nombre,
                'article_url': urljoin(BASE_WIKI_URL, href),
                'padre_id': ciudad_id
            })
    
    return {'distritos': distritos, 'pedanias': pedanias}


# ============================================================================
# EXTRACCIÓN DE INFORMACIÓN DE LUGAR (POBLACIÓN, PROVINCIA, COMUNIDAD, COORDS)
# ============================================================================

def extract_lugar_info(html: str, nombre_lugar: str) -> dict:
    """
    Extrae información de un lugar desde su artículo Wikipedia:
    - población, provincia, comunidad autónoma
    - coordenadas (lat/lng)
    - Busca en infobox y párrafos.
    
    Returns:
        {
            'poblacion': int or None,
            'provincia': str or None,
            'comunidad': str or None,
            'lat': float or None,
            'lng': float or None,
            'error': str or None (si hubo problema)
        }
    """
    if not html.strip():
        return {'error': 'html_vacio', 'poblacion': None, 'provincia': None, 'comunidad': None, 'lat': None, 'lng': None}
    
    result = {
        'poblacion': None,
        'provincia': None,
        'comunidad': None,
        'lat': None,
        'lng': None,
        'error': None
    }
    
    # Extraer coordenadas
    lat, lng = extract_coordinates_from_html(html)
    result['lat'] = lat
    result['lng'] = lng
    
    # Parsear infobox
    soup = BeautifulSoup(html, 'html.parser')
    infobox = soup.find('table', class_='infobox')
    
    if infobox:
        # Buscar población
        for row in infobox.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) >= 2:
                header = _normalizar_texto(cells[0].get_text(' ', strip=True))
                value = _limpiar_valor_infobox(cells[1].get_text(' ', strip=True))
                
                if 'poblaci' in header or 'habitantes' in header:
                    # Limpiar: "123.456 (2023)" -> 123456
                    poblacion_str = re.sub(r'[^\d]', '', value.split('(')[0])
                    try:
                        result['poblacion'] = int(poblacion_str)
                    except ValueError:
                        pass
                
                elif 'provincia' in header:
                    result['provincia'] = value
                
                elif (
                    'comunidad' in header
                    or 'comunitat' in header
                    or 'autonoma' in header
                    or 'region' in header
                ):
                    result['comunidad'] = value
    
    comunidad_por_provincia = inferir_comunidad_por_provincia(result['provincia'])
    if comunidad_por_provincia:
        result['comunidad'] = comunidad_por_provincia
    
    # Si no encontró en infobox, buscar en párrafos iniciales via LLM
    if not result['poblacion'] or not result['provincia'] or not result['comunidad']:
        paras = soup.find('div', id='mw-content-text')
        if paras:
            first_paras = ' '.join(
                p.get_text(' ', strip=True) 
                for p in paras.find_all('p', limit=3)
                if p.get_text(strip=True)
            )
            
            if contar_tokens(first_paras) > MAX_SNIPPET_TOKENS:
                words = first_paras.split()
                first_paras = ' '.join(words[:MAX_SNIPPET_TOKENS // 2])
            
            system_prompt = (
                "Extrae del texto: población (número), provincia y comunidad autónoma. "
                "RESPONDE SOLO JSON: {\"poblacion\": int or null, \"provincia\": str or null, \"comunidad\": str or null}"
            )
            
            resp = call_llm(
                system_prompt,
                first_paras,
                context_info={'stage': 'extract_lugar_info', 'lugar': nombre_lugar},
            )
            
            if resp and resp.strip():
                try:
                    llm_data = json.loads(resp)
                    if llm_data.get('poblacion') and not result['poblacion']:
                        result['poblacion'] = llm_data['poblacion']
                    if llm_data.get('provincia') and not result['provincia']:
                        result['provincia'] = llm_data['provincia']
                    if llm_data.get('comunidad') and not result['comunidad']:
                        result['comunidad'] = llm_data['comunidad']
                except json.JSONDecodeError:
                    pass
    
    comunidad_por_provincia = inferir_comunidad_por_provincia(result['provincia'])
    if comunidad_por_provincia:
        result['comunidad'] = comunidad_por_provincia
    
    return result


# ============================================================================
# CLASIFICACION DE MUNICIPIO COMPUESTO (LLM como unico decisor)
# ============================================================================

def _recoger_senales_compuesto(html: str, nombre: str) -> dict:
    """
    Extrae senales estructurales del HTML de Wikipedia SIN tomar decision.

    Recopila indicios que luego se pasan como contexto al LLM para que
    sea el quien decida si el municipio es compuesto.

    Returns:
        Dict con senales booleanas y texto relevante.
    """
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.find('div', id='mw-content-text')
    if not content:
        content = soup.find('div', class_='mw-parser-output')
    if not content:
        content = soup.body
    if not content:
        content = soup

    senales = {
        'se_autodefine_lugar_fisico': False,
        'capital_diferente_al_nombre': False,
        'tiene_seccion_localidades': False,
        'tiene_seccion_entidades_poblacion': False,
        'tiene_seccion_parroquias': False,
        'tiene_seccion_concejos': False,
        'tiene_seccion_pedanias': False,
        'tiene_seccion_barrios': False,
        'tiene_seccion_distritos': False,
        'frase_agrupacion_nucleos': False,
        'tipo_entidad_infobox': '',
        'texto_contexto': '',
        'categorias_relevantes': [],
    }

    if not content:
        return senales

    # --- Senales de los parrafos iniciales ---
    paras = [
        p.get_text(' ', strip=True)
        for p in content.find_all('p', limit=5)
        if p.get_text(strip=True)
    ]
    primeros_parrafos = ' '.join(paras)
    primeros_parrafos_norm = _normalizar_texto(primeros_parrafos)

    # Senal 1: el articulo define al lugar como un sitio fisico
    patron_lugar_fisico = re.compile(
        r'\bes\s+un(?:a)?\s+(?:'
        r'ciudad|villa|pueblo|localidad|aldea|'
        r'municipio\s+y\s+(?:villa|pueblo|ciudad|localidad)|'
        r'(?:villa|pueblo|ciudad|localidad)\s+y\s+municipio'
        r')\b',
        re.IGNORECASE
    )
    senales['se_autodefine_lugar_fisico'] = bool(patron_lugar_fisico.search(primeros_parrafos_norm))

    # Senal 2: la capital del municipio tiene nombre diferente
    nombre_norm = _normalizar_texto(nombre)
    match_cap = re.search(
        r'\bla\s+capital\s+(?:del\s+municipio|municipal)\s+es\s+([^,\.\(]+)',
        primeros_parrafos_norm
    )
    if match_cap:
        capital_extraida = match_cap.group(1).strip()
        if nombre_norm not in capital_extraida:
            senales['capital_diferente_al_nombre'] = True

    # Senal 3: frase explicita de agrupacion
    patron_agrupacion = re.compile(
        r'\b(?:municipio|concejo)\b.*\b(?:formado|compuesto|integrado)\s+por\b|'
        r'\bcomprende\s+las\s+(?:localidades|entidades|parroquias|concejos|pedanias|pedanías)\s+de\b',
        re.IGNORECASE
    )
    senales['frase_agrupacion_nucleos'] = bool(patron_agrupacion.search(primeros_parrafos_norm))

    # --- Senales del infobox ---
    infobox = soup.find('table', class_='infobox')
    if infobox:
        infobox_text = _normalizar_texto(infobox.get_text(' ', strip=True))
        for etiqueta in ('concejo', 'parroquia', 'comarca'):
            if etiqueta in infobox_text:
                senales['tipo_entidad_infobox'] = etiqueta
                break

    # --- Senales de secciones (via headings del propio HTML) ---
    for heading in content.find_all(['h2', 'h3', 'h4']):
        line = _normalizar_texto(heading.get_text(' ', strip=True))

        if 'localidades' in line:
            senales['tiene_seccion_localidades'] = True
        if any(t in line for t in ('entidades de poblaci', 'entidades singulares',
                                    'nucleos de poblaci', 'entidades de poblacio',
                                    'nucleos de poblacio')):
            senales['tiene_seccion_entidades_poblacion'] = True
        if 'parroquias' in line:
            senales['tiene_seccion_parroquias'] = True
        if 'concejos' in line:
            senales['tiene_seccion_concejos'] = True
        if 'pedani' in line:
            senales['tiene_seccion_pedanias'] = True
        if 'barrios' in line:
            senales['tiene_seccion_barrios'] = True
        if 'distritos' in line:
            senales['tiene_seccion_distritos'] = True

    # --- Categorias ---
    cat_links = soup.find('div', id='catlinks')
    if not cat_links:
        # En el HTML de la API, a veces las categorías vienen como enlaces normales
        cat_links = content
        
    palabras_clave_cats = ('localidad', 'localidades', 'pedania', 'pedanias', 'concejo', 'concejos', 'entidad', 'entidades', 'aldea', 'aldeas')
    if cat_links:
        for a in cat_links.find_all('a', href=True):
            texto = a.get_text(' ', strip=True)
            texto_norm = _normalizar_texto(texto)
            if 'categor' in a['href'].lower() and any(p in texto_norm for p in palabras_clave_cats):
                if texto not in senales['categorias_relevantes'] and 'oculta' not in texto_norm:
                    senales['categorias_relevantes'].append(texto)

    # --- Texto de contexto para el LLM ---
    bloques = []

    if infobox:
        filas_infobox = []
        for row in infobox.find_all('tr'):
            texto = row.get_text(' ', strip=True)
            if texto:
                filas_infobox.append(texto)
        if filas_infobox:
            bloques.append('INFOBOX: ' + ' | '.join(filas_infobox[:40]))

    if paras:
        bloques.append('PARRAFOS INICIALES: ' + ' '.join(paras))

    palabras_clave = (
        'nucleo', 'nucleos', 'localidad', 'localidades', 'pedania', 'pedanias',
        'entidad', 'entidades', 'parroquia', 'parroquias', 'concejo', 'concejos',
        'aldea', 'aldeas', 'formado por', 'compuesto por', 'integrado por',
        'capitalidad', 'capital', 'ayuntamiento', 'sede'
    )
    listas_relevantes = []
    for li in content.find_all('li', limit=120):
        texto = li.get_text(' ', strip=True)
        texto_norm = _normalizar_texto(texto)
        if texto and any(palabra in texto_norm for palabra in palabras_clave):
            listas_relevantes.append(texto)
        if len(listas_relevantes) >= 30:
            break
    if listas_relevantes:
        bloques.append('LISTAS RELEVANTES: ' + ' | '.join(listas_relevantes))

    contexto = '\n\n'.join(bloques)
    contexto = re.sub(r'\[\d+\]', '', contexto)
    contexto = re.sub(r'\s+', ' ', contexto).strip()

    if contar_tokens(contexto) > MAX_SNIPPET_TOKENS:
        words = contexto.split()
        contexto = ' '.join(words[:MAX_SNIPPET_TOKENS])

    senales['texto_contexto'] = contexto
    return senales




def _fallback_descripciones_desde_wikipedia(html: str) -> dict:
    """
    Genera descripciones recortando el texto inicial de Wikipedia.
    Se usa solo como respaldo si el LLM no responde.
    """
    if not html.strip():
        return {'descripcion_corta': '', 'descripcion': ''}
    
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.find('div', id='mw-content-text')
    
    if not content:
        return {'descripcion_corta': '', 'descripcion': ''}
    
    # Obtener párrafos iniciales
    paras = [p.get_text(' ', strip=True) for p in content.find_all('p', limit=5) if p.get_text(strip=True)]
    
    if not paras:
        return {'descripcion_corta': '', 'descripcion': ''}
    
    # Crear descripción larga concatenando párrafos
    full_text = ' '.join(paras)
    
    # Limpiar: remover referencias [1][2], etc.
    full_text = re.sub(r'\[\d+\]', '', full_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()
    
    # Truncar a longitud máxima de descripción larga
    words = full_text.split()
    desc_larga = ' '.join(words[:DESC_LARGA_MAX_WORDS])
    if len(words) > DESC_LARGA_MAX_WORDS:
        desc_larga += '.'
    
    # Descripción corta: primeras 12-15 palabras
    desc_corta = ' '.join(words[:DESC_CORTA_MAX_WORDS])
    if len(words) > DESC_CORTA_MAX_WORDS:
        desc_corta += '.'
    
    return {
        'descripcion_corta': desc_corta,
        'descripcion': desc_larga
    }


def _extraer_texto_wikipedia_para_descripcion(html: str) -> str:
    """
    Extrae un snippet informativo del articulo para pasarlo al LLM.
    """
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.find('div', id='mw-content-text')

    if not content:
        return ''

    bloques = []
    for p in content.find_all('p', limit=8):
        texto = p.get_text(' ', strip=True)
        if texto:
            bloques.append(texto)

    texto_wiki = ' '.join(bloques)
    texto_wiki = re.sub(r'\[\d+\]', '', texto_wiki)
    texto_wiki = re.sub(r'\s+', ' ', texto_wiki).strip()

    if contar_tokens(texto_wiki) > MAX_SNIPPET_TOKENS:
        words = texto_wiki.split()
        texto_wiki = ' '.join(words[:MAX_SNIPPET_TOKENS])

    return texto_wiki


def extract_descripciones(html: str, nombre_lugar: str = "", tipo: str = None) -> dict:
    """
    Crea descripciones corta y larga usando el LLM con informacion de Wikipedia.
    """
    if not html.strip():
        return {'descripcion_corta': '', 'descripcion': ''}

    texto_wiki = _extraer_texto_wikipedia_para_descripcion(html)
    if not texto_wiki:
        return {'descripcion_corta': '', 'descripcion': ''}

    system_prompt = (
        "Eres un redactor experto para una app de turismo en España (Fiestyfy). "
        "Tu tarea es crear una descripción de este lugar basándote en el texto proporcionado. "
        "REGLAS OBLIGATORIAS:\n"
        "1. RESPONDE ÚNICAMENTE CON UN JSON VÁLIDO. DEBES ASEGURARTE DE CERRAR LA ÚLTIMA LLAVE '}' DEL JSON.\n"
        "2. NO escribas NINGÚN texto fuera del JSON.\n"
        "3. NO menciones la población, ni el censo, ni la cantidad de habitantes. Enfócate en geografía, historia, cultura, fiestas o monumentos.\n"
        "4. Idioma: Español castellano correcto (usa tildes y eñes correctamente).\n"
        "5. NO incluyas ninguna coma al final del último elemento del JSON.\n"
    )
    user_prompt = (
        f"Lugar: {nombre_lugar or 'desconocido'}\n"
        f"Tipo: {tipo or 'desconocido'}\n\n"
        "FORMATO REQUERIDO ESTRICTO:\n"
        "{\n"
        f"  \"descripcion_corta\": \"Una sola frase de entre 12 y {DESC_CORTA_MAX_WORDS} palabras resumiendo qué es y dónde está el lugar.\",\n"
        f"  \"descripcion\": \"Texto fluido de entre 50 y {DESC_LARGA_MAX_WORDS} palabras. SIN MENCIONAR HABITANTES NI POBLACIÓN. Habla del entorno natural, cultura o historia.\"\n"
        "}\n\n"
        f"Texto fuente:\n{texto_wiki}"
    )

    resp = call_llm(
        system_prompt,
        user_prompt,
        context_info={'stage': 'extract_descripciones', 'lugar': nombre_lugar},
    )

    if resp and resp.strip():
        try:
            resp_clean = resp.strip()
            # Heurística para JSON truncado
            if not resp_clean.endswith("}"):
                if resp_clean.endswith("\""):
                    resp_clean += "\n}"
                elif resp_clean.endswith("."):
                    resp_clean += "\"\n}"
                else:
                    resp_clean += ".\"\n}"
                    
            # Limpiar comillas markdown
            resp_clean = re.sub(r'^```json\s*', '', resp_clean)
            resp_clean = re.sub(r'\s*```$', '', resp_clean)
            
            data = json.loads(resp_clean)
            desc_corta = str(data.get('descripcion_corta') or '').strip()
            desc_larga = str(data.get('descripcion') or '').strip()
            if desc_corta and desc_larga:
                return {
                    'descripcion_corta': desc_corta,
                    'descripcion': desc_larga
                }
        except (json.JSONDecodeError, TypeError):
            log_error(
                "Respuesta LLM invalida generando descripciones",
                context={'stage': 'extract_descripciones', 'lugar': nombre_lugar, 'response': resp[:500]}
            )

    log_error(
        "LLM sin respuesta valida; usando fallback local de descripciones",
        context={'stage': 'extract_descripciones', 'lugar': nombre_lugar}
    )
    return _fallback_descripciones_desde_wikipedia(html)


# ============================================================================
# EXTRACCIÓN DE IMÁGENES
# ============================================================================

def extract_imagenes(html: str, lugar_id: str, wikipedia_url: str = None) -> dict:
    """
    Extrae URLs de banner y logo para un lugar.
    Busca preferentemente el escudo (o emblema heráldico) sobre la bandera para el logo.
    
    Returns:
        {'banner': str, 'logo': str}
    """
    if not html.strip():
        return {
            'banner': COMMONS_FALLBACK_IMAGE.format(id=lugar_id),
            'logo': COMMONS_FALLBACK_LOGO.format(id=lugar_id)
        }
    
    soup = BeautifulSoup(html, 'html.parser')
    banner = get_wikidata_p18_url(wikipedia_url) if wikipedia_url else None
    logo = None
    
    infobox = soup.find('table', class_='infobox')
    if infobox:
        best_logo_img = None
        best_logo_score = -9999
        
        # Analizar todas las imágenes en la infobox
        for img in infobox.find_all('img'):
            src = img.get('src', '')
            if not src:
                continue
                
            alt = img.get('alt', '').lower()
            src_lower = src.lower()
            
            # Buscar también en atributos title del tag a padre (a menudo contiene el nombre del archivo)
            parent_a = img.find_parent('a')
            parent_title = parent_a.get('title', '').lower() if parent_a else ''
            
            # Texto circundante (ej. enlaces abajo de la imagen que digan "Escudo" o "Bandera")
            parent_td = img.find_parent('td')
            td_text = parent_td.get_text(' ', strip=True).lower() if parent_td else ''
            
            score = 0
            
            # Términos que indican escudo (alta prioridad)
            escudo_keywords = ['escudo', 'escut', 'heraldica', 'heráldica', 'coa', 'coat of arms', 'shield']
            # Términos que indican bandera (rechazo total)
            bandera_keywords = ['bandera', 'flag', 'bandeira']
            
            es_bandera = False
            
            if any(k in alt for k in escudo_keywords) or any(k in src_lower for k in escudo_keywords) or any(k in parent_title for k in escudo_keywords):
                score += 100
            if any(k in td_text for k in ['escudo', 'escut', 'heráldica', 'heraldica']):
                score += 50
                
            if any(k in alt for k in bandera_keywords) or any(k in src_lower for k in bandera_keywords) or any(k in parent_title for k in bandera_keywords):
                es_bandera = True
            if any(k in td_text for k in ['bandera', 'bandeira']):
                es_bandera = True
                
            # Si es claramente una bandera, la ignoramos por completo
            if es_bandera:
                continue
                
            if score > best_logo_score:
                best_logo_score = score
                best_logo_img = img
        
        if best_logo_img:
            src = best_logo_img.get('src', '')
            if src.startswith('//'):
                logo = 'https:' + src
            else:
                logo = src
                
    # Si no se encontró logo a través de la infobox, fallback a la primera imagen de la infobox
    if not logo and infobox:
        img = infobox.find('img')
        if img:
            src = img.get('src', '')
            if src.startswith('//'):
                logo = 'https:' + src
            else:
                logo = src
                
    banner = banner or COMMONS_FALLBACK_IMAGE.format(id=lugar_id)
    logo = logo or COMMONS_FALLBACK_LOGO.format(id=lugar_id)
    
    return {'banner': banner, 'logo': logo}


def extract_sitio_web(html: str) -> str:
    """
    Extrae el sitio web oficial desde la infobox de Wikipedia, si existe.
    """
    if not html.strip():
        return ''

    soup = BeautifulSoup(html, 'html.parser')
    infobox = soup.find('table', class_='infobox')
    if not infobox:
        return ''

    cabeceras_web = (
        'sitio web',
        'pagina web',
        'pag web',
        'web oficial',
        'sede electronica',
    )

    for row in infobox.find_all('tr'):
        cells = row.find_all(['th', 'td'])
        if len(cells) < 2:
            continue

        header = _normalizar_texto(cells[0].get_text(' ', strip=True))
        if not any(cabecera in header for cabecera in cabeceras_web):
            continue

        for enlace in cells[1].find_all('a', href=True):
            href = enlace.get('href', '').strip()
            if href.startswith('//'):
                return 'https:' + href
            if href.startswith(('http://', 'https://')):
                return href

        texto = _limpiar_valor_infobox(cells[1].get_text(' ', strip=True))
        match = re.search(r'https?://[^\s]+', texto)
        if match:
            return match.group(0).rstrip('.,;)')

    return ''


# ============================================================================
# CONSTRUCCIÓN DE OBJETO LUGAR COMPLETO
# ============================================================================

def construir_lugar(
    nombre: str,
    html: str,
    tipo: str = None,
    padre_id: str = None,
    padre_info: dict = None,
    wikipedia_url: str = None
) -> dict:
    """
    Construye un objeto 'lugar' completo extrayendo todos sus campos.
    
    Args:
        nombre: Nombre del lugar
        html: HTML descargado del artículo
        tipo: Tipo de lugar (si no se pasa, se infiere por población)
        padre_id: ID del lugar padre (para distritos/pedanías)
        padre_info: Dict del padre para heredar provincia/comunidad
    
    Returns:
        Dict con estructura de 'lugar' listo para JSON
    """
    # Generar ID sin prefijo primero
    lugar_id_base = nombre.lower().replace(' ', '-').replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    lugar_id_base = re.sub(r'[^a-z0-9\-]', '', lugar_id_base)
    
    # Si tiene padre, prefija el ID
    if padre_id:
        lugar_id = f"{padre_id}-{lugar_id_base}"
    else:
        lugar_id = lugar_id_base
    
    # Extraer información
    info = extract_lugar_info(html, nombre)
    
    # Heredar provincia/comunidad del padre si no se encontraron
    if padre_info:
        if not info['provincia']:
            info['provincia'] = padre_info.get('provincia')
        if not info['comunidad']:
            info['comunidad'] = padre_info.get('comunidad')
    
    # Inferir tipo si no se pasó
    if not tipo:
        tipo = clasificar_por_poblacion(info['poblacion']) or 'pueblo'
    descripciones = extract_descripciones(html, nombre_lugar=nombre, tipo=tipo)
    imagenes = extract_imagenes(html, lugar_id, wikipedia_url)
    sitio_web = extract_sitio_web(html)
    
    # Construir objeto
    lugar = {
        'id': lugar_id,
        'tipo': tipo,
        'nombre': nombre,
        'provincia': info['provincia'] or '',
        'comunidad': info['comunidad'] or '',
        'poblacion': info['poblacion'] or 0,
        'lat': info['lat'] or 0.0,
        'lng': info['lng'] or 0.0,
        'descripcion_corta': descripciones['descripcion_corta'],
        'descripcion': descripciones['descripcion'],
        'imagenes': imagenes,
        'sitio_web': sitio_web,
        'wikipedia_url': wikipedia_url or ''
    }
    
    # Agregar padre_id si es aplicable
    if padre_id:
        lugar['padre_id'] = padre_id
    
    return lugar

# datos_ine.py
"""
Módulo para cargar y consultar las tablas del INE (Instituto Nacional de Estadística).

Tablas:
  - pobmun25.xlsx: Municipios con población actualizada (padrón 2025).
  - nomdef2025.xlsx: Unidades poblacionales (localidades/núcleos) por municipio.

Uso típico:
    from datos_ine import cargar_datos_ine, buscar_municipio_ine

    datos_ine = cargar_datos_ine()  # carga una sola vez
    info = buscar_municipio_ine("Amurrio", "Álava", datos_ine)
"""

import os
import re
import unicodedata

from logger import safe_print


# ============================================================================
# RUTAS DE LOS FICHEROS
# ============================================================================
_DATOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_municipios")
_POBMUN_FILE = os.path.join(_DATOS_DIR, "pobmun25.xlsx")
_NOMDEF_FILE = os.path.join(_DATOS_DIR, "nomdef2025.xlsx")


# ============================================================================
# NORMALIZACIÓN DE TEXTO
# ============================================================================

def _normalizar(texto: str) -> str:
    """
    Normaliza un texto para comparación: quita tildes, pasa a minúsculas,
    elimina caracteres no alfanuméricos (excepto espacios y guiones).
    """
    if not texto:
        return ""
    # Quitar tildes
    nfkd = unicodedata.normalize('NFKD', texto)
    sin_tildes = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Minúsculas
    sin_tildes = sin_tildes.lower().strip()
    # Normalizar espacios
    sin_tildes = re.sub(r'\s+', ' ', sin_tildes)
    return sin_tildes


def _normalizar_nombre_provincia(provincia: str) -> str:
    """
    Normaliza nombre de provincia para matching.
    Gestiona casos como 'Araba/Álava' → 'araba/alava',
    'Illes Balears' vs 'Islas Baleares', etc.
    """
    return _normalizar(provincia)

def limpiar_nombre_ine(nombre_ine: str) -> list[str]:
    """
    Recibe un nombre bruto del INE y devuelve una lista de posibles nombres limpios.
    Ej: "RETES DE TUDELA/ERRETES TUDELA" -> ["RETES DE TUDELA", "ERRETES TUDELA"]
    Ej: "CAMPILLAR (EL)" -> ["EL CAMPILLAR"]
    Ej: "ETXAGUEN (ZIGOITIA)" -> ["ETXAGUEN"]
    """
    partes = [p.strip() for p in nombre_ine.split('/')]
    resultados = []
    for p in partes:
        # Detectar artículo pospuesto: "Nombre (El)"
        match_art = re.search(r'\(\s*(EL|LA|LOS|LAS|L\'|ES|SA|SES)\s*\)$', p, re.IGNORECASE)
        if match_art:
            art = match_art.group(1).strip()
            nombre_base = p[:match_art.start()].strip()
            if art.upper() == "L'":
                resultados.append(f"{art}{nombre_base}")
            else:
                resultados.append(f"{art} {nombre_base}")
            continue
            
        # Detectar paréntesis de aclaración
        p_sin_parentesis = re.sub(r'\(.*?\)', '', p).strip()
        if p_sin_parentesis:
            resultados.append(p_sin_parentesis)
            if p_sin_parentesis != p:
                resultados.append(p)
            
    return resultados


# ============================================================================
# CARGA DE TABLAS
# ============================================================================

def cargar_datos_ine() -> dict:
    """
    Carga ambas tablas del INE en memoria usando NGMEP (Mock legacy).
    """
    safe_print("Cargando tablas INE desde CSV NGMEP...")
    muni_ngmep = cargar_municipios_ngmep()
    enti_ngmep = cargar_entidades_ngmep()
    provs_ngmep = cargar_provincias_ngmep()

    municipios = {}
    localidades = {}
    indice_nombre = {}

    for cod_ine, data in muni_ngmep.items():
        if len(cod_ine) >= 5:
            cpro = cod_ine[:2]
            cmun = cod_ine[2:5]
            clave = (cpro, cmun)
            
            prov_data = provs_ngmep.get(cpro, {})
            provincia_orig = prov_data.get('provincia', '')

            municipios[clave] = {
                'nombre': data['nombre'],
                'poblacion': data['poblacion'],
                'provincia': provincia_orig,
            }

            nombre_norm = _normalizar(data['nombre'])
            if nombre_norm not in indice_nombre:
                indice_nombre[nombre_norm] = []
            indice_nombre[nombre_norm].append((cpro, cmun, provincia_orig))

    for inemuni, entidades in enti_ngmep.items():
        if len(inemuni) >= 5:
            cpro = inemuni[:2]
            cmun = inemuni[2:5]
            clave = (cpro, cmun)
            
            localidades[clave] = []
            for ent in entidades:
                localidades[clave].append({
                    'nombre': ent['nombre'],
                    'poblacion': ent['poblacion']
                })

    total_locs = sum(len(v) for v in localidades.values())
    safe_print(f"  OK: {total_locs} localidades en {len(localidades)} municipios.")
    safe_print("Tablas INE cargadas correctamente (NGMEP).\n")

    return {
        'municipios': municipios,
        'localidades': localidades,
        'indice_nombre': indice_nombre,
    }



# ============================================================================
# BÚSQUEDA
# ============================================================================

def _consultar_nombre_ine_llm(nombre_wiki: str, provincia: str, html_municipio: str, candidatos_ine: list[str] = None) -> str | None:
    """Extrae el nombre oficial del INE del primer parrafo de Wikipedia usando el LLM.
    
    Si se proporciona candidatos_ine, le pide al LLM que elija de esa lista.
    """
    try:
        from scraper import get_soup
        import re
        
        soup = get_soup(html_municipio)
        parrafos = [p.get_text(strip=True) for p in soup.find_all('p') if p.get_text(strip=True)]
        texto_intro = " ".join(parrafos[:3])
        
        if not texto_intro:
            return None
            
        from llm_client import call_llm
        
        if candidatos_ine:
            lista_str = "\n".join(f"- {c}" for c in candidatos_ine)
            prompt = (
                f"El municipio '{nombre_wiki}' de la provincia de '{provincia}' tiene esta introduccion en Wikipedia:\n\n"
                f"\"{texto_intro}\"\n\n"
                f"De la siguiente lista de municipios del INE en esa provincia, ¿cual corresponde a este municipio?\n\n"
                f"{lista_str}\n\n"
                "Responde SOLO con el nombre exacto de la lista, copiado tal cual. Si ninguno corresponde, responde NINGUNO."
            )
        else:
            prompt = (
                f"Lee la introduccion de Wikipedia para el municipio '{nombre_wiki}' de '{provincia}':\n\n"
                f"\"{texto_intro}\"\n\n"
                "Dime cual es su nombre oficial o cooficial (el que usaria el INE). "
                "Responde SOLO con el nombre, sin mas palabras ni puntuacion extra."
            )
        
        respuesta = call_llm("Eres un asistente experto en toponimia española.", prompt, context_info={"stage": "consultar_nombre_ine"}, json_mode=False)
        if not respuesta: return None
        
        respuesta = respuesta.strip()
        if respuesta.upper() == "NINGUNO":
            return None
        return respuesta
    except Exception as e:
        print(f"Error en LLM municipio: {e}")
    return None

def buscar_municipio_ine(nombre_municipio: str, provincia: str, datos_ine: dict, html_municipio: str = None) -> dict | None:
    """
    Busca un municipio en las tablas INE por nombre y provincia.

    Args:
        nombre_municipio: Nombre del municipio (del JSON).
        provincia: Provincia del municipio (del JSON).
        datos_ine: Diccionario devuelto por cargar_datos_ine().

    Returns:
        dict con:
            'clave': (cpro, cmun)
            'nombre_ine': str
            'poblacion_ine': int
            'localidades': [{'nombre': str, 'poblacion': int}, ...]
            'nombre_en_localidades': bool  (si el nombre del municipio aparece como localidad)
        o None si no se encuentra.
    """
    nombre_norm = _normalizar(nombre_municipio)
    provincia_norm = _normalizar_nombre_provincia(provincia)

    candidatos = datos_ine['indice_nombre'].get(nombre_norm, [])

    if not candidatos:
        # Intentar búsqueda parcial: a veces los nombres difieren ligeramente
        # Ejemplo: "San Martín de Oscos" vs "San Martin de Oscos"
        for nombre_ine_norm, claves in datos_ine['indice_nombre'].items():
            if nombre_norm in nombre_ine_norm or nombre_ine_norm in nombre_norm:
                # FILTRO: solo aceptar si la provincia coincide
                for cpro, cmun, prov_orig in claves:
                    prov_norm_ine = _normalizar_nombre_provincia(prov_orig)
                    partes_prov = re.split(r'[/,]', prov_norm_ine)
                    if (provincia_norm and 
                        (provincia_norm in prov_norm_ine or prov_norm_ine in provincia_norm or
                         any(provincia_norm in p.strip() or p.strip() in provincia_norm for p in partes_prov))):
                        candidatos.append((cpro, cmun, prov_orig))
        # Deduplicar
        candidatos = list(set(candidatos))

    if not candidatos:
        # Usar Fuzzy Matching (difflib) entre los municipios de la misma provincia
        # Útil para traducir topónimos (ej. Aramayona -> Aramaio)
        import difflib
        candidatos_prov = {}
        for (cpro, cmun), info in datos_ine['municipios'].items():
            prov_norm = _normalizar_nombre_provincia(info['provincia'])
            # Filtro flexible de provincia
            partes_prov = re.split(r'[/,]', prov_norm)
            if provincia_norm in prov_norm or prov_norm in provincia_norm or any(provincia_norm in p.strip() for p in partes_prov):
                for p_limpio in limpiar_nombre_ine(info['nombre']):
                    candidatos_prov[_normalizar(p_limpio)] = (cpro, cmun, info['provincia'])

        if candidatos_prov:
            matches = difflib.get_close_matches(nombre_norm, list(candidatos_prov.keys()), n=1, cutoff=0.85)
            if matches:
                candidatos.append(candidatos_prov[matches[0]])
                
        # TERCER FALLBACK: Si no hay match matematico y tenemos HTML, usar LLM
        if not candidatos and html_municipio and candidatos_prov:
            # Construir lista legible de nombres INE de la provincia
            nombres_ine_legibles = {}
            for (cpro, cmun), info in datos_ine['municipios'].items():
                prov_norm = _normalizar_nombre_provincia(info['provincia'])
                partes_prov = re.split(r'[/,]', prov_norm)
                if provincia_norm in prov_norm or prov_norm in provincia_norm or any(provincia_norm in p.strip() for p in partes_prov):
                    nombres_ine_legibles[info['nombre']] = (cpro, cmun, info['provincia'])
            
            lista_nombres = list(nombres_ine_legibles.keys())
            nombre_oficial_llm = _consultar_nombre_ine_llm(nombre_municipio, provincia, html_municipio, lista_nombres)
            if nombre_oficial_llm:
                # Buscar match directo primero
                if nombre_oficial_llm in nombres_ine_legibles:
                    print(f"     -> [LLM] Match directo: '{nombre_municipio}' = '{nombre_oficial_llm}'")
                    candidatos.append(nombres_ine_legibles[nombre_oficial_llm])
                else:
                    # Fuzzy match contra la respuesta del LLM
                    matches_llm = difflib.get_close_matches(_normalizar(nombre_oficial_llm), list(candidatos_prov.keys()), n=1, cutoff=0.6)
                    if matches_llm:
                        print(f"     -> [LLM] Alias encontrado: '{nombre_municipio}' = '{matches_llm[0]}'")
                        candidatos.append(candidatos_prov[matches_llm[0]])

    if not candidatos:
        return None

    # Filtrar por provincia
    mejor = None
    for cpro, cmun, prov_orig in candidatos:
        prov_norm = _normalizar_nombre_provincia(prov_orig)
        # Match exacto o parcial de provincia
        if provincia_norm in prov_norm or prov_norm in provincia_norm:
            mejor = (cpro, cmun)
            break
        # Match por partes (ej: "Álava" en "Araba/Álava")
        partes_prov_ine = re.split(r'[/,]', prov_norm)
        if any(provincia_norm in parte.strip() or parte.strip() in provincia_norm
               for parte in partes_prov_ine):
            mejor = (cpro, cmun)
            break

    if not mejor:
        return None

    info_mun = datos_ine['municipios'].get(mejor)
    locs = datos_ine['localidades'].get(mejor, [])

    # Comprobar si el nombre oficial del municipio (INE) coincide con alguna localidad (INE)
    nombre_base_ine = info_mun['nombre'] if info_mun else nombre_municipio
    nombre_en_locs = _nombre_coincide_con_localidad(nombre_base_ine, locs)

    return {
        'clave': mejor,
        'nombre_ine': info_mun['nombre'] if info_mun else '',
        'poblacion_ine': info_mun['poblacion'] if info_mun else 0,
        'localidades': locs,
        'nombre_en_localidades': nombre_en_locs,
    }


def _nombre_coincide_con_localidad(nombre_municipio: str, localidades: list[dict]) -> bool:
    """
    Comprueba si el nombre del municipio coincide con alguna localidad del INE.

    Hace comparación normalizada (sin tildes, minúsculas) y divide los nombres bilingües separados por '/'.
    """
    nombre_norm = _normalizar(nombre_municipio)
    # También probar con las variantes limpias del nombre del municipio
    variantes_mun = {nombre_norm}
    # Sin artículos
    sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', nombre_norm)
    if sin_art: variantes_mun.add(sin_art)
    # Partes bilingües
    for parte in nombre_municipio.split('/'):
        variantes_mun.add(_normalizar(parte.strip()))
    
    for loc in localidades:
        partes_loc = limpiar_nombre_ine(loc['nombre'])
        variantes_loc = set()
        for p_loc in partes_loc:
            loc_norm = _normalizar(p_loc)
            variantes_loc.add(loc_norm)
            loc_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', loc_norm)
            if loc_sin_art: variantes_loc.add(loc_sin_art)
        
        # Match: cualquier variante del municipio coincide con cualquier variante de la localidad
        if variantes_mun & variantes_loc:
            return True
        
        # Match parcial (contenido) solo para nombres largos
        for vm in variantes_mun:
            for vl in variantes_loc:
                if len(vm) > 4 and len(vl) > 4:
                    if vm in vl or vl in vm:
                        return True
    
    return False


def formatear_localidades_para_prompt(localidades: list[dict]) -> str:
    """
    Formatea la lista de localidades del INE para incluir en el prompt del LLM.

    Returns:
        Texto formateado con las localidades y sus poblaciones.
    """
    if not localidades:
        return "No se encontraron localidades del INE para este municipio."

    lineas = []
    for loc in sorted(localidades, key=lambda x: x['poblacion'], reverse=True):
        lineas.append(f"  - {loc['nombre']} ({loc['poblacion']} hab.)")

    return f"Localidades/entidades registradas ({len(localidades)}):\n" + "\n".join(lineas)

# ============================================================================
# CARGA DE TABLAS NGMEP (NUEVAS)
# ============================================================================
import csv

def cargar_provincias_ngmep() -> dict:
    provincias = {}
    path = os.path.join(_DATOS_DIR, "PROVINCIAS.csv")
    if not os.path.exists(path): return {}
    with open(path, 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            provincias[row['COD_PROV'].strip()] = {
                'provincia': row['PROVINCIA'].strip(),
                'comunidad': row['COMUNIDAD_AUTONOMA'].strip()
            }
    return provincias

def cargar_municipios_ngmep() -> dict:
    municipios = {}
    path = os.path.join(_DATOS_DIR, "MUNICIPIOS.csv")
    if not os.path.exists(path): return {}
    with open(path, 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            try: lat = float(row['LATITUD_ETRS89_REGCAN95'].replace(',', '.')) if row['LATITUD_ETRS89_REGCAN95'] else 0.0
            except: lat = 0.0
            try: lng = float(row['LONGITUD_ETRS89_REGCAN95'].replace(',', '.')) if row['LONGITUD_ETRS89_REGCAN95'] else 0.0
            except: lng = 0.0
            
            pob = 0
            try: pob = int(row['POBLACION_MUNI'])
            except: pass
            
            municipios[row['COD_INE'].strip()] = {
                'nombre': row['NOMBRE_ACTUAL'].strip(),
                'poblacion': pob,
                'lat': lat,
                'lng': lng,
                'cod_prov': row['COD_PROV'].strip()
            }
    return municipios

def cargar_entidades_ngmep() -> dict:
    entidades_por_muni = {}
    path = os.path.join(_DATOS_DIR, "ENTIDADES.csv")
    if not os.path.exists(path): return {}
    with open(path, 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            tipo = row['TIPO'].strip()
            if tipo not in ('Capital de municipio', 'Otras entidades'):
                continue
            
            try: pob = int(row['POBLACION'])
            except: pob = 0
            
            if pob <= 0:
                continue

            inemuni = row['INEMUNI'].strip()
            if inemuni not in entidades_por_muni:
                entidades_por_muni[inemuni] = []
                
            try: lat = float(row['LATITUD_ETRS89_REGCAN95'].replace(',', '.')) if row['LATITUD_ETRS89_REGCAN95'] else 0.0
            except: lat = 0.0
            try: lng = float(row['LONGITUD_ETRS89_REGCAN95'].replace(',', '.')) if row['LONGITUD_ETRS89_REGCAN95'] else 0.0
            except: lng = 0.0
            
            entidades_por_muni[inemuni].append({
                'id': row['CODIGOINE'].strip(),
                'nombre': row['NOMBRE'].strip(),
                'poblacion': pob,
                'lat': lat,
                'lng': lng,
                'es_capital': (tipo == 'Capital de municipio')
            })
            
    for inemuni, entidades in entidades_por_muni.items():
        unicas = {}
        for ent in entidades:
            nombre_norm = _normalizar(ent['nombre'])
            if nombre_norm not in unicas:
                unicas[nombre_norm] = ent
            else:
                if ent['poblacion'] > unicas[nombre_norm]['poblacion']:
                    unicas[nombre_norm] = ent
        entidades_por_muni[inemuni] = list(unicas.values())
        
    return entidades_por_muni

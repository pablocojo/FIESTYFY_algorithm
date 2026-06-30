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
    Carga ambas tablas del INE en memoria.

    Returns:
        dict con claves:
            'municipios': {(cpro, cmun): {'nombre': str, 'poblacion': int, 'provincia': str}}
            'localidades': {(cpro, cmun): [{'nombre': str, 'poblacion': int}, ...]}
            'indice_nombre': {nombre_normalizado: [(cpro, cmun, provincia_original), ...]}
    """
    import openpyxl

    safe_print("Cargando tablas INE...")

    # --- Cargar municipios (pobmun25.xlsx) ---
    safe_print("  Leyendo pobmun25.xlsx (municipios)...")
    municipios = {}
    indice_nombre = {}  # nombre_norm -> lista de (cpro, cmun, provincia_orig)

    wb_mun = openpyxl.load_workbook(_POBMUN_FILE, read_only=True, data_only=True)
    ws_mun = wb_mun.active

    fila_datos = False
    for row in ws_mun.iter_rows(values_only=True):
        # Detectar la fila de cabecera real (CPRO, PROVINCIA, ...)
        if row and str(row[0]).strip() == 'CPRO':
            fila_datos = True
            continue
        if not fila_datos:
            continue

        cpro = str(row[0]).strip() if row[0] else ''
        provincia_orig = str(row[1]).strip() if row[1] else ''
        cmun = str(row[2]).strip() if row[2] else ''
        nombre = str(row[3]).strip() if row[3] else ''
        poblacion = int(row[4]) if row[4] is not None else 0

        if not cpro or not cmun:
            continue

        clave = (cpro, cmun)
        municipios[clave] = {
            'nombre': nombre,
            'poblacion': poblacion,
            'provincia': provincia_orig,
        }

        # Índice por nombre normalizado
        nombre_norm = _normalizar(nombre)
        if nombre_norm not in indice_nombre:
            indice_nombre[nombre_norm] = []
        indice_nombre[nombre_norm].append((cpro, cmun, provincia_orig))

    wb_mun.close()
    safe_print(f"  OK: {len(municipios)} municipios cargados.")

    # --- Cargar localidades (nomdef2025.xlsx) ---
    safe_print("  Leyendo nomdef2025.xlsx (localidades)... [fichero grande, puede tardar]")
    localidades = {}  # (cpro, cmun) -> [{'nombre': str, 'poblacion': int}, ...]

    wb_loc = openpyxl.load_workbook(_NOMDEF_FILE, read_only=True, data_only=True)
    ws_loc = wb_loc.active

    filas_procesadas = 0
    for row in ws_loc.iter_rows(min_row=2, values_only=True):
        # Columnas: Provincia, Municipio, Unidad Poblacional, Total 2025, Hombres, Mujeres
        cpro = str(row[0]).strip() if row[0] else ''
        cmun = str(row[1]).strip() if row[1] else ''
        unidad_raw = str(row[2]).strip() if row[2] else ''
        total_pob = int(row[3]) if row[3] is not None else 0

        if not cpro or not cmun or not unidad_raw:
            continue

        # Parsear código y nombre de la unidad poblacional
        # Formato: "CCCCCC NOMBRE" (6 dígitos + espacio + nombre)
        match = re.match(r'^(\d{6})\s+(.+)$', unidad_raw)
        if not match:
            continue

        codigo_up = match.group(1)
        nombre_up = match.group(2).strip()

        # Filtrar:
        # - 000000 = total del municipio (skip)
        # - XXXX00 (excepto 000000) = entidades/localidades (INCLUIR)
        # - XXXX01, XXXX02... = núcleos dentro de la entidad (skip, ya tenemos la entidad)
        # - *DISEMINADO* = skip
        if codigo_up == '000000':
            continue
        if '*DISEMINADO*' in nombre_up:
            continue
        # Solo incluir filas de nivel entidad (últimos 2 dígitos = 00)
        if codigo_up[-2:] != '00':
            continue

        clave = (cpro, cmun)
        if clave not in localidades:
            localidades[clave] = []

        localidades[clave].append({
            'nombre': nombre_up,
            'poblacion': total_pob,
        })

        filas_procesadas += 1

    wb_loc.close()

    # Deduplicar pedanías con el mismo nombre dentro del mismo municipio
    for clave, lista_locs in localidades.items():
        locs_dedup = {}
        for loc in lista_locs:
            nombre_norm = _normalizar(loc['nombre'])
            if nombre_norm not in locs_dedup:
                locs_dedup[nombre_norm] = loc
            else:
                # Si hay conflicto, nos quedamos con la de mayor población
                if loc['poblacion'] > locs_dedup[nombre_norm]['poblacion']:
                    locs_dedup[nombre_norm] = loc
        localidades[clave] = list(locs_dedup.values())

    total_locs = sum(len(v) for v in localidades.values())
    safe_print(f"  OK: {total_locs} localidades en {len(localidades)} municipios.")

    safe_print("Tablas INE cargadas correctamente.\n")

    return {
        'municipios': municipios,
        'localidades': localidades,
        'indice_nombre': indice_nombre,
    }


# ============================================================================
# BÚSQUEDA
# ============================================================================

def _consultar_nombre_ine_llm(nombre_wiki: str, provincia: str, html_municipio: str) -> str | None:
    """Extrae el nombre oficial del INE del primer parrafo de Wikipedia usando el LLM."""
    try:
        from scraper import get_soup
        import re
        
        soup = get_soup(html_municipio)
        parrafos = [p.get_text(strip=True) for p in soup.find_all('p') if p.get_text(strip=True)]
        texto_intro = " ".join(parrafos[:3])
        
        if not texto_intro:
            return None
            
        from llm_client import call_llm
        prompt = (
            f"Lee la introduccion de Wikipedia para el municipio '{nombre_wiki}' de '{provincia}':\n\n"
            f"\"{texto_intro}\"\n\n"
            "Dime cual es su nombre oficial o cooficial (el que usaria el INE). "
            "Responde SOLO con el nombre, sin mas palabras ni puntuacion extra."
        )
        respuesta = call_llm("Eres un asistente experto en toponimia española.", prompt, context_info={"stage": "consultar_nombre_ine"})
        if not respuesta: return None
        
        return respuesta.strip()
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
            nombre_oficial_llm = _consultar_nombre_ine_llm(nombre_municipio, provincia, html_municipio)
            if nombre_oficial_llm:
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

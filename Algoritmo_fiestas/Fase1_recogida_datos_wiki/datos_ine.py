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

def buscar_municipio_ine(nombre_municipio: str, provincia: str, datos_ine: dict) -> dict | None:
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
                candidatos.extend(claves)
        # Deduplicar
        candidatos = list(set(candidatos))

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
        # Si solo hay un candidato, usarlo igualmente
        if len(candidatos) == 1:
            mejor = (candidatos[0][0], candidatos[0][1])
        else:
            return None

    info_mun = datos_ine['municipios'].get(mejor)
    locs = datos_ine['localidades'].get(mejor, [])

    # Comprobar si el nombre del municipio coincide con alguna localidad
    nombre_en_locs = _nombre_coincide_con_localidad(nombre_municipio, locs)

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

    Hace comparación normalizada (sin tildes, minúsculas).
    """
    nombre_norm = _normalizar(nombre_municipio)

    for loc in localidades:
        loc_norm = _normalizar(loc['nombre'])
        if nombre_norm == loc_norm:
            return True
        # También comprobar sin artículos comunes (El, La, Los, Las, L')
        nombre_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', nombre_norm)
        loc_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', loc_norm)
        if nombre_sin_art and loc_sin_art and nombre_sin_art == loc_sin_art:
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

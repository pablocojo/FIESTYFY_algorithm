import os
import re

base_path = 'c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase1_recogida_datos_wiki'

# PATCH DATOS_INE.PY
f_ine = os.path.join(base_path, 'datos_ine.py')
with open(f_ine, 'r', encoding='utf-8') as f:
    ine_code = f.read()

# Edit 1
target1 = """    if not candidatos:
        # Intentar búsqueda parcial: a veces los nombres difieren ligeramente
        # Ejemplo: "San Martín de Oscos" vs "San Martin de Oscos"
        for nombre_ine_norm, claves in datos_ine['indice_nombre'].items():
            if nombre_norm in nombre_ine_norm or nombre_ine_norm in nombre_norm:
                candidatos.extend(claves)
        # Deduplicar
        candidatos = list(set(candidatos))"""

repl1 = """    if not candidatos:
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
        candidatos = list(set(candidatos))"""

# Edit 2
target2 = """    if not mejor:
        # Si solo hay un candidato, usarlo igualmente
        if len(candidatos) == 1:
            mejor = (candidatos[0][0], candidatos[0][1])
        else:
            return None"""

repl2 = """    if not mejor:
        return None"""

# Edit 3
target3 = """def _nombre_coincide_con_localidad(nombre_municipio: str, localidades: list[dict]) -> bool:
    \"\"\"
    Comprueba si el nombre del municipio coincide con alguna localidad del INE.

    Hace comparación normalizada (sin tildes, minúsculas) y divide los nombres bilingües separados por '/'.
    \"\"\"
    nombre_norm = _normalizar(nombre_municipio)

    for loc in localidades:
        partes_loc = limpiar_nombre_ine(loc['nombre'])
        for p_loc in partes_loc:
            loc_norm = _normalizar(p_loc)
            if nombre_norm == loc_norm:
                return True
            # También comprobar sin artículos comunes
            nombre_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', nombre_norm)
            loc_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', loc_norm)
            if nombre_sin_art and loc_sin_art and nombre_sin_art == loc_sin_art:
                return True
            # Contenidos directos para cubrir compuestos parciales (solo si son largos)
            if len(nombre_norm) > 4 and len(loc_norm) > 4:
                if nombre_norm in loc_norm or loc_norm in nombre_norm:
                    return True

    return False"""

repl3 = """def _nombre_coincide_con_localidad(nombre_municipio: str, localidades: list[dict]) -> bool:
    \"\"\"
    Comprueba si el nombre del municipio coincide con alguna localidad del INE.

    Hace comparación normalizada (sin tildes, minúsculas) y divide los nombres bilingües separados por '/'.
    \"\"\"
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
    
    return False"""

ine_code = ine_code.replace(target1, repl1)
ine_code = ine_code.replace(target2, repl2)
ine_code = ine_code.replace(target3, repl3)

with open(f_ine, 'w', encoding='utf-8') as f:
    f.write(ine_code)

# PATCH DISTRITOS_PEDANIAS.PY
f_dp = os.path.join(base_path, 'parte2_distritos_pedanias', 'distritos_pedanias.py')
with open(f_dp, 'r', encoding='utf-8') as f:
    dp_code = f.read()

target_dp = """    info_ine = buscar_municipio_ine(lugar.get("nombre", ""), lugar.get("provincia", ""), DATOS_INE_GLOBAL, html_municipio)
    if not info_ine or not info_ine.get("localidades"):
        print("   - No se encontraron pedanias en el INE para este municipio.")
        return []"""

repl_dp = """    info_ine = buscar_municipio_ine(lugar.get("nombre", ""), lugar.get("provincia", ""), DATOS_INE_GLOBAL, html_municipio)
    
    if info_ine:
        cpro_ine, cmun_ine = info_ine['clave']
        prov_ine = DATOS_INE_GLOBAL['municipios'].get((cpro_ine, cmun_ine), {}).get('provincia', '')
        prov_lugar = lugar.get('provincia', '')
        if prov_lugar and prov_ine:
            from utilities.normalizacion import _normalizar
            if _normalizar(prov_lugar) not in _normalizar(prov_ine) and _normalizar(prov_ine) not in _normalizar(prov_lugar):
                print(f"   - [ALERTA] INE matcheó {lugar['nombre']} [{prov_lugar}] con {info_ine['nombre_ine']} [{prov_ine}]. DESCARTANDO.")
                return []
                
    if not info_ine or not info_ine.get("localidades"):
        print("   - No se encontraron pedanias en el INE para este municipio.")
        return []"""

dp_code = dp_code.replace(target_dp, repl_dp)

with open(f_dp, 'w', encoding='utf-8') as f:
    f.write(dp_code)

print("Archivos parcheados.")

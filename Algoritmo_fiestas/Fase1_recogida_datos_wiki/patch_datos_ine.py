import re

with open('datos_ine.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Buscamos la funcion cargar_datos_ine() entera (hasta el return { ... })
match = re.search(r'def cargar_datos_ine\(\) -> dict:.*?return \{(.*?)\}', content, flags=re.DOTALL)
if not match:
    print('No se encontró cargar_datos_ine()')
    exit(1)

new_func = '''def cargar_datos_ine() -> dict:
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
    safe_print("Tablas INE cargadas correctamente (NGMEP).\\n")

    return {
        'municipios': municipios,
        'localidades': localidades,
        'indice_nombre': indice_nombre,
    }
'''

new_content = content[:match.start()] + new_func + content[match.end():]

with open('datos_ine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('datos_ine.py modificado con éxito.')

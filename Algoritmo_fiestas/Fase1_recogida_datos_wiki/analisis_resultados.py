"""Analiza los casos especificos de matching erroneo del INE."""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

from datos_ine import cargar_datos_ine, _normalizar, buscar_municipio_ine, limpiar_nombre_ine
datos = cargar_datos_ine()

# Casos concretos de matching erroneo
test_cases = [
    # (nombre_municipio_json, provincia_json, pedanias_erroneas)
    ("Cuartango", "Álava", ["ARTÀ", "COLÒNIA DE SANT PERE"]),
    ("El Bonillo", "Albacete", ["ONIL"]),
    ("La Herrera", "Albacete", ["HERRERA"]),
    ("Aguas de Busot", "Alicante", ["BUSOT"]),
    ("Alcocer de Planes", "Alicante", ["PLANES"]),
    ("Facheca", "Alicante", ["CHECA"]),
    ("El Carrascalejo", "Badajoz", ["CARRASCALEJO"]),
    ("La Nava de Santiago", "Badajoz", ["NAVA"]),
    ("El Ballestero", "Albacete", ["LES"]),
    ("Alquería de Aznar", "Alicante", ["QUER"]),
    ("Valle de Alcalá", "Alicante", ["CALA"]),
]

print("=" * 70)
print("DIAGNOSTICO DE MATCHING ERRONEO DEL INE")
print("=" * 70)

for nombre, prov, peds_erroneas in test_cases:
    info = buscar_municipio_ine(nombre, prov, datos)
    if info:
        locs = [loc['nombre'] for loc in info.get('localidades', [])]
        print(f"\n{nombre} [{prov}]:")
        print(f"  INE clave: {info['clave']}, nombre_ine: {info['nombre_ine']}, pob: {info['poblacion_ine']}")
        print(f"  Localidades INE ({len(locs)}): {locs[:10]}")
        for ped in peds_erroneas:
            found = ped in locs
            print(f"  -> {ped} esta en localidades? {found}")
    else:
        print(f"\n{nombre} [{prov}]: NO ENCONTRADO EN INE")

# Ahora analizar por qué nombre_coincide_con_localidad falla
print("\n" + "=" * 70)
print("ANALISIS DE _nombre_coincide_con_localidad (FALSOS POSITIVOS)")  
print("=" * 70)

# El problema es la comparación parcial en línea 381-383 de datos_ine.py:
# if len(nombre_norm) > 4 and len(loc_norm) > 4:
#     if nombre_norm in loc_norm or loc_norm in nombre_norm:
#         return True

d = json.load(open('lugares_espana.json', 'r', encoding='utf-8'))
mun_compuestos = [l for l in d['lugares'] if l.get('tipo') == 'municipio_compuesto' and not l.get('padre_id')]

# Los que son "realmente compuestos" segun el sistema actual pero que deberian NO serlo
# porque la comparacion parcial debería haber detectado la homonima
fallos_parcial = []
for mun in mun_compuestos[:100]:
    nombre = mun.get('nombre','')
    prov = mun.get('provincia','')
    info = buscar_municipio_ine(nombre, prov, datos)
    if not info: continue
    
    nombre_ine = info['nombre_ine']
    locs = info.get('localidades', [])
    
    # La logica actual dice que NO tiene homonima. Veamos por qué
    nombre_norm = _normalizar(nombre_ine)
    
    for loc in locs:
        partes = limpiar_nombre_ine(loc['nombre'])
        for p in partes:
            loc_norm = _normalizar(p)
            if nombre_norm == loc_norm:
                fallos_parcial.append((nombre, nombre_ine, loc['nombre'], "EXACTO"))
                break
            nombre_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', nombre_norm)
            loc_sin_art = re.sub(r"^(?:el|la|los|las|l'|es|sa|ses)\s+", '', loc_norm)
            if nombre_sin_art and loc_sin_art and nombre_sin_art == loc_sin_art:
                fallos_parcial.append((nombre, nombre_ine, loc['nombre'], "SIN ARTICULO"))
                break
            if len(nombre_norm) > 4 and len(loc_norm) > 4:
                if nombre_norm in loc_norm or loc_norm in nombre_norm:
                    fallos_parcial.append((nombre, nombre_ine, loc['nombre'], "PARCIAL"))
                    break

if fallos_parcial:
    print(f"\nMunicipios compuestos que SÍ deberían tener homonima detectada:")
    for n, nine, loc, tipo in fallos_parcial[:20]:
        print(f"  {n} -> INE:{nine} tiene localidad '{loc}' (match {tipo})")

# Los verdaderos compuestos - los que realmente NO tienen match
print(f"\n--- VERDADEROS COMPUESTOS (sin homonima en absolutamente nada): ---")
from datos_ine import _nombre_coincide_con_localidad
reales = []
for mun in mun_compuestos:
    nombre = mun.get('nombre','')
    prov = mun.get('provincia','')
    info = buscar_municipio_ine(nombre, prov, datos)
    if not info: continue
    locs = info.get('localidades', [])
    if not _nombre_coincide_con_localidad(info['nombre_ine'], locs):
        reales.append((nombre, prov, info['nombre_ine'], [l['nombre'] for l in locs[:5]]))

print(f"Total: {len(reales)}")
for n, p, nine, locs in reales[:30]:
    print(f"  {n} [{p}] INE:{nine} -> locs: {locs}")

import json
import difflib
import sys
import os
import shutil

sys.path.append(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki')
from datos_ine import cargar_datos_ine, buscar_municipio_ine, _normalizar, _normalizar_nombre_provincia

def match_all():
    datos_ine = cargar_datos_ine()
    
    file_path = r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json'
    backup_path = file_path.replace('.json', '_backup.json')
    
    if not os.path.exists(backup_path):
        shutil.copy2(file_path, backup_path)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
        
    lugares_muni = data_muni.get('lugares', [])
    
    # Pre-agrupar INE por provincia
    ine_por_prov = {}
    for (cpro, cmun), m in datos_ine['municipios'].items():
        prov = _normalizar_nombre_provincia(m['provincia'])
        if prov not in ine_por_prov:
            ine_por_prov[prov] = []
        ine_por_prov[prov].append(m['nombre'])

    def buscar_en_ine_reducido(nombre, prov):
        prov_norm = _normalizar_nombre_provincia(prov)
        # Buscar la provincia más parecida si no coincide exacto
        prov_key = None
        for k in ine_por_prov.keys():
            if prov_norm in k or k in prov_norm:
                prov_key = k
                break
        
        if not prov_key:
            # Try fuzzy match on provinces
            matches_p = difflib.get_close_matches(prov_norm, list(ine_por_prov.keys()), n=1, cutoff=0.6)
            if matches_p:
                prov_key = matches_p[0]
                
        if not prov_key:
            return None
            
        candidatos = ine_por_prov[prov_key]
        nombres_norm = { _normalizar(c): c for c in candidatos }
        
        nombre_norm = _normalizar(nombre)
        if nombre_norm in nombres_norm:
            return nombres_norm[nombre_norm]
            
        matches = difflib.get_close_matches(nombre_norm, list(nombres_norm.keys()), n=1, cutoff=0.4)
        if matches:
            return nombres_norm[matches[0]]
            
        return None

    ok_list = []
    skipped_list = []
    
    no_encontrados_totalmente = []

    for m in lugares_muni:
        nombre = m.get('nombre', '')
        prov = m.get('provincia', '')
        
        # Test original
        info_ine = buscar_municipio_ine(nombre, prov, datos_ine)
        
        if info_ine:
            m['nombre_oficial'] = info_ine['nombre_ine']
            ok_list.append(m)
        else:
            # Fallback custom fuzzy
            nombre_oficial = buscar_en_ine_reducido(nombre, prov)
            if nombre_oficial:
                m['nombre_oficial'] = nombre_oficial
            else:
                m['nombre_oficial'] = nombre # Fallback original
                no_encontrados_totalmente.append(m)
            
            skipped_list.append(m)

    data_muni['lugares'] = ok_list + skipped_list
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_muni, f, ensure_ascii=False, indent=2)
        
    print(f"Completado. OK: {len(ok_list)}, Reubicados: {len(skipped_list)}")
    print(f"No mapeados por fuzzy: {len(no_encontrados_totalmente)}")
    if no_encontrados_totalmente:
        print("Ejemplos no mapeados:")
        for x in no_encontrados_totalmente[:10]:
            print(f" - {x['nombre']} ({x.get('provincia')})")

if __name__ == '__main__':
    match_all()

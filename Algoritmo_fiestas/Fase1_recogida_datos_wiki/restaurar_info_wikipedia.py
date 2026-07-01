import json
import unicodedata
import re

def normalizar(texto):
    if not isinstance(texto, str):
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", "", texto.lower().strip())

def main():
    print("Cargando lugares_espana.json...")
    with open("lugares_espana.json", "r", encoding="utf-8") as f:
        datos_nuevos = json.load(f)
        
    print("Cargando lugares_espana_old.json...")
    with open("lugares_espana_old.json", "r", encoding="utf-8") as f:
        datos_viejos = json.load(f)
        
    lugares_n = datos_nuevos.get("lugares", [])
    lugares_v = datos_viejos.get("lugares", [])
    
    # Construir diccionarios de padres para buscar rápido
    padres_viejos = {l["id"]: l for l in lugares_v if "id" in l}
    padres_nuevos = {l["id"]: l for l in lugares_n if "id" in l}
    
    # Crear mapas de lugares viejos 
    # Usaremos 2 claves: (padre_nombre, hijo_nombre) y (hijo_nombre, provincia)
    mapa_viejos = {}
    for l in lugares_v:
        n_hijo = normalizar(l.get("nombre", ""))
        n_prov = normalizar(l.get("provincia", ""))
        
        padre_id = l.get("padre_id") or l.get("abuelo_id")
        n_padre = ""
        if padre_id and padre_id in padres_viejos:
            n_padre = normalizar(padres_viejos[padre_id].get("nombre", ""))
            
        if n_padre and n_hijo:
            mapa_viejos[f"{n_padre}_{n_hijo}"] = l
        if n_hijo and n_prov:
            mapa_viejos[f"{n_hijo}_{n_prov}"] = l
            
    # Para los municipios principales por si acaso
    for l in lugares_v:
        if not l.get("padre_id"):
            n_mun = normalizar(l.get("nombre", ""))
            n_prov = normalizar(l.get("provincia", ""))
            mapa_viejos[f"MUNI_{n_mun}_{n_prov}"] = l
            
    restaurados = 0
    for l_new in lugares_n:
        # Detectar si el lugar necesita reparación
        # 1. Falta sitio_web
        # 2. Wikipedia URL está vacío
        # 3. La descripción es la genérica generada por fallback
        desc_actual = l_new.get("descripcion", "")
        necesita_reparacion = (
            not l_new.get("sitio_web") or 
            not l_new.get("wikipedia_url") or 
            "es una localidad perteneciente al municipio de" in desc_actual or
            not l_new.get("imagenes", {}).get("logo")
        )

        if necesita_reparacion:
            # Buscar el match en el JSON antiguo
            match = None
            n_hijo = normalizar(l_new.get("nombre", ""))
            n_prov = normalizar(l_new.get("provincia", ""))
            
            padre_id = l_new.get("padre_id") or l_new.get("abuelo_id")
            if padre_id:
                n_padre = ""
                if padre_id in padres_nuevos:
                    n_padre = normalizar(padres_nuevos[padre_id].get("nombre", ""))
                
                clave1 = f"{n_padre}_{n_hijo}"
                clave2 = f"{n_hijo}_{n_prov}"
                
                if clave1 in mapa_viejos:
                    match = mapa_viejos[clave1]
                elif clave2 in mapa_viejos:
                    match = mapa_viejos[clave2]
            else:
                clave_muni = f"MUNI_{n_hijo}_{n_prov}"
                if clave_muni in mapa_viejos:
                    match = mapa_viejos[clave_muni]
                    
            if match:
                hubo_cambio = False
                
                # Restaurar wiki, sitio_web y descripciones (si son mejores)
                if match.get("wikipedia_url") and not l_new.get("wikipedia_url"):
                    l_new["wikipedia_url"] = match["wikipedia_url"]
                    hubo_cambio = True
                    
                if match.get("sitio_web") and not l_new.get("sitio_web"):
                    l_new["sitio_web"] = match["sitio_web"]
                    hubo_cambio = True
                    
                # Si el actual tiene la descripcion fallback pero el viejo tiene la real
                if "es una localidad perteneciente al municipio de" in desc_actual and match.get("descripcion"):
                    l_new["descripcion"] = match["descripcion"]
                    l_new["descripcion_corta"] = match.get("descripcion_corta", "")
                    hubo_cambio = True
                # O si esta vacía
                elif not desc_actual and match.get("descripcion"):
                    l_new["descripcion"] = match["descripcion"]
                    l_new["descripcion_corta"] = match.get("descripcion_corta", "")
                    hubo_cambio = True
                        
                # Restaurar imágenes
                if match.get("imagenes"):
                    if not l_new.get("imagenes"):
                        l_new["imagenes"] = match["imagenes"]
                        hubo_cambio = True
                    else:
                        if match["imagenes"].get("banner") and not l_new["imagenes"].get("banner"):
                            l_new["imagenes"]["banner"] = match["imagenes"]["banner"]
                            hubo_cambio = True
                        if match["imagenes"].get("logo") and not l_new["imagenes"].get("logo"):
                            l_new["imagenes"]["logo"] = match["imagenes"]["logo"]
                            hubo_cambio = True
                            
                if hubo_cambio:
                    restaurados += 1

    print(f"Se han restaurado campos para {restaurados} lugares.")
    
    print("Guardando en lugares_espana_corregido.json...")
    with open("lugares_espana_corregido.json", "w", encoding="utf-8") as f:
        json.dump(datos_nuevos, f, indent=2, ensure_ascii=False)
    
    print("¡Hecho! Renombra 'lugares_espana_corregido.json' a 'lugares_espana.json' cuando compruebes que esta bien.")

if __name__ == "__main__":
    main()

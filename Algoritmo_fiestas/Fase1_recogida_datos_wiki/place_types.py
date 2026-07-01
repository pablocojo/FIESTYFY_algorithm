# place_types.py
"""
Módulo de tipificación y clasificación de lugares españoles.
Define lógica para clasificar un lugar según población, estructura administrativa y metadatos.
"""

from typing import Literal, Optional

PlaceType = Literal[
    "municipio",
    "pueblo",
    "ciudad_pequena",
    "ciudad_grande",
    "distrito",
    "barrio",
]


def clasificar_por_poblacion(poblacion: int | None) -> Optional[PlaceType]:
    """
    Clasifica un lugar según población.
    
    - pueblo: < 10,000
    - ciudad_pequena: 10,000 - 40,000
    - ciudad_grande: > 40,000
    """
    if poblacion is None or poblacion < 0:
        return None
    
    if poblacion < 10000:
        return "pueblo"
    elif poblacion < 40000:
        return "ciudad_pequena"
    else:
        return "ciudad_grande"


def es_tipo_valido(tipo: str) -> bool:
    """Valida que un tipo sea uno de los permitidos."""
    tipos_validos = {
        "municipio",
        "pueblo",
        "ciudad_pequena",
        "ciudad_grande",
        "distrito",
        "barrio",
    }
    return tipo in tipos_validos


def valida_lugar(lugar: dict) -> tuple[bool, list[str]]:
    """Valida estructura de un objeto 'lugar' contra el esquema esperado."""
    errores = []
    
    # Campos obligatorios para todos los lugares
    campos_obligatorios = {"id", "tipo", "nombre", "provincia", "comunidad", "poblacion", "lat", "lng", "es_capital", "descripcion_corta", "descripcion", "imagenes", "sitio_web", "wikipedia_url"}
    for campo in campos_obligatorios:
        if campo not in lugar:
            errores.append(f"Campo obligatorio faltante: {campo}")
    
    if "tipo" in lugar and not es_tipo_valido(lugar["tipo"]):
        errores.append(f"Tipo inválido: {lugar['tipo']}")
    
    if "poblacion" in lugar:
        if not isinstance(lugar["poblacion"], int) or lugar["poblacion"] < 0:
            errores.append(f"Población inválida: {lugar['poblacion']}")
    
    if "lat" in lugar:
        try:
            float(lugar["lat"])
        except (ValueError, TypeError):
            errores.append(f"Latitud inválida: {lugar['lat']}")
    
    if "lng" in lugar:
        try:
            float(lugar["lng"])
        except (ValueError, TypeError):
            errores.append(f"Longitud inválida: {lugar['lng']}")
    
    if "imagenes" in lugar:
        img = lugar["imagenes"]
        if not isinstance(img, dict):
            errores.append("Imágenes debe ser un diccionario")
        else:
            if "banner" not in img:
                errores.append("Imágenes sin 'banner'")
            if "logo" not in img:
                errores.append("Imágenes sin 'logo'")
    
    if "tipo" in lugar and lugar["tipo"] in ("pueblo", "ciudad_pequena", "ciudad_grande", "distrito", "barrio"):
        if "padre_id" not in lugar or not lugar["padre_id"]:
            errores.append(f"Tipo '{lugar['tipo']}' requiere padre_id")
    
    if "padre_id" in lugar and lugar.get("padre_id"):
        if lugar.get("tipo") == "municipio":
            errores.append(f"Tipo '{lugar.get('tipo')}' no debería tener padre_id")

    if "abuelo_id" in lugar and lugar.get("abuelo_id"):
        if lugar.get("tipo") != "barrio":
            errores.append(f"Tipo '{lugar.get('tipo')}' no debería tener abuelo_id")
    
    es_valido = len(errores) == 0
    return es_valido, errores


def valida_dataset(dataset: dict) -> tuple[bool, list[str]]:
    """Valida dataset completo."""
    errores = []
    
    if "version" not in dataset:
        errores.append("Campo 'version' faltante en raíz")
    
    if "lugares" not in dataset:
        errores.append("Campo 'lugares' faltante en raíz")
        return False, errores
    
    lugares = dataset["lugares"]
    if not isinstance(lugares, list):
        errores.append("'lugares' debe ser una lista")
        return False, errores
    
    ids_vistos = set()
    for idx, lugar in enumerate(lugares):
        lugar_valido, lugar_errores = valida_lugar(lugar)
        if not lugar_valido:
            for err in lugar_errores:
                errores.append(f"Lugar [{idx}] ({lugar.get('nombre', '?')}): {err}")
        
        if "id" in lugar:
            lugar_id = lugar["id"]
            if lugar_id in ids_vistos:
                errores.append(f"ID duplicado: {lugar_id}")
            ids_vistos.add(lugar_id)
    
    for idx, lugar in enumerate(lugares):
        if "padre_id" in lugar and lugar["padre_id"]:
            padre_id = lugar["padre_id"]
            if padre_id not in ids_vistos:
                errores.append(f"Lugar [{idx}] ({lugar.get('nombre', '?')}): padre_id '{padre_id}' no existe")
            else:
                padre = next((l for l in lugares if l.get("id") == padre_id), None)
                if padre:
                    tipo_hijo = lugar.get("tipo")
                    tipo_padre = padre.get("tipo")
                    if tipo_hijo in ("pueblo", "ciudad_pequena", "ciudad_grande") and tipo_padre != "municipio":
                        errores.append(f"Tipo '{tipo_hijo}' '{lugar['nombre']}' debe tener padre municipio, no '{tipo_padre}'")
                    elif tipo_hijo == "distrito" and tipo_padre != "ciudad_grande":
                        errores.append(f"Distrito '{lugar['nombre']}' debe tener padre ciudad_grande, no '{tipo_padre}'")
                    elif tipo_hijo == "barrio" and tipo_padre not in ("distrito", "ciudad_grande", "ciudad_pequena"):
                        errores.append(f"Barrio '{lugar['nombre']}' tiene padre inválido de tipo '{tipo_padre}'")
                    elif tipo_hijo == "barrio" and tipo_padre == "distrito":
                        abuelo_id = lugar.get("abuelo_id")
                        if not abuelo_id:
                            errores.append(f"Barrio '{lugar['nombre']}' dentro de distrito requiere abuelo_id")
                        elif abuelo_id not in ids_vistos:
                            errores.append(f"Barrio '{lugar['nombre']}': abuelo_id '{abuelo_id}' no existe")
                        else:
                            abuelo = next((l for l in lugares if l.get("id") == abuelo_id), None)
                            if abuelo and abuelo.get("tipo") not in ("ciudad_grande", "municipio"):
                                errores.append(f"Barrio '{lugar['nombre']}' debe tener abuelo ciudad_grande o municipio, no '{abuelo.get('tipo') if abuelo else 'None'}'")
    
    es_valido = len(errores) == 0
    return es_valido, errores

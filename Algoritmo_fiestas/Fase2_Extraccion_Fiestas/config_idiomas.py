# config_idiomas.py

from typing import Dict, Any

# Definición de los motores disponibles
MOTOR_FASTTEXT = "fasttext"
MOTOR_OPUS = "opus-mt"
MOTOR_APERTIUM = "apertium"

# Diccionario maestro de perfiles de idiomas
PERFILES_IDIOMA = {
    "castellano": {
        "id_idioma": "es",
        "keywords_busqueda": ["fiestas patronales", "programa fiestas", "cartel fiestas", "eventos", "actividades"],
        "terminos_rag": "Fiestas, programa, cartel, eventos, actividades",
        "motor_traduccion": None,  # No necesita traducción
        "modelo_id": None
    },
    "catalan": {
        "id_idioma": "ca",
        "keywords_busqueda": ["festa major", "festes patronals", "programa festes", "cartell festes", "esdeveniments"],
        "terminos_rag": "Fiestas, programa, cartel / Festa major, festes, cartell",
        "motor_traduccion": MOTOR_OPUS,
        "modelo_id": "Helsinki-NLP/opus-mt-ca-es"
    },
    "valenciano": {
        "id_idioma": "ca-valencia", # Usamos tag técnico
        "keywords_busqueda": ["festa major", "festes patronals", "programa festes", "cartell festes"],
        "terminos_rag": "Fiestas, programa, cartel / Festa major, festes, cartell",
        "motor_traduccion": MOTOR_APERTIUM,
        "modelo_id": "cat_valencia" # Bandera de variante en apertium-spa-cat
    },
    "gallego": {
        "id_idioma": "gl",
        "keywords_busqueda": ["festas patronais", "programa de festas", "cartel festas", "eventos"],
        "terminos_rag": "Fiestas, programa, cartel / Festas patronais, programa, cartel",
        "motor_traduccion": MOTOR_OPUS,
        "modelo_id": "Helsinki-NLP/opus-mt-gl-es"
    },
    "euskera": {
        "id_idioma": "eu",
        "keywords_busqueda": ["jaiak", "jai egitaraua", "festak", "kartela"],
        "terminos_rag": "Fiestas, programa, cartel / Jaiak, jai egitaraua, festak",
        "motor_traduccion": MOTOR_OPUS,
        "modelo_id": "Helsinki-NLP/opus-mt-eu-es"
    },
    "aranes": {
        "id_idioma": "oc-aran",
        "keywords_busqueda": ["hèsta major", "hèstes patronaus", "programa"],
        "terminos_rag": "Fiestas, programa / Hèsta major, hèstes",
        "motor_traduccion": MOTOR_APERTIUM,
        "modelo_id": "oci_aran" # Bandera de variante en apertium-spa-oci
    }
}

def comunidad_de(lugar: Dict[str, Any]) -> str:
    """
    La comunidad autónoma de un lugar del dataset, se llame como se llame el campo.

    El dataset de Fase 1 la guarda en `comunidad`; el código la leía en cuatro
    sitios como `comunidad_autonoma`, que NINGUNO de sus 9.752 lugares tiene.
    Resultado: la comunidad iba vacía en la construcción de consultas y en la
    elección del perfil de idioma —el que decide con qué lengua se busca y se
    filtra—, en todas las ejecuciones y para todos los municipios, incluidos los
    vascos. Se conserva la clave larga como respaldo por si otra fuente la usa.

    Existe como función para que el nombre del campo se decida en un solo sitio:
    repetir el respaldo en cada llamada es como volvió a colarse la primera vez.
    """
    if not isinstance(lugar, dict):
        return ""
    return (lugar.get("comunidad") or lugar.get("comunidad_autonoma") or "").strip()


def perfil_de_lugar(municipio: Dict[str, Any]) -> Dict[str, Any]:
    """Perfil lingüístico de un municipio del dataset, sin equivocarse de campo."""
    return get_language_profile(comunidad_de(municipio), (municipio or {}).get("provincia", ""))


def get_language_profile(comunidad_autonoma: str, provincia: str = "") -> Dict[str, Any]:
    """
    Retorna el perfil lingüístico aplicable (o múltiples si hay complejidad regional).
    Devuelve un diccionario con la estructura principal y los idiomas a detectar.
    """
    comunidad = comunidad_autonoma.lower() if comunidad_autonoma else ""
    provincia_lower = provincia.lower() if provincia else ""
    
    # Castellano por defecto
    resultado = {
        "perfil_principal": PERFILES_IDIOMA["castellano"],
        "idiomas_a_detectar": ["es"] # Fasttext labels
    }
    
    # Lógica por comunidad
    if "cataluña" in comunidad or "catalunya" in comunidad:
        if "lérida" in provincia_lower or "lleida" in provincia_lower:
            # Excepción Valle de Arán / Provincia de Lérida
            resultado["perfil_principal"] = PERFILES_IDIOMA["catalan"]
            # Añadimos aranes (oc) al radar de fasttext
            resultado["idiomas_a_detectar"] = ["es", "ca", "oc"]
            # Agregamos el perfil aranés por si fasttext lo detecta
            resultado["perfil_secundario"] = PERFILES_IDIOMA["aranes"]
        else:
            resultado["perfil_principal"] = PERFILES_IDIOMA["catalan"]
            resultado["idiomas_a_detectar"] = ["es", "ca"]
            
    elif "valenciana" in comunidad:
        resultado["perfil_principal"] = PERFILES_IDIOMA["valenciano"]
        resultado["idiomas_a_detectar"] = ["es", "ca"] # fasttext lo detecta como ca
        
    elif "balear" in comunidad:
        resultado["perfil_principal"] = PERFILES_IDIOMA["catalan"]
        resultado["idiomas_a_detectar"] = ["es", "ca"]
        
    elif "galicia" in comunidad:
        resultado["perfil_principal"] = PERFILES_IDIOMA["gallego"]
        resultado["idiomas_a_detectar"] = ["es", "gl"]
        
    elif "vasco" in comunidad or "euskadi" in comunidad or "navarra" in comunidad:
        resultado["perfil_principal"] = PERFILES_IDIOMA["euskera"]
        resultado["idiomas_a_detectar"] = ["es", "eu"]
        
    return resultado

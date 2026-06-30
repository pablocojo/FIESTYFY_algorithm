import json
import re
import os
import time

from scraper import fetch_url
from extractors import _extraer_texto_wikipedia_para_descripcion
from llm_client import call_llm

JSON_FILE = "lugares_espana.json"
ERROR_LOG = "lugares_espana_error_log.txt"

def main():
    print("\n" + "=" * 70)
    print(" REPARACIÓN DE DESCRIPCIONES (FALLBACK Y ENCODING)")
    print("=" * 70 + "\n")
    
    # 1. Encontrar los lugares con errores en el log
    lugares_con_error = set()
    if os.path.exists(ERROR_LOG):
        with open(ERROR_LOG, "r", encoding="utf-8", errors="ignore") as f:
            contenido = f.read()
            # Buscar el nombre en los bloques de contexto de error
            matches = re.findall(r'"lugar":\s*"([^"]+)"', contenido)
            for m in matches:
                lugares_con_error.add(m)
                
    # 2. Cargar JSON
    print(f"Cargando {JSON_FILE}...")
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: No se encontró {JSON_FILE}")
        return
        
    lugares = data.get("lugares", [])
    
    # 3. Identificar lugares que necesitan reparación
    para_reparar = []
    for l in lugares:
        desc = l.get("descripcion", "")
        desc_corta = l.get("descripcion_corta", "")
        nombre = l.get("nombre", "")
        
        # Consideramos problemático si su nombre aparece en el log de errores
        # O si el texto tiene caracteres de error típicos (, Ǹ, ǭ, Ã, etc.)
        es_problematico = (
            nombre in lugares_con_error or 
            "" in desc or "" in desc_corta or 
            "Ǹ" in desc or "ǭ" in desc or 
            "Ã" in desc or "" in desc
        )
        
        if es_problematico and l.get("wikipedia_url"):
            para_reparar.append(l)
                
    print(f"Se encontraron {len(para_reparar)} lugares para reparar.\n")
    
    if not para_reparar:
        print("No hay descripciones que reparar. ¡Todo está correcto!")
        return
        
    # 4. Reparar usando LLM con prompt estricto
    reparados_con_exito = 0
    for i, lugar in enumerate(para_reparar):
        print(f"[{i+1}/{len(para_reparar)}] Reparando: {lugar['nombre']}...")
        
        html = fetch_url(lugar["wikipedia_url"])
        if not html:
            print("  -> Error: No se pudo descargar la página de Wikipedia.")
            continue
            
        texto_wiki = _extraer_texto_wikipedia_para_descripcion(html)
        if not texto_wiki:
            print("  -> Error: No se pudo extraer texto del artículo.")
            continue
            
        system_prompt = (
            "Eres un redactor experto para una app de turismo en España. "
            "Tu tarea es crear una descripción de este lugar basándote en el texto proporcionado. "
            "REGLAS OBLIGATORIAS:\n"
            "1. RESPONDE ÚNICAMENTE CON UN JSON VÁLIDO. DEBES ASEGURARTE DE CERRAR LA ÚLTIMA LLAVE '}' DEL JSON.\n"
            "2. NO escribas NINGÚN texto fuera del JSON.\n"
            "3. NO menciones la población, ni el censo, ni la cantidad de habitantes. Enfócate en geografía, historia, cultura, fiestas o monumentos.\n"
            "4. Idioma: Español castellano correcto (usa tildes y eñes correctamente).\n"
            "5. NO incluyas ninguna coma al final del último elemento del JSON.\n"
        )
        
        user_prompt = (
            f"Lugar: {lugar['nombre']}\n"
            f"Tipo: {lugar.get('tipo', 'desconocido')}\n\n"
            "Formato de salida esperado (ESTRICTO):\n"
            "{\n"
            "  \"descripcion_corta\": \"Una sola frase (máximo 15 palabras) resumiendo qué es y dónde está el lugar.\",\n"
            "  \"descripcion\": \"Texto fluido de entre 50 y 80 palabras. SIN MENCIONAR HABITANTES NI POBLACIÓN. Habla del entorno natural, cultura o historia.\"\n"
            "}\n\n"
            f"Texto fuente:\n{texto_wiki}"
        )
        
        resp = call_llm(system_prompt, user_prompt, context_info={'stage': 'repair_desc', 'lugar': lugar['nombre']})
        
        if resp:
            try:
                # Heurística para arreglar el JSON si el LLM lo vuelve a dejar a medias
                resp_clean = resp.strip()
                if not resp_clean.endswith("}"):
                    if resp_clean.endswith("\""):
                        resp_clean += "\n}"
                    elif resp_clean.endswith("."):
                        resp_clean += "\"\n}"
                    else:
                        resp_clean += ".\"\n}"
                        
                # Limpiar comillas markdown si el LLM las pone
                resp_clean = re.sub(r'^```json\s*', '', resp_clean)
                resp_clean = re.sub(r'\s*```$', '', resp_clean)
                
                parsed = json.loads(resp_clean)
                
                if parsed.get("descripcion") and parsed.get("descripcion_corta"):
                    lugar["descripcion"] = parsed["descripcion"]
                    lugar["descripcion_corta"] = parsed["descripcion_corta"]
                    print("  -> ¡Reparado con éxito!")
                    reparados_con_exito += 1
                else:
                    print("  -> El JSON no contenía los campos esperados.")
            except json.JSONDecodeError as e:
                print(f"  -> Falló al parsear el JSON del LLM: {e}")
                print(f"  -> Respuesta bruta: {resp[:100]}...")
        else:
            print("  -> Error: El LLM no devolvió ninguna respuesta.")
                
        time.sleep(1.5) # Pausa para no saturar la API
        
        # Guardar progreso cada 10 lugares reparados
        if (i + 1) % 10 == 0:
            with open(JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
    # Guardado final
    print("\nGuardando resultados finales...")
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print(f"\nProceso finalizado. Se repararon {reparados_con_exito}/{len(para_reparar)} lugares.")

if __name__ == "__main__":
    main()

# revalidar_compuestos.py
"""
Script de revalidación de municipios compuestos.

Lee municipios.json, busca todos los que tienen tipo='municipio_compuesto',
y los pasa por el nuevo algoritmo es_municipio_compuesto() (LLM como único
decisor). Si el nuevo algoritmo dice que NO es compuesto, lo reclasifica
según su población.

Guarda progreso tras cada municipio procesado, de modo que se puede
interrumpir con Ctrl+C y reanudar sin perder trabajo.

Uso:
    python revalidar_compuestos.py
"""

import json
import os
import shutil
import time
import datetime

import requests

from config import (
    MUNICIPIOS_JSON,
    WIKIPEDIA_API_URL,
    DELAY_BETWEEN_REQUESTS,
    COMPUESTO_MIN_CONFIDENCE,
)
from datos_ine import cargar_datos_ine, buscar_municipio_ine, formatear_localidades_para_prompt
from extractors import _recoger_senales_compuesto, extract_imagenes
from llm_client import call_llm, contar_tokens
from logger import dump_error_log, log_error, safe_print
from place_types import clasificar_por_poblacion


BACKUP_REVALIDACION = "municipios_pre_revalidacion.json"
LOG_FILE = "revalidar_compuestos_log.txt"
INFORME_FILE = "revalidar_compuestos_informe.md"

# Fichero de progreso: guarda los IDs ya procesados para poder reanudar
PROGRESO_FILE = "revalidar_compuestos_progreso.json"


# Fichero de revision manual de evaluaciones de compuesto
_COMPUESTOS_REVIEW_FILE = 'compuestos_revision_manual.jsonl'


def _registrar_evaluacion_compuesto(
    nombre: str,
    es_compuesto: bool,
    confianza: float,
    razon: str,
    categoria: str,
) -> None:
    """
    Registra cada evaluacion de municipio compuesto en un fichero JSONL
    para revision manual posterior.
    """
    import datetime
    registro = {
        'timestamp': datetime.datetime.now().isoformat(),
        'nombre': nombre,
        'resultado': 'municipio_compuesto' if es_compuesto else 'pueblo',
        'confianza': round(confianza, 3),
        'categoria': categoria,
        'razon': razon,
    }
    try:
        with open(_COMPUESTOS_REVIEW_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(registro, ensure_ascii=False) + '\n')
    except Exception:
        pass  # No fallar el proceso principal por un log


def es_municipio_compuesto_con_ine(
    html: str,
    nombre: str,
    localidades_ine: list[dict] | None = None,
    poblacion_ine: int | None = None,
    nombre_en_localidades_ine: bool | None = None,
) -> tuple[bool, str]:
    """
    Determina si un municipio es compuesto usando senales + datos INE + LLM.

    Flujo:
    1. Pre-filtro INE: si el nombre del municipio coincide con una localidad
       del INE, NO es compuesto (existe un nucleo fisico con ese nombre).
    2. Recoger senales estructurales del HTML.
    3. Si las senales NO indican nada sospechoso, devolver False sin LLM.
    4. Si hay indicios, consultar al LLM con contexto enriquecido
       (incluye localidades y poblacion del INE).
    5. Solo devolver True si el LLM responde true con confianza >= 0.90.
    6. Ante CUALQUIER duda, devolver False (pueblo).
    7. Registrar TODA evaluacion con indicios en un log de revision.

    Args:
        html: HTML del articulo de Wikipedia.
        nombre: Nombre del municipio.
        localidades_ine: Lista de localidades del INE [{'nombre': str, 'poblacion': int}, ...].
        poblacion_ine: Poblacion oficial del INE (padron 2025).
        nombre_en_localidades_ine: Si el nombre del municipio aparece como localidad en el INE.

    Returns:
        (es_compuesto: bool, razon: str)
    """
    # --- Pre-filtro INE: si el nombre coincide con una localidad, NO es compuesto ---
    if nombre_en_localidades_ine:
        razon = (f'PRE-FILTRO INE: El nombre "{nombre}" coincide con una localidad '
                 f'registrada en el INE. Existe un nucleo fisico con ese nombre -> NO compuesto.')
        _registrar_evaluacion_compuesto(nombre, False, 0, razon, 'INE_NOMBRE_COINCIDE')
        return False, razon

    senales = _recoger_senales_compuesto(html, nombre)

    # --- Pre-filtro: si no hay NINGUN indicio, no molestar al LLM ---
    hay_indicios = (
        senales['capital_diferente_al_nombre']
        or senales['frase_agrupacion_nucleos']
        or senales['tiene_seccion_localidades']
        or senales['tiene_seccion_entidades_poblacion']
        or senales['tiene_seccion_parroquias']
        or senales['tiene_seccion_concejos']
        or senales['tipo_entidad_infobox'] in ('concejo', 'parroquia')
        or len(senales.get('categorias_relevantes', [])) > 0
    )

    # Si se autodefine como lugar fisico Y no hay ningun indicio de agrupacion
    if senales['se_autodefine_lugar_fisico'] and not hay_indicios:
        return False, f'Se autodefine como lugar fisico y sin indicios de agrupacion.'

    # Si no se autodefine como fisico pero tampoco hay indicios de nada
    if not hay_indicios and not senales['texto_contexto']:
        return False, 'Sin indicios de compuesto ni contexto para analizar.'

    # --- Hay indicios: consultar al LLM ---
    senales_resumen = (
        f"SENALES ESTRUCTURALES DETECTADAS:\n"
        f"- El articulo define a {nombre} como un lugar fisico (pueblo/villa/ciudad): "
        f"{'SI' if senales['se_autodefine_lugar_fisico'] else 'NO'}\n"
        f"- La capital del municipio tiene nombre diferente a {nombre}: "
        f"{'SI' if senales['capital_diferente_al_nombre'] else 'NO'}\n"
        f"- Tiene seccion de Localidades: "
        f"{'SI' if senales['tiene_seccion_localidades'] else 'NO'}\n"
        f"- Tiene seccion de Entidades de poblacion / Nucleos: "
        f"{'SI' if senales['tiene_seccion_entidades_poblacion'] else 'NO'}\n"
        f"- Tiene seccion de Parroquias: "
        f"{'SI' if senales['tiene_seccion_parroquias'] else 'NO'}\n"
        f"- Tiene seccion de Concejos: "
        f"{'SI' if senales['tiene_seccion_concejos'] else 'NO'}\n"
        f"- Tiene seccion de Pedanias: "
        f"{'SI' if senales['tiene_seccion_pedanias'] else 'NO'}\n"
        f"- Tiene seccion de Barrios: "
        f"{'SI' if senales['tiene_seccion_barrios'] else 'NO'}\n"
        f"- Tiene seccion de Distritos: "
        f"{'SI' if senales['tiene_seccion_distritos'] else 'NO'}\n"
        f"- Frase de agrupacion de nucleos en parrafos iniciales: "
        f"{'SI' if senales['frase_agrupacion_nucleos'] else 'NO'}\n"
        f"- Tipo de entidad en infobox: "
        f"{senales['tipo_entidad_infobox'] or 'no detectado'}\n"
        f"- Categorias y subpaginas relevantes: "
        f"{', '.join(senales['categorias_relevantes']) if senales.get('categorias_relevantes') else 'Ninguna detectada'}\n"
    )

    system_prompt = (
        "Eres un clasificador experto de geografia administrativa espanola. "
        "Tu UNICA tarea es decidir si un municipio es un municipio_compuesto "
        "para un dataset de fiestas locales. Responde SOLO JSON valido."
    )

    user_prompt = (
        f"MUNICIPIO A CLASIFICAR: {nombre}\n\n"
        "===== DEFINICION =====\n"
        "Un municipio_compuesto es una entidad PURAMENTE ADMINISTRATIVA que NO "
        "corresponde a un lugar fisico real. No es un pueblo, villa ni ciudad "
        "donde puedas ir y decir 'estoy en X'. Es una agrupacion administrativa "
        "de varias localidades/nucleos/parroquias/aldeas.\n\n"
        "===== REGLAS DE DECISION =====\n"
        "1. Si el articulo describe a este municipio como un pueblo, villa, ciudad "
        "o localidad fisica, NO es compuesto, aunque tenga pedanias, barrios, "
        "aldeas o nucleos asociados. Un pueblo con pedanias sigue siendo un pueblo.\n"
        "2. Si tiene seccion de Barrios o Distritos, eso REFUERZA que es un "
        "lugar fisico (ciudades/pueblos reales se dividen en barrios/distritos).\n"
        "3. Solo es compuesto si el nombre del municipio designa al CONJUNTO "
        "ADMINISTRATIVO y la realidad fisica se reparte entre varias localidades, "
        "sin que exista un nucleo principal con el mismo nombre.\n"
        "4. Si un nucleo/localidad dentro del municipio tiene el mismo nombre "
        "que el municipio, NO es compuesto: es un lugar fisico con hijos.\n"
        "5. Que tenga seccion de Localidades o Entidades de poblacion NO basta "
        "por si solo: muchos pueblos reales listan sus aldeas y pedanias asi.\n"
        "6. ANTE LA DUDA, responde false. La inmensa mayoria de municipios "
        "espanoles SI son lugares fisicos. El compuesto es la EXCEPCION.\n\n"
        "===== EJEMPLOS =====\n"
        "COMPUESTO (true):\n"
        "- Puentes Viejas: municipio formado por Cinco Villas, Mangirón, etc. "
        "No existe un pueblo llamado 'Puentes Viejas'.\n"
        "- El Barco de Ávila: si el articulo dice que es 'un municipio que "
        "comprende las localidades de...' y no existe como nucleo propio.\n\n"
        "NO COMPUESTO (false):\n"
        "- Alcoy: 'es una ciudad espanola...' → es un lugar fisico real.\n"
        "- Torrox: 'es un municipio y pueblo...' → lugar fisico con pedanias.\n"
        "- Madrid: ciudad grande con distritos → lugar fisico.\n"
        "- Un pueblo con seccion 'Localidades' que lista aldeas → lugar fisico "
        "con nucleos dependientes.\n\n"
        f"{senales_resumen}\n"
    )

    # --- Añadir datos del INE si están disponibles ---
    datos_ine_texto = ""
    if localidades_ine is not None:
        datos_ine_texto = (
            "===== DATOS OFICIALES DEL INE (Padron 2025) =====\n"
        )
        if poblacion_ine is not None:
            datos_ine_texto += f"Poblacion oficial del municipio: {poblacion_ine} habitantes\n"
        datos_ine_texto += formatear_localidades_para_prompt(localidades_ine) + "\n"
        if nombre_en_localidades_ine is False:
            datos_ine_texto += (
                f"NOTA: El nombre '{nombre}' NO aparece como localidad en los registros del INE. "
                f"Esto sugiere que NO existe un nucleo fisico con ese nombre.\n"
            )
        datos_ine_texto += "\n"

    user_prompt += (
        f"{datos_ine_texto}"
        "===== TEXTO DE WIKIPEDIA =====\n"
        f"{senales['texto_contexto']}\n\n"
        "===== FORMATO DE RESPUESTA (JSON) =====\n"
        "{\"es_municipio_compuesto\": boolean, \"confianza\": number (0-1), "
        "\"razon\": \"explicacion breve\"}\n"
        "Usa confianza >= 0.90 SOLO si hay evidencia clara e inequivoca."
    )

    resp = call_llm(
        system_prompt,
        user_prompt,
        context_info={'stage': 'clasificar_municipio_compuesto', 'lugar': nombre},
    )

    # --- Ante cualquier error del LLM: duda = pueblo ---
    if not resp or not resp.strip():
        razon = 'LLM sin respuesta; duda -> pueblo.'
        _registrar_evaluacion_compuesto(nombre, False, 0, razon, 'LLM_SIN_RESPUESTA')
        return False, razon

    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        razon = 'Respuesta LLM invalida; duda -> pueblo.'
        _registrar_evaluacion_compuesto(nombre, False, 0, razon, 'JSON_INVALIDO')
        return False, razon

    valor_compuesto = data.get('es_municipio_compuesto')
    if isinstance(valor_compuesto, bool):
        es_compuesto_val = valor_compuesto
    elif isinstance(valor_compuesto, str):
        es_compuesto_val = valor_compuesto.strip().lower() == 'true'
    else:
        es_compuesto_val = False

    try:
        confidence = float(data.get('confianza') or data.get('confidence') or 0)
    except (TypeError, ValueError):
        confidence = 0

    razon_llm = str(data.get('razon') or data.get('reason') or '')

    if es_compuesto_val and confidence >= COMPUESTO_MIN_CONFIDENCE:
        razon = f'LLM: compuesto (confianza {confidence:.2f}). {razon_llm}'
        _registrar_evaluacion_compuesto(nombre, True, confidence, razon, 'COMPUESTO_CONFIRMADO')
        return True, razon

    if es_compuesto_val:
        # LLM dijo compuesto pero con poca confianza => duda => pueblo
        razon = f'LLM dijo compuesto pero confianza baja ({confidence:.2f} < {COMPUESTO_MIN_CONFIDENCE}). Duda -> pueblo. {razon_llm}'
        _registrar_evaluacion_compuesto(nombre, False, confidence, razon, 'DUDA_BAJA_CONFIANZA')
        return False, razon

    razon = f'LLM: NO compuesto (confianza {confidence:.2f}). {razon_llm}'
    _registrar_evaluacion_compuesto(nombre, False, confidence, razon, 'NO_COMPUESTO')
    return False, razon


def cargar_dataset() -> dict:
    with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_dataset(data: dict) -> None:
    with open(MUNICIPIOS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_progreso() -> set:
    """Carga IDs ya procesados en ejecuciones anteriores."""
    if not os.path.exists(PROGRESO_FILE):
        return set()
    try:
        with open(PROGRESO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("procesados", []))
    except Exception:
        return set()


def guardar_progreso(procesados: set) -> None:
    with open(PROGRESO_FILE, "w", encoding="utf-8") as f:
        json.dump({"procesados": list(procesados)}, f, ensure_ascii=False)


def descargar_html(wikipedia_url: str) -> tuple[str, str | None]:
    """
    Descarga el HTML del artículo de Wikipedia a partir de su URL.
    Usa la API de Wikipedia (action=parse) para obtener el contenido renderizado.
    """
    if not wikipedia_url:
        return "", "Sin URL de Wikipedia"

    # Extraer el título de la página desde la URL
    try:
        import urllib.parse
        parts = wikipedia_url.split("/wiki/")
        if len(parts) < 2:
            parts = wikipedia_url.split("title=")
        if len(parts) < 2:
            return "", "No se pudo extraer el título de la URL"
        page_title = urllib.parse.unquote(parts[-1].split("&")[0])
    except Exception as e:
        return "", f"Error parseando URL: {e}"

    headers = {
        "User-Agent": "Fiestyfy/Revalidacion (FIESTYFY_algorithm; contact: pablocojo@example.com)"
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            params = {
                "action": "parse",
                "page": page_title,
                "prop": "text",
                "redirects": 1,
                "format": "json",
            }
            time.sleep(1.5)
            resp = requests.get(WIKIPEDIA_API_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return "", f"Wikipedia API error: {data['error'].get('info', 'desconocido')}"
            if "parse" in data and "text" in data["parse"]:
                return data["parse"]["text"]["*"], None
        except Exception as e:
            if attempt == max_retries - 1:
                return "", f"Error de red tras {max_retries} intentos: {e}"
            time.sleep(1)

    return "", "No se pudo obtener el HTML"


def test_llm_connection() -> bool:
    """Comprueba si LM Studio está activo."""
    from config import LMSTUDIO_API
    try:
        base_url = LMSTUDIO_API.split("/v1/")[0]
        requests.get(base_url, timeout=3)
        return True
    except Exception:
        return False


def main():
    safe_print("\n" + "=" * 70)
    safe_print(" REVALIDACION DE MUNICIPIOS COMPUESTOS")
    safe_print(" Nuevo algoritmo: LLM como unico decisor")
    safe_print("=" * 70 + "\n")

    # Verificar que el JSON existe
    if not os.path.exists(MUNICIPIOS_JSON):
        safe_print(f"ERROR: No se encontro {MUNICIPIOS_JSON}.")
        safe_print("Ejecuta primero la Fase 1 (main.py).")
        return

    # Verificar LLM
    if test_llm_connection():
        safe_print("OK: Conexion con LM Studio detectada.\n")
    else:
        safe_print("ERROR: No se detecto LM Studio en el puerto 1234.")
        safe_print("Arranca LM Studio antes de ejecutar este script.")
        return

    # Cargar dataset
    data = cargar_dataset()
    lugares = data.get("lugares", [])
    total_lugares = len(lugares)

    # Cargar tablas INE (una sola vez)
    try:
        datos_ine = cargar_datos_ine()
    except Exception as e:
        safe_print(f"ERROR: No se pudieron cargar las tablas INE: {e}")
        safe_print("Asegurate de que los ficheros pobmun25.xlsx y nomdef2025.xlsx")
        safe_print("estan en la carpeta datos_municipios/.")
        return

    # Filtrar compuestos
    compuestos_filtrados = [(i, l) for i, l in enumerate(lugares) if l["tipo"] == "municipio_compuesto"]
    total_compuestos = len(compuestos_filtrados)
    
    # Añadir índice (1-N) a cada compuesto para poder referenciarlo
    compuestos = [(i, l, c_idx) for c_idx, (i, l) in enumerate(compuestos_filtrados, start=1)]

    if total_compuestos == 0:
        safe_print("No hay municipios compuestos en el dataset. Nada que revalidar.")
        return

    safe_print(f"Dataset: {total_lugares} municipios totales, {total_compuestos} compuestos.\n")

    # Preguntar al usuario si quiere empezar desde un punto especifico
    start_index_str = input(f"¿Desde que numero de municipio compuesto empezar? (1-{total_compuestos}) [Enter = reanudar progreso]: ").strip()
    
    # Cargar progreso previo
    ya_procesados = cargar_progreso()
    
    ignorar_progreso = False
    if start_index_str.isdigit():
        start_index = int(start_index_str)
        if 1 <= start_index <= total_compuestos:
            compuestos = compuestos[start_index - 1:]
            ignorar_progreso = True
            safe_print(f"\nForzando inicio desde el #{start_index}. Se ignorara el progreso guardado para este y los siguientes.")
            
    if ignorar_progreso:
        # Quitamos de ya_procesados los IDs que vamos a procesar forzosamente
        for _, l, _ in compuestos:
            ya_procesados.discard(l["id"])
            
    pendientes = [(i, l, c_idx) for i, l, c_idx in compuestos if l["id"] not in ya_procesados]

    if not pendientes:
        safe_print("Todos los municipios compuestos seleccionados ya fueron procesados.")
        safe_print(f"Para re-ejecutar desde cero, borra {PROGRESO_FILE}\n")
        return

    if ya_procesados and not ignorar_progreso:
        safe_print(f"Reanudando: {len(ya_procesados)} ya procesados globalmente, {len(pendientes)} en esta cola.\n")

    # Crear backup solo si es la primera vez
    if not ya_procesados:
        safe_print(f"Creando backup en {BACKUP_REVALIDACION}...")
        try:
            shutil.copyfile(MUNICIPIOS_JSON, BACKUP_REVALIDACION)
            safe_print("Backup creado correctamente.\n")
        except Exception as e:
            safe_print(f"ADVERTENCIA: No se pudo crear backup: {e}\n")

    # Resultados para informe
    resultados = []
    cambios_tipo = 0
    errores = 0

    safe_print("Procesando municipios compuestos uno a uno...\n")
    safe_print(f"{'#':>4}  {'Municipio':<45} {'Resultado':<20} {'Razon'}")
    safe_print("-" * 120)

    try:
        for i, lugar, comp_idx in pendientes:
            idx = i  # indice global en la lista lugares
            nombre = lugar["nombre"]
            lugar_id = lugar["id"]
            wiki_url = lugar.get("wikipedia_url", "")
            provincia = lugar.get("provincia", "")

            # Buscar datos del INE para este municipio
            info_ine = buscar_municipio_ine(nombre, provincia, datos_ine)
            localidades_ine = None
            poblacion_ine = None
            nombre_en_localidades_ine = None

            if info_ine:
                localidades_ine = info_ine['localidades']
                poblacion_ine = info_ine['poblacion_ine']
                nombre_en_localidades_ine = info_ine['nombre_en_localidades']

                # Actualizar población del JSON con dato oficial del INE
                if poblacion_ine and poblacion_ine > 0:
                    lugares[idx]["poblacion"] = poblacion_ine

            # Descargar HTML
            html, error = descargar_html(wiki_url)
            if not html:
                resultado = {
                    "nombre": nombre,
                    "id": lugar_id,
                    "tipo_anterior": "municipio_compuesto",
                    "tipo_nuevo": "municipio_compuesto",
                    "cambio": False,
                    "razon": f"Error descargando HTML: {error}",
                }
                resultados.append(resultado)
                errores += 1
                safe_print(f"{comp_idx:>4}  {nombre:<45} {'ERROR':<20} {error}")
                ya_procesados.add(lugar_id)
                guardar_progreso(ya_procesados)
                continue

            # Revalidar con el nuevo algoritmo (ahora con datos INE)
            try:
                es_compuesto, razon = es_municipio_compuesto_con_ine(
                    html,
                    nombre,
                    localidades_ine=localidades_ine,
                    poblacion_ine=poblacion_ine,
                    nombre_en_localidades_ine=nombre_en_localidades_ine,
                )
            except Exception as e:
                resultado = {
                    "nombre": nombre,
                    "id": lugar_id,
                    "tipo_anterior": "municipio_compuesto",
                    "tipo_nuevo": "municipio_compuesto",
                    "cambio": False,
                    "razon": f"Error en LLM: {e}",
                }
                resultados.append(resultado)
                errores += 1
                safe_print(f"{comp_idx:>4}  {nombre:<45} {'ERROR LLM':<20} {e}")
                log_error(f"Error revalidando {nombre}: {e}")
                ya_procesados.add(lugar_id)
                guardar_progreso(ya_procesados)
                continue

            if es_compuesto:
                # Sigue siendo compuesto: no cambiar nada
                resultado = {
                    "nombre": nombre,
                    "id": lugar_id,
                    "tipo_anterior": "municipio_compuesto",
                    "tipo_nuevo": "municipio_compuesto",
                    "cambio": False,
                    "razon": razon,
                }
                resultados.append(resultado)
                safe_print(f"{comp_idx:>4}  {nombre:<45} {'CONFIRMADO':<20} {razon[:55]}")
            else:
                # Ya NO es compuesto: reclasificar por población
                nuevo_tipo = clasificar_por_poblacion(lugar.get("poblacion")) or "pueblo"
                lugares[idx]["tipo"] = nuevo_tipo
                resultado = {
                    "nombre": nombre,
                    "id": lugar_id,
                    "tipo_anterior": "municipio_compuesto",
                    "tipo_nuevo": nuevo_tipo,
                    "cambio": True,
                    "razon": razon,
                }
                resultados.append(resultado)
                cambios_tipo += 1
                safe_print(f"{comp_idx:>4}  {nombre:<45} {'-> ' + nuevo_tipo:<20} {razon[:55]}")

                # Guardar JSON tras cada cambio
                guardar_dataset(data)

            # Registrar como procesado y guardar progreso
            ya_procesados.add(lugar_id)
            guardar_progreso(ya_procesados)

            # Delay entre peticiones
            time.sleep(DELAY_BETWEEN_REQUESTS)

    except KeyboardInterrupt:
        safe_print("\n\nInterrumpido por el usuario. Guardando progreso...")
        guardar_dataset(data)
        guardar_progreso(ya_procesados)
        dump_error_log(LOG_FILE)
        safe_print(f"Progreso guardado. {len(ya_procesados)}/{total_compuestos} procesados.")
        safe_print(f"Ejecuta de nuevo para continuar desde donde se quedo.\n")
        _generar_informe(resultados, total_compuestos, cambios_tipo, errores)
        return

    # Guardar resultado final
    guardar_dataset(data)
    dump_error_log(LOG_FILE)

    # Limpiar fichero de progreso (completado)
    if os.path.exists(PROGRESO_FILE):
        os.remove(PROGRESO_FILE)

    # Informe
    _generar_informe(resultados, total_compuestos, cambios_tipo, errores)

    # Resumen en consola
    safe_print("\n" + "=" * 70)
    safe_print(f" REVALIDACION COMPLETADA")
    safe_print(f"   Compuestos analizados: {total_compuestos}")
    safe_print(f"   Reclasificados:        {cambios_tipo}")
    safe_print(f"   Confirmados:           {total_compuestos - cambios_tipo - errores}")
    safe_print(f"   Errores:               {errores}")
    safe_print(f"")
    safe_print(f"   JSON actualizado:      {MUNICIPIOS_JSON}")
    safe_print(f"   Backup original:       {BACKUP_REVALIDACION}")
    safe_print(f"   Informe:               {INFORME_FILE}")
    safe_print(f"   Log de errores:        {LOG_FILE}")
    safe_print("=" * 70 + "\n")


def _generar_informe(resultados: list, total: int, cambios: int, errores: int) -> None:
    """Genera un informe markdown con los resultados de la revalidación."""
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lineas = [
        "# Informe de Revalidación de Municipios Compuestos\n",
        f"**Fecha**: {fecha}  ",
        f"**Algoritmo**: LLM como único decisor (confianza >= 0.90)  ",
        f"**Total compuestos analizados**: {total}  ",
        f"**Reclasificados**: {cambios}  ",
        f"**Confirmados como compuestos**: {total - cambios - errores}  ",
        f"**Errores**: {errores}  \n",
    ]

    # Tabla de reclasificados
    reclasificados = [r for r in resultados if r["cambio"]]
    if reclasificados:
        lineas.append("## Municipios Reclasificados\n")
        lineas.append("| Municipio | Antes | Ahora | Razón |")
        lineas.append("|---|---|---|---|")
        for r in sorted(reclasificados, key=lambda x: x["nombre"]):
            razon = r["razon"].replace("|", "/").replace("\n", " ")
            lineas.append(
                f"| **{r['nombre']}** | `{r['tipo_anterior']}` | `{r['tipo_nuevo']}` | {razon} |"
            )
        lineas.append("")

    # Tabla de confirmados
    confirmados = [r for r in resultados if not r["cambio"] and "Error" not in r["razon"]]
    if confirmados:
        lineas.append("## Municipios Confirmados como Compuestos\n")
        lineas.append("| Municipio | Razón |")
        lineas.append("|---|---|")
        for r in sorted(confirmados, key=lambda x: x["nombre"]):
            razon = r["razon"].replace("|", "/").replace("\n", " ")
            lineas.append(f"| {r['nombre']} | {razon} |")
        lineas.append("")

    # Errores
    con_error = [r for r in resultados if "Error" in r["razon"]]
    if con_error:
        lineas.append("## Errores\n")
        lineas.append("| Municipio | Error |")
        lineas.append("|---|---|")
        for r in sorted(con_error, key=lambda x: x["nombre"]):
            lineas.append(f"| {r['nombre']} | {r['razon']} |")
        lineas.append("")

    with open(INFORME_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    safe_print(f"\nInforme guardado en {INFORME_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        safe_print("\n\nProceso interrumpido.")
    except Exception as e:
        safe_print(f"\nError no esperado: {e}")
        log_error(f"Error no esperado en revalidar_compuestos: {e}")
        dump_error_log(LOG_FILE)

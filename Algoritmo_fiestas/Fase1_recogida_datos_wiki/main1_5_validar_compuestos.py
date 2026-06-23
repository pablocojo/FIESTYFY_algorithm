# main1_5_validar_compuestos.py
"""
Fase 1.5: validacion secuencial de municipios compuestos y correccion de logos.

Procesa un municipio cada vez, guarda municipios.json tras cada municipio y
permite interrumpir con Ctrl+C conservando el progreso.
"""

import datetime
import json
import os
import shutil
import time
import urllib.parse

import requests

from config import (
    MUNICIPIOS_JSON,
    WIKIPEDIA_API_URL,
    INFORME_CAMBIOS_COMPUESTOS,
    VALIDACION_COMPUESTOS_LOG,
)
from extractors import es_municipio_compuesto, extract_imagenes
from logger import dump_error_log, log_error, safe_print
from place_types import clasificar_por_poblacion


BACKUP_JSON = "municipios_backup.json"
RESPALDO_FUENTE = "munis_hasta1800_20_junio.json"
MIN_ITEMS_RESTORE = 10


def test_llm_connection() -> bool:
    """
    Comprueba si LM Studio esta activo.
    """
    from config import LMSTUDIO_API

    try:
        base_url = LMSTUDIO_API.split("/v1/")[0]
        requests.get(base_url, timeout=2)
        return True
    except Exception:
        return False


def restaurar_si_hace_falta() -> None:
    """
    Restaura un respaldo si municipios.json no existe o parece vacio/corrupto.
    """
    intentar_restaurar = False
    if not os.path.exists(MUNICIPIOS_JSON):
        intentar_restaurar = True
    else:
        try:
            with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
                data_test = json.load(f)
            if len(data_test.get("lugares", [])) < MIN_ITEMS_RESTORE:
                intentar_restaurar = True
        except Exception:
            intentar_restaurar = True

    if intentar_restaurar and os.path.exists(RESPALDO_FUENTE):
        safe_print(f"Restaurando progreso desde {RESPALDO_FUENTE} a {MUNICIPIOS_JSON}...")
        shutil.copyfile(RESPALDO_FUENTE, MUNICIPIOS_JSON)
        safe_print("Restauracion completada.\n")


def cargar_dataset() -> dict:
    with open(MUNICIPIOS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_dataset(data: dict) -> None:
    with open(MUNICIPIOS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extraer_page_title(wiki_url: str) -> str | None:
    if not wiki_url:
        return None
    try:
        parts = wiki_url.split("/wiki/")
        if len(parts) < 2:
            parts = wiki_url.split("title=")
        if len(parts) < 2:
            return None
        return urllib.parse.unquote(parts[-1].split("&")[0])
    except Exception:
        return None


def descargar_html_wikipedia(page_title: str, headers: dict) -> tuple[str, str | None]:
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
    return "", "No se pudo obtener el contenido HTML del articulo"


def procesar_lugar(lugar: dict, headers: dict) -> dict:
    """
    Procesa un unico municipio y devuelve los cambios aplicados.
    """
    resultado = {
        "id": lugar["id"],
        "nombre": lugar["nombre"],
        "tipo_anterior": lugar["tipo"],
        "tipo_nuevo": lugar["tipo"],
        "logo_anterior": lugar.get("imagenes", {}).get("logo", ""),
        "logo_nuevo": lugar.get("imagenes", {}).get("logo", ""),
        "cambio_tipo": False,
        "cambio_logo": False,
        "error": None,
        "razon": "No requiere revalidacion de tipo (no era compuesto)",
    }

    page_title = extraer_page_title(str(lugar.get("wikipedia_url") or ""))
    if not page_title:
        resultado["error"] = "Sin URL de Wikipedia valida"
        resultado["razon"] = "El municipio no tiene una URL de Wikipedia asociada."
        return resultado

    html, error = descargar_html_wikipedia(page_title, headers)
    if not html:
        resultado["error"] = error
        return resultado

    try:
        imagenes_nuevas = extract_imagenes(html, lugar["id"])
        nuevo_logo = imagenes_nuevas.get("logo")
        if nuevo_logo and nuevo_logo != resultado["logo_anterior"]:
            resultado["logo_nuevo"] = nuevo_logo
            resultado["cambio_logo"] = True
    except Exception as e:
        log_error(f"Error extrayendo logo para {lugar['nombre']}: {e}")

    if lugar["tipo"] == "municipio_compuesto":
        try:
            es_compuesto, razon = es_municipio_compuesto(html, lugar["nombre"])
            resultado["razon"] = razon
            if not es_compuesto:
                resultado["tipo_nuevo"] = clasificar_por_poblacion(lugar.get("poblacion")) or "pueblo"
                resultado["cambio_tipo"] = True
        except Exception as e:
            resultado["error"] = f"Error en validacion de compuesto: {e}"
            resultado["razon"] = f"Error al procesar: {e}"
            log_error(f"Error validando compuesto para {lugar['nombre']}: {e}")

    return resultado


def aplicar_resultado(lugar: dict, resultado: dict) -> tuple[int, int]:
    """
    Aplica cambios al lugar en memoria. Devuelve (cambio_tipo, cambio_logo).
    """
    cambio_tipo = 0
    cambio_logo = 0

    if resultado["cambio_logo"]:
        lugar.setdefault("imagenes", {})["logo"] = resultado["logo_nuevo"]
        cambio_logo = 1

    if resultado["cambio_tipo"]:
        lugar["tipo"] = resultado["tipo_nuevo"]
        cambio_tipo = 1

    return cambio_tipo, cambio_logo


def generar_informe(resultados_proceso: dict, total_lugares: int, total_cambios_tipo: int, total_cambios_logo: int) -> None:
    fecha_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reporte_md = [
        "# Informe de Cambios - Validacion de Municipios Compuestos (Fase 1.5)\n",
        f"**Fecha de ejecucion**: {fecha_str}  ",
        f"**Total de municipios en el dataset**: {total_lugares}  ",
        f"**Municipios reclasificados**: {total_cambios_tipo}  ",
        f"**Logos actualizados**: {total_cambios_logo}  \n",
        "## Resumen de Decisiones de Reclasificacion\n",
        "| Municipio | Tipo Anterior | Tipo Nuevo | Cambio Logo | Razon / Detalle |",
        "|---|---|---|---|---|",
    ]

    for _lid, res in sorted(resultados_proceso.items(), key=lambda item: item[1]["nombre"]):
        if res["cambio_tipo"] or res["tipo_anterior"] == "municipio_compuesto":
            logo_status = "Si" if res["cambio_logo"] else "No"
            razon_limpia = str(res["razon"]).replace("\n", " ").replace("|", "/")
            reporte_md.append(
                f"| **{res['nombre']}** | `{res['tipo_anterior']}` | `{res['tipo_nuevo']}` | {logo_status} | {razon_limpia} |"
            )

    with open(INFORME_CAMBIOS_COMPUESTOS, "w", encoding="utf-8") as f:
        f.write("\n".join(reporte_md))


def main():
    safe_print("\n" + "=" * 70)
    safe_print(" FASE 1.5: VALIDACION SECUENCIAL DE COMPUESTOS Y LOGOS")
    safe_print("=" * 70 + "\n")

    restaurar_si_hace_falta()

    if not os.path.exists(MUNICIPIOS_JSON):
        safe_print(f"ERROR: No se encontro el archivo {MUNICIPIOS_JSON}.")
        safe_print("Ejecuta primero la Fase 1 (main.py).")
        return

    safe_print(f"Creando copia de seguridad en {BACKUP_JSON}...")
    try:
        shutil.copyfile(MUNICIPIOS_JSON, BACKUP_JSON)
        safe_print("Copia de seguridad creada correctamente.\n")
    except Exception as e:
        safe_print(f"ADVERTENCIA: No se pudo crear copia de seguridad: {e}")

    data = cargar_dataset()
    lugares = data.get("lugares", [])
    total_lugares = len(lugares)
    safe_print(f"Cargados {total_lugares} municipios desde {MUNICIPIOS_JSON}.")

    if test_llm_connection():
        safe_print("INFO: Conexion con LM Studio detectada.")
    else:
        safe_print("ADVERTENCIA: No se detecto LM Studio en el puerto 1234.")

    headers = {
        "User-Agent": "Fiestyfy/1.5 (FIESTYFY_algorithm; contact: pablocojo@example.com)"
    }

    resultados_proceso = {}
    total_procesados = 0
    total_cambios_tipo = 0
    total_cambios_logo = 0

    safe_print("\nProcesando municipios uno a uno. Se guarda tras cada municipio.\n")

    try:
        for lugar in lugares:
            resultado = procesar_lugar(lugar, headers)
            resultados_proceso[resultado["id"]] = resultado

            cambio_tipo, cambio_logo = aplicar_resultado(lugar, resultado)
            total_cambios_tipo += cambio_tipo
            total_cambios_logo += cambio_logo
            total_procesados += 1

            guardar_dataset(data)
            safe_print(
                f"  - {total_procesados}/{total_lugares}: {resultado['nombre']} "
                f"({total_cambios_tipo} reclasificados, {total_cambios_logo} logos actualizados)"
            )
    except KeyboardInterrupt:
        guardar_dataset(data)
        dump_error_log(VALIDACION_COMPUESTOS_LOG)
        safe_print("\nProceso interrumpido por el usuario.")
        safe_print(f"Progreso guardado en {MUNICIPIOS_JSON}.")
        safe_print(f"Log guardado en {VALIDACION_COMPUESTOS_LOG}")
        return

    guardar_dataset(data)
    generar_informe(resultados_proceso, total_lugares, total_cambios_tipo, total_cambios_logo)
    dump_error_log(VALIDACION_COMPUESTOS_LOG)

    safe_print(f"\nJSON actualizado guardado en {MUNICIPIOS_JSON}.")
    safe_print(f"Informe guardado en {INFORME_CAMBIOS_COMPUESTOS}.")
    safe_print(f"Log guardado en {VALIDACION_COMPUESTOS_LOG}.")
    safe_print("\n" + "=" * 70)
    safe_print(" FASE 1.5 FINALIZADA")
    safe_print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

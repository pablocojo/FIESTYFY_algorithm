"""
Caché en disco del texto ya extraído de cada URL.

El problema que resuelve no es la velocidad, es la varianza. Medido entre el
2026-08-23 y el 2026-08-24 con el mismo código: Cordovilla sacó 25 documentos un
día y 4 al siguiente, y Tobarra 8 y 17. Con ese suelo moviéndose no se puede
saber si un cambio mejora o empeora, porque cada ejecución parte de material
distinto. Guardando lo descargado, la segunda ejecución ve lo que vio la
primera y la diferencia que se mida es del código.

De paso quita casi toda la carga de los servidores, que es lo que provoca los
bloqueos y los timeouts que se comían la mitad de los PDF.

Qué se guarda y qué no:

- Lo que salió bien, con su texto y los PDF que enlazaba.
- Los fallos que son una propiedad del recurso y no del momento: un 404, un
  fichero de 25 MB, un content-type que no sabemos leer, un PDF escaneado sin
  capa de texto. Repetirlos cada ejecución es tirar tiempo, y en el caso del
  fichero de 25 MB, tirar ancho de banda a lo tonto.
- NO se guardan los timeouts ni los errores de conexión: son del momento y
  guardarlos congelaría un fallo pasajero.
- NO se guarda el 403. Puede ser un bloqueo temporal por haber insistido mucho,
  y darlo por muerto durante días nos cerraría una fuente que quizá vuelve.
"""

import hashlib
import json
import logging
import os
import time

from config import (
    CACHE_PAGINAS_ACTIVA,
    CACHE_PAGINAS_DIR,
    CACHE_PAGINAS_TTL_DIAS,
    CACHE_PAGINAS_TTL_MUERTAS_DIAS,
    CACHE_BUSQUEDAS_TTL_DIAS,
)

logger = logging.getLogger("cache_paginas")

# Contadores de la ejecución, para poder decir cuánto se ha reaprovechado.
_ESTADISTICAS = {"aciertos": 0, "fallos": 0, "guardados": 0,
                 "aciertos_busqueda": 0, "fallos_busqueda": 0}


def _ruta(url: str) -> str:
    """Un fichero por URL, nombrado por hash: los nombres de URL no valen como nombre de fichero."""
    clave = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()[:20]
    return os.path.join(CACHE_PAGINAS_DIR, f"{clave}.json")


def _vigente(entrada: dict) -> bool:
    dias = CACHE_PAGINAS_TTL_MUERTAS_DIAS if entrada.get("motivo") else CACHE_PAGINAS_TTL_DIAS
    return (time.time() - entrada.get("guardado_en", 0)) < dias * 86400


def leer(url: str) -> tuple[str, list[str], str, list[str]] | None:
    """
    Devuelve (texto, pdfs, motivo, enlaces) si la URL está guardada y vigente.

    `motivo` vacío significa que la descarga fue buena; con contenido, es un
    fallo estable que ya conocemos y no hace falta volver a comprobar.

    `enlaces` son las páginas HTML que esta enlazaba y que parecían llevar al
    programa. Las entradas guardadas antes de que existiera este campo devuelven
    una lista vacía y se comportan como siempre.
    """
    if not CACHE_PAGINAS_ACTIVA:
        return None
    try:
        with open(_ruta(url), "r", encoding="utf-8") as f:
            entrada = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _ESTADISTICAS["fallos"] += 1
        return None

    if not _vigente(entrada):
        _ESTADISTICAS["fallos"] += 1
        return None

    _ESTADISTICAS["aciertos"] += 1
    return (entrada.get("texto", ""), entrada.get("pdfs", []),
            entrada.get("motivo", ""), entrada.get("enlaces", []))


def guardar(url: str, texto: str, pdfs: list[str], motivo: str = "",
            enlaces: list[str] | None = None) -> None:
    """Guarda el resultado. Escritura atómica: un run interrumpido no deja JSON a medias."""
    if not CACHE_PAGINAS_ACTIVA:
        return
    entrada = {
        "url": url,
        "guardado_en": time.time(),
        "texto": texto,
        "pdfs": pdfs or [],
        "motivo": motivo,
        "enlaces": enlaces or [],
    }
    destino = _ruta(url)
    temporal = destino + ".tmp"
    try:
        os.makedirs(CACHE_PAGINAS_DIR, exist_ok=True)
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(entrada, f, ensure_ascii=False)
        os.replace(temporal, destino)
        _ESTADISTICAS["guardados"] += 1
    except OSError as e:
        # Que falle la caché no puede tumbar una ejecución: se sigue sin ella.
        logger.debug(f"No se pudo guardar en caché {url[:80]}: {e}")
        try:
            os.remove(temporal)
        except OSError:
            pass


def leer_busqueda(query: str) -> list[dict] | None:
    """
    Resultados guardados de una consulta, o None.

    Cachear las páginas no bastaba. Medido el 2026-08-24 con dos pasadas
    seguidas del mismo tramo: el número de documentos ya salía estable (28 y 27
    en Tobarra, donde antes hubo 25 y 4), pero la huella de las URLs cambiaba,
    porque los motores no devuelven la misma lista dos veces. Mientras la lista
    de partida baile, la ejecución no es reproducible por mucho que el contenido
    de cada URL lo sea.
    """
    if not CACHE_PAGINAS_ACTIVA:
        return None
    clave = "busqueda:" + " ".join(query.lower().split())
    try:
        with open(_ruta(clave), "r", encoding="utf-8") as f:
            entrada = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _ESTADISTICAS["fallos_busqueda"] += 1
        return None

    if (time.time() - entrada.get("guardado_en", 0)) >= CACHE_BUSQUEDAS_TTL_DIAS * 86400:
        _ESTADISTICAS["fallos_busqueda"] += 1
        return None

    _ESTADISTICAS["aciertos_busqueda"] += 1
    return entrada.get("resultados", [])


def guardar_busqueda(query: str, resultados: list[dict]) -> None:
    """Guarda los resultados de una consulta. Una lista vacía no se guarda: es un fallo, no un dato."""
    if not CACHE_PAGINAS_ACTIVA or not resultados:
        return
    clave = "busqueda:" + " ".join(query.lower().split())
    destino = _ruta(clave)
    temporal = destino + ".tmp"
    try:
        os.makedirs(CACHE_PAGINAS_DIR, exist_ok=True)
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump({"query": query, "guardado_en": time.time(), "resultados": resultados},
                      f, ensure_ascii=False)
        os.replace(temporal, destino)
    except OSError as e:
        logger.debug(f"No se pudo guardar la consulta '{query[:60]}': {e}")
        try:
            os.remove(temporal)
        except OSError:
            pass


def estadisticas() -> dict:
    return dict(_ESTADISTICAS)


def reiniciar_estadisticas() -> None:
    for k in _ESTADISTICAS:
        _ESTADISTICAS[k] = 0


def resumen() -> str:
    e = _ESTADISTICAS
    pedidas = e["aciertos"] + e["fallos"]
    pct = round(100 * e["aciertos"] / pedidas) if pedidas else 0
    consultas = e["aciertos_busqueda"] + e["fallos_busqueda"]
    extra = f", {e['aciertos_busqueda']}/{consultas} consultas" if consultas else ""
    return f"{e['aciertos']}/{pedidas} URLs desde caché ({pct}%), {e['guardados']} guardadas{extra}"

"""
Construcción de la cola de trabajo del runner de apps a partir de:
- redes_sociales_cache.json (Etapa B): URLs conocidas → tareas "leer";
  redes a null con pendiente_apps → tareas "buscar".
- lugares_espana.json: nombres (necesarios para buscar) y población (prioridad).
- rrss_contenido_cache.json: TTL para no releer perfiles recientes.
"""

from datetime import date

from scraper.social_apps.util import handle_de_url
from scraper.social_apps.contenido_cache import ContenidoCache

REDES = ("instagram", "facebook", "twitter")


def construir_cola(
    redes_cache: dict,
    lugares_por_id: dict,
    contenido: ContenidoCache,
    ttl_dias: int,
    redes_habilitadas: tuple = REDES,
    hoy: date | None = None,
) -> list[dict]:
    """
    Devuelve tareas ordenadas: primero "leer" (perfil ya verificado, máximo valor),
    después "buscar"; dentro de cada tipo, por población descendente.

    Tarea: {tipo, lugar_id, red, url|None, handle|None, nombre, municipio_nombre, poblacion}
    """
    tareas = []
    for lugar_id, entrada in (redes_cache or {}).items():
        if not isinstance(entrada, dict):
            continue
        lugar = lugares_por_id.get(lugar_id)
        nombre = (lugar or {}).get("nombre")
        poblacion = (lugar or {}).get("poblacion") or 0

        for red in redes_habilitadas:
            url = entrada.get(red)
            if url:
                if contenido.vigente(lugar_id, red, ttl_dias, hoy):
                    continue
                tareas.append({
                    "tipo": "leer",
                    "lugar_id": lugar_id,
                    "red": red,
                    "url": url,
                    "handle": handle_de_url(url),
                    "nombre": nombre,
                    "poblacion": poblacion,
                })
            elif entrada.get("pendiente_apps"):
                # Sin nombre no se puede buscar; sin resultado previo reciente tampoco se repite
                if not nombre:
                    continue
                buscado = (entrada.get("apps_sin_resultado") or {}).get(red)
                if buscado:
                    continue  # ya se buscó en apps y no existía; el TTL lo gestiona la Etapa C futura
                tareas.append({
                    "tipo": "buscar",
                    "lugar_id": lugar_id,
                    "red": red,
                    "url": None,
                    "handle": None,
                    "nombre": nombre,
                    "poblacion": poblacion,
                })

    orden_tipo = {"leer": 0, "buscar": 1}
    tareas.sort(key=lambda t: (orden_tipo[t["tipo"]], -t["poblacion"]))
    return tareas

"""
Nombre oficial completo de un municipio, resuelto por el LLM y cacheado.

El problema
-----------
El dataset de Fase 1 guarda los municipios por su nombre corto. Para el municipio
`06121000000` guarda "Santa Marta", y su nombre real es **Santa Marta de los
Barros**. Eso costó dos cosas medidas el 2026-09-04:

  * De las 14 consultas de búsqueda de ese municipio, ninguna usó el nombre
    completo y trece preguntaron "Santa Marta" a secas. En cualquier buscador eso
    devuelve la ciudad colombiana de 500.000 habitantes antes que un pueblo
    pacense de 4.199, y el contexto de discovery acabó encabezado por
    `malokal.com/es/colombia/santa-marta` (23 chunks) y por las fiestas de
    Astorga (12).
  * El juez de pertenencia descartó 'Candelas 2026' —la única ficha real que el
    pipeline llegó a producir para ese pueblo— porque el modelo la situó en
    "Santa Marta de los Barros" y el código no reconoció ese nombre como nuestro.

Por qué lo decide el LLM y no el código
---------------------------------------
Se puede deducir del dominio (`santamartadelosbarros.com` lleva el nombre
dentro), pero solo a veces: hay ayuntamientos en `aytoXXX.es`, en dominios de la
diputación o sin web. Y la regla contraria —alargar siempre— es peor: "Tobarra"
es "Tobarra" y forzarle un apellido rompería sus consultas, que hoy funcionan.

Es un hecho del mundo, no una regla derivable, así que lo decide el modelo con
los datos delante y se cachea: una llamada por municipio y para siempre.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger("nombre_oficial")

_AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(_AQUI, "nombres_oficiales_cache.json")

_SYS = """Te dan un municipio español del INE con su nombre corto, su provincia, su comunidad
y la web de su ayuntamiento. Dices cuál es su NOMBRE OFICIAL COMPLETO.

Muchos municipios españoles tienen un apellido que los distingue de sus homónimos:
"Santa Marta" es "Santa Marta de los Barros" (Badajoz), "Aranda" es "Aranda de Duero".
Otros no tienen ninguno: "Tobarra" es "Tobarra" y nada más.

Reglas:
- Si el nombre corto YA es el completo, repítelo tal cual. Es lo más frecuente.
- NO te inventes un apellido para desambiguar. Solo pon el que el municipio tenga
  de verdad.
- El dominio de la web suele delatarlo: santamartadelosbarros.com → "Santa Marta
  de los Barros". Pero no siempre: aytoburgos.es no significa que el municipio se
  llame "Ayto Burgos".
- Si dudas, devuelve el nombre corto.

Responde solo JSON: {"nombre_oficial": "...", "seguro": true|false}"""


def _leer(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except Exception as e:
        logger.debug(f"No se pudo leer la caché de nombres oficiales: {e}")
        return {}


def _escribir_sync(path: str, datos: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class _CacheNombres:
    """Misma forma que `_PatronCache`: carga perezosa, escritura fuera del hilo."""

    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def _cargar(self):
        if self._loaded:
            return
        self._loaded = True
        self._data = _leer(self.path)
        if self._data:
            logger.info(f"Caché de nombres oficiales cargada: {len(self._data)} municipios")

    async def get(self, mun_id: str):
        async with self._lock:
            self._cargar()
            return self._data.get(mun_id)

    async def set(self, mun_id: str, valor: str):
        async with self._lock:
            self._cargar()
            self._data[mun_id] = valor
            await asyncio.to_thread(_escribir_sync, self.path, dict(self._data))


_cache = _CacheNombres(CACHE_FILE)


async def nombre_oficial_del_municipio(municipio: dict, llm_chat_json) -> str:
    """
    Nombre oficial completo del municipio. Cae al nombre corto ante cualquier duda.

    `llm_chat_json` se recibe por parámetro, no se importa: `text_analyzer` ya
    importa medio proyecto y hacerlo al revés cerraría el círculo. Es el mismo
    criterio que sigue `reparto_contexto` con `ensamblar` y `contar_tokens`.
    """
    corto = (municipio.get("nombre") or "").strip()
    mun_id = municipio.get("id") or corto
    if not corto:
        return ""

    guardado = await _cache.get(mun_id)
    if guardado:
        return guardado

    ficha = "\n".join(filter(None, [
        f"Nombre corto: {corto}",
        f"Provincia: {municipio.get('provincia', '')}",
        f"Comunidad: {municipio.get('comunidad') or municipio.get('comunidad_autonoma') or ''}",
        f"Población: {municipio.get('poblacion')}" if municipio.get("poblacion") else "",
        f"Web del ayuntamiento: {municipio.get('sitio_web', '')}",
    ]))

    nombre = corto
    try:
        datos = await llm_chat_json(_SYS, ficha, max_tokens=400, etiqueta="NOMBRE_OFICIAL")
        if isinstance(datos, dict):
            propuesto = (datos.get("nombre_oficial") or "").strip()
            # Solo se acepta si CONTIENE el nombre corto. Un modelo que devuelve
            # algo sin parecido se ha equivocado de municipio, y quedarse con eso
            # envenenaría todas las consultas de ese pueblo para siempre.
            if propuesto and corto.lower() in propuesto.lower():
                nombre = propuesto
            elif propuesto:
                logger.warning(
                    f"  [NOMBRE] Descartado '{propuesto}' para {corto}: no contiene "
                    f"el nombre del municipio. Se usa el corto."
                )
    except Exception as e:
        logger.debug(f"  [NOMBRE] No se pudo resolver el nombre oficial de {corto}: {e}")

    if nombre != corto:
        logger.info(f"  [NOMBRE] {corto} → «{nombre}»")
    await _cache.set(mun_id, nombre)
    return nombre

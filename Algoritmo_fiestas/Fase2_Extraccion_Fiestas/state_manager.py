"""
Gestor de Estado — Persistencia segura del progreso de extracción.

- Escritura atómica (tmp → rename), con copia .bak de la versión anterior
- Lectura con respaldo: si la salida está truncada, se recupera del .bak
- Thread-safe con asyncio.Lock
- Deduplicación de fiestas al guardar
"""

import json
import os
import shutil
import asyncio
import re
import logging

logger = logging.getLogger("state_manager")


def _leer_json(ruta: str):
    """JSON de `ruta`, o None si no está o no se puede leer."""
    if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
        return None
    with open(ruta, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def escribir_json_con_respaldo(ruta: str, datos, indent: int = 2) -> None:
    """
    Escribe `datos` en `ruta` dejando siempre recuperable la versión anterior.

    El tmp+rename por sí solo no basta aquí. Estas ejecuciones corren sobre
    /mnt/c desde WSL, y en drvfs el rename no es la operación atómica que es en
    ext4: si el proceso muere en mitad, el destino se queda a cero bytes. Es lo
    que pasó el 2026-08-26 con `rrss_contenido_cache.json` (16 KB → 0) y lo que
    lleva desde el 2026-08-20 impidiendo reanudar, porque `fiestas_neutros.json`
    aparecía vacío al arrancar y cada ejecución empezaba de cero.
    """
    if os.path.exists(ruta) and os.path.getsize(ruta) > 2:
        try:
            shutil.copy2(ruta, f"{ruta}.bak")
        except OSError as e:
            logger.debug(f"No se pudo respaldar {ruta}: {e}")
    temp = f"{ruta}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=indent)
    os.replace(temp, ruta)


def leer_json_con_respaldo(ruta: str, etiqueta: str = ""):
    """
    JSON de `ruta`; si está truncado o ilegible, el de su `.bak`.

    Devuelve None cuando no hay nada que leer. Lo que NO hace es callarse: un
    fichero de estado vacío significa que se ha perdido trabajo, y merece un
    aviso con el tamaño, no un "se creará uno nuevo" que parece rutina.
    """
    nombre = etiqueta or os.path.basename(ruta)
    try:
        datos = _leer_json(ruta)
        if datos is not None:
            return datos
        if os.path.exists(ruta):
            logger.warning(f"{nombre} existe pero está vacío (0 bytes).")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning(f"{nombre} ilegible ({type(e).__name__}: {e}).")

    try:
        datos = _leer_json(f"{ruta}.bak")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        datos = None
    if datos is not None:
        logger.warning(f"  Recuperado {nombre} desde su copia .bak.")
        return datos
    return None


class StateManager:
    """Gestiona la persistencia del progreso y el archivo de salida."""

    def __init__(self, output_file="fiestas_espana.json", anno=2026):
        self.output_file = output_file
        self._lock = asyncio.Lock()
        self.state = {
            "version": 2,
            "anno": anno,
            "ultimo_municipio_procesado": None,
            "municipios_completados": [],
            "localidades_completadas": [],
            "fiestas": [],
        }

    def cargar_estado(self) -> dict:
        """Carga el estado previo si existe, recurriendo al .bak si hace falta."""
        if not os.path.exists(self.output_file):
            return self.state

        data = leer_json_con_respaldo(self.output_file, os.path.basename(self.output_file))
        if not isinstance(data, dict):
            logger.warning(
                f"No hay estado previo utilizable en {self.output_file}: se empieza de "
                f"cero y NO se reanuda nada."
            )
            return self.state

        # Migrar desde versión 1 si es necesario
        if data.get("version", 1) < 2:
            data["municipios_completados"] = []
            data["version"] = 2
            if data.get("ultimo_municipio_procesado"):
                data["municipios_completados"].append(data["ultimo_municipio_procesado"])

        data.setdefault("localidades_completadas", [])
        data.setdefault("fiestas", [])
        self.state = data
        logger.info(
            f"Estado cargado: {len(self.state['fiestas'])} fiestas, "
            f"{len(self.state.get('municipios_completados', []))} municipios completados"
        )
        return self.state

    async def guardar_estado(self, fiestas_nuevas: list, municipio_id: str):
        """Guarda progreso de forma atómica y thread-safe."""
        async with self._lock:
            # Añadir fiestas (con deduplicación)
            existing_ids = {f.get("id") for f in self.state["fiestas"]}
            nuevas_unicas = 0
            for f in fiestas_nuevas:
                fiesta_id = f.get("id", "")
                if fiesta_id and fiesta_id not in existing_ids:
                    self.state["fiestas"].append(f)
                    existing_ids.add(fiesta_id)
                    nuevas_unicas += 1

            # Registrar municipio como completado
            self.state["ultimo_municipio_procesado"] = municipio_id
            if municipio_id not in self.state.get("municipios_completados", []):
                self.state.setdefault("municipios_completados", []).append(municipio_id)

            try:
                escribir_json_con_respaldo(self.output_file, self.state)
                logger.info(
                    f"  Estado guardado: +{nuevas_unicas} fiestas nuevas | "
                    f"Total: {len(self.state['fiestas'])} fiestas | "
                    f"Municipio: {municipio_id}"
                )
            except Exception as e:
                logger.error(f"Error guardando estado: {e}")

    async def guardar_estado_localidad(self, fiestas_nuevas: list, localidad_id: str):
        """Guarda progreso intermedio de una localidad de forma atómica."""
        async with self._lock:
            existing_ids = {f.get("id") for f in self.state["fiestas"]}
            nuevas_unicas = 0
            for f in fiestas_nuevas:
                fiesta_id = f.get("id", "")
                if fiesta_id and fiesta_id not in existing_ids:
                    self.state["fiestas"].append(f)
                    existing_ids.add(fiesta_id)
                    nuevas_unicas += 1

            if localidad_id not in self.state.get("localidades_completadas", []):
                self.state.setdefault("localidades_completadas", []).append(localidad_id)

            try:
                escribir_json_con_respaldo(self.output_file, self.state)
                logger.info(
                    f"  [VOLCADO TEMPORAL] +{nuevas_unicas} fiestas. "
                    f"Localidad completada: {localidad_id}"
                )
            except Exception as e:
                logger.error(f"Error guardando estado temporal: {e}")

    def obtener_indice_reanudacion(self, municipios_raiz: list) -> int:
        """Calcula desde qué índice reanudar basado en municipios completados."""
        completados = set(self.state.get("municipios_completados", []))

        if not completados:
            # Compatibilidad con versión 1
            ultimo = self.state.get("ultimo_municipio_procesado")
            if ultimo:
                for i, m in enumerate(municipios_raiz):
                    if m["id"] == ultimo:
                        return i + 1
            return 0

        # Encontrar el primer municipio no completado
        for i, m in enumerate(municipios_raiz):
            if m["id"] not in completados:
                return i

        return len(municipios_raiz)  # Todos completados

    def esta_completado(self, municipio_id: str) -> bool:
        """Verifica si un municipio ya fue procesado."""
        return municipio_id in self.state.get("municipios_completados", [])

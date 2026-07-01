"""
Gestor de Estado — Persistencia segura del progreso de extracción.

- Escritura atómica (tmp → rename)
- Thread-safe con asyncio.Lock
- Deduplicación de fiestas al guardar
"""

import json
import os
import asyncio
import re
import logging

logger = logging.getLogger("state_manager")


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
        """Carga el estado previo si existe."""
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Migrar desde versión 1 si es necesario
                    if data.get("version", 1) < 2:
                        data["municipios_completados"] = []
                        data["version"] = 2
                        if data.get("ultimo_municipio_procesado"):
                            data["municipios_completados"].append(data["ultimo_municipio_procesado"])
                    
                    if "localidades_completadas" not in data:
                        data["localidades_completadas"] = []
                    
                    self.state = data
                    logger.info(
                        f"Estado cargado: {len(self.state['fiestas'])} fiestas, "
                        f"{len(self.state.get('municipios_completados', []))} municipios completados"
                    )
            except json.JSONDecodeError:
                logger.warning(f"Error al leer {self.output_file}. Se creará uno nuevo.")
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

            # Escritura atómica: escribir en tmp y renombrar
            temp_file = f"{self.output_file}.tmp"
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, self.output_file)
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

            temp_file = f"{self.output_file}.tmp"
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, indent=2)
                os.replace(temp_file, self.output_file)
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

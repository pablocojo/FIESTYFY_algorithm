"""
Cliente del servidor RRSS (rrss_server.py) para main.py en WSL.

Envía peticiones HTTP al servidor que corre en Windows para que procese
perfiles de RRSS usando las apps de escritorio (pywinauto + SafetyGuard).

Si el servidor no está disponible, se omite la fuente RRSS: el pipeline
continúa con el resto de fuentes (webs + búsqueda browser), exactamente
como hacía antes de esta integración.
"""

import logging

import aiohttp

from config import RRSS_SERVER_URL, RRSS_SERVER_TIMEOUT

logger = logging.getLogger("rrss_client")


class RRSSClient:
    """Cliente async para comunicarse con rrss_server.py en Windows."""

    def __init__(self, server_url: str = RRSS_SERVER_URL, timeout: int = RRSS_SERVER_TIMEOUT):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._disponible: bool | None = None  # None = no comprobado aún

    async def verificar_servidor(self) -> bool:
        """
        Comprueba si el servidor RRSS está activo y tiene apps disponibles.
        Se llama una vez al inicio de main.py.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/status",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        self._disponible = False
                        return False
                    data = await resp.json()
                    apps = data.get("apps", {})
                    alguna_app = any(apps.values())
                    self._disponible = alguna_app
                    if alguna_app:
                        logger.info(
                            f"Servidor RRSS OK en {self.server_url} — "
                            f"Apps: {', '.join(r for r, ok in apps.items() if ok)}"
                        )
                    else:
                        logger.warning(
                            f"Servidor RRSS en {self.server_url} responde "
                            f"pero ninguna app está disponible."
                        )
                    return alguna_app
        except Exception as e:
            logger.info(f"Servidor RRSS no disponible en {self.server_url}: {e}")
            self._disponible = False
            return False

    @property
    def disponible(self) -> bool:
        """True si el servidor fue verificado y está disponible."""
        return self._disponible is True

    async def procesar_rrss(
        self,
        lugar_ids: list[str],
        perfiles_extra: dict | None = None,
    ) -> dict:
        """
        Solicita al servidor que procese los perfiles RRSS de los lugar_ids.

        :param lugar_ids: IDs de los lugares a procesar.
        :param perfiles_extra: {lugar_id: {red: url}} descubiertos por el spider.
        :return: dict con el contenido por lugar_id, o {} si hubo error.
        """
        if not self.disponible:
            return {}

        payload = {"lugar_ids": lugar_ids}
        if perfiles_extra:
            payload["perfiles"] = perfiles_extra

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.server_url}/procesar",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status == 503:
                        logger.warning("Servidor RRSS ocupado. Omitiendo RRSS para esta localidad.")
                        return {}
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Error del servidor RRSS: {resp.status} — {body[:200]}")
                        return {}
                    data = await resp.json()
                    resumen_runner = data.get("runner", {})
                    resumen_vlm = data.get("vlm", {})
                    contenido = data.get("contenido", {})

                    completadas = resumen_runner.get("completadas", 0)
                    programas = resumen_vlm.get("programas", 0)
                    if completadas or programas:
                        logger.info(
                            f"    RRSS server: {completadas} perfiles leídos, "
                            f"{programas} programas VLM detectados"
                        )
                    return contenido

        except aiohttp.ClientError as e:
            logger.warning(f"Error de conexión con el servidor RRSS: {e}")
            # Marcar como no disponible para no reintentar en cada localidad
            self._disponible = False
            return {}
        except Exception as e:
            logger.error(f"Error inesperado del cliente RRSS: {e}")
            return {}

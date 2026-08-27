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

    # Fases abortadas seguidas que se toleran antes de dejar de pedir RRSS. El
    # servidor las aborta cuando la ventana de la app pierde el primer plano y
    # no lo recupera, y eso NO se arregla solo: si ha pasado dos veces seguidas,
    # va a pasar las diez restantes. Medido el 2026-08-26: doce localidades,
    # doce abortos, dos minutos de espera cada uno — 24 de los 52 minutos del
    # run esperando un foco de ventana que nunca volvió, y cero contenido.
    MAX_ABORTOS_SEGUIDOS = 2

    def __init__(self, server_url: str = RRSS_SERVER_URL, timeout: int = RRSS_SERVER_TIMEOUT):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._disponible: bool | None = None  # None = no comprobado aún
        self._abortos_seguidos = 0

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
                        self._abortos_seguidos = 0
                        logger.info(
                            f"    RRSS server: {completadas} perfiles leídos, "
                            f"{programas} programas VLM detectados"
                        )
                        return contenido

                    # Ni un perfil leído. Si además la fase se abortó, el
                    # servidor no está en condiciones de trabajar y seguir
                    # pidiéndoselo solo cuesta tiempo.
                    if resumen_runner.get("abortado"):
                        self._abortos_seguidos += 1
                        logger.warning(
                            f"    El servidor RRSS abortó la fase sin leer ningún perfil "
                            f"({self._abortos_seguidos}/{self.MAX_ABORTOS_SEGUIDOS})."
                        )
                        if self._abortos_seguidos >= self.MAX_ABORTOS_SEGUIDOS:
                            self._disponible = False
                            logger.error(
                                f"    Servidor RRSS descartado para el resto de la ejecución: "
                                f"{self._abortos_seguidos} fases abortadas seguidas. Revisa que "
                                f"las ventanas de las apps sigan en primer plano. Las RRSS se "
                                f"omiten a partir de aquí."
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

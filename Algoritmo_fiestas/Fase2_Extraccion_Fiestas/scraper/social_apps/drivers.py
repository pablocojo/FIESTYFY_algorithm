"""
Drivers de las apps de escritorio (Facebook/Instagram de Microsoft Store, X como PWA).

Estrategia v1, deliberadamente defensiva:
- Toda acción pasa por el SafetyGuard (foco verificado, clics dentro de la ventana).
- La navegación usa el buscador interno de cada app (control UIA tipo Edit).
- La lectura de un perfil combina dos vías:
  1. Texto accesible del árbol UIA (las tres apps son contenedores web y exponen
     bastante texto por accesibilidad).
  2. Capturas del rectángulo de la ventana en cada posición de scroll → las
     interpreta el VLM en la Etapa D (es_programa / texto_programa).

Las apps cambian su UI con las actualizaciones: los nombres de los controles
se definen como regex por driver para poder ajustarlos sin tocar la lógica.
"""

import logging
import os
import re
import time
from datetime import date, timedelta

from config import (
    SOCIAL_MAX_POSTS_PER_PROFILE,
    SOCIAL_MAX_SCROLLS,
    SOCIAL_MAX_MINUTES_PER_PROFILE,
    SOCIAL_POST_MONTHS_BACK,
)
from scraper.social_apps.util import (
    validar_candidato_perfil,
    parsear_fecha_post,
    url_de_handle,
)

logger = logging.getLogger("social_drivers")

# Textos de UI que no son contenido (botones, menús...)
_RUIDO_UI = re.compile(
    r"^(me gusta|like|comentar|comment|compartir|share|seguir|follow|siguiendo|"
    r"following|inicio|home|buscar|search|reels?|mensajes?|messages|notificaciones|"
    r"notifications|perfil|profile|m[aá]s|more|crear|create|explorar|explore|"
    r"publicar|post|responder|reply|repostear|repost|ver traducci[oó]n|"
    r"ver m[aá]s|see more|\d+\s*(me gusta|likes?|comentarios?|comments?))$",
    re.IGNORECASE,
)


class DriverBase:
    red = ""
    # Regex del control de búsqueda (nombre accesible del Edit)
    buscador_re = r"buscar|search"

    def __init__(self, ventana, guard):
        self.ventana = ventana
        self.guard = guard

    # ── primitivas ──

    def _descendientes(self, **kwargs):
        self.guard.verificar()
        try:
            return self.ventana.descendants(**kwargs)
        except Exception as e:
            logger.debug(f"[{self.red}] Error leyendo árbol UIA: {e}")
            return []

    def _texto_visible(self) -> list[str]:
        """Textos accesibles visibles, filtrando ruido de UI."""
        textos = []
        for el in self._descendientes():
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if len(t) < 3 or _RUIDO_UI.match(t):
                continue
            textos.append(t)
        return textos

    def _buscar_control_busqueda(self):
        patron = re.compile(self.buscador_re, re.IGNORECASE)
        for tipo in ("Edit", "ComboBox"):
            for el in self._descendientes(control_type=tipo):
                try:
                    nombre = f"{el.window_text()} {el.element_info.name or ''}"
                except Exception:
                    continue
                if patron.search(nombre):
                    return el
        # A veces el buscador es un botón que abre el campo
        for el in self._descendientes(control_type="Button"):
            try:
                if patron.search(el.window_text() or ""):
                    return el
            except Exception:
                continue
        return None

    def _escribir_en_buscador(self, consulta: str) -> bool:
        control = self._buscar_control_busqueda()
        if control is None:
            logger.warning(f"[{self.red}] No se encontró el buscador interno.")
            return False
        if not self.guard.click_seguro(control):
            return False
        time.sleep(0.8)
        # Limpiar y escribir (el foco queda en el campo tras el clic)
        self.guard.teclear_seguro("^a{DELETE}", con_espacios=False)
        self.guard.teclear_seguro(consulta)
        time.sleep(2.5)  # dejar que carguen las sugerencias
        return True

    def _candidatos_de_busqueda(self):
        """Elementos clicables del panel de resultados con su texto."""
        candidatos = []
        for tipo in ("ListItem", "Link", "Button", "Text"):
            for el in self._descendientes(control_type=tipo):
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                if len(t) >= 3 and not _RUIDO_UI.match(t):
                    candidatos.append((t, el))
        return candidatos

    # ── operaciones de alto nivel ──

    def abrir_perfil(self, handle: str, nombre_localidad: str) -> bool:
        """Abre un perfil YA VERIFICADO buscando su handle en la app."""
        self.guard.activar()
        if not self._escribir_en_buscador(handle):
            return False
        for texto, el in self._candidatos_de_busqueda():
            ok, _ = validar_candidato_perfil(texto, nombre_localidad, handle_esperado=handle)
            if ok and self.guard.click_seguro(el):
                time.sleep(3.0)
                logger.info(f"[{self.red}] Perfil abierto: {handle}")
                return True
        logger.warning(f"[{self.red}] No apareció '{handle}' en los resultados de búsqueda.")
        return False

    def buscar_perfil(self, nombre_localidad: str, nombre_municipio: str) -> dict | None:
        """
        Busca el perfil OFICIAL de una localidad sin URL previa. Validación
        estricta (nombre completo + marcador institucional): sin certeza → None.
        Devuelve {"texto": nombre del perfil, "url": None} y deja el perfil abierto.
        """
        self.guard.activar()
        for consulta in (f"ayuntamiento {nombre_localidad}", f"ayuntamiento de {nombre_localidad}"):
            if not self._escribir_en_buscador(consulta):
                return None
            for texto, el in self._candidatos_de_busqueda():
                ok, motivo = validar_candidato_perfil(texto, nombre_localidad)
                if ok:
                    if self.guard.click_seguro(el):
                        time.sleep(3.0)
                        logger.info(f"[{self.red}] Perfil validado ({motivo}): {texto!r}")
                        return {"texto": texto, "url": None}
        logger.info(f"[{self.red}] Sin perfil oficial concluyente para {nombre_localidad}.")
        return None

    def extraer_handle_visible(self) -> str | None:
        """Intenta leer el handle (@usuario) del perfil abierto para construir su URL."""
        for t in self._texto_visible()[:60]:
            m = re.search(r"@([a-z0-9._]{2,30})", t, re.IGNORECASE)
            if m:
                return m.group(1).lower()
        return None

    def leer_perfil_abierto(self, lugar_id: str, dir_capturas: str, anno: int) -> list[dict]:
        """
        Lee el perfil actualmente abierto: en cada posición de scroll cosecha el
        texto accesible nuevo y guarda una captura de la ventana para el VLM.
        Corta por nº de posts, nº de scrolls, tiempo o antigüedad de las fechas.
        """
        os.makedirs(dir_capturas, exist_ok=True)
        limite_antiguedad = date.today() - timedelta(days=30 * SOCIAL_POST_MONTHS_BACK)

        posts: list[dict] = []
        vistos: set[str] = set()
        inicio = time.time()

        for n_scroll in range(SOCIAL_MAX_SCROLLS):
            if time.time() - inicio > SOCIAL_MAX_MINUTES_PER_PROFILE * 60:
                logger.info(f"[{self.red}] Tiempo máximo por perfil alcanzado.")
                break
            if len(posts) >= SOCIAL_MAX_POSTS_PER_PROFILE:
                break

            textos = self._texto_visible()
            nuevos = [t for t in textos if t not in vistos and len(t) >= 15]
            vistos.update(textos)

            ruta_captura = os.path.join(dir_capturas, f"{self.red}_{n_scroll:02d}.png")
            if not self.guard.captura_ventana(ruta_captura):
                ruta_captura = None

            if nuevos or ruta_captura:
                texto_bloque = "\n".join(nuevos[:25])
                fecha = parsear_fecha_post(texto_bloque)
                posts.append({
                    "texto": texto_bloque,
                    "fecha": fecha.isoformat() if fecha else None,
                    "captura": ruta_captura,
                    "url_post": None,
                })
                # Si ya estamos viendo posts demasiado antiguos, parar
                if fecha and fecha < limite_antiguedad:
                    logger.info(f"[{self.red}] Posts anteriores a {limite_antiguedad}: se detiene el scroll.")
                    break

            self.guard.verificar()
            self.guard.teclear_seguro("{PGDN}", con_espacios=False)
            time.sleep(1.5)

        logger.info(f"[{self.red}] Leídos {len(posts)} bloques de {lugar_id}.")
        return posts


class InstagramApp(DriverBase):
    red = "instagram"
    buscador_re = r"buscar|search"


class FacebookApp(DriverBase):
    red = "facebook"
    buscador_re = r"buscar|search"


class XApp(DriverBase):
    red = "twitter"
    buscador_re = r"buscar|search|b[uú]squeda"

    def abrir_perfil(self, handle: str, nombre_localidad: str) -> bool:
        # La web de X tiene atajo "/" para enfocar el buscador: se intenta primero
        self.guard.activar()
        try:
            self.guard.teclear_seguro("/", con_espacios=False)
            time.sleep(0.8)
            self.guard.teclear_seguro("^a{DELETE}", con_espacios=False)
            self.guard.teclear_seguro(f"@{handle}")
            time.sleep(2.5)
            for texto, el in self._candidatos_de_busqueda():
                ok, _ = validar_candidato_perfil(texto, nombre_localidad, handle_esperado=handle)
                if ok and self.guard.click_seguro(el):
                    time.sleep(3.0)
                    return True
        except Exception as e:
            logger.debug(f"[twitter] Atajo '/' falló: {e}")
        return super().abrir_perfil(handle, nombre_localidad)


DRIVERS = {
    "instagram": InstagramApp,
    "facebook": FacebookApp,
    "twitter": XApp,
}

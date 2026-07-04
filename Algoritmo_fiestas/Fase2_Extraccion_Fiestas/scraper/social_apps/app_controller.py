"""
Localización de ventanas de las apps + SafetyGuard (aislamiento estricto).

GARANTÍAS DE NO-ESCAPE (requisito duro del usuario):
1. El runner NUNCA lanza ni cierra aplicaciones: solo localiza ventanas de las
   apps que ya están abiertas (por título + proceso). Si una app no está, se omite.
2. Antes de CADA acción se verifica que la ventana objetivo existe, es visible
   y está en primer plano. Si no lo está, TODO se pausa hasta que vuelva a
   estarlo (o se aborta tras demasiadas anomalías / demasiado tiempo).
3. Los clics de coordenadas se validan contra el rectángulo de la ventana:
   jamás se hace clic fuera de ella.
4. Las capturas de pantalla son solo del rectángulo de la ventana, nunca del
   escritorio.
5. Si la ventana desaparece → AppPerdidaError (la red se deshabilita).
   Si el foco se pierde demasiadas veces → AbortoAnomaliasError (se aborta
   la fase completa dejando la cola donde estaba).
"""

import logging
import re
import time

from config import (
    SOCIAL_APPS_VENTANAS,
    SOCIAL_GUARD_MAX_ANOMALIAS,
    SOCIAL_GUARD_MAX_ESPERA_FOCO,
)

logger = logging.getLogger("app_controller")

try:
    import win32gui
    import win32process
    import win32api
    import win32con
    from pywinauto import Desktop
    PYWINAUTO_DISPONIBLE = True
except ImportError:  # el resto del pipeline no necesita pywinauto
    PYWINAUTO_DISPONIBLE = False


class AppPerdidaError(Exception):
    """La ventana de la app desapareció (cerrada/minimizada sin recuperación)."""


class AbortoAnomaliasError(Exception):
    """Demasiadas anomalías de foco: se aborta la fase por seguridad."""


# ──────────────────────────────────────────────────
# LOCALIZACIÓN DE VENTANAS (solo lectura, sin input)
# ──────────────────────────────────────────────────

def _nombre_proceso(pid: int) -> str:
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
        )
        try:
            ruta = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        return ruta.replace("\\", "/").rsplit("/", 1)[-1].lower()
    except Exception:
        return ""


def nombre_elemento_con_foco() -> str | None:
    """
    Nombre accesible del elemento CON FOCO (vía IUIAutomation.GetFocusedElement).
    Clave del fallback por teclado: el foco obliga a Chromium a materializar el
    nodo aunque el árbol UIA del contenido web esté vacío.
    """
    if not PYWINAUTO_DISPONIBLE:
        return None
    try:
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo
        elemento = IUIA().iuia.GetFocusedElement()
        return (UIAElementInfo(elemento).name or "").strip()
    except Exception:
        return None


def listar_ventanas() -> list[dict]:
    """Todas las ventanas top-level visibles con título (para el modo diagnóstico)."""
    if not PYWINAUTO_DISPONIBLE:
        return []
    ventanas = []
    for w in Desktop(backend="uia").windows():
        try:
            titulo = w.window_text()
            if not titulo:
                continue
            pid = w.process_id()
            ventanas.append({
                "titulo": titulo,
                "proceso": _nombre_proceso(pid),
                "pid": pid,
                "handle": w.handle,
            })
        except Exception:
            continue
    return ventanas


def localizar_app(red: str):
    """
    Localiza la ventana de una app por título + proceso según SOCIAL_APPS_VENTANAS.
    Devuelve el wrapper UIA de pywinauto o None. NUNCA lanza la aplicación.
    """
    if not PYWINAUTO_DISPONIBLE:
        logger.error("pywinauto no está instalado: py -3.11 -m pip install pywinauto")
        return None

    spec = SOCIAL_APPS_VENTANAS.get(red)
    if not spec:
        return None
    titulo_re = re.compile(spec["titulo_re"])
    procesos = {p.lower() for p in spec["procesos"]}

    candidatas = []
    for w in Desktop(backend="uia").windows():
        try:
            titulo = w.window_text()
            if not titulo or not titulo_re.search(titulo):
                continue
            proceso = _nombre_proceso(w.process_id())
            if proceso in procesos:
                candidatas.append((len(titulo), titulo, w))
        except Exception:
            continue

    if candidatas:
        # Con varias candidatas, la de título más corto suele ser la PWA/app pura
        # (una pestaña de navegador arrastra el título de la página)
        candidatas.sort(key=lambda c: c[0])
        _, titulo, ventana = candidatas[0]
        logger.info(f"[{red}] Ventana localizada: '{titulo}'")
        return ventana

    logger.warning(f"[{red}] No se encontró la ventana (¿app abierta y con sesión?). Se omite esta red.")
    return None


# ──────────────────────────────────────────────────
# SAFETY GUARD
# ──────────────────────────────────────────────────

class SafetyGuard:
    """Verificación previa a CADA acción sobre la ventana de una app."""

    def __init__(
        self,
        ventana,
        red: str,
        max_anomalias: int = SOCIAL_GUARD_MAX_ANOMALIAS,
        max_espera_foco: int = SOCIAL_GUARD_MAX_ESPERA_FOCO,
    ):
        self.ventana = ventana
        self.red = red
        self.max_anomalias = max_anomalias
        self.max_espera_foco = max_espera_foco
        self.anomalias = 0

    # ── comprobaciones ──

    def ventana_existe(self) -> bool:
        try:
            h = self.ventana.handle
            return bool(win32gui.IsWindow(h) and win32gui.IsWindowVisible(h))
        except Exception:
            return False

    def en_primer_plano(self) -> bool:
        try:
            return win32gui.GetForegroundWindow() == self.ventana.handle
        except Exception:
            return False

    def rect(self) -> tuple[int, int, int, int]:
        r = self.ventana.rectangle()
        return (r.left, r.top, r.right, r.bottom)

    # ── activación y espera ──

    def activar(self):
        """Trae la app al frente (acción legítima sobre la propia app) y verifica."""
        if not self.ventana_existe():
            raise AppPerdidaError(f"[{self.red}] La ventana ya no existe.")
        try:
            self.ventana.set_focus()
        except Exception as e:
            logger.warning(f"[{self.red}] No se pudo enfocar la ventana: {e}")
        time.sleep(0.5)
        self.verificar()

    def verificar(self):
        """
        Bloquea hasta que la ventana esté en primer plano. Si el usuario toca el
        PC (la ventana pierde el foco), TODO queda en pausa — jamás se envía
        input a otra ventana. Aborta tras max_anomalias o max_espera_foco.
        """
        if not self.ventana_existe():
            raise AppPerdidaError(f"[{self.red}] La ventana desapareció.")
        if self.en_primer_plano():
            return

        self.anomalias += 1
        if self.anomalias > self.max_anomalias:
            raise AbortoAnomaliasError(
                f"[{self.red}] {self.anomalias} anomalías de foco: se aborta la fase por seguridad."
            )
        logger.warning(
            f"[{self.red}] La ventana perdió el primer plano "
            f"(anomalía {self.anomalias}/{self.max_anomalias}). EN PAUSA hasta recuperarlo..."
        )
        inicio = time.time()
        while True:
            if not self.ventana_existe():
                raise AppPerdidaError(f"[{self.red}] La ventana desapareció durante la pausa.")
            if self.en_primer_plano():
                logger.info(f"[{self.red}] Foco recuperado. Se reanuda.")
                return
            if time.time() - inicio > self.max_espera_foco:
                raise AbortoAnomaliasError(
                    f"[{self.red}] {self.max_espera_foco}s sin recuperar el foco: se aborta la fase."
                )
            time.sleep(0.5)

    # ── acciones seguras ──

    def punto_dentro(self, x: int, y: int, margen: int = 4) -> bool:
        l, t, r, b = self.rect()
        return (l + margen) <= x <= (r - margen) and (t + margen) <= y <= (b - margen)

    def click_seguro(self, elemento) -> bool:
        """Clic sobre un elemento UIA solo si su centro cae dentro de la ventana."""
        self.verificar()
        try:
            r = elemento.rectangle()
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        except Exception:
            return False
        if not self.punto_dentro(cx, cy):
            logger.warning(f"[{self.red}] Clic rechazado: ({cx},{cy}) fuera de la ventana.")
            return False
        elemento.click_input()
        return True

    def teclear_seguro(self, texto_o_teclas: str, con_espacios: bool = True):
        """Teclea sobre la ventana de la app, verificada en primer plano."""
        self.verificar()
        self.ventana.type_keys(texto_o_teclas, with_spaces=con_espacios, pause=0.03)

    def captura_ventana(self, ruta: str) -> bool:
        """Captura SOLO el rectángulo de la ventana (nunca el escritorio)."""
        self.verificar()
        try:
            imagen = self.ventana.capture_as_image()
            imagen.save(ruta)
            return True
        except Exception as e:
            logger.warning(f"[{self.red}] No se pudo capturar la ventana: {e}")
            return False

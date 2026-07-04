"""
Orquestador del runner de apps: consume la cola (leer/buscar perfiles),
conduce las apps con el SafetyGuard y vuelca resultados a las cachés.

Se ejecuta con `py social_apps_runner.py` en sesiones con PC DEDICADO.
El pipeline principal (main.py) NUNCA llama a este módulo: solo lee las
cachés que este produce.
"""

import json
import logging
import os
from datetime import date

from config import (
    SOCIAL_PROFILE_CACHE_FILE,
    SOCIAL_CONTENT_CACHE_FILE,
    SOCIAL_CONTENT_TTL_DIAS,
    SOCIAL_CAPTURAS_DIR,
    SOCIAL_APPS_VENTANAS,
)
from scraper.social_apps.cola import construir_cola, REDES
from scraper.social_apps.contenido_cache import ContenidoCache
from scraper.social_apps.util import url_de_handle, dominio_base
from scraper.social_apps.app_controller import (
    localizar_app,
    listar_ventanas,
    SafetyGuard,
    AppPerdidaError,
    AbortoAnomaliasError,
    PYWINAUTO_DISPONIBLE,
)
from scraper.social_apps.drivers import DRIVERS

logger = logging.getLogger("social_runner")

_FASE2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ruta(nombre: str) -> str:
    return os.path.join(_FASE2_DIR, nombre)


def _cargar_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _guardar_json_atomico(path: str, data: dict):
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def _cargar_lugares(ruta_lugares: str) -> dict:
    with open(ruta_lugares, "r", encoding="utf-8") as f:
        data = json.load(f)
    lugares = data["lugares"] if isinstance(data, dict) and "lugares" in data else data
    return {l["id"]: l for l in lugares if isinstance(l, dict) and "id" in l}


class RunnerApps:
    def __init__(self, ruta_lugares: str, redes: tuple = REDES, max_tareas: int = 20, anno: int = 2026):
        self.redes = tuple(r for r in redes if r in SOCIAL_APPS_VENTANAS)
        self.max_tareas = max_tareas
        self.anno = anno
        self.ruta_redes_cache = _ruta(SOCIAL_PROFILE_CACHE_FILE)
        self.redes_cache = _cargar_json(self.ruta_redes_cache)
        self.lugares_por_id = _cargar_lugares(ruta_lugares)
        self.contenido = ContenidoCache(_ruta(SOCIAL_CONTENT_CACHE_FILE))
        self.dir_capturas = _ruta(SOCIAL_CAPTURAS_DIR)

    # ──────────────────────────────────────────────
    # DIAGNÓSTICO (solo lectura: ni un clic, ni una tecla)
    # ──────────────────────────────────────────────

    def diagnostico(self):
        print("=" * 60)
        print("  DIAGNÓSTICO DEL RUNNER DE APPS (sin enviar ningún input)")
        print("=" * 60)

        if not PYWINAUTO_DISPONIBLE:
            print("[X] pywinauto NO está instalado: py -3.11 -m pip install pywinauto")
            return

        print("\n— Ventanas de las apps objetivo:")
        faltan = []
        for red in self.redes:
            ventana = localizar_app(red)
            if ventana:
                print(f"  [OK] {red}: '{ventana.window_text()}'")
            else:
                faltan.append(red)
                print(f"  [--] {red}: NO localizada (¿app abierta con sesión iniciada?)")

        if faltan:
            print("\n— Todas las ventanas visibles (para ajustar SOCIAL_APPS_VENTANAS en config.py):")
            for v in listar_ventanas():
                print(f"    '{v['titulo'][:60]}'  <- {v['proceso']}")

        cola = construir_cola(
            self.redes_cache, self.lugares_por_id, self.contenido,
            SOCIAL_CONTENT_TTL_DIAS, self.redes,
        )
        leer = sum(1 for t in cola if t["tipo"] == "leer")
        buscar = len(cola) - leer
        print(f"\n— Cola de trabajo: {len(cola)} tareas ({leer} leer, {buscar} buscar)")
        for t in cola[:10]:
            print(f"    {t['tipo']:7s} {t['red']:9s} {t['nombre'] or t['lugar_id']}")
        if len(cola) > 10:
            print(f"    ... y {len(cola) - 10} más")

    # ──────────────────────────────────────────────
    # EJECUCIÓN
    # ──────────────────────────────────────────────

    def ejecutar(self, solo_tipo: str | None = None) -> dict:
        cola = construir_cola(
            self.redes_cache, self.lugares_por_id, self.contenido,
            SOCIAL_CONTENT_TTL_DIAS, self.redes,
        )
        if solo_tipo:
            cola = [t for t in cola if t["tipo"] == solo_tipo]
        cola = cola[: self.max_tareas]

        if not cola:
            logger.info("Cola vacía: nada que hacer.")
            return {"completadas": 0, "fallidas": 0, "abortado": False}

        # Localizar ventanas y preparar guard+driver por red (sin lanzar nada)
        drivers = {}
        for red in self.redes:
            ventana = localizar_app(red)
            if ventana is None:
                continue
            guard = SafetyGuard(ventana, red)
            drivers[red] = DRIVERS[red](ventana, guard)

        if not drivers:
            logger.error("Ninguna app localizada. Abre las apps (con sesión) y reintenta.")
            return {"completadas": 0, "fallidas": 0, "abortado": True}

        logger.info(f"Apps disponibles: {sorted(drivers)} | Tareas: {len(cola)}")

        completadas, fallidas, abortado = 0, 0, False
        for i, tarea in enumerate(cola):
            red = tarea["red"]
            driver = drivers.get(red)
            if driver is None:
                continue
            logger.info(
                f"[{i + 1}/{len(cola)}] {tarea['tipo']} {red} — "
                f"{tarea['nombre'] or tarea['lugar_id']}"
            )
            try:
                if tarea["tipo"] == "leer":
                    ok = self._tarea_leer(driver, tarea)
                else:
                    ok = self._tarea_buscar(driver, tarea)
                completadas += 1 if ok else 0
                fallidas += 0 if ok else 1
            except AppPerdidaError as e:
                logger.error(f"{e} — la red {red} queda deshabilitada en esta sesión.")
                drivers.pop(red, None)
                fallidas += 1
                if not drivers:
                    break
            except AbortoAnomaliasError as e:
                logger.error(f"{e} — SE ABORTA LA FASE. La cola queda donde estaba.")
                abortado = True
                break
            except Exception as e:
                logger.error(f"Error inesperado en la tarea: {e}")
                fallidas += 1

        logger.info(f"Sesión terminada: {completadas} completadas, {fallidas} fallidas, abortado={abortado}")
        return {"completadas": completadas, "fallidas": fallidas, "abortado": abortado}

    # ──────────────────────────────────────────────
    # TAREAS
    # ──────────────────────────────────────────────

    def _dir_capturas(self, lugar_id: str) -> str:
        return os.path.join(self.dir_capturas, lugar_id)

    def _dominios_del_lugar(self, lugar_id: str) -> set:
        """Dominios oficiales conocidos del lugar y de su municipio padre."""
        dominios = set()
        lugar = self.lugares_por_id.get(lugar_id) or {}
        padre = self.lugares_por_id.get(lugar.get("padre_id")) or {}
        for lug in (lugar, padre):
            dom = dominio_base(lug.get("sitio_web") or "")
            if dom:
                dominios.add(dom)
        return dominios

    def _procesar_ficha(self, driver, tarea) -> bool:
        """
        Extrae la ficha del perfil abierto (bio, webs, emails, seguidores) y la
        cruza con el sitio_web del lugar/municipio:
        - coincide → confirmación máxima (bio_web_match);
        - contradice → perfil SOSPECHOSO: no se lee nada (cero falsos positivos).
        Devuelve True si se puede continuar leyendo el perfil.
        """
        lugar_id, red = tarea["lugar_id"], tarea["red"]
        ficha = driver.extraer_ficha()
        entrada = self.redes_cache.setdefault(lugar_id, {})
        entrada.setdefault("fichas", {})[red] = ficha

        dominios_lugar = self._dominios_del_lugar(lugar_id)
        dominios_bio = {dominio_base(w) for w in ficha.get("webs", [])}
        dominios_bio |= {dominio_base(e.split("@", 1)[1]) for e in ficha.get("emails", [])}
        dominios_bio.discard(None)

        continuar = True
        if dominios_lugar and dominios_bio:
            if dominios_lugar & dominios_bio:
                entrada.setdefault("bio_web_match", {})[red] = True
                logger.info(f"  [FICHA] Confirmado por web de la bio: {sorted(dominios_lugar & dominios_bio)}")
            else:
                entrada.setdefault("bio_web_match", {})[red] = False
                entrada.setdefault("sospechosos", {})[red] = date.today().isoformat()
                logger.warning(
                    f"  [FICHA] SOSPECHOSO: la bio enlaza {sorted(dominios_bio)} pero el lugar "
                    f"usa {sorted(dominios_lugar)}. No se lee este perfil."
                )
                continuar = False

        _guardar_json_atomico(self.ruta_redes_cache, self.redes_cache)
        return continuar

    def _tarea_leer(self, driver, tarea) -> bool:
        if not driver.abrir_perfil(tarea["handle"], tarea["nombre"] or ""):
            return False
        if not self._procesar_ficha(driver, tarea):
            return True  # tarea resuelta: el perfil queda marcado sospechoso, sin lectura
        posts = driver.leer_perfil_abierto(
            tarea["lugar_id"], self._dir_capturas(tarea["lugar_id"]), self.anno
        )
        self.contenido.guardar_posts(tarea["lugar_id"], tarea["red"], posts)
        return True

    def _tarea_buscar(self, driver, tarea) -> bool:
        resultado = driver.buscar_perfil(tarea["nombre"], "")
        if resultado is None:
            # Se registra el "no existe" para no repetir la búsqueda cada sesión
            self._actualizar_redes_cache(tarea["lugar_id"], tarea["red"], sin_resultado=True)
            return True  # la tarea terminó correctamente: la respuesta es "no hay perfil"

        if not self._procesar_ficha(driver, tarea):
            return True  # perfil sospechoso: ni se registra su URL ni se lee

        handle = driver.extraer_handle_visible()
        if handle:
            url = url_de_handle(tarea["red"], handle)
            self._actualizar_redes_cache(tarea["lugar_id"], tarea["red"], url=url)
            logger.info(f"  Perfil oficial nuevo: {url}")

        posts = driver.leer_perfil_abierto(
            tarea["lugar_id"], self._dir_capturas(tarea["lugar_id"]), self.anno
        )
        self.contenido.guardar_posts(tarea["lugar_id"], tarea["red"], posts)
        return True

    def _actualizar_redes_cache(self, lugar_id: str, red: str, url: str | None = None, sin_resultado: bool = False):
        entrada = self.redes_cache.setdefault(lugar_id, {})
        hoy = date.today().isoformat()
        if url:
            entrada[red] = url
            entrada.setdefault("apps_validadas", {})[red] = hoy
        if sin_resultado:
            entrada.setdefault("apps_sin_resultado", {})[red] = hoy
        # Sigue pendiente si queda alguna red sin URL y sin búsqueda in-app hecha
        entrada["pendiente_apps"] = any(
            not entrada.get(r) and r not in (entrada.get("apps_sin_resultado") or {})
            for r in REDES
        )
        _guardar_json_atomico(self.ruta_redes_cache, self.redes_cache)

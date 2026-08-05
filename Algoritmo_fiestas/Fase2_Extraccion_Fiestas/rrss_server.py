"""
Servidor RRSS — Fase 2.

Corre en Windows con las apps de RRSS ya abiertas (Instagram, Facebook, X).
Expone un API HTTP que main.py (en WSL) consume para obtener contenido de
perfiles RRSS por localidad.

El servidor envuelve el RunnerApps existente SIN modificar nada de los
drivers, SafetyGuard ni la lógica de automatización de apps.

Uso:
    py rrss_server.py --confirmo-pc-dedicado [--puerto 8787]

Endpoints:
    GET  /status     → estado del servidor y apps disponibles
    POST /procesar   → procesa perfiles RRSS para los lugar_ids indicados
    POST /shutdown   → apaga el servidor limpiamente
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Añadir Fase2 al path para importar módulos del proyecto
RUTA_FASE2 = os.path.dirname(os.path.abspath(__file__))
if RUTA_FASE2 not in sys.path:
    sys.path.insert(0, RUTA_FASE2)

from config import (
    RRSS_SERVER_PORT,
    SOCIAL_CONTENT_CACHE_FILE,
    VISION_ENABLED,
)
from scraper.social_apps.runner import RunnerApps
from scraper.social_apps.app_controller import localizar_app, PYWINAUTO_DISPONIBLE
from scraper.social_apps.cola import REDES

logger = logging.getLogger("rrss_server")

RUTA_LUGARES_DEFECTO = os.path.normpath(
    os.path.join(RUTA_FASE2, "..", "Fase1_recogida_datos_wiki", "lugares_espana.json")
)
RUTA_CACHE_CONTENIDO = os.path.join(RUTA_FASE2, SOCIAL_CONTENT_CACHE_FILE)

# Lock para serializar peticiones (las apps son secuenciales)
_lock = threading.Lock()


# ──────────────────────────────────────────────
# VLM: post-proceso de capturas
# ──────────────────────────────────────────────

def _procesar_vlm(lugar_ids: list[str]) -> dict:
    """
    Ejecuta el VLM (vision_analyzer) sobre las capturas de los lugar_ids
    indicados. Usa asyncio.run() porque el servidor HTTP es síncrono.
    """
    if not VISION_ENABLED:
        return {"procesadas": 0, "programas": 0, "deshabilitado": True}

    try:
        from llm_processor.vision_analyzer import procesar_cache_contenido
    except ImportError as e:
        logger.warning(f"No se pudo importar vision_analyzer: {e}")
        return {"procesadas": 0, "error": str(e)}

    if not os.path.exists(RUTA_CACHE_CONTENIDO):
        return {"procesadas": 0}

    try:
        with open(RUTA_CACHE_CONTENIDO, "r", encoding="utf-8") as f:
            data_completa = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error leyendo caché de contenido: {e}")
        return {"procesadas": 0, "error": str(e)}

    # Filtrar a los lugar_ids pedidos para no reprocesar todo
    ids_set = set(lugar_ids)
    data_filtrada = {k: v for k, v in data_completa.items() if k in ids_set}

    if not data_filtrada:
        return {"procesadas": 0}

    try:
        resumen = asyncio.run(procesar_cache_contenido(data_filtrada))
    except Exception as e:
        logger.error(f"Error en VLM: {e}")
        return {"procesadas": 0, "error": str(e)}

    # Merge de vuelta al archivo completo
    data_completa.update(data_filtrada)
    _guardar_atomico(RUTA_CACHE_CONTENIDO, data_completa)

    return resumen


def _guardar_atomico(path: str, data: dict):
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def _leer_contenido(lugar_ids: list[str]) -> dict:
    """Lee el contenido de RRSS de la caché para los lugar_ids indicados."""
    if not os.path.exists(RUTA_CACHE_CONTENIDO):
        return {}
    try:
        with open(RUTA_CACHE_CONTENIDO, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    ids_set = set(lugar_ids)
    return {k: v for k, v in data.items() if k in ids_set}


# ──────────────────────────────────────────────
# HTTP HANDLER
# ──────────────────────────────────────────────

class RRSSHandler(BaseHTTPRequestHandler):
    """Handler HTTP del servidor RRSS."""

    def log_message(self, format, *args):
        logger.info(f"HTTP {args[0]}")

    def _respond_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw)

    # ── GET /status ──

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        else:
            self._respond_json(404, {"error": "Not found"})

    def _handle_status(self):
        apps = {}
        if PYWINAUTO_DISPONIBLE:
            for red in REDES:
                ventana = localizar_app(red)
                apps[red] = ventana is not None
        self._respond_json(200, {
            "estado": "listo",
            "apps": apps,
            "vision_enabled": VISION_ENABLED,
            "pywinauto": PYWINAUTO_DISPONIBLE,
        })

    # ── POST /procesar | /shutdown ──

    def do_POST(self):
        if self.path == "/procesar":
            self._handle_procesar()
        elif self.path == "/shutdown":
            self._respond_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._respond_json(404, {"error": "Not found"})

    def _handle_procesar(self):
        try:
            body = self._read_body()
        except Exception as e:
            self._respond_json(400, {"error": f"JSON inválido: {e}"})
            return

        lugar_ids = body.get("lugar_ids", [])
        perfiles_extra = body.get("perfiles")

        if not lugar_ids:
            self._respond_json(400, {"error": "lugar_ids es obligatorio"})
            return

        acquired = _lock.acquire(timeout=1)
        if not acquired:
            self._respond_json(503, {
                "error": "Servidor ocupado procesando otra petición",
                "estado": "ocupado",
            })
            return

        try:
            logger.info(f">>> Procesando {len(lugar_ids)} lugar(es): {lugar_ids[:5]}...")

            # 1. Runner de apps: buscar/leer perfiles en las apps de escritorio
            runner: RunnerApps = self.server.runner
            resumen_runner = runner.ejecutar_para_lugares(lugar_ids, perfiles_extra)
            logger.info(f"    Runner: {resumen_runner}")

            # 2. VLM: analizar capturas recién generadas
            resumen_vlm = _procesar_vlm(lugar_ids)
            logger.info(f"    VLM: {resumen_vlm}")

            # 3. Leer contenido resultante de la caché
            contenido = _leer_contenido(lugar_ids)

            self._respond_json(200, {
                "runner": resumen_runner,
                "vlm": resumen_vlm,
                "contenido": contenido,
            })
        except Exception as e:
            logger.error(f"Error procesando: {e}", exc_info=True)
            self._respond_json(500, {"error": str(e)})
        finally:
            _lock.release()


# ──────────────────────────────────────────────
# SERVIDOR
# ──────────────────────────────────────────────

class RRSSHTTPServer(HTTPServer):
    """HTTPServer con referencia al RunnerApps."""
    runner: RunnerApps


def configurar_logging():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(RUTA_FASE2, f"rrss_server_{timestamp}.log"),
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)-16s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(description="Servidor RRSS (PC dedicado)")
    parser.add_argument("--puerto", type=int, default=RRSS_SERVER_PORT)
    parser.add_argument("--lugares", default=RUTA_LUGARES_DEFECTO)
    parser.add_argument("--anno", type=int, default=2026)
    parser.add_argument("--max-tareas-por-peticion", type=int, default=20)
    parser.add_argument("--redes", default=",".join(REDES))
    parser.add_argument(
        "--confirmo-pc-dedicado",
        action="store_true",
        help="Confirmas que durante la ejecución no usarás ratón/teclado",
    )
    args = parser.parse_args()

    configurar_logging()

    if not args.confirmo_pc_dedicado:
        print(
            "\nEl servidor RRSS toma el control de las apps: mientras corre NO debes\n"
            "usar el ratón ni el teclado (el guardián pausa si detecta actividad).\n\n"
            "Relanza añadiendo --confirmo-pc-dedicado para continuar."
        )
        sys.exit(2)

    if not os.path.exists(args.lugares):
        print(f"No existe el JSON de lugares: {args.lugares}")
        sys.exit(1)

    if not PYWINAUTO_DISPONIBLE:
        print("[X] pywinauto NO está instalado: py -3.11 -m pip install pywinauto")
        sys.exit(1)

    redes = tuple(r.strip() for r in args.redes.split(",") if r.strip() in REDES)

    # Diagnóstico inicial
    print("=" * 60)
    print("  SERVIDOR RRSS — Fase 2")
    print("=" * 60)
    print(f"\n  Puerto: {args.puerto}")
    print(f"  Redes: {redes}")
    print(f"  VLM: {'habilitado' if VISION_ENABLED else 'deshabilitado'}")
    print(f"\n  Ventanas de las apps:")
    for red in redes:
        ventana = localizar_app(red)
        if ventana:
            print(f"    [OK] {red}: '{ventana.window_text()}'")
        else:
            print(f"    [--] {red}: NO localizada")
    print()

    # Crear runner
    runner = RunnerApps(
        args.lugares,
        redes=redes,
        max_tareas=args.max_tareas_por_peticion,
        anno=args.anno,
    )

    # Crear y arrancar servidor HTTP
    server = RRSSHTTPServer(("0.0.0.0", args.puerto), RRSSHandler)
    server.runner = runner

    print(
        f"*** SERVIDOR RRSS ESCUCHANDO en 0.0.0.0:{args.puerto} ***\n"
        f"Desde WSL: curl http://<IP_WINDOWS>:{args.puerto}/status\n"
        f"Para apagar: POST /shutdown o Ctrl+C\n"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nApagando servidor...")
        server.shutdown()


if __name__ == "__main__":
    main()

"""
CLI del runner de apps de escritorio — Fase 2, Etapa C.

Lee los perfiles oficiales de RRSS conduciendo las apps YA ABIERTAS
(Facebook/Instagram de Microsoft Store, X como app web) con aislamiento
estricto: solo ve y toca las ventanas de esas apps, nada más del equipo.

MODOS:
  diagnostico  (por defecto) Solo lectura: localiza las ventanas, muestra la
               cola de trabajo y NO envía ni un clic ni una tecla.
  ejecutar     Procesa la cola. REQUIERE PC DEDICADO: mientras corre no debes
               usar ratón ni teclado (si tocas algo, el guardián lo pausa todo
               y reanuda cuando la app recupere el primer plano).

Ejemplos:
  py social_apps_runner.py
  py social_apps_runner.py --modo ejecutar --confirmo-pc-dedicado --max-tareas 5
  py social_apps_runner.py --modo ejecutar --confirmo-pc-dedicado --solo leer --redes facebook
"""

import argparse
import logging
import os
import sys
from datetime import datetime

from scraper.social_apps.runner import RunnerApps
from scraper.social_apps.cola import REDES

RUTA_FASE2 = os.path.dirname(os.path.abspath(__file__))
LUGARES_DEFECTO = os.path.normpath(
    os.path.join(RUTA_FASE2, "..", "Fase1_recogida_datos_wiki", "lugares_espana.json")
)


def configurar_logging():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(RUTA_FASE2, f"rrss_runner_{timestamp}.log"), encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)-16s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(description="Runner de apps de RRSS (PC dedicado)")
    parser.add_argument("--modo", choices=["diagnostico", "ejecutar"], default="diagnostico")
    parser.add_argument("--lugares", default=LUGARES_DEFECTO, help="Ruta del JSON de lugares (Fase 1)")
    parser.add_argument("--max-tareas", type=int, default=20, help="Tareas máximas en esta sesión")
    parser.add_argument("--redes", default=",".join(REDES), help="Redes a usar: instagram,facebook,twitter")
    parser.add_argument("--solo", choices=["leer", "buscar"], default=None, help="Procesar solo un tipo de tarea")
    parser.add_argument("--anno", type=int, default=2026, help="Año objetivo (ventana temporal de posts)")
    parser.add_argument(
        "--confirmo-pc-dedicado",
        action="store_true",
        help="Confirmas que durante la ejecución no usarás ratón/teclado",
    )
    args = parser.parse_args()

    configurar_logging()

    if not os.path.exists(args.lugares):
        print(f"No existe el JSON de lugares: {args.lugares}")
        sys.exit(1)

    redes = tuple(r.strip() for r in args.redes.split(",") if r.strip() in REDES)
    runner = RunnerApps(args.lugares, redes=redes, max_tareas=args.max_tareas, anno=args.anno)

    if args.modo == "diagnostico":
        runner.diagnostico()
        return

    if not args.confirmo_pc_dedicado:
        print(
            "\nEl modo ejecutar toma el control de las apps: mientras corre NO debes\n"
            "usar el ratón ni el teclado (el guardián pausa si detecta actividad,\n"
            "pero la sesión debe ser de PC dedicado).\n\n"
            "Relanza añadiendo --confirmo-pc-dedicado para continuar."
        )
        sys.exit(2)

    print(
        "\n*** PC DEDICADO ***\n"
        "El runner solo tocará las ventanas de las apps de RRSS ya abiertas.\n"
        "Si mueves el ratón o cambias de ventana, TODO se pausa hasta que la app\n"
        "recupere el primer plano. Cierra la app para abortar esa red.\n"
    )
    resumen = runner.ejecutar(solo_tipo=args.solo)
    print(f"\nResumen: {resumen}")


if __name__ == "__main__":
    main()

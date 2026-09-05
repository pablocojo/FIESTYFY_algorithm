"""
Tirada corta para probar el juez de pertenencia (paso 8) sobre municipios nuevos.

Por qué existe
--------------
El juez se ajustó contra las 42 fichas de `fiestas_amplio.json`: cuatro rondas de
prompt medidas siempre sobre los mismos 26 casos etiquetados a mano. Eso es
sobreajuste esperando a que lo confirmen, y es el mismo error con el que empezó
el proyecto —49 ejecuciones sobre Tobarra—. Este script mide sobre municipios que
el juez no ha visto.

Los municipios NO están elegidos al azar: son trampas. Los cuatro se llaman igual
que otros pueblos de España, que es exactamente el fallo que el juez existe para
corregir, y en los cuatro la capital está marcada `es_capital`, que es el arreglo
que peor calibrado quedó.

  Santa Marta (Badajoz)   Comparte nombre con Santa Marta (Albacete) —la pedanía
                          a la que se le colgaron los 64 actos de las fiestas de
                          Astorga— y con Santa Marta de Tormes (Salamanca). Si el
                          juez acepta las fiestas de ESTA y rechaza las de las
                          otras, funciona. Es el caso adversario del proyecto.
  La Parra (Badajoz)      Seis homónimos en España, uno de ellos La Parra (Ávila),
                          que también está en el conjunto monolingüe.
  El Fresno (Ávila)       Cuatro homónimos.
  Corral-Rubio (Albacete) Tres localidades; su pedanía La Higuera también repite
                          nombre. Ejercita la regla del evento municipal.

Se listan cuatro para hora y media a propósito: el plazo manda y corta donde
llegue. Lo que no entre queda para la siguiente.

Uso
---
  py probar_juez.py                 # hora y media, informe del juez al final
  py probar_juez.py --horas 3       # más margen
  py probar_juez.py --solo-informe  # releer la última salida sin ejecutar nada

Escribe en `fiestas_prueba_juez.json`, aparte de la línea base y de la tirada
amplia. No toca ninguna de las dos.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import time
from datetime import datetime

_AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(_AQUI, "fiestas_prueba_juez.json")

# Por id y no por nombre: hay cuatro "Santa Marta" en el dataset y resolver por
# nombre coge el primero que encuentra.
MUNICIPIOS = [
    ("06121000000", "Santa Marta",  "Badajoz",  "homónima de la pedanía del caso Astorga"),
    ("06099000000", "La Parra",     "Badajoz",  "6 homónimos, uno en Ávila"),
    ("05076000000", "El Fresno",    "Ávila",    "4 homónimos"),
    ("02027000000", "Corral-Rubio", "Albacete", "3 localidades; pedanía homónima"),
]

_RE_PERTENENCIA = re.compile(r"\[PERTENENCIA\]\s*(.*)")


def informe_del_juez(desde: float) -> None:
    """
    Qué decidió el juez, leído de los logs que ha dejado la tirada.

    Es el motivo de este script: `ejecutar_amplio` dice cuántas fichas salieron,
    pero lo que hay que mirar aquí es qué se descartó y por qué. El juez deja
    cada veredicto en el log con su razón y el lugar al que manda la ficha, así
    que la propia ejecución se autoevalúa sin volver a etiquetar a mano.
    """
    logs = [p for p in glob.glob(os.path.join(_AQUI, "fase2_*.log"))
            if os.path.getmtime(p) >= desde]
    if not logs:
        print("\n  No hay logs de esta tirada que leer.")
        return

    descartes, conservadas, avisos = [], [], []
    for ruta in sorted(logs):
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for linea in f:
                m = _RE_PERTENENCIA.search(linea)
                if not m:
                    continue
                texto = m.group(1).strip()
                if texto.startswith("DESCARTADA"):
                    descartes.append(texto)
                elif "Se conserva" in texto:
                    conservadas.append(texto)
                elif "fichas descartadas" in texto:
                    avisos.append(texto)

    print(f"\n{'=' * 78}\n  QUÉ DECIDIÓ EL JUEZ DE PERTENENCIA\n{'=' * 78}")
    if not (descartes or conservadas):
        print("  El juez no llegó a pronunciarse: ninguna ficha llegó al paso 8.")
        print("  Comprueba que PERTENENCIA_ENABLED sigue en True en config.py.")
        return

    print(f"\n  DESCARTADAS ({len(descartes)}) — cada una con el motivo del modelo:")
    for d in descartes or ["(ninguna)"]:
        print(f"     {d[:150]}")

    if conservadas:
        print(f"\n  RESCATADAS POR UN VETO DEL CÓDIGO ({len(conservadas)}):")
        for c in conservadas:
            print(f"     {c[:150]}")

    for a in avisos:
        print(f"\n  {a}")

    print(f"""
  CÓMO LEERLO
    - Un descarte que nombra otra provincia o el municipio como dueño de la
      fiesta es un acierto: es para lo que está.
    - Un descarte de unas patronales con programa y fuente del propio pueblo es
      un FALSO POSITIVO, y es lo que hay que vigilar: perder fiestas reales de
      pueblos pequeños es peor que dejar pasar alguna falsa.
    - Si Santa Marta (Badajoz) sale con sus fiestas y ninguna es de Astorga ni
      de Salamanca, el caso adversario del proyecto está resuelto.""")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Tirada corta sobre municipios trampa para probar el juez de pertenencia.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__,
    )
    p.add_argument("--horas", type=float, default=1.5)
    p.add_argument("--salida", default=SALIDA)
    p.add_argument("--solo-informe", action="store_true")
    p.add_argument("--reiniciar", action="store_true",
                   help="Borrar la salida previa y empezar de cero.")
    args = p.parse_args()

    print("=" * 78)
    print("  PRUEBA DEL JUEZ DE PERTENENCIA — municipios elegidos por homonimia")
    print("=" * 78)
    for _id, nombre, prov, motivo in MUNICIPIOS:
        print(f"   {nombre[:20]:22s}{prov[:10]:11s}{motivo}")
    print(f"\n   Plazo: {args.horas} h · salida: {os.path.basename(args.salida)}")
    print("   El plazo corta donde llegue; lo que no entre queda para la siguiente.")

    inicio = time.time()

    if not args.solo_informe:
        cmd = [sys.executable, os.path.join(_AQUI, "ejecutar_amplio.py"),
               "--nombres", *[m[0] for m in MUNICIPIOS],
               "--horas", str(args.horas),
               "--salida", args.salida,
               "--max-localidades", "4"]
        if args.reiniciar:
            cmd.append("--reiniciar")
        print(f"\n  $ {' '.join(os.path.basename(c) if c.endswith('.py') else c for c in cmd)}\n")
        r = subprocess.run(cmd, cwd=_AQUI)
        if r.returncode != 0:
            print(f"\n  [!] ejecutar_amplio.py terminó con código {r.returncode}.")
    else:
        # Sin ejecutar, se miran los logs de las últimas 24 horas.
        inicio = time.time() - 24 * 3600

    informe_del_juez(inicio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Ejecuta la Fase 2 sobre MUCHOS municipios nuevos, con un plazo de reloj.

Para qué es
-----------
`ejecutar_neutros.py` corre siempre sobre los mismos cuatro municipios: es la
línea base con la que se compara un cambio. Este script es lo contrario: coge
municipios que no se han tocado nunca y los procesa hasta agotar un plazo, para
responder a la única pregunta que la línea base no puede responder —si lo que
funciona en Tobarra y Aranda de Duero funciona en un pueblo cualquiera—.

Contando todos los logs, Tobarra aparece en 49 ejecuciones y Aranda en 37, y el
conjunto dorado son esos dos más Amurrio. El conjunto de desarrollo y el de
validación son el mismo, así que ninguna métrica de hoy dice nada sobre el resto
de España. De ahí este script.

Cómo trabaja
------------
Llama a `main.py` UNA VEZ POR MUNICIPIO en vez de pasarle la lista entera. Cuesta
unos segundos más de arranque por municipio y a cambio da tres cosas que en una
sola llamada no se tienen:

  * Se puede parar en seco al cumplirse el plazo, entre municipios y no a mitad
    de uno, dejando la salida coherente.
  * Un municipio que se atasca se corta por su propio tope sin llevarse la noche
    por delante. Lo ya extraído se conserva: `state_manager` hace checkpoint por
    localidad.
  * Se mide el tiempo de cada municipio por separado, que es justamente el dato
    que se quiere de una ejecución larga.

El estado se acumula solo: `StateManager` relee la salida, deduplica por `id` de
fiesta y salta los municipios ya completados. Cortar y relanzar es seguro.

Uso
---
  py ejecutar_amplio.py --listar                 # ver la muestra elegida y salir
  py ejecutar_amplio.py                          # 7 horas, muestra por defecto
  py ejecutar_amplio.py --horas 3 --municipios 6
  py ejecutar_amplio.py --semilla 7              # otra muestra, reproducible
  py ejecutar_amplio.py --solo-informe           # releer la salida y analizarla

No toca `fiestas_neutros.json` ni el conjunto dorado: escribe en
`fiestas_amplio.json`.
"""

import argparse
import collections
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta

from ejecutar_neutros import (
    FUENTE_POR_DEFECTO,
    TIPOS_LOCALIDAD,
    agrupar,
    candidatos,
    cargar,
    informe,
    resolver,
)

_AQUI = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(_AQUI, "lugares_amplio_input.json")
SALIDA = os.path.join(_AQUI, "fiestas_amplio.json")
BITACORA = os.path.join(_AQUI, "amplio_bitacora.json")

# Los municipios sobre los que se ha desarrollado. Meterlos en una ejecución que
# existe para medir generalización sería medirse a uno mismo.
YA_TRABAJADOS = {"Tobarra", "Aranda de Duero", "Amurrio"}

# Tramos de población. El pipeline se ajustó sobre Aranda (33.904 hab) y Tobarra
# (8.002), y la España que falta por procesar está casi entera por debajo: de los
# 1.553 municipios del dataset, la inmensa mayoría son de tres cifras. Una muestra
# que no cubra los tramos pequeños no mide lo que hay que medir.
TRAMOS = [(0, 500), (500, 2_000), (2_000, 10_000), (10_000, 10**9)]

# Minutos por localidad con los que se estima antes de tener medidas propias. La
# última ejecución dio 12,2 min/localidad CON las cachés calientes; aquí van
# frías, así que se parte de más y el script se recalibra solo sobre la marcha.
MIN_POR_LOCALIDAD_INICIAL = 16.0


def _tramo(poblacion) -> int:
    p = poblacion or 0
    for i, (bajo, alto) in enumerate(TRAMOS):
        if bajo <= p < alto:
            return i
    return len(TRAMOS) - 1


def _nombre_tramo(i: int) -> str:
    bajo, alto = TRAMOS[i]
    return f"<{alto}" if bajo == 0 else (f">{bajo}" if alto > 10**8 else f"{bajo}-{alto}")


def seleccionar(pool, cuantos, semilla, min_loc, max_loc, ya_hechos):
    """
    Muestra repartida por provincia y por tamaño, reproducible con la semilla.

    Se hace por reparto en corro sobre las casillas (provincia, tramo) en vez de
    coger los N primeros de una lista barajada: con 996 candidatos y 367 de ellos
    en Burgos, una muestra al azar sale casi entera de Burgos y de pueblos de
    menos de 500 habitantes, que es la casilla más poblada. Eso no es variedad,
    es la misma prueba repetida.
    """
    casillas = collections.defaultdict(list)
    for m, locs in pool:
        if m["nombre"] in YA_TRABAJADOS or m["id"] in ya_hechos:
            continue
        if not (min_loc <= len(locs) + 1 <= max_loc):
            continue
        casillas[(m.get("provincia") or "?", _tramo(m.get("poblacion")))].append((m, locs))

    rnd = random.Random(semilla)
    for v in casillas.values():
        v.sort(key=lambda t: t[0]["id"])      # orden estable antes de barajar
        rnd.shuffle(v)

    claves = sorted(casillas)
    rnd.shuffle(claves)
    elegidos = []
    while len(elegidos) < cuantos and any(casillas[c] for c in claves):
        for c in claves:
            if casillas[c]:
                elegidos.append(casillas[c].pop())
                if len(elegidos) >= cuantos:
                    break
    return elegidos


def escribir_entrada_de(municipio, locs, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump([municipio] + list(locs), f, ensure_ascii=False, indent=1)


def leer_salida(ruta):
    if not os.path.exists(ruta):
        return {"fiestas": [], "localidades_completadas": [], "municipios_completados": []}
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"fiestas": [], "localidades_completadas": [], "municipios_completados": []}


def _hhmm(segundos):
    return str(timedelta(seconds=int(max(0, segundos))))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Fase 2 sobre muchos municipios nuevos, con plazo de reloj.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--horas", type=float, default=7.0, help="Plazo total (por defecto 7).")
    p.add_argument("--municipios", type=int, default=None,
                   help="Tope de municipios. Por defecto se dimensiona al plazo, "
                        "con reserva por si el ritmo real sale mejor que el estimado.")
    p.add_argument("--semilla", type=int, default=2026, help="Semilla de la muestra.")
    p.add_argument("--min-localidades", type=int, default=2)
    p.add_argument("--max-localidades", type=int, default=7,
                   help="Municipios enormes gastan el plazo en uno solo.")
    p.add_argument("--tope-municipio", type=float, default=75.0,
                   help="Minutos máximos por municipio antes de cortarlo y seguir.")
    p.add_argument("--nombres", nargs="+", metavar="NOMBRE",
                   help="Municipios concretos en vez de la muestra automática.")
    p.add_argument("--fuente", default=FUENTE_POR_DEFECTO)
    p.add_argument("--salida", default=SALIDA)
    p.add_argument("--anno", type=int, default=2026)
    p.add_argument("--con-rrss", action="store_true",
                   help="Usar el servidor de RRSS. Desaconsejado sin vigilancia.")
    p.add_argument("--listar", action="store_true", help="Ver la muestra y salir.")
    p.add_argument("--solo-informe", action="store_true", help="Analizar la salida existente.")
    p.add_argument("--reiniciar", action="store_true", help="Borrar la salida previa.")
    args = p.parse_args()

    if not os.path.exists(args.fuente):
        print(f"No existe el dataset de Fase 1: {args.fuente}")
        return 1

    lugares = cargar(args.fuente)
    hijos = agrupar(lugares)

    if args.reiniciar and os.path.exists(args.salida) and not args.solo_informe:
        os.remove(args.salida)
        print("  --reiniciar: borrada la salida previa.")

    previo = leer_salida(args.salida)
    ya_hechos = set(previo.get("municipios_completados", []))

    if args.nombres:
        elegidos = resolver(args.nombres, lugares, hijos)
    else:
        # Se elige DE MÁS a propósito: el plazo es quien corta, y si el ritmo real
        # sale mejor que el estimado conviene tener municipios de reserva en la
        # lista en vez de terminar antes de hora con el equipo parado.
        cuantos = args.municipios or max(
            4, int(args.horas * 60 / MIN_POR_LOCALIDAD_INICIAL / 2.5 * 1.8)
        )
        elegidos = seleccionar(
            candidatos(lugares, hijos), cuantos, args.semilla,
            args.min_localidades, args.max_localidades, ya_hechos,
        )
    if not elegidos:
        print("La muestra ha salido vacía. Prueba a subir --max-localidades o cambiar --semilla.")
        return 1

    if args.solo_informe:
        informe(args.salida, elegidos)
        return 0

    total_loc = sum(len(locs) + 1 for _, locs in elegidos)
    print("=" * 78)
    print(f"  EJECUCIÓN AMPLIA — {len(elegidos)} municipios, {total_loc} localidades")
    print(f"  Plazo: {args.horas} h · tope por municipio: {args.tope_municipio:.0f} min "
          f"· semilla {args.semilla}")
    print(f"  Salida: {os.path.basename(args.salida)}"
          + (f" (reanuda: {len(ya_hechos)} municipios ya hechos)" if ya_hechos else ""))
    print("=" * 78)
    porcom = collections.Counter()
    acumulado, cortado_ya, n_dentro, loc_dentro = 0.0, False, 0, 0
    for m, locs in elegidos:
        porcom[(m.get("provincia"), _nombre_tramo(_tramo(m.get("poblacion"))))] += 1
        n_loc = len(locs) + 1
        acumulado += n_loc * MIN_POR_LOCALIDAD_INICIAL
        if acumulado > args.horas * 60 and not cortado_ya:
            cortado_ya = True
            print(f"   {'- ' * 12}hasta aquí caben en las {args.horas:g} h estimadas"
                  f"{' -' * 6}")
        if not cortado_ya:
            n_dentro, loc_dentro = n_dentro + 1, loc_dentro + n_loc
        marca = "  (ya hecho, se salta)" if m["id"] in ya_hechos else ""
        print(f"   {m['nombre'][:26]:26s} {m.get('provincia','')[:10]:10s} "
              f"{m.get('poblacion') or 0:>7} hab  {n_loc:2d} loc{marca}")
    print(f"\n  Reparto por provincia y tamaño: "
          f"{len(porcom)} casillas distintas de {len(elegidos)} municipios")
    print(f"  A {MIN_POR_LOCALIDAD_INICIAL:.0f} min/localidad se estiman {n_dentro} municipios "
          f"y {loc_dentro} localidades dentro del plazo; el resto queda de reserva")
    print(f"  por si el ritmo real sale mejor. Manda el reloj, no la lista.")

    if args.listar:
        return 0

    inicio = time.time()
    limite = inicio + args.horas * 3600
    min_por_loc = MIN_POR_LOCALIDAD_INICIAL
    bitacora, hechos, saltados = [], 0, 0
    n_fiestas_previo = len(previo.get("fiestas", []))

    try:
        for i, (m, locs) in enumerate(elegidos, 1):
            if m["id"] in ya_hechos:
                saltados += 1
                continue

            n_loc = len(locs) + 1
            estimado = n_loc * min_por_loc * 60
            restante = limite - time.time()
            if restante <= 0:
                print(f"\n  Plazo agotado. Quedaban {len(elegidos) - i + 1} municipios sin empezar.")
                break
            if estimado > restante:
                print(f"\n  [{i}/{len(elegidos)}] {m['nombre']}: se estiman "
                      f"{estimado / 60:.0f} min y quedan {restante / 60:.0f}. No se empieza: "
                      f"un municipio a medias no sirve para medir.")
                break

            print(f"\n{'-' * 78}")
            print(f"  [{i}/{len(elegidos)}] {m['nombre']} ({m.get('provincia')}, {n_loc} loc) "
                  f"— quedan {_hhmm(restante)} de plazo")
            print(f"{'-' * 78}")

            escribir_entrada_de(m, locs, ENTRADA)
            cmd = [sys.executable, os.path.join(_AQUI, "main.py"),
                   "--input", ENTRADA, "--output", args.salida,
                   "--anno", str(args.anno), "--parallel", "1"]
            if not args.con_rrss:
                cmd.append("--sin-rrss")

            t0 = time.time()
            cortado = False
            # El tope se recorta al plazo que queda: sin esto, el último municipio
            # podría pasarse de la hora de fin por su propio tope.
            tope = min(args.tope_municipio * 60, max(60.0, limite - t0))
            try:
                r = subprocess.run(cmd, cwd=_AQUI, timeout=tope)
                codigo = r.returncode
            except subprocess.TimeoutExpired:
                cortado, codigo = True, -1
                print(f"  [!] {m['nombre']} cortado a los {tope / 60:.0f} min. "
                      f"Lo extraído hasta ahora queda guardado (checkpoint por localidad).")
            dur = time.time() - t0

            estado = leer_salida(args.salida)
            fiestas_m = [f for f in estado.get("fiestas", [])
                         if any(f.get("lugar_id") == l["id"] for l in [m] + list(locs))]
            loc_con = {f.get("lugar_id") for f in fiestas_m}
            bitacora.append({
                "municipio": m["nombre"], "id": m["id"], "provincia": m.get("provincia"),
                "poblacion": m.get("poblacion"), "localidades": n_loc,
                "minutos": round(dur / 60, 1), "min_por_localidad": round(dur / 60 / n_loc, 1),
                "fiestas": len(fiestas_m),
                "localidades_con_fiesta": len(loc_con),
                "localidades_sin_fiesta": n_loc - len(loc_con),
                "cortado_por_tope": cortado, "codigo_salida": codigo,
            })
            hechos += 1
            print(f"  -> {m['nombre']}: {len(fiestas_m)} fiestas, "
                  f"{len(loc_con)}/{n_loc} localidades con ficha, {dur / 60:.1f} min "
                  f"({dur / 60 / n_loc:.1f} min/localidad)")

            # Recalibración: la media real de lo que llevamos, que es mejor
            # estimador que una constante escrita a mano hace semanas.
            if not cortado:
                vistos = [b for b in bitacora if not b["cortado_por_tope"]]
                min_por_loc = sum(b["minutos"] for b in vistos) / sum(b["localidades"] for b in vistos)

            with open(BITACORA, "w", encoding="utf-8") as f:
                json.dump({"inicio": datetime.fromtimestamp(inicio).isoformat(),
                           "semilla": args.semilla, "municipios": bitacora}, f,
                          ensure_ascii=False, indent=2)

    except KeyboardInterrupt:
        print("\n  Interrumpido a mano. Lo hecho hasta ahora está guardado.")

    # ── Resumen ──────────────────────────────────────────────
    transcurrido = time.time() - inicio
    estado = leer_salida(args.salida)
    print(f"\n{'=' * 78}")
    print(f"  FIN — {_hhmm(transcurrido)} de reloj, {hechos} municipios procesados"
          + (f" ({saltados} ya estaban hechos)" if saltados else ""))
    print(f"{'=' * 78}")
    if bitacora:
        print(f"\n  {'MUNICIPIO':24s}{'PROV':12s}{'loc':>4}{'fiestas':>8}"
              f"{'sin ficha':>10}{'min':>7}{'min/loc':>8}")
        for b in bitacora:
            corte = " CORTADO" if b["cortado_por_tope"] else ""
            print(f"  {b['municipio'][:23]:24s}{(b['provincia'] or '')[:11]:12s}"
                  f"{b['localidades']:>4}{b['fiestas']:>8}{b['localidades_sin_fiesta']:>10}"
                  f"{b['minutos']:>7.0f}{b['min_por_localidad']:>8.1f}{corte}")
        n_loc = sum(b["localidades"] for b in bitacora)
        sin = sum(b["localidades_sin_fiesta"] for b in bitacora)
        print(f"\n  Localidades procesadas: {n_loc} | sin ninguna ficha: {sin} "
              f"({sin / max(n_loc, 1):.0%})")
        print(f"  Fiestas nuevas en esta tirada: "
              f"{len(estado.get('fiestas', [])) - n_fiestas_previo}")
        print(f"  Ritmo medio: {transcurrido / 60 / max(n_loc, 1):.1f} min/localidad")
        print(f"  Bitácora: {os.path.basename(BITACORA)}")

    informe(args.salida, elegidos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

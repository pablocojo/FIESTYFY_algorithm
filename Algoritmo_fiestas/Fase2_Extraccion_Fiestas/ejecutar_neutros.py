"""
Ejecuta la Fase 2 sobre municipios CASTELLANOHABLANTES, como línea base.

La idea es aislar la variable idioma. En Amurrio el programa de la capital salió
en euskera porque la web municipal es bilingüe y el modelo se llevó los chunks
que le tocaron, mezclando "misa NAGUSIA" y "LANDAKO misa". Sobre un municipio
monolingüe ese ruido no existe, así que lo que falle ahí falla de verdad.

  py ejecutar_neutros.py                          # el conjunto por defecto
  py ejecutar_neutros.py --listar                 # ver qué municipios hay disponibles
  py ejecutar_neutros.py --municipios Tobarra "Aranda de Duero"
  py ejecutar_neutros.py --reiniciar              # empezar de cero, sin reanudar
  py ejecutar_neutros.py --solo-preparar          # generar la entrada y no ejecutar
  py ejecutar_neutros.py --solo-informe           # releer la última salida y analizarla

NOTA sobre Madrid: no está en el dataset. Fase 1 solo recogió Asturias, Castilla
y León, Cataluña, Comunidad Valenciana, Andalucía, Extremadura, Castilla-La
Mancha y País Vasco. De esas, las monolingües en castellano son las cuatro que
usa este script.
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime

_AQUI = os.path.dirname(os.path.abspath(__file__))
FUENTE_POR_DEFECTO = os.path.join(
    _AQUI, "..", "Fase1_recogida_datos_wiki", "lugares_espana_actualizado.json"
)
ENTRADA_FILTRADA = os.path.join(_AQUI, "lugares_neutros_input.json")
SALIDA = os.path.join(_AQUI, "fiestas_neutros.json")

# Comunidades sin lengua cooficial: aquí el nombre de un acto no puede aparecer
# en dos idiomas, que es lo que dejaba pasar las copias entre localidades.
COMUNIDADES_MONOLINGUES = {
    "Castilla y León", "Castilla-La Mancha", "Extremadura", "Andalucía",
}

TIPOS_LOCALIDAD = {"pueblo", "ciudad_pequena", "ciudad_grande", "distrito", "barrio"}

# Conjunto por defecto: cuatro municipios de cuatro provincias distintas, todos
# con pedanías (que es donde estaban todos los fallos) y con web propia que
# rastrear. Suman 21 localidades, unos 40 minutos de ejecución.
MUNICIPIOS_POR_DEFECTO = [
    "Aranda de Duero",        # Burgos, 33.904 hab, 5 localidades
    "Tobarra",                # Albacete, 8.002 hab, 7 localidades
    "Vélez-Rubio",            # Almería, 6.670 hab, 5 localidades
    "Arenas de San Pedro",    # Ávila, 6.480 hab, 4 localidades
]


# ──────────────────────────────────────────────────────────────
# CARGA Y FILTRADO
# ──────────────────────────────────────────────────────────────

def _clave(nombre: str) -> str:
    t = unicodedata.normalize("NFKD", (nombre or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def cargar(ruta: str) -> list[dict]:
    with open(ruta, "r", encoding="utf-8-sig") as f:
        d = json.load(f)
    return d["lugares"] if isinstance(d, dict) and "lugares" in d else d


def agrupar(lugares: list[dict]) -> dict[str, list[dict]]:
    """Descendientes por municipio, con la misma regla que usa main.py."""
    hijos = collections.defaultdict(list)
    ids_municipio = {l["id"] for l in lugares if l.get("tipo") == "municipio"}
    for l in lugares:
        for clave in ("padre_id", "abuelo_id"):
            padre = l.get(clave)
            if padre and padre in ids_municipio:
                hijos[padre].append(l)
                break
    return hijos


def candidatos(lugares: list[dict], hijos: dict) -> list[tuple]:
    """Municipios monolingües con web propia y al menos una localidad."""
    out = []
    for m in lugares:
        if m.get("tipo") != "municipio" or m.get("comunidad") not in COMUNIDADES_MONOLINGUES:
            continue
        if not (m.get("sitio_web") or "").strip():
            continue
        locs = [h for h in hijos.get(m["id"], []) if h.get("tipo") in TIPOS_LOCALIDAD]
        if locs:
            out.append((m, locs))
    return out


def resolver(pedidos: list[str], lugares: list[dict], hijos: dict) -> list[tuple]:
    """
    Empareja lo que pide el usuario (nombre o id) con los municipios reales.

    Se busca sobre TODOS los municipios, no solo los monolingües: el conjunto por
    defecto es la línea base, pero nombrar uno a mano tiene que funcionar —para
    volver sobre Amurrio, o para comparar contra un municipio bilingüe cuando
    toque atacar el idioma. Si el elegido no es de los neutros, se avisa.
    """
    todos = {}
    for m in lugares:
        if m.get("tipo") != "municipio":
            continue
        locs = [h for h in hijos.get(m["id"], []) if h.get("tipo") in TIPOS_LOCALIDAD]
        todos[m["id"]] = (m, locs)
    por_nombre = {}
    for m, locs in todos.values():
        por_nombre.setdefault(_clave(m["nombre"]), (m, locs))

    elegidos, faltan = [], []
    for p in pedidos:
        hit = todos.get(p.strip()) or por_nombre.get(_clave(p))
        if hit:
            elegidos.append(hit)
        else:
            faltan.append(p)
    if faltan:
        print(f"  [!] No existen como municipio en el dataset: {', '.join(faltan)}")
        print("      Usa --listar para ver los disponibles.")

    for m, locs in elegidos:
        avisos = []
        if m.get("comunidad") not in COMUNIDADES_MONOLINGUES:
            avisos.append(f"{m.get('comunidad')} tiene lengua cooficial: no sirve de línea base")
        if not (m.get("sitio_web") or "").strip():
            avisos.append("sin web municipal que rastrear")
        if not locs:
            avisos.append("sin pedanías: no ejercita el anticopia entre localidades")
        if avisos:
            print(f"  [!] {m['nombre']}: {'; '.join(avisos)}.")
    return elegidos


def escribir_entrada(elegidos: list[tuple], ruta: str) -> int:
    seleccion = []
    for m, locs in elegidos:
        seleccion.append(m)
        seleccion.extend(locs)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(seleccion, f, ensure_ascii=False, indent=1)
    return len(seleccion)


# ──────────────────────────────────────────────────────────────
# INFORME SOBRE LA SALIDA
# ──────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def informe(ruta_salida: str, elegidos: list[tuple]) -> None:
    """
    Las mismas comprobaciones que veníamos haciendo a mano cada vez: qué salió,
    si un acto se repite día tras día, si dos localidades comparten actos y si
    a alguna se le ha colado el nombre de otra dentro del programa.
    """
    if not os.path.exists(ruta_salida):
        print(f"\n  No hay salida que analizar en {ruta_salida}")
        return
    with open(ruta_salida, "r", encoding="utf-8") as f:
        datos = json.load(f)
    fiestas = datos.get("fiestas", [])

    nombres, capitales, municipio_de = {}, set(), {}
    for m, locs in elegidos:
        for l in [m] + locs:
            nombres[l["id"]] = l["nombre"]
            municipio_de[l["id"]] = m["nombre"]
            if l.get("es_capital"):
                capitales.add(l["id"])

    print(f"\n{'=' * 78}\n  RESULTADO  ({len(fiestas)} fichas, "
          f"{len(datos.get('localidades_completadas', []))} localidades procesadas)\n{'=' * 78}")

    por_municipio = collections.defaultdict(list)
    for f in fiestas:
        por_municipio[municipio_de.get(f.get("lugar_id"), "?")].append(f)

    for muni, fs in sorted(por_municipio.items()):
        print(f"\n### {muni}")
        con_ficha = {f["lugar_id"] for f in fs}
        for f in sorted(fs, key=lambda x: (nombres.get(x["lugar_id"], ""), x["fecha_inicio"])):
            prog = f.get("programa") or []
            actos = sum(len(d.get("eventos", [])) for d in prog)
            marca = " (capital)" if f["lugar_id"] in capitales else ""
            estado = {"completo": "", "parcial": " PROGRAMA A MEDIAS",
                      "no_encontrado": " SIN PROGRAMA"}.get(f.get("programa_estado"), "")
            print(f"   {nombres.get(f['lugar_id'], f['lugar_id']):22s}{marca:10s} "
                  f"{f['fecha_inicio']}~{f['fecha_fin']} {len(prog)}d {actos:3d} actos  "
                  f"[{f.get('origen')}/{f.get('confianza')}]  {f['nombre'][:38]}{estado}")
        # Localidades de este municipio que no han dado ninguna ficha.
        del_muni = [l["id"] for m, locs in elegidos if m["nombre"] == muni for l in [m] + locs]
        sin = [nombres[i] for i in del_muni if i not in con_ficha and i in nombres
               and any(i == l["id"] for m, locs in elegidos for l in locs)]
        if sin:
            print(f"   SIN FIESTA: {', '.join(sin)}")

    # ── Comprobaciones de calidad ────────────────────────────
    print(f"\n{'-' * 78}\n  COMPROBACIONES\n{'-' * 78}")

    problemas = 0

    # Se usan las funciones de producción, no una copia: si el criterio de qué
    # es un acto concreto cambia allí, este informe cambia con él. Con un
    # criterio propio marcaba "Tardeo" repetido, que la regla real permite a
    # propósito por ser corto y genérico.
    from llm_processor.text_analyzer import _acto_es_concreto

    reps = []
    for f in fiestas:
        claves, total = [], 0
        for d in f.get("programa") or []:
            for e in d.get("eventos", []):
                total += 1
                if _acto_es_concreto(e.get("descripcion", "")):
                    claves.append((_norm(e.get("descripcion", "")), (e.get("hora") or "").strip()))
        r = sum(c - 1 for c in collections.Counter(claves).values() if c > 1)
        if r:
            reps.append((nombres.get(f["lugar_id"], "?"), r, total))
    if reps:
        problemas += 1
        print("  Actos repetidos dentro de una misma fiesta:")
        for n, r, t in reps:
            print(f"     {n:22s} {r} de {t}")
    else:
        print("  Actos repetidos dentro de una fiesta: ninguno")

    # Actos compartidos entre localidades distintas del mismo municipio.
    por_acto = collections.defaultdict(set)
    for f in fiestas:
        for d in f.get("programa") or []:
            for e in d.get("eventos", []):
                desc = _norm(e.get("descripcion", ""))
                if len(desc) > 12:
                    por_acto[desc].add(f.get("lugar_id"))
    compartidos = {a: l for a, l in por_acto.items() if len(l) >= 2}
    if compartidos:
        problemas += 1
        print(f"  Actos que figuran en 2+ localidades: {len(compartidos)}")
        for a, l in list(compartidos.items())[:5]:
            print(f"     {a[:52]:52s} -> {', '.join(nombres.get(i, i) for i in l)}")
    else:
        print("  Actos compartidos entre localidades: ninguno")

    # El nombre de otra localidad del municipio dentro del programa.
    #
    # Salvo cuando lo que viaja es el grupo, no el acto. "Misa y procesión con
    # la Agrupación Musical Santa Mujer Verónica de Tobarra" es un acto de
    # Cordovilla y está bien: las bandas, charangas y peñas tocan por todo el
    # municipio y se las nombra por su pueblo de origen. Sin esta salvedad, el
    # informe marcaba el programa MEJOR extraído del run como contaminado.
    procedencia = re.compile(
        r"\b(?:agrupacion|banda|charanga|orquesta|coro|rondalla|grupo|asociacion|"
        r"peña|pena|comparsa|academia|escuela|club|union)\b[^.;]{0,60}?\bde $"
    )
    for f in fiestas:
        propio = _norm(nombres.get(f["lugar_id"], ""))
        cuerpo = _norm(" ".join(e.get("descripcion", "") for d in f.get("programa") or []
                                for e in d.get("eventos", [])))
        ajenas = set()
        for i, n in nombres.items():
            if _norm(n) == propio:
                continue
            for m in re.finditer(rf"\b{re.escape(_norm(n))}\b", cuerpo):
                if not procedencia.search(cuerpo[:m.start()]):
                    ajenas.add(n)
                    break
        if ajenas:
            problemas += 1
            print(f"  [!] El programa de {nombres.get(f['lugar_id'])} nombra a: {', '.join(ajenas)}")

    vacias = [nombres.get(f["lugar_id"], "?") for f in fiestas
              if not (f.get("programa") or []) and f.get("origen") != "santo_patron"]
    if vacias:
        print(f"  Fichas sin programa (no estimadas): {', '.join(vacias)}")

    # Días sin un solo acto dentro del rango. O sobran días o falta programa, y
    # en ambos casos la ficha está mal. Es el defecto que más se repite ahora:
    # Tobarra anunciaba San Antón del 17 al 31 de enero con actos solo tres días.
    flojas = []
    for f in fiestas:
        prog = f.get("programa") or []
        if not prog or f.get("origen") == "santo_patron":
            continue
        sin = sum(1 for d in prog if not d.get("eventos"))
        if sin:
            flojas.append((nombres.get(f["lugar_id"], "?"), f["nombre"], sin, len(prog)))
    if flojas:
        problemas += 1
        print("  Días sin ningún acto (rango demasiado ancho o programa incompleto):")
        for n, nom, sin, tot in sorted(flojas, key=lambda t: -t[2]):
            print(f"     {n:22s} {sin:2d} de {tot:2d} días vacíos   {nom[:38]}")

    print(f"\n  {'Sin problemas detectados.' if not problemas else 'Revisar lo marcado arriba.'}")


# ──────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description="Fase 2 sobre municipios monolingües en castellano, como línea base.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--municipios", nargs="+", metavar="NOMBRE",
                   help="Municipios por nombre o por id. Por defecto, el conjunto base.")
    p.add_argument("--fuente", default=FUENTE_POR_DEFECTO, help="Dataset de Fase 1.")
    p.add_argument("--salida", default=SALIDA, help="JSON de resultados.")
    p.add_argument("--anno", type=int, default=2026)
    p.add_argument("--parallel", type=int, default=1,
                   help="Municipios en paralelo. 1 deja el log legible (por defecto).")
    p.add_argument("--listar", action="store_true", help="Listar municipios disponibles y salir.")
    p.add_argument("--solo-preparar", action="store_true", help="Generar la entrada y no ejecutar.")
    p.add_argument("--solo-informe", action="store_true", help="Analizar la salida existente.")
    p.add_argument("--sin-rrss", action="store_true",
                   help="No usar el servidor de RRSS (ejecuciones desatendidas).")
    p.add_argument("--reiniciar", action="store_true",
                   help="Borrar la salida previa. Sin esto se reanuda donde se quedó.")
    args = p.parse_args()

    if not os.path.exists(args.fuente):
        print(f"No existe el dataset de Fase 1: {args.fuente}")
        return 1

    lugares = cargar(args.fuente)
    hijos = agrupar(lugares)

    if args.listar:
        cands = candidatos(lugares, hijos)
        print(f"{len(cands)} municipios monolingües con web propia y pedanías.\n")
        por_com = collections.defaultdict(list)
        for m, locs in cands:
            por_com[m["comunidad"]].append((m, locs))
        for com, v in sorted(por_com.items()):
            v.sort(key=lambda t: -(t[0].get("poblacion") or 0))
            print(f"--- {com} ({len(v)})")
            for m, locs in v[:12]:
                print(f"     {m['id']}  {m['nombre'][:30]:30s} pob={m.get('poblacion'):>7}  "
                      f"{len(locs):3d} localidades")
            if len(v) > 12:
                print(f"     … y {len(v) - 12} más")
        return 0

    elegidos = resolver(args.municipios or MUNICIPIOS_POR_DEFECTO, lugares, hijos)
    if not elegidos:
        print("Ningún municipio válido. Nada que hacer.")
        return 1

    if args.solo_informe:
        informe(args.salida, elegidos)
        return 0

    total_loc = sum(len(locs) for _, locs in elegidos)
    print(f"{'=' * 78}")
    print(f"  LÍNEA BASE MONOLINGÜE — {len(elegidos)} municipios, {total_loc} localidades")
    print(f"{'=' * 78}")
    for m, locs in elegidos:
        print(f"   {m['nombre']:26s} {m['comunidad'][:20]:20s} {len(locs):2d} loc  {m.get('sitio_web','')}")
    print(f"\n  Estimación: ~{total_loc * 2} min "
          f"(unos 2 minutos por localidad, medido sobre Amurrio).")

    n = escribir_entrada(elegidos, ENTRADA_FILTRADA)
    print(f"  Entrada escrita: {ENTRADA_FILTRADA} ({n} lugares)")

    if args.solo_preparar:
        print("  --solo-preparar: no se ejecuta nada más.")
        return 0

    if args.reiniciar and os.path.exists(args.salida):
        os.remove(args.salida)
        print(f"  --reiniciar: borrada la salida previa.")
    elif os.path.exists(args.salida):
        print(f"  Se reanuda sobre {os.path.basename(args.salida)} "
              f"(usa --reiniciar para empezar de cero).")

    cmd = [sys.executable, os.path.join(_AQUI, "main.py"),
           "--input", ENTRADA_FILTRADA, "--output", args.salida,
           "--anno", str(args.anno), "--parallel", str(args.parallel)]
    if args.sin_rrss:
        cmd.append("--sin-rrss")
    print(f"\n  $ {' '.join(cmd)}\n")

    inicio = datetime.now()
    r = subprocess.run(cmd, cwd=_AQUI)
    dur = (datetime.now() - inicio).total_seconds() / 60
    print(f"\n  main.py terminó con código {r.returncode} en {dur:.0f} min.")

    informe(args.salida, elegidos)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

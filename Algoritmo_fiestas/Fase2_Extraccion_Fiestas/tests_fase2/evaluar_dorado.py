"""
Evaluador del conjunto dorado (Fase 0 del plan de mejora del contexto).

Mide, sin volver a ejecutar el pipeline, las métricas con las que se juzga cada
fase. Lee:

    debug_contexto/{localidad}_discovery_debug.json   (qué llegó al LLM y por qué)
    fiestas_espana.json                               (qué salió al final)
    tests_fase2/conjunto_dorado.json                  (qué debería haber salido)

Métricas
--------
  recall_fuente        % de localidades en que la página CORRECTA está en el contexto.
                       Es la métrica que importa: si la fuente no llega al modelo,
                       ningún prompt puede arreglarlo.
  contaminacion        % de localidades cuyo contexto contiene fuentes prohibidas
                       (PDFs de presupuestos, actas...).
  pct_unico            % del contexto que NO son chunks duplicados.
  docs_distintos       documentos distintos por contexto (1 = monocultivo).
  uso_ventana          % del presupuesto de contexto realmente aprovechado.
  fiestas_ok           % de fiestas esperadas encontradas con fecha dentro de tolerancia.
  programa_ok          % de esas fiestas que además traen programa de actos.

Uso:
    py tests_fase2/evaluar_dorado.py
    py tests_fase2/evaluar_dorado.py --guardar linea_base_fase0.json
    py tests_fase2/evaluar_dorado.py --comparar linea_base_fase0.json
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR_DEBUG = os.path.join(BASE, "debug_contexto")
DORADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conjunto_dorado.json")

_RE_NO_SEGURO = re.compile(r"[^\w\-.]", re.UNICODE)


def _slug(nombre):
    return _RE_NO_SEGURO.sub("_", (nombre or "").strip())[:80]


def _cargar_json(ruta, por_defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return por_defecto


def _debug_de(localidad):
    return _cargar_json(os.path.join(DIR_DEBUG, f"{_slug(localidad)}_discovery_debug.json"))


def _urls_del_contexto(debug):
    """URLs de los chunks realmente seleccionados."""
    return [c.get("url", "") for c in debug.get("chunks", []) if c.get("seleccionado")]


def _fecha(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def evaluar():
    dorado = _cargar_json(DORADO)
    if not dorado:
        print(f"No se pudo leer {DORADO}")
        return None

    salida = _cargar_json(os.path.join(BASE, "fiestas_espana.json"), {}) or {}
    fiestas_por_lugar = {}
    for f in salida.get("fiestas", []):
        fiestas_por_lugar.setdefault(f.get("lugar_id"), []).append(f)

    filas, avisos = [], []
    for loc in dorado.get("localidades", []):
        if loc.get("_plantilla") or not loc.get("localidad"):
            continue

        nombre = loc["localidad"]
        debug = _debug_de(nombre)
        fila = {"localidad": nombre, "tipo": loc.get("tipo", "")}

        if not debug:
            avisos.append(f"sin volcado de debug para '{nombre}' (¿se ejecutó la Fase 2?)")
            fila.update(evaluado=False)
            filas.append(fila)
            continue

        m = debug.get("metricas", {})
        urls = " | ".join(_urls_del_contexto(debug))

        esperadas = loc.get("fuente_esperada") or []
        prohibidas = loc.get("fuente_prohibida") or []
        encontradas = [p for p in esperadas if p and p.lower() in urls.lower()]
        contaminantes = [p for p in prohibidas if p and p.lower() in urls.lower()]

        presup_chars = (m.get("presupuesto") or {}).get("presupuesto_chars") or 0
        fila.update(
            evaluado=True,
            recall_fuente=(len(encontradas) / len(esperadas)) if esperadas else None,
            fuentes_encontradas=encontradas,
            contaminado=bool(contaminantes),
            contaminantes=contaminantes,
            docs_distintos=m.get("documentos_distintos", 0),
            pct_unico=m.get("pct_unico", 0.0),
            tokens_contexto=m.get("tokens_contexto", 0),
            uso_ventana=round(100 * m.get("chars_contexto", 0) / presup_chars, 1) if presup_chars else None,
        )

        # ── Fiestas y programas ──
        obtenidas = fiestas_por_lugar.get(loc.get("lugar_id"), [])
        aciertos, con_programa, esperadas_f = 0, 0, loc.get("fiestas_esperadas") or []
        for exp in esperadas_f:
            patron = (exp.get("nombre_contiene") or "").lower()
            f_exp = _fecha(exp.get("fecha_inicio_aprox"))
            tol = int(exp.get("tolerancia_dias", 3))
            for got in obtenidas:
                if patron and patron not in (got.get("nombre") or "").lower():
                    continue
                f_got = _fecha(got.get("fecha_inicio"))
                if f_exp and f_got and abs((f_got - f_exp).days) > tol:
                    continue
                aciertos += 1
                if got.get("programa"):
                    con_programa += 1
                break

        fila.update(
            fiestas_esperadas=len(esperadas_f),
            fiestas_ok=aciertos,
            programa_ok=con_programa,
            estimadas=sum(1 for g in obtenidas if g.get("es_estimada")),
            reales=sum(1 for g in obtenidas if not g.get("es_estimada")),
        )
        filas.append(fila)

    evaluadas = [f for f in filas if f.get("evaluado")]
    con_recall = [f for f in evaluadas if f.get("recall_fuente") is not None]
    tot_esp = sum(f.get("fiestas_esperadas", 0) for f in evaluadas)

    def media(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    resumen = {
        "localidades_evaluadas": len(evaluadas),
        "recall_fuente_pct": round(100 * sum(f["recall_fuente"] for f in con_recall) / len(con_recall), 1) if con_recall else None,
        "contaminacion_pct": round(100 * sum(1 for f in evaluadas if f.get("contaminado")) / len(evaluadas), 1) if evaluadas else None,
        "pct_unico_medio": media([f.get("pct_unico") for f in evaluadas]),
        "docs_distintos_medio": media([f.get("docs_distintos") for f in evaluadas]),
        "uso_ventana_pct": media([f.get("uso_ventana") for f in evaluadas]),
        "fiestas_ok_pct": round(100 * sum(f.get("fiestas_ok", 0) for f in evaluadas) / tot_esp, 1) if tot_esp else None,
        "programa_ok_pct": round(100 * sum(f.get("programa_ok", 0) for f in evaluadas) / tot_esp, 1) if tot_esp else None,
        "fiestas_reales": sum(f.get("reales", 0) for f in evaluadas),
        "fiestas_estimadas": sum(f.get("estimadas", 0) for f in evaluadas),
    }
    return {"resumen": resumen, "detalle": filas, "avisos": avisos,
            "fecha": date.today().isoformat()}


def imprimir(r):
    print("\n" + "=" * 74)
    print("  CONJUNTO DORADO — evaluación del contexto de discovery")
    print("=" * 74)

    if not r["detalle"]:
        print("  Sin localidades evaluables.")
    print(f"\n  {'Localidad':<16} {'recall':>7} {'docs':>5} {'únic%':>6} {'tok':>6} {'vent%':>6}  contaminado")
    print("  " + "-" * 70)
    for f in r["detalle"]:
        if not f.get("evaluado"):
            print(f"  {f['localidad']:<16} {'—':>7}  (sin volcado de debug)")
            continue
        rec = f.get("recall_fuente")
        print(
            f"  {f['localidad']:<16} "
            f"{(f'{100*rec:.0f}%' if rec is not None else 'n/a'):>7} "
            f"{f.get('docs_distintos', 0):>5} "
            f"{f.get('pct_unico', 0):>6} "
            f"{f.get('tokens_contexto', 0):>6} "
            f"{(f.get('uso_ventana') if f.get('uso_ventana') is not None else '—'):>6}  "
            f"{'SÍ → ' + ', '.join(f['contaminantes']) if f.get('contaminado') else 'no'}"
        )

    print("\n  RESUMEN")
    print("  " + "-" * 70)
    for k, v in r["resumen"].items():
        print(f"  {k:<26} {v}")

    for a in r["avisos"]:
        print(f"  [aviso] {a}")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--guardar", help="Guardar el resultado como línea base (JSON)")
    ap.add_argument("--comparar", help="Comparar contra una línea base guardada")
    args = ap.parse_args()

    r = evaluar()
    if r is None:
        sys.exit(1)
    imprimir(r)

    if args.guardar:
        with open(args.guardar, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"  Línea base guardada en {args.guardar}\n")

    if args.comparar:
        base = _cargar_json(args.comparar)
        if not base:
            print(f"  No se pudo leer la línea base {args.comparar}")
            sys.exit(1)
        print(f"  COMPARACIÓN contra {args.comparar} ({base.get('fecha', '?')})")
        print("  " + "-" * 70)
        for k, v in r["resumen"].items():
            antes = base["resumen"].get(k)
            if isinstance(v, (int, float)) and isinstance(antes, (int, float)):
                d = v - antes
                flecha = "▲" if d > 0 else ("▼" if d < 0 else "=")
                print(f"  {k:<26} {antes}  →  {v}   {flecha} {d:+.1f}")
            else:
                print(f"  {k:<26} {antes}  →  {v}")
        print()

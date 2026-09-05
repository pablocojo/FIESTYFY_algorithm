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
import glob
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# La consola de Windows llega en cp1252 y el informe lleva flechas, comillas
# angulares y nombres con tilde. Sin esto, el evaluador se cae a mitad de tabla
# con UnicodeEncodeError en cuanto una localidad tiene una fiesta que enseñar
# —justamente cuando empieza a ser útil—.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

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


def _debugs_enrichment_de(localidad):
    """
    Todos los volcados de enrichment de una localidad, uno por fiesta.

    El evaluador solo miraba el contexto de DISCOVERY, y ahí no es donde se
    pierde el programa: en Aranda de Duero la página correcta estaba en los dos
    contextos y aun así se perdió el 83 % del PDF en el de enrichment. La
    métrica principal habría dado verde en el caso que peor salió.
    """
    patron = os.path.join(DIR_DEBUG, f"{_slug(localidad)}__*_enrichment_debug.json")
    fuera = []
    for ruta in sorted(glob.glob(patron)):
        d = _cargar_json(ruta)
        if d:
            fuera.append(d)
    return fuera


def _urls_del_contexto(debug):
    """URLs de los chunks realmente seleccionados."""
    return [c.get("url", "") for c in debug.get("chunks", []) if c.get("seleccionado")]


def _actos_de(fiesta):
    return sum(len(d.get("eventos", []) or []) for d in (fiesta.get("programa") or []))


def _descartados_de(metricas):
    """
    Chunks candidatos que no llegaron al modelo.

    Los volcados escritos antes de que existiera el campo se reconstruyen
    restando: así la línea base del reparto se puede calcular sobre las
    ejecuciones que ya están en disco, sin volver a ejecutar la Fase 2.
    """
    if metricas.get("descartados") is not None:
        return metricas["descartados"]
    return max(0, (metricas.get("candidatos") or 0) - (metricas.get("seleccionados") or 0))


def _norm_nombre(s):
    return " ".join((s or "").lower().split())


def _fecha(s):
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def evaluar(salida_json=None):
    dorado = _cargar_json(DORADO)
    if not dorado:
        print(f"No se pudo leer {DORADO}")
        return None

    # La salida no siempre se llama igual: las ejecuciones sobre lugares sueltos
    # escriben en fiestas_neutros.json. Se coge el primero que tenga fiestas para
    # que el evaluador no informe de 0% cuando el fichero por defecto está vacío.
    candidatos = [salida_json] if salida_json else ["fiestas_espana.json", "fiestas_neutros.json"]
    salida = {}
    for nombre in candidatos:
        ruta = nombre if os.path.isabs(nombre) else os.path.join(BASE, nombre)
        datos = _cargar_json(ruta, {}) or {}
        if datos.get("fiestas"):
            salida = datos
            print(f"  (fiestas leídas de {os.path.basename(ruta)})\n")
            break
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

        # Cuánto del lote se llena. Antes se medía contra `presupuesto_chars`,
        # el tope que recortaba; con el reparto ese número ya no existe como
        # límite y compararse con él daba usos del 295%. Ahora se mide en
        # tokens contra el tamaño del lote, que es lo que de verdad acota una
        # llamada. Por debajo del 100% significa que cabía todo en una.
        presup_tok = (m.get("presupuesto") or {}).get("lote_tokens") or 0
        fila.update(
            evaluado=True,
            recall_fuente=(len(encontradas) / len(esperadas)) if esperadas else None,
            fuentes_encontradas=encontradas,
            contaminado=bool(contaminantes),
            contaminantes=contaminantes,
            docs_distintos=m.get("documentos_distintos", 0),
            pct_unico=m.get("pct_unico", 0.0),
            tokens_contexto=m.get("tokens_contexto", 0),
            uso_ventana=round(100 * m.get("tokens_contexto", 0) / presup_tok, 1) if presup_tok else None,
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

        # ── Contexto de ENRICHMENT: donde de verdad se pierde el programa ──
        enr = _debugs_enrichment_de(nombre)
        urls_enr = " | ".join(u for d in enr for u in _urls_del_contexto(d))
        enc_enr = [p for p in esperadas if p and p.lower() in urls_enr.lower()]

        # Cobertura: qué parte de los días que el documento nombra ha llegado a
        # la ficha. La calcula el propio enrichment (`cobertura_dias`), que es
        # quien tiene delante el documento; aquí solo se agrega.
        #
        # NO se mide por actos: `contar_actos_horarios` cuenta horas de reloj
        # distintas, no actos, así que como denominador daría coberturas del
        # 500% en cualquier programa con horas repetidas.
        coberturas = [
            g["cobertura_dias"] for g in obtenidas
            if isinstance(g.get("cobertura_dias"), (int, float))
        ]

        # Chunks candidatos que no llegaron al modelo, en las dos etapas. Es la
        # métrica del reparto: el objetivo es que llegue a 0.
        # Solo del DISCOVERY. En el enrichment, desde que el documento elegido
        # es la fuente, el pool no se envía a propósito: contarlo como descarte
        # convertiría la decisión correcta en una alarma. Lo que se pierde en el
        # enrichment lo miden `cobertura_dias` y `programa_no_recuperado`.
        descartados = _descartados_de(m)
        candidatos_tot = m.get("candidatos") or 0

        fila.update(
            recall_fuente_enrich=(len(enc_enr) / len(esperadas)) if esperadas else None,
            cobertura_dias=round(sum(coberturas) / len(coberturas), 3) if coberturas else None,
            programa_no_recuperado=sum(1 for g in obtenidas if g.get("programa_no_recuperado")),
            # Señales de que el recall ha subido a costa de la precisión.
            n_fiestas=len(obtenidas),
            actos_compartidos=sum(g.get("actos_compartidos_retirados", 0) for g in obtenidas),
            sin_programa_publicado=sum(1 for g in obtenidas if g.get("sin_programa_publicado")),
            chunks_descartados=descartados,
            chunks_candidatos=candidatos_tot,
        )
        filas.append(fila)

    evaluadas = [f for f in filas if f.get("evaluado")]
    con_recall = [f for f in evaluadas if f.get("recall_fuente") is not None]
    tot_esp = sum(f.get("fiestas_esperadas", 0) for f in evaluadas)

    def media(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    con_recall_e = [f for f in evaluadas if f.get("recall_fuente_enrich") is not None]
    cobs = [f["cobertura_dias"] for f in evaluadas if f.get("cobertura_dias") is not None]
    desc_tot = sum(f.get("chunks_descartados", 0) for f in evaluadas)
    cand_tot = sum(f.get("chunks_candidatos", 0) for f in evaluadas)

    resumen = {
        "localidades_evaluadas": len(evaluadas),
        "recall_fuente_pct": round(100 * sum(f["recall_fuente"] for f in con_recall) / len(con_recall), 1) if con_recall else None,
        "recall_fuente_enrich_pct": round(100 * sum(f["recall_fuente_enrich"] for f in con_recall_e) / len(con_recall_e), 1) if con_recall_e else None,
        "cobertura_dias_media": round(sum(cobs) / len(cobs), 3) if cobs else None,
        "chunks_descartados": desc_tot,
        "chunks_descartados_pct": round(100 * desc_tot / cand_tot, 1) if cand_tot else None,
        "programa_no_recuperado": sum(f.get("programa_no_recuperado", 0) for f in evaluadas),
        # Alarmas de precisión: una pedanía que pasa de 1 a 4 fiestas no ha
        # mejorado el recall, ha empezado a copiar de su capital.
        "fiestas_por_localidad_max": max((f.get("n_fiestas", 0) for f in evaluadas), default=0),
        "actos_compartidos_retirados": sum(f.get("actos_compartidos", 0) for f in evaluadas),
        "sin_programa_publicado": sum(f.get("sin_programa_publicado", 0) for f in evaluadas),
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
    print("\n" + "=" * 92)
    print("  CONJUNTO DORADO — contexto de discovery Y de enrichment")
    print("=" * 92)

    if not r["detalle"]:
        print("  Sin localidades evaluables.")
    print(
        f"\n  {'Localidad':<16} {'rec.disc':>9} {'rec.enr':>8} {'cobert':>7} "
        f"{'descart':>9} {'docs':>5} {'únic%':>6}  contaminado"
    )
    print("  " + "-" * 88)
    for f in r["detalle"]:
        if not f.get("evaluado"):
            print(f"  {f['localidad']:<16} {'—':>9}  (sin volcado de debug)")
            continue
        rec = f.get("recall_fuente")
        rec_e = f.get("recall_fuente_enrich")
        cob = f.get("cobertura_dias")
        desc, cand = f.get("chunks_descartados", 0), f.get("chunks_candidatos", 0)
        print(
            f"  {f['localidad']:<16} "
            f"{(f'{100*rec:.0f}%' if rec is not None else 'n/a'):>9} "
            f"{(f'{100*rec_e:.0f}%' if rec_e is not None else 'n/a'):>8} "
            f"{(f'{cob:.2f}' if cob is not None else '—'):>7} "
            f"{(f'{desc}/{cand}' if cand else '—'):>9} "
            f"{f.get('docs_distintos', 0):>5} "
            f"{f.get('pct_unico', 0):>6}  "
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
    ap.add_argument("--salida", help="JSON de fiestas a evaluar (por defecto, fiestas_espana.json y luego fiestas_neutros.json)")
    ap.add_argument("--guardar", help="Guardar el resultado como línea base (JSON)")
    ap.add_argument("--comparar", help="Comparar contra una línea base guardada")
    args = ap.parse_args()

    r = evaluar(args.salida)
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

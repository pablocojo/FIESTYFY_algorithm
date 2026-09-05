# -*- coding: utf-8 -*-
"""
Una consulta suelta al modelo de chat configurado, para probar que responde.

Usa la misma configuración que el pipeline (config.py): el mismo modelo, la
misma clave y el mismo tope de tokens, así que si esto funciona, la Fase 2
también tiene por dónde hablar.

Uso:
    py probar_modelo.py                          # pregunta de ejemplo
    py probar_modelo.py "¿Cuándo es San Roque?"  # tu pregunta
    py probar_modelo.py --json "..."             # pide y valida JSON
    py probar_modelo.py --local "..."            # fuerza LM Studio, sin gastar
    py probar_modelo.py --razonamiento "..."     # muestra también lo que pensó

Imprime la respuesta, los tokens gastados y el coste estimado.
"""

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from config import (
    OPENROUTER_API_KEY, OPENROUTER_CHAT_URL, OPENROUTER_MODELS,
    OPENROUTER_MAX_TOKENS, OPENROUTER_REFERER, OPENROUTER_TITLE,
    LMSTUDIO_CHAT_URL, LMSTUDIO_CHAT_MODEL,
)

# Precio de qwen/qwen3-32b por millón de tokens, consultado a la API el
# 2026-09-02. Solo sirve para que la prueba diga lo que ha costado.
PRECIO_ENTRADA = 0.08
PRECIO_SALIDA = 0.28

PREGUNTA_EJEMPLO = (
    "¿Cuándo se celebran las Fiestas de San Roque de Tobarra (Albacete) "
    "y qué es la Tamborada? Responde en dos frases."
)

SISTEMA_JSON = "Devuelve SOLO JSON estricto, sin texto alrededor ni ```."
PREGUNTA_JSON = (
    'Del texto siguiente saca las fiestas. Formato: '
    '{"fiestas":[{"nombre":"...","fecha_inicio":"YYYY-MM-DD","fecha_fin":"YYYY-MM-DD"}]}\n\n'
    "TEXTO: Las Fiestas de San Roque de Tobarra se celebran del 14 al 21 de "
    "agosto de 2026. En mayo son las patronales del Cristo de la Antigua, "
    "del 8 al 23."
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta", nargs="?", help="Qué preguntarle al modelo")
    ap.add_argument("--json", action="store_true",
                    help="Pide JSON y comprueba que se puede parsear")
    ap.add_argument("--local", action="store_true",
                    help="Usa LM Studio en vez de OpenRouter (no cuesta dinero)")
    ap.add_argument("--razonamiento", action="store_true",
                    help="Muestra también el razonamiento del modelo")
    ap.add_argument("--max-tokens", type=int, default=None)
    args = ap.parse_args()

    if args.local:
        url, modelo, cabeceras, remoto = LMSTUDIO_CHAT_URL, LMSTUDIO_CHAT_MODEL, {}, False
    else:
        if not OPENROUTER_API_KEY:
            sys.exit("No hay clave de OpenRouter. Ponla en openrouter_key.txt "
                     "o en la variable OPENROUTER_API_KEY, o usa --local.")
        url, modelo, remoto = OPENROUTER_CHAT_URL, OPENROUTER_MODELS[0], True
        cabeceras = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
        }

    if args.json:
        sistema, pregunta = SISTEMA_JSON, (args.pregunta or PREGUNTA_JSON)
    else:
        sistema = "Eres un asistente conciso. Responde en español."
        pregunta = args.pregunta or PREGUNTA_EJEMPLO

    cuerpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": pregunta}],
        "max_tokens": args.max_tokens or OPENROUTER_MAX_TOKENS,
        "temperature": 0.1,
    }

    print(f"modelo   : {modelo}  ({'OpenRouter' if remoto else 'LM Studio'})")
    print(f"pregunta : {pregunta[:120]}{'…' if len(pregunta) > 120 else ''}")
    print("-" * 72)

    peticion = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", **cabeceras})

    t0 = time.time()
    try:
        with urllib.request.urlopen(peticion, timeout=300) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
    except Exception as e:
        sys.exit(f"{type(e).__name__}: {e}")
    tardanza = time.time() - t0

    # OpenRouter puede devolver 200 con el error dentro del cuerpo.
    if isinstance(datos, dict) and datos.get("error"):
        sys.exit(f"Error del proveedor: {datos['error']}")

    eleccion = (datos.get("choices") or [{}])[0]
    mensaje = eleccion.get("message") or {}
    contenido = (mensaje.get("content") or "").strip()
    razonado = (mensaje.get("reasoning") or "").strip()

    if args.razonamiento and razonado:
        print("RAZONAMIENTO:")
        print(razonado[:2000])
        print("-" * 72)

    print("RESPUESTA:")
    print(contenido or "(vacía)")

    if args.json:
        print("-" * 72)
        try:
            crudo = contenido[contenido.index("{"):contenido.rindex("}") + 1]
            print("JSON válido:", json.dumps(json.loads(crudo), ensure_ascii=False))
        except Exception as e:
            print(f"JSON NO válido: {e}")

    uso = datos.get("usage") or {}
    entrada = uso.get("prompt_tokens") or 0
    salida = uso.get("completion_tokens") or 0
    print("-" * 72)
    print(f"tiempo   : {tardanza:.1f}s   finish_reason={eleccion.get('finish_reason')}")
    print(f"tokens   : entrada={entrada}  salida={salida}"
          + (f"  (de los cuales {len(razonado)} chars fueron razonamiento)" if razonado else ""))
    if remoto and (entrada or salida):
        coste = entrada / 1e6 * PRECIO_ENTRADA + salida / 1e6 * PRECIO_SALIDA
        print(f"coste    : ${coste:.6f}  (~{1 / coste:,.0f} consultas por dólar)"
              if coste else "coste    : $0")


if __name__ == "__main__":
    main()

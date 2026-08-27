"""
Recorre `enrich_festival_program` de verdad, sin red.

Existe por lo del 2026-08-26. Un cambio dejó `hay_programa` usado en una función
y definido en otra: la suite pasó con 542 tests en verde y la ejecución real
murió en las DOCE localidades con `name 'hay_programa' is not defined`, después
de 34 minutos. Ningún test recorría esta función, así que un NameError en ella
era invisible.

No comprueba calidad de extracción; comprueba que la ruta se puede recorrer.
"""

import ast
import asyncio

import pytest

import llm_processor.text_analyzer as ta


PROGRAMA = "\n".join([
    "12:00 Cohete de inicio de fiestas en la plaza.",
    "14:30 Comida popular en el centro social.",
    "20:00 Verbena con la orquesta del pueblo.",
    "23:00 Castillo de fuegos artificiales.",
])
PROSA = ("La localidad celebra sus fiestas cada verano con mucha participacion "
         "vecinal, actos religiosos y musica para todos los publicos.")


def _chunks(texto, url="https://ejemplo.es/programa"):
    return [{
        "chunk": texto, "chunk_contextualizado": texto, "fuente": "web_municipio",
        "url": url, "es_calendario": False, "prioridad": 2, "score_spider": 0,
        "rank_spider": None, "embedding": None, "doc_relevancia": "DIRECTA",
        "indice_chunk": 0, "score": 0.9,
    }]


FIESTA = {"nombre": "Fiestas de San Roque", "fecha_inicio": "2026-08-14",
          "fecha_fin": "2026-08-16", "programa": []}
MUNICIPIO = {"nombre": "Tobarra", "provincia": "Albacete"}
LOCALIDAD = {"nombre": "Cordovilla", "id": "02074000201"}


def _enriquecer(monkeypatch, texto, respuesta=None):
    llamadas = []

    async def falso_llm(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        llamadas.append(etiqueta)
        return respuesta or {"programa": []}

    monkeypatch.setattr(ta, "llm_chat_json", falso_llm)
    monkeypatch.setattr(ta, "process_translation_pipeline", lambda t, m: t)
    salida = asyncio.run(ta.enrich_festival_program(
        MUNICIPIO, LOCALIDAD, dict(FIESTA), _chunks(texto), 2026,
        nombres_hermanas=["Aljubé", "Sierra"],
    ))
    return salida, llamadas


def _de_enrichment(llamadas):
    """
    Solo las llamadas que PIDEN ACTOS.

    Las del localizador son otra cosa: preguntan en qué página está el programa,
    y tienen que poder hacerse justamente cuando el recuento de horas no ve nada
    —un índice o un PDF mal parseado— porque para eso existen. Lo que no puede
    pasar es que se pidan actos sin material, que es lo que produce programas
    inventados.
    """
    return [e for e in llamadas if not e.startswith("LOCATOR")]


def test_con_programa_se_llama_al_modelo(monkeypatch):
    """La ruta entera, de principio a fin. Esto es lo que no cubría ningún test."""
    salida, llamadas = _enriquecer(monkeypatch, PROGRAMA)
    assert _de_enrichment(llamadas), "no se llegó a preguntar al modelo"
    assert not salida.get("sin_programa_publicado")


def test_sin_programa_no_se_piden_actos(monkeypatch):
    """El umbral corta, y corta DESPUÉS de volcar el contexto para poder auditarlo."""
    salida, llamadas = _enriquecer(monkeypatch, PROSA)
    assert _de_enrichment(llamadas) == [], "se pidieron actos sin material"
    assert salida.get("sin_programa_publicado") is True
    assert salida.get("programa") == []


def test_ninguna_funcion_usa_un_nombre_que_no_define():
    """
    El fallo concreto del 2026-08-26: `hay_programa` definido en una función y
    usado en otra. Se comprueba en el árbol sintáctico, sin ejecutar nada.
    """
    arbol = ast.parse(open(ta.__file__, encoding="utf-8").read())
    globales = {n.id for n in ast.walk(arbol)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    globales |= {n.name for n in ast.walk(arbol)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    globales |= {a.asname or a.name.split(".")[0]
                 for n in ast.walk(arbol) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in n.names}
    import builtins
    conocidos = globales | set(dir(builtins))

    huerfanos = []
    for fn in ast.walk(arbol):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        locales = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        if fn.args.vararg:
            locales.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            locales.add(fn.args.kwarg.arg)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                locales.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # La función anidada y TAMBIÉN sus parámetros: el recorrido entra
                # en su cuerpo, así que sus argumentos se verían como usados sin
                # definir desde el punto de vista de la función de fuera.
                locales.add(n.name)
                locales |= {a.arg for a in n.args.args + n.args.kwonlyargs}
                if n.args.vararg:
                    locales.add(n.args.vararg.arg)
                if n.args.kwarg:
                    locales.add(n.args.kwarg.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                locales.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                locales |= {a.asname or a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.comprehension):
                for t in ast.walk(n.target):
                    if isinstance(t, ast.Name):
                        locales.add(t.id)
            elif isinstance(n, ast.Lambda):
                # Los parámetros de una lambda son suyos, no de la función que la
                # contiene; sin esto salían como «usados sin definir».
                locales |= {a.arg for a in n.args.args + n.args.kwonlyargs}
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                for t in ast.walk(n.optional_vars):
                    if isinstance(t, ast.Name):
                        locales.add(t.id)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in locales and n.id not in conocidos:
                    huerfanos.append(f"{fn.name}:{n.lineno} usa '{n.id}'")
    assert not huerfanos, "nombres usados sin definir: " + "; ".join(huerfanos[:8])

"""
Que `informacion_suficiente: false` signifique algo.

En la ejecución del 2026-09-03, 4 de las 8 rondas del localizador devolvieron
`suficiente=False` y en las 4 el pipeline siguió adelante sin hacer nada: dos
porque el modelo no propuso ninguna URL —no había ninguna en el contexto que
seguir— y dos porque las que propuso ya estaban descargadas. La Aguilera y
Jornadas de Agua salieron sin programa después de que el modelo dijera
explícitamente que le faltaba información.

Ahora el modelo puede pedir además CONSULTAS de buscador, y el bucle solo para
cuando dice que le basta o cuando una ronda no trae ningún documento nuevo.
"""

import asyncio

import pytest

import llm_processor.text_analyzer as ta


CONTEXTO = (
    "--- [https://agregador.example/aranda] | Relevancia: DIRECTA ---\n"
    "Fiestas patronales de La Aguilera. Descripcion generica sin horarios.\n"
    "El programa completo se publica en la revista comarcal.\n"
)
FIESTA = {"nombre": "Fiestas de San Pedro Regalado", "fecha_inicio": "2026-05-12",
          "fecha_fin": "2026-05-17"}
MUNICIPIO = {"nombre": "Aranda de Duero", "provincia": "Burgos",
             "comunidad_autonoma": "Castilla y León"}
LOCALIDAD = {"nombre": "La Aguilera", "id": "09018000301"}

DOC_BUENO = {
    "fuente": "busqueda_web",
    "url": "https://revistacomarcal.example/programa-la-aguilera-2026",
    "texto": ("Programa de fiestas de La Aguilera 2026.\n"
              "12 de mayo. 12:00 Pasacalles. 20:00 Verbena en La Aguilera.\n"),
    "tipo": "pagina",
}


def _correr(monkeypatch, respuestas, docs_por_consulta=None, docs_por_url=None):
    """Ejecuta el localizador con un modelo guionizado y la red simulada."""
    consultas_lanzadas, urls_descargadas = [], []

    async def falso_llm(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        return respuestas.pop(0) if respuestas else {
            "paginas_elegidas": [], "informacion_suficiente": True,
            "urls_a_seguir": [], "consultas_sugeridas": [],
        }

    async def falso_buscar(queries, localidad, municipio, visited=None):
        consultas_lanzadas.extend(queries)
        return list(docs_por_consulta or [])

    async def falsa_descarga(urls, fuente="busqueda_web", timeout=15):
        urls_descargadas.extend(urls)
        return list(docs_por_url or [])

    import scraper.google_search as gs
    monkeypatch.setattr(ta, "llm_chat_json", falso_llm)
    monkeypatch.setattr(gs, "_buscar_y_descargar", falso_buscar)
    monkeypatch.setattr(gs, "descargar_urls_bajo_demanda", falsa_descarga)
    # Los filtros de procedencia se prueban aparte; aquí estorban.
    monkeypatch.setattr(ta, "documento_es_ajeno_al_municipio",
                        lambda *a, **k: False)

    async def sin_homonimos(docs, *a, **k):
        return docs
    monkeypatch.setattr(ta, "descartar_homonimos", sin_homonimos)

    indexed = []
    urls, docs = asyncio.run(ta.localizar_programa_con_llm(
        CONTEXTO, dict(FIESTA), LOCALIDAD, MUNICIPIO, 2026, indexed,
        nombres_hermanas=[], provincia="Burgos", idiomas=["es"],
    ))
    return urls, docs, consultas_lanzadas, urls_descargadas, indexed


# ── El caso de La Aguilera ───────────────────────────────────────────────────

def test_suficiente_false_sin_urls_ahora_lanza_las_consultas(monkeypatch):
    """
    Antes: `suficiente=False` + 0 URLs → break, ficha sin programa.
    Ahora: se lanzan las consultas que el propio modelo redacta.
    """
    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [],
         "consultas_sugeridas": ["programa fiestas La Aguilera 2026"],
         "razon": "solo hay una descripcion generica"},
        {"paginas_elegidas": [DOC_BUENO["url"]], "informacion_suficiente": True,
         "urls_a_seguir": [], "consultas_sugeridas": []},
    ]
    urls, docs, consultas, _u, indexed = _correr(
        monkeypatch, respuestas, docs_por_consulta=[DOC_BUENO])

    assert consultas == ["programa fiestas La Aguilera 2026"]
    assert DOC_BUENO["url"] in urls, "no se eligió la página que trajo la búsqueda"
    assert docs and docs[0]["url"] == DOC_BUENO["url"]
    assert any(c["url"] == DOC_BUENO["url"] for c in indexed), \
        "el documento nuevo no se indexó para que el enrichment lo lea entero"


def test_para_cuando_una_ronda_no_trae_nada(monkeypatch):
    """El criterio de parada real no es el número de rondas: es no avanzar."""
    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [], "consultas_sugeridas": ["consulta que no da nada"]},
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [], "consultas_sugeridas": ["otra que tampoco"]},
    ]
    _urls, docs, consultas, _u, _i = _correr(monkeypatch, respuestas, docs_por_consulta=[])
    assert docs == []
    assert len(consultas) == 1, "siguió pidiendo búsquedas tras una ronda estéril"


def test_para_en_cuanto_dice_que_le_basta(monkeypatch):
    respuestas = [
        {"paginas_elegidas": ["https://agregador.example/aranda"],
         "informacion_suficiente": True, "urls_a_seguir": [],
         "consultas_sugeridas": ["esta no deberia lanzarse"]},
    ]
    _urls, _docs, consultas, _u, _i = _correr(monkeypatch, respuestas,
                                              docs_por_consulta=[DOC_BUENO])
    assert consultas == [], "se buscó pese a que el modelo dijo que le bastaba"


def test_no_repite_la_misma_consulta(monkeypatch):
    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [], "consultas_sugeridas": ["programa La Aguilera"]},
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [], "consultas_sugeridas": ["Programa   La  Aguilera"]},
    ]
    _urls, _docs, consultas, _u, _i = _correr(monkeypatch, respuestas,
                                              docs_por_consulta=[DOC_BUENO])
    assert len(consultas) == 1, f"consultas repetidas: {consultas}"


def test_respeta_el_tope_de_consultas_por_ronda(monkeypatch):
    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False, "urls_a_seguir": [],
         "consultas_sugeridas": [f"consulta numero {n}" for n in range(10)]},
        {"paginas_elegidas": [], "informacion_suficiente": True,
         "urls_a_seguir": [], "consultas_sugeridas": []},
    ]
    _urls, _docs, consultas, _u, _i = _correr(monkeypatch, respuestas,
                                              docs_por_consulta=[DOC_BUENO])
    assert len(consultas) <= ta.LOCATOR_MAX_CONSULTAS_POR_RONDA


def test_urls_y_consultas_se_pueden_pedir_a_la_vez(monkeypatch):
    otro = dict(DOC_BUENO, url="https://emisora.example/programa")
    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": ["https://emisora.example/programa"],
         "consultas_sugeridas": ["programa La Aguilera 2026"]},
        {"paginas_elegidas": [otro["url"]], "informacion_suficiente": True,
         "urls_a_seguir": [], "consultas_sugeridas": []},
    ]
    _urls, docs, consultas, urls_desc, _i = _correr(
        monkeypatch, respuestas, docs_por_consulta=[DOC_BUENO], docs_por_url=[otro])
    assert consultas, "no se lanzó la consulta"
    assert urls_desc == ["https://emisora.example/programa"]
    assert {d["url"] for d in docs} == {DOC_BUENO["url"], otro["url"]}


# ── Lo innegociable ──────────────────────────────────────────────────────────

def test_lo_que_entra_por_la_busqueda_pasa_por_el_filtro_de_homonimos(monkeypatch):
    """
    Una consulta escrita por el modelo con el nombre de una advocación atrae el
    programa del pueblo homónimo que celebra esa misma fiesta.
    """
    vistos = {}

    async def homonimos_espia(docs, loc, mun, prov, hermanas, idiomas):
        vistos["llamado"] = True
        vistos["localidad"] = loc
        return []          # todo lo que llegó era de otro pueblo

    respuestas = [
        {"paginas_elegidas": [], "informacion_suficiente": False,
         "urls_a_seguir": [], "consultas_sugeridas": ["San Pedro Regalado programa"]},
    ]

    async def falso_llm(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        return respuestas.pop(0) if respuestas else {"informacion_suficiente": True}

    async def falso_buscar(queries, localidad, municipio, visited=None):
        return [dict(DOC_BUENO, url="https://otra-aguilera.example/programa")]

    import scraper.google_search as gs
    monkeypatch.setattr(ta, "llm_chat_json", falso_llm)
    monkeypatch.setattr(gs, "_buscar_y_descargar", falso_buscar)
    monkeypatch.setattr(ta, "documento_es_ajeno_al_municipio", lambda *a, **k: False)
    monkeypatch.setattr(ta, "descartar_homonimos", homonimos_espia)

    indexed = []
    _urls, docs = asyncio.run(ta.localizar_programa_con_llm(
        CONTEXTO, dict(FIESTA), LOCALIDAD, MUNICIPIO, 2026, indexed,
        nombres_hermanas=[], provincia="Burgos", idiomas=["es"],
    ))
    assert vistos.get("llamado"), "el filtro de homónimos no llegó a ejecutarse"
    assert vistos["localidad"] == "La Aguilera"
    assert docs == []
    assert indexed == [], "se indexó un documento que el filtro había descartado"

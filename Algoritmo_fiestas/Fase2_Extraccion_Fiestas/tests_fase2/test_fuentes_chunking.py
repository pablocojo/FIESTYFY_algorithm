"""Tests de la Etapa A: fuentes, chunking por documentos, cuotas RAG y validación de fuentes."""

from fuentes import (
    crear_documento,
    detectar_es_calendario,
    es_fuente_oficial,
    fuente_base,
    prioridad_fuente,
    rotulo_fuente,
    FUENTE_WEB_LOCALIDAD,
    FUENTE_WEB_MUNICIPIO,
    FUENTE_BUSQUEDA,
)
from llm_processor.text_analyzer import (
    chunk_documento,
    seleccionar_chunks,
    ensamblar_contexto,
    _validar_fuentes_fiesta,
)


# ──────────────────────────────────────────────
# fuentes.py
# ──────────────────────────────────────────────

def test_prioridades_y_oficialidad():
    assert prioridad_fuente("web_localidad") == 1
    assert prioridad_fuente("rrss_localidad:instagram") == 3
    assert prioridad_fuente("prensa_regional") == 5
    assert prioridad_fuente("busqueda_web") == 6
    assert es_fuente_oficial("web_municipio")
    assert es_fuente_oficial("rrss_municipio:facebook")
    assert not es_fuente_oficial("prensa_regional")
    assert not es_fuente_oficial("busqueda_web")
    assert not es_fuente_oficial("fuente_inventada")
    assert fuente_base("rrss_localidad:twitter") == "rrss_localidad"


def test_rotulo_incluye_red_social():
    assert "INSTAGRAM" in rotulo_fuente("rrss_localidad:instagram")
    assert "CALENDARIO" in rotulo_fuente("web_municipio", es_calendario=True)


def test_detectar_calendario():
    assert detectar_es_calendario("https://ayto.es/calendario-laboral-2026", "")
    assert detectar_es_calendario("", "Calendario escolar del curso 2025-2026. Días no lectivos...")
    assert not detectar_es_calendario("https://ayto.es/fiestas-2026", "Programa de fiestas patronales")


def test_crear_documento_autodetecta_calendario():
    doc = crear_documento(FUENTE_WEB_MUNICIPIO, "https://ayto.es/calendario-laboral", "1 de enero...")
    assert doc["es_calendario"] is True
    doc2 = crear_documento(FUENTE_WEB_MUNICIPIO, "https://ayto.es/fiestas", "Programa de actos")
    assert doc2["es_calendario"] is False


# ──────────────────────────────────────────────
# Chunking por documentos
# ──────────────────────────────────────────────

def test_programa_no_se_parte():
    # Programa largo con horarios (supera con creces el chunk_size de 1200)
    lineas = ["PROGRAMA DE FIESTAS DE SAN ROQUE 2026"]
    for dia in range(10, 20):
        lineas.append(f"Día {dia} de agosto")
        for hora, acto in [("12:00", "Pasacalles con charanga por el pueblo"),
                           ("18:30", "Juegos infantiles en la plaza mayor"),
                           ("20:00", "Toro de fuego para todos los vecinos"),
                           ("23:30", "Verbena con orquesta hasta la madrugada")]:
            lineas.append(f"{hora} {acto}")
    texto = "\n".join(lineas)
    assert len(texto) > 1200

    chunks = chunk_documento(texto, chunk_size=1200)
    assert len(chunks) == 1, f"El programa se partió en {len(chunks)} chunks"


def test_texto_normal_se_trocea_por_frases():
    texto = " ".join(f"Esta es la frase número {i} de un texto largo sobre la historia del municipio." for i in range(60))
    chunks = chunk_documento(texto, chunk_size=1200)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 1300  # margen: nunca cortes salvajes muy por encima
        # ningún chunk termina a mitad de palabra
        assert c.endswith(".") or c.endswith("municipio.")


def test_unidad_gigante_se_trocea_con_limite_duro():
    texto = "palabra " * 3000  # 24000 chars sin puntuación ni saltos
    chunks = chunk_documento(texto.strip(), chunk_size=1200)
    assert all(len(c) <= 8000 for c in chunks)


# ──────────────────────────────────────────────
# Selección por cuotas
# ──────────────────────────────────────────────

def _item(fuente, score, contenido="x" * 100):
    return {
        "chunk": contenido,
        "fuente": fuente,
        "url": "",
        "es_calendario": False,
        "prioridad": prioridad_fuente(fuente),
        "score": score,
    }


def test_oficial_nunca_expulsado_por_busqueda():
    # Presupuesto para 3 chunks de 100 chars; la búsqueda tiene MEJOR score
    items = [
        _item(FUENTE_WEB_MUNICIPIO, 0.40),
        _item(FUENTE_WEB_MUNICIPIO, 0.45),
        _item(FUENTE_WEB_LOCALIDAD, 0.50),
        _item(FUENTE_BUSQUEDA, 0.99),
        _item(FUENTE_BUSQUEDA, 0.98),
        _item(FUENTE_BUSQUEDA, 0.97),
    ]
    seleccion = seleccionar_chunks(items, budget_chars=300, umbral=0.35)
    fuentes = [i["fuente"] for i in seleccion]
    assert fuentes.count(FUENTE_BUSQUEDA) == 0
    assert len(seleccion) == 3


def test_busqueda_rellena_presupuesto_restante():
    items = [
        _item(FUENTE_WEB_MUNICIPIO, 0.50),
        _item(FUENTE_BUSQUEDA, 0.90),
        _item(FUENTE_BUSQUEDA, 0.20),  # bajo umbral → fuera
    ]
    seleccion = seleccionar_chunks(items, budget_chars=1000, umbral=0.35)
    fuentes = [i["fuente"] for i in seleccion]
    assert FUENTE_WEB_MUNICIPIO in fuentes
    assert fuentes.count(FUENTE_BUSQUEDA) == 1


def test_red_de_seguridad_oficiales_bajo_umbral():
    # Ningún oficial pasa el umbral → aún así entran los mejores N
    items = [_item(FUENTE_WEB_MUNICIPIO, 0.10) for _ in range(8)]
    seleccion = seleccionar_chunks(items, budget_chars=10000, umbral=0.35, min_oficiales=5)
    assert len(seleccion) == 5


def test_ensamblar_contexto_ordena_y_rotula():
    items = [
        _item(FUENTE_BUSQUEDA, 0.9, "texto de buscador"),
        _item(FUENTE_WEB_LOCALIDAD, 0.5, "texto oficial localidad"),
    ]
    contexto = ensamblar_contexto(items)
    pos_loc = contexto.index("WEB OFICIAL DE LA LOCALIDAD")
    pos_bus = contexto.index("RESULTADOS DE BUSCADOR")
    assert pos_loc < pos_bus
    assert "texto oficial localidad" in contexto


# ──────────────────────────────────────────────
# Validación de fuentes declaradas por el LLM
# ──────────────────────────────────────────────

def test_solo_busqueda_fuerza_confianza_baja():
    f = {"fuentes": ["busqueda_web"], "confianza": "alta"}
    _validar_fuentes_fiesta(f, "Test", {"web_municipio", "busqueda_web"})
    assert f["solo_fuentes_no_oficiales"] is True
    assert f["confianza"] == "baja"


def test_fuente_oficial_declarada_valida():
    f = {"fuentes": ["web_municipio", "busqueda_web"], "confianza": "alta"}
    _validar_fuentes_fiesta(f, "Test", {"web_municipio", "busqueda_web"})
    assert f["solo_fuentes_no_oficiales"] is False
    assert f["confianza"] == "alta"


def test_fuente_inventada_se_elimina():
    # El LLM declara web_localidad pero el contexto solo tenía buscador
    f = {"fuentes": ["web_localidad", "busqueda_web"], "confianza": "alta"}
    _validar_fuentes_fiesta(f, "Test", {"busqueda_web"})
    assert f["fuentes"] == ["busqueda_web"]
    assert f["solo_fuentes_no_oficiales"] is True
    assert f["confianza"] == "baja"


def test_sin_declaracion_con_contexto_oficial_puro():
    f = {"fuentes": [], "confianza": "media"}
    _validar_fuentes_fiesta(f, "Test", {"web_municipio", "rrss_localidad:facebook"})
    assert f["solo_fuentes_no_oficiales"] is False
    assert f["confianza"] == "media"


def test_sin_declaracion_con_contexto_mixto_es_conservador():
    f = {"fuentes": None, "confianza": "alta"}
    _validar_fuentes_fiesta(f, "Test", {"web_municipio", "busqueda_web"})
    assert f["solo_fuentes_no_oficiales"] is True
    assert f["confianza"] == "baja"


def test_sufijo_de_red_tolerado():
    # El modelo declara la red sin sufijo exacto presente en contexto
    f = {"fuentes": ["rrss_localidad:instagram"], "confianza": "alta"}
    _validar_fuentes_fiesta(f, "Test", {"rrss_localidad:facebook"})
    # la base rrss_localidad estaba presente → se acepta como oficial
    assert f["solo_fuentes_no_oficiales"] is False

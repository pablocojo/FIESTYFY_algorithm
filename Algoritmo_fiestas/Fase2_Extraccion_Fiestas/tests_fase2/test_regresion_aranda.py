"""
La cadena de Aranda de Duero, reproducida.

Ejecución del 2026-09-03, «Fiestas Patronales en Honor de la Virgen de las
Viñas», del 11 al 20 de septiembre:

  1. El PDF oficial del programa se descargó entero: 82 fragmentos indexados.
  2. El localizador lo identificó bien ("PDF oficial, título PROGRAMA 2026").
  3. `ENRICHMENT_MAX_CHARS = 32000` dejó entrar 14 de los 82.
  4. La guarda de «días no mencionados» leyó ese contexto mutilado y descartó
     5 de los 7 lotes de días.
  5. La ficha salió con 4 días, 26 actos y `confianza: alta`.

Cada paso, por separado, hacía lo correcto. Este test fija que la composición
deje de perder el documento: si alguien vuelve a meter un recorte por
presupuesto entre el paso 2 y el 4, aquí se ve.
"""

import asyncio
import re

import pytest

import llm_processor.text_analyzer as ta


URL_PDF = "https://www.arandadeduero.es/wp-content/uploads/2026/09/PROGRAMA-2026.pdf"
URL_RUIDO = "https://agregador-seo.example/fiestas-de-espana"

DIAS = [f"2026-09-{d:02d}" for d in range(11, 21)]   # 10 días
FRAGMENTOS_POR_DIA = 8                                # 80 fragmentos + 2 de portada


# Tamaño de fragmento igual al real: el PDF de Aranda son ~98.000 caracteres en
# 82 trozos. Importa que sea así de grande, porque lo que se está probando es
# justo que ya no haya un tope de 32.000 caracteres. Con fragmentos pequeños el
# documento cabría en el presupuesto viejo y el test no probaría nada.
CHARS_POR_FRAGMENTO = 1200


def _fragmentos_del_pdf():
    """
    82 fragmentos, como el PDF real: una portada y ocho por cada uno de los 10
    días. Cada fragmento nombra SU día y lleva actos con hora, así que el texto
    de los días finales solo existe en los fragmentos finales — que son los que
    el recorte por presupuesto tiraba.
    """
    def _rellenar(texto):
        falta = CHARS_POR_FRAGMENTO - len(texto)
        return texto + ("\nInformacion util para los visitantes de las fiestas. "
                        * (falta // 52 + 1))[:max(0, falta)]

    trozos = [
        _rellenar("PROGRAMA DE FIESTAS 2026 - Virgen de las Vinas - Aranda de Duero"),
        _rellenar("Saluda del alcalde. Un ano mas Aranda se viste de fiesta."),
    ]
    for dia in DIAS:
        for k in range(FRAGMENTOS_POR_DIA):
            hora = 9 + k
            trozos.append(_rellenar(
                f"{dia} DIA {dia[-2:]} DE SEPTIEMBRE\n"
                f"{hora:02d}:00 Acto numero {k + 1} del dia {dia[-2:]} en la plaza mayor."
            ))
    return trozos


def _chunk(url, indice, texto, score, fuente="web_municipio", prioridad=2):
    return {
        "chunk": texto, "chunk_contextualizado": texto, "fuente": fuente,
        "url": url, "es_calendario": False, "prioridad": prioridad,
        "score_spider": 100, "rank_spider": 1, "embedding": None,
        "doc_relevancia": "DIRECTA", "indice_chunk": indice, "score": score,
    }


def _indexed_chunks():
    pdf = [_chunk(URL_PDF, n, t, 0.80) for n, t in enumerate(_fragmentos_del_pdf())]
    # Ruido que puntúa MÁS que el programa: es lo que ganaba el presupuesto.
    ruido = [
        _chunk(URL_RUIDO, n,
               f"Fiestas de pueblos de Espana, resumen {n}. " + "relleno " * 60,
               0.95, fuente="busqueda_web", prioridad=6)
        for n in range(40)
    ]
    return pdf + ruido


FIESTA = {
    "nombre": "Fiestas Patronales en Honor de la Virgen de las Vinas",
    "fecha_inicio": "2026-09-11", "fecha_fin": "2026-09-20",
    "confianza": "alta", "programa": [],
}
MUNICIPIO = {"nombre": "Aranda de Duero", "provincia": "Burgos"}
LOCALIDAD = {"nombre": "Aranda de Duero", "id": "09018000101"}

_RE_DIAS_PEDIDOS = re.compile(r"DÍAS PEDIDOS: (\d{4}-\d{2}-\d{2}) a (\d{4}-\d{2}-\d{2})")


def _ejecutar(monkeypatch):
    """Recorre el enrichment de verdad con un modelo fiel: solo copia lo que ve."""
    peticiones = []

    async def falso_llm(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        peticiones.append((etiqueta, user_prompt))
        if etiqueta.startswith("LOCATOR"):
            return {"paginas_elegidas": [URL_PDF], "informacion_suficiente": True,
                    "razon": "PDF oficial con el programa de 2026"}
        m = _RE_DIAS_PEDIDOS.search(user_prompt)
        if not m:
            return {"programa": []}
        desde, hasta = m.group(1), m.group(2)
        # Un modelo honrado: devuelve los actos que EL TEXTO trae para esos días.
        programa = []
        for dia in DIAS:
            if not (desde <= dia <= hasta):
                continue
            eventos = [
                {"hora": f"{9 + k:02d}:00",
                 "descripcion": f"Acto numero {k + 1} del dia {dia[-2:]}"}
                for k in range(FRAGMENTOS_POR_DIA)
                if f"{dia} DIA" in user_prompt
            ]
            if eventos:
                programa.append({"dia": DIAS.index(dia) + 1, "fecha": dia,
                                 "eventos": eventos})
        return {"programa": programa}

    monkeypatch.setattr(ta, "llm_chat_json", falso_llm)
    monkeypatch.setattr(ta, "process_translation_pipeline", lambda t, m: t)

    salida = asyncio.run(ta.enrich_festival_program(
        MUNICIPIO, LOCALIDAD, dict(FIESTA), _indexed_chunks(), 2026,
        nombres_hermanas=None,
    ))
    return salida, peticiones


def _de_enrichment(peticiones):
    return [p for p in peticiones if p[0].startswith("ENRICHMENT")]


# ── Lo que se rompió y no puede volver a romperse ────────────────────────────

def test_el_documento_de_prueba_no_cabria_en_el_presupuesto_viejo():
    """
    Guarda del propio test. Si alguien encoge los fragmentos, el PDF de prueba
    cabría en los 32.000 caracteres de antes y los demás tests de este fichero
    pasarían con el recorte puesto: dejarían de probar nada sin avisar.
    """
    chars = sum(len(t) for t in _fragmentos_del_pdf())
    assert chars > ta.ENRICHMENT_MAX_CHARS * 2, (
        f"el documento de prueba son {chars} chars; hace falta que supere de "
        f"sobra los {ta.ENRICHMENT_MAX_CHARS} del presupuesto que se retiró"
    )

def test_el_documento_del_programa_llega_entero(monkeypatch):
    """Los 82 fragmentos, no 14. El recorte por presupuesto era el paso 3."""
    _salida, peticiones = _ejecutar(monkeypatch)
    enr = _de_enrichment(peticiones)
    assert enr, "no se llegó a pedir ningún acto"
    todo = "\n".join(p[1] for p in enr)
    faltan = [d for d in DIAS if f"{d} DIA" not in todo]
    assert not faltan, f"días del PDF que nunca se le enseñaron al modelo: {faltan}"


def test_se_preguntan_todos_los_lotes_de_dias(monkeypatch):
    """
    En la ejecución real se preguntaron 2 de 7 lotes. La guarda de «días no
    mencionados» leía el contexto recortado, así que descartaba justo los días
    cuyos fragmentos el presupuesto había tirado.
    """
    _salida, peticiones = _ejecutar(monkeypatch)
    pedidos = set()
    for _etiqueta, prompt in _de_enrichment(peticiones):
        m = _RE_DIAS_PEDIDOS.search(prompt)
        if m:
            pedidos.update(d for d in DIAS if m.group(1) <= d <= m.group(2))
    assert pedidos == set(DIAS), f"días que nadie llegó a pedir: {sorted(set(DIAS) - pedidos)}"


def test_la_ficha_recoge_los_diez_dias(monkeypatch):
    """4 días de 10 era el resultado real. Con el documento entero, 10 de 10."""
    salida, _ = _ejecutar(monkeypatch)
    assert len(salida["programa"]) == len(DIAS), (
        f"{len(salida['programa'])} días de {len(DIAS)}"
    )
    n_actos = sum(len(d["eventos"]) for d in salida["programa"])
    assert n_actos == len(DIAS) * FRAGMENTOS_POR_DIA


def test_no_se_marca_como_no_recuperado_cuando_esta_completo(monkeypatch):
    salida, _ = _ejecutar(monkeypatch)
    assert not salida.get("programa_no_recuperado")
    assert not salida.get("sin_programa_publicado")
    assert salida.get("cobertura_dias", 0) >= ta.COBERTURA_DIAS_MINIMA


def test_el_ruido_mejor_puntuado_no_desplaza_al_programa(monkeypatch):
    """
    Los 40 fragmentos de ruido puntúan 0,95 frente al 0,80 del PDF. Con el
    empaquetado anterior ganaban el presupuesto; ahora el documento elegido es
    lo único que se envía.
    """
    _salida, peticiones = _ejecutar(monkeypatch)
    primero = _de_enrichment(peticiones)[0][1]
    assert URL_PDF in primero, "el documento del programa no está en la llamada"


def test_al_extraer_actos_se_manda_el_documento_y_no_el_pool(monkeypatch):
    """
    Identificado el documento, el RAG sobra: todo lo demás es ruido que estorba
    y que se paga en tokens.

    Medido el 2026-09-03, la primera vez que se probó dejando el relleno dentro:
    el documento eran 18 fragmentos y el contexto salió a 105.346 tokens, así
    que las cuatro llamadas de Aranda enviaron 106.124 tokens cada una y LAS
    CUATRO agotaron el timeout de 300 s. La ficha salió con 0 días y 0 actos
    teniendo el programa descargado y bien identificado.
    """
    _salida, peticiones = _ejecutar(monkeypatch)
    for etiqueta, prompt in _de_enrichment(peticiones):
        assert URL_RUIDO not in prompt, (
            f"{etiqueta} lleva el pool entero además del documento"
        )

    # Y el tamaño: lo enviado no puede pasar del documento más sus rótulos.
    mayor = max(len(p) for _e, p in _de_enrichment(peticiones))
    doc = sum(len(t) for t in _fragmentos_del_pdf())
    ruido = sum(len(c["chunk"]) for c in _indexed_chunks()
                if c["url"] == URL_RUIDO)
    assert mayor < doc + ruido, (
        f"la llamada mayor son {mayor} chars: documento {doc} + ruido {ruido}"
    )
    assert mayor < doc * 1.15, (
        f"la llamada mayor son {mayor} chars para un documento de {doc}: "
        f"sobra material que no es el programa"
    )


def test_la_cobertura_se_mide_y_se_avisa_cuando_falta(monkeypatch):
    """
    El otro lado de la moneda: si el modelo solo cubre un día de los diez que
    el documento nombra, la ficha tiene que decirlo. En la ejecución real
    salieron 4 días de 10 con `confianza: alta` y nada lo indicaba.
    """
    async def llm_tacano(system_prompt, user_prompt, max_tokens=-1, etiqueta="LLM"):
        if etiqueta.startswith("LOCATOR"):
            return {"paginas_elegidas": [URL_PDF], "informacion_suficiente": True}
        m = _RE_DIAS_PEDIDOS.search(user_prompt)
        if not m or m.group(1) != DIAS[0]:
            return {"programa": []}      # solo contesta el primer lote
        return {"programa": [{"dia": 1, "fecha": DIAS[0],
                              "eventos": [{"hora": "09:00", "descripcion": "Un acto"}]}]}

    monkeypatch.setattr(ta, "llm_chat_json", llm_tacano)
    monkeypatch.setattr(ta, "process_translation_pipeline", lambda t, m: t)
    salida = asyncio.run(ta.enrich_festival_program(
        MUNICIPIO, LOCALIDAD, dict(FIESTA), _indexed_chunks(), 2026,
        nombres_hermanas=None,
    ))
    assert salida.get("programa_no_recuperado") is True
    assert salida.get("cobertura_dias", 1.0) < ta.COBERTURA_DIAS_MINIMA

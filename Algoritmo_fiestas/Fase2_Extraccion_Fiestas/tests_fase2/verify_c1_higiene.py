"""
Verificación de la Fase 1 (higiene de documentos).

Los casos negativos NO son inventados: salen del fallo real de la ejecución del
2026-08-21 sobre Amurrio, donde el contexto del LLM acabó siendo 21.409
caracteres del PDF de presupuestos municipales, con cada bloque repetido 3 veces.

  C1.1  El regex de horas no confunde códigos contables con horarios.
  C1.2  `is_promising_pdf` rechaza ANEXO_3_Ppto_2025.pdf y acepta los programas.
  C1.3  El mismo PDF enlazado desde 3 páginas produce 1 documento, no 3.
  C1.4  `es_texto_tabular` separa presupuestos de programas, incluso en tabla.
  C1.5  El boilerplate del gestor de contenidos desaparece sin tocar las fiestas.
  C1.6  El pipeline completo sobre el caso de Amurrio recupera el contexto.
  C1.7  `crear_documento` conserva la puntuación de la araña.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import senales_festivas as sf
import higiene_documentos as hd
from fuentes import crear_documento
from scraper.document_extractor import is_promising_pdf

# ── Material real de la ejecución del 2026-08-21 ─────────────────────────────
PPTO_LINEAS = [
    "TOTAL CONCEPTO 3.2.1. 581.580,00 0,00 581.580,00 1.358.729,64 200,00 0,00 1.358.529,64",
    "3.2.2.01. Entrada vehículos por aceras y reserva aparcamiento 56.000,00 0,00 56.408,63",
    "3.2.2.03. Tasa por aprovechamiento pastos comunales 900,00 0,00 900,00 1.071,05",
    "3.4.0.17. Ingreso teatro euskara 6.966,00 0,00 6.966,00 4.311,00 0,00 0,00 4.311,00",
    "TOTAL ARTICULO 3.2. 639.380,00 0,00 639.380,00 1.417.120,36 200,00 0,00 1.416.920,36",
    "Estado de ejecución del presupuesto de ingresos Impreso el 14/01/2025 a las 13:35",
]
TEXTO_PPTO = "\n".join(PPTO_LINEAS * 8)

TEXTO_PROGRAMA = """SAN ROQUE 2026 — PROGRAMA DE ACTOS
Sábado 15 de agosto
12:00 Chupinazo desde el balcón del Ayuntamiento y suelta de la vaquilla
13:00 Kalejira con la banda de música y los gigantes y cabezudos
18:30 Concurso de tortilla de patata en la plaza Juan Urrutia
23:30 Verbena con la orquesta Panorama hasta la madrugada
Domingo 16 de agosto — Día de San Roque
11:00 Misa mayor en la iglesia parroquial con la coral
12:30 Procesión del santo por las calles del casco viejo
00:30 Fuegos artificiales desde el parque"""

TEXTO_PROGRAMA_TABLA = """16/08/2026 | 12:00 | Txupinazoa | Udaletxeko balkoia | 0,00
16/08/2026 | 13:30 | Kalejira | Herriko plaza | 0,00
16/08/2026 | 19:00 | Kontzertua: Gatibu | Frontoia | 15,00
17/08/2026 | 11:00 | Meza nagusia | Eliza | 0,00
17/08/2026 | 18:00 | Herri kirolak | Plaza | 0,00
17/08/2026 | 23:00 | Erromeria | Frontoia | 0,00"""


def test_c1_1_regex_horas_no_confunde_codigos_contables():
    for linea in PPTO_LINEAS[:5]:
        assert sf.contar_horas(linea) == 0, f"falso positivo de hora en: {linea[:60]}"
    # El documento entero: solo las marcas de impresión, que no son actos.
    assert sf.contar_actos_horarios(TEXTO_PPTO) == 0
    assert not sf.parece_programa_de_actos(TEXTO_PPTO)

    # Y no se pierde ninguna hora legítima, incluida la que el regex viejo fallaba.
    for linea, esperado in [("12:00 Chupinazo", 1), ("23.30 Verbena", 1),
                            ("9:30h Misa mayor", 1), ("18.00 h Concurso", 1),
                            ("00:30 Fuegos", 1), ("de 09:00 a 14:00", 2)]:
        assert sf.contar_horas(linea) == esperado, f"'{linea}' -> {sf.contar_horas(linea)}"

    assert sf.parece_programa_de_actos(TEXTO_PROGRAMA)
    assert sf.parece_programa_de_actos(TEXTO_PROGRAMA_TABLA)
    # Una hora suelta en una noticia no es un programa.
    assert not sf.parece_programa_de_actos("La oficina abre a las 09:00 y cierra a las 14:00.")


def test_c1_2_filtro_de_pdf_administrativo():
    portada = ("Ayuntamiento de Amurrio Inicio Noticias Fiestas Jaiak Agenda "
               "Trámites Turismo Contacto Cookies")

    # El caso real: PDF de presupuestos enlazado desde la portada del ayuntamiento.
    assert not is_promising_pdf(
        "https://udala.amurrio.eus/images/docs/pdf/ANEXO_3_Ppto_2025.pdf",
        "Anexo 3", portada, 2026), "el PDF de presupuestos vuelve a colarse"

    # Otros administrativos típicos.
    for u in ["https://x.eus/docs/ordenanzas_fiscales_2026.pdf",
              "https://x.eus/docs/acta_pleno_2026_03.pdf",
              "https://x.eus/docs/licitacion_2026.pdf",
              "https://x.eus/docs/padron_2025.pdf",
              "https://x.eus/docs/memoria_2026.pdf"]:
        assert not is_promising_pdf(u, "Descargar", portada, 2026), f"no filtrado: {u}"

    # Los que SÍ deben pasar.
    for u, t in [("https://x.eus/docs/programa-fiestas-2026.pdf", "Programa"),
                 ("https://x.eus/docs/egitaraua_2026.pdf", "Egitaraua"),
                 ("https://x.eus/docs/cartel_san_roque.pdf", "Cartel"),
                 ("https://x.eus/f/doc.pdf", "Programa de fiestas de San Roque 2026"),
                 ("https://x.cat/docs/festa-major-2026.pdf", "Festa Major")]:
        assert is_promising_pdf(u, t, portada, 2026), f"rechazado indebidamente: {u} / {t}"

    # Un PDF administrativo que SÍ es de fiestas (bases de un concurso) debe pasar.
    assert is_promising_pdf("https://x.eus/docs/bases_concurso_carrozas_fiestas_2026.pdf",
                            "Bases del concurso de carrozas", portada, 2026)

    # Coherencia temporal: un programa de 2019 no sirve para 2026.
    assert not is_promising_pdf("https://x.eus/docs/programa-fiestas-2019.pdf",
                                "Programa 2019", "", 2026)


def test_c1_3_dedup_del_mismo_pdf_desde_varias_paginas():
    url = "https://udala.amurrio.eus/images/docs/pdf/ANEXO_3_Ppto_2025.pdf"
    docs = [crear_documento("web_municipio", url, TEXTO_PPTO, tipo="pdf", score_spider=1220)
            for _ in range(3)]
    docs.append(crear_documento("web_municipio", "https://www.amurrioturismo.com/agenda-amurrio",
                                TEXTO_PROGRAMA, tipo="pagina", score_spider=3340))
    salida, m = hd.deduplicar_documentos(docs)
    assert len(salida) == 2, f"esperados 2 documentos, quedan {len(salida)}"
    assert m["eliminados"] == 2

    # Variantes de la misma URL (www, barra final, fragmento, utm) son la misma.
    variantes = [
        "https://www.amurrio.eus/agenda/",
        "http://amurrio.eus/agenda",
        "https://amurrio.eus/agenda#seccion",
        "https://amurrio.eus/agenda?utm_source=twitter",
    ]
    assert len({hd.canonicalizar_url(u) for u in variantes}) == 1, \
        [hd.canonicalizar_url(u) for u in variantes]
    # Pero distinta ruta es distinto documento.
    assert hd.canonicalizar_url("https://amurrio.eus/agenda") != hd.canonicalizar_url("https://amurrio.eus/agenda2")

    # Casi-duplicado: mismo texto con una línea cambiada, URLs distintas.
    a = crear_documento("web_municipio", "https://a.eus/1", TEXTO_PPTO)
    b = crear_documento("web_municipio", "https://a.eus/2", TEXTO_PPTO + "\nLínea extra final")
    salida2, _ = hd.deduplicar_documentos([a, b])
    assert len(salida2) == 1, "no ha detectado el casi-duplicado"

    # Documentos genuinamente distintos NO se fusionan.
    c = crear_documento("web_municipio", "https://a.eus/3", TEXTO_PROGRAMA)
    salida3, _ = hd.deduplicar_documentos([a, c])
    assert len(salida3) == 2, "ha fusionado documentos distintos"


def test_c1_4_deteccion_de_tablas_de_cifras():
    assert hd.es_texto_tabular(TEXTO_PPTO), "no detecta el presupuesto"
    assert hd.es_texto_tabular(
        "Población por edades 2025\n" + "\n".join(
            f"{i}-{i+4} años {400+i} {200+i} {198+i}" for i in range(0, 80, 5)))
    assert not hd.es_texto_tabular(TEXTO_PROGRAMA), "descarta un programa"
    assert not hd.es_texto_tabular(TEXTO_PROGRAMA_TABLA), "descarta un programa maquetado como tabla"
    # Prosa normal nunca es tabular.
    assert not hd.es_texto_tabular(
        "El Ayuntamiento de Amurrio ha presentado hoy el programa de las fiestas "
        "de San Roque, que se celebrarán del 15 al 17 de agosto con más de "
        "cuarenta actividades para todos los públicos. " * 5)
    # Textos muy cortos no se juzgan por densidad.
    assert not hd.es_texto_tabular("1,00 2,00 3,00")


def test_c1_5_boilerplate():
    menu = "Inicio\nNoticias\nTrámites\nContacto\nAviso legal\nPolítica de cookies"
    docs = [
        crear_documento("web_municipio", f"https://udala.amurrio.eus/p{i}",
                        f"{menu}\nContenido propio de la página {i} con su texto distinto.")
        for i in range(12)
    ]
    docs.append(crear_documento("web_municipio", "https://udala.amurrio.eus/fiestas",
                                f"{menu}\nPrograma de fiestas de San Roque 2026\n12:00 Chupinazo"))
    salida, m = hd.eliminar_boilerplate(docs)
    assert m["lineas_eliminadas"] > 0, "no ha quitado nada"
    for d in salida:
        assert "Aviso legal" not in d["texto"], "queda boilerplate"
    fiestas = [d for d in salida if d["url"].endswith("/fiestas")][0]
    assert "San Roque" in fiestas["texto"] and "12:00 Chupinazo" in fiestas["texto"], \
        "el boilerplate se ha llevado por delante el contenido festivo"

    # Con pocas páginas del dominio no se toca nada (la frecuencia no significa).
    pocos = docs[:3]
    textos_antes = [d["texto"] for d in pocos]
    hd.eliminar_boilerplate(pocos, min_docs=8)
    assert [d["texto"] for d in pocos] == textos_antes, "ha actuado con muestra insuficiente"


def test_c1_6_pipeline_completo_sobre_el_caso_amurrio():
    """El escenario exacto que produjo 0 fiestas: 3 copias del presupuesto + la agenda."""
    url_ppto = "https://udala.amurrio.eus/images/docs/pdf/ANEXO_3_Ppto_2025.pdf"
    docs = [crear_documento("web_municipio", url_ppto, TEXTO_PPTO, tipo="pdf", score_spider=1220)
            for _ in range(3)]
    docs.append(crear_documento("web_municipio", "https://www.amurrioturismo.com/agenda-amurrio",
                                TEXTO_PROGRAMA, tipo="pagina", score_spider=3340))
    docs.append(crear_documento("web_municipio", "https://udala.amurrio.eus/cas/calendario/eventosanual/2026/",
                                TEXTO_PROGRAMA_TABLA, tipo="pagina", score_spider=1650))

    salida, m = hd.limpiar_documentos(docs, etiqueta="Amurrio")
    urls = {d["url"] for d in salida}

    assert url_ppto not in urls, "el presupuesto sigue en el material que verá el LLM"
    assert "https://www.amurrioturismo.com/agenda-amurrio" in urls, "se ha perdido la agenda"
    assert any("eventosanual" in u for u in urls), "se ha perdido el calendario de 2026"
    assert len(salida) == 2, f"esperados 2 documentos útiles, hay {len(salida)}: {urls}"
    assert m["chars_salida"] < m["chars_entrada"]


def test_c1_7_crear_documento_conserva_el_score_de_la_arana():
    d = crear_documento("web_municipio", "https://x/agenda", "texto", tipo="pagina",
                        score_spider=3340, rank_spider=0)
    assert d["score_spider"] == 3340 and d["rank_spider"] == 0
    # Compatibilidad: las llamadas antiguas siguen funcionando.
    d2 = crear_documento("web_municipio", "https://x/y", "texto")
    assert d2["score_spider"] == 0 and d2["rank_spider"] is None


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  OK    {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  FALLO {nombre}: {e}")
    if fallos:
        print(f"\nVERIFY C1 FALLIDO: {fallos} comprobaciones.")
        sys.exit(1)
    print("\nVERIFY C1 PASSED: higiene de documentos operativa.")

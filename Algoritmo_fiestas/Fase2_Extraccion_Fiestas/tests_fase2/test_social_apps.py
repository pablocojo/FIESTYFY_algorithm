"""Tests de las partes sin GUI de la Etapa C (util, cola, caché de contenido)."""

import json
from datetime import date

from scraper.social_apps.util import (
    validar_candidato_perfil,
    parsear_fecha_post,
    handle_de_url,
    url_de_handle,
)
from scraper.social_apps.cola import construir_cola
from scraper.social_apps.contenido_cache import ContenidoCache
from scraper import social_content


# ──────────────────────────────────────────────
# Validación de candidatos in-app
# ──────────────────────────────────────────────

def test_candidato_oficial_valido():
    ok, motivo = validar_candidato_perfil("Ayuntamiento de Salinas de Añana", "Salinas de Añana")
    assert ok, motivo
    ok, _ = validar_candidato_perfil("Ayto Salinas de Añana Oficial", "Salinas de Añana")
    assert ok


def test_candidato_sin_marcador_rechaza():
    # Peña privada: contiene la localidad pero no es institucional
    ok, motivo = validar_candidato_perfil("Peña El Cohete Salinas de Añana", "Salinas de Añana")
    assert not ok, motivo


def test_candidato_otro_pueblo_rechaza():
    # Homónimo parcial: no contiene el nombre COMPLETO
    ok, _ = validar_candidato_perfil("Ayuntamiento de Salinas de Pisuerga", "Salinas de Añana")
    assert not ok


def test_candidato_por_handle():
    ok, _ = validar_candidato_perfil("Ayto Albacete @aytoalbacete", "Albacete", handle_esperado="aytoalbacete")
    assert ok
    ok, _ = validar_candidato_perfil("Otra cuenta @otracosa", "Albacete", handle_esperado="aytoalbacete")
    assert not ok


def test_candidato_handle_con_puntos():
    # El handle con puntos debe casar aunque la app lo muestre con puntos
    ok, _ = validar_candidato_perfil("ayto.laadrada", "La Adrada", handle_esperado="ayto.laadrada")
    assert ok


# ──────────────────────────────────────────────
# Fechas de posts
# ──────────────────────────────────────────────

HOY = date(2026, 7, 4)


def test_fecha_absoluta():
    assert parsear_fecha_post("Publicado el 12 de junio", HOY) == date(2026, 6, 12)
    assert parsear_fecha_post("3 jul", HOY) == date(2026, 7, 3)
    assert parsear_fecha_post("15 de agosto de 2025", HOY) == date(2025, 8, 15)


def test_fecha_futura_sin_anno_es_del_anno_pasado():
    # "10 dic" visto el 4 de julio → diciembre pasado
    assert parsear_fecha_post("10 dic", HOY) == date(2025, 12, 10)


def test_fecha_relativa():
    assert parsear_fecha_post("hace 3 dias", HOY) == date(2026, 7, 1)
    assert parsear_fecha_post("hace 2 semanas", HOY) == date(2026, 6, 20)
    assert parsear_fecha_post("hace 5 horas", HOY) == HOY
    assert parsear_fecha_post("ayer", HOY) == date(2026, 7, 3)


def test_fecha_relativa_corta_instagram():
    # Formato corto de IG/X: "1 sem", "3 d", "5 h"
    assert parsear_fecha_post("dssgazteria 1 sem", HOY) == date(2026, 6, 27)
    assert parsear_fecha_post("publicado 3 d", HOY) == date(2026, 7, 1)
    assert parsear_fecha_post("5 h", HOY) == HOY


def test_fecha_absoluta_no_confundida_con_corta():
    # "8 de agosto" NO debe interpretarse como el formato corto "8 d"
    # (al ser futura y sin año, como fecha de post se asume del año pasado)
    assert parsear_fecha_post("publicado el 8 de agosto", HOY) == date(2025, 8, 8)
    # "22 de junio" (caption real de IG) → absoluta del año en curso
    assert parsear_fecha_post("34 Me gusta 22 de junio", HOY) == date(2026, 6, 22)


def test_fecha_ilegible():
    assert parsear_fecha_post("texto sin fecha alguna", HOY) is None


# ──────────────────────────────────────────────
# Handles y URLs
# ──────────────────────────────────────────────

def test_handle_de_url():
    assert handle_de_url("https://www.instagram.com/aytoalbacete") == "aytoalbacete"
    assert handle_de_url("https://www.facebook.com/profile.php?id=123456") == "123456"
    assert handle_de_url("https://www.facebook.com/pages/ayto-x/999") == "ayto-x"
    assert handle_de_url("https://x.com/aytolaadrada") == "aytolaadrada"


def test_url_de_handle():
    assert url_de_handle("twitter", "ayto") == "https://x.com/ayto"
    assert url_de_handle("instagram", "ayto") == "https://www.instagram.com/ayto"


# ──────────────────────────────────────────────
# Cola de trabajo
# ──────────────────────────────────────────────

LUGARES = {
    "l1": {"id": "l1", "nombre": "Villagrande", "poblacion": 20000},
    "l2": {"id": "l2", "nombre": "Aldeachica", "poblacion": 300},
}


def _contenido(tmp_path, datos=None):
    path = tmp_path / "contenido.json"
    if datos is not None:
        path.write_text(json.dumps(datos), encoding="utf-8")
    return ContenidoCache(str(path))


def test_cola_leer_y_buscar(tmp_path):
    redes_cache = {
        "l1": {"instagram": "https://www.instagram.com/villagrande", "facebook": None,
               "twitter": None, "pendiente_apps": True},
        "l2": {"instagram": None, "facebook": None, "twitter": None, "pendiente_apps": True},
    }
    cola = construir_cola(redes_cache, LUGARES, _contenido(tmp_path), ttl_dias=30)
    tipos = [(t["tipo"], t["lugar_id"], t["red"]) for t in cola]
    # 1 leer (l1 instagram) + 2 buscar de l1 (fb, tw) + 3 buscar de l2
    assert tipos[0] == ("leer", "l1", "instagram")
    assert ("buscar", "l1", "facebook") in tipos
    assert sum(1 for t in cola if t["tipo"] == "buscar") == 5
    # leer va antes que buscar; y dentro de buscar, mayor población primero
    buscar = [t for t in cola if t["tipo"] == "buscar"]
    assert buscar[0]["lugar_id"] == "l1"


def test_cola_respeta_ttl(tmp_path):
    redes_cache = {"l1": {"instagram": "https://www.instagram.com/villagrande",
                          "facebook": None, "twitter": None, "pendiente_apps": False}}
    contenido = _contenido(tmp_path, {
        "l1": {"instagram": {"leido_en": "2026-07-01", "posts": []}},
    })
    cola = construir_cola(redes_cache, LUGARES, contenido, ttl_dias=30, hoy=date(2026, 7, 4))
    assert cola == []  # leído hace 3 días < TTL 30

    cola2 = construir_cola(redes_cache, LUGARES, contenido, ttl_dias=2, hoy=date(2026, 7, 4))
    assert len(cola2) == 1  # TTL vencido → releer


def test_cola_no_repite_busquedas_sin_resultado(tmp_path):
    redes_cache = {"l2": {"instagram": None, "facebook": None, "twitter": None,
                          "pendiente_apps": True,
                          "apps_sin_resultado": {"instagram": "2026-07-01"}}}
    cola = construir_cola(redes_cache, LUGARES, _contenido(tmp_path), ttl_dias=30)
    redes_en_cola = {t["red"] for t in cola}
    assert "instagram" not in redes_en_cola
    assert redes_en_cola == {"facebook", "twitter"}


def test_cola_sin_nombre_no_busca(tmp_path):
    redes_cache = {"desconocido": {"instagram": None, "facebook": None, "twitter": None,
                                   "pendiente_apps": True}}
    cola = construir_cola(redes_cache, {}, _contenido(tmp_path), ttl_dias=30)
    assert cola == []


# ──────────────────────────────────────────────
# Caché de contenido + compatibilidad con social_content
# ──────────────────────────────────────────────

def test_contenido_cache_guardar_y_vigencia(tmp_path):
    cache = ContenidoCache(str(tmp_path / "c.json"))
    posts = [{"texto": "Fiestas este finde", "fecha": "2026-08-01", "captura": None}]
    cache.guardar_posts("l1", "facebook", posts, hoy=date(2026, 7, 4))

    assert cache.vigente("l1", "facebook", ttl_dias=30, hoy=date(2026, 7, 10))
    assert not cache.vigente("l1", "facebook", ttl_dias=3, hoy=date(2026, 7, 10))
    # Releer desde disco
    cache2 = ContenidoCache(str(tmp_path / "c.json"))
    assert cache2.entrada("l1", "facebook")["posts"] == posts


# ──────────────────────────────────────────────
# Similitud difusa handle ↔ nombre mostrado
# ──────────────────────────────────────────────

def test_similitud_handle_nombre_de_pagina():
    from scraper.social_apps.drivers import similitud_handle
    # Caso real de la sesión supervisada: FB muestra el nombre, no el handle
    assert similitud_handle("Donostiako Gazteria", "dssgazteria") >= 0.55
    assert similitud_handle("Ayuntamiento de Albacete", "aytoalbacete") >= 0.55
    # Contención directa
    assert similitud_handle("Ayto La Adrada @ayto.laadrada", "ayto.laadrada") == 1.0
    # Nada que ver → por debajo del umbral
    assert similitud_handle("Peluquería Loli", "aytoalbacete") < 0.55


# ──────────────────────────────────────────────
# Verificación de perfil abierto (por título de ventana)
# ──────────────────────────────────────────────

class _VentanaStub:
    def __init__(self, titulo):
        self._titulo = titulo

    def window_text(self):
        return self._titulo

    def descendants(self, **kwargs):
        return []


class _GuardStub:
    def verificar(self):
        pass


def _driver_con_titulo(titulo):
    from scraper.social_apps.drivers import DriverBase
    return DriverBase(_VentanaStub(titulo), guard=_GuardStub())


def test_perfil_abierto_facebook_por_nombre():
    d = _driver_con_titulo("(1) Ayuntamiento de Torrejón de Velasco | Facebook")
    assert d._perfil_abierto(None, "Ayuntamiento de Torrejón de Velasco")


def test_resultados_de_busqueda_no_es_perfil():
    d = _driver_con_titulo("(1) torrejón de velasco - Resultados de búsqueda | Facebook")
    assert not d._perfil_abierto(None, "Torrejón de Velasco")


def test_perfil_abierto_instagram_por_handle():
    d = _driver_con_titulo("Ayto La Adrada (@ayto.laadrada) • Fotos y videos de Instagram")
    assert d._perfil_abierto("ayto.laadrada", None)


def test_otro_titulo_no_es_perfil():
    d = _driver_con_titulo("X - Explore / X")
    assert not d._perfil_abierto("aytoalbacete", "Albacete")


def test_filas_de_historial_no_son_candidatos():
    # Caso real del log: 'dssgazteria Eliminar dssgazteria del historial'
    from scraper.social_apps.drivers import es_fila_historial
    assert es_fila_historial("dssgazteria Eliminar dssgazteria del historial")
    assert es_fila_historial("Recent searches")
    assert not es_fila_historial("Donostia Gazteria")
    assert not es_fila_historial("Ayuntamiento de Amurrio")


def test_enlaces_externos_no_son_candidatos():
    # Caso real: el panel Detalles de FB expone la web del ayuntamiento;
    # clicarla sacaba al driver del perfil
    from scraper.social_apps.drivers import es_link_externo
    assert es_link_externo("donostia.eus/Gazteria")
    assert es_link_externo("gazteria@donostia.eus")
    assert es_link_externo("https://www.ayto-ejemplo.es")
    assert es_link_externo("www.aytoalbacete.es")
    # Nombres de página normales NO se filtran
    assert not es_link_externo("Donostia Gazteria")
    assert not es_link_externo("Ayuntamiento de Torrejón de Velasco")


def test_verificacion_por_nombre_de_pagina():
    # FB no muestra el handle en el perfil: se acepta el nombre del candidato
    # clicado en el título (ya pre-validado contra el handle)
    d = _driver_con_titulo("(1) Donostia Gazteria | Facebook")
    assert d._verificar_perfil_con_handle("dssgazteria", "Donostia Gazteria") is True
    # Sin candidato y sin handle visible → NO se verifica (no se lee nada)
    # (_texto_visible necesita guard; con título no-resultados y sin nombre debe fallar antes)
    d2 = _driver_con_titulo("(1) dssgazteria - Resultados de búsqueda | Facebook")
    assert d2._verificar_perfil_con_handle("dssgazteria", "Donostia Gazteria") is False


def test_social_content_lee_formato_runner(monkeypatch):
    monkeypatch.setattr(social_content, "_cache", {
        "l1": {"facebook": {"leido_en": "2026-07-04", "posts": [
            {"texto": "Verbena el sábado", "fecha": "2026-08-01",
             "es_programa": True, "texto_programa": "23:00 Orquesta"},
        ]}},
    })
    docs = social_content.cargar_documentos_rrss(
        {"id": "l1", "nombre": "Villagrande"}, {"id": "m1", "nombre": "Municipio"}
    )
    assert len(docs) == 1
    assert "Verbena el sábado" in docs[0]["texto"]
    assert "23:00 Orquesta" in docs[0]["texto"]

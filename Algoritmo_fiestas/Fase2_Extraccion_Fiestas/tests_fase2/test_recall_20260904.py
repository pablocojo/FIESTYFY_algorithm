"""
Los arreglos del 2026-09-04, medidos sobre los casos reales que los provocaron.

Salen todos de la tirada corta sobre municipios trampa (`fiestas_prueba_juez.json`),
donde de ~12 fiestas documentadas en internet solo salieron 2.
"""

import asyncio

import pytest

from config_idiomas import comunidad_de, perfil_de_lugar
from scraper.google_search import _build_queries
from fuentes import documento_es_ajeno_al_municipio
from scraper.heuristic_spider import URL_BLACKLIST, AsyncTwoPassSpider
import llm_processor.text_analyzer as ta


# ──────────────────────────────────────────────────────────────
# La comunidad, que nunca llegaba
# ──────────────────────────────────────────────────────────────

def test_la_comunidad_se_lee_del_campo_que_existe():
    """
    El código la leía como `comunidad_autonoma` y NINGUNO de los 9.752 lugares
    del dataset tiene esa clave: iba vacía en las consultas y en la elección del
    perfil de idioma, en todas las ejecuciones y todos los municipios.
    """
    assert comunidad_de({"comunidad": "Extremadura"}) == "Extremadura"
    assert comunidad_de({"comunidad_autonoma": "Galicia"}) == "Galicia"   # respaldo
    assert comunidad_de({}) == ""
    assert comunidad_de(None) == ""


def test_un_municipio_vasco_vuelve_a_ser_bilingue():
    """Con la comunidad vacía, Álava se trataba como monolingüe castellano."""
    vasco = {"nombre": "Amurrio", "provincia": "Álava", "comunidad": "País Vasco"}
    assert "eu" in perfil_de_lugar(vasco)["idiomas_a_detectar"]
    manchego = {"nombre": "Tobarra", "provincia": "Albacete", "comunidad": "Castilla-La Mancha"}
    assert perfil_de_lugar(manchego)["idiomas_a_detectar"] == ["es"]


# ──────────────────────────────────────────────────────────────
# El salto de dominio
# ──────────────────────────────────────────────────────────────

# Todas las redirecciones REALES del histórico de logs, más el caso que falló.
REDIRECCIONES = [
    ("http://www.santamartadelosbarros.com", "https://badajoz.es", True),
    ("http://www.villagarciadelatorre.es", "https://villagarciadelatorre.com", False),
    ("https://www.ayuntamientodeoyon.com/", "https://ayuntamientodeoyon.eus/es/", False),
    ("http://www.tobarra.es/", "https://tobarra.es/", False),
    ("http://www.laparra.es", "https://laparra.es/", False),
    ("https://www.alfozdequintanadueñas.es/", "https://www.xn--alfozdequintanadueas-l7b.es/", False),
    ("https://www.añanagesaltzaudala.eus/", "https://www.xn--aanagesaltzaudala-fxb.eus/", False),
    ("http://amurrio.eus/cas", "https://udala.amurrio.eus/cas", False),
    ("https://agurain.eus/index.php/es/", "https://agurain.eus/eu/index.php/es", False),
    ("https://www.elchedelasierra.es", "https://elchedelasierra.es/", False),
]


@pytest.mark.parametrize("origen,destino,salta", REDIRECCIONES)
def test_solo_salta_cuando_la_web_es_de_otro(origen, destino, salta):
    """
    `santamartadelosbarros.com` redirige a la Diputación de Badajoz, y se
    mapearon 77 páginas suyas como si fueran del municipio. Pero la regla debe
    ser conservadora: un falso positivo cuesta el rastreo entero de un pueblo.
    """
    assert AsyncTwoPassSpider.salta_a_otro_dominio(origen, destino) is salta


def test_el_punycode_no_cuenta_como_otro_dominio():
    """`xn--alfozdequintanadueas-l7b.es` es `alfozdequintanadueñas.es`."""
    assert AsyncTwoPassSpider._nombre_de_dominio(
        "https://www.xn--alfozdequintanadueas-l7b.es/") == "alfozdequintanadueñas"


# ──────────────────────────────────────────────────────────────
# Páginas legales fuera del rastreo
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,bloqueada", [
    ("https://www.elfresno.es/contacto/portal-web/proteccion-de-datos.html", True),
    ("https://www.elfresno.es/contacto/portal-web/aviso-legal.html", True),
    ("https://x.es/politica-de-cookies", True),
    ("https://corralrubio.es/fiestas/", False),
    ("https://laroda.es/wp-content/uploads/2026/07/LA-RODA-Fiestas-Programa.pdf", False),
    ("https://tobarra.es/semana-santa/", False),
])
def test_el_aviso_legal_no_entra_pero_las_fiestas_si(url, bloqueada):
    """
    El Fresno: 15 de 60 chunks del contexto —el 25%— salían de su propio aviso
    legal y su política de datos, y encabezaban el ranking. Son el falso positivo
    perfecto: del dominio correcto y sin una palabra sobre fiestas.
    """
    assert any(b in url.lower() for b in URL_BLACKLIST) is bloqueada


# ──────────────────────────────────────────────────────────────
# El topónimo lo decide el LLM, no el código
# ──────────────────────────────────────────────────────────────

SM_LOC = {"id": "06121000101", "nombre": "Santa Marta", "provincia": "Badajoz",
          "comunidad": "Extremadura", "es_capital": True}
SM_MUN = {"id": "06121000000", "nombre": "Santa Marta", "provincia": "Badajoz",
          "comunidad": "Extremadura", "sitio_web": "http://www.santamartadelosbarros.com",
          "nombre_oficial": "Santa Marta de los Barros"}


def _con_llm(monkeypatch, primera, repregunta):
    llamadas = []

    async def falso(sysp, userp, max_tokens=None, etiqueta=""):
        llamadas.append(etiqueta)
        return repregunta if etiqueta == "PERTENENCIA/REPREGUNTA" else primera

    monkeypatch.setattr(ta, "llm_chat_json", falso)
    return llamadas


def test_el_nombre_largo_del_propio_pueblo_ya_no_mata_la_ficha(monkeypatch):
    """
    'Candelas 2026' era la ÚNICA ficha real de Santa Marta y el veto del código
    la descartó: el modelo la situó bien —en "Santa Marta de los Barros"— y el
    código no reconoció ese nombre porque el dataset guarda el corto.
    """
    llamadas = _con_llm(
        monkeypatch,
        {"es_de_la_localidad": "si", "es_una_fiesta": "si",
         "lugar_real": "Santa Marta de los Barros, Badajoz", "razon": "hogueras y verbena"},
        {"es_de_la_localidad": "si", "razon": "es el nombre oficial del mismo pueblo"},
    )
    ficha = {"nombre": "Candelas 2026", "fecha_inicio": "2026-02-02",
             "fecha_fin": "2026-02-02", "programa": []}
    salvadas = asyncio.run(ta.filtrar_por_pertenencia([ficha], SM_LOC, SM_MUN, [], []))

    assert len(salvadas) == 1
    assert "PERTENENCIA/REPREGUNTA" in llamadas, "debía repreguntar, no descartar"


def test_un_pueblo_distinto_con_nombre_parecido_sigue_cayendo(monkeypatch):
    """
    El veto existía por un fallo medido: el modelo respondía "sí" y a la vez
    situaba la fiesta en "Arroyomolinos de la Vera", otro municipio. Quitar el
    veto sin repreguntar devolvería esa ficha.
    """
    _con_llm(
        monkeypatch,
        {"es_de_la_localidad": "si", "es_una_fiesta": "si",
         "lugar_real": "Arroyomolinos de la Vera", "razon": "lo organiza su ayuntamiento"},
        {"es_de_la_localidad": "no", "razon": "es otro municipio de Cáceres"},
    )
    loc = {"id": "1", "nombre": "Arroyomolinos", "provincia": "Cáceres",
           "comunidad": "Extremadura", "es_capital": True}
    ficha = {"nombre": "Fiestas de Arroyomolinos", "fecha_inicio": "2026-10-29",
             "fecha_fin": "2026-10-30", "programa": []}
    assert asyncio.run(ta.filtrar_por_pertenencia([ficha], loc, dict(loc), [], [])) == []


def test_la_identidad_lleva_el_nombre_oficial_y_la_web():
    """Es lo que permite al modelo reconocer el topónimo largo como nuestro."""
    bloque = ta._bloque_identidad(SM_LOC, SM_MUN, [])
    assert "Santa Marta de los Barros" in bloque
    assert "santamartadelosbarros.com" in bloque
    assert "ES LA CAPITAL" in bloque


def test_los_dos_nombres_van_juntos_y_dicen_que_son_el_mismo_sitio():
    """
    Puestos como dos campos separados, el modelo los leyó como dos pueblos
    distintos y descartó la Semana Santa de Santa Marta razonando: «el texto la
    sitúa en Santa Marta de los Barros, pero el nombre oficial del municipio es
    Santa Marta de los Barros, no Santa Marta». Cambiar el veto del código por el
    mismo error dentro del modelo no es progreso.
    """
    bloque = ta._bloque_identidad(SM_LOC, SM_MUN, [])
    linea = next(l for l in bloque.splitlines() if l.strip().startswith("Localidad:"))
    assert "Santa Marta de los Barros" in linea, "los dos nombres deben ir en la misma línea"
    assert "mismo sitio" in linea
    # Y no debe existir un campo aparte que invite a leerlos como sitios distintos.
    assert "Nombre oficial completo del municipio:" not in bloque


def test_sin_nombre_oficial_la_identidad_no_lo_inventa():
    mun = {"id": "1", "nombre": "Tobarra", "provincia": "Albacete", "comunidad": "Castilla-La Mancha"}
    bloque = ta._bloque_identidad(mun, mun, [])
    assert "Nombre oficial completo" not in bloque


# ──────────────────────────────────────────────────────────────
# La forma invertida del INE: "Parra, La"
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto,url,ajeno", [
    # Documentos que SÍ son de La Parra (Badajoz) y se descartaban por escribirla
    # como la escribe el INE. Los dos son reales de la tirada del 2026-09-04.
    ("festivos de Parra, La", "https://calendariosnacionales.com/es/festivos/ext/badajoz/parra-la/", False),
    ("calendario laboral Parra (La)", "https://www.calendarios-laborales.es/laboral-parra_(la)-2026-ba", False),
    ("Las fiestas de La Parra se celebran en agosto", "https://x.es/a", False),
    # Y lo que debe seguir cayendo.
    ("Fiestas de La Parrilla", "https://x.es/b", True),
    ("Fiestas de Almansa", "https://almansa.es", True),
    ("Fiestas patronales de Roda, La", "https://x.es/c", True),
])
def test_el_nombre_invertido_del_ine_cuenta_como_mencion(texto, url, ajeno):
    """
    "Parra, La" es como lo escriben el INE y casi todo lo administrativo, y en
    las URLs sale "parra-la" o "parra_(la)". Buscando solo "La Parra" esas
    fuentes se daban por ajenas mientras el contexto se llenaba con el La Parra
    de Ávila. Afecta a 1.786 lugares del dataset, el 18 % del total.
    """
    assert documento_es_ajeno_al_municipio(texto, url, "La Parra", "La Parra") is ajeno


def test_un_nombre_sin_articulo_no_cambia_de_comportamiento():
    assert documento_es_ajeno_al_municipio(
        "Fiestas de Tobarra", "https://x.es", "Tobarra", "Tobarra") is False
    assert documento_es_ajeno_al_municipio(
        "Fiestas de Almansa", "https://x.es", "Tobarra", "Tobarra") is True


# ──────────────────────────────────────────────────────────────
# Un lote perdido no puede recortar la fiesta
# ──────────────────────────────────────────────────────────────

def test_un_lote_sin_respuesta_no_recorta_el_rango():
    """
    Santa Marta de los Barros: el 4.º de cuatro lotes del enrichment se perdió
    por timeout y el recorte dio la fiesta por terminada el 28 de julio, cuando
    su programa llega al 1 de agosto. El día que se perdió era el 29, el de la
    patrona. Los días que faltan no es que no existan: es que nadie los preguntó.
    """
    fiesta = {
        "nombre": "Fiestas Patronales de Santa Marta de los Barros",
        "fecha_inicio": "2026-07-23", "fecha_fin": "2026-08-01",
        "lotes_incompletos": 1,
        "programa": [{"dia": i, "fecha": f"2026-07-{22 + i}",
                      "eventos": [{"hora": "20:00", "descripcion": f"acto {i}"}]}
                     for i in range(1, 7)],
    }
    assert ta.recortar_rango_al_programa(dict(fiesta))["fecha_fin"] == "2026-08-01"


def test_sin_lotes_perdidos_el_recorte_sigue_funcionando():
    """El freno nuevo no puede desactivar el recorte cuando todo fue bien."""
    fiesta = {
        "nombre": "F", "fecha_inicio": "2026-07-23", "fecha_fin": "2026-08-15",
        "programa": [{"dia": i, "fecha": f"2026-07-{22 + i}",
                      "eventos": [{"hora": "20:00", "descripcion": f"acto {i}"}]}
                     for i in range(1, 7)],
    }
    assert ta.recortar_rango_al_programa(dict(fiesta))["fecha_fin"] < "2026-08-15"


def test_un_lote_perdido_deja_el_programa_como_parcial():
    """
    "Completo" es la bandera de la que se va a fiar la base de datos. Con un lote
    sin preguntar no se puede afirmar.
    """
    fiesta = {
        "nombre": "F", "origen": "extraccion", "confianza": "alta",
        "lotes_incompletos": 1,
        "programa": [{"dia": 1, "fecha": "2026-07-23", "eventos": [
            {"hora": "20:00", "descripcion": "a"}, {"hora": "21:00", "descripcion": "b"}]}],
    }
    assert ta.marcar_estado_del_programa(fiesta)["programa_estado"] == "parcial"

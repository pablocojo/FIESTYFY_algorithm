"""Tests del plan de mejora de lectura de perfiles (M1-M6, partes puras)."""

from datetime import date

from PIL import Image, ImageDraw

from scraper.social_apps.util import (
    agrupar_posts,
    hash_perceptual,
    dominio_base,
    extraer_datos_ficha,
    parsear_fecha_post,
)

HOY = date(2026, 7, 4)


# ──────────────────────────────────────────────
# M1 — Clustering de textos en posts
# ──────────────────────────────────────────────

def _item(texto, left, top, right, bottom, clave=None):
    return {"texto": texto, "left": left, "top": top, "right": right, "bottom": bottom, "clave": clave}


def test_clustering_separa_columnas_y_posts():
    # Caso real: panel Detalles (izquierda) + dos posts del feed (derecha)
    items = [
        _item("Detalles", 40, 300, 360, 320),
        _item("gazteria@donostia.eus", 40, 330, 360, 350),
        _item("Post A: fiestas este finde", 400, 300, 900, 320),
        _item("1 de julio a las 1:29 p. m.", 400, 325, 700, 345),
        _item("Post B: pleno municipal", 400, 500, 900, 520),  # hueco 155px > 90
    ]
    clusters = agrupar_posts(items)
    assert len(clusters) == 3
    textos = [c["texto"] for c in clusters]
    assert any("Post A" in t and "1 de julio" in t for t in textos)
    assert any("Detalles" in t and "gazteria@" in t for t in textos)
    assert any("Post B" in t and "Post A" not in t for t in textos)


def test_clustering_por_clave_de_contenedor():
    # Mismo contenedor UIA = mismo post aunque estén separados verticalmente
    items = [
        _item("Caption del post", 400, 300, 900, 320, clave=("a", 1)),
        _item("22 de junio", 400, 600, 500, 615, clave=("a", 1)),
        _item("Otro post", 400, 700, 900, 720, clave=("b", 2)),
    ]
    clusters = agrupar_posts(items)
    assert len(clusters) == 2
    assert any("Caption" in c["texto"] and "22 de junio" in c["texto"] for c in clusters)


def test_clustering_fechas_por_post():
    # LA CLAVE del bug: el Destacado de 2022 no debe contaminar el post nuevo
    items = [
        _item("Destacado antiguo", 400, 100, 600, 120),
        _item("22 de noviembre de 2022", 400, 125, 600, 140),
        _item("Post nuevo con verbena", 400, 400, 900, 420),
        _item("1 de julio a la 1:29", 400, 425, 700, 445),
    ]
    clusters = agrupar_posts(items)
    fechas = [parsear_fecha_post(c["texto"], HOY) for c in clusters]
    assert date(2022, 11, 22) in fechas
    assert date(2026, 7, 1) in fechas  # el post nuevo conserva SU fecha


# ──────────────────────────────────────────────
# M4 — Hash perceptual
# ──────────────────────────────────────────────

def _imagen_patron(tmp_path, nombre, desplazamiento):
    ruta = str(tmp_path / nombre)
    img = Image.new("RGB", (400, 400), (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([desplazamiento, 50, desplazamiento + 120, 300], fill=(20, 20, 20))
    img.save(ruta)
    return ruta


def test_hash_igual_para_capturas_identicas(tmp_path):
    r1 = _imagen_patron(tmp_path, "a.png", 50)
    r2 = _imagen_patron(tmp_path, "b.png", 50)
    assert hash_perceptual(r1) == hash_perceptual(r2)


def test_hash_distinto_para_capturas_distintas(tmp_path):
    r1 = _imagen_patron(tmp_path, "a.png", 50)
    r2 = _imagen_patron(tmp_path, "b.png", 220)
    assert hash_perceptual(r1) != hash_perceptual(r2)


def test_hash_imagen_invalida():
    assert hash_perceptual("no_existe.png") is None


# ──────────────────────────────────────────────
# M2 — Ficha del perfil y dominios
# ──────────────────────────────────────────────

def test_dominio_base():
    assert dominio_base("https://www.donostia.eus/Gazteria") == "donostia.eus"
    assert dominio_base("www.aytolaadrada.es") == "aytolaadrada.es"
    assert dominio_base("donostia.eus") == "donostia.eus"
    assert dominio_base("") is None


def test_extraer_datos_ficha_caso_donostia():
    textos = [
        "Gazteria Saila - Departamento de Juventud / Donostiako Udala",
        "943 48 19 09",
        "gazteria@donostia.eus",
        "donostia.eus/Gazteria",
        "3,1 mil seguidores",
        "Página · Organización gubernamental",
    ]
    ficha = extraer_datos_ficha(textos, titulo="(1) Donostia Gazteria | Facebook")
    assert "donostia.eus" in ficha["webs"]
    assert "gazteria@donostia.eus" in ficha["emails"]
    assert "seguidores" in (ficha["seguidores"] or "")
    assert ficha["titulo"].startswith("(1) Donostia")


def test_ficha_email_no_contamina_webs():
    # Si el dominio SOLO aparece en el email, no es una "web" de la bio
    ficha = extraer_datos_ficha(["contacto: info@aytoexample.es"])
    assert ficha["webs"] == []
    assert ficha["emails"] == ["info@aytoexample.es"]


# ──────────────────────────────────────────────
# M6 — Fechas en lenguas cooficiales
# ──────────────────────────────────────────────

def test_fecha_euskera_mes_delante():
    # "ekainak 27" = 27 de junio (formato de los carteles de las capturas)
    assert parsear_fecha_post("Intxaurjaiak 2026 ekainak 27", HOY) == date(2026, 6, 27)
    assert parsear_fecha_post("ekainak 23", HOY) == date(2026, 6, 23)
    # futura sin año → año pasado (regla de timestamps de posts)
    assert parsear_fecha_post("abenduak 10", HOY) == date(2025, 12, 10)


def test_fecha_catalan_y_gallego():
    assert parsear_fecha_post("3 de febrer", HOY) == date(2026, 2, 3)
    assert parsear_fecha_post("15 de maio", HOY) == date(2026, 5, 15)

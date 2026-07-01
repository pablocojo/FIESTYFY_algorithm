"""
Parte 2: enriquecimiento del JSON con distritos, barrios y pedanias.

Esta fase parte de una ciudad grande ya construida y anade sus lugares hijos
cuando Wikipedia permite localizarlos con poblacion demostrada superior a 20.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from config import BASE_WIKI_URL, DELAY_BETWEEN_REQUESTS, MAX_SNIPPET_TOKENS
from extractors import construir_lugar
from llm_client import call_llm, contar_tokens
from logger import log_error
from scraper import fetch_url, get_soup, buscar_titulos_relacionados_api
from datos_ine import buscar_municipio_ine

DATOS_INE_GLOBAL: dict | None = None

Candidate = dict[str, str | int | float | bool | None]

def _clean_soup_for_extraction(soup: BeautifulSoup) -> None:
    """Elimina infoboxes y navboxes para evitar ruido en la extraccion de barrios/pedanias."""
    for box in soup.find_all(class_=['infobox', 'navbox']):
        box.decompose()

RELEVANT_SECTION_WORDS = (
    "distrito",
    "distritos",
    "barrio",
    "barrios",
    "pedania",
    "pedanias",
    "localidad",
    "localidades",
    "aldea",
    "caserio",
    "nucleo",
    "nucleos",
    "entidad singular",
    "entidad local menor",
    "eatim",
    "parroquia",
    "diputacion",
    "urbanizacion",
    "anejo",
    "agregado",
    "organizacion territorial",
    "organizacion administrativa",
    "division administrativa",
    "division territorial",
    "urbanismo",
    "administracion",
    "politico-administrativa",
)

FALSE_POSITIVE_WORDS = (
    "aeropuerto",
    "avenida",
    "calle",
    "carretera",
    "castillo",
    "catedral",
    "colegio",
    "comarca",
    "estacion",
    "iglesia",
    "monumento",
    "museo",
    "parque",
    "playa",
    "plaza",
    "provincia",
    "puente",
    "rio",
    "teatro",
    "universidad",
)


def _normalizar_texto(texto: any) -> str:
    if isinstance(texto, list):
        texto = " ".join(str(t) for t in texto)
    elif not isinstance(texto, str):
        texto = str(texto or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def _limpiar_nombre(nombre: str, tipo: str, ciudad_nombre: str = "") -> str:
    nombre = re.sub(r"\[\d+\]", "", nombre or "").strip()
    nombre = re.sub(r"^(distrito|barrio|barriada|pedania|pedanía|localidad|aldea|caserio|caserío|nucleo|núcleo|urbanizacion|urbanización)\s+(de|del|de la|d'|n\.?\s*)\s+", "", nombre, flags=re.I)
    nombre = re.sub(r"^(distrito|barrio|barriada|pedania|pedanía|localidad|aldea|caserio|caserío|nucleo|núcleo|urbanizacion|urbanización)\s+", "", nombre, flags=re.I)
    nombre = re.sub(r"\s*\([^)]*\)\s*$", "", nombre).strip()
    if ciudad_nombre:
        nombre = re.sub(rf"\s+de\s+{re.escape(ciudad_nombre)}$", "", nombre, flags=re.I).strip()
    if tipo == "distrito":
        nombre = re.sub(r"^distrito\s+", "", nombre, flags=re.I).strip()
    return nombre.strip(" -–—:;,.")


def _slug(texto: str) -> str:
    limpio = _normalizar_texto(texto)
    limpio = re.sub(r"[^a-z0-9]+", "-", limpio)
    return limpio.strip("-")


def _parse_int(texto: str) -> int | None:
    limpio = re.sub(r"[^\d]", "", texto or "")
    if not limpio:
        return None
    try:
        return int(limpio)
    except ValueError:
        return None


def _es_url_wiki_valida(href: str) -> bool:
    if not href:
        return False
    if href.startswith("#") or href.startswith("/wiki/Archivo:"):
        return False
    if href.startswith("/wiki/") and ":" in href.replace("/wiki/Categor%C3%ADa:", "").replace("/wiki/Categoría:", ""):
        return href.startswith(("/wiki/Categor%C3%ADa:", "/wiki/Categoría:", "/wiki/Anexo:"))
    return href.startswith(("/wiki/", "https://es.wikipedia.org/wiki/"))


def _es_categoria(url: str) -> bool:
    return "Categor%C3%ADa:" in url or "Categoría:" in url


def _es_anexo(url: str) -> bool:
    return "/wiki/Anexo:" in url


def _parece_falso_positivo(nombre: str, href: str = "") -> bool:
    texto = _normalizar_texto(f"{nombre} {href}")
    if not nombre or len(nombre) < 3:
        return True
    if texto.startswith(("distritos de", "barrios de", "anexo barrios", "anexo distritos")):
        return True
    if any(palabra in texto for palabra in FALSE_POSITIVE_WORDS):
        return True
    if texto.startswith(("lista de", "anexo de", "historia de")):
        return True
    return False


def _inferir_tipo_desde_texto(texto: str, href: str, tipo_preferido: str | None = None) -> str | None:
    normalizado = _normalizar_texto(f"{texto} {href}")
    if any(
        palabra in normalizado
        for palabra in (
            "pedania",
            "pedanias",
            "localidad",
            "localidades",
            "aldea",
            "caserio",
            "nucleo de poblacion",
            "nucleo poblacional",
            "entidad singular",
            "entidad local menor",
            "entidad menor",
            "eatim",
            "junta vecinal",
            "parroquia",
            "diputacion",
            "urbanizacion",
            "poblado",
            "anejo",
            "agregado",
        )
    ):
        return "pedania"
    if "barrios" in normalizado or "barrio" in normalizado or "barriada" in normalizado:
        return "barrio"
    if "distritos" in normalizado or "distrito" in normalizado:
        return "distrito"
    return tipo_preferido


def _make_candidate(
    nombre: str,
    article_url: str | None,
    tipo: str,
    ciudad_nombre: str,
    source: str,
    evidencia: str,
    parent_nombre: str | None = None,
    confianza: float = 0.75,
    population_hint: int | None = None,
    source_url: str | None = None,
) -> Candidate | None:
    nombre_limpio = _limpiar_nombre(nombre, tipo, ciudad_nombre)
    article_url = article_url or ""
    if not source.startswith("table") and _parece_falso_positivo(nombre_limpio, article_url):
        return None
    if not nombre_limpio or len(nombre_limpio) < 3:
        return None
    return {
        "nombre": nombre_limpio,
        "tipo": tipo,
        "article_url": article_url,
        "parent_nombre": parent_nombre,
        "source": source,
        "source_url": source_url or article_url,
        "evidencia": evidencia[:500],
        "confianza": confianza,
        "population_hint": population_hint,
        "categoria": _es_categoria(article_url),
        "anexo": _es_anexo(article_url),
    }


def _dedupe_candidates(candidatos: list[Candidate]) -> list[Candidate]:
    resultado: list[Candidate] = []
    vistos = set()

    def sort_key(candidato: Candidate) -> tuple[int, int, int]:
        es_pagina = not candidato.get("categoria") and not candidato.get("anexo")
        tiene_poblacion = 0 if candidato.get("population_hint") is not None else 1
        return (tiene_poblacion, 0 if es_pagina else 1, -int(float(candidato.get("confianza") or 0) * 100))

    for candidato in sorted(candidatos, key=sort_key):
        url = str(candidato.get("article_url") or "")
        parent = _slug(str(candidato.get("parent_nombre") or ""))
        clave = url or f"{candidato.get('tipo')}:{parent}:{_slug(str(candidato.get('nombre') or ''))}"
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(candidato)

    return resultado


def _links_de_contenido(soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    _clean_soup_for_extraction(soup)
    content = soup.find(id="mw-content-text") or soup
    links = []
    for a in content.find_all("a", href=True):
        href = a.get("href", "").strip()
        texto = a.get_text(" ", strip=True)
        if texto and _es_url_wiki_valida(href):
            links.append((texto, href, str(a.parent.get_text(" ", strip=True))[:500]))
    return links


def _buscar_paginas_auxiliares(html: str, lugar: dict) -> list[str]:
    """
    Localiza paginas fuente como "Distritos de X", "Organizacion politico-
    administrativa de X", anexos o categorias de barrios/distritos.
    """
    soup = get_soup(html)
    ciudad = _normalizar_texto(str(lugar.get("nombre") or ""))
    urls: list[str] = []
    vistos = set()

    for texto, href, contexto in _links_de_contenido(soup):
        combinado = _normalizar_texto(f"{texto} {href} {contexto}")
        es_fuente = (
            "distritos de" in combinado
            or "barrios de" in combinado
            or "pedanias de" in combinado
            or "pedania de" in combinado
            or "localidades de" in combinado
            or "nucleos de poblacion" in combinado
            or "organizacion politico-administrativa" in combinado
            or "organizacion politica-administrativa" in combinado
            or "organizacion territorial" in combinado
            or "division administrativa" in combinado
        )
        if not es_fuente:
            continue
        if ciudad and ciudad not in combinado and "organizacion" not in combinado:
            continue
        url = urljoin(BASE_WIKI_URL, href)
        if url not in vistos:
            vistos.add(url)
            urls.append(url)

    return urls


def _resumen_estructura_pagina(html: str) -> str:
    soup = get_soup(html)
    _clean_soup_for_extraction(soup)
    content = soup.find(id="mw-content-text") or soup
    bloques: list[str] = []

    headings = []
    for heading in content.find_all(["h2", "h3", "h4"], limit=40):
        titulo = heading.get_text(" ", strip=True)
        if titulo:
            headings.append(f"- {titulo}")
    if headings:
        bloques.append("SECCIONES:\n" + "\n".join(headings))

    tablas = []
    for idx, table in enumerate(content.find_all("table", limit=12), start=1):
        rows = table.find_all("tr", limit=4)
        textos = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            row_text = " | ".join(c.get_text(" ", strip=True) for c in cells)
            if row_text:
                textos.append(row_text[:500])
        if textos:
            tablas.append(f"TABLA {idx}:\n" + "\n".join(textos))
    if tablas:
        bloques.append("TABLAS:\n" + "\n\n".join(tablas))

    enlaces = []
    for texto, href, contexto in _links_de_contenido(soup):
        combinado = _normalizar_texto(f"{texto} {href} {contexto}")
        if any(
            p in combinado
            for p in (
                "distrito",
                "distritos",
                "barrio",
                "barrios",
                "pedania",
                "pedanias",
                "localidad",
                "localidades",
                "nucleo",
                "nucleos",
                "entidad",
                "urbanizacion",
                "organizacion",
                "division",
            )
        ):
            enlaces.append(f"- {texto}: {urljoin(BASE_WIKI_URL, href)} | {contexto[:220]}")
        if len(enlaces) >= 80:
            break
    if enlaces:
        bloques.append("ENLACES RELEVANTES:\n" + "\n".join(enlaces))

    resumen = "\n\n".join(bloques).strip()
    if contar_tokens(resumen) > MAX_SNIPPET_TOKENS:
        resumen = " ".join(resumen.split()[:MAX_SNIPPET_TOKENS])
    return resumen


def _normalizar_url_wiki(url: object) -> str:
    url_text = str(url or "").strip()
    if not url_text:
        return ""
    if not _es_url_wiki_valida(url_text):
        return ""
    return urljoin(BASE_WIKI_URL, url_text)


def analizar_ruta_extraccion_llm(
    html: str,
    lugar: dict,
    tipo_preferido: str,
    contexto: str,
) -> dict:
    """
    Pide al LLM que lea la estructura de la pagina y elija el camino correcto
    hacia distritos/barrios/pedanias antes de lanzar extractores masivos.
    """
    resumen = _resumen_estructura_pagina(html)
    if not resumen:
        return {"usar_pagina_actual": False, "urls_fuente": [], "motivo": "sin resumen", "_llm_ok": False}

    system_prompt = (
        "Eres un analista de paginas de Wikipedia para extraer geografia urbana. "
        "Tu tarea es decidir por donde extraer distritos, barrios o pedanias de la pagina dada, "
        "sin inventar fuentes. Responde SOLO JSON valido con: "
        "{\"usar_pagina_actual\": bool, \"urls_fuente\": [str], "
        "\"secciones_relevantes\": [str], \"tablas_relevantes\": [int], "
        "\"confianza\": number, \"motivo\": str}."
    )
    api_opciones = buscar_titulos_relacionados_api(lugar.get("nombre"))
    api_opciones_str = "\n".join([f"- {url}" for url in api_opciones]) if api_opciones else "Ninguna adicional."

    user_prompt = (
        f"Lugar: {lugar.get('nombre')}\n"
        f"Tipo del lugar: {lugar.get('tipo')}\n"
        f"Tipo que buscamos: {tipo_preferido}\n"
        f"Contexto: {contexto}\n\n"
        "Reglas:\n"
        "- Indica usar_pagina_actual=true solo si la propia pagina contiene secciones/tablas/listas utiles del tipo buscado.\n"
        "- urls_fuente debe incluir solo URLs de Wikipedia que parezcan fuentes directas para ese mismo lugar: anexos, categorias, paginas de barrios/distritos/pedanias/localidades u organizacion territorial.\n"
        "- Si alguna de las 'Opciones adicionales descubiertas via API de Wikipedia' parece ser el listado exacto que buscas (como un 'Anexo:...' o 'Categoría:...'), INCLÚYELA en urls_fuente obligatoriamente, incluso si no estaba en el resumen.\n"
        "- No incluyas enlaces a candidatos individuales salvo que la pagina sea claramente una fuente de listado.\n"
        "- Si una fuente parece de otra ciudad o de otro tema, no la incluyas.\n"
        "- Si no hay camino claro, deja urls_fuente vacio y explica el motivo.\n\n"
        f"Opciones adicionales descubiertas via API de Wikipedia:\n{api_opciones_str}\n\n"
        f"Estructura de la pagina:\n{resumen}"
    )

    resp = call_llm(
        system_prompt,
        user_prompt,
        context_info={
            "stage": "fase2_ruta_extraccion",
            "lugar": lugar.get("nombre"),
            "tipo": tipo_preferido,
            "contexto": contexto,
        },
    )
    if not resp:
        log_error(
            "LLM sin respuesta analizando ruta de extraccion",
            context={"lugar": lugar.get("nombre"), "tipo": tipo_preferido},
        )
        return {"usar_pagina_actual": False, "urls_fuente": [], "motivo": "sin respuesta LLM", "_llm_ok": False}

    try:
        data = json.loads(resp)
    except (json.JSONDecodeError, TypeError):
        log_error("Respuesta LLM invalida analizando ruta de extraccion", context={"response": resp[:500]})
        return {"usar_pagina_actual": False, "urls_fuente": [], "motivo": "respuesta invalida", "_llm_ok": False}

    if not isinstance(data, dict):
        return {"usar_pagina_actual": False, "urls_fuente": [], "motivo": "respuesta no objeto", "_llm_ok": False}

    urls = []
    for raw_url in data.get("urls_fuente") or []:
        url = _normalizar_url_wiki(raw_url)
        if url and url not in urls:
            import urllib.parse
            url_unquoted = urllib.parse.unquote(url)
            title_part = url_unquoted.split("/wiki/")[-1].replace("_", " ")
            title_part_quoted = url.split("/wiki/")[-1]
            
            es_valida = (
                (api_opciones and url in api_opciones)
                or (title_part in resumen)
                or (title_part_quoted in resumen)
                or (url in resumen)
                or (url_unquoted in resumen)
            )
            
            if es_valida:
                urls.append(url)
            else:
                print(f"   - [ALERTA] LLM alucinó la URL: {url} (descartada)")

    # Forzar la inclusión de las opciones de la API siempre para no depender del capricho del LLM
    if api_opciones:
        for api_url in api_opciones:
            if api_url not in urls:
                urls.append(api_url)

    return {
        "usar_pagina_actual": data.get("usar_pagina_actual") is not False,
        "urls_fuente": urls,
        "secciones_relevantes": data.get("secciones_relevantes") if isinstance(data.get("secciones_relevantes"), list) else [],
        "tablas_relevantes": data.get("tablas_relevantes") if isinstance(data.get("tablas_relevantes"), list) else [],
        "confianza": _parse_float(data.get("confianza")),
        "motivo": str(data.get("motivo") or "").strip(),
        "_llm_ok": True,
    }


def _ruta_tiene_camino(estrategia: dict) -> bool:
    return bool(
        estrategia.get("_llm_ok")
        and (
            estrategia.get("usar_pagina_actual")
            or estrategia.get("urls_fuente")
        )
    )


def _paginas_auxiliares_guiadas(html: str, lugar: dict, estrategia: dict) -> list[str]:
    urls_llm = [str(url) for url in estrategia.get("urls_fuente") or [] if url]
    if urls_llm:
        return urls_llm
    return []


def _extraer_enlaces_de_celda(cell) -> list[tuple[str, str]]:
    enlaces = []
    for a in cell.find_all("a", href=True):
        texto = a.get_text(" ", strip=True)
        href = a.get("href", "").strip()
        if texto and _es_url_wiki_valida(href):
            enlaces.append((texto, urljoin(BASE_WIKI_URL, href)))
    return enlaces


def _dividir_nombres_barrios(texto: str) -> list[str]:
    texto = re.sub(r"\[\d+\]", "", texto or "")
    texto = re.sub(r"\([^)]*\)", "", texto)
    partes = re.split(r",|;|\n|\s+y\s+", texto)
    nombres = []
    for parte in partes:
        nombre = re.sub(r"^\d+\s*[:.-]\s*", "", parte.strip()).strip(" -–—:;.")
        if nombre:
            nombres.append(nombre)
    return nombres


def _separar_nombre_y_poblacion(texto: str) -> tuple[str, int | None]:
    texto = re.sub(r"\[\d+\]", "", texto or "").strip()
    poblacion = _parse_int(texto)
    nombre = re.sub(r"\b\d[\d\s.,]*\b", "", texto)
    nombre = re.sub(r"\bhab\.?\b|\bhabitantes\b|\bpoblacion\b", "", nombre, flags=re.I)
    nombre = re.sub(r"\s+", " ", nombre).strip(" -–—:;,.")
    return nombre or texto, poblacion


def _extraer_candidatos_de_tablas(
    html: str,
    ciudad_nombre: str,
    source_url: str,
    tipo_preferido: str | None = None,
) -> list[Candidate]:
    """
    Parseo orientado a tablas tipo:
    - Distrito | Poblacion | Barrios
    - Distrito | Barrios y pedanias
    - Distrito | ... | Nombre barrio | Poblacion barrio
    """
    soup = get_soup(html)
    _clean_soup_for_extraction(soup)
    candidatos: list[Candidate] = []

    for table in soup.select("#mw-content-text table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        headers = [
            _normalizar_texto(th.get_text(" ", strip=True))
            for th in rows[0].find_all(["th", "td"])
        ]
        tabla_texto = _normalizar_texto(table.get_text(" ", strip=True)[:1200])
        if tipo_preferido == "pedania":
            if not any(
                p in tabla_texto
                for p in (
                    "pedania",
                    "localidad",
                    "aldea",
                    "caserio",
                    "nucleo",
                    "entidad",
                    "eatim",
                    "parroquia",
                    "diputacion",
                    "urbanizacion",
                    "poblado",
                    "anejo",
                    "agregado",
                    "habitantes",
                    "poblacion",
                )
            ):
                continue

            name_idx = next(
                (
                    i
                    for i, h in enumerate(headers)
                    if any(
                        p in h
                        for p in (
                            "pedania",
                            "localidad",
                            "aldea",
                            "caserio",
                            "nucleo",
                            "entidad",
                            "parroquia",
                            "diputacion",
                            "urbanizacion",
                            "poblado",
                            "anejo",
                            "agregado",
                            "nombre",
                        )
                    )
                ),
                0,
            )
            poblacion_idx = next(
                (
                    i
                    for i, h in enumerate(headers)
                    if "poblacion" in h or "habitantes" in h
                ),
                None,
            )

            for row in rows[1:]:
                cells = row.find_all(["th", "td"])
                if not cells or name_idx >= len(cells):
                    continue
                texts = [c.get_text(" ", strip=True) for c in cells]
                row_text = " | ".join(texts)
                population_hint = None
                if poblacion_idx is not None and poblacion_idx < len(cells):
                    population_hint = _parse_int(texts[poblacion_idx])
                enlaces = _extraer_enlaces_de_celda(cells[name_idx])
                if enlaces:
                    for nombre_pedania, pedania_url in enlaces:
                        candidato = _make_candidate(
                            nombre=nombre_pedania,
                            article_url=pedania_url,
                            tipo="pedania",
                            ciudad_nombre=ciudad_nombre,
                            source="table_link",
                            evidencia=row_text,
                            confianza=0.9,
                            population_hint=population_hint,
                            source_url=source_url,
                        )
                        if candidato:
                            candidatos.append(candidato)
                else:
                    nombre_pedania, poblacion_en_nombre = _separar_nombre_y_poblacion(texts[name_idx])
                    candidato = _make_candidate(
                        nombre=nombre_pedania,
                        article_url=None,
                        tipo="pedania",
                        ciudad_nombre=ciudad_nombre,
                        source="table_text",
                        evidencia=row_text,
                        confianza=0.75,
                        population_hint=population_hint or poblacion_en_nombre,
                        source_url=source_url,
                    )
                    if candidato:
                        candidatos.append(candidato)
            continue

        if not any(p in tabla_texto for p in ("distrito", "barrios", "barrio")):
            continue

        current_district_name: str | None = None
        current_district_url: str | None = None
        current_district_population: int | None = None

        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue

            texts = [c.get_text(" ", strip=True) for c in cells]
            norm_texts = [_normalizar_texto(t) for t in texts]
            row_text = " | ".join(texts)

            distrito_idx = next(
                (
                    i
                    for i, h in enumerate(headers)
                    if i < len(cells) and ("distrito" in h or h in ("nombre", "district"))
                ),
                None,
            )
            barrios_idx = next((i for i, h in enumerate(headers) if i < len(cells) and "barrio" in h), None)
            poblacion_idx = next(
                (
                    i
                    for i, h in enumerate(headers)
                    if i < len(cells) and ("poblacion" in h or "habitantes" in h)
                ),
                None,
            )

            if distrito_idx is None and len(cells) >= 3 and "distrito" in tabla_texto:
                distrito_idx = 0
            if barrios_idx is None:
                barrios_idx = next((i for i, t in enumerate(norm_texts) if "barrio" in t and i != distrito_idx), None)
                if barrios_idx is None and len(cells) >= 3:
                    barrios_idx = len(cells) - 1

            if distrito_idx is not None and distrito_idx < len(cells):
                distrito_text = texts[distrito_idx]
                enlaces_distrito = _extraer_enlaces_de_celda(cells[distrito_idx])
                if distrito_text and not re.fullmatch(r"\d+", distrito_text.strip()):
                    current_district_name, poblacion_en_nombre = _separar_nombre_y_poblacion(distrito_text)
                    current_district_url = enlaces_distrito[0][1] if enlaces_distrito else None
                    current_district_population = poblacion_en_nombre
                    if poblacion_idx is not None and poblacion_idx < len(cells):
                        current_district_population = _parse_int(texts[poblacion_idx]) or current_district_population
                    if tipo_preferido in (None, "distrito"):
                        candidato = _make_candidate(
                            nombre=current_district_name,
                            article_url=current_district_url,
                            tipo="distrito",
                            ciudad_nombre=ciudad_nombre,
                            source="table",
                            evidencia=row_text,
                            confianza=0.95,
                            population_hint=current_district_population,
                            source_url=source_url,
                        )
                        if candidato:
                            candidatos.append(candidato)

            if tipo_preferido not in (None, "barrio") or barrios_idx is None or barrios_idx >= len(cells):
                continue

            barrio_cell = cells[barrios_idx]
            barrio_population_hint = None
            if re.fullmatch(r"\d+", barrio_cell.get_text(" ", strip=True)) and barrios_idx + 1 < len(cells):
                barrio_cell = cells[barrios_idx + 1]
                if barrios_idx + 2 < len(cells):
                    barrio_population_hint = _parse_int(cells[barrios_idx + 2].get_text(" ", strip=True))

            enlaces_barrio = _extraer_enlaces_de_celda(barrio_cell)
            if enlaces_barrio:
                for barrio_nombre, barrio_url in enlaces_barrio:
                    candidato = _make_candidate(
                        nombre=barrio_nombre,
                        article_url=barrio_url,
                        tipo="barrio",
                        ciudad_nombre=ciudad_nombre,
                        source="table_link",
                        evidencia=row_text,
                        parent_nombre=current_district_name,
                        confianza=0.95,
                        population_hint=barrio_population_hint,
                        source_url=source_url,
                    )
                    if candidato:
                        candidatos.append(candidato)
            else:
                for barrio_nombre in _dividir_nombres_barrios(barrio_cell.get_text("\n", strip=True)):
                    candidato = _make_candidate(
                        nombre=barrio_nombre,
                        article_url=None,
                        tipo="barrio",
                        ciudad_nombre=ciudad_nombre,
                        source="table_text",
                        evidencia=row_text,
                        parent_nombre=current_district_name,
                        confianza=0.8,
                        population_hint=barrio_population_hint,
                        source_url=source_url,
                    )
                    if candidato:
                        candidatos.append(candidato)

    return candidatos


def _extraer_candidatos_por_enlaces(
    html: str,
    ciudad_nombre: str,
    tipo_preferido: str | None = None,
    parent_nombre: str | None = None,
) -> list[Candidate]:
    soup = get_soup(html)
    _clean_soup_for_extraction(soup)
    candidatos: list[Candidate] = []

    for texto, href, contexto in _links_de_contenido(soup):
        # SOLO inferir tipo desde el texto del enlace y su href.
        # El contexto genera miles de falsos positivos si un párrafo menciona la palabra 'barrio'.
        tipo = _inferir_tipo_desde_texto(texto, href, tipo_preferido)
        if tipo not in ("distrito", "barrio", "pedania"):
            continue
        if tipo_preferido and tipo != tipo_preferido:
            continue

        url = urljoin(BASE_WIKI_URL, href)
        candidato = _make_candidate(
            nombre=texto,
            article_url=url,
            tipo=tipo,
            ciudad_nombre=ciudad_nombre,
            source="link",
            evidencia=contexto,
            parent_nombre=parent_nombre,
            confianza=0.7,
        )
        if candidato:
            candidatos.append(candidato)

    return candidatos


def _extraer_candidatos_de_secciones(
    html: str,
    ciudad_nombre: str,
    tipo_preferido: str | None = None,
    parent_nombre: str | None = None,
) -> list[Candidate]:
    soup = get_soup(html)
    _clean_soup_for_extraction(soup)
    content = soup.find(id="mw-content-text")
    if not content:
        return []

    candidatos: list[Candidate] = []
    for heading in content.find_all(["h2", "h3", "h4"]):
        titulo = heading.get_text(" ", strip=True)
        titulo_norm = _normalizar_texto(titulo)
        if not any(palabra in titulo_norm for palabra in RELEVANT_SECTION_WORDS):
            continue

        for sibling in heading.find_next_siblings():
            if sibling.name in ("h2", "h3") and sibling.name <= heading.name:
                break
            if sibling.name not in ("p", "ul", "ol", "table", "div"):
                continue
            for a in sibling.find_all("a", href=True):
                texto = a.get_text(" ", strip=True)
                href = a.get("href", "").strip()
                tipo = _inferir_tipo_desde_texto(f"{titulo} {texto}", href, tipo_preferido)
                if tipo not in ("distrito", "barrio", "pedania"):
                    continue
                if tipo_preferido and tipo != tipo_preferido:
                    continue
                candidato = _make_candidate(
                    nombre=texto,
                    article_url=urljoin(BASE_WIKI_URL, href),
                    tipo=tipo,
                    ciudad_nombre=ciudad_nombre,
                    source="section",
                    evidencia=f"{titulo}: {sibling.get_text(' ', strip=True)[:450]}",
                    parent_nombre=parent_nombre,
                    confianza=0.85,
                )
                if candidato:
                    candidatos.append(candidato)

    return candidatos


def _extraer_desde_categoria_o_anexo(
    url: str,
    tipo: str,
    ciudad_nombre: str,
    parent_nombre: str | None = None,
) -> list[Candidate]:
    html = fetch_url(url)
    if not html:
        return []

    soup = get_soup(html)
    candidatos: list[Candidate] = []
    selector = ".mw-category-group a" if _es_categoria(url) else "#mw-content-text a"

    # Inferir el tipo real de la URL, ignorando el preferido de la fase actual
    url_lower = _normalizar_texto(url)
    tipo_real = tipo
    if "barrio" in url_lower:
        tipo_real = "barrio"
    elif "distrito" in url_lower:
        tipo_real = "distrito"
    elif "pedania" in url_lower or "localidad" in url_lower:
        tipo_real = "pedania"

    # Si es un anexo, extraer también de tablas para capturar población
    if _es_anexo(url):
        cands_tabla = _extraer_candidatos_de_tablas(html, ciudad_nombre, url, tipo_real)
        for c in cands_tabla:
            c["confianza"] = 1.0 # Confianza máxima ya que proviene del Anexo oficial
            c["source"] = "annex_table"
            c["tipo"] = tipo_real
            candidatos.append(c)

    for a in soup.select(selector):
        texto = a.get_text(" ", strip=True)
        href = a.get("href", "").strip()
        if not texto or not _es_url_wiki_valida(href):
            continue
        if _es_categoria(url) and _es_categoria(href):
            continue
            
        # Si es un anexo genérico, aplicamos filtros de texto. Si es Categoría oficial, es 100% de ese tipo.
        if not _es_categoria(url):
            texto_inf = _inferir_tipo_desde_texto(texto, href, None)
            if texto_inf and texto_inf != tipo_real:
                continue # Evitar extraer edificios o monumentos de Anexos ruidosos
                
        candidato = _make_candidate(
            nombre=texto,
            article_url=urljoin(BASE_WIKI_URL, href),
            tipo=tipo_real,
            ciudad_nombre=ciudad_nombre,
            source="category" if _es_categoria(url) else "annex",
            evidencia=f"Extraido desde {url}",
            parent_nombre=parent_nombre,
            confianza=1.0 if _es_categoria(url) else 0.9,
        )
        if candidato:
            candidatos.append(candidato)

    candidatos.extend(_extraer_candidatos_de_tablas(html, ciudad_nombre, source_url=url, tipo_preferido=tipo))
    time.sleep(DELAY_BETWEEN_REQUESTS)
    return candidatos


def _snippet_para_llm(html: str) -> str:
    soup = get_soup(html)
    content = soup.find(id="mw-content-text")
    if not content:
        return ""

    bloques = []
    for heading in content.find_all(["h2", "h3", "h4"]):
        titulo = heading.get_text(" ", strip=True)
        titulo_norm = _normalizar_texto(titulo)
        if not any(palabra in titulo_norm for palabra in RELEVANT_SECTION_WORDS):
            continue

        lineas = [f"SECCION: {titulo}"]
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h2", "h3") and sibling.name <= heading.name:
                break
            if sibling.name in ("p", "ul", "ol", "table"):
                texto = sibling.get_text(" ", strip=True)
                if texto:
                    lineas.append(texto)
            if len(" ".join(lineas).split()) > 800:
                break
        bloques.append("\n".join(lineas))

    if not bloques:
        enlaces = [
            f"- {texto}: {urljoin(BASE_WIKI_URL, href)}"
            for texto, href, _ in _links_de_contenido(soup)[:80]
            if any(
                p in _normalizar_texto(f"{texto} {href}")
                for p in (
                    "distrito",
                    "barrio",
                    "barrios",
                    "pedania",
                    "pedanias",
                    "localidad",
                    "localidades",
                    "nucleo",
                    "nucleos",
                    "entidad",
                    "urbanizacion",
                )
            )
        ]
        bloques.append("ENLACES RELEVANTES:\n" + "\n".join(enlaces))

    snippet = "\n\n".join(bloques)
    if contar_tokens(snippet) > MAX_SNIPPET_TOKENS:
        snippet = " ".join(snippet.split()[:MAX_SNIPPET_TOKENS])
    return snippet


def _contexto_articulo_para_verificacion(html: str) -> str:
    soup = get_soup(html)
    content = soup.find(id="mw-content-text") or soup
    partes: list[str] = []

    infobox = soup.find("table", class_="infobox")
    if infobox:
        partes.append("INFOBOX:\n" + infobox.get_text(" ", strip=True)[:2500])

    if content:
        parrafos = [
            p.get_text(" ", strip=True)
            for p in content.find_all("p", limit=3)
            if p.get_text(strip=True)
        ]
        
        variantes_oficial = ["nombre oficial", "oficialmente llamado", "denominación oficial", "denominacion oficial", "oficialmente"]
        for elem in content.find_all(["p", "li", "td"]):
            txt = elem.get_text(" ", strip=True)
            txt_lower = _normalizar_texto(txt)
            if any(var in txt_lower for var in variantes_oficial) and txt not in parrafos:
                parrafos.append("Mención oficial: " + txt[:500])
                if len(parrafos) >= 8:
                    break

        if parrafos:
            partes.append("PRIMEROS PARRAFOS Y CONTEXTO OFICIAL:\n" + "\n".join(parrafos))

    contexto = "\n\n".join(partes).strip()
    if contar_tokens(contexto) > MAX_SNIPPET_TOKENS:
        contexto = " ".join(contexto.split()[:MAX_SNIPPET_TOKENS])
    return contexto



def _contexto_fuente_para_verificacion(html: str, candidato: Candidate) -> str:
    snippet = _snippet_para_llm(html)
    evidencia = str(candidato.get("evidencia") or "").strip()
    if evidencia:
        snippet = f"EVIDENCIA DEL CANDIDATO:\n{evidencia}\n\nFUENTE:\n{snippet}"
    if contar_tokens(snippet) > MAX_SNIPPET_TOKENS:
        snippet = " ".join(snippet.split()[:MAX_SNIPPET_TOKENS])
    return snippet


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nombre_normalizado_seguro(nombre_actual: str, nombre_llm: object) -> str:
    nombre_nuevo = str(nombre_llm or "").strip()
    if not nombre_nuevo:
        return nombre_actual

    actual_slug = _slug(nombre_actual)
    nuevo_slug = _slug(nombre_nuevo)
    if not actual_slug or not nuevo_slug:
        return nombre_actual
    if actual_slug == nuevo_slug or actual_slug in nuevo_slug or nuevo_slug in actual_slug:
        return nombre_nuevo
    return nombre_actual


def verificar_candidato_llm(
    candidato: Candidate,
    padre: dict,
    ciudad: dict,
    html_articulo: str | None = None,
    html_fuente: str | None = None,
) -> tuple[bool, dict, str]:
    """
    Verificacion estricta con LM Studio antes de anadir distritos/barrios/pedanias.
    Si no hay confirmacion clara del LLM, el candidato se descarta.
    """
    tipo = str(candidato.get("tipo") or "").strip()
    nombre = str(candidato.get("nombre") or "").strip()
    if tipo not in ("distrito", "barrio", "pedania") or not nombre:
        return False, {}, "descartado por LLM invalido"

    is_trusted = candidato.get("confianza", 0.0) >= 1.0
    population_hint = candidato.get("population_hint")

    if is_trusted and population_hint is not None:
        # Instant return without LLM!
        return True, {
            "aceptar": True,
            "tipo_confirmado": tipo,
            "nombre_normalizado": nombre,
            "parent_nombre": padre.get("nombre"),
            "poblacion": population_hint,
            "confianza": 1.0,
            "motivo": "Confiable con poblacion pre-extraida"
        }, "confianza 1.0 y poblacion conocida"

    contexto_html = ""
    contexto_origen = ""
    if html_articulo:
        contexto_html = _contexto_articulo_para_verificacion(html_articulo)
        contexto_origen = "articulo propio"
    elif html_fuente:
        contexto_html = _contexto_fuente_para_verificacion(html_fuente, candidato)
        contexto_origen = "fuente/listado"
    
    is_trusted = candidato.get("confianza", 0.0) >= 1.0

    if is_trusted:
        system_prompt = (
            "Eres un extractor rapido de datos poblacionales. "
            "El lugar ya esta confirmado, SOLO necesitas extraer su poblacion si aparece en el texto. "
            "Responde SOLO JSON valido con: "
            "{\"aceptar\": true, \"tipo_confirmado\": \"" + tipo + "\", "
            "\"nombre_normalizado\": \"" + nombre + "\", \"parent_nombre\": null, "
            "\"poblacion\": int|null, \"confianza\": 1.0, \"motivo\": \"Confiable\"}."
        )
    else:
        system_prompt = (
            "Eres un verificador estricto de geografia urbana espanola usando solo la "
            "evidencia dada. Debes decidir si un candidato es realmente un distrito, "
            "barrio o pedania/localidad externa del municipio indicado. Responde SOLO JSON valido con: "
            "{\"aceptar\": bool, \"tipo_confirmado\": \"distrito\"|\"barrio\"|\"pedania\"|null, "
            "\"nombre_normalizado\": str|null, \"parent_nombre\": str|null, "
            "\"poblacion\": int|null, \"confianza\": number, \"motivo\": str}."
        )

    user_prompt = (
        f"Ciudad esperada: {ciudad.get('nombre')}\n"
        f"Provincia esperada: {ciudad.get('provincia')}\n"
        f"Padre esperado: {padre.get('nombre')} ({padre.get('tipo')})\n"
        f"Tipo esperado: {tipo}\n"
        f"Nombre candidato: {nombre}\n"
        f"URL candidato: {candidato.get('article_url') or ''}\n"
        f"URL fuente: {candidato.get('source_url') or ''}\n"
        f"Origen de contexto: {contexto_origen}\n"
        f"Evidencia previa: {candidato.get('evidencia') or ''}\n\n"
    )

    if is_trusted:
        user_prompt += "Evalua y extrae solo la poblacion basandote en el contexto. Aceptalo siempre.\n"
    else:
        user_prompt += (
            "Reglas estrictas:\n"
            "- Acepta solo si la evidencia confirma que pertenece a la ciudad/padre esperado.\n"
            "- El tipo_confirmado debe coincidir con el tipo esperado.\n"
            "- Excluye calles, avenidas, playas naturales, plazas, monumentos, estaciones, parques, comarcas, provincias y lugares de otra ciudad.\n"
            "- Excluye instituciones, instalaciones deportivas, hospitales, colegios, oficinas, empresas, edificios y poligonos industriales (salvo que sea el nombre historico de un barrio residencial).\n"
            "- Para barrios, rechaza pedanias, pueblos, localidades externas o nucleos separados del casco urbano.\n"
            "- Para distritos, acepta solo divisiones administrativas/territoriales urbanas de la ciudad.\n"
            "- Para pedanias, acepta localidades, pueblos, aldeas, caserios, nucleos, entidades menores, parroquias, diputaciones, urbanizaciones o poblados separados fisicamente pero pertenecientes al municipio.\n"
            "- Para pedanias, rechaza barrios/distritos internos del continuo urbano.\n"
            "- Si no hay evidencia suficiente, rechaza (aceptar: false).\n\n"
        )
    
    user_prompt += f"=== CONTEXTO EXTRAIDO ===\n{contexto_html}\n=========================\n"

    resp = call_llm(
        system_prompt,
        user_prompt,
        context_info={
            "stage": "fase2_verificacion",
            "lugar": ciudad.get("nombre"),
            "padre": padre.get("nombre"),
            "candidato": nombre,
            "tipo": tipo,
        },
    )
    if not resp:
        log_error("LLM sin respuesta verificando candidato", context={"candidato": nombre, "tipo": tipo})
        return False, {}, "descartado por LLM sin respuesta"

    try:
        data = json.loads(resp)
    except (json.JSONDecodeError, TypeError):
        log_error("Respuesta LLM invalida verificando candidato", context={"response": resp[:500]})
        return False, {}, "descartado por LLM invalido"

    if not isinstance(data, dict):
        return False, {}, "descartado por LLM invalido"

    motivo = str(data.get("motivo") or "sin motivo").strip()
    tipo_confirmado = data.get("tipo_confirmado")
    confianza = _parse_float(data.get("confianza"))
    if data.get("aceptar") is not True:
        return False, data, f"descartado por LLM: {motivo}"
    if tipo_confirmado != tipo:
        return False, data, f"descartado por LLM: tipo {tipo_confirmado or 'desconocido'}"
    if confianza and confianza < 0.55:
        return False, data, f"descartado por LLM: baja confianza ({confianza:.2f})"

    return True, data, "OK (verificado LLM)"


def _extraer_candidatos_llm(
    html: str,
    lugar_padre: dict,
    tipo_preferido: str | None,
    contexto: str,
) -> list[Candidate]:
    snippet = _snippet_para_llm(html)
    if not snippet:
        return []

    system_prompt = (
        "Extrae candidatos de distritos, barrios y pedanias desde texto de Wikipedia. "
        "No inventes lugares ni poblacion. Responde SOLO JSON valido con una "
        "lista: [{\"nombre\": str, \"tipo\": \"distrito\"|\"barrio\"|\"pedania\", "
        "\"article_url\": str|null, \"parent_nombre\": str|null, "
        "\"population_hint\": int|null, \"evidencia\": str, \"confianza\": number}]."
    )
    user_prompt = (
        f"Municipio o padre: {lugar_padre.get('nombre')}\n"
        f"Tipo buscado: {tipo_preferido or 'distrito, barrio o pedania'}\n"
        f"Contexto: {contexto}\n"
        "Reglas:\n"
        "- Devuelve solo distritos/barrios internos o pedanias/localidades externas pertenecientes al municipio o padre indicado.\n"
        "- Excluye monumentos, calles, plazas, estaciones, comarcas, provincias y lugares de otro municipio.\n"
        "- Excluye instituciones, instalaciones deportivas, hospitales, oficinas, empresas, playas, colegios y edificios comerciales.\n"
        "- Si tipo buscado es pedania, acepta localidades, pueblos, aldeas, caserios, nucleos, entidades menores, parroquias, diputaciones, urbanizaciones, poblados, anejos o agregados del municipio.\n"
        "- Si tipo buscado es pedania, rechaza barrios/distritos urbanos.\n"
        "- Si falta URL, usa null; no inventes URLs.\n\n"
        f"Texto:\n{snippet}"
    )

    resp = call_llm(
        system_prompt,
        user_prompt,
        context_info={"stage": "fase2_candidatos", "lugar": lugar_padre.get("nombre"), "tipo": tipo_preferido},
    )
    if not resp:
        return []

    try:
        data = json.loads(resp)
    except (json.JSONDecodeError, TypeError):
        log_error("Respuesta LLM invalida buscando distritos/barrios/pedanias", context={"response": resp[:500]})
        return []

    if isinstance(data, dict):
        data = data.get("candidatos", [])
    if not isinstance(data, list):
        return []

    candidatos: list[Candidate] = []
    ciudad_nombre = str(lugar_padre.get("nombre") or "")
    for item in data:
        if not isinstance(item, dict):
            continue
        tipo = item.get("tipo")
        if tipo_preferido and tipo != tipo_preferido:
            continue
        if tipo not in ("distrito", "barrio", "pedania"):
            continue
        article_url = item.get("article_url")
        candidato = _make_candidate(
            nombre=str(item.get("nombre") or ""),
            article_url=str(article_url) if article_url else None,
            tipo=tipo,
            ciudad_nombre=ciudad_nombre,
            source="llm",
            evidencia=str(item.get("evidencia") or ""),
            parent_nombre=item.get("parent_nombre"),
            confianza=float(item.get("confianza") or 0.6),
            population_hint=item.get("population_hint") if isinstance(item.get("population_hint"), int) else None,
            source_url=str(lugar_padre.get("wikipedia_url") or ""),
        )
        if candidato:
            candidatos.append(candidato)

    return candidatos


def _expandir_categorias_y_anexos(candidatos: list[Candidate], tipo: str, ciudad_nombre: str) -> list[Candidate]:
    expandidos: list[Candidate] = []
    for candidato in candidatos:
        url = str(candidato.get("article_url") or "")
        if candidato.get("categoria") or candidato.get("anexo"):
            expandidos.extend(
                _extraer_desde_categoria_o_anexo(
                    url=url,
                    tipo=tipo,
                    ciudad_nombre=ciudad_nombre,
                    parent_nombre=candidato.get("parent_nombre"),
                )
            )
        else:
            expandidos.append(candidato)
    return _dedupe_candidates(expandidos)


def _extraer_candidatos_guiados(
    html: str,
    lugar: dict,
    tipo_preferido: str,
    contexto: str,
    source_url: str,
    parent_nombre: str | None = None,
    profundidad: int = 0,
    vistos: set[str] | None = None,
) -> list[Candidate]:
    """
    Extrae candidatos solo desde paginas cuya ruta ha sido aprobada por el LLM.
    La recursion permite listas/anexos intermedios, pero evita bucles y rastreos
    demasiado amplios.
    """
    if profundidad > 2:
        return []
    vistos = vistos or set()
    if source_url:
        if source_url in vistos:
            return []
        vistos.add(source_url)
        
        # Fast-track para Categorías y Anexos: ¡No preguntamos al LLM qué hacer con ellas!
        if _es_categoria(source_url) or _es_anexo(source_url):
            print(f"   - Ruta Rápida ({tipo_preferido}): Extrayendo directamente de {source_url}")
            return _extraer_desde_categoria_o_anexo(
                url=source_url,
                tipo=tipo_preferido,
                ciudad_nombre=str(lugar.get("nombre") or ""),
                parent_nombre=parent_nombre,
            )

    estrategia = analizar_ruta_extraccion_llm(html, lugar, tipo_preferido=tipo_preferido, contexto=contexto)
    print(f"   - Ruta LLM {tipo_preferido} ({lugar.get('nombre')}): {estrategia.get('motivo') or 'sin motivo'}")
    if not _ruta_tiene_camino(estrategia):
        log_error(
            "Ruta LLM no clara; no se extraen hijos de esta pagina",
            context={
                "lugar": lugar.get("nombre"),
                "tipo": tipo_preferido,
                "source_url": source_url,
                "motivo": estrategia.get("motivo"),
            },
        )
        return []

    ciudad_nombre = str(lugar.get("nombre") or "")
    candidatos: list[Candidate] = []
    if estrategia.get("usar_pagina_actual"):
        candidatos.extend(
            _extraer_candidatos_por_enlaces(
                html,
                ciudad_nombre,
                tipo_preferido=tipo_preferido,
                parent_nombre=parent_nombre,
            )
        )
        candidatos.extend(
            _extraer_candidatos_de_secciones(
                html,
                ciudad_nombre,
                tipo_preferido=tipo_preferido,
                parent_nombre=parent_nombre,
            )
        )
        candidatos.extend(
            _extraer_candidatos_de_tablas(
                html,
                ciudad_nombre,
                source_url=source_url,
                tipo_preferido=tipo_preferido,
            )
        )
        candidatos.extend(
            _extraer_candidatos_llm(
                html,
                lugar,
                tipo_preferido=tipo_preferido,
                contexto=contexto,
            )
        )

    for aux_url in _paginas_auxiliares_guiadas(html, lugar, estrategia):
        aux_html = fetch_url(aux_url)
        if not aux_html:
            log_error("No se pudo descargar pagina guiada por LLM", context={"url": aux_url, "lugar": lugar.get("nombre")})
            continue
        candidatos.extend(
            _extraer_candidatos_guiados(
                aux_html,
                lugar,
                tipo_preferido=tipo_preferido,
                contexto=f"fuente auxiliar {aux_url}",
                source_url=aux_url,
                parent_nombre=parent_nombre,
                profundidad=profundidad + 1,
                vistos=vistos,
            )
        )
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return candidatos


def buscar_distritos(lugar: dict, html_ciudad: str) -> list[Candidate]:
    """
    Busca candidatos a distrito desde la pagina de una ciudad grande.
    """
    ciudad_nombre = str(lugar.get("nombre") or "")
    source_url = str(lugar.get("wikipedia_url") or "")
    candidatos = _extraer_candidatos_guiados(
        html_ciudad,
        lugar,
        tipo_preferido="distrito",
        contexto="ciudad_grande",
        source_url=source_url,
    )
    candidatos = _expandir_categorias_y_anexos(_dedupe_candidates(candidatos), "distrito", ciudad_nombre)
    return _dedupe_candidates(candidatos)


def buscar_barrios(lugar_padre: dict, html_origen: str, contexto: str) -> list[Candidate]:
    """
    Busca candidatos a barrio desde una ciudad o desde un distrito.
    """
    ciudad_nombre = str(lugar_padre.get("nombre") or "")
    parent_nombre = ciudad_nombre
    source_url = str(lugar_padre.get("wikipedia_url") or "")
    candidatos = _extraer_candidatos_guiados(
        html_origen,
        lugar_padre,
        tipo_preferido="barrio",
        contexto=contexto,
        source_url=source_url,
        parent_nombre=parent_nombre,
    )
    candidatos = _expandir_categorias_y_anexos(_dedupe_candidates(candidatos), "barrio", ciudad_nombre)
    return _dedupe_candidates(candidatos)


def buscar_pedanias(lugar: dict, html_ciudad: str, contexto: str = "ciudad_grande_pedanias") -> list[Candidate]:
    """
    Busca pedanias/localidades externas pertenecientes a un municipio.
    En esta iteracion cuelgan directamente del municipio analizado.
    """
    ciudad_nombre = str(lugar.get("nombre") or "")
    source_url = str(lugar.get("wikipedia_url") or "")
    candidatos = _extraer_candidatos_guiados(
        html_ciudad,
        lugar,
        tipo_preferido="pedania",
        contexto=contexto,
        source_url=source_url,
    )
    candidatos = _expandir_categorias_y_anexos(_dedupe_candidates(candidatos), "pedania", ciudad_nombre)
    return _dedupe_candidates(candidatos)


def _reclasificar_barrios_como_pedanias(candidatos: list[Candidate]) -> list[Candidate]:
    """
    En municipios compuestos algunas paginas llaman "barrios" a los nucleos hijos.
    Se prueban como pedanias, pero solo se anadiran si la verificacion LLM lo confirma.
    """
    resultado: list[Candidate] = []
    for candidato in candidatos:
        if candidato.get("tipo") != "barrio":
            continue
        candidato_pedania = dict(candidato)
        candidato_pedania["tipo"] = "pedania"
        candidato_pedania["source"] = f"{candidato.get('source') or 'unknown'}_municipio_compuesto"
        candidato_pedania["evidencia"] = (
            f"{candidato.get('evidencia') or ''} "
            "Candidato tratado como pedania porque procede de subdivisiones de un municipio compuesto."
        ).strip()
        resultado.append(candidato_pedania)
    return resultado


def buscar_pedanias_municipio_compuesto(lugar: dict, html_municipio: str) -> list[Candidate]:
    """
    Busca las localidades hijas de un municipio compuesto.
    No busca distritos ni barrios internos; si una fuente llama barrios a las
    subdivisiones del municipio, se verifican como posibles pedanias.
    """
    ciudad_nombre = str(lugar.get("nombre") or "")
    source_url = str(lugar.get("wikipedia_url") or "")

    candidatos = buscar_pedanias(
        lugar,
        html_municipio,
        contexto="municipio_compuesto_pedanias",
    )

    barrios_como_hijos = _extraer_candidatos_guiados(
        html_municipio,
        lugar,
        tipo_preferido="barrio",
        contexto="municipio_compuesto_subdivisiones_llamadas_barrios",
        source_url=source_url,
        parent_nombre=ciudad_nombre,
    )
    candidatos.extend(_reclasificar_barrios_como_pedanias(barrios_como_hijos))

    candidatos = _expandir_categorias_y_anexos(_dedupe_candidates(candidatos), "pedania", ciudad_nombre)
    return _dedupe_candidates(candidatos)


def _resolver_article_url(candidato: Candidate, padre: dict, ciudad: dict) -> str:
    url = str(candidato.get("article_url") or "").strip()
    if url:
        return url

    nombre = str(candidato.get("nombre") or "").strip()
    tipo = str(candidato.get("tipo") or "").strip()
    ciudad_nombre = str(ciudad.get("nombre") or "")
    padre_nombre = str(padre.get("nombre") or "")
    consultas = [
        f"{nombre} {ciudad_nombre}",
        f"{nombre} {tipo} {ciudad_nombre}",
    ]
    if padre_nombre and padre_nombre != ciudad_nombre:
        consultas.append(f"{nombre} {padre_nombre} {ciudad_nombre}")

    for consulta in consultas:
        api_url = (
            "https://es.wikipedia.org/w/api.php?action=query&list=search&format=json"
            f"&srlimit=5&srsearch={quote(consulta)}"
        )
        raw = fetch_url(api_url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for result in data.get("query", {}).get("search", []):
            title = str(result.get("title") or "")
            title_norm = _normalizar_texto(title)
            nombre_norm = _normalizar_texto(nombre)
            ciudad_norm = _normalizar_texto(ciudad_nombre)
            if nombre_norm and nombre_norm in title_norm:
                if not ciudad_norm or ciudad_norm in title_norm or tipo in _normalizar_texto(result.get("snippet", "")):
                    return urljoin(BASE_WIKI_URL, title.replace(" ", "_"))
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return ""


def _descripcion_generica(candidato: Candidate, padre: dict, ciudad: dict) -> tuple[str, str]:
    tipo = str(candidato.get("tipo") or "lugar")
    nombre = str(candidato.get("nombre") or "")
    padre_nombre = str(padre.get("nombre") or "")
    ciudad_nombre = str(ciudad.get("nombre") or "")
    if tipo == "barrio" and padre.get("tipo") == "distrito":
        corta = f"Barrio de {ciudad_nombre}, integrado en el distrito de {padre_nombre}."
        larga = (
            f"{nombre} es un barrio de {ciudad_nombre} integrado en el distrito de "
            f"{padre_nombre}. Se ha incorporado a partir de la organizacion territorial "
            "recogida en Wikipedia para mantener la jerarquia administrativa de la ciudad."
        )
    elif tipo == "barrio":
        corta = f"Barrio de {ciudad_nombre}, incorporado a la estructura territorial de la ciudad."
        larga = (
            f"{nombre} es un barrio de {ciudad_nombre}. Se ha incorporado a partir de "
            "la organizacion territorial recogida en Wikipedia cuando no existe un "
            "distrito intermedio claramente documentado."
        )
    elif tipo == "pedania":
        corta = f"Pedania o localidad externa de {ciudad_nombre}, perteneciente al municipio."
        larga = (
            f"{nombre} es una pedania, localidad o nucleo de poblacion de {ciudad_nombre}. "
            "Se ha incorporado a partir de la organizacion territorial recogida en Wikipedia "
            "cuando aparece como lugar separado fisicamente del continuo urbano pero perteneciente "
            "al municipio."
        )
    else:
        corta = f"Distrito de {ciudad_nombre}, unidad administrativa de la ciudad."
        larga = (
            f"{nombre} es un distrito de {ciudad_nombre}. Se ha incorporado a partir "
            "de la organizacion territorial recogida en Wikipedia, junto con los "
            "barrios asociados cuando aparecen documentados."
        )
    return corta, larga


def _construir_desde_fuente(candidato: Candidate, padre: dict, ciudad: dict, source_url: str) -> tuple[dict | None, str]:
    html = fetch_url(source_url)
    if not html:
        return None, "sin articulo propio y error descargando fuente"

    nombre = str(candidato.get("nombre") or "")
    tipo = str(candidato.get("tipo") or "")
    try:
        lugar_obj = construir_lugar(
            nombre=nombre,
            html=html,
            tipo=tipo,
            padre_id=padre["id"],
            padre_info=padre,
            wikipedia_url=source_url,
        )
    except Exception as e:
        log_error(f"Error construyendo {tipo} {nombre} desde fuente: {e}")
        return None, f"ERROR ({e})"

    population_hint = candidato.get("population_hint")
    if isinstance(population_hint, int) and population_hint > 0:
        lugar_obj["poblacion"] = population_hint
    else:
        lugar_obj["poblacion"] = 0

    if tipo == "barrio" and padre.get("tipo") == "distrito":
        lugar_obj["abuelo_id"] = ciudad["id"]

    corta, larga = _descripcion_generica(candidato, padre, ciudad)
    lugar_obj["descripcion_corta"] = corta
    lugar_obj["descripcion"] = larga
    return lugar_obj, "OK (desde fuente)"


def _texto_no_contradice_parentesco(html: str, lugar: dict, padre: dict, candidato: Candidate) -> bool:
    """
    Evita descartar de forma agresiva: solo bloquea si hay una senal clara de que
    el lugar pertenece a otra ciudad/provincia y no aparece el padre esperado.
    """
    soup = get_soup(html)
    content = soup.find(id="mw-content-text")
    texto = ""
    if content:
        partes = [p.get_text(" ", strip=True) for p in content.find_all("p", limit=4)]
        infobox = soup.find("table", class_="infobox")
        if infobox:
            partes.append(infobox.get_text(" ", strip=True))
        texto = _normalizar_texto(" ".join(partes))

    padre_nombre = _normalizar_texto(str(padre.get("nombre") or ""))
    ciudad_nombre = _normalizar_texto(str(lugar.get("nombre") or ""))
    provincia = _normalizar_texto(str(lugar.get("provincia") or ""))
    evidencia = _normalizar_texto(str(candidato.get("evidencia") or ""))

    if padre_nombre and (padre_nombre in texto or padre_nombre in evidencia):
        return True
    if ciudad_nombre and (ciudad_nombre in texto or ciudad_nombre in evidencia):
        return True
    if provincia and provincia in texto:
        return True
    return bool(candidato.get("source") in ("category", "annex", "section"))


def _aceptar_como_pedania_si_ciudad_pequena(
    candidato: Candidate,
    verificacion: dict,
    permitir: bool,
) -> Candidate | None:
    if not permitir:
        return None
    if candidato.get("tipo") != "barrio":
        return None
    if verificacion.get("aceptar") is not True or verificacion.get("tipo_confirmado") != "pedania":
        return None

    candidato_pedania = dict(candidato)
    candidato_pedania["tipo"] = "pedania"
    candidato_pedania["source"] = f"{candidato.get('source') or 'unknown'}_reclasificado"
    candidato_pedania["evidencia"] = (
        f"{candidato.get('evidencia') or ''} "
        "Reclasificado como pedania por regla de ciudad pequena."
    ).strip()
    return candidato_pedania


def _validar_poblacion_o_ine(poblacion: int | None, lugar_obj: dict, ciudad: dict) -> tuple[bool, str]:
    if not isinstance(poblacion, int):
        poblacion = 0
        
    # Si viene directamente del INE y se encontró en Wikipedia, aceptar siempre (mínimo 1 hab)
    if lugar_obj.get("source") == "ine":
        wiki_url = str(lugar_obj.get("wikipedia_url") or "")
        if poblacion >= 1 and wiki_url and "/wiki/" in wiki_url:
            return True, "OK (validado en INE y con Wikipedia)"
            
    if poblacion > 20:
        return True, "OK"
    if poblacion == 0:
        return False, f"descartado por poblacion ({poblacion})"
    if not DATOS_INE_GLOBAL:
        return False, f"descartado por poblacion ({poblacion}) y sin datos_ine"
    cpro = str(ciudad.get("cpro") or "")
    cmun = str(ciudad.get("cmun") or "")
    if not cpro or not cmun:
        return False, f"descartado por poblacion ({poblacion}) sin cpro/cmun"
    municipio_ine = DATOS_INE_GLOBAL.get((cpro, cmun))
    if not municipio_ine:
        return False, f"descartado por poblacion ({poblacion}) y municipio no hallado en INE"
    nombre_norm = _slug(str(lugar_obj.get("nombre") or ""))
    for loc in municipio_ine.get("localidades", []):
        if _slug(loc["nombre"]) == nombre_norm:
            lugar_obj["tipo"] = "pedania"
            return True, "OK (validado en INE como pedania)"
    return False, f"descartado por poblacion ({poblacion}) y no hallado en INE"


def _es_municipio_independiente(nombre: str, ciudad: dict) -> bool:
    if not DATOS_INE_GLOBAL or 'municipios' not in DATOS_INE_GLOBAL:
        return False
    nombre_norm = _slug(nombre)
    ciudad_norm = _slug(ciudad.get("nombre") or "")
    if nombre_norm == ciudad_norm:
        return False

    provincia_ciudad = _slug(ciudad.get("provincia") or "")
    for (cpro, cmun), info in DATOS_INE_GLOBAL['municipios'].items():
        if _slug(info['nombre']) == nombre_norm:
            # Es de la misma provincia
            if _slug(info['provincia']) == provincia_ciudad:
                return True
            # O es un municipio grande de Espana (> 50k hab)
            if info.get('poblacion', 0) > 50000:
                return True
    return False


def _construir_si_supera_poblacion(
    candidato: Candidate,
    padre: dict,
    ciudad: dict,
    permitir_pedania_si_ciudad_pequena: bool = False,
) -> tuple[dict | None, str]:
    nombre = str(candidato.get("nombre") or "").strip()
    if _es_municipio_independiente(nombre, ciudad):
        return None, "descartado por ser municipio independiente conocido"
        
    url = _resolver_article_url(candidato, padre, ciudad)
    tipo = str(candidato.get("tipo") or "").strip()
    if not nombre:
        return None, "sin nombre"
    if not url:
        source_url = str(candidato.get("source_url") or ciudad.get("wikipedia_url") or "").strip()
        if source_url:
            html_fuente = fetch_url(source_url)
            if not html_fuente:
                return None, "sin articulo propio y error descargando fuente"

            if candidato.get("verificado"):
                aceptado = True
                verificacion = candidato.get("_verificacion_cache", {"motivo": "ya verificado en paso anterior"})
                estado_llm = "verificado previamente"
            else:
                aceptado, verificacion, estado_llm = verificar_candidato_llm(
                    candidato,
                    padre,
                    ciudad,
                    html_fuente=html_fuente,
                )
            if not aceptado:
                candidato_pedania = _aceptar_como_pedania_si_ciudad_pequena(
                    candidato,
                    verificacion,
                    permitir_pedania_si_ciudad_pequena,
                )
                if not candidato_pedania:
                    return None, estado_llm
                candidato = candidato_pedania
                tipo = "pedania"
                aceptado, verificacion, estado_llm = verificar_candidato_llm(
                    candidato,
                    padre,
                    ciudad,
                    html_fuente=html_fuente,
                )
                if not aceptado:
                    return None, estado_llm

            candidato_verificado = dict(candidato)
            candidato_verificado["nombre"] = _nombre_normalizado_seguro(
                nombre,
                verificacion.get("nombre_normalizado"),
            )
            poblacion_llm = verificacion.get("poblacion")
            if isinstance(poblacion_llm, int) and poblacion_llm > 0:
                candidato_verificado["population_hint"] = poblacion_llm
            if verificacion.get("parent_nombre"):
                candidato_verificado["parent_nombre"] = str(verificacion.get("parent_nombre"))

            lugar_obj, estado = _construir_desde_fuente(candidato_verificado, padre, ciudad, source_url)
            if not lugar_obj:
                return None, estado
            poblacion = lugar_obj.get("poblacion")
            valido, msg = _validar_poblacion_o_ine(poblacion, lugar_obj, ciudad)
            if not valido:
                return None, msg
            return lugar_obj, "OK (desde fuente, verificado LLM/INE)"
        return None, "sin URL ni fuente"

    html = fetch_url(url)
    if not html:
        return None, "error descargando"

    if not _texto_no_contradice_parentesco(html, ciudad, padre, candidato):
        return None, "descartado por parentesco dudoso"

    if candidato.get("verificado"):
        aceptado = True
        verificacion = candidato.get("_verificacion_cache", {"motivo": "ya verificado en paso anterior"})
        estado_llm = "verificado previamente"
    else:
        aceptado, verificacion, estado_llm = verificar_candidato_llm(
            candidato,
            padre,
            ciudad,
            html_articulo=html,
        )
    if not aceptado:
        candidato_pedania = _aceptar_como_pedania_si_ciudad_pequena(
            candidato,
            verificacion,
            permitir_pedania_si_ciudad_pequena,
        )
        if not candidato_pedania:
            return None, estado_llm
        candidato = candidato_pedania
        tipo = "pedania"
        aceptado, verificacion, estado_llm = verificar_candidato_llm(
            candidato,
            padre,
            ciudad,
            html_articulo=html,
        )
        if not aceptado:
            return None, estado_llm

    candidato_verificado = dict(candidato)
    candidato_verificado["nombre"] = _nombre_normalizado_seguro(
        nombre,
        verificacion.get("nombre_normalizado"),
    )
    poblacion_llm = verificacion.get("poblacion")
    if isinstance(poblacion_llm, int) and poblacion_llm > 0:
        candidato_verificado["population_hint"] = poblacion_llm
    if verificacion.get("parent_nombre"):
        candidato_verificado["parent_nombre"] = str(verificacion.get("parent_nombre"))

    try:
        lugar_obj = construir_lugar(
            nombre=str(candidato_verificado.get("nombre") or nombre),
            html=html,
            tipo=tipo,
            padre_id=padre["id"],
            padre_info=padre,
            wikipedia_url=url,
        )
    except Exception as e:
        log_error(f"Error construyendo {tipo} {nombre}: {e}")
        return None, f"ERROR ({e})"

    population_hint = candidato_verificado.get("population_hint")
    if isinstance(population_hint, int) and population_hint > 0:
        lugar_obj["poblacion"] = population_hint

    if tipo == "barrio" and padre.get("tipo") == "distrito":
        lugar_obj["abuelo_id"] = ciudad["id"]

    poblacion = lugar_obj.get("poblacion")
    valido, msg = _validar_poblacion_o_ine(poblacion, lugar_obj, ciudad)
    if not valido:
        return None, msg

    return lugar_obj, estado_llm


def _buscar_distrito_por_nombre(parent_nombre: str | None, distritos: list[tuple[dict, str]]) -> dict | None:
    if not parent_nombre:
        return None
    parent_slug = _slug(parent_nombre)
    for distrito_obj, _ in distritos:
        nombre_slug = _slug(str(distrito_obj.get("nombre") or ""))
        if parent_slug == nombre_slug or parent_slug in nombre_slug or nombre_slug in parent_slug:
            return distrito_obj
    return None


def _clave_lugar_local(lugar_obj: dict) -> tuple[str, str, str, str]:
    return (
        str(lugar_obj.get("tipo") or ""),
        str(lugar_obj.get("padre_id") or ""),
        str(lugar_obj.get("abuelo_id") or ""),
        _slug(str(lugar_obj.get("nombre") or "")),
    )


def _score_lugar_local(lugar_obj: dict) -> tuple[int, int, int, int, int]:
    wikipedia_url = str(lugar_obj.get("wikipedia_url") or "")
    poblacion = lugar_obj.get("poblacion") if isinstance(lugar_obj.get("poblacion"), int) else 0
    descripcion_len = len(str(lugar_obj.get("descripcion") or ""))
    has_coords = int(bool(lugar_obj.get("lat")) and bool(lugar_obj.get("lng")))
    
    tipo = str(lugar_obj.get("tipo") or "")
    tipo_score = 3 if tipo == "pedania" else (2 if tipo == "distrito" else 1)
    
    return (
        tipo_score,
        int(bool(wikipedia_url and "/wiki/" in wikipedia_url)),
        int(poblacion or 0),
        has_coords,
        descripcion_len,
    )


def _dedupe_lugares_local(lugares: list[dict]) -> list[dict]:
    """
    Deduplicacion determinista dentro de la ciudad procesada.
    Conserva el objeto con articulo/poblacion/evidencia mas fuerte.
    """
    por_id: dict[str, dict] = {}
    por_clave: dict[tuple[str, str, str, str], dict] = {}
    por_url: dict[str, dict] = {}

    for lugar_obj in lugares:
        lugar_id = str(lugar_obj.get("id") or "")
        clave = _clave_lugar_local(lugar_obj)
        wiki_url = str(lugar_obj.get("wikipedia_url") or "")
        
        existente = por_id.get(lugar_id) or por_clave.get(clave)
        if not existente and wiki_url and "/wiki/" in wiki_url:
            existente = por_url.get(wiki_url)
            
        if existente:
            if _score_lugar_local(lugar_obj) > _score_lugar_local(existente):
                if lugar_id:
                    por_id[lugar_id] = lugar_obj
                por_clave[clave] = lugar_obj
                if wiki_url and "/wiki/" in wiki_url:
                    por_url[wiki_url] = lugar_obj
                    
                viejo_id = str(existente.get("id") or "")
                if viejo_id and viejo_id != lugar_id and por_id.get(viejo_id) is existente:
                    por_id[viejo_id] = lugar_obj
                    
                vieja_url = str(existente.get("wikipedia_url") or "")
                if vieja_url and vieja_url != wiki_url and por_url.get(vieja_url) is existente:
                    por_url[vieja_url] = lugar_obj
        else:
            if lugar_id:
                por_id[lugar_id] = lugar_obj
            por_clave[clave] = lugar_obj
            if wiki_url and "/wiki/" in wiki_url:
                por_url[wiki_url] = lugar_obj

    resultado: list[dict] = []
    vistos_ids = set()
    vistos_claves = set()
    vistos_urls = set()
    for lugar_obj in lugares:
        lugar_id = str(lugar_obj.get("id") or "")
        clave = _clave_lugar_local(lugar_obj)
        wiki_url = str(lugar_obj.get("wikipedia_url") or "")
        
        elegido = por_id.get(lugar_id) or por_clave.get(clave)
        if not elegido and wiki_url and "/wiki/" in wiki_url:
            elegido = por_url.get(wiki_url)
            
        if elegido is not lugar_obj:
            continue
        if lugar_id in vistos_ids or clave in vistos_claves or (wiki_url and wiki_url in vistos_urls and "/wiki/" in wiki_url):
            continue
            
        vistos_ids.add(lugar_id)
        vistos_claves.add(clave)
        if wiki_url and "/wiki/" in wiki_url:
            vistos_urls.add(wiki_url)
            
        resultado.append(lugar_obj)

    return resultado


def _validar_lugares_ciudad(lugares: list[dict], ciudad: dict) -> list[dict]:
    ciudad_id = str(ciudad.get("id") or "")
    ids_validos = {ciudad_id}
    resultado: list[dict] = []

    for lugar_obj in _dedupe_lugares_local(lugares):
        tipo = lugar_obj.get("tipo")
        poblacion = lugar_obj.get("poblacion")
        lugar_id = str(lugar_obj.get("id") or "")
        padre_id = str(lugar_obj.get("padre_id") or "")
        abuelo_id = str(lugar_obj.get("abuelo_id") or "")

        if tipo not in ("distrito", "barrio", "pedania"):
            log_error("Lugar hijo descartado por tipo invalido", context={"lugar": lugar_obj.get("nombre"), "tipo": tipo})
            continue
        valido, _ = _validar_poblacion_o_ine(poblacion, lugar_obj, ciudad)
        if not valido:
            log_error("Lugar hijo descartado por poblacion", context={"lugar": lugar_obj.get("nombre"), "poblacion": poblacion})
            continue
        if not lugar_id or lugar_id in ids_validos:
            log_error("Lugar hijo descartado por id duplicado o vacio", context={"lugar": lugar_obj.get("nombre"), "id": lugar_id})
            continue
        if tipo == "distrito" and padre_id != ciudad_id:
            log_error("Distrito descartado por padre invalido", context={"lugar": lugar_obj.get("nombre"), "padre_id": padre_id})
            continue
        if tipo == "pedania" and padre_id != ciudad_id:
            log_error("Pedania descartada por padre invalido", context={"lugar": lugar_obj.get("nombre"), "padre_id": padre_id})
            continue
        if tipo == "barrio":
            if padre_id not in ids_validos:
                log_error("Barrio descartado por padre inexistente", context={"lugar": lugar_obj.get("nombre"), "padre_id": padre_id})
                continue
            if abuelo_id and abuelo_id != ciudad_id:
                log_error("Barrio descartado por abuelo invalido", context={"lugar": lugar_obj.get("nombre"), "abuelo_id": abuelo_id})
                continue

        resultado.append(lugar_obj)
        ids_validos.add(lugar_id)

    return resultado



def procesar_estructura_ciudad(html: str, lugar: dict) -> list[dict]:
    """
    Busca distritos y barrios en el HTML de una ciudad grande o pequeña.
    El lugar pasado es la entidad hija (ciudad_grande o ciudad_pequena).
    """
    import time
    from config import DELAY_BETWEEN_REQUESTS
    from scraper import fetch_url
    
    tipo = lugar.get("tipo")
    if tipo not in ("ciudad_grande", "ciudad_pequena"):
        return []
        
    lugares_resultado = []
    ids_creados = set()

    if tipo == "ciudad_grande":
        print("   -> Buscando distritos...")
        distritos_candidatos = buscar_distritos(lugar, html)
        print(f"   - Candidatos a distrito: {len(distritos_candidatos)}")
        distritos_creados = []
        for candidato in distritos_candidatos:
            nombre = str(candidato.get("nombre") or "?")
            print(f"     - Distrito [{nombre}]", end=" ")
            distrito_obj, estado = _construir_si_supera_poblacion(candidato, lugar, lugar)
            print(estado)
            if distrito_obj:
                lugares_resultado.append(distrito_obj)
                distritos_creados.append((distrito_obj, str(candidato.get("article_url") or "")))
            time.sleep(DELAY_BETWEEN_REQUESTS)
            
        if distritos_creados:
            barrios_globales = buscar_barrios(lugar, html, contexto="ciudad_grande_con_distritos")
            for candidato in barrios_globales:
                distrito_padre = _buscar_distrito_por_nombre(str(candidato.get("parent_nombre") or ""), distritos_creados)
                if not distrito_padre:
                    aceptado, verificacion, _ = verificar_candidato_llm(candidato, lugar, lugar, html_fuente=html)
                    if aceptado and verificacion.get("parent_nombre"):
                        candidato["parent_nombre"] = str(verificacion.get("parent_nombre"))
                        distrito_padre = _buscar_distrito_por_nombre(str(candidato.get("parent_nombre") or ""), distritos_creados)
                if not distrito_padre: continue
                nombre = str(candidato.get("nombre") or "?")
                print(f"     - Barrio [{nombre}] -> {distrito_padre['nombre']}", end=" ")
                barrio_obj, estado = _construir_si_supera_poblacion(candidato, distrito_padre, lugar)
                print(estado)
                if barrio_obj and barrio_obj.get("id") not in ids_creados:
                    lugares_resultado.append(barrio_obj)
                    ids_creados.add(barrio_obj["id"])
                time.sleep(DELAY_BETWEEN_REQUESTS)
                
            for distrito_obj, distrito_url in distritos_creados:
                if not distrito_url: continue
                html_distrito = fetch_url(distrito_url)
                if not html_distrito: continue
                barrios = buscar_barrios(distrito_obj, html_distrito, contexto=f"distrito de {lugar.get('nombre')}")
                for candidato in barrios:
                    nombre = str(candidato.get("nombre") or "?")
                    print(f"     - Barrio [{nombre}]", end=" ")
                    barrio_obj, estado = _construir_si_supera_poblacion(candidato, distrito_obj, lugar)
                    print(estado)
                    if barrio_obj and barrio_obj.get("id") not in ids_creados:
                        lugares_resultado.append(barrio_obj)
                        ids_creados.add(barrio_obj["id"])
                    time.sleep(DELAY_BETWEEN_REQUESTS)
        else:
            barrios = buscar_barrios(lugar, html, contexto="ciudad_grande_sin_distritos")
            print(f"   - Barrios candidatos directos: {len(barrios)}")
            for candidato in barrios:
                nombre = str(candidato.get("nombre") or "?")
                print(f"     - Barrio [{nombre}]", end=" ")
                barrio_obj, estado = _construir_si_supera_poblacion(candidato, lugar, lugar)
                print(estado)
                if barrio_obj:
                    lugares_resultado.append(barrio_obj)
                time.sleep(DELAY_BETWEEN_REQUESTS)
                
    elif tipo == "ciudad_pequena":
        print("   -> Buscando barrios...")
        barrios = buscar_barrios(lugar, html, contexto="ciudad_pequena_barrios")
        for candidato in barrios:
            nombre = str(candidato.get("nombre") or "?")
            print(f"     - Barrio [{nombre}]", end=" ")
            barrio_obj, estado = _construir_si_supera_poblacion(candidato, lugar, lugar)
            print(estado)
            if barrio_obj and barrio_obj.get("id") not in ids_creados:
                lugares_resultado.append(barrio_obj)
                ids_creados.add(barrio_obj["id"])
            time.sleep(DELAY_BETWEEN_REQUESTS)
            
    lugares_validados = _validar_lugares_ciudad(lugares_resultado, lugar)
    return lugares_validados

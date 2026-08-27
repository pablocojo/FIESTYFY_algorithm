"""
Descubrimiento de perfiles oficiales de redes sociales — Nivel 1 (web oficial).

Un perfil de Instagram/Facebook/X enlazado desde las páginas INTERNAS de la web
oficial de un ayuntamiento/localidad se considera oficial por definición
(verificado_por: "web_oficial"). Este módulo:

1. Clasifica y normaliza los enlaces cosechados por el spider, descartando todo
   lo que no sea un perfil (botones de compartir, posts sueltos, grupos, etc.)
   → cero falsos positivos.
2. Elige el mejor candidato por red (el más repetido en el sitio: los enlaces
   del footer/header aparecen en todas las páginas, así que dominan sobre
   enlaces puntuales a perfiles ajenos).
3. Persiste el resultado en `redes_sociales_cache.json` (fuente de verdad,
   incluye los "no encontrado"). El volcado a lugares_espana.json lo hace
   `sync_redes_a_lugares.py`, re-ejecutable mientras la Fase 1 siga añadiendo
   lugares.

Las redes que queden a None se marcan `pendiente_apps: true` → cola de búsqueda
in-app del runner de la Etapa C.
"""

import asyncio
import json
import os
import re
import logging
import urllib.parse
from collections import Counter
from datetime import date

from config import SOCIAL_PROFILE_DISCOVERY_ENABLED, SOCIAL_PROFILE_CACHE_FILE

logger = logging.getLogger("social_finder")

REDES = ("instagram", "facebook", "twitter")

# ──────────────────────────────────────────────────
# CLASIFICACIÓN Y NORMALIZACIÓN DE ENLACES
# ──────────────────────────────────────────────────

# Rutas de Instagram que NO son un perfil
_IG_RESERVADOS = {
    "p", "reel", "reels", "tv", "stories", "explore", "accounts", "about",
    "developer", "legal", "directory", "share", "web", "invites", "static",
}
_IG_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")

# Rutas de X/Twitter que NO son un perfil
_TW_RESERVADOS = {
    "share", "intent", "home", "search", "hashtag", "i", "login", "signup",
    "privacy", "tos", "explore", "settings", "account", "notifications",
    "messages", "compose", "download", "about", "en", "es",
}
_TW_HANDLE = re.compile(r"^[a-z0-9_]{1,15}$")

# Primeros segmentos de ruta de Facebook que NO son una página/perfil
_FB_RECHAZADOS = {
    "sharer.php", "share.php", "share", "sharer", "dialog", "plugins", "login",
    "login.php", "watch", "events", "groups", "photo", "photo.php", "photos",
    "posts", "story.php", "hashtag", "reel", "reels", "video.php", "videos",
    "help", "policies", "legal", "marketplace", "gaming", "live", "l.php",
    "tr", "media", "notes", "search", "settings", "stories",
}
_FB_HANDLE = re.compile(r"^[a-z0-9.\-_]{3,}$")


def _red_de_netloc(netloc: str) -> str | None:
    """Determina la red social a partir del dominio (tolerando subdominios www/m/es-es...)."""
    netloc = netloc.lower().split(":")[0]
    if netloc == "l.facebook.com":  # redirector, no perfil
        return None
    for dominio, red in (
        ("instagram.com", "instagram"),
        ("facebook.com", "facebook"),
        ("fb.com", "facebook"),
        ("fb.me", "facebook"),
        ("twitter.com", "twitter"),
        ("x.com", "twitter"),
    ):
        if netloc == dominio or netloc.endswith("." + dominio):
            # Subdominios técnicos que nunca son perfiles
            sub = netloc[: -len(dominio)].rstrip(".")
            if sub in ("", "www", "m", "mobile", "web") or re.match(r"^[a-z]{2}(-[a-z]{2})?$", sub):
                return red
            return None
    return None


def normalizar_link_social(url: str) -> tuple[str, str] | None:
    """
    Clasifica una URL como perfil social oficial y la canonicaliza.
    Devuelve (red, url_canonica) o None si no es un perfil.
    """
    if not url or not url.lower().startswith("http"):
        return None
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return None

    red = _red_de_netloc(parsed.netloc)
    if not red:
        return None

    segmentos = [s for s in parsed.path.split("/") if s]
    if not segmentos:
        return None
    primero = segmentos[0].lower()

    if red == "instagram":
        if primero in _IG_RESERVADOS or len(segmentos) > 1:
            return None
        if not _IG_HANDLE.match(primero):
            return None
        return red, f"https://www.instagram.com/{primero}"

    if red == "twitter":
        if primero in _TW_RESERVADOS or len(segmentos) > 1:
            return None
        if not _TW_HANDLE.match(primero):
            return None
        return red, f"https://x.com/{primero}"

    # Facebook
    if primero in _FB_RECHAZADOS:
        return None
    if primero == "profile.php":
        query = urllib.parse.parse_qs(parsed.query)
        perfil_id = (query.get("id") or [""])[0]
        if not perfil_id.isdigit():
            return None
        return red, f"https://www.facebook.com/profile.php?id={perfil_id}"
    if primero in ("pages", "people"):
        # facebook.com/pages/<nombre>/<id> — requiere nombre e id
        if len(segmentos) < 3:
            return None
        return red, "https://www.facebook.com/" + "/".join(
            s.lower() for s in segmentos[:3]
        )
    if len(segmentos) > 1:
        return None  # facebook.com/<pagina>/<subruta> → post, foto, about...
    if not _FB_HANDLE.match(primero) or ".php" in primero:
        return None
    return red, f"https://www.facebook.com/{primero}"


import unicodedata

_RUIDO_HANDLES = {"diario", "noticias", "club", "cf", "cd", "asociacion", "tv", "radio", "prensa", "deporte", "futbol"}

def _extraer_handle(url: str, red: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if red == "facebook" and "profile.php" in parsed.path:
        return "" # Los IDs numéricos no se pueden validar léxicamente, los aceptamos por defecto
    segmentos = [s for s in parsed.path.split("/") if s]
    if not segmentos: 
        return ""
    if red == "facebook" and segmentos[0] in ("pages", "people") and len(segmentos) >= 3:
        return segmentos[1]
    return segmentos[-1]

def _validar_handle(handle: str, nombre_lugar: str) -> bool:
    if not handle:
        return True # Si no hay handle (ej. ID numerico), confiamos en que era el mas repetido de la web
    handle_lower = handle.lower()
    for ruido in _RUIDO_HANDLES:
        if ruido in handle_lower:
            return False
            
    # Normalize with unicodedata
    nombre_norm = ''.join(c for c in unicodedata.normalize('NFD', nombre_lugar) if unicodedata.category(c) != 'Mn').lower()
    
    oficiales = {"ayto", "ayuntamiento", "udala", "turismo", "fiestas", "kultura", "cultura"}
    
    for off in oficiales:
        if off in handle_lower:
            return True
            
    words = [w for w in re.split(r'\W+', nombre_norm) if len(w) >= 4]
    if not words: # Nombre muy corto (ej. "A", "Ea")
        return nombre_norm in handle_lower
        
    for w in words:
        if w in handle_lower:
            return True
            
    return False

def resolver_perfiles(contador: Counter, nombre_lugar: str = "") -> dict:
    """
    Elige el mejor perfil por red validándolo léxicamente.
    """
    candidatos: dict[str, list] = {}
    for (red, url), n in (contador or Counter()).items():
        handle = _extraer_handle(url, red)
        if not nombre_lugar or _validar_handle(handle, nombre_lugar):
            candidatos.setdefault(red, []).append((n, -len(url), url))

    perfiles = {red: None for red in REDES}
    for red, lista in candidatos.items():
        if red in perfiles:
            perfiles[red] = max(lista)[2]
    return perfiles


# ──────────────────────────────────────────────────
# CACHÉ PERSISTENTE (fuente de verdad de los perfiles)
# ──────────────────────────────────────────────────

_CACHE_MISS = object()


def _write_json_cache_sync(path: str, data: dict):
    from state_manager import escribir_json_con_respaldo
    try:
        escribir_json_con_respaldo(path, data, indent=1)
    except OSError as e:
        logger.error(f"Error guardando caché de perfiles RRSS: {e}")


class RedesCache:
    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def _cargar(self):
        if self._loaded:
            return
        self._loaded = True
        if os.path.exists(self.path):
            from state_manager import leer_json_con_respaldo
            datos = leer_json_con_respaldo(self.path, "La caché de perfiles RRSS")
            if isinstance(datos, dict):
                self._data = datos
                logger.info(f"Caché de perfiles RRSS cargada: {len(self._data)} lugares")

    async def get(self, lugar_id: str):
        async with self._lock:
            self._cargar()
            return self._data.get(lugar_id, _CACHE_MISS)

    async def set(self, lugar_id: str, valor: dict):
        async with self._lock:
            self._cargar()
            self._data[lugar_id] = valor
            await asyncio.to_thread(_write_json_cache_sync, self.path, dict(self._data))


_FASE2_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = RedesCache(os.path.join(_FASE2_DIR, SOCIAL_PROFILE_CACHE_FILE))


# ──────────────────────────────────────────────────
# REGISTRO DE PERFILES DESCUBIERTOS
# ──────────────────────────────────────────────────

async def buscar_perfiles_externos(lugar: dict) -> dict:
    """Etapa C: Busca perfiles oficiales activamente usando DuckDuckGo."""
    nombre = lugar.get("nombre", "")
    if not nombre:
        return {}
        
    from scraper.google_search import _sync_fetch_ddg
    perfiles_encontrados = {}
    
    # Búsquedas dirigidas
    for red in REDES:
        site = "facebook.com" if red == "facebook" else ("instagram.com" if red == "instagram" else "x.com")
        queries = [
            f'"Ayuntamiento de {nombre}" site:{site}',
            f'"Fiestas de {nombre}" site:{site}'
        ]
        
        for q in queries:
            try:
                # Ejecutar búsqueda síncrona en el thread pool
                resultados = await asyncio.to_thread(_sync_fetch_ddg, q)
                for res in resultados:
                    url = res.get("url", "")
                    norm = normalizar_link_social(url)
                    if norm and norm[0] == red:
                        handle = _extraer_handle(norm[1], red)
                        if _validar_handle(handle, nombre):
                            perfiles_encontrados[red] = norm[1]
                            break # Encontramos uno válido
            except Exception as e:
                logger.debug(f"Error en búsqueda externa para {red}: {e}")
            
            if red in perfiles_encontrados:
                break
                
    return perfiles_encontrados

async def registrar_perfiles_web(lugar: dict, links_sociales: Counter) -> dict | None:
    """
    Registra los perfiles cosechados de la web oficial de un lugar.
    Si faltan redes, ejecuta una búsqueda externa (Etapa C) para intentar encontrarlas.
    """
    if not SOCIAL_PROFILE_DISCOVERY_ENABLED:
        return None

    lugar_id = lugar["id"]
    cacheado = await _cache.get(lugar_id)
    if cacheado is not _CACHE_MISS:
        return cacheado

    previo = lugar.get("redes_sociales")
    if isinstance(previo, dict) and any(previo.get(red) for red in REDES):
        await _cache.set(lugar_id, previo)
        return previo

    perfiles = resolver_perfiles(links_sociales, lugar.get("nombre", ""))
    
    faltan_redes = any(not perfiles.get(red) for red in REDES)
    if faltan_redes:
        logger.info(f"  [RRSS] Faltan redes en web oficial de {lugar.get('nombre')}, lanzando búsqueda externa...")
        extra = await buscar_perfiles_externos(lugar)
        for red, url in extra.items():
            if not perfiles.get(red):
                perfiles[red] = url

    entrada = {
        **perfiles,
        "verificado_por": "web_oficial" if not faltan_redes else "web_oficial_y_busqueda",
        "fecha_verificacion": date.today().isoformat(),
        "pendiente_apps": any(not perfiles.get(red) for red in REDES),
    }
    await _cache.set(lugar_id, entrada)

    hallados = [f"{red}={url}" for red, url in perfiles.items() if url]
    logger.info(
        f"  [RRSS] {lugar['nombre']}: "
        + (", ".join(hallados) if hallados else "sin perfiles enlazados ni encontrados")
    )
    return entrada

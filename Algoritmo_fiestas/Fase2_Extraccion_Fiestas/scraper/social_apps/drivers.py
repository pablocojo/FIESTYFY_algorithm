"""
Drivers de las apps de escritorio (Facebook/Instagram/X — PWAs bajo Edge/Chrome).

Estrategia v3 (tras las sesiones supervisadas del 04-07-2026):
- Candidatos de búsqueda: SOLO filas clicables reales (o el ancestro clicable de
  un texto), recogidos en UN solo paseo del árbol UIA (los árboles de FB son
  enormes) y con log de muestra para diagnosticar sesiones.
- X: va directo a la página de resultados y clica la pestaña "Personas/People"
  antes de evaluar candidatos (en "Top" sale contenido de cualquier cuenta).
- Facebook: en la página de resultados clica el filtro "Páginas".
- Instagram: la lectura del perfil abre la PRIMERA publicación de la cuadrícula
  y avanza con la flecha derecha post a post (la cuadrícula no expone captions).
- Verificación dura post-clic: el handle debe aparecer en el título o el
  contenido del perfil antes de leer nada (cero falsos positivos).
- Filtro de fecha: NINGÚN post de hace 1 año o más entra en la caché.
- Toda acción pasa por el SafetyGuard.
"""

import difflib
import logging
import os
import re
import time
from datetime import date, timedelta

from config import (
    SOCIAL_MAX_POSTS_PER_PROFILE,
    SOCIAL_MAX_SCROLLS,
    SOCIAL_MAX_MINUTES_PER_PROFILE,
    SOCIAL_POST_MONTHS_BACK,
)
from scraper.social_apps.util import (
    normalizar,
    validar_candidato_perfil,
    parsear_fecha_post,
    agrupar_posts,
    hash_perceptual,
    extraer_datos_ficha,
)
from scraper.social_apps.app_controller import nombre_elemento_con_foco

logger = logging.getLogger("social_drivers")

# Tipos UIA que se pueden clicar para navegar
_TIPOS_CLICABLES = ("ListItem", "Hyperlink", "Button")

# Textos de UI que no son contenido (botones, menús...)
_RUIDO_UI = re.compile(
    r"^(me gusta|like|comentar|comment|compartir|share|seguir|follow|siguiendo|"
    r"following|inicio|home|buscar|search|reels?|mensajes?|messages|notificaciones|"
    r"notifications|perfil|profile|m[aá]s|more|crear|create|explorar|explore|"
    r"publicar|post|responder|reply|repostear|repost|ver traducci[oó]n|"
    r"ver m[aá]s|see more|\d+\s*(me gusta|likes?|comentarios?|comments?)|"
    # Controles de ventana y navegación del navegador
    r"minimizar|restaurar|cerrar|maximize|minimize|close|"
    r"volver|adelante|volver a cargar|back|forward|reload|"
    # Sidebar de Twitter/X
    r"grok|bookmarks|premium|creator studio|communities|"
    r"direct messages|lists|verified orgs|"
    # Sidebar de Instagram
    r"nueva publicaci[oó]n|hilos|threads|"
    # Sidebar de Facebook
    r"amigos|grupos|videojuegos|friends|groups|gaming|marketplace|"
    # Acciones genéricas
    r"guardar|save|silenciar|mute|reportar|report|bloquear|block|"
    r"copiar enlace|copy link|embed|insertar|"
    r"trending now|image|video)$",
    re.IGNORECASE,
)

# Textos más largos que son claramente UI/chrome, no contenido de posts
_RUIDO_UI_LARGO = re.compile(
    r"(view keyboard shortcuts|press question mark"
    r"|you might like|who to follow|show more"
    r"|what.s happening|trending in \w+"
    r"|terms\s.*privacy\s.*cookies"
    r"|© \d{4} (x|meta|instagram)"
    r"|ads info|new unread posts"
    r"|unread notification"
    r"|opens profile photo"
    r"|not followed by anyone"
    r"|verified account\b"
    r"|\d+ views?\.\s*view post analytics)",
    re.IGNORECASE,
)

# El título de ventana de una página de resultados (nunca es un perfil)
_TITULO_RESULTADOS = re.compile(r"resultados de b[uú]squeda|search results|/\s*search", re.IGNORECASE)

# Enlaces externos/correos que aparecen en los perfiles (panel "Detalles" de FB,
# bio de IG...): JAMÁS son un resultado de búsqueda clicable válido — clicarlos
# saca al driver del perfil (p. ej. hacia la web del ayuntamiento).
_RE_LINK_EXTERNO = re.compile(
    r"@[\w.\-]+\.\w{2,}"            # correos
    r"|https?://|www\."             # urls explícitas
    r"|\b[\w\-]+\.(es|com|eus|org|net|cat|gal|info|edu)\b",  # dominios
    re.IGNORECASE,
)


def es_link_externo(texto: str) -> bool:
    return bool(_RE_LINK_EXTERNO.search(texto or ""))


# Filas del historial de búsqueda ("dssgazteria Eliminar dssgazteria del
# historial"): parecen resultados pero llevan a la página de resultados
_RE_HISTORIAL = re.compile(r"del historial|historial de|search history|recent searches", re.IGNORECASE)


def es_fila_historial(texto: str) -> bool:
    return bool(_RE_HISTORIAL.search(texto or ""))


def _compactar(texto: str) -> str:
    return re.sub(r"[\s._@\-]", "", normalizar(texto))


def similitud_handle(texto: str, handle: str) -> float:
    """
    Similitud difusa entre un texto de resultado y un handle esperado.
    Las apps muestran el NOMBRE de la página, no el handle: 'Donostia Gazteria'
    vs 'dssgazteria' deben parecerse lo bastante para INTENTAR el clic
    (la verificación dura llega después, ya dentro del perfil).
    """
    a, b = _compactar(texto), _compactar(handle)
    if not a or not b:
        return 0.0
    if b in a or a in b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class DriverBase:
    red = ""
    buscador_re = r"buscar|search"
    # Fases de exploración de la búsqueda; X salta las sugerencias
    fases_busqueda = ("sugerencias", "resultados")
    # Filtro/pestaña a clicar en la página de resultados (Personas, Páginas...)
    filtro_resultados_re: str | None = None

    def __init__(self, ventana, guard):
        self.ventana = ventana
        self.guard = guard

    # ── primitivas (UN solo paseo del árbol UIA por llamada) ──

    def _paseo(self) -> list[tuple[str, str, object]]:
        """Recorre el árbol UIA una sola vez: [(control_type, texto, elemento)]."""
        self.guard.verificar()
        try:
            elementos = self.ventana.descendants()
        except Exception as e:
            logger.debug(f"[{self.red}] Error leyendo árbol UIA: {e}")
            return []
        resultado = []
        for el in elementos:
            try:
                tipo = el.element_info.control_type
                texto = (el.window_text() or "").strip()
            except Exception:
                continue
            resultado.append((tipo, texto, el))
        return resultado

    def _texto_visible(self) -> list[str]:
        textos = []
        for _tipo, t, _el in self._paseo():
            if len(t) >= 3 and not _RUIDO_UI.match(t):
                textos.append(t)
        return textos

    def _ancestro_clicable(self, elemento, max_niveles: int = 6):
        actual = elemento
        for _ in range(max_niveles):
            try:
                actual = actual.parent()
            except Exception:
                return None
            if actual is None:
                return None
            try:
                tipo = actual.element_info.control_type
            except Exception:
                continue
            if tipo in _TIPOS_CLICABLES:
                return actual
            if tipo in ("Window", "Pane") and getattr(actual, "handle", None) == self.ventana.handle:
                return None
        return None

    # ── operaciones de alto nivel ──

    def abrir_perfil(self, url: str) -> bool:
        """
        Navega directamente a la URL del perfil oficial usando la barra de
        direcciones del navegador (Ctrl+L).
        """
        self.guard.activar()
        # Enfocar barra de direcciones y escribir URL
        self.guard.teclear_seguro("^l", con_espacios=False)
        time.sleep(0.5)
        self.guard.teclear_seguro(url)
        self.guard.teclear_seguro("{ENTER}", con_espacios=False)
        
        # Esperar a que cargue la página
        time.sleep(4.0)
        logger.info(f"[{self.red}] Navegación directa completada: {url}")
        return True


    def extraer_handle_visible(self) -> str | None:
        try:
            m = re.search(r"@([a-z0-9._]{2,30})", self.ventana.window_text() or "", re.IGNORECASE)
            if m:
                return m.group(1).lower()
        except Exception:
            pass
        for t in self._texto_visible()[:60]:
            m = re.search(r"@([a-z0-9._]{2,30})", t, re.IGNORECASE)
            if m:
                return m.group(1).lower()
        return None

    def _perfil_abierto(self, handle_esperado: str | None = None, candidato_nombre: str | None = None) -> bool:
        try:
            titulo = self.ventana.window_text() or ""
        except Exception:
            titulo = ""
        if not titulo:
            return False
        if _TITULO_RESULTADOS.search(titulo):
            return False

        norm_titulo = normalizar(titulo)

        if handle_esperado:
            h_norm = normalizar(handle_esperado)
            h_compact = _compactar(handle_esperado)
            if h_norm in norm_titulo or h_compact in _compactar(titulo):
                return True

        if candidato_nombre:
            c_norm = normalizar(candidato_nombre)
            if c_norm in norm_titulo:
                return True
            if similitud_handle(titulo, candidato_nombre) >= 0.55:
                return True

        return False

    def _verificar_perfil_con_handle(self, handle: str, candidato_nombre: str | None = None) -> bool:
        if not self._perfil_abierto(handle, candidato_nombre):
            return False
        if self._perfil_abierto(handle, None):
            return True
        if candidato_nombre and self._perfil_abierto(None, candidato_nombre):
            return True
        vis = self.extraer_handle_visible()
        if vis and (normalizar(vis) == normalizar(handle) or _compactar(vis) == _compactar(handle)):
            return True
        return False

    # ── lectura del perfil (helpers compartidos) ──

    def _limite_antiguedad(self) -> date:
        return date.today() - timedelta(days=30 * SOCIAL_POST_MONTHS_BACK)

    def extraer_ficha(self) -> dict:
        """
        Ficha del perfil abierto (panel Detalles/bio): webs, emails, seguidores,
        handle visible. La web de la bio es la señal de validación más fuerte
        (se cruza con el sitio_web del lugar en el runner).
        """
        try:
            titulo = self.ventana.window_text() or ""
        except Exception:
            titulo = ""
        ficha = extraer_datos_ficha(self._texto_visible()[:150], titulo)
        ficha["handle_visible"] = self.extraer_handle_visible()
        return ficha

    def _clave_contenedor(self, elemento, max_niveles: int = 8):
        """Identifica el contenedor 'post/artículo' de un texto para el clustering."""
        try:
            alto_ventana = self.ventana.rectangle().height() or 800
        except Exception:
            alto_ventana = 800
        actual = elemento
        for _ in range(max_niveles):
            try:
                actual = actual.parent()
            except Exception:
                return None
            if actual is None:
                return None
            try:
                tipo = actual.element_info.control_type
                rc = actual.rectangle()
            except Exception:
                continue
            if tipo in ("ListItem", "Group") and 100 <= rc.height() <= alto_ventana * 1.3:
                try:
                    rid = tuple(actual.element_info.runtime_id or ())
                except Exception:
                    rid = ()
                return rid or (rc.left, rc.top, rc.right, rc.bottom)
            if tipo == "Window":
                return None
        return None

    def _cosechar_items_visibles(self, vistos: set) -> list[dict]:
        """
        Textos y enlaces de fecha visibles CON su rectángulo y contenedor,
        para agruparlos en posts individuales (agrupar_posts).
        Filtra ruido de UI y restringe a la zona central de la ventana.
        """
        # Zona central: excluir sidebar izquierda (~20%) y panel derecho (~25%)
        try:
            wr = self.ventana.rectangle()
            ancho = wr.right - wr.left
            zona_izq = wr.left + int(ancho * 0.18)
            zona_der = wr.right - int(ancho * 0.22)
        except Exception:
            zona_izq, zona_der = 0, 99999

        items = []
        for tipo, texto, el in self._paseo():
            if tipo not in ("Text", "Hyperlink"):
                continue
            if not texto or len(texto) < 4 or _RUIDO_UI.match(texto):
                continue
            if len(texto) < 120 and _RUIDO_UI_LARGO.search(texto):
                continue
            if texto in vistos:
                continue
            try:
                rc = el.rectangle()
            except Exception:
                continue
            if rc.width() <= 0 or rc.height() <= 0:
                continue
            # Filtro de zona: el centro del elemento debe estar en el área de contenido
            cx = (rc.left + rc.right) // 2
            if cx < zona_izq or cx > zona_der:
                continue
            vistos.add(texto)
            items.append({
                "texto": texto,
                "left": rc.left, "top": rc.top, "right": rc.right, "bottom": rc.bottom,
                "clave": self._clave_contenedor(el),
            })
            if len(items) >= 120:
                break
        return items

    def _recorrer_timeline(self, dir_capturas: str, prefijo: str, posts: list,
                           vistos: set, inicio: float, max_scrolls: int) -> None:
        """
        Scroll con PGDN cosechando POSTS individuales (clustering por contenedor
        y banda vertical). Reglas de parada:
        - 3 posts fechados consecutivos con ≥ 1 año (y nunca en los 2 primeros
          viewports: ahí viven Destacados/cabecera con fechas viejas);
        - 2 capturas idénticas seguidas (el scroll ya no avanza).
        Los posts viejos individuales se descartan sin abortar el resto.
        """
        limite = self._limite_antiguedad()
        viejos_consecutivos = 0
        hash_anterior = None
        capturas_iguales = 0

        for n in range(max_scrolls):
            if time.time() - inicio > SOCIAL_MAX_MINUTES_PER_PROFILE * 60:
                logger.info(f"[{self.red}] Tiempo máximo por perfil alcanzado.")
                return
            if len(posts) >= SOCIAL_MAX_POSTS_PER_PROFILE:
                return

            clusters = agrupar_posts(self._cosechar_items_visibles(vistos))

            ruta_captura = os.path.join(dir_capturas, f"{prefijo}_{n:02d}.png")
            if not self.guard.captura_ventana(ruta_captura):
                ruta_captura = None
            hash_c = hash_perceptual(ruta_captura) if ruta_captura else None
            if hash_c and hash_c == hash_anterior:
                capturas_iguales += 1
                if capturas_iguales >= 2:
                    logger.info(f"[{self.red}] El scroll ya no avanza: fin del feed.")
                    return
            else:
                capturas_iguales = 0
            hash_anterior = hash_c

            for cluster in clusters:
                fecha = parsear_fecha_post(cluster["texto"])
                if fecha and fecha < limite:
                    viejos_consecutivos += 1
                    if n >= 2 and viejos_consecutivos >= 3:
                        logger.info(
                            f"[{self.red}] 3 posts consecutivos de hace ≥ 1 año: fin del recorrido."
                        )
                        return
                    continue  # post viejo individual: fuera, sin abortar el resto
                if fecha:
                    viejos_consecutivos = 0
                if len(cluster["texto"]) < 15 and not ruta_captura:
                    continue
                fecha_iso = fecha.isoformat() if fecha else None
                posts.append({
                    "texto": cluster["texto"],
                    "fecha": fecha_iso,
                    "fecha_publicacion": fecha_iso,
                    "captura": ruta_captura,
                    "hash_captura": hash_c,
                    "url_post": None,
                })
                if len(posts) >= SOCIAL_MAX_POSTS_PER_PROFILE:
                    return

            self.guard.verificar()
            self.guard.teclear_seguro("{PGDN}", con_espacios=False)
            time.sleep(1.5)

    def _abrir_primer_elemento_galeria(self, umbral_ratio: float = 0.28) -> bool:
        """
        Clica el primer elemento de una cuadrícula de publicaciones/fotos:
        el clicable más arriba-a-la-izquierda del área de contenido.
        """
        l, t, r, b = self.guard.rect()
        umbral_cabecera = t + int((b - t) * umbral_ratio)
        candidatas = []
        for tipo, texto, el in self._paseo():
            if tipo not in ("Hyperlink", "Image", "Button", "ListItem"):
                continue
            if es_link_externo(texto):
                continue
            try:
                rc = el.rectangle()
            except Exception:
                continue
            if rc.top < umbral_cabecera or rc.width() < 80 or rc.height() < 80:
                continue
            candidatas.append((rc.top, rc.left, el))

        candidatas.sort(key=lambda c: (c[0], c[1]))
        for _top, _left, el in candidatas[:3]:
            if self.guard.click_seguro(el):
                time.sleep(2.5)
                logger.info(f"[{self.red}] Primer elemento de la galería abierto.")
                return True
        logger.warning(f"[{self.red}] No se pudo abrir el primer elemento de la galería.")
        return False

    def _recorrer_visor(self, dir_capturas: str, prefijo: str, posts: list,
                        vistos: set, inicio: float, max_items: int | None = None) -> None:
        """
        Recorre el visor de publicaciones/fotos con la FLECHA DERECHA (cada
        posición = UN post, con su fecha). Fin de galería: 2 capturas idénticas
        seguidas (la flecha ya no avanza). 2 posts fechados viejos seguidos
        también paran (el visor va en orden cronológico). ESC al terminar.
        """
        limite = self._limite_antiguedad()
        max_items = max_items or SOCIAL_MAX_POSTS_PER_PROFILE
        hash_anterior = None
        capturas_iguales = 0
        viejos_consecutivos = 0

        try:
            for n in range(max_items):
                if time.time() - inicio > SOCIAL_MAX_MINUTES_PER_PROFILE * 60:
                    logger.info(f"[{self.red}] Tiempo máximo por perfil alcanzado.")
                    return
                if len(posts) >= SOCIAL_MAX_POSTS_PER_PROFILE:
                    return

                items = self._cosechar_items_visibles(vistos)
                texto_post = "\n".join(
                    it["texto"] for it in sorted(items, key=lambda x: (x["top"], x["left"]))
                )[:2500]
                fecha = parsear_fecha_post(texto_post)

                ruta_captura = os.path.join(dir_capturas, f"{prefijo}_{n:02d}.png")
                if not self.guard.captura_ventana(ruta_captura):
                    ruta_captura = None
                hash_c = hash_perceptual(ruta_captura) if ruta_captura else None
                if hash_c and hash_c == hash_anterior:
                    capturas_iguales += 1
                    if capturas_iguales >= 2:
                        logger.info(f"[{self.red}] Fin de la galería (la flecha ya no avanza).")
                        return
                else:
                    capturas_iguales = 0
                hash_anterior = hash_c

                if fecha and fecha < limite:
                    viejos_consecutivos += 1
                    logger.info(f"[{self.red}] Elemento de {fecha} (≥ 1 año): descartado.")
                    if viejos_consecutivos >= 2:
                        logger.info(f"[{self.red}] 2 elementos antiguos seguidos: fin del visor.")
                        return
                else:
                    viejos_consecutivos = 0
                    if texto_post or ruta_captura:
                        fecha_iso = fecha.isoformat() if fecha else None
                        posts.append({
                            "texto": texto_post,
                            "fecha": fecha_iso,
                            "fecha_publicacion": fecha_iso,
                            "captura": ruta_captura,
                            "hash_captura": hash_c,
                            "url_post": None,
                        })

                self.guard.verificar()
                self.guard.teclear_seguro("{RIGHT}", con_espacios=False)
                time.sleep(1.8)
        finally:
            # Cerrar el visor pase lo que pase
            try:
                self.guard.teclear_seguro("{ESC}", con_espacios=False)
                time.sleep(1.0)
            except Exception:
                pass

    def _clicar_seccion(self, patron_re: str) -> bool:
        """Clica una pestaña/sección del perfil por nombre exacto (Fotos, Publicaciones...)."""
        patron = re.compile(patron_re, re.IGNORECASE)
        for tipo, texto, el in self._paseo():
            if tipo not in ("Hyperlink", "Button", "TabItem", "MenuItem", "ListItem", "Text"):
                continue
            if not patron.fullmatch(texto.strip()):
                continue
            objetivo = el if tipo != "Text" else (self._ancestro_clicable(el) or el)
            if self.guard.click_seguro(objetivo):
                logger.info(f"[{self.red}] Sección '{texto}' abierta.")
                time.sleep(2.5)
                return True
        logger.info(f"[{self.red}] No se encontró la sección {patron_re}.")
        return False

    def leer_perfil_abierto(self, lugar_id: str, dir_capturas: str, anno: int) -> list[dict]:
        """
        Lee EXCLUSIVAMENTE el perfil abierto (verificado por el llamador),
        scrolleando el timeline. FILTRO DE FECHA: nada de hace 1 año o más.
        """
        os.makedirs(dir_capturas, exist_ok=True)
        posts: list[dict] = []
        vistos: set[str] = set()
        inicio = time.time()
        self._recorrer_timeline(dir_capturas, self.red, posts, vistos, inicio, SOCIAL_MAX_SCROLLS)
        logger.info(f"[{self.red}] Leídos {len(posts)} bloques de {lugar_id}.")
        return posts


class InstagramApp(DriverBase):
    red = "instagram"
    buscador_re = r"b[uú]squeda|buscar|search"

    def leer_perfil_abierto(self, lugar_id: str, dir_capturas: str, anno: int) -> list[dict]:
        """
        Instagram no expone los captions en la cuadrícula: se abre la primera
        publicación y se avanza post a post con la FLECHA DERECHA.
        """
        os.makedirs(dir_capturas, exist_ok=True)
        if not self._abrir_primer_elemento_galeria():
            # Fallback: al menos capturas de la cuadrícula
            return super().leer_perfil_abierto(lugar_id, dir_capturas, anno)

        posts: list[dict] = []
        vistos: set[str] = set()
        inicio = time.time()
        self._recorrer_visor(dir_capturas, "instagram", posts, vistos, inicio)
        logger.info(f"[instagram] Leídos {len(posts)} posts de {lugar_id}.")
        return posts


class FacebookApp(DriverBase):
    red = "facebook"
    buscador_re = r"b[uú]squeda|buscar|search"
    # En la página de resultados, restringir a Páginas (perfiles oficiales)
    filtro_resultados_re = r"p[aá]ginas|pages"

    def _ir_a_inicio(self) -> bool:
        """Vuelve a la home de FB (donde SIEMPRE está el ComboBox 'Buscar en Facebook')."""
        for tipo, texto, el in self._paseo():
            if tipo not in ("Hyperlink", "Button"):
                continue
            if re.fullmatch(r"(facebook|inicio|home)", (texto or "").strip(), re.IGNORECASE):
                if self.guard.click_seguro(el):
                    logger.info("[facebook] Vuelta a Inicio para recuperar el buscador.")
                    time.sleep(2.5)
                    return True
        return False

    def _escribir_en_buscador(self, consulta: str) -> bool:
        if super()._escribir_en_buscador(consulta):
            return True
        # La ventana quedó en una página sin buscador (tras una tarea anterior):
        # volver a Inicio y reintentar
        if self._ir_a_inicio():
            return super()._escribir_en_buscador(consulta)
        return False

    def _leer_destacados(self, dir_capturas: str, posts: list, vistos: set, inicio: float):
        """
        Los ayuntamientos suelen FIJAR el programa de fiestas en Destacados.
        Abre la primera tarjeta bajo el rótulo 'Destacados' y la recorre con
        el visor (el filtro de ≥ 1 año descarta los destacados viejos).
        """
        ancla = None
        for tipo, texto, el in self._paseo():
            if tipo == "Text" and re.fullmatch(r"(destacados|featured)", texto.strip(), re.IGNORECASE):
                try:
                    ancla = el.rectangle()
                except Exception:
                    pass
                break
        if ancla is None:
            return

        tarjetas = []
        for tipo, texto, el in self._paseo():
            if tipo not in ("Hyperlink", "Button", "ListItem", "Image"):
                continue
            if es_link_externo(texto):
                continue
            try:
                rc = el.rectangle()
            except Exception:
                continue
            if ancla.bottom <= rc.top <= ancla.bottom + 320 and rc.width() >= 60 and rc.height() >= 60:
                tarjetas.append((rc.left, el))

        tarjetas.sort(key=lambda c: c[0])
        for _left, el in tarjetas[:2]:
            if self.guard.click_seguro(el):
                time.sleep(2.5)
                logger.info("[facebook] Destacados abiertos.")
                self._recorrer_visor(dir_capturas, "facebook_destacado", posts, vistos, inicio, max_items=8)
                return

    def leer_perfil_abierto(self, lugar_id: str, dir_capturas: str, anno: int) -> list[dict]:
        """
        Facebook, en tres fases:
        1. Destacados (ahí se fija el programa de fiestas).
        2. Feed de Publicaciones: scroll corto cosechando posts individuales.
        3. Sección Fotos: primera foto + FLECHA DERECHA foto a foto.
        El driver NUNCA sale del perfil: los enlaces externos están vetados.
        """
        os.makedirs(dir_capturas, exist_ok=True)
        posts: list[dict] = []
        vistos: set[str] = set()
        inicio = time.time()

        # Fase 1: Destacados
        self._leer_destacados(dir_capturas, posts, vistos, inicio)

        # Fase 2: feed de publicaciones (presupuesto corto de scrolls)
        if len(posts) < SOCIAL_MAX_POSTS_PER_PROFILE:
            self._recorrer_timeline(
                dir_capturas, "facebook_feed", posts, vistos, inicio,
                max_scrolls=max(3, SOCIAL_MAX_SCROLLS // 3),
            )

        # Fase 3: sección Fotos con visor
        if len(posts) < SOCIAL_MAX_POSTS_PER_PROFILE:
            if self._clicar_seccion(r"^(fotos|photos|ver todas las fotos)$"):
                if self._abrir_primer_elemento_galeria(umbral_ratio=0.20):
                    self._recorrer_visor(dir_capturas, "facebook_foto", posts, vistos, inicio)
                self._volver_atras()  # de la sección Fotos al perfil

        logger.info(f"[facebook] Leídos {len(posts)} bloques de {lugar_id}.")
        return posts


class XApp(DriverBase):
    red = "twitter"
    buscador_re = r"buscar|search|b[uú]squeda"
    # Ir SIEMPRE a la página de resultados y a la pestaña Personas:
    # en "Top" aparece contenido de cualquier cuenta (falsos positivos)
    fases_busqueda = ("resultados",)
    filtro_resultados_re = r"personas|people"

    def _escribir_en_buscador(self, consulta: str) -> bool:
        # La web de X tiene el atajo "/" para enfocar el buscador
        try:
            self.guard.activar()
            self.guard.teclear_seguro("/", con_espacios=False)
            time.sleep(0.8)
            self.guard.teclear_seguro("^a{DELETE}", con_espacios=False)
            self.guard.teclear_seguro(consulta)
            time.sleep(2.0)
            return True
        except Exception as e:
            logger.debug(f"[twitter] Atajo '/' falló: {e}")
        return super()._escribir_en_buscador(consulta)


DRIVERS = {
    "instagram": InstagramApp,
    "facebook": FacebookApp,
    "twitter": XApp,
}

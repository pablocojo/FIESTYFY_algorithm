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
    r"ver m[aá]s|see more|\d+\s*(me gusta|likes?|comentarios?|comments?))$",
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

    # ── buscador ──

    def _encontrar_edit_busqueda(self, paseo=None):
        patron = re.compile(self.buscador_re, re.IGNORECASE)
        paseo = paseo if paseo is not None else self._paseo()
        edits = []
        for tipo, texto, el in paseo:
            if tipo not in ("Edit", "ComboBox"):
                continue
            try:
                nombre = f"{texto} {el.element_info.name or ''}"
            except Exception:
                nombre = texto
            edits.append((el, nombre))
        for el, nombre in edits:
            if patron.search(nombre):
                return el
        if len(edits) == 1:
            return edits[0][0]
        return None

    def _abrir_buscador(self):
        """
        Devuelve el Edit del buscador. En las PWAs (p. ej. Instagram) el
        buscador es un ICONO del carril lateral que abre el panel: si no hay
        Edit visible, se clica el icono "Buscar/Search" (una sola vez por
        nombre: su Image gemela lo volvería a cerrar) y se espera al campo.
        """
        paseo = self._paseo()
        edit = self._encontrar_edit_busqueda(paseo)
        if edit is not None:
            return edit

        patron = re.compile(self.buscador_re, re.IGNORECASE)
        nombres_clicados: set[str] = set()
        for tipo, texto, el in paseo:
            if tipo not in ("Button", "Hyperlink", "TabItem", "MenuItem", "ListItem", "Text", "Image"):
                continue
            try:
                nombre = f"{texto} {el.element_info.name or ''}".strip()
            except Exception:
                nombre = texto
            if not patron.search(nombre):
                continue
            clave = normalizar(nombre)
            if clave in nombres_clicados:
                continue  # el mismo control expone Hyperlink + Image con igual nombre
            nombres_clicados.add(clave)
            objetivo = el if tipo != "Text" else (self._ancestro_clicable(el) or el)
            if not self.guard.click_seguro(objetivo):
                continue
            # Esperar a que el panel exponga el campo de texto
            for _ in range(4):
                time.sleep(1.0)
                edit = self._encontrar_edit_busqueda()
                if edit is not None:
                    return edit
            if len(nombres_clicados) >= 3:
                break
        return None

    def _escribir_en_buscador(self, consulta: str) -> bool:
        control = self._abrir_buscador()
        if control is None:
            logger.warning(f"[{self.red}] No se encontró el buscador interno.")
            return False
        if not self.guard.click_seguro(control):
            return False
        time.sleep(0.8)
        self.guard.teclear_seguro("^a{DELETE}", con_espacios=False)
        self.guard.teclear_seguro(consulta)
        time.sleep(2.5)  # dejar que carguen las sugerencias
        return True

    # ── candidatos y fases de resultados ──

    def _candidatos_de_busqueda(self, consulta: str) -> list[tuple[str, object]]:
        """Filas de resultado clicables con su texto (excluye el eco de la consulta)."""
        consulta_norm = normalizar(consulta)
        paseo = self._paseo()
        candidatos = []
        vistos_textos = set()

        def _agregar(texto, elemento):
            if not texto or len(texto) < 3 or _RUIDO_UI.match(texto):
                return
            if es_link_externo(texto):
                return  # enlaces/correos de paneles de perfil: nunca son resultados
            if es_fila_historial(texto):
                return  # filas del historial de búsqueda: no llevan al perfil
            if normalizar(texto) == consulta_norm or texto in vistos_textos:
                return
            vistos_textos.add(texto)
            candidatos.append((texto, elemento))

        for tipo, texto, el in paseo:
            if tipo in _TIPOS_CLICABLES:
                _agregar(texto, el)
        for tipo, texto, el in paseo:
            if tipo == "Text" and texto and len(texto) >= 3:
                ancestro = self._ancestro_clicable(el)
                if ancestro is not None:
                    _agregar(texto, ancestro)
        return candidatos

    def _clicar_filtro_resultados(self) -> bool:
        """Clica la pestaña/filtro de la página de resultados (Personas, Páginas...)."""
        if not self.filtro_resultados_re:
            return True
        patron = re.compile(self.filtro_resultados_re, re.IGNORECASE)
        for tipo, texto, el in self._paseo():
            if tipo not in ("Hyperlink", "Button", "TabItem", "MenuItem", "ListItem", "Text"):
                continue
            if not patron.fullmatch(texto.strip()):
                continue
            objetivo = el if tipo != "Text" else (self._ancestro_clicable(el) or el)
            if self.guard.click_seguro(objetivo):
                logger.info(f"[{self.red}] Filtro de resultados '{texto}' seleccionado.")
                time.sleep(2.0)
                return True
        logger.info(f"[{self.red}] No se encontró el filtro '{self.filtro_resultados_re}' en resultados.")
        return False

    def _preparar_fase_resultados(self):
        """ENTER hacia la página de resultados completa + filtro propio de la app."""
        self.guard.teclear_seguro("{ENTER}", con_espacios=False)
        time.sleep(3.0)
        self._clicar_filtro_resultados()

    # ── verificación de navegación ──

    def _perfil_abierto(self, handle: str | None = None, nombre: str | None = None) -> bool:
        try:
            titulo = self.ventana.window_text() or ""
        except Exception:
            return False
        if _TITULO_RESULTADOS.search(titulo):
            return False
        titulo_comp = _compactar(titulo)
        if handle and _compactar(handle) and _compactar(handle) in titulo_comp:
            return True
        if nombre and normalizar(nombre) and normalizar(nombre) in normalizar(titulo):
            return True
        return False

    def _verificar_perfil_con_handle(self, handle: str, texto_candidato: str | None = None) -> bool:
        """
        Verificación post-clic de que estamos en el perfil correcto:
        1. el handle aparece en el título o el contenido visible; o
        2. el título contiene el NOMBRE del candidato clicado (Facebook no
           muestra el handle en la página: 'Donostia Gazteria' titula la
           ventana, y ese candidato ya pasó la pre-validación contra el handle).
        Sin confirmación NO se lee nada.
        """
        if self._perfil_abierto(handle=handle):
            return True
        try:
            titulo = self.ventana.window_text() or ""
        except Exception:
            return False
        if _TITULO_RESULTADOS.search(titulo):
            return False

        objetivo = _compactar(handle)
        if objetivo:
            for t in self._texto_visible()[:120]:
                if objetivo in _compactar(t):
                    return True

        if texto_candidato and self._perfil_abierto(nombre=texto_candidato):
            logger.info(
                f"[{self.red}] Perfil verificado por nombre de página "
                f"('{texto_candidato[:40]}' en el título; el handle no es visible)."
            )
            return True
        if texto_candidato and self._parece_perfil_por_contenido(texto_candidato):
            return True
        return False

    def _parece_perfil_por_contenido(self, nombre_perfil: str) -> bool:
        """
        Verificación por CONTENIDO (el título de las PWAs tarda en actualizarse):
        el nombre del perfil clicado aparece en la página junto a señales de
        cabecera de perfil (seguidores/publicaciones). Nunca en una página de
        resultados (excluida antes por el título).
        """
        objetivo = normalizar(nombre_perfil)
        if not objetivo:
            return False
        textos = self._texto_visible()[:100]
        nombre_visto = any(objetivo in normalizar(t) for t in textos)
        senal_perfil = any(
            re.search(r"seguidores|followers|publicaciones|posts|siguiendo|following", t, re.IGNORECASE)
            for t in textos
        )
        if nombre_visto and senal_perfil:
            logger.info(f"[{self.red}] Perfil verificado por contenido ('{nombre_perfil[:40]}' + cabecera).")
            return True
        return False

    def _verificar_con_espera(self, verificar, texto: str, intentos: int = 4, espera: float = 2.0) -> bool:
        """El título/árbol de las PWAs tarda en reflejar la navegación: reintentar."""
        for i in range(intentos):
            if verificar(texto):
                return True
            if i < intentos - 1:
                time.sleep(espera)
        return False

    def _volver_atras(self):
        self.guard.teclear_seguro("%{LEFT}", con_espacios=False)
        time.sleep(2.0)

    def _tab_walk_activar(self, es_valido, max_tabs: int = 40) -> str | None:
        """
        Fallback por TECLADO cuando el árbol UIA no expone los resultados
        (Chromium a veces no materializa el contenido web): TAB recorre los
        elementos accionables, el FOCO fuerza a materializar cada nodo, se lee
        su nombre y con ENTER se activa el que valida. Sin ratón, sin árbol.
        """
        logger.info(f"[{self.red}] Árbol UIA sin resultados: fallback por teclado (TAB)...")
        for _ in range(max_tabs):
            self.guard.verificar()
            self.guard.teclear_seguro("{TAB}", con_espacios=False)
            time.sleep(0.3)
            nombre = nombre_elemento_con_foco() or ""
            if len(nombre) < 3 or _RUIDO_UI.match(nombre):
                continue
            if es_link_externo(nombre) or es_fila_historial(nombre):
                continue
            if es_valido(nombre):
                logger.info(f"[{self.red}] TAB-walk: activando '{nombre[:50]}'")
                self.guard.teclear_seguro("{ENTER}", con_espacios=False)
                time.sleep(3.0)
                return nombre
        return None

    def _explorar_candidatos(self, consulta: str, es_valido, verificar) -> str | None:
        """
        Recorre las fases de búsqueda de la app: clic → verificar (con espera:
        el título tarda en actualizarse) → si falla, atrás y siguiente.
        Si el árbol UIA no expone resultados, fallback por teclado (TAB-walk).
        """
        intentados: set[str] = set()
        for fase in self.fases_busqueda:
            if fase == "resultados":
                self._preparar_fase_resultados()
            for intento in range(4):
                candidatos = self._candidatos_de_busqueda(consulta)
                validos = [
                    (texto, el) for texto, el in candidatos
                    if texto not in intentados and es_valido(texto)
                ]
                if not validos:
                    if intento < 3:
                        time.sleep(1.5)
                        continue
                    muestra = [t[:45] for t, _ in candidatos[:6]]
                    logger.info(
                        f"[{self.red}] Fase '{fase}': ningún candidato válido "
                        f"entre {len(candidatos)} vistos. Muestra: {muestra}"
                    )
                    # El árbol no expone los resultados → recorrido por teclado
                    if fase == "resultados":
                        nombre = self._tab_walk_activar(es_valido)
                        if nombre and self._verificar_con_espera(verificar, nombre):
                            return nombre
                        if nombre:
                            self._volver_atras()
                    break
                texto, el = validos[0]
                intentados.add(texto)
                if not self.guard.click_seguro(el):
                    continue
                time.sleep(3.0)
                if self._verificar_con_espera(verificar, texto):
                    return texto
                logger.info(
                    f"[{self.red}] '{texto[:50]}' no llevó al perfil esperado "
                    f"(título: '{self.ventana.window_text()[:50]}'). Atrás."
                )
                self._volver_atras()
        return None

    # ── operaciones de alto nivel ──

    def abrir_perfil(self, handle: str, nombre_localidad: str) -> bool:
        """
        Abre un perfil YA VERIFICADO en la Etapa B buscando su handle.
        Pre-validación laxa (las apps muestran nombres, no handles) +
        verificación dura del handle dentro del perfil.
        """
        self.guard.activar()
        if not self._escribir_en_buscador(handle):
            return False

        def es_valido(texto: str) -> bool:
            ok, _ = validar_candidato_perfil(texto, nombre_localidad, handle_esperado=handle)
            return ok or similitud_handle(texto, handle) >= 0.55

        hallado = self._explorar_candidatos(
            handle, es_valido, lambda t: self._verificar_perfil_con_handle(handle, t)
        )
        if hallado:
            logger.info(f"[{self.red}] Perfil abierto y verificado: {handle}")
            return True
        logger.warning(f"[{self.red}] No se pudo abrir el perfil '{handle}'.")
        return False

    def buscar_perfil(self, nombre_localidad: str, nombre_municipio: str) -> dict | None:
        """
        Busca el perfil OFICIAL de una localidad sin URL previa. Validación
        estricta (nombre completo + marcador institucional) y verificación
        de la navegación antes de dar el perfil por bueno.
        """
        self.guard.activar()
        for consulta in (f"ayuntamiento {nombre_localidad}", f"ayuntamiento de {nombre_localidad}"):
            if not self._escribir_en_buscador(consulta):
                return None

            def es_valido(texto: str) -> bool:
                return validar_candidato_perfil(texto, nombre_localidad)[0]

            def verificar(texto: str) -> bool:
                if self._perfil_abierto(None, texto):
                    return True
                try:
                    if _TITULO_RESULTADOS.search(self.ventana.window_text() or ""):
                        return False
                except Exception:
                    return False
                return self._parece_perfil_por_contenido(texto)

            hallado = self._explorar_candidatos(consulta, es_valido, verificar)
            if hallado:
                logger.info(f"[{self.red}] Perfil oficial verificado: {hallado!r}")
                return {"texto": hallado, "url": None}
        logger.info(f"[{self.red}] Sin perfil oficial concluyente para {nombre_localidad}.")
        return None

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
        """
        items = []
        for tipo, texto, el in self._paseo():
            if tipo not in ("Text", "Hyperlink"):
                continue
            if not texto or len(texto) < 4 or _RUIDO_UI.match(texto):
                continue
            if texto in vistos:
                continue
            try:
                rc = el.rectangle()
            except Exception:
                continue
            if rc.width() <= 0 or rc.height() <= 0:
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
                posts.append({
                    "texto": cluster["texto"],
                    "fecha": fecha.isoformat() if fecha else None,
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
                        posts.append({
                            "texto": texto_post,
                            "fecha": fecha.isoformat() if fecha else None,
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

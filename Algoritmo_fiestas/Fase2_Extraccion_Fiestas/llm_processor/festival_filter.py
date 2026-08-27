"""
Filtro determinista adaptativo de fiestas — post-LLM.

Reglas (según criterio_identificacion_fiestas.md + decisiones del usuario):
- Fiestas multi-día (fecha_inicio < fecha_fin): filtro regular — basta una señal
  de tipo fiesta, una señal nocturna o un programa con varios eventos.
- Fiestas de UN solo día: filtro estricto — requieren señal nocturna fuerte
  (orquesta, verbena, DJ, discomóvil, concierto...). Excepción: nombre claramente
  patronal o coincidencia con el día del santo patrón → se aceptan con confianza baja.
- Eventos completamente privados (discoteca, pub, sala de fiestas) → rechazados.
- sanear_fiesta() corrige fiestas mal formadas (nombre genérico, duración absurda,
  programa con fechas fuera de rango).
"""

import re
import logging
import unicodedata
from datetime import datetime, date

from config import FIESTA_MAX_DURACION_DIAS, FILTRO_MIN_EVENTOS_PROGRAMA

logger = logging.getLogger("festival_filter")


# ──────────────────────────────────────────────────
# NORMALIZACIÓN
# ──────────────────────────────────────────────────

def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes, solo alfanumérico y espacios."""
    if not texto:
        return ""
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


# ──────────────────────────────────────────────────
# SEÑALES (keywords normalizadas, sin tildes)
# ──────────────────────────────────────────────────

# Señal FUERTE de fiesta nocturna/musical → aceptación automática (regla de oro del criterio)
SENALES_NOCTURNAS = [
    "orquesta", "verbena", "dj", "djs", "deejay",
    "disco movil", "discomovil", "discoteca movil", "macrodiscoteca", "macro discoteca",
    "concierto", "conciertos", "actuacion musical", "actuaciones musicales",
    "musica en directo", "musica en vivo", "grupo musical", "grupos musicales",
    "festival", "baile", "sesion de baile", "gaupasa", "txosna", "txosnas",
    "charanga", "txaranga", "batucada", "chupinazo",
    "correfoc", "revetlla", "foliada", "herri bazkaria",
]

# Señal de que la celebración es una fiesta popular reconocible
SENALES_TIPO_FIESTA = [
    "fiestas patronales", "fiesta patronal", "fiesta mayor", "fiestas mayores",
    "fiesta de", "fiestas de", "fiestas en honor", "fiesta en honor",
    "fiesta de verano", "fiestas de verano", "semana de fiestas", "semana grande",
    "feria", "ferias", "carnaval", "carnavales", "moros y cristianos",
    "romeria", "san juan", "hoguera", "hogueras", "pregon",
    "encierro", "encierros", "vaquillas", "toro de fuego",
    "gigantes y cabezudos", "pasacalles", "pena", "penas",
    "comida popular", "cena popular", "paella popular", "sardinada",
    "fiesta popular", "fiestas populares",
    "festa major", "festes patronals", "festas patronais", "cercavila", "kalejira", "hèsta major",
]

# Actos que por sí solos NO tienen carácter festivo (solo informativo para el motivo)
SENALES_NEGATIVAS = [
    "procesion", "misa", "eucaristia", "novena", "triduo", "ofrenda",
    "via crucis", "vigilia", "besamanos", "semana santa",
    "exposicion", "conferencia", "charla", "coloquio", "jornada", "jornadas",
    "pleno", "homenaje", "inauguracion", "presentacion",
]

# Indicadores de evento privado / local comercial (no fiesta de la localidad)
SENALES_PRIVADAS = [
    "discoteca", "pub", "sala de fiestas",
    "entrada vip", "entradas vip", "evento privado", "fiesta privada",
    "solo socios", "reservado el derecho de admision",
]

# Festivos del calendario laboral/escolar (días no lectivos SIN celebración propia).
# Nombres normalizados. NO incluye advocaciones patronales comunes (Asunción,
# Inmaculada, Todos los Santos...) para no matar fiestas patronales reales:
# esas se resuelven por la regla de evidencia de celebración.
FESTIVOS_CALENDARIO = [
    "ano nuevo", "dia de ano nuevo", "nochevieja", "nochebuena", "navidad",
    "reyes", "dia de reyes", "reyes magos", "epifania", "epifania del senor",
    "jueves santo", "viernes santo", "lunes de pascua", "pascua granada",
    "fiesta del trabajo", "dia del trabajo", "dia del trabajador", "dia internacional del trabajo",
    "dia de la hispanidad", "fiesta nacional de espana", "fiesta nacional",
    "dia de la constitucion",
    # Días de las comunidades autónomas
    "dia de andalucia", "dia de aragon", "dia de asturias", "dia de las islas baleares",
    "dia de les illes balears", "dia de canarias", "dia de cantabria",
    "dia de castilla la mancha", "dia de castilla y leon", "diada", "diada nacional de catalunya",
    "dia de la comunidad valenciana", "dia de la comunitat valenciana", "dia de extremadura",
    "dia nacional de galicia", "dia de la rioja", "dia de la comunidad de madrid",
    "dia de la region de murcia", "dia de navarra", "dia del pais vasco",
    "dia de ceuta", "dia de melilla",
]

# Señales de que el texto procede de un calendario laboral/escolar, no de una celebración
SENALES_CALENDARIO = [
    "calendario laboral", "calendario escolar", "no lectivo", "no lectivos",
    "dia festivo", "dias festivos", "festivo local", "festivos locales",
    "dia inhabil", "dias inhabiles", "apertura de comercios", "fiesta oficial",
]

# Señales FUERTES de celebración real (para rescatar festivos que sí son fiesta local)
TIPO_CELEBRACION_FUERTE = [
    "fiestas patronales", "fiesta patronal", "fiesta mayor", "fiestas mayores",
    "feria", "carnaval", "moros y cristianos", "romeria", "verbena", "encierro",
    "hoguera", "pasacalles", "comida popular", "cena popular", "charanga",
    "gigantes y cabezudos", "vaquillas", "toro de fuego",
    "festa major", "festes patronals", "festas patronais", "correfoc", "revetlla", "kalejira",
]

# Frases positivas que hay que enmascarar antes de buscar señales privadas
# ("discoteca movil" es señal festiva, no un local privado)
_MASCARAS_PRIVADAS = ["discoteca movil", "disco movil", "discomovil", "macrodiscoteca"]

# Nombre claramente patronal (excepción del filtro estricto de un día)
_RE_NOMBRE_PATRONAL = re.compile(
    r"\bfiestas?\b.*\bpatronal(es)?\b"
    r"|\b(festes|festas|jaiak|hèsta|festak)\b"
    r"|\bfiestas?\s+(en\s+honor\s+)?(a\s+|de\s+|del\s+|de\s+la\s+|de\s+los\s+|de\s+las\s+)?"
    r"(san|santa|santo|sant|virgen|cristo|santisimo|santisima|inmaculada|purisima|asuncion|nuestra\s+senora)\b"
    r"|\bpatron(a)?\b"
)

_NOMBRES_GENERICOS = {
    "fiesta", "fiestas", "evento", "eventos", "acto", "actos",
    "celebracion", "celebraciones", "programa", "programacion",
}


def _compilar(senales: list[str]) -> list[tuple[str, re.Pattern]]:
    return [(s, re.compile(rf"\b{re.escape(s)}\b")) for s in senales]


_RE_NOCTURNAS = _compilar(SENALES_NOCTURNAS)
_RE_TIPO_FIESTA = _compilar(SENALES_TIPO_FIESTA)
_RE_NEGATIVAS = _compilar(SENALES_NEGATIVAS)
_RE_PRIVADAS = _compilar(SENALES_PRIVADAS)
_RE_FESTIVOS_CAL = _compilar(FESTIVOS_CALENDARIO)
_RE_SENALES_CAL = _compilar(SENALES_CALENDARIO)
_RE_CELEBRACION_FUERTE = _compilar(TIPO_CELEBRACION_FUERTE)


def _buscar_senales(texto_norm: str, patrones: list[tuple[str, re.Pattern]]) -> list[str]:
    return [nombre for nombre, patron in patrones if patron.search(texto_norm)]


def _texto_de_fiesta(fiesta: dict) -> str:
    """Concatena nombre + descripción + descripciones de todos los eventos del programa."""
    partes = [fiesta.get("nombre", ""), fiesta.get("descripcion", "")]
    for dia in fiesta.get("programa", []) or []:
        if not isinstance(dia, dict):
            continue
        for evento in dia.get("eventos", []) or []:
            if isinstance(evento, dict):
                partes.append(evento.get("descripcion", ""))
    return " ".join(p for p in partes if p)


# ──────────────────────────────────────────────────
# SANEADO DE FIESTAS MAL FORMADAS
# ──────────────────────────────────────────────────

def _parsear_fecha(fecha_str) -> date | None:
    try:
        return datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def sanear_fiesta(fiesta: dict) -> dict | None:
    """
    Corrige o descarta fiestas mal formadas. Devuelve la fiesta saneada o None.
    Requiere fechas ya validadas en formato YYYY-MM-DD.
    """
    nombre = fiesta.get("nombre", "").strip()

    if len(nombre) < 4:
        logger.info(f"  [SANEADO] Nombre demasiado corto: '{nombre}'. Descartada.")
        return None

    if normalizar_texto(nombre) in _NOMBRES_GENERICOS:
        logger.info(f"  [SANEADO] Nombre genérico sin identidad: '{nombre}'. Descartada.")
        return None

    inicio = _parsear_fecha(fiesta.get("fecha_inicio"))
    fin = _parsear_fecha(fiesta.get("fecha_fin"))
    if not inicio or not fin:
        logger.info(f"  [SANEADO] '{nombre}' con fechas no parseables. Descartada.")
        return None

    duracion = (fin - inicio).days
    if duracion > FIESTA_MAX_DURACION_DIAS:
        logger.info(
            f"  [SANEADO] '{nombre}' dura {duracion} días (> {FIESTA_MAX_DURACION_DIAS}). "
            f"Probable alucinación. Descartada."
        )
        return None

    # Limpiar el programa: días con fecha inválida o fuera del rango de la fiesta
    programa_limpio = []
    for dia in fiesta.get("programa", []) or []:
        if not isinstance(dia, dict):
            continue
        fecha_dia = _parsear_fecha(dia.get("fecha"))
        if not fecha_dia or not (inicio <= fecha_dia <= fin):
            logger.info(f"  [SANEADO] '{nombre}': día de programa fuera de rango ({dia.get('fecha')}). Eliminado.")
            continue
        eventos = [e for e in (dia.get("eventos") or []) if isinstance(e, dict) and e.get("descripcion")]
        if not eventos:
            continue
        dia["eventos"] = eventos
        programa_limpio.append((fecha_dia, dia))

    # Renumerar los días de forma coherente con la fecha
    programa_limpio.sort(key=lambda x: x[0])
    for fecha_dia, dia in programa_limpio:
        dia["dia"] = (fecha_dia - inicio).days + 1

    fiesta["programa"] = [dia for _, dia in programa_limpio]
    return fiesta


# ──────────────────────────────────────────────────
# FILTRO ADAPTATIVO
# ──────────────────────────────────────────────────

def evaluar_fiesta(fiesta: dict, fecha_patron: date | None = None) -> tuple[bool, str, str | None]:
    """
    Decide si una fiesta es válida.

    Devuelve (aceptada, motivo, confianza_forzada):
    - confianza_forzada solo se rellena cuando la fiesta se acepta por la
      excepción patronal (un día sin evidencia nocturna) → "baja".
    """
    texto_norm = normalizar_texto(_texto_de_fiesta(fiesta))

    nocturnas = _buscar_senales(texto_norm, _RE_NOCTURNAS)
    tipo_fiesta = _buscar_senales(texto_norm, _RE_TIPO_FIESTA)
    negativas = _buscar_senales(texto_norm, _RE_NEGATIVAS)

    # Enmascarar frases positivas antes de detectar señales privadas
    def _enmascarar(texto: str) -> str:
        for mascara in _MASCARAS_PRIVADAS:
            texto = texto.replace(mascara, " ")
        return texto

    privadas = _buscar_senales(_enmascarar(texto_norm), _RE_PRIVADAS)
    privadas_en_nombre = _buscar_senales(
        _enmascarar(normalizar_texto(fiesta.get("nombre", ""))), _RE_PRIVADAS
    )

    # 1. Evento privado / de local comercial → fuera
    #    - señal privada en el NOMBRE: rechazo directo (p. ej. "Fiesta en Discoteca Luna")
    #    - señal privada en el resto del texto: solo se rechaza si no hay ninguna señal festiva
    if privadas_en_nombre:
        return False, f"nombre de evento privado/local comercial ({', '.join(privadas_en_nombre)})", None
    if privadas and not (tipo_fiesta or nocturnas):
        return False, f"evento privado/local comercial ({', '.join(privadas)})", None

    # 2. Festivos de calendario laboral/escolar: un día no lectivo NO es una fiesta.
    #    Solo se rescatan si hay evidencia de celebración real (música, programa,
    #    señal fuerte de celebración o coincidencia con el día del patrón).
    num_eventos = sum(len(d.get("eventos", [])) for d in fiesta.get("programa", []) or [])
    patron_en_rango = (
        fecha_patron is not None
        and fiesta.get("fecha_inicio", "") <= fecha_patron.isoformat() <= fiesta.get("fecha_fin", "")
    )
    celebracion_fuerte = _buscar_senales(texto_norm, _RE_CELEBRACION_FUERTE)
    evidencia_celebracion = bool(nocturnas or num_eventos >= 1 or celebracion_fuerte or patron_en_rango)

    nombre_norm = normalizar_texto(fiesta.get("nombre", ""))
    festivo_cal_nombre = _buscar_senales(nombre_norm, _RE_FESTIVOS_CAL)
    senales_cal = _buscar_senales(texto_norm, _RE_SENALES_CAL)

    if festivo_cal_nombre and not evidencia_celebracion:
        return False, f"festivo de calendario sin celebración ({festivo_cal_nombre[0]})", None
    if senales_cal and not evidencia_celebracion:
        return False, f"procede de calendario laboral/escolar sin celebración ({senales_cal[0]})", None

    un_dia = fiesta.get("fecha_inicio") == fiesta.get("fecha_fin")

    # 3. Multi-día → filtro regular
    if not un_dia:
        if nocturnas:
            return True, f"multi-día con actividad nocturna ({nocturnas[0]})", None
        if tipo_fiesta:
            return True, f"multi-día tipo fiesta ({tipo_fiesta[0]})", None
        if num_eventos >= FILTRO_MIN_EVENTOS_PROGRAMA:
            return True, f"multi-día con programa de {num_eventos} eventos", None
        motivo = "multi-día sin ninguna señal festiva"
        if negativas:
            motivo += f" (solo actos sueltos: {', '.join(negativas)})"
        return False, motivo, None

    # 4. Un solo día → filtro estricto
    if nocturnas:
        return True, f"un día con actividad nocturna ({nocturnas[0]})", None

    es_patronal = bool(_RE_NOMBRE_PATRONAL.search(nombre_norm))
    coincide_patron = (
        fecha_patron is not None
        and fiesta.get("fecha_inicio") == fecha_patron.isoformat()
    )

    if es_patronal or coincide_patron:
        motivo = "un día patronal sin evidencia nocturna"
        if coincide_patron:
            motivo += " (coincide con el día del patrón)"
        return True, motivo, "baja"

    motivo = "un solo día sin actividad festiva nocturna"
    if negativas:
        motivo += f" ({', '.join(negativas)})"
    return False, motivo, None


# ──────────────────────────────────────────────────
# FUSIÓN DE FIESTAS PRÓXIMAS (Problema 1)
# ──────────────────────────────────────────────────
from datetime import timedelta

def fusionar_fiestas_proximas(fiestas: list[dict]) -> list[dict]:
    """
    Fusiona fiestas de la misma localidad que se solapen o tengan una diferencia
    de 7 días o menos entre sí, asumiendo que pertenecen al mismo ciclo festivo,
    excepto si tienen nombres forzadamente distintos.
    """
    if not fiestas:
        return []

    # Excepciones que NUNCA deben fusionarse juntas
    NOMBRES_DISTINTOS_FORZADOS = [
        "carnaval", "san juan", "navidad", "semana santa", "corpus christi"
    ]

    def parse_fecha(f_str):
        try:
            return datetime.strptime(f_str, "%Y-%m-%d").date()
        except:
            return date.max

    validas = [f for f in fiestas if _parsear_fecha(f.get("fecha_inicio")) and _parsear_fecha(f.get("fecha_fin"))]
    invalidas = [f for f in fiestas if f not in validas]

    validas.sort(key=lambda f: parse_fecha(f.get("fecha_inicio")))

    fusionadas = []
    for actual in validas:
        if not fusionadas:
            fusionadas.append(actual)
            continue
            
        anterior = fusionadas[-1]
        
        ant_fin = parse_fecha(anterior.get("fecha_fin"))
        act_ini = parse_fecha(actual.get("fecha_inicio"))
        
        son_fusionables = False
        if act_ini <= ant_fin + timedelta(days=7):
            nombre_ant_norm = normalizar_texto(anterior.get("nombre", ""))
            nombre_act_norm = normalizar_texto(actual.get("nombre", ""))
            
            es_excepcion = False
            for exc in NOMBRES_DISTINTOS_FORZADOS:
                if (exc in nombre_ant_norm and exc not in nombre_act_norm) or \
                   (exc in nombre_act_norm and exc not in nombre_ant_norm):
                    es_excepcion = True
                    break
                    
            if not es_excepcion:
                son_fusionables = True
                
        if son_fusionables:
            # Nombre: el más largo
            if len(actual.get("nombre", "")) > len(anterior.get("nombre", "")):
                anterior["nombre"] = actual.get("nombre")
                anterior["descripcion"] = actual.get("descripcion", anterior.get("descripcion", ""))
                
            # Fechas
            act_fin = parse_fecha(actual.get("fecha_fin"))
            if act_fin > ant_fin:
                anterior["fecha_fin"] = actual.get("fecha_fin")
                
            # Fuentes
            fuentes_ant = set(anterior.get("fuentes", []))
            fuentes_act = set(actual.get("fuentes", []))
            anterior["fuentes"] = list(fuentes_ant | fuentes_act)
            
            # Confianza
            if actual.get("confianza") == "alta" or anterior.get("confianza") == "alta":
                anterior["confianza"] = "alta"
            elif actual.get("confianza") == "media" or anterior.get("confianza") == "media":
                anterior["confianza"] = "media"
                
            # Programa
            prog_ant = anterior.get("programa", []) or []
            prog_act = actual.get("programa", []) or []
            
            dias_dict = {}
            for d in prog_ant + prog_act:
                fecha = d.get("fecha")
                if fecha not in dias_dict:
                    dias_dict[fecha] = {"fecha": fecha, "eventos": []}
                dias_dict[fecha]["eventos"].extend(d.get("eventos", []))
                
            nuevo_prog = list(dias_dict.values())
            nuevo_prog.sort(key=lambda d: parse_fecha(d["fecha"]))
            for i, d in enumerate(nuevo_prog):
                d["dia"] = i + 1
                
            anterior["programa"] = nuevo_prog
            logger.info(f"  [FUSION] Fusionadas fiestas próximas -> '{anterior['nombre']}' ({anterior['fecha_inicio']} a {anterior['fecha_fin']})")
        else:
            fusionadas.append(actual)

    return fusionadas + invalidas


# ──────────────────────────────────────────────────
# VALIDACIÓN DE FECHAS MÓVILES (Problema 4)
# ──────────────────────────────────────────────────
def _calcular_pascua(year: int) -> date:
    # Computus (Algoritmo de Butcher-Meeus)
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, mes, dia)

def validar_fechas_moviles(fiestas: list[dict], anno: int) -> list[dict]:
    """
    Corrige las fechas de fiestas móviles comunes (Carnaval, etc.) si el LLM
    las ha inventado o colocado mal.
    """
    pascua = _calcular_pascua(anno)
    
    # Offsets respecto a Pascua (min_days, max_days)
    FIESTAS_MOVILES = {
        "carnaval": (-52, -45),       # De Jueves Lardero a Miércoles de Ceniza
        "jueves lardero": (-52, -50),
        "semana santa": (-7, 1),
        "corpus christi": (60, 63),
    }

    for fiesta in fiestas:
        nombre_norm = normalizar_texto(fiesta.get("nombre", ""))
        
        for kw, (offset_min, offset_max) in FIESTAS_MOVILES.items():
            if kw in nombre_norm:
                fecha_min = pascua + timedelta(days=offset_min)
                fecha_max = pascua + timedelta(days=offset_max)
                
                f_ini = _parsear_fecha(fiesta.get("fecha_inicio"))
                f_fin = _parsear_fecha(fiesta.get("fecha_fin"))
                
                if not f_ini or not f_fin:
                    continue
                    
                # Si la fiesta dictada por el LLM cae fuera de la ventana móvil
                if f_fin < fecha_min or f_ini > fecha_max:
                    logger.warning(f"  [MOVIL] Alucinación detectada en '{fiesta.get('nombre')}'. Fecha dictada: {f_ini}. Ventana real: {fecha_min} a {fecha_max}")
                    # Degradar confianza y forzar fecha estimada a la ventana real
                    fiesta["confianza"] = "baja"
                    fiesta["es_estimada"] = True
                    fiesta["fecha_inicio"] = fecha_min.isoformat()
                    fiesta["fecha_fin"] = fecha_max.isoformat()
                    fiesta["programa"] = []
                break 
                
    return fiestas


"""
Procesador RAG + LLM — Adaptado para Qwen 2.5 7B (32k ventana).

- Chunking optimizado para español
- Embeddings en batch
- Criterio de fiestas inyectado en el system prompt
- Validación post-LLM robusta (schema, fechas, deduplicación)
"""

import asyncio
import math
import json
import re
import logging
from datetime import datetime, date

import aiohttp

from config import (
    RAG_MAX_TOKENS,
    RAG_CHARS_PER_TOKEN,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
    RAG_EMBEDDING_BATCH_SIZE,
    RAG_PROGRAMA_MAX_CHARS,
    RAG_UMBRAL_SIMILITUD,
    RAG_MIN_OFICIALES_SIN_UMBRAL,
    LMSTUDIO_EMBEDDING_URL,
    LMSTUDIO_CHAT_URL,
    LMSTUDIO_EMBEDDING_MODEL,
    LMSTUDIO_CHAT_MODEL,
    LMSTUDIO_CHAT_TIMEOUT,
    LMSTUDIO_EMBEDDING_TIMEOUT,
    LMSTUDIO_CHAT_TEMPERATURE,
    LMSTUDIO_CHAT_MAX_TOKENS,
)
from llm_processor.festival_filter import sanear_fiesta, evaluar_fiesta
from fuentes import (
    es_fuente_oficial,
    es_fuente_valida,
    fuente_base,
    prioridad_fuente,
    rotulo_fuente,
)

logger = logging.getLogger("text_analyzer")

# Semáforo global: solo UNA petición simultánea al LLM local (evita desbordar la VRAM)
LLM_SEMAPHORE = asyncio.Semaphore(1)

# Diccionario de pre-mapeo para idiomas cooficiales
DICCIONARIO_FESTIVO = {
    r'\bjaiak\b': 'fiestas',
    r'\bherri bazkaria\b': 'comida popular',
    r'\bkalejira\b': 'pasacalles',
    r'\btxapelketa\b': 'campeonato',
    r'\bmeza\b': 'misa',
    r'\btxupinazoa?\b': 'chupinazo',
    r'\bdantza\b': 'baile',
    r'\bkontzertua?\b': 'concierto',
    r'\bumeen eguna\b': 'día del niño',
    r'\bfestes\b': 'fiestas',
    r'\bcorrefoc\b': 'pasacalles con fuego',
    r'\bcercavila\b': 'pasacalles',
    r'\bfestas\b': 'fiestas',
    r'\bverbena\b': 'verbena',
    r'\bgau-jai\b': 'fiesta nocturna',
    r'\btxosna\b': 'caseta',
    r'\bbertso\b': 'versos',
    r'\bpilota\b': 'pelota',
    r'\berromeria\b': 'romería',
    r'\bdesfilea\b': 'desfile',
}


# ──────────────────────────────────────────────────
# CRITERIO DE FIESTAS (condensado para el LLM)
# ──────────────────────────────────────────────────

CRITERIO_FIESTAS = """
CRITERIO DE IDENTIFICACIÓN DE FIESTAS VÁLIDAS:

1. FIESTAS VÁLIDAS (extraer siempre):
   - Fiestas patronales (prioridad MÁXIMA): San Roque, Virgen del Rosario, Santiago Apóstol, etc.
   - Fiestas mayores: Fiesta Mayor de Verano, Fiesta Mayor de Agosto, etc.
   - Ferias locales: Feria de Agosto, Feria de Primavera, etc.
   - Fiestas tradicionales: Carnaval, San Juan, Moros y Cristianos, Romerías festivas.
   - Fiestas de barrio y pedanía.
   - Verbenas y fiestas populares de verano.

2. REGLA DE ORO — ACTIVIDAD NOCTURNA:
   Si la celebración incluye orquesta, verbena, DJ, discoteca móvil, concierto nocturno o
   actuación musical en directo → la celebración es AUTOMÁTICAMENTE una fiesta válida.
   Esta regla prevalece incluso si el nombre no contiene "fiesta" o si tiene origen religioso.

3. PROGRAMA DE ACTOS:
   Una vez identificada una fiesta válida, TODOS los actos dentro de su periodo oficial son
   parte de la fiesta sin filtro: procesiones, misas, exposiciones, concursos, deportes,
   comidas populares, encierros, desfiles, conciertos, pirotecnia, mercados, etc.

4. RECHAZAR únicamente eventos aislados SIN vinculación con ninguna fiesta:
   conferencias sueltas, exposiciones independientes, actos institucionales aislados.

5. JERARQUÍA: Patronales > Fiestas Mayores > Ferias > Carnaval/San Juan > Fiestas de barrio > Verbenas.

6. FIESTAS DE UN SOLO DÍA — FILTRO ESTRICTO:
   Una celebración cuya fecha_inicio y fecha_fin son el MISMO día solo es fiesta válida si incluye
   de forma explícita orquesta, verbena, DJ, discoteca móvil, concierto o actuación musical.
   NUNCA extraigas como fiesta un acto aislado de un solo día (una procesión, una misa, una exposición,
   una conferencia) que no tenga programación festiva.

7. RANGO COMPLETO: si el texto indica que la fiesta abarca varios días, devuelve UNA sola fiesta con el
   rango completo (fecha_inicio a fecha_fin), nunca la trocees en actos sueltos de un día.

8. EVENTOS PRIVADOS: NO extraigas eventos de negocios privados (discotecas, salas de fiestas, pubs, clubs).
   Solo celebraciones populares propias de la localidad y abiertas a todo el mundo.

9. CALENDARIO LABORAL/ESCOLAR: un festivo del calendario (día no lectivo, festivo local listado en un
   calendario laboral o escolar) NO es una fiesta por sí solo. Solo extráelo si hay evidencia de
   celebración real (programa de actos, verbena, música, feria).
""".strip()


# Bloque de jerarquía de fuentes para el system prompt
JERARQUIA_FUENTES = """
JERARQUÍA DE FUENTES DEL TEXTO:
El texto está dividido en secciones "===== FUENTE: ... =====" ordenadas de MÁS a MENOS fiable:
  1. WEB OFICIAL DE LA LOCALIDAD (máxima fiabilidad)
  2. WEB OFICIAL DEL MUNICIPIO
  3. RED SOCIAL OFICIAL DE LA LOCALIDAD
  4. RED SOCIAL OFICIAL DEL MUNICIPIO
  5. RESULTADOS DE BUSCADOR (fiabilidad BAJA: verificar contra las anteriores)

REGLAS DE FUENTES:
- Cada fiesta debe declarar en "fuentes" TODAS las fuentes donde aparece. Usa exactamente estos
  identificadores: "web_localidad", "web_municipio", "rrss_localidad:<red>", "rrss_municipio:<red>", "busqueda_web".
- Si una fiesta SOLO aparece en RESULTADOS DE BUSCADOR: "solo_fuentes_no_oficiales": true y "confianza": "baja".
- FUSIÓN DE EVENTOS: si una fuente oficial (1-4) confirma la fiesta y un resultado de buscador aporta un
  evento concreto dentro de su periodo, AÑADE ese evento al programa con normalidad — la fiesta mantiene
  la confianza de la fuente oficial.
- Las secciones marcadas como CALENDARIO LABORAL/ESCOLAR solo listan días festivos: NO son evidencia de
  fiesta ni de celebración.
""".strip()


# ──────────────────────────────────────────────────
# CHUNKING POR DOCUMENTOS (no corta programas ni mezcla fuentes)
# ──────────────────────────────────────────────────

_RE_HORA_PROGRAMA = re.compile(r"\b\d{1,2}[:.h]\d{2}\b")


def _dividir_en_unidades(texto: str) -> list[str]:
    """Divide un texto en unidades semánticas: líneas si las hay, frases si no."""
    if "\n" in texto:
        unidades = [l.strip() for l in texto.split("\n") if l.strip()]
    else:
        unidades = [u.strip() for u in re.split(r"(?<=[.!?])\s+", texto) if u.strip()]

    # Trocear unidades desmesuradas por límite duro (última defensa)
    resultado = []
    for u in unidades:
        while len(u) > RAG_PROGRAMA_MAX_CHARS:
            corte = u.rfind(" ", 0, RAG_PROGRAMA_MAX_CHARS)
            corte = corte if corte > 0 else RAG_PROGRAMA_MAX_CHARS
            resultado.append(u[:corte])
            u = u[corte:].strip()
        if u:
            resultado.append(u)
    return resultado


def chunk_documento(texto: str, chunk_size: int = RAG_CHUNK_SIZE) -> list[str]:
    """
    Fragmenta UN documento respetando límites de línea/frase.
    Cuando detecta un bloque tipo programa (líneas consecutivas con horarios),
    lo mantiene íntegro hasta RAG_PROGRAMA_MAX_CHARS en lugar de cortarlo a
    chunk_size — un programa de fiestas nunca debe llegar partido al LLM.
    """
    unidades = _dividir_en_unidades(texto)
    chunks: list[str] = []
    actual: list[str] = []
    len_actual = 0
    horas_en_actual = 0

    for u in unidades:
        tiene_hora = bool(_RE_HORA_PROGRAMA.search(u))
        # Modo programa: el chunk ya acumula varios horarios y la unidad sigue el patrón
        en_programa = horas_en_actual >= 3 and (tiene_hora or len(u) <= 80)
        limite = RAG_PROGRAMA_MAX_CHARS if en_programa else chunk_size

        if actual and len_actual + len(u) + 1 > limite:
            chunks.append("\n".join(actual))
            actual, len_actual, horas_en_actual = [], 0, 0

        actual.append(u)
        len_actual += len(u) + 1
        if tiene_hora:
            horas_en_actual += 1

    if actual:
        chunks.append("\n".join(actual))
    return chunks


def seleccionar_chunks(
    items: list[dict],
    budget_chars: int,
    umbral: float = RAG_UMBRAL_SIMILITUD,
    min_oficiales: int = RAG_MIN_OFICIALES_SIN_UMBRAL,
) -> list[dict]:
    """
    Selección por cuotas de prioridad. items: {chunk, fuente, url, es_calendario, prioridad, score}.
    1º entran los chunks relevantes de fuentes OFICIALES (por prioridad y score);
    la búsqueda web solo rellena el presupuesto restante: un chunk oficial nunca
    es expulsado por uno de buscador.
    """
    oficiales = [i for i in items if es_fuente_oficial(i["fuente"])]
    externos = [i for i in items if not es_fuente_oficial(i["fuente"])]

    oficiales_rel = [i for i in oficiales if i["score"] >= umbral]
    if not oficiales_rel and oficiales:
        # Red de seguridad: nunca dejar fuera TODO lo oficial por el umbral
        oficiales_rel = sorted(oficiales, key=lambda i: -i["score"])[:min_oficiales]

    seleccion = []
    usados = 0
    for i in sorted(oficiales_rel, key=lambda i: (i["prioridad"], -i["score"])):
        if usados + len(i["chunk"]) > budget_chars:
            continue
        seleccion.append(i)
        usados += len(i["chunk"])

    for i in sorted(externos, key=lambda i: -i["score"]):
        if i["score"] < umbral:
            break
        if usados + len(i["chunk"]) > budget_chars:
            continue
        seleccion.append(i)
        usados += len(i["chunk"])

    return seleccion


def ensamblar_contexto(seleccion: list[dict]) -> str:
    """Agrupa los chunks por fuente (en orden de prioridad, calendarios al final) con rótulos."""
    grupos: dict[tuple, list[dict]] = {}
    for i in seleccion:
        grupos.setdefault((i["fuente"], i["es_calendario"]), []).append(i)

    def _orden(clave):
        fuente, es_cal = clave
        return (1 if es_cal else 0, prioridad_fuente(fuente))

    partes = []
    for clave in sorted(grupos, key=_orden):
        fuente, es_cal = clave
        partes.append(f"\n===== FUENTE: {rotulo_fuente(fuente, es_cal)} =====")
        for i in grupos[clave]:
            if i.get("url") and i["url"] != "buscadores:snippets":
                partes.append(f"[{i['url']}]")
            partes.append(i["chunk"])
    return "\n".join(partes).strip()


# ──────────────────────────────────────────────────
# RAG PROCESSOR (async, batch embeddings)
# ──────────────────────────────────────────────────

class AsyncRAGProcessor:
    """Procesador RAG con embeddings en batch y selección por cuotas de fuente."""

    def __init__(
        self,
        max_tokens=RAG_MAX_TOKENS,
        chunk_size=RAG_CHUNK_SIZE,
        chunk_overlap=RAG_CHUNK_OVERLAP,
        batch_size=RAG_EMBEDDING_BATCH_SIZE,
    ):
        self.max_tokens = max_tokens
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.batch_size = batch_size
        # Límite de caracteres basado en ratio español
        self.context_limit_chars = int(max_tokens * RAG_CHARS_PER_TOKEN)

    @staticmethod
    def cosine_similarity(v1, v2):
        if not v1 or not v2:
            return 0
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = math.sqrt(sum(a * a for a in v1))
        mag2 = math.sqrt(sum(b * b for b in v2))
        if mag1 == 0 or mag2 == 0:
            return 0
        return dot / (mag1 * mag2)

    async def get_embeddings_batch(self, session: aiohttp.ClientSession, texts: list[str]) -> list:
        """Obtiene embeddings para un batch de textos en una sola petición."""
        try:
            payload = {
                "input": texts,
                "model": LMSTUDIO_EMBEDDING_MODEL,
            }
            async with session.post(
                LMSTUDIO_EMBEDDING_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=LMSTUDIO_EMBEDDING_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Ordenar por index para mantener correspondencia
                    sorted_data = sorted(data["data"], key=lambda x: x["index"])
                    return [item["embedding"] for item in sorted_data]
                else:
                    logger.warning(f"Error embeddings batch: status {resp.status}")
        except Exception as e:
            logger.warning(f"Error embeddings batch: {e}")
        return [None] * len(texts)

    async def saturate_context_docs(self, documentos: list[dict], query: str) -> tuple[str, set]:
        """
        Fragmenta cada documento por separado (sin mezclar fuentes ni cortar
        programas), vectoriza y selecciona por cuotas de prioridad de fuente.
        Devuelve (contexto rotulado por fuente, set de fuentes presentes).
        """
        items = []
        for doc in documentos:
            texto = (doc.get("texto") or "").strip()
            if not texto:
                continue
            for chunk in chunk_documento(texto, self.chunk_size):
                items.append({
                    "chunk": chunk,
                    "fuente": doc["fuente"],
                    "url": doc.get("url", ""),
                    "es_calendario": doc.get("es_calendario", False),
                    "prioridad": prioridad_fuente(doc["fuente"]),
                    "score": 0.0,
                })

        if not items:
            return "", set()

        logger.info(
            f"  RAG: {len(items)} chunks de {len(documentos)} documentos. "
            f"Vectorizando en batches de {self.batch_size}..."
        )

        umbral = RAG_UMBRAL_SIMILITUD
        async with aiohttp.ClientSession() as session:
            query_embeddings = await self.get_embeddings_batch(session, [query])
            query_emb = query_embeddings[0] if query_embeddings else None

            if not query_emb:
                # Sin embeddings: seleccionar solo por prioridad de fuente
                logger.warning("  RAG: sin embedding de la query; selección solo por prioridad de fuente.")
                umbral = -1.0
            else:
                chunks = [i["chunk"] for i in items]
                all_embeddings = []
                for b in range(0, len(chunks), self.batch_size):
                    batch_embs = await self.get_embeddings_batch(session, chunks[b : b + self.batch_size])
                    all_embeddings.extend(batch_embs)
                for item, emb in zip(items, all_embeddings):
                    item["score"] = self.cosine_similarity(query_emb, emb) if emb else 0.0

        seleccion = seleccionar_chunks(items, self.context_limit_chars, umbral)
        usados = sum(len(i["chunk"]) for i in seleccion)
        oficiales = sum(1 for i in seleccion if es_fuente_oficial(i["fuente"]))
        logger.info(
            f"  RAG: Seleccionados {len(seleccion)}/{len(items)} chunks "
            f"({oficiales} oficiales, {len(seleccion) - oficiales} de buscador; "
            f"{usados} chars ~ {int(usados / RAG_CHARS_PER_TOKEN)} tokens)"
        )

        contexto = ensamblar_contexto(seleccion)
        fuentes_presentes = {i["fuente"] for i in seleccion}
        return contexto, fuentes_presentes


# ──────────────────────────────────────────────────
# VALIDACIÓN POST-LLM
# ──────────────────────────────────────────────────

def _validar_fecha(fecha_str: str, anno: int) -> bool:
    """Valida que una fecha sea YYYY-MM-DD del año correcto."""
    try:
        parsed = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        return parsed.year == anno
    except (ValueError, TypeError):
        return False


def _normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre de fiesta para comparación."""
    nombre = nombre.lower().strip()
    nombre = re.sub(r"[^a-záéíóúüñ\s]", "", nombre)
    nombre = re.sub(r"\s+", " ", nombre)
    return nombre


def _deduplicar_fiestas(fiestas: list[dict]) -> list[dict]:
    """Elimina fiestas duplicadas por nombre normalizado + fechas solapadas."""
    if not fiestas:
        return []

    seen = {}
    deduplicadas = []

    for f in fiestas:
        nombre_norm = _normalizar_nombre(f.get("nombre", ""))
        fecha_inicio = f.get("fecha_inicio", "")

        # Clave de deduplicación: nombre normalizado + fecha inicio
        key = f"{nombre_norm}_{fecha_inicio}"

        if key not in seen:
            seen[key] = True
            deduplicadas.append(f)
        else:
            logger.info(f"  Deduplicada: '{f.get('nombre')}' ({fecha_inicio})")

    return deduplicadas


def _validar_fuentes_fiesta(f: dict, nombre: str, fuentes_contexto: set | None) -> None:
    """
    Normaliza las fuentes declaradas por el LLM y calcula solo_fuentes_no_oficiales.
    - Se eliminan fuentes inventadas (no válidas o no presentes en el contexto).
    - Si tras la limpieza no queda ninguna fuente oficial → solo_fuentes_no_oficiales
      = True y confianza forzada a baja.
    - Si el modelo no declaró fuentes pero el contexto era íntegramente oficial,
      se asume oficial.
    """
    declaradas = f.get("fuentes")
    if not isinstance(declaradas, list):
        declaradas = []
    declaradas = [s for s in declaradas if isinstance(s, str) and es_fuente_valida(s)]

    if fuentes_contexto is not None:
        bases_contexto = {fuente_base(s) for s in fuentes_contexto}
        filtradas = [s for s in declaradas if s in fuentes_contexto or fuente_base(s) in bases_contexto]
        if len(filtradas) != len(declaradas):
            descartadas = set(declaradas) - set(filtradas)
            logger.info(
                f"  [FUENTES] '{nombre}': el LLM declaró fuentes ausentes del contexto: "
                f"{sorted(descartadas)}. Eliminadas."
            )
        declaradas = filtradas

    solo_no_oficiales = not any(es_fuente_oficial(s) for s in declaradas)

    if not declaradas and fuentes_contexto:
        # Sin declaración del modelo: solo inferimos oficialidad si TODO el contexto lo era
        if all(es_fuente_oficial(s) for s in fuentes_contexto):
            solo_no_oficiales = False

    f["fuentes"] = declaradas
    f["solo_fuentes_no_oficiales"] = bool(solo_no_oficiales)
    if f["solo_fuentes_no_oficiales"]:
        f["confianza"] = "baja"


def validar_fiestas(
    fiestas_raw: list[dict],
    localidad: dict,
    anno: int,
    fecha_patron=None,
    fuentes_contexto: set | None = None,
) -> list[dict]:
    """
    Validación robusta de las fiestas extraídas por el LLM.
    Incluye saneado de fiestas mal formadas, el filtro adaptativo por duración
    (regular para multi-día, estricto para un solo día) y la validación de las
    fuentes declaradas contra las realmente presentes en el contexto.
    """
    fiestas_validas = []

    for f in fiestas_raw:
        nombre = f.get("nombre", "").strip()

        # 1. Campos obligatorios
        if not nombre:
            logger.warning(f"  [VALIDACIÓN] Fiesta sin nombre. Descartada.")
            continue

        if not f.get("fecha_inicio") or not f.get("fecha_fin"):
            logger.warning(f"  [VALIDACIÓN] '{nombre}' sin fechas. Descartada.")
            continue

        # 2. Validar lugar_id
        if f.get("lugar_id") != localidad["id"]:
            logger.warning(
                f"  [ALUCINACIÓN] '{nombre}' asignada a '{f.get('lugar_id')}' "
                f"en vez de '{localidad['id']}'. Descartada."
            )
            continue

        # 3. Validar formato y año de fechas
        if not _validar_fecha(f["fecha_inicio"], anno):
            logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_inicio inválida: {f['fecha_inicio']}. Descartada.")
            continue

        if not _validar_fecha(f["fecha_fin"], anno):
            logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_fin inválida: {f['fecha_fin']}. Descartada.")
            continue

        # 4. fecha_inicio <= fecha_fin
        if f["fecha_inicio"] > f["fecha_fin"]:
            logger.warning(f"  [VALIDACIÓN] '{nombre}' fecha_inicio > fecha_fin. Intercambiando.")
            f["fecha_inicio"], f["fecha_fin"] = f["fecha_fin"], f["fecha_inicio"]

        # 5. Asegurar campos con valores por defecto
        f.setdefault("tamano", "pequeña")
        f.setdefault("descripcion", "")
        f.setdefault("confianza", "media")
        f.setdefault("programa", [])

        # 6. Saneado de fiestas mal formadas (nombre genérico, duración absurda, programa incoherente)
        f = sanear_fiesta(f)
        if f is None:
            continue

        # 7. Filtro adaptativo: regular para multi-día, estricto para un solo día
        aceptada, motivo, confianza_forzada = evaluar_fiesta(f, fecha_patron)
        if not aceptada:
            logger.info(f"  [FILTRO] '{nombre}' descartada: {motivo}.")
            continue
        logger.info(f"  [FILTRO] '{nombre}' aceptada: {motivo}.")
        if confianza_forzada:
            f["confianza"] = confianza_forzada

        # 8. Fuentes declaradas vs contexto real → solo_fuentes_no_oficiales
        _validar_fuentes_fiesta(f, nombre, fuentes_contexto)

        # 9. Campos de trazabilidad del origen
        f.setdefault("origen", "extraccion")
        f.setdefault("es_estimada", False)
        f.setdefault("incluye_dia_patron", False)

        # 10. Generar slug si no existe o es inválido
        if not f.get("id") or not re.match(r"^[a-z0-9\-]+$", f.get("id", "")):
            slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower())
            slug = slug.strip("-")[:60]
            f["id"] = f"{slug}-{localidad['id']}"

        fiestas_validas.append(f)

    # 11. Deduplicar
    fiestas_validas = _deduplicar_fiestas(fiestas_validas)

    return fiestas_validas


# ──────────────────────────────────────────────────
# INFERENCIA LLM
# ──────────────────────────────────────────────────

class ContextOverflowError(Exception):
    """El prompt supera el n_ctx con que está cargado el modelo en LM Studio."""


def _parse_json_llm(content: str) -> dict | None:
    """Limpia y parsea la respuesta JSON del LLM (tolerante a basura típica)."""
    content = content.replace("```json", "").replace("```", "").strip()
    # Limpiar comas sueltas típicas de modelos pequeños antes de un ] o }
    content = re.sub(r",\s*([\]}])", r"\1", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"  JSON malformado del LLM: {e}")
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                logger.error("  No se pudo recuperar JSON parcial.")
    return None


async def llm_chat_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = LMSTUDIO_CHAT_MAX_TOKENS,
) -> dict | None:
    """
    Petición genérica al LLM local que devuelve un dict parseado del JSON de respuesta.
    Serializada con el semáforo global para no desbordar la VRAM.
    """
    payload = {
        "model": LMSTUDIO_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LMSTUDIO_CHAT_TEMPERATURE,
        "max_tokens": max_tokens,
    }

    try:
        async with LLM_SEMAPHORE:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    LMSTUDIO_CHAT_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=LMSTUDIO_CHAT_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        error_body = await resp.text()
                        if resp.status == 400 and (
                            "n_keep" in error_body or "context length" in error_body.lower()
                        ):
                            raise ContextOverflowError(error_body[:200])
                        logger.error(f"  Error LLM: status {resp.status} — {error_body[:200]}")
                        return None
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
    except ContextOverflowError:
        raise
    except asyncio.TimeoutError:
        logger.error(f"  Timeout del LLM tras {LMSTUDIO_CHAT_TIMEOUT}s")
        return None
    except Exception as e:
        logger.error(f"  Error LLM: {e}")
        return None

    return _parse_json_llm(content)


async def analyze_festivals_for_locality(
    municipio: dict,
    localidad: dict,
    texto_filtrado: str,
    anno: int,
    fecha_patron=None,
    fuentes_contexto: set | None = None,
) -> list[dict]:
    """
    Llama al LLM para extraer fiestas de una localidad concreta.
    Incluye el criterio de fiestas y validación post-generación.
    fecha_patron (datetime.date | None) afina el filtro de fiestas de un solo día.
    fuentes_contexto: fuentes realmente presentes en el texto, para validar
    las que declare el modelo.
    """

    es_capital = (localidad['nombre'].strip().lower() == municipio['nombre'].strip().lower())
    
    if es_capital:
        regla_exclusividad = (
            f'Extraer las fiestas ÚNICAMENTE para el núcleo principal/capital del municipio: "{localidad["nombre"]}".\n'
            f'Asegúrate de NO incluir fiestas que pertenezcan a otras pedanías o aldeas periféricas menores.'
        )
    else:
        regla_exclusividad = (
            f'Extraer las fiestas ÚNICAMENTE para la localidad menor/pedanía: "{localidad["nombre"]}" (ID: {localidad["id"]}).\n'
            f'NUNCA asignes ni generes fiestas para el municipio principal ({municipio["nombre"]}) a menos que ocurran específicamente en esta pedanía.\n'
            f'Si no encuentras fiestas para "{localidad["nombre"]}", devuelve la lista vacía.'
        )

    system_prompt = f"""Eres un API estricta especializada en extraer información de fiestas locales en España.
CONTEXTO: Estás analizando información de {municipio['nombre']} ({municipio.get('provincia', 'España')}).

{CRITERIO_FIESTAS}

{JERARQUIA_FUENTES}

OBJETIVO CRÍTICO:
{regla_exclusividad}
AÑO: {anno}. Todas las fechas deben ser del año {anno}.

REGLA DE ORO: SI EL TEXTO NO MENCIONA NINGUNA FIESTA DE FORMA EXPLÍCITA PARA ESTA LOCALIDAD, DEBES DEVOLVER ESTRICTAMENTE '{{"fiestas": []}}' SIN AÑADIR NINGUNA EXPLICACIÓN.

TRADUCCIÓN: Los textos pueden estar en castellano, euskera, catalán o gallego. Extrae los eventos sin importar el idioma, pero TRADUCE la descripción y el nombre al castellano en el JSON.

Devuelve SOLO JSON estricto con esta estructura (no escribas markdown, ni saludos, ni confirmaciones):
{{
  "fiestas": [
    {{
      "id": "slug-unico",
      "lugar_id": "{localidad['id']}",
      "nombre": "Nombre de la Fiesta",
      "fecha_inicio": "YYYY-MM-DD",
      "fecha_fin": "YYYY-MM-DD",
      "tamano": "pequeña" o "grande",
      "descripcion": "Breve descripción de la celebración",
      "confianza": "alta", "media" o "baja",
      "fuentes": ["web_municipio", "busqueda_web"],
      "solo_fuentes_no_oficiales": false,
      "programa": [
         {{ "dia": 1, "fecha": "YYYY-MM-DD", "eventos": [ {{"hora": "HH:MM", "descripcion": "Descripción del acto"}}] }}
      ]
    }}
  ]
}}"""

    # Pre-procesado: traducir palabras clave para facilitar la labor del LLM
    texto_traducido = texto_filtrado
    for patron, reemplazo in DICCIONARIO_FESTIVO.items():
        texto_traducido = re.sub(patron, reemplazo, texto_traducido, flags=re.IGNORECASE)

    # Reintento adaptativo: si el prompt no cabe en el n_ctx del modelo cargado,
    # se recorta el contexto (en un límite de línea) y se reintenta.
    parsed = None
    for factor in (1.0, 0.7, 0.5):
        texto_intento = texto_traducido
        if factor < 1.0:
            corte = int(len(texto_traducido) * factor)
            salto = texto_traducido.rfind("\n", 0, corte)
            texto_intento = texto_traducido[: salto if salto > 0 else corte]
            logger.warning(
                f"  Contexto no cabe en el n_ctx del modelo. Reintentando con el "
                f"{int(factor * 100)}% ({len(texto_intento)} chars)..."
            )

        user_prompt = (
            f"AÑO: {anno}\n\n"
            f"TEXTO RECUPERADO:\n{texto_intento}\n\n"
            f"Extrae las fiestas en formato JSON exclusivamente para {localidad['nombre']}. Recuerda, responde SOLO con JSON:\n```json\n"
        )

        logger.info(f"  Llamando a {LMSTUDIO_CHAT_MODEL} (Locality-Centric)...")
        try:
            parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=LMSTUDIO_CHAT_MAX_TOKENS)
            break
        except ContextOverflowError as e:
            logger.warning(f"  [n_ctx] {e}")
            continue

    if parsed is None:
        return []

    fiestas_raw = parsed.get("fiestas", [])
    fiestas_validas = validar_fiestas(fiestas_raw, localidad, anno, fecha_patron, fuentes_contexto)

    logger.info(
        f"  Resultado: {len(fiestas_validas)} fiestas válidas "
        f"(de {len(fiestas_raw)} generadas) para {localidad['nombre']}"
    )
    return fiestas_validas

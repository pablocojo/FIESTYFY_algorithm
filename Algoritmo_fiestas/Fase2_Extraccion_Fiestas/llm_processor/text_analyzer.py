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
from datetime import datetime, date, timedelta

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
from config_idiomas import get_language_profile
import fasttext

logger = logging.getLogger("text_analyzer")

try:
    logger.info("Cargando modelo FastText...")
    _LID_MODEL = fasttext.load_model("lid.176.ftz")
except Exception as e:
    logger.warning(f"No se pudo cargar fasttext (lid.176.ftz): {e}")
    _LID_MODEL = None

_OPUS_PIPELINES = {}

def translate_chunk(text: str, motor: str, modelo_id: str) -> str:
    if not text.strip():
        return text
    
    if motor == "opus-mt":
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            if modelo_id not in _OPUS_PIPELINES:
                logger.info(f"Cargando modelo Opus-MT: {modelo_id}...")
                tokenizer = AutoTokenizer.from_pretrained(modelo_id)
                model = AutoModelForSeq2SeqLM.from_pretrained(modelo_id)
                _OPUS_PIPELINES[modelo_id] = (tokenizer, model)
            
            tokenizer, model = _OPUS_PIPELINES[modelo_id]
            lines = text.split("\n")
            translated_lines = []
            for line in lines:
                if not line.strip() or line.startswith("=====") or line.startswith("[http"):
                    translated_lines.append(line)
                    continue
                
                # Traducimos usando directamente el modelo Seq2Seq (super robusto en cualquier versión de transformers)
                inputs = tokenizer(line, return_tensors="pt", padding=True, truncation=True, max_length=512)
                outputs = model.generate(**inputs, max_new_tokens=512)
                trans_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
                translated_lines.append(trans_text)
                
            return "\n".join(translated_lines)
        except Exception as e:
            logger.error(f"Error Opus-MT: {e}")
            return text

    elif motor == "apertium":
        import subprocess
        import sys
        # Si el modelo_id es cat_valencia, usamos el par cat-spa
        pair = "cat-spa" if "cat" in modelo_id else "oci-spa"
        
        # Si ejecutamos directamente en Linux/WSL (Opción B), llamamos a 'apertium' de forma nativa.
        # Si por alguna razón se ejecutara en Windows, añade el prefijo 'wsl'.
        comando = ["wsl", "apertium", pair] if sys.platform == "win32" else ["apertium", pair]
        try:
            proceso = subprocess.Popen(
                comando,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )
            # Metemos el chunk de texto directamente a las tripas de Apertium
            stdout, stderr = proceso.communicate(input=text)
            
            if proceso.returncode == 0:
                return stdout.strip()
            else:
                logger.error(f"Error Apertium ({comando[0]}): {stderr.strip()}")
                return text
        except FileNotFoundError:
            logger.error(f"No se encontró el ejecutable '{comando[0]}' en el sistema. Omitiendo traducción.")
            return text
        except Exception as e:
            logger.error(f"Error llamando a Apertium: {e}")
            return text

    return text

def process_translation_pipeline(texto: str, municipio: dict) -> str:
    comunidad = municipio.get("comunidad_autonoma", "")
    provincia = municipio.get("provincia", "")
    perfil_data = get_language_profile(comunidad, provincia)
    
    perfil_principal = perfil_data.get("perfil_principal")
    perfil_secundario = perfil_data.get("perfil_secundario")
    idiomas_a_detectar = perfil_data.get("idiomas_a_detectar", ["es"])
    
    if len(idiomas_a_detectar) <= 1 or not _LID_MODEL:
        return texto
        
    blocks = texto.split("===== FUENTE:")
    translated_blocks = []
    
    for i, block in enumerate(blocks):
        if not block:
            continue
        
        if i > 0 or texto.startswith("===== FUENTE:"):
            real_block = "===== FUENTE:" + block
        else:
            real_block = block
        
        clean_text = re.sub(r'=====.*?=====', '', real_block)
        clean_text = re.sub(r'\[http.*?\]', '', clean_text)
        clean_text = clean_text.replace('\n', ' ').strip()
        
        if len(clean_text) < 20:
            translated_blocks.append(real_block)
            continue
            
        pred = _LID_MODEL.predict(clean_text, k=3)
        labels = [l.replace('__label__', '') for l in pred[0]]
        probs = pred[1]
        
        best_lang = "es"
        best_prob = 0.0
        for l, p in zip(labels, probs):
            if l in idiomas_a_detectar and p > best_prob:
                best_lang = l
                best_prob = p
                
        if best_lang != "es" and best_prob > 0.4:
            motor = perfil_principal["motor_traduccion"]
            modelo = perfil_principal["modelo_id"]
            if best_lang == "oc" and perfil_secundario:
                motor = perfil_secundario["motor_traduccion"]
                modelo = perfil_secundario["modelo_id"]
                
            logger.info(f"  [IDIOMA] Detectado {best_lang} ({best_prob:.2f}). Traduciendo con {motor}...")
            translated_block = translate_chunk(real_block, motor, modelo)
            translated_blocks.append(translated_block)
        else:
            translated_blocks.append(real_block)
            
    return "".join(translated_blocks)

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

7. FUSIÓN OBLIGATORIA (REGLA DE LOS 7 DÍAS):
   a) Si el texto indica que la fiesta abarca varios días, devuelve UNA sola fiesta con el rango
      completo (fecha_inicio a fecha_fin). NUNCA la trocees en actos sueltos de un día.
   b) Si identificas eventos festivos consecutivos o separados por 7 días o menos (ej. chupinazo
      el día 12 y San Roque el día 17, o dos fines de semana seguidos), DEBES FUSIONARLOS en una
      única fiesta conjunta. El rango (fecha_inicio a fecha_fin) debe abarcar desde el primer
      evento hasta el último.
   c) ÚNICA EXCEPCIÓN para NO fusionar: que el texto indique de forma inequívoca que se trata de
      festividades con NOMBRES completamente distintos (ej. "Feria de Mayo" y "Corpus Christi").
      Simples actividades dentro del mismo periodo (chupinazo, verbena, procesión) NO son nombres
      distintos y DEBEN fusionarse en la fiesta que los engloba.

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

def _validar_fecha(
    fecha_str: str,
    anno: int,
    es_fecha_fin: bool = False,
    fecha_inicio_str: str | None = None,
) -> bool:
    """
    Valida que una fecha sea YYYY-MM-DD del año correcto.
    Permite que fecha_fin sea del año siguiente (anno + 1) si fecha_inicio está en diciembre del año objetivo (anno).
    """
    try:
        parsed = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        if parsed.year == anno:
            return True
        if parsed.year == anno + 1 and (es_fecha_fin or fecha_inicio_str):
            if fecha_inicio_str:
                try:
                    parsed_ini = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
                    if parsed_ini.year == anno and parsed_ini.month == 12:
                        return True
                except (ValueError, TypeError):
                    pass
            elif es_fecha_fin:
                return True
        return False
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

        if not _validar_fecha(f["fecha_fin"], anno, es_fecha_fin=True, fecha_inicio_str=f.get("fecha_inicio")):
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
            f'DESCARTA automáticamente cualquier fiesta que se anuncie de forma explícita para un barrio, '
            f'distrito, pedanía o zona concreta (ej. "Fiestas del barrio de Ibarra", "Fiestas de Butarque").\n'
            f'Solo extrae las fiestas MATRICES que engloban a toda la localidad en su conjunto '
            f'(ej. "Fiestas de {localidad["nombre"]}", "San Roque", fiestas patronales generales).\n'
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

    # 1. Pipeline de Traducción Neuronal / Léxica (FastText + OpusMT/Apertium)
    texto_traducido = process_translation_pipeline(texto_filtrado, municipio)

    # 2. Pre-procesado fallback: traducir palabras clave estáticas por si falla lo anterior
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


# ──────────────────────────────────────────────────
# MULTI-PASS RAG ARCHITECTURE (DISCOVERY + ENRICHMENT)
# ──────────────────────────────────────────────────

DISCOVERY_MAX_CHARS = 15000
ENRICHMENT_MAX_CHARS = 25000
FIESTA_MAX_DURACION_DIAS = 30


def _parse_fecha_con_fallback_bisiesto(fecha_str: str | None) -> date | None:
    """
    Parsea una fecha YYYY-MM-DD.
    Si fecha_str es 'YYYY-02-29' y el año YYYY no es bisiesto,
    hace fallback a 'YYYY-02-28'. Retorna date o None si es inválida.
    """
    if not fecha_str or not isinstance(fecha_str, str):
        return None
    s = fecha_str.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        if "-02-29" in s:
            s_fallback = s.replace("-02-29", "-02-28")
            try:
                return datetime.strptime(s_fallback, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None
        return None


def generar_consultas_enriquecimiento(
    nombre_fiesta: str | dict,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    max_dias: int = FIESTA_MAX_DURACION_DIAS,
) -> list[tuple[str, str]]:
    """
    Genera una lista de tuplas (fecha_str, query_str) para cada día de una fiesta.
    Formato: (fecha_str, f"{nombre_fiesta} {fecha_str} programa actos")

    Maneja:
    - Rango intra-mes (ej. 10 a 14 de agosto)
    - Rango inter-mes (ej. 28 de agosto a 3 de septiembre)
    - Rango inter-año (ej. 29 de diciembre a 3 de enero)
    - Año bisiesto (29 de febrero) y año no bisiesto (28 de febrero fallback)
    - Fechas invertidas (auto-intercambia inicio y fin)
    - Fechas malformadas o vacías (retorna lista vacía)
    - Límite máximo de días (max_dias = 30)
    """
    if isinstance(nombre_fiesta, dict):
        f_dict = nombre_fiesta
        nombre = f_dict.get("nombre", "")
        fecha_ini_str = fecha_inicio or f_dict.get("fecha_inicio", "")
        fecha_fin_str = fecha_fin or f_dict.get("fecha_fin", "")
    else:
        nombre = str(nombre_fiesta) if nombre_fiesta is not None else ""
        fecha_ini_str = fecha_inicio or ""
        fecha_fin_str = fecha_fin or ""

    nombre = nombre.strip()
    if not nombre or not fecha_ini_str or not fecha_fin_str:
        return []

    d_start = _parse_fecha_con_fallback_bisiesto(str(fecha_ini_str))
    d_end = _parse_fecha_con_fallback_bisiesto(str(fecha_fin_str))

    if d_start is None or d_end is None:
        return []

    if d_start > d_end:
        d_start, d_end = d_end, d_start

    consultas = []
    current = d_start
    count = 0
    while current <= d_end and count < max_dias:
        fecha_str = current.strftime("%Y-%m-%d")
        query_str = f"{nombre} {fecha_str} programa actos"
        consultas.append((fecha_str, query_str))
        current += timedelta(days=1)
        count += 1

    return consultas


async def index_document_chunks(
    rag_processor: AsyncRAGProcessor | None,
    documentos: list[dict],
) -> list[dict]:
    """
    Fragmenta cada documento y calcula sus vector embeddings en batch 1 sola vez per localidad.
    Devuelve una lista de dicts indexed_chunks.
    """
    if not documentos:
        return []

    chunk_size = rag_processor.chunk_size if rag_processor else RAG_CHUNK_SIZE
    items = []
    for doc in documentos:
        texto = (doc.get("texto") or "").strip()
        if not texto:
            continue
        for chunk in chunk_documento(texto, chunk_size):
            items.append({
                "chunk": chunk,
                "fuente": doc.get("fuente", "busqueda_web"),
                "url": doc.get("url", ""),
                "es_calendario": doc.get("es_calendario", False),
                "prioridad": prioridad_fuente(doc.get("fuente", "busqueda_web")),
                "embedding": None,
            })

    if not items:
        return []

    if rag_processor is not None:
        chunks_text = [i["chunk"] for i in items]
        batch_size = rag_processor.batch_size
        all_embeddings = []
        try:
            async with aiohttp.ClientSession() as session:
                for b in range(0, len(chunks_text), batch_size):
                    batch_embs = await rag_processor.get_embeddings_batch(
                        session, chunks_text[b : b + batch_size]
                    )
                    all_embeddings.extend(batch_embs)
            for item, emb in zip(items, all_embeddings):
                item["embedding"] = emb
        except Exception as e:
            logger.warning(f"Error calculando embeddings batch en index_document_chunks: {e}")

    return items


async def discover_festivals_for_locality(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
    fecha_patron=None,
) -> list[dict]:
    """
    Paso 1 del RAG Multi-Pass (Discovery Pass):
    Recupera top 10-15 chunks (~15,000 chars / ~5.8K tokens) para extraer JSON con metadatos básicos de fiestas.
    """
    if not indexed_chunks:
        return []

    es_capital = (localidad['nombre'].strip().lower() == municipio['nombre'].strip().lower())
    if es_capital:
        regla_exclusividad = (
            f'Extraer las fiestas ÚNICAMENTE para el núcleo principal/capital del municipio: "{localidad["nombre"]}".\n'
            f'DESCARTA automáticamente cualquier fiesta que se anuncie de forma explícita para un barrio, '
            f'distrito, pedanía o zona concreta (ej. "Fiestas del barrio de Ibarra", "Fiestas de Butarque").\n'
            f'Solo extrae las fiestas MATRICES que engloban a toda la localidad en su conjunto '
            f'(ej. "Fiestas de {localidad["nombre"]}", "San Roque", fiestas patronales generales).\n'
            f'Asegúrate de NO incluir fiestas que pertenezcan a otras pedanías o aldeas periféricas menores.'
        )
    else:
        regla_exclusividad = (
            f'Extraer las fiestas ÚNICAMENTE para la localidad menor/pedanía: "{localidad["nombre"]}" (ID: {localidad["id"]}).\n'
            f'NUNCA asignes ni generes fiestas para el municipio principal ({municipio["nombre"]}) a menos que ocurran específicamente en esta pedanía.\n'
            f'Si no encuentras fiestas para "{localidad["nombre"]}", devuelve la lista vacía.'
        )

    system_prompt = f"""Eres un API estricta especializada en identificar y catalogar las fiestas locales en España.
CONTEXTO: Municipio {municipio['nombre']} ({municipio.get('provincia', 'España')}), Localidad: {localidad['nombre']}.

{CRITERIO_FIESTAS}

{JERARQUIA_FUENTES}

OBJETIVO CRÍTICO:
{regla_exclusividad}
AÑO: {anno}. Identifica la lista de fiestas que se celebran en {anno}.

REGLA DE AGRUPACIÓN CRÍTICA:
Si encuentras varios eventos festivos cercanos en el tiempo (ej. "Día del Chupinazo el 12 de agosto" y "Día de San Roque el 16 de agosto"), FUSIONA TODOS en una ÚNICA fiesta global cuya `fecha_inicio` sea el primer evento (12 de agosto) y `fecha_fin` sea el último evento (16 de agosto). NO crees múltiples fiestas pequeñas si pertenecen al mismo ciclo festivo.

Devuelve SOLO JSON estricto con esta estructura (NO incluyas el programa detallado de actos en este paso):
{{
  "fiestas": [
    {{
      "id": "slug-unico",
      "lugar_id": "{localidad['id']}",
      "nombre": "Nombre de la Fiesta",
      "fecha_inicio": "YYYY-MM-DD",
      "fecha_fin": "YYYY-MM-DD",
      "tamano": "pequeña" o "grande",
      "descripcion": "Breve descripción general de la celebración",
      "confianza": "alta", "media" o "baja",
      "fuentes": ["web_municipio", "busqueda_web"],
      "solo_fuentes_no_oficiales": false
    }}
  ]
}}"""

    comunidad = municipio.get("comunidad_autonoma", "")
    provincia = municipio.get("provincia", "")
    perfil_data = get_language_profile(comunidad, provincia)
    terminos_rag = perfil_data["perfil_principal"]["terminos_rag"]

    query_discovery = (
        f"{terminos_rag} en {municipio['nombre']} "
        f"para la localidad de {localidad['nombre']} en el año {anno}"
    )

    items_copy = [dict(item) for item in indexed_chunks]
    query_emb = None
    if rag_processor is not None:
        try:
            async with aiohttp.ClientSession() as session:
                query_embs = await rag_processor.get_embeddings_batch(session, [query_discovery])
                query_emb = query_embs[0] if query_embs else None
        except Exception as e:
            logger.warning(f"Error obteniendo embedding de la query de discovery: {e}")

    if query_emb:
        for item in items_copy:
            item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
    else:
        for item in items_copy:
            item["score"] = 0.0

    seleccion = seleccionar_chunks(items_copy, DISCOVERY_MAX_CHARS, RAG_UMBRAL_SIMILITUD if query_emb else -1.0)
    if not seleccion:
        seleccion = sorted(items_copy, key=lambda i: (i["prioridad"], -i.get("score", 0.0)))[:15]

    contexto = ensamblar_contexto(seleccion)
    fuentes_contexto = {i["fuente"] for i in seleccion}

    if not contexto.strip():
        logger.warning(f"  [DISCOVERY] No hay texto de contexto para {localidad['nombre']}.")
        return []

    texto_traducido = process_translation_pipeline(contexto, municipio)
    for patron_str, reemplazo in DICCIONARIO_FESTIVO.items():
        texto_traducido = re.sub(patron_str, reemplazo, texto_traducido, flags=re.IGNORECASE)

    parsed = None
    for factor in (1.0, 0.7, 0.5):
        texto_intento = texto_traducido
        if factor < 1.0:
            corte = int(len(texto_traducido) * factor)
            salto = texto_traducido.rfind("\n", 0, corte)
            texto_intento = texto_traducido[: salto if salto > 0 else corte]

        user_prompt = (
            f"AÑO: {anno}\n\n"
            f"TEXTO RECUPERADO:\n{texto_intento}\n\n"
            f"Extrae la lista básica de fiestas en formato JSON exclusivamente para {localidad['nombre']}. Recuerda, responde SOLO con JSON:\n```json\n"
        )

        logger.info(f"  [DISCOVERY] Llamando a {LMSTUDIO_CHAT_MODEL}...")
        try:
            parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=LMSTUDIO_CHAT_MAX_TOKENS)
            break
        except ContextOverflowError as e:
            logger.warning(f"  [DISCOVERY n_ctx] {e}")
            continue

    if parsed is None:
        return []

    fiestas_raw = parsed.get("fiestas", [])
    fiestas_validas = validar_fiestas(fiestas_raw, localidad, anno, fecha_patron, fuentes_contexto)
    logger.info(f"  [DISCOVERY] Descubiertas {len(fiestas_validas)} fiestas preliminares para {localidad['nombre']}.")
    return fiestas_validas


async def enrich_festival_program(
    municipio: dict,
    localidad: dict,
    fiesta: dict,
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
) -> dict:
    """
    Paso 2 del RAG Multi-Pass (Enrichment Pass):
    Recupera chunks día a día para la fiesta descubierta y enriquece el campo programa.
    """
    nombre_fiesta = fiesta.get("nombre", "")
    fecha_ini = fiesta.get("fecha_inicio", "")
    fecha_fin = fiesta.get("fecha_fin", "")

    consultas_dias = generar_consultas_enriquecimiento(nombre_fiesta, fecha_ini, fecha_fin, max_dias=FIESTA_MAX_DURACION_DIAS)
    if not consultas_dias:
        fiesta.setdefault("programa", [])
        return fiesta

    logger.info(f"  [ENRICHMENT] Enriqueciendo '{nombre_fiesta}' ({len(consultas_dias)} días: {fecha_ini} a {fecha_fin})...")

    chunks_seleccionados_dias = []
    seen_chunks = set()

    query_embs = [None] * len(consultas_dias)
    if rag_processor is not None:
        try:
            async with aiohttp.ClientSession() as session:
                query_texts = [q for _, q in consultas_dias]
                query_embs = await rag_processor.get_embeddings_batch(session, query_texts)
        except Exception as e:
            logger.warning(f"Error calculando embeddings batch de consultas diarias: {e}")
            query_embs = [None] * len(consultas_dias)

    for (fecha_str, query_str), query_emb in zip(consultas_dias, query_embs):
        items_copy = [dict(item) for item in indexed_chunks]
        if query_emb:
            for item in items_copy:
                item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
        else:
            for item in items_copy:
                txt = item["chunk"].lower()
                score = 0.0
                if fecha_str in txt:
                    score += 0.5
                if nombre_fiesta.lower() in txt:
                    score += 0.3
                item["score"] = score

        chunks_dia = [i for i in items_copy if i.get("score", 0.0) >= RAG_UMBRAL_SIMILITUD]
        if not chunks_dia:
            chunks_dia = sorted(items_copy, key=lambda i: -i.get("score", 0.0))[:3]
        else:
            chunks_dia = sorted(chunks_dia, key=lambda i: (i["prioridad"], -i.get("score", 0.0)))[:3]

        for item in chunks_dia:
            chunk_key = (item["fuente"], item["chunk"])
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                chunks_seleccionados_dias.append(item)


    if not chunks_seleccionados_dias:
        fiesta.setdefault("programa", [])
        return fiesta

    usados = 0
    chunks_finales = []
    for item in chunks_seleccionados_dias:
        if usados + len(item["chunk"]) > ENRICHMENT_MAX_CHARS:
            break
        chunks_finales.append(item)
        usados += len(item["chunk"])

    contexto = ensamblar_contexto(chunks_finales)

    texto_traducido = process_translation_pipeline(contexto, municipio)
    for patron_str, reemplazo in DICCIONARIO_FESTIVO.items():
        texto_traducido = re.sub(patron_str, reemplazo, texto_traducido, flags=re.IGNORECASE)

    system_prompt = f"""Eres un API estricta especializada en estructurar el PROGRAMA DE ACTOS Y EVENTOS de una fiesta local en España.
CONTEXTO: Municipio {municipio['nombre']} ({municipio.get('provincia', 'España')}), Localidad: {localidad['nombre']}.
FIESTA A ENRIQUECER: "{nombre_fiesta}" ({fecha_ini} a {fecha_fin}).

REGLAS DE PROGRAMA DE ACTOS:
1. Extrae todos los actos y eventos mencionados en el texto para los días comprendidos entre {fecha_ini} y {fecha_fin}.
2. Organiza los actos día por día. "dia" es 1 para {fecha_ini}, 2 para el siguiente día, etc. "fecha" debe ser YYYY-MM-DD.
3. Para cada acto, indica la hora si está disponible (formato HH:MM, ej. "12:00", "23:30"), o "" si no especifica hora.
4. Traduce descripciones al castellano.

Devuelve SOLO JSON estricto con esta estructura:
{{
  "programa": [
    {{
      "dia": 1,
      "fecha": "YYYY-MM-DD",
      "eventos": [
        {{ "hora": "HH:MM", "descripcion": "Descripción del acto o evento" }}
      ]
    }}
  ]
}}"""

    user_prompt = (
        f"FIESTA: {nombre_fiesta} ({fecha_ini} a {fecha_fin})\n\n"
        f"TEXTO RECUPERADO:\n{texto_traducido}\n\n"
        f"Genera el programa de actos en formato JSON. Responde SOLO con JSON:\n```json\n"
    )

    try:
        parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=LMSTUDIO_CHAT_MAX_TOKENS)
        if parsed and isinstance(parsed, dict) and "programa" in parsed:
            prog = parsed["programa"]
            if isinstance(prog, list):
                fiesta["programa"] = prog
                logger.info(f"  [ENRICHMENT] '{nombre_fiesta}' enriquecida con {len(prog)} días de programa.")
            else:
                fiesta.setdefault("programa", [])
        else:
            fiesta.setdefault("programa", [])
    except Exception as e:
        logger.warning(f"  [ENRICHMENT] Error enriqueciendo '{nombre_fiesta}': {e}")
        fiesta.setdefault("programa", [])

    return fiesta


async def retrieve_discovery_context(
    indexed_chunks: list[dict],
    municipio: dict,
    localidad: dict,
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
    max_chars: int = DISCOVERY_MAX_CHARS,
) -> tuple[str, set]:
    """Recupera los top 10-15 chunks (~15,000 chars) para el contexto del Discovery Pass."""
    if not indexed_chunks:
        return "", set()

    comunidad = municipio.get("comunidad_autonoma", "")
    provincia = municipio.get("provincia", "")
    perfil_data = get_language_profile(comunidad, provincia)
    terminos_rag = perfil_data["perfil_principal"]["terminos_rag"]

    query_discovery = (
        f"{terminos_rag} en {municipio['nombre']} "
        f"para la localidad de {localidad['nombre']} en el año {anno}"
    )

    items_copy = [dict(item) for item in indexed_chunks]
    query_emb = None
    if rag_processor is not None:
        try:
            async with aiohttp.ClientSession() as session:
                query_embs = await rag_processor.get_embeddings_batch(session, [query_discovery])
                query_emb = query_embs[0] if query_embs else None
        except Exception as e:
            logger.warning(f"Error obteniendo embedding de la query de discovery: {e}")

    if query_emb:
        for item in items_copy:
            item["score"] = AsyncRAGProcessor.cosine_similarity(query_emb, item.get("embedding")) if item.get("embedding") else 0.0
    else:
        for item in items_copy:
            item["score"] = 0.0

    seleccion = seleccionar_chunks(items_copy, max_chars, RAG_UMBRAL_SIMILITUD if query_emb else -1.0)
    if not seleccion:
        seleccion = sorted(items_copy, key=lambda i: (i["prioridad"], -i.get("score", 0.0)))[:15]

    contexto = ensamblar_contexto(seleccion)
    fuentes_contexto = {i["fuente"] for i in seleccion}
    return contexto, fuentes_contexto


async def analyze_festivals_multipass(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    anno: int,
    fecha_patron=None,
    rag_processor: AsyncRAGProcessor | None = None,
    logger: logging.Logger | None = None,
    analyzer_fn=None,
) -> list[dict]:
    """
    Coordinador de la arquitectura RAG Multi-Pass:
    1. Pre-indexa chunks y embeddings con index_document_chunks.
    2. Recupera el contexto de discovery (top 10-15 chunks, ~15,000 chars / ~5.8K tokens).
    3. Ejecuta Discovery Pass a través de analyzer_fn o discover_festivals_for_locality.
    4. Ejecuta Enrichment Pass (enrich_festival_program) por cada fiesta descubierta.
    5. Devuelve la lista final de fiestas validadas y enriquecidas.
    """
    if not documentos:
        return []

    if rag_processor is None:
        rag_processor = AsyncRAGProcessor()

    # Paso 1: Indexar chunks y calcular embeddings 1 sola vez
    indexed_chunks = await index_document_chunks(rag_processor, documentos)
    if not indexed_chunks:
        return []

    # Paso 2: Obtener contexto de discovery
    discovery_context, fuentes_contexto = await retrieve_discovery_context(
        indexed_chunks=indexed_chunks,
        municipio=municipio,
        localidad=localidad,
        anno=anno,
        rag_processor=rag_processor,
        max_chars=DISCOVERY_MAX_CHARS,
    )

    if not discovery_context.strip():
        return []

    # Paso 3: Discovery Pass
    if analyzer_fn is not None:
        fiestas_descubiertas = await analyzer_fn(
            municipio, localidad, discovery_context, anno, fecha_patron, fuentes_contexto
        )
    else:
        fiestas_descubiertas = await discover_festivals_for_locality(
            municipio=municipio,
            localidad=localidad,
            documentos=documentos,
            indexed_chunks=indexed_chunks,
            anno=anno,
            rag_processor=rag_processor,
            fecha_patron=fecha_patron,
        )

    if not fiestas_descubiertas:
        return []

    # Paso 4: Enrichment Pass por fiesta
    fiestas_enriquecidas = []
    for fiesta in fiestas_descubiertas:
        f_enriched = await enrich_festival_program(
            municipio=municipio,
            localidad=localidad,
            fiesta=fiesta,
            indexed_chunks=indexed_chunks,
            anno=anno,
            rag_processor=rag_processor,
        )
        fiestas_enriquecidas.append(f_enriched)

    return fiestas_enriquecidas


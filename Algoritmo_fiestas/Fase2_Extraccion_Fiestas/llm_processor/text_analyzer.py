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
    LMSTUDIO_EMBEDDING_URL,
    LMSTUDIO_CHAT_URL,
    LMSTUDIO_EMBEDDING_MODEL,
    LMSTUDIO_CHAT_MODEL,
    LMSTUDIO_CHAT_TIMEOUT,
    LMSTUDIO_EMBEDDING_TIMEOUT,
    LMSTUDIO_CHAT_TEMPERATURE,
)

logger = logging.getLogger("text_analyzer")

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
""".strip()


# ──────────────────────────────────────────────────
# RAG PROCESSOR (async, batch embeddings)
# ──────────────────────────────────────────────────

class AsyncRAGProcessor:
    """Procesador RAG con embeddings en batch y saturación a ~27k tokens."""

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

    def chunk_text(self, text: str) -> list[str]:
        """Fragmenta texto en chunks con overlap."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start += (self.chunk_size - self.chunk_overlap)
        return chunks

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

    async def saturate_context(self, text: str, query: str) -> str:
        """Fragmenta, vectoriza en batch y satura contexto por relevancia."""
        logger.info(f"  RAG: Fragmentando texto ({len(text)} chars)...")
        chunks = self.chunk_text(text)
        if not chunks:
            return ""

        logger.info(f"  RAG: {len(chunks)} chunks. Vectorizando en batches de {self.batch_size}...")

        async with aiohttp.ClientSession() as session:
            # Obtener embedding de la query
            query_embeddings = await self.get_embeddings_batch(session, [query])
            query_emb = query_embeddings[0] if query_embeddings else None

            if not query_emb:
                # Fallback: devolver el texto truncado
                logger.warning("  RAG: No se pudo obtener embedding de la query. Usando fallback.")
                return text[:self.context_limit_chars]

            # Vectorizar chunks en batches
            all_embeddings = []
            for i in range(0, len(chunks), self.batch_size):
                batch = chunks[i : i + self.batch_size]
                batch_embs = await self.get_embeddings_batch(session, batch)
                all_embeddings.extend(batch_embs)

        # Puntuar y ordenar
        scored_chunks = []
        for chunk, emb in zip(chunks, all_embeddings):
            score = self.cosine_similarity(query_emb, emb) if emb else 0
            scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # Saturar hasta el límite de caracteres
        current_chars = 0
        selected_chunks = []

        for score, chunk in scored_chunks:
            if current_chars + len(chunk) > self.context_limit_chars:
                break
            selected_chunks.append(chunk)
            current_chars += len(chunk)

        logger.info(
            f"  RAG: Seleccionados {len(selected_chunks)}/{len(chunks)} chunks "
            f"({current_chars} chars ≈ {int(current_chars / RAG_CHARS_PER_TOKEN)} tokens)"
        )
        return "\n...\n".join(selected_chunks)


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


def validar_fiestas(fiestas_raw: list[dict], localidad: dict, anno: int) -> list[dict]:
    """Validación robusta de las fiestas extraídas por el LLM."""
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

        # 6. Generar slug si no existe o es inválido
        if not f.get("id") or not re.match(r"^[a-z0-9\-]+$", f.get("id", "")):
            slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower())
            slug = slug.strip("-")[:60]
            f["id"] = f"{slug}-{localidad['id']}"

        fiestas_validas.append(f)

    # 7. Deduplicar
    fiestas_validas = _deduplicar_fiestas(fiestas_validas)

    return fiestas_validas


# ──────────────────────────────────────────────────
# INFERENCIA LLM
# ──────────────────────────────────────────────────

async def analyze_festivals_for_locality(
    municipio: dict,
    localidad: dict,
    texto_filtrado: str,
    anno: int,
) -> list[dict]:
    """
    Llama al LLM para extraer fiestas de una localidad concreta.
    Incluye el criterio de fiestas y validación post-generación.
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

    user_prompt = (
        f"AÑO: {anno}\n\n"
        f"TEXTO RECUPERADO:\n{texto_traducido}\n\n"
        f"Extrae las fiestas en formato JSON exclusivamente para {localidad['nombre']}. Recuerda, responde SOLO con JSON:\n```json\n"
    )

    payload = {
        "model": LMSTUDIO_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LMSTUDIO_CHAT_TEMPERATURE,
        "max_tokens": 1500,  # Prevenir bucles infinitos y alucinaciones masivas
    }

    # Global semaphore to ensure only ONE request hits the local LLM at a time, preventing VRAM overflow
    global _llm_semaphore
    if '_llm_semaphore' not in globals():
        _llm_semaphore = asyncio.Semaphore(1)

    try:
        async with _llm_semaphore:
            logger.info(f"  Llamando a {LMSTUDIO_CHAT_MODEL} (Locality-Centric)...")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    LMSTUDIO_CHAT_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=LMSTUDIO_CHAT_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"]["content"]

                        # Limpiar posible basura final (ej. si corta por max_tokens o añade ```)
                        
                        # Limpiar posible basura final (ej. si corta por max_tokens o añade ```)
                        content = content.replace("```json", "").replace("```", "").strip()

                        try:
                            # Limpiar comas sueltas típicas de modelos pequeños antes de un ] o }
                            content = re.sub(r',\s*([\]}])', r'\1', content)
                            parsed = json.loads(content)
                        except json.JSONDecodeError as e:
                            logger.error(f"  JSON malformado del LLM: {e}")
                            # Intentar extraer JSON parcial si falló el primer intento
                            # Como inyectamos "{", el primer match ya debería ser el JSON
                            match = re.search(r"\{.*\}", content, re.DOTALL)
                            if match:
                                try:
                                    parsed = json.loads(match.group())
                                except json.JSONDecodeError:
                                    logger.error(f"  No se pudo recuperar JSON parcial.")
                                    return []
                            else:
                                return []

                        fiestas_raw = parsed.get("fiestas", [])
                        fiestas_validas = validar_fiestas(fiestas_raw, localidad, anno)

                        logger.info(
                            f"  Resultado: {len(fiestas_validas)} fiestas válidas "
                            f"(de {len(fiestas_raw)} generadas) para {localidad['nombre']}"
                        )
                        return fiestas_validas
                    else:
                        error_body = await resp.text()
                        logger.error(f"  Error LLM: status {resp.status} — {error_body[:200]}")

    except asyncio.TimeoutError:
        logger.error(f"  Timeout del LLM tras {LMSTUDIO_CHAT_TIMEOUT}s")
    except Exception as e:
        logger.error(f"  Error LLM: {e}")

    return []

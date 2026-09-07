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
import unicodedata
from datetime import datetime, date, timedelta

import aiohttp

from llm_processor.patron_finder import buscar_en_santoral, clave_en_santoral

from config import (
    RAG_MAX_TOKENS,
    RAG_CHARS_PER_TOKEN,
    RAG_CHUNK_SIZE,
    RAG_CHUNK_OVERLAP,
    RAG_EMBEDDING_BATCH_SIZE,
    RAG_PROGRAMA_MAX_CHARS,
    RAG_UMBRAL_SIMILITUD,
    RAG_MIN_OFICIALES_SIN_UMBRAL,
    ENRICHMENT_BONUS_OFICIAL,
    ENRICHMENT_TOP_GARANTIZADOS,
    ENRICHMENT_DIAS_POR_LLAMADA,
    ANTICOPIA_MIN_DOCS_DIRECTOS,
    ANTICOPIA_MIN_ACTOS_COMUNES,
    ANTICOPIA_FRACCION_COPIA,
    ANTICOPIA_MIN_PALABRAS_VERBATIM,
    ANTICOPIA_MIN_ACTOS_DUP_INTERNO,
    ANTICOPIA_FRACCION_DUP_INTERNO,
    ANCLA_PESO_MINIMO,
    ANCLA_PESO_MINIMO_CORRECCION,
    ANCLA_MAX_DIAS,
    ANCLA_PESO_MINIMO_EXTRA,
    ANCLA_MAX_FIESTAS_EXTRA,
    ANCLA_EVIDENCIA_CHARS,
    PROCEDENCIA_CHARS,
    PROCEDENCIA_MAX_TOKENS,
    PERTENENCIA_ENABLED,
    PERTENENCIA_MAX_TOKENS,
    PERTENENCIA_CONTEXTO_TOKENS,
    PERTENENCIA_DESCARTAR_SI_DUDA,
    ENRICHMENT_MIN_ACTOS_EN_PAGINA,
    COBERTURA_DIAS_MINIMA,
    DISCOVERY_MIN_CHUNKS_MES_PROPIO,
    DISCOVERY_MAX_LLAMADAS_LOCALIDAD,
    ANCLA_MAX_RANGOS_POR_SEGMENTO,
    ANCLA_DIAS_DE_SEPARACION,
    ANCLA_MIN_DIAS_TRAS_RECORTE,
    ANCLA_MAX_CHARS_A_LA_LOCALIDAD,
    LLM_FACTOR_REINTENTO_TRUNCADO,
    LLM_TOPE_REINTENTO,
    LLM_REINTENTOS_429,
    LLM_BACKOFF_429,
    RECORTE_PROGRAMA_MIN_DIAS,
    PROGRAMA_MIN_CHARS_ACTO_UNICO,
    DISCOVERY_TOP_GARANTIZADOS,
    LMSTUDIO_EMBEDDING_URL,
    LMSTUDIO_CHAT_URL,
    LMSTUDIO_EMBEDDING_MODEL,
    LMSTUDIO_CHAT_MODEL,
    LMSTUDIO_CHAT_TIMEOUT,
    LMSTUDIO_EMBEDDING_TIMEOUT,
    LMSTUDIO_CHAT_TEMPERATURE,
    LMSTUDIO_CHAT_MAX_TOKENS,
    LMSTUDIO_SEED,
    OPENROUTER_ENABLED,
    OPENROUTER_API_KEY,
    OPENROUTER_CHAT_URL,
    OPENROUTER_MODELS,
    OPENROUTER_CHAT_TIMEOUT,
    LLM_SEGUNDOS_POR_1K_TOKENS,
    LLM_TIMEOUT_MAXIMO,
    OPENROUTER_N_CTX,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_CONCURRENCY,
    OPENROUTER_PAUSA_ENTRE_MODELOS,
    OPENROUTER_REFERER,
    OPENROUTER_TITLE,
)
from llm_processor.festival_filter import (
    sanear_fiesta, evaluar_fiesta, fusionar_fiestas_proximas, validar_fechas_moviles,
    meses_de_fiestas_moviles, tiene_senal_nocturna,
)
from fuentes import (
    es_fuente_oficial,
    es_fuente_valida,
    fuente_base,
    FUENTE_BUSQUEDA,
    FUENTE_HISTORICO,
    FUENTE_PRENSA_REGIONAL,
    prioridad_fuente,
    rotulo_fuente,
    generar_cabecera_chunk,
    clasificar_relevancia_chunk,
    clasificar_relevancia_documento,
    documento_es_ajeno_al_municipio,
    documento_avalado_solo_por_la_localidad,
    web_es_de_este_lugar,
    procedencia_contradice_al_lugar,
    lengua_cooficial_detectada,
    parece_listado_institucional,
    normalize_text,
    FUENTE_WEB_MUNICIPIO,
    FUENTE_WEB_LOCALIDAD,
    FUENTE_RRSS_LOCALIDAD,
)
from config_idiomas import comunidad_de, get_language_profile, perfil_de_lugar
from senales_festivas import (
    PATRON_HORA, contar_actos_horarios, tiene_termino_festivo, unir_hora_con_acto,
)
from context_budget import (
    contar_tokens,
    get_n_ctx,
    get_model_info,
    registrar_uso_real,
    resumen_presupuesto,
    tokens_por_lote,
    OVERHEAD_PLANTILLA_TOKENS,
    RESERVA_SALIDA_DISCOVERY,
    RESERVA_SALIDA_ENRICHMENT,
)
from debug_contexto import volcar_contexto
from higiene_documentos import es_texto_tabular
from ranking_chunks import puntuar_chunks, umbral_adaptativo, chunks_garantizados
from reparto_contexto import repartir_en_lotes, resumen_reparto
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
    perfil_data = perfil_de_lugar(municipio)
    
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

# En OpenRouter no hay VRAM que proteger, así que la restricción no es la misma:
# lo que limita es el cupo por minuto del nivel gratuito. Semáforo aparte para no
# arrastrar el cuello de botella del local a las llamadas en la nube.
LLM_SEMAPHORE_REMOTO = asyncio.Semaphore(max(1, OPENROUTER_CONCURRENCY))

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

MARCADORES DE RELEVANCIA GEOGRÁFICA:
Cada fragmento tiene un indicador de relevancia:
- "DIRECTA": El texto menciona explícitamente la localidad que estás analizando.
  → Información de alta confianza para esta localidad.
- "GENERAL": El texto NO menciona ninguna localidad específica.
  → Puede ser de cualquier localidad del municipio. Usar con precaución.
Si un programa de actos aparece marcado como GENERAL y menciona lugares físicos
(plazas, frontones, calles) que no son de la localidad, ignóralo.
""".strip()


# ──────────────────────────────────────────────────
# CHUNKING POR DOCUMENTOS (no corta programas ni mezcla fuentes)
# ──────────────────────────────────────────────────

# La misma hora que reconoce el detector de actos, y por el mismo motivo por el
# que `unir_hora_con_acto` se aplica aquí: si el troceador y el detector no leen
# lo mismo, el "modo programa" no se activa en los documentos que existen para él.
#
# El patrón propio que había aquí —`\b\d{1,2}[:.h]\d{2}\b`— no reconocía
# "10:00h", "12:00h." ni "9:30h", que es como se escribe un programa de fiestas
# en español: la "h" pegada al minuto se come el `\b` final. Medido el
# 2026-09-04 sobre los 159 contextos de enrichment de la última ejecución, se le
# escapaba el 18% de las líneas con hora (2.491 de 13.739), de modo que en los
# programas con ese formato el modo programa no llegaba a arrancar y el programa
# se troceaba con el `chunk_size` normal.
_RE_HORA_PROGRAMA = PATRON_HORA


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

    Antes de trocear se pegan las horas que van solas en su línea con el acto que
    llevan debajo. Se hace AQUÍ, en el único sitio por el que pasan los dos
    caminos de indexado, para que el modelo lea el programa igual que lo cuenta
    el detector: una hora suelta y un acto suelto son, además, dos unidades que
    el troceador puede separar en chunks distintos.
    """
    unidades = _dividir_en_unidades(unir_hora_con_acto(texto))
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




def filtrar_chunks_por_localidad(
    items: list[dict],
    localidad_nombre: str,
    nombres_hermanas: list[str],
    penalizar_general: bool = True,
) -> list[dict]:
    """
    Filtro geográfico para chunks.
    Solo penaliza o descarta chunks de fuente 'web_municipio' cuando se procesa una pedanía.

    Usa la relevancia pre-calculada a nivel de documento (doc_relevancia) cuando está
    disponible, para que chunks de programas de actos (horarios sin nombre de pueblo)
    hereden la relevancia de la página completa de la que proceden.
    Si no hay doc_relevancia, clasifica el chunk individual como fallback.
    """
    # Qué páginas están ya avaladas por alguno de sus propios fragmentos. El
    # interior de un programa no repite el nombre del pueblo —dice "12:00h Misa
    # de la fiesta principal" y nada más—, así que sale GENERAL y se lleva una
    # penalización que lo deja fuera del contexto. Medido el 2026-08-27 en
    # Sinovas: su programa se parte en cuatro fragmentos, tres nombran "Sinovas"
    # y el cuarto —el de los días 23 al 26, con 14 de sus 58 actos— no. Ese fue
    # el único que no llegó al modelo, y el modelo rellenó esos días con actos
    # de los días siguientes, cambiándoles la fecha.
    #
    # Si un fragmento de la página la sitúa aquí, la página es de aquí y sus
    # demás fragmentos también. La herencia ya existía para la web del
    # municipio; esto la extiende a lo que viene de los buscadores, que es de
    # donde salen los programas de las pedanías.
    avaladas: set[str] = set()
    if nombres_hermanas:
        for item in items:
            url = item.get("url") or ""
            if not url or url == "buscadores:snippets" or url in avaladas:
                continue
            if clasificar_relevancia_chunk(
                item["chunk"], localidad_nombre, nombres_hermanas) == "DIRECTA":
                avaladas.add(url)

    filtrados = []
    es_pedania = bool(nombres_hermanas)
    for item in items:
        fuente = fuente_base(item["fuente"])
        url = item.get("url") or ""
        hereda = url in avaladas

        # Solo aplicar a chunks genéricos del municipio
        if fuente == FUENTE_WEB_MUNICIPIO and es_pedania:
            # Prioridad: relevancia del documento padre > relevancia del chunk.
            # El documento padre puede haber sido clasificado como 'DESCARTAR'
            # (la página va de una hermana). Antes ese veredicto se guardaba como
            # None, indistinguible de "sin clasificar", y el fallback por chunk lo
            # borraba: el descarte a nivel de documento nunca llegaba a aplicarse.
            doc_rel = item.get("doc_relevancia")
            if doc_rel is not None:
                relevancia = None if doc_rel == "DESCARTAR" else doc_rel
                # La herencia tiene un límite: un documento no puede hacer
                # DIRECTA a un chunk que es un listado de organismos.
                #
                # Medido el 2026-08-25 en Sierra. Su contexto de enriquecimiento
                # eran 6.073 caracteres del desplegable «cambiar de sede» de un
                # portal administrativo —la lista de todos los ayuntamientos de
                # Albacete—, rotulado «fiabilidad MUY ALTA | Relevancia: DIRECTA»
                # porque «Sierra» aparecía suelta en el documento padre. Con ese
                # aval, el modelo devolvió 39 actos inventados con confianza alta.
                # Bajarlo a GENERAL no lo descarta, solo deja de mentirle al
                # modelo sobre lo que le estamos dando.
                if relevancia == "DIRECTA" and parece_listado_institucional(item["chunk"]):
                    relevancia = "GENERAL"
            else:
                # Fallback: clasificar el chunk individual
                relevancia = clasificar_relevancia_chunk(item["chunk"], localidad_nombre, nombres_hermanas)

            if relevancia is None:
                # Descarta chunk porque pertenece a otra pedanía explícitamente
                continue
            elif relevancia == "GENERAL" and penalizar_general:
                # No se sabe, penaliza un poco el score si ya lo tenía
                item["score"] = max(0.0, item.get("score", 0.0) - 0.10)
            elif relevancia == "DIRECTA":
                # Es específico para la localidad
                item["score"] = item.get("score", 0.0) + 0.15

            item["relevancia_geo"] = relevancia
        elif es_pedania and fuente not in (FUENTE_WEB_LOCALIDAD,) and not fuente.startswith(FUENTE_RRSS_LOCALIDAD):
            # RRSS del municipio y resultados de buscador NO son de la pedanía por
            # defecto. Marcarlos DIRECTA a ciegas contradecía la propia cabecera
            # del chunk ("AVISO: pertenece al MUNICIPIO, NO a la pedanía") y le
            # decía al modelo que el programa del pueblo grande era de la aldea.
            # Se les clasifica por su contenido, como a cualquier otro texto.
            relevancia = clasificar_relevancia_chunk(item["chunk"], localidad_nombre, nombres_hermanas)
            if relevancia is None:
                continue
            # El fragmento sin topónimo de una página que sí lo tiene: es el
            # cuerpo del programa, no un texto de otro pueblo.
            if relevancia == "GENERAL" and hereda:
                relevancia = "DIRECTA"
                item["relevancia_heredada"] = True
            if relevancia == "GENERAL" and penalizar_general:
                item["score"] = max(0.0, item.get("score", 0.0) - 0.10)
            elif relevancia == "DIRECTA":
                item["score"] = item.get("score", 0.0) + 0.15
            item["relevancia_geo"] = relevancia
        else:
            # Fuente propia de la localidad, o se está procesando el núcleo
            # principal del municipio: el material es suyo por definición.
            item["relevancia_geo"] = "DIRECTA"

        filtrados.append(item)
    return filtrados

def seleccionar_chunks(
    items: list[dict],
    budget_chars: int,
    umbral: float = RAG_UMBRAL_SIMILITUD,
    min_oficiales: int = RAG_MIN_OFICIALES_SIN_UMBRAL,
    garantizados: list[dict] | None = None,
) -> list[dict]:
    """
    FUERA DE LA RUTA PRINCIPAL desde el 2026-09-03. Solo lo usa
    `AsyncRAGProcessor.saturate_context_docs`, que es la ruta heredada. El
    discovery y el enrichment reparten con `reparto_contexto.repartir_en_lotes`
    y no descartan nada: era este empaquetador, y no el ranking, quien decidía
    qué veía el modelo —el 5,7% de los chunks en discovery—.

    Selección por cuotas de prioridad sobre items PRE-FILTRADOS y PRE-PONDERADOS.
    items: {chunk, fuente, url, es_calendario, prioridad, score}.
    1º entran los chunks GARANTIZADOS (mejores páginas según la araña);
    2º los chunks relevantes de fuentes OFICIALES (por prioridad y score);
    la búsqueda web solo rellena el presupuesto restante: un chunk oficial nunca
    es expulsado por uno de buscador.

    Sigue siendo un empaquetador puro: no modifica el score de ningún item.
    """
    seleccion = []
    usados = 0
    ya_dentro = set()

    # Reserva para las mejores páginas de la araña. Entran las primeras porque
    # son las que no pueden faltar, no porque puntúen más.
    for i in (garantizados or []):
        if id(i) in ya_dentro:
            continue
        if usados + len(i["chunk"]) > budget_chars:
            continue
        seleccion.append(i)
        ya_dentro.add(id(i))
        usados += len(i["chunk"])

    oficiales = [i for i in items if es_fuente_oficial(i["fuente"])]
    externos = [i for i in items if not es_fuente_oficial(i["fuente"])]

    oficiales_rel = [i for i in oficiales if i["score"] >= umbral]
    if not oficiales_rel and oficiales:
        # Red de seguridad: nunca dejar fuera TODO lo oficial por el umbral
        oficiales_rel = sorted(oficiales, key=lambda i: -i["score"])[:min_oficiales]

    for i in sorted(oficiales_rel, key=lambda i: (i["prioridad"], -i["score"])):
        if id(i) in ya_dentro:
            continue
        if usados + len(i["chunk"]) > budget_chars:
            continue
        seleccion.append(i)
        ya_dentro.add(id(i))
        usados += len(i["chunk"])

    for i in sorted(externos, key=lambda i: -i["score"]):
        if i["score"] < umbral:
            break
        if id(i) in ya_dentro:
            continue
        if usados + len(i["chunk"]) > budget_chars:
            continue
        seleccion.append(i)
        ya_dentro.add(id(i))
        usados += len(i["chunk"])

    return seleccion


# Los doce, por su número de mes. Para mirar si un texto habla del mes de una
# fiesta sin tener que invertir _MES_A_NUMERO, que trae abreviaturas y duplica
# septiembre.
_MESES_EN_ORDEN = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_MES_A_NUMERO = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
}
# Solo nombres completos, y enumerados a mano. Entre las abreviaturas de
# _MES_A_NUMERO esta "mar", que en castellano es palabra corriente y daria marzo
# en cualquier texto de costa. Pero filtrarlas por longitud tampoco vale: se
# probo con `len(m) > 4` y dejaba fuera "mayo", que tiene cuatro letras, de modo
# que el programa del Cristo de Tobarra --donde pone <<Del 15 al 23 de mayo>>--
# seguia colandose como programa de la fiesta de enero.
_MESES_COMPLETOS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_RE_MESES = r"\b(" + "|".join(_MESES_COMPLETOS) + r")\b"


_RE_MARCADOR_ORIGEN = re.compile(r"\s*\|\s*ORIGEN:\s*\S*")


def _sin_marcador_de_origen(chunk: str) -> str:
    """
    Quita de los snippets el «| ORIGEN: url» antes de que lo vea el modelo.

    Ese marcador se añade al recoger los snippets para poder purgar los de una
    URL descartada; al modelo no le sirve de nada y sí le estorba. Medido el
    2026-08-26: a Sierra le salió una ficha llamada «Fiestas de San Francisco
    Javier Origen Https», con el marcador incrustado en el nombre de la fiesta.
    """
    return _RE_MARCADOR_ORIGEN.sub("", chunk or "")


def paginas_del_contexto(contexto: str) -> list[tuple[str, str]]:
    """Parte el contexto en (dirección, texto) por cada bloque de página."""
    trozos = re.split(r"--- \[([^\]]+)\] \| Relevancia[^-]*---", contexto or "")
    return [(trozos[i], trozos[i + 1]) for i in range(1, len(trozos) - 1, 2)]


def _normalizar_para_meses(texto: str) -> str:
    """Minúsculas y sin tildes, para que "Setiembre" y "SEPTIEMBRE" cuenten igual."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _habla_de_otro_mes(texto: str, meses_fiesta: set[int]) -> bool:
    """
    ¿Esta página nombra meses, y ninguno es el de la fiesta?

    La ausencia no descarta: muchos programas solo dicen «día 14, día 15» y el
    mes está en el cartel. Lo que descarta es nombrar OTROS meses y no el nuestro.
    """
    if not meses_fiesta:
        return False
    citados = {_MESES_COMPLETOS[m] for m in re.findall(_RE_MESES, _normalizar_para_meses(texto))}
    return bool(citados) and not (citados & meses_fiesta)


# Palabras que aparecen en el nombre de cualquier fiesta y por tanto no
# distinguen a una de otra dentro del mismo pueblo.
_PALABRAS_NO_DISTINGUEN = frozenset({
    "fiestas", "fiesta", "festividad", "patronales", "patronal", "mayores",
    "honor", "verano", "invierno", "primavera", "otono", "barrio", "pueblo",
    "villa", "ciudad", "municipio", "programa", "feria", "ferias",
})


_RE_ANNO_EN_URL = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")


def anno_del_documento(url: str, texto: str = "") -> int | None:
    """
    El año del que habla un documento, o None si no se puede decir.

    Manda la URL, que es donde los gestores de contenido dejan la fecha sin
    ambigüedad: `uploads/2025/09/PROGRAMA-FIESTAS…` es el programa de 2025 por
    mucho que su texto nombre también el 2026. Si la URL no dice nada, vale que
    el TEXTO nombre un solo año.

    Existe porque sin esto el pipeline rellenaba fichas con programas viejos y
    las daba por buenas: el 2026-08-27, Aranda de Duero salió con 21 actos y
    `confianza: alta` sacados del programa de 2025 del propio ayuntamiento, y
    Sinovas con 39 del de 2024. Peor que quedarse vacío, porque no se ve.
    """
    annos_url = {int(a) for a in _RE_ANNO_EN_URL.findall(url or "")}
    if len(annos_url) == 1:
        return annos_url.pop()
    if annos_url:
        return max(annos_url)  # `/2025/09/programa-2025` → 2025
    annos_texto = {int(a) for a in _RE_ANNO_EN_URL.findall(texto or "")}
    return annos_texto.pop() if len(annos_texto) == 1 else None


def es_de_otro_anno(url: str, texto: str, anno: int | None) -> bool:
    """¿Este documento es, sin lugar a dudas, de un año que no es el nuestro?"""
    if not anno:
        return False
    del_doc = anno_del_documento(url, texto)
    return del_doc is not None and del_doc != anno


def tokens_distintivos(nombre_fiesta: str, localidad_nombre: str = "") -> set[str]:
    """
    Palabras que identifican a ESTA fiesta frente a otra del mismo pueblo.

    Es casi siempre la advocación: lo que separa el Cristo de la Antigua de
    Tobarra de su San Roque es "antigua" contra "roque", no el mes ni el pueblo.
    Por eso se quita el nombre de la localidad —sale en todas las páginas del
    contexto y no distingue nada— y las palabras de relleno.

    Devuelve un conjunto vacío cuando el nombre no aporta ninguna seña propia
    ("Fiestas Patronales de Tobarra Verano 2026", "Fiestas de Aranda de Duero").
    Vacío significa "no se puede decidir por aquí", no "no coincide": el
    2026-08-27 una primera versión comparaba la frase entera —"tobarra mayo 2026
    bajada ofrenda floral"— contra el texto de la página, no casaba nunca, y
    avisó de advocación ajena en cuatro fichas que estaban bien.
    """
    santo = clave_en_santoral(nombre_fiesta) or ""
    tokens = set(_clave_advocacion(santo).split())
    if not tokens:
        tokens = set(_clave_advocacion(nombre_fiesta).split())
    tokens -= _PALABRAS_NO_DISTINGUEN
    tokens -= set(_clave_advocacion(localidad_nombre or "").split())
    return {t for t in tokens if len(t) >= 4 and not t.isdigit()}


def cuenta_tokens(tokens: set[str], texto: str) -> int:
    """Veces que las señas de una fiesta aparecen en un texto."""
    if not tokens:
        return 0
    plano = _plano(texto)
    return sum(len(re.findall(rf"\b{re.escape(t)}\b", plano)) for t in tokens)


def pagina_entera(indexed_chunks: list[dict], url: str) -> list[dict]:
    """
    Todos los fragmentos de una página, en su orden de lectura.

    Si el código ha decidido que el programa está en una página, el modelo tiene
    que ver esa página ENTERA. Antes sus fragmentos competían por el presupuesto
    con todo lo demás y podían caerse: el 2026-08-27 el programa de Sinovas se
    partió en cuatro, y el trozo de los días 23 al 26 —14 de sus 58 actos— fue
    el único que no llegó, porque es el único que no repite el nombre del pueblo
    y el filtro geográfico lo penalizó. El modelo rellenó esos días con actos de
    los días siguientes, cambiándoles la fecha.

    Cabe de sobra: medida la página de programa más pesada de todo el run
    —`sanroque26.pdf`— son 5.164 tokens de los 32.768 de la ventana.
    """
    trozos = [i for i in indexed_chunks if (i.get("url") or "") == url]
    return sorted(trozos, key=lambda i: i.get("indice_chunk", 0))


def texto_pagina_entera(indexed_chunks: list[dict], url: str) -> str:
    """
    El texto COMPLETO de una página, en su orden de lectura.

    Existe porque varias decisiones se estaban tomando sobre el trozo de página
    que había sobrevivido al recorte por presupuesto, y no sobre la página. Con
    el contexto mutilado, `contar_actos_horarios` cuenta de menos y
    `_habla_de_otro_mes` ve meses que no son los que la página trata.
    """
    return "\n".join(i.get("chunk", "") for i in pagina_entera(indexed_chunks, url))


def actos_del_documento(indexed_chunks: list[dict], urls: list[str]) -> int:
    """Actos con hora de la página más completa de `urls`, leída ENTERA."""
    return max(
        (contar_actos_horarios(texto_pagina_entera(indexed_chunks, u)) for u in urls),
        default=0,
    )


def _contexto_con_las_paginas_enteras(
    chunks_finales: list[dict], indexed_chunks: list[dict], urls: list[str],
    anno: int | None = None,
) -> tuple[list[dict], int, int]:
    """
    FUERA DE LA RUTA VIVA desde el 2026-09-03. Su tope de ENRICHMENT_MAX_CHARS
    es lo que dejaba entrar 14 de los 82 fragmentos del PDF de Aranda; ahora el
    enrichment coge la página entera y la reparte con `repartir_en_lotes`.
    Se conserva porque sus tests documentan el comportamiento que se retiró.

    Rehace la selección poniendo delante y completas las páginas del programa.

    Son varias porque el programa puede estarlo: una fiesta larga se publica a
    veces en dos entradas, o el cartel va en un PDF y los horarios en la
    noticia. El orden entre ellas es el de `urls`, que es el del localizador
    —lo que él pone primero es lo que más se parece al programa—.

    Si no caben todas se corta por el FINAL, nunca por el medio:
    `ensamblar_contexto` marca el salto con […] y el prompt le explica al modelo
    qué significa esa marca, así que lee una página truncada y no una con
    agujeros. Con las páginas reales no llega a pasar —la mayor de todo el run
    son 13.921 caracteres de los 32.000 del presupuesto—, pero un cartel de
    veinte páginas sí lo haría.

    Devuelve (selección, fragmentos inyectados, fragmentos disponibles).
    """
    disponibles: list[dict] = []
    vistos: set[int] = set()
    for url in urls:
        for item in pagina_entera(indexed_chunks, url):
            if id(item) not in vistos:
                vistos.add(id(item))
                disponibles.append(item)

    inyectados, usados = [], 0
    for item in disponibles:
        if usados + len(item["chunk"]) > ENRICHMENT_MAX_CHARS:
            break
        inyectados.append(item)
        usados += len(item["chunk"])

    # Con la página del programa ya identificada, el relleno de detrás solo
    # puede estorbar si es de otro año: el programa de 2024 de Sinovas quedaba
    # justo después del de 2026, y son casi idénticos salvo en las fechas.
    del_programa = set(urls)
    seleccion = list(inyectados)
    for item in chunks_finales:
        url = item.get("url") or ""
        if url in del_programa:
            continue
        if anno and es_de_otro_anno(url, item.get("chunk", ""), anno):
            continue
        if usados + len(item["chunk"]) > ENRICHMENT_MAX_CHARS:
            continue
        seleccion.append(item)
        usados += len(item["chunk"])
    return seleccion, len(inyectados), len(disponibles)


def vetar_paginas_imposibles(
    urls: list[str], contexto: str, fiesta: dict, anno: int | None = None,
    indexed_chunks: list[dict] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Quita de la elección del modelo las páginas que NO pueden ser el programa
    de esta fiesta, por calendario.

    El modelo propone y el código veta. Sabe leer lo que la regex no —distinguir
    un índice de un programa, ver que una noticia remite a otra web— pero no
    tiene delante el texto entero de cada candidata, solo un extracto, y con eso
    se lleva por delante lo que el filtro de meses ya había resuelto. Medido el
    2026-08-27, en cuanto el localizador entró en juego:

      - `radiotobarra.es/cristo26-1.pdf`, que es el programa de MAYO, salió
        elegido para las fiestas de AGOSTO de Tobarra y para una tercera ficha.
        Es la misma confusión que este proyecto ya había arreglado una vez.
      - Sierra recibió un cartel de un concierto de JUNIO como programa de sus
        fiestas de finales de julio.
      - El PDF de las patronales de septiembre de 2025 de Aranda se usó como
        programa de su Fiesta de la Cerveza (junio) y de su Fiesta de Peñas
        (julio).

    Devuelve (urls_validas, vetadas) donde cada vetada lleva su motivo.
    """
    ini = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio"))
    fin = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_fin"))
    meses = {ini.month, fin.month} if (ini and fin) else set()
    anno = anno or (ini.year if ini else None)

    # La página ENTERA cuando se puede, y el trozo del contexto solo como
    # respaldo. Juzgar una página por el fragmento que sobrevivió al recorte es
    # cómo se descartó el PROGRAMA-2026.pdf de Aranda de Duero para su propia
    # fiesta de septiembre: los fragmentos presentes citaban otros meses.
    textos = dict(paginas_del_contexto(contexto))
    if indexed_chunks:
        for u in urls:
            entera = texto_pagina_entera(indexed_chunks, u)
            if entera.strip():
                textos[u] = entera

    validas, vetadas = [], []
    for url in urls:
        texto = textos.get(url, "")
        if texto and _habla_de_otro_mes(texto, meses):
            vetadas.append((url, "habla de otros meses y no del de esta fiesta"))
            continue
        validas.append(url)

    # El año solo veta si queda alternativa: cuando el único programa que existe
    # es el del año pasado se usa igual, marcado, que para eso está
    # `programa_de_otro_anno`.
    del_anno = [u for u in validas if not es_de_otro_anno(u, textos.get(u, ""), anno)]
    if del_anno and len(del_anno) < len(validas):
        for u in validas:
            if u not in del_anno:
                vetadas.append((u, f"es de otro año y hay candidata de {anno}"))
        validas = del_anno

    return validas, vetadas


def _ordenar_para_el_presupuesto(chunks: list[dict], paginas_del_dia: list[dict]) -> list[dict]:
    """
    En qué orden se llenan los caracteres del contexto de enriquecimiento.

    Los snippets de buscador van al final, ocupen el puesto que ocupen por
    puntuación. Son dos líneas por sitio y siempre nombran el pueblo, así que
    puntúan alto y desplazan a las páginas que traen el programa de verdad: el
    2026-08-27, de los 31 fragmentos del contexto de Sinovas, 18 eran snippets y
    solo 3 eran su programa. Sirven para descubrir que la fiesta existe, no para
    escribir sus actos; si sobra presupuesto, entran igual.
    """
    def es_snippet(i: dict) -> bool:
        return (i.get("url") or "") == "buscadores:snippets"

    paginas = [i for i in chunks if not es_snippet(i)]
    snippets = [i for i in chunks if es_snippet(i)]

    mejores = sorted(paginas, key=lambda i: -i.get("score", 0.0))[:ENRICHMENT_TOP_GARANTIZADOS]
    garantizados = {id(i) for i in mejores}
    for i in sorted(paginas_del_dia, key=lambda i: fecha_de_url(i.get("url", "")) or date.max):
        if id(i) not in garantizados:
            mejores.append(i)
            garantizados.add(id(i))
    return (mejores
            + [i for i in paginas if id(i) not in garantizados]
            + sorted(snippets, key=lambda i: -i.get("score", 0.0)))


def mejor_pagina_con_programa(contexto: str, fiesta: dict | None = None) -> tuple[str, int]:
    """
    La página del contexto que más se parece al programa DE ESTA fiesta.

    Se mide en actos con hora de reloj porque es lo que distingue un programa de
    una página que habla de la fiesta. Medido el 2026-08-25 sobre los contextos
    reales de Tobarra: Cordovilla 14 actos con hora en elfarodehellin.com —y su
    ficha salió con 15 de 16 actos rastreables—, mientras que Sierra tenía CERO
    en todas sus páginas, y de ahí salieron 39 actos inventados con confianza
    alta. Los Mardos, también cero, produjo 5 actos de los que ninguno se pudo
    rastrear.

    Lo de «de esta fiesta» costó una segunda vuelta. La primera versión no
    miraba las fechas y señalaba `radiotobarra.es/cristo26-1.pdf` como el
    programa de TRES fiestas de Tobarra a la vez: San Antón (enero), San Roque
    (agosto) y el Cristo (mayo). Ese PDF cita «mayo» catorce veces y no nombra ni
    enero ni agosto: es el programa de una sola de las tres. De ahí salía que la
    ficha de enero llevara «Concierto en Plaza de España. Orquesta Señor
    Aliaga», que es un acto real de la fiesta de mayo.
    """
    meses = set()
    if fiesta:
        ini = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio"))
        fin = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_fin"))
        if ini and fin:
            meses = {ini.month, fin.month}

    # Y lo de «de esta fiesta» costó una tercera. El mes no separa dos fiestas
    # del mismo pueblo en el mismo mes: el 2026-08-26, para el Cristo de la
    # Antigua de Tobarra (9-17 de agosto) se eligió una página de agregador
    # sobre el SAN ROQUE de Tobarra, con 22 actos, teniendo en el mismo contexto
    # `radiotobarra.es/cristo26-1.pdf` con 11. La que gana el recuento no es
    # siempre la de la fiesta que se está enriqueciendo. Entre las páginas que
    # ya parecen un programa, manda la advocación.
    tokens = tokens_distintivos(
        (fiesta or {}).get("nombre", ""), (fiesta or {}).get("sede_segun_el_texto", ""),
    )

    # Y el año manda sobre todo lo demás. El programa del año pasado se parece
    # tanto al de este que gana cualquier comparación de contenido: el
    # 2026-08-27 Sinovas tenía en el mismo contexto su programa de 2026 y el de
    # 2024, y se llevó el de 2024 por traer más actos con hora.
    anno = None
    if fiesta:
        ini = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio"))
        anno = ini.year if ini else None

    candidatas = []
    for url, texto in paginas_del_contexto(contexto):
        if _habla_de_otro_mes(texto, meses):
            continue
        n = contar_actos_horarios(texto)
        if not n:
            continue
        del_anno = not es_de_otro_anno(url, texto, anno)
        candidatas.append((del_anno, cuenta_tokens(tokens, texto), n, url))
    if not candidatas:
        return "", 0

    # Por debajo del umbral no hay programa que elegir, así que ahí sigue
    # mandando el recuento: lo único que se devuelve es "no hay material".
    con_programa = [c for c in candidatas if c[2] >= ENRICHMENT_MIN_ACTOS_EN_PAGINA]
    del_anno, menciones, n, url = max(con_programa or candidatas)
    return url, n


def hay_material_para_un_programa(contexto: str, fiesta: dict | None = None) -> bool:
    """
    ¿Merece la pena pedirle el programa al modelo, o va a inventárselo?

    No se pierde nada real al decir que no: en las dos localidades donde ninguna
    página traía actos con hora, TODO lo que devolvió el modelo resultó ser
    irrastreable. Preguntar sin material no produce datos flojos, produce datos
    falsos.
    """
    return mejor_pagina_con_programa(contexto, fiesta)[1] >= ENRICHMENT_MIN_ACTOS_EN_PAGINA


from config import (
    PROGRAM_LOCATOR_ENABLED,
    PROGRAM_LOCATOR_SNIPPET_CHARS,
    PROGRAM_LOCATOR_MAX_CANDIDATES,
    PROGRAM_LOCATOR_MAX_ITERATIONS,
    PROGRAM_LOCATOR_MAX_URLS_PER_ROUND,
    LOCATOR_MAX_CONSULTAS_POR_RONDA,
    LOCATOR_MAX_CONSULTAS_POR_FIESTA,
    PROGRAM_LOCATOR_MAX_TOKENS,
    PROGRAM_LOCATOR_DOWNLOAD_TIMEOUT,
)


def _resumir_candidatas(contexto: str, fiesta: dict) -> list[dict]:
    candidatas = []
    bloques = contexto.split("\n--- [")
    for bloque in bloques:
        if not bloque.strip() or "] |" not in bloque: continue
        url_part, resto = bloque.split("] |", 1)
        url = url_part.strip()
        texto = resto.split("\n", 1)[1] if "\n" in resto else ""
        candidatas.append({
            "url": url,
            "snippet": texto[:PROGRAM_LOCATOR_SNIPPET_CHARS].strip(),
        })
    vistas = set()
    unicas = []
    for c in candidatas:
        if c["url"] not in vistas:
            vistas.add(c["url"])
            unicas.append(c)
    return unicas[:PROGRAM_LOCATOR_MAX_CANDIDATES]

def _prompt_locator(fiesta: dict, localidad: dict, municipio: dict, anno: int, candidatas: list[dict], iteracion: int) -> tuple[str, str]:
    nombre_fiesta = fiesta.get("nombre", "")
    bloque_candidatas = ""
    for idx, c in enumerate(candidatas):
        bloque_candidatas += f"[{idx+1}] URL: {c['url']}\nExtracto:\n{c['snippet']}...\n\n"
        
    system_prompt = f"""Eres un API estricta encargada de LOCALIZAR el programa de fiestas.
CONTEXTO: Municipio {municipio.get('nombre')} ({municipio.get('provincia', 'Espaa')}), Localidad: {localidad.get('nombre')}.

CRITERIOS DE DECISIN:
- Un PROGRAMA tiene actos con horas estructuradas a lo largo de varios das.
- AO {anno}: Es FUNDAMENTAL que la pgina sea del ao {anno}. Rechaza programas de aos anteriores (ej. {anno-1}).
- Prioriza la pgina que nombre la advocacin de ESTA fiesta.
- Un PDF suele ser ms fiable que una pgina HTML genrica, SIEMPRE que sea del ao correcto.
- Puedes elegir VARIAS pginas si varias contienen partes del programa.
- Si NINGUNA candidata contiene el programa pero alguna MENCIONA dnde encontrarlo, indica esas URLs externas en "urls_a_seguir".
- FECHAS REALES: Revisa las fechas del programa en la pgina elegida. Si las fechas reales (ej. del 24 al 26 de julio) son diferentes a las estimadas ({fiesta.get('fecha_inicio', '')} a {fiesta.get('fecha_fin', '')}), indica las fechas correctas en formato YYYY-MM-DD. Si no hay programa, deja las originales.

JSON ESPERADO:
`json
{{
  "paginas_elegidas": ["URL1"],
  "informacion_suficiente": true,
  "fecha_inicio_real": "{fiesta.get('fecha_inicio', '')}",
  "fecha_fin_real": "{fiesta.get('fecha_fin', '')}",
  "urls_a_seguir": [],
  "razon": "Por qu se ha elegido esta pgina"
}}
`

Si NINGUNA candidata sirve y no hay URLs externas:
`json
{{
  "paginas_elegidas": [],
  "informacion_suficiente": true,
  "fecha_inicio_real": "{fiesta.get('fecha_inicio', '')}",
  "fecha_fin_real": "{fiesta.get('fecha_fin', '')}",
  "urls_a_seguir": [],
  "razon": "Ninguna pgina contiene el programa"
}}
`"""

    ronda = f" (RONDA {iteracion})" if iteracion > 1 else ""
    user_prompt = f"FIESTA: {nombre_fiesta}{ronda}\n\nPGINAS CANDIDATAS:\n{bloque_candidatas}\n\nResponde SOLO con JSON:\n`json\n"
    return system_prompt, user_prompt



    return mejor_pagina_con_programa(contexto, fiesta)[1] >= ENRICHMENT_MIN_ACTOS_EN_PAGINA


# ──────────────────────────────────────────────────
# PROGRAM LOCATOR PASS (LLM-guided)
# ──────────────────────────────────────────────────

def _resumir_candidatas(contexto: str, fiesta: dict | None,
                        max_candidatas: int = PROGRAM_LOCATOR_MAX_CANDIDATES,
                        snippet_chars: int = PROGRAM_LOCATOR_SNIPPET_CHARS,
                        ) -> list[dict]:
    """
    Prepara un resumen compacto de cada página del contexto para que el LLM
    decida cuál contiene el programa.

    Para cada página devuelve: url, extracto de N caracteres, nº de actos con
    hora detectados por regex (para que el LLM tenga la misma señal que el
    determinista, pero pueda ignorarla si ve que es un índice).
    """
    candidatas = []
    for url, texto in paginas_del_contexto(contexto):
        if not texto.strip():
            continue
        n_actos = contar_actos_horarios(texto)
        # Extracto: las primeras líneas no vacías, que suelen incluir título y lead
        lineas = [l.strip() for l in texto.split("\n") if l.strip()]
        extracto = "\n".join(lineas)[:snippet_chars]
        candidatas.append({
            "url": url,
            "extracto": extracto,
            "actos_con_hora": n_actos,
        })
    # Ordenar para que el LLM vea primero las que más actos tienen
    candidatas.sort(key=lambda c: -c["actos_con_hora"])
    return candidatas[:max_candidatas]


def _prompt_locator(
    fiesta: dict, localidad: dict, municipio: dict, anno: int,
    candidatas: list[dict], iteracion: int,
) -> tuple[str, str]:
    """Construye system + user prompt para el Program Locator."""
    nombre_fiesta = fiesta.get("nombre", "")
    fecha_ini = fiesta.get("fecha_inicio", "")
    fecha_fin = fiesta.get("fecha_fin", "")

    lista_txt = []
    for i, c in enumerate(candidatas, 1):
        lista_txt.append(
            f"[{i}] URL: {c['url']}\n"
            f"    Horarios detectados por regex: {c['actos_con_hora']}\n"
            f"    Extracto:\n    {c['extracto']}\n"
        )
    bloque_candidatas = "\n".join(lista_txt)

    system_prompt = f"""\
Eres una API que localiza la página o páginas web donde está publicado el
PROGRAMA DE ACTOS de una fiesta local de España.

FIESTA: "{nombre_fiesta}" ({fecha_ini} a {fecha_fin})
LOCALIDAD: {localidad.get('nombre', '')}, municipio de {municipio.get('nombre', '')} ({municipio.get('provincia', 'España')})
AÑO: {anno}

A continuación tienes un resumen de {len(candidatas)} páginas web candidatas.
Cada una muestra su URL, cuántos horarios tipo "HH:MM" contiene (detección
automática, puede incluir falsos positivos), y un extracto de su contenido.

CRITERIOS DE DECISIÓN:
- Un PROGRAMA tiene actos con hora organizados por días. Un ÍNDICE o PORTADA
  tiene eventos dispersos de diferentes fiestas/fechas.
- Prioriza la página que nombre la advocación/nombre de ESTA fiesta y del año {anno}.
- Un PDF suele ser más fiable que una página HTML genérica.
- Un agregador SEO (fiestasdepueblos.net, pueblosdeespana.es, etc.) casi nunca
  tiene el programa real; suelen ser directorios genéricos.
- Puedes elegir VARIAS páginas si varias contienen partes del programa.
- Si NINGUNA candidata contiene el programa pero alguna MENCIONA dónde encontrarlo
  (ej. "consulta el programa en www.X.es", "descarga el cartel en..."), indica
  esas URLs externas en "urls_a_seguir".

CAMPO "informacion_suficiente":
- true: la(s) página(s) elegida(s) contienen el programa completo o toda la
  información disponible. NO hace falta buscar más.
- false: lo que tienes delante no basta. Di POR QUÉ en "razon" y, sobre todo,
  di qué hacer para arreglarlo. Tienes dos herramientas y puedes usar las dos
  a la vez:
    · "urls_a_seguir": direcciones concretas que aparecen en los extractos y
      que hay que descargar.
    · "consultas_sugeridas": búsquedas de internet que redactas tú y que se
      lanzarán tal cual en un buscador.

CÓMO ESCRIBIR "consultas_sugeridas" (máximo {LOCATOR_MAX_CONSULTAS_POR_RONDA}):
- Escribe la consulta como la escribiría una persona, sin operadores raros.
- Incluye SIEMPRE el nombre del pueblo, para no traerte el programa de otro
  pueblo que celebre la misma advocación —los hay a cientos—.
- Lo que suele funcionar: el nombre de la fiesta con el pueblo y el año; el
  pueblo con "programa de actos" y el mes; el nombre del pueblo junto al de la
  emisora, la revista o el periódico comarcal si algún extracto los nombra.
- No sugieras consultas si el problema es que esta fiesta sencillamente no
  tiene programa publicado: devolver la lista vacía es una respuesta correcta.

Responde SOLO con JSON estricto:
{{
  "paginas_elegidas": ["url1", "url2"],
  "informacion_suficiente": true o false,
  "urls_a_seguir": ["url_externa1"],
  "consultas_sugeridas": ["programa fiestas X 2026"],
  "razon": "Breve explicación de por qué has elegido esas páginas"
}}

Si NINGUNA candidata sirve y no hay nada que buscar:
{{
  "paginas_elegidas": [],
  "informacion_suficiente": true,
  "urls_a_seguir": [],
  "consultas_sugeridas": [],
  "razon": "Ninguna página contiene el programa de esta fiesta"
}}"""

    ronda = f" (RONDA {iteracion}: se están revisando las páginas descargadas tras tu indicación anterior)" if iteracion > 1 else ""

    user_prompt = (
        f"FIESTA: {nombre_fiesta}{ronda}\n\n"
        f"PÁGINAS CANDIDATAS:\n{bloque_candidatas}\n\n"
        f"Elige la(s) página(s) que contengan el programa de actos. "
        f"Responde SOLO con JSON:\n```json\n"
    )
    return system_prompt, user_prompt


async def localizar_programa_con_llm(
    contexto: str,
    fiesta: dict,
    localidad: dict,
    municipio: dict,
    anno: int,
    indexed_chunks: list[dict],
    nombres_hermanas: list[str] | None = None,
    provincia: str = "",
    idiomas: list[str] | None = None,
) -> tuple[list[str], list[dict]]:
    """
    Program Locator Pass: el LLM decide qué página(s) contienen el programa.

    Flujo iterativo (máximo PROGRAM_LOCATOR_MAX_ITERATIONS rondas):
      1. Se presentan las páginas candidatas con su snippet y nº de actos.
      2. El LLM elige página(s) y dice si la información es suficiente.
      3. Si no es suficiente y señala urls_a_seguir, se descargan esas URLs,
         se añaden al contexto, y se vuelve a preguntar (ronda 2).
      4. Tras la última ronda o cuando dice suficiente, se devuelven las URLs
         elegidas y los documentos nuevos descargados.

    Devuelve:
        (urls_elegidas, documentos_nuevos)
        - urls_elegidas: lista de URLs que el LLM señala como programa
        - documentos_nuevos: documentos descargados en caliente (pueden ser [])
    """
    nombre_fiesta = fiesta.get("nombre", "")
    documentos_nuevos: list[dict] = []
    urls_elegidas: list[str] = []
    contexto_acumulado = contexto
    consultas_hechas: set[str] = set()
    urls_ya_pedidas: set[str] = set()

    for iteracion in range(1, PROGRAM_LOCATOR_MAX_ITERATIONS + 1):
        candidatas = _resumir_candidatas(contexto_acumulado, fiesta)
        if not candidatas:
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': sin páginas candidatas en "
                f"ronda {iteracion}."
            )
            break

        system_prompt, user_prompt = _prompt_locator(
            fiesta, localidad, municipio, anno, candidatas, iteracion,
        )

        try:
            parsed = await llm_chat_json(
                system_prompt, user_prompt,
                max_tokens=PROGRAM_LOCATOR_MAX_TOKENS,
                etiqueta=f"LOCATOR {iteracion}/{PROGRAM_LOCATOR_MAX_ITERATIONS}",
            )
        except Exception as e:
            logger.warning(
                f"  [LOCATOR] Error en ronda {iteracion} para '{nombre_fiesta}': {e}"
            )
            break

        if not parsed or not isinstance(parsed, dict):
            logger.warning(
                f"  [LOCATOR] '{nombre_fiesta}': respuesta no parseable en "
                f"ronda {iteracion}."
            )
            break

        elegidas = parsed.get("paginas_elegidas") or []
        if isinstance(elegidas, str):
            elegidas = [elegidas]
        suficiente = parsed.get("informacion_suficiente", True)
        
        # Correccion de fechas reales
        f_ini_real = parsed.get("fecha_inicio_real")
        f_fin_real = parsed.get("fecha_fin_real")
        if f_ini_real and f_ini_real != fiesta.get("fecha_inicio"):
            logger.info(f"  [LOCATOR] '{nombre_fiesta}': corrigiendo fecha inicio estimada ({fiesta.get('fecha_inicio')}) a REAL ({f_ini_real})")
            fiesta["fecha_inicio"] = f_ini_real
        if f_fin_real and f_fin_real != fiesta.get("fecha_fin"):
            logger.info(f"  [LOCATOR] '{nombre_fiesta}': corrigiendo fecha fin estimada ({fiesta.get('fecha_fin')}) a REAL ({f_fin_real})")
            fiesta["fecha_fin"] = f_fin_real

        urls_a_seguir = parsed.get("urls_a_seguir") or []
        if isinstance(urls_a_seguir, str):
            urls_a_seguir = [urls_a_seguir]
        consultas = parsed.get("consultas_sugeridas") or []
        if isinstance(consultas, str):
            consultas = [consultas]
        consultas = [c.strip() for c in consultas if isinstance(c, str) and c.strip()]
        razon = parsed.get("razon", "")

        # Registrar las elegidas de esta ronda
        for u in elegidas:
            if u and u not in urls_elegidas:
                urls_elegidas.append(u)

        logger.info(
            f"  [LOCATOR] '{nombre_fiesta}' ronda {iteracion}: "
            f"{len(elegidas)} página(s) elegida(s), "
            f"suficiente={suficiente}, "
            f"{len(urls_a_seguir)} URL(s) a seguir, "
            f"{len(consultas)} consulta(s) sugerida(s). "
            f"Razón: {razon[:120]}"
        )

        # Se para cuando el modelo dice que le basta. Si dice que NO le basta,
        # se sigue mientras tenga algo concreto que pedir: hasta ahora el bucle
        # se rompía también cuando no proponía URLs, que es justo el caso en que
        # más falta hacía salir a buscar.
        if suficiente:
            break
        if not urls_a_seguir and not consultas:
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': dice que no le basta pero no "
                f"propone ni URLs ni consultas. Se sigue con lo que hay."
            )
            break
        if iteracion >= PROGRAM_LOCATOR_MAX_ITERATIONS:
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': máximo de rondas alcanzado "
                f"({PROGRAM_LOCATOR_MAX_ITERATIONS}). Se procede con lo que hay."
            )
            break

        # Se distinguen los dos orígenes a propósito: una URL que el modelo
        # señala DENTRO de un extracto ya vetado es como el enlace que sigue la
        # araña —la noticia del ayuntamiento que remite a la emisora—, y esa
        # página casi nunca repite el nombre del municipio. Una consulta de
        # buscador, en cambio, puede devolver cualquier cosa.
        nuevos_de_url: list[dict] = []
        nuevos_de_busqueda: list[dict] = []

        # 1. Las URLs concretas que el modelo señala en los extractos.
        urls_conocidas = {c["url"] for c in candidatas} | urls_ya_pedidas
        urls_nuevas = [
            u for u in urls_a_seguir[:PROGRAM_LOCATOR_MAX_URLS_PER_ROUND]
            if u and u.startswith("http") and u not in urls_conocidas
        ]
        if urls_nuevas:
            urls_ya_pedidas.update(urls_nuevas)
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': descargando {len(urls_nuevas)} "
                f"URL(s): {[u[:70] for u in urls_nuevas]}"
            )
            try:
                from scraper.google_search import descargar_urls_bajo_demanda
                nuevos_de_url += await descargar_urls_bajo_demanda(
                    urls_nuevas, fuente=FUENTE_BUSQUEDA,
                    timeout=PROGRAM_LOCATOR_DOWNLOAD_TIMEOUT,
                ) or []
            except Exception as e:
                logger.warning(f"  [LOCATOR] Error descargando URLs: {e}")

        # 2. Las consultas que redacta el propio modelo. Es la novedad: hasta
        #    ahora solo se podía seguir un enlace que ya estuviera en el texto,
        #    y en 2 de las 4 rondas con suficiente=False no había ninguno.
        pendientes = [
            c for c in consultas[:LOCATOR_MAX_CONSULTAS_POR_RONDA]
            if " ".join(c.lower().split()) not in consultas_hechas
        ][: max(0, LOCATOR_MAX_CONSULTAS_POR_FIESTA - len(consultas_hechas))]
        if pendientes:
            consultas_hechas.update(" ".join(c.lower().split()) for c in pendientes)
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': buscando lo que pide el modelo: {pendientes}"
            )
            try:
                from scraper.google_search import _buscar_y_descargar
                nuevos_de_busqueda += await _buscar_y_descargar(
                    pendientes, localidad, municipio, set(urls_conocidas),
                ) or []
            except Exception as e:
                logger.warning(f"  [LOCATOR] Error buscando: {e}")

        # Lo que llega por BÚSQUEDA pasa por los mismos filtros que cualquier
        # otro resultado de buscador. Una consulta escrita por el modelo con el
        # nombre de una advocación atrae con fuerza el programa del pueblo
        # homónimo que celebra esa misma fiesta, y los hay a cientos.
        if nuevos_de_busqueda:
            antes = len(nuevos_de_busqueda)
            nuevos_de_busqueda = [
                d for d in nuevos_de_busqueda
                if not documento_es_ajeno_al_municipio(
                    d.get("texto") or "", d.get("url", ""),
                    localidad.get("nombre", ""), municipio.get("nombre", ""),
                    nombres_hermanas,
                )
            ]
            nuevos_de_busqueda = await descartar_homonimos(
                nuevos_de_busqueda, localidad.get("nombre", ""),
                municipio.get("nombre", ""), provincia, nombres_hermanas,
                idiomas or ["es"],
            )
            if len(nuevos_de_busqueda) != antes:
                logger.info(
                    f"  [LOCATOR] '{nombre_fiesta}': {antes - len(nuevos_de_busqueda)} de "
                    f"{antes} resultados de búsqueda descartados por no ser de "
                    f"{localidad.get('nombre', '')}."
                )

        nuevos = [d for d in (nuevos_de_url + nuevos_de_busqueda)
                  if (d.get("texto") or "").strip()]
        if not nuevos:
            logger.info(
                f"  [LOCATOR] '{nombre_fiesta}': la ronda {iteracion} no ha traído "
                f"ningún documento nuevo. Se para."
            )
            break

        documentos_nuevos.extend(nuevos)
        logger.info(
            f"  [LOCATOR] '{nombre_fiesta}': {len(nuevos)} documento(s) nuevo(s)."
        )

        # Al índice, para que el enrichment pueda leerlos enteros después.
        partes_nuevas = []
        for doc in nuevos:
            texto_doc, url_doc = doc.get("texto", ""), doc.get("url", "")
            for idx, chunk_text in enumerate(chunk_documento(texto_doc)):
                indexed_chunks.append({
                    "fuente": doc.get("fuente", FUENTE_BUSQUEDA),
                    "url": url_doc, "chunk": chunk_text, "indice_chunk": idx,
                    "es_calendario": doc.get("es_calendario", False),
                    "relevancia_geo": "DIRECTA", "score": 0.5, "prioridad": 6,
                })
            partes_nuevas.append(
                f"\n--- [{url_doc}] | Relevancia: DIRECTA ---\n"
                f"{texto_doc[:PROGRAM_LOCATOR_SNIPPET_CHARS * 3]}"
            )
        contexto_acumulado = contexto_acumulado + "\n".join(partes_nuevas)

    return urls_elegidas, documentos_nuevos




def ensamblar_contexto(seleccion: list[dict]) -> str:
    """
    Monta el contexto agrupando por fuente y, dentro de cada fuente, por PÁGINA.

    Los chunks de una misma página van juntos y en su orden de lectura, no
    barajados por puntuación. El programa de una fiesta está en una página y
    seguido —medido el 2026-08-25: de los 16 actos de Cordovilla, 15 salían de un
    único documento, y era la ficha de más calidad de toda la ejecución—, pero
    llegaba al modelo despedazado: 22 chunks de San Roque de 8 páginas distintas
    con 16 saltos entre ellas, y hasta los 4 chunks buenos de Cordovilla partidos
    en tres grupos separados por otras webs.

    Esa mezcla tiene consecuencias visibles: la ficha de San Antón, de enero,
    llevaba «Concierto en Plaza de España. Orquesta Señor Aliaga», que está en el
    programa del Cristo de la Antigua, de mayo. Acto real, fiesta equivocada.

    Cuando entre dos chunks de la misma página falta alguno, se marca con […]:
    pegarlos sin más insinuaría una continuidad que no existe.
    """
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

        # Dentro de la fuente, una página por bloque. Las páginas se ordenan por
        # su mejor chunk: la selección ya se hizo por puntuación y no se toca,
        # solo cambia cómo se presenta.
        paginas: dict[str, list[dict]] = {}
        for i in grupos[clave]:
            paginas.setdefault(i.get("url") or "sin url", []).append(i)

        for url in sorted(paginas, key=lambda u: -max(x.get("score", 0.0) for x in paginas[u])):
            chunks = sorted(paginas[url], key=lambda x: x.get("indice_chunk", 0))
            if url != "buscadores:snippets":
                rel = chunks[0].get("relevancia_geo", "DIRECTA")
                partes.append(f"\n--- [{url}] | Relevancia: {rel} ---")
            anterior = None
            for i in chunks:
                actual = i.get("indice_chunk")
                if anterior is not None and actual is not None and actual > anterior + 1:
                    partes.append("[…]")
                partes.append(_sin_marcador_de_origen(i["chunk"]))
                anterior = actual
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

    async def saturate_context_docs(
        self,
        documentos: list[dict],
        query: str,
        localidad_nombre: str = "",
        nombres_hermanas: list[str] | None = None,
        anno: int | None = None,
    ) -> tuple[str, set]:
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
                    "score_spider": doc.get("score_spider", 0),
                    "embedding": None,
                    "score": 0.0,
                })

        if not items:
            return "", set()

        logger.info(
            f"  RAG: {len(items)} chunks de {len(documentos)} documentos. "
            f"Vectorizando en batches de {self.batch_size}..."
        )

        anno = anno or datetime.now().year
        async with aiohttp.ClientSession() as session:
            query_embeddings = await self.get_embeddings_batch(session, [query])
            query_emb = query_embeddings[0] if query_embeddings else None

            if not query_emb:
                # Sin embeddings: seleccionar solo por prioridad de fuente
                logger.warning("  RAG: sin embedding de la query; selección solo por prioridad de fuente.")
            else:
                chunks = [i["chunk"] for i in items]
                all_embeddings = []
                for b in range(0, len(chunks), self.batch_size):
                    batch_embs = await self.get_embeddings_batch(session, chunks[b : b + self.batch_size])
                    all_embeddings.extend(batch_embs)
                for item, emb in zip(items, all_embeddings):
                    item["embedding"] = emb

        # Misma fusión de señales que el resto del pipeline: un solo criterio de
        # ranking en todo el módulo.
        puntuar_chunks(items, query_emb=query_emb, anno=anno,
                       coseno=self.cosine_similarity)
        items = filtrar_chunks_por_localidad(items, localidad_nombre, nombres_hermanas or [])
        umbral = umbral_adaptativo(items) if query_emb else -1.0
        seleccion = seleccionar_chunks(items, self.context_limit_chars, umbral,
                                       garantizados=chunks_garantizados(items, anno=anno))
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

    # 10.5. Validar fechas móviles (Carnaval, etc.)
    fiestas_validas = validar_fechas_moviles(fiestas_validas, anno)

    # 11. Fusionar fiestas próximas (Problema 1)
    fiestas_validas = fusionar_fiestas_proximas(fiestas_validas)

    # 12. Deduplicar
    fiestas_validas = _deduplicar_fiestas(fiestas_validas)

    return fiestas_validas


# ──────────────────────────────────────────────────
# INFERENCIA LLM
# ──────────────────────────────────────────────────

class ContextOverflowError(Exception):
    """El prompt supera el n_ctx con que está cargado el modelo en LM Studio."""


def _cerrar_json_truncado(fragmento: str) -> str | None:
    """
    Cierra las llaves y corchetes que quedan abiertos en un JSON cortado.

    Recorta primero hasta el último elemento completo —el último `}` o `]` que
    no esté dentro de una cadena— y añade los cierres que falten en orden
    inverso. Devuelve None si no hay ni un elemento completo que salvar.
    """
    pila, en_cadena, escapado, ultimo_cierre = [], False, False, -1
    for i, c in enumerate(fragmento):
        if escapado:
            escapado = False
            continue
        if c == "\\":
            escapado = True
        elif c == '"':
            en_cadena = not en_cadena
        elif en_cadena:
            continue
        elif c in "{[":
            pila.append(c)
        elif c in "}]":
            if pila and pila[-1] == ("{" if c == "}" else "["):
                pila.pop()
                if pila:  # un cierre de nivel superior no deja nada dentro
                    ultimo_cierre = i
    if ultimo_cierre < 0:
        return None

    recorte = fragmento[: ultimo_cierre + 1]
    pila, en_cadena, escapado = [], False, False
    for c in recorte:
        if escapado:
            escapado = False
        elif c == "\\":
            escapado = True
        elif c == '"':
            en_cadena = not en_cadena
        elif not en_cadena and c in "{[":
            pila.append(c)
        elif not en_cadena and c in "}]" and pila:
            pila.pop()
    return recorte + "".join("}" if c == "{" else "]" for c in reversed(pila))


def _parse_json_llm(content: str) -> dict | None:
    """
    Limpia y parsea la respuesta JSON del LLM (tolerante a basura típica y tags
    de razonamiento).

    Cuando el JSON viene roto se intenta salvar lo que haya hasta el punto del
    error, porque lo que se pierde no es una respuesta sino un tercio del
    programa: el 2026-08-26, en la tercera de las tres llamadas del programa de
    Tobarra, un fallo en la línea 20 tiró los 663 tokens enteros y la ficha se
    quedó con 4 actos de los 22 que traía su página. El "recuperar JSON parcial"
    que había reintentaba `\\{.*\\}` sobre el MISMO texto roto, así que nunca
    recuperó nada.
    """
    # Eliminar bloques de razonamiento si el modelo (ej. prism-ml/bonsai-27b) los genera
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = content.replace("```json", "").replace("```", "").strip()
    # Limpiar comas sueltas típicas de modelos pequeños antes de un ] o }
    content = re.sub(r",\s*([\]}])", r"\1", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"  JSON malformado del LLM: {e}")
        pos_error = e.pos

    inicio = content.find("{")
    if inicio < 0:
        return None
    cuerpo = content[inicio:]

    # Cortar por donde falló y cerrar lo que quede abierto. Se prueba también
    # desde el principio, por si el error estaba en la cabecera y no en la cola.
    for corte in (max(0, pos_error - inicio), len(cuerpo)):
        reparado = _cerrar_json_truncado(cuerpo[:corte])
        if not reparado:
            continue
        try:
            datos = json.loads(re.sub(r",\s*([\]}])", r"\1", reparado))
        except json.JSONDecodeError:
            continue
        if isinstance(datos, dict):
            logger.warning(
                f"  JSON parcial recuperado: {len(reparado)} de {len(cuerpo)} caracteres "
                f"({100 * len(reparado) // max(1, len(cuerpo))}%). Lo posterior al error se pierde."
            )
            return datos

    logger.error("  No se pudo recuperar JSON parcial.")
    return None


_SYS_PROCEDENCIA = """Lees un fragmento de una web sobre fiestas de pueblo. El fragmento habla de un
pueblo. Extraes DE QUÉ SITIO MAYOR depende ese pueblo, según lo que el texto dice.

- "municipio": el ayuntamiento, concejo, cendea, comarca o ciudad de la que el texto
  dice que el pueblo forma parte. Es SIEMPRE un sitio DISTINTO del pueblo: si lo único
  que encuentras es el nombre del propio pueblo, pon null.
- "provincia": la provincia o comunidad donde el texto lo sitúa. Vale una pista
  inequívoca: una capital de provincia cercana que el texto nombre, o un gentilicio.
- Si el texto NO lo dice, pon null. NO adivines por lo que sepas de fuera del texto.

Ejemplo: "Cordovilla, concejo de la Cendea de Galar a las puertas de Pamplona"
-> {"municipio": "Cendea de Galar", "provincia": "Navarra"}

Responde solo JSON: {"municipio": ..., "provincia": ...}

(La lengua del documento NO se pregunta: la reconoce el código, que para eso no falla.)"""


_SYS_PERTENENCIA = """Filtras fichas de fiestas populares españolas antes de guardarlas. Respondes DOS
preguntas independientes sobre la ficha que se te da.

Te dan la identidad de la localidad que buscamos, la ficha, y el texto de las
fuentes de donde salió.

PREGUNTA 1 — ¿Es la fiesta PROPIA de nuestra localidad?

No preguntamos dónde se celebra, sino DE QUIÉN es. Son cosas distintas y la
diferencia decide la respuesta.

1. Manda lo que dice el TEXTO DE LAS FUENTES, no el nombre de la fiesta. Una
   fiesta puede llamarse igual que nuestra localidad y ser de otra provincia.
2. Que el texto la sitúe en el MUNICIPIO al que pertenece nuestra localidad es
   señal BUENA, no mala. Las pedanías se escriben así de continuo: "fiestas de X
   en Y", donde Y es el municipio o la comarca. Eso es NUESTRO. También lo es que
   se nombre la provincia o la comunidad correctas.
3. Si arriba se te da un segundo nombre para nuestra localidad, los dos nombres
   son EL MISMO SITIO. Un texto que use el nombre largo habla de NOSOTROS, y la
   respuesta es "si". No lo trates como un pueblo distinto por llamarse de otra
   manera: es la misma localidad escrita entera.
4. Es de OTRO SITIO cuando el texto la sitúa en una provincia o comunidad
   distintas, o en un municipio que no es el nuestro. Cuidado con los nombres que
   empiezan igual y siguen distinto —"X de la Vera", "X de Tormes", "X de León"
   son pueblos DIFERENTES de "X"—, y con las direcciones y códigos postales, que
   delatan la provincia aunque el texto no la nombre. Pero mira SIEMPRE la
   provincia antes de decidirlo: si la provincia es la nuestra, el nombre largo
   casi seguro es el nuestro escrito entero, no otro pueblo.
5. NO ES NUESTRA, aunque se celebre físicamente aquí, la fiesta que pertenece a
   OTRO: la del municipio entero, la de la comarca, o la que cada año cambia de
   sede entre los pueblos. Si el texto dice que el municipio organiza un día o
   una jornada y que este año toca en nuestro pueblo, la fiesta es del municipio
   y la respuesta es "no". Esta regla pesa MÁS que la 2: que se nombre a nuestro
   municipio ayuda a situarla, pero si el dueño de la fiesta ES el municipio, no
   es la fiesta de nuestra localidad.
   EXCEPCIÓN, y solo esta: si arriba pone que nuestra localidad ES LA CAPITAL,
   sus fiestas patronales y su fiesta mayor son también las del municipio, así
   que un texto que las llame "fiestas de <municipio>" habla de las NUESTRAS.
   La excepción NO alcanza a los otros casos: una jornada que rota de sede sigue
   siendo del municipio aunque toque en la capital, y NADA de esto vale si la
   regla 3 ya dijo que el texto sitúa la fiesta en otra provincia. La geografía
   manda siempre sobre esta excepción.
6. Si no puedes decidir con el texto, responde "no_se". No adivines por lo que
   sepas de fuera del texto ni supongas que es nuestra por descarte.

PREGUNTA 2 — ¿Es una fiesta popular?

SÍ lo son: las fiestas patronales, la fiesta mayor, las ferias locales con
programación festiva, las tradicionales (carnaval, San Juan, moros y cristianos,
romerías, hogueras), las fiestas de barrio o de pedanía, y las verbenas y fiestas
populares de verano.

NO lo son cuando aparecen SUELTOS, sin ser parte del programa de una fiesta:
- Un acto institucional, un pleno, un día autonómico o una jornada oficial.
- Un concurso, un certamen, una exposición, una conferencia o un ciclo de charlas.
- Una feria comercial o un mercado sin programación festiva.
- Una jornada gastronómica puntual.
- Una competición deportiva suelta, una procesión suelta o una misa extraordinaria.
- Un plazo administrativo, una convocatoria o el menú de navegación de una web.

La pregunta correcta no es qué tipo de acto es, sino si es una celebración
popular por sí misma o parte del programa de una. Una procesión dentro de las
fiestas patronales SÍ cuenta; esa misma procesión suelta en marzo, no.

REGLA DE ACEPTACIÓN OBLIGATORIA: si el programa incluye orquesta, verbena, DJ,
discomóvil, charanga o música en directo por la noche, es una fiesta. Responde
"si" a la pregunta 2 aunque el nombre te parezca raro.

Responde solo JSON:
{"es_de_la_localidad": "si" | "no" | "no_se",
 "lugar_real": "dónde la sitúa el texto, o null si no lo dice",
 "es_una_fiesta": "si" | "no" | "no_se",
 "que_es": "si no es una fiesta, qué es; si lo es, null",
 "razon": "una frase, citando lo que te ha hecho decidir"}"""


def _bloque_identidad(localidad: dict, municipio: dict, nombres_hermanas: list[str] | None) -> str:
    """
    Quiénes somos, en el formato que lee el juez de pertenencia.

    Se le da todo lo que el dataset de Fase 1 trae con cobertura completa
    —provincia, comunidad, población y descripción están en las 8.199 localidades
    del fichero—, porque sin saber qué buscamos el modelo solo puede extraer de
    dónde es el documento y dejar que lo compare el código, que es justo lo que
    no distingue "Santa Marta de Astorga" de "Santa Marta de La Roda".
    """
    # La capital no se reconoce solo por el id: en el dataset la cabecera del
    # municipio es una localidad aparte, con su propio id y `es_capital`. Son
    # 1.548 de las 8.199 localidades, casi una de cada cinco, y decirlo importa:
    # sin esto el juez rechazó las fiestas de la Virgen del Rosario de
    # Quintanadueñas «porque el texto las sitúa en el municipio de Alfoz de
    # Quintanadueñas, no en la localidad» —siendo Quintanadueñas su capital, y
    # llamándose el municipio así por ella—.
    es_capital = (localidad.get("id") == municipio.get("id")) or bool(localidad.get("es_capital"))
    # El nombre corto y el oficial van en LA MISMA LÍNEA y diciendo expresamente
    # que son el mismo sitio. Ponerlos en dos campos separados —"Localidad: Santa
    # Marta" y "Nombre oficial: Santa Marta de los Barros"— hizo que el modelo los
    # leyera como dos pueblos distintos: descartó la Semana Santa de Santa Marta
    # razonando «el texto la sitúa en Santa Marta de los Barros, pero el nombre
    # oficial del municipio es Santa Marta de los Barros, no Santa Marta».
    # Medido el 2026-09-04: cambiar el veto del código por el mismo error dentro
    # del modelo no es progreso.
    nombre_loc = localidad.get("nombre", "")
    oficial = (municipio.get("nombre_oficial") or "").strip()
    if oficial and _normalizar_nombre(oficial) != _normalizar_nombre(nombre_loc):
        lineas = [
            f"  Localidad: {nombre_loc}, que TAMBIÉN se escribe «{oficial}» "
            f"—es el mismo sitio, dos formas de nombrarlo—"
        ]
    else:
        lineas = [f"  Localidad: {nombre_loc}"]
    if (municipio.get("sitio_web") or "").strip():
        lineas.append(f"  Web oficial del ayuntamiento: {municipio['sitio_web']}")
    if es_capital:
        lineas.append(
            f"  ES LA CAPITAL del municipio de {municipio.get('nombre', '')}: "
            f"las fiestas del municipio son las suyas."
        )
    else:
        lineas.append(f"  Es una localidad del municipio de: {municipio.get('nombre', '')}")
    for etiqueta, clave, fuente in (
        ("Provincia", "provincia", municipio), ("Comunidad", "comunidad", municipio),
    ):
        valor = (localidad.get(clave) or fuente.get(clave) or "").strip()
        if valor:
            lineas.append(f"  {etiqueta}: {valor}")
    if localidad.get("poblacion"):
        lineas.append(f"  Población: {localidad['poblacion']} habitantes")
    hermanas = [h for h in (nombres_hermanas or []) if h and h != localidad.get("nombre")]
    if hermanas:
        lineas.append(f"  Otras localidades del mismo municipio: {', '.join(hermanas[:12])}")
    # La `descripcion_corta` del dataset NO entra, aunque esté en las 8.199
    # localidades. Está generada a partir del NOMBRE del pueblo, que es
    # exactamente el error que este juez existe para corregir: Santa Marta (La
    # Roda, Albacete) viene descrita como «pueblo encantador con vistas al mar y
    # ruinas romanas», y Las Arenas y Santa Marina (Burgos) con «playas de arena
    # dorada». Comprobado el 2026-09-04: siete localidades de provincias sin
    # costa traen playas o acantilados en su descripción. Darle eso al modelo
    # junto a la provincia correcta es ponerle una contradicción delante.
    # La ficha del pueblo va DENTRO del bloque de identidad, no como seccion
    # aparte, porque forma parte de quienes somos: sin ella el juez decide si
    # una fiesta es de este pueblo sabiendo solo su nombre y su provincia. La
    # pone `main` sobre la localidad, igual que `nombre_oficial` viaja en el
    # municipio. Si no hay patron resuelto, `ficha_del_pueblo` devuelve '' y
    # aqui no se anade nada.
    ficha = (localidad.get("ficha_pueblo") or "").strip()
    if ficha:
        lineas.append("")
        lineas.append(ficha)
    return "\n".join(lineas)


def _bloque_ficha(fiesta: dict) -> str:
    """La ficha tal como se guardaría, para que el juez vea lo que se va a aceptar."""
    lineas = [
        f"  Nombre: {fiesta.get('nombre', '')}",
        f"  Fechas: {fiesta.get('fecha_inicio', '')} a {fiesta.get('fecha_fin', '')}",
    ]
    for etiqueta, clave in (("Descripción", "descripcion"), ("Sede según el texto", "sede_segun_el_texto")):
        if (fiesta.get(clave) or "").strip():
            lineas.append(f"  {etiqueta}: {str(fiesta[clave])[:400]}")
    if (fiesta.get("evidencia") or "").strip():
        lineas.append(f"  Frase de la que salieron sus fechas: «{fiesta['evidencia'][:300]}»")
    if fiesta.get("url_programa"):
        lineas.append(f"  Página de la que se copió el programa: {fiesta['url_programa']}")
    prog = fiesta.get("programa") or []
    actos = [e.get("descripcion", "") for d in prog for e in (d.get("eventos") or [])]
    if actos:
        lineas.append(f"  Programa: {len(prog)} días, {len(actos)} actos. Primeros:")
        lineas += [f"    - {a[:150]}" for a in actos[:6]]
    else:
        lineas.append("  Programa: no se encontró ninguno (la ficha es solo nombre y fechas).")
    return "\n".join(lineas)


async def veredicto_de_pertenencia(
    fiesta: dict,
    localidad: dict,
    municipio: dict,
    nombres_hermanas: list[str] | None,
    contexto_alrededor: str,
) -> dict:
    """
    ¿Esta fiesta es de esta localidad? Lo dice el modelo, con los papeles delante.

    Nace del peor registro de la ejecución del 2026-09-04: a Santa Marta —pedanía
    de La Roda, Albacete— se le colgaron los 64 actos de las fiestas de Astorga
    (León). Y no por falta de guardas: el juez de homónimos había descartado
    correctamente catorce documentos, la web del ayuntamiento de Astorga entre
    ellos. Lo que falló es que ese juez opina sobre DOCUMENTOS, uno a uno y sin
    saber a quién buscamos, y la ficha se rehízo después desde un fragmento
    suelto. Aquí se pregunta por la FICHA ya montada, que es lo que se guarda, y
    diciéndole al modelo quiénes somos.
    """
    datos = await llm_chat_json(
        _SYS_PERTENENCIA,
        "LOCALIDAD QUE BUSCAMOS\n"
        + _bloque_identidad(localidad, municipio, nombres_hermanas)
        + "\n\nFICHA A JUZGAR\n"
        + _bloque_ficha(fiesta)
        + "\n\nTEXTO DE LAS FUENTES DE LAS QUE SALIÓ\n"
        + (contexto_alrededor or "(no hay texto disponible)"),
        max_tokens=PERTENENCIA_MAX_TOKENS,
        etiqueta="PERTENENCIA",
    )
    return datos if isinstance(datos, dict) else {}


async def procedencia_declarada(texto: str) -> dict:
    """
    Qué dice el documento sobre sí mismo: dónde se sitúa y en qué lengua está.

    Solo EXTRAE; quien decide es `procedencia_contradice_al_lugar`, en código.
    El reparto está medido: a un 7B no se le puede pedir el veredicto (ver la
    nota en esa función), pero extraer un dato se le da bien.
    """
    if not (texto or "").strip():
        return {}
    datos = await llm_chat_json(
        _SYS_PROCEDENCIA,
        "FRAGMENTO:\n" + texto[:PROCEDENCIA_CHARS],
        max_tokens=PROCEDENCIA_MAX_TOKENS,
        etiqueta="PROCEDENCIA",
    )
    return datos if isinstance(datos, dict) else {}


async def descartar_homonimos(
    documentos: list[dict],
    localidad_nombre: str,
    municipio_nombre: str,
    provincia: str,
    nombres_hermanas: list[str] | None = None,
    idiomas_de_la_provincia: list[str] | None = None,
) -> list[dict]:
    """
    Quita los documentos que hablan de otro pueblo que se llama igual.

    El filtro por nombre no puede distinguirlos: el programa de Cordovilla Bajo
    (Cendea de Galar, Navarra) dice «Cordovilla» y por eso entra como si fuera de
    Cordovilla de Tobarra (Albacete), a 600 km. El 2026-08-24 eso produjo DOS
    fichas falsas para esa pedanía, una de ellas con 25 actos y confianza alta.

    Solo se examinan los documentos que entran avalados ÚNICAMENTE por el nombre
    del pueblo, que son el 5% del total y donde está todo el riesgo. Preguntar
    por los otros sería pagar una llamada al modelo por nada.
    """
    if not documentos or not localidad_nombre:
        return documentos

    sospechosos = [
        d for d in documentos
        if fuente_base(d.get("fuente", "")) in (FUENTE_BUSQUEDA, FUENTE_HISTORICO, FUENTE_PRENSA_REGIONAL)
        # El bloque de snippets no se examina: no habla de un sitio, sino de los
        # veinte que ha devuelto el buscador, y preguntarle al modelo dónde se
        # sitúa daría una respuesta sin sentido con la que se borraría entero.
        # Se limpia línea a línea al final, con las URLs ya decididas.
        and d.get("tipo") != "snippets"
        and documento_avalado_solo_por_la_localidad(
            d.get("texto") or "", d.get("url", ""),
            localidad_nombre, municipio_nombre, nombres_hermanas,
        )
    ]
    if not sospechosos:
        return documentos

    logger.info(
        f"    [HOMONIMO] {len(sospechosos)} de {len(documentos)} documentos entran solo "
        f"por el nombre de {localidad_nombre}; se comprueba su procedencia."
    )
    procedencias = await asyncio.gather(
        *[procedencia_declarada(d.get("texto") or "") for d in sospechosos],
        return_exceptions=True,
    )

    descartadas = set()
    urls_fuera: set[str] = set()
    for doc, proc in zip(sospechosos, procedencias):
        if isinstance(proc, BaseException) or not isinstance(proc, dict):
            continue  # si la comprobación falla, el documento se queda: el sesgo es conservar
        # La lengua no se la preguntamos al modelo: la detecta el código. Medido
        # el 2026-08-24 sobre el PDF de Cordovilla Bajo, cuya primera línea es
        # «ANTOLATZAILEA: CORDOBILLAKO KONTZEJUA», qwen2.5-7b devolvía null.
        proc = dict(proc, lengua_iso=lengua_cooficial_detectada(doc.get("texto") or ""))
        motivo = procedencia_contradice_al_lugar(
            proc, localidad_nombre, municipio_nombre, provincia,
            nombres_hermanas, idiomas_de_la_provincia,
        )
        if motivo:
            descartadas.add(id(doc))
            if doc.get("url"):
                urls_fuera.add(doc["url"])
            logger.info(f"    [HOMONIMO] Descartado '{doc.get('url', '')[:74]}': {motivo}.")

    if not descartadas:
        return documentos

    # Un sitio web entero es de un sitio geográfico, aunque sus páginas no lo
    # repitan todas. Lo que se acaba de descartar dice de quién es el dominio.
    descartadas, urls_fuera = _extender_descarte_al_dominio(
        documentos, descartadas, urls_fuera, municipio_nombre, provincia,
    )

    logger.info(f"    [HOMONIMO] {len(descartadas)} documentos de un pueblo homónimo descartados.")
    quedan = [d for d in documentos if id(d) not in descartadas]
    return _purgar_snippets(quedan, urls_fuera)


def _extender_descarte_al_dominio(
    documentos: list[dict],
    descartadas: set,
    urls_fuera: set[str],
    municipio_nombre: str,
    provincia: str,
) -> tuple[set, set[str]]:
    """
    Si un dominio ya tiene una página descartada y NINGUNA de las suyas nombra a
    nuestro municipio o provincia, cae entero.

    La comprobación de procedencia decide página por página, y una página que no
    dice dónde está se acepta —la ausencia nunca descarta, para no cerrar las
    webs de pueblo pequeño—. El problema es que basta con que la callada sea la
    que lleva el programa. Medido el 2026-08-26 en Sierra: de
    `festisierra.com` se descartó la revista, que dice «Fregenal de la Sierra»,
    y se aceptó `/programacion/`, que no dice de dónde es. De esa segunda
    salieron los 12 actos del Festival Internacional de la Sierra, en Badajoz,
    colocados como fiestas de una pedanía de Albacete.

    Lo que NO se hace es tirar el dominio entero sin más, que fue el primer
    impulso. De los 14 dominios con descartes, cuatro son agregadores que cubren
    muchos pueblos y también el nuestro: `enaranda.es` tiene 12 páginas de Aranda
    de 14, y es de donde salen los programas de La Aguilera, Sinovas y La
    Calabaza. Tirarlo habría costado tres programas buenos por arreglar uno malo.

    La diferencia entre «un sitio que va de otro pueblo» y «un sitio que cubre
    muchos, el nuestro entre ellos» es exactamente si alguna vez habla de
    nosotros. Se ancla al MUNICIPIO y no a la localidad: el mismo portal comarcal
    vale para todas las pedanías a la vez.
    """
    from urllib.parse import urlparse

    def dominio(url: str) -> str:
        return urlparse(url or "").netloc.replace("www.", "").lower()

    dominios_tocados = {dominio(u) for u in urls_fuera}
    dominios_tocados.discard("")
    if not dominios_tocados:
        return descartadas, urls_fuera

    anclas = [normalize_text(x).strip() for x in (municipio_nombre, provincia) if x]
    anclas = [a for a in anclas if a]

    por_dominio: dict[str, list[dict]] = {}
    for doc in documentos:
        d = dominio(doc.get("url", ""))
        if d in dominios_tocados:
            por_dominio.setdefault(d, []).append(doc)

    for d, docs in por_dominio.items():
        alguna_nuestra = any(
            any(a in normalize_text(f"{doc.get('texto') or ''} {doc.get('url', '')}") for a in anclas)
            for doc in docs
        )
        if alguna_nuestra:
            continue  # agregador: la decisión se queda como estaba, página a página
        nuevas = [doc for doc in docs if id(doc) not in descartadas]
        if not nuevas:
            continue
        logger.info(
            f"    [HOMONIMO] El dominio '{d}' es de otro sitio —ninguna de sus "
            f"{len(docs)} páginas nombra a {municipio_nombre} ni a {provincia}—; "
            f"caen sus otras {len(nuevas)}."
        )
        for doc in nuevas:
            descartadas.add(id(doc))
            if doc.get("url"):
                urls_fuera.add(doc["url"])

    return descartadas, urls_fuera


def _purgar_snippets(documentos: list[dict], urls_fuera: set[str]) -> list[dict]:
    """
    Quita del bloque de snippets las líneas de las URLs que se han descartado.

    Hace falta porque el bloque de snippets es UN documento que acumula el
    título y el resumen de todos los resultados de todas las consultas, de
    sitios distintos, bajo la url ficticia 'buscadores:snippets'. Ningún filtro
    por procedencia puede con él: no habla de un sitio, habla de veinte.

    Medido el 2026-08-25 en Cordovilla. Las dos páginas de la Cendea de Galar
    salían descartadas en el log y sus actos —«Escuela Belén Hervás», «grupo Son
    de Ases»— seguían llegando al modelo, porque el snippet de esas mismas URLs
    viajaba dentro de este bloque. Descartar la página y dejar su resumen es no
    descartar nada.
    """
    if not urls_fuera:
        return documentos

    salida = []
    for doc in documentos:
        if doc.get("tipo") != "snippets":
            salida.append(doc)
            continue
        lineas = (doc.get("texto") or "").splitlines()
        limpias = [ln for ln in lineas if not any(u and u in ln for u in urls_fuera)]
        quitadas = len(lineas) - len(limpias)
        if quitadas:
            logger.info(f"    [HOMONIMO] {quitadas} snippets de esas URLs quitados del bloque de resultados.")
            doc = dict(doc, texto="\n".join(limpias))
        if (doc.get("texto") or "").strip():
            salida.append(doc)
    return salida


# Modelo remoto que respondió la última vez. Con ocho modelos en cascada y varios
# cientos de llamadas por ejecución, arrancar siempre por el primero significa
# pagar el 429 del modelo saturado una y otra vez; recordar cuál funciona ahorra
# esa ida y vuelta en todas las llamadas siguientes.
_MODELO_REMOTO_PREFERIDO: str | None = None


# Ventanas de contexto REALES aprendidas de los errores del propio motor, que no
# siempre coinciden con las que declara al cargarse. Ver el bloque que lo anota
# en `_pedir_a_proveedor`. Vive en memoria: se reaprende en cada ejecución.
_VENTANA_REAL: dict[str, int] = {}


def _cadena_proveedores() -> list[dict]:
    """
    Proveedores de chat a probar, en orden: primero la cascada de OpenRouter
    —ordenada por parecido con el 27B, con el último que funcionó al frente— y
    LM Studio al final como red de seguridad.

    Los embeddings y el VLM de visión NO pasan por aquí: siguen en LM Studio.
    """
    cadena: list[dict] = []

    if OPENROUTER_ENABLED and OPENROUTER_API_KEY:
        modelos = list(OPENROUTER_MODELS)
        if _MODELO_REMOTO_PREFERIDO in modelos:
            modelos.remove(_MODELO_REMOTO_PREFERIDO)
            modelos.insert(0, _MODELO_REMOTO_PREFERIDO)
        for model_id in modelos:
            cadena.append({
                "nombre": model_id,
                "remoto": True,
                "url": OPENROUTER_CHAT_URL,
                "modelo": model_id,
                "n_ctx": OPENROUTER_N_CTX,
                "timeout": OPENROUTER_CHAT_TIMEOUT,
                "headers": {
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": OPENROUTER_REFERER,
                    "X-Title": OPENROUTER_TITLE,
                },
            })

    # La ventana del local se consulta a LM Studio: es la red de seguridad de la
    # cadena y su n_ctx suele ser mucho menor que el del remoto, así que hay que
    # saberlo ANTES de ofrecerle un prompt que no le va a caber.
    try:
        n_ctx_local = get_model_info()["n_ctx"]
    except Exception:
        n_ctx_local = 8192
    nombre_local = f"LM Studio/{LMSTUDIO_CHAT_MODEL}"
    # Si en esta ejecución ya nos ha dicho su ventana real —rechazando un prompt
    # que según lo declarado le cabía—, esa manda sobre lo que anuncia.
    n_ctx_local = min(n_ctx_local, _VENTANA_REAL.get(nombre_local, n_ctx_local))
    cadena.append({
        "nombre": nombre_local,
        "remoto": False,
        "url": LMSTUDIO_CHAT_URL,
        "modelo": LMSTUDIO_CHAT_MODEL,
        "n_ctx": n_ctx_local,
        "timeout": LMSTUDIO_CHAT_TIMEOUT,
        "headers": {},
    })
    return cadena


async def _pedir_a_proveedor(
    prov: dict,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    etiqueta: str,
    chars_prompt: int,
) -> tuple[str, str]:
    """
    Una petición a un proveedor concreto. Devuelve `(estado, contenido)`:
      - `("ok", texto)`      respuesta utilizable
      - `("siguiente", "")`  este proveedor no sirve; probar el de detrás
      - `("contexto", "")`   el prompt no cabe en la ventana de este modelo
      - `("cupo", "")`       429: hay que esperar, no cambiar de proveedor
    """
    payload = {
        "model": prov["modelo"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LMSTUDIO_CHAT_TEMPERATURE,
        "seed": LMSTUDIO_SEED,
    }
    # LM Studio interpreta max_tokens=-1 como "sin límite"; OpenRouter responde
    # 400 ante un valor negativo, así que para la nube se traduce a un tope.
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = max_tokens
    elif prov["remoto"]:
        payload["max_tokens"] = OPENROUTER_MAX_TOKENS
    else:
        payload["max_tokens"] = max_tokens

    # El timeout crece con el prompt: el modelo tiene que leerse la entrada
    # entera antes de escribir el primer token, y 300 s fijos tumbaron las
    # cuatro llamadas de 106.000 tokens del 2026-09-03.
    tok_prompt = max(0, chars_prompt) / 4.0
    timeout = min(
        LLM_TIMEOUT_MAXIMO,
        prov["timeout"] + (tok_prompt / 1000.0) * LLM_SEGUNDOS_POR_1K_TOKENS,
    )

    semaforo = LLM_SEMAPHORE_REMOTO if prov["remoto"] else LLM_SEMAPHORE
    try:
        async with semaforo:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    prov["url"],
                    json=payload,
                    headers=prov["headers"],
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    cuerpo = await resp.text()
                    if resp.status == 429:
                        logger.warning(
                            f"  [{etiqueta}] {prov['nombre']}: 429, cupo agotado."
                        )
                        return "cupo", ""
                    if resp.status != 200:
                        cuerpo_bajo = cuerpo.lower()
                        if resp.status == 400 and (
                            "n_keep" in cuerpo
                            or "context length" in cuerpo_bajo
                            or "maximum context" in cuerpo_bajo
                            or "available context size" in cuerpo_bajo
                        ):
                            # El motor dice en el error cuál es su ventana DE
                            # VERDAD, y no tiene por qué ser la que declaró al
                            # cargarse: medido el 2026-09-04, LM Studio anunció
                            # n_ctx=262144 y rechazó un prompt de 6.854 tokens
                            # porque servía 8192. Con la ventana declarada, el
                            # guardián de más arriba deja pasar prompts que el
                            # motor no puede atender y la red de seguridad no
                            # salva nada. Se aprende del error y se recuerda.
                            real = re.search(r"available context size \((\d+)", cuerpo_bajo)
                            if real:
                                ventana_real = int(real.group(1))
                                if ventana_real < (prov.get("n_ctx") or 10**9):
                                    prov["n_ctx"] = ventana_real
                                    _VENTANA_REAL[prov["nombre"]] = ventana_real
                                    logger.warning(
                                        f"  [{etiqueta}] {prov['nombre']}: su ventana real son "
                                        f"{ventana_real} tok, no los que declaró. Anotado para "
                                        f"el resto de la ejecución."
                                    )
                            else:
                                logger.warning(
                                    f"  [{etiqueta}] {prov['nombre']}: el prompt no cabe en su ventana."
                                )
                            return "contexto", ""
                        logger.warning(
                            f"  [{etiqueta}] {prov['nombre']}: status {resp.status} — {cuerpo[:160]}"
                        )
                        return "siguiente", ""
                    data = json.loads(cuerpo)
    except asyncio.TimeoutError:
        logger.warning(f"  [{etiqueta}] {prov['nombre']}: timeout tras {timeout:.0f}s "
                       f"(prompt de ~{tok_prompt:.0f} tok).")
        return "siguiente", ""
    except Exception as e:
        logger.warning(f"  [{etiqueta}] {prov['nombre']}: {e}")
        return "siguiente", ""

    # OpenRouter puede devolver 200 con el error dentro del cuerpo.
    if isinstance(data, dict) and data.get("error"):
        detalle = data["error"]
        mensaje_err = detalle.get("message") if isinstance(detalle, dict) else detalle
        logger.warning(f"  [{etiqueta}] {prov['nombre']}: {str(mensaje_err)[:160]}")
        return "siguiente", ""

    truncada = False
    mensaje = (data.get("choices") or [{}])[0].get("message") or {}
    # Los modelos de razonamiento a veces dejan `content` vacío y vuelcan la
    # salida en `reasoning`.
    contenido = mensaje.get("content") or mensaje.get("reasoning") or ""
    if not contenido.strip():
        logger.warning(f"  [{etiqueta}] {prov['nombre']}: respuesta vacía.")
        return "siguiente", ""

    # ── Consumo real declarado por el proveedor + autocalibración ─────────────
    try:
        uso = data.get("usage") or {}
        prompt_tokens = uso.get("prompt_tokens")
        completion_tokens = uso.get("completion_tokens")
        finish_reason = (data.get("choices") or [{}])[0].get("finish_reason")

        if prompt_tokens:
            logger.info(
                f"  [CTX/{etiqueta}] real: prompt={prompt_tokens} tok, "
                f"respuesta={completion_tokens} tok, finish_reason={finish_reason} "
                f"| vía {prov['nombre']}"
            )
            # La calibración chars→tokens sirve para presupuestar el contexto
            # del modelo local: alimentarla con el tokenizador de otro modelo la
            # falsearía. Solo cuenta lo que mide LM Studio.
            if not prov["remoto"]:
                registrar_uso_real(chars_prompt, prompt_tokens)

        if finish_reason == "length":
            logger.warning(
                f"  [CTX/{etiqueta}] La respuesta se cortó por LONGITUD "
                f"({completion_tokens} tok). El JSON llegará truncado."
            )
            truncada = True
    except Exception as e:
        logger.debug(f"  [CTX/{etiqueta}] No se pudo leer `usage`: {e}")

    # Un JSON cortado a media frase no se parsea. Se avisa al llamador para que
    # lo reintente con más presupuesto en vez de dar la respuesta por perdida.
    return ("truncado" if truncada else "ok"), contenido


async def llm_chat_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = LMSTUDIO_CHAT_MAX_TOKENS,
    etiqueta: str = "LLM",
) -> dict | None:
    """
    Petición genérica de chat que devuelve un dict parseado del JSON de respuesta.

    Recorre la cadena de proveedores: primero los modelos gratuitos de OpenRouter
    (por orden de parecido con el 27B) y LM Studio como último recurso. Gana el
    primero que conteste algo utilizable; el resto ni se toca.

    `etiqueta` identifica la llamada en la traza de contexto (DISCOVERY, ENRICHMENT...).
    Toda petición deja constancia de: n_ctx del modelo local, tokens del system
    prompt, tokens del contexto enviado, reserva de salida y tokens realmente
    generados. Si el modelo se corta por longitud (`finish_reason == "length"`)
    se avisa: ese caso pasaría inadvertido y produce JSON truncado.
    """
    global _MODELO_REMOTO_PREFERIDO

    # ── Traza de contexto (Fase 0: solo mide, no decide) ──────────────────────
    # El n_ctx es el del modelo local: sigue siendo el presupuesto más estrecho
    # de la cadena, así que vale como cota conservadora para todos.
    chars_prompt = len(system_prompt) + len(user_prompt)
    try:
        n_ctx = get_n_ctx()
        tok_system = contar_tokens(system_prompt)
        tok_user = contar_tokens(user_prompt)
        tok_prompt_est = tok_system + tok_user + OVERHEAD_PLANTILLA_TOKENS
        margen_est = n_ctx - tok_prompt_est
        nivel = logger.warning if margen_est < 512 else logger.info
        nivel(
            f"  [CTX/{etiqueta}] n_ctx={n_ctx} | system={tok_system} tok | "
            f"contexto={tok_user} tok | prompt≈{tok_prompt_est} tok | "
            f"libre para respuesta≈{margen_est} tok | max_tokens={max_tokens}"
        )
    except Exception as e:  # la instrumentación jamás debe tumbar el pipeline
        logger.debug(f"  [CTX/{etiqueta}] No se pudo calcular la traza de contexto: {e}")

    cadena = _cadena_proveedores()
    hubo_desbordamiento = False
    # Tokens que este prompt necesita de verdad, para no ofrecérselo a un
    # proveedor cuya ventana no lo admite. Sin esto, un 429 del remoto hacía
    # saltar a LM Studio con su n_ctx de 8192 y la llamada se perdía "por
    # contexto" cuando el problema era el cupo.
    try:
        tok_necesarios = (contar_tokens(system_prompt) + contar_tokens(user_prompt)
                          + OVERHEAD_PLANTILLA_TOKENS)
    except Exception:
        tok_necesarios = 0

    for i, prov in enumerate(cadena):
        ventana = prov.get("n_ctx") or 0
        if tok_necesarios and ventana and tok_necesarios >= ventana:
            logger.info(
                f"  [{etiqueta}] {prov['nombre']} se salta: el prompt necesita "
                f"{tok_necesarios} tok y su ventana son {ventana}."
            )
            hubo_desbordamiento = True
            continue

        estado, contenido = await _pedir_a_proveedor(
            prov, system_prompt, user_prompt, max_tokens, etiqueta, chars_prompt,
        )

        # 429: es cupo, no un fallo del proveedor. Cambiar de modelo aquí es
        # justo lo que no hay que hacer —el siguiente es el local, que no puede
        # con el prompt—, así que se espera y se reintenta con el mismo.
        espera = LLM_BACKOFF_429
        for intento in range(LLM_REINTENTOS_429):
            if estado != "cupo":
                break
            logger.info(
                f"  [{etiqueta}] {prov['nombre']}: esperando {espera:.0f}s por cupo "
                f"(intento {intento + 1}/{LLM_REINTENTOS_429})."
            )
            await asyncio.sleep(espera)
            espera *= 2
            estado, contenido = await _pedir_a_proveedor(
                prov, system_prompt, user_prompt, max_tokens, etiqueta, chars_prompt,
            )
        if estado == "cupo":
            logger.warning(
                f"  [{etiqueta}] {prov['nombre']}: sigue sin cupo tras "
                f"{LLM_REINTENTOS_429} reintentos. Se prueba el siguiente."
            )
            estado = "siguiente"

        # Cortada por longitud: el JSON viene a medias y no se puede parsear.
        # Se reintenta UNA vez con más presupuesto antes de darla por perdida.
        #
        # Existe porque los modelos que razonan gastan del mismo presupuesto que
        # la respuesta, y los topes finos de este pipeline están calibrados para
        # un modelo que no razona. Medido el 2026-09-03 con qwen3-32b: 15 de las
        # 20 llamadas de PROCEDENCIA se cortaron en sus 90 tokens —todo el
        # presupuesto se iba en pensar, sin llegar a escribir el JSON— y las que
        # sí terminaron necesitaron entre 275 y 749. Cada corte apagaba en
        # silencio el filtro de homónimos para ese documento, porque una
        # comprobación fallida conserva el documento.
        if estado == "truncado" and max_tokens and 0 < max_tokens < LLM_TOPE_REINTENTO:
            ampliado = min(max_tokens * LLM_FACTOR_REINTENTO_TRUNCADO, LLM_TOPE_REINTENTO)
            logger.info(
                f"  [CTX/{etiqueta}] Reintento con {ampliado} tokens de salida "
                f"(antes {max_tokens}), que no daban para cerrar el JSON."
            )
            estado, contenido = await _pedir_a_proveedor(
                prov, system_prompt, user_prompt, ampliado, etiqueta, chars_prompt,
            )

        if estado in ("ok", "truncado"):
            if prov["remoto"]:
                _MODELO_REMOTO_PREFERIDO = prov["modelo"]
            return _parse_json_llm(contenido)

        if estado == "contexto":
            hubo_desbordamiento = True
        # El que acaba de fallar deja de ser el atajo preferido.
        if prov["remoto"] and prov["modelo"] == _MODELO_REMOTO_PREFERIDO:
            _MODELO_REMOTO_PREFERIDO = None
        if prov["remoto"] and i < len(cadena) - 1:
            await asyncio.sleep(OPENROUTER_PAUSA_ENTRE_MODELOS)

    # No sirvió ninguno. Si alguno se quejó de la ventana de contexto hay que
    # avisar al llamador, que sabe recortar el contexto y reintentar.
    if hubo_desbordamiento:
        raise ContextOverflowError(
            f"[{etiqueta}] el prompt no cupo en ningún modelo de la cadena."
        )
    logger.error(f"  [{etiqueta}] Ningún proveedor devolvió respuesta utilizable.")
    return None


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
            f'Extraer fiestas ÚNICAMENTE para: "{localidad["nombre"]}" (ID: {localidad["id"]}).\n'
            f'IMPORTANTE: Estás analizando una PEDANÍA del municipio de {municipio["nombre"]}. '
            f'El texto puede contener información de las fiestas generales de {municipio["nombre"]} '
            f'que NO son de esta pedanía.\n'
            f'REGLA ANTI-CONTAMINACIÓN:\n'
            f'PREGUNTA CLAVE, antes de incluir cualquier fiesta: ¿de quién dice el texto que ES '
            f'esta fiesta? No de qué habla, sino a quién se la atribuye. Escribe esa respuesta en '
            f'el campo "sede_segun_el_texto" de cada fiesta.\n'
            f'- Si la respuesta es "{localidad["nombre"]}", inclúyela.\n'
            f'- Si la respuesta es "{municipio["nombre"]}", el municipio, el pueblo grande o la '
            f'capital, NO la incluyas: no es de {localidad["nombre"]}, por muy detallado que sea su '
            f'programa.\n'
            f'- Señales de que la fiesta es del municipio y no de esta pedanía: el nombre de la '
            f'fiesta contiene "{municipio["nombre"]}"; los actos citan recintos, plazas, calles o '
            f'premios del municipio; el texto la presenta como "las fiestas patronales" sin más, '
            f'a secas, refiriéndose al conjunto.\n'
            f'- Que un texto de {localidad["nombre"]} MENCIONE al municipio no lo descalifica: lo '
            f'que decide es a quién atribuye la celebración, no a quién nombra.\n'
            f'- REGLA POSITIVA: si el texto sitúa una fiesta EN {localidad["nombre"]}, extráela '
            f'aunque nombre también a {municipio["nombre"]}. Ejemplo correcto: "Fiestas de Santiago '
            f'en el concejo de Larrinbe (Amurrio), del 24 al 26 de julio" es una fiesta de Larrinbe.\n'
            f'- Ejemplo INCORRECTO que debes evitar: atribuir a {localidad["nombre"]} una fiesta '
            f'llamada "Fiestas Patronales de {municipio["nombre"]}". Si el nombre lleva el del '
            f'municipio, la sede es el municipio.\n'
            f'- "Relevancia: DIRECTA" solo significa que el texto NOMBRA a {localidad["nombre"]}; '
            f'no significa que la fiesta sea suya.\n'
            f'- Que {localidad["nombre"]} aparezca en una enumeración de aldeas '
            f'("las localidades de X, Y y Z") no le atribuye ninguna fiesta.\n'
            f'- Si un programa cita plazas o ubicaciones que no reconoces como propias de '
            f'{localidad["nombre"]}, no se lo asignes.\n'
            f'- IMPORTANTE, y no es un fallo: MUCHAS localidades pequeñas no tienen fiestas '
            f'documentadas en internet. Devolver {{"fiestas": []}} es un resultado CORRECTO, '
            f'esperado y frecuente. No estás obligado a encontrar nada. Nadie te penaliza por '
            f'la lista vacía; sí por inventar o por copiar las de otro pueblo.\n'
            f'- Ante la duda entre no devolver nada y devolver una fiesta que quizá no sea de '
            f'{localidad["nombre"]}, NO devuelvas nada.'
        )

    system_prompt = f"""Eres un API estricta especializada en extraer información de fiestas locales en España.
CONTEXTO: Estás analizando información de {municipio['nombre']} ({municipio.get('provincia', 'España')}).

{CRITERIO_FIESTAS}

{JERARQUIA_FUENTES}

OBJETIVO CRÍTICO:
{regla_exclusividad}
RECUERDA: una lista vacía es una respuesta legítima. Es preferible no devolver ninguna fiesta que devolver una que no le corresponde a esta localidad.
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
      "sede_segun_el_texto": "nombre de la localidad a la que el TEXTO atribuye esta fiesta",
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
            parsed = await llm_chat_json(system_prompt, user_prompt, max_tokens=LMSTUDIO_CHAT_MAX_TOKENS, etiqueta="SINGLEPASS")
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

# Los dos topes en caracteres con los que se recortaba el contexto. Ya no
# recortan nada: el tamaño de cada lote sale de `tokens_por_lote()`, que lo
# deriva del presupuesto real del modelo. Se conservan porque siguen siendo el
# valor por defecto de algún parámetro y varios tests los importan.
DISCOVERY_MAX_CHARS = 20000
ENRICHMENT_MAX_CHARS = 32000

# Longitudes típicas de los system prompts, para dimensionar el lote cuando
# todavía no se ha construido el prompt de esa llamada. Medidas en la ejecución
# del 2026-09-03: discovery ≈ 2.057 tokens, enrichment ≈ 742.
_SYSTEM_DISCOVERY_TIPICO = "x" * 7000
_SYSTEM_ENRICHMENT_TIPICO = "x" * 2500
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
    municipio_nombre: str = "",
    localidad_nombre: str = "",
    nombres_hermanas: list[str] | None = None,
    anno: int | None = None,
) -> list[dict]:
    """
    Fragmenta cada documento y calcula sus vector embeddings en batch 1 sola vez per localidad.
    Pre-calcula la relevancia geográfica a nivel de DOCUMENTO (por URL) para que los chunks
    de programas de actos (que no mencionan el nombre del pueblo) hereden la relevancia
    de la página completa de la que proceden.
    Devuelve una lista de dicts indexed_chunks.
    """
    if not documentos:
        return []

    # Pre-calcular relevancia geográfica por URL usando el texto COMPLETO del documento.
    # Así un chunk de horarios ("10:00 Pasacalles, 23:00 DJ") hereda la relevancia
    # de su página padre ("Fiestas de Ibarra 2026 — programa de actos...").
    # `clasificar_relevancia_documento` exige que la página TRATE de la localidad
    # (la nombra en URL o encabezado, o varias veces fuera de enumeraciones). Con
    # el criterio anterior bastaba una aparición en 20.000 chars: la agenda de
    # Amurrio salía DIRECTA para Aloria por figurar en "(Aloria, Artomaña,
    # Tertanga y Delika)", y sus chunks —el programa de San Roque incluido—
    # heredaban esa etiqueta y se le atribuían a la aldea.
    doc_relevancia_cache: dict[str, str] = {}
    if nombres_hermanas and localidad_nombre:
        for doc in documentos:
            url = doc.get("url", "")
            if url and url not in doc_relevancia_cache:
                texto_doc = (doc.get("texto") or "").strip()
                if texto_doc and fuente_base(doc.get("fuente", "")) == FUENTE_WEB_MUNICIPIO:
                    doc_relevancia_cache[url] = clasificar_relevancia_documento(
                        texto_doc, url, localidad_nombre, nombres_hermanas
                    )

    # Documentos de OTRO sitio de España. Los buscadores devuelven el programa de
    # fiestas de cualquier pueblo homónimo o simplemente parecido, y una vez
    # dentro compiten por el presupuesto con ventaja: son programas de verdad,
    # largos y llenos de horarios, así que puntúan alto. Se van antes de trocear
    # para no gastar embeddings en ellos.
    #
    # Solo se examina lo que llega de BUSCADOR, que es por donde entra: los 109
    # chunks de Almansa venían todos de 'busqueda_web'. Una web oficial o unas
    # RRSS del ayuntamiento hablan de su pueblo aunque no repitan su nombre en
    # cada página, y ahí este criterio no vale.
    ajenos = 0
    if localidad_nombre or municipio_nombre:
        conservados = []
        for doc in documentos:
            de_buscador = fuente_base(doc.get("fuente", "")) in (
                FUENTE_BUSQUEDA, FUENTE_HISTORICO, FUENTE_PRENSA_REGIONAL
            )
            if de_buscador and documento_es_ajeno_al_municipio(
                doc.get("texto") or "", doc.get("url", ""),
                localidad_nombre, municipio_nombre, nombres_hermanas,
            ):
                ajenos += 1
                logger.info(
                    f"    [AJENO] Descartado '{doc.get('url', '')[:80]}': no nombra ni a "
                    f"{localidad_nombre} ni a {municipio_nombre} en todo el documento."
                )
                continue
            conservados.append(doc)
        documentos = conservados
    if ajenos:
        logger.info(f"    [AJENO] {ajenos} documentos de fuera del municipio descartados.")

    chunk_size = rag_processor.chunk_size if rag_processor else RAG_CHUNK_SIZE
    items = []
    chunks_tabulares = 0
    for doc in documentos:
        texto = (doc.get("texto") or "").strip()
        if not texto:
            continue
        url = doc.get("url", "")
        # De qué año es el documento, para que la cabecera pueda avisarlo. Se
        # calcula una vez por documento, no por fragmento.
        if anno:
            doc = dict(doc, anno_objetivo=anno,
                       anno_documento=anno_del_documento(url, texto))
        doc_rel = doc_relevancia_cache.get(url)  # None si no hay cache o no es web_municipio
        for n_chunk, chunk in enumerate(chunk_documento(texto, chunk_size)):
            # Un documento puede ser mayoritariamente prosa y contener aun asi
            # tablas de cifras (anexos, listados de tasas). Se filtran chunk a
            # chunk: ocupan presupuesto y no describen ninguna fiesta.
            if es_texto_tabular(chunk):
                chunks_tabulares += 1
                continue
            cabecera = generar_cabecera_chunk(doc, municipio_nombre, localidad_nombre)
            chunk_contextualizado = f"{cabecera}\n{chunk}"
            items.append({
                "chunk": chunk,
                "chunk_contextualizado": chunk_contextualizado,
                "fuente": doc.get("fuente", "busqueda_web"),
                "url": url,
                # Posición dentro de su página. El programa de una fiesta está
                # en UNA página y seguido, no repartido; sin este número no se
                # puede devolver al contexto en el orden en que se leía.
                "indice_chunk": n_chunk,
                "es_calendario": doc.get("es_calendario", False),
                "prioridad": prioridad_fuente(doc.get("fuente", "busqueda_web")),
                # Puntuación con la que la araña ordenó la página de origen: el
                # ranking deja de recalcularse desde cero en el RAG.
                "score_spider": doc.get("score_spider", 0),
                "rank_spider": doc.get("rank_spider"),
                "embedding": None,
                "doc_relevancia": doc_rel,
            })

    if chunks_tabulares:
        logger.info(f"  RAG: {chunks_tabulares} chunks descartados por ser tablas de cifras.")

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


def barrer_meses_con_senal(
    indexed_chunks: list[dict], localidad_nombre: str, anno: int | None = None,
) -> dict[int, list[dict]]:
    """
    Agrupa por mes los chunks que hablan de una fiesta DE ESTA localidad.

    Es el paso que decide qué mirar, y lo hace sin modelo: un chunk cuenta si
    nombra a la localidad, trae algún término festivo y cita un mes. Sustituye a
    preguntarle al modelo «¿qué fiestas tiene este pueblo?» sobre una muestra.

    El porqué está medido. El descubrimiento decidía qué fiestas existen viendo
    20.000 caracteres, que en Tobarra son 23 chunks de 189 —un 12%— y en Aranda
    23 de 415, un 6%. Con un corte tan estrecho, cualquier reordenación pequeña
    cambia lo que entra: entre dos ejecuciones del 2026-08-26 con el mismo
    material, Tobarra pasó de 4 fiestas a 2 y perdió la del Cristo, que tiene 50
    actos y es la principal del municipio.

    Lo de exigir que el CHUNK nombre a la localidad, y no solo el documento, no
    es un detalle. Medido sobre cuatro localidades: pidiéndolo solo al documento,
    el mes correcto salía primero en 2 de 4 —a Cordovilla, cuya fiesta es en
    noviembre, le salía julio, que es cuando celebran las otras pedanías del
    municipio—. Exigiéndolo al chunk, sale primero en 5 de 6.
    """
    por_mes: dict[int, list[dict]] = {}
    clave_loc = normalize_text(localidad_nombre or "").strip()
    if not clave_loc:
        return por_mes

    for item in indexed_chunks:
        chunk = item.get("chunk") or ""
        if not tiene_termino_festivo(chunk):
            continue
        texto = normalize_text(chunk)
        if clave_loc not in texto:
            continue
        meses = {_MESES_COMPLETOS[m] for m in re.findall(_RE_MESES, texto)}
        # Y los meses en los que caen este año los días móviles que el texto
        # nombre sin decir el mes: "Miércoles Santo", "martes de carnaval",
        # "Corpus". Sin esto, la Tamborada de Tobarra —lo más conocido del
        # municipio, 104 horas de tambor, inscrita por la UNESCO— no entra en
        # ningún cubo y nunca se le llega a preguntar al modelo. Comprobado el
        # 2026-09-02: falta en las dos ejecuciones completas, con el 9B y con
        # el 27B, y no es recall del modelo.
        if anno:
            meses |= meses_de_fiestas_moviles(chunk, anno)
        for mes in meses:
            por_mes.setdefault(mes, []).append(item)
    return por_mes


def agrupar_meses_para_preguntar(
    por_mes: dict[int, list[dict]], minimo_propio: int = 3,
) -> list[tuple[tuple[int, ...], list[dict]]]:
    """
    Decide por qué meses se pregunta y cuáles van juntos.

    Un mes con material propio se pregunta solo, para que el modelo no tenga que
    separar fiestas de meses distintos. Los meses con una o dos menciones sueltas
    se juntan en una tanda común: siguen mirándose —el corte acordado es «todos
    los meses con señal»— pero sin gastar una llamada cada uno. En Sinovas, tres
    de sus cuatro llamadas se iban en meses de un solo chunk.
    """
    propios = {m: v for m, v in por_mes.items() if len(v) >= minimo_propio}
    sueltos = [(m, v) for m, v in por_mes.items() if len(v) < minimo_propio]

    grupos: list[tuple[tuple[int, ...], list[dict]]] = [
        ((m,), v) for m, v in sorted(propios.items(), key=lambda kv: -len(kv[1]))
    ]
    if sueltos:
        meses = tuple(sorted(m for m, _ in sueltos))
        vistos, juntos = set(), []
        for _, v in sueltos:
            for item in v:
                if id(item) not in vistos:
                    vistos.add(id(item))
                    juntos.append(item)
        grupos.append((meses, juntos))
    return grupos


def repartir_en_llamadas(chunks: list[dict], presupuesto: int) -> list[list[dict]]:
    """
    FUERA DE LA RUTA VIVA desde el 2026-09-03: el discovery reparte con
    `reparto_contexto.repartir_en_lotes`, que mide en tokens sobre el texto ya
    ensamblado y no parte las páginas. Ajustar esto ya no cambia nada.

    Parte los chunks de un mes en tandas que quepan en el contexto.

    Solo se trocea lo que no cabe. Medido en Tobarra: de 450 chunks quedan 108
    con señal, pero son 131.660 caracteres, 6,6 veces el presupuesto. Agosto y
    mayo se llevan 58 cada uno y necesitan cuatro tandas; octubre, con 10, se
    resuelve en una.
    """
    tandas: list[list[dict]] = []
    actual: list[dict] = []
    usados = 0
    for item in sorted(chunks, key=lambda i: -i.get("score", 0.0)):
        largo = len(item.get("chunk") or "")
        if actual and usados + largo > presupuesto:
            tandas.append(actual)
            actual, usados = [], 0
        actual.append(item)
        usados += largo
    if actual:
        tandas.append(actual)
    return tandas


_NOMBRE_MES = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


async def _descubrir_sin_barrido(
    lotes: list[list[dict]], localidad: dict, municipio: dict,
    anno: int, system_prompt: str,
) -> list[dict]:
    """
    Red de seguridad para cuando el barrido no encuentra ningún mes con señal.

    Ya no es «la llamada única»: se pregunta por cada lote, igual que el barrido.
    Antes esta rama reintentaba con el 100%, el 70% y el 50% del texto cuando no
    cabía en la ventana; con el reparto eso sobra, porque ningún lote tiene que
    caber a la fuerza en una sola llamada. Y la traducción se hace lote a lote,
    no sobre el pool entero: en una comarca bilingüe traducir 600.000 caracteres
    para descartarlos luego era el peor negocio posible.
    """
    if not lotes:
        return []

    async def _preguntar(n: int, lote: list[dict]) -> list[dict]:
        texto = process_translation_pipeline(ensamblar_contexto(lote), municipio)
        for patron_str, reemplazo in DICCIONARIO_FESTIVO.items():
            texto = re.sub(patron_str, reemplazo, texto, flags=re.IGNORECASE)
        situacion = ""
        if len(lotes) > 1:
            situacion = (
                f"\nEste es el lote {n} de {len(lotes)} del material de esta "
                f"localidad, ordenados de más a menos relevante. Que un lote no "
                f"traiga ninguna fiesta es normal.\n"
            )
        user_prompt = (
            f"AÑO: {anno}\n{situacion}\n"
            f"TEXTO RECUPERADO:\n{texto}\n\n"
            f"Extrae la lista básica de fiestas en formato JSON exclusivamente para {localidad['nombre']}. "
            f"Recuerda, responde SOLO con JSON:\n```json\n"
        )
        sufijo = f" {n}/{len(lotes)}" if len(lotes) > 1 else ""
        try:
            parsed = await llm_chat_json(
                system_prompt, user_prompt,
                max_tokens=LMSTUDIO_CHAT_MAX_TOKENS, etiqueta=f"DISCOVERY{sufijo}",
            )
        except ContextOverflowError as e:
            logger.warning(f"  [DISCOVERY n_ctx]{sufijo}: {e}")
            return []
        return (parsed or {}).get("fiestas", []) or []

    logger.info(
        f"  [DISCOVERY] {localidad['nombre']}: sin meses con señal; "
        f"se pregunta por los {len(lotes)} lote(s) del material."
    )
    resultados = await asyncio.gather(
        *[_preguntar(n, lote) for n, lote in enumerate(lotes, 1)],
        return_exceptions=True,
    )
    fiestas: list[dict] = []
    for r in resultados:
        if isinstance(r, BaseException):
            logger.warning(f"  [DISCOVERY] {localidad['nombre']}: un lote falló: {r}")
            continue
        fiestas.extend(r)
    return _fusionar_fiestas_descubiertas(fiestas)


async def _descubrir_por_meses(
    indexed_chunks: list[dict], localidad: dict, municipio: dict,
    anno: int, system_prompt: str,
) -> list[dict] | None:
    """
    Pregunta mes a mes, con el material de cada mes delante.

    Devuelve None si el barrido no encuentra nada, para que el llamante caiga a
    la llamada única. Los meses con poco material van juntos en una tanda común:
    se siguen mirando, pero sin gastar una llamada cada uno.
    """
    por_mes = barrer_meses_con_senal(indexed_chunks, localidad.get("nombre", ""), anno)
    if not por_mes:
        return None

    # El tamaño del lote sale del presupuesto real del modelo que va a contestar,
    # no de una constante en caracteres. Con n_ctx = 131.072 son ~114.000 tokens,
    # así que la mayoría de los meses caben en un solo lote y el reparto solo
    # actúa donde de verdad sobra material.
    lote_tok = tokens_por_lote(system_prompt, RESERVA_SALIDA_DISCOVERY)

    grupos = agrupar_meses_para_preguntar(por_mes, DISCOVERY_MIN_CHUNKS_MES_PROPIO)
    tandas: list[tuple[tuple[int, ...], list[dict], int, int]] = []
    for meses, chunks in grupos:
        lotes = repartir_en_lotes(chunks, lote_tok, ensamblar_contexto, contar_tokens)
        for n, lote in enumerate(lotes, 1):
            tandas.append((meses, lote, n, len(lotes)))

    # Tope de seguridad, no de diseño. Antes estaba en 10 y Aranda de Duero lo
    # tocaba —12 meses con señal, 10 llamadas—, así que dos meses con material
    # se quedaban sin preguntar. Ahora solo existe para que un nombre corriente
    # («Sierra» disparaba 21 tandas) no se lleve la ejecución por delante.
    if len(tandas) > DISCOVERY_MAX_LLAMADAS_LOCALIDAD:
        logger.warning(
            f"  [DISCOVERY] {localidad['nombre']}: {len(tandas)} tandas recortadas "
            f"a {DISCOVERY_MAX_LLAMADAS_LOCALIDAD}. Se pierde material: revisa el tope."
        )
        tandas = tandas[:DISCOVERY_MAX_LLAMADAS_LOCALIDAD]

    total_chunks = sum(len(t[1]) for t in tandas)
    logger.info(
        f"  [DISCOVERY] {localidad['nombre']}: {len(por_mes)} meses con señal, "
        f"{len(tandas)} llamadas, {total_chunks} fragmentos "
        f"(lote de {lote_tok} tok)."
    )

    # Las tandas se preguntan A LA VEZ. Cada una mira meses distintos del mismo
    # pueblo con su propio material delante, y ninguna necesita lo que devuelva
    # otra: encadenarlas era tiempo de reloj regalado. Medido el 2026-09-03, el
    # discovery se lleva el 22% de la ejecución y Tobarra gasta siete llamadas.
    #
    # El orden se conserva (`gather` respeta el de entrada), que importa porque
    # `_fusionar_fiestas_descubiertas` da preferencia a lo que llega primero, y
    # las tandas vienen ordenadas de más material a menos.
    async def _preguntar_tanda(
        meses: tuple, tanda: list[dict], n_lote: int, total_lotes: int,
    ) -> list[dict]:
        etiqueta_meses = " y ".join(_NOMBRE_MES[m] for m in meses if 1 <= m <= 12)
        contexto = ensamblar_contexto(tanda)
        texto = process_translation_pipeline(contexto, municipio)
        for patron_str, reemplazo in DICCIONARIO_FESTIVO.items():
            texto = re.sub(patron_str, reemplazo, texto, flags=re.IGNORECASE)

        # Decirle al modelo DÓNDE está mirando. Desde que nada se descarta, los
        # últimos lotes de un mes son la cola del ranking y es normal que no
        # traigan ninguna fiesta; sin este aviso, un modelo aplicado se siente
        # obligado a encontrar algo, que es exactamente como salieron los 39
        # actos inventados de Sierra.
        situacion = ""
        if total_lotes > 1:
            situacion = (
                f"\nEste es el lote {n_lote} de {total_lotes} del material de "
                f"{etiqueta_meses}, ordenados de más a menos relevante. "
                + ("Es el mejor material que hay.\n" if n_lote == 1 else
                   "Los lotes anteriores ya traían lo mejor, así que es normal "
                   "que en este no haya ninguna fiesta.\n")
            )

        user_prompt = (
            f"AÑO: {anno}\n"
            f"{situacion}\n"
            f"TEXTO RECUPERADO:\n{texto}\n\n"
            f"Extrae las fiestas de {localidad['nombre']} que este texto sitúe en "
            f"{etiqueta_meses} de {anno}. Si el texto no trae ninguna fiesta de "
            f"{etiqueta_meses}, devuelve la lista vacía: es una respuesta correcta.\n"
            f"Responde SOLO con JSON:\n```json\n"
        )
        sufijo = f" {n_lote}/{total_lotes}" if total_lotes > 1 else ""
        try:
            parsed = await llm_chat_json(
                system_prompt, user_prompt,
                max_tokens=LMSTUDIO_CHAT_MAX_TOKENS,
                etiqueta=f"DISCOVERY/{etiqueta_meses[:12]}{sufijo}",
            )
        except ContextOverflowError as e:
            logger.warning(f"  [DISCOVERY n_ctx] {etiqueta_meses}{sufijo}: {e}")
            return []
        nuevas = (parsed or {}).get("fiestas", []) or []
        if nuevas:
            logger.info(f"  [DISCOVERY] {etiqueta_meses}{sufijo}: {len(nuevas)} fiesta(s).")
        return nuevas

    resultados = await asyncio.gather(
        *[_preguntar_tanda(meses, tanda, n, total) for meses, tanda, n, total in tandas],
        return_exceptions=True,
    )
    fiestas: list[dict] = []
    for r in resultados:
        if isinstance(r, BaseException):
            logger.warning(f"  [DISCOVERY] {localidad['nombre']}: una tanda falló: {r}")
            continue
        fiestas.extend(r)

    return _fusionar_fiestas_descubiertas(fiestas)


def _fusionar_fiestas_descubiertas(fiestas: list[dict]) -> list[dict]:
    """
    Une lo que devuelven las distintas tandas.

    Dos tandas del mismo mes pueden devolver la misma fiesta, y una fiesta a
    caballo entre dos meses sale en las dos. Se quedan por nombre y fecha de
    inicio, conservando la versión con más información.
    """
    fuera: dict[tuple, dict] = {}
    for f in fiestas:
        if not isinstance(f, dict):
            continue
        clave = (normalize_text(f.get("nombre") or "").strip(), (f.get("fecha_inicio") or "").strip())
        previa = fuera.get(clave)
        if previa is None or len(json.dumps(f, ensure_ascii=False)) > len(json.dumps(previa, ensure_ascii=False)):
            fuera[clave] = f
    return list(fuera.values())


async def discover_festivals_for_locality(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
    fecha_patron=None,
    nombres_hermanas: list[str] = None,
    contexto_precalculado: tuple[str, set, list] | None = None,
) -> list[dict]:
    """
    Paso 1 del RAG Multi-Pass (Discovery Pass):
    Recupera los mejores chunks y extrae el JSON con los metadatos básicos de fiestas.

    `contexto_precalculado` evita repetir la recuperación cuando quien llama
    (`analyze_festivals_multipass`) ya la ha hecho.
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
            f'Extraer fiestas ÚNICAMENTE para: "{localidad["nombre"]}" (ID: {localidad["id"]}).\n'
            f'IMPORTANTE: Estás analizando una PEDANÍA del municipio de {municipio["nombre"]}. '
            f'El texto puede contener información de las fiestas generales de {municipio["nombre"]} '
            f'que NO son de esta pedanía.\n'
            f'REGLA ANTI-CONTAMINACIÓN:\n'
            f'PREGUNTA CLAVE, antes de incluir cualquier fiesta: ¿de quién dice el texto que ES '
            f'esta fiesta? No de qué habla, sino a quién se la atribuye. Escribe esa respuesta en '
            f'el campo "sede_segun_el_texto" de cada fiesta.\n'
            f'- Si la respuesta es "{localidad["nombre"]}", inclúyela.\n'
            f'- Si la respuesta es "{municipio["nombre"]}", el municipio, el pueblo grande o la '
            f'capital, NO la incluyas: no es de {localidad["nombre"]}, por muy detallado que sea su '
            f'programa.\n'
            f'- Señales de que la fiesta es del municipio y no de esta pedanía: el nombre de la '
            f'fiesta contiene "{municipio["nombre"]}"; los actos citan recintos, plazas, calles o '
            f'premios del municipio; el texto la presenta como "las fiestas patronales" sin más, '
            f'a secas, refiriéndose al conjunto.\n'
            f'- Que un texto de {localidad["nombre"]} MENCIONE al municipio no lo descalifica: lo '
            f'que decide es a quién atribuye la celebración, no a quién nombra.\n'
            f'- REGLA POSITIVA: si el texto sitúa una fiesta EN {localidad["nombre"]}, extráela '
            f'aunque nombre también a {municipio["nombre"]}. Ejemplo correcto: "Fiestas de Santiago '
            f'en el concejo de Larrinbe (Amurrio), del 24 al 26 de julio" es una fiesta de Larrinbe.\n'
            f'- Ejemplo INCORRECTO que debes evitar: atribuir a {localidad["nombre"]} una fiesta '
            f'llamada "Fiestas Patronales de {municipio["nombre"]}". Si el nombre lleva el del '
            f'municipio, la sede es el municipio.\n'
            f'- "Relevancia: DIRECTA" solo significa que el texto NOMBRA a {localidad["nombre"]}; '
            f'no significa que la fiesta sea suya.\n'
            f'- Que {localidad["nombre"]} aparezca en una enumeración de aldeas '
            f'("las localidades de X, Y y Z") no le atribuye ninguna fiesta.\n'
            f'- Si un programa cita plazas o ubicaciones que no reconoces como propias de '
            f'{localidad["nombre"]}, no se lo asignes.\n'
            f'- IMPORTANTE, y no es un fallo: MUCHAS localidades pequeñas no tienen fiestas '
            f'documentadas en internet. Devolver {{"fiestas": []}} es un resultado CORRECTO, '
            f'esperado y frecuente. No estás obligado a encontrar nada. Nadie te penaliza por '
            f'la lista vacía; sí por inventar o por copiar las de otro pueblo.\n'
            f'- Ante la duda entre no devolver nada y devolver una fiesta que quizá no sea de '
            f'{localidad["nombre"]}, NO devuelvas nada.'
        )

    system_prompt = f"""Eres un API estricta especializada en identificar y catalogar las fiestas locales en España.
CONTEXTO: Municipio {municipio['nombre']} ({municipio.get('provincia', 'España')}), Localidad: {localidad['nombre']}.

{CRITERIO_FIESTAS}

{JERARQUIA_FUENTES}

OBJETIVO CRÍTICO:
{regla_exclusividad}
RECUERDA: una lista vacía es una respuesta legítima. Es preferible no devolver ninguna fiesta que devolver una que no le corresponde a esta localidad.
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
      "sede_segun_el_texto": "nombre de la localidad a la que el TEXTO atribuye esta fiesta",
      "solo_fuentes_no_oficiales": false
    }}
  ]
}}"""

    # La recuperación vive en un único sitio (`retrieve_discovery_context`).
    # Antes estaba duplicada literalmente aquí, lo que provocaba una segunda
    # ronda de embeddings por localidad y el riesgo de que ambas copias
    # divergieran al tocar una sola.
    if contexto_precalculado is not None:
        contexto, fuentes_contexto, lotes = contexto_precalculado
    else:
        contexto, fuentes_contexto, _n_directa, lotes = await retrieve_discovery_context(
            indexed_chunks=indexed_chunks,
            municipio=municipio,
            localidad=localidad,
            anno=anno,
            rag_processor=rag_processor,
            max_chars=DISCOVERY_MAX_CHARS,
            nombres_hermanas=nombres_hermanas,
            system_prompt=system_prompt,
        )

    if not contexto.strip():
        logger.warning(f"  [DISCOVERY] No hay texto de contexto para {localidad['nombre']}.")
        return []

    # La traducción NO se hace aquí. Se hacía sobre el contexto entero y antes de
    # saber si haría falta; ahora que el contexto es todo el material —cientos de
    # miles de caracteres— traducirlo por si acaso costaría más que todo lo
    # demás junto. Cada rama traduce su propio lote, y solo el que va a enviar.

    # El barrido decide QUÉ MESES mirar, y se pregunta por cada uno con su propio
    # material. Si no encuentra ningún mes con señal se cae a preguntar por los
    # lotes del pool, que es mejor que no preguntar nada.
    fiestas_raw = await _descubrir_por_meses(
        indexed_chunks, localidad, municipio, anno, system_prompt,
    )
    if fiestas_raw is None:
        fiestas_raw = await _descubrir_sin_barrido(
            lotes, localidad, municipio, anno, system_prompt,
        )
    fiestas_validas = validar_fiestas(fiestas_raw, localidad, anno, fecha_patron, fuentes_contexto)
    logger.info(
        f"  [DISCOVERY] Descubiertas {len(fiestas_validas)} fiestas preliminares "
        f"para {localidad['nombre']}."
    )
    return fiestas_validas


# Nombres de mes en las lenguas cooficiales, para reconocer una fecha escrita en
# prosa. El orden es enero..diciembre (índice 0..11).
_MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_MESES_CA = ("gener", "febrer", "març", "abril", "maig", "juny", "juliol",
             "agost", "setembre", "octubre", "novembre", "desembre")
_MESES_GL = ("xaneiro", "febreiro", "marzo", "abril", "maio", "xuño", "xullo",
             "agosto", "setembro", "outubro", "novembro", "decembro")
# Radical del mes en euskera: se declina con -a/-ak/-aren según la frase
# ("abuztua", "abuztuak 11", "abuztuaren 11ean").
_MESES_EU_RADICAL = ("urtarril", "otsail", "martxo", "apiril", "maiatz", "ekain",
                     "uztail", "abuztu", "irail", "urri", "azaro", "abendu")


def _variantes_fecha(fecha_str: str) -> list[str]:
    """
    Representaciones textuales de una fecha ISO tal como puede aparecer escrita
    en una web municipal real.

    La señal de día del enrichment solo comparaba contra el ISO exacto
    ("2026-08-11"), y casi ninguna web lo escribe así: lo normal es "11 de
    agosto", "11/08/2026" o, en euskera, "Abuztuak 11". Con solo el ISO la señal
    estaba casi siempre en 0 y el ranking de cada día caía al ranking general,
    que es indistinguible entre los días de una misma fiesta.
    """
    d = _parse_fecha_con_fallback_bisiesto(fecha_str)
    if d is None:
        return [fecha_str.lower()]

    dia, mes, anno = d.day, d.month, d.year
    variantes = {
        fecha_str,
        f"{dia:02d}-{mes:02d}-{anno}",
        f"{dia:02d}/{mes:02d}/{anno}",
        f"{dia}/{mes}/{anno}",
        f"{dia}-{mes}-{anno}",
        f"{anno}/{mes:02d}/{dia:02d}",
    }
    for meses in (_MESES_ES, _MESES_CA, _MESES_GL):
        nombre_mes = meses[mes - 1]
        variantes.add(f"{dia} de {nombre_mes}")
        variantes.add(f"{dia} {nombre_mes}")
    radical_eu = _MESES_EU_RADICAL[mes - 1]
    variantes.add(f"{radical_eu}ak {dia}")
    variantes.add(f"{radical_eu}aren {dia}")
    return [v.lower() for v in variantes]


def _bonus_oficial(prioridad: int) -> float:
    """
    Ventaja que se concede a una fuente por ser oficial, en la misma escala que
    el score (0..1).

    No es un desempate simbólico ni un veto: basta para que, a igualdad de
    calidad, gane la web del ayuntamiento, pero no para que un chunk municipal
    mediocre desplace al PDF del programa hallado por buscador.
    """
    if prioridad <= 2:      # web_localidad, web_municipio
        return ENRICHMENT_BONUS_OFICIAL
    if prioridad <= 4:      # rrss_localidad, rrss_municipio
        return ENRICHMENT_BONUS_OFICIAL / 2
    return 0.0              # prensa_regional, busqueda_web


def _fusionar_dias(programa: list) -> list:
    """
    Une los trozos de programa que devuelven los distintos lotes.

    Un mismo día puede aparecer en dos lotes si el modelo se sale del rango que
    se le pidió, así que se fusionan por fecha y se quitan los actos repetidos
    (misma hora y misma descripción), que es como se colaba el relleno cíclico.
    """
    por_fecha: dict = {}
    for dia in programa or []:
        if not isinstance(dia, dict):
            continue
        fecha = dia.get("fecha")
        if not fecha:
            continue
        destino = por_fecha.setdefault(
            fecha, {"dia": dia.get("dia"), "fecha": fecha, "eventos": []}
        )
        vistos = {
            ((e.get("hora") or "").strip(), (e.get("descripcion") or "").strip().lower())
            for e in destino["eventos"]
        }
        for evento in dia.get("eventos") or []:
            if not isinstance(evento, dict):
                continue
            clave = ((evento.get("hora") or "").strip(),
                     (evento.get("descripcion") or "").strip().lower())
            if not clave[1] or clave in vistos:
                continue
            vistos.add(clave)
            destino["eventos"].append(evento)
    return [por_fecha[f] for f in sorted(por_fecha)]


def _recortar_programa_al_rango(programa: list, fecha_ini: str, fecha_fin: str) -> list:
    """
    Deja en el programa solo los días comprendidos entre fecha_ini y fecha_fin.

    El modelo devuelve lo que quiere: para una fiesta declarada del 11 al 17 de
    agosto (7 días) entregó 21 días, hasta el 31, con los catorce últimos vacíos.
    Se aceptaba tal cual, así que el JSON anunciaba una fiesta de una semana con
    un programa de tres.
    """
    if not isinstance(programa, list):
        return []
    d_ini = _parse_fecha_con_fallback_bisiesto(fecha_ini)
    d_fin = _parse_fecha_con_fallback_bisiesto(fecha_fin)
    if d_ini is None or d_fin is None:
        return programa
    if d_ini > d_fin:
        d_ini, d_fin = d_fin, d_ini

    dentro = []
    for dia in programa:
        if not isinstance(dia, dict):
            continue
        d = _parse_fecha_con_fallback_bisiesto(dia.get("fecha"))
        if d is None or not (d_ini <= d <= d_fin):
            continue
        # Renumerar: el "dia" del modelo no es de fiar si ha inventado jornadas.
        dia["dia"] = (d - d_ini).days + 1
        dentro.append(dia)

    dentro.sort(key=lambda x: x.get("dia", 0))
    return dentro


async def enrich_festival_program(
    municipio: dict,
    localidad: dict,
    fiesta: dict,
    indexed_chunks: list[dict],
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
    nombres_hermanas: list[str] = None,
) -> dict:
    """
    Paso 2 del RAG Multi-Pass (Enrichment Pass):
    Recupera chunks día a día para la fiesta descubierta y enriquece `programa`.
    """
    nombre_fiesta = fiesta.get("nombre", "")
    fecha_ini = fiesta.get("fecha_inicio", "")
    fecha_fin = fiesta.get("fecha_fin", "")

    consultas_dias = generar_consultas_enriquecimiento(
        nombre_fiesta, fecha_ini, fecha_fin, max_dias=FIESTA_MAX_DURACION_DIAS
    )
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

    base_items = [dict(item) for item in indexed_chunks]

    for (fecha_str, query_str), query_emb in zip(consultas_dias, query_embs):
        # Copia superficial para no machacar el score entre días
        items_copy = [dict(item) for item in base_items]
        
        # Señal propia del enrichment: que el chunk hable del día concreto o de
        # esta fiesta por su nombre. Se mezcla como un componente más, con su
        # peso, en lugar de sumarse a pelo sobre el coseno.
        nombre_norm = nombre_fiesta.lower()
        variantes_fecha = _variantes_fecha(fecha_str)

        def _senal_dia(item, _variantes=variantes_fecha, _nombre=nombre_norm):
            txt = item["chunk"].lower()
            s = 0.0
            if any(v in txt for v in _variantes):
                s += 0.7
            if _nombre and _nombre in txt:
                s += 0.3
            return s

        puntuar_chunks(
            items_copy,
            query_emb=query_emb,
            anno=anno,
            coseno=AsyncRAGProcessor.cosine_similarity,
            señales_extra=_senal_dia,
        )

        # Aplicar filtro geográfico DESPUÉS de calcular similitud/score
        items_copy = filtrar_chunks_por_localidad(items_copy, localidad["nombre"], nombres_hermanas or [])
        items_copy = solo_chunks_de_la_localidad(items_copy, localidad, nombres_hermanas)

        umbral_dia = umbral_adaptativo(items_copy)
        chunks_dia = [i for i in items_copy if i.get("score", 0.0) >= umbral_dia]
        if not chunks_dia:
            chunks_dia = sorted(items_copy, key=lambda i: -i.get("score", 0.0))[:5]
        else:
            # Ordena por PUNTUACIÓN, con una bonificación para las fuentes
            # oficiales. Antes la clave era (prioridad, -score), con la prioridad
            # de primera: eso colocaba TODOS los chunks de web_municipio
            # (prioridad 2) por delante de CUALQUIERA de busqueda_web
            # (prioridad 6), puntuara lo que puntuara cada uno.
            #
            # Medido en Amurrio el 2026-08-21: los 37 chunks que entraron al
            # contexto eran los 37 de web_municipio, el peor con 0.531, y quedó
            # fuera el PDF del programa oficial —el que tiene los 44 actos con
            # hora— que puntuaba 0.675. La bonificación mantiene la preferencia
            # por lo oficial sin convertirla en un veto absoluto.
            chunks_dia = sorted(
                chunks_dia,
                key=lambda i: -(i.get("score", 0.0) + _bonus_oficial(i.get("prioridad", 9))),
            )

        for item in chunks_dia:
            chunk_key = (item["fuente"], item["chunk"])
            if chunk_key not in seen_chunks:
                seen_chunks.add(chunk_key)
                chunks_seleccionados_dias.append(item)


    if not chunks_seleccionados_dias:
        fiesta.setdefault("programa", [])
        return fiesta

    # Reserva para lo mejor puntuado, venga de donde venga. Es la misma idea que
    # `chunks_garantizados` en discovery: la jerarquía de fuentes ordena, pero no
    # puede vetar. En Amurrio el PDF del programa oficial era el 9º de 105 por
    # score y bastaban 16.254 de los 32.000 chars de presupuesto para alcanzarlo;
    # aun así quedaba fuera, porque los 37 chunks de web_municipio iban delante
    # por prioridad de fuente y agotaban el presupuesto.
    # Fuera las páginas fechadas en días que no son de esta fiesta, y plaza fija
    # para las que sí lo son: son el programa del día, y compiten entre ellas por
    # centésimas de score que no significan nada.
    chunks_seleccionados_dias, paginas_del_dia = filtrar_chunks_por_dias_de_la_fiesta(
        chunks_seleccionados_dias,
        _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio")),
        _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_fin")),
    )
    if not chunks_seleccionados_dias:
        fiesta.setdefault("programa", [])
        return fiesta

    orden_final = _ordenar_para_el_presupuesto(chunks_seleccionados_dias, paginas_del_dia)

    # Aquí estaba el recorte por presupuesto: un bucle que iba metiendo chunks
    # hasta llenar 32.000 caracteres y saltándose los que no cabían. Es el paso
    # que en Aranda de Duero dejó fuera 68 de los 82 fragmentos del PDF del
    # programa —el correcto, el que el localizador acababa de identificar— y,
    # de rebote, hizo que la guarda de «días no mencionados» descartara 5 de los
    # 7 lotes de días, porque juzgaba el documento por el trozo que sobrevivía.
    #
    # Ya no se recorta. El ranking ordena y el reparto decide en qué llamada va
    # cada cosa. Lo que ve el localizador es TODO el material, no lo que cupo:
    # antes solo podía elegir entre las páginas que el presupuesto había dejado
    # pasar.
    lote_tok = tokens_por_lote(_SYSTEM_ENRICHMENT_TIPICO, RESERVA_SALIDA_ENRICHMENT)
    chunks_finales = list(orden_final)
    contexto = ensamblar_contexto(chunks_finales)

    # Sin una página que traiga un programa de verdad no se pregunta. Preguntar
    # sin material no da un programa incompleto, da uno inventado: en Sierra,
    # donde ninguna página tenía un solo acto con hora, salieron 39 actos con
    # confianza alta y ni uno rastreable hasta su documento.
    urls_programa: list[str] = []
    if PROGRAM_LOCATOR_ENABLED:
        try:
            # La provincia y las lenguas viajan hasta el localizador porque
            # ahora puede traer documentos nuevos de internet, y todo lo que
            # entra pasa por el filtro de homónimos como cualquier otra fuente.
            _prov = (municipio.get("provincia") or "").strip()
            _com = (municipio.get("comunidad")
                    or municipio.get("comunidad_autonoma") or "").strip()
            try:
                _idiomas = get_language_profile(_com, _prov).get("idiomas_a_detectar") or ["es"]
            except Exception:
                _idiomas = ["es"]
            urls_programa, _docs_nuevos = await localizar_programa_con_llm(
                contexto, fiesta, localidad, municipio, anno, indexed_chunks,
                nombres_hermanas=nombres_hermanas, provincia=_prov, idiomas=_idiomas,
            )
            # Si por el camino se han afinado las fechas de la fiesta, los lotes
            # de días hay que rehacerlos: si no, se preguntaría por los días de
            # antes y el programa saldría fuera de rango.
            if urls_programa and (fiesta.get("fecha_inicio") != fecha_ini
                                  or fiesta.get("fecha_fin") != fecha_fin):
                fecha_ini, fecha_fin = fiesta.get("fecha_inicio"), fiesta.get("fecha_fin")
                logger.info(
                    f"  [ENRICHMENT] '{nombre_fiesta}': las fechas han cambiado a "
                    f"{fecha_ini}–{fecha_fin}. Se rehacen los lotes de días."
                )
                consultas_dias = generar_consultas_enriquecimiento(
                    nombre_fiesta, fecha_ini, fecha_fin,
                    max_dias=FIESTA_MAX_DURACION_DIAS,
                )
        except Exception as e:
            logger.warning(f"  [LOCATOR] '{nombre_fiesta}': {e}. Se sigue sin él.")
            urls_programa = []

    # El modelo propone, el calendario veta. El veto juzga la página ENTERA, no
    # el trozo que había en el contexto: en Aranda de Duero descartó el PDF de
    # septiembre de una fiesta de septiembre —«habla de otros meses y no del de
    # esta fiesta»— porque los fragmentos que habían sobrevivido al recorte
    # citaban julio y agosto y no septiembre. La ficha salió sin programa.
    if urls_programa:
        urls_programa, vetadas = vetar_paginas_imposibles(
            urls_programa, contexto, fiesta, anno, indexed_chunks=indexed_chunks)
        for url, motivo in vetadas:
            logger.warning(
                f"  [LOCATOR] '{nombre_fiesta}': descartada la elección del modelo "
                f"{url[:64]} — {motivo}."
            )

    # El determinista no se retira: es el respaldo cuando el modelo no se moja o
    # cuando el calendario le tumba la elección, y su veredicto se registra para
    # poder comparar los dos métodos.
    url_deterministe, n_actos_det = mejor_pagina_con_programa(contexto, fiesta)
    if urls_programa and url_deterministe and url_deterministe not in urls_programa:
        logger.info(
            f"  [LOCATOR] '{nombre_fiesta}': discrepan. El modelo elige "
            f"{urls_programa[0][:56]} y el recuento de horas "
            f"{url_deterministe[:56]} ({n_actos_det} actos). Manda el modelo."
        )
    if not urls_programa and url_deterministe:
        urls_programa = [url_deterministe]

    # Elegida la página, se deja de hacer RAG: el documento ES la fuente.
    #
    # Sus fragmentos entran ENTEROS y en orden, repartidos en tantos lotes como
    # haga falta. Antes esto lo hacía `_contexto_con_las_paginas_enteras` contra
    # un tope de 32.000 caracteres, y por eso en Aranda de Duero entraban 14 de
    # los 82 fragmentos del PDF: seleccionar por relevancia es lo contrario de
    # leer un documento entero y en orden.
    lotes_ctx: list[list[dict]] = []
    del_programa: list[dict] = []
    n_inyectados = n_disponibles = 0
    if urls_programa:
        vistos: set[int] = set()
        for u in urls_programa:
            for it in pagina_entera(indexed_chunks, u):
                if id(it) not in vistos:
                    vistos.add(id(it))
                    del_programa.append(it)
        n_disponibles = len(del_programa)

        # Y NADA MÁS. Ni el resto del pool ni el relleno mejor puntuado: para
        # extraer los actos de un documento conocido, todo lo demás es ruido que
        # estorba y que se paga caro.
        #
        # Medido el 2026-09-03, la primera vez que se probó con el relleno
        # dentro: el documento eran 18 fragmentos y el contexto salió a 105.346
        # tokens, así que las cuatro llamadas del enrichment de Aranda enviaron
        # 106.124 tokens cada una y LAS CUATRO agotaron el timeout de 300 s. La
        # ficha salió con 0 días y 0 actos teniendo el programa descargado y bien
        # identificado. Con solo el documento son ~20.000 tokens.
        #
        # Si hicieran falta dos fuentes —el cartel con las fechas y la noticia
        # con las horas—, el localizador puede elegir varias páginas: para eso
        # `urls_programa` es una lista.
        del_prog = set(urls_programa)
        lotes_ctx = repartir_en_lotes(
            del_programa, lote_tok, ensamblar_contexto, contar_tokens,
        )
        n_inyectados = sum(
            1 for l in lotes_ctx for i in l if (i.get("url") or "") in del_prog
        )
        chunks_finales = [i for l in lotes_ctx for i in l]
        contexto = ensamblar_contexto(chunks_finales)

    # El modelo dice dónde, pero el material sigue teniendo que existir. Sin
    # actos con hora lo que devuelve no es un programa flojo, es uno inventado:
    # en Sierra salieron 39 actos con confianza alta y ni uno rastreable hasta
    # su documento.
    n_actos_pagina = max(
        (contar_actos_horarios(t) for u, t in paginas_del_contexto(contexto)
         if u in set(urls_programa)), default=0)
    url_programa = urls_programa[0] if urls_programa else ""

    # Lo mismo, pero contado sobre la página ENTERA y no sobre el trozo que
    # sobrevivió al recorte. Es lo que distingue «este pueblo no publica
    # programa» de «el programa existe y no se lo hemos enseñado al modelo»:
    # dos resultados opuestos que hasta ahora salían con la misma bandera.
    #
    # Y es lo que decide si se pregunta. Antes decidía `n_actos_pagina`, contado
    # sobre el contexto ya recortado: un programa que existía pero no cabía
    # producía exactamente el mismo resultado que un pueblo sin programa.
    n_actos_documento = actos_del_documento(indexed_chunks, urls_programa)
    hay_programa = n_actos_documento >= ENRICHMENT_MIN_ACTOS_EN_PAGINA
    # De dónde se copió el programa, guardado en la ficha. Lo necesita el juez de
    # pertenencia del paso 8 —y su veto: si la página es la web del propio
    # pueblo, la ficha no se tira aunque el modelo dude—. Además es trazabilidad
    # que la base de datos agradecerá: hoy `fuentes` dice "busqueda_web", que no
    # permite volver al documento.
    if url_programa:
        fiesta["url_programa"] = url_programa
    if hay_programa:
        logger.info(
            f"  [ENRICHMENT] '{nombre_fiesta}': el programa está en "
            + (f"{len(urls_programa)} páginas, la primera " if len(urls_programa) > 1 else "")
            + f"{url_programa[:70]} ({n_actos_documento} actos con hora en el "
            f"documento, {n_actos_pagina} visibles en el contexto). "
            f"Entran {n_inyectados} de {n_disponibles} fragmentos, enteros y en orden."
        )
        # Cuando la única página que parece un programa no nombra la advocación
        # de ESTA fiesta, el programa que salga puede ser el de otra fiesta del
        # mismo pueblo, y eso no se ve luego en la ficha. Medido el 2026-08-26:
        # el Cristo de la Antigua de Tobarra se enriqueció desde una página de
        # agregador sobre el San Roque de Tobarra, porque su propio programa de
        # agosto no estaba en el contexto. Aquí no se puede decidir cuál es
        # —las dos caen en agosto—, pero sí dejarlo dicho.
        pagina = dict(paginas_del_contexto(contexto)).get(url_programa, "")

        # De qué año es lo que vamos a copiar. Si no es del nuestro se usa
        # igual —las fiestas se repiten y un programa viejo orienta— pero la
        # ficha lo dice y baja de confianza. Callarlo es lo que hizo que Aranda
        # saliera con 21 actos de 2025 y `confianza: alta`.
        anno_pagina = anno_del_documento(url_programa, pagina)
        if anno_pagina and anno_pagina != anno:
            fiesta["programa_de_otro_anno"] = anno_pagina
            fiesta["confianza"] = "baja"
            logger.warning(
                f"  [ENRICHMENT/AÑO] El único programa que hay para "
                f"'{nombre_fiesta}' de {localidad['nombre']} es de {anno_pagina}, "
                f"no de {anno}. Se usa como referencia y la ficha queda marcada: "
                f"{url_programa[:70]}"
            )

        senas = tokens_distintivos(nombre_fiesta, localidad.get("nombre", ""))
        if senas and not cuenta_tokens(senas, pagina):
            # Y baja de confianza, igual que el programa de otro año. Un
            # programa que no nombra por ningún sitio la advocación de la fiesta
            # que dice describir no puede sostener una ficha "alta". Medido en la
            # ejecución del 2026-09-02: Aranda de Duero salió con unas "Fiestas
            # Patronales (San Roque)" de veintinueve días y 166 actos, marcadas
            # con esta bandera y aun así con `confianza: alta` —el patrón de
            # Aranda es la Virgen de las Viñas, y San Roque no es fiesta suya—.
            fiesta["programa_advocacion_dudosa"] = True
            if fiesta.get("confianza") == "alta":
                fiesta["confianza"] = "media"
            logger.warning(
                f"  [ENRICHMENT/ADVOCACIÓN] La página elegida para "
                f"'{nombre_fiesta}' de {localidad['nombre']} no nombra "
                f"{sorted(senas)} por ningún sitio. Puede ser el programa de otra "
                f"fiesta del mismo pueblo: {url_programa[:70]}"
            )
    else:
        logger.info(
            f"  [ENRICHMENT] '{nombre_fiesta}' de {localidad['nombre']}: sin programa que "
            f"estructurar (la mejor página trae {n_actos_det} actos con hora); no se pregunta."
        )

    volcar_contexto(
        etapa="enrichment",
        localidad_nombre=f"{localidad['nombre']}__{_normalizar_nombre(nombre_fiesta)[:40]}",
        municipio_nombre=municipio.get("nombre", ""),
        contexto=contexto,
        candidatos=chunks_seleccionados_dias,
        seleccion=chunks_finales,
        # En modo documento el material que debía llegar son los fragmentos de
        # la página elegida, no el pool entero. Sin esto el volcado marcaba como
        # pérdida lo que el localizador había descartado a propósito.
        universo=del_programa if urls_programa else None,
        contar_tokens=contar_tokens,
        presupuesto={"lote_tokens": lote_tok},
        extra={
            "fiesta": nombre_fiesta,
            "dias_consultados": len(consultas_dias),
            "fragmentos_sin_presupuesto": 0,  # ya no se descarta por presupuesto
            # Numerador y denominador de la cobertura de actos: lo que el
            # documento trae frente a lo que el contexto llegó a enseñar.
            # En modo "documento" el pool NO se envía a propósito: su papel
            # terminó cuando el localizador eligió la página. Lo que en discovery
            # sería una pérdida, aquí es la decisión.
            "modo": "documento" if urls_programa else "pool",
            "url_programa": url_programa,
            "actos_documento": n_actos_documento,
            "actos_contexto": n_actos_pagina,
            "tramos_documento": len(lotes_ctx) or 1,
        },
        lotes=lotes_ctx or None,
    )

    # El corte va DESPUÉS del volcado, a propósito. Cuando estaba antes, las
    # fichas bloqueadas no dejaban contexto en disco y no había forma de
    # comprobar si el bloqueo era acertado: el 2026-08-26 se bloquearon La
    # Calabaza, Monte Costaján y Aranda, y para diagnosticarlo solo quedaban
    # volcados de ejecuciones de dos días antes. Es el mismo error que ya se
    # cometió con las descargas mudas: no se puede juzgar lo que no se ve.
    if not hay_programa:
        # Ahora esto significa de verdad «no hay programa publicado»: se ha
        # mirado la página ENTERA, no el trozo que cupo en el contexto. El caso
        # contrario —el programa existe y no lo hemos recogido— se detecta al
        # final, comparando la ficha con su documento.
        fiesta.setdefault("programa", [])
        fiesta["sin_programa_publicado"] = True
        return fiesta

    # Solo se interrogan los lotes de contexto donde ESTÁ el documento del
    # programa. El resto del pool sirvió para encontrarlo y ahí acaba su papel:
    # pedirle actos a la cola del ranking no da un programa incompleto, da uno
    # inventado, que es de lo que salieron los 39 actos de Sierra.
    _urls_prog = set(urls_programa)
    lotes_con_programa = [
        l for l in lotes_ctx if any((i.get("url") or "") in _urls_prog for i in l)
    ]
    if not lotes_con_programa:
        lotes_con_programa = [chunks_finales]

    # La traducción se hace por lote, no sobre el pool entero.
    textos_ctx: list[str] = []
    for _lote in lotes_con_programa:
        _t = process_translation_pipeline(ensamblar_contexto(_lote), municipio)
        for patron_str, reemplazo in DICCIONARIO_FESTIVO.items():
            _t = re.sub(patron_str, reemplazo, _t, flags=re.IGNORECASE)
        textos_ctx.append(_t)
    if len(textos_ctx) > 1:
        logger.info(
            f"  [ENRICHMENT] '{nombre_fiesta}': el documento no cabe en un solo "
            f"lote; se lee en {len(textos_ctx)} tramos."
        )

    # El programa se pide POR LOTES DE DÍAS, no de una vez. Medido el 2026-08-21:
    # con los 118 actos del cartel de Amurrio en el contexto (verificado que
    # estaban), pedir el programa entero en una sola respuesta devolvía 83 actos
    # y se dejaba fuera el día 13 completo, que era el más cargado con 32. No es
    # un fallo de recuperación sino de capacidad del modelo. Troceando, cada
    # llamada enumera unos pocos días y ninguna se satura.
    fechas = [f for f, _ in consultas_dias]
    lotes = [
        fechas[i:i + ENRICHMENT_DIAS_POR_LLAMADA]
        for i in range(0, len(fechas), ENRICHMENT_DIAS_POR_LLAMADA)
    ]

    # Un lote de días de los que el contexto no dice nada no se pregunta. Pedirlo
    # no deja el hueco vacío: el modelo lo rellena con lo que tiene cerca. Medido
    # el 2026-08-27 en Sinovas, cuando le faltaba el fragmento de los días 23 al
    # 26 y se le pidieron igual: colocó en el 23 la carrera urbana y la marcha
    # nocturna, que son del 26, y en el 25 el torneo de fútbol-sala, que es del
    # 27. No inventó actos —son todos reales— pero les cambió la fecha, que es
    # más difícil de ver que un día en blanco.
    # El silencio solo cuenta cuando sabemos leer las fechas de esta fuente. Si
    # el contexto no nombra NINGÚN día de la fiesta en un formato reconocible
    # —los carteles escaneados suelen poner "DÍA 14" a secas—, no hay nada que
    # deducir de que falte uno: ahí se pregunta todo, como hasta ahora.
    _planos = [t.lower() for t in textos_ctx]

    def _mencionado(dia: str, plano: str) -> bool:
        return any(v.lower() in plano for v in _variantes_fecha(dia))

    dias_reconocibles = sum(
        1 for f in fechas if any(_mencionado(f, p) for p in _planos)
    )
    # La guarda no depende de que el localizador haya acertado: depende de que
    # el contexto deje leer sus fechas. Con el documento entero delante, todos
    # sus días son reconocibles y la guarda no quita nada; solo salta en los
    # días que de verdad no están, que es cuando el modelo los rellenaba con
    # actos de los días vecinos cambiándoles la fecha.
    #
    # Antes se medía sobre el contexto RECORTADO, así que en Aranda de Duero
    # descartó 5 de los 7 lotes de días de una fiesta cuyo programa completo
    # estaba descargado: los días que faltaban eran justo los de los 68
    # fragmentos que el presupuesto había dejado fuera.
    aplicar_guarda = dias_reconocibles >= 2

    # Los lotes se piden A LA VEZ. Cada uno cubre días distintos de la misma
    # fiesta y no depende de lo que devuelvan los demás, así que encadenarlos
    # con `await` era tiempo de reloj regalado: medido el 2026-09-03, el
    # enrichment se lleva el 26% de la ejecución y una fiesta de quince días se
    # pide en cinco lotes, uno detrás de otro.
    #
    # El orden del resultado se conserva —`gather` respeta el de entrada— y el
    # número de llamadas en vuelo lo limita el semáforo remoto, no este bucle.
    # Qué se pregunta y contra qué tramo del documento. Un lote de días se pide
    # a cada tramo que nombre alguno de esos días; si ninguno los nombra, no se
    # pregunta y el hueco se queda vacío a propósito.
    peticiones: list[tuple[int, list[str], int, str]] = []
    for _n_dias, _dias in enumerate(lotes, 1):
        _tramos = [
            (j, txt) for j, (txt, plano) in enumerate(zip(textos_ctx, _planos), 1)
            if not aplicar_guarda or any(_mencionado(d, plano) for d in _dias)
        ]
        if not _tramos:
            logger.info(
                f"  [ENRICHMENT] '{nombre_fiesta}': el documento no menciona los días "
                f"{_dias[0]} a {_dias[-1]}; no se preguntan (se dejan sin actos)."
            )
            continue
        for _j, _txt in _tramos:
            peticiones.append((_n_dias, _dias, _j, _txt))

    async def _pedir_lote(n_lote: int, lote: list[str], n_tramo: int, texto_ctx: str) -> list[dict]:
        desde, hasta = lote[0], lote[-1]
        system_prompt = f"""Eres un API estricta especializada en estructurar el PROGRAMA DE ACTOS Y EVENTOS de una fiesta local en España.
CONTEXTO: Municipio {municipio['nombre']} ({municipio.get('provincia', 'España')}), Localidad: {localidad['nombre']}.
FIESTA: "{nombre_fiesta}" ({fecha_ini} a {fecha_fin}).

TE PIDO SOLO ESTOS DÍAS: {desde} a {hasta}. Ignora los actos de cualquier otro día.

REGLAS DE PROGRAMA DE ACTOS:
1. Extrae TODOS los actos que el texto sitúe en los días {desde} a {hasta}. No resumas ni agrupes: si un día tiene veinte actos, devuelve los veinte.
2. "fecha" debe ser YYYY-MM-DD y estar entre {desde} y {hasta}. "dia" es 1 para {fecha_ini}, 2 para el siguiente, etc.
3. Indica la hora si el texto la da (formato HH:MM, ej. "12:00", "23:30"). Si no la da, deja "". NO inventes horas.
4. Un acto pertenece al día bajo el que aparece en el texto. NO repitas el mismo acto en varios días.
5. Traduce las descripciones al castellano.
6. NO INVENTES ACTOS. Cada acto que devuelvas tiene que estar escrito en el texto que
   te doy. Si el texto no trae el programa de estos días —porque habla de otra cosa,
   porque solo describe la fiesta en general, o porque es una página administrativa—
   devuelve el programa VACÍO. Una lista vacía es una respuesta correcta y no te
   penaliza; inventar actos plausibles sí.

   El criterio es SOLO ese: que esté o no esté en el texto. Que un acto suene
   genérico no lo hace falso —«procesión del santo», «comida popular» o «diana y
   misa» son actos reales en cualquier pueblo—; si está escrito, va.
7. El texto viene en bloques, uno por página, marcados con --- [dirección] ---.
   Dentro de un bloque el texto va seguido, tal como se leía en esa página; un
   […] indica que falta un trozo por medio. El programa de una fiesta suele
   estar ENTERO en una sola página: en cuanto encuentres el bloque que lo trae,
   saca de ahí los actos y sus horas, y no los completes con actos de otros
   bloques, que casi siempre son de otra fiesta o de otro año.

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

        etiqueta_tramo = f" tramo {n_tramo}" if len(textos_ctx) > 1 else ""
        user_prompt = (
            f"FIESTA: {nombre_fiesta}\n"
            f"DÍAS PEDIDOS: {desde} a {hasta}\n\n"
            f"TEXTO RECUPERADO:\n{texto_ctx}\n\n"
            f"Genera el programa SOLO de los días {desde} a {hasta}. "
            f"Responde SOLO con JSON:\n```json\n"
        )

        try:
            parsed = await llm_chat_json(
                system_prompt, user_prompt,
                max_tokens=LMSTUDIO_CHAT_MAX_TOKENS,
                etiqueta=f"ENRICHMENT {n_lote}/{len(lotes)}{etiqueta_tramo}",
            )
        except Exception as e:
            logger.warning(
                f"  [ENRICHMENT] Error en el lote {desde}..{hasta} de '{nombre_fiesta}': {e}"
            )
            return None

        # `None` es "no se pudo preguntar"; `[]` es "se preguntó y no hay actos".
        # Devolver lo mismo en los dos casos convertía un fallo pasajero en un
        # dato erróneo: en Santa Marta de los Barros el 4.º de cuatro lotes se
        # perdió por timeout, y el recorte de rango dio la fiesta por terminada
        # el 28 de julio cuando el programa llega al 1 de agosto. Se perdió el
        # 29, que es el día de la patrona.
        if not (parsed and isinstance(parsed, dict) and isinstance(parsed.get("programa"), list)):
            return None
        # Cada lote se acota a SUS días: el modelo tiende a colar los vecinos.
        return _recortar_programa_al_rango(parsed["programa"], desde, hasta)

    resultados = await asyncio.gather(
        *[_pedir_lote(i, dias, j, txt) for i, dias, j, txt in peticiones],
        return_exceptions=True,
    )
    programa_total: list[dict] = []
    lotes_fallidos = 0
    for r in resultados:
        if isinstance(r, BaseException):
            logger.warning(f"  [ENRICHMENT] '{nombre_fiesta}': un lote falló: {r}")
            lotes_fallidos += 1
            continue
        if r is None:
            lotes_fallidos += 1
            continue
        programa_total.extend(r)

    # Se deja dicho en la ficha para que el recorte de rango no dé por
    # inexistentes los días que nadie llegó a preguntar.
    if lotes_fallidos:
        fiesta["lotes_incompletos"] = lotes_fallidos
        logger.warning(
            f"  [ENRICHMENT] '{nombre_fiesta}': {lotes_fallidos} de {len(peticiones)} "
            f"lotes sin respuesta. El programa queda incompleto y el rango NO se recorta: "
            f"los días que faltan no se han mirado, no es que no existan."
        )

    programa_total = _fusionar_dias(programa_total)
    programa_total = _recortar_programa_al_rango(programa_total, fecha_ini, fecha_fin)
    fiesta["programa"] = programa_total
    n_actos = sum(len(d.get("eventos", [])) for d in programa_total)
    logger.info(
        f"  [ENRICHMENT] '{nombre_fiesta}': {len(programa_total)} días y {n_actos} actos "
        f"en {len(peticiones)} llamada(s)."
    )

    # Verificación de cobertura: qué parte de lo que el documento trae ha
    # llegado a la ficha. Se mide por DÍAS, no por actos: el denominador son los
    # días de la fiesta que el propio documento nombra, leídos con el mismo
    # detector que la guarda de más arriba.
    #
    # En Aranda de Duero el documento nombraba los 10 días y la ficha salió con
    # 4, con `confianza: alta` y sin que nada dijera que faltaban 6.
    # PENDIENTE: este denominador cuenta como "día del documento" cualquier día
    # cuya fecha aparezca en el texto, aunque el documento no le ponga ni un
    # acto. En Tobarra eso hizo saltar «0 de 4 días del documento (0%) … no se ha
    # recogido entero» sobre un documento que no programaba ninguno de los cuatro
    # —eran el 24-abr y el 4-may de una venta de tickets y el 27-abr de la fecha
    # del artículo—, es decir culpando a la extracción de un fallo que estaba en
    # las fechas de la ficha.
    #
    # Se probó exigir una hora detrás de la fecha (ventana de 300 chars) y NO
    # sirve: en un programa denso siempre hay una hora cerca, así que en Tobarra
    # seguían contando los cuatro días, y en Aranda se perdía el 15-sep, que sí
    # es un día programado. Hace falta detectar la CABECERA de un día ("Sábado,
    # 9 de mayo" al principio de línea) y no una fecha cualquiera; hasta
    # entonces se deja el criterio antiguo, que peca de ruidoso pero no calla.
    dias_con_material = {d for d in fechas if any(_mencionado(d, p) for p in _planos)}
    dias_con_actos = {
        d.get("fecha") for d in programa_total if d.get("eventos")
    } & dias_con_material
    if dias_con_material:
        cobertura = len(dias_con_actos) / len(dias_con_material)
        fiesta["cobertura_dias"] = round(cobertura, 2)
        if cobertura < COBERTURA_DIAS_MINIMA:
            fiesta["programa_no_recuperado"] = True
            faltan = sorted(dias_con_material - dias_con_actos)
            logger.warning(
                f"  [ENRICHMENT/COBERTURA] '{nombre_fiesta}' de {localidad['nombre']}: "
                f"{len(dias_con_actos)} de {len(dias_con_material)} días del documento "
                f"({100 * cobertura:.0f}%). Sin actos: {faltan[:6]}. "
                f"El programa está en {url_programa[:60]} y no se ha recogido entero."
            )

    return fiesta


async def retrieve_discovery_context(
    indexed_chunks: list[dict],
    municipio: dict,
    localidad: dict,
    anno: int,
    rag_processor: AsyncRAGProcessor | None = None,
    max_chars: int = DISCOVERY_MAX_CHARS,
    nombres_hermanas: list[str] = None,
    system_prompt: str = "",
) -> tuple[str, set, int, list]:
    """
    Ordena TODO el material de la localidad y lo reparte en lotes.

    Devuelve `(contexto, fuentes, n_documentos_directos, lotes)`.

    `contexto` es ahora el pool ENTERO ensamblado, no un recorte. Lo consumen las
    anclas —`ajustar_fechas_con_anclas`, `recuperar_fiestas_desde_anclas` y
    `descartar_por_patron_ajeno`—, que son la red de seguridad que caza lo que el
    modelo se deja. Hasta ahora leían los mismos 20.000 caracteres que el
    discovery, o sea el 3,2% del material recopilado en Aranda de Duero: la pieza
    que existe para recuperar lo perdido era la que menos material tenía delante.
    No se traduce: las anclas leen expresiones de fecha, no prosa.

    `lotes` es ese mismo material repartido para preguntar. Nada se descarta.
    """
    if not indexed_chunks:
        return "", set(), 0, []

    perfil_data = perfil_de_lugar(municipio)
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

    # Fusión de señales acotada (similitud + ranking de la araña + programa +
    # coherencia temporal). Sustituye a los bonus sueltos que se sumaban sobre el
    # coseno y que hacían ganar a una tabla de presupuestos.
    puntuar_chunks(
        items_copy,
        query_emb=query_emb,
        anno=anno,
        coseno=AsyncRAGProcessor.cosine_similarity,
    )

    # El ajuste geográfico se sigue aplicando DESPUÉS del score, como hasta ahora.
    items_copy = filtrar_chunks_por_localidad(items_copy, localidad["nombre"], nombres_hermanas or [])

    umbral = umbral_adaptativo(items_copy)
    garantizados = chunks_garantizados(items_copy, anno=anno)

    # Además de las mejores páginas de la araña, se reservan plazas para los
    # chunks mejor PUNTUADOS, vengan de donde vengan. `seleccionar_chunks` ordena
    # las fuentes oficiales por delante de las de buscador y agota el presupuesto
    # antes de llegar a estas: medido el 2026-08-21, el PDF del cartel de Amurrio
    # era candidato en discovery y NO entraba, así que el modelo no llegaba a ver
    # que las fiestas son del 12 al 17 y las recortó a dos días. Es el mismo
    # arreglo que ya lleva el enrichment.
    mejores = sorted(items_copy, key=lambda i: -i.get("score", 0.0))[:DISCOVERY_TOP_GARANTIZADOS]
    ya = {id(i) for i in garantizados}
    garantizados = garantizados + [i for i in mejores if id(i) not in ya]

    # El reparto sustituye a `seleccionar_chunks`. El umbral se sigue calculando
    # —se vuelca, y sirve para ver si el orden es sano— pero ya no descarta a
    # nadie: lo que no cabe en un lote va en el siguiente.
    lote_tok = tokens_por_lote(system_prompt or _SYSTEM_DISCOVERY_TIPICO, RESERVA_SALIDA_DISCOVERY)
    lotes = repartir_en_lotes(
        items_copy, lote_tok, ensamblar_contexto, contar_tokens, fijos=garantizados,
    )
    seleccion = [i for lote in lotes for i in lote]

    contexto = ensamblar_contexto(seleccion)
    logger.info(
        f"  [REPARTO/discovery] {localidad['nombre']}: "
        f"{resumen_reparto(lotes, contar_tokens, ensamblar_contexto)}"
    )

    # Volcado de depuración: el contexto y la justificación de por qué es ese.
    volcar_contexto(
        etapa="discovery",
        localidad_nombre=localidad["nombre"],
        municipio_nombre=municipio.get("nombre", ""),
        contexto=contexto,
        candidatos=items_copy,
        seleccion=seleccion,
        contar_tokens=contar_tokens,
        presupuesto={
            # `presupuesto_chars` era el tope que recortaba; ya no recorta nada
            # y se deja solo por trazabilidad. Lo que dimensiona ahora es el lote.
            "presupuesto_chars_historico": max_chars,
            "lote_tokens": lote_tok,
            "query_embedding_ok": bool(query_emb),
            "umbral": umbral,
        },
        extra={"query_discovery": query_discovery},
        lotes=lotes,
    )

    fuentes_contexto = {i["fuente"] for i in seleccion}
    # Documentos DISTINTOS que nombran de verdad a esta localidad. Lo usa la
    # guarda anti-copia como prueba de que la fiesta existe en la aldea.
    #
    # Se excluye 'buscadores:snippets' a propósito: no es un documento, es un
    # único chunk que apelmaza una treintena de resultados de búsqueda, así que
    # basta con que UNO cualquiera mencione el pueblo para marcarlo DIRECTA
    # entero. Medido el 2026-08-21, con los snippets contando: Larrinbe tenía 5
    # chunks DIRECTA y los 5 eran ese bloque; Lekamaña 2, ambos el mismo bloque.
    # Todas las localidades pasaban el filtro y la guarda nunca llegó a evaluar
    # nada. Se cuentan URLs distintas, no chunks: cinco trozos del mismo
    # documento son una sola prueba.
    urls_directas = {
        i.get("url", "")
        for i in seleccion
        if i.get("relevancia_geo") == "DIRECTA"
        and i.get("url") != "buscadores:snippets"
        and i.get("url")
    }
    # La ficha del pueblo encabeza el contexto de discovery: el modelo decide
    # QUE fiestas existen, y sin saber a quien celebra este pueblo ni cuando,
    # no puede distinguir un programa de Cuaresma de unas patronales de agosto
    # —que es como Garrucha acabo con 'Fiestas Patronales de San Joaquin' del
    # 20 de febrero en la ejecucion del 2026-09-06—.
    #
    # Va DESPUES del reparto y descontando su tamano del presupuesto, no
    # sumandose por encima: `presupuesto_chars_historico` quedaria mintiendo y
    # este pipeline se mide por esa cifra.
    ficha = (localidad.get("ficha_pueblo") or "").strip()
    if ficha and contexto:
        contexto = ficha + "\n\n" + contexto[: max(0, len(contexto) - len(ficha) - 2)]
    return contexto, fuentes_contexto, len(urls_directas), lotes


def descartar_copias_de_la_capital(
    fiestas: list[dict],
    fiestas_capital: list[dict] | None,
    n_chunks_directa: int,
    localidad: dict,
    municipio: dict,
) -> list[dict]:
    """
    Retira las fiestas de una pedanía que son, en realidad, la de la capital.

    El prompt ya se lo pide al modelo, pero un 7B no siempre obedece y el daño de
    que falle creció mucho al mejorar la lectura de los carteles: antes copiaba
    tres líneas vagas, ahora copia noventa actos con hora exacta, que parecen
    ciertos. Medido el 2026-08-21: Larrinbe recibió "Fiestas Patronales de
    Amurrio" con 90 actos y Delika una con "Villa de Amurrio" dentro.

    El criterio es doble y exige AMBAS cosas para descartar:
      1. La fiesta coincide con una de la capital en nombre normalizado o en
         fechas solapadas.
      2. El contexto de esa pedanía no tenía NI UN chunk que la nombrase.

    Sin (2) no se descarta nada: dos pueblos del mismo valle celebran de verdad
    al mismo patrón las mismas fechas, y eso es legítimo. Lo que no lo es, es
    reproducir el programa de la capital sin una sola prueba de que la fiesta
    exista en la aldea.
    """
    if not fiestas or not fiestas_capital:
        return fiestas
    if localidad.get("es_capital"):
        return fiestas
    if n_chunks_directa >= ANTICOPIA_MIN_DOCS_DIRECTOS:
        return fiestas  # había evidencia propia suficiente: no es una copia a ciegas

    nombres_capital = {_normalizar_nombre(f.get("nombre", "")) for f in fiestas_capital}
    rangos_capital = []
    for f in fiestas_capital:
        ini = _parse_fecha_con_fallback_bisiesto(f.get("fecha_inicio"))
        fin = _parse_fecha_con_fallback_bisiesto(f.get("fecha_fin"))
        if ini and fin:
            rangos_capital.append((ini, fin))

    conservadas = []
    for f in fiestas:
        if f.get("origen") == "santo_patron":
            conservadas.append(f)
            continue

        nombre_norm = _normalizar_nombre(f.get("nombre", ""))
        mismo_nombre = nombre_norm in nombres_capital

        ini = _parse_fecha_con_fallback_bisiesto(f.get("fecha_inicio"))
        fin = _parse_fecha_con_fallback_bisiesto(f.get("fecha_fin"))
        solapa = bool(ini and fin and any(ini <= r_fin and r_ini <= fin
                                          for r_ini, r_fin in rangos_capital))

        if mismo_nombre or solapa:
            motivo = "mismo nombre que la de la capital" if mismo_nombre else "fechas solapadas con la de la capital"
            logger.warning(
                f"  [ANTI-COPIA] '{f.get('nombre')}' descartada para {localidad['nombre']}: "
                f"{motivo} y ningún chunk del contexto nombra a la localidad."
            )
            continue
        conservadas.append(f)

    return conservadas


def _palabras(texto: str) -> list[str]:
    """
    Palabras normalizadas para comparar texto literal, CIFRAS INCLUIDAS.

    No vale `_normalizar_nombre`: quita los dígitos, y el número es justo lo que
    delata la copia ("más de 100 actos en una semana").
    """
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def _tramo_verbatim_mas_largo(a: str, b: str) -> int:
    """Longitud, en palabras, del tramo contiguo más largo común a dos textos."""
    A, B = _palabras(a), _palabras(b)
    if not A or not B:
        return 0
    mejor = 0
    previa = [0] * (len(B) + 1)
    for i in range(1, len(A) + 1):
        actual = [0] * (len(B) + 1)
        for j in range(1, len(B) + 1):
            if A[i - 1] == B[j - 1]:
                actual[j] = previa[j - 1] + 1
                if actual[j] > mejor:
                    mejor = actual[j]
        previa = actual
    return mejor


def _rangos_de(fiestas: list[dict]) -> list[tuple]:
    """Rangos (inicio, fin) parseables de una lista de fiestas."""
    rangos = []
    for f in fiestas:
        ini = _parse_fecha_con_fallback_bisiesto(f.get("fecha_inicio"))
        fin = _parse_fecha_con_fallback_bisiesto(f.get("fecha_fin"))
        if ini and fin:
            rangos.append((ini, fin))
    return rangos


def _solapa_con(fiesta: dict, rangos: list[tuple]) -> bool:
    """¿Las fechas de la fiesta pisan alguno de los rangos dados?"""
    ini = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio"))
    fin = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_fin"))
    if not (ini and fin):
        return False
    return any(ini <= r_fin and r_ini <= fin for r_ini, r_fin in rangos)


def descartar_por_sede_ajena(
    fiestas: list[dict],
    localidad: dict,
    municipio: dict,
    nombres_hermanas: list[str] | None = None,
) -> list[dict]:
    """
    Retira las fiestas que el propio texto atribuye a OTRA localidad.

    `sede_segun_el_texto` ya se le pide al modelo en el prompt de discovery, y
    resulta que lo rellena bien incluso cuando se equivoca en todo lo demás:
    medido el 2026-08-21, Artomaña se llevó "Fiestas Patronales de Nuestra Señora
    y San Roke" con sede_segun_el_texto = "Amurrio". El dato estaba escrito en el
    JSON de salida y no lo miraba nadie.

    Solo se descarta cuando la sede es una localidad CONOCIDA del municipio
    (capital o hermana). Si nombra un barrio, una ermita o un sitio que no está
    en el padrón no hay forma de saber si es un error, y se conserva.

    Salvedad: si el nombre de la fiesta menciona a la localidad que se está
    procesando, se conserva aunque la sede diga otra cosa. Los portales de
    eventos titulan "Fiestas de Tertanga 2026 en Amurrio" y el modelo lee el
    municipio como sede; descartar ahí costaría la fiesta buena.
    """
    if not fiestas:
        return fiestas

    propio = _normalizar_nombre(localidad.get("nombre", ""))
    ajenas = {
        _normalizar_nombre(n)
        for n in ([municipio.get("nombre", "")] + list(nombres_hermanas or []))
        if _normalizar_nombre(n) and _normalizar_nombre(n) != propio
    }
    if not ajenas:
        return fiestas

    conservadas = []
    for f in fiestas:
        if f.get("origen") == "santo_patron":
            conservadas.append(f)
            continue

        sede = _normalizar_nombre(f.get("sede_segun_el_texto") or "")
        if sede in ajenas and propio not in _normalizar_nombre(f.get("nombre", "")):
            logger.warning(
                f"  [ANTI-COPIA/SEDE] '{f.get('nombre')}' descartada para "
                f"{localidad['nombre']}: el texto la atribuye a '{f.get('sede_segun_el_texto')}'."
            )
            continue
        conservadas.append(f)

    return conservadas



_MES_RE = r"(?:" + "|".join(_MES_A_NUMERO) + r")"

# Formas en que una fuente escribe el rango de fechas de unas fiestas.
_RANGOS_FECHA = [
    rf"del?\s+(\d{{1,2}})\s+(?:de\s+)?({_MES_RE})?\s*(?:al|a|hasta|-|—|–)\s+(?:el\s+)?(\d{{1,2}})\s+de\s+({_MES_RE})",
    rf"entre\s+el\s+(\d{{1,2}})\s+(?:de\s+({_MES_RE}))?\s*y\s+el\s+(\d{{1,2}})\s+de\s+({_MES_RE})",
    rf"\b(\d{{1,2}})\s+({_MES_RE})\.?\s*(?:-|—|–)\s*(\d{{1,2}})\s+({_MES_RE})\.?",
    rf"\b(?:el\s+)?(\d{{1,2}})\s+()y\s+(\d{{1,2}})\s+de\s+({_MES_RE})",
]


# Palabras que, junto a un rango de fechas, delatan que ese rango NO es el de la
# fiesta sino el de un trámite: plazos de inscripción, de presentación de obras,
# de votación. Medido el 2026-08-22, a Los Mardos se le asignaron once días sin
# un solo acto porque su contexto decía "Aquellos que se animen a participar
# deberán inscribirse del 20 al 30 de julio en la Casa de la Cultura".
_TRAMITE = re.compile(
    r"\binscri\w*|\bplazo\b|\bmatricul\w*|\bsolicitud\w*|\badmisi\w*|\bvotaci\w*"
    r"|\bpresentaci\w*\s+de\s+(?:obras|trabajos|proyectos|carteles|bocetos)"
    r"|\brecepci\w*\s+de\b|\bbases\b"
    # Comprar la entrada también es un trámite, y su ventana no son las fiestas.
    # Medido el 2026-09-03 sobre el PDF cristo26-1.pdf de Tobarra: «Venta de
    # tickets en Droguería Sila y Centro Médico Tobarra, del 24 de abril al 4 de
    # mayo» fabricó una ficha entera —"Fiestas de Tobarra", 24-abr a 4-may— que
    # además se llevó el mejor documento del municipio y salió con 0 actos,
    # mientras las fiestas de verdad (8-24 de mayo) se quedaban con el PDF peor.
    r"|\bventas?\b|\bcanje\w*|\babono\s+de\b"
    r"|\b(?:recogida|retirada|reserva|adquisici\w*|compra)\s+(?:anticipada\s+)?de\b",
    re.IGNORECASE,
)


def _es_rango_de_tramite(seg: str, ini: int, fin: int) -> bool:
    """
    ¿El rango habla de un trámite en vez de una fiesta?

    Solo se mira lo que va DELANTE del rango, que es donde cae el verbo del
    trámite: "deberán inscribirse del…", "el plazo va del…", "presentación de
    obras del…". Mirar también detrás tumbaba programas legítimos, porque un
    programa de fiestas menciona de pasada la inscripción a sus concursos:
    "las fiestas de Delika se celebran del 26 al 28 de junio. Inscripciones para
    el concurso de tortilla…" no deja de ser el rango de la fiesta.
    """
    return bool(_TRAMITE.search(seg[max(0, ini - 130):ini]))


# Un día seguido de una hora dentro de la misma línea o frase: "Viernes, 8 de
# mayo 10:00h. POSTULACIÓN". La ventana es corta a propósito —el título del acto
# va justo detrás de la hora, no a media página—.
_VENTANA_DIA_HORA = 120

# La hora TAL COMO LLEGA AQUÍ. `_plano()` deja el segmento en [a-z0-9 -], así
# que los dos puntos ya no existen: "10:00h." llega como "10 00h". Por eso este
# patrón no puede ser el de `senales_festivas`, que trabaja sobre texto crudo.
#
# Se exige la "h" final. Sin ella, "10 00" es indistinguible de dos números
# cualesquiera del texto aplanado, y un programa escrito "10:00" sin hache se
# queda fuera —falso negativo, que aquí solo significa no vetar nada—.
_RE_HORA_APLANADA = re.compile(r"\b(?:[01]?\d|2[0-3])\s+[0-5]\d\s*h\b")


def dias_con_acto_del_segmento(seg: str, anno: int) -> list[date]:
    """
    Días del segmento que llevan detrás un acto con hora, es decir: los días que
    este texto documenta como programa.

    `seg` es un segmento ya aplanado por `_plano()`; ver `_RE_HORA_APLANADA`.

    Se devuelven ordenados y sin repetir. Si el segmento no es un programa
    —ninguna fecha lleva hora— la lista sale vacía y nadie decide nada con ella.
    """
    dias: set[date] = set()
    for m in re.finditer(rf"\b(\d{{1,2}})\s+de\s+({_MES_RE})\b", seg):
        cola = seg[m.end():m.end() + _VENTANA_DIA_HORA]
        if not _RE_HORA_APLANADA.search(cola):
            continue
        mes = _MES_A_NUMERO.get(m.group(2))
        if not mes:
            continue
        try:
            dias.add(date(anno, mes, int(m.group(1))))
        except ValueError:
            continue
    return sorted(dias)


def rango_contradice_al_programa(seg: str, ini: date, fin: date, anno: int) -> bool:
    """
    ¿El rango candidato cae fuera de los días que el propio segmento programa?

    Cuando un texto ES un programa —varios días con sus actos y sus horas—, esos
    días son la fiesta. Un rango que no toca ninguno de ellos habla de otra cosa
    aunque esté en la misma página: una venta de entradas, una exposición previa,
    la fiesta del pueblo de al lado en el pie del artículo.

    Es la versión general del fallo que `_TRAMITE` ataca por vocabulario. En
    Tobarra el segmento programaba el 8 y el 9 de mayo con sus horas, y el rango
    que ganó la votación fue el 24-abr a 4-may de la venta de tickets: ningún
    día en común. Con esta regla no habría hecho falta conocer la palabra
    "venta" para descartarlo.

    Se exigen DOS días programados antes de decidir: con uno solo, un texto que
    menciona de pasada un acto con hora vetaría el rango bueno de su propia
    fiesta, que es exactamente el error contrario.
    """
    dias = dias_con_acto_del_segmento(seg, anno)
    if len(dias) < 2:
        return False
    return not any(ini <= d <= fin for d in dias)


_DIAS_SEMANA = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}
_ORDINALES = {
    "primer": 1, "primero": 1, "primera": 1, "1": 1, "1o": 1, "1er": 1, "1a": 1,
    "segundo": 2, "segunda": 2, "2": 2, "2o": 2, "2a": 2,
    "tercer": 3, "tercero": 3, "tercera": 3, "3": 3, "3o": 3, "3er": 3, "3a": 3,
    "cuarto": 4, "cuarta": 4, "4": 4, "4o": 4, "4a": 4,
    "quinto": 5, "quinta": 5, "5": 5, "5o": 5, "5a": 5,
    "ultimo": -1, "ultima": -1,
}
_ORD_RE = "|".join(sorted(_ORDINALES, key=len, reverse=True))
_DIA_RE = "|".join(_DIAS_SEMANA)

# "2.º, 3.º y 4.º domingo de mayo" — varios ordinales encadenados sobre el mismo
# día de la semana. Es como se anuncian las patronales de muchos pueblos.
_REL_VARIOS = re.compile(
    rf"\b((?:(?:{_ORD_RE})\s*(?:,|y|-)?\s*){{2,}})\s*(?:fin(?:es)?\s+de\s+semana|{_DIA_RE})s?\s+de\s+({_MES_RE})\b"
)
# "el primer domingo de agosto", "el último fin de semana de septiembre"
_REL_UNO = re.compile(
    rf"\b(?:el\s+|los\s+)?({_ORD_RE})\s+(?:fin(?:es)?\s+de\s+semana|({_DIA_RE}))s?\s+de\s+({_MES_RE})\b"
)
# "el domingo siguiente al 8 de septiembre", "el sábado anterior al 24 de junio"
_REL_RELATIVO_A_FECHA = re.compile(
    rf"\b({_DIA_RE})\s+(siguiente|posterior|anterior|previo)\s+al?\s+(\d{{1,2}})\s+de\s+({_MES_RE})\b"
)


def _nesimo_dia_semana(anno: int, mes: int, dia_semana: int, n: int) -> date | None:
    """Fecha del n-ésimo <día de la semana> del mes. n negativo cuenta desde el final."""
    try:
        primero = date(anno, mes, 1)
    except ValueError:
        return None
    dias = []
    d = primero
    while d.month == mes:
        if d.weekday() == dia_semana:
            dias.append(d)
        d += timedelta(days=1)
    if not dias:
        return None
    if n == -1:
        return dias[-1]
    return dias[n - 1] if 1 <= n <= len(dias) else None


def fechas_relativas(seg: str, anno: int) -> tuple[list[tuple], list[date]]:
    """
    Resuelve las fechas que el texto expresa como regla y no como número.

    Media España anuncia sus fiestas así y hasta ahora eran invisibles: ni el
    modelo las sacaba ni el anclaje las entendía. Medido el 2026-08-22, el
    contexto de Tobarra decía "Las Fiestas Patronales de Tobarra de mayo se
    celebran durante el 2.º, 3.º y 4.º domingo de mayo en honor al Santísimo
    Cristo de la Antigua y a la Virgen de la Encarnación, patronos de Tobarra",
    con nombre, patronos y fecha, y la ficha no salió.

    Devuelve (rangos, sueltas). Varios ordinales encadenados dan un rango del
    primero al último; uno solo da una fecha.
    """
    rangos, sueltas = [], []
    # El indicador ordinal "º" se descompone en "o" al normalizar (NFKD), así que
    # "el 2.º, 3.º y 4.º domingo" llega como "el 2 o 3 o y 4 o domingo". Se vuelve
    # a pegar al número; solo delante de un día de la semana, para no confundirlo
    # con la conjunción "o" de "el 2 o 3 de mayo".
    seg = re.sub(rf"\b(\d)\s+o\b(?=[\s,y-]*(?:\d|{_ORD_RE}|{_DIA_RE}))", r"\1o", seg)

    for m in _REL_VARIOS.finditer(seg):
        mes = _MES_A_NUMERO.get(m.group(2))
        dia_txt = re.search(_DIA_RE, m.group(0))
        if not mes or not dia_txt:
            continue          # "fines de semana" sin día concreto: demasiado vago
        dsem = _DIAS_SEMANA[dia_txt.group(0)]
        ns = [_ORDINALES[o] for o in re.findall(_ORD_RE, m.group(1))]
        fechas = [f for f in (_nesimo_dia_semana(anno, mes, dsem, n) for n in ns) if f]
        if len(fechas) >= 2:
            rangos.append((min(fechas), max(fechas)))

    for m in _REL_UNO.finditer(seg):
        if _REL_VARIOS.search(seg[max(0, m.start() - 30):m.end()]):
            continue          # ya lo ha cogido la forma encadenada
        mes = _MES_A_NUMERO.get(m.group(3))
        if not mes or not m.group(2):
            continue
        f = _nesimo_dia_semana(anno, mes, _DIAS_SEMANA[m.group(2)], _ORDINALES[m.group(1)])
        if f:
            sueltas.append(f)

    for m in _REL_RELATIVO_A_FECHA.finditer(seg):
        mes = _MES_A_NUMERO.get(m.group(4))
        if not mes:
            continue
        try:
            base = date(anno, mes, int(m.group(3)))
        except ValueError:
            continue
        objetivo = _DIAS_SEMANA[m.group(1)]
        if m.group(2) in ("anterior", "previo"):
            # Días hacia atrás hasta el día de la semana pedido, sin contar el
            # propio día base: "el sábado anterior al 24" nunca es el 24.
            sueltas.append(base - timedelta(days=(base.weekday() - objetivo) % 7 or 7))
        else:
            sueltas.append(base + timedelta(days=(objetivo - base.weekday()) % 7 or 7))

    return rangos, sueltas


# "Lugar: Galar" — el campo con el que los portales de eventos dicen dónde se
# celebra. Se exige que lo que sigue no empiece por preposición o artículo, para
# no confundir el campo con la prosa ("en el lugar de la ermita", "el lugar donde").
_CAMPO_LUGAR = re.compile(r"\blugar[:\s]+((?!(?:de|del|la|el|los|las|en|donde|que)\b)[a-z][a-z ]{2,24})")


_PALABRA_DE_FIESTA = re.compile(r"^(?:fiestas?|jaiak|patronales?|programa|feria|romeria|verbena|celebra\w*)$")


def _mencion_es_cola_de_otro_toponimo(seg: str, pos: int, loc: str) -> bool:
    """
    ¿El nombre del pueblo aparece solo como final de otro topónimo más largo?

    Los nombres genéricos lo sufren constantemente. Medido el 2026-08-23, a
    Sierra (pedanía de Tobarra, Albacete) se le asignó el programa de
    "Miraflores de la Sierra" (Madrid): "sierra" está ahí como palabra entera y
    con frontera, así que todas las comprobaciones normales la daban por buena.
    En la misma provincia está además "Elche de la Sierra".

    Lo que delata al compuesto es el ARTÍCULO: los topónimos españoles se forman
    con "de la", "del", "de los" —"Miraflores de la Sierra", "Elche de la
    Sierra"—, mientras que el "de" a secas introduce cualquier cosa. Sin exigir
    el artículo, "el ayuntamiento de Aranda de Duero" y "la localidad de Aranda
    de Duero" se tomaban por topónimos compuestos y Aranda se quedaba sin ancla:
    de sus cuatro menciones, las cuatro caían.

    Aun con artículo, si la palabra previa es de fiesta la mención vale: "las
    fiestas de la Aguilera" habla de La Aguilera, no de otro sitio.
    """
    m = re.search(r"(\w+)\s+(?:de\s+la|del|de\s+los|de\s+las)\s+$", seg[:pos])
    return bool(m) and not _PALABRA_DE_FIESTA.match(m.group(1))


def _evidencia_situa_la_fiesta_en_otro_sitio(
    evidencia: str, localidad: dict, municipio_nombre: str
) -> bool:
    """
    ¿La propia fuente dice que la fiesta se celebra en otra parte?

    Es el mismo razonamiento que `sede_segun_el_texto`, aplicado a la frase que
    ancla la fecha. Sirve contra los pueblos homónimos, que son un problema real:
    medido el 2026-08-23, a Cordovilla (Tobarra, Albacete) se le asignó el
    programa de Cordovilla de la Cendea de Galar (Navarra) porque el documento
    nombraba "Cordovilla" y el filtro de documentos ajenos lo daba por bueno. La
    ficha traía dentro "lugar galar 31".

    Solo se mira el campo "Lugar", que es explícito. Las reglas más amplias que
    probé —descartar por provincia distinta, o exigir que el documento nombre al
    municipio— se llevaban por delante las fuentes buenas: sobre los contextos
    reales tumbaban las páginas de enaranda.es que publican las fiestas de
    Sinovas y La Aguilera, y en Sierra 38 documentos de 102.
    """
    m = _CAMPO_LUGAR.search(evidencia or "")
    if not m:
        return False
    sitio = m.group(1).strip()
    propios = [_plano(localidad.get("nombre", "")).strip(), _plano(municipio_nombre or "").strip()]
    return not any(p and (p in sitio or sitio.startswith(p)) for p in propios)


def _cuenta_rangos(seg: str) -> int:
    """
    Cuántos rangos de fechas DISTINTOS enumera un segmento.

    Distintos, no repetidos: una página que dice tres veces "del 5 al 12 de mayo"
    está insistiendo en una fecha, no enumerando tres.
    """
    return len({m.groups() for pat in _RANGOS_FECHA for m in re.finditer(pat, seg)})


def _plano(texto: str) -> str:
    """Texto en minúsculas, sin acentos, conservando guiones (unen topónimos)."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("↵", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s\-—–]", " ", t))


# Armazón de los portales de eventos: cargadores y bloques de "más eventos".
# Llevan el nombre del pueblo y la palabra "fiestas" pegados a fechas que no son
# las de esta fiesta.
#
# La lista está medida, no imaginada, y hubo que estrecharla. La primera versión
# incluía también "proponer una correccion", "skip to content" y "añadir a
# calendario", que son botones de las fichas de evento LEGÍTIMAS: con ellos
# dentro, el 2026-08-27 se tiró el segmento bueno de La Aguilera —el que dice
# "del 13 al 17 de mayo"— y sus fiestas se quedaron en un solo día y sin
# programa, de 17 actos a 0. Sobre los siete contextos del run, la lista de
# abajo acierta las siete fechas y la ancha solo tres.
_RE_ARMAZON_DE_PORTAL = re.compile(
    r"command palette|cargando fiestas|"
    r"mas eventos en|mas fiestas y ferias|otros eventos|eventos relacionados|"
    r"eventos cercanos",
)


def anclas_de_fechas(
    contexto: str,
    localidad: dict,
    nombres_hermanas: list[str] | None,
    anno: int,
    municipio_nombre: str = "",
) -> list[dict]:
    """
    Saca del contexto los rangos de fechas que las fuentes atribuyen a ESTA
    localidad, ordenados por cuánto los respaldan.

    Existe porque el cuello de botella no está donde parecía. Medido el
    2026-08-22 sobre el run del día anterior: en Larrinbe, Delika y Lekamaña la
    fiesta buena estaba en el chunk MEJOR PUNTUADO del contexto —"Las fiestas de
    Delika 2026 se celebrarán del 26 al 28 de junio"— y el modelo de 7B devolvió
    igualmente la fiesta de la capital. La recuperación funciona; lo que falla es
    la lectura. Una frase así se lee con una expresión regular, sin modelo.

    El texto se parte en segmentos (cada resultado de buscador, cada página) y
    una fecha solo se atribuye a la localidad si ambas están en el MISMO
    segmento. Con ventanas de caracteres en vez de segmentos, la fecha de las
    fiestas de un pueblo se pegaba al titular del siguiente.

    El municipio NO cuenta como localidad rival: "fiestas de Tertanga 2026 en
    Amurrio" es la forma normal de escribirlo en los portales de eventos, y
    tratar "Amurrio" como competidor tumbaba justo las atribuciones correctas.
    """
    if not contexto:
        return []

    loc = re.escape(_plano(localidad.get("nombre", "")).strip())
    if not loc:
        return []
    hermanas = [
        re.escape(h) for h in
        (_plano(n).strip() for n in (nombres_hermanas or []))
        if h and h != _plano(localidad.get("nombre", "")).strip()
    ]

    votos: dict[tuple, int] = {}
    evidencias: dict[tuple, str] = {}
    # Las fechas sueltas se cuentan aparte y solo se usan si no hay ningún rango.
    # Son mucho más frecuentes en el texto que los rangos, así que como fuente
    # principal darían más ruido; como respaldo salvan a la localidad cuyo
    # portal de eventos no salió en los resultados de esta ejecución.
    votos_sueltas: dict[tuple, int] = {}
    evidencias_sueltas: dict[tuple, str] = {}

    for seg in re.split(r"(?=\btitulo\b)|---+|\n\n", _plano(contexto)):
        # Menciones de la localidad que NO son la cola de otro topónimo.
        pos_loc_validas = [
            m.start() for m in re.finditer(rf"\b{loc}\b", seg)
            if not _mencion_es_cola_de_otro_toponimo(seg, m.start(), loc)
        ]
        m_loc = pos_loc_validas[0] if pos_loc_validas else None
        if m_loc is None or not re.search(r"fiestas?|jaiak|celebrar|patronal|programa", seg):
            continue

        def _cerca_de_la_localidad(pos: int) -> bool:
            """
            ¿La fecha está lo bastante cerca de donde se nombra al pueblo?

            El segmento ya garantiza que las dos cosas salen de la misma página,
            pero una página entera es una unidad demasiado grande. Medido el
            2026-09-02: en el contexto de Mora de Santa Quiteria, el titular
            «Mora de Santa Quiteria se prepara para un gran fin de semana de
            fiestas en honor a su patrona» y la frase «El festival se celebrará
            del 10 al 12 de septiembre en la Casa de la Cultura… tres referentes
            de la narración y la literatura oral» están en el mismo segmento y a
            noventa líneas de distancia. De ahí salió una fiesta entera que no
            existe, con las fechas de un festival de narración oral de Tobarra,
            mientras el propio contexto decía que las de Mora «arrancarán el 22
            de mayo y se alargarán hasta el día 24».

            No se vuelve a las ventanas de caracteres sueltas —que pegaban la
            fecha de un pueblo al titular del siguiente—: esto se suma al
            segmento, no lo sustituye.
            """
            return any(abs(pos - p) <= ANCLA_MAX_CHARS_A_LA_LOCALIDAD
                       for p in pos_loc_validas)
        # La propia fuente puede estar situando la fiesta en otro pueblo del
        # mismo nombre. En España los homónimos son muchos.
        if _evidencia_situa_la_fiesta_en_otro_sitio(seg, localidad, municipio_nombre):
            continue
        # Ni en otro AÑO. Que el segmento no nombre el año se acepta —los
        # carteles suelen decir solo "del 14 al 21 de agosto"—, pero que nombre
        # años y ninguno sea el nuestro es la firma de un archivo viejo. Medido
        # el 2026-08-26: a Los Mardos se le fabricó una ficha de "Fiestas de San
        # Roque" del 14 al 21 de agosto de 2026 a partir de «caseta 2018 …
        # programa de fiestas de san roque 2017 del 14 al 21 de agosto».
        annos_citados = {int(a) for a in re.findall(r"\b(19\d\d|20\d\d)\b", seg)}
        if annos_citados and not (annos_citados & {anno, anno + 1}):
            continue
        # Ni del armazón de un portal de eventos. Las fechas que salen de ahí no
        # son las de esta fiesta: son las del bloque "más eventos" de al lado, o
        # ninguna. Medido el 2026-08-27, las dos fichas peores del run salieron
        # de aquí: Monte Costaján —un monte -- se llevó una fiesta entera de
        # «fiestas monte costajan 2026 fechas y guia … cargando fiestas command
        # palette search», y a Sinovas le cambiaron sus fiestas del 22-31 de
        # agosto por el «20 ago - 25 ago» de un listado de eventos vecinos.
        if _RE_ARMAZON_DE_PORTAL.search(seg):
            continue

        # Una hermana nombrada ANTES que nosotros indica que el segmento es suyo.
        # Salvo que venga pegada con guion: "Lezama-Lekamaña" es el nombre entero
        # de un concejo, no dos pueblos compitiendo.
        sin_compuestos = seg
        for h in hermanas:
            sin_compuestos = re.sub(rf"\b{h}\s*[-–]\s*{loc}\b|\b{loc}\s*[-–]\s*{h}\b", loc, sin_compuestos)
        pos_loc = (re.search(rf"\b{loc}\b", sin_compuestos) or m_loc).start()
        pos_hermanas = [
            m.start() for h in hermanas
            for m in [re.search(rf"\b{h}\b", sin_compuestos)] if m
        ]
        if pos_hermanas and min(pos_hermanas) < pos_loc:
            continue

        posesivo = bool(re.search(rf"fiestas?\s+(?:patronales\s+)?(?:de|en)\s+{loc}", seg))
        # Un segmento que habla de "fiestas patronales" pesa más que uno de
        # actividades sueltas. Sin esto, en Aranda empataban a 2 el rango bueno
        # —"fiestas patronales… del 11 al 20 de septiembre", que es el real— y
        # un "actividades de ocio alternativo" de julio, y ganaba julio por caer
        # antes en el calendario, que es un criterio sin ningún sentido.
        patronal = bool(re.search(r"\bpatronal(?:es)?\b", seg))
        # Un segmento que enumera muchos rangos es un listado de actividades, no
        # el anuncio de una fiesta. Medido el 2026-08-23: los siete anclajes que
        # coinciden con fechas verificadas en fuentes reales salen todos de
        # segmentos con UN solo rango, mientras que el de "actividades de ocio
        # alternativo" de Aranda traía cinco y le robaba el puesto a la fecha
        # buena por caer antes en el calendario.
        if _cuenta_rangos(seg) > ANCLA_MAX_RANGOS_POR_SEGMENTO:
            continue

        for patron_fecha in _RANGOS_FECHA:
            for m in re.finditer(patron_fecha, seg):
                if _es_rango_de_tramite(seg, m.start(), m.end()):
                    continue
                if not _cerca_de_la_localidad(m.start()):
                    continue
                d1, mes1, d2, mes2 = m.groups()
                mes_fin = _MES_A_NUMERO.get(mes2)
                mes_ini = _MES_A_NUMERO.get(mes1) if mes1 else mes_fin
                if not (mes_ini and mes_fin):
                    continue
                try:
                    ini = date(anno, mes_ini, int(d1))
                    fin = date(anno, mes_fin, int(d2))
                except ValueError:
                    continue
                if fin < ini:  # rango que cruza el fin de año
                    try:
                        fin = date(anno + 1, mes_fin, int(d2))
                    except ValueError:
                        continue
                if (fin - ini).days > ANCLA_MAX_DIAS:
                    continue
                # Si el segmento es un programa, sus días mandan sobre cualquier
                # rango suelto que aparezca dentro. Ver `rango_contradice_al_programa`.
                if rango_contradice_al_programa(seg, ini, fin, anno):
                    continue
                clave = (ini, fin)
                votos[clave] = votos.get(clave, 0) + (2 if posesivo else 1) + (1 if str(anno) in seg else 0) + (1 if patronal else 0)
                evidencias.setdefault(clave, seg.strip()[:ANCLA_EVIDENCIA_CHARS])

        # Fechas expresadas como regla ("2.º, 3.º y 4.º domingo de mayo"). Se
        # resuelven contra el calendario del año y entran como una más.
        rel_rangos, rel_sueltas = fechas_relativas(seg, anno)
        peso_seg = (2 if posesivo else 1) + (1 if str(anno) in seg else 0) + (1 if patronal else 0)
        for ini_r, fin_r in rel_rangos:
            if (fin_r - ini_r).days <= ANCLA_MAX_DIAS:
                votos[(ini_r, fin_r)] = votos.get((ini_r, fin_r), 0) + peso_seg
                evidencias.setdefault((ini_r, fin_r), seg.strip()[:ANCLA_EVIDENCIA_CHARS])
        for d_rel in rel_sueltas:
            votos_sueltas[(d_rel, d_rel)] = votos_sueltas.get((d_rel, d_rel), 0) + peso_seg
            evidencias_sueltas.setdefault((d_rel, d_rel), seg.strip()[:ANCLA_EVIDENCIA_CHARS])

        for m in re.finditer(rf"\b(?:el\s+)?(\d{{1,2}})\s+de\s+({_MES_RE})\b", seg):
            # Una fecha detrás de "del", "al", "hasta"… es un extremo de rango, no
            # una fecha suelta. Sin esto, "del 1 de junio al 30 de septiembre" —un
            # rango de temporada que los patrones de arriba descartan por largo—
            # se colaba partido en dos fechas sueltas.
            if re.search(r"\b(?:del|al|a|hasta|entre|y)\s+(?:el\s+)?$", seg[:m.start()]):
                continue
            if _es_rango_de_tramite(seg, m.start(), m.end()):
                continue
            if not _cerca_de_la_localidad(m.start()):
                continue
            mes = _MES_A_NUMERO.get(m.group(2))
            if not mes:
                continue
            try:
                d = date(anno, mes, int(m.group(1)))
            except ValueError:
                continue
            votos_sueltas[(d, d)] = votos_sueltas.get((d, d), 0) + (2 if posesivo else 1) + (1 if str(anno) in seg else 0) + (1 if patronal else 0)
            evidencias_sueltas.setdefault((d, d), seg.strip()[:ANCLA_EVIDENCIA_CHARS])

    if not votos:
        # Sin ningún rango: la fecha suelta mejor respaldada. Medido el
        # 2026-08-22, esto rescata a Saratxo ("Fiestas de Saratxo · 6 de
        # diciembre de 2026 · Duración 1 día") y a Lekamaña ("San Miguel en el
        # concejo de Lezama-Lekamaña … el 29 de septiembre"), que se quedaron sin
        # fiesta porque el portal que publicaba su rango no salió esa vez en los
        # resultados de búsqueda.
        votos, evidencias = votos_sueltas, evidencias_sueltas

    if not votos:
        return []

    orden = sorted(votos.items(), key=lambda kv: (-kv[1], kv[0][0]))
    # Las fuentes recortan el rango a los días grandes ("el 24 y 25 de julio"
    # cuando son del 24 al 26). Entre las que coinciden en el día de inicio se
    # toma la más larga: medido sobre Amurrio, arregla Larrinbe sin tocar el resto.
    ini_ganador = orden[0][0][0]
    fin_ganador = max(k[1] for k, _ in orden if k[0] == ini_ganador)
    principal = (ini_ganador, fin_ganador)

    salida = [{
        "inicio": principal[0], "fin": principal[1],
        "peso": max(v for k, v in orden if k[0] == ini_ganador),
        "evidencia": evidencias.get((ini_ganador, fin_ganador)) or evidencias[orden[0][0]],
    }]
    for k, v in orden:
        if k[0] != ini_ganador:
            salida.append({"inicio": k[0], "fin": k[1], "peso": v, "evidencia": evidencias[k]})
    return salida


_URL_FECHA = re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})(?:/|$|\?|#|-)")


def solo_chunks_de_la_localidad(
    items: list[dict],
    localidad: dict,
    nombres_hermanas: list[str] | None,
) -> list[dict]:
    """
    En el ENRICHMENT de una pedanía, solo valen los chunks que la nombran.

    El discovery necesita el contexto del municipio para situarse; el enrichment
    no. El enrichment pregunta "qué pasa cada día de ESTA fiesta", y un chunk
    marcado GENERAL —el que no nombra a la localidad— no puede contestar a eso:
    lo único que aporta son los actos de otro, casi siempre los de la capital,
    que es quien publica el cartel gordo.

    Medido el 2026-08-22, la correlación es exacta:
        Artomaña  10 de 10 chunks DIRECTA          -> programa propio y correcto
        Baranbio   5 de 8 GENERAL, 78% del texto   -> programa de la capital entero
        Tertanga   8 DIRECTA / 2 GENERAL           -> propio, con dos fugas

    Baranbio salió con "AUTOBUSES A SAN ROQUE", "SUBIDA DEL SANTO" y "ENTREGA DEL
    IGUARRAKO DE ORO" en unas fiestas de septiembre. Las guardas que comparan
    actos con la capital no lo atrapan del todo porque cada una extrajo el cartel
    en un idioma distinto y "SAN ROKERA AUTOBUSAK" no casa con su traducción.

    Si no queda ningún chunk propio, la fiesta se queda sin programa. Es la
    respuesta correcta: de esa localidad no hay programa publicado, y rellenarlo
    con el del pueblo grande es peor que dejarlo vacío.
    """
    if not nombres_hermanas or localidad.get("es_capital"):
        return items
    propios = [i for i in items if i.get("relevancia_geo") != "GENERAL"]
    # Se traza a DEBUG: esta función corre una vez por cada día que se consulta,
    # y en INFO llenaba el log con la misma línea veinte veces por fiesta.
    if len(propios) != len(items):
        logger.debug(
            f"    [ENRICH/GEO] {localidad['nombre']}: {len(items) - len(propios)} chunks "
            f"que no nombran a la localidad fuera del programa; quedan {len(propios)}."
        )
    return propios


def fecha_de_url(url: str) -> date | None:
    """
    Día concreto al que corresponde una página, si su URL lo lleva.

    Los gestores de contenido municipales publican una página por día
    (`/calendario/eventosdiarios/2026/8/14/`), y esa página es literalmente el
    programa de ese día. Saber a qué día pertenece cada una permite quedarse con
    las de la fiesta que se está enriqueciendo y tirar las demás.
    """
    m = _URL_FECHA.search(url or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def filtrar_chunks_por_dias_de_la_fiesta(
    items: list[dict],
    fecha_inicio: date | None,
    fecha_fin: date | None,
) -> tuple[list[dict], list[dict]]:
    """
    Aparta las páginas fechadas fuera de la fiesta y garantiza las de dentro.

    Devuelve (chunks_utiles, chunks_de_dias_de_la_fiesta).

    Medido el 2026-08-21 en el enrichment de Amurrio (fiestas del 12 al 17 de
    agosto): de las 31 páginas de calendario diario del pool entraban 12, y entre
    ellas las del 1, 8, 10, 11, 18, 22 y 23 de agosto —días que no son de la
    fiesta— mientras que la del 14, el Día de las Cuadrillas, se quedaba fuera
    por una milésima de score. De ahí salían a la vez las dos averías del
    programa: días con el contenido cambiado y solo 23 actos de más de cien.

    Estas páginas puntúan casi igual entre sí, porque todas dicen lo mismo salvo
    la lista de actos, y el orden entre ellas es puro ruido. La fecha de la URL
    no es ruido: o cae dentro de la fiesta o no.
    """
    if not (fecha_inicio and fecha_fin):
        return items, []

    fechados = [i for i in items if fecha_de_url(i.get("url", ""))]
    cascaron = _lineas_de_cascaron(fechados)

    utiles, del_rango = [], []
    for i in items:
        f = fecha_de_url(i.get("url", ""))
        if f is None:
            utiles.append(i)
            continue
        if not (fecha_inicio <= f <= fecha_fin):
            continue        # fechada en otro día: es de otra fiesta
        propio = _sin_cascaron(i, cascaron)
        if propio is None:
            continue        # la página no dice nada que no digan todas las demás
        utiles.append(propio)
        del_rango.append(propio)
    return utiles, del_rango


def _sin_cascaron(item: dict, cascaron: set) -> dict | None:
    """
    Deja de una página de calendario lo suyo y le quita el menú.

    Estas páginas son casi todas navegación. Medido el 2026-08-22 en Amurrio:
    57 líneas por página, de las que 55 son el mismo menú en las seis —el filtro
    de categorías, los doce meses, los años de 2024 a 2031— y solo dos son de la
    jornada: "16 DE AGOSTO, DOMINGO - SAN ROQUE" y su fecha.

    Recortarlas en vez de descartarlas importa, porque esas dos líneas son las
    que ponen bien el título de cada día. Lo que no puede pasar es que entren
    enteras: con la reserva de plaza que tenían, el contexto de enrichment
    empezaba con cinco mil caracteres de menú y el modelo devolvió como programa
    los seis titulares y nada más, 6 actos donde antes sacaba 25.
    """
    if not cascaron:
        return item
    lineas = [l for l in re.split(r"[\n\r↵⏎]", item.get("chunk", ""))
              if l.strip() and l.strip() not in cascaron]
    if not lineas:
        return None
    recortado = dict(item)
    recortado["chunk"] = "\n".join(lineas)
    return recortado


def _lineas_de(texto: str) -> set:
    """Líneas no vacías. Los volcados de depuración usan ⏎ (U+23CE) por salto."""
    return {l.strip() for l in re.split(r"[\n\r↵⏎]", texto or "") if l.strip()}


def _lineas_de_cascaron(chunks: list[dict]) -> set:
    """
    Líneas que repiten TODAS las páginas fechadas: el menú, no el programa.

    Los gestores municipales sirven el calendario por JavaScript, así que la
    araña se trae una página por día que solo contiene la navegación. Medido el
    2026-08-22 en Amurrio: 31 páginas `eventosdiarios`, las mismas diez líneas en
    las 31 —"Calendario / CAS / EUS / Inicio / Elija una categoría…"— y ni un
    solo acto. Ocupaban unos 26.000 caracteres del presupuesto de enrichment y
    encima mi propia reserva de plaza para los días de la fiesta se las
    garantizaba, desplazando al material que sí tenía el programa.

    Con menos de tres páginas no hay con qué comparar y no se descarta nada.
    """
    if len(chunks) < 3:
        return set()
    conjuntos = [_lineas_de(c["chunk"]) for c in chunks]
    return set.intersection(*conjuntos) if conjuntos else set()


def _es_patronal(fiesta: dict) -> bool:
    """¿La fiesta se presenta como LA fiesta patronal del pueblo?"""
    return bool(re.search(r"\bpatronal(?:es)?\b", fiesta.get("nombre", ""), re.IGNORECASE))


# Tratamientos y partículas que acompañan a una advocación sin identificarla:
# "San Roque" y "Roque" son el mismo santo, y "Virgen de las Viñas" y "Nuestra
# Señora de las Viñas" también. Se quitan como PALABRAS, no como prefijos: con
# un prefijo, "santisimo" perdía la "san" y dejaba "tisimo".
_PALABRAS_TRATAMIENTO = frozenset({
    "san", "santo", "santa", "santos", "santas", "santisimo", "santisima",
    "sto", "sta", "stmo", "stma", "sn", "s",
    "nuestra", "nuestro", "senora", "senor", "ntra", "ntro", "sra", "sro",
    "virgen", "cristo", "maria", "purisima", "inmaculada",
    "el", "la", "los", "las", "de", "del", "y", "e",
})


def _clave_advocacion(nombre: str) -> str:
    """
    Núcleo comparable de una advocación: sin tratamientos ni partículas.

    "Stmo. Cristo de la Antigua" y "Santísimo Cristo de la Antigua" tienen que
    dar lo mismo, porque son el mismo patrón escrito por dos fuentes distintas.
    """
    t = re.sub(r"[^a-z0-9\s]", " ", _plano(nombre))
    return " ".join(p for p in t.split() if p not in _PALABRAS_TRATAMIENTO)


def nombra_al_patron(nombre_fiesta: str, patron: dict | None) -> bool:
    """
    ¿El nombre de la fiesta nombra la advocación de ESTE patrón?

    Se compara por prefijo en las dos direcciones a propósito. Las fuentes
    truncan y alargan los nombres de los santos sin criterio: el 2026-08-26 el
    modelo guardó en caché "San Francisco" como patrón de Sierra a partir de una
    página que decía "San Francisco Javier", y con una comparación de igualdad
    esa fiesta —la buena— quedaba como si fuese la de otro pueblo.
    """
    if not patron or not patron.get("nombre"):
        return False
    clave_patron = _clave_advocacion(patron["nombre"])
    clave_fiesta = _clave_advocacion(re.sub(
        r"^fiestas?\s+(?:patronales\s+)?(?:mayores\s+)?(?:en\s+honor\s+(?:a|de)\s+|de\s+|a\s+)?",
        "", _plano(nombre_fiesta), flags=re.IGNORECASE,
    ))
    if not clave_patron or not clave_fiesta:
        return False
    # Palabras completas, no trozos: "antigua" no puede casar con "antiguano".
    p, f = clave_patron.split(), clave_fiesta.split()
    if not p or not f:
        return False
    corto = min(len(p), len(f))
    if p[:corto] == f[:corto]:
        return True
    # La advocación puede ir dentro de un nombre más largo: "Fiestas Patronales
    # de Sierra en honor a San Francisco Javier".
    return f" {clave_patron} " in f" {clave_fiesta} "


def es_la_fiesta_del_patron(fiesta: dict, patron: dict | None, dia_patron: date | None) -> bool:
    """
    ¿Esta ficha ES la fiesta patronal de la localidad, caiga cuando caiga?

    Tres señales, cualquiera vale:
      - cubre el día del santo en el calendario;
      - nombra su advocación;
      - se anuncia como "patronal" y el patrón es propio de la localidad, así
        que no hay otra patronal con la que confundirla.
    """
    if dia_patron and _solapa_con(fiesta, [(dia_patron, dia_patron)]):
        return True
    if nombra_al_patron(fiesta.get("nombre", ""), patron):
        return True
    return bool(patron) and patron.get("ambito") == "localidad" and _es_patronal(fiesta)


def _hay_atribucion_explicita(contexto: str, localidad: dict) -> bool:
    """
    ¿Dice el texto, en algún sitio, que hay fiestas EN ESTA localidad?

    No basta con que el nombre del pueblo aparezca cerca de la palabra "fiestas":
    en el contexto de cualquier pedanía sale el municipio entero, y ella misma
    sale en listas de concejos, en avisos de tráfico y en direcciones. Medido el
    2026-08-22 con una ventana de 60 caracteres, las 8 localidades daban True y
    la comprobación no servía para nada.

    Se exige la construcción locativa o posesiva completa —"fiestas de Saratxo",
    "fiestas en Delika", "Larrinbe celebra sus fiestas"—, que es la que de verdad
    dice que las fiestas se celebran ahí.
    """
    if not contexto:
        return False
    loc = re.escape(_normalizar_nombre(localidad.get("nombre", "")))
    if not loc:
        return False
    plano = _normalizar_nombre(contexto)
    return bool(
        # "(programa de) fiestas [patronales] de/en/del <localidad>"
        re.search(rf"\b(?:fiestas?|jaiak)\s+(?:patronales\s+)?(?:de|en|del)\s+(?:la\s+|el\s+)?{loc}\b", plano)
        # "<localidad> (Amurrio) celebra(rá) sus fiestas"
        or re.search(rf"\b{loc}\s+(?:\w+\s+){{0,2}}(?:celebra|celebrara|celebran)\b", plano)
    )


def descartar_por_patron_ajeno(
    fiestas: list[dict],
    patron: dict | None,
    localidad: dict,
    contexto: str = "",
    anno: int | None = None,
) -> list[dict]:
    """
    Regla del patrón: un pueblo tiene el patrón que tiene, y no cambia.

    De ahí se sigue que la fiesta que se anuncia como PATRONAL de un pueblo tiene
    que caer sobre el día de SU patrón. Si cae en otra fecha, será una fiesta de
    alguien —normalmente de la capital— pero no la patronal de este pueblo.

    Se aplica solo a las fiestas que se presentan como patronales. Un pueblo
    tiene un patrón pero puede celebrar varias fiestas al año (Baranbio tiene el
    Día de la cabra y Garrastatxu además de la patronal), y esas no compiten con
    el patrón ni tienen por qué caer en su día.

    Dos regímenes, según de dónde salga el patrón:

    - Patrón PROPIO (`ambito == "localidad"`, sacado de una fuente que trata de
      este pueblo): vale cualquiera de estas tres cosas —caer en el día del
      santo, nombrar su advocación, o que el texto sitúe las fiestas aquí—. NO
      se exige la coincidencia de fechas: un pueblo traslada sus patronales al
      verano y las sigue llamando patronales, así que exigirla descartaba las
      fiestas buenas (ver el comentario en el cuerpo). Lo que queda vetado es la
      patronal de OTRA advocación que nadie sitúa en este pueblo, que es la
      forma que tiene de colarse la fiesta de la capital.

    - Patrón HEREDADO del municipio: no se sabe cuál es el patrón del pueblo, así
      que la coincidencia de fechas no demuestra nada — de hecho es sospechosa,
      porque significa que la pedanía celebra exactamente cuando la capital. Ahí
      solo vale que el texto diga explícitamente que esas fiestas son de esta
      localidad, o que la localidad SEA la capital.

    Las fiestas estimadas a partir del santo (`origen == "santo_patron"`) se
    dejan pasar: son otro asunto y se tratan aparte.
    """
    if not fiestas or not patron:
        return fiestas

    dia, mes = patron.get("dia"), patron.get("mes")
    if not (dia and mes):
        return fiestas  # sin fecha del patrón no hay nada que comparar

    anno = anno or _anno_de(fiestas)
    if not anno:
        return fiestas
    try:
        dia_patron = date(anno, mes, dia)
    except ValueError:
        return fiestas

    propio = patron.get("ambito") == "localidad"
    es_capital = bool(localidad.get("es_capital"))

    conservadas = []
    for f in fiestas:
        if f.get("origen") == "santo_patron" or not _es_patronal(f):
            conservadas.append(f)
            continue

        cubre_patron = _solapa_con(f, [(dia_patron, dia_patron)])

        if propio:
            if cubre_patron:
                conservadas.append(f)
                continue
            # El día del santo NO es la fecha de la fiesta. Media España traslada
            # sus patronales al verano o al fin de semana grande y las sigue
            # llamando patronales: Tobarra celebra al Stmo. Cristo de la Antigua
            # —14 de septiembre en el santoral— del 9 al 17 de agosto, y hace
            # además su bajada en mayo. El 2026-08-26 esta regla, exigiendo la
            # coincidencia, le tiró las dos fiestas buenas y dejó al pueblo con
            # un rescate degradado; a Sierra le tiró la suya y le dejó una ficha
            # vacía de septiembre. Lo que de verdad delata una copia no es que la
            # fecha se mueva, sino que la fiesta se anuncie bajo OTRA advocación
            # o que nadie la sitúe en este pueblo.
            if (es_capital
                    or nombra_al_patron(f.get("nombre", ""), patron)
                    or _hay_atribucion_explicita(contexto, localidad)):
                if not cubre_patron:
                    f["patron_trasladado"] = True
                conservadas.append(f)
                continue
            logger.warning(
                f"  [ANTI-COPIA/PATRÓN] '{f.get('nombre')}' descartada para "
                f"{localidad['nombre']}: se anuncia como patronal del "
                f"{f.get('fecha_inicio')} al {f.get('fecha_fin')}, no cae en el día de "
                f"{patron['nombre']} ({dia_patron.isoformat()}), no nombra esa advocación "
                f"y ningún texto sitúa esas fiestas en {localidad['nombre']}."
            )
            continue

        # Patrón heredado: la coincidencia con su día no avala nada.
        if es_capital or _hay_atribucion_explicita(contexto, localidad):
            conservadas.append(f)
            continue
        logger.warning(
            f"  [ANTI-COPIA/PATRÓN] '{f.get('nombre')}' descartada para "
            f"{localidad['nombre']}: se anuncia como patronal, pero el patrón "
            f"({patron['nombre']}) está heredado del municipio y ningún texto dice "
            f"que estas fiestas se celebren en {localidad['nombre']}."
        )

    return conservadas


def _nombre_desde_evidencia(evidencia: str, localidad: dict, patron: dict | None = None) -> str:
    """
    Nombre de la fiesta rescatada, a partir del texto que la anuncia.

    Se busca el santo en la propia frase; si no aparece, se usa el del patrón,
    que para entonces ya viene limpio del santoral. Solo cuando no hay ninguno de
    los dos se cae en "Fiestas de <pueblo>".

    Los santos de una sola palabra hay que nombrarlos aparte: "Santiago" no es
    "san" + algo, y por eso Larrinbe salió como "Fiestas de Larrinbe" teniendo
    "fiestas de santiago 2026 en larrinbe" escrito en su propia evidencia.
    """
    # El complemento del santo puede tener hasta cuatro palabras, pero ninguna de
    # ellas puede ser un verbo ni un conector que arranque la frase siguiente:
    # sin esto Artomaña salía como "Fiestas de San Jorge Que Se Celebraran".
    resto = (r"(?:\s+(?!que|se|con|para|durante|desde|hasta|es|son|sera|seran|"
             r"celebra\w*|tendra\w*|tienen|contenido|titulo)[a-z]+){1,4}")
    advocacion = (
        r"(?:santisim[oa]\s+)?(?:san|santa|santo|cristo|virgen|ntra|nuestra\s+se[nñ]ora|andra)"
        + resto +
        r"|santiago|corpus|carmen|asuncion|candelaria|rosario|pilar"
    )
    # "en honor al Santísimo Cristo de la Antigua" es la forma más fiable y puede
    # ir lejos de la palabra "fiestas", así que se busca por su cuenta.
    m = (re.search(rf"en\s+honor\s+a(?:l|\s+la|\s+los)?\s+({advocacion})", evidencia)
         or re.search(rf"fiestas?\s+(?:patronales\s+)?(?:de|en)\s+({advocacion})", evidencia))
    if m:
        return f"Fiestas de {_titular(m.group(1))}"
    if patron and patron.get("nombre"):
        return f"Fiestas de {patron['nombre']}"
    return f"Fiestas de {localidad.get('nombre', '')}".strip()


_MINUSCULAS = {"de", "del", "la", "las", "los", "el", "y", "en", "a"}


def _titular(texto: str) -> str:
    """
    Capitaliza un nombre de advocación dejando en minúscula las partículas.

    Recorta antes las que quedan colgando al final: la expresión captura hasta
    cuatro palabras y se lleva el conector que enlaza con lo siguiente
    ("...Cristo de la Antigua y", "...Virgen de las Viñas de").
    """
    palabras = texto.strip().split()
    while palabras and palabras[-1] in _MINUSCULAS:
        palabras.pop()
    # "San Isidro Labrador y Ntra": el tope de palabras cortó la segunda
    # advocación por la mitad. Mejor quedarse con la primera entera.
    if len(palabras) >= 2 and palabras[-2] == "y" and (
        len(palabras[-1]) <= 4 or palabras[-1] in {"ntra", "ntro", "sta", "sto", "stma"}
    ):
        palabras = palabras[:-2]
    return " ".join(
        p if i and p in _MINUSCULAS else p.capitalize() for i, p in enumerate(palabras)
    )


def _dia_y_mes(d: date) -> str:
    """«22 de agosto», para redactar descripciones."""
    return f"{d.day} de {_NOMBRE_MES[d.month]}"


def descripcion_desde_ancla(a: dict, localidad: dict, nombre: str) -> str:
    """
    Descripción legible de una fiesta rescatada del contexto.

    Antes se metía la evidencia en bruto y salía a la base de datos tal cual:
    «titulo sinovas se viste de fiesta diez dias para honrar a san bartolome con
    contenido el barrio desinovas en aranda de duero acogera del 22 al 31…»,
    con los andamios del scraper ("titulo", "con contenido") y las palabras
    pegadas que deja el HTML sin espacios. La evidencia no se pierde: se guarda
    aparte, en su propio campo, que es donde sirve para depurar.
    """
    ini, fin = a["inicio"], a["fin"]
    if ini == fin:
        cuando = f"el {_dia_y_mes(ini)}"
    elif ini.month == fin.month:
        cuando = f"del {ini.day} al {_dia_y_mes(fin)}"
    else:
        cuando = f"del {_dia_y_mes(ini)} al {_dia_y_mes(fin)}"
    return (f"{nombre} en {localidad.get('nombre', '')}, {cuando} de {ini.year}. "
            f"Fechas recuperadas del texto que las anuncia; sin descripción publicada.")


# "con motivo del festival Sonorama Ribera", "durante el Festival de Cine…":
# las fechas son de un evento con nombre propio, no de las fiestas del pueblo.
_RE_EVENTO_CON_NOMBRE = re.compile(
    r"\b(?:festival|certamen|congreso|feria del|maraton|carrera|torneo|"
    r"campeonato|mercado medieval|concurso)\b",
)


def ancla_es_de_otro_evento(a: dict, localidad: dict, nombre: str) -> bool:
    """
    ¿Las fechas del anclaje son de un evento con nombre propio, y no de las
    fiestas de este pueblo?

    Solo se rechaza cuando además NO se ha podido sacar un santo del texto, es
    decir cuando la ficha iba a llamarse "Fiestas de <pueblo>" a secas. Medido
    el 2026-08-27: Aranda de Duero salió con unas "Fiestas de Aranda de Duero"
    del 5 al 9 de agosto que eran, literalmente, «con motivo de la celebración
    del festival Sonorama Ribera que tendrá lugar del 5 al 9 de agosto». Un
    festival de música con nombre propio no son las fiestas del pueblo, y
    ponerle el nombre del pueblo lo afirma.
    """
    generico = _normalizar_nombre(nombre) == _normalizar_nombre(
        f"Fiestas de {localidad.get('nombre', '')}")
    return generico and bool(_RE_EVENTO_CON_NOMBRE.search(a.get("evidencia", "")))


def _ficha_desde_ancla(a: dict, localidad: dict, patron: dict | None) -> dict:
    """
    Construye la ficha de una fiesta a partir de un anclaje del contexto.

    El patrón solo da nombre a la fiesta si su día cae DENTRO de ella. Delika
    tiene por patrona a la Virgen de la Antigua, del valle de Arrastaria y sin
    fecha fija, y sus fiestas de junio salieron llamándose "Fiestas de Virgen de
    la Antigua", que no las llama así nadie.
    """
    patron_del_rango = None
    if patron and patron.get("dia") and patron.get("mes"):
        try:
            d = date(a["inicio"].year, patron["mes"], patron["dia"])
        except ValueError:
            d = None
        if d and a["inicio"] <= d <= a["fin"]:
            patron_del_rango = patron
    nombre = _nombre_desde_evidencia(a["evidencia"], localidad, patron_del_rango)
    return {
        "id": f"ancla-{_normalizar_nombre(nombre).replace(' ', '-')}-{localidad['id']}",
        "lugar_id": localidad["id"],
        "nombre": nombre,
        "fecha_inicio": a["inicio"].isoformat(),
        "fecha_fin": a["fin"].isoformat(),
        "tamano": "pequeña",
        "descripcion": descripcion_desde_ancla(a, localidad, nombre),
        "evidencia": a["evidencia"][:ANCLA_EVIDENCIA_CHARS],
        "confianza": "media",
        "fuentes": ["busqueda_web"],
        "sede_segun_el_texto": localidad.get("nombre", ""),
        "solo_fuentes_no_oficiales": True,
        "programa": [],
        "origen": "ancla_contexto",
    }


def _anclas_en_fechas_libres(
    anclas: list[dict],
    fiestas: list[dict],
    localidad: dict,
    nombres_hermanas: list[str] | None,
    anno: int,
    patron: dict | None,
    descartadas: list[dict] | None = None,
) -> list[dict]:
    """
    Fiestas que el contexto anuncia en fechas donde no hay ninguna ficha todavía.

    Se exige más respaldo que para el rescate a secas: aquí no estamos supliendo
    un vacío, estamos añadiendo sobre lo que el modelo ya dio, y equivocarse
    cuesta una ficha inventada en vez de una casilla vacía.

    Y se respeta lo que las guardas hayan descartado. Sin esto, lo que una tira
    por la puerta lo devuelve la otra por la ventana: medido el 2026-08-23, la
    regla del patrón descartó en Cordovilla unas "Fiestas Patronales de San Cosme
    y San Damián" del 5 al 14 de septiembre —el patrón de Cordovilla es San Diego
    de Alcalá— y el rescate volvió a emitir ese mismo rango acto seguido.
    """
    rangos = _rangos_de(fiestas) + _rangos_de(descartadas or [])
    nuevas = []
    for a in anclas:
        if a["peso"] < ANCLA_PESO_MINIMO_EXTRA:
            continue
        # No basta con que no se solapen: dos fiestas pegadas del mismo pueblo
        # son casi siempre la misma con fuentes que discrepan. Medido el
        # 2026-08-23, a La Aguilera se le añadió "del 5 al 12 de mayo" junto a la
        # que ya tenía del 13 al 17, y el deduplicador interno vio después que
        # compartían el 88% de los actos.
        margen = timedelta(days=ANCLA_DIAS_DE_SEPARACION)
        if any(a["inicio"] - margen <= r_fin and r_ini <= a["fin"] + margen
               for r_ini, r_fin in rangos):
            continue
        if len(nuevas) >= ANCLA_MAX_FIESTAS_EXTRA:
            break
        ficha = _ficha_desde_ancla(a, localidad, patron)
        if ancla_es_de_otro_evento(a, localidad, ficha["nombre"]):
            logger.info(
                f"  [RESCATE/EXTRA] {localidad['nombre']}: descartado el anclaje "
                f"{a['inicio']} → {a['fin']}; sus fechas son de un evento con nombre "
                f"propio, no de las fiestas del pueblo. Ev.: «{a['evidencia'][:90]}»"
            )
            continue
        rangos.append((a["inicio"], a["fin"]))
        nuevas.append(ficha)
        logger.warning(
            f"  [RESCATE/EXTRA] {localidad['nombre']}: el contexto anuncia "
            f"'{ficha['nombre']}' {a['inicio']} → {a['fin']} (respaldo {a['peso']}) y no "
            f"había ninguna ficha en esas fechas. Ev.: «{a['evidencia'][:100]}»"
        )
    return nuevas


def recuperar_fiestas_desde_anclas(
    fiestas: list[dict],
    contexto: str,
    localidad: dict,
    nombres_hermanas: list[str] | None,
    anno: int,
    patron: dict | None = None,
    descartadas: list[dict] | None = None,
    municipio_nombre: str = "",
) -> list[dict]:
    """
    Cuando una localidad se queda sin ninguna fiesta, la rescata del contexto.

    Es el otro lado de las guardas anti-copia. Descartar la fiesta de la capital
    mal atribuida deja al pueblo a cero, y a cero se queda aunque su fiesta
    estuviera escrita con todas las letras en el contexto: medido el 2026-08-21,
    Delika acabó sin ninguna fiesta teniendo "Las fiestas de Delika 2026 se
    celebrarán del 26 al 28 de junio" en el primer chunk de su propio contexto.

    Hace dos cosas, y la segunda importa tanto como la primera:

    1. Si no queda NINGUNA fiesta, rescata la mejor ancla. No compite con el
       modelo: lo sustituye cuando el modelo no ha dado nada.

    2. Si quedan fiestas pero el contexto anuncia otra en fechas donde no hay
       nada, la añade. Un pueblo celebra varias veces al año y el modelo suele
       quedarse con una. Medido el 2026-08-22, Tobarra salía con San Antón y San
       Roque y se dejaba sus patronales de verdad —las del Cristo de la Antigua
       y la Virgen de la Encarnación, en mayo—, que estaban en su contexto con
       nombre, patronos y fecha. Sobre las 21 localidades medidas esta regla
       añade exactamente esa: no es una puerta abierta, es un hueco concreto.
    """
    anclas = anclas_de_fechas(contexto, localidad, nombres_hermanas, anno, municipio_nombre)
    if not anclas:
        return fiestas

    hay_extraidas = any(f.get("origen") != "santo_patron" for f in fiestas)
    if hay_extraidas:
        return fiestas + _anclas_en_fechas_libres(
            anclas, fiestas, localidad, nombres_hermanas, anno, patron, descartadas
        )

    if anclas[0]["peso"] < ANCLA_PESO_MINIMO:
        return fiestas

    a = anclas[0]
    # El nombre y la descripción salen de `_ficha_desde_ancla`, la misma que usa
    # el rescate por fechas libres: son la misma clase de ficha y antes se
    # construían dos veces, con la descripción divergiendo entre las dos copias.
    ficha = _ficha_desde_ancla(a, localidad, patron)
    logger.warning(
        f"  [RESCATE] {localidad['nombre']} se quedaba sin fiestas: se recupera "
        f"'{ficha['nombre']}' {a['inicio']} → {a['fin']} (respaldo {a['peso']}) de una "
        f"frase del contexto. Ev.: «{a['evidencia'][:110]}»"
    )
    return fiestas + [ficha]


def _dia_del_santo_de_la_fiesta(
    fiesta: dict, anno: int, dia_patron: date | None, nombre_patron: str = "",
) -> tuple[date | None, str]:
    """
    Día del santo que sostiene esta fiesta: el del patrón del pueblo si se
    conoce, y si no el del santo que la fiesta lleva en el nombre.

    El segundo camino hace falta más de lo que parece. En Tobarra el patrón que
    trae Wikipedia es el Cristo de la Antigua, que es una advocación sin fecha
    fija en el santoral, así que `dia_patron` viene vacío y con él no se puede
    proteger nada; pero su fiesta de agosto se llama "Fiestas Patronales de San
    Roque" y San Roque sí está en el santoral, el 16. Ese 16 de agosto es tan
    ancla como el del patrón registrado, y sin él el caso de Tobarra se queda
    fuera de la guarda.
    """
    if dia_patron:
        return dia_patron, nombre_patron or "el patrón"
    nombre = (fiesta.get("nombre") or "").strip()
    if not nombre:
        return None, ""
    dm = buscar_en_santoral(nombre)
    if not dm:
        return None, ""
    try:
        return date(anno, dm[1], dm[0]), clave_en_santoral(nombre) or nombre
    except ValueError:
        return None, ""


def _anotar_ancla_propuesta(fiesta: dict, a: dict) -> None:
    """
    Guarda en la ficha el rango que proponía el contexto, sin aplicarlo.

    Cuando una guarda frena al anclaje, la frase que lo respaldaba sigue siendo
    información: dice que alguien publicó esas fechas. Tirarla obliga a volver al
    log para saber por qué una ficha tiene el rango que tiene. Se anota la
    primera propuesta frenada, que es la de más respaldo —los anclajes llegan
    ordenados—, junto con su evidencia.
    """
    if fiesta.get("ancla_propuesta"):
        return
    fiesta["ancla_propuesta"] = {
        "fecha_inicio": a["inicio"].isoformat(),
        "fecha_fin": a["fin"].isoformat(),
        "peso": a["peso"],
        "evidencia": (a.get("evidencia") or "")[:ANCLA_EVIDENCIA_CHARS],
    }


def ajustar_fechas_con_anclas(
    fiestas: list[dict],
    contexto: str,
    localidad: dict,
    nombres_hermanas: list[str] | None,
    anno: int,
    patron: dict | None = None,
    municipio_nombre: str = "",
) -> list[dict]:
    """
    Afina las fechas del modelo con la frase del contexto que las anuncia.

    Solo corrige cuando el anclaje SOLAPA con lo que dijo el modelo: entonces no
    se está sustituyendo una fiesta por otra, sino ajustando dónde empieza y
    dónde acaba la misma. Un anclaje que cae en otras fechas se ignora, porque
    ahí no hay forma de saber cuál de las dos es y el modelo tuvo delante más
    texto que una frase.

    Dos frenos, los dos puestos después de que esto estropeara fechas correctas:

    - Respaldo mínimo (ANCLA_PESO_MINIMO_CORRECCION). Una mención suelta no basta
      para enmendar al modelo, que ha leído el contexto entero.

    - El día del patrón. Si la fiesta que dio el modelo cae sobre el día del
      patrón y la del anclaje no, manda el modelo. Medido el 2026-08-22 en
      La Aguilera: el modelo dijo del 12 al 17 de mayo, que incluye el 13, día de
      San Pedro Regalado —el santo del pueblo, que murió allí—, y el anclaje lo
      movió a 5-12, dejándolo fuera. Una patronal no se celebra sin su santo.
    """
    if not fiestas or not contexto:
        return fiestas

    dia_patron = None
    if patron and patron.get("dia") and patron.get("mes"):
        try:
            dia_patron = date(anno, patron["mes"], patron["dia"])
        except ValueError:
            dia_patron = None
    nombre_patron = (patron or {}).get("nombre") or ""

    anclas = [a for a in anclas_de_fechas(contexto, localidad, nombres_hermanas, anno, municipio_nombre)
              if a["peso"] >= ANCLA_PESO_MINIMO_CORRECCION]
    if not anclas:
        return fiestas

    for f in fiestas:
        if f.get("origen") in ("santo_patron", "ancla_contexto"):
            continue
        ini = _parse_fecha_con_fallback_bisiesto(f.get("fecha_inicio"))
        fin = _parse_fecha_con_fallback_bisiesto(f.get("fecha_fin"))
        if not (ini and fin):
            continue
        dia_santo, nombre_santo = _dia_del_santo_de_la_fiesta(f, anno, dia_patron, nombre_patron)
        for a in anclas:
            if a["inicio"] > fin or ini > a["fin"]:
                continue  # no solapan: hablan de fiestas distintas
            if (a["inicio"], a["fin"]) == (ini, fin):
                break
            dias_modelo = (fin - ini).days + 1
            dias_ancla = (a["fin"] - a["inicio"]).days + 1

            # Guarda 1: un anclaje no convierte una fiesta de varios días en una
            # de un día. Afinar dónde empieza y acaba una fiesta es una cosa;
            # decir que dura un día lo que el modelo leyó como diez es otra.
            #
            # Medido el 2026-09-02 sobre las dos ejecuciones completas: los dos
            # colapsos a un día son los peores daños del pipeline. Aranda de
            # Duero, cuyas fiestas mayores son del 11 al 20 de septiembre —el
            # ayuntamiento lo repite seis veces en el propio contexto—, salió
            # durando el 15 y sin programa; Los Mardos, del 16 al 19 de julio
            # según su programa oficial, salió durando el 19. En las dos el
            # modelo había dado el rango correcto.
            if dias_modelo > 1 and dias_ancla < ANCLA_MIN_DIAS_TRAS_RECORTE:
                _anotar_ancla_propuesta(f, a)
                logger.info(
                    f"  [ANCLA] '{f.get('nombre')}' de {localidad['nombre']}: se conservan "
                    f"{f['fecha_inicio']}→{f['fecha_fin']}; el contexto proponía "
                    f"{a['inicio']}→{a['fin']}, que dejaría la fiesta en un solo día. "
                    f"Anotado como propuesta."
                )
                break

            # Guarda 2: si las fechas del modelo ya cubren el día del santo, el
            # rango es coherente y no lo mueve una frase del contexto —ni
            # saliéndose de él ni recortándolo—.
            #
            # Medido el 2026-08-23, al subir el techo de descarga: en Tobarra
            # entraron más copias de "las fiestas patronales de verano se
            # celebran del 9 al 17 de agosto en La Caseta" —que es la temporada
            # de conciertos, no San Roque— y con ese respaldo el anclaje movió
            # San Roque del 14-21, que es su fecha real, al 9-17.
            #
            # Hasta el 2026-09-02 esta guarda tenía una excepción: si el anclaje
            # caía DENTRO del rango del modelo se dejaba pasar, porque en Aloria
            # recortaba 28-30 a 29-30 y acertaba. La excepción costaba más de lo
            # que daba. Por ella pasaron el recorte de San Roque de Tobarra en la
            # ejecución del 27B (08-08→08-22, que contiene el 16 de agosto,
            # recortado a 08-09→08-17: se perdieron los cuatro últimos días,
            # incluido el castillo de fin de fiestas) y el de La Aguilera en las
            # dos ejecuciones (12-17 de mayo, que contiene el 13, día de San
            # Pedro Regalado, recortado a 13-17). La precisión que daba en Aloria
            # la recupera ahora `recortar_rango_al_programa`, que recorta con los
            # días que de verdad tienen actos en vez de con una frase.
            if dia_santo and ini <= dia_santo <= fin:
                _anotar_ancla_propuesta(f, a)
                logger.info(
                    f"  [ANCLA] '{f.get('nombre')}' de {localidad['nombre']}: se conservan "
                    f"{f['fecha_inicio']}→{f['fecha_fin']}, que ya cubren el día de "
                    f"{nombre_santo} ({dia_santo}); el contexto proponía "
                    f"{a['inicio']}→{a['fin']}. Anotado como propuesta."
                )
                break
            logger.info(
                f"  [ANCLA] '{f.get('nombre')}' de {localidad['nombre']}: "
                f"{f['fecha_inicio']}→{f['fecha_fin']} ajustada a "
                f"{a['inicio']}→{a['fin']} (respaldo {a['peso']} en el texto)."
            )
            f["fecha_inicio"] = a["inicio"].isoformat()
            f["fecha_fin"] = a["fin"].isoformat()
            break
    return fiestas


def _anno_de(fiestas: list[dict]) -> int | None:
    """Año de trabajo, deducido de las fechas de las fiestas."""
    for f in fiestas:
        d = _parse_fecha_con_fallback_bisiesto(f.get("fecha_inicio"))
        if d:
            return d.year
    return None


def descartar_descripciones_copiadas(
    fiestas: list[dict],
    fiestas_capital: list[dict] | None,
    localidad: dict,
) -> list[dict]:
    """
    Retira las fiestas cuya DESCRIPCIÓN está calcada de la de la capital.

    Las otras dos guardas comparan programas, y eso se viene abajo cuando la
    capital se extrae a medias. Medido el 2026-08-21: Amurrio sacó 21 actos
    (solo los titulares de cada jornada) y Saratxo 83 (el cartel entero); tenían
    2 actos en común, un 2%, así que la copia pasó de largo. La copia más
    completa que el original es invisible para una comparación de programas.

    La descripción no tiene ese problema: la redacta el modelo a partir del mismo
    párrafo de cabecera del cartel, y sale casi literal. Tramo verbatim más largo
    contra la capital, sobre las 13 fichas reales de Amurrio:
        copias  -> Artomaña 12, Aloria 11, Saratxo 5 palabras
        propias -> San Jorge 3, todas las demás 1

    Se exige ADEMÁS que las fechas pisen las de la capital. Sin ese segundo
    requisito, dos fiestas del mismo municipio redactadas con la plantilla del
    ayuntamiento se parecerían lo suficiente para caer, y son legítimas.
    """
    if not fiestas or not fiestas_capital or localidad.get("es_capital"):
        return fiestas

    rangos_capital = _rangos_de(fiestas_capital)
    if not rangos_capital:
        return fiestas

    conservadas = []
    for f in fiestas:
        if f.get("origen") == "santo_patron" or not _solapa_con(f, rangos_capital):
            conservadas.append(f)
            continue

        tramo, cual = 0, None
        for c in fiestas_capital:
            n = _tramo_verbatim_mas_largo(f.get("descripcion"), c.get("descripcion"))
            if n > tramo:
                tramo, cual = n, c

        if tramo >= ANTICOPIA_MIN_PALABRAS_VERBATIM:
            logger.warning(
                f"  [ANTI-COPIA/DESCRIPCIÓN] '{f.get('nombre')}' descartada para "
                f"{localidad['nombre']}: {tramo} palabras seguidas calcadas de "
                f"'{cual.get('nombre')}' y fechas solapadas con la capital."
            )
            continue
        conservadas.append(f)

    return conservadas


def _actos_de(fiesta: dict) -> set:
    """Conjunto de actos de una fiesta, normalizados para poder compararlos."""
    actos = set()
    for dia in fiesta.get("programa") or []:
        for evento in dia.get("eventos") or []:
            desc = _normalizar_nombre(evento.get("descripcion", ""))
            if len(desc) > 8:      # descartar "misa", "baile" y demás genéricos cortos
                actos.add(desc)
    return actos


def _huecos_de(fiesta: dict) -> set:
    """
    Pares (fecha, hora) del programa. Es la huella independiente del idioma.

    Comparar descripciones no basta: el mismo acto sale en euskera en una
    localidad y en castellano en otra ("abereerakusketa" / "exposición de
    ganado") y no casan como cadenas. La hora sí es la misma. Y que dos pueblos
    distintos coincidan en treinta actos al mismo minuto del mismo día no ocurre:
    o es el mismo programa, o no es ninguno de los dos.
    """
    huecos = set()
    for dia in fiesta.get("programa") or []:
        fecha = dia.get("fecha")
        for evento in dia.get("eventos") or []:
            hora = (evento.get("hora") or "").strip().replace(" ", "")
            if fecha and hora:
                huecos.add((fecha, hora))
    return huecos


def descartar_programas_copiados(
    fiestas: list[dict],
    fiestas_capital: list[dict] | None,
    localidad: dict,
) -> list[dict]:
    """
    Retira las fiestas cuyo PROGRAMA es el de la capital, aunque el nombre y las
    fechas se hayan disfrazado.

    Es la señal más robusta de todas, y la que salta a la vista leyendo el JSON:
    los nombres varían ("Fiestas Patronales de Delika") y las fechas se desplazan
    un día, pero los actos concretos no. Medido el 2026-08-21, con la guarda por
    nombre y fechas ya puesta: "Mariachi México Lindo 'Sí Señor'" aparecía en
    5 localidades y "Teatro: The Return of Delirios" en otras 5. Un mariachi
    contratado y una obra concreta no se celebran en cinco pueblos a la vez.

    Se compara contra los actos de la capital y se descarta cuando comparten una
    fracción alta. Se exige un mínimo de actos en común además del porcentaje,
    para que una fiesta de tres actos genéricos no se descarte por casualidad.
    """
    if not fiestas or not fiestas_capital or localidad.get("es_capital"):
        return fiestas

    actos_capital, huecos_capital = set(), set()
    for f in fiestas_capital:
        actos_capital |= _actos_de(f)
        huecos_capital |= _huecos_de(f)
    if len(actos_capital) < ANTICOPIA_MIN_ACTOS_COMUNES and len(huecos_capital) < ANTICOPIA_MIN_ACTOS_COMUNES:
        return fiestas

    conservadas = []
    for f in fiestas:
        if f.get("origen") == "santo_patron":
            conservadas.append(f)
            continue

        actos, huecos = _actos_de(f), _huecos_de(f)
        if not actos and not huecos:
            conservadas.append(f)
            continue

        # Se toma la señal MÁS fuerte de las dos. Cada una falla en un caso
        # distinto: las descripciones no casan si las dos localidades tomaron el
        # cartel en idiomas diferentes, y los huecos no sirven si el programa no
        # trae horas. Medido el 2026-08-21 sobre las copias reales: Delika 100%
        # por horario y 3% por texto; Larrinbe al revés, 46% por texto y 34% por
        # horario. Con el máximo de ambas se cazan las dos.
        comunes_actos = actos & actos_capital
        comunes_huecos = huecos & huecos_capital
        # Fracción MUTUA: se divide entre el programa más corto de los dos. Si la
        # capital se extrajo a medias, medir solo contra los actos de la pedanía
        # diluye la señal justo cuando la copia es más completa que el original.
        # Medido el 2026-08-21: Saratxo copió 83 actos y Amurrio solo había
        # extraído 21, así que la copia daba 2% y pasaba de largo.
        frac_actos = (
            len(comunes_actos) / min(len(actos), len(actos_capital))
            if actos and actos_capital else 0.0
        )
        frac_huecos = (
            len(comunes_huecos) / min(len(huecos), len(huecos_capital))
            if huecos and huecos_capital else 0.0
        )

        if frac_huecos >= frac_actos:
            fraccion, comunes, unidad = frac_huecos, len(comunes_huecos), "horarios"
            ejemplos = ", ".join(f"{d} {h}" for d, h in sorted(comunes_huecos)[:3])
        else:
            fraccion, comunes, unidad = frac_actos, len(comunes_actos), "actos"
            ejemplos = ", ".join(sorted(comunes_actos)[:3])

        if comunes >= ANTICOPIA_MIN_ACTOS_COMUNES and fraccion >= ANTICOPIA_FRACCION_COPIA:
            logger.warning(
                f"  [ANTI-COPIA/PROGRAMA] '{f.get('nombre')}' descartada para "
                f"{localidad['nombre']}: {comunes} {unidad} ({100 * fraccion:.0f}%) "
                f"coinciden con los de la capital. Ej.: {ejemplos}"
            )
            continue
        conservadas.append(f)

    return conservadas


_ACTO_DE_RELLENO = re.compile(
    r"\bno\s+hay\b|\bno\s+se\s+(?:especific|mencion|indic|detall)|\bsin\s+eventos\b"
    r"|\bno\s+consta\b|\bno\s+especificad|\(si\s+existe\)|\bpor\s+determinar\b",
    re.IGNORECASE,
)


def _es_acto_de_relleno(descripcion: str) -> bool:
    """
    El modelo, cuando no encuentra nada para un día, escribe que no encuentra
    nada y lo mete como si fuera un acto: "No hay eventos especificados para este
    día", "Romería hacia la ermita (si existe)". Es texto sobre el programa, no
    programa.
    """
    return bool(_ACTO_DE_RELLENO.search(descripcion or ""))


def _acto_es_concreto(descripcion: str) -> bool:
    """
    ¿Es un acto que solo puede ocurrir una vez, o algo genérico que se repite?

    Dos señales. La longitud: "misa" o "romería" se celebran cada día de las
    fiestas y en todos los pueblos a la vez; "Maratón de DJs de Cuadrillas", no.
    Y los dos puntos o las comillas, que en un cartel introducen un nombre
    propio: "Concierto: NØT" es un grupo contratado, se llame como se llame y
    ocupe lo que ocupe. Sin esta segunda señal se colaba justo ese, que al
    normalizar se queda en doce caracteres y empataba con el umbral.
    """
    if re.search(r"[:\"«»“”]", descripcion or ""):
        return True
    return len(_normalizar_nombre(descripcion)) > PROGRAMA_MIN_CHARS_ACTO_UNICO


def sanear_programa(
    fiesta: dict,
    fiestas_capital: list[dict] | None = None,
    localidad: dict | None = None,
) -> dict:
    """
    Limpia el programa de una fiesta: quita los actos repetidos día tras día y
    los que en realidad son de la capital.

    Dos averías distintas, las dos medidas en la ejecución del 2026-08-22:

    1. REPETICIÓN CÍCLICA. El enrichment pide el programa de tres en tres días
       con el mismo contexto delante, y cuando el modelo no sabe distinguir un
       día de otro repite los mismos actos en todos. Tertanga tenía 25 de 28
       actos repetidos (89%), Baranbio 16 de 20, Larrinbe 13 de 23. Se agrava
       cuando el rango de fechas es más largo que la fiesta: a Baranbio se le
       dieron 9 días para una fiesta de 4 y el modelo cicló el programa dos
       veces, hasta poner el chupinazo el último día a las 23:30.

       Un acto concreto ocurre UNA vez en unas fiestas. Se conserva la primera
       aparición y se quitan las demás. Se respetan los actos que de verdad se
       repiten a diario —misa, dianas, hinchables—, que son cortos y genéricos:
       el umbral de longitud los deja fuera de la comparación.

    2. ACTOS DE LA CAPITAL. Las guardas anticopia trabajan sobre la ficha: si la
       fiesta tiene nombre, fechas y sede propios, pasa entera, y luego el
       enrichment la rellena con el cartel del pueblo grande. Larrinbe (24-26 de
       julio) y Lekamaña (26-29 de septiembre) compartían diez conciertos, entre
       ellos "Benito Kamelas", que era el cabeza de cartel de Amurrio el 15 de
       agosto. Un concierto contratado no se da tres veces en tres pueblos.
    """
    programa = fiesta.get("programa") or []
    if not programa:
        return fiesta

    actos_capital = set()
    if fiestas_capital and localidad and not localidad.get("es_capital"):
        for f in fiestas_capital:
            actos_capital |= _actos_de(f)

    vistos: set[tuple] = set()
    quitados_rep = quitados_cap = quitados_relleno = 0
    nuevo_programa = []
    for dia in programa:
        eventos = []
        for ev in dia.get("eventos") or []:
            if _es_acto_de_relleno(ev.get("descripcion", "")):
                quitados_relleno += 1
                continue
            desc = _normalizar_nombre(ev.get("descripcion", ""))
            # La hora entra en la clave: el mismo acto a dos horas distintas son
            # dos pases de verdad. En Lekamaña el maratón de DJs figura a las
            # 00:00 y a las 02:00, y borrar el segundo perdía media noche.
            clave = (desc, (ev.get("hora") or "").strip())
            if not _acto_es_concreto(ev.get("descripcion", "")):
                eventos.append(ev)      # genérico: puede repetirse a diario
                continue
            if clave in vistos:
                quitados_rep += 1
                continue
            if desc in actos_capital:
                quitados_cap += 1
                continue
            vistos.add(clave)
            eventos.append(ev)
        dia = dict(dia, eventos=eventos)
        nuevo_programa.append(dia)

    if quitados_rep or quitados_cap or quitados_relleno:
        donde = localidad.get("nombre", "") if localidad else ""
        partes = []
        if quitados_rep:
            partes.append(f"{quitados_rep} actos repetidos en varios días")
        if quitados_cap:
            partes.append(f"{quitados_cap} actos que son del programa de la capital")
        if quitados_relleno:
            partes.append(f"{quitados_relleno} líneas de relleno del modelo")
        logger.warning(
            f"  [PROGRAMA] '{fiesta.get('nombre')}' de {donde}: retirados " + " y ".join(partes) + "."
        )

    fiesta["programa"] = nuevo_programa
    return fiesta


def recortar_rango_al_programa(fiesta: dict) -> dict:
    """
    Recorta las fechas de la fiesta a los días que el programa llegó a cubrir.

    Es el sustituto con datos del recorte que hacía el anclaje con una frase.
    Cuando el enrichment ha construido un programa, sus días dicen hasta dónde
    llega la fiesta según las fuentes; los días que quedan fuera de ese tramo son
    los que el modelo añadió al declarar el rango y nadie respaldó después.

    Frenos, todos por lo mismo —que recortar de más cuesta días reales—:

    - Solo encoge. Si el programa se sale del rango declarado, el rango manda:
      ampliar por esta vía sería inventar fiesta.

    - Nunca deja la fiesta en un día. Igual que en el anclaje: convertir una
      fiesta de varios días en una de un día no es afinar.

    - Cuenta los días que el programa ABARCA, tengan actos o no, no los que
      traen contenido. Medido el 2026-09-02 sobre Aljubé: su ficha salió del 13
      al 24 de mayo cuando su programa dice "Del 13 al 17"; el esqueleto del
      programa llega al 18 y a partir de ahí no hay ni día creado —esos seis
      días no los miró nadie—, mientras que el 13 sí está y solo le faltan actos.
      Recortando por días CON actos se perdía el 13, que es día de fiesta.

    - El programa tiene que abarcar al menos RECORTE_PROGRAMA_MIN_DIAS días.
      Uno de dos días no dice cuánto dura la fiesta, solo que esos dos días
      existen. Medido en la ejecución del 2026-09-02, que es la que descubrió
      este freno: con el recorte sin condición, Sierra pasó del 30 de julio al 2
      de agosto —correcto— a durar dos días, y Santiago de Mora de cinco días a
      dos, cuando lo suyo son once. Los dos programas tenían dos días. Los
      recortes que sí acertaron (San Roque de Tobarra al 14 de agosto exacto,
      Aljubé al 18 de mayo) venían de programas de cinco y seis días.

    - Y no se recorta con un programa del que ya se sospecha: ni el de otro año
      ni el que no nombra la advocación de esta fiesta. En esa misma ejecución,
      las patronales de Aranda se recortaron al 13 de septiembre usando el
      programa de 2025, el único publicado; y el programa de Sierra venía de una
      página que el propio enrichment había avisado de que no nombra a San
      Francisco Javier por ningún sitio.

    - Y NO se recorta si algún lote del enrichment se quedó sin respuesta. Los
      días que faltan no es que no existan: es que nadie llegó a preguntarlos.
      Medido el 2026-09-04 en Santa Marta de los Barros: el 4.º de cuatro lotes
      se perdió por timeout y el recorte dio la fiesta por terminada el 28 de
      julio, cuando su programa llega al 1 de agosto. El día que se perdió era
      el 29, el de la patrona. Un fallo pasajero no debe convertirse en un dato
      erróneo y sin marcar.
    """
    if fiesta.get("lotes_incompletos"):
        return fiesta

    ini = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_inicio"))
    fin = _parse_fecha_con_fallback_bisiesto(fiesta.get("fecha_fin"))
    programa = fiesta.get("programa") or []
    if not (ini and fin) or ini == fin or not programa:
        return fiesta
    if not any(d.get("eventos") for d in programa):
        return fiesta
    if fiesta.get("programa_de_otro_anno") or fiesta.get("programa_advocacion_dudosa"):
        return fiesta

    dias = sorted(
        d for d in (
            _parse_fecha_con_fallback_bisiesto(x.get("fecha")) for x in programa
        ) if d
    )
    if len(dias) < RECORTE_PROGRAMA_MIN_DIAS:
        return fiesta

    nuevo_ini, nuevo_fin = max(ini, dias[0]), min(fin, dias[-1])
    if (nuevo_ini, nuevo_fin) == (ini, fin):
        return fiesta
    if (nuevo_fin - nuevo_ini).days + 1 < ANCLA_MIN_DIAS_TRAS_RECORTE:
        return fiesta

    logger.info(
        f"  [PROGRAMA] '{fiesta.get('nombre')}': {fiesta['fecha_inicio']}→"
        f"{fiesta['fecha_fin']} recortada a {nuevo_ini}→{nuevo_fin}; el programa "
        f"no llega a los {(nuevo_ini - ini).days + (fin - nuevo_fin).days} día(s) "
        f"que quedan fuera."
    )
    fiesta["fecha_inicio"] = nuevo_ini.isoformat()
    fiesta["fecha_fin"] = nuevo_fin.isoformat()
    return fiesta


def marcar_estado_del_programa(fiesta: dict) -> dict:
    """
    Dice si el programa de la fiesta está completo, a medias o no se ha
    encontrado, y baja la confianza cuando no lo está.

    Sin esto, una ficha con fechas verificadas y tres actos sale igual que una
    bien extraída, y el que la lee no puede distinguirlas. Medido el 2026-08-22:
    Aranda de Duero salía con `confianza: alta`, diez días y tres actos, y no era
    un fallo de extracción —sus fiestas son del 11 al 20 de septiembre y el
    ayuntamiento aún no había publicado el programa: "programa de fiestas" y
    "cañonazo" aparecían cero veces en sus 110 chunks—.

    Se separa a propósito de `confianza`, que habla de si la fiesta existe y de
    si sus fechas son fiables. Son dos preguntas distintas: en Aranda las fechas
    son exactas y el programa no está. Y no se afirma que "no esté publicado",
    que no se puede saber desde aquí, solo que no se ha encontrado.
    """
    if fiesta.get("origen") == "santo_patron":
        return fiesta

    programa = fiesta.get("programa") or []
    actos = sum(len(d.get("eventos") or []) for d in programa)
    dias = max(len(programa), 1)

    if actos == 0:
        fiesta["programa_estado"] = "no_encontrado"
        # Y fuera el esqueleto de días vacíos. Un programa sin un solo acto no
        # es un programa: el 2026-08-26 Aranda de Duero salió con quince días
        # numerados y ninguno con nada dentro, mientras las demás fichas sin
        # programa llevaban la lista vacía. Dos formas de decir lo mismo obligan
        # a quien lee la salida a comprobar las dos.
        fiesta["programa"] = []
    elif actos < dias:
        fiesta["programa_estado"] = "parcial"
    elif fiesta.get("lotes_incompletos"):
        # Hay actos y salen las cuentas, pero uno de los lotes se quedó sin
        # respuesta: de esos días no sabemos nada. "Completo" sería mentir en la
        # única bandera que la base de datos va a mirar para fiarse.
        fiesta["programa_estado"] = "parcial"
    else:
        fiesta["programa_estado"] = "completo"
        return fiesta

    if fiesta.get("confianza") == "alta":
        fiesta["confianza"] = "media"
    return fiesta


def limpiar_actos_compartidos_del_municipio(
    fiestas: list[dict],
    lugar_id_capital: str | None = None,
) -> list[dict]:
    """
    Barrido final del municipio: quita el acto concreto que aparece en varios
    pueblos a la vez.

    `sanear_programa` compara cada pedanía contra la capital, y eso deja de
    funcionar cuando la capital se extrae a medias. Medido el 2026-08-22: Amurrio
    solo sacó 25 actos de más de cien, así que "Concierto: Benito Kamelas" —que
    es su cabeza de cartel del 15 de agosto— no estaba entre ellos, y sobrevivió
    a la vez en Larrinbe (24-26 de julio) y en Lekamaña (26-29 de septiembre).
    Nueve conciertos compartidos entre dos pueblos que celebran con dos meses de
    diferencia.

    Al terminar el municipio ya están todas las localidades, y entonces la
    coincidencia se ve sin depender de que ninguna se extrajera bien. Un acto
    contratado —un grupo con nombre y apellidos, un espectáculo concreto— se da
    en un sitio. Si figura en dos o más pedanías, en al menos una sobra y no hay
    forma de saber en cuál: se quita de todas. En la capital se conserva, que es
    de donde suelen venir.

    Actúa in situ sobre los dicts, que son los mismos que tiene el estado.
    """
    if len(fiestas) < 2:
        return fiestas

    localidades_por_acto: dict[str, set] = {}
    for f in fiestas:
        for dia in f.get("programa") or []:
            for ev in dia.get("eventos") or []:
                if _acto_es_concreto(ev.get("descripcion", "")):
                    desc = _normalizar_nombre(ev.get("descripcion", ""))
                    localidades_por_acto.setdefault(desc, set()).add(f.get("lugar_id"))

    compartidos = {a for a, locs in localidades_por_acto.items() if len(locs) >= 2}
    if not compartidos:
        return fiestas

    quitados: dict[str, int] = {}
    for f in fiestas:
        if f.get("lugar_id") == lugar_id_capital:
            continue
        for dia in f.get("programa") or []:
            antes = len(dia.get("eventos") or [])
            dia["eventos"] = [
                ev for ev in dia.get("eventos") or []
                if _normalizar_nombre(ev.get("descripcion", "")) not in compartidos
            ]
            if antes != len(dia["eventos"]):
                n = antes - len(dia["eventos"])
                quitados[f.get("nombre", "?")] = quitados.get(f.get("nombre", "?"), 0) + n
                # Queda en la ficha, no solo en el log. Es la señal de alarma de
                # que una pedanía ha empezado a copiar de su capital, y con el
                # triple de material en el contexto hay que poder vigilarla
                # ejecución a ejecución sin releer los logs.
                f["actos_compartidos_retirados"] = f.get("actos_compartidos_retirados", 0) + n

    if quitados:
        logger.warning(
            f"  [PROGRAMA/MUNICIPIO] {len(compartidos)} actos figuraban en dos o más "
            f"localidades y se han retirado de las pedanías: "
            + ", ".join(f"{n} (-{c})" for n, c in quitados.items())
        )
    return fiestas


def _avales_de_patronal(f: dict, patron: dict | None, dia_patron: date | None) -> tuple:
    """Con qué cuenta una ficha para ser LA patronal del pueblo. Mayor gana."""
    return (
        bool(dia_patron and _solapa_con(f, [(dia_patron, dia_patron)])),
        nombra_al_patron(f.get("nombre", ""), patron),
        sum(len(d.get("eventos") or []) for d in f.get("programa") or []) > 0,
        any(es_fuente_oficial(s) for s in f.get("fuentes") or []),
        {"alta": 3, "media": 2, "baja": 1}.get(f.get("confianza"), 0),
    )


def descartar_patronales_duplicadas(
    fiestas: list[dict],
    patron: dict | None,
    localidad: dict,
    anno: int | None = None,
) -> list[dict]:
    """
    Un pueblo tiene UNA fiesta patronal. Si salen dos, sobra una.

    `descartar_duplicados_internos` ya funde las que comparten actos, pero exige
    que ambas TENGAN actos, y las patronales duplicadas suelen salir las dos
    vacías —el programa aún no está publicado— así que se le escapaban. Medido
    el 2026-08-26: Aranda de Duero salió a la vez con "Fiestas Patronales de
    Aranda de Duero" del 17 al 31 de agosto (fechas inventadas: dos hermanas
    suyas de 40 y 71 días ya habían caído por alucinación) y con "Fiestas
    Patronales en honor a Nuestra Señora de las Viñas" del 11 al 20 de
    septiembre, que son las de verdad. Ninguna traía un solo acto y las dos
    llegaron a la salida.

    Con una excepción que NO es un duplicado: el pueblo que traslada sus
    patronales y sigue celebrando el día de su patrón. Muchos pueblos con el
    patrón en invierno mueven la fiesta grande al verano, cuando hay gente, y
    mantienen aparte la celebración del día del santo. Sierra es el caso: San
    Francisco Javier es el 3 de diciembre, sus patronales son de finales de
    julio, y celebra las dos cosas. Si de las dos fichas una cae sobre el día del
    patrón y la otra no, son las dos celebraciones complementarias y se conservan
    ambas. Sin esta salvedad, la de diciembre —mejor avalada por cubrir el día
    del santo— borraba la patronal de verano, que es la de verdad.

    Fuera de esa excepción se conserva la mejor avalada, y solo cuando hay con
    qué elegir; si empatan se quedan las dos y se deja constancia, por la misma
    razón que en el deduplicador de programas: un duplicado se ve, una fiesta
    real borrada en silencio no.
    """
    candidatas = [
        i for i, f in enumerate(fiestas)
        if f.get("origen") != "santo_patron" and _es_patronal(f)
    ]
    if len(candidatas) < 2:
        return fiestas

    dia_patron = None
    if patron and patron.get("dia") and patron.get("mes"):
        try:
            dia_patron = date(anno or _anno_de(fiestas), patron["mes"], patron["dia"])
        except (ValueError, TypeError):
            dia_patron = None

    descartadas: set[int] = set()
    for pos, i in enumerate(candidatas):
        for j in candidatas[pos + 1:]:
            if i in descartadas or j in descartadas:
                continue
            a, b = fiestas[i], fiestas[j]

            # Cada una con SU programa extraído: son dos celebraciones, no una
            # contada dos veces. Tobarra hace la Bajada del Cristo en mayo y sus
            # fiestas grandes en agosto, y ninguna de las dos cae el 14 de
            # septiembre, que es el día del santo. El 2026-08-27 esta función le
            # borró la de mayo con 19 actos ya extraídos.
            #
            # Compartir programa no las salva: para cuando llegan aquí,
            # `descartar_duplicados_internos` ya ha fundido las que copian actos
            # una de otra. Si las dos siguen teniendo actos propios, son dos.
            if _actos_de(a) and _actos_de(b):
                logger.info(
                    f"  [PATRONAL] {localidad['nombre']} tiene dos patronales con programa "
                    f"propio: '{a.get('nombre')}' ({a.get('fecha_inicio')}) y "
                    f"'{b.get('nombre')}' ({b.get('fecha_inicio')}). Son dos celebraciones."
                )
                continue

            # La patronal trasladada y la del día del santo tampoco son un
            # duplicado: son las dos celebraciones que hace el mismo pueblo.
            cubre_a = bool(dia_patron and _solapa_con(a, [(dia_patron, dia_patron)]))
            cubre_b = bool(dia_patron and _solapa_con(b, [(dia_patron, dia_patron)]))
            if cubre_a != cubre_b:
                trasladada, del_santo = (b, a) if cubre_a else (a, b)
                logger.info(
                    f"  [PATRONAL] {localidad['nombre']} celebra las dos: "
                    f"'{del_santo.get('nombre')}' ({del_santo.get('fecha_inicio')}) cae en el "
                    f"día de {patron['nombre']}, y '{trasladada.get('nombre')}' "
                    f"({trasladada.get('fecha_inicio')}) es la patronal trasladada. "
                    f"No son un duplicado."
                )
                trasladada["patron_trasladado"] = True
                continue

            # Dos patronales que se solapan ya las funde el filtro de fechas; lo
            # que aquí se persigue es la misma fiesta en dos ventanas distintas.
            aval_a, aval_b = (_avales_de_patronal(a, patron, dia_patron),
                              _avales_de_patronal(b, patron, dia_patron))
            if aval_a == aval_b:
                logger.warning(
                    f"  [PATRONAL/DUPLICADA] {localidad['nombre']} tiene dos fiestas "
                    f"patronales, '{a.get('nombre')}' ({a.get('fecha_inicio')}) y "
                    f"'{b.get('nombre')}' ({b.get('fecha_inicio')}), y nada permite decidir "
                    f"cuál es la buena. Se conservan las dos."
                )
                continue
            gana_a = aval_a > aval_b
            ganadora, perdedora = (a, b) if gana_a else (b, a)
            descartadas.add(j if gana_a else i)
            logger.warning(
                f"  [PATRONAL/DUPLICADA] '{perdedora.get('nombre')}' "
                f"({perdedora.get('fecha_inicio')} a {perdedora.get('fecha_fin')}) descartada "
                f"para {localidad['nombre']}: un pueblo tiene una sola patronal y "
                f"'{ganadora.get('nombre')}' ({ganadora.get('fecha_inicio')}) está mejor "
                f"avalada."
            )

    return [f for k, f in enumerate(fiestas) if k not in descartadas]


def descartar_duplicados_internos(
    fiestas: list[dict],
    fiestas_capital: list[dict] | None,
    localidad: dict,
) -> list[dict]:
    """
    Funde las fiestas de UNA MISMA localidad que son la misma fiesta re-fechada.

    Las guardas anteriores miran hacia la capital. Esta mira hacia dentro, y hace
    falta porque el modelo también duplica sin salir del pueblo: medido el
    2026-08-21, Artomaña recibió su propio programa de San Jorge dos veces, una
    con sus fechas buenas (17-23 abr) y otra con el nombre y las fechas de la
    fiesta de la capital (12-17 ago). Nueve actos idénticos palabra por palabra,
    el 75% del programa más corto.

    De cada par se conserva la ficha mejor avalada, y solo si hay con qué elegir:
      1. La que el texto atribuye a esta misma localidad (`sede_segun_el_texto`).
      2. La que NO pisa las fechas de la capital: si una de las dos cae dentro de
         la semana grande del municipio, es la que se ha contagiado.

    Si ninguna de las dos señales distingue al par, se conserva TODO y solo se
    deja constancia en el log. El desempate que quedaría es "la del programa más
    largo", y apunta justo al revés: la ficha contaminada hereda el cartel entero
    del municipio y siempre es la más gorda, así que borraría la buena. Un
    duplicado en la salida se ve y se corrige; una fiesta real borrada en
    silencio, no.
    """
    if len(fiestas) < 2:
        return fiestas

    rangos_capital = _rangos_de(fiestas_capital or [])
    propio = _normalizar_nombre(localidad.get("nombre", ""))

    def aval(f: dict) -> tuple:
        sede_propia = _normalizar_nombre(f.get("sede_segun_el_texto") or "") == propio
        return (sede_propia, not _solapa_con(f, rangos_capital))

    descartadas: set[int] = set()
    for i in range(len(fiestas)):
        for j in range(i + 1, len(fiestas)):
            if i in descartadas or j in descartadas:
                continue
            a, b = fiestas[i], fiestas[j]
            if a.get("origen") == "santo_patron" or b.get("origen") == "santo_patron":
                continue

            actos_a, actos_b = _actos_de(a), _actos_de(b)
            if not actos_a or not actos_b:
                continue
            comunes = actos_a & actos_b
            fraccion = len(comunes) / min(len(actos_a), len(actos_b))
            if len(comunes) < ANTICOPIA_MIN_ACTOS_DUP_INTERNO or fraccion < ANTICOPIA_FRACCION_DUP_INTERNO:
                continue

            aval_a, aval_b = aval(a), aval(b)
            if aval_a == aval_b:
                logger.warning(
                    f"  [ANTI-COPIA/INTERNO] '{a.get('nombre')}' ({a.get('fecha_inicio')}) y "
                    f"'{b.get('nombre')}' ({b.get('fecha_inicio')}) comparten {len(comunes)} "
                    f"actos ({100 * fraccion:.0f}%) en {localidad['nombre']}: parecen la misma "
                    f"fiesta con dos fechas, pero nada permite decidir cuál es la buena. "
                    f"Se conservan las dos."
                )
                continue

            gana_a = aval_a > aval_b
            ganadora, perdedora = (a, b) if gana_a else (b, a)
            descartadas.add(j if gana_a else i)
            logger.warning(
                f"  [ANTI-COPIA/INTERNO] '{perdedora.get('nombre')}' "
                f"({perdedora.get('fecha_inicio')}) descartada para {localidad['nombre']}: "
                f"{len(comunes)} actos ({100 * fraccion:.0f}%) idénticos a "
                f"'{ganadora.get('nombre')}' ({ganadora.get('fecha_inicio')}), "
                f"la misma fiesta con otras fechas."
            )

    return [f for k, f in enumerate(fiestas) if k not in descartadas]


async def buscar_programas_de_las_fiestas(
    fiestas: list[dict],
    localidad: dict,
    municipio: dict,
    anno: int,
    provincia: str = "",
    idiomas: list[str] | None = None,
    nombres_hermanas: list[str] | None = None,
) -> list[dict]:
    """
    Busca en la web el programa de cada fiesta ya descubierta.

    Va después del descubrimiento porque hasta entonces no se sabe qué fiestas
    tiene el pueblo. Las consultas de localidad se hacen con el patrón, y una
    localidad con varias fiestas solo busca la del patrón: en Tobarra eso dejó a
    San Antón y a San Roque sin que nadie fuese a por su programa.

    Los documentos que vuelven pasan por los mismos filtros que los demás —los de
    fuera del municipio y los de pueblos homónimos—, porque una consulta más
    específica no los hace más de fiar.
    """
    if not fiestas:
        return []

    from scraper.google_search import search_fiesta_web

    fuera: list[dict] = []
    vistos: set[str] = set()
    for fiesta in fiestas:
        if fiesta.get("origen") == "santo_patron":
            continue  # una estimación no tiene programa que buscar
        try:
            docs = await search_fiesta_web(fiesta, localidad, municipio, anno)
        except Exception as e:
            logger.warning(
                f"    [PROGRAMAS] Error buscando el programa de "
                f"'{fiesta.get('nombre')}': {e}"
            )
            continue
        for d in docs:
            url = d.get("url", "")
            if url and url in vistos:
                continue
            vistos.add(url)
            fuera.append(d)

    if not fuera:
        return []

    # Los mismos filtros que el resto del material: una consulta por el nombre de
    # la fiesta atrae con fuerza el programa del pueblo homónimo que celebra esa
    # misma advocación, que las hay a cientos.
    antes = len(fuera)
    fuera = [
        d for d in fuera
        if not documento_es_ajeno_al_municipio(
            d.get("texto") or "", d.get("url", ""),
            localidad["nombre"], municipio["nombre"], nombres_hermanas,
        )
    ]
    fuera = await descartar_homonimos(
        fuera, localidad["nombre"], municipio["nombre"], provincia,
        nombres_hermanas, idiomas or ["es"],
    )
    if len(fuera) != antes:
        logger.info(
            f"    [PROGRAMAS] {antes - len(fuera)} de {antes} documentos descartados "
            f"por no ser de {localidad['nombre']}."
        )
    return fuera


def _contexto_alrededor_de(fiesta: dict, indexed_chunks: list[dict]) -> str:
    """
    El texto que rodea a esta fiesta, para que el juez pueda situarla.

    Se priorizan, por este orden: los fragmentos de la página de la que se copió
    el programa, los que nombran la fiesta, y los que caen en sus fechas. Es la
    diferencia con el juez de documentos, que solo ve 1.200 caracteres de
    cabecera: aquí lo que se pregunta es de dónde es la fiesta, y eso se decide
    justo en el texto de alrededor —el «en Astorga» que delata a Santa Marta
    aparece en el cuerpo, no en el titular—.
    """
    if not indexed_chunks:
        return ""
    url_prog = (fiesta.get("url_programa") or "").strip()
    senas = {t for t in tokens_distintivos(fiesta.get("nombre", ""), "") if len(t) > 3}
    fechas = {fiesta.get("fecha_inicio", ""), fiesta.get("fecha_fin", "")}
    meses = {_MESES_EN_ORDEN[int(f[5:7]) - 1] for f in fechas if len(f) >= 7 and f[5:7].isdigit()}

    def prioridad(item: dict) -> tuple:
        url = item.get("url") or ""
        texto = (item.get("chunk") or "").lower()
        return (
            0 if (url_prog and url == url_prog) else 1,
            0 if senas and any(s in texto for s in senas) else 1,
            0 if any(m and m in texto for m in meses) else 1,
            -float(item.get("score", 0.0)),
        )

    elegidos, usados = [], 0
    for item in sorted(indexed_chunks, key=prioridad):
        trozo = item.get("chunk") or ""
        coste = contar_tokens(trozo) + 12
        if usados + coste > PERTENENCIA_CONTEXTO_TOKENS:
            if usados:
                break
            trozo = trozo[:4000]
            coste = contar_tokens(trozo) + 12
        elegidos.append(f"--- [{item.get('url', '')}] ---\n{trozo}")
        usados += coste
    return "\n\n".join(elegidos)


_PALABRAS_VACIAS_LUGAR = {
    "de", "del", "la", "las", "el", "los", "y", "en", "provincia", "comunidad",
    "municipio", "pedania", "localidad", "ayuntamiento", "espana",
}


def lugar_real_contradice(lugar_real: str, localidad: dict, municipio: dict) -> bool:
    """
    ¿El sitio que el modelo nombra es OTRO, aunque él haya contestado que sí?

    Medido en la validación del 2026-09-04 sobre las 42 fichas reales: el juez
    contestó "si" a las 'Fiestas de Arroyomolinos' y en el mismo JSON escribió
    lugar_real: "Arroyomolinos de la Vera" —otro municipio de Cáceres—. Se
    contradecía dentro de la misma respuesta, y el veredicto se llevaba la ficha.

    La comprobación es por palabras, no por subcadena, justamente por ese caso:
    "Arroyomolinos de la Vera" CONTIENE "Arroyomolinos", así que un `in` lo daría
    por nuestro. Lo que delata a un pueblo distinto es la palabra que sobra —"Vera",
    "Tormes", "Astorga", "Madrid"—. Si todo lo que nombra es nuestro pueblo, nuestro
    municipio, nuestra provincia o nuestra comunidad, no contradice nada.
    """
    if not (lugar_real or "").strip():
        return False

    def palabras(texto: str) -> set[str]:
        # La puntuación se quita aquí y no con `normalize_text`, que la conserva:
        # el modelo escribe "Garrucha, Almería" y "Alcuéscar (Cáceres)", y sin
        # esto los tokens salen como "garrucha," y "(caceres,", que no casan con
        # nada. Medido: el veto tumbaba doce fichas legítimas por las comas.
        return {p for p in re.split(r"[^\w]+", normalize_text(texto or "")) if p}

    nuestros: set[str] = set()
    for valor in (
        localidad.get("nombre"), municipio.get("nombre"),
        localidad.get("provincia"), municipio.get("provincia"),
        localidad.get("comunidad"), municipio.get("comunidad"),
    ):
        nuestros |= palabras(valor)
    nuestros -= _PALABRAS_VACIAS_LUGAR
    suyas = palabras(lugar_real) - _PALABRAS_VACIAS_LUGAR
    if not suyas:
        return False
    return bool(suyas - nuestros)


_SYS_REPREGUNTA = """Antes dijiste que esta fiesta SÍ es de la localidad que buscamos, pero la situaste en
un sitio cuyo nombre no coincide con el nuestro. Puede ser que sean el mismo sitio
—muchos municipios españoles tienen un nombre largo y otro corto: "Santa Marta" es
"Santa Marta de los Barros", "Aranda" es "Aranda de Duero"— o puede ser que sean
pueblos distintos que se llaman parecido: "Arroyomolinos" y "Arroyomolinos de la
Vera" son municipios diferentes.

Mira la provincia, la comunidad, el municipio y la web oficial que se te dan, y
responde una sola cosa: ¿es ese sitio NUESTRA localidad?

Responde solo JSON:
{"es_de_la_localidad": "si" | "no" | "no_se",
 "razon": "una frase"}"""


async def _repreguntar_pertenencia(
    fiesta: dict,
    localidad: dict,
    municipio: dict,
    nombres_hermanas: list[str] | None,
    lugar_real: str,
) -> dict:
    """
    Segunda pregunta cuando el modelo se contradice: ¿ese sitio somos nosotros?

    Es deliberadamente estrecha —no repite el juicio entero, solo resuelve la
    duda del topónimo— para que la respuesta no dependa otra vez de todo el
    contexto. Cuesta una llamada, y solo en los casos raros: sobre las 42 fichas
    de la tirada del 2026-09-04 habrían sido una o dos.
    """
    datos = await llm_chat_json(
        _SYS_REPREGUNTA,
        "LOCALIDAD QUE BUSCAMOS\n"
        + _bloque_identidad(localidad, municipio, nombres_hermanas)
        + f"\n\nSITIO QUE NOMBRASTE: {lugar_real}"
        + f"\n\nFIESTA: {fiesta.get('nombre', '')} "
          f"({fiesta.get('fecha_inicio', '')} a {fiesta.get('fecha_fin', '')})",
        max_tokens=PERTENENCIA_MAX_TOKENS,
        etiqueta="PERTENENCIA/REPREGUNTA",
    )
    return datos if isinstance(datos, dict) else {}


async def filtrar_por_pertenencia(
    fiestas: list[dict],
    localidad: dict,
    municipio: dict,
    nombres_hermanas: list[str] | None,
    indexed_chunks: list[dict],
) -> list[dict]:
    """
    Quita las fichas que el modelo no reconoce como de esta localidad.

    El veto del código se queda con la última palabra en un caso: si el programa
    viene de la web oficial del propio pueblo o de su ayuntamiento, no se tira
    aunque el modelo dude. Ahí el documento ES la prueba de pertenencia, y un
    "no" en esas condiciones es un error del modelo, no un hallazgo.

    Las descartadas no se borran en silencio: quedan en el log con el motivo y el
    lugar al que el texto las manda, que es lo que permite medir después si el
    juez acierta.
    """
    if not (PERTENENCIA_ENABLED and fiestas):
        return fiestas

    veredictos = await asyncio.gather(*[
        veredicto_de_pertenencia(
            f, localidad, municipio, nombres_hermanas,
            _contexto_alrededor_de(f, indexed_chunks),
        )
        for f in fiestas
    ], return_exceptions=True)

    salvadas: list[dict] = []
    for fiesta, v in zip(fiestas, veredictos):
        nombre = fiesta.get("nombre", "")
        if isinstance(v, BaseException) or not v:
            logger.warning(
                f"  [PERTENENCIA] '{nombre[:44]}': el modelo no contestó; se conserva."
            )
            salvadas.append(fiesta)
            continue

        de_aqui = str(v.get("es_de_la_localidad", "")).strip().lower()
        es_fiesta = str(v.get("es_una_fiesta", "")).strip().lower() or "si"
        razon = str(v.get("razon", ""))[:160]
        lugar = (v.get("lugar_real") or "") or "sin decir dónde"
        que_es = (v.get("que_es") or "").strip()

        # ── Pregunta 2: ¿es una fiesta? ───────────────────────────────
        #
        # Se juzga primero porque su veto es distinto del de la procedencia: que
        # el programa venga de la web del ayuntamiento demuestra de DÓNDE es,
        # no que sea una fiesta. El "Concurso de Bailes Modernos" de Alcuéscar
        # estaba publicado en el BOP por su propio ayuntamiento y no deja de ser
        # un concurso.
        if es_fiesta in ("no", "no_se"):
            # Regla de oro del criterio del proyecto: orquesta, verbena, DJ o
            # música nocturna en el programa y es una fiesta, diga lo que diga
            # el modelo. Es la misma señal que usa `festival_filter`.
            if tiene_senal_nocturna(fiesta):
                logger.info(
                    f"  [PERTENENCIA] '{nombre[:44]}': el modelo dice que no es fiesta, "
                    f"pero su programa trae orquesta/verbena/música nocturna. Se conserva."
                )
            elif es_fiesta == "no" or PERTENENCIA_DESCARTAR_SI_DUDA:
                logger.warning(
                    f"  [PERTENENCIA] DESCARTADA '{nombre[:44]}' de {localidad.get('nombre','')}: "
                    f"no es una fiesta{f' — es {que_es}' if que_es else ''}. {razon}"
                )
                continue
            else:
                fiesta["confianza"] = "baja"
                fiesta["naturaleza_dudosa"] = True

        # ── Pregunta 1: ¿es de aquí? ──────────────────────────────────
        #
        # Si dice "sí" y a la vez nombra un sitio que no reconocemos, NO se
        # descarta: se le vuelve a preguntar señalándole la duda. El código
        # detecta la incoherencia; quien decide sigue siendo el modelo.
        #
        # Antes esto era un veredicto del código y se llevó por delante 'Candelas
        # 2026', la única ficha real de Santa Marta: el modelo la situó bien, en
        # "Santa Marta de los Barros", y el código no reconoció ese nombre porque
        # el dataset guarda el corto. Decidir si dos topónimos son el mismo sitio
        # es un hecho del mundo, no una regla que se pueda escribir.
        if de_aqui == "si" and lugar_real_contradice(v.get("lugar_real") or "", localidad, municipio):
            v2 = await _repreguntar_pertenencia(
                fiesta, localidad, municipio, nombres_hermanas, lugar,
            )
            de_aqui = str((v2 or {}).get("es_de_la_localidad", "")).strip().lower()
            razon = str((v2 or {}).get("razon", ""))[:160] or razon
            if de_aqui == "si":
                logger.info(
                    f"  [PERTENENCIA] '{nombre[:44]}': situaba la fiesta en «{lugar}»; "
                    f"repreguntado, confirma que es de aquí. {razon}"
                )
                salvadas.append(fiesta)
                continue
            # Si a la segunda tampoco lo tiene claro, fuera. Decisión tomada.
            logger.warning(
                f"  [PERTENENCIA] DESCARTADA '{nombre[:44]}' de {localidad.get('nombre','')}: "
                f"situaba la fiesta en «{lugar}» y al repreguntar dice '{de_aqui or 'nada'}'. {razon}"
            )
            continue

        if de_aqui == "si":
            salvadas.append(fiesta)
            continue

        # Veto del código: para la PROCEDENCIA, la web del propio pueblo manda
        # sobre el modelo. Ahí el documento es la prueba.
        if web_es_de_este_lugar(
            fiesta.get("url_programa", ""), localidad.get("nombre", ""),
            municipio.get("nombre", ""),
        ):
            logger.info(
                f"  [PERTENENCIA] '{nombre[:44]}': el modelo dice '{de_aqui}' pero el "
                f"programa viene de la web del propio lugar. Se conserva."
            )
            salvadas.append(fiesta)
            continue

        if de_aqui == "no_se" and not PERTENENCIA_DESCARTAR_SI_DUDA:
            fiesta["confianza"] = "baja"
            fiesta["pertenencia_dudosa"] = True
            logger.info(
                f"  [PERTENENCIA] '{nombre[:44]}': el modelo no puede situarla; "
                f"se conserva con confianza baja. {razon}"
            )
            salvadas.append(fiesta)
            continue

        logger.warning(
            f"  [PERTENENCIA] DESCARTADA '{nombre[:44]}' de {localidad.get('nombre','')}: "
            f"{'no es de aquí' if de_aqui == 'no' else 'no se puede situar'} → {lugar}. {razon}"
        )

    quitadas = len(fiestas) - len(salvadas)
    if quitadas:
        logger.warning(
            f"  [PERTENENCIA] {localidad.get('nombre','')}: {quitadas} de {len(fiestas)} "
            f"fichas descartadas por no ser de esta localidad."
        )
    return salvadas


async def analyze_festivals_multipass(
    municipio: dict,
    localidad: dict,
    documentos: list[dict],
    anno: int,
    fecha_patron=None,
    rag_processor: AsyncRAGProcessor | None = None,
    logger: logging.Logger | None = None,
    analyzer_fn=None,
    nombres_hermanas: list[str] = None,
    fiestas_capital: list[dict] | None = None,
    patron: dict | None = None,
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

    # Paso 1: Indexar chunks y calcular embeddings 1 sola vez.
    # La provincia y las lenguas de la provincia viajan hasta aquí para la
    # comprobación de homónimos: sin ellas no se puede decir que un documento en
    # euskera delata otra región, y decirlo a ciegas arrasaría Amurrio.
    provincia = (municipio.get("provincia") or "").strip()
    comunidad = comunidad_de(municipio)
    try:
        idiomas = get_language_profile(comunidad, provincia).get("idiomas_a_detectar") or ["es"]
    except Exception:
        idiomas = ["es"]

    # Los homónimos se quitan AQUÍ y no dentro de index_document_chunks, que es
    # donde estaban al principio. Aquello limpiaba el índice de chunks pero no la
    # lista `documentos`, que sigue viva y se le pasa entera al discovery unas
    # líneas más abajo. Medido el 2026-08-24: los dos documentos de Cordovilla
    # Bajo salían descartados en el log y sus actos —«Escuela Belén Hervás»,
    # «grupo Son de Ases»— seguían apareciendo en las fichas, porque entraban por
    # la otra puerta. Filtrando antes del reparto, las dos rutas ven lo mismo.
    documentos = await descartar_homonimos(
        documentos, localidad['nombre'], municipio['nombre'], provincia,
        nombres_hermanas, idiomas,
    )
    if not documentos:
        return []

    indexed_chunks = await index_document_chunks(
        rag_processor, documentos, municipio['nombre'], localidad['nombre'],
        nombres_hermanas=nombres_hermanas, anno=anno,
    )
    if not indexed_chunks:
        return []

    # Paso 2: Obtener contexto de discovery
    discovery_context, fuentes_contexto, n_directa, discovery_lotes = await retrieve_discovery_context(
        indexed_chunks=indexed_chunks,
        municipio=municipio,
        localidad=localidad,
        anno=anno,
        rag_processor=rag_processor,
        max_chars=DISCOVERY_MAX_CHARS,
        nombres_hermanas=nombres_hermanas,
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
            nombres_hermanas=nombres_hermanas,
            contexto_precalculado=(discovery_context, fuentes_contexto, discovery_lotes),
        )

    # Aquí NO se sale aunque el modelo no haya encontrado nada: el rescate por
    # anclaje existe justo para ese caso y, saliendo antes, no llegaba a correr.
    # Medido el 2026-08-23, Aranda de Duero se quedó sin ninguna ficha porque el
    # discovery solo sacó "Fiesta Peñas" y un eclipse —los dos de un día, los dos
    # filtrados— mientras su contexto repetía diez veces "fiestas patronales de
    # Aranda de Duero del 11 al 20 de septiembre de 2026", que es la fecha real.

    # Paso 3b: retirar las que son la fiesta de la capital copiada. Se hace ANTES
    # del enrichment: enriquecer una copia gasta una llamada al LLM en fabricar
    # noventa actos que luego habria que tirar igualmente.
    # Lo que descarten las guardas queda vetado: el rescate de abajo no puede
    # devolver por la ventana lo que estas echan por la puerta.
    antes_de_las_guardas = list(fiestas_descubiertas)

    fiestas_descubiertas = descartar_copias_de_la_capital(
        fiestas_descubiertas, fiestas_capital, n_directa, localidad, municipio
    )
    # 3c. Las dos guardas que NO dependen de tener evidencia propia, y que por eso
    # cazan lo que la de arriba deja pasar: la de arriba se desactiva entera en
    # cuanto un par de documentos nombran al pueblo, y los pueblos de verdad
    # siempre tienen quien los nombre. Medido el 2026-08-21, las tres copias que
    # sobrevivieron (Aloria, Artomaña y Saratxo) eran de pueblos con evidencia
    # propia de sobra; las cazan la sede y la descripción, no el programa.
    fiestas_descubiertas = descartar_por_sede_ajena(
        fiestas_descubiertas, localidad, municipio, nombres_hermanas
    )
    fiestas_descubiertas = descartar_descripciones_copiadas(
        fiestas_descubiertas, fiestas_capital, localidad
    )
    # 3d. Regla del patrón: la fiesta que se anuncia como patronal de un pueblo
    # tiene que caer sobre el día del patrón DE ESE pueblo. No depende de que la
    # capital se haya extraído bien, así que sigue funcionando cuando las guardas
    # que comparan contra ella se quedan cortas.
    fiestas_descubiertas = descartar_por_patron_ajeno(
        fiestas_descubiertas, patron, localidad, discovery_context, anno
    )

    # 3e. Si de todo lo anterior no queda nada, rescatar la fiesta de la frase
    # que la anuncia en el contexto. Va ANTES del enrichment para que la fiesta
    # rescatada pase por él y salga con programa, como cualquier otra.
    # 3e-bis. Afinar las fechas de lo que sí dio el modelo con la frase que las
    # anuncia en el contexto, antes de enriquecer: el enrichment pide el programa
    # día a día, así que arrancar con el rango correcto cambia lo que se le pide.
    fiestas_descubiertas = ajustar_fechas_con_anclas(
        fiestas_descubiertas, discovery_context, localidad, nombres_hermanas, anno, patron,
        municipio_nombre=municipio.get("nombre", ""),
    )
    vivas = {id(f) for f in fiestas_descubiertas}
    descartadas_por_guardas = [f for f in antes_de_las_guardas if id(f) not in vivas]
    fiestas_descubiertas = recuperar_fiestas_desde_anclas(
        fiestas_descubiertas, discovery_context, localidad, nombres_hermanas, anno,
        patron, descartadas_por_guardas, municipio.get("nombre", ""),
    )
    if not fiestas_descubiertas:
        logger.info(
            f"  [SIN FIESTAS] {localidad['nombre']}: ni el modelo ni el contexto "
            f"dan ninguna fiesta. Se da por no publicada."
        )
        return []

    # Paso 3-ter: buscar el programa DE CADA FIESTA, ahora que sabemos cuáles son.
    #
    # Las consultas de localidad se construyen con el patrón, y eso deja sin
    # buscar a las demás fiestas del pueblo. Medido el 2026-08-26 en Tobarra, que
    # tiene tres: las seis consultas fueron todas sobre el Cristo de la Antigua
    # —el patrón— y ninguna nombró a San Antón ni a San Roque. Las dos se
    # quedaron sin programa aunque el de San Roque está publicado en
    # radiotobarra.es/sanroque26/: nadie fue a buscarlo.
    docs_por_fiesta = await buscar_programas_de_las_fiestas(
        fiestas_descubiertas, localidad, municipio, anno, provincia, idiomas, nombres_hermanas,
    )
    if docs_por_fiesta:
        nuevos = await index_document_chunks(
            rag_processor, docs_por_fiesta, municipio["nombre"], localidad["nombre"],
            nombres_hermanas=nombres_hermanas, anno=anno,
        )
        if nuevos:
            indexed_chunks = indexed_chunks + nuevos
            logger.info(
                f"    [PROGRAMAS] {len(nuevos)} chunks nuevos de {len(docs_por_fiesta)} "
                f"documentos buscados por fiesta."
            )

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
            nombres_hermanas=nombres_hermanas,
        )
        # Saneado del programa recién construido: quitar los actos que el modelo
        # ha reciclado de un día a otro y los que son del cartel de la capital,
        # y ajustar las fechas a los días que quedan con contenido propio.
        f_enriched = sanear_programa(f_enriched, fiestas_capital, localidad)
        # Y recortar el rango a lo que el programa llegó a cubrir: es aquí, con
        # los días ya construidos, donde se quitan los días de más que el modelo
        # declaró y ninguna fuente respaldó.
        f_enriched = recortar_rango_al_programa(f_enriched)
        # Dejar dicho, en la propia ficha, si el programa está o no está.
        f_enriched = marcar_estado_del_programa(f_enriched)
        fiestas_enriquecidas.append(f_enriched)

    # Paso 5: segunda pasada anti-copia, ahora comparando PROGRAMAS. La del paso
    # 3b solo podía mirar nombre y fechas, que el modelo disfraza; los actos
    # concretos, no. Se hace aquí porque el programa no existe hasta ahora.
    fiestas_enriquecidas = descartar_programas_copiados(
        fiestas_enriquecidas, fiestas_capital, localidad
    )

    # Paso 6: y la misma comparación hacia dentro. El modelo no solo copia de la
    # capital: también duplica una fiesta de la propia localidad cambiándole las
    # fechas. Igual que la anterior, necesita el programa, así que va aquí.
    fiestas_enriquecidas = descartar_duplicados_internos(
        fiestas_enriquecidas, fiestas_capital, localidad
    )

    # Paso 7: y el duplicado que el de arriba no puede ver, porque las dos
    # fichas están vacías: la fiesta patronal por partida doble.
    fiestas_enriquecidas = descartar_patronales_duplicadas(
        fiestas_enriquecidas, patron, localidad, anno
    )

    # Paso 8: la última puerta. Con la ficha ya montada, se le pregunta al modelo
    # si esa fiesta es de este pueblo, enseñándole quiénes somos y el texto de
    # sus fuentes. Va al final a propósito: los pasos anteriores juzgan
    # documentos y fragmentos, y lo que se guarda es la ficha.
    fiestas_enriquecidas = await filtrar_por_pertenencia(
        fiestas_enriquecidas, localidad, municipio, nombres_hermanas, indexed_chunks,
    )

    return fiestas_enriquecidas









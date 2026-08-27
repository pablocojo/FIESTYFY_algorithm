"""
Presupuesto de contexto del LLM local (Fase 0 del plan de mejora).

Responde a tres preguntas que hoy nadie hace y que provocan que el contexto
que llega al modelo esté mal dimensionado:

  1. ¿Con qué `n_ctx` está REALMENTE cargado el modelo en LM Studio?
     -> `get_n_ctx()` lo consulta en /api/v0/models (campo loaded_context_length).

  2. ¿Cuántos tokens ocupa de verdad este texto?
     -> `contar_tokens()` usa el tokenizador de Qwen si está disponible y, si no,
        un ratio chars/token AUTOCALIBRADO con el `usage.prompt_tokens` que
        devuelve el propio LM Studio en cada respuesta.

  3. ¿Cuánto contexto puedo permitirme, descontando el system prompt y dejando
     sitio para la respuesta?
     -> `presupuesto_contexto()`.

Este módulo NO cambia ninguna decisión del pipeline: solo mide e informa.
Las fases 1-4 del plan consumirán estas funciones.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path

from config import LMSTUDIO_BASE_URL, LMSTUDIO_CHAT_MODEL

logger = logging.getLogger("context_budget")

_BASE_DIR = Path(__file__).resolve().parent
CALIBRACION_FILE = _BASE_DIR / "context_calibracion.json"

# ── Valores por defecto (solo si LM Studio no responde) ──────────────────────
N_CTX_FALLBACK = 8192          # conservador a propósito: mejor quedarse corto
RATIO_CHARS_TOKEN_INICIAL = 3.5  # castellano web con el BPE de Qwen2.5
RATIO_MIN, RATIO_MAX = 2.0, 5.0  # cotas de seguridad de la autocalibración

# Sobrecarga de la plantilla de chat (tokens de rol/marcadores por petición).
OVERHEAD_PLANTILLA_TOKENS = 25

# Reservas de salida recomendadas (tokens que el modelo necesita para responder)
RESERVA_SALIDA_DISCOVERY = 1536    # lista de fiestas, sin programa
RESERVA_SALIDA_ENRICHMENT = 4096   # programa de actos de varios días
RESERVA_SALIDA_PATRON = 256
MARGEN_SEGURIDAD_TOKENS = 256

_lock = threading.Lock()
_model_info_cache: dict | None = None
_tokenizer_cache = "sin_intentar"  # "sin_intentar" | None | objeto tokenizer
_ratio_cache: float | None = None


# ══════════════════════════════════════════════════════════════════════════════
# 1. n_ctx real del modelo cargado
# ══════════════════════════════════════════════════════════════════════════════

def _http_get_json(url: str, timeout: float = 4.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_model_info(refrescar: bool = False) -> dict:
    """
    Consulta LM Studio y devuelve información del modelo de chat cargado.

    Devuelve siempre un dict con al menos:
        {"id": str, "n_ctx": int, "max_context_length": int|None, "detectado": bool}

    `detectado` es False cuando se ha tenido que recurrir al fallback: en ese caso
    el presupuesto será conservador y quedará constancia en el log.
    """
    global _model_info_cache
    if _model_info_cache is not None and not refrescar:
        return _model_info_cache

    info = {
        "id": LMSTUDIO_CHAT_MODEL,
        "n_ctx": N_CTX_FALLBACK,
        "max_context_length": None,
        "detectado": False,
    }

    try:
        data = _http_get_json(f"{LMSTUDIO_BASE_URL}/api/v0/models")
        modelos = data.get("data", data if isinstance(data, list) else [])

        # Preferimos el modelo configurado; si no aparece, el primer LLM cargado.
        candidato = None
        for m in modelos:
            if m.get("id") == LMSTUDIO_CHAT_MODEL:
                candidato = m
                break
        if candidato is None:
            for m in modelos:
                if m.get("state") == "loaded" and m.get("type") in (None, "llm"):
                    candidato = m
                    break

        if candidato:
            cargado = candidato.get("loaded_context_length")
            maximo = candidato.get("max_context_length")
            n_ctx = cargado or maximo
            if isinstance(n_ctx, int) and n_ctx > 0:
                info = {
                    "id": candidato.get("id", LMSTUDIO_CHAT_MODEL),
                    "n_ctx": int(n_ctx),
                    "max_context_length": maximo,
                    "detectado": True,
                }
                if cargado and maximo and cargado < maximo:
                    logger.warning(
                        f"[BUDGET] '{info['id']}' está cargado con n_ctx={cargado} "
                        f"pero soporta hasta {maximo}. Subirlo en LM Studio "
                        f"multiplicaría el contexto disponible sin coste."
                    )
    except Exception as e:
        logger.warning(
            f"[BUDGET] No se pudo leer /api/v0/models ({e}). "
            f"Usando n_ctx de seguridad = {N_CTX_FALLBACK}."
        )

    if info["detectado"]:
        logger.info(f"[BUDGET] Modelo '{info['id']}' cargado con n_ctx = {info['n_ctx']}")

    with _lock:
        _model_info_cache = info
    return info


def get_n_ctx(refrescar: bool = False) -> int:
    """Ventana de contexto real (en tokens) del modelo cargado en LM Studio."""
    return get_model_info(refrescar)["n_ctx"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. Conteo de tokens
# ══════════════════════════════════════════════════════════════════════════════

def _get_tokenizer():
    """
    Carga perezosa del tokenizador de Qwen2.5. Devuelve None si no está disponible
    (sin red, sin transformers, sin caché de HuggingFace): en ese caso se usa el
    ratio autocalibrado, que es suficientemente bueno para dimensionar.

    Ruta local opcional mediante la variable de entorno QWEN_TOKENIZER_PATH.
    """
    global _tokenizer_cache
    if _tokenizer_cache != "sin_intentar":
        return _tokenizer_cache

    ruta = os.environ.get("QWEN_TOKENIZER_PATH", "Qwen/Qwen2.5-7B-Instruct")
    tok = None
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(ruta, trust_remote_code=False)
        logger.info(f"[BUDGET] Tokenizador exacto cargado desde '{ruta}'.")
    except Exception as e:
        logger.info(
            f"[BUDGET] Sin tokenizador exacto ({type(e).__name__}). "
            f"Se usará el ratio chars/token autocalibrado."
        )

    with _lock:
        _tokenizer_cache = tok
    return tok


def _cargar_ratio() -> float:
    global _ratio_cache
    if _ratio_cache is not None:
        return _ratio_cache
    ratio = RATIO_CHARS_TOKEN_INICIAL
    try:
        if CALIBRACION_FILE.exists():
            datos = json.loads(CALIBRACION_FILE.read_text(encoding="utf-8"))
            valor = float(datos.get("ratio_chars_token", ratio))
            if RATIO_MIN <= valor <= RATIO_MAX:
                ratio = valor
    except Exception as e:
        logger.debug(f"[BUDGET] No se pudo leer la calibración: {e}")
    with _lock:
        _ratio_cache = ratio
    return ratio


def contar_tokens(texto: str) -> int:
    """
    Número de tokens de `texto`. Exacto si hay tokenizador; estimado con el ratio
    autocalibrado en caso contrario. Nunca lanza.
    """
    if not texto:
        return 0
    tok = _get_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(texto, add_special_tokens=False))
        except Exception:
            pass
    return int(len(texto) / _cargar_ratio()) + 1


def tokens_a_chars(tokens: int) -> int:
    """Conversión inversa aproximada, para presupuestos expresados en caracteres."""
    return max(0, int(tokens * _cargar_ratio()))


def registrar_uso_real(chars_prompt: int, prompt_tokens: int) -> None:
    """
    Autocalibración: compara los caracteres que enviamos con los `prompt_tokens`
    que LM Studio dice haber consumido, y ajusta el ratio con una media móvil
    exponencial. Se persiste para que la siguiente ejecución arranque calibrada.

    Solo se usa cuando NO hay tokenizador exacto (si lo hay, el ratio es
    irrelevante para el conteo, pero se sigue registrando por trazabilidad).
    """
    if chars_prompt <= 0 or prompt_tokens <= OVERHEAD_PLANTILLA_TOKENS:
        return
    observado = chars_prompt / (prompt_tokens - OVERHEAD_PLANTILLA_TOKENS)
    if not (RATIO_MIN <= observado <= RATIO_MAX):
        logger.debug(f"[BUDGET] Ratio observado fuera de rango ({observado:.2f}); descartado.")
        return

    actual = _cargar_ratio()
    nuevo = 0.8 * actual + 0.2 * observado

    global _ratio_cache
    with _lock:
        _ratio_cache = nuevo
    try:
        CALIBRACION_FILE.write_text(
            json.dumps(
                {"ratio_chars_token": round(nuevo, 4), "ultima_observacion": round(observado, 4)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"[BUDGET] No se pudo persistir la calibración: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Presupuesto
# ══════════════════════════════════════════════════════════════════════════════

def presupuesto_contexto(
    system_prompt: str,
    reserva_salida: int = RESERVA_SALIDA_DISCOVERY,
    margen: int = MARGEN_SEGURIDAD_TOKENS,
    n_ctx: int | None = None,
) -> int:
    """
    Tokens disponibles para el TEXTO RECUPERADO, una vez descontados el system
    prompt, la respuesta que el modelo debe poder escribir y un margen.

    Nunca devuelve menos de 512: si sale negativo es que el system prompt o la
    reserva están mal dimensionados, y se avisa en el log.
    """
    ctx = n_ctx if n_ctx is not None else get_n_ctx()
    tokens_system = contar_tokens(system_prompt) + OVERHEAD_PLANTILLA_TOKENS
    disponible = ctx - tokens_system - reserva_salida - margen

    if disponible < 512:
        logger.warning(
            f"[BUDGET] Presupuesto insuficiente: n_ctx={ctx}, system={tokens_system}, "
            f"reserva={reserva_salida}, margen={margen} -> {disponible} tokens. "
            f"Se fuerza a 512; revisa el n_ctx de LM Studio."
        )
        return 512
    return disponible


def resumen_presupuesto(system_prompt: str, reserva_salida: int) -> dict:
    """Desglose para logs y para el volcado de depuración."""
    ctx = get_n_ctx()
    tokens_system = contar_tokens(system_prompt) + OVERHEAD_PLANTILLA_TOKENS
    disponible = presupuesto_contexto(system_prompt, reserva_salida, n_ctx=ctx)
    return {
        "n_ctx": ctx,
        "n_ctx_detectado": get_model_info()["detectado"],
        "tokens_system": tokens_system,
        "reserva_salida": reserva_salida,
        "margen": MARGEN_SEGURIDAD_TOKENS,
        "presupuesto_contexto_tokens": disponible,
        "presupuesto_contexto_chars_aprox": tokens_a_chars(disponible),
        "ratio_chars_token": round(_cargar_ratio(), 3),
        "tokenizador_exacto": _get_tokenizer() is not None,
    }


def truncar_a_tokens(texto: str, max_tokens: int) -> str:
    """
    Recorta `texto` para que no supere `max_tokens`, cortando en un salto de línea
    para no partir una línea de programa por la mitad. Último recurso: las fases
    1-4 deben evitar llegar aquí seleccionando bien.
    """
    if contar_tokens(texto) <= max_tokens:
        return texto
    objetivo_chars = tokens_a_chars(max_tokens)
    recorte = texto[:objetivo_chars]
    salto = recorte.rfind("\n")
    if salto > objetivo_chars * 0.5:
        recorte = recorte[:salto]
    # Ajuste fino: el ratio puede haberse quedado corto.
    while recorte and contar_tokens(recorte) > max_tokens:
        salto = recorte.rfind("\n", 0, int(len(recorte) * 0.9))
        recorte = recorte[:salto] if salto > 0 else recorte[: int(len(recorte) * 0.9)]
    return recorte


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s | %(message)s")
    info = get_model_info()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print(json.dumps(resumen_presupuesto("Eres una API estricta." * 50, RESERVA_SALIDA_DISCOVERY),
                     ensure_ascii=False, indent=2))

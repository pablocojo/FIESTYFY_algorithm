# llm_client.py
import json
import time

import requests

from config import LMSTUDIO_API, HEADERS, LLM_TEMPERATURE, MAX_LLM_RETRIES
import config
from logger import log_error


def contar_tokens(text: str) -> int:
    """
    Contabiliza tokens de forma aproximada.
    """
    return len(text.split())


def isolate_json(text: str) -> str:
    """
    Extrae el bloque JSON completo desde el primer '{' o '[' hasta el ultimo
    '}' o ']'.
    """
    start = next((i for i, c in enumerate(text) if c in ("{", "[")), None)
    if start is None:
        return ""

    last_obj = text.rfind("}")
    last_arr = text.rfind("]")
    end = max(last_obj, last_arr)

    if end == -1 or end <= start:
        return text[start:].strip()
    return text[start : end + 1].strip()


def call_llm(system_prompt: str, user_prompt: str, context_info: dict = {}, model_name: str = None, json_mode: bool = True) -> str:
    """
    Envia prompts al unico LLM configurado.
    Si json_mode es True, aísla y devuelve solo el JSON puro.

    No hay alternancia de modelos ni llamadas paralelas desde este cliente.
    """
    payload = {
        "model": model_name or config.LLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "stream": False,
    }

    timeout_seconds = 300
    retries = MAX_LLM_RETRIES or 3

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(LMSTUDIO_API, headers=HEADERS, json=payload, timeout=timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if json_mode:
                return isolate_json(content)
            return content.strip()
        except Exception as e:
            log_error(
                f"Error al llamar al LLM (intento {attempt}/{retries}): {e}",
                context={**context_info, "model": config.LLM_MODEL_NAME},
            )
            if attempt < retries:
                time.sleep(2 * attempt)
            else:
                return ""

    return ""

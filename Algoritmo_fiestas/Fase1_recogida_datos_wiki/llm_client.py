# llm_client.py
import requests
import json
import sys
from config import LMSTUDIO_API, HEADERS, TIMEOUT, LLM_MODEL_NAME, LLM_TEMPERATURE
from logger import log_error


def contar_tokens(text: str) -> int:
    """
    Contabiliza tokens de forma aproximada (split por espacios).
    """
    return len(text.split())


def isolate_json(text: str) -> str:
    """
    Extrae el bloque JSON completo desde el primer '{' o '['
    hasta el último '}' o ']', limpiando restos.
    """
    start = next((i for i, c in enumerate(text) if c in ('{', '[')), None)
    if start is None:
        return ""
    last_obj = text.rfind('}')
    last_arr = text.rfind(']')
    end = max(last_obj, last_arr)
    if end == -1 or end <= start:
        return text[start:].strip()
    return text[start:end+1].strip()


def call_llm(system_prompt: str, user_prompt: str, context_info: dict = {}) -> str:
    """
    Envía prompts al LLM y devuelve sólo el JSON puro.
    Usa streaming, filtra chunks no JSON y muestra la respuesta en tiempo real.
    """
    payload = {
        "model": LLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": LLM_TEMPERATURE,
        "stream": True
    }

    full_response = ""
    brace_balance = 0
    bracket_balance = 0
    started = False

    try:
        with requests.post(LMSTUDIO_API, headers=HEADERS, json=payload, stream=True, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=None):
                if not chunk:
                    continue
                text = chunk.decode('utf-8', errors='ignore')
                for line in text.splitlines():
                    if not line.startswith("data: "):
                        continue
                    payload_line = line[len("data: "):].strip()
                    if not payload_line or payload_line == "[DONE]":
                        continue
                    if payload_line[0] not in ('{', '['):
                        log_error("Chunk ignorado: no parece JSON", context={**context_info, "chunk": payload_line[:100]})
                        continue
                    try:
                        obj = json.loads(payload_line)
                    except json.JSONDecodeError:
                        log_error("Chunk JSON malformado, salto", context={**context_info, "chunk": payload_line[:200]})
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        # Mostrar streaming en consola
                        print(content, end='')
                        sys.stdout.flush()
                        full_response += content
                        if not started and any(c in content for c in ('{','[')):
                            started = True
                        if started:
                            brace_balance += content.count('{') - content.count('}')
                            bracket_balance += content.count('[') - content.count(']')
                            if brace_balance <= 0 and bracket_balance <= 0:
                                resp.close()
                                break
                if started and brace_balance <= 0 and bracket_balance <= 0:
                    break
    except Exception as e:
        log_error(f"Error al llamar al LLM: {e}", context=context_info)
        return ""

    json_only = isolate_json(full_response)
    print()  # Nueva línea tras streaming
    return json_only

# fin llm_client.py

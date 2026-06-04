# logger.py

import json
import datetime
import sys

error_log_entries = []

def log_error(message: str, context: dict = None):
    """
    Registra un mensaje de error con timestamp y contexto.
    Ya no imprime nada en consola.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    if context:
        entry += "\n  Contexto: " + json.dumps(context, indent=2, ensure_ascii=False)
    error_log_entries.append(entry)
    # NOTE: Ya no hacemos print(...) aquí.

def dump_error_log(path: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            for e in error_log_entries:
                f.write(e + "\n" + "-"*80 + "\n")
    except Exception as e:
        # Este print sí puede quedarse si quieres ver fallos al volcar
        print(f"No se pudo volcar el log de errores en {path}: {e}", file=sys.stderr)
        sys.stdout.flush()

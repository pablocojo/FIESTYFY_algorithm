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

def safe_print(message: str):
    """
    Imprime en consola de forma segura en Windows, evitando UnicodeEncodeError.
    """
    try:
        print(message)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'ascii'
            print(message.encode(encoding, errors='replace').decode(encoding))
        except Exception:
            try:
                print(message.encode('ascii', errors='ignore').decode('ascii'))
            except Exception:
                pass

def dump_error_log(path: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            for e in error_log_entries:
                f.write(e + "\n" + "-"*80 + "\n")
    except Exception as e:
        # Usar safe_print aquí también por seguridad
        safe_print(f"No se pudo volcar el log de errores en {path}: {e}")


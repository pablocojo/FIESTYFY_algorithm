import urllib.request
import urllib.error
import json
import time

BASE_URL = "http://192.168.1.103:1234"

def test_models():
    print(f"[*] Comprobando conexión a {BASE_URL}...")
    try:
        req = urllib.request.Request(f"{BASE_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            models = [m.get("id", "Desconocido") for m in data.get("data", [])]
            print("  [OK] Conexión establecida.")
            print(f"  [OK] Modelos cargados: {', '.join(models) if models else 'Ninguno'}")
            return True if models else False
    except urllib.error.URLError as e:
        print(f"  [ERROR] No se pudo conectar: {e.reason}")
        return False
    except Exception as e:
        print(f"  [ERROR] Ocurrió un error inesperado: {e}")
        return False

def test_chat():
    print(f"\n[*] Enviando mensaje de prueba al LLM...")
    url = f"{BASE_URL}/v1/chat/completions"
    payload = {
        # LM Studio normalmente ignora el nombre del modelo o usa el cargado
        "model": "local-model",
        "messages": [
            {"role": "system", "content": "Responde con una sola frase corta en español."},
            {"role": "user", "content": "Hola, ¿estás funcionando?"}
        ],
        "temperature": 0.3,
        "max_tokens": 50
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode())
            respuesta = res_data["choices"][0]["message"]["content"]
            t1 = time.time()
            print(f"  [OK] Respuesta recibida en {t1 - t0:.2f} segundos:")
            print(f"       >> {respuesta}")
    except urllib.error.URLError as e:
        print(f"  [ERROR] Falló la petición de chat: {e.reason}")
    except Exception as e:
        print(f"  [ERROR] Ocurrió un error inesperado: {e}")

if __name__ == "__main__":
    print("=== TEST DE CONEXIÓN LM STUDIO ===")
    if test_models():
        test_chat()
    else:
        print("\n[!] Asegúrate de que LM Studio está ejecutándose, que el servidor está encendido")
        print("    y que está configurado para escuchar en 0.0.0.0 (o en 192.168.1.103).")

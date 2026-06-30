# Fase2_Comprobación_tipo/Comprobacion.py
#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.parse

# --- Definir rutas ---
BASE_DIR   = os.path.dirname(__file__)
JSON_FILE  = os.path.join(BASE_DIR, '..', 'municipios_ejemplo.json')  # JSON de ejemplo
INDEX_FILE = os.path.join(BASE_DIR, '..', 'progress.txt')
SEPARACION = os.path.join(BASE_DIR, '..', 'Fase3_busqueda_fiestas_WebScraper', 'paso0', 'Separación.py')
MASTER_FILE = os.path.join(BASE_DIR, '..', 'municipality_data.json')  # JSON real con article_url

def cargar_municipios():
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] Error cargando {JSON_FILE}: {e}")
        sys.exit(1)

    if not isinstance(data, list):
        print(f"[ERROR] Formato inválido en {JSON_FILE}: se esperaba una lista de municipios")
        sys.exit(1)
    return data

def leer_indice():
    if not os.path.exists(INDEX_FILE):
        return 0
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            t = f.read().strip()
            return int(t) if t.isdigit() else 0
    except:
        return 0

def guardar_indice(n):
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        f.write(str(n))

def cargar_municipality_data():
    try:
        with open(MASTER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('municipalities', [])
    except Exception as e:
        print(f"[ERROR] No se pudo leer {MASTER_FILE}: {e}")
        sys.exit(1)

def normalizar(nombre):
    return urllib.parse.quote(nombre.strip().replace(' ', '_'))

def existe_municipio(nombre_buscado, municipalities):
    nombre_normalizado = normalizar(nombre_buscado)
    for rec in municipalities:
        url = rec.get('article_url', '')
        if url != 'No URL' and url.strip().endswith(nombre_normalizado):
            return True
    return False

def main():
    municipios = cargar_municipios()
    dataset = cargar_municipality_data()
    idx = leer_indice()

    if idx >= len(municipios):
        print("✅ Todos los municipios procesados.")
        return

    rec = municipios[idx]
    nombre = rec.get('nombre', 'Desconocido')
    barrios = rec.get('barrios', [])
    pueblos = rec.get('pueblos', [])

    if not existe_municipio(nombre, dataset):
        print(f"[ERROR] Municipio '{nombre}' no encontrado en {MASTER_FILE}")
        sys.exit(1)

    if barrios:
        estado = 'tiene barrios'
    elif pueblos:
        estado = 'tiene pueblos'
    else:
        estado = 'está solo'

    texto = f"Municipio: {nombre} -> {estado}"
    print(f"▶ Procesando [{idx+1}/{len(municipios)}]: {texto}")

    try:
        subprocess.run([sys.executable, SEPARACION, texto], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Al ejecutar Separacion.py: {e}")
        sys.exit(1)

    guardar_indice(idx + 1)

if __name__ == '__main__':
    main()
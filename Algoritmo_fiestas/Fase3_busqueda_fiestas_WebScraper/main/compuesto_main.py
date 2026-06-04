#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import requests
import urllib.parse

# --- Configuración fija de Dify ---
API_KEY       = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'
DATASET_ID    = '579014f6-3bc1-4b19-8087-9d77623c2c56'
DOCUMENT_ID   = '00fc7f8c-5b6d-4cf8-a0f2-75f73a6fe235'
DIFY_URL      = 'http://localhost:80'
WORKFLOW1_ID  = 'workflow_fiestas_general'
WORKFLOW2_ID  = 'workflow_fiestas_detalle'

# --- Rutas dinámicas ---
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.dirname(os.path.dirname(BASE_DIR))
MASTER_FILE   = os.path.join(PROJECT_ROOT, 'municipality_data.json')
SCRAPY_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso1', 'my_scrapy.py')
CHUNKS_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso3', 'subirchunks.py')
CHUNKING_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso2', 'chunking.py')



def load_municipalities():
    with open(MASTER_FILE, encoding='utf-8') as f:
        data = json.load(f)
    m = data.get('municipalities')
    if not isinstance(m, list):
        print(f"[ERROR] 'municipalities' no es lista en {MASTER_FILE}")
        sys.exit(1)
    return m


def normalize_article_url(article_url):
    if not article_url or article_url == 'No URL':
        return ''
    last_segment = article_url.strip('/').split('/')[-1]
    decoded = urllib.parse.unquote(last_segment)
    return decoded.replace('_', ' ').lower()


def extract_id(raw: str) -> str:
    if raw.startswith("Municipio:"):
        return raw.split("Municipio:")[1].split("->")[0].strip()
    return raw


def find_municipio(input_id: str) -> dict:
    input_norm = input_id.strip().lower()
    for rec in load_municipalities():
        if rec.get('municipio_id', '').lower() == input_norm:
            return rec
        if rec.get('municipio', '').lower() == input_norm:
            return rec
        if normalize_article_url(rec.get('article_url', '')) == input_norm:
            return rec
    print(f"[ERROR] Municipio '{input_id}' no encontrado en {MASTER_FILE}")
    sys.exit(1)


def build_url(rec: dict) -> str:
    if rec.get('official_website') and rec['official_website'] != 'No Official Website':
        return rec['official_website']
    if rec.get('article_url') and rec['article_url'] != 'No URL':
        return rec['article_url']
    if rec.get('domain') and rec['domain'] != 'No Domain':
        d = rec['domain']
        return d if d.startswith("http") else f"http://{d}"
    return ""


def run_scrapy(url: str):
    subprocess.check_call([sys.executable, SCRAPY_SCRIPT, url])

def run_chunking(): subprocess.check_call([sys.executable, CHUNKING_SCRIPT])

def upload_chunks():
    subprocess.check_call([sys.executable, CHUNKS_SCRIPT])


def call_workflow(workflow_id: str) -> dict:
    url = f"{DIFY_URL}/v1/workflows/{workflow_id}/execute"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'}
    payload = {'dataset_id': DATASET_ID, 'document_id': DOCUMENT_ID}
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) < 2:
        print("Uso: python compuesto_main.py <municipio_id_o_nombre>")
        sys.exit(1)

    raw         = sys.argv[1]
    input_id    = extract_id(raw)
    rec         = find_municipio(input_id)
    name        = rec['municipio']
    subdivisions = rec.get('subdivisions', [])

    website = build_url(rec)
    if not website:
        print(f"[ERROR] No se encontró URL válida para {name}")
        sys.exit(1)

    print(f"[INFO] Procesando municipio compuesto: {name}")
    print("[1/3] Scraping principal…", website)
    run_scrapy(website)

    print("[2/3] Procesando chunks…")
    run_chunking()
    print("Subiendo chunks…")
    upload_chunks()

    detalle_subs = []
    if subdivisions:
        print("[3/3] Ejecutando workflows en subdivisiones…")
        for sub in subdivisions:
            sub_name = sub.get('name')
            print(f" → Subdivisión: {sub_name}")
            wf1 = call_workflow(WORKFLOW1_ID)
            detalles = []
            for f in wf1.get('festivities', []):
                nombre = f.get('nombre') or f.get('name', '')
                fecha  = f.get('fecha')  or f.get('date', '')
                wf2    = call_workflow(WORKFLOW2_ID)
                detalles.append({'nombre': nombre, 'fecha': fecha, 'detalle': wf2})
            detalle_subs.append({
                'subdivision':      sub_name,
                'tiene_fiestas':    wf1.get('has_fiestas', False),
                'numero_fiestas':   wf1.get('count', 0),
                'detalles_fiestas': detalles
            })

    print("\n[FINAL] Workflows para municipio completo…")
    wf1_main = call_workflow(WORKFLOW1_ID)
    detalles_main = []
    for f in wf1_main.get('festivities', []):
        nombre = f.get('nombre') or f.get('name', '')
        fecha  = f.get('fecha')  or f.get('date', '')
        wf2    = call_workflow(WORKFLOW2_ID)
        detalles_main.append({'nombre': nombre, 'fecha': fecha, 'detalle': wf2})

    resultado = {
        'municipio': name,
        'detalle_subdivisiones': detalle_subs,
        'resultado_global': {
            'tiene_fiestas':    wf1_main.get('has_fiestas', False),
            'numero_fiestas':   wf1_main.get('count', 0),
            'detalles_fiestas': detalles_main
        }
    }

    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
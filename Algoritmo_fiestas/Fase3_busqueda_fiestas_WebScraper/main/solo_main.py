# =========================
# Fase3_busqueda_fiestas_WebScraper/main/solo_main.py
# =========================
import os
import sys
import json
import subprocess
import requests
import urllib.parse

API_KEY       = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'
DATASET_ID    = '579014f6-3bc1-4b19-8087-9d77623c2c56'
DOCUMENT_ID   = '00fc7f8c-5b6d-4cf8-a0f2-75f73a6fe235'
DIFY_URL      = 'http://localhost:80'
WORKFLOW1_ID  = 'workflow_fiestas_general'
WORKFLOW2_ID  = 'workflow_fiestas_detalle'

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.dirname(os.path.dirname(BASE_DIR))
MASTER_FILE   = os.path.join(PROJECT_ROOT, 'municipality_data.json')
SCRAPY_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso1', 'my_scrapy.py')
CHUNKS_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso3', 'subirchunks.py')
CHUNKING_SCRIPT = os.path.join(PROJECT_ROOT, 'Fase3_busqueda_fiestas_WebScraper', 'paso2', 'chunking.py')
OUTPUT_DIR    = os.path.join(PROJECT_ROOT, 'output_fiestas')


def normalize(text):
    return urllib.parse.unquote(text.strip().lower().replace(" ", "_")).replace("%C3%AD", "i")


def load_municipalities():
    with open(MASTER_FILE, encoding='utf-8') as f:
        data = json.load(f)
    m = data.get('municipalities')
    if not isinstance(m, list):
        print(f"[ERROR] 'municipalities' no es lista en {MASTER_FILE}")
        sys.exit(1)
    return m


def extract_id(raw: str) -> str:
    if raw.startswith("Municipio:"):
        return raw.split("Municipio:")[1].split("->")[0].strip()
    return raw


def find_municipio(rid: str) -> dict:
    target = normalize(rid)
    for rec in load_municipalities():
        url = rec.get("article_url", "")
        if url and url != "No URL":
            final = url.split("/")[-1]
            if normalize(final) == target:
                return rec
        if normalize(rec.get("municipio_id", "")) == target or normalize(rec.get("municipio", "")) == target:
            return rec
    print(f"[ERROR] Municipio '{rid}' no encontrado en {MASTER_FILE}")
    sys.exit(1)


def build_url(rec):
    return rec.get('official_website') if rec.get('official_website') and rec['official_website'] != 'No Official Website' else \
           rec.get('article_url') if rec.get('article_url') and rec['article_url'] != 'No URL' else \
           f"http://{rec.get('domain')}" if rec.get('domain') and rec['domain'] != 'No Domain' else ''


def run_script(script, arg=None):
    cmd = [sys.executable, script]
    if arg:
        cmd.append(arg)
    subprocess.check_call(cmd)


def call_workflow(wid):
    r = requests.post(
        f"{DIFY_URL}/v1/workflows/{wid}/execute",
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        },
        json={'dataset_id': DATASET_ID, 'document_id': DOCUMENT_ID}
    )
    r.raise_for_status()
    return r.json()


class MunicipioObj:
    def __init__(self, name, has_fiestas, num_fiestas):
        self.name = name
        self.has_fiestas = has_fiestas
        self.num_fiestas = num_fiestas
        self.fiestas = []

class FiestaObj:
    def __init__(self, name, date, details):
        self.name = name
        self.date = date
        self.details = details


def main():
    if len(sys.argv)<2:
        sys.exit("Uso: python solo_main.py <municipio_id_o_nombre>")

    # Identificador y registro
    rid = extract_id(sys.argv[1])
    rec = find_municipio(rid)
    name = rec['municipio']
    url = build_url(rec)
    if not url:
        sys.exit(f"[ERROR] URL inválida para {name}")

    # Asegurar carpeta de salida
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    outfile = os.path.join(OUTPUT_DIR, f"{normalize(name)}.json")

    # Scraping y chunking
    print(f"[INFO] Scraping {name}…")
    run_script(SCRAPY_SCRIPT, url)
    print("[INFO] Procesando chunks…")
    run_script(CHUNKING_SCRIPT)
    print("[INFO] Subiendo chunks…")
    run_script(CHUNKS_SCRIPT)

    # Workflow general
    print("[INFO] Ejecutando workflow general…")
    wf1 = call_workflow(WORKFLOW1_ID)

    # Construir objeto de dominio
    municipio = MunicipioObj(
        name=name,
        has_fiestas=wf1.get('has_fiestas', False),
        num_fiestas=wf1.get('count', 0)
    )

    # Recolectar fiestas y detalles
    for fest in wf1.get('festivities', []):
        nom = fest.get('nombre') or fest.get('name', '')
        fec = fest.get('fecha') or fest.get('date', '')
        print(f"[INFO] Detalle de la fiesta {nom}…")
        det = call_workflow(WORKFLOW2_ID)
        fiesta = FiestaObj(name=nom, date=fec, details=det)
        municipio.fiestas.append(fiesta)

    # Serializar a JSON
    output_data = {
        'municipio': municipio.name,
        'tiene_fiestas': municipio.has_fiestas,
        'numero_fiestas': municipio.num_fiestas,
        'fiestas': [
            {'nombre': f.name, 'fecha': f.date, 'detalle': f.details}
            for f in municipio.fiestas
        ]
    }
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"[INFO] Datos guardados en {outfile}")

    # Invocar siguiente paso (p.ej., procesamiento a base de datos)
    # subprocess.check_call([sys.executable, 'dataset_update.py', outfile])

if __name__=='__main__':
    main()
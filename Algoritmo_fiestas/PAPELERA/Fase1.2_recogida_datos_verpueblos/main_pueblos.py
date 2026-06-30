# main_pueblos.py
import json
import time
from urllib.parse import urljoin
from scraper import fetch_url
from extractors_pueblos import (
    extract_autonomias,
    extract_provincias_o_pueblos,
    extract_pueblo_info_with_llm
)
from config import ROOT_REGION_URL, OUTPUT_PUEBLOS_JSON, ERROR_LOG_FILE, BASE_VER_PUEBLOS_URL
from logger import dump_error_log, log_error

def main():
    print("[DEBUG] main: iniciando programa")
    municipios_pueblos = []
    html_root = fetch_url(ROOT_REGION_URL)
    print(f"[DEBUG] HTML raíz cargado, longitud: {len(html_root)}")
    autonomias = extract_autonomias(html_root)

    todos_pueblos = []
    for ca in autonomias:
        ca_url = urljoin(BASE_VER_PUEBLOS_URL, ca['url'])
        print(f"[DEBUG] Procesando CA: {ca['nombre']} -> {ca_url}")
        html_ca = fetch_url(ca_url)
        enlaces = extract_provincias_o_pueblos(html_ca)
        for link in enlaces:
            if link['tipo'] == 'provincia':
                prov_url = urljoin(BASE_VER_PUEBLOS_URL, link['url'])
                print(f"[DEBUG] Entrando en provincia: {link['nombre']} -> {prov_url}")
                html_pr = fetch_url(prov_url)
                pueblos_links = extract_provincias_o_pueblos(html_pr)
            else:
                pueblos_links = [link]
            for plink in pueblos_links:
                full_url = urljoin(BASE_VER_PUEBLOS_URL, plink['url'])
                print(f"[DEBUG] Pueblo detectado: {plink['nombre']} -> {full_url}")
                todos_pueblos.append({'nombre': plink['nombre'], 'url': full_url, 'region': ca['nombre']})

    print(f"[DEBUG] total de pueblos a procesar: {len(todos_pueblos)}")
    for idx, pu in enumerate(todos_pueblos, 1):
        print(f"[DEBUG] Procesando {idx}/{len(todos_pueblos)}: {pu['nombre']}")
        html_pu = fetch_url(pu['url'])
        detalles = extract_pueblo_info_with_llm(pu['nombre'], html_pu, pu['region'])
        if detalles.get('error'):
            log_error(f"Error en {pu['nombre']}: {detalles}")
            continue

        parent = detalles.pop('municipio_parent')
        if parent == pu['nombre'] or parent == 'Ayuntamiento no encontrado':
            entry = {'municipio_nombre': pu['nombre'], 'municipio_category_url': pu['url'], 'distritos': [], 'barrios': [], 'pueblos': []}
        else:
            entry = {'municipio_nombre': parent, 'municipio_category_url': '', 'distritos': [], 'barrios': [], 'pueblos': [
                {'nombre': pu['nombre'], 'article_url': pu['url'], **detalles}
            ]}
        print(f"[DEBUG] Entry creado: {entry}")
        municipios_pueblos.append(entry)
        time.sleep(1)

    print(f"[DEBUG] Guardando {len(municipios_pueblos)} municipios en JSON")
    with open(OUTPUT_PUEBLOS_JSON, 'w', encoding='utf-8') as f:
        json.dump(municipios_pueblos, f, ensure_ascii=False, indent=2)
    dump_error_log(ERROR_LOG_FILE)
    print("[DEBUG] main: finalizado programa")

if __name__ == '__main__':
    main()

# main.py
import json
import time
from urllib.parse import urljoin

from extractors import (
    extract_municipios,
    extract_municipio_structure,
    extract_barrio_info_with_llm
)
from scraper import fetch_url
from config import ROOT_CATEGORY_URL, OUTPUT_JSON, ERROR_LOG_FILE, BASE_WIKI_URL
from logger import dump_error_log, log_error

def main():
    # 0) Preguntar si reanudar desde un municipio concreto
    resume_input = input("¿Desde qué municipio (índice) quieres reanudar? (ENTER para 1): ").strip()
    start_idx = int(resume_input) if resume_input.isdigit() and int(resume_input) > 0 else 1

    # 1) Obtener lista de municipios
    print("🔍 Extrayendo municipios de la categoría raíz...")
    root_html = fetch_url(ROOT_CATEGORY_URL)
    municipios = extract_municipios(root_html)
    total_mun = len(municipios)
    if start_idx > total_mun:
        print(f"El índice {start_idx} excede el total de municipios ({total_mun}). Abortando.")
        return

    print(f"➡️  {total_mun} municipios encontrados. Comenzando en el índice {start_idx}.\n")

    resultados = []

    # 2) Para cada municipio, parsear distritos y barrios
    for idx, mun in enumerate(municipios[start_idx-1:], start=start_idx):
        nombre = mun.get('municipio_nombre')
        url_cat = mun.get('municipio_category_url')
        print(f"[{idx}/{total_mun}] Procesando municipio: {nombre}")
        if not url_cat:
            log_error(f"Sin URL categoría para {nombre}")
            print("  ❌ Sin URL de categoría, saltando.\n")
            continue

        # Convertir a URL absoluta y bajar el HTML
        full_cat_url = urljoin(BASE_WIKI_URL, url_cat)
        html_cat = fetch_url(full_cat_url)

        estructura = extract_municipio_structure(html_cat)
        distritos = estructura.get('distritos', [])
        barrios_directos = estructura.get('barrios', [])
        print(f"   • Distritos encontrados: {len(distritos)}")
        print(f"   • Barrios directos encontrados: {len(barrios_directos)}")

        entry = {
            'municipio_nombre': nombre,
            'municipio_category_url': full_cat_url,
            'distritos': distritos,
            'barrios': []
        }

        # 3) Detalles de cada barrio
        for jdx, barrio in enumerate(barrios_directos, start=1):
            bname = barrio.get('nombre')
            art_url = barrio.get('article_url')
            print(f"    - [{jdx}/{len(barrios_directos)}] Barrio: {bname}")
            if not art_url:
                log_error(f"Sin URL de artículo para barrio {bname} en {nombre}")
                print("       ❌ Sin URL de artículo, omitiendo.\n")
                continue

            html_b = fetch_url(art_url)

            # Reintentos si el modelo está caído
            while True:
                detalles = extract_barrio_info_with_llm(bname, html_b, nombre)
                if detalles.get('error') == 'model_down':
                    log_error(f"LLM caído procesando {bname}", 
                              context={'municipio': nombre, 'barrio': bname})
                    respuesta = input(
                        "El modelo no responde. ¿Está operativo ahora? (s/n): "
                    ).strip().lower()
                    if respuesta == 's':
                        continue  # reintentar mismo barrio
                    else:
                        print("Abortando ejecución.")
                        dump_error_log(ERROR_LOG_FILE)
                        return
                break

            # Si el LLM indica no es barrio válido, omitimos
            if detalles.get('error') == 'not_a_barrio':
                reason = detalles.get('reason')
                log_error(
                    f"Omitiendo {bname}: {reason}", 
                    context={'municipio': nombre, 'barrio': bname}
                )
                print(f"       ⚠️ No es barrio válido: {reason}\n")
                continue

            # Merge de datos básicos y detalles
            barrio_entry = {
                'nombre': bname,
                'article_url': art_url,
                **detalles
            }
            entry['barrios'].append(barrio_entry)
            print("       ✅ Detalles extraídos.\n")
            time.sleep(1)

        resultados.append(entry)
        print(f"✅ Finalizado municipio: {nombre}\n")
        time.sleep(2)

    # 4) Guardar resultados finales
    print("💾 Guardando JSON final...")
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"✅ Datos guardados en {OUTPUT_JSON}")

    # 5) Volcar log de errores
    print("📋 Volcando log de errores...")
    dump_error_log(ERROR_LOG_FILE)
    print(f"✅ Errores (si hay) en {ERROR_LOG_FILE}")

if __name__ == '__main__':
    main()

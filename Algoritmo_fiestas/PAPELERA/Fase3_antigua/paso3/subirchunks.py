import requests
import json
import sys
import time
import concurrent.futures

# Configuraciones (ajusta estos valores)
API_KEY = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'  # Tu clave de API real
DATASET_ID = '579014f6-3bc1-4b19-8087-9d77623c2c56'  # Tu dataset ID real
DOCUMENT_ID = '00fc7f8c-5b6d-4cf8-a0f2-75f73a6fe235'   # El ID del documento destino
DIFY_URL = 'http://localhost:80'  # Asegúrate de que este es el puerto correcto

# Headers de autenticación.
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {API_KEY}'
}

def cargar_chunks(archivo):
    """
    Lee el archivo JSON Lines y retorna una lista con el contenido de cada chunk.
    Se intenta primero con la clave "text" y, de no existir, con "markdown".
    """
    lista_chunks = []
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                try:
                    data_line = json.loads(line)
                    # Intentamos obtener el contenido con la clave 'text'; si no, 'markdown'
                    chunk_text = data_line.get('text') or data_line.get('markdown')
                    if chunk_text and chunk_text.strip():
                        lista_chunks.append(chunk_text.strip())
                    else:
                        print(f"Advertencia: Línea {line_num} sin contenido válido. Se omitirá.", file=sys.stderr)
                except json.JSONDecodeError as e:
                    print(f"Error al decodificar JSON en línea {line_num}: {e}", file=sys.stderr)
    except FileNotFoundError:
        print(f"Error: El archivo {archivo} no existe.", file=sys.stderr)
        sys.exit(1)
    return lista_chunks

def send_batch(url, headers, payload, start, end):
    """
    Envía un lote de chunks y retorna el resultado junto con el rango.
    """
    response = requests.post(url, headers=headers, json=payload)
    return (start, end, response)

def agregar_chunks_al_documento_concurrente(dataset_id, document_id, chunks, max_chunks_per_request=20, max_workers=5):
    """
    Agrega los chunks al documento destino en lotes de forma concurrente.
    Usa un ThreadPoolExecutor para enviar varios lotes a la vez.
    """
    url = f"{DIFY_URL}/v1/datasets/{dataset_id}/documents/{document_id}/segments"
    total = len(chunks)
    print(f"Total de chunks a enviar: {total}")
    
    batches = []
    for i in range(0, total, max_chunks_per_request):
        lote = chunks[i:i + max_chunks_per_request]
        segments = [{"content": chunk} for chunk in lote]
        payload = {"segments": segments}
        batches.append((i, i + len(lote), payload))
    
    # Enviar lotes concurrentemente
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(send_batch, url, headers, payload, start, end): (start, end)
            for start, end, payload in batches
        }
        for future in concurrent.futures.as_completed(future_to_batch):
            start, end = future_to_batch[future]
            try:
                s, e, response = future.result()
                print(f"\nEnviando chunks del {s+1} al {e}:")
                print(f"Código de estado: {response.status_code}")
                print("Respuesta:", response.text)
                if response.status_code not in [200, 201]:
                    print(f"Error al agregar chunks del {s+1} al {e}.", file=sys.stderr)
            except Exception as exc:
                print(f"Excepción al enviar chunks del {start+1} al {end}: {exc}", file=sys.stderr)

if __name__ == '__main__':
    archivo_chunks = "../paso2/chunks_for_dify.jsonl"  # Nombre del archivo con los chunks generados
    chunks = cargar_chunks(archivo_chunks)
    if not chunks:
        print("No se encontraron chunks válidos en el archivo.", file=sys.stderr)
        sys.exit(1)
    
    agregar_chunks_al_documento_concurrente(DATASET_ID, DOCUMENT_ID, chunks)
    print("\nProceso de subida de chunks completado.")

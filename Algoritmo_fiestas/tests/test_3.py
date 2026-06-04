import requests
import json
import sys
import time

# Configuraciones (ajusta estos valores)
API_KEY = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'  # Tu clave de API real
DATASET_ID = '579014f6-3bc1-4b19-8087-9d77623c2c56'  # Tu dataset ID real
DOCUMENT_ID = 'cedbb1aa-ce36-4431-8a7e-49fdead00886'   # El ID del documento destino
DIFY_URL = 'http://localhost:80'  # Asegúrate de que este es el puerto correcto

# Headers de autenticación
# Dependiendo de la API, puede que debas usar "Authorization: Bearer ..." o "api-key".
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {API_KEY}'
    # Si la API espera 'api-key' en lugar de 'Authorization', usa:
    # 'api-key': API_KEY
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

def agregar_chunks_al_documento(dataset_id, document_id, chunks, max_chunks_per_request=20):
    """
    Agrega los chunks al documento destino en lotes, usando el endpoint indicado en la documentación:
    POST /datasets/{dataset_id}/documents/{document_id}/segments
    """
    # IMPORTANTE: Usa f-string para interpolar correctamente las variables en la URL.
    url = f"{DIFY_URL}/v1/datasets/{dataset_id}/documents/{document_id}/segments"
    total = len(chunks)
    print(f"Total de chunks a enviar: {total}")
    
    for i in range(0, total, max_chunks_per_request):
        lote = chunks[i:i + max_chunks_per_request]
        segments = [{"content": chunk} for chunk in lote]
        payload = {"segments": segments}
        
        print(f"\nEnviando chunks del {i+1} al {i+len(lote)}:")
        print("URL:", url)
        print("Headers:", headers)
        print("Payload:", json.dumps(payload, indent=2, ensure_ascii=False))
        
        response = requests.post(url, headers=headers, json=payload)
        print(f"Código de estado: {response.status_code}")
        print("Respuesta:", response.text)
        
        if response.status_code not in [200, 201]:
            print(f"Error al agregar chunks del {i+1} al {i+len(lote)}. Deteniendo el proceso.", file=sys.stderr)
            break
        
        # Pausa para evitar sobrecargar la API (ajusta si es necesario)
        time.sleep(1)

if __name__ == '__main__':
    archivo_chunks = "chunks_for_dify.jsonl"  # Asegúrate de que este es el nombre correcto del archivo con los chunks
    chunks = cargar_chunks(archivo_chunks)
    if not chunks:
        print("No se encontraron chunks válidos en el archivo.", file=sys.stderr)
        sys.exit(1)
    
    agregar_chunks_al_documento(DATASET_ID, DOCUMENT_ID, chunks)
    print("\nProceso de subida de chunks completado.")

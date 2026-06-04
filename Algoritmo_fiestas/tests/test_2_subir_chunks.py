import requests
import json

# Configuraciones
API_KEY = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'  # Reemplaza con tu clave de API real
DATASET_ID = '105364df-8098-4db9-abcc-e98e2990cee7'
DIFY_URL = 'http://localhost'  # Ajusta el puerto si es necesario

# Headers de autenticación
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {API_KEY}'  # O 'api-key': API_KEY si la API lo requiere
}

# Lista de chunks obtenidos tras el RAG
lista_de_chunks = [
    "Chunk 1: Información sobre servicios municipales...",
    "Chunk 2: Detalles de los eventos culturales...",
    # Agrega todos los chunks que tengas
]

def crear_documento():
    url = 'http://localhost/v1/datasets/105364df-8098-4db9-abcc-e98e2990cee7/document/create-by-text'

    data = {
        "data_source": "upload",
        "name": "Documento de Información Municipal",
        "text": "",  # Si la API lo requiere, puedes proporcionar el texto completo aquí
        "segment_rule": {
            "mode": "automatic"
        }
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        documento = response.json()
        document_id = documento['data']['document_id']
        print(f"Documento creado exitosamente. ID: {document_id}")
        return document_id
    else:
        print(f"Error al crear el documento: {response.status_code} - {response.text}")
        return None

def subir_segmentos(document_id):
    url = f'{DIFY_URL}/datasets/{DATASET_ID}/documents/{document_id}/segments'

    for idx, chunk in enumerate(lista_de_chunks):
        data = {
            "text": chunk,
            "order": idx,  # Mantiene el orden de los chunks
            "metadata": {
                "titulo": "Información Municipal",
                "fuente": "https://www.ejemplo-ayuntamiento.es",
                "fecha": "2023-10-20"
            }
        }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code in [200, 201]:
            print(f"Segmento {idx+1} subido exitosamente.")
        else:
            print(f"Error al subir el segmento {idx+1}: {response.status_code} - {response.text}")

if __name__ == '__main__':
    document_id = crear_documento()
    if document_id:
        subir_segmentos(document_id)
    else:
        print("No se pudo crear el documento, abortando el proceso de subida de segmentos.")

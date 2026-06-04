import requests
import json

# Configuraciones
API_KEY = 'dataset-yLsC4O4NgRwqFSTbkIkwuJuA'  # Reemplaza con tu clave de API real
KNOWLEDGE_BASE_ID = '105364df-8098-4db9-abcc-e98e2990cee7'
DIFY_URL = 'http://localhost:80'  # Reemplaza PORT con el puerto correcto

# Headers de autenticación
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {API_KEY}'
}

# Lista de chunks obtenidos tras el RAG
lista_de_chunks = [
    "Chunk 1: Información sobre servicios municipales...",
    "Chunk 2: Detalles de los eventos culturales...",
    # Agrega todos los chunks que tengas
]

# Función para subir los chunks
def subir_chunks():
    documentos = []
    for chunk in lista_de_chunks:
        documento = {
            "content": chunk,
            "metadata": {
                "titulo": "Información Municipal",
                "fuente": "https://www.ejemplo-ayuntamiento.es",
                "fecha": "2023-10-20"
            }
        }
        documentos.append(documento)

    data = {
        "documents": documentos
    }

    url = "http://localhost/datasets/105364df-8098-4db9-abcc-e98e2990cee7/documents"

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code in [200, 201]:
        print("Chunks subidos exitosamente a la Knowledge Base.")
    else:
        print(f"Error al subir chunks: {response.status_code} - {response.text}")

if __name__ == '__main__':
    subir_chunks()

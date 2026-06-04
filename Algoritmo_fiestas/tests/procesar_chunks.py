import os
import json
import nltk
import markdown
from bs4 import BeautifulSoup
from nltk.tokenize import sent_tokenize



def convertir_markdown_a_texto(markdown_text):
    """
    Convierte un texto en Markdown a texto plano eliminando etiquetas HTML innecesarias.
    """
    html = markdown.markdown(markdown_text)
    soup = BeautifulSoup(html, 'html.parser')
    # Eliminar elementos que no interesan
    for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
        element.decompose()
    text = soup.get_text(separator=' ')
    # Limpiar líneas vacías y espacios extra
    lines = (line.strip() for line in text.splitlines())
    texto_limpio = ' '.join(line for line in lines if line)
    return texto_limpio

def cargar_y_procesar_data_json_contenido(archivo):
    """
    Carga el contenido del archivo JSONL generado por Scrapy y convierte el contenido Markdown a texto.
    """
    textos = []
    with open(archivo, 'r', encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            if 'markdown' in item and item['markdown']:
                texto_markdown = item['markdown']
                texto = convertir_markdown_a_texto(texto_markdown)
                textos.append(texto)
    return textos

def dividir_en_chunks(documentos, tamaño_chunk=500, solapamiento=50):
    """
    Divide una lista de documentos en chunks basados en oraciones.
    - tamaño_chunk: número máximo de palabras por chunk.
    - solapamiento: número de oraciones que se mantienen para solapar entre chunks.
    """
    chunks = []
    for doc in documentos:
        oraciones = sent_tokenize(doc)
        current_chunk = []
        current_length = 0
        for oracion in oraciones:
            palabras_oracion = oracion.split()
            if current_length + len(palabras_oracion) <= tamaño_chunk:
                current_chunk.append(oracion)
                current_length += len(palabras_oracion)
            else:
                if current_chunk:
                    chunk_text = ' '.join(current_chunk)
                    chunks.append(chunk_text)
                    # Solapamiento: mantener las últimas 'solapamiento' oraciones
                    overlap = current_chunk[-solapamiento:] if solapamiento < len(current_chunk) else current_chunk
                    current_chunk = overlap + [oracion]
                    current_length = sum(len(s.split()) for s in current_chunk)
                else:
                    # Caso en el que una oración es demasiado larga
                    chunks.append(oracion)
                    current_chunk = []
                    current_length = 0
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append(chunk_text)
    return chunks

def main():
    input_file = "scraped_output.jl"
    output_file = "chunks_for_dify.jsonl"
    
    if not os.path.exists(input_file):
        print(f"El archivo {input_file} no existe. Asegúrate de haber corrido el scraper primero.")
        return

    # Cargar y procesar el contenido extraído
    documentos = cargar_y_procesar_data_json_contenido(input_file)
    print(f"Se han cargado {len(documentos)} documentos.")

    # Dividir los documentos en chunks
    chunks = dividir_en_chunks(documentos, tamaño_chunk=500, solapamiento=50)
    print(f"Se han creado {len(chunks)} chunks.")

    # Guardar los chunks en un archivo JSONL
    with open(output_file, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(chunks):
            chunk_data = {"id": idx, "text": chunk}
            json.dump(chunk_data, f, ensure_ascii=False)
            f.write("\n")
    print(f"Chunks guardados en {output_file}")

if __name__ == "__main__":
    main()

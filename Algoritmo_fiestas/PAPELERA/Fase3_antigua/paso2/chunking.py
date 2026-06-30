import os
import json
import nltk
import markdown
import hashlib
import re
from bs4 import BeautifulSoup
from nltk.tokenize import sent_tokenize
from tqdm import tqdm

# Descargar recursos necesarios de NLTK (si no se han descargado previamente)
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

#############################################
# FUNCIONES DE PROCESAMIENTO Y EXTRACCIÓN DE CONTEXTO
#############################################

def convertir_markdown_a_texto(markdown_text):
    """
    Convierte un texto en Markdown a texto plano eliminando etiquetas HTML no deseadas.
    """
    html = markdown.markdown(markdown_text)
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
        element.decompose()
    text = soup.get_text(separator=' ')
    lines = (line.strip() for line in text.splitlines())
    return ' '.join(line for line in lines if line)

def cargar_y_procesar_data_json_contenido(archivo):
    """
    Carga el contenido del archivo JSONL generado por el scraper y convierte el contenido Markdown a texto.
    Se filtran documentos duplicados basándose en la URL (si existe) o en un hash MD5 del contenido.
    """
    textos = []
    seen_docs = set()
    with open(archivo, 'r', encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            identifier = item.get('url')
            if identifier is None:
                identifier = hashlib.md5(item.get('markdown', '').encode('utf-8')).hexdigest()
            if identifier in seen_docs:
                continue
            seen_docs.add(identifier)
            if 'markdown' in item and item['markdown']:
                texto = convertir_markdown_a_texto(item['markdown'])
                textos.append(texto)
    return textos

def dividir_en_chunks(documentos, tamaño_chunk=500, solapamiento=1):
    """
    Divide cada documento en chunks basados en oraciones.
      - tamaño_chunk: número máximo de palabras por chunk.
      - solapamiento: número mínimo de oraciones que se mantienen para solapar entre chunks.
    Se utiliza un conjunto para evitar agregar chunks duplicados.
    """
    chunks = []
    seen_chunks = set()
    for doc in tqdm(documentos, desc="Dividiendo documentos en chunks"):
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
                    chunk_text = ' '.join(current_chunk).strip()
                    # Agregar solo si no se ha creado antes
                    if chunk_text not in seen_chunks:
                        chunks.append(chunk_text)
                        seen_chunks.add(chunk_text)
                    # Mantener solapamiento mínimo
                    overlap = current_chunk[-solapamiento:] if solapamiento < len(current_chunk) else current_chunk
                    current_chunk = overlap + [oracion]
                    current_length = sum(len(s.split()) for s in current_chunk)
                else:
                    chunk_text = oracion.strip()
                    if chunk_text not in seen_chunks:
                        chunks.append(chunk_text)
                        seen_chunks.add(chunk_text)
                    current_chunk = []
                    current_length = 0
        if current_chunk:
            chunk_text = ' '.join(current_chunk).strip()
            if chunk_text not in seen_chunks:
                chunks.append(chunk_text)
                seen_chunks.add(chunk_text)
    return chunks

def deduplicate_chunks(chunks):
    """
    Elimina chunks duplicados utilizando una versión normalizada del texto.
    Se normaliza pasando a minúsculas, eliminando caracteres no alfanuméricos y espacios redundantes.
    """
    deduped = []
    seen = set()
    for chunk in tqdm(chunks, desc="Deduplicando chunks"):
        normalized = re.sub(r'\W+', ' ', chunk.lower()).strip()
        if normalized not in seen:
            deduped.append(chunk)
            seen.add(normalized)
    return deduped

def guardar_chunks(chunks, archivo_salida="chunks_for_dify.jsonl"):
    """
    Guarda la lista de chunks en un archivo JSONL.
    Cada línea tendrá la estructura: {"id": index, "text": chunk}
    """
    with open(archivo_salida, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(tqdm(chunks, desc="Guardando chunks")):
            chunk_data = {"id": idx, "text": chunk}
            json.dump(chunk_data, f, ensure_ascii=False)
            f.write("\n")
    print(f"Chunks guardados en {archivo_salida}")

def main():
    archivo_input = "../paso1/scraped_output.jl"
    if not os.path.exists(archivo_input):
        raise FileNotFoundError("No se encontró el archivo de salida del scraping.")

    # Cargar y filtrar documentos duplicados
    documentos = cargar_y_procesar_data_json_contenido(archivo_input)
    print(f"Se han cargado {len(documentos)} documentos (sin duplicados).")

    # Dividir documentos en chunks con solapamiento mínimo
    chunks = dividir_en_chunks(documentos, tamaño_chunk=500, solapamiento=1)
    print(f"Se han creado {len(chunks)} chunks (previa deduplicación durante la creación).")

    # Aplicar deduplicación adicional (por si quedan variaciones menores)
    chunks = deduplicate_chunks(chunks)
    print(f"Se han quedado {len(chunks)} chunks después de la deduplicación final.")

    # Guardar los chunks resultantes
    guardar_chunks(chunks)

if __name__ == "__main__":
    main()

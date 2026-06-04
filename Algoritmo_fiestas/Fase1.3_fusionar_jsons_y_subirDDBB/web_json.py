import json
import psycopg2
import re
import unicodedata

# Configuración de la base de datos
DB_NAME = "tu_basedatos"
DB_USER = "tu_usuario"
DB_PASSWORD = "tu_contraseña"
DB_HOST = "localhost"
DB_PORT = "5432"

# Función para normalizar nombres
def normalizar_nombre(nombre):
    if not nombre:
        return ""
    nombre = nombre.lower()
    nombre = unicodedata.normalize('NFD', nombre)
    nombre = nombre.encode('ascii', 'ignore').decode('utf-8')
    nombre = re.sub(r'[()\-_,.]', '', nombre)
    nombre = re.sub(r'\b(el|la|los|las|de|del|y|en)\b', '', nombre)
    nombre = re.sub(r'\s+', ' ', nombre).strip()
    return nombre

# Cargar JSON de webs
with open('webs_municipios.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

municipios_web = data.get("municipalities", [])

# Conexión a la base de datos
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT
)
cur = conn.cursor()

# Crear índice temporal de municipios ya en la base de datos
cur.execute("SELECT id, nombre FROM municipio")
municipios_en_db = cur.fetchall()
index_db = {
    normalizar_nombre(nombre): (id_, nombre)
    for id_, nombre in municipios_en_db
}

# Recorrer municipios del JSON y procesar
for m in municipios_web:
    nombre_original = m.get("municipio")
    web = m.get("official_website")

    # Validaciones
    if not nombre_original or nombre_original.startswith("Q"):  # descartar sin nombre
        continue
    if not web or web.lower().startswith("no official website"):
        continue

    nombre_normalizado = normalizar_nombre(nombre_original)

    if nombre_normalizado in index_db:
        # Municipio ya existe -> actualizar web
        id_muni, _ = index_db[nombre_normalizado]
        cur.execute("""
            UPDATE municipio SET web_url = %s WHERE id = %s
        """, (web.strip(), id_muni))
    else:
        # Municipio nuevo con web válida -> insertar
        cur.execute("""
            INSERT INTO municipio (nombre, category_url, web_url)
            VALUES (%s, %s, %s)
        """, (nombre_original.strip(), None, web.strip()))

# Guardar y cerrar
conn.commit()
cur.close()
conn.close()
print("Actualización de webs completada correctamente.")

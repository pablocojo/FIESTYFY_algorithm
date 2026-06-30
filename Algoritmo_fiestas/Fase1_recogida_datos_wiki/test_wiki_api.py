import urllib.parse
import requests

ciudad = 'La Roda'
titulos_posibles = [
    f"Anexo:Barrios de {ciudad}",
    f"Categoría:Barrios de {ciudad}",
    f"Barrios de {ciudad}",
    f"Anexo:Distritos de {ciudad}",
    f"Categoría:Distritos de {ciudad}",
    f"Distritos de {ciudad}",
    f"Anexo:Pedanías de {ciudad}",
    f"Categoría:Pedanías de {ciudad}",
    f"Pedanías de {ciudad}",
    f"Organización territorial de {ciudad}"
]

url = "https://es.wikipedia.org/w/api.php"
headers = {"User-Agent": "FiestyfyBot/1.0 (test@gmail.com)"}
params = {
    "action": "query",
    "titles": "|".join(titulos_posibles),
    "format": "json"
}

resp = requests.get(url, params=params, headers=headers)
data = resp.json()

for page_id, page_info in data.get("query", {}).get("pages", {}).items():
    if "missing" not in page_info:
        print("FOUND:", page_info["title"])

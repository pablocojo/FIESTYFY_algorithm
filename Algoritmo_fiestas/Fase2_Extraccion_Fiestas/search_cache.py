import os
import json

cache_dir = "caches/municipios"
found = False

for file in os.listdir(cache_dir):
    if "amurrio" in file.lower():
        with open(os.path.join(cache_dir, file), "r", encoding="utf-8") as f:
            data = json.load(f)
            docs = data.get("documentos", [])
            print(f"File {file} has {len(docs)} documents.")
            
            san_roque_mentions = 0
            for i, d in enumerate(docs):
                txt = d.get("texto", "")
                if "san roque" in txt.lower():
                    san_roque_mentions += 1
                    # print snippet
                    idx = txt.lower().find("san roque")
                    print(f"  Doc {i} ({d.get('url', '')}): ... {txt[max(0, idx-30):min(len(txt), idx+50)]} ...")
            print(f"Total documents with 'san roque': {san_roque_mentions}")
            found = True
if not found:
    print("No cache found for amurrio.")

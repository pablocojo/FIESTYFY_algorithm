import json

try:
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\lugares_espana.json', 'r', encoding='utf-8') as f:
        data_esp = json.load(f)
    ultimos = [l for l in data_esp['lugares'] if l.get('tipo') == 'municipio']
    ultimo = ultimos[-1]
    last_id = ultimo.get('original_id') or ultimo.get('id')
    print(f"Ultimo procesado en lugares_espana.json: {ultimo.get('nombre')} (id: {last_id})")
    
    with open(r'c:\Users\Usuario\PROYECTOS\DEV-FIESTYFY_0426\FIESTYFY_algorithm\Algoritmo_fiestas\Fase1_recogida_datos_wiki\municipios.json', 'r', encoding='utf-8') as f:
        data_muni = json.load(f)
    municipios_wiki = data_muni['lugares']
    
    start_idx = -1
    for i, m in enumerate(municipios_wiki):
        if m.get('id') == last_id:
            start_idx = i + 2
            break
            
    print(f"main2.py se reanudara en el indice: {start_idx} (Elemento: {municipios_wiki[start_idx-1].get('nombre')})")
    
    print("Posicion de saltados famosos en municipios.json:")
    for m in ['Busot', 'Jalón', 'Ibiza', 'Alaró']:
        for i, w in enumerate(municipios_wiki):
            if w.get('nombre') == m:
                print(f" - {m} esta en indice: {i+1}")
                break
except Exception as e:
    print('Error:', e)

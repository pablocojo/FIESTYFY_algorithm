import json

def check():
    with open('lugares_espana.json', encoding='utf-8') as f:
        data = json.load(f).get('lugares', [])
    
    ali = [d for d in data if d.get('id')=='alicante' or d.get('padre_id')=='alicante' or d.get('abuelo_id')=='alicante']
    
    distritos = [d for d in ali if d.get('tipo') == 'distrito']
    barrios = [d for d in ali if d.get('tipo') == 'barrio']
    pedanias = [d for d in ali if d.get('tipo') == 'pedania']
    
    print(f"Total: {len(ali)} (Distritos: {len(distritos)}, Barrios: {len(barrios)}, Pedanias: {len(pedanias)})")
    for d in ali:
        p_name = d.get('parent_nombre') or d.get('padre_id')
        print(f"[{d.get('tipo')}] {d.get('nombre')} (Padre: {p_name})")

if __name__ == '__main__':
    check()

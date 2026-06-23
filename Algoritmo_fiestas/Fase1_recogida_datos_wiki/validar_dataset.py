#!/usr/bin/env python3
"""
Script de validación para dataset lugares_espana.json.
Verifica estructura, campos, relaciones padre-hijo, imágenes, etc.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

from place_types import valida_dataset, valida_lugar
from config import OUTPUT_JSON


def cargar_json(filepath: str) -> dict:
    """Carga JSON del archivo."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Archivo no encontrado: {filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ JSON inválido: {e}")
        sys.exit(1)


def verificar_urls_imagenes(dataset: dict, muestreo: int = 5) -> dict:
    """
    Verifica accesibilidad de URLs de imágenes (con muestreo).
    
    Args:
        dataset: Dict con 'lugares'
        muestreo: Cantidad de lugares a verificar (random)
    
    Returns:
        {'validas': int, 'invalidas': int, 'errores': list}
    """
    import random
    
    lugares = dataset.get('lugares', [])
    if not lugares:
        return {'validas': 0, 'invalidas': 0, 'errores': []}
    
    # Muestrear lugares
    muestra = random.sample(lugares, min(muestreo, len(lugares)))
    
    resultados = {'validas': 0, 'invalidas': 0, 'errores': []}
    
    print(f"\n📸 Verificando {len(muestra)} URLs de imágenes (muestreo)...")
    
    for lugar in muestra:
        nombre = lugar.get('nombre', '?')
        imagenes = lugar.get('imagenes', {})
        
        for tipo, url in imagenes.items():
            if not url:
                resultados['errores'].append(f"{nombre}: {tipo} vacío")
                continue
            
            try:
                # Hacer HEAD request
                response = urlopen(url, timeout=5)
                if response.status == 200:
                    resultados['validas'] += 1
                    print(f"  ✅ {nombre}/{tipo}")
                else:
                    resultados['invalidas'] += 1
                    resultados['errores'].append(f"{nombre}: {tipo} → HTTP {response.status}")
                    print(f"  ⚠️  {nombre}/{tipo} → HTTP {response.status}")
            except URLError as e:
                resultados['invalidas'] += 1
                resultados['errores'].append(f"{nombre}: {tipo} → {str(e)[:50]}")
                print(f"  ❌ {nombre}/{tipo} → Error")
            except Exception as e:
                resultados['errores'].append(f"{nombre}: {tipo} → Error inesperado")
    
    return resultados


def estadisticas_dataset(dataset: dict) -> dict:
    """Calcula estadísticas del dataset."""
    lugares = dataset.get('lugares', [])
    
    stats = {
        'total_lugares': len(lugares),
        'por_tipo': {},
        'poblacion_total': 0,
        'provincia_unica': set(),
        'comunidad_unica': set(),
        'sin_poblacion': 0,
        'sin_provincia': 0,
        'sin_comunidad': 0,
        'sin_coords': 0,
    }
    
    for lugar in lugares:
        tipo = lugar.get('tipo', 'desconocido')
        stats['por_tipo'][tipo] = stats['por_tipo'].get(tipo, 0) + 1
        
        pob = lugar.get('poblacion', 0)
        if pob:
            stats['poblacion_total'] += pob
        else:
            stats['sin_poblacion'] += 1
        
        prov = lugar.get('provincia', '')
        if prov:
            stats['provincia_unica'].add(prov)
        else:
            stats['sin_provincia'] += 1
        
        comm = lugar.get('comunidad', '')
        if comm:
            stats['comunidad_unica'].add(comm)
        else:
            stats['sin_comunidad'] += 1
        
        if not lugar.get('lat') or not lugar.get('lng'):
            stats['sin_coords'] += 1
    
    stats['provincia_unica'] = len(stats['provincia_unica'])
    stats['comunidad_unica'] = len(stats['comunidad_unica'])
    
    return stats


def main():
    """Función principal."""
    print("\n" + "=" * 70)
    print(" VALIDADOR DE DATASET LUGARES_ESPAÑA.JSON")
    print("=" * 70 + "\n")
    
    # 1) Cargar JSON
    print(f"📂 Cargando {OUTPUT_JSON}...")
    dataset = cargar_json(OUTPUT_JSON)
    print("✅ JSON cargado correctamente\n")
    
    # 2) Validación estructural
    print("🔍 Validando estructura...\n")
    es_valido, errores = valida_dataset(dataset)
    
    if es_valido:
        print("✅ Estructura completamente válida\n")
    else:
        print(f"❌ Errores encontrados ({len(errores)}):\n")
        for err in errores[:20]:
            print(f"   - {err}")
        if len(errores) > 20:
            print(f"   ... y {len(errores) - 20} más\n")
        print()
    
    # 3) Estadísticas
    print("📊 Estadísticas del dataset:\n")
    stats = estadisticas_dataset(dataset)
    print(f"   Total de lugares: {stats['total_lugares']}")
    print(f"   Población total: {stats['poblacion_total']:,}")
    print(f"   Provincias: {stats['provincia_unica']}")
    print(f"   Comunidades: {stats['comunidad_unica']}")
    print()
    print("   Por tipo:")
    for tipo, cantidad in sorted(stats['por_tipo'].items()):
        print(f"      - {tipo}: {cantidad}")
    print()
    
    # 4) Validación de integridad
    print("🔗 Validación de integridad:\n")
    
    # IDs únicos
    ids_lugares = [l.get('id') for l in dataset.get('lugares', [])]
    ids_duplicados = [id for id in set(ids_lugares) if ids_lugares.count(id) > 1]
    if ids_duplicados:
        print(f"   ❌ IDs duplicados: {ids_duplicados}")
    else:
        print(f"   ✅ Todos los IDs son únicos")
    
    # Relaciones padre_id
    ids_padres_validos = set(ids_lugares)
    for lugar in dataset.get('lugares', []):
        if 'padre_id' in lugar and lugar['padre_id']:
            padre_id = lugar['padre_id']
            if padre_id not in ids_padres_validos:
                print(f"   ❌ {lugar.get('nombre')}: padre_id '{padre_id}' no existe")
    
    print()
    
    # 5) Muestreo de URLs (opcional)
    respuesta = input("¿Verificar URLs de imágenes? (s/n): ").strip().lower()
    if respuesta == 's':
        verificar_urls_imagenes(dataset, muestreo=10)
    
    # 6) Resumen
    print("\n" + "=" * 70)
    if es_valido and not ids_duplicados:
        print(" ✅ DATASET VÁLIDO Y LISTO")
    else:
        print(" ⚠️  DATASET CON ERRORES - REVISAR ARRIBA")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()

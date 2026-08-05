import sys
import logging
import os
import io

# Forzamos la codificación estándar a UTF-8 para CMD en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Importamos nuestra lógica recién creada
from llm_processor.text_analyzer import process_translation_pipeline, _LID_MODEL

# Configurar un logger básico para ver los pasos por pantalla
logging.basicConfig(level=logging.INFO, format="%(message)s")

print("\n" + "="*50)
print("   PRUEBA DE PIPELINE MULTILINGÜE AISLADO")
print("="*50)

if _LID_MODEL is None:
    print("\n❌ ERROR: El modelo FastText (lid.176.ftz) no se cargó correctamente.")
    print("Asegúrate de que el archivo lid.176.ftz está en la misma carpeta.")
    sys.exit(1)
else:
    print("\n✅ FastText cargado correctamente.\n")


# ---------------------------------------------------------
# TEST 1: VALENCIANO (Debe llamar a WSL Apertium)
# ---------------------------------------------------------
municipio_valencia = {
    "nombre": "Sueca",
    "comunidad_autonoma": "Comunidad Valenciana",
    "provincia": "Valencia"
}

texto_valenciano = """===== FUENTE: WEB OFICIAL =====
Les Festes Majors de Sueca se celebren al setembre. Enguany tindrem orquestra, focs artificials i cercavila pels carrers del poble."""

print("▶️  TEST 1: VALENCIANO (FastText -> WSL Apertium)")
print("-" * 50)
print("ORIGINAL:")
print(texto_valenciano)
print("-" * 50)
resultado_val = process_translation_pipeline(texto_valenciano, municipio_valencia)
print("TRADUCCIÓN:")
print(resultado_val)
print("="*50 + "\n")


# ---------------------------------------------------------
# TEST 2: GALLEGO (Debe llamar a Transformers Opus-MT)
# ---------------------------------------------------------
municipio_galicia = {
    "nombre": "Rianxo",
    "comunidad_autonoma": "Galicia",
    "provincia": "A Coruña"
}

texto_gallego = """===== FUENTE: RESULTADOS DE BUSCADOR =====
As festas da Guadalupe contarán cun programa cheo de concertos, verbenas e unha gran romaría tradicional no centro da vila."""

print("▶️  TEST 2: GALLEGO (FastText -> HuggingFace Opus-MT)")
print("-" * 50)
print("ORIGINAL:")
print(texto_gallego)
print("-" * 50)
resultado_gal = process_translation_pipeline(texto_gallego, municipio_galicia)
print("TRADUCCIÓN:")
print(resultado_gal)
print("="*50 + "\n")

print("¡Pruebas finalizadas con éxito!")

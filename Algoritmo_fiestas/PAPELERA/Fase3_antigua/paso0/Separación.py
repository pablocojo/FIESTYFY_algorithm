import os
import sys
import subprocess

def main(texto):
    """
    Elige entre solo_main.py o compuesto_main.py según contenga 'está solo'.
    Ambos scripts viven en Fase3_busqueda_fiestas_WebScraper/main/.
    """
    base_dir    = os.path.dirname(__file__)
    main_dir    = os.path.join(base_dir, '..', 'main')
    solo_script = os.path.join(main_dir, 'solo_main.py')
    comp_script = os.path.join(main_dir, 'compuesto_main.py')

    # Si el texto incluye 'está solo', lanzamos solo_main
    target = solo_script if "está solo" in texto else comp_script

    subprocess.run([sys.executable, target, texto], check=True)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python Separación.py \"<texto>\"")
        sys.exit(1)
    texto = " ".join(sys.argv[1:])
    main(texto)

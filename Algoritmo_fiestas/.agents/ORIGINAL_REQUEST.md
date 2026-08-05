# Original User Request

## Initial Request — 2026-08-02T11:22:17Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Execute the Teamwork project

Implementar un mapeo dinámico de fuentes de prensa local por provincia en `fuentes.py` e inyectar búsquedas específicas para captar fiestas de pedanías, garantizando el uso exclusivo de medios confiables y enriquecidos.

Working directory: c:/Users/Usuario/PROYECTOS/DEV-FIESTYFY_0426/FIESTYFY_algorithm/Algoritmo_fiestas/Fase2_Extraccion_Fiestas

## Requirements

### R1. Diccionario de Prensa Confiable por Provincia
Definir en `fuentes.py` una estructura de datos que asocie los códigos postales/IDs de provincia (los 2 primeros dígitos del `lugar_id`) con una lista depurada de medios locales y regionales de alta fiabilidad.

### R2. Inyección de Consultas (site:)
Modificar el motor de búsqueda en internet de la Fase 2 para que, al no encontrar resultados oficiales para una pedanía pequeña, lance búsquedas suplementarias acotadas a esos medios mediante el operador `site:` (ej. `site:radiollodio.com OR site:elcorreo.com`).

## Acceptance Criteria

### Verificación Programática
- [ ] Dada una localidad como "Retes de Tudela" (Álava, prefijo 01), el sistema loguea una query que incluye los medios alaveses.
- [ ] Si la localidad pertenece a Bizkaia (prefijo 48), debe usar los medios de Bizkaia (ej. deia.eus, elcorreo.com).
- [ ] La estructura de fuentes debe poder ampliarse en el futuro sin modificar la lógica principal de búsqueda.

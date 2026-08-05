"""
Test aislado para simulación de límites de tokens RAG Multi-Pass (Requisito R1 / M1 / M3).

Simula el ensamblado de payloads de Discovery Pass y Enrichment Pass contra conjuntos de
chunks sintetizados para asegurar que el conteo de tokens de cada petición LLM se mantenga
estrictamente por debajo del límite objetivo de 12K tokens (y muy por debajo del límite duro de 32K).
"""

import pytest
from config import RAG_CHARS_PER_TOKEN
from llm_processor.text_analyzer import (
    generar_consultas_enriquecimiento,
    DISCOVERY_MAX_CHARS,
    ENRICHMENT_MAX_CHARS,
)

LOCALIDAD_MOCK = {"id": "01049000201", "nombre": "Salinas de Añana"}
MUNICIPIO_MOCK = {
    "id": "01049",
    "nombre": "Añana",
    "provincia": "Araba/Álava",
    "comunidad_autonoma": "País Vasco",
}
ANNO_MOCK = 2026


def calcular_tokens_estimados(texto: str, chars_per_token: float = RAG_CHARS_PER_TOKEN) -> int:
    """Calcula la estimación de tokens basada en caracteres de acuerdo a config.py."""
    if not texto:
        return 0
    return int(len(texto) / chars_per_token)


def simular_discovery_pass_payload(
    documentos_mock: list[dict],
    localidad: dict = LOCALIDAD_MOCK,
    municipio: dict = MUNICIPIO_MOCK,
    anno: int = ANNO_MOCK,
    max_chars: int = DISCOVERY_MAX_CHARS,
) -> dict:
    """
    Simula la selección de chunks y ensamblado del prompt para el Discovery Pass.
    Retorna un diccionario con las métricas del payload generado.
    """
    chunks_seleccionados = []
    usados = 0
    for doc in documentos_mock:
        texto = doc.get("texto", "") if isinstance(doc, dict) else str(doc)
        if usados + len(texto) > max_chars:
            resto = max_chars - usados
            if resto > 0:
                chunks_seleccionados.append(texto[:resto])
                usados += len(texto[:resto])
            break
        chunks_seleccionados.append(texto)
        usados += len(texto)

    contexto = "\n\n".join(chunks_seleccionados)
    if len(contexto) > max_chars:
        contexto = contexto[:max_chars]

    system_prompt = (
        f"Eres un API estricta especializada en identificar y catalogar las fiestas locales en España. "
        f"CONTEXTO: Municipio {municipio['nombre']}, Localidad: {localidad['nombre']}. AÑO: {anno}."
    )
    user_prompt = f"AÑO: {anno}\n\nTEXTO RECUPERADO:\n{contexto}\n\nExtrae la lista básica de fiestas en JSON."

    total_prompt_text = system_prompt + "\n" + user_prompt
    tokens_est = calcular_tokens_estimados(total_prompt_text)

    return {
        "pass_name": "Discovery Pass",
        "context_chars": len(contexto),
        "total_prompt_chars": len(total_prompt_text),
        "estimated_tokens": tokens_est,
        "chunks_count": len(chunks_seleccionados),
    }


def simular_enrichment_pass_payload(
    fiesta: dict,
    chunks_por_dia: dict[str, list[str]],
    localidad: dict = LOCALIDAD_MOCK,
    municipio: dict = MUNICIPIO_MOCK,
    anno: int = ANNO_MOCK,
    max_chars_cap: int = ENRICHMENT_MAX_CHARS,
) -> dict:
    """
    Simula el enriquecimiento de una fiesta: deduplica chunks entre días,
    aplica el límite duro de caracteres y ensambla el prompt final.
    """
    consultas_dias = generar_consultas_enriquecimiento(
        fiesta["nombre"], fiesta["fecha_inicio"], fiesta["fecha_fin"]
    )

    chunks_unicos = []
    seen = set()

    for fecha_str, _ in consultas_dias:
        cand_chunks = chunks_por_dia.get(fecha_str, [])
        for chk in cand_chunks:
            if chk not in seen:
                seen.add(chk)
                chunks_unicos.append(chk)

    chunks_finales = []
    usados = 0
    for chk in chunks_unicos:
        if usados + len(chk) > max_chars_cap:
            resto = max_chars_cap - usados
            if resto > 0:
                chunks_finales.append(chk[:resto])
                usados += len(chk[:resto])
            break
        chunks_finales.append(chk)
        usados += len(chk)

    contexto = "\n\n".join(chunks_finales)
    if len(contexto) > max_chars_cap:
        contexto = contexto[:max_chars_cap]

    system_prompt = (
        f"Eres un API estricta especializada en estructurar el PROGRAMA DE ACTOS Y EVENTOS de una fiesta local. "
        f"CONTEXTO: Municipio {municipio['nombre']}, Localidad: {localidad['nombre']}. FIESTA: '{fiesta['nombre']}'."
    )
    user_prompt = f"FIESTA: {fiesta['nombre']}\n\nTEXTO RECUPERADO:\n{contexto}\n\nGenera el programa de actos en JSON."

    total_prompt_text = system_prompt + "\n" + user_prompt
    tokens_est = calcular_tokens_estimados(total_prompt_text)

    return {
        "pass_name": "Enrichment Pass",
        "context_chars": len(contexto),
        "total_prompt_chars": len(total_prompt_text),
        "estimated_tokens": tokens_est,
        "chunks_count": len(chunks_finales),
    }


def test_discovery_pass_token_limit():
    mock_docs = [
        {"texto": f"Chunk de prueba {i}: Programa de fiestas de San Roque con verbena, orquesta y actividades..." * 15}
        for i in range(100)
    ]

    payload = simular_discovery_pass_payload(mock_docs)

    assert payload["context_chars"] <= DISCOVERY_MAX_CHARS
    assert payload["estimated_tokens"] < 12000
    assert payload["estimated_tokens"] < 32768
    print(f"\n[DISCOVERY PASS] Chars: {payload['context_chars']}, Estimated Tokens: {payload['estimated_tokens']}")


def test_enrichment_pass_standard_festival_tokens():
    fiesta = {
        "nombre": "Fiestas de San Roque",
        "fecha_inicio": "2026-08-28",
        "fecha_fin": "2026-09-03",
    }

    chunks_por_dia = {}
    consultas = generar_consultas_enriquecimiento(fiesta["nombre"], fiesta["fecha_inicio"], fiesta["fecha_fin"])
    for i, (fecha_str, _) in enumerate(consultas):
        c1 = f"Chunk del día {fecha_str}: Actos matinales, pasacalles y diana floreada..." * 12
        c2 = f"Chunk del día {fecha_str}: Verbena nocturna a las 23:00h con la Orquesta Panorama..." * 12
        c3 = "Chunk compartido entre días: Recinto ferial abierto todas las tardes desde las 17:00h..." * 12
        chunks_por_dia[fecha_str] = [c1, c2, c3]

    payload = simular_enrichment_pass_payload(fiesta, chunks_por_dia)

    assert payload["estimated_tokens"] < 12000
    assert payload["estimated_tokens"] < 32768
    print(f"\n[ENRICHMENT PASS STANDARD] Chars: {payload['context_chars']}, Estimated Tokens: {payload['estimated_tokens']}")


def test_enrichment_pass_heavy_stress_tokens():
    fiesta = {
        "nombre": "Fiesta Mayor de Verano",
        "fecha_inicio": "2026-08-01",
        "fecha_fin": "2026-08-25",
    }

    chunks_por_dia = {}
    consultas = generar_consultas_enriquecimiento(fiesta["nombre"], fiesta["fecha_inicio"], fiesta["fecha_fin"])
    for fecha_str, _ in consultas:
        c1 = f"Día {fecha_str} - Mañana: Diana floreada, gigantes y cabezudos por el casco antiguo..." * 15
        c2 = f"Día {fecha_str} - Tarde: Campeonatos de pelota vasca, deporte rural y juegos infantiles..." * 15
        c3 = f"Día {fecha_str} - Noche: Gran concierto, orquesta y fuegos artificiales..." * 15
        chunks_por_dia[fecha_str] = [c1, c2, c3]

    payload = simular_enrichment_pass_payload(fiesta, chunks_por_dia, max_chars_cap=25000)

    assert payload["context_chars"] <= 25000
    assert payload["estimated_tokens"] < 12000
    assert payload["estimated_tokens"] < 32768
    print(f"\n[ENRICHMENT PASS HEAVY STRESS] Chars: {payload['context_chars']}, Estimated Tokens: {payload['estimated_tokens']}")


def test_token_ratio_consistency():
    texto_prueba = (
        "Fiestas Patronales de Salinas de Añana 2026 en honor a la Virgen del Rosario. "
        "Programa de actos: 12:00h Chupinazo y volteo de campanas. 23:30h Verbena con Orquesta."
    )
    tokens = calcular_tokens_estimados(texto_prueba)
    expected = int(len(texto_prueba) / RAG_CHARS_PER_TOKEN)
    assert tokens == expected
    assert tokens > 0


if __name__ == "__main__":
    test_discovery_pass_token_limit()
    test_enrichment_pass_standard_festival_tokens()
    test_enrichment_pass_heavy_stress_tokens()
    test_token_ratio_consistency()
    print("✅ Todos los tests de test_rag_token_limit_simulation.py pasaron exitosamente.")

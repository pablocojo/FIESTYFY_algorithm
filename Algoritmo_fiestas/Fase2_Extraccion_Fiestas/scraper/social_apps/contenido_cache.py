"""
Caché de contenido de RRSS producida por el runner de apps.

Formato de `rrss_contenido_cache.json`:
{
  "<lugar_id>": {
    "<red>": {
      "leido_en": "2026-07-04",
      "posts": [
        {"texto": "...", "fecha": "2026-08-01"|null, "captura": "rrss_capturas/...png",
         "es_programa": bool (lo rellena la Etapa D), "texto_programa": str}
      ]
    }
  }
}

`scraper/social_content.py` (pipeline principal) acepta tanto este formato
como una lista directa de posts.
"""

import json
import os
from datetime import date, datetime


class ContenidoCache:
    """Acceso síncrono (el runner es secuencial) con escritura atómica."""

    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        self._cargar()

    def _cargar(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _guardar(self):
        temp = f"{self.path}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(temp, self.path)

    def entrada(self, lugar_id: str, red: str) -> dict | None:
        valor = (self._data.get(lugar_id) or {}).get(red)
        if isinstance(valor, dict):
            return valor
        if isinstance(valor, list):  # formato antiguo: lista directa de posts
            return {"leido_en": None, "posts": valor}
        return None

    def vigente(self, lugar_id: str, red: str, ttl_dias: int, hoy: date | None = None) -> bool:
        """True si el perfil se leyó hace menos de ttl_dias (no hay que releerlo)."""
        entrada = self.entrada(lugar_id, red)
        if not entrada or not entrada.get("leido_en"):
            return False
        hoy = hoy or date.today()
        try:
            leido = datetime.strptime(entrada["leido_en"], "%Y-%m-%d").date()
        except ValueError:
            return False
        return (hoy - leido).days < ttl_dias

    def guardar_posts(self, lugar_id: str, red: str, posts: list[dict], hoy: date | None = None):
        hoy = hoy or date.today()
        self._data.setdefault(lugar_id, {})[red] = {
            "leido_en": hoy.isoformat(),
            "posts": posts,
        }
        self._guardar()

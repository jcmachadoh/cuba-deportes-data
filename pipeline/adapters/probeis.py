"""Probeis (Panamá) — DESACTIVADO.

panamaprobeis.com no resolvió DNS desde el entorno de pruebas (2026-10-03).
No se escribe un parser sin haber visto el HTML real. Cuando el sitio
responda, implementar aquí y poner enabled: true en config/competitions.yml.
"""
from ..core.model import Bundle


def collect(ctx, comp, season, start_year, mode):
    raise NotImplementedError("Probeis: fuente pendiente de verificación (ver docs/estado-fuentes.md)")

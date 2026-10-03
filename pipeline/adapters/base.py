"""Contrato común de los adaptadores.

Cada módulo en pipeline/adapters/ expone:

    def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle

mode:
  "full"       equipos + plantillas + clasificación (diario / semanal)
  "standings"  solo clasificación / ranking (perfil "live", cada 1-2 h)
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from ..core.http import Http
from ..core.ids import IdRegistry


@dataclass
class Ctx:
    http: Http
    ids: IdRegistry


def load(adapter_name: str):
    return importlib.import_module(f"pipeline.adapters.{adapter_name}")

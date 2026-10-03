"""Carga de configuración y cálculo de temporadas."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

import yaml

from .paths import CONFIG_DIR
from .util import today


@dataclass
class Competition:
    id: str
    sport: str
    name: dict[str, str]
    adapter: str
    params: dict[str, Any]
    season_format: str = "year"
    start_month: int = 1
    active_months: list[int] = field(default_factory=lambda: list(range(1, 13)))
    history_seasons: int = 0
    short: str | None = None
    country: str | None = None
    tier: int = 1
    tags: list[str] = field(default_factory=list)
    logo: dict[str, str] | None = None
    enabled: bool = True
    refresh: str = "daily"          # daily | weekly | monthly (frecuencia mínima en perfil full)

    # ------------------------------------------------------------ temporadas
    def season_start_year(self, d: date | None = None) -> int:
        d = d or today()
        if self.season_format == "split":
            return d.year if d.month >= self.start_month else d.year - 1
        return d.year

    def season_label(self, start_year: int) -> str:
        if self.season_format == "split":
            return f"{start_year}-{(start_year + 1) % 100:02d}"
        return str(start_year)

    def current_season(self, d: date | None = None) -> tuple[str, int]:
        y = self.season_start_year(d)
        return self.season_label(y), y

    def past_seasons(self, n: int | None = None) -> list[tuple[str, int]]:
        y = self.season_start_year()
        n = self.history_seasons if n is None else n
        return [(self.season_label(y - i), y - i) for i in range(1, n + 1)]

    def is_active(self, d: date | None = None) -> bool:
        d = d or today()
        return d.month in self.active_months

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id, "sport": self.sport, "name": self.name, "short": self.short,
            "country": self.country, "tier": self.tier, "tags": self.tags,
            "seasonFormat": self.season_format, "activeMonths": self.active_months,
        }


@lru_cache(maxsize=1)
def sports() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load((CONFIG_DIR / "sports.yml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["sports"]}


@lru_cache(maxsize=1)
def competitions() -> dict[str, Competition]:
    data = yaml.safe_load((CONFIG_DIR / "competitions.yml").read_text(encoding="utf-8"))
    out: dict[str, Competition] = {}
    for c in data["competitions"]:
        s = c.get("season") or {}
        comp = Competition(
            id=c["id"], sport=c["sport"], name=c["name"], adapter=c["adapter"],
            params=c.get("params") or {}, season_format=s.get("format", "year"),
            start_month=int(s.get("start_month", 1)),
            active_months=c.get("active_months") or list(range(1, 13)),
            history_seasons=int(c.get("history_seasons", 0)), short=c.get("short"),
            country=c.get("country"), tier=int(c.get("tier", 1)), tags=c.get("tags") or [],
            logo=c.get("logo"), enabled=c.get("enabled", True), refresh=c.get("refresh", "daily"),
        )
        if comp.sport not in sports():
            raise ValueError(f"{comp.id}: deporte desconocido {comp.sport}")
        if comp.id in out:
            raise ValueError(f"ID de competición duplicado: {comp.id}")
        out[comp.id] = comp
    return out


def group_for(sport: str, position: str | None) -> str | None:
    if not position:
        return None
    mapping = sports()[sport].get("position_to_group") or {}
    return mapping.get(position.upper())

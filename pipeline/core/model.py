"""Registros intermedios que devuelven los adaptadores.

Todos los adaptadores, sin importar la fuente, devuelven un `Bundle` con la
misma forma. El escritor (store.py) lo convierte al modelo canónico publicado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    """Candidato de imagen. type: url | page | lichess_fide | wikidata | mlb | espn"""
    type: str
    value: str
    source: str
    priority: int = 50          # menor = se intenta antes
    credit: str | None = None   # autor/fotógrafo si la fuente lo indica

    def as_dict(self) -> dict[str, Any]:
        d = {"type": self.type, "value": self.value, "source": self.source, "priority": self.priority}
        if self.credit:
            d["credit"] = self.credit
        return d


@dataclass
class TeamRec:
    id: str
    name: str
    short: str | None = None
    abbrev: str | None = None
    nickname: str | None = None
    city: str | None = None
    country: str | None = None
    colors: list[str] = field(default_factory=list)
    venue: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    logos: list[Candidate] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)
    kind: str = "club"           # club | national | division (pesos UFC/boxeo)


@dataclass
class PersonRec:
    id: str
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    birth_date: str | None = None          # YYYY-MM-DD o YYYY
    birth_city: str | None = None
    birth_country: str | None = None       # ISO alfa-2
    nationalities: list[str] = field(default_factory=list)
    height_cm: float | None = None
    weight_kg: float | None = None
    bats: str | None = None
    throws: str | None = None
    gender: str | None = None
    nickname: str | None = None
    title: str | None = None               # GM, IM... (ajedrez)
    external_ids: dict[str, str] = field(default_factory=dict)
    photos: list[Candidate] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RosterEntry:
    person_id: str
    position: str | None = None            # código de la fuente normalizado (P, C, SS, G...)
    group: str | None = None               # grupo de pantalla (P, C, IF, OF, STAFF...)
    number: str | None = None
    role: str = "player"                   # player | staff
    role_name: str | None = None           # "Director Técnico", "Coach de banca"...
    status: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StandingRow:
    participant_id: str
    rank: int | None
    stats: dict[str, Any]
    extra: dict[str, Any] = field(default_factory=dict)
    participant_type: str = "team"


@dataclass
class StandingGroup:
    id: str
    name: str
    rows: list[StandingRow] = field(default_factory=list)


@dataclass
class RankingRec:
    id: str                                # open, women, lightweight...
    name: str
    as_of: str | None                      # fecha o periodo ("2026-10")
    entries: list[StandingRow] = field(default_factory=list)
    champion_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventRec:
    """Torneo/edición (ajedrez) o evento puntual."""
    id: str
    name: str
    group: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    url: str | None = None
    status: str | None = None              # upcoming | in_progress | finished
    standings: list[StandingRow] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bundle:
    competition_id: str
    season: str                            # etiqueta canónica: "2026" o "2026-27"
    source: str
    source_urls: list[str] = field(default_factory=list)
    teams: list[TeamRec] = field(default_factory=list)
    persons: list[PersonRec] = field(default_factory=list)
    rosters: dict[str, list[RosterEntry]] = field(default_factory=dict)
    standings: list[StandingGroup] = field(default_factory=list)
    rankings: list[RankingRec] = field(default_factory=list)
    events: list[EventRec] = field(default_factory=list)
    competition_logos: list[Candidate] = field(default_factory=list)
    season_info: dict[str, Any] = field(default_factory=dict)   # fechas, estado, nombre oficial
    warnings: list[str] = field(default_factory=list)

    def add_person(self, p: PersonRec) -> PersonRec:
        for q in self.persons:
            if q.id == p.id:
                return q
        self.persons.append(p)
        return p

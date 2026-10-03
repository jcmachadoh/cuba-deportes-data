"""ESPN (site.api.espn.com) para fútbol.

Endpoints (sin clave, no documentados oficialmente; aprobados para el MVP):
  /apis/site/v2/sports/{sport}/{slug}/teams               equipos actuales (colores)
  /apis/v2/sports/{sport}/{slug}/standings?season=YYYY    clasificación (YYYY = año de inicio)
  /apis/site/v2/sports/{sport}/{slug}/teams/{id}/roster?season=YYYY

Notas verificadas:
  * El campo "coach" de la plantilla devuelve una lista histórica (no el DT
    actual), por eso no se usa.
  * Las fotos de futbolistas en a.espncdn.com casi siempre dan 404; se dejan
    como candidato de baja prioridad y la etapa de fotos cae en Wikidata.
"""
from __future__ import annotations

import logging

from ..core.config import Competition, group_for
from ..core.model import Bundle, Candidate, PersonRec, RosterEntry, StandingGroup, StandingRow, TeamRec
from ..core.util import country_code, to_float, to_int
from .base import Ctx

log = logging.getLogger("espn")
SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://site.api.espn.com/apis/v2/sports"
STAT_MAP = {"gamesPlayed": "GP", "wins": "W", "ties": "D", "losses": "L", "pointsFor": "GF",
            "pointsAgainst": "GA", "pointDifferential": "GD", "points": "PTS"}


def _logo(team: dict) -> str | None:
    logos = team.get("logos") or []
    for lg in logos:
        if "default" in (lg.get("rel") or []):
            return lg.get("href")
    return logos[0]["href"] if logos else None


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    sport, slug = comp.params.get("sport", "soccer"), comp.params["slug"]
    b = Bundle(comp.id, season, source="espn")
    teams: dict[str, TeamRec] = {}

    def team_rec(t: dict) -> TeamRec:
        eid = str(t["id"])
        if eid in teams:
            return teams[eid]
        name = t.get("displayName") or t.get("name") or eid
        rec = TeamRec(
            id=ctx.ids.team(comp.sport, "espn", eid, name), name=name,
            short=t.get("shortDisplayName"), abbrev=t.get("abbreviation"), city=t.get("location"),
            country=comp.country, colors=[f"#{c}" for c in (t.get("color"), t.get("alternateColor")) if c],
            external_ids={"espn": eid}, kind="national" if t.get("isNational") else "club",
        )
        href = _logo(t)
        if href:
            rec.logos.append(Candidate("url", href, "espn", 20))
        teams[eid] = rec
        return rec

    # ---------------------------------------------------------------- clasificación
    url = f"{CORE}/{sport}/{slug}/standings"
    st = ctx.http.json(url, params={"season": start_year})
    b.source_urls.append(url)
    b.season_info = {"name": st.get("name")}
    children = st.get("children") or ([st] if st.get("standings") else [])
    for i, ch in enumerate(children):
        entries = (ch.get("standings") or {}).get("entries") or []
        if not entries:
            continue
        b.season_info["name"] = (ch.get("standings") or {}).get("seasonDisplayName") or b.season_info.get("name")
        g = StandingGroup(str(ch.get("id") or i), ch.get("name") or ch.get("abbreviation") or comp.name["es"])
        for e in entries:
            t = team_rec(e["team"])
            raw = {s.get("name"): s for s in e.get("stats", [])}
            stats = {}
            for k, code in STAT_MAP.items():
                if k in raw:
                    v = raw[k].get("value")
                    stats[code] = int(v) if isinstance(v, float) and v.is_integer() else v
            rank = to_int((raw.get("rank") or {}).get("value"))
            extra = {}
            note = e.get("note")
            if note:
                extra["note"] = {"text": note.get("description"), "color": note.get("color")}
            if (raw.get("deductions") or {}).get("value"):
                extra["deductions"] = raw["deductions"]["value"]
            g.rows.append(StandingRow(t.id, rank, stats, extra))
        g.rows.sort(key=lambda r: r.rank or 999)
        b.standings.append(g)

    # Equipos actuales (aporta colores y equipos aún sin partidos en la tabla)
    if start_year == comp.current_season()[1]:
        try:
            tj = ctx.http.json(f"{SITE}/{sport}/{slug}/teams")
            for item in ((tj.get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams", []):
                team_rec(item["team"])
        except Exception as e:  # noqa: BLE001
            b.warnings.append(f"teams: {e}")
    b.teams = list(teams.values())

    if mode == "standings":
        return b

    try:  # logo de la liga
        lg = ctx.http.json(f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{slug}")
        for lo in lg.get("logos") or []:
            if "default" in (lo.get("rel") or []):
                b.competition_logos.append(Candidate("url", lo["href"], "espn", 20))
    except Exception as e:  # noqa: BLE001
        b.warnings.append(f"league logo: {e}")

    # ---------------------------------------------------------------- plantillas
    if comp.params.get("rosters", True) is False:
        return b
    for eid, team in teams.items():
        try:
            r = ctx.http.json(f"{SITE}/{sport}/{slug}/teams/{eid}/roster", params={"season": start_year}, allow_404=True)
        except Exception as e:  # noqa: BLE001
            b.warnings.append(f"roster {team.id}: {e}")
            continue
        if not r:
            continue
        athletes = r.get("athletes") or []
        # algunos deportes agrupan: [{position:"...", items:[...]}]
        if athletes and "items" in athletes[0]:
            athletes = [a for grp in athletes for a in grp.get("items", [])]
        entries = []
        for a in athletes:
            if not a.get("id"):
                continue
            dob = (a.get("dateOfBirth") or "")[:10] or None
            pid = ctx.ids.person("espn", a["id"], a.get("fullName", ""), dob)
            nat = country_code(a.get("citizenship")) or country_code((a.get("citizenshipCountry") or {}).get("abbreviation"))
            bp = a.get("birthPlace") or {}
            photos = []
            hs = (a.get("headshot") or {}).get("href")
            if hs:
                photos.append(Candidate("url", hs, "espn", 30))
            b.add_person(PersonRec(
                id=pid, full_name=a.get("fullName", ""), first_name=a.get("firstName"), last_name=a.get("lastName"),
                birth_date=dob, birth_city=bp.get("city"), birth_country=country_code(bp.get("country")),
                nationalities=[nat] if nat else [],
                height_cm=round(a["height"] * 2.54, 1) if a.get("height") else None,
                weight_kg=round(a["weight"] * 0.4536, 1) if a.get("weight") else None,
                gender="M" if comp.sport == "soccer" else None,
                external_ids={"espn": str(a["id"])}, photos=photos,
            ))
            pos = (a.get("position") or {}).get("abbreviation")
            entries.append(RosterEntry(pid, position=pos, group=group_for(comp.sport, pos), number=a.get("jersey")))
        if entries:
            b.rosters[team.id] = entries
    return b

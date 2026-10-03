"""MLB Stats API (statsapi.mlb.com).

Cubre MLB (sportId 1), ligas invernales (sportId 17: LIDOM 131, LMP 132,
LBPRC 133, LVBP 135, Serie del Caribe 162) y la LMB (sportId 23, liga 125).
Para ligas invernales, el parámetro season de la API es el año de inicio
(season=2026 -> temporada 2026-27).
"""
from __future__ import annotations

import logging

from ..core.config import Competition, group_for
from ..core.model import Bundle, Candidate, PersonRec, RosterEntry, StandingGroup, StandingRow, TeamRec
from ..core.util import country_code, to_float, to_int
from .base import Ctx

log = logging.getLogger("mlb")
API = "https://statsapi.mlb.com/api/v1"
LOGO = "https://www.mlbstatic.com/team-logos/{id}.svg"
PHOTO_MLB = ("https://img.mlbstatic.com/mlb-photos/image/upload/w_213,d_people:generic:headshot:silo:current.png,"
             "q_auto:best,f_auto/v1/people/{id}/headshot/67/current")
PHOTO_MILB = "https://img.mlbstatic.com/mlb-photos/image/upload/w_213,g_auto,c_fill/v1/people/{id}/headshot/milb/current"


def _height_cm(h: str | None) -> float | None:
    # "6' 2\"" -> 187.96
    if not h or "'" not in h:
        return None
    try:
        ft, inch = h.replace('"', "").split("'")
        return round(int(ft) * 30.48 + int(inch.strip() or 0) * 2.54, 1)
    except ValueError:
        return None


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    p = comp.params
    sport_id, league_ids = p["sport_id"], [int(x) for x in p["league_ids"]]
    b = Bundle(comp.id, season, source="mlb-statsapi")
    if len(league_ids) == 1:   # existe para algunas ligas (LIDOM 131, LMB 125); si da 404 se ignora
        b.competition_logos.append(Candidate("url", f"https://www.mlbstatic.com/team-logos/league-on-light/{league_ids[0]}.svg", "mlb", 20))

    # ---------------------------------------------------------------- equipos
    url = f"{API}/teams"
    data = ctx.http.json(url, params={"sportId": sport_id, "season": start_year, "leagueIds": ",".join(map(str, league_ids))})
    b.source_urls.append(url)
    teams: dict[int, TeamRec] = {}
    for t in data.get("teams", []):
        if (t.get("league") or {}).get("id") not in league_ids:
            continue
        tid = ctx.ids.team(comp.sport, "mlb", t["id"], t["name"])
        rec = TeamRec(
            id=tid, name=t["name"], short=t.get("teamName") or t.get("shortName"), abbrev=t.get("abbreviation"),
            nickname=t.get("clubName"), city=t.get("locationName"), venue=(t.get("venue") or {}).get("name"),
            country=comp.country, external_ids={"mlb": str(t["id"])},
            logos=[Candidate("url", LOGO.format(id=t["id"]), "mlb", 20)],
            kind="national" if comp.id == "baseball.serie-del-caribe" else "club",
        )
        teams[t["id"]] = rec
    b.teams = list(teams.values())

    # ---------------------------------------------------------------- clasificación
    st = ctx.http.json(f"{API}/standings", params={
        "leagueId": ",".join(map(str, league_ids)), "season": start_year, "hydrate": "division,team"})
    for rec in st.get("records", []):
        div = rec.get("division") or {}
        lg = rec.get("league") or {}
        gid = str(div.get("id") or lg.get("id") or "all")
        gname = div.get("name") or comp.name.get("es")
        group = StandingGroup(gid, gname)
        for tr in rec.get("teamRecords", []):
            mlb_tid = tr["team"]["id"]
            team = teams.get(mlb_tid)
            if team is None:  # equipo no listado en /teams (raro); lo registramos igual
                name = tr["team"].get("name", str(mlb_tid))
                team = TeamRec(id=ctx.ids.team(comp.sport, "mlb", mlb_tid, name), name=name,
                               external_ids={"mlb": str(mlb_tid)}, logos=[Candidate("url", LOGO.format(id=mlb_tid), "mlb", 20)])
                teams[mlb_tid] = team
                b.teams.append(team)
            splits = {s["type"]: f'{s["wins"]}-{s["losses"]}' for s in (tr.get("records") or {}).get("splitRecords", [])}
            stats = {
                "GP": tr.get("gamesPlayed"), "W": tr.get("wins"), "L": tr.get("losses"),
                "PCT": to_float(tr.get("winningPercentage")),
                "GB": None if tr.get("gamesBack") in ("-", None) else to_float(tr.get("gamesBack")),
                "STRK": (tr.get("streak") or {}).get("streakCode"),
                "L10": splits.get("lastTen"), "HOME": splits.get("home"), "AWAY": splits.get("away"),
                "RS": tr.get("runsScored"), "RA": tr.get("runsAllowed"), "RD": tr.get("runDifferential"),
            }
            extra = {k: tr.get(k) for k in ("clinchIndicator", "wildCardGamesBack", "leagueRank") if tr.get(k) not in (None, "-")}
            group.rows.append(StandingRow(team.id, to_int(tr.get("divisionRank") or tr.get("leagueRank")),
                                          {k: v for k, v in stats.items() if v is not None}, extra))
        group.rows.sort(key=lambda r: r.rank or 99)
        b.standings.append(group)

    if mode == "standings":
        return b

    # ---------------------------------------------------------------- plantillas
    photo_tpl = PHOTO_MLB if sport_id == 1 else PHOTO_MILB
    for mlb_tid, team in teams.items():
        try:
            r = ctx.http.json(f"{API}/teams/{mlb_tid}/roster", params={
                "season": start_year, "rosterType": p.get("roster_type", "active"), "hydrate": "person"})
        except Exception as e:  # noqa: BLE001
            b.warnings.append(f"roster {team.id}: {e}")
            continue
        entries: list[RosterEntry] = []
        for it in r.get("roster", []):
            per = it.get("person") or {}
            if not per.get("id"):
                continue
            pid = ctx.ids.person("mlb", per["id"], per.get("fullName", ""), per.get("birthDate"))
            b.add_person(PersonRec(
                id=pid, full_name=per.get("fullName", ""), first_name=per.get("useName") or per.get("firstName"),
                last_name=per.get("useLastName") or per.get("lastName"), birth_date=per.get("birthDate"),
                birth_city=per.get("birthCity"), birth_country=country_code(per.get("birthCountry")),
                height_cm=_height_cm(per.get("height")),
                weight_kg=round(per["weight"] * 0.4536, 1) if per.get("weight") else None,
                bats=(per.get("batSide") or {}).get("code"), throws=(per.get("pitchHand") or {}).get("code"),
                nickname=per.get("nickName"), external_ids={"mlb": str(per["id"])},
                photos=[Candidate("url", photo_tpl.format(id=per["id"]), "mlb", 20)],
            ))
            pos = (it.get("position") or {}).get("abbreviation")
            entries.append(RosterEntry(pid, position=pos, group=group_for(comp.sport, pos),
                                       number=it.get("jerseyNumber") or None,
                                       status=(it.get("status") or {}).get("description")))
        # cuerpo técnico
        try:
            co = ctx.http.json(f"{API}/teams/{mlb_tid}/coaches", params={"season": start_year})
            for c in co.get("roster", []):
                per = c.get("person") or {}
                if not per.get("id"):
                    continue
                pid = ctx.ids.person("mlb", per["id"], per.get("fullName", ""))
                b.add_person(PersonRec(id=pid, full_name=per.get("fullName", ""), external_ids={"mlb": str(per["id"])}))
                entries.append(RosterEntry(pid, role="staff", role_name=c.get("job"), number=c.get("jerseyNumber") or None))
        except Exception as e:  # noqa: BLE001
            b.warnings.append(f"coaches {team.id}: {e}")
        if entries:
            b.rosters[team.id] = entries
    return b

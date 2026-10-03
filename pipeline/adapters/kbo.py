"""KBO (Corea) — eng.koreabaseball.com (sitio oficial en inglés).

  /Standings/TeamStandings.aspx   clasificación de la temporada en curso
Plantillas: la búsqueda de jugadores es un postback ASP.NET; queda pendiente
(ver docs/estado-fuentes.md). Los jugadores cubanos en KBO se cubren desde
Wikidata en la etapa `enrich`.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, StandingGroup, StandingRow, TeamRec
from ..core.util import to_float, to_int
from .base import Ctx

URL = "https://eng.koreabaseball.com/Standings/TeamStandings.aspx"
LOGO = "https://6ptotvmi5753.edge.naverncp.com/KBO_IMAGE/eng/resources/images/ebl/regular/{year}/ebl_s_{code}.png"
# nombre en la tabla -> (nombre completo, código de logo)
TEAMS = {
    "KIA": ("KIA Tigers", "HT"), "SAMSUNG": ("Samsung Lions", "SS"), "LG": ("LG Twins", "LG"),
    "DOOSAN": ("Doosan Bears", "OB"), "KT": ("KT Wiz", "KT"), "SSG": ("SSG Landers", "SK"),
    "LOTTE": ("Lotte Giants", "LT"), "HANWHA": ("Hanwha Eagles", "HH"), "NC": ("NC Dinos", "NC"),
    "KIWOOM": ("Kiwoom Heroes", "WO"),
}


def parse_standings(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    tb = s.select("table")[0]
    rows = tb.select("tr")
    headers = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
    out = []
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) == len(headers):
            out.append(dict(zip(headers, cells)))
    return out


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="kbo")
    if start_year != comp.current_season()[1]:
        b.warnings.append("el sitio solo expone la temporada en curso")
        return b
    ids = {}
    for key, (name, code) in TEAMS.items():
        tid = ctx.ids.team(comp.sport, "kbo", code, name)
        ids[key] = tid
        b.teams.append(TeamRec(id=tid, name=name, abbrev=code, country="KR", external_ids={"kbo": code},
                               logos=[Candidate("url", LOGO.format(year=start_year, code=code), "kbo", 20)]))
    g = StandingGroup("all", "KBO")
    for r in parse_standings(ctx.http.text(URL) or ""):
        tid = ids.get(r.get("TEAM", "").upper())
        if not tid:
            b.warnings.append(f"equipo desconocido {r.get('TEAM')}")
            continue
        stats = {"GP": to_int(r.get("GAMES")), "W": to_int(r.get("W")), "L": to_int(r.get("L")), "T": to_int(r.get("D")),
                 "PCT": to_float(r.get("PCT")), "GB": to_float(r.get("GB")), "STRK": r.get("STREAK"),
                 "HOME": r.get("HOME"), "AWAY": r.get("AWAY")}
        g.rows.append(StandingRow(tid, to_int(r.get("RK")), {k: v for k, v in stats.items() if v is not None}))
    b.standings.append(g)
    return b

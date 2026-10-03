"""NPB (Japón) — npb.jp, sitio oficial en inglés.

  /bis/eng/teams/rst_{code}.html          plantilla (dirigente, lanzadores, receptores,
                                          cuadro, jardineros + equipo de desarrollo)
  /bis/eng/{year}/stats/std_c.html        Liga Central
  /bis/eng/{year}/stats/std_p.html        Liga del Pacífico
  /bis/eng/players/{pid}.html             ficha (contiene la foto oficial)

El sitio no publica nacionalidad; la etapa `enrich` (Wikidata P4260) la añade.
La página de plantillas solo existe para la temporada en curso.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RosterEntry, StandingGroup, StandingRow, TeamRec
from ..core.util import clean, parse_date, to_float, to_int
from .base import Ctx

BASE = "https://npb.jp"
TEAMS = {
    "g": ("Yomiuri Giants", "central"), "t": ("Hanshin Tigers", "central"),
    "db": ("Yokohama DeNA BayStars", "central"), "c": ("Hiroshima Toyo Carp", "central"),
    "s": ("Tokyo Yakult Swallows", "central"), "d": ("Chunichi Dragons", "central"),
    "h": ("Fukuoka SoftBank Hawks", "pacific"), "f": ("Hokkaido Nippon-Ham Fighters", "pacific"),
    "m": ("Chiba Lotte Marines", "pacific"), "e": ("Tohoku Rakuten Golden Eagles", "pacific"),
    "b": ("ORIX Buffaloes", "pacific"), "l": ("Saitama Seibu Lions", "pacific"),
}
SECTION = {"MANAGER": "STAFF", "PITCHERS": "P", "CATCHERS": "C", "INFIELDERS": "IF", "OUTFIELDERS": "OF"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def natural(name: str) -> str:
    """'Moinelo, Livan' -> 'Livan Moinelo'"""
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        return f"{first} {last}".strip()
    return name


def parse_roster(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    out, section, dev = [], None, False
    tables = s.select("table")
    for ti, tb in enumerate(tables[1:], 1):
        dev = ti >= 2  # la 3ª tabla es el equipo de desarrollo (ikusei)
        for tr in tb.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and cells[0] == "No.":
                section = SECTION.get(cells[1].upper())
                continue
            a = tr.select_one("a[href*='/bis/eng/players/']")
            if not section or len(cells) < 2:
                continue
            if a:
                pid = re.search(r"players/(\d+)\.html", a["href"])[1]
                name = clean(a.get_text()) or ""
            elif section == "STAFF" and cells[1]:
                name = cells[1]
                pid = "staff-" + re.sub(r"[^a-z]", "", name.lower())   # el dirigente no tiene ficha
            else:
                continue
            row = {"pid": pid, "number": cells[0] or None, "name": natural(name),
                   "born": parse_date(cells[2]) if len(cells) > 2 else None, "group": section,
                   "developmental": dev, "url": f"{BASE}/bis/eng/players/{pid}.html" if a else None}
            if section != "STAFF" and len(cells) >= 7:
                row.update(height=to_float(cells[3]), weight=to_float(cells[4]), throws=cells[5] or None, bats=cells[6] or None)
            out.append(row)
    return out


def parse_standings(html: str, name_to_team: dict[str, str], gid: str, gname: str) -> StandingGroup:
    """Admite el formato actual (tabla simple) y el de temporadas pasadas
    (la celda del equipo contiene otra tabla con el logo). Se usan solo filas
    y celdas directas de la primera tabla cuyo encabezado es Team, G, W, L... GB
    (la tabla de interliga, que va después, no tiene GB)."""
    s = BeautifulSoup(html, "lxml")
    g = StandingGroup(gid, gname)
    for tb in s.select("table"):
        rows = tb.select(":scope > tr, :scope > tbody > tr, :scope > thead > tr")
        if not rows:
            continue
        cells0 = lambda tr: [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        headers = cells0(rows[0])
        if headers[:4] != ["Team", "G", "W", "L"] or "GB" not in headers:
            continue
        for tr in rows[1:]:
            cells = cells0(tr)
            if not cells or _norm(cells[0]) not in name_to_team:
                continue
            v = dict(zip([h for h in headers if h], cells))   # el formato antiguo tiene una columna vacía sin celdas
            stats = {"GP": to_int(v.get("G")), "W": to_int(v.get("W")), "L": to_int(v.get("L")), "T": to_int(v.get("T")),
                     "PCT": to_float(v.get("PCT")), "GB": to_float(v.get("GB")) if v.get("GB") not in ("--", "-") else None,
                     "HOME": (v.get("Home") or "").split(" ")[0] or None, "AWAY": (v.get("Road") or "").split(" ")[0] or None}
            g.rows.append(StandingRow(name_to_team[_norm(cells[0])], len(g.rows) + 1,
                                      {k: x for k, x in stats.items() if x is not None}))
        if g.rows:
            break
    return g


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="npb")
    name_to_team, code_to_team = {}, {}
    for code, (name, lg) in TEAMS.items():
        tid = ctx.ids.team(comp.sport, "npb", code, name)
        code_to_team[code] = tid
        name_to_team[_norm(name)] = tid
        b.teams.append(TeamRec(
            id=tid, name=name, country="JP", external_ids={"npb": code},
            logos=[Candidate("url", f"https://p.npb.jp/img/common/logo/{start_year}/logo_{code}_m.gif", "npb", 20)],
            links={"official": f"{BASE}/bis/eng/teams/rst_{code}.html"},
        ))
    for lg, lname in (("c", "Liga Central"), ("p", "Liga del Pacífico")):
        html = ctx.http.text(f"{BASE}/bis/eng/{start_year}/stats/std_{lg}.html", allow_404=True)
        if html:
            b.standings.append(parse_standings(html, name_to_team, "central" if lg == "c" else "pacific", lname))
    if mode == "standings" or start_year != comp.current_season()[1]:
        return b

    for code, tid in code_to_team.items():
        html = ctx.http.text(f"{BASE}/bis/eng/teams/rst_{code}.html")
        entries = []
        for r in parse_roster(html or ""):
            pid = ctx.ids.person("npb", r["pid"], r["name"], r.get("born"))
            b.add_person(PersonRec(
                id=pid, full_name=r["name"], birth_date=r.get("born"), height_cm=r.get("height"),
                weight_kg=r.get("weight"), bats=r.get("bats"), throws=r.get("throws"), gender="M",
                external_ids={"npb": r["pid"]},
                photos=[Candidate("page", r["url"], "npb", 15)] if r["url"] else [],
            ))
            if r["group"] == "STAFF":
                entries.append(RosterEntry(pid, role="staff", role_name="Manager", number=r["number"]))
            else:
                entries.append(RosterEntry(pid, position=r["group"], group=r["group"], number=r["number"],
                                           status="Desarrollo" if r["developmental"] else None))
        if entries:
            b.rosters[tid] = entries
    return b

"""Serie Nacional de Béisbol — beisbolcubano.cu (sitio oficial de la FCB).

Páginas HTML (ASP.NET + DevExpress), verificadas el 2026-10-03:
  /general/equipos?eq={code}         plantilla por secciones TeamRoster_*
  /estadisticas/posiciones           tablas de posiciones por zona
Las URLs .aspx redirigen; el cliente sigue redirecciones.
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RosterEntry, StandingGroup, StandingRow, TeamRec
from ..core.util import clean, natural_name, parse_date, to_float, to_int
from .base import Ctx

log = logging.getLogger("snb")
BASE = "https://www.beisbolcubano.cu"
TEAMS = {  # código del sitio -> nombre oficial y provincia
    "art": ("Artemisa", "Artemisa"), "cav": ("Ciego de Ávila", "Ciego de Ávila"),
    "cfg": ("Cienfuegos", "Cienfuegos"), "cmg": ("Camagüey", "Camagüey"),
    "gra": ("Granma", "Granma"), "gtm": ("Guantánamo", "Guantánamo"),
    "hol": ("Holguín", "Holguín"), "ijv": ("Isla de la Juventud", "Isla de la Juventud"),
    "ind": ("Industriales", "La Habana"), "ltu": ("Las Tunas", "Las Tunas"),
    "may": ("Mayabeque", "Mayabeque"), "mtz": ("Matanzas", "Matanzas"),
    "pri": ("Pinar del Río", "Pinar del Río"), "scu": ("Santiago de Cuba", "Santiago de Cuba"),
    "ssp": ("Sancti Spíritus", "Sancti Spíritus"), "vcl": ("Villa Clara", "Villa Clara"),
}
SECTIONS = {"TeamRoster_Pitcher": "P", "TeamRoster_Catcher": "C", "TeamRoster_Infielder": "IF",
            "TeamRoster_Outfielder": "OF", "TeamRoster_Tecnicos": "STAFF"}
HAND = {"D": "R", "Z": "L", "A": "S"}
COLS = {"JJ": "GP", "JG": "W", "JP": "L", "DIF": "GB", "PRO": "PCT", "Ult. 10": "L10", "Racha": "STRK"}
SPLITS = {"VS": "AWAY", "HC": "HOME"}   # VS = de visitante, HC = home club


def _season_from_title(html: str) -> tuple[str | None, str | None]:
    m = re.search(r"([LXVI]+\s+SERIE NACIONAL DE B[EÉ]ISBOL\s+(\d{4})-(\d{4}))", html, re.I)
    if not m:
        return None, None
    return f"{m[2]}-{m[3][2:]}", m[1].title().replace("De ", "de ")


def parse_standings(html: str, code_to_team: dict[str, str]) -> list[StandingGroup]:
    s = BeautifulSoup(html, "lxml")
    zone_titles = [clean(h.get_text()) for h in s.select("h3") if "Zona" in h.get_text()]
    groups: list[StandingGroup] = []
    grids = [t for t in s.select("table[id]") if re.search(r"Posiciones(_GV_Grupos_\d+|_GV)$", t.get("id", ""))]
    for gi, t in enumerate(grids):
        headers = [h.get_text(strip=True) for h in t.select("td.dxgvHeader")]
        if "JJ" not in headers:
            continue
        gname = zone_titles[gi] if gi < len(zone_titles) else "General"
        g = StandingGroup(re.sub(r"\W+", "-", gname.lower()), gname)
        for tr in t.select("tr[class*=dxgvDataRow]"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            imgs = [i.get("src", "") for i in tr.select("img")]
            sigla = None
            for src in imgs:
                m = re.search(r"/([A-Za-z]{3})\.png", src)
                if m:
                    sigla = m[1].lower()
                    break
            if not sigla and len(tds) > 2:
                sigla = tds[2].lower()
            if sigla not in code_to_team:
                continue
            stats: dict = {}
            for i, h in enumerate(headers):
                if i >= len(tds) or not h:
                    continue
                v = tds[i]
                if h in COLS:
                    key = COLS[h]
                    stats[key] = (to_float(v) if key in ("PCT", "GB") else to_int(v) if key in ("GP", "W", "L") else v.strip("()") or None)
                else:
                    for suf, key in SPLITS.items():
                        if h.startswith("JG") and h.endswith(suf):
                            stats[f"{key}_W"] = to_int(v)
                        elif h.startswith("JP") and h.endswith(suf):
                            stats[f"{key}_L"] = to_int(v)
            for key in ("HOME", "AWAY"):
                if f"{key}_W" in stats and f"{key}_L" in stats:
                    stats[key] = f'{stats.pop(f"{key}_W")}-{stats.pop(f"{key}_L")}'
            g.rows.append(StandingRow(code_to_team[sigla], to_int(tds[0]), {k: v for k, v in stats.items() if v is not None}))
        groups.append(g)
    return groups


def parse_roster(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    out = []
    for sec, grp in SECTIONS.items():
        box = s.find(id=sec)
        if not box:
            continue
        for row in box.select("div.row"):
            a = row.select_one("a[href*=idJugador]")
            if not a:
                continue
            m = re.search(r"idJugador=(\d+)", a["href"])
            info: dict = {"id": m[1] if m else None, "name": natural_name(clean(a.get_text()) or ""), "group": grp}
            shirt = row.select_one("span.shirt")
            info["number"] = re.sub(r"\D", "", shirt.get_text()) if shirt else None
            img = row.select_one("img.roster_img_FSB")
            info["img"] = img.get("src") if img else None
            for lab in row.select("span[title]"):
                val = lab.find_next_sibling("span")
                v = clean(val.get_text()) if val else None
                key = lab.get("title")
                if key == "Fecha de Nacimiento":
                    info["birth"] = parse_date(v)
                elif key == "Batea/Tira" and v and "/" in v:
                    b_, t_ = v.split("/", 1)
                    info["bats"], info["throws"] = HAND.get(b_.strip().upper()), HAND.get(t_.strip().upper())
                elif key == "Altura":
                    info["height"] = to_float(v)
                elif key == "Peso":
                    info["weight"] = to_float(v)
            if grp == "STAFF":
                role = [clean(x.get_text()) for x in row.select("span") if not x.get("title") and "shirt" not in (x.get("class") or [])]
                info["role"] = next((r for r in role if r), None)
            out.append(info)
    return out


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="beisbolcubano")
    code_to_team: dict[str, str] = {}
    for code, (name, prov) in TEAMS.items():
        tid = ctx.ids.team(comp.sport, "snb", code, name)
        code_to_team[code] = tid
        b.teams.append(TeamRec(
            id=tid, name=name, abbrev=code.upper(), city=prov, country="CU",
            external_ids={"snb": code},
            logos=[Candidate("url", f"{BASE}/images/logos/100%20x%20100/{code}.png", "beisbolcubano", 10)],
            links={"official": f"{BASE}/general/equipos?eq={code}"},
        ))

    html = ctx.http.text(f"{BASE}/estadisticas/posiciones")
    page_season, official = _season_from_title(html or "")
    if page_season and page_season != season:
        b.warnings.append(f"el sitio muestra {page_season}, se esperaba {season}; se usa {page_season}")
        b.season = page_season
    b.season_info = {"name": official}
    b.standings = parse_standings(html or "", code_to_team)
    if mode == "standings":
        return b

    for code, tid in code_to_team.items():
        try:
            th = ctx.http.text(f"{BASE}/general/equipos", params={"eq": code})
        except Exception as e:  # noqa: BLE001
            b.warnings.append(f"roster {code}: {e}")
            continue
        entries = []
        for r in parse_roster(th or ""):
            if not r.get("id"):
                continue
            pid = ctx.ids.person("snb", r["id"], r["name"], r.get("birth"))
            photos = []
            if r.get("img"):
                photos.append(Candidate("url", f"{BASE}/images/PELOTERO%20SNB/{r['id']}.jpg", "beisbolcubano", 10))
            b.add_person(PersonRec(
                id=pid, full_name=r["name"], birth_date=r.get("birth"), nationalities=["CU"],
                height_cm=r.get("height") or None, weight_kg=r.get("weight") or None,
                bats=r.get("bats"), throws=r.get("throws"), gender="M",
                external_ids={"snb": r["id"]}, photos=photos,
            ))
            if r["group"] == "STAFF":
                entries.append(RosterEntry(pid, role="staff", role_name=r.get("role"), number=r.get("number") or None))
            else:
                entries.append(RosterEntry(pid, position=r["group"], group=r["group"], number=r.get("number") or None))
        if entries:
            b.rosters[tid] = entries
    return b

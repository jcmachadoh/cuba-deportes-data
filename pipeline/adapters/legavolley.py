"""Voleibol — Lega Pallavolo Serie A (legavolley.it), SuperLega masculina.

  /classifica/?Anno={año}&IdCampionato={id}   clasificación (sin IdCampionato -> SuperLega)
  /category/superlega/                         enlaces /team/{id} de la temporada actual
  /team/{id}                                   plantilla + cuerpo técnico + logo

Columnas de la clasificación (verificadas con 2025/2026):
  Equipo | Punti | Giocate Vinte Perse | 3·0 3·1 3·2 2·3 1·3 0·3 | Set V P | Punti F S | Quoziente Set Punti | Squal.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RosterEntry, StandingGroup, StandingRow, TeamRec
from ..core.util import clean, country_code, natural_name, norm_name, to_float, to_int
from .base import Ctx

BASE = "https://www.legavolley.it"
ROLE = {"palleggiatore": "S", "schiacciatore": "OH", "opposto": "OPP", "centrale": "MB", "libero": "L"}


def _n(s: str) -> str:
    return norm_name(s.replace("’", "'").replace("'", " "))


def parse_standings(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    out = []
    for tr in s.select("table")[0].select("tr")[2:]:
        c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
        if len(c) < 17:
            continue
        m = re.match(r"(\d+)\s+(.*)", c[0])
        if not m:
            continue
        num = lambda v: to_int(v.replace(".", "")) if v else None  # "1.960" -> 1960
        out.append({
            "rank": int(m[1]), "team": m[2].strip(),
            "stats": {k: v for k, v in {
                "PTS": num(c[1]), "GP": num(c[2]), "W": num(c[3]), "L": num(c[4]),
                "R30": num(c[5]), "R31": num(c[6]), "R32": num(c[7]), "R23": num(c[8]), "R13": num(c[9]), "R03": num(c[10]),
                "SW": num(c[11]), "SL": num(c[12]), "PF": num(c[13]), "PA": num(c[14]),
                "SR": to_float(c[15]), "PR": to_float(c[16]),
            }.items() if v is not None},
        })
    return out


def parse_team_links(html: str) -> dict[str, str]:
    s = BeautifulSoup(html, "lxml")
    out = {}
    for a in s.select('a[href*="/team/"]'):
        m = re.search(r"/team/(\d+)", a["href"])
        name = a.get_text(" ", strip=True)
        if m and name:
            out[_n(name)] = m[1]
    return out


def parse_team(html: str) -> dict:
    s = BeautifulSoup(html, "lxml")
    title = clean(s.title.get_text()) if s.title else None
    players, staff = [], []
    tables = s.select("table")
    if tables:
        hdr = [c.get_text(strip=True) for c in tables[0].select("tr")[0].find_all(["td", "th"])]
        if "Ruolo" in hdr:
            for tr in tables[0].select("tr")[1:]:
                c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
                a = tr.select_one('a[href*="/player/"]')
                if not a or len(c) < 8:
                    continue
                key = a["href"].rstrip("/").split("/")[-1]
                role = c[3]
                name = c[2][: -len(role)].strip() if role and c[2].endswith(role) else c[2]
                img = tr.select_one("img")
                players.append({"key": key, "number": c[1] or None, "name": natural_name(name), "role": role,
                                "birth": c[4] or None, "height": to_float(c[5]), "nat": c[7] or None,
                                "photo": img.get("src") if img else None})
        if len(tables) > 1:
            for tr in tables[1].select("tr"):
                c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
                if len(c) >= 3 and c[1]:
                    img = tr.select_one("img")
                    k = re.search(r"Key=([^&]+)", img.get("src", "")) if img else None
                    staff.append({"name": natural_name(c[1]), "role": c[2], "key": k[1] if k else None,
                                  "photo": img.get("src") if img else None})
    logos = []
    for img in s.select("img[src*='GetLogo.aspx']"):
        src = urljoin(BASE + "/", img["src"]).replace(" ", "%20")
        if src not in logos:
            logos.append(src)
    return {"title": title, "players": players, "staff": staff, "logos": logos}


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="legavolley")
    camp = (comp.params.get("campionati") or {}).get(season)
    params = {"Anno": start_year}
    if camp:
        params["IdCampionato"] = camp
    rows = parse_standings(ctx.http.text(f"{BASE}/classifica/", params=params) or "")
    is_current = start_year == comp.current_season()[1]
    links = parse_team_links(ctx.http.text(f"{BASE}/category/superlega/") or "") if is_current else {}

    teams: dict[str, TeamRec] = {}
    g = StandingGroup("regular", "Temporada regular")
    for r in rows:
        lv_id = links.get(_n(r["team"]))
        name_key = _n(r["team"]).replace(" ", "-")
        if lv_id:
            tid = ctx.ids.team(comp.sport, "legavolley", lv_id, r["team"])
            ctx.ids.alias("team", "legavolley-name", name_key, tid)   # permite enlazar temporadas pasadas por nombre
        else:
            tid = ctx.ids.team(comp.sport, "legavolley-name", name_key, r["team"])
        rec = TeamRec(id=tid, name=r["team"], country="IT", external_ids={"legavolley": lv_id} if lv_id else {})
        if lv_id:
            rec.logos.append(Candidate("url", f"{BASE}/GetLogo.aspx?Field=LogoWeb&maxWidth=220&Proc=LogoSquadra&Web=0&Key={lv_id}&Char=False", "legavolley", 20))
            rec.links["official"] = f"{BASE}/team/{lv_id}"
        teams[tid] = rec
        g.rows.append(StandingRow(tid, r["rank"], r["stats"]))
    b.teams = list(teams.values())
    if g.rows:
        b.standings.append(g)
    if mode == "standings" or not is_current:
        return b

    for tid, team in teams.items():
        lv_id = team.external_ids.get("legavolley")
        if not lv_id:
            continue
        info = parse_team(ctx.http.text(f"{BASE}/team/{lv_id}") or "")
        # el logo de la "squadra" a veces es un JPEG vacío de 2x2; se añade el de la sociedad como alternativa
        for k, src in enumerate(info["logos"]):
            if src not in [c.value for c in team.logos]:
                team.logos.append(Candidate("url", src, "legavolley", 21 + k))
        entries = []
        for p in info["players"]:
            pid = ctx.ids.person("legavolley", p["key"], p["name"], p.get("birth"))
            nat = country_code(p.get("nat"))
            b.add_person(PersonRec(id=pid, full_name=p["name"], birth_date=p.get("birth"), height_cm=p.get("height"),
                                   nationalities=[nat] if nat else [], gender="M",
                                   external_ids={"legavolley": p["key"]},
                                   photos=[Candidate("url", p["photo"], "legavolley", 20)] if p.get("photo") else []))
            pos = ROLE.get((p.get("role") or "").lower())
            entries.append(RosterEntry(pid, position=pos, group=pos, number=p.get("number"),
                                       extra={"roleName": p.get("role")}))
        for st in info["staff"]:
            key = st.get("key") or st["name"]
            pid = ctx.ids.person("legavolley-staff", key, st["name"])
            b.add_person(PersonRec(id=pid, full_name=st["name"], external_ids={"legavolley": st["key"]} if st.get("key") else {},
                                   photos=[Candidate("url", st["photo"], "legavolley", 20)] if st.get("photo") else []))
            entries.append(RosterEntry(pid, role="staff", role_name=st["role"]))
        if entries:
            b.rosters[tid] = entries
    return b

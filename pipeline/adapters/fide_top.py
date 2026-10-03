"""Ajedrez — Top 100 oficial de la FIDE (ratings.fide.com/a_top.php).

Listas: open, women, juniors, girls. Columnas: # | Name | Fed | Rating | B-Year.
El título de la página indica el mes de la lista ("Top 100 Players October 2026").
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RankingRec, StandingRow
from ..core.util import clean, country_code, to_int
from .base import Ctx

URL = "https://ratings.fide.com/a_top.php"
NAMES = {"open": "Absoluto", "women": "Femenino", "juniors": "Juvenil (sub-20)", "girls": "Juvenil femenino (sub-20)"}


def fide_name(s: str) -> str:
    """'Carlsen, Magnus' -> 'Magnus Carlsen'"""
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        return f"{first} {last}".strip()
    return s.strip()


def parse_top(html: str) -> tuple[str | None, list[dict]]:
    s = BeautifulSoup(html, "lxml")
    m = re.search(r"Top 100 [A-Za-z ]*?([A-Z][a-z]+ \d{4})", s.get_text(" "))
    period = None
    if m:
        try:
            period = datetime.strptime(m[1], "%B %Y").strftime("%Y-%m")
        except ValueError:
            period = None
    rows = []
    for tr in s.select("table")[0].select("tr")[1:]:
        c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
        a = tr.select_one("a[href*='/profile/']")
        if len(c) < 5 or not a:
            continue
        rows.append({"rank": to_int(c[0]), "name": fide_name(c[1]), "fed": c[2], "rating": to_int(c[3]),
                     "byear": c[4] or None, "fide_id": a["href"].rstrip("/").split("/")[-1]})
    return period, rows


def person_from_fide(ctx: Ctx, fide_id: str, name: str, fed: str | None, byear: str | None,
                     title: str | None = None, gender: str | None = None) -> PersonRec:
    pid = ctx.ids.person("fide", fide_id, name, byear)
    nat = country_code(fed) if fed else None
    return PersonRec(id=pid, full_name=name, birth_date=byear, nationalities=[nat] if nat else [], title=title or None,
                     gender=gender, external_ids={"fide": str(fide_id)},
                     photos=[Candidate("lichess_fide", str(fide_id), "lichess", 30)],
                     extra={"federation": fed} if fed else {})


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="fide")
    for lst in comp.params.get("lists", ["open"]):
        period, rows = parse_top(ctx.http.text(URL, params={"list": lst}) or "")
        rk = RankingRec(id=lst, name=f"Top 100 FIDE · {NAMES.get(lst, lst)}", as_of=period,
                        extra={"url": f"{URL}?list={lst}"})
        for r in rows:
            p = b.add_person(person_from_fide(ctx, r["fide_id"], r["name"], r["fed"], r["byear"],
                                              gender="F" if lst in ("women", "girls") else None))
            rk.entries.append(StandingRow(p.id, r["rank"], {"RANK": r["rank"], "ELO": r["rating"]},
                                          participant_type="person"))
        b.rankings.append(rk)
    return b

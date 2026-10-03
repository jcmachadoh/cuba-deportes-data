"""Boxeo — clasificaciones oficiales del WBC (wbcboxing.com).

  /en/ratings/{male|female}/{division}/
    - bloque del campeón (nombre, país, récord, fechas, campeones Silver/WBO/IBF...)
    - tabla: # | Boxer | Nationality (bandera + país) | Title
    - "Updated: September 3, 2026"
Las divisiones se descubren de los enlaces del propio sitio, así que si el WBC
crea o elimina una división no hay que tocar el código.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RankingRec, StandingRow
from ..core.util import clean, countries_from_text, country_code, slugify, to_int
from .base import Ctx

BASE = "https://wbcboxing.com"
LABELS = ("Born", "Height", "Reach", "Stance", "Pro debut", "KO ratio", "Champion since")
OTHER_TITLES = ("Silver", "International", "WBO", "IBF", "WBA", "Interim", "Diamond", "Franchise")


def _date(s: str | None) -> str | None:
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s or "", fmt).date().isoformat()
        except ValueError:
            continue
    return None


def division_links(html: str) -> list[tuple[str, str]]:
    out = []
    for g, d in re.findall(r"/en/ratings/(male|female)/([a-z-]+)/", html):
        if (g, d) not in out:
            out.append((g, d))
    return out


def parse_division(html: str) -> dict:
    s = BeautifulSoup(html, "lxml")
    lines = [l for l in s.get_text("\n", strip=True).split("\n") if l.strip()]
    out: dict = {"champion": None, "others": {}, "updated": None, "rows": []}
    m = re.search(r"Updated:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", "\n".join(lines))
    out["updated"] = _date(m[1]) if m else None
    if "WBC World Champion" in lines:
        i = lines.index("WBC World Champion")
        j = i + 2
        nickname = None
        if j < len(lines) and lines[j][:1] in "“\"«":     # apodo opcional antes del nombre
            nickname = lines[j].strip("“”\"«» ")
            j += 1
        name = lines[j] if j < len(lines) else None
        champ: dict = {"division": lines[i + 1], "name": name, "nickname": nickname}
        j += 1
        if j < len(lines) and not re.search(r"[A-Za-z]", lines[j]):  # bandera emoji
            j += 1
        champ["country"] = country_code(lines[j]) if j < len(lines) else None
        # récord "27 – 0 19 KO"
        rec = " ".join(lines[j + 1:j + 6])
        mr = re.match(r"(\d+)\s*[–-]\s*(\d+)(?:\s*[–-]\s*(\d+))?\s+(\d+)\s*KO", rec)
        if mr:
            champ["record"] = {"W": int(mr[1]), "L": int(mr[2]), "D": int(mr[3] or 0), "KO": int(mr[4])}
        end = next((k for k in range(i, len(lines)) if lines[k].startswith("All boxers rated")), len(lines))
        block = lines[i:end]
        for lab in LABELS:
            if lab in block:
                champ[lab] = block[block.index(lab) + 1]
        for t in OTHER_TITLES:
            if t in block:
                v = block[block.index(t) + 1]
                out["others"][t] = None if v == "Vacant" else v
        img = s.find("img", alt=name) if name else None
        champ["img"] = img.get("src") if img else None
        if name and name != "Vacant":
            out["champion"] = champ
    tb = s.select_one("table")
    if tb:
        for tr in tb.select("tr")[1:]:
            c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
            if len(c) >= 3 and c[1]:
                out["rows"].append({"rank": to_int(c[0].rstrip(".")), "name": clean(c[1]),
                                    "countries": countries_from_text(c[2]), "country_text": clean(c[2]),
                                    "title": clean(c[3]) if len(c) > 3 else None})
    return out


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="wbcboxing")
    first = ctx.http.text(f"{BASE}/en/ratings/male/heavyweight/") or ""
    genders = set(comp.params.get("genders") or ["male", "female"])
    persons: dict[str, PersonRec] = {}

    def person(name: str, countries: list[str], gender: str) -> PersonRec:
        key = f"{gender}:{slugify(name)}"   # el WBC no publica IDs; clave = género + nombre
        if key in persons:
            return persons[key]
        p = PersonRec(id=ctx.ids.person("wbc", key, name), full_name=name, nationalities=countries,
                      gender="F" if gender == "female" else "M")
        persons[key] = p
        return b.add_person(p)

    for gender, div in division_links(first):
        if gender not in genders:
            continue
        url = f"{BASE}/en/ratings/{gender}/{div}/"
        html = first if (gender, div) == ("male", "heavyweight") else ctx.http.text(url, allow_404=True)
        if not html:
            continue
        d = parse_division(html)
        rk = RankingRec(id=f"{gender}-{div}", name=f"{'Femenino' if gender == 'female' else 'Masculino'} · {div.replace('-', ' ').title()}",
                        as_of=d["updated"], extra={"gender": "F" if gender == "female" else "M", "division": div,
                                                   "otherTitles": {k: v for k, v in d["others"].items() if v}, "url": url})
        ch = d["champion"]
        if ch:
            p = person(ch["name"], [ch["country"]] if ch.get("country") else [], gender)
            p.nickname = ch.get("nickname")
            if ch.get("Born"):
                p.birth_date = _date(ch["Born"])
            p.extra = {k: v for k, v in {"record": ch.get("record"), "stance": ch.get("Stance"), "height": ch.get("Height"),
                                         "reach": ch.get("Reach"), "proDebut": _date(ch.get("Pro debut")),
                                         "koRatio": ch.get("KO ratio")}.items() if v}
            if ch.get("img"):
                p.photos.append(Candidate("url", ch["img"], "wbcboxing", 15))
            rk.champion_id = p.id
            stats = {"RANK": 0}
            if ch.get("record"):
                stats.update(ch["record"])
            rk.entries.append(StandingRow(p.id, 0, stats, {"champion": True, "since": _date(ch.get("Champion since"))},
                                          participant_type="person"))
        for r in d["rows"]:
            p = person(r["name"], r["countries"], gender)
            extra = {"title": r["title"]} if r["title"] else {}
            if not r["countries"] and r["country_text"]:
                extra["countryText"] = r["country_text"]
            rk.entries.append(StandingRow(p.id, r["rank"], {"RANK": r["rank"]}, extra, participant_type="person"))
        b.rankings.append(rk)
    return b

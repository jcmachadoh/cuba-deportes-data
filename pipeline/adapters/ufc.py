"""UFC — rankings oficiales de ufc.com (HTML).

Se descartó el endpoint de rankings de ESPN porque, verificado el 2026-10-03,
devuelve rankings desactualizados (p. ej. Charles Oliveira como campeón ligero).

  https://www.ufc.com/rankings          libra por libra + divisiones (campeón + top 15)
  https://www.ufc.com/athlete/{slug}    ficha: lugar de nacimiento, récord, apodo, foto

Las fichas se consultan para peleadores nuevos y, para todos, una vez por
semana (lunes) en modo full, para refrescar el récord.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, PersonRec, RankingRec, StandingRow, TeamRec
from ..core.util import clean, country_code, slugify, to_float, to_int, today
from .base import Ctx

BASE = "https://www.ufc.com"


def parse_rankings(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for g in s.select(".view-grouping"):
        head = g.select_one(".view-grouping-header")
        name = clean(head.get_text(" ")) if head else None
        if not name or name in seen:
            continue
        seen.add(name)
        cap = g.select_one("caption")
        champ = cap.select_one("h5 a") if cap else None
        is_champ = bool(cap and cap.select_one("h6") and "Champion" in cap.select_one("h6").get_text())
        cimg = cap.select_one("img") if cap else None
        rows = []
        for tr in g.select("tbody tr"):
            a = tr.select_one("a[href*='/athlete/']")
            if not a:
                continue
            ch = tr.select_one(".views-field-weight-class-rank-change")
            change = clean(ch.get_text(" ")) if ch else None
            m = re.search(r"(increased|decreased) by\s*(\d+)", change or "")
            rows.append({"rank": to_int(clean(tr.find("td").get_text())), "name": clean(a.get_text()),
                         "slug": a["href"].rstrip("/").split("/")[-1],
                         "trend": (int(m[2]) if m[1] == "increased" else -int(m[2])) if m else 0})
        out.append({
            "name": name, "id": slugify(name.replace("Top Rank", "")),
            "pound_for_pound": "Pound-for-Pound" in name, "gender": "F" if name.startswith("Women") else "M",
            "champion": {"name": clean(champ.get_text()), "slug": champ["href"].rstrip("/").split("/")[-1],
                         "img": cimg.get("src") if cimg else None} if champ else None,
            "champion_is_title": is_champ, "rows": rows,
        })
    return out


def parse_athlete(html: str) -> dict:
    s = BeautifulSoup(html, "lxml")
    bio = {}
    for f in s.select(".c-bio__field"):
        lab = f.select_one(".c-bio__label")
        val = f.select_one(".c-bio__text")
        if lab and val:
            bio[clean(lab.get_text())] = clean(val.get_text(" "))
    rec = s.select_one(".hero-profile__division-body")
    m = re.match(r"(\d+)-(\d+)-(\d+)", clean(rec.get_text()) if rec else "")
    nick = s.select_one(".hero-profile__nickname")
    og = s.select_one('meta[property="og:image"]')
    div = s.select_one(".hero-profile__division-title")
    pob = bio.get("Place of Birth")
    return {
        "birth_place": pob, "birth_country": country_code(pob.split(",")[-1]) if pob else None,
        "birth_city": pob.split(",")[0].strip() if pob and "," in pob else None,
        "record": {"W": int(m[1]), "L": int(m[2]), "D": int(m[3])} if m else None,
        "nickname": clean(nick.get_text()).strip('"') if nick else None,
        "height_cm": round(to_float(bio["Height"]) * 2.54, 1) if to_float(bio.get("Height")) else None,
        "weight_kg": round(to_float(bio["Weight"]) * 0.4536, 1) if to_float(bio.get("Weight")) else None,
        "reach_cm": round(to_float(bio["Reach"]) * 2.54, 1) if to_float(bio.get("Reach")) else None,
        "status": bio.get("Status"), "division": clean(div.get_text()) if div else None,
        "photo": og.get("content") if og else None,
    }


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="ufc.com")
    b.source_urls.append(f"{BASE}/rankings")
    ranks = parse_rankings(ctx.http.text(f"{BASE}/rankings") or "")
    weekly = today().weekday() == 0
    persons: dict[str, PersonRec] = {}

    def person(slug: str, name: str, gender: str) -> PersonRec:
        if slug in persons:
            return persons[slug]
        known = ctx.ids.lookup("person", "ufc", slug)
        pid = known or ctx.ids.person("ufc", slug, name)
        p = PersonRec(id=pid, full_name=name, gender=gender, external_ids={"ufc": slug})
        if mode == "full" and (not known or weekly):
            try:
                a = parse_athlete(ctx.http.text(f"{BASE}/athlete/{slug}") or "")
                p.birth_country, p.birth_city = a["birth_country"], a["birth_city"]
                p.nickname, p.height_cm, p.weight_kg = a["nickname"], a["height_cm"], a["weight_kg"]
                p.extra = {k: a[k] for k in ("record", "reach_cm", "status", "division") if a.get(k)}
                if a.get("photo"):
                    p.photos.append(Candidate("url", a["photo"], "ufc.com", 15))
            except Exception as e:  # noqa: BLE001
                b.warnings.append(f"athlete {slug}: {e}")
        persons[slug] = p
        return b.add_person(p)

    for r in ranks:
        rk = RankingRec(id=r["id"], name=r["name"], as_of=str(today()),
                        extra={"poundForPound": r["pound_for_pound"], "gender": r["gender"]})
        if r["champion"] and r["champion_is_title"]:
            c = person(r["champion"]["slug"], r["champion"]["name"], r["gender"])
            if r["champion"].get("img"):
                c.photos.append(Candidate("url", r["champion"]["img"], "ufc.com", 16))
            rk.champion_id = c.id
            rk.entries.append(StandingRow(c.id, 0, {"RANK": 0}, {"champion": True}, participant_type="person"))
        for row in r["rows"]:
            p = person(row["slug"], row["name"], r["gender"])
            rk.entries.append(StandingRow(p.id, row["rank"], {"RANK": row["rank"]},
                                          {"trend": row["trend"]} if row["trend"] else {}, participant_type="person"))
        b.rankings.append(rk)
    return b

"""Ajedrez — torneos publicados en chess-results.com (p. ej. Capablanca in Memoriam).

Por cada edición configurada (tnr):
  ?art=0  ranking inicial: No. | título | Nombre | FIDE-ID | FED | Elo
  ?art=1  clasificación:   Rk. | No.Ini. | título | Nombre | FED | Elo | Pts. | Des 1..3
Se cruzan por número inicial para obtener el FIDE-ID de cada jugador.
Los puntos usan coma decimal ("6,5").
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, EventRec, StandingRow
from ..core.util import clean, to_float, to_int
from .base import Ctx
from .fide_top import fide_name, person_from_fide


def _rows(html: str) -> tuple[list[str], list[list[str]], str | None, str | None]:
    s = BeautifulSoup(html, "lxml")
    t = s.select_one("table.CRs1")
    title = clean(s.select_one("h2").get_text()) if s.select_one("h2") else None
    m = re.search(r"(?:Última actualización|Last update)\s*(\d{2}\.\d{2}\.\d{4})", s.get_text(" "))
    upd = datetime.strptime(m[1], "%d.%m.%Y").date().isoformat() if m else None
    if not t:
        return [], [], title, upd
    trs = t.select("tr")
    head = [c.get_text(" ", strip=True) for c in trs[0].find_all(["td", "th"])]
    return head, [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs[1:]], title, upd


def parse_start(html: str) -> dict[str, dict]:
    head, rows, _, _ = _rows(html)
    if "FIDE-ID" not in head:
        return {}
    i_no, i_name, i_id, i_fed, i_elo = head.index("No."), head.index("Nombre"), head.index("FIDE-ID"), head.index("FED"), head.index("Elo")
    out = {}
    for r in rows:
        if len(r) == len(head):
            out[r[i_no]] = {"title": r[i_name - 1] or None, "name": fide_name(r[i_name]), "fide": r[i_id] or None,
                            "fed": r[i_fed] or None, "elo": to_int(r[i_elo])}
    return out


def parse_final(html: str) -> tuple[str | None, str | None, list[dict]]:
    head, rows, title, upd = _rows(html)
    if "Pts." not in head:
        return title, upd, []
    ix = {h: i for i, h in enumerate(head) if h}
    out = []
    for r in rows:
        if len(r) != len(head):
            continue
        tb = {f"TB{k}": to_float(r[ix[f"Des {k}"]]) for k in (1, 2, 3) if f"Des {k}" in ix}
        out.append({"rank": to_int(r[ix["Rk."]]), "start_no": r[ix["No.Ini."]], "name": fide_name(r[ix["Nombre"]]),
                    "fed": r[ix["FED"]], "elo": to_int(r[ix["Elo"]]), "pts": to_float(r[ix["Pts."]]),
                    "title": r[ix["Nombre"] - 1] or None, **tb})
    return title, upd, out


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="chess-results")
    for ed in comp.params.get("editions", []):
        if str(ed["season"]) != season:
            continue
        host = ed.get("host", "chess-results.com")
        base = f"https://{host}/tnr{ed['tnr']}.aspx"
        start = parse_start(ctx.http.text(base, params={"lan": 2, "art": 0, "turdet": "NO", "flag": 30}) or "")
        title, upd, final = parse_final(ctx.http.text(base, params={"lan": 2, "art": 1, "turdet": "NO", "flag": 30}) or "")
        ev = EventRec(id=f"{ed['tnr']}", name=ed.get("name") or title or str(ed["tnr"]), group=ed.get("group"),
                      start=ed.get("start"), end=ed.get("end"), location=ed.get("location"),
                      url=f"{base}?lan=2&art=1", status=ed.get("status"),
                      extra={"officialName": title, "lastUpdate": upd, "players": len(start) or len(final)})
        for r in final:
            info = start.get(r["start_no"], {})
            fid = info.get("fide")
            if fid:
                p = person_from_fide(ctx, fid, r["name"], r["fed"], None, r["title"])
            else:
                from ..core.model import PersonRec
                from ..core.util import country_code
                nat = country_code(r["fed"])
                p = PersonRec(id=ctx.ids.person("chess-results", f"{ed['tnr']}:{r['start_no']}", r["name"]),
                              full_name=r["name"], nationalities=[nat] if nat else [], title=r["title"])
            p = b.add_person(p)
            stats = {"RANK": r["rank"], "PTS": r["pts"], "ELO": r["elo"], **{k: r[k] for k in ("TB1", "TB2", "TB3") if r.get(k) is not None}}
            ev.standings.append(StandingRow(p.id, r["rank"], stats, participant_type="person"))
        if final and ev.status is None:
            ev.extra["note"] = "clasificación según la última carga del organizador"
        b.events.append(ev)
    return b

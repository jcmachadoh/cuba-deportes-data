"""Ajedrez — ranking de una federación (por defecto CUB) a partir de la lista
oficial completa de la FIDE (ratings.fide.com/download/standard_rating_list_xml.zip,
~14 MB, se actualiza cada mes). Se lee en streaming y se filtra por país.

Campos XML: fideid, name, country, sex, title, w_title, o_title, foa_title,
rating, games, k, birthday, flag (i = inactivo, w = mujer, wi = mujer inactiva).
"""
from __future__ import annotations

import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from ..core.config import Competition
from ..core.model import Bundle, RankingRec, StandingRow
from ..core.util import to_int
from .base import Ctx
from .fide_top import fide_name, person_from_fide

URL = "https://ratings.fide.com/download/standard_rating_list_xml.zip"


def iter_players(zip_path: Path, federation: str):
    with zipfile.ZipFile(zip_path) as z:
        info = z.infolist()[0]
        file_date = datetime(*info.date_time[:3]).date().isoformat()
        with z.open(info) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != "player":
                    continue
                if (el.findtext("country") or "") == federation:
                    yield file_date, {c.tag: (c.text or "").strip() for c in el}
                el.clear()


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    fed = comp.params.get("federation", "CUB")
    top = int(comp.params.get("top", 500))
    b = Bundle(comp.id, season, source="fide")
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "list.zip"
        ctx.http.get(URL, stream_to=zp, use_cache=False)
        players, file_date = [], None
        for file_date, p in iter_players(zp, fed):
            players.append(p)
    active = [p for p in players if "i" not in (p.get("flag") or "") and to_int(p.get("rating"))]
    active.sort(key=lambda p: -to_int(p["rating"]))
    lists = {
        "open": ("Absoluto", active),
        "women": ("Femenino", [p for p in active if p.get("sex") == "F"]),
        "juniors": ("Juvenil (sub-20)", [p for p in active if (to_int(p.get("birthday")) or 0) >= start_year - 20]),
    }
    for lid, (lname, rows) in lists.items():
        rk = RankingRec(id=lid, name=f"Ranking FIDE {fed} · {lname}", as_of=file_date,
                        extra={"federation": fed, "totalPlayers": len(players), "activePlayers": len(active),
                               "fileDate": file_date, "url": URL})
        for i, p in enumerate(rows[:top], 1):
            title = p.get("title") or p.get("w_title") or None
            per = b.add_person(person_from_fide(ctx, p["fideid"], fide_name(p["name"]), p.get("country"),
                                                p.get("birthday") or None, title, p.get("sex") or None))
            rk.entries.append(StandingRow(per.id, i, {"RANK": i, "ELO": to_int(p["rating"])},
                                          {"games": to_int(p.get("games"))} if to_int(p.get("games")) else {},
                                          participant_type="person"))
        b.rankings.append(rk)
    return b

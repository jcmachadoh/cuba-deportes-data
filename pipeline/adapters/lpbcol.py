"""Liga Profesional de Béisbol de Colombia — lpbcol.com.co (WordPress + Elementor).

La tabla de /posiciones/ se arma con widgets de encabezado (.elementor-heading-title):
  "Equipo", "#", "W", "L", "T", "PCT", "GB", luego bloques de 7 valores por equipo.
La página no indica la temporada: se asume la temporada vigente según el
calendario de config (start_month). Se registra un aviso para revisión.
El sitio no publica plantillas estructuradas.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ..core.config import Competition
from ..core.model import Bundle, Candidate, StandingGroup, StandingRow, TeamRec
from ..core.util import clean, to_float, to_int
from .base import Ctx

URL = "https://www.lpbcol.com.co/posiciones/"
HEADER = ["Equipo", "#", "W", "L", "T", "PCT", "GB"]


def parse_standings(html: str) -> list[dict]:
    s = BeautifulSoup(html, "lxml")
    t = [clean(x.get_text(" ")) or "" for x in s.select(".elementor-heading-title")]
    for i in range(len(t) - len(HEADER)):
        if t[i:i + len(HEADER)] == HEADER:
            out, j = [], i + len(HEADER)
            while j + 7 <= len(t) and to_int(t[j + 1]) is not None and to_int(t[j + 2]) is not None:
                out.append(dict(zip(HEADER, t[j:j + 7])))
                j += 7
            return out
    return []


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="lpbcol")
    if start_year != comp.current_season()[1]:
        return b
    b.competition_logos = [Candidate("url", "https://www.lpbcol.com.co/wp-content/uploads/2025/11/Logo-LPBC-5.png", "lpbcol", 10)]
    g = StandingGroup("all", "Temporada regular")
    for r in parse_standings(ctx.http.text(URL) or ""):
        name = r["Equipo"]
        tid = ctx.ids.team(comp.sport, "lpbcol", name.lower(), name)
        b.teams.append(TeamRec(id=tid, name=name, country="CO", external_ids={"lpbcol": name.lower()}))
        stats = {"W": to_int(r["W"]), "L": to_int(r["L"]), "T": to_int(r["T"]), "PCT": to_float(r["PCT"]), "GB": to_float(r["GB"])}
        g.rows.append(StandingRow(tid, to_int(r["#"]), {k: v for k, v in stats.items() if v is not None}))
    if g.rows:
        b.standings.append(g)
        b.warnings.append("lpbcol no indica la temporada en la página; verificar al inicio de cada temporada")
    return b

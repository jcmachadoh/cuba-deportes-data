"""Ajedrez — torneos de élite transmitidos por Lichess (API pública, sin clave).

  GET /api/broadcast/top?page=N          active / upcoming / past (tier 3-5)
  GET /api/broadcast/{tourId}            rondas + fotos de jugadores por FIDE ID
  GET /broadcast/{tourId}/players        (Accept: application/json) clasificación
Lichess pide una petición a la vez y esperar 1 min tras un 429 (el cliente lo hace).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.config import Competition
from ..core.model import Bundle, Candidate, EventRec, StandingRow
from ..core.util import to_float
from .base import Ctx
from .fide_top import fide_name, person_from_fide

API = "https://lichess.org"


def _d(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat() if ms else None


def collect(ctx: Ctx, comp: Competition, season: str, start_year: int, mode: str) -> Bundle:
    b = Bundle(comp.id, season, source="lichess")
    min_tier = int(comp.params.get("min_tier", 4))
    max_events = int(comp.params.get("max_events", 30))
    tours: list[tuple[str, dict]] = []
    seen = set()
    for page in (1, 2):
        top = ctx.http.json(f"{API}/api/broadcast/top", params={"page": page})
        groups = [("in_progress", top.get("active") or []), ("upcoming", top.get("upcoming") or []),
                  ("finished", (top.get("past") or {}).get("currentPageResults") or [])]
        if page > 1:
            groups = groups[2:]
        for status, items in groups:
            for it in items:
                t = it.get("tour") or {}
                if (t.get("tier") or 0) >= min_tier and t["id"] not in seen:
                    seen.add(t["id"])
                    tours.append((status, t))
    tours = tours[:max_events]

    for status, t in tours:
        dates = t.get("dates") or []
        start, end = _d(dates[0]) if dates else None, _d(dates[-1]) if dates else None
        if start and not start.startswith(season) and not (end or "").startswith(season):
            continue  # cada temporada (año) guarda los torneos que la tocan
        info = t.get("info") or {}
        ev = EventRec(id=t["id"], name=t["name"], start=start, end=end, location=info.get("location"),
                      url=t.get("url"), status=status,
                      extra={k: v for k, v in {"format": info.get("format"), "timeControl": info.get("fideTC"),
                                               "tc": info.get("tc"), "website": info.get("website"),
                                               "tier": t.get("tier"), "image": t.get("image")}.items() if v})
        photos = {}
        if mode == "full" or status == "in_progress":
            try:
                det = ctx.http.json(f"{API}/api/broadcast/{t['id']}")
                photos = det.get("photos") or {}
                ev.extra["rounds"] = [{"name": r.get("name"), "startsAt": r.get("startsAt"), "finished": r.get("finished")}
                                      for r in det.get("rounds", [])]
            except Exception as e:  # noqa: BLE001
                b.warnings.append(f"tour {t['id']}: {e}")
            try:
                players = ctx.http.json(f"{API}/broadcast/{t['id']}/players") or []
            except Exception as e:  # noqa: BLE001
                b.warnings.append(f"players {t['id']}: {e}")
                players = []
            for pl in players:
                fid = pl.get("fideId")
                if not fid:
                    continue
                p = person_from_fide(ctx, str(fid), fide_name(pl.get("name", "")), pl.get("fed"), None, pl.get("title"))
                ph = photos.get(str(fid))
                if ph and ph.get("medium"):
                    p.photos.insert(0, Candidate("url", ph["medium"], "lichess", 12, credit=ph.get("credit")))
                p = b.add_person(p)
                stats = {"RANK": pl.get("rank"), "PTS": to_float(pl.get("score")), "ELO": pl.get("rating"),
                         "GP": pl.get("played")}
                extra = {k: v for k, v in {"team": pl.get("team"), "performance": (pl.get("performances") or {}).get(info.get("fideTC") or "standard")}.items() if v}
                ev.standings.append(StandingRow(p.id, pl.get("rank"), {k: v for k, v in stats.items() if v is not None},
                                                extra, participant_type="person"))
            ev.standings.sort(key=lambda r: r.rank or 9999)
        b.events.append(ev)
    return b

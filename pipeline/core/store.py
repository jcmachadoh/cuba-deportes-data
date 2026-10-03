"""Escritura del modelo canónico en data/v1 (fuente de verdad versionada en git).

Reglas:
  * Un archivo solo se reescribe si su contenido cambió (ignorando updatedAt),
    para que los commits del pipeline reflejen cambios reales.
  * Las entidades que llegan desde varias fuentes (personas, equipos) se
    fusionan: los campos nuevos no nulos ganan, los IDs externos se unen.
  * Las personas se guardan en 256 "shards" (persons/xx.json) para no superar
    el límite de 20.000 archivos de Workers Static Assets.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from . import config as cfg
from .model import Bundle, PersonRec, RosterEntry, TeamRec
from .paths import DATA_DIR, STATE_DIR
from .util import now_iso

log = logging.getLogger("store")
SCHEMA_VERSION = 1
VOLATILE = ("updatedAt",)


# ------------------------------------------------------------------ JSON I/O
def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def write_json(path: Path, obj: Any) -> bool:
    """Escribe si cambió. Devuelve True si hubo escritura."""
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if _strip_volatile(old) == _strip_volatile(obj):
                return False
        except json.JSONDecodeError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return True


def envelope(doc_type: str, doc_id: str, payload: dict[str, Any], source: str | list[str] | None = None) -> dict[str, Any]:
    out = {"schemaVersion": SCHEMA_VERSION, "type": doc_type, "id": doc_id, "updatedAt": now_iso()}
    if source:
        out["sources"] = source if isinstance(source, list) else [source]
    out.update(payload)
    return out


def shard_of(person_id: str) -> str:
    return hashlib.sha1(person_id.encode()).hexdigest()[:2]


def _merge(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    out = dict(old)
    for k, v in new.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list) and k in ("nationalities", "sources", "cubanEvidence"):
            out[k] = sorted(set(out[k]) | set(v))
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ conversores
def person_doc(p: PersonRec, source: str) -> dict[str, Any]:
    nats = sorted(set(p.nationalities))   # el país de nacimiento va aparte (birthPlace)
    evidence = []
    if p.birth_country == "CU":
        evidence.append(f"{source}.birthCountry")
    if "CU" in p.nationalities:
        evidence.append(f"{source}.nationality")
    doc = {
        "id": p.id,
        "name": {k: v for k, v in {"full": p.full_name, "first": p.first_name, "last": p.last_name}.items() if v},
        "birthDate": p.birth_date,
        "birthPlace": {k: v for k, v in {"city": p.birth_city, "country": p.birth_country}.items() if v} or None,
        "nationalities": nats,
        "isCuban": bool(evidence),
        "cubanEvidence": evidence,
        "gender": p.gender,
        "nickname": p.nickname,
        "title": p.title,
        "body": {"heightCm": p.height_cm, "weightKg": p.weight_kg} if (p.height_cm or p.weight_kg) else None,
        "hand": {"bats": p.bats, "throws": p.throws} if (p.bats or p.throws) else None,
        "externalIds": p.external_ids,
        "sources": [source],
        "extra": p.extra or None,
    }
    return {k: v for k, v in doc.items() if v not in (None, {}, [])} | {"isCuban": doc["isCuban"]}


def team_doc(t: TeamRec, comp_id: str, sport: str, source: str) -> dict[str, Any]:
    doc = {
        "id": t.id, "sport": sport, "kind": t.kind,
        "name": {k: v for k, v in {"full": t.name, "short": t.short, "abbrev": t.abbrev, "nickname": t.nickname}.items() if v},
        "city": t.city, "country": t.country, "colors": t.colors or None, "venue": t.venue,
        "competitions": [comp_id], "externalIds": t.external_ids, "links": t.links or None,
        "sources": [source],
    }
    return {k: v for k, v in doc.items() if v not in (None, {}, [])}


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: p.get(k) for k in ("id", "name", "birthDate", "nationalities", "isCuban", "title") if p.get(k) not in (None, [])}
    if (p.get("birthPlace") or {}).get("country"):
        out["birthCountry"] = p["birthPlace"]["country"]
    return out


# ------------------------------------------------------------------ Store
class Store:
    def __init__(self, data_dir: Path | None = None, state_dir: Path | None = None):
        self.dir = data_dir or DATA_DIR
        self.state = state_dir or STATE_DIR
        self.written: list[Path] = []
        self._shards: dict[str, dict[str, Any]] = {}
        self._cands: dict[str, dict[str, Any]] = {}

    def _w(self, path: Path, obj: Any) -> None:
        if write_json(path, obj):
            self.written.append(path)

    # ---------------------------------------------------------------- personas
    def _shard(self, sid: str) -> dict[str, Any]:
        if sid not in self._shards:
            self._shards[sid] = read_json(self.dir / "persons" / f"{sid}.json", {"persons": {}})
        return self._shards[sid]

    def upsert_person(self, doc: dict[str, Any]) -> dict[str, Any]:
        sh = self._shard(shard_of(doc["id"]))
        old = sh["persons"].get(doc["id"], {})
        merged = _merge(old, doc)
        merged["isCuban"] = bool(old.get("isCuban") or doc.get("isCuban"))
        sh["persons"][doc["id"]] = merged
        return merged

    def get_person(self, pid: str) -> dict[str, Any] | None:
        return self._shard(shard_of(pid))["persons"].get(pid)

    def flush(self) -> None:
        for sid, sh in self._shards.items():
            sh_sorted = {"schemaVersion": SCHEMA_VERSION, "type": "persons", "id": sid,
                         "updatedAt": now_iso(), "persons": dict(sorted(sh["persons"].items()))}
            self._w(self.dir / "persons" / f"{sid}.json", sh_sorted)

    # ---------------------------------------------------------------- candidatos de imagen
    def add_candidates(self, kind: str, entity_id: str, cands: list[dict[str, Any]]) -> None:
        if not cands:
            return
        path = self.state / "candidates" / f"{kind}.json"
        data = self._cand_cache(kind, path)
        cur = {(c["type"], c["value"]): c for c in data.get(entity_id, [])}
        for c in cands:
            cur[(c["type"], c["value"])] = c
        data[entity_id] = sorted(cur.values(), key=lambda c: (c.get("priority", 50), c["value"]))

    def _cand_cache(self, kind: str, path: Path) -> dict[str, Any]:
        if kind not in self._cands:
            self._cands[kind] = read_json(path, {})
        return self._cands[kind]

    def flush_candidates(self) -> None:
        for kind, data in self._cands.items():
            path = self.state / "candidates" / f"{kind}.json"
            write_json(path, dict(sorted(data.items())))

    # ---------------------------------------------------------------- bundle
    def write_bundle(self, b: Bundle) -> dict[str, int]:
        comp = cfg.competitions()[b.competition_id]
        sport = comp.sport
        base = self.dir / "competitions" / comp.id
        sdir = base / "seasons" / b.season
        counts = {"teams": 0, "persons": 0, "rosters": 0, "standings": 0, "rankings": 0, "events": 0}

        # competición + lista de temporadas
        meta_path = self.dir / "competitions" / f"{comp.id}.json"
        meta = read_json(meta_path, {})
        seasons = {s["id"]: s for s in meta.get("seasons", [])}
        sinfo = seasons.get(b.season, {"id": b.season})
        sinfo.update({k: v for k, v in b.season_info.items() if v is not None})
        sinfo["current"] = b.season == comp.current_season()[0]
        seasons[b.season] = sinfo
        for s in seasons.values():
            s["current"] = s["id"] == comp.current_season()[0]
        doc = envelope("competition", comp.id, comp.to_public() | {
            "seasons": sorted(seasons.values(), key=lambda s: s["id"], reverse=True),
        }, b.source)
        self._w(meta_path, doc)
        if b.competition_logos:
            self.add_candidates("logos", comp.id, [c.as_dict() for c in b.competition_logos])
        if comp.logo:   # el logo fijado en config tiene la máxima prioridad
            self.add_candidates("logos", comp.id, [{"type": "url", "value": comp.logo["url"], "source": comp.logo.get("source", "config"), "priority": 5}])

        # personas
        pdocs: dict[str, dict[str, Any]] = {}
        for p in b.persons:
            pdocs[p.id] = self.upsert_person(person_doc(p, b.source))
            if p.photos:
                self.add_candidates("photos", p.id, [c.as_dict() for c in p.photos])
            counts["persons"] += 1

        # equipos
        team_summaries = []
        for t in b.teams:
            tpath = self.dir / "teams" / f"{t.id}.json"
            old = read_json(tpath, {})
            new = team_doc(t, comp.id, sport, b.source)
            merged = _merge({k: v for k, v in old.items() if k not in ("schemaVersion", "type", "updatedAt")}, new)
            merged["competitions"] = sorted(set(old.get("competitions", [])) | {comp.id})
            self._w(tpath, envelope("team", t.id, {k: v for k, v in merged.items() if k != "id"}, merged.get("sources")))
            if t.logos:
                self.add_candidates("logos", t.id, [c.as_dict() for c in t.logos])
            team_summaries.append({"id": t.id, "name": new["name"], "country": t.country})
            counts["teams"] += 1
        if team_summaries:
            self._w(sdir / "teams.json", envelope("season-teams", f"{comp.id}:{b.season}",
                                                  {"competitionId": comp.id, "season": b.season, "teams": team_summaries}, b.source))

        # plantillas por posición
        groups_cfg = cfg.sports()[sport].get("roster_groups") or []
        for team_id, entries in b.rosters.items():
            self._w(self.dir / "teams" / team_id / "seasons" / b.season / "roster.json",
                    self._roster_doc(comp.id, sport, b.season, team_id, entries, pdocs, groups_cfg, b.source))
            counts["rosters"] += 1

        # clasificación
        if b.standings:
            self._w(sdir / "standings.json", envelope("standings", f"{comp.id}:{b.season}", {
                "competitionId": comp.id, "season": b.season,
                "groups": [{"id": g.id, "name": g.name, "rows": [
                    {"participantId": r.participant_id, "participantType": r.participant_type,
                     "rank": r.rank, "stats": r.stats, **({"extra": r.extra} if r.extra else {})}
                    for r in g.rows]} for g in b.standings],
            }, b.source))
            counts["standings"] = sum(len(g.rows) for g in b.standings)

        # rankings (ajedrez, UFC, boxeo)
        for rk in b.rankings:
            self._w(sdir / "rankings" / f"{rk.id}.json", envelope("ranking", f"{comp.id}:{b.season}:{rk.id}", {
                "competitionId": comp.id, "season": b.season, "rankingId": rk.id, "name": rk.name,
                "asOf": rk.as_of, "championId": rk.champion_id, "extra": rk.extra or None,
                "entries": [self._entry(r, pdocs) for r in rk.entries],
            }, b.source))
            counts["rankings"] += 1

        # eventos / torneos
        for ev in b.events:
            self._w(sdir / "events" / f"{ev.id}.json", envelope("event", f"{comp.id}:{b.season}:{ev.id}", {
                "competitionId": comp.id, "season": b.season, "name": ev.name, "group": ev.group,
                "start": ev.start, "end": ev.end, "location": ev.location, "url": ev.url, "status": ev.status,
                "extra": ev.extra or None, "standings": [self._entry(r, pdocs) for r in ev.standings],
            }, b.source))
            counts["events"] += 1
        return counts

    def _entry(self, r, pdocs) -> dict[str, Any]:
        e = {"rank": r.rank, "participantId": r.participant_id, "participantType": r.participant_type, "stats": r.stats}
        if r.participant_type == "person" and r.participant_id in pdocs:
            e["person"] = _summary(pdocs[r.participant_id])
        if r.extra:
            e["extra"] = r.extra
        return e

    def _roster_doc(self, comp_id, sport, season, team_id, entries: list[RosterEntry], pdocs, groups_cfg, source):
        order = [g["code"] for g in groups_cfg]
        names = {g["code"]: g["name"] for g in groups_cfg}
        buckets: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            g = "STAFF" if e.role == "staff" else (e.group or cfg.group_for(sport, e.position) or "OTHER")
            item = {"personId": e.person_id, "number": e.number, "position": e.position,
                    "role": e.role, "roleName": e.role_name, "status": e.status}
            if e.person_id in pdocs:
                item["person"] = _summary(pdocs[e.person_id])
            if e.extra:
                item["extra"] = e.extra
            buckets.setdefault(g, []).append({k: v for k, v in item.items() if v is not None})
        groups = []
        for code in order + sorted(set(buckets) - set(order)):
            if code in buckets:
                groups.append({"code": code, "name": names.get(code, {"es": code}),
                               "players": sorted(buckets[code], key=lambda x: (_num(x.get("number")), x["personId"]))})
        return envelope("roster", f"{team_id}:{season}", {
            "teamId": team_id, "competitionId": comp_id, "season": season,
            "count": sum(len(g["players"]) for g in groups), "groups": groups,
        }, source)


def _num(n: Any) -> int:
    try:
        return int(str(n))
    except (TypeError, ValueError):
        return 9999

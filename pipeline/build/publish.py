"""Genera public/ (lo que se sube a Cloudflare Workers Static Assets).

data/v1 es la fuente de verdad (canónica, sin URLs de imágenes); aquí se
"hidrata" para la app:
  * filas de clasificación con nombre/abreviatura/logo del equipo
  * personas con su foto resuelta (url + crédito)
  * historial de temporadas por equipo (a partir de las clasificaciones)
  * índice "cubanos por el mundo"
  * media.json + paquetes zip de logos por deporte (descarga en el primer arranque)
  * manifest.json con sha256 y tamaño de cada archivo (sincronización incremental)
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..core import config as cfg
from ..core.paths import DATA_DIR, PUBLIC_DIR, STATE_DIR
from ..core.store import SCHEMA_VERSION, read_json
from ..core.util import now_iso

log = logging.getLogger("build")
MAX_FILES = 19000                 # límite de Workers Static Assets: 20.000 por versión
MAX_BYTES = 25 * 1024 * 1024      # 25 MiB por archivo
MEDIA_SRC = DATA_DIR.parent / "media" / "logos"


class Builder:
    def __init__(self, out: Path):
        self.out = out
        self.v1 = out / "v1"
        self.logos = read_json(STATE_DIR / "media" / "logos.json", {})
        self.photos = read_json(STATE_DIR / "media" / "photos.json", {})
        self.teams: dict[str, dict] = {}
        self.persons: dict[str, dict] = {}
        self.manifest: dict[str, dict] = {}

    # ------------------------------------------------------------ helpers
    def logo(self, eid: str) -> dict | None:
        lg = self.logos.get(eid)
        if not lg or lg.get("status") != "ok":
            return None
        return {"hash": lg["hash"], "sizes": lg["sizes"], "path": f"/media/logos/{lg['hash']}-{{size}}.webp"}

    def photo(self, pid: str) -> dict | None:
        ph = self.photos.get(pid)
        if not ph or ph.get("status") != "ok":
            return None
        return {k: v for k, v in {"url": ph["url"], "source": ph.get("source"), "credit": ph.get("credit"),
                                  "license": ph.get("license"), "page": ph.get("page")}.items() if v}

    def team_ref(self, tid: str) -> dict:
        t = self.teams.get(tid, {})
        return {k: v for k, v in {"id": tid, "name": (t.get("name") or {}).get("full"),
                                  "short": (t.get("name") or {}).get("short"),
                                  "abbrev": (t.get("name") or {}).get("abbrev"), "logo": self.logo(tid)}.items() if v}

    def hydrate_person(self, summary: dict) -> dict:
        ph = self.photo(summary["id"])
        return summary | ({"photo": ph} if ph else {})

    def write(self, rel: str, obj: Any) -> None:
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        if len(data) > MAX_BYTES:
            raise RuntimeError(f"{rel} supera 25 MiB")
        p.write_bytes(data)
        self.manifest["/" + rel] = {"sha256": hashlib.sha256(data).hexdigest()[:20], "bytes": len(data)}

    # ------------------------------------------------------------ build
    def run(self) -> dict[str, int]:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.v1.mkdir(parents=True)
        for f in (DATA_DIR / "teams").glob("*.json"):
            self.teams[f.stem] = read_json(f)
        for f in (DATA_DIR / "persons").glob("*.json"):
            self.persons.update(read_json(f)["persons"])

        comps = {c.id: c for c in cfg.competitions().values()}
        history: dict[str, list[dict]] = {}
        cubans: dict[str, dict] = {}

        def cuban_link(pid: str, link: dict) -> None:
            p = self.persons.get(pid)
            if p and p.get("isCuban"):
                c = cubans.setdefault(pid, {"person": p, "links": []})
                if link not in c["links"]:
                    c["links"].append(link)

        # --------------------------------------------- competiciones
        comp_index = []
        for f in sorted((DATA_DIR / "competitions").glob("*.json")):
            doc = read_json(f)
            cid = doc["id"]
            if cid not in comps:
                continue
            doc["logo"] = self.logo(cid)
            self.write(f"v1/competitions/{cid}.json", doc)
            cur = next((s["id"] for s in doc.get("seasons", []) if s.get("current")), None)
            comp_index.append({k: doc.get(k) for k in ("id", "sport", "name", "short", "country", "tier", "tags", "logo")}
                              | {"currentSeason": cur, "latestSeason": (doc.get("seasons") or [{}])[0].get("id"),
                                 "enabled": comps[cid].enabled})
            base = DATA_DIR / "competitions" / cid / "seasons"
            for sdir in sorted(base.glob("*")) if base.exists() else []:
                season = sdir.name
                rel = f"v1/competitions/{cid}/seasons/{season}"
                st = read_json(sdir / "standings.json")
                if st:
                    for g in st["groups"]:
                        for r in g["rows"]:
                            if r["participantType"] == "team":
                                r["team"] = self.team_ref(r["participantId"])
                                history.setdefault(r["participantId"], []).append({
                                    "competitionId": cid, "season": season, "group": g["name"],
                                    "rank": r.get("rank"), "stats": r.get("stats")})
                    self.write(f"{rel}/standings.json", st)
                tl = read_json(sdir / "teams.json")
                if tl:
                    tl["teams"] = [t | {"logo": self.logo(t["id"])} for t in tl["teams"]]
                    self.write(f"{rel}/teams.json", tl)
                rk_index = []
                for rf in sorted((sdir / "rankings").glob("*.json")):
                    rk = read_json(rf)
                    for e in rk["entries"]:
                        if e.get("person"):
                            e["person"] = self.hydrate_person(e["person"])
                        cuban_link(e["participantId"], {"type": "ranking", "competitionId": cid, "season": season,
                                                        "rankingId": rk["rankingId"], "rankingName": rk["name"], "rank": e.get("rank")})
                    self.write(f"{rel}/rankings/{rf.stem}.json", rk)
                    rk_index.append({"id": rk["rankingId"], "name": rk["name"], "asOf": rk.get("asOf"),
                                     "count": len(rk["entries"]), "championId": rk.get("championId")})
                ev_index = []
                for ef in sorted((sdir / "events").glob("*.json")):
                    ev = read_json(ef)
                    for e in ev["standings"]:
                        if e.get("person"):
                            e["person"] = self.hydrate_person(e["person"])
                        cuban_link(e["participantId"], {"type": "event", "competitionId": cid, "season": season,
                                                        "eventId": ef.stem, "eventName": ev["name"], "rank": e.get("rank")})
                    self.write(f"{rel}/events/{ef.stem}.json", ev)
                    ev_index.append({k: ev.get(k) for k in ("name", "group", "start", "end", "location", "status")}
                                    | {"id": ef.stem, "players": len(ev["standings"])})
                self.write(f"{rel}/index.json", {
                    "schemaVersion": SCHEMA_VERSION, "competitionId": cid, "season": season,
                    "hasStandings": bool(st), "hasTeams": bool(tl),
                    "rankings": rk_index, "events": sorted(ev_index, key=lambda e: e.get("start") or "", reverse=True)})

        # --------------------------------------------- equipos + plantillas
        for tid, t in self.teams.items():
            tdir = DATA_DIR / "teams" / tid / "seasons"
            rosters = []
            for rf in sorted(tdir.glob("*/roster.json")) if tdir.exists() else []:
                ro = read_json(rf)
                season = rf.parent.name
                for g in ro["groups"]:
                    for pl in g["players"]:
                        if pl.get("person"):
                            pl["person"] = self.hydrate_person(pl["person"])
                        cuban_link(pl["personId"], {"type": "roster", "teamId": tid, "teamName": (t.get("name") or {}).get("full"),
                                                    "competitionId": ro["competitionId"], "season": season,
                                                    "role": pl.get("role"), "position": pl.get("position")})
                self.write(f"v1/teams/{tid}/seasons/{season}/roster.json", ro)
                rosters.append({"season": season, "competitionId": ro["competitionId"], "count": ro["count"]})
            out = t | {"logo": self.logo(tid),
                       "seasons": sorted(history.get(tid, []), key=lambda h: h["season"], reverse=True),
                       "rosters": sorted(rosters, key=lambda r: r["season"], reverse=True)}
            self.write(f"v1/teams/{tid}.json", out)

        # --------------------------------------------- personas (256 shards)
        shards: dict[str, dict] = {}
        for f in (DATA_DIR / "persons").glob("*.json"):
            sh = read_json(f)
            sh["persons"] = {pid: p | ({"photo": self.photo(pid)} if self.photo(pid) else {}) for pid, p in sh["persons"].items()}
            self.write(f"v1/persons/{f.stem}.json", sh)
            shards[f.stem] = len(sh["persons"])

        # --------------------------------------------- cubanos por el mundo
        cub_list = []
        for pid, c in cubans.items():
            p = c["person"]
            sports = sorted({comps[l["competitionId"]].sport for l in c["links"] if l["competitionId"] in comps})
            # "por el mundo" = al menos una competición fuera de Cuba (o internacional sin sede cubana)
            abroad = any(comps[l["competitionId"]].country != "CU" for l in c["links"] if l["competitionId"] in comps)
            cub_list.append({"id": pid, "abroad": abroad, "name": p.get("name"), "birthDate": p.get("birthDate"),
                             "birthPlace": p.get("birthPlace"), "nationalities": p.get("nationalities"),
                             "evidence": p.get("cubanEvidence"), "photo": self.photo(pid),
                             "sports": sports, "links": c["links"]})
        cub_list.sort(key=lambda x: (x["sports"][0] if x["sports"] else "", (x["name"] or {}).get("full", "")))
        self.write("v1/cubanos/index.json", {"schemaVersion": SCHEMA_VERSION, "type": "cubans", "updatedAt": now_iso(),
                                             "count": len(cub_list),
                                             "bySport": {s: sum(1 for x in cub_list if s in x["sports"]) for s in cfg.sports()},
                                             "abroadBySport": {s: sum(1 for x in cub_list if s in x["sports"] and x["abroad"]) for s in cfg.sports()},
                                             "note": "Incluye solo a los jugadores/as que aparecen en las competiciones cubiertas. "
                                                     "'evidence' indica la fuente del dato (lugar de nacimiento, nacionalidad o Wikidata).",
                                             "persons": cub_list})

        # --------------------------------------------- catálogo + media + estado
        sports = []
        for sid, s in sorted(cfg.sports().items(), key=lambda kv: kv[1].get("order", 99)):
            sports.append({"id": sid, "name": s["name"], "participant": s["participant"],
                           "rosterGroups": s.get("roster_groups"), "stats": s.get("stats"),
                           "competitions": sorted([c for c in comp_index if c["sport"] == sid],
                                                  key=lambda c: (c["tier"], c["id"]))})
        self.write("v1/sports.json", {"schemaVersion": SCHEMA_VERSION, "type": "catalog", "updatedAt": now_iso(), "sports": sports})
        self.build_media()
        status = read_json(STATE_DIR / "status.json", {})
        self.write("v1/status.json", {"schemaVersion": SCHEMA_VERSION, "updatedAt": now_iso(), "sources": {
            k: {kk: v.get(kk) for kk in ("ok", "at", "lastOk", "mode")} for k, v in status.items()}})

        n_files = sum(1 for _ in self.out.rglob("*") if _.is_file()) + 2
        if n_files > MAX_FILES:
            raise RuntimeError(f"{n_files} archivos: supera el margen del límite de 20.000 de Cloudflare")
        self.write_headers()
        self.write("v1/manifest.json", {"schemaVersion": SCHEMA_VERSION, "generatedAt": now_iso(),
                                        "fileCount": len(self.manifest), "files": dict(sorted(self.manifest.items()))})
        return {"files": n_files, "teams": len(self.teams), "persons": len(self.persons), "cubans": len(cub_list)}

    def build_media(self) -> None:
        dst = self.out / "media" / "logos"
        dst.mkdir(parents=True, exist_ok=True)
        entries, by_sport = {}, {}
        for eid, lg in sorted(self.logos.items()):
            if lg.get("status") != "ok":
                continue
            entries[eid] = {"hash": lg["hash"], "sizes": lg["sizes"], "source": lg.get("source")}
            sport = eid.split(".", 1)[0]
            by_sport.setdefault(sport, []).append(eid)
            for s in lg["sizes"]:
                src = MEDIA_SRC / f"{lg['hash']}-{s}.webp"
                if src.exists():
                    shutil.copy2(src, dst / src.name)
        packs = {}
        pdir = self.out / "media" / "packs"
        pdir.mkdir(parents=True, exist_ok=True)
        for sport, eids in by_sport.items():
            buf = pdir / f"logos-{sport}.zip"
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # WebP ya está comprimido
                for eid in eids:
                    for s in entries[eid]["sizes"]:
                        name = f"{entries[eid]['hash']}-{s}.webp"
                        if (dst / name).exists():
                            z.write(dst / name, name)
                z.writestr("index.json", json.dumps({e: entries[e] for e in eids}, ensure_ascii=False))
            data = buf.read_bytes()
            # el nombre del paquete con hash permite caché inmutable
            h = hashlib.sha256(data).hexdigest()[:16]
            final = pdir / f"logos-{sport}-{h}.zip"
            buf.rename(final)
            packs[sport] = {"path": f"/media/packs/{final.name}", "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "count": len(eids)}
        self.write("v1/media.json", {"schemaVersion": SCHEMA_VERSION, "updatedAt": now_iso(),
                                     "logoPath": "/media/logos/{hash}-{size}.webp", "logos": entries, "packs": packs})

    def write_headers(self) -> None:
        (self.out / "_headers").write_text(
            "/*\n"
            "  Access-Control-Allow-Origin: *\n"
            "  X-Content-Type-Options: nosniff\n"
            "/v1/*\n"
            "  Cache-Control: public, max-age=300, stale-while-revalidate=3600\n"
            "/v1/manifest.json\n"
            "  ! Cache-Control\n"          # quita la regla de /v1/* (si no, Cloudflare une ambos valores)
            "  Cache-Control: public, max-age=60\n"
            "/media/*\n"
            "  Cache-Control: public, max-age=31536000, immutable\n", encoding="utf-8")


def run() -> int:
    stats = Builder(PUBLIC_DIR).run()
    log.info("build OK: %s", stats)
    return 0

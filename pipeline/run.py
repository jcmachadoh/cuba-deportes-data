"""Punto de entrada del pipeline.

Uso:
  python -m pipeline.run collect --profile live|full|backfill [--only baseball.mlb,soccer.esp-1] [--sport baseball]
  python -m pipeline.run enrich           # Wikidata: cubanos por el mundo + fotos Commons
  python -m pipeline.run logos            # descarga/convierte logos (WebP) -> data/media
  python -m pipeline.run photos [--limit 400]   # resuelve fotos de jugadores
  python -m pipeline.run build            # genera public/ para Cloudflare
  python -m pipeline.run report           # resumen de estado

Perfiles de collect:
  live      solo clasificación/ranking de competiciones activas este mes
  full      equipos + plantillas + clasificación de la temporada actual
  backfill  como full, pero también temporadas pasadas (history_seasons)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback

from .adapters.base import Ctx, load
from .core import config as cfg
from .core.http import Http
from .core.ids import IdRegistry
from .core.paths import STATE_DIR
from .core.store import Store, write_json
from .core.util import now_iso

log = logging.getLogger("run")


def _select(args) -> list[cfg.Competition]:
    comps = [c for c in cfg.competitions().values() if c.enabled]
    if args.only:
        wanted = set(args.only.split(","))
        comps = [c for c in cfg.competitions().values() if c.id in wanted]
    if args.sport:
        comps = [c for c in comps if c.sport in args.sport.split(",")]
    if args.adapter:
        comps = [c for c in comps if c.adapter in args.adapter.split(",")]
    return comps


def _due(comp: cfg.Competition, status: dict) -> bool:
    """Respeta refresh: weekly/monthly (p. ej. la lista FIDE completa es mensual)."""
    if comp.refresh == "daily":
        return True
    last = status.get(f"{comp.id}:{comp.current_season()[0]}", {}).get("lastOk")
    if not last:
        return True
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
    return age >= (7 if comp.refresh == "weekly" else 28)


def cmd_collect(args) -> int:
    http, ids, store = Http(), IdRegistry(), Store()
    ctx = Ctx(http, ids)
    status_path = STATE_DIR / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    failures = 0
    for comp in _select(args):
        if args.profile == "live" and not comp.is_active() and not args.only:
            continue
        if args.profile == "full" and not args.only and not _due(comp, status):
            continue
        seasons = [comp.current_season()]
        if args.profile == "backfill":
            seasons += comp.past_seasons()
        mode = "standings" if args.profile == "live" else "full"
        mod = load(comp.adapter)
        for label, year in seasons:
            t0 = time.time()
            try:
                bundle = mod.collect(ctx, comp, label, year, mode)
                counts = store.write_bundle(bundle)
                st = {"ok": True, "at": now_iso(), "mode": mode, "counts": counts,
                      "warnings": bundle.warnings[:20], "seconds": round(time.time() - t0, 1)}
                log.info("%s %s %s %s", comp.id, label, counts, ("avisos=%d" % len(bundle.warnings)) if bundle.warnings else "")
            except Exception as e:  # noqa: BLE001 — una fuente rota no detiene al resto
                failures += 1
                st = {"ok": False, "at": now_iso(), "mode": mode, "error": f"{type(e).__name__}: {e}"}
                log.error("FALLÓ %s %s: %s", comp.id, label, e)
                log.debug(traceback.format_exc())
            prev = status.get(f"{comp.id}:{label}", {})
            if st["ok"]:
                st["lastOk"] = st["at"]
            elif prev.get("lastOk"):
                st["lastOk"] = prev["lastOk"]
            status[f"{comp.id}:{label}"] = st
            # guardar progreso tras cada competición (si el job se corta, no se pierde)
            store.flush()
            store.flush_candidates()
            ids.save()
    write_json(status_path, dict(sorted(status.items())))
    log.info("HTTP %s", http.stats)
    total = len(_select(args)) or 1
    # el job solo falla si falló más de la mitad (señal de problema general, no de una fuente)
    return 1 if failures > total / 2 else 0


def cmd_enrich(args) -> int:
    from .enrich import run
    return run()


def cmd_logos(args) -> int:
    from .assets.logos import run
    return run(limit=args.limit, force=args.force)


def cmd_photos(args) -> int:
    from .assets.photos import run
    return run(limit=args.limit)


def cmd_build(args) -> int:
    from .build.publish import run
    return run()


def cmd_report(args) -> int:
    path = STATE_DIR / "status.json"
    status = json.loads(path.read_text()) if path.exists() else {}
    bad = {k: v for k, v in status.items() if not v.get("ok")}
    print(f"{len(status)} entradas, {len(bad)} con error")
    for k, v in bad.items():
        print(f"  {k}: {v.get('error')} (último OK: {v.get('lastOk')})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--profile", choices=["live", "full", "backfill"], default="full")
    c.add_argument("--only")
    c.add_argument("--sport")
    c.add_argument("--adapter")
    lg = sub.add_parser("logos")
    lg.add_argument("--limit", type=int, default=0)
    lg.add_argument("--force", action="store_true")
    ph = sub.add_parser("photos")
    ph.add_argument("--limit", type=int, default=400)
    sub.add_parser("enrich")
    sub.add_parser("build")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return {"collect": cmd_collect, "enrich": cmd_enrich, "logos": cmd_logos, "photos": cmd_photos,
            "build": cmd_build, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

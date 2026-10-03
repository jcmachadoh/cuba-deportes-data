"""Logos de ligas y equipos: se descargan una vez, se normalizan y se publican
como archivos estáticos con hash en el nombre (caché inmutable).

Flujo por entidad (state/candidates/logos.json -> state/media/logos.json):
  1. probar candidatos por prioridad (URL oficial de la liga, ESPN, MLB...)
  2. SVG -> PNG con cairosvg; cualquier formato -> RGBA con Pillow
  3. lienzo cuadrado transparente, WebP de 256 px y 64 px
  4. nombre = sha256(webp256)[:16]; si el hash no cambia no se reescribe nada

La app descarga los logos la primera vez que se abre (ver docs/pantallas.md)
usando media.json, y solo vuelve a bajar los que cambien de hash.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from ..core.http import Http, HttpError
from ..core.paths import DATA_DIR, STATE_DIR
from ..core.store import read_json, write_json
from ..core.util import now_iso, sha256_bytes

log = logging.getLogger("logos")
SIZES = (256, 64)
MEDIA_DIR = DATA_DIR.parent / "media" / "logos"     # data/media/logos/{hash}-{size}.webp
STATE = STATE_DIR / "media" / "logos.json"
REVALIDATE_DAYS = 30


def to_image(raw: bytes, url: str) -> Image.Image:
    head = raw[:300].lstrip().lower()
    if url.lower().split("?")[0].endswith(".svg") or head.startswith(b"<svg") or b"<svg" in head:
        import cairosvg  # requiere libcairo (presente en ubuntu-latest)
        raw = cairosvg.svg2png(bytestring=raw, output_width=512)
    img = Image.open(io.BytesIO(raw))
    img.load()
    if getattr(img, "n_frames", 1) > 1:   # GIF animado: primer cuadro
        img.seek(0)
    return img.convert("RGBA")


def square(img: Image.Image, size: int) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)              # recorta el margen transparente
    w, h = img.size
    scale = (size * 0.92) / max(w, h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    return canvas


def encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


def process(http: Http, cands: list[dict]) -> dict | None:
    for c in sorted(cands, key=lambda c: c.get("priority", 50)):
        if c["type"] != "url":
            continue
        try:
            r = http.get(c["value"], allow_404=True, use_cache=False)
            if r is None or len(r.content) < 100:
                continue
            img = to_image(r.content, c["value"])
            if min(img.size) < 16:
                continue
            files = {s: encode(square(img, s)) for s in SIZES}
            h = sha256_bytes(files[256])[:16]
            return {"hash": h, "files": files, "source": c["source"], "sourceUrl": c["value"],
                    "origSize": list(img.size)}
        except (HttpError, OSError, ValueError) as e:
            log.warning("logo falló %s: %s", c["value"], e)
    return None


def run(limit: int = 0, force: bool = False) -> int:
    http = Http()
    cands = read_json(STATE_DIR / "candidates" / "logos.json", {})
    state = read_json(STATE, {})
    now = datetime.now(timezone.utc)
    done = 0
    for eid, cl in sorted(cands.items()):
        cur = state.get(eid)
        if cur and not force:
            checked = datetime.fromisoformat(cur["checkedAt"].replace("Z", "+00:00"))
            if now - checked < timedelta(days=REVALIDATE_DAYS) and cur.get("status") == "ok":
                continue
            if cur.get("status") == "missing" and now - checked < timedelta(days=7):
                continue
        if limit and done >= limit:
            break
        done += 1
        res = process(http, cl)
        if not res:
            state[eid] = (cur or {}) | {"status": cur.get("status", "missing") if cur else "missing", "checkedAt": now_iso()}
            continue
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        for size, data in res["files"].items():
            p = MEDIA_DIR / f"{res['hash']}-{size}.webp"
            if not p.exists():
                p.write_bytes(data)
        changed = not cur or cur.get("hash") != res["hash"]
        entry = {"status": "ok", "hash": res["hash"], "source": res["source"], "sourceUrl": res["sourceUrl"],
                 "sizes": list(SIZES), "origSize": res["origSize"], "checkedAt": now_iso(),
                 "validFrom": now_iso() if changed else cur.get("validFrom")}
        if changed and cur and cur.get("hash"):
            entry["previous"] = ([{"hash": cur["hash"], "validFrom": cur.get("validFrom"), "validTo": now_iso()}]
                                 + cur.get("previous", []))[:5]
        elif cur and cur.get("previous"):
            entry["previous"] = cur["previous"]
        state[eid] = entry
        if done % 25 == 0:
            write_json(STATE, dict(sorted(state.items())))
    write_json(STATE, dict(sorted(state.items())))
    ok = sum(1 for v in state.values() if v.get("status") == "ok")
    log.info("logos procesados=%d, con logo=%d/%d", done, ok, len(cands))
    return 0

"""Fotos de jugadores: se resuelve una URL válida por persona y la app la
carga desde internet (no se copian al repo, salvo la opción R2 para Commons).

Cadena de resolución (state/candidates/photos.json, por prioridad):
  url           URL directa de la fuente (MLB, SNB, legavolley, ufc.com, WBC, Lichess)
  page          página de ficha; se extrae la foto (NPB)
  lichess_fide  API de Lichess /api/fide/player/{fideId} -> photo.medium (con crédito)
  commons       Wikidata P18 (Wikimedia Commons), con autor y licencia
  (fallback)    consulta por lote a Wikidata P18 usando los IDs externos
  sin foto      la app muestra un avatar con iniciales

Detección de "foto genérica": si el mismo contenido (hash) aparece para 3 o
más personas del mismo host, se marca como marcador de posición y se descarta.
"""
from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urljoin, urlparse

from PIL import Image

from ..core.http import Http, HttpError
from ..core.ids import IdRegistry
from ..core.paths import STATE_DIR
from ..core.store import Store, read_json, write_json
from ..core.util import now_iso, sha256_bytes
from ..enrich import PROPS, sparql

log = logging.getLogger("photos")
STATE = STATE_DIR / "media" / "photos.json"
PLACEHOLDERS = STATE_DIR / "media" / "placeholders.json"
RECHECK_OK_DAYS = 30
RECHECK_NONE_DAYS = 14
WIKIDATA_BATCH = int(os.environ.get("PHOTOS_WIKIDATA_BATCH", "3000"))   # personas por ejecución


class BudgetExceeded(Exception):
    """Se agotó el cupo de una fuente en esta ejecución; se reintenta en la próxima."""


class Resolver:
    def __init__(self, http: Http, lichess_budget: int = 40):
        self.http = http
        self.lichess_budget = lichess_budget   # Lichess limita con 429: pocas consultas por ejecución
        self.commons_blocked = False
        self.ph = read_json(PLACEHOLDERS, {})          # host -> {hash: [personIds]}

    def _is_placeholder(self, host: str, h: str) -> bool:
        return len(self.ph.get(host, {}).get(h, [])) >= 3

    def check_image(self, url: str, pid: str) -> dict | None:
        try:
            r = self.http.get(url, allow_404=True, use_cache=False)
        except HttpError:
            return None
        if r is None or len(r.content) < 1500:
            return None
        try:
            img = Image.open(io.BytesIO(r.content))
            w, h = img.size
        except OSError:
            return None
        if min(w, h) < 40:
            return None
        host = urlparse(url).netloc
        hsh = sha256_bytes(r.content)[:16]
        seen = self.ph.setdefault(host, {}).setdefault(hsh, [])
        if pid not in seen and len(seen) < 3:
            seen.append(pid)
        if self._is_placeholder(host, hsh):
            return None
        return {"url": url, "hash": hsh, "width": w, "height": h}

    def resolve(self, pid: str, cand: dict) -> dict | None:
        t, v = cand["type"], cand["value"]
        if t == "url":
            res = self.check_image(v, pid)
            return res | {"source": cand["source"], **({"credit": cand["credit"]} if cand.get("credit") else {})} if res else None
        if t == "page":
            html = self.http.text(v, allow_404=True)
            m = re.search(r'src="([^"]*players_photo[^"]+)"', html or "")
            if m:
                res = self.check_image(urljoin(v, m[1]), pid)
                return res | {"source": cand["source"]} if res else None
            return None
        if t == "lichess_fide":
            if self.lichess_budget <= 0:
                raise BudgetExceeded
            self.lichess_budget -= 1
            try:
                d = self.http.json(f"https://lichess.org/api/fide/player/{v}", allow_404=True, retries=0)
            except HttpError as e:
                if e.status == 429:          # límite de Lichess: dejar el resto para la próxima ejecución
                    self.lichess_budget = 0
                    raise BudgetExceeded from e
                return None
            ph = (d or {}).get("photo") or {}
            if ph.get("medium"):
                res = self.check_image(ph["medium"], pid)
                if res:
                    return res | {"source": "lichess", "credit": ph.get("credit")}
            return None
        if t == "commons":
            return self.commons(v, pid)
        return None

    def commons(self, file_url: str, pid: str) -> dict | None:
        name = unquote(file_url.rsplit("/", 1)[-1])
        if self.commons_blocked:
            raise BudgetExceeded
        try:
            d = self.http.json("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "titles": f"File:{name}", "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": 320, "format": "json"}, retries=0)
        except HttpError as e:
            if e.status == 429:              # límite de Wikimedia: continuar en la próxima ejecución
                self.commons_blocked = True
                raise BudgetExceeded from e
            return None
        pages = (d.get("query") or {}).get("pages") or {}
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            thumb = ii.get("thumburl")
            if not thumb:
                continue
            md = ii.get("extmetadata") or {}
            artist = re.sub(r"<[^>]+>", "", (md.get("Artist") or {}).get("value", "")).strip()
            lic = (md.get("LicenseShortName") or {}).get("value")
            res = self.check_image(thumb, pid)
            if res:
                res |= {"source": "wikimedia-commons", "credit": artist or None, "license": lic,
                        "page": ii.get("descriptionurl")}
                return mirror_r2(self.http, res)
        return None


def mirror_r2(http: Http, res: dict) -> dict:
    """Opcional: copia la foto de Commons a R2 si hay credenciales (R2_*)."""
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE")
    if not all(os.environ.get(k) for k in need):
        return res
    import boto3
    key = f"photos/{res['hash']}.jpg"
    s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                      aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    try:
        s3.head_object(Bucket=os.environ["R2_BUCKET"], Key=key)
    except Exception:  # noqa: BLE001 — no existe aún
        body = http.get(res["url"], use_cache=False).content
        s3.put_object(Bucket=os.environ["R2_BUCKET"], Key=key, Body=body, ContentType="image/jpeg",
                      CacheControl="public, max-age=31536000, immutable")
    res["originalUrl"] = res["url"]
    res["url"] = os.environ["R2_PUBLIC_BASE"].rstrip("/") + "/" + key
    return res


def wikidata_fallback(http: Http, store: Store, pending: list[str]) -> int:
    """Busca P18 por lotes para personas sin candidatos útiles."""
    ids = IdRegistry()
    rev: dict[str, dict[str, str]] = {}
    for key, pid in ids.data.get("person", {}).items():
        src, ext = key.split(":", 1)
        rev.setdefault(pid, {})[src] = ext
    by_prop: dict[str, dict[str, str]] = {}
    for pid in pending:
        for prop, src in PROPS.items():
            if src in rev.get(pid, {}):
                by_prop.setdefault(prop, {})[rev[pid][src]] = pid
    added = 0
    for prop, m in by_prop.items():
        keys = list(m)
        for i in range(0, len(keys), 150):
            vals = " ".join('"%s"' % k.replace('"', "") for k in keys[i:i + 150])
            q = f"SELECT ?ext ?img WHERE {{ VALUES ?ext {{ {vals} }} ?item wdt:{prop} ?ext ; wdt:P18 ?img . }}"
            try:
                for r in sparql(http, q):
                    store.add_candidates("photos", m[r["ext"]], [{"type": "commons", "value": r["img"], "source": "wikidata", "priority": 40}])
                    added += 1
            except Exception as e:  # noqa: BLE001
                log.warning("wikidata P18 %s: %s", prop, e)
    store.flush_candidates()
    return added


def run(limit: int = 400) -> int:
    http, store = Http(), Store()
    state = read_json(STATE, {})
    now = datetime.now(timezone.utc)

    def due(pid: str) -> bool:
        cur = state.get(pid)
        if not cur:
            return True
        age = now - datetime.fromisoformat(cur["checkedAt"].replace("Z", "+00:00"))
        return age > timedelta(days=RECHECK_OK_DAYS if cur["status"] == "ok" else RECHECK_NONE_DAYS)

    # 1) personas sin candidatos o con todos fallidos -> buscar en Wikidata
    cands = read_json(STATE_DIR / "candidates" / "photos.json", {})
    def wd_due(st: dict) -> bool:   # reintentar Wikidata cada 30 días (la comunidad añade fotos)
        t = st.get("wikidataTried")
        return not t or now - datetime.fromisoformat(t.replace("Z", "+00:00")) > timedelta(days=30)
    no_photo = [pid for pid, st in state.items() if st.get("status") == "none" and wd_due(st)]
    # personas que ninguna fuente acompañó con foto (p. ej. futbolistas de ESPN)
    srcs = set(PROPS.values())
    for key, pid in IdRegistry().data.get("person", {}).items():
        if key.split(":", 1)[0] in srcs and pid not in cands and pid not in state:
            state[pid] = {"status": "none", "checkedAt": now_iso()}
            no_photo.append(pid)
    if no_photo:
        batch = no_photo[:WIKIDATA_BATCH]
        n = wikidata_fallback(http, store, batch)
        for pid in batch:
            state[pid]["wikidataTried"] = now_iso()
            state[pid]["checkedAt"] = "2000-01-01T00:00:00Z"   # forzar nueva comprobación
        log.info("Wikidata aportó %d candidatos nuevos", n)
        cands = read_json(STATE_DIR / "candidates" / "photos.json", {})

    # 2) prioridad: cubanos primero
    def is_cuban(pid: str) -> bool:
        p = store.get_person(pid)
        return bool(p and p.get("isCuban"))

    todo = [pid for pid in cands if due(pid)]
    todo.sort(key=lambda pid: (not is_cuban(pid), pid in state))
    res_ = Resolver(http)
    done = 0
    for pid in todo:
        if limit and done >= limit:
            break
        found, skipped = None, False
        for c in sorted(cands[pid], key=lambda c: c.get("priority", 50)):
            try:
                found = res_.resolve(pid, c)
            except BudgetExceeded:
                skipped = True
                continue
            if found:
                break
        if not found and skipped:
            continue   # queda pendiente para la próxima ejecución
        prev = state.get(pid, {})
        state[pid] = ({"status": "ok", **found} if found else {"status": "none"}) | {
            "checkedAt": now_iso(), **({"wikidataTried": prev["wikidataTried"]} if prev.get("wikidataTried") else {})}
        done += 1
        if done % 50 == 0:
            write_json(STATE, dict(sorted(state.items())))
            write_json(PLACEHOLDERS, res_.ph)

    # 3) invalidar retroactivamente las que resultaron ser genéricas
    for pid, st in state.items():
        if st.get("status") == "ok" and st.get("hash"):
            host = urlparse(st["url"]).netloc
            if res_._is_placeholder(host, st["hash"]):
                state[pid] = {"status": "none", "checkedAt": now_iso(), "reason": "placeholder"}
    write_json(STATE, dict(sorted(state.items())))
    write_json(PLACEHOLDERS, res_.ph)
    ok = sum(1 for v in state.values() if v["status"] == "ok")
    log.info("fotos comprobadas=%d; con foto=%d de %d con estado", done, ok, len(state))
    return 0

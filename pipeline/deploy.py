"""Despliega public/ como Worker de solo archivos estáticos (Workers Static Assets)
usando directamente la API de Cloudflare, sin Node ni wrangler.

Pasos (https://developers.cloudflare.com/workers/static-assets/direct-upload/):
  1. POST  /workers/scripts/{name}/assets-upload-session   con el manifiesto {ruta: {hash, size}}
  2. POST  /workers/assets/upload?base64=true               por cada bucket pendiente (JWT de subida)
  3. PUT   /workers/scripts/{name}                          metadata con assets.jwt + config (_headers)
  4. POST  /workers/scripts/{name}/subdomain                activa {name}.{subdominio}.workers.dev

Uso:
  CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... python -m pipeline.deploy [--dir public] [--name cuba-deportes-data]
Si CLOUDFLARE_API_TOKEN no está definido, se asume que un proxy HTTPS inyecta la autenticación.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import mimetypes
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import requests.adapters

log = logging.getLogger("deploy")
API = "https://api.cloudflare.com/client/v4"
COMPAT_DATE = "2026-09-01"
SPECIAL = {"_headers", "_redirects", ".assetsignore"}
mimetypes.add_type("image/webp", ".webp")


class CfError(RuntimeError):
    pass


class _LenientTLS(requests.adapters.HTTPAdapter):
    """Algunos proxies HTTPS corporativos usan una CA sin la extensión keyUsage;
    Python 3.13+ la rechaza por VERIFY_X509_STRICT. Solo se usa en modo proxy."""

    def init_poolmanager(self, *a, **kw):
        import ssl
        ctx = ssl.create_default_context(cafile=os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE"))
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)

    def proxy_manager_for(self, proxy, **kw):
        import ssl
        ctx = ssl.create_default_context(cafile=os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE"))
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kw["ssl_context"] = ctx
        return super().proxy_manager_for(proxy, **kw)


def _check(r: requests.Response) -> dict:
    try:
        d = r.json()
    except ValueError:
        raise CfError(f"{r.request.method} {r.url} -> {r.status_code}: {r.text[:300]}")
    if not d.get("success", r.ok):
        raise CfError(f"{r.request.method} {r.url} -> {r.status_code}: {d.get('errors')}")
    return d.get("result") or {}


def file_hash(path: Path, b64: bytes) -> str:
    # 32 caracteres hex, como pide la API; mismo criterio que wrangler (contenido base64 + extensión)
    return hashlib.sha256(b64 + path.suffix.lstrip(".").encode()).hexdigest()[:32]


def build_manifest(root: Path) -> tuple[dict, dict]:
    manifest, files = {}, {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in SPECIAL and p.parent == root:
            continue
        data = p.read_bytes()
        if len(data) > 25 * 1024 * 1024:
            raise CfError(f"{p} supera 25 MiB")
        b64 = base64.b64encode(data)
        h = file_hash(p, b64)
        rel = "/" + p.relative_to(root).as_posix()
        manifest[rel] = {"hash": h, "size": len(data)}
        files[h] = (p, b64)
    if len(manifest) > 20000:
        raise CfError(f"{len(manifest)} archivos: el plan Free admite 20 000 por versión")
    return manifest, files


def deploy(root: Path, name: str, account: str, token: str | None) -> str:
    api = requests.Session()                       # llamadas con el token de API
    if token:
        api.headers["Authorization"] = f"Bearer {token}"
    else:
        api.mount("https://", _LenientTLS())
    up = requests.Session()                        # subida con el JWT de sesión: sin proxy que reemplace el header
    up.trust_env = bool(token)
    base = f"{API}/accounts/{account}"

    manifest, files = build_manifest(root)
    log.info("manifiesto: %d archivos, %.1f MB", len(manifest), sum(v["size"] for v in manifest.values()) / 1e6)
    res = _check(api.post(f"{base}/workers/scripts/{name}/assets-upload-session", json={"manifest": manifest}, timeout=120))
    jwt, buckets = res["jwt"], res.get("buckets") or []
    log.info("buckets por subir: %d (%d archivos nuevos o cambiados)", len(buckets), sum(map(len, buckets)))

    completion = jwt if not buckets else None

    def send(bucket: list[str]) -> str | None:
        parts = []
        for h in bucket:
            p, b64 = files[h]
            ctype = mimetypes.guess_type(p.name)[0] or "application/null"
            parts.append((h, (h, b64, ctype)))
        for attempt in range(4):
            r = up.post(f"{base}/workers/assets/upload", params={"base64": "true"}, files=parts,
                        headers={"Authorization": f"Bearer {jwt}"}, timeout=300)
            if r.status_code < 500 and r.status_code != 429:
                return _check(r).get("jwt")
            time.sleep(5 * (attempt + 1))
        raise CfError(f"subida fallida: {r.status_code} {r.text[:200]}")

    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, tok in enumerate(ex.map(send, buckets), 1):
            if tok:
                completion = tok
            if i % 10 == 0 or i == len(buckets):
                log.info("subidos %d/%d buckets", i, len(buckets))
    if not completion:
        raise CfError("la API no devolvió el token de finalización")

    config = {"html_handling": "none", "not_found_handling": "none"}
    for special in ("_headers", "_redirects"):
        f = root / special
        if f.exists():
            config[special] = f.read_text(encoding="utf-8")
    metadata = {"assets": {"jwt": completion, "config": config}, "compatibility_date": COMPAT_DATE}
    _check(api.put(f"{base}/workers/scripts/{name}",
                   files={"metadata": (None, json.dumps(metadata), "application/json")}, timeout=120))
    log.info("worker %s actualizado", name)

    _check(api.post(f"{base}/workers/scripts/{name}/subdomain", json={"enabled": True, "previews_enabled": False}, timeout=60))
    sub = _check(api.get(f"{base}/workers/subdomain", timeout=60)).get("subdomain")
    url = f"https://{name}.{sub}.workers.dev" if sub else f"(activa un subdominio workers.dev en la cuenta) {name}"
    log.info("publicado en %s", url)
    return url


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="pipeline.deploy")
    ap.add_argument("--dir", default=os.environ.get("PUBLIC_DIR", "public"))
    ap.add_argument("--name", default=os.environ.get("CF_WORKER_NAME", "cuba-deportes-data"))
    a = ap.parse_args(argv)
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not account:
        log.error("falta CLOUDFLARE_ACCOUNT_ID")
        return 2
    try:
        url = deploy(Path(a.dir), a.name, account, os.environ.get("CLOUDFLARE_API_TOKEN"))
    except CfError as e:
        log.error("%s", e)
        return 1
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(f"\n**Desplegado:** {url}\n")
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())

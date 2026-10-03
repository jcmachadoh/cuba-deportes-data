"""Cliente HTTP "educado": intervalo mínimo por host, reintentos con backoff,
User-Agent por host y caché opcional en disco (útil en desarrollo y para
reutilizar respuestas dentro de la misma ejecución de GitHub Actions)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml

from .paths import CONFIG_DIR, CACHE_DIR

log = logging.getLogger("http")


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int, msg: str = ""):
        super().__init__(f"HTTP {status} {url} {msg}".strip())
        self.url, self.status = url, status


class Http:
    def __init__(self, cache_ttl_s: int | None = None):
        cfg = yaml.safe_load((CONFIG_DIR / "sources.yml").read_text(encoding="utf-8"))
        self.defaults: dict[str, Any] = cfg["defaults"]
        self.hosts: dict[str, dict[str, Any]] = cfg.get("hosts") or {}
        self.contact = os.environ.get("PIPELINE_CONTACT", "https://github.com/")
        self.session = requests.Session()
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        # TTL de caché en segundos (None = sin caché). Se controla con HTTP_CACHE_TTL.
        env_ttl = os.environ.get("HTTP_CACHE_TTL")
        self.cache_ttl = int(env_ttl) if env_ttl else cache_ttl_s
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}

    # ------------------------------------------------------------------ helpers
    def _policy(self, host: str) -> dict[str, Any]:
        p = dict(self.defaults)
        p.update(self.hosts.get(host, {}))
        p["user_agent"] = p["user_agent"].replace("{contact}", self.contact)
        return p

    def _wait_turn(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            delay = last + min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def _cache_path(self, url: str, headers: dict | None) -> Path:
        key = hashlib.sha256((url + json.dumps(headers or {}, sort_keys=True)).encode()).hexdigest()
        return CACHE_DIR / key[:2] / key

    # ------------------------------------------------------------------ API
    def get(self, url: str, *, headers: dict | None = None, params: dict | None = None,
            allow_404: bool = False, binary: bool = False, use_cache: bool = True,
            stream_to: Path | None = None, retries: int | None = None) -> requests.Response | None:
        if params:
            req = requests.Request("GET", url, params=params).prepare()
            url = req.url  # type: ignore[assignment]
        host = urlparse(url).netloc
        pol = self._policy(host)
        hdrs = {"User-Agent": pol["user_agent"], "Accept-Language": "es,en;q=0.8"}
        if headers:
            hdrs.update(headers)

        cpath = self._cache_path(url, headers)
        if use_cache and self.cache_ttl and stream_to is None and cpath.exists():
            if time.time() - cpath.stat().st_mtime < self.cache_ttl:
                self.stats["cache_hits"] += 1
                return _CachedResponse(url, cpath.read_bytes())

        attempts = int(pol["retries"] if retries is None else retries) + 1
        for i in range(attempts):
            self._wait_turn(host, float(pol["min_interval_s"]))
            self.stats["requests"] += 1
            try:
                r = self.session.get(url, headers=hdrs, timeout=float(pol["timeout_s"]),
                                     stream=stream_to is not None)
            except requests.RequestException as e:  # red / DNS / timeout
                log.warning("intento %s/%s falló %s: %s", i + 1, attempts, url, e)
                if i + 1 == attempts:
                    self.stats["errors"] += 1
                    raise HttpError(url, 0, str(e)) from e
                time.sleep(float(pol["backoff_s"]) * (i + 1))
                continue
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                wait = float(r.headers.get("Retry-After") or 0) or float(pol["backoff_s"]) * (2 ** i)
                if r.status_code == 429:
                    wait = max(wait, 60.0)  # Lichess y otros: esperar un minuto completo
                if i + 1 == attempts:
                    self.stats["errors"] += 1
                    raise HttpError(url, r.status_code, "agotados los reintentos")
                log.warning("HTTP %s en %s, reintento en %.0fs", r.status_code, url, wait)
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                self.stats["errors"] += 1
                raise HttpError(url, r.status_code)
            if stream_to is not None:
                stream_to.parent.mkdir(parents=True, exist_ok=True)
                with open(stream_to, "wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        fh.write(chunk)
                return r
            if use_cache and self.cache_ttl:
                cpath.parent.mkdir(parents=True, exist_ok=True)
                cpath.write_bytes(r.content)
            return r
        self.stats["errors"] += 1
        raise HttpError(url, 429, "agotados los reintentos")

    def json(self, url: str, **kw) -> Any:
        h = {"Accept": "application/json"}
        h.update(kw.pop("headers", None) or {})
        r = self.get(url, headers=h, **kw)
        if r is None:
            return None
        return r.json()

    def text(self, url: str, encoding: str | None = None, **kw) -> str | None:
        r = self.get(url, **kw)
        if r is None:
            return None
        if encoding:
            r.encoding = encoding
        elif not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text

    def head_ok(self, url: str) -> bool:
        """True si la URL existe (usa GET liviano porque varios CDNs no soportan HEAD)."""
        try:
            r = self.get(url, allow_404=True, use_cache=False)
            return r is not None and len(r.content) > 200
        except HttpError:
            return False


class _CachedResponse:
    """Respuesta mínima compatible con requests.Response para la caché."""

    def __init__(self, url: str, content: bytes):
        self.url, self.content, self.status_code = url, content, 200
        self.encoding = "utf-8"
        self.headers: dict[str, str] = {}

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def apparent_encoding(self) -> str:
        return "utf-8"

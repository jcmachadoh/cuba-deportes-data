"""Registro de identificadores canónicos.

Cada entidad (equipo, persona) recibe un ID propio y estable, independiente de
la fuente. El registro guarda (fuente:idExterno) -> idCanónico en
state/registry.json, versionado en git. Así:
  * si la fuente cambia el nombre del equipo, el ID no cambia;
  * si mañana se reemplaza la fuente, basta con añadir el alias nuevo;
  * las correcciones manuales se hacen en state/overrides.json.

Formato de IDs (seguros para nombres de archivo):
  equipo  : "{sport}.{slug}"                 p. ej. baseball.industriales
  persona : "p.{slug-nombre}[.{año-nac}]"   p. ej. p.lee-andy-plumas-portomene.2003
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .paths import STATE_DIR
from .util import slugify


class IdRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE_DIR / "registry.json"
        self.overrides_path = self.path.parent / "overrides.json"
        self._lock = threading.Lock()
        self.data: dict[str, dict[str, str]] = {"team": {}, "person": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        self.overrides: dict[str, dict[str, str]] = {"team": {}, "person": {}}
        if self.overrides_path.exists():
            self.overrides.update(json.loads(self.overrides_path.read_text(encoding="utf-8")))
        self._used = {k: set(v.values()) for k, v in self.data.items()}
        self.dirty = False

    def _mint(self, kind: str, base: str) -> str:
        used = self._used.setdefault(kind, set())
        cand, n = base, 2
        while cand in used:
            cand = f"{base}-{n}"
            n += 1
        used.add(cand)
        return cand

    def resolve(self, kind: str, source: str, ext_id: str | int, *, base: str) -> str:
        """Devuelve el ID canónico para (source, ext_id); lo crea si no existe."""
        key = f"{source}:{ext_id}"
        if key in self.overrides.get(kind, {}):
            return self.overrides[kind][key]
        with self._lock:
            table = self.data.setdefault(kind, {})
            if key in table:
                return table[key]
            cid = self._mint(kind, base)
            table[key] = cid
            self.dirty = True
            return cid

    def alias(self, kind: str, source: str, ext_id: str | int, canonical: str) -> None:
        """Vincula otra fuente a un ID ya existente (fusión de identidades)."""
        with self._lock:
            self.data.setdefault(kind, {})[f"{source}:{ext_id}"] = canonical
            self._used.setdefault(kind, set()).add(canonical)
            self.dirty = True

    def lookup(self, kind: str, source: str, ext_id: str | int) -> str | None:
        key = f"{source}:{ext_id}"
        return self.overrides.get(kind, {}).get(key) or self.data.get(kind, {}).get(key)

    # ------------------------------------------------------------- atajos
    def team(self, sport: str, source: str, ext_id: str | int, name: str) -> str:
        return self.resolve("team", source, ext_id, base=f"{sport}.{slugify(name)}")

    def person(self, source: str, ext_id: str | int, name: str, birth: str | None = None) -> str:
        base = f"p.{slugify(name, 50)}"
        if birth and len(birth) >= 4:
            base += f".{birth[:4]}"
        return self.resolve("person", source, ext_id, base=base)

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = {k: dict(sorted(v.items())) for k, v in self.data.items()}
        self.path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.dirty = False

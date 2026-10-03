import json
from datetime import date

import pytest


def test_config_valid():
    from pipeline.adapters.base import load
    from pipeline.core import config as cfg
    comps = cfg.competitions()
    assert len(comps) > 30
    for c in comps.values():
        mod = load(c.adapter)
        assert hasattr(mod, "collect"), c.id
        assert c.id.split(".")[0] == c.sport, c.id


def test_seasons():
    from pipeline.core.config import competitions
    snb = competitions()["baseball.snb"]
    assert snb.current_season(date(2026, 10, 3)) == ("2026-27", 2026)
    assert snb.current_season(date(2027, 2, 1)) == ("2026-27", 2026)
    mlb = competitions()["baseball.mlb"]
    assert mlb.current_season(date(2026, 10, 3)) == ("2026", 2026)


def test_util():
    from pipeline.core.util import country_code, natural_name, parse_date, slugify, to_int
    assert slugify("Ciego de Ávila") == "ciego-de-avila"
    assert parse_date("Mar. 20, 1979") == "1979-03-20"
    assert parse_date("11/09/2006") == "2006-09-11"
    assert country_code("🇨🇺 Cuba") == "CU" and country_code("CUB") == "CU" and country_code("Kosovo") == "XK"
    assert natural_name("CARMONA CASANOVA Guillermo Rolando") == "Guillermo Rolando Carmona Casanova"
    assert to_int(3.0) == 3 and to_int("1.0") == 1


def test_registry_stable(tmp_path):
    from pipeline.core.ids import IdRegistry
    r = IdRegistry(tmp_path / "registry.json")
    a = r.person("mlb", 1, "José Abreu", "1987-01-29")
    b = r.person("snb", 9, "José Abreu", "1987-01-29")
    assert a == "p.jose-abreu.1987" and b == "p.jose-abreu.1987-2"   # sin colisiones
    r.save()
    r2 = IdRegistry(tmp_path / "registry.json")
    assert r2.person("mlb", 1, "Otro nombre") == a                    # el ID no cambia si cambia el nombre


def test_write_only_on_change(tmp_path):
    from pipeline.core.store import write_json
    p = tmp_path / "x.json"
    assert write_json(p, {"a": 1, "updatedAt": "1"})
    assert not write_json(p, {"a": 1, "updatedAt": "2"})   # solo cambió la marca de tiempo
    assert write_json(p, {"a": 2, "updatedAt": "3"})

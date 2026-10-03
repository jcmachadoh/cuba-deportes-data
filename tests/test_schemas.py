"""Valida una muestra de data/v1 contra schemas/v1 (si hay datos generados)."""
import json
import random
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "v1"
SCHEMAS = {p.name.split(".")[0]: json.loads(p.read_text()) for p in (ROOT / "schemas" / "v1").glob("*.schema.json")}


def sample(pattern, n=25):
    files = sorted(DATA.glob(pattern))
    random.Random(1).shuffle(files)
    return files[:n]


CASES = [("competitions/*.json", "competition"), ("competitions/*/seasons/*/standings.json", "standings"),
         ("teams/*/seasons/*/roster.json", "roster"), ("competitions/*/seasons/*/rankings/*.json", "ranking"),
         ("competitions/*/seasons/*/events/*.json", "event"), ("teams/*.json", "team"), ("persons/*.json", "persons")]


@pytest.mark.parametrize("pattern,schema", CASES)
def test_data_matches_schema(pattern, schema):
    files = sample(pattern)
    if not files:
        pytest.skip("sin datos generados")
    for f in files:
        jsonschema.validate(json.loads(f.read_text()), SCHEMAS[schema])

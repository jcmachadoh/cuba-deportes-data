"""Pruebas de los parsers HTML con páginas reales guardadas en tests/fixtures/.
Si una fuente cambia su HTML, actualizar el fixture y ajustar el parser."""
from pathlib import Path

import pytest

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_bytes().decode("utf-8", errors="replace")


def test_snb_standings_archived():
    from pipeline.adapters.beisbolcubano import TEAMS, parse_standings
    groups = parse_standings(read("snb_posiciones_2026-02.html"), {c: f"t.{c}" for c in TEAMS})
    assert groups and len(groups[0].rows) == 16
    first = groups[0].rows[0]
    assert first.participant_id == "t.ltu" and first.rank == 1
    assert first.stats["W"] == 48 and first.stats["L"] == 26 and first.stats["PCT"] == 0.649
    assert first.stats["HOME"] == "22-15" and first.stats["AWAY"] == "26-11"


def test_snb_roster():
    from pipeline.adapters.beisbolcubano import parse_roster
    rows = parse_roster(read("snb_equipo_ind.html"))
    assert len(rows) > 30
    groups = {r["group"] for r in rows}
    assert {"P", "C", "IF", "OF", "STAFF"} <= groups
    p = next(r for r in rows if r["group"] == "P")
    assert p["id"].isdigit() and p["birth"] and len(p["birth"]) == 10
    dt = next(r for r in rows if r.get("role") == "Director Técnico")
    assert dt["name"] == "Guillermo Rolando Carmona Casanova"


def test_npb_roster_and_standings():
    from pipeline.adapters.npb import parse_roster, parse_standings, TEAMS, _norm
    rows = parse_roster(read("npb_rst_g.html"))
    assert rows[0]["group"] == "STAFF" and rows[0]["name"] == "Shinnosuke Abe"
    assert any(r["developmental"] for r in rows)
    st = parse_standings(read("npb_std_c.html"), {_norm(n): k for k, (n, _) in TEAMS.items()}, "central", "Central")
    assert len(st.rows) == 6 and st.rows[0].stats["W"] > 0


def test_kbo_standings():
    from pipeline.adapters.kbo import parse_standings, TEAMS
    rows = parse_standings(read("kbo_standings.html"))
    assert len(rows) == 10
    assert all(r["TEAM"].upper() in TEAMS for r in rows)


def test_lpbcol():
    from pipeline.adapters.lpbcol import parse_standings
    rows = parse_standings(read("lpbcol_posiciones.html"))
    assert len(rows) == 4 and rows[0]["Equipo"] == "Caimanes"


def test_legavolley():
    from pipeline.adapters.legavolley import parse_standings, parse_team
    rows = parse_standings(read("legavolley_classifica_2025.html"))
    assert rows[0]["team"] == "Sir Susa Scai Perugia" and rows[0]["stats"]["PTS"] == 58
    assert rows[0]["stats"]["PF"] == 1960 and rows[0]["stats"]["SR"] == 3.15
    t = parse_team(read("legavolley_team_6858.html"))
    assert t["players"] and t["staff"] and t["logos"]
    assert t["players"][0]["name"] and not t["players"][0]["name"].endswith(t["players"][0]["role"])


def test_ufc():
    from pipeline.adapters.ufc import parse_athlete, parse_rankings
    rk = parse_rankings(read("ufc_rankings.html"))
    names = [r["name"] for r in rk]
    assert len(names) == len(set(names)) >= 12
    assert any(r["pound_for_pound"] for r in rk)
    a = parse_athlete(read("ufc_athlete.html"))
    assert a["birth_country"] == "BR" and a["record"]["W"] >= 1


def test_wbc():
    from pipeline.adapters.wbc import parse_division
    d = parse_division(read("wbc_male_heavyweight.html"))
    assert d["champion"]["name"] and d["champion"]["record"]["KO"] >= 0
    assert d["updated"] and len(d["rows"]) >= 15
    assert any("CU" in r["countries"] for r in d["rows"])


def test_fide_top():
    from pipeline.adapters.fide_top import parse_top
    period, rows = parse_top(read("fide_top_open.html"))
    assert period and len(period) == 7 and len(rows) == 100
    assert rows[0]["fide_id"].isdigit() and "," not in rows[0]["name"]


def test_chess_results():
    from pipeline.adapters.chess_results import parse_final, parse_start
    start = parse_start(read("chessresults_start.html"))
    title, upd, final = parse_final(read("chessresults_final.html"))
    assert len(start) == len(final) == 122
    assert final[0]["pts"] == 7.0 and start[final[0]["start_no"]]["fide"]
    assert upd == "2026-06-25"


def test_npb_standings_past_format():
    from pipeline.adapters.npb import parse_standings, TEAMS, _norm
    st = parse_standings(read("npb_std_c_2025.html"), {_norm(n): k for k, (n, _) in TEAMS.items()}, "central", "Central")
    assert [r.participant_id for r in st.rows][:1] == ["t"] and len(st.rows) == 6
    assert st.rows[0].stats == {"GP": 143, "W": 85, "L": 54, "T": 4, "PCT": 0.612, "HOME": "41-29", "AWAY": "44-25"}

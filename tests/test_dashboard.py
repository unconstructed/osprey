"""Tests for scripts/build_dashboard.py (standard library + pytest only).

The builder is a script, not a package module, so it is loaded by path. The
repo is found by walking up from this file, so the tests also run from a copy
of tests/ inside the repo, such as mutmut's mutants/tests/ (mutmut copies
tests/ but not scripts/ or dashboard/). Without a builder above them, they skip.
Every test works in pytest's tmp_path; nothing is written into the repo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest


def find_repo(start: Path):
    """The nearest folder at or above `start` holding the builder and its template."""
    for folder in (start, *start.parents):
        if (folder / "scripts" / "build_dashboard.py").is_file() and (
            folder / "dashboard" / "template.html"
        ).is_file():
            return folder
    return None


REPO = find_repo(Path(__file__).resolve().parent)
if REPO is None:
    pytest.skip(
        "scripts/build_dashboard.py and dashboard/template.html not found in any folder above this test "
        "file (a copy of tests/ without the repo around it); the dashboard tests need the builder",
        allow_module_level=True,
    )
BUILDER = REPO / "scripts" / "build_dashboard.py"
TEMPLATE_FILE = REPO / "dashboard" / "template.html"


def _load_builder():
    spec = importlib.util.spec_from_file_location("osprey_build_dashboard", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bd = _load_builder()
TEMPLATE = TEMPLATE_FILE.read_text(encoding="utf-8")
DATA_BLOCK = re.compile(r'<script type="application/json" id="dashboard-data">(.*?)</script>', re.S)


# --------------------------------------------------------------------------- helpers


def write(root: Path, rel: str, content) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content)
    path.write_text(content, encoding="utf-8")
    return path


def page_data(html: str) -> dict:
    m = DATA_BLOCK.search(html)
    assert m, "data block missing"
    return json.loads(m.group(1))


def warnings_for(data: dict, source_part: str) -> list[str]:
    return [w["message"] for w in data["warnings"] if source_part in w["source"]]


def gate(state: str) -> dict:
    flag = {"pass": True, "fail": False, "pending": None}[state]
    return {"value": 1.0, "threshold": 0.5, "op": ">=", "pass": flag}


def audit_doc(strategy: str, date: str, verdict: str, states: dict | None = None, drop=(), **extra) -> dict:
    states = states or {}
    gates = {k: gate(states.get(k, "pass")) for k in bd.GATE_KEYS if k not in drop}
    doc = {"schema": "osprey.audit/1", "strategy": strategy, "date": date, "verdict": verdict, "gates": gates}
    doc.update(extra)
    return doc


def write_audit(root: Path, doc: dict, md: bool = True) -> Path:
    path = write(root, f"reports/{doc['strategy']}/{doc['date']}.json", doc)
    if md:
        write(root, f"reports/{doc['strategy']}/{doc['date']}.md", "# audit\n")
    return path


def gates_from_states(states: dict, drop=()) -> dict:
    w = bd.Warnings()
    return {
        k: bd.normalise_gate(k, None if k in drop else gate(states.get(k, "pass")), "t", w)
        for k in bd.GATE_KEYS
    }


# --------------------------------------------------------------------------- whole-page builds


def test_empty_root_renders_with_empty_states(tmp_path):
    data = bd.collect(tmp_path)
    assert data["warnings"] == []
    assert data["strategies"] == [] and data["milestones"] == []
    assert data["testing"]["junit"] is None and data["testing"]["coverage"] is None
    assert [a["present"] for a in data["testing"]["mutation"]] == [False] * 5
    assert data["data"]["snapshot"] is None and data["studies"] == [] and data["reports"] == []
    assert data["git"] == {"commit": "unknown", "branch": "unknown"}
    assert data["sample"] is False

    html = bd.render(data, TEMPLATE)
    assert "<title>Osprey Strategy Lab - results dashboard</title>" in html
    assert page_data(html) == data

    out = tmp_path / "site" / "index.html"
    assert bd.main(["--root", str(tmp_path), "--out", str(out)]) == 0
    assert out.is_file() and "dashboard-data" in out.read_text(encoding="utf-8")


def test_default_output_path_and_json_export(tmp_path, capsys):
    json_out = tmp_path / "data.json"
    assert bd.main(["--root", str(tmp_path), "--json", str(json_out)]) == 0
    assert (tmp_path / "dashboard" / "index.html").is_file()
    exported = json.loads(json_out.read_text(encoding="utf-8"))
    assert exported["schema"] == "osprey.dashboard/1"
    assert exported["link_root"] == ".."
    line = capsys.readouterr().out.strip()
    assert line.startswith("dashboard: 0 strategies") and line.endswith("index.html")


def test_missing_root_is_an_error_not_a_traceback(tmp_path, capsys):
    assert bd.main(["--root", str(tmp_path / "nope")]) == 2
    assert "not a folder" in capsys.readouterr().err


def test_sample_build_exercises_every_state_and_stays_out_of_the_repo(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bd.tempfile, "tempdir", str(tmp_path))  # the synthetic tree goes under tmp_path
    before = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "dashboard").rglob("*"))
    out = tmp_path / "sample.html"
    assert bd.main(["--sample", "--out", str(out)]) == 0
    assert "SAMPLE dashboard" in capsys.readouterr().out
    after = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "dashboard").rglob("*"))
    assert before == after, "--sample wrote into the repo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.html"], "the synthetic tree was left behind"

    html = out.read_text(encoding="utf-8")
    assert re.search(r"<title>SAMPLE", html)
    data = page_data(html)
    assert data["sample"] is True
    states = {s["name"]: (s["latest"] or {}).get("state") for s in data["strategies"]}
    assert set(states.values()) == {bd.READY, bd.AWAITING, bd.FAIL, bd.INCOMPLETE, None}
    assert any(w["level"] == "integrity" for w in data["warnings"])
    assert not [w for w in data["warnings"] if "internal error" in w["message"]]
    t = data["testing"]
    assert t["junit"]["total"] > 0 and t["coverage"]["percent"] is not None
    assert all(a["present"] for a in t["mutation"])
    assert data["data"]["snapshot"]["series"] and data["data"]["quality_reports"]
    assert len(data["studies"]) >= 2 and data["exports"] and data["reports"]
    assert any(s["latest"] and s["latest"]["equity"] for s in data["strategies"])
    assert data["link_root"] is None  # the synthetic tree is gone, so nothing is linked
    momentum = next(s for s in data["strategies"] if s["name"] == "momentum-bold")
    assert [h["state"] for h in momentum["history"]] == [bd.UNREADABLE, bd.FAIL]  # older broken file


def test_sample_without_out_goes_to_the_temp_folder_never_the_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bd.tempfile, "tempdir", str(tmp_path))
    before = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "dashboard").rglob("*"))
    assert bd.main(["--sample"]) == 0
    assert (tmp_path / "osprey-dashboard-sample.html").is_file()
    assert str(tmp_path / "osprey-dashboard-sample.html") in capsys.readouterr().out
    assert sorted(p.relative_to(REPO).as_posix() for p in (REPO / "dashboard").rglob("*")) == before


def test_sample_refuses_to_write_inside_a_git_checkout(tmp_path, capsys):
    (tmp_path / "other-repo" / ".git").mkdir(parents=True)
    out = tmp_path / "other-repo" / "dashboard" / "index.html"
    assert bd.main(["--sample", "--out", str(out)]) == 2
    assert "never be committed" in capsys.readouterr().err
    assert not out.exists()
    inside = REPO / "dashboard" / "sample-refusal-test.html"  # this checkout, with or without .git
    try:
        assert bd.main(["--sample", "--out", str(inside)]) == 2
        assert not inside.exists()
    finally:
        inside.unlink(missing_ok=True)


def test_sample_tree_is_deterministic(tmp_path):
    a = bd.make_sample_root(tmp_path / "a")
    b = bd.make_sample_root(tmp_path / "b")
    files = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


# --------------------------------------------------------------------------- AGENTS.md / TESTING.md

AGENTS_FIXTURE = (
    """# AGENTS.md

```yaml
# config/costs.yaml - a comment, not a heading
## Milestones (inside a fence, ignored)
```

## Validation gates

| Gate | Default |
|---|---|
"""
    + "".join(f"| gate {i} | rule {i} |\n" for i in range(9))
    + """
## Strategies to build first

| Strategy | Risk level | Idea | Free parameters (keep ≤ 4) |
|---|---|---|---|
| `alpha-steady` | Steady | Hold **BTC** with a [band](x.md) | a, b |
| `beta-bold` | Bold | Pipe \\| inside | k |

## Milestones

| # | Milestone | Done when |
|---|---|---|
| 0 | Verified | [TESTING.md](TESTING.md) definition of done met |
| 1 | Data | `SNAPSHOT.json` written |
| x | Not a milestone row | ignored |

## Commands
"""
)


def test_agents_md_tables(tmp_path):
    write(tmp_path, "AGENTS.md", AGENTS_FIXTURE)
    w = bd.Warnings()
    agents = bd.collect_agents(tmp_path, w)
    assert w.items == []
    assert [(m["id"], m["name"], m["done_when"]) for m in agents["milestones"]] == [
        ("0", "Verified", "TESTING.md definition of done met"),
        ("1", "Data", "SNAPSHOT.json written"),
    ]
    assert [g["default"] for g in agents["gates"]] == [f"rule {i}" for i in range(9)]
    assert [s["name"] for s in agents["strategies"]] == ["alpha-steady", "beta-bold"]
    assert agents["strategies"][0]["idea"] == "Hold BTC with a band"
    assert agents["strategies"][1]["idea"] == "Pipe | inside"
    defs = bd.build_gate_defs(agents, w)
    assert [d["rule"] for d in defs] == [f"rule {i}" for i in range(9)]


def test_agents_md_missing_sections_warn(tmp_path):
    write(tmp_path, "AGENTS.md", "# AGENTS.md\n\nNo tables here.\n")
    data = bd.collect(tmp_path)
    messages = warnings_for(data, "AGENTS.md")
    assert any("Milestones" in m for m in messages)
    assert any("Validation gates" in m for m in messages)
    assert [g["key"] for g in data["gate_defs"]] == list(bd.GATE_KEYS)


@pytest.mark.skipif(not (REPO / "AGENTS.md").is_file(), reason="AGENTS.md not in this checkout")
def test_real_agents_md_parses():
    w = bd.Warnings()
    agents = bd.collect_agents(REPO, w)
    assert w.items == []
    assert [m["id"] for m in agents["milestones"]][:6] == ["0", "1", "2", "3", "4", "5"]
    assert len(agents["gates"]) == 9
    assert {"rebalance-steady", "dip-buy-balanced", "momentum-bold"} <= {
        s["name"] for s in agents["strategies"]
    }


TESTING_FIXTURE = """# TESTING.md

## 4. Bug log

| # | Where | Bug | Fix |
|---|---|---|---|
| 1 | a | b | c |
| 2 | a | b | c |
| 3 | a | b | c |
| - | a note row, not a numbered bug | | |

## 5. Open work, in order

### 5.1 First `thing`
```
### 5.9 inside a fence, ignored
```
### 5.2 Second thing

## 8. Definition of done (this testing work)

- [ ] Not yet
- [x] Done one
- [X] Done two

## 9. Report back
- [ ] not part of the definition of done
"""


def test_testing_md_checkboxes_bug_log_and_open_work(tmp_path):
    write(tmp_path, "TESTING.md", TESTING_FIXTURE)
    w = bd.Warnings()
    t = bd.collect_testing_md(tmp_path, w)
    assert w.items == []
    assert t["bug_count"] == 3
    assert [(o["id"], o["title"]) for o in t["open_work"]] == [
        ("5.1", "First thing"),
        ("5.2", "Second thing"),
    ]
    assert [(d["text"], d["done"]) for d in t["dod"]] == [
        ("Not yet", False),
        ("Done one", True),
        ("Done two", True),
    ]


@pytest.mark.skipif(not (REPO / "TESTING.md").is_file(), reason="TESTING.md not in this checkout")
def test_real_testing_md_parses():
    w = bd.Warnings()
    t = bd.collect_testing_md(REPO, w)
    assert w.items == []
    assert t["bug_count"] >= 7
    assert [o["id"] for o in t["open_work"]][:7] == [f"5.{i}" for i in range(1, 8)]
    assert len(t["dod"]) >= 7 and all(isinstance(d["done"], bool) for d in t["dod"])


def test_committed_status_json_is_clean():
    w = bd.Warnings()
    status = bd.collect_status(REPO, w)
    assert status["present"] and w.items == []
    assert sorted(status["milestones"]) == ["0", "1", "2", "3", "4", "5"]
    assert all(m["status"] in bd.STATUS_VALUES for m in status["milestones"].values())


def test_status_json_unknown_value_is_shown_with_a_warning(tmp_path):
    write(
        tmp_path,
        "dashboard/status.json",
        {
            "milestones": {"0": {"status": "paused"}, "1": 5},
            "open_work": {"5.1": "done"},
            "strategies": {"x": {"paper": 3}},
        },
    )
    w = bd.Warnings()
    status = bd.collect_status(tmp_path, w)
    assert status["milestones"]["0"]["status"] == "paused"
    assert "1" not in status["milestones"]
    assert status["open_work"]["5.1"]["status"] == "done"
    messages = " ".join(i["message"] for i in w.items)
    assert "unknown status 'paused'" in messages and "milestones.1" in messages and "strategies.x" in messages


# --------------------------------------------------------------------------- gate state


@pytest.mark.parametrize(
    "states, drop, expected",
    [
        ({}, (), bd.READY),
        ({"final_test": "pending"}, (), bd.AWAITING),
        ({"dsr": "fail"}, (), bd.FAIL),
        ({"dsr": "fail", "final_test": "pending"}, ("pbo",), bd.FAIL),
        ({"pbo": "pending"}, (), bd.INCOMPLETE),
        ({}, ("regime_max_profit_share",), bd.INCOMPLETE),  # missing gate is never a pass
        ({}, ("final_test",), bd.INCOMPLETE),  # missing final test is not "awaiting"
        ({"final_test": "pending", "pbo": "pending"}, (), bd.INCOMPLETE),
        ({"final_test": "pending"}, ("pbo",), bd.INCOMPLETE),  # a missing gate is never "awaiting"
        ({"final_test": "pending"}, ("beats_benchmarks", "dsr"), bd.INCOMPLETE),
    ],
)
def test_gate_state_derivation(states, drop, expected):
    state, reason = bd.derive_state(gates_from_states(states, drop))
    assert state == expected
    if expected == bd.INCOMPLETE and drop:
        missing = reason.split("missing: ", 1)[1].split(";")[0].split(", ")
        assert sorted(missing) == sorted(drop)


def test_gate_with_bad_pass_flag_counts_as_pending():
    w = bd.Warnings()
    g = bd.normalise_gate("dsr", {"value": 0.97, "pass": "yes"}, "f", w)
    assert g["pass"] is None and g["state"] == "pending" and w.items


def test_verdict_pass_with_missing_gate_is_an_integrity_warning(tmp_path):
    write_audit(tmp_path, audit_doc("s1", "2026-11-19", "PASS", drop=("pbo",)))
    data = bd.collect(tmp_path)
    latest = data["strategies"][0]["latest"]
    assert latest["state"] == bd.INCOMPLETE
    assert latest["integrity"]["level"] == "integrity"
    assert data["overview"]["integrity_warnings"] == 1
    assert data["strategies"][0]["stages"][3] == {
        "key": "ready",
        "label": "Ready for paper",
        "reached": False,
    }


def test_other_verdict_mismatch_is_a_plain_warning(tmp_path):
    write_audit(tmp_path, audit_doc("s1", "2026-11-19", "FAIL"))
    data = bd.collect(tmp_path)
    assert data["strategies"][0]["latest"]["state"] == bd.READY
    assert data["strategies"][0]["latest"]["integrity"]["level"] == "warning"
    assert data["overview"]["integrity_warnings"] == 0 and data["overview"]["warnings"] == 1


def test_consistent_audit_has_no_warnings(tmp_path):
    write_audit(tmp_path, audit_doc("s1", "2026-11-19", "PASS", report_md="reports/s1/2026-11-19.md"))
    data = bd.collect(tmp_path)
    assert data["warnings"] == []
    s = data["strategies"][0]
    assert s["stage"] == "ready" and s["latest"]["report_md"]["path"] == "reports/s1/2026-11-19.md"


def test_latest_audit_is_chosen_by_file_date_not_mtime(tmp_path):
    new = write_audit(tmp_path, audit_doc("s1", "2026-11-19", "FAIL", {"dsr": "fail"}))
    old = write_audit(tmp_path, audit_doc("s1", "2026-01-05", "PASS"))
    mid = write_audit(tmp_path, audit_doc("s1", "2026-02-01", "INCOMPLETE", {"final_test": "pending"}))
    os.utime(new, (1_000_000, 1_000_000))
    os.utime(old, (2_000_000_000, 2_000_000_000))
    os.utime(mid, (1_500_000_000, 1_500_000_000))
    write(tmp_path, "reports/s1/notes.json", {"schema": "osprey.audit/1"})
    write(tmp_path, "reports/demo/2026-12-01.json", audit_doc("demo", "2026-12-01", "PASS"))
    data = bd.collect(tmp_path)
    assert [s["name"] for s in data["strategies"]] == ["s1"]
    s1 = data["strategies"][0]
    assert s1["latest"]["date"] == "2026-11-19" and s1["latest"]["state"] == bd.FAIL
    assert [h["date"] for h in s1["history"]] == ["2026-01-05", "2026-02-01", "2026-11-19"]
    assert warnings_for(data, "reports/s1/notes.json")


# --------------------------------------------------------------------------- malformed inputs


@pytest.mark.parametrize(
    "rel, content, expect",
    [
        ("reports/s1/2026-11-19.json", '{"schema": "osprey.audit/1", ', "invalid JSON"),
        ("reports/s1/2026-11-19.json", "", "empty"),
        ("reports/s1/2026-11-19.json", "[1, 2]", "expected a JSON object"),
        ("reports/s1/2026-11-19.json", '{"schema": "other/2"}', "expected 'osprey.audit/1'"),
        ("dashboard/status.json", "", "empty"),
        ("dashboard/status.json", '{"milestones": [1, 2]}', "should be an object"),
        ("results/tests/junit.xml", "<testsuites><testsuite", "invalid XML"),
        ("results/tests/junit.xml", "<report/>", "no <testsuite>"),
        ("results/tests/junit.xml", '<testsuite tests="1e400" failures="nan" time="1e400"/>', "not a count"),
        ("results/tests/coverage.json", '{"totals": {"percent_covered": NaN}}', "percent_covered"),
        ("results/tests/coverage.json", '{"totals": "x"}', "percent_covered"),
        ("results/tests/mutation/data.json", '{"killed": "many", "survived": -1}', "skipped"),
        ("results/tests/mutation/extra.json", '{"killed": 1}', "unknown mutation area"),
        ("data/catalog/SNAPSHOT.json", '{"foo": 1}', "unrecognised shape"),
        ("data/catalog/SNAPSHOT.json", "[]", "expected a JSON object"),
        ("data/catalog/SNAPSHOT.json", '{"id": "s", "series": "x", "created": Infinity}', "series"),
        (
            "results/tests/coverage.json",
            '{"totals": {"percent_covered": ' + "9" * 5000 + "}}",
            "could not parse JSON",
        ),
    ],
)
def test_malformed_input_becomes_a_warning(tmp_path, rel, content, expect):
    write(tmp_path, rel, content)
    data = bd.collect(tmp_path)
    messages = warnings_for(data, rel)
    assert any(expect in m for m in messages), messages
    assert not [w for w in data["warnings"] if "internal error" in w["message"]]
    page_data(bd.render(data, TEMPLATE))  # still renders, still valid JSON


def test_wrong_types_inside_an_audit_never_crash(tmp_path):
    doc = audit_doc(
        "s1",
        "2026-11-19",
        7,
        metrics="fast",
        benchmarks=[1],
        window="all",
        seed={"a": 1},
        equity={"dates": ["2020-01-01", "2020-01-02"], "series": {"strategy": [1, 2, 3], "b": "x"}},
    )
    doc["gates"]["dsr"] = [0.9]
    doc["gates"]["unknown_gate"] = {"pass": True}
    write_audit(tmp_path, doc)
    data = bd.collect(tmp_path)
    latest = data["strategies"][0]["latest"]
    assert latest["state"] == bd.INCOMPLETE  # dsr counts as missing
    assert latest["equity"] is None and latest["metrics"] == [] and latest["seed"] is None
    text = " ".join(warnings_for(data, "reports/s1"))
    for fragment in (
        "unknown verdict",
        "gate 'dsr'",
        "unknown gate",
        "'metrics'",
        "has 3 values",
        "not a list",
    ):
        assert fragment in text
    assert not [w for w in data["warnings"] if "internal error" in w["message"]]


def test_gates_not_an_object_counts_every_gate_missing(tmp_path):
    doc = audit_doc("s1", "2026-11-19", "PASS")
    doc["gates"] = [1, 2, 3]
    write_audit(tmp_path, doc)
    data = bd.collect(tmp_path)
    assert data["strategies"][0]["latest"]["gate_counts"]["missing"] == 9
    assert data["overview"]["integrity_warnings"] == 1


# --------------------------------------------------------------------------- equity


def test_equity_is_normalised_and_bad_series_are_skipped():
    w = bd.Warnings()
    eq = bd.normalise_equity(
        {
            "dates": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "series": {
                "buy_hold_btc": [200, 100, 400],
                "strategy": [50, None, 75],
                "short": [1, 2],
                "zero_start": [0, 1, 2],
                "goes_negative": [10, -5, 20],
                "nan": [1.0, float("nan"), 2.0],
            },
        },
        "f",
        w,
    )
    names = [s["name"] for s in eq["series"]]
    assert names[:2] == ["strategy", "buy_hold_btc"]  # fixed colour order
    assert "short" not in names and "zero_start" not in names
    by = {s["name"]: s for s in eq["series"]}
    assert by["strategy"]["values"] == [1.0, None, 1.5]
    assert by["buy_hold_btc"]["values"] == [1.0, 0.5, 2.0]
    assert by["goes_negative"]["nonpositive"] == 1
    assert by["nan"]["values"] == [1.0, None, 2.0]
    text = " ".join(i["message"] for i in w.items)
    assert "has 2 values for 3 dates" in text and "positive number" in text and "log scale" in text


def test_long_equity_is_thinned_but_keeps_the_last_point():
    n = bd.EQUITY_MAX_POINTS * 2 + 7
    eq = bd.normalise_equity(
        {"dates": [str(i) for i in range(n)], "series": {"strategy": list(range(1, n + 1))}},
        "f",
        bd.Warnings(),
    )
    assert len(eq["dates"]) <= bd.EQUITY_MAX_POINTS + 1
    assert eq["dates"][-1] == str(n - 1) and eq["series"][0]["values"][-1] == n
    assert eq["thinned_every"] == 3


# --------------------------------------------------------------------------- testing inputs


def test_mutation_score_formula_matches_the_testing_md_baseline():
    score, score_ex = bd.mutation_scores({"killed": 492, "timeout": 3, "survived": 123})
    assert score == pytest.approx(0.801, abs=5e-4)
    assert score == pytest.approx(495 / 618) and score_ex == score
    _, score_ex = bd.mutation_scores({"killed": 492, "timeout": 3, "survived": 123, "equivalent": 23})
    assert score_ex == pytest.approx(495 / 595)
    assert bd.mutation_scores({"killed": 0, "survived": 0}) == (None, None)
    _, capped = bd.mutation_scores({"killed": 5, "survived": 2, "equivalent": 9})
    assert capped == 1.0


def test_mutation_file_is_read_and_compared_with_its_target(tmp_path):
    write(
        tmp_path,
        "results/tests/mutation/validation.json",
        {
            "killed": 492,
            "survived": 123,
            "timeout": 3,
            "suspicious": 0,
            "no_tests": 12,
            "skipped": 0,
            "total": 630,
        },
    )
    write(tmp_path, "results/tests/mutation/data.json", {"killed": 90, "survived": 10, "timeout": 0})
    areas = {a["area"]: a for a in bd.collect(tmp_path)["testing"]["mutation"]}
    assert areas["validation"]["score"] == pytest.approx(0.801, abs=5e-4)
    assert areas["validation"]["meets_target"] is False  # target 90%
    assert areas["data"]["meets_target"] is True and areas["data"]["score"] == pytest.approx(0.9)
    assert areas["runner"]["present"] is False


def test_meets_target_uses_the_score_without_equivalent_mutants(tmp_path):
    # raw score 85/100 misses 90%; without the 10 equivalent survivors it is 85/90 = 94%
    write(tmp_path, "results/tests/mutation/runner.json", {"killed": 85, "survived": 15, "equivalent": 10})
    runner = {a["area"]: a for a in bd.collect(tmp_path)["testing"]["mutation"]}["runner"]
    assert runner["score"] == pytest.approx(0.85)
    assert runner["score_excluding_equivalent"] == pytest.approx(85 / 90)
    assert runner["meets_target"] is True


def test_real_mutmut_stats_file_is_read(tmp_path):
    # the key set mutmut 3.8 writes with `export-cicd-stats`
    stats = {
        "killed": 492,
        "survived": 123,
        "total": 640,
        "no_tests": 12,
        "skipped": 0,
        "suspicious": 0,
        "timeout": 3,
        "check_was_interrupted_by_user": 4,
        "segfault": 2,
    }
    write(tmp_path, "results/tests/mutation/validation.json", stats)
    data = bd.collect(tmp_path)
    area = data["testing"]["mutation"][0]
    assert area["counts"]["segfault"] == 2 and area["score"] == pytest.approx(495 / 618)
    assert any("interrupted" in m for m in warnings_for(data, "mutation/validation.json"))


def test_junit_counts(tmp_path):
    write(
        tmp_path,
        "results/tests/junit.xml",
        """<?xml version="1.0"?>
<testsuites name="pytest tests">
  <testsuite name="a" tests="10" failures="1" errors="1" skipped="2" time="3.5" timestamp="2026-11-18T10:00:00">
    <testcase classname="tests.test_a" name="test_ok"/>
    <testcase classname="tests.test_a" name="test_bad"><failure message="x"/></testcase>
    <testcase classname="tests.test_a" name="test_err"><error message="y"/></testcase>
  </testsuite>
  <testsuite name="b" tests="5" failures="0" errors="0" skipped="0" time="1.5" timestamp="2026-11-18T10:01:00"/>
</testsuites>""",
    )
    j = bd.collect_junit(tmp_path, bd.Warnings())
    assert (j["total"], j["passed"], j["failed"], j["errors"], j["skipped"]) == (15, 11, 1, 1, 2)
    assert j["time_s"] == 5.0 and j["timestamp"] == "2026-11-18T10:01:00"
    assert j["failing_tests"] == ["tests.test_a::test_bad", "tests.test_a::test_err"]


def test_junit_single_testsuite_root(tmp_path):
    write(tmp_path, "results/tests/junit.xml", '<testsuite tests="3" failures="0" errors="0" skipped="1"/>')
    j = bd.collect_junit(tmp_path, bd.Warnings())
    assert (j["total"], j["passed"]) == (3, 2)


def test_coverage_totals_and_lowest_files(tmp_path):
    write(
        tmp_path,
        "results/tests/coverage.json",
        {
            "meta": {"branch_coverage": True, "timestamp": "2026-11-18T10:00:00"},
            "files": {f"lab/m{i}.py": {"summary": {"percent_covered": 100 - i}} for i in range(8)},
            "totals": {"percent_covered": 96.25, "num_branches": 80, "covered_branches": 77},
        },
    )
    c = bd.collect_coverage(tmp_path, bd.Warnings())
    assert c["percent"] == 96.25 and (c["branches_covered"], c["branches_total"]) == (77, 80)
    assert [f["file"] for f in c["lowest_files"]] == [f"lab/m{i}.py" for i in (7, 6, 5, 4, 3)]
    assert c["n_files"] == 8


def test_coverage_without_branch_flag_warns(tmp_path):
    write(
        tmp_path,
        "results/tests/coverage.json",
        {"meta": {"branch_coverage": False}, "totals": {"percent_covered": 90}},
    )
    w = bd.Warnings()
    assert bd.collect_coverage(tmp_path, w)["percent"] == 90
    assert "--cov-branch" in w.items[0]["message"]


# --------------------------------------------------------------------------- safety


def test_hostile_strings_cannot_break_out_of_the_data_block(tmp_path):
    evil = '</script><img src=x onerror="alert(1)"><!-- \u2028 &amp; a&b>c \u2029'
    doc = audit_doc(
        "s1",
        "2026-11-19",
        "PASS",
        report_md=evil,
        metrics={evil: 1.0},
        risk_level="</SCRIPT><script>alert(2)</script>",
    )
    doc["gates"]["dsr"]["note"] = evil
    write_audit(tmp_path, doc)
    html = bd.render(bd.collect(tmp_path), TEMPLATE)
    assert html.count("</script>") == TEMPLATE.count("</script>")
    assert "<img" not in html and "<!--  " not in html and " " not in html
    assert html.upper().count("</SCRIPT") == TEMPLATE.upper().count("</SCRIPT")
    block = DATA_BLOCK.search(html).group(1)
    for raw in ("<", ">", "&", "\u2028", "\u2029"):
        assert raw not in block, f"{raw!r} must be escaped inside the data block"
    latest = page_data(html)["strategies"][0]["latest"]
    assert latest["report_md"] == {"text": evil, "path": None}  # shown as text, never linked
    assert latest["metrics"][0][0] == evil
    assert latest["gates"][2]["note"] == evil
    assert latest["risk_level"] == "</SCRIPT><script>alert(2)</script>"


def test_report_md_outside_the_repo_is_not_linked(tmp_path):
    for value in ("javascript:alert(1)", "/etc/passwd", "../outside.md", "https://example.com/a.md"):
        w = bd.Warnings()
        assert bd._report_link(value, tmp_path, "f", w)["path"] is None
        assert w.items


def test_template_renders_data_without_html_injection_or_network():
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert forbidden not in TEMPLATE, forbidden
    assert "<link" not in TEMPLATE and not re.search(r"<script[^>]+src=", TEMPLATE)
    urls = set(re.findall(r"https?://[^\s'\")]+", TEMPLATE))
    assert urls <= {"http://www.w3.org/2000/svg"}, urls
    assert TEMPLATE.count(bd.DATA_PLACEHOLDER) == 1 and TEMPLATE.count(bd.TITLE_PLACEHOLDER) == 1


def test_render_rejects_a_template_without_placeholders():
    with pytest.raises(ValueError):
        bd.render({"sample": False}, "<html></html>")


def test_sample_title_and_banner_flag():
    html = bd.render({"sample": True, "x": 1}, TEMPLATE)
    assert re.search(r"<title>SAMPLE DATA - not real results \| Osprey", html)
    plain = bd.render({"sample": False}, TEMPLATE)
    assert "<title>SAMPLE" not in plain


# --------------------------------------------------------------------------- misc collectors


def test_strategy_union_and_lifecycle(tmp_path):
    write(tmp_path, "AGENTS.md", AGENTS_FIXTURE)
    write(tmp_path, "strategies/alpha-steady/strategy.py", "")
    write(tmp_path, "strategies/gamma/params.yaml", "")
    write(tmp_path, "exports/delta/config.yaml", "secret: never read\n")
    write(
        tmp_path,
        "dashboard/status.json",
        {"strategies": {"alpha-steady": {"paper": {"status": "in_progress"}}}},
    )
    write_audit(tmp_path, audit_doc("alpha-steady", "2026-11-19", "PASS"))
    data = bd.collect(tmp_path)
    by = {s["name"]: s for s in data["strategies"]}
    assert list(by)[:2] == ["alpha-steady", "beta-bold"]  # launch table order first
    assert set(by) == {"alpha-steady", "beta-bold", "gamma", "delta"}
    assert by["alpha-steady"]["stage"] == "paper"
    assert by["beta-bold"]["stage"] == "planned"
    assert by["gamma"]["stage"] == "planned" and by["gamma"]["folder"]["files"]["params.yaml"] is True
    assert by["delta"]["stage"] == "exported" and by["delta"]["export"]["path"] == "exports/delta/config.yaml"
    assert warnings_for(data, "strategy delta")  # exported without a ready audit
    assert "never read" not in json.dumps(data)


def test_status_json_strategy_alone_does_not_create_a_strategy(tmp_path):
    write(tmp_path, "dashboard/status.json", {"strategies": {"ghost": {"paper": {"status": "done"}}}})
    data = bd.collect(tmp_path)
    assert data["strategies"] == []
    assert any("strategies.ghost" in m for m in warnings_for(data, "dashboard/status.json"))


def test_studies_snapshot_and_reports(tmp_path):
    write(tmp_path, "results/study-a/trials/0.parquet", "")
    write(tmp_path, "results/study-a/trials/1.parquet", "")
    write(tmp_path, "results/study-a/journal.log", "")
    write(tmp_path, "results/study-b/x.txt", "")
    write(tmp_path, "results/tests/junit-not-a-study.xml", "")
    write(
        tmp_path,
        "data/catalog/SNAPSHOT.json",
        {
            "snapshot_id": "snap-1",
            "sources": {"kraken": {}, "binance": {}},
            "series": [{"instrument": "BTC/USD", "rows": 10, "extra": [1]}],
        },
    )
    write(tmp_path, "reports/data/2026-01-02-quality.md", "")
    write(tmp_path, "reports/s1/2026-03-04.md", "")
    write(tmp_path, "reports/demo/2026-02-03.md", "")
    data = bd.collect(tmp_path)
    studies = {s["name"]: s for s in data["studies"]}
    assert set(studies) == {"study-a", "study-b"}
    assert studies["study-a"]["parquet_files"] == 2 and studies["study-a"]["journal"] is True
    assert studies["study-b"]["journal"] is False
    snap = data["data"]["snapshot"]
    assert snap["id"] == "snap-1" and snap["sources"] == ["kraken", "binance"]
    assert snap["series"][0]["instrument"] == "BTC/USD" and "extra" not in snap["series"][0]
    assert [r["path"] for r in data["reports"]] == [
        "reports/s1/2026-03-04.md",
        "reports/demo/2026-02-03.md",
        "reports/data/2026-01-02-quality.md",
    ]
    assert [r["kind"] for r in data["reports"]] == ["audit", "demo", "data"]


def test_git_falls_back_to_head_file(tmp_path):
    write(tmp_path, ".git/HEAD", "ref: refs/heads/feature-x\n")
    git = bd.collect_git(tmp_path)
    assert git["branch"] == "feature-x" and git["commit"] == "unknown"


def test_link_root_points_from_the_page_to_the_repo(tmp_path):
    assert bd.link_root(tmp_path, tmp_path / "dashboard" / "index.html") == ".."
    assert bd.link_root(tmp_path / "repo", tmp_path / "out.html") == "repo"


# --------------------------------------------------------------------------- review regressions


def test_repo_is_found_from_a_copy_of_tests_inside_it(tmp_path):
    # mutmut runs a copy of tests/ from mutants/tests/; the builder is two levels up
    write(tmp_path, "scripts/build_dashboard.py", "")
    write(tmp_path, "dashboard/template.html", "")
    copy = tmp_path / "mutants" / "tests"
    copy.mkdir(parents=True)
    assert find_repo(copy) == tmp_path
    write(tmp_path, "mutants/scripts/build_dashboard.py", "")  # a builder without its template is skipped
    assert find_repo(copy) == tmp_path
    assert find_repo(tmp_path / "mutants" / "elsewhere") == tmp_path
    lonely = tmp_path.parent / (tmp_path.name + "-lonely") / "tests"
    lonely.mkdir(parents=True)
    assert find_repo(lonely) is None


def test_lone_surrogate_in_json_is_repaired_with_a_warning(tmp_path):
    write(
        tmp_path,
        "dashboard/status.json",
        '{"note": "bad \\ud800 surrogate", "milestones": {"\\udcff": "done"}}',
    )
    write_audit(tmp_path, audit_doc("s1", "2026-11-19", "PASS", risk_level="x\udc80y"))
    data = bd.collect(tmp_path)
    assert data["status"]["note"] == "bad � surrogate"
    assert any("invalid Unicode" in m for m in warnings_for(data, "dashboard/status.json"))
    html = bd.render(data, TEMPLATE)
    html.encode("utf-8")  # must not raise
    out = tmp_path / "out.html"
    assert bd.main(["--root", str(tmp_path), "--out", str(out), "--json", str(tmp_path / "d.json")]) == 0
    assert page_data(out.read_text(encoding="utf-8"))["status"]["note"] == "bad � surrogate"


@pytest.mark.skipif(os.name == "nt", reason="needs a file system that accepts non-UTF-8 names")
def test_file_names_that_are_not_utf8_do_not_stop_the_build(tmp_path):
    reports = os.fsencode(str(tmp_path / "reports"))
    os.makedirs(reports + b"/s\xff", exist_ok=True)
    with open(reports + b"/bad\xffname.md", "wb") as f:
        f.write(b"# report\n")
    os.makedirs(os.fsencode(str(tmp_path / "strategies")) + b"/t\xfe", exist_ok=True)
    out = tmp_path / "out.html"
    assert bd.main(["--root", str(tmp_path), "--out", str(out)]) == 0
    data = page_data(out.read_text(encoding="utf-8"))
    assert "reports/bad�name.md" in [r["path"] for r in data["reports"]]
    assert "t�" in [s["name"] for s in data["strategies"]]
    assert any("not valid UTF-8" in w["message"] for w in data["warnings"])


def test_a_failed_write_never_truncates_the_previous_page(tmp_path, monkeypatch, capsys):
    out = tmp_path / "dashboard" / "index.html"
    write(tmp_path, "dashboard/index.html", "PREVIOUS GOOD PAGE")
    with pytest.raises(UnicodeEncodeError):
        bd.write_atomic(out, "half a page \ud800")
    assert out.read_text(encoding="utf-8") == "PREVIOUS GOOD PAGE"
    monkeypatch.setattr(bd, "render", lambda data, template: "broken \ud800 page")
    assert bd.main(["--root", str(tmp_path)]) == 2
    assert "cannot write output" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "PREVIOUS GOOD PAGE"
    assert sorted(p.name for p in out.parent.iterdir()) == ["index.html"]  # no temp file left


@pytest.mark.parametrize(
    "newest",
    [
        '{"schema": "osprey.audit/1", "verdict": "FAIL", ',  # truncated
        '{"schema": "osprey.audit/2", "verdict": "FAIL"}',  # unknown schema
        '{"schema": "osprey.audit/1", "seed": ' + "9" * 5000 + "}",  # integer too long to parse
        "[]",
    ],
)
def test_an_unreadable_newest_audit_is_never_replaced_by_an_older_pass(tmp_path, newest):
    write_audit(tmp_path, audit_doc("s1", "2026-01-01", "PASS"))
    write(tmp_path, "reports/s1/2026-06-01.json", newest)
    data = bd.collect(tmp_path)
    s1 = data["strategies"][0]
    assert s1["latest"]["date"] == "2026-06-01" and s1["latest"]["state"] == bd.UNREADABLE
    assert s1["stage"] == "audited" and data["overview"]["strategies_ready"] == 0
    assert [h["state"] for h in s1["history"]] == [bd.READY, bd.UNREADABLE]
    integrity = [x for x in data["warnings"] if x["level"] == "integrity"]
    assert len(integrity) == 1 and "reports/s1/2026-06-01.json" in integrity[0]["message"]
    assert "2026-01-01" in integrity[0]["message"]
    page_data(bd.render(data, TEMPLATE))


def test_an_unreadable_older_audit_stays_in_the_history_only(tmp_path):
    write(tmp_path, "reports/s1/2026-01-01.json", "{")
    write_audit(tmp_path, audit_doc("s1", "2026-06-01", "PASS"))
    data = bd.collect(tmp_path)
    s1 = data["strategies"][0]
    assert s1["latest"]["state"] == bd.READY and s1["stage"] == "ready"
    assert [h["state"] for h in s1["history"]] == [bd.UNREADABLE, bd.READY]
    assert data["overview"]["integrity_warnings"] == 0
    assert warnings_for(data, "reports/s1/2026-01-01.json")


def test_a_pass_with_no_number_behind_it_is_an_integrity_warning(tmp_path):
    doc = audit_doc("s1", "2026-11-19", "PASS")
    doc["gates"]["dsr"] = {"value": float("nan"), "threshold": 0.95, "op": ">=", "pass": True}
    doc["gates"]["pbo"] = {"threshold": 0.25, "op": "<=", "pass": True}  # no value at all
    doc["gates"]["mc_p95_max_drawdown"] = {"value": 0.2, "threshold": None, "op": "<=", "pass": True}
    doc["gates"]["beats_benchmarks"] = {"value": True, "pass": True}  # true/false gate: fine
    write(tmp_path, "reports/s1/2026-11-19.json", json.dumps(doc))  # NaN written as NaN
    write(tmp_path, "reports/s1/2026-11-19.md", "# audit\n")
    data = bd.collect(tmp_path)
    latest = data["strategies"][0]["latest"]
    assert latest["state"] == bd.READY  # the flags still decide the state; nothing is re-judged
    gates = {g["key"]: g for g in latest["gates"]}
    assert gates["dsr"]["unsupported"] == ["value"] and gates["pbo"]["unsupported"] == ["value"]
    assert gates["mc_p95_max_drawdown"]["unsupported"] == ["threshold"]
    assert gates["beats_benchmarks"]["unsupported"] == [] and gates["final_test"]["unsupported"] == []
    integrity = [x for x in data["warnings"] if x["level"] == "integrity"]
    assert len(integrity) == 1 and "dsr" in integrity[0]["message"] and "pbo" in integrity[0]["message"]
    assert [a["level"] for a in latest["alerts"]] == ["integrity"]


def test_threshold_is_shown_as_written():
    g = bd.normalise_gate(
        "wf_oos_sharpe", {"value": 1.2, "threshold": 1.0, "op": ">=", "pass": True}, "f", bd.Warnings()
    )
    assert g["threshold_text"] == "1.0" and g["unsupported"] == []


def test_equity_values_out_of_range_become_gaps_and_small_values_survive():
    w = bd.Warnings()
    eq = bd.normalise_equity(
        {
            "dates": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "series": {"strategy": [1, 1e300, 1e308], "tiny_base": [1e-300, 1, 1e-9], "small": [1, 1e-9, 2]},
        },
        "f",
        w,
    )
    by = {s["name"]: s["values"] for s in eq["series"]}
    assert by["strategy"] == [1.0, None, None]
    assert by["tiny_base"] == [1.0, None, None]
    assert by["small"] == [1.0, 1e-9, 2.0]  # not rounded away to 0
    text = " ".join(i["message"] for i in w.items)
    assert text.count("shown as gaps") == 2 and "log scale" not in text


def test_template_guards_the_chart_and_test_tile():
    # Bounded tick loops, a range check before drawing, and per-chart error isolation.
    assert "guard < 100" in TEMPLATE and "e1 - e0 > 8" in TEMPLATE
    assert "out of the range this chart can draw" in TEMPLATE
    assert "redraws.push(safeDraw)" in TEMPLATE
    # The test-run tile is green only for a run with tests and nothing failing.
    assert "if (j.total === 0) return" in TEMPLATE and "if (listed > 0) return" in TEMPLATE
    # The mutation hint creates the folder before copying into it.
    assert TEMPLATE.index("'mkdir -p results/tests/mutation'") < TEMPLATE.index(
        "'cp mutants/mutmut-cicd-stats.json"
    )

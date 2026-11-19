"""Tests for scripts/build_dashboard.py (standard library + pytest only).

The builder is a script, not a package module, so it is loaded by path.
Every test works in pytest's tmp_path; nothing is written into the repo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
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
    ],
)
def test_gate_state_derivation(states, drop, expected):
    state, reason = bd.derive_state(gates_from_states(states, drop))
    assert state == expected
    if expected == bd.INCOMPLETE:
        for key in drop:
            assert f"missing: {key}" in reason


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
    evil = '</script><img src=x onerror="alert(1)"><!--   &amp;'
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

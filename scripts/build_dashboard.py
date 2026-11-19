#!/usr/bin/env python3
"""Build the Osprey Strategy Lab results dashboard.

Reads result files from a checkout of this repo and writes one self-contained
HTML page (no network, no CDN, works from file://). Standard library only.

    python3 scripts/build_dashboard.py                 # read the repo root (cwd), write dashboard/index.html
    python3 scripts/build_dashboard.py --root PATH     # read another checkout
    python3 scripts/build_dashboard.py --out PATH      # write elsewhere (default: <root>/dashboard/index.html)
    python3 scripts/build_dashboard.py --json PATH     # also write the collected data as JSON
    python3 scripts/build_dashboard.py --sample --out /tmp/sample.html   # synthetic preview

Every input is optional. A missing input renders as an empty state with a hint
on how to produce it; a file that cannot be read or has an unexpected shape
becomes an entry in the page's warnings list. Nothing here raises on bad input.

The builder never re-judges a number. Audit thresholds and pass flags are shown
as the auditor wrote them; the only thing derived is each audit's overall state,
from the gates' pass flags (a missing gate counts as not passed).

Input reference and the audit JSON schema: HOWTO.md#dashboard.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DASHBOARD_SCHEMA = "osprey.dashboard/1"
AUDIT_SCHEMA = "osprey.audit/1"
TITLE = "Osprey Strategy Lab - results dashboard"
SAMPLE_BANNER = "SAMPLE DATA - not real results"
SAMPLE_MARKER = ".osprey-dashboard-sample"  # file at the root of a --sample tree
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "template.html"
DATA_PLACEHOLDER = "__DASHBOARD_DATA__"
TITLE_PLACEHOLDER = "__DASHBOARD_TITLE__"
UTC = dt.timezone.utc  # noqa: UP017 - datetime.UTC needs Python 3.11; this script supports 3.10

STATUS_VALUES = ("not_started", "in_progress", "done", "blocked")
VERDICTS = ("PASS", "FAIL", "INCOMPLETE")

READY = "READY FOR PAPER"
AWAITING = "AWAITING FINAL TEST"
INCOMPLETE = "INCOMPLETE"
FAIL = "FAIL"

# (key, display label, short label, default rule as written in AGENTS.md)
GATES = (
    ("wf_oos_sharpe", "Walk-forward OOS Sharpe after costs", "OOS Sharpe", ">= 1.0"),
    ("wf_oos_sharpe_2x_costs", "Same, costs doubled", "2x costs", "> 0.5"),
    ("dsr", "Deflated Sharpe Ratio", "DSR", ">= 0.95"),
    ("pbo", "Probability of Backtest Overfitting", "PBO", "<= 0.25"),
    ("plateau_retention", "Parameter plateau (+/-20% keeps Sharpe)", "Plateau", "Keeps >= 70% of the Sharpe"),
    ("mc_p95_max_drawdown", "Monte Carlo p95 max drawdown", "MC p95 DD", "Within the risk level's budget"),
    (
        "beats_benchmarks",
        "Beats benchmarks",
        "Benchmarks",
        "Better risk-adjusted return than buy-and-hold BTC and 50/50 rebalance over the walk-forward",
    ),
    (
        "regime_max_profit_share",
        "No single regime makes most of the profit",
        "Regimes",
        "No single regime (bull, bear, sideways) produces most of the profit",
    ),
    (
        "final_test",
        "Final test window (run once)",
        "Final test",
        "Sharpe within a reasonable distance of walk-forward; no new failure modes",
    ),
)
GATE_KEYS = tuple(g[0] for g in GATES)

# (area, code mutated, target share of non-equivalent mutants killed) from TESTING.md 5.3/5.4
MUTATION_AREAS = (
    ("validation", "lab/validation/", 0.90),
    ("runner", "lab/runner/reference.py", 0.90),
    ("search", "lab/search/", 0.80),
    ("models", "lab/models/", 0.80),
    ("data", "lab/data/loaders.py", 0.80),
)
MUTATION_KEYS = ("killed", "survived", "timeout", "suspicious", "no_tests", "skipped", "total", "equivalent")

STAGES = (
    ("planned", "Planned"),
    ("built", "Built"),
    ("audited", "Audited"),
    ("ready", "Ready for paper"),
    ("paper", "Paper"),
    ("exported", "Exported"),
)

# Equity series drawn in this order, so a series keeps its colour slot.
EQUITY_ORDER = ("strategy", "buy_hold_btc", "rebalance_50_50")
EQUITY_MAX_SERIES = 8
EQUITY_MAX_POINTS = 2500

NOT_STRATEGY_REPORT_DIRS = {"demo", "data"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT = 2000


# --------------------------------------------------------------------------
# Warnings and small value helpers
# --------------------------------------------------------------------------


class Warnings:
    """Collects every problem the builder hits; they are shown on the page."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, source: str, message: str, level: str = "warning") -> None:
        self.items.append({"source": source, "message": message, "level": level})


def num(value):
    """A finite float, or None for anything else (bools, strings, NaN, Infinity)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def count(value):
    """A non-negative whole number, or None."""
    value = num(value)
    if value is None or value < 0 or value != int(value):
        return None
    return int(value)


def text(value, limit: int = MAX_TEXT):
    """A display string for a scalar, or None. Containers are not text."""
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        s = str(value)
    except ValueError:  # an int too long to convert
        return "(number too long to show)"
    return s if len(s) <= limit else s[: limit - 1] + "\u2026"


def scalar(value):
    """Keep JSON scalars (finite numbers, bools, short strings); drop the rest."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return num(value)
    if isinstance(value, str):
        return text(value, 200)
    return None


def clean(obj):
    """Recursively replace non-finite floats by None. Returns (value, n_replaced)."""
    if isinstance(obj, float):
        return (obj, 0) if math.isfinite(obj) else (None, 1)
    if isinstance(obj, dict):
        out, bad = {}, 0
        for k, v in obj.items():
            out[str(k)], b = clean(v)
            bad += b
        return out, bad
    if isinstance(obj, (list, tuple)):
        out, bad = [], 0
        for v in obj:
            v, b = clean(v)
            out.append(v)
            bad += b
        return out, bad
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj, 0
    return str(obj), 0


def utc_iso(timestamp: float):
    try:
        return dt.datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def mtime(path: Path):
    try:
        return utc_iso(path.stat().st_mtime)
    except OSError:
        return None


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def valid_date(s) -> bool:
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------
# File readers
# --------------------------------------------------------------------------


def read_text(path: Path, source: str, w: Warnings):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        w.add(source, "file is not valid UTF-8; skipped")
    except OSError as exc:
        w.add(source, f"could not read file ({exc.strerror or type(exc).__name__}); skipped")
    return None


def read_json(path: Path, source: str, w: Warnings):
    """Parsed JSON with NaN/Infinity replaced by None, or None after a warning."""
    raw = read_text(path, source, w)
    if raw is None:
        return None
    if not raw.strip():
        w.add(source, "file is empty; skipped")
        return None
    try:
        obj, bad = clean(json.loads(raw))
    except json.JSONDecodeError as exc:
        w.add(source, f"invalid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}); skipped")
        return None
    except ValueError as exc:  # e.g. an integer longer than Python's 4300-digit limit
        w.add(source, f"could not parse JSON ({text(str(exc), 200)}); skipped")
        return None
    except RecursionError:
        w.add(source, "JSON is nested too deeply; skipped")
        return None
    if bad:
        w.add(source, f"{bad} non-finite number(s) (NaN or Infinity) shown as empty")
    return obj


def read_json_object(path: Path, source: str, w: Warnings):
    obj = read_json(path, source, w)
    if obj is not None and not isinstance(obj, dict):
        w.add(source, f"expected a JSON object, found {type(obj).__name__}; skipped")
        return None
    return obj


# --------------------------------------------------------------------------
# Markdown helpers (AGENTS.md, TESTING.md)
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def md_lines(markdown: str):
    """Yield (line, in_fence). Headings and tables inside code fences are ignored."""
    in_fence = False
    for line in markdown.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            yield line, True
            continue
        yield line, in_fence


def md_section(markdown: str, title_pattern: str, level: int):
    """Body lines of the first heading at `level` matching the pattern, up to the
    next heading at the same or a higher level. None when absent."""
    body = None
    for line, fenced in md_lines(markdown):
        m = None if fenced else HEADING_RE.match(line)
        if m:
            lvl = len(m.group(1))
            if body is not None and lvl <= level:
                break
            if body is None and lvl == level and re.search(title_pattern, m.group(2), re.I):
                body = []
                continue
        if body is not None:
            body.append((line, fenced))
    return body


def md_plain(s: str) -> str:
    """Inline markdown to plain text: links, code spans, bold and italics."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = s.replace("`", "").replace("**", "")
    s = re.sub(r"(?<![\w*])\*(\S(?:[^*]*?\S)?)\*(?![\w*])", r"\1", s)
    s = s.replace("\\|", "|")
    return " ".join(s.split())


def md_split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [md_plain(cell) for cell in re.split(r"(?<!\\)\|", s)]


def md_first_table(body):
    """(header, rows) of the first pipe table in a section body, or None."""
    if not body:
        return None
    block = []
    for line, fenced in body:
        if not fenced and line.strip().startswith("|"):
            block.append(line)
        elif block:
            break
    if len(block) < 2 or not TABLE_SEP_RE.match(block[1]):
        return None
    return md_split_row(block[0]), [md_split_row(line) for line in block[2:]]


def column(header: list[str], prefix: str, fallback: int) -> int:
    for i, name in enumerate(header):
        if name.strip().lower().startswith(prefix):
            return i
    return fallback


def cell(row: list[str], i: int) -> str:
    return row[i] if 0 <= i < len(row) else ""


# --------------------------------------------------------------------------
# Collectors, one per input
# --------------------------------------------------------------------------


def collect_agents(root: Path, w: Warnings) -> dict:
    """Milestones, validation gates and launch strategies from AGENTS.md."""
    out = {"present": False, "milestones": [], "gates": [], "strategies": []}
    path = root / "AGENTS.md"
    if not path.is_file():
        return out
    markdown = read_text(path, "AGENTS.md", w)
    if markdown is None:
        return out
    out["present"] = True

    table = md_first_table(md_section(markdown, r"^milestones\b", 2))
    if table is None:
        w.add("AGENTS.md", "no table under '## Milestones'; milestones come from dashboard/status.json only")
    else:
        header, rows = table
        c_id, c_name, c_done = (
            column(header, "#", 0),
            column(header, "milestone", 1),
            column(header, "done", 2),
        )
        for row in rows:
            mid = cell(row, c_id).strip()
            if not re.fullmatch(r"\d+", mid):
                continue
            out["milestones"].append({"id": mid, "name": cell(row, c_name), "done_when": cell(row, c_done)})

    table = md_first_table(md_section(markdown, r"^validation gates\b", 2))
    if table is None:
        w.add("AGENTS.md", "no table under '## Validation gates'; using the built-in gate list")
    else:
        header, rows = table
        c_gate, c_default = column(header, "gate", 0), column(header, "default", 1)
        out["gates"] = [{"gate": cell(r, c_gate), "default": cell(r, c_default)} for r in rows if any(r)]

    table = md_first_table(md_section(markdown, r"^strategies to build first\b", 2))
    if table is None:
        w.add("AGENTS.md", "no table under '## Strategies to build first'")
    else:
        header, rows = table
        c_name, c_risk = column(header, "strategy", 0), column(header, "risk", 1)
        c_idea, c_free = column(header, "idea", 2), column(header, "free param", 3)
        for row in rows:
            name = cell(row, c_name).strip()
            if name:
                out["strategies"].append(
                    {
                        "name": name,
                        "risk_level": cell(row, c_risk),
                        "idea": cell(row, c_idea),
                        "free_params": cell(row, c_free),
                    }
                )
    return out


def collect_testing_md(root: Path, w: Warnings) -> dict:
    """Definition-of-done checkboxes, bug-log size and 5.N open work from TESTING.md."""
    out = {"present": False, "dod": [], "dod_found": False, "bug_count": None, "open_work": []}
    path = root / "TESTING.md"
    if not path.is_file():
        return out
    markdown = read_text(path, "TESTING.md", w)
    if markdown is None:
        return out
    out["present"] = True

    body = md_section(markdown, r"definition of done", 2)
    if body is None:
        w.add("TESTING.md", "no '## ... Definition of done' section")
    else:
        out["dod_found"] = True
        for line, fenced in body:
            m = None if fenced else CHECKBOX_RE.match(line)
            if m:
                out["dod"].append({"text": md_plain(m.group(2)), "done": m.group(1) in "xX"})

    table = md_first_table(md_section(markdown, r"bug log", 2))
    if table is None:
        w.add("TESTING.md", "no numbered table under '## ... Bug log'")
    else:
        out["bug_count"] = sum(1 for row in table[1] if re.fullmatch(r"\d+", cell(row, 0).strip()))

    body = md_section(markdown, r"^5\.?\s|open work", 2)
    if body is None:
        w.add("TESTING.md", "no '## 5. Open work' section")
    else:
        for line, fenced in body:
            m = None if fenced else re.match(r"^###\s+(5\.\d+)\s+(.*?)\s*$", line)
            if m:
                out["open_work"].append({"id": m.group(1), "title": md_plain(m.group(2))})
    return out


def normalise_status_value(value, source: str, where: str, w: Warnings):
    if value is None:
        return None
    if not isinstance(value, str):
        w.add(source, f"{where}: status should be a string, found {type(value).__name__}")
        return None
    if value not in STATUS_VALUES:
        w.add(
            source,
            f"{where}: unknown status '{text(value, 60)}' "
            f"(expected one of {', '.join(STATUS_VALUES)}); shown as given",
        )
    return text(value, 60)


def collect_status(root: Path, w: Warnings) -> dict:
    """The hand-edited dashboard/status.json."""
    src = "dashboard/status.json"
    out = {
        "present": False,
        "updated": None,
        "note": None,
        "milestones": {},
        "open_work": {},
        "strategies": {},
    }
    path = root / "dashboard" / "status.json"
    if not path.is_file():
        return out
    obj = read_json_object(path, src, w)
    if obj is None:
        return out
    out["present"] = True
    out["updated"] = text(obj.get("updated"), 40)
    out["note"] = text(obj.get("note"))

    for key, entry in _dict_field(obj, "milestones", src, w).items():
        if isinstance(entry, str):
            entry = {"status": entry}
        if not isinstance(entry, dict):
            w.add(src, f"milestones.{key}: expected an object with status and note")
            continue
        out["milestones"][key] = {
            "status": normalise_status_value(entry.get("status"), src, f"milestones.{key}", w),
            "note": text(entry.get("note")),
        }

    for key, entry in _dict_field(obj, "open_work", src, w).items():
        if isinstance(entry, dict):
            status, note = entry.get("status"), text(entry.get("note"))
        else:
            status, note = entry, None
        out["open_work"][key] = {
            "status": normalise_status_value(status, src, f"open_work.{key}", w),
            "note": note,
        }

    for name, entry in _dict_field(obj, "strategies", src, w).items():
        paper = entry.get("paper") if isinstance(entry, dict) else None
        if not isinstance(paper, dict):
            w.add(src, f'strategies.{name}: expected {{"paper": {{"status": ...}}}}')
            continue
        out["strategies"][name] = {
            "paper": {
                "status": normalise_status_value(paper.get("status"), src, f"strategies.{name}.paper", w),
                "started": text(paper.get("started"), 40),
                "note": text(paper.get("note")),
            }
        }
    return out


def _dict_field(obj: dict, key: str, source: str, w: Warnings) -> dict:
    value = obj.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        w.add(source, f"'{key}' should be an object, found {type(value).__name__}; ignored")
        return {}
    return value


def _xml_int(element, name: str):
    try:
        return int(float(element.get(name, "0") or 0))
    except (TypeError, ValueError):
        return None


def collect_junit(root: Path, w: Warnings):
    """Counts from results/tests/junit.xml (pytest --junitxml)."""
    src = "results/tests/junit.xml"
    path = root / src
    if not path.is_file():
        return None
    try:
        tree_root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        w.add(src, f"invalid XML ({exc}); skipped")
        return None
    except (OSError, RecursionError) as exc:
        w.add(src, f"could not read file ({type(exc).__name__}); skipped")
        return None
    suites = [tree_root] if tree_root.tag == "testsuite" else tree_root.findall("testsuite")
    if not suites:
        w.add(src, f"no <testsuite> element (root is <{text(tree_root.tag, 40)}>); skipped")
        return None
    totals = {"total": 0, "failed": 0, "errors": 0, "skipped": 0}
    attr = {"total": "tests", "failed": "failures", "errors": "errors", "skipped": "skipped"}
    time_s, timestamps = 0.0, []
    for suite in suites:
        for key, name in attr.items():
            value = _xml_int(suite, name)
            if value is None or value < 0:
                w.add(src, f"attribute {name}='{text(suite.get(name), 40)}' is not a count; read as 0")
                value = 0
            totals[key] += value
        try:
            time_s += float(suite.get("time", "0") or 0)
        except ValueError:
            pass
        if suite.get("timestamp"):
            timestamps.append(text(suite.get("timestamp"), 40))
    failing = []
    for case in tree_root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            name = "::".join(p for p in (case.get("classname"), case.get("name")) if p)
            failing.append(text(name, 300))
    passed = totals["total"] - totals["failed"] - totals["errors"] - totals["skipped"]
    if passed < 0:
        w.add(src, "failures + errors + skipped exceed the number of tests")
        passed = 0
    return {
        "path": src,
        **totals,
        "passed": passed,
        "time_s": round(time_s, 2) if math.isfinite(time_s) else None,
        "timestamp": max(timestamps) if timestamps else None,
        "modified": mtime(path),
        "failing_tests": failing[:20],
        "failing_more": max(0, len(failing) - 20),
    }


def collect_coverage(root: Path, w: Warnings):
    """Totals and the five least-covered files from coverage.py's JSON report."""
    src = "results/tests/coverage.json"
    path = root / src
    if not path.is_file():
        return None
    obj = read_json_object(path, src, w)
    if obj is None:
        return None
    totals = obj.get("totals")
    if not isinstance(totals, dict) or num(totals.get("percent_covered")) is None:
        w.add(src, "no numeric totals.percent_covered (expected coverage.py JSON format); skipped")
        return None
    meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
    branch = meta.get("branch_coverage")
    if branch is False:
        w.add(src, "coverage was measured without --cov-branch; the percentage covers lines only")
    n_branches, covered_branches = count(totals.get("num_branches")), count(totals.get("covered_branches"))
    lowest = []
    files = obj.get("files")
    if isinstance(files, dict):
        for name, entry in files.items():
            summary = entry.get("summary") if isinstance(entry, dict) else None
            pct = num(summary.get("percent_covered")) if isinstance(summary, dict) else None
            if pct is not None:
                lowest.append({"file": text(name, 300), "percent": pct})
        lowest.sort(key=lambda f: (f["percent"], f["file"]))
    return {
        "path": src,
        "percent": num(totals.get("percent_covered")),
        "branch_measured": branch if isinstance(branch, bool) else None,
        "branches_covered": covered_branches,
        "branches_total": n_branches,
        "timestamp": text(meta.get("timestamp"), 40),
        "modified": mtime(path),
        "lowest_files": lowest[:5],
        "n_files": len(lowest),
    }


def mutation_scores(counts: dict):
    """(score, score_excluding_equivalent) as defined in HOWTO.md#dashboard.

    score = (killed + timeout) / (killed + timeout + survived)
    score_excluding_equivalent = (killed + timeout) / (killed + timeout + survived - equivalent)
    """
    killed = counts.get("killed") or 0
    timeout = counts.get("timeout") or 0
    survived = counts.get("survived") or 0
    equivalent = counts.get("equivalent") or 0
    caught = killed + timeout
    denom = caught + survived
    score = caught / denom if denom > 0 else None
    denom_ex = denom - min(equivalent, survived)
    score_ex = caught / denom_ex if denom_ex > 0 else None
    return score, score_ex


def collect_mutation(root: Path, w: Warnings) -> list:
    """One entry per area from results/tests/mutation/<area>.json."""
    folder = root / "results" / "tests" / "mutation"
    areas = []
    for area, code_path, target in MUTATION_AREAS:
        src = f"results/tests/mutation/{area}.json"
        entry = {"area": area, "code_path": code_path, "target": target, "path": src, "present": False}
        areas.append(entry)
        path = folder / f"{area}.json"
        if not path.is_file():
            continue
        obj = read_json_object(path, src, w)
        if obj is None:
            continue
        counts = {}
        for key in MUTATION_KEYS:
            if key in obj and obj[key] is not None:
                value = count(obj[key])
                if value is None:
                    w.add(src, f"'{key}' is not a whole number >= 0; ignored")
                counts[key] = value
        if counts.get("killed") is None and counts.get("survived") is None:
            w.add(src, "no 'killed' or 'survived' counts (expected mutmut-cicd-stats.json); skipped")
            continue
        if (counts.get("equivalent") or 0) > (counts.get("survived") or 0):
            w.add(src, "'equivalent' is larger than 'survived'; capped at 'survived'")
        score, score_ex = mutation_scores(counts)
        entry.update(
            {
                "present": True,
                "counts": counts,
                "score": score,
                "score_excluding_equivalent": score_ex,
                "meets_target": None if score_ex is None else score_ex >= target,
                "modified": mtime(path),
            }
        )
    if folder.is_dir():
        known = {a[0] for a in MUTATION_AREAS}
        for path in sorted(folder.glob("*.json")):
            if path.stem not in known:
                w.add(
                    rel(root, path),
                    f"unknown mutation area '{path.stem}' (expected {', '.join(sorted(known))}); ignored",
                )
    return areas


def collect_snapshot(root: Path, w: Warnings):
    """data/catalog/SNAPSHOT.json, read leniently (its format is not fixed yet)."""
    src = "data/catalog/SNAPSHOT.json"
    path = root / src
    if not path.is_file():
        return None
    obj = read_json(path, src, w)
    if obj is None:
        return None
    if not isinstance(obj, dict):
        w.add(src, f"expected a JSON object, found {type(obj).__name__}")
        return {
            "path": src,
            "id": None,
            "recognised": False,
            "top_level_keys": [],
            "series": [],
            "sources": [],
        }
    snap_id = text(obj.get("snapshot_id"), 200) or text(obj.get("id"), 200)
    sources = obj.get("sources")
    if isinstance(sources, dict):
        source_names = [text(k, 100) for k in sources]
    elif isinstance(sources, list):
        source_names = []
        for s in sources:
            if isinstance(s, dict):
                s = s.get("name") or s.get("source") or s.get("id")
            if text(s, 100):
                source_names.append(text(s, 100))
    else:
        source_names = []
    series = []
    raw_series = obj.get("series")
    if isinstance(raw_series, list):
        for item in raw_series:
            if not isinstance(item, dict):
                continue
            series.append(
                {
                    k: scalar(item.get(k))
                    for k in ("instrument", "source", "bar", "start", "end", "rows", "gaps")
                }
            )
    elif raw_series is not None:
        w.add(src, "'series' should be a list; not shown")
    recognised = bool(snap_id or source_names or series or obj.get("created"))
    if not recognised:
        w.add(
            src, "unrecognised shape (no snapshot_id/id, sources, series or created); showing top-level keys"
        )
    return {
        "path": src,
        "id": snap_id,
        "created": text(obj.get("created"), 60),
        "sources": source_names[:50],
        "series": series[:500],
        "recognised": recognised,
        "top_level_keys": [text(k, 100) for k in list(obj)[:50]],
        "modified": mtime(path),
    }


def list_files(root: Path, folder: Path, pattern: str) -> list:
    if not folder.is_dir():
        return []
    return [{"path": rel(root, p), "modified": mtime(p)} for p in sorted(folder.glob(pattern)) if p.is_file()]


def collect_studies(root: Path, w: Warnings) -> list:
    """Each folder under results/ except tests/: a local, git-ignored search run."""
    results = root / "results"
    if not results.is_dir():
        return []
    studies = []
    for folder in sorted(p for p in results.iterdir() if p.is_dir() and p.name != "tests"):
        parquet, journal, newest = 0, False, None
        try:
            for dirpath, _dirs, files in os.walk(folder):
                for name in files:
                    lower = name.lower()
                    if lower.endswith(".parquet"):
                        parquet += 1
                    if lower.endswith((".log", ".journal")) or lower.startswith("journal"):
                        journal = True
                    try:
                        t = os.stat(os.path.join(dirpath, name)).st_mtime
                    except OSError:
                        continue
                    newest = t if newest is None or t > newest else newest
        except OSError as exc:
            w.add(rel(root, folder), f"could not list folder ({exc.strerror or type(exc).__name__})")
        studies.append(
            {
                "name": folder.name,
                "path": rel(root, folder),
                "parquet_files": parquet,
                "journal": journal,
                "modified": utc_iso(newest) if newest is not None else mtime(folder),
            }
        )
    return studies


def collect_exports(root: Path, w: Warnings) -> dict:
    """exports/<name>/config.yaml: listed only, never opened (no secrets are read)."""
    folder = root / "exports"
    out = {}
    if not folder.is_dir():
        return out
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        config = sub / "config.yaml"
        if config.is_file():
            out[sub.name] = {"path": rel(root, config), "modified": mtime(config)}
        else:
            w.add(rel(root, sub), "export folder has no config.yaml")
    return out


def collect_strategy_dirs(root: Path) -> dict:
    folder = root / "strategies"
    out = {}
    if not folder.is_dir():
        return out
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        out[sub.name] = {
            "path": rel(root, sub),
            "files": {name: (sub / name).is_file() for name in ("strategy.py", "params.yaml", "README.md")},
        }
    return out


def collect_reports(root: Path) -> list:
    """Every reports/**/*.md, newest first (date from the file name, else mtime)."""
    folder = root / "reports"
    if not folder.is_dir():
        return []
    items = []
    for path in folder.rglob("*.md"):
        if not path.is_file():
            continue
        parts = path.relative_to(folder).parts
        stem_date = path.stem[:10] if valid_date(path.stem[:10]) else None
        modified = mtime(path)
        kind = "other"
        if len(parts) > 1:
            kind = parts[0] if parts[0] in NOT_STRATEGY_REPORT_DIRS else "audit"
        items.append(
            {
                "path": rel(root, path),
                "date": stem_date or (modified or "")[:10] or None,
                "kind": kind,
                "group": parts[0] if len(parts) > 1 else "",
            }
        )
    items.sort(key=lambda r: (r["date"] or "", r["path"]), reverse=True)
    return items


def collect_git(root: Path) -> dict:
    info = {"commit": "unknown", "branch": "unknown"}
    if not (root / ".git").exists():
        return info

    def git(*args):
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        out = done.stdout.strip()
        return out if done.returncode == 0 and out else None

    info["commit"] = git("rev-parse", "--short", "HEAD") or "unknown"
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        branch = git("symbolic-ref", "--short", "-q", "HEAD") or ("detached" if branch == "HEAD" else None)
    if not branch:
        try:
            head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref: refs/heads/"):
                branch = head[len("ref: refs/heads/") :]
        except OSError:
            pass
    info["branch"] = text(branch, 200) or "unknown"
    info["commit"] = text(info["commit"], 64)
    return info


# --------------------------------------------------------------------------
# Audits
# --------------------------------------------------------------------------


def normalise_gate(key: str, raw, source: str, w: Warnings) -> dict:
    gate = {
        "key": key,
        "present": False,
        "value": None,
        "threshold": None,
        "op": None,
        "pass": None,
        "note": None,
        "state": "missing",
    }
    if raw is None:
        return gate
    if not isinstance(raw, dict):
        w.add(source, f"gate '{key}' should be an object; counted as missing")
        return gate
    gate["present"] = True
    value = raw.get("value")
    gate["value"] = scalar(value)
    if gate["value"] is None and value is not None:
        w.add(source, f"gate '{key}': value of type {type(value).__name__} not shown")
    gate["threshold"] = scalar(raw.get("threshold"))
    gate["op"] = text(raw.get("op"), 10)
    gate["note"] = text(raw.get("note"), 300)
    flag = raw.get("pass")
    if flag is None or isinstance(flag, bool):
        gate["pass"] = flag
    else:
        w.add(
            source,
            f"gate '{key}': pass should be true, false or null, found '{text(flag, 40)}'; treated as pending",
        )
    gate["state"] = {True: "pass", False: "fail", None: "pending"}[gate["pass"]]
    return gate


def derive_state(gates: dict) -> tuple[str, str]:
    """Overall state from the nine gates' pass flags. Returns (state, reason).

    any gate fail                        -> FAIL
    all nine pass                        -> READY FOR PAPER
    eight pass and final_test pending    -> AWAITING FINAL TEST
    anything else (missing or pending)   -> INCOMPLETE   (a missing gate is never a pass)
    """
    states = {k: (gates.get(k) or {}).get("state", "missing") for k in GATE_KEYS}
    failed = [k for k in GATE_KEYS if states[k] == "fail"]
    missing = [k for k in GATE_KEYS if states[k] == "missing"]
    pending = [k for k in GATE_KEYS if states[k] == "pending"]
    if failed:
        return FAIL, "failed: " + ", ".join(failed)
    if not missing and not pending:
        return READY, "all nine gates pass"
    if not missing and pending == ["final_test"]:
        return AWAITING, "eight gates pass; final test window not run yet"
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if pending:
        parts.append("pending: " + ", ".join(pending))
    return INCOMPLETE, "; ".join(parts)


def verdict_check(verdict, state: str, reason: str, source: str, w: Warnings):
    """Compare the file's verdict with the derived state. Returns an integrity note or None."""
    expected = {READY: "PASS", FAIL: "FAIL", AWAITING: "INCOMPLETE", INCOMPLETE: "INCOMPLETE"}[state]
    if verdict is None:
        w.add(source, "no 'verdict' field")
        return None
    if verdict not in VERDICTS:
        w.add(source, f"unknown verdict '{verdict}' (expected PASS, FAIL or INCOMPLETE)")
        return None
    if verdict == expected:
        return None
    if verdict == "PASS":
        message = (
            f"Audit file says PASS but its gate flags give {state} ({reason}). "
            "Do not treat this strategy as ready for paper until the audit is corrected."
        )
        w.add(source, message, level="integrity")
        return {"level": "integrity", "message": message}
    message = f"Audit file says {verdict} but its gate flags give {state} ({reason})."
    w.add(source, message)
    return {"level": "warning", "message": message}


def normalise_equity(raw, source: str, w: Warnings):
    """Equity curves normalised to 1.0 at their first value. Bad series are skipped."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        w.add(source, "equity should be an object with 'dates' and 'series'; not drawn")
        return None
    dates, series = raw.get("dates"), raw.get("series")
    if not isinstance(dates, list) or not dates:
        w.add(source, "equity.dates should be a non-empty list; chart not drawn")
        return None
    if not isinstance(series, dict) or not series:
        w.add(source, "equity.series should be a non-empty object; chart not drawn")
        return None
    dates = [text(d, 40) or "" for d in dates]
    names = [n for n in EQUITY_ORDER if n in series] + [n for n in series if n not in EQUITY_ORDER]
    out = []
    for name in names:
        values = series[name]
        if not isinstance(values, list):
            w.add(source, f"equity series '{name}' is not a list; skipped")
            continue
        if len(values) != len(dates):
            w.add(source, f"equity series '{name}' has {len(values)} values for {len(dates)} dates; skipped")
            continue
        nums = [num(v) for v in values]
        bad = sum(1 for v, n in zip(values, nums, strict=True) if n is None and v is not None)
        if bad:
            w.add(source, f"equity series '{name}': {bad} non-numeric value(s) shown as gaps")
        base = next((v for v in nums if v is not None), None)
        if base is None or base <= 0:
            w.add(
                source,
                f"equity series '{name}' does not start with a positive number; "
                "cannot normalise to 1.0, skipped",
            )
            continue
        normalised = [None if v is None else round(v / base, 8) for v in nums]
        nonpositive = sum(1 for v in normalised if v is not None and v <= 0)
        if nonpositive:
            w.add(
                source,
                f"equity series '{name}': {nonpositive} value(s) <= 0 cannot be drawn on the log scale",
            )
        if len(out) == EQUITY_MAX_SERIES:
            w.add(source, f"equity has more than {EQUITY_MAX_SERIES} series; '{name}' and later not drawn")
            break
        out.append({"name": text(name, 100), "values": normalised, "nonpositive": nonpositive})
    if not out:
        return None
    step = 1
    if len(dates) > EQUITY_MAX_POINTS:
        step = math.ceil(len(dates) / EQUITY_MAX_POINTS)
        keep = list(range(0, len(dates), step))
        if keep[-1] != len(dates) - 1:
            keep.append(len(dates) - 1)
        dates = [dates[i] for i in keep]
        for s in out:
            s["values"] = [s["values"][i] for i in keep]
    return {"dates": dates, "series": out, "thinned_every": step}


def _scalar_map(raw, source: str, field: str, w: Warnings) -> list:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        w.add(source, f"'{field}' should be an object; not shown")
        return []
    return [[text(k, 100), scalar(v)] for k, v in raw.items() if not isinstance(v, (dict, list))]


def _report_link(raw, root: Path, source: str, w: Warnings):
    """report_md is free text in the file: only link it if it is a plain relative path that exists."""
    shown = text(raw, 300)
    if shown is None:
        return None
    safe = (
        not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", shown)
        and not shown.startswith(("/", "\\"))
        and ".." not in Path(shown).parts
        and "\\" not in shown
    )
    exists = False
    if safe:
        try:
            exists = (root / shown).is_file()
        except (OSError, ValueError):
            exists = False
    if not exists:
        w.add(source, f"report_md '{shown}' is not a file in this repo; shown without a link")
    return {"text": shown, "path": shown if (safe and exists) else None}


def normalise_audit(obj: dict, strategy: str, date: str, root: Path, path: Path, w: Warnings) -> dict:
    source = rel(root, path)
    if obj.get("strategy") is not None and obj.get("strategy") != strategy:
        w.add(
            source,
            f"'strategy' is '{text(obj.get('strategy'), 100)}' but the file is under "
            f"reports/{strategy}/; filed under {strategy}",
        )
    if obj.get("date") is not None and obj.get("date") != date:
        w.add(
            source,
            f"'date' is '{text(obj.get('date'), 40)}' but the file name says {date}; "
            "the file name is used for ordering",
        )
    raw_gates = obj.get("gates")
    if not isinstance(raw_gates, dict):
        w.add(source, "'gates' should be an object keyed by gate name; every gate counted as missing")
        raw_gates = {}
    unknown = [k for k in raw_gates if k not in GATE_KEYS]
    if unknown:
        w.add(source, "unknown gate key(s) ignored: " + ", ".join(text(k, 60) for k in unknown))
    gates = {k: normalise_gate(k, raw_gates.get(k), source, w) for k in GATE_KEYS}
    state, reason = derive_state(gates)
    verdict = obj.get("verdict")
    verdict = (
        verdict.strip().upper() if isinstance(verdict, str) else (None if verdict is None else text(verdict))
    )
    integrity = verdict_check(verdict, state, reason, source, w)

    window = obj.get("window") if isinstance(obj.get("window"), dict) else None
    md_sibling = path.with_suffix(".md")
    if not md_sibling.is_file():
        w.add(source, f"no matching audit report {rel(root, md_sibling)}")
    test_window = obj.get("test_window_opened")
    counts = {
        s: sum(1 for g in gates.values() if g["state"] == s) for s in ("pass", "fail", "pending", "missing")
    }
    return {
        "date": date,
        "path": source,
        "md_path": rel(root, md_sibling) if md_sibling.is_file() else None,
        "report_md": _report_link(obj.get("report_md"), root, source, w),
        "verdict": verdict,
        "state": state,
        "state_reason": reason,
        "integrity": integrity,
        "risk_level": text(obj.get("risk_level"), 60),
        "git_commit": text(obj.get("git_commit"), 64),
        "data_snapshot": text(obj.get("data_snapshot"), 200),
        "seed": scalar(obj.get("seed")),
        "n_trials": scalar(obj.get("n_trials")),
        "effective_trials": scalar(obj.get("effective_trials")),
        "window": {"start": text(window.get("start"), 40), "end": text(window.get("end"), 40)}
        if window
        else None,
        "test_window_opened": test_window if isinstance(test_window, bool) else None,
        "gates": [gates[k] for k in GATE_KEYS],
        "gate_counts": counts,
        "metrics": _scalar_map(obj.get("metrics"), source, "metrics", w),
        "benchmarks": _benchmarks(obj.get("benchmarks"), source, w),
        "equity": normalise_equity(obj.get("equity"), source, w),
    }


def _benchmarks(raw, source: str, w: Warnings) -> list:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        w.add(source, "'benchmarks' should be an object; not shown")
        return []
    out = []
    for name, values in raw.items():
        if isinstance(values, dict):
            out.append(
                {"name": text(name, 100), "values": _scalar_map(values, source, f"benchmarks.{name}", w)}
            )
        else:
            w.add(source, f"benchmarks.{text(name, 60)} should be an object; not shown")
    return out


def collect_audits(root: Path, w: Warnings) -> dict:
    """reports/<strategy>/<YYYY-MM-DD>.json sidecars, oldest first per strategy."""
    folder = root / "reports"
    audits: dict[str, list] = {}
    if not folder.is_dir():
        return audits
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and p.name not in NOT_STRATEGY_REPORT_DIRS):
        for path in sorted(sub.glob("*.json")):
            source = rel(root, path)
            if not valid_date(path.stem):
                w.add(source, "audit file name is not a YYYY-MM-DD date; ignored")
                continue
            obj = read_json_object(path, source, w)
            if obj is None:
                continue
            if obj.get("schema") != AUDIT_SCHEMA:
                w.add(
                    source, f"schema is '{text(obj.get('schema'), 60)}', expected '{AUDIT_SCHEMA}'; skipped"
                )
                continue
            audits.setdefault(sub.name, []).append(normalise_audit(obj, sub.name, path.stem, root, path, w))
    for items in audits.values():
        items.sort(key=lambda a: a["date"])
    return audits


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_milestones(agents: dict, status: dict) -> list:
    rows = [dict(m) for m in agents["milestones"]]
    if not rows:
        rows = [{"id": k, "name": None, "done_when": None} for k in sorted(status["milestones"], key=_id_key)]
    for row in rows:
        entry = status["milestones"].get(row["id"], {})
        row["status"] = entry.get("status")
        row["note"] = entry.get("note")
    return rows


def _id_key(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def build_gate_defs(agents: dict, w: Warnings) -> list:
    rows = agents["gates"]
    use_agents = len(rows) == len(GATES)
    if rows and not use_agents:
        w.add(
            "AGENTS.md",
            f"'## Validation gates' has {len(rows)} rows, expected {len(GATES)}; showing built-in rule text",
        )
    return [
        {
            "key": k,
            "label": label,
            "short": short,
            "rule": rows[i]["default"] if use_agents and rows[i]["default"] else rule,
        }
        for i, (k, label, short, rule) in enumerate(GATES)
    ]


def build_strategies(agents, folders, audits, exports, status, w: Warnings) -> list:
    launch = {s["name"]: s for s in agents["strategies"]}
    names = list(launch)
    for extra in sorted(set(folders) | set(audits) | set(exports)):
        if extra not in launch:
            names.append(extra)
    for name in status["strategies"]:
        if name not in names:
            w.add(
                "dashboard/status.json",
                f"strategies.{name} is not in the AGENTS.md launch table, strategies/, "
                "reports/ or exports/; not shown",
            )
    out = []
    for name in names:
        history = audits.get(name, [])
        latest = history[-1] if history else None
        paper = status["strategies"].get(name, {}).get("paper")
        folder = folders.get(name)
        reached = {
            "planned": True,
            "built": bool(folder and folder["files"]["strategy.py"]),
            "audited": bool(history),
            "ready": bool(latest and latest["state"] == READY),
            "paper": bool(paper and paper["status"] in ("in_progress", "done")),
            "exported": name in exports,
        }
        current = [key for key, _ in STAGES if reached[key]][-1]
        for later, earlier in (("exported", "ready"), ("paper", "ready")):
            if reached[later] and not reached[earlier]:
                w.add(
                    f"strategy {name}",
                    f"stage '{later}' is recorded but the latest audit is not "
                    f"{READY}; check the audit and dashboard/status.json",
                )
        info = launch.get(name, {})
        out.append(
            {
                "name": name,
                "in_launch_table": name in launch,
                "risk_level": info.get("risk_level") or (latest or {}).get("risk_level"),
                "idea": info.get("idea"),
                "free_params": info.get("free_params"),
                "stages": [{"key": k, "label": label, "reached": reached[k]} for k, label in STAGES],
                "stage": current,
                "folder": folder,
                "latest": latest,
                "history": [
                    {"date": a["date"], "verdict": a["verdict"], "state": a["state"], "path": a["path"]}
                    for a in history
                ],
                "paper": paper,
                "export": exports.get(name),
            }
        )
    return out


def build_overview(milestones, strategies, junit, coverage) -> dict:
    return {
        "milestones_done": sum(1 for m in milestones if m["status"] == "done"),
        "milestones_total": len(milestones),
        "strategies_total": len(strategies),
        "strategies_audited": sum(1 for s in strategies if s["latest"]),
        "strategies_ready": sum(1 for s in strategies if s["latest"] and s["latest"]["state"] == READY),
        "tests_passed": junit["passed"] if junit else None,
        "tests_total": junit["total"] if junit else None,
        "tests_failed": (junit["failed"] + junit["errors"]) if junit else None,
        "coverage_percent": coverage["percent"] if coverage else None,
    }


def _safely(w: Warnings, name: str, fn, default):
    """Run one collector; an unexpected exception becomes a warning, not a crash."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the page must render whatever happens
        w.add(
            name,
            f"internal error while reading this input ({type(exc).__name__}: {text(exc, 300)}); "
            "please report it",
        )
        return default


def collect(root) -> dict:
    """Read every input under `root` and return the dashboard data (JSON-safe)."""
    root = Path(root)
    w = Warnings()
    agents = _safely(
        w,
        "AGENTS.md",
        lambda: collect_agents(root, w),
        {"present": False, "milestones": [], "gates": [], "strategies": []},
    )
    testing_md = _safely(
        w,
        "TESTING.md",
        lambda: collect_testing_md(root, w),
        {"present": False, "dod": [], "dod_found": False, "bug_count": None, "open_work": []},
    )
    status = _safely(
        w,
        "dashboard/status.json",
        lambda: collect_status(root, w),
        {
            "present": False,
            "updated": None,
            "note": None,
            "milestones": {},
            "open_work": {},
            "strategies": {},
        },
    )
    junit = _safely(w, "results/tests/junit.xml", lambda: collect_junit(root, w), None)
    coverage = _safely(w, "results/tests/coverage.json", lambda: collect_coverage(root, w), None)
    mutation = _safely(w, "results/tests/mutation", lambda: collect_mutation(root, w), [])
    snapshot = _safely(w, "data/catalog/SNAPSHOT.json", lambda: collect_snapshot(root, w), None)
    quality = _safely(w, "reports/data", lambda: list_files(root, root / "reports" / "data", "*.md"), [])
    studies = _safely(w, "results", lambda: collect_studies(root, w), [])
    exports = _safely(w, "exports", lambda: collect_exports(root, w), {})
    folders = _safely(w, "strategies", lambda: collect_strategy_dirs(root), {})
    audits = _safely(w, "reports", lambda: collect_audits(root, w), {})
    reports = _safely(w, "reports", lambda: collect_reports(root), [])
    git = _safely(w, "git", lambda: collect_git(root), {"commit": "unknown", "branch": "unknown"})

    milestones = build_milestones(agents, status)
    gate_defs = build_gate_defs(agents, w)
    strategies = _safely(
        w, "strategies", lambda: build_strategies(agents, folders, audits, exports, status, w), []
    )
    open_work = [
        dict(item, **status["open_work"].get(item["id"], {"status": None, "note": None}))
        for item in testing_md["open_work"]
    ]
    for key in status["open_work"]:
        if testing_md["present"] and key not in {o["id"] for o in testing_md["open_work"]}:
            w.add(
                "dashboard/status.json", f"open_work.{key} has no matching '### {key}' heading in TESTING.md"
            )

    data = {
        "schema": DASHBOARD_SCHEMA,
        "title": TITLE,
        "sample": (root / SAMPLE_MARKER).is_file(),
        "generated_utc": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "link_root": "..",
        "git": git,
        "inputs": {
            "agents_md": agents["present"],
            "testing_md": testing_md["present"],
            "status_json": status["present"],
        },
        "status": {"present": status["present"], "updated": status["updated"], "note": status["note"]},
        "milestones": milestones,
        "gate_defs": gate_defs,
        "strategies": strategies,
        "testing": {
            "junit": junit,
            "coverage": coverage,
            "mutation": mutation,
            "dod": testing_md["dod"],
            "dod_found": testing_md["dod_found"],
            "bug_count": testing_md["bug_count"],
            "open_work": open_work,
        },
        "data": {"snapshot": snapshot, "quality_reports": quality},
        "studies": studies,
        "reports": reports,
        "exports": [{"name": k, **v} for k, v in exports.items()],
        "overview": build_overview(milestones, strategies, junit, coverage),
    }
    data["warnings"] = w.items
    data["overview"]["warnings"] = len(w.items)
    data["overview"]["integrity_warnings"] = sum(1 for x in w.items if x["level"] == "integrity")
    return clean(data)[0]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def to_script_json(data) -> str:
    """JSON safe to place inside <script type="application/json">.

    <, > and & are escaped so no string can close the script element or open a
    comment; U+2028/2029 are escaped for older JavaScript parsers.
    """
    payload = json.dumps(clean(data)[0], ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def page_title(data: dict) -> str:
    return f"{SAMPLE_BANNER} | {TITLE}" if data.get("sample") else TITLE


def render(data: dict, template: str) -> str:
    """Fill the template's title and data placeholders. Raises ValueError if they are missing."""
    for marker in (TITLE_PLACEHOLDER, DATA_PLACEHOLDER):
        if template.count(marker) != 1:
            raise ValueError(f"template must contain {marker} exactly once")
    head, _, tail = template.partition(DATA_PLACEHOLDER)
    head = head.replace(TITLE_PLACEHOLDER, html.escape(page_title(data)))
    tail = tail.replace(TITLE_PLACEHOLDER, html.escape(page_title(data)))
    return head + to_script_json(data) + tail


def link_root(root: Path, out: Path):
    """Path from the page's folder to the repo root, for relative links (None if impossible)."""
    try:
        return Path(os.path.relpath(root.resolve(), out.resolve().parent)).as_posix()
    except ValueError:
        return None


def summary_line(data: dict, out: Path) -> str:
    o = data["overview"]
    tests = (
        f"tests {o['tests_passed']}/{o['tests_total']} passed"
        if o["tests_total"] is not None
        else "no test run recorded"
    )
    return (
        f"{'SAMPLE ' if data['sample'] else ''}dashboard: {o['strategies_total']} strategies "
        f"({o['strategies_audited']} audited, {o['strategies_ready']} ready for paper), "
        f"milestones {o['milestones_done']}/{o['milestones_total']} done, {tests}, "
        f"{o['warnings']} warning(s) -> {out}"
    )


# --------------------------------------------------------------------------
# --sample: a synthetic repo tree (fixed seed), never written into the repo
# --------------------------------------------------------------------------

SAMPLE_NOTE = "Synthetic file written by scripts/build_dashboard.py --sample. Not a real result."


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, indent=2)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _sample_markdown() -> tuple[str, str]:
    gates = "\n".join(f"| {label} | {rule} |" for _k, label, _s, rule in GATES)
    agents = f"""# AGENTS.md (sample)

{SAMPLE_NOTE}

## Validation gates

| Gate | Default |
|---|---|
{gates}

## Strategies to build first

| Strategy | Risk level | Idea | Free parameters (keep <= 4) |
|---|---|---|---|
| `rebalance-steady` | Steady | Hold BTC, ETH and USDC at target weights | Target weights, drift band, check frequency |
| `dip-buy-balanced` | Balanced | Buy BTC or ETH after a drop of X% over N days | Drop %, lookback, cap, stop % |
| `momentum-bold` | Bold | Hold the top K tokens by trailing return | Lookback, K, rebalance day, cash filter |

## Milestones

| # | Milestone | Done when |
|---|---|---|
| 0 | Starter code verified | Sample: definition of done met |
| 1 | Setup and data | Sample: catalog and SNAPSHOT.json written |
| 2 | Costs and Nautilus runner | Sample: contract suite and parity test pass |
| 3 | Launch strategies | Sample: three strategies backtested |
| 4 | Search and validation on real data | Sample: first audit reports written |
| 5 | Prediction track on real data | Sample: one model-sized variant audited |
"""
    testing = (
        f"""# TESTING.md (sample)

{SAMPLE_NOTE}

## 4. Bug log

| # | Where | Bug | Fix |
|---|---|---|---|
"""
        + "".join(f"| {i} | sample | sample bug {i} | sample fix |\n" for i in range(1, 10))
        + """
## 5. Open work, in order

### 5.1 Verify the refactor that was in progress
### 5.2 Fix the two failures found by the deep profile
### 5.3 Close the mutation-testing gaps in `lab/validation/`
### 5.4 Extend mutation testing to the rest of `lab/`
### 5.5 Rerun the demo and update the docs
### 5.6 Turn the backtester tests into a contract every runner must pass
### 5.7 Raise the coverage floor

## 8. Definition of done (this testing work)

- [ ] Full, deep and slow tiers pass
- [x] Bug log updated, including 5.2A and 5.2B
- [ ] Mutation targets met for every area in 5.4
- [ ] Branch coverage 100% with `fail_under = 100`
- [ ] Demo rerun; the report and AGENTS.md figures updated
- [ ] Contract suite split out and parametrized over runners
- [x] `uv run ruff check` clean
"""
    )
    return agents, testing


def _sample_curve(rng: random.Random, n: int, sharpe: float, weekly_vol: float) -> list:
    """Weekly equity whose log returns have exactly the given annualised Sharpe."""
    z = [rng.gauss(0.0, 1.0) for _ in range(n - 1)]
    mean = sum(z) / len(z)
    sd = math.sqrt(sum((v - mean) ** 2 for v in z) / (len(z) - 1))
    drift = sharpe / math.sqrt(52)
    level, curve = 1.0, [1.0]
    for v in z:
        level *= math.exp(weekly_vol * ((v - mean) / sd + drift))
        curve.append(round(level, 6))
    return curve


def _max_drawdown(curve: list) -> float:
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        worst = max(worst, 1 - v / peak)
    return round(worst, 4)


def _cagr(curve: list) -> float:
    return round(curve[-1] ** (52 / (len(curve) - 1)) - 1, 4)


def _sample_gate(rng, key, passed, budget=None):
    """A plausible gate entry on the side of its threshold that `passed` asks for."""
    specs = {
        "wf_oos_sharpe": (1.0, ">="),
        "wf_oos_sharpe_2x_costs": (0.5, ">"),
        "dsr": (0.95, ">="),
        "pbo": (0.25, "<="),
        "plateau_retention": (0.70, ">="),
        "regime_max_profit_share": (0.5, "<"),
    }
    if key == "beats_benchmarks":
        return {"value": passed, "pass": passed}
    if key == "final_test":
        if passed is None:
            return {"value": None, "pass": None, "note": "run once at sign-off"}
        return {
            "value": round(rng.uniform(0.85, 1.1), 2),
            "pass": passed,
            "note": "Sharpe on the test window",
        }
    if key == "mc_p95_max_drawdown":
        if budget is None:
            return {
                "value": round(rng.uniform(0.2, 0.4), 3),
                "threshold": None,
                "op": "<=",
                "pass": None,
                "note": "risk budget TBD",
            }
        value = budget * (rng.uniform(0.6, 0.95) if passed else rng.uniform(1.05, 1.4))
        return {"value": round(value, 3), "threshold": budget, "op": "<=", "pass": passed}
    threshold, op = specs[key]
    if passed is None:
        return {"value": None, "threshold": threshold, "op": op, "pass": None, "note": "not computed yet"}
    good = op.startswith(">")
    side = 1 if (passed == good) else -1
    value = threshold * (1 + side * rng.uniform(0.04, 0.35))
    if key in ("dsr", "plateau_retention"):  # probabilities / shares stay below 1
        value = rng.uniform(threshold + 0.001, 0.995) if passed else rng.uniform(0.3, threshold - 0.01)
    return {"value": round(value, 3), "threshold": threshold, "op": op, "pass": passed}


def _sample_audit(rng, ctx, name, date, risk, verdict, sharpe, passes, budget=None, drop=()):
    dates, btc, mix = ctx
    curve = _sample_curve(rng, len(dates), sharpe, 0.035)
    gates = {}
    for key in GATE_KEYS:
        if key in drop:
            continue
        gates[key] = _sample_gate(rng, key, passes.get(key, True), budget)
    gates["wf_oos_sharpe"]["value"] = sharpe
    return {
        "schema": AUDIT_SCHEMA,
        "strategy": name,
        "date": date,
        "risk_level": risk,
        "verdict": verdict,
        "git_commit": "".join(rng.choice("0123456789abcdef") for _ in range(7)),
        "data_snapshot": "sample-snapshot-2026-07-01",
        "seed": 7,
        "n_trials": rng.choice((800, 1200, 2000)),
        "effective_trials": round(rng.uniform(120, 400), 1),
        "window": {"start": dates[0], "end": dates[-1]},
        "test_window_opened": gates.get("final_test", {}).get("pass") is not None,
        "gates": gates,
        "metrics": {
            "wf_oos_sharpe": sharpe,
            "cagr": _cagr(curve),
            "max_drawdown": _max_drawdown(curve),
            "n_trades": rng.randint(40, 220),
            "walk_forward_efficiency": round(rng.uniform(0.4, 0.8), 2),
        },
        "benchmarks": {
            "buy_hold_btc": {"sharpe": 0.9, "max_drawdown": _max_drawdown(btc)},
            "rebalance_50_50": {"sharpe": 0.95, "max_drawdown": _max_drawdown(mix)},
            "random_entry": {
                "sharpe_median": round(rng.uniform(-0.1, 0.3), 2),
                "sharpe_p95": round(rng.uniform(0.5, 0.9), 2),
            },
        },
        "equity": {
            "dates": dates,
            "series": {"strategy": curve, "buy_hold_btc": btc, "rebalance_50_50": mix},
        },
        "report_md": f"reports/{name}/{date}.md",
    }


def make_sample_root(base) -> Path:
    """Write a synthetic repo tree under `base` (seed 7) that exercises every section."""
    rng = random.Random(7)
    root = Path(base)
    _write(root / SAMPLE_MARKER, SAMPLE_NOTE + "\n")
    agents_md, testing_md = _sample_markdown()
    _write(root / "AGENTS.md", agents_md)
    _write(root / "TESTING.md", testing_md)
    _write(
        root / "dashboard" / "status.json",
        {
            "updated": "2026-11-18",
            "note": "Sample status. Every number on this page is synthetic.",
            "milestones": {
                "0": {"status": "done", "note": "Sample"},
                "1": {"status": "done", "note": "Sample"},
                "2": {"status": "done", "note": "Sample"},
                "3": {"status": "in_progress", "note": "Sample"},
                "4": {"status": "blocked", "note": "Sample: waiting on milestone 3"},
                "5": {"status": "paused", "note": "Sample: unknown status value, to show the warning"},
            },
            "open_work": {
                "5.1": "done",
                "5.2": "done",
                "5.3": "in_progress",
                "5.4": "not_started",
                "5.5": "not_started",
                "5.6": "blocked",
                "5.7": "not_started",
            },
            "strategies": {
                "rebalance-steady": {"paper": {"status": "done", "started": "2026-09-16", "note": "Sample"}},
                "dip-buy-balanced": {"paper": {"status": "not_started", "started": None, "note": ""}},
                "momentum-bold": {"paper": {"status": "not_started", "started": None, "note": ""}},
            },
        },
    )

    cases = "".join(
        f'<testcase classname="tests.test_sample" name="test_{i}" time="0.01"/>' for i in range(5)
    )
    _write(
        root / "results" / "tests" / "junit.xml",
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="1" skipped="3" tests="214" time="118.4" '
        'timestamp="2026-11-18T14:02:11.000000+00:00">'
        + cases
        + '<testcase classname="tests.test_validation_exact" name="test_expected_max_sharpe_n1000">'
        '<failure message="sample failure">sample</failure></testcase></testsuite></testsuites>',
    )
    files = {
        f"lab/{m}.py": round(rng.uniform(93, 100), 2)
        for m in (
            "validation/stats",
            "validation/splits",
            "validation/montecarlo",
            "search/study",
            "search/walkforward",
            "models/train",
            "runner/reference",
            "data/loaders",
        )
    }
    _write(
        root / "results" / "tests" / "coverage.json",
        {
            "meta": {"version": "sample", "timestamp": "2026-11-18T14:04:00", "branch_coverage": True},
            "files": {k: {"summary": {"percent_covered": v}} for k, v in files.items()},
            "totals": {
                "percent_covered": round(sum(files.values()) / len(files), 2),
                "num_branches": 1240,
                "covered_branches": 1196,
            },
        },
    )
    for area, _path, _target in MUTATION_AREAS:
        killed = rng.randint(300, 600)
        survived = int(killed * rng.uniform(0.05, 0.3))
        stats = {
            "killed": killed,
            "survived": survived,
            "timeout": rng.randint(0, 6),
            "suspicious": 0,
            "no_tests": rng.randint(0, 40),
            "skipped": 0,
            "total": killed + survived + 50,
        }
        if area == "validation":
            stats["equivalent"] = min(survived, 14)
        _write(root / "results" / "tests" / "mutation" / f"{area}.json", stats)

    _write(
        root / "data" / "catalog" / "SNAPSHOT.json",
        {
            "snapshot_id": "sample-snapshot-2026-07-01",
            "created": "2026-07-01T09:00:00Z",
            "sources": ["kraken", "binance"],
            "series": [
                {
                    "instrument": coin + ("/USD" if src == "kraken" else "/USDT"),
                    "source": src,
                    "bar": bar,
                    "start": "2017-01-01",
                    "end": "2026-06-30",
                    "rows": (3468 if bar == "1d" else 83232) - rng.randint(0, 40),
                    "gaps": rng.randint(0, 4),
                }
                for coin in ("BTC", "ETH")
                for src in ("kraken", "binance")
                for bar in ("1d", "1h")
            ],
        },
    )
    _write(root / "reports" / "data" / "2026-07-01-quality.md", f"# Data quality (sample)\n\n{SAMPLE_NOTE}\n")
    _write(root / "reports" / "demo" / "2026-06-20.md", f"# Demo report (sample)\n\n{SAMPLE_NOTE}\n")
    for i in range(3):
        _write(root / "results" / "dip-buy-balanced-wf" / f"trials-{i:03d}.parquet", b"")
    _write(root / "results" / "dip-buy-balanced-wf" / "journal.log", "sample\n")
    for i in range(2):
        _write(root / "results" / "momentum-bold-search" / f"trials-{i:03d}.parquet", b"")

    for name in ("rebalance-steady", "dip-buy-balanced", "momentum-bold", "vol-sized-dip"):
        for f in ("strategy.py", "params.yaml", "README.md"):
            _write(root / "strategies" / name / f, f"# {SAMPLE_NOTE}\n")
    _write(root / "strategies" / "trend-steady" / "strategy.py", f"# {SAMPLE_NOTE}\n")
    _write(root / "strategies" / "trend-steady" / "params.yaml", f"# {SAMPLE_NOTE}\n")
    _write(
        root / "exports" / "rebalance-steady" / "config.yaml",
        f"# {SAMPLE_NOTE}\nstrategy: rebalance-steady\n",
    )

    start = dt.date(2019, 1, 6)
    dates = [(start + dt.timedelta(weeks=i)).isoformat() for i in range(286)]
    ctx = (dates, _sample_curve(rng, len(dates), 0.9, 0.10), _sample_curve(rng, len(dates), 0.95, 0.05))
    every_pass = {k: True for k in GATE_KEYS}
    audits = [
        (
            "rebalance-steady",
            "2026-07-20",
            "steady",
            "INCOMPLETE",
            1.21,
            dict(every_pass, plateau_retention=None, final_test=None),
            None,
            (),
        ),
        ("rebalance-steady", "2026-09-14", "steady", "PASS", 1.32, every_pass, 0.25, ()),
        (
            "dip-buy-balanced",
            "2026-08-03",
            "balanced",
            "FAIL",
            0.86,
            dict(every_pass, wf_oos_sharpe=False, dsr=False, beats_benchmarks=False, final_test=None),
            0.35,
            (),
        ),
        (
            "dip-buy-balanced",
            "2026-11-02",
            "balanced",
            "INCOMPLETE",
            1.14,
            dict(every_pass, final_test=None),
            0.35,
            (),
        ),
        (
            "momentum-bold",
            "2026-10-20",
            "bold",
            "FAIL",
            0.74,
            dict(
                every_pass,
                wf_oos_sharpe=False,
                dsr=False,
                pbo=False,
                beats_benchmarks=False,
                regime_max_profit_share=False,
                final_test=None,
            ),
            None,
            (),
        ),
        (
            "vol-sized-dip",
            "2026-11-10",
            "balanced",
            "PASS",
            1.18,
            every_pass,
            0.35,
            ("regime_max_profit_share",),
        ),
    ]
    for name, date, risk, verdict, sharpe, passes, budget, drop in audits:
        audit = _sample_audit(rng, ctx, name, date, risk, verdict, sharpe, passes, budget, drop)
        _write(root / "reports" / name / f"{date}.json", audit)
        _write(root / "reports" / name / f"{date}.md", f"# Audit: {name}, {date} (sample)\n\n{SAMPLE_NOTE}\n")
    # A truncated file, to show how a malformed input surfaces as a warning.
    _write(root / "reports" / "momentum-bold" / "2026-10-27.json", '{"schema": "osprey.audit/1", "verdict": ')
    return root


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Build the Osprey Strategy Lab results dashboard (one self-contained HTML file).",
        epilog="Inputs and the audit JSON schema are described in HOWTO.md#dashboard.",
    )
    p.add_argument("--root", default=".", help="repo checkout to read (default: current directory)")
    p.add_argument(
        "--out",
        help="HTML file to write (default: <root>/dashboard/index.html; "
        "with --sample: <tmpdir>/osprey-dashboard-sample.html)",
    )
    p.add_argument("--json", dest="json_out", metavar="PATH", help="also write the collected data as JSON")
    p.add_argument(
        "--sample",
        action="store_true",
        help="build from a synthetic repo tree generated in a temp folder (seed 7); "
        "the page carries a SAMPLE DATA banner",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"build_dashboard: cannot read template {TEMPLATE_PATH}: {exc.strerror}", file=sys.stderr)
        return 2
    if args.sample:
        if args.root != ".":
            print("build_dashboard: --root is ignored with --sample", file=sys.stderr)
        root = make_sample_root(tempfile.mkdtemp(prefix="osprey-dashboard-sample-"))
        out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "osprey-dashboard-sample.html"
    else:
        root = Path(args.root).resolve()
        if not root.is_dir():
            print(f"build_dashboard: --root {args.root} is not a folder", file=sys.stderr)
            return 2
        out = Path(args.out) if args.out else root / "dashboard" / "index.html"

    data = collect(root)
    data["link_root"] = link_root(root, out)
    try:
        page = render(data, template)
    except ValueError as exc:
        print(f"build_dashboard: bad template {TEMPLATE_PATH}: {exc}", file=sys.stderr)
        return 2
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        if args.json_out:
            json_path = Path(args.json_out)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
            )
    except OSError as exc:
        print(f"build_dashboard: cannot write output ({exc.strerror or exc})", file=sys.stderr)
        return 2
    print(summary_line(data, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Freeze the trend-steady train results before the single validate look (PLAN.md section 13, stop rule 10).

    uv run python research/trend-steady/freeze.py [--triaged "<note>"]
    uv run python research/trend-steady/freeze.py --out-dir <scratch> [--config-dir <dir>] [--any-verdict]

Reads ``train/run<k>/summary.json`` of the reported run (the highest-numbered run, which must be complete; a crashed
or stopped run is rerun as an amendment run), recomputes the config hash and every frozen file's SHA-256 and
compares them with that run's start fields. If any differs it exits non-zero WITHOUT writing FROZEN.json. The one
exception (stop rule 10): only ``config/risk_levels.yaml`` differs and ``risk_limits("steady")`` still gives the
train-start coins, ``min_cash`` and ``max_coin``; the freeze then records both hashes and a deviation, and G6 keeps its
train-start value. A real freeze uses the pinned folders only (results/trend-steady, config/); a synthetic one never
writes into results/trend-steady or the repo. A run with failed trials is frozen only with ``--triaged "<note>"``
(stop rule 4). It refuses when the look is not earned (the reported run's reported look_earned: E1-E8 and P must hold
and no stop rule fired, in it and in every earlier run it is reported beside; stop rules 8 and 18; ``--any-verdict``
lets a synthetic dry run through) and when FROZEN.json exists. For an amendment run it also refuses a RUNLOG line
without a trigger and beside runs that the earlier summaries no longer give.

Writes ``<out>/FROZEN.json`` and a byte-identical copy: ``research/trend-steady/FROZEN.json`` for real data (the lead
commits it, with trials.csv, evaluations.csv and RUNLOG.jsonl, before the look), ``<out>/tracked/FROZEN.json`` for a
synthetic dry run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def _study_module():
    name = "trend_steady_study"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("study.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _study_module()


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(S.DEFAULT_OUT))
    ap.add_argument("--config-dir", default=None, help="the config folder the train run used")
    ap.add_argument(
        "--any-verdict", action="store_true", help="synthetic dry runs only: freeze whatever the verdict"
    )
    ap.add_argument(
        "--triaged",
        default=None,
        metavar="NOTE",
        help="the triage of the reported run's failed trials (stop rule 4: no code bug, the run stands)",
    )
    return ap.parse_args(argv)


def reported_run(train: Path) -> tuple[int, dict]:
    """The highest-numbered run, which must have status 'complete' (INTERPRETATIONS["reported_run"])."""
    runs = sorted(
        (int(p.name[3:]), p)
        for p in train.glob("run*")
        if p.name[3:].isdigit() and (p / "summary.json").is_file()
    )
    if not runs:
        raise S.Refusal(f"no train run under {train}")
    k, path = runs[-1]
    summary = json.loads((path / "summary.json").read_text())
    if summary.get("status") != "complete":
        raise S.Refusal(
            f"run {k}, the last train run, is not complete (status {summary.get('status')!r}): a crashed or stopped "
            "run is rerun as an amendment run (stop rules 5-7), and an earlier run it superseded is never reported"
        )
    return k, summary


def check_trigger(runlog: Path, k: int, data: str) -> None:
    """Stop rule 18: amendment run k's RUNLOG line must record how its bug was found (a, b, c or "other, after the
    verdict"); a line without one is refused."""
    lines = [
        x
        for x in S.runlog_entries(runlog)
        if x.get("script") == "run_train.py" and x.get("run") == k and x.get("data") == data
    ]
    if not lines or any(x.get("trigger") not in S.TRIGGERS for x in lines):
        raise S.Refusal(
            f"stop rule 18: {runlog} has no line for amendment run {k} with a trigger in {S.TRIGGERS}"
        )


def check_beside(train: Path, k: int, start: dict, reported: dict) -> None:
    """Stop rule 18: the earlier runs run k is reported beside, as its start record fixed them, are still the ones the
    earlier summaries give (INTERPRETATIONS["look_hash_check"])."""
    now = S.jsonable(S.beside_runs(train, k, start["trigger"]))
    if not (S.same_json(start["beside"], now) and S.same_json(reported["beside"], now)):
        raise S.Refusal(
            f"stop rule 18: run {k}'s beside runs (start record {start['beside']}, reported {reported['beside']}) are "
            f"not the ones the earlier summaries give now ({now}): an earlier summary changed"
        )


def freeze(args) -> int:
    out = Path(args.out_dir)
    frozen_path = out / "FROZEN.json"
    if frozen_path.exists():
        raise S.Refusal(f"{frozen_path} exists: the study is frozen once")
    train = out / "train"
    k, summary = reported_run(train)
    start, results = summary["start"], summary["results"]
    synthetic = start["data"] == "synthetic"
    if args.any_verdict and not synthetic:
        raise S.Refusal("--any-verdict is for synthetic dry runs only")
    config_dir = Path(args.config_dir) if args.config_dir else None
    S.check_paths(out, config_dir, None, synthetic)
    if results.get("triage_required") and not args.triaged:
        raise S.Refusal(
            f"run {k} recorded {len(results.get('failed_trials', []))} failed trials: triage them first (stop rule "
            "4). A code bug means an amendment run; if there is none, freeze with --triaged '<note>'"
        )
    reported = results["reported"]
    want = S.combine_reported(start["beside"], results["own"])
    if not all(S.same_json(reported[key], want[key]) for key in want):
        got = {key: reported[key] for key in want}
        raise S.Refusal(
            f"stop rule 18: run {k}'s reported record {got} is not its own record combined with the runs its start "
            f"record says it is reported beside ({want})"
        )
    if reported["look_earned"] is not True and not args.any_verdict:
        raise S.Refusal(
            f"run {k}'s reported verdict is {reported['verdict']} (its own: {results['verdict']['label']}; reported "
            f"beside runs {[b['run'] for b in reported['beside']]}): E1-E8 and P do not all hold in every run it is "
            "reported with, so there is no validate look (section 13, stop rules 8 and 18) and nothing to freeze"
        )
    if k:
        check_trigger(S.runlog_path(out, synthetic), k, start["data"])
        check_beside(train, k, start, reported)
    hashes = S.file_hashes(config_dir)
    check = S.compare_hashes(
        start["file_hashes"], start["config_hash"], hashes, start["risk_limits"], config_dir
    )
    if not check["ok"]:
        raise S.Refusal(
            f"the code, plan or config changed since run {k} started (stop rule 10): {check['differs']}"
            + (f"; {check['reason']}" if check.get("reason") else "")
            + ". FROZEN.json is not written"
        )
    frozen = {
        "label": S.LABEL,
        "study": S.STUDY,
        "data": start["data"],
        "synthetic_seed": start["synthetic_seed"],
        "frozen_utc": S.utc_now(),
        "run": k,
        "summary_sha256": S.sha256_file(train / f"run{k}" / "summary.json"),
        "config_hash": S.config_hash(hashes),
        "file_hashes": hashes,
        "train_start": {
            "utc": start["utc"],
            "config_hash": start["config_hash"],
            "file_hashes": start["file_hashes"],
            "git": start["git"],
        },
        "hash_check": check,
        "deviations": [check["exception"]] if check["exception"] else [],
        "train_outputs_sha256": S.tree_hashes(train),
        **S.frozen_numbers(results),
        "n_trials_per_study": start["settings"]["n_trials"],
        "settings": start["settings"],
        "seeds": S.SEEDS,
        "trials": results["trials"],
        "snapshot": start["snapshot"],
        "panels": {
            src: {key: rec[key] for key in ("hash", "rows", "first", "last")}
            for src, rec in summary["panels"].items()
        },
        "risk_limits_train_start": start["risk_limits"],
        "g6_budget": start["g6_budget"],
        "branch": start["branch"],
        "git": S.git_state(),
        "any_verdict": bool(args.any_verdict),
        "triage_note": args.triaged,
    }
    S.write_json(frozen_path, frozen)
    copy = S.tracked_dir(out, synthetic) / "FROZEN.json"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(frozen_path.read_bytes())
    print(
        f"frozen run {k}: config hash {frozen['config_hash'][:16]}; {len(frozen['train_outputs_sha256'])} train files "
        f"hashed; theta_final A {frozen['theta_final']['A']['params']}; copy at {copy}"
        + (f"; DEVIATION: {frozen['deviations'][0]['rule']}" if frozen["deviations"] else "")
    )
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return freeze(args)
    except S.Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

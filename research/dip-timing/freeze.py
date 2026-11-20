"""Freeze the study config after the train run and before the validate look (PLAN.md section 9, look #1).

Writes FROZEN.json: the config hash (code + interpretations), every frozen file's SHA-256, the SHA-256 of the
train outputs, the selected best variant and the time. run_validate.py refuses to run if anything differs.
The task forbids commits, so this file stands in for the "frozen config hash is committed" step (RESULTS.md,
Deviations).

    uv run python research/dip-timing/freeze.py
    uv run python research/dip-timing/freeze.py --train <scratch>/train --out <scratch>/FROZEN.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import study as S


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train", default=str(S.REPO / "results/dip-timing/train"))
    ap.add_argument("--out", default=str(S.REPO / "results/dip-timing/FROZEN.json"))
    args = ap.parse_args(argv)
    out, train = Path(args.out), Path(args.train)
    if out.exists():
        print(f"{out} exists: the config is frozen once", file=sys.stderr)
        return 2
    summary = json.loads((train / "summary.json").read_text())
    if summary["config_hash"] != S.config_hash():
        print("WARNING: the code changed after the train run; recording both hashes", file=sys.stderr)
    outputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(train.iterdir()) if p.is_file()}
    frozen = {
        "frozen_utc": datetime.now(UTC).isoformat(),
        "config_hash": S.config_hash(),
        "config_hash_at_train_run": summary["config_hash"],
        "code_hashes": S.code_hashes(),
        "train_outputs_sha256": outputs,
        "best": summary["selections"]["best"],
        "git": S.git_state(),
        "snapshot": summary["snapshot"],
    }
    out.write_text(json.dumps(frozen, indent=1, sort_keys=True))
    print(json.dumps({k: frozen[k] for k in ("frozen_utc", "config_hash", "best")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

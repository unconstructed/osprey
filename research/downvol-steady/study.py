"""downvol-steady: what run_train.py, freeze.py, run_validate.py, controls.py and throughput.py share (PLAN.md 3-17).

SCOUTING ONLY. Every profit number comes from the lab's reference portfolio engine (``lab.runner.portfolio``, driven
by ``lab.runner.trend``'s one executor through ``lab.runner.downvol``), not NautilusTrader (AGENTS.md hard rule 3),
with the PLACEHOLDER costs of ``config/costs.yaml``, and exchange candles stand in for Base prices. Nothing from this
study goes into ``reports/<strategy>/``, ``strategies/`` or ``exports/``; it cannot make anything ready for paper.

PLAN.md is vol-steady's plan ("VP" = ``research/vol-steady/PLAN.md`` at ``ea1426e``, itself trend-steady's protocol, TP)
with three changes: the volatility measure (the downside deviation around zero, ``lab.runner.downvol``), E1 judged with
each fold's share held fixed (the q-only shift of amendment M1; VP's whole-schedule shift is the description E1-whole)
and the strict trial count (VP's plus vol-steady run 0's 2,400 trials). These scripts are vol-steady's, adapted: the
computations live in tested code (``lab/runner/downvol.py``, ``lab/runner/volsteady.py``, ``lab/runner/trend.py``,
``lab/runner/steady.py``, ``lab/search``, ``lab/validation``); this file holds the pinned values, the integrity checks
(config hash, git state, snapshot, hash comparison, RUNLOG, the branch guard, the projection guard), the panel loading
and the harness bundle (S with its R_0, q-only and whole-schedule shifts, N0 and X). ``research/`` is never imported by
``lab/``.

The test window is never read: every panel comes from ``lab.data.panel.load_panel`` with ``last_close`` at most
2024-07-01 00:00 UTC (its guard raises ``HoldoutWindowError`` for anything later), and :func:`load_study_panel` checks
the returned index again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import subprocess
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError, holdout_cut
from lab.data.panel import load_panel
from lab.data.synthetic import synthetic_market
from lab.runner import downvol as D
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.runner.portfolio import ASSETS, LIMIT_TOL, make_panel
from lab.runner.reference import Costs
from lab.search.study import SearchConfig, run_study
from lab.validation import montecarlo as mc
from lab.validation import stats

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
STUDY = "downvol-steady"
LABEL = (
    "SCOUTING: reference portfolio engine (lab.runner.portfolio via lab.runner.trend and lab.runner.downvol), not "
    "NautilusTrader (AGENTS.md hard rule 3); PLACEHOLDER costs (config/costs.yaml); exchange candles stand in for "
    "Base prices"
)
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog"
SCRIPTS = ("study.py", "run_train.py", "freeze.py", "run_validate.py", "controls.py", "throughput.py")

SOURCE, ROBUSTNESS, INTERVAL = "KRAKEN", "BINANCE", "1d"
TRAIN_LAST_CLOSE = pd.Timestamp("2023-01-01", tz="UTC")  # section 3: the last train close
VALIDATE_LAST_CLOSE = pd.Timestamp("2024-07-01", tz="UTC")  # the last validate close; nothing later is read
BARS_SHA256 = "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"  # TP 3 (stop rule 2)
PANEL_SHA256 = {  # TP 3: the train panel hashes (steady.panel_hash), rebalance-steady run 0
    SOURCE: "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
    ROBUSTNESS: "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
}
ROWS = {"train": {SOURCE: 2190, ROBUSTNESS: 1963}, "validate": {SOURCE: 2737, ROBUSTNESS: 2510}}
KEPT_ROWS = 1820  # 5 x 364 stitched kept returns (TP 7)
W_KRAKEN, W_BINANCE, W_VALIDATE = 260, 208, 78  # check closes deciding kept fills (TP appendix B)
VALIDATE_TEST = (2190, 2736)  # Kraken rows of the validate block (TP 13)
VALIDATE_KEPT = 546
SEEDS = {"A": 0, "B": 1}
FOLD_SEED_STEP, FINAL_SEED_OFFSET = 1000, 5000  # TP 7
STABLE_K = 10
MAX_AMENDMENTS = 2
BRANCH = "R"
BUDGET_PCT = 35  # owner decision of 2026-11-21, quoted in PLAN.md's branch line; stop rule 11
QUOTED_LIMITS = {"min_cash": 0.20, "max_coin": 0.60, "coins": ("BTC", "ETH", "USDC")}
RISK_SHA256_QUOTED = "d3f58253dfc2dbbe0ca5e54a4fa12489ab0e08827ecbc309e8ab2b7cc028723e"  # the branch line
STRICT_EXTRA = 49  # VP 14 (TP 14, Branch R, the stop-variant terms removed: 48 counted runs + TP's K4 term)
PRIOR_TRIALS = 2400  # section 14: vol-steady run 0's trials on the same data (prior look W1)
K4_AS_15 = 14  # TP M6's description: K4 counted as 15 instead of 1
R4_BOOKS = (100.0, 500.0, 2500.0, 10_000.0, 50_000.0)
REF_BOOK = 10_000.0
CHECK_DAYS = (1, 2, 3, 4, 5, 6)  # E5(b): the other weekdays
WHIPSAW_DAYS = 28  # TP 16: a change reversed within 4 weeks
TRADES_FLAG = 30
DEGRADE_BPS = 10.0
BEAR_YEARS = (2018, 2022)  # the "two bear years together" description (TP 16)
TRIGGERS = V.TRIGGERS
RISK_FILE = "config/risk_levels.yaml"
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", RISK_FILE)
STUDY_RE = re.compile(r"^downvol-steady-s(?P<seed>\d+)(?:_a(?P<run>\d+))?_(?P<part>wf\d{2}|final)$")


class Refusal(Exception):
    """A start guard refused: nothing was run (exit code 2)."""


class Stop(Exception):
    """A stop rule fired after the start (exit code 3)."""


@dataclass(frozen=True)
class Settings:
    """Simulation sizes. The plan's values are pinned; ``FAST`` is for synthetic dry runs only."""

    n_trials: int = 200
    bootstrap_resamples: int = 10_000
    shuffle_sims: int = 5000
    degrade_sims: int = 1000
    timing_trials: int = 200
    timing_reps: int = 20


PLAN_SETTINGS = Settings()
FAST = Settings(
    n_trials=10, bootstrap_resamples=200, shuffle_sims=100, degrade_sims=100, timing_trials=10, timing_reps=2
)

# The projection's run-count table (stop rule 17): units of volsteady.TIMING_KEYS for one train run. "run": one
# executor run of the rule or a comparator (each fold piece, each shift or check run); "bootstrap": one paired bootstrap
# or one Monte Carlo drawdown set (each counted as a paired bootstrap, which over-projects). Built from named parts so
# a test can check it by hand. VP's table (TP 7's without the stop-loss variant's parts), its shifts q-only (M1), with
# the whole-schedule shifts of the description E1-whole added.
RUN_PARTS = {
    "study": {"searches (2 seeds x (5 folds + final))": 12},
    "run": {
        "walk_forward_optimize's in-sample and out-of-sample runs (2 seeds x 5 folds x 2)": 20,
        "S, S at 2x, N0, N0 at 2x, X (2 seeds x 5 folds x 5)": 50,
        "R_0 and its 259 q-only shifts (2 seeds x 260)": 520,
        "E1-whole: R_0's 207 guarded whole-schedule shifts (2 seeds x 207)": 414,
        "G5(a) plateau steps (2 seeds x 6 steps x 5 folds)": 60,
        "theta_final in-sample and its 2x check (2 seeds x 1, plus 1)": 3,
        "grid steps at 1x and 2x (4 x 2) and their N0 (4 x 5)": 28,
        "G5(b) steps from the default": 6,
        "S(s_k) at 1x and 2x (4 x 5 x 2), N0(s_k) (4 x 5), R_0(s_k) and 207 q-only shifts (4 x 208)": 892,
        "check-day variants (6 x 5) and the daily-check variant (5)": 35,
        "R4 book sizes": 4,
        "Binance S, N0 (4 + 4), R_0 and its 155 q-only shifts (156)": 164,
        "B1 and B2 (2 x 5), N0-span (1)": 11,
    },
    "bootstrap": {
        "paired bootstraps: E2 (2 seeds), E7 (2 seeds x 2), E8, S(s_k) (4), block-20, the LOYO years (5)": 17,
        "Monte Carlo drawdown sets (G6's statistic and the descriptions), at most": 60,
    },
}


def run_counts(parts: Mapping = RUN_PARTS) -> dict[str, int]:
    """The projection's units per volsteady.TIMING_KEYS."""
    return {key: sum(parts[key].values()) for key in V.TIMING_KEYS}


A0_PANELS = 20  # positive and negative controls each (section 9)
A0_VOL_PANELS = 200  # volatility clustering with no momentum (section 9; a description, no alarm)
A0_VOL_POINT = {"lookback": 30, "target_vol": 0.60, "crypto_share": 0.50}
A0_ALARM_FP = 3
A0_POWER_MIN = 4


def a0_counts(n_panels: int = A0_PANELS, n_vol: int = A0_VOL_PANELS) -> dict[str, int]:
    """A0's projection units (controls.py, stop rule 17 at 120 CPU-minutes) for 2 x ``n_panels`` panels: per panel 5
    fold studies; S and N0 per fold (10) and R_0 with its 207 guarded shifts (208); one paired bootstrap. The
    volatility-clustering panels: per panel one rule run and 208 schedule runs."""
    panels = 2 * n_panels
    return {"study": panels * 5, "run": panels * (10 + 208) + n_vol * 209, "bootstrap": panels}


SECTION_4_READINGS = (
    "At close t >= 1 the basket return is x_t = log1p(0.5 (C_BTC,t / C_BTC,t-1 - 1) + 0.5 (C_ETH,t / C_ETH,t-1 - 1)); "
    "a missing close makes one 2-day return, unscaled.",
    "At a Monday 00:00 UTC check close c >= L: the downside deviation sigma = sqrt(365) x sqrt(2 x ss / L), ss = "
    "math.fsum(d_t^2) with d_t = min(x_t, 0.0) over rows c - L + 1 .. c (one exactly rounded sum per window, around "
    "zero, divided by L); m = 1 if sigma = 0 else min(1, tau / sigma); q = floor(4 m + 1e-9) / 4; the crypto share in "
    "force is s q, split 50/50; before the first check close c >= L the book is all USDC.",
    "An order is sent at a close where the target vector in force changes, or at a limit breach (the vector in "
    "force); one order per close, filled at the next open; the last close's decision is never filled.",
    "Breaches are judged at the limits themselves at every daily close; targets keep h = 0.02 inside the limits.",
)

# Readings the scripts make where the plan is loosely worded. They are part of the config hash.
INTERPRETATIONS = {
    "dirty": "A git tree is dirty when `git status --porcelain --untracked-files=all` prints anything: modified, "
    "staged, deleted or untracked files count; git-ignored files (results/, data/, caches) do not. Real runs of "
    "run_train.py and run_validate.py refuse a dirty tree; a synthetic dry run refuses it too unless --allow-dirty "
    "is given.",
    "writers": "run_train.py writes research/downvol-steady/trials.csv (every trial of every study of runs 0..k) and "
    "evaluations.csv (every evaluation of runs 0..k), rewriting both at the end of each real run; run_validate.py "
    "writes validate.csv. Synthetic dry runs write them to <out>/tracked/ instead, never into the repo.",
    "amendment_section": "PLAN.md's section 15 is the text from the line starting '## 15.' to the next line starting "
    "'## ' (downvol-steady's plan has no '**Amendments.**' and '**Deviations.**' markers, as TP 15 has).",
    "amendment_row": "run_train.py --amendment k (real data) refuses unless PLAN.md section 15 holds a line starting "
    "with '- **Amendment run k' (stop rule 7).",
    "trigger": "run_train.py --amendment k needs --trigger, one of a, b, c or 'other, after the verdict' (stop rule "
    "18); it is written into the RUNLOG line and the start record. Run 0 takes none.",
    "paths": "Real runs use the pinned folders only: --out-dir results/downvol-steady, --config-dir unset (or "
    "config/) and --catalog-dir data/catalog. Synthetic dry runs and the A0 controls refuse results/downvol-steady "
    "and any folder inside the repo (section 14).",
    "same_kind_of_run": "run_train.py --amendment k refuses unless every earlier run k' < k has the same data (real "
    "or synthetic) and the same --fast setting in its start record.",
    "runlog_guard": "run_train.py refuses a run number that the RUNLOG already holds for the same data, and "
    "run_validate.py refuses when the RUNLOG holds a look for the same data: a deleted results folder reopens "
    "neither. Real runs read the tracked research/downvol-steady/RUNLOG.jsonl, dry runs <out>/RUNLOG.jsonl.",
    "branch": "Stop rule 11: the branch is the line starting '- Branch: ' (or '- **Branch: ') in PLAN.md, the letter "
    "after it, with the budget '**<n>%**' on that line. Only Branch R is built; it refuses unless the budget read is "
    "35 (0.35), min_cash 0.20, max_coin 0.60 and the coins exactly BTC, ETH and USDC. Another file SHA-256 with those "
    "values is recorded, not refused.",
    "g6_budget": "G6 uses run 0's train-start reading of config/risk_levels.yaml for the whole study, amendment runs "
    "included; an amendment run records its own reading too but never uses it for G6.",
    "projection": "Stop rule 17 re-times, on make_panel(synthetic_market(2190, seed=21, start='2017-01-02')), one "
    "study of the built adapter (n_workers 1, the box of section 5; its CPU time scaled to N trials), the median of "
    "the reps' full-length downvol_backtest runs at (30, 0.60, 0.50) and one paired bootstrap of 10,000 resamples x 1820 "
    "rows at block 60, in CPU seconds (time.process_time), and projects run_counts(). Dry runs record it and never "
    "refuse; a timing that raises refuses.",
    "kept": "S's kept rows are the closes after each fold's t0 up to its last close (1820). A fixed configuration "
    "(theta_final, a grid step, the default's G5(b) steps, R4) runs once from row 0 over the whole train panel and "
    "is scored on the same 1820 closes; this equals stitching its fold runs, since each fold run is a prefix.",
    "grid_n0": "A fixed run's own N0 (G8-excess at a grid step) is built per fold on the fold's H0 slice from that "
    "run's targets before t0, then (s/2, s/2) from close t0 on with limit fixes, and stitched on the kept rows.",
    "orders_in_kept_rows": "R1, the trade-frequency table and the episode table count orders filled in kept rows: a "
    "fold run's fills after its t0, a fixed run's fills on the 1820 kept closes.",
    "e7_masks": "E7 (G7's removals, the LOYO table) keep the rows whose bar-year is not removed, in time order: E1 on "
    "the masked rows of R_0 and of every guarded q-only shift (INTERPRETATIONS['e1_q_only']); E2 the paired bootstrap of the masked S and N0; E3 the max "
    "drawdown and G6's statistic of the masked S and X; E4 the masked Sharpes at 2x.",
    "boom_years": "BTC's bar-years are ranked on Kraken's closes over S's 1820 kept rows (trend.boom_years).",
    "binance": "A Binance fold run is downvol_backtest on Binance's H0 slice (its own first close, 2017-08-18, to the "
    "fold's last Kraken close); its kept closes must be Kraken's; its rows count from Binance's own row 0 (L is in "
    "rows), so its first volatility comes earlier in its folds. Binance R_0 starts from Binance S's fold-1 book.",
    "counted": "The strict count's runs (TP 14 without the stop-variant terms) are the evaluation rows with counted "
    "= true (one per stitched run); their number must be 48, plus 1 for TP's K4 term (not a run), which the plan's "
    "'stop-variant terms removed' keeps. The whole-schedule shifts of E1-whole are descriptions and not counted.",
    "strict_count": "Section 14: the strict trial count is N_raw + 49 (VP's: the 48 counted runs and TP's K4 term) + "
    "2400 (vol-steady run 0's trials on the same data, prior look W1); the K4-as-15 description adds 14 more. The "
    "effective count, PBO and the trial-Sharpe variance come from this study's own searches only.",
    "measure": "The volatility measure is the downside deviation around zero (lab.runner.downvol.downside): "
    "sqrt(365) x math.sqrt(2.0 x ss / L) with ss = math.fsum(d x d), d = min(x, 0.0), over the L basket returns of "
    "rows c - L + 1 .. c; it exists from c >= L (x starts at row 1), as VP's; the parse of the params is VP's "
    "(volsteady.parse_params: lookback an integer >= 2, though the downside measure would allow 1; the box and the "
    "plateau never go below 8). attrs['sigma'] and VolPath.sigma hold this measure.",
    "e1_q_only": "E1's null (amendment M1) for shift u: share_u(c_k) = s_fold(c_k) x q(c_((k + u) mod W)) over R_0's W "
    "check closes (downvol.q_shifted), the state pair z (activation, (1, 1) at every check of the span) moving with q, "
    "each check keeping its fold's s, the rows before c_0 unchanged, one book from row 0 (downvol.run_q_shift); the "
    "guarded offsets u = 53 .. W - 1, the rank-p rule (trend.e1_test) and the execution from S's book are VP's. It is "
    "used for E1 at S (both seeds), inside E7 and the leave-one-year-out and bear-year descriptions, for E8 (155 "
    "Binance shifts), at S(s_k), at E9's validate shifts, for B3-lead and the lag rank (descriptions), and in A0 and "
    "the slow calibration. Where s is one value (S(s_k), E9, the fixed points) it equals the whole-schedule shift bit "
    "for bit.",
    "e1_whole": "E1-whole (a description that decides nothing): VP's whole-schedule shifts (trend.shifted: s moving "
    "with q) of R_0, the 207 guarded offsets, E1's rank-p rule, at S for both seeds on Kraken; reported as "
    "seeds.<A|B>.e1_whole, logged as evaluation rows of kind 'shift_whole' (not counted), and in oos.parquet as "
    "percentiles.",
    "narrowing": "Per allowed value: p5 is the deepest of its grid step's and its S(s_k)'s G6 statistic; risk_fail "
    "is G6 failing at either; other_fail is any other failing point of that value (G1, G2, G5(c), G7, G8-excess and "
    "R1 at the grid step, the G5(b) steps at the default's value, G1, G2, E1 and E2 at S(s_k)). A failing non-risk "
    "point measured at S, the search studies or theta_final(A) marks every value (narrowing cannot fix it).",
    "look_due": "freeze.py and run_validate.py refuse unless the reported run's REPORTED look_earned is True "
    "(summary.json results.reported.look_earned; FROZEN.json reported.look_earned): its own verdict earns the look "
    "(E1-E8 and P hold and no stop rule fired; stop rule 8) and so does every earlier run it is reported beside "
    "(INTERPRETATIONS['reported']). Synthetic dry runs may pass --any-verdict.",
    "reported_run": "The reported run is the highest-numbered run; freeze.py refuses unless its summary.json has "
    "status 'complete'. Its reported verdict, headline and look_earned follow INTERPRETATIONS['reported'] (stop rule "
    "18).",
    "reported": "Stop rule 18 over a chain of runs (TP M26), with no stop-loss outcome. An amendment run j with "
    "trigger (a), (b) or (c) supersedes run j - 1 alone: whatever run j - 1 was reported beside stays beside run j. "
    "One with 'other, after the verdict' is reported beside run j - 1 too, so it needs run j - 1 complete (its "
    "verdict known); otherwise it is refused at the start. The runs a run is reported beside (each one's own verdict, "
    "headline, look_earned, E1 rank p and E2 p) are fixed in its start record before any bar. Its reported verdict "
    "and headline are the least favourable of its own and theirs (volsteady.reported_verdict pairwise, ties to the "
    "later run); its reported look_earned is True only if its own and every one of theirs is. At the look, the frozen "
    "run's own verdict and headline after E9 are combined the same way with the same earlier runs' train values, and "
    "that is the look's verdict and headline; the frozen run's own values after E9 are recorded next to them. Every "
    "complete run's E1 rank p and E2 p are listed.",
    "prior_amendments": "A real run_train.py run (run 0 or an amendment run) refuses, after the dirty-tree check and "
    "before the snapshot is read, unless PLAN.md section 15 (INTERPRETATIONS['amendment_section']) holds exactly one "
    "line starting '- **A1' or '- **Amendment A1' that says 'N = <n>' with n the trials per study this build runs "
    "(study.PLAN_SETTINGS.n_trials), and exactly one line starting '- **A0' or '- **Amendment A0' that says either "
    "both 'stop rule 15: no alarm' and 'power: no alarm', or 'owner decision: reports/director/<file>.md' naming a "
    "file that exists (section 14's order of work step 4; TP M27). The plan's placeholder lines '- **A1:**' and "
    "'- **A0:**' are such lines: the dated record is written into them, not added beside them (a second line is "
    "refused). Dry runs are exempt.",
    "triage_before_freeze": "freeze.py refuses a reported run with failed trials (stop rule 4) unless it is given "
    "--triaged '<note>'; FROZEN.json records the note.",
    "missing": "A point whose number (any of its numbers) is NaN is MISSING (None); MISSING fails.",
    "risk_exception": "Stop rule 10's exception compares the coin list, min_cash and max_coin with the train-start "
    "reading and needs the config hash to match once the train-start hash of risk_levels.yaml is put back.",
    "look_hash_check": "run_validate.py also refuses if any file under train/ changed since the freeze, or (real "
    "data) if research/downvol-steady/FROZEN.json is not byte-identical to the results copy, or if FROZEN.json's "
    "summary_sha256, theta_final, fold params, criteria, verdict, own and reported records, points and train "
    "Sharpes are not those of the reported run's summary.json. freeze.py also refuses when the reported run's "
    "recorded beside runs (its start record) are not the ones the earlier summaries give now.",
    "look_failure": "A failed consistency check at the look writes look.json with verdict INCONCLUSIVE and exits "
    "non-zero: the look is spent.",
    "trades_per_parameter": "TP 16's 'kept fill rows / 2' is reported as written (TP's draft's 2 parameters), with "
    "the same over the box's 3 free parameters next to it.",
    "p_count": "P (section 11): per fold run, the share changes (exact float comparison with the share in force at "
    "the close before) at check closes whose orders fill in the fold's kept rows; each fold run's first share change "
    "(from the start share 0, at activation or at the first later check with q > 0) is its first buy and is not "
    "counted (volsteady.power_count). The verdict's LOW POWER label reads 'k share changes'.",
    "whipsaw": "A whipsaw is a counted share change (P's count) whose next counted change in the same fold run returns "
    "to the share in force before it, within 28 days; its cost is the USD cost of the fills of both orders. The total "
    "counts each order once, however many whipsaws share it (TESTING.md #60).",
    "episodes": "A step-back spell is a maximal run of a fold's kept closes where the fold run's q in force is below "
    "1; per spell: its first and last close, the lowest q, the 50/50 basket's compounded close-to-close return over "
    "the spell's rows (the loss avoided while stepped back) and the regret, N0's minus S's log growth over those rows.",
    "r3": "R3 (section 12): the worst kept day, the 1st-percentile day, the share of kept rows with any crypto at "
    "their close, and the share of kept rows at each step q, by the q in force at the row's close. TP's exit delay is "
    "dropped.",
    "active_rescoring": "Each completed trial of each search study is re-scored on its logged returns' rows 15 .. end "
    "(volsteady.FIRST_ACTIVE_ROW): 4 blocks (np.array_split), mean minus 0.5 x std of their Sharpes, -10 when its "
    "logged n_trades < 5; stable_region (k = 10) is rerun on those scores and its choice compared with the study's "
    "in unit distance.",
    "schedule_head": "R_0's rows before its first check close c_0 are fold 0's, row by row: the schedule's head_share "
    "is fold 0's per-row share (volsteady.stitched_schedule), since the share changes weekly from activation on.",
    "correlations": "Rebalance-steady's, trend-steady's and vol-steady's stored stitched S_A are column S_A of "
    "oos.parquet of each study's last complete run under results/<study>/train/; the correlation is on the common closes, MISSING when "
    "not found or on synthetic data.",
    "validate_checks": "The look's schedule holds the validate check closes whose orders fill by 2024-07-01 "
    "(78, 2023-01-02 .. 2024-06-24, TP appendix B): a check on the last close, 2024-07-01, decides nothing and is "
    "left out; R_0 then equals theta's run on the 546 kept rows bit for bit.",
    "throughput_redo": "A1's redo flag (TP 7 rule 3) compares the built adapter's median backtest with trend-steady's "
    "stand-in, 0.0131 s (TP appendix B): downvol-steady has no stand-in of its own.",
    "failed_trials": "Failed trials are counted and listed with Optuna's logged error; the run's numbers stand only "
    "after triage (stop rule 4), which the summary flags.",
}

PINNED = {
    "study": STUDY,
    "section_4_readings": list(SECTION_4_READINGS),
    "branch": BRANCH,
    "budget_pct": BUDGET_PCT,
    "quoted_limits": QUOTED_LIMITS,
    "headroom": V.HEADROOM,
    "f_split": V.F_SPLIT,
    "weekday": V.WEEKDAY,
    "start_state": "all USDC before the first check close c >= L",
    "quarters": list(V.QUARTERS),
    "q_tol": V.Q_TOL,
    "annual_days": V.ANNUAL_DAYS,
    "down_factor": D.DOWN_FACTOR,
    "measure": "downside deviation around zero: sqrt(365) x sqrt(2 x fsum(min(x, 0)^2) / L)",
    "e1_null": "q-only shift: share_u(c_k) = s_fold(c_k) x q(c_((k + u) mod W)) (amendment M1)",
    "warmup": T.WARMUP,
    "lead_guard": T.LEAD_GUARD,
    "first_active_row": V.FIRST_ACTIVE_ROW,
    "specs": [asdict(p) for p in V.SPECS],
    "allowed_s": list(V.ALLOWED_S),
    "search_config": {
        "n_trials": PLAN_SETTINGS.n_trials,
        "n_workers": 1,
        "n_blocks": 4,
        "penalty": 0.5,
        "periods_per_year": 365,
        "min_trades": 5,
    },
    "seeds": SEEDS,
    "fold_seed": "seed + 1000 * i",
    "final_seed": "seed + 5000",
    "folds": {"n": 2190, "train_size": 365, "test_size": 365, "expanding": True, "purge": 0},
    "harness": "H0: walk_forward_optimize(warmup=2190); every run from its panel's row 0",
    "stable_region_k": STABLE_K,
    "data": {
        "source": SOURCE,
        "robustness": ROBUSTNESS,
        "interval": INTERVAL,
        "train_last_close": TRAIN_LAST_CLOSE.isoformat(),
        "validate_last_close": VALIDATE_LAST_CLOSE.isoformat(),
        "bars_content_sha256": BARS_SHA256,
        "panel_sha256": PANEL_SHA256,
        "rows": ROWS,
    },
    "settings": asdict(PLAN_SETTINGS),
    "budgets_minutes": {"run": T.RUN_BUDGET_MINUTES, "controls": T.CONTROLS_BUDGET_MINUTES},
    "run_parts": RUN_PARTS,
    "a0": {
        "panels": A0_PANELS,
        "vol_panels": A0_VOL_PANELS,
        "vol_point": A0_VOL_POINT,
        "alarm_false_positives": A0_ALARM_FP,
        "power_min": A0_POWER_MIN,
    },
    "calibration_points": [list(p) for p in V.CALIBRATION_POINTS],
    "strict_extra": STRICT_EXTRA,
    "prior_trials": PRIOR_TRIALS,
    "r4_books": list(R4_BOOKS),
    "max_amendments": MAX_AMENDMENTS,
    "interpretations": INTERPRETATIONS,
}


# ------------------------------------------------------------------------------------------------ hashing


def frozen_paths() -> list[str]:
    """The repo-relative files of the config hash (PLAN.md section 14), sorted."""
    fixed = [
        "research/downvol-steady/PLAN.md",
        *(f"research/downvol-steady/{name}" for name in SCRIPTS),
        "lab/__init__.py",
        "lab/config.py",
        "lab/data/__init__.py",
        "lab/data/catalog.py",
        "lab/data/external.py",
        "lab/data/futures.py",
        "lab/data/loaders.py",
        "lab/data/panel.py",
        "lab/data/sources.py",
        "lab/data/synthetic.py",
        "lab/runner/__init__.py",
        "lab/runner/downvol.py",
        "lab/runner/interface.py",
        "lab/runner/portfolio.py",
        "lab/runner/reference.py",
        "lab/runner/steady.py",
        "lab/runner/trend.py",
        "lab/runner/volsteady.py",
        *CONFIG_FILES,
        "pyproject.toml",
        "uv.lock",
    ]
    globbed = [
        p.relative_to(REPO).as_posix()
        for d in ("lab/search", "lab/validation")
        for p in (REPO / d).glob("*.py")
    ]
    return sorted(set(fixed) | set(globbed))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hashes(config_dir: Path | None = None) -> dict[str, str]:
    """SHA-256 of every frozen file; the three ``config/*.yaml`` files are read from ``config_dir``."""
    cfg = Path(config_dir) if config_dir is not None else CONFIG_DIR
    return {
        rel: sha256_file(cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel)
        for rel in frozen_paths()
    }


def config_hash(hashes: Mapping[str, str]) -> str:
    """SHA-256 over the per-file hashes (sorted by path) and the pinned values."""
    blob = json.dumps({"files": dict(hashes), "pinned": jsonable(PINNED)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def compare_hashes(
    recorded_files: Mapping[str, str],
    recorded_config: str,
    current_files: Mapping[str, str],
    start_limits: Mapping,
    config_dir: Path | None = None,
) -> dict:
    """Stop rule 10, as rebalance-steady's: ``ok`` when nothing differs; also ``ok`` with an ``exception`` when only
    ``config/risk_levels.yaml`` differs, the config hash matches once its recorded hash is put back, and the Steady
    coins, ``min_cash`` and ``max_coin`` read now are the train-start ones."""
    keys = set(recorded_files) | set(current_files)
    differs = sorted(k for k in keys if recorded_files.get(k) != current_files.get(k))
    out = {"ok": False, "differs": differs, "exception": None}
    if not differs:
        out["ok"] = config_hash(current_files) == recorded_config
        if not out["ok"]:
            out["differs"] = ["<pinned values>"]
        return out
    if differs != [RISK_FILE]:
        return out
    restored = {**current_files, RISK_FILE: recorded_files[RISK_FILE]}
    if config_hash(restored) != recorded_config:
        return out
    try:
        now = sd.steady_limits(config_dir)
    except (ValueError, OSError) as exc:
        out["reason"] = f"risk_limits('steady') no longer reads: {exc}"
        return out
    if not (
        list(now["coins"]) == list(start_limits["coins"])
        and now["min_cash"] == start_limits["min_cash"]
        and now["max_coin"] == start_limits["max_coin"]
    ):
        out["reason"] = "risk_limits('steady') changed its coins, min_cash or max_coin"
        return out
    out["ok"] = True
    out["exception"] = {
        "rule": "stop rule 10: only config/risk_levels.yaml differs and the Steady coins and limits are unchanged",
        "risk_levels_sha256_recorded": recorded_files[RISK_FILE],
        "risk_levels_sha256_now": current_files[RISK_FILE],
        "limits_now": jsonable(now),
        "g6": "keeps its train-start value; never rescored",
        "deviation": "write a Deviations row in RESULTS.md",
    }
    return out


# ------------------------------------------------------------------------------------- git, logs, json


def git_state(repo: Path = REPO) -> dict:
    """``commit`` (full SHA of HEAD), ``dirty`` (INTERPRETATIONS["dirty"]) and the porcelain lines."""

    def run(*args: str) -> str:
        res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {res.stderr.strip()}")
        return res.stdout

    commit = run("rev-parse", "HEAD").strip()
    changes = [line for line in run("status", "--porcelain", "--untracked-files=all").splitlines() if line]
    return {"commit": commit, "dirty": bool(changes), "changes": changes[:50]}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def jsonable(x):
    """Plain JSON types: numpy scalars and arrays, timestamps, tuples; NaN and inf become None."""
    if isinstance(x, Mapping):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, np.bool_ | bool):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, float | np.floating):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def same_json(a, b) -> bool:
    """Equal as JSON (NaN equals NaN; sorted keys)."""
    return json.dumps(jsonable(a), sort_keys=True) == json.dumps(jsonable(b), sort_keys=True)


def write_json(path: Path, obj) -> None:
    """Write ``obj`` as JSON through a temporary file, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(obj), indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def append_runlog(path: Path, entry: Mapping) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(jsonable(entry), sort_keys=True) + "\n")


def runlog_path(out: Path, synthetic: bool) -> Path:
    """The tracked ``RUNLOG.jsonl`` for real runs; ``<out>/RUNLOG.jsonl`` for synthetic dry runs."""
    return Path(out) / "RUNLOG.jsonl" if synthetic else HERE / "RUNLOG.jsonl"


def tracked_dir(out: Path, synthetic: bool) -> Path:
    """Where the committed copies go: this folder for real runs, ``<out>/tracked`` for dry runs."""
    return Path(out) / "tracked" if synthetic else HERE


def runlog_entries(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def amendments_section(plan_text: str) -> str | None:
    """PLAN.md section 15 (INTERPRETATIONS["amendment_section"]): from the line starting '## 15.' to the next line
    starting '## '; None when the heading is missing."""
    start = re.search(r"^## 15\.", plan_text, re.MULTILINE)
    if start is None:
        return None
    end = re.search(r"^## ", plan_text[start.end() :], re.MULTILINE)
    return plan_text[start.start() : start.end() + end.start()] if end else plan_text[start.start() :]


def amendment_row_present(plan_text: str, k: int) -> bool:
    """INTERPRETATIONS["amendment_row"]."""
    section = amendments_section(plan_text)
    if section is None:
        return False
    return bool(re.search(rf"^- \*\*Amendment run {k}\b", section, re.MULTILINE))


OWNER_DECISION_RE = re.compile(r"owner decision: `?(?P<path>reports/director/[\w.-]+\.md)")


def prior_amendments(plan_text: str, n_trials: int, repo: Path = REPO) -> dict:
    """INTERPRETATIONS["prior_amendments"]: amendments A1 (throughput, with the N this build runs) and A0 (the
    procedure controls, with no alarm or an owner decision on file) are in PLAN.md before a real run starts."""
    section = amendments_section(plan_text)
    if section is None:
        raise Refusal("PLAN.md has no section 15 ('## 15.')")
    rows = {
        name: [ln for ln in section.splitlines() if re.match(rf"- \*\*(?:Amendment )?{name}\b", ln)]
        for name in ("A1", "A0")
    }
    for name, what in (("A1", "throughput"), ("A0", "the procedure controls")):
        if len(rows[name]) != 1:
            raise Refusal(
                f"PLAN.md section 15 needs exactly one '- **{name}' line ({what}) before a real run (section 14, "
                f"order of work step 4); found {len(rows[name])}"
            )
    a1, a0 = rows["A1"][0], rows["A0"][0]
    if not re.search(rf"\bN = {int(n_trials)}\b", a1):
        raise Refusal(
            f"amendment A1 does not say 'N = {int(n_trials)}', the trials per study this build runs "
            "(study.PLAN_SETTINGS.n_trials; stop rule 3): fix the build or the amendment first"
        )
    decision = OWNER_DECISION_RE.search(a0)
    if decision is not None and not (Path(repo) / decision["path"]).is_file():
        raise Refusal(f"amendment A0 names an owner decision {decision['path']} that does not exist")
    no_alarm = "stop rule 15: no alarm" in a0 and "power: no alarm" in a0
    if decision is None and not no_alarm:
        raise Refusal(
            "amendment A0 says neither 'stop rule 15: no alarm' and 'power: no alarm', nor 'owner decision: "
            "reports/director/<file>.md': after an alarm, run 0 waits for the owner's written decision (stop rule "
            "15; section 9)"
        )
    return {"A1": a1, "A0": a0, "owner_decision": None if decision is None else decision["path"]}


OTHER = TRIGGERS[-1]  # "other, after the verdict"
OWN_KEYS = ("verdict", "headline", "look_earned", "e1_rank_p", "e2_p")


def run_summary(train: Path, j: int) -> dict:
    return json.loads((Path(train) / f"run{j}" / "summary.json").read_text())


def beside_runs(train: Path, k: int, trigger: str | None) -> list[dict]:
    """INTERPRETATIONS["reported"]: the earlier runs that run ``k`` is reported beside, oldest first, each as
    ``{"run": j, **its own record}``. ``trigger`` is run k's; earlier runs' come from their start records."""
    beside: list[dict] = []
    for j in range(1, k + 1):
        t = trigger if j == k else run_summary(train, j)["start"].get("trigger")
        if t not in TRIGGERS:
            raise Refusal(f"stop rule 18: amendment run {j} has no trigger in {TRIGGERS} (got {t!r})")
        if t != OTHER:
            continue
        prev = run_summary(train, j - 1)
        own = prev.get("results", {}).get("own") if prev.get("status") == "complete" else None
        if own is None:
            raise Refusal(
                f"stop rule 18: amendment run {j}'s trigger is {OTHER!r}, but run {j - 1} has no verdict (status "
                f"{prev.get('status')!r}); a rerun after a crash or a stop is trigger (a)"
            )
        beside.append({"run": j - 1, **{key: own[key] for key in OWN_KEYS}})
    return beside


def outcome_base(label: str, order: Sequence[str]) -> str:
    """The outcome a printed label stands for ("NO EDGE (LOW POWER: 3 switches)" -> "NO EDGE")."""
    hits = [base for base in order if label == base or label.startswith(base + " (")]
    if not hits:
        raise ValueError(f"unknown outcome {label!r}; expected one of {tuple(order)}")
    return hits[-1]


def combine_reported(beside: Sequence[Mapping], own: Mapping) -> dict:
    """INTERPRETATIONS["reported"]: the least favourable verdict and headline of ``own`` and every run in ``beside``
    (``volsteady.reported_verdict`` pairwise, ties to the later run); look_earned only if all earn it."""
    out = {key: own[key] for key in ("verdict", "headline", "e1_rank_p", "e2_p")}
    for b in reversed(beside):
        rv = V.reported_verdict(b, out, OTHER)
        out.update({key: rv[key] for key in ("verdict", "headline")})
    earned = own["look_earned"] is True and all(b["look_earned"] is True for b in beside)
    return {key: out[key] for key in ("verdict", "headline")} | {"look_earned": earned}


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path) -> None:
    """A synthetic dry run (or A0, or the timing) never writes into the study's results folder or the repo."""
    where = Path(out).resolve()
    if where == DEFAULT_OUT.resolve() or _inside(where, REPO.resolve()):
        raise Refusal(
            f"--out-dir {out}: a synthetic run never writes into {DEFAULT_OUT} or inside the repo (PLAN.md section "
            "14); use a scratch folder"
        )


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path | None = None) -> None:
    """Real runs use the pinned folders only (INTERPRETATIONS["paths"])."""
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT} (PLAN.md section 14)")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(
            f"--config-dir {config_dir}: a real run reads config/costs.yaml, splits.yaml and risk_levels.yaml only"
        )
    if catalog_dir is not None and Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(
            f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG} (PLAN.md section 3)"
        )


def check_paths(out: Path, config_dir: Path | None, catalog_dir: Path | None, synthetic: bool) -> None:
    if synthetic:
        check_out_dir(out)
    else:
        check_real_paths(out, config_dir, catalog_dir)


# ----------------------------------------------------------------------------- the branch, feasibility, timing


def plan_branch(plan_text: str) -> dict:
    """The header's branch line (INTERPRETATIONS["branch"]): ``{"branch": "R", "budget_pct": 35}``."""
    m = re.search(r"^- (?:\*\*)?Branch: (?P<branch>[A-Z])\b(?P<rest>.*)$", plan_text, re.MULTILINE)
    if m is None:
        raise Refusal("stop rule 11: PLAN.md has no '- Branch: ' line")
    budget = re.search(r"\*\*(\d+)%\*\*", m["rest"])
    return {"branch": m["branch"], "budget_pct": int(budget[1]) if budget else None}


def check_branch(limits: Mapping, plan_text: str) -> dict:
    """Stop rule 11 before any bar: Branch R, and ``risk_limits("steady")`` as the header quotes it."""
    line = plan_branch(plan_text)
    if line["branch"] != BRANCH:
        raise Refusal(
            f"stop rule 11: PLAN.md's branch is {line['branch']}; this build runs Branch {BRANCH} only, and the branch "
            "never changes after run 0"
        )
    if line["budget_pct"] != BUDGET_PCT:
        raise Refusal(
            f"stop rule 11: the branch line quotes a budget of {line['budget_pct']}%, not {BUDGET_PCT}%"
        )
    read = {
        "max_drawdown_budget": limits.get("max_drawdown_budget"),
        "min_cash": limits.get("min_cash"),
        "max_coin": limits.get("max_coin"),
        "coins": sorted(limits.get("coins", ())),
    }
    want = {
        "max_drawdown_budget": BUDGET_PCT / 100,
        "min_cash": QUOTED_LIMITS["min_cash"],
        "max_coin": QUOTED_LIMITS["max_coin"],
        "coins": sorted(QUOTED_LIMITS["coins"]),
    }
    if read != want:
        raise Refusal(f"stop rule 11: risk_limits('steady') reads {read}, the plan quotes {want}")
    return {
        **line,
        "limits_read": read,
        "risk_levels_sha256": limits.get("sha256"),
        "sha256_as_quoted": limits.get("sha256") == RISK_SHA256_QUOTED,
    }


def timing_panel() -> pd.DataFrame:
    return make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")


def measure_timing(limits: Mapping, costs: Costs, settings: Settings, n_trials: int) -> dict:
    """INTERPRETATIONS["projection"]: CPU seconds per unit of volsteady.TIMING_KEYS."""
    panel = timing_panel()
    fn = partial(D.downvol_backtest, limits=limits, costs=costs)
    cfg = SearchConfig(n_trials=settings.timing_trials, n_workers=1, seed=0)
    with tempfile.TemporaryDirectory() as tmp:
        c0 = time.process_time()
        run_study("timing", fn, list(V.SPECS), panel, tmp, cfg)
        study = (time.process_time() - c0) * n_trials / settings.timing_trials
    ts = []
    for _ in range(settings.timing_reps):
        c = time.process_time()
        fn(dict(A0_VOL_POINT), panel)
        ts.append(time.process_time() - c)
    run = float(np.median(ts))
    rng = np.random.default_rng(0)
    idx = pd.RangeIndex(1820)
    a, b = pd.Series(rng.normal(0, 0.02, 1820), index=idx), pd.Series(rng.normal(0, 0.02, 1820), index=idx)
    c = time.process_time()
    sd.paired_bootstrap(a, b, n_resamples=10_000, mean_block=60, seed=0)
    boot = time.process_time() - c
    return {
        "seconds": {"study": study, "run": run, "bootstrap": boot},
        "timing_trials": settings.timing_trials,
        "timing_reps": settings.timing_reps,
        "n_trials": n_trials,
    }


def projection(timing: Mapping, counts: Mapping[str, int], budget: float) -> dict:
    minutes = V.project_cpu_minutes(timing["seconds"], counts)
    return {"cpu_minutes": minutes, "budget_minutes": budget, "allows": T.projection_allows(minutes, budget)}


# -------------------------------------------------------------------------------------------- the data


def read_snapshot(catalog_dir: Path, synthetic: bool) -> dict:
    """``snapshot_id`` and ``bars_content_sha256`` from ``SNAPSHOT.json`` (no bar is read); stop rule 2 refuses
    another bars hash. Synthetic dry runs read nothing."""
    if synthetic:
        return {"snapshot_id": "synthetic", "bars_content_sha256": "synthetic"}
    path = Path(catalog_dir) / catalog.SNAPSHOT_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc
    snap = {"snapshot_id": data.get("snapshot_id"), "bars_content_sha256": data.get("bars_content_sha256")}
    if snap["bars_content_sha256"] != BARS_SHA256:
        raise Refusal(
            f"stop rule 2: the catalog's bars hash {snap['bars_content_sha256']!r} is not {BARS_SHA256} (PLAN.md "
            "section 3): amend the plan"
        )
    return snap


SYNTHETIC_FIRST = "2017-01-02"
SYNTHETIC_DAYS = 2738  # closes 2017-01-02 .. 2024-07-01, the Kraken grid of DATA.md
SYNTHETIC_GAP = pd.Timestamp("2018-01-13", tz="UTC")  # Kraken ETH has no bar there (DATA.md)
SYNTHETIC_BINANCE_FIRST = pd.Timestamp("2017-08-18", tz="UTC")
_SYNTHETIC_IDS = {
    "BTC/USD.KRAKEN": (SOURCE, "BTC"),
    "ETH/USD.KRAKEN": (SOURCE, "ETH"),
    "BTCUSDT.BINANCE": (ROBUSTNESS, "BTC"),
    "ETHUSDT.BINANCE": (ROBUSTNESS, "ETH"),
}


def synthetic_bar_loader(seed: int) -> Callable:
    """A stand-in for ``lab.data.catalog.load_bars`` serving SYNTHETIC daily bars (``synthetic_market``) on the
    plan's date grid, for dry runs and tests only: Kraken from close 2017-01-02 with ETH's 2018-01-13 bar missing,
    Binance from close 2017-08-18 (Kraken's bars times a small per-bar factor). A longer load starts with a shorter
    one. Snapshot id ``"synthetic"``."""
    market: dict[str, pd.DataFrame] = {}

    def full() -> dict[str, pd.DataFrame]:
        if not market:
            market.update(synthetic_market(SYNTHETIC_DAYS, seed=seed, start=SYNTHETIC_FIRST))
        return market

    def loader(instrument, interval, start=None, end=None, catalog_dir=None) -> pd.DataFrame:
        if interval != INTERVAL or instrument not in _SYNTHETIC_IDS:
            raise ValueError(f"synthetic loader: no {instrument!r} {interval!r} bars")
        source, asset = _SYNTHETIC_IDS[instrument]
        bars = full()[asset].copy()
        bars.index = pd.DatetimeIndex(bars.index, name="ts").as_unit("us")
        if source == SOURCE and asset == "ETH":
            bars = bars.drop(SYNTHETIC_GAP)
        if source == ROBUSTNESS:
            rng = np.random.default_rng([seed, 7, ("BTC", "ETH").index(asset)])
            factor = np.exp(rng.normal(0.0, 0.001, len(bars)))
            for col in ("open", "high", "low", "close"):
                bars[col] = bars[col].to_numpy() * factor
            bars = bars.loc[SYNTHETIC_BINANCE_FIRST:]
        if start is not None:
            bars = bars.loc[pd.Timestamp(start) :]
        if end is not None:
            bars = bars.loc[: pd.Timestamp(end)]
        bars.attrs = {
            "snapshot_id": "synthetic",
            "bar_type": catalog.bar_type(instrument, interval),
            "instrument": instrument,
        }
        return bars

    return loader


def load_study_panel(
    source: str,
    last_close: pd.Timestamp,
    *,
    catalog_dir: Path,
    config_dir: Path | None,
    loader: Callable | None,
) -> pd.DataFrame:
    """``load_panel(source, "1d", last_close=...)`` (its guard refuses the test window), checked again here."""
    if last_close > VALIDATE_LAST_CLOSE:
        raise HoldoutWindowError(f"last_close {last_close} is after {VALIDATE_LAST_CLOSE} (the test window)")
    panel = load_panel(
        source, INTERVAL, last_close=last_close, catalog_dir=catalog_dir, config_dir=config_dir, loader=loader
    )
    if panel.index.max() > last_close or panel.index.max() > holdout_cut(config_dir):
        raise HoldoutWindowError(f"{source}: a close after {last_close} was loaded")
    return panel


def panel_record(panel: pd.DataFrame) -> dict:
    al = panel.attrs["alignment"]
    return {
        "hash": sd.panel_hash(panel),
        "rows": len(panel),
        "first": panel.index[0].isoformat(),
        "last": panel.index[-1].isoformat(),
        "snapshot_id": panel.attrs["snapshot_id"],
        "instruments": panel.attrs["instruments"],
        "dropped": {a: al["dropped"][a]["closes"] for a in al["dropped"]},
        "missing": al["missing"]["closes"],
    }


def search_config(seed: int, settings: Settings) -> SearchConfig:
    return SearchConfig(
        n_trials=settings.n_trials,
        n_workers=1,
        n_blocks=4,
        penalty=0.5,
        seed=seed,
        periods_per_year=365,
        min_trades=5,
    )


def study_tag(seed: int, run: int) -> str:
    """``downvol-steady-s<seed>`` (run 0) or ``downvol-steady-s<seed>_a<run>`` (section 7)."""
    return f"{STUDY}-s{seed}" + (f"_a{run}" if run else "")


def parse_study(name: str) -> dict:
    m = STUDY_RE.match(name)
    if not m:
        return {"seed": None, "run": None, "part": None}
    return {"seed": int(m["seed"]), "run": int(m["run"] or 0), "part": m["part"]}


def study_dirs(train_dir: Path) -> list[str]:
    train_dir = Path(train_dir)
    if not train_dir.is_dir():
        return []
    return sorted(p.name for p in train_dir.iterdir() if (p / "study.journal").is_file())


def plain_params(params: Mapping) -> dict:
    """The 3 vol params as plain Python numbers (``lookback`` an int)."""
    look = float(params["lookback"])
    if look != int(look):
        raise ValueError(f"lookback must be integral, got {params['lookback']!r}")
    return {
        "lookback": int(look),
        "target_vol": float(params["target_vol"]),
        "crypto_share": float(params["crypto_share"]),
    }


def trial_table(train_dir: Path, studies: Sequence[str]) -> pd.DataFrame:
    """Every trial (every state) of ``studies``, read from the journals: study, run, seed, part, number, state,
    value, the 3 params, sharpe, n_trades, the block Sharpes, ``fail_reason`` (filled by run_train.py from
    :class:`FailureLog`) and the study's context as JSON."""
    import optuna
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend

    rows = []
    for name in studies:
        path = Path(train_dir) / name / "study.journal"
        study = optuna.load_study(study_name=name, storage=JournalStorage(JournalFileBackend(str(path))))
        tag = parse_study(name)
        context = json.dumps(jsonable(study.user_attrs), sort_keys=True)
        for t in study.trials:
            p = t.params
            blocks = t.user_attrs.get("block_sharpes") or []
            rows.append(
                {
                    "study": name,
                    "run": tag["run"],
                    "seed": tag["seed"],
                    "part": tag["part"],
                    "number": t.number,
                    "state": t.state.name,
                    "value": t.value if t.value is not None else np.nan,
                    **{f"params_{k}": p.get(k, np.nan) for k in V.PARAM_NAMES},
                    "sharpe": t.user_attrs.get("sharpe", np.nan),
                    "n_trades": t.user_attrs.get("n_trades", np.nan),
                    **{f"block_sharpe_{i}": blocks[i] if i < len(blocks) else np.nan for i in range(4)},
                    "fail_reason": "",
                    "datetime_start": str(t.datetime_start),
                    "context": context,
                    "label": LABEL,
                }
            )
    return pd.DataFrame(rows)


class FailureLog(logging.Handler):
    """Optuna's "Trial N failed ..." warnings while it is entered (Optuna stores no reason with a failed trial)."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "failed with parameters" in message:
            tb = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
            self.records.append({"utc": utc_now(), "message": message, "traceback": tb[-4000:]})

    def __enter__(self) -> FailureLog:
        logging.getLogger("optuna").addHandler(self)
        return self

    def __exit__(self, *exc) -> None:
        logging.getLogger("optuna").removeHandler(self)


def failure_reason(row: Mapping, records: Sequence[Mapping]) -> str:
    """The logged error of a failed trial: the record starting "Trial <n> failed with parameters: <params>"."""
    params = plain_params({k: row[f"params_{k}"] for k in V.PARAM_NAMES})
    head = f"Trial {int(row['number'])} failed with parameters: {params}"
    found = [r["message"] for r in records if r["message"].startswith(head)]
    return found[0] if found else ""


# ---------------------------------------------------------------------------------------- the numbers


def sharpe(r) -> float:
    return stats.annualized_sharpe(np.asarray(r, dtype=float), 365)


def series_metrics(r) -> dict:
    x = np.asarray(r, dtype=float)
    return {
        "rows": int(x.size),
        "sharpe": sharpe(x),
        "total_return": float(np.prod(1.0 + x) - 1.0) if x.size else math.nan,
        "max_drawdown": mc.max_drawdown(x),
        "worst_day": float(x.min()) if x.size else math.nan,
    }


def kept_of(result: pd.DataFrame, t0) -> pd.Series:
    """``result["ret"].loc[t0:].iloc[1:]`` with no attrs (``steady.kept_returns``)."""
    return sd.kept_returns(result, pd.Timestamp(t0))


def stitch(results: Sequence[pd.DataFrame], windows: Sequence) -> pd.Series:
    return pd.concat([kept_of(r, w.t0) for r, w in zip(results, windows, strict=True)])


def on_kept(result: pd.DataFrame, kept: pd.DatetimeIndex) -> pd.Series:
    out = result["ret"].loc[kept].copy()
    out.attrs = {}
    return out


def missing(*numbers) -> bool:
    return any(x is None or (isinstance(x, float | np.floating) and math.isnan(x)) for x in numbers)


def point(value, *numbers):
    """A measurement point: True or False, or None (MISSING) when one of its numbers is NaN."""
    return None if missing(*numbers) else bool(value)


def status(value) -> str:
    return "PASS" if value is True else ("MISSING" if value is None else "FAIL")


def plain(x):
    out = x.copy()
    out.attrs = {}
    return out


# --------------------------------------------------------------------------------- the harness bundles


def windows_of(index: pd.DatetimeIndex) -> list[sd.Window]:
    """The 5 fold windows of ``walk_forward(2190, 365, 365, expanding=True)`` in H0."""
    return T.fold_windows(index)


def span_of(panel: pd.DataFrame, windows: Sequence, like: pd.DataFrame | None = None) -> pd.DataFrame:
    """The panel's rows from its own first close to the last window's last close (R_0's span)."""
    return T.h0_slice(panel, (windows[0].t0, windows[-1].last), like=like)


class Tally:
    """How many executor runs of each kind a run made (recorded next to the projection's table)."""

    def __init__(self):
        self.n = {"rule": 0, "comparator": 0, "bootstrap": 0}

    def add(self, key: str, k: int = 1) -> None:
        self.n[key] += k


def offsets_of(offsets: str | Sequence[int], w: int) -> list[int]:
    """``"all"``: u = 1 .. W - 1 (the guarded shifts and B3-lead); ``"guarded"``: u = G + 1 .. W - 1; else as given."""
    if offsets == "all":
        return list(range(1, w))
    if offsets == "guarded":
        return T.guarded_offsets(w).tolist()
    return [int(u) for u in offsets]


def _same_book(a: pd.DataFrame, b: pd.DataFrame, t0, what: str) -> None:
    if not T.same_book_at(a, b, t0):
        raise Stop(
            f"stop rule 14: {what} does not hold S's book at close {pd.Timestamp(t0).date()} bit for bit"
        )


def plain_bundle(
    panel: pd.DataFrame,
    windows: Sequence,
    params: Sequence[Mapping],
    *,
    limits: Mapping,
    costs1: Costs,
    costs2: Costs | None,
    like: pd.DataFrame | None = None,
    offsets: str | Sequence[int] = (),
    whole: str | Sequence[int] = (),
    n0: bool = True,
    x: bool = True,
    tally: Tally | None = None,
    what: str = "S",
) -> dict:
    """S (one H0 run per fold, stitched) and its comparators on ``panel`` (section 9): R_0 (S's share schedule, one
    book from row 0), E1's q-only shifts ``offsets`` (amendment M1; kept returns), the whole-schedule shifts ``whole``
    (E1-whole, a description; kept returns), N0 (and N0 at 2x from S at 2x) and X per fold, with stop rules 13
    (orders equal at 1x and 2x) and 14 (common start; R_0 equals S on the first fold's kept rows) checked."""
    tally = tally or Tally()
    fn1 = partial(D.downvol_backtest, limits=limits, costs=costs1)
    slices = [T.h0_slice(panel, w, like=like) for w in windows]
    runs = [fn1(dict(p), piece) for p, piece in zip(params, slices, strict=True)]
    tally.add("rule", len(runs))
    s = stitch(runs, windows)
    out = {"runs": runs, "slices": slices, "S": s, "kept": s.index, "params": [dict(p) for p in params]}
    if costs2 is not None:
        fn2 = partial(D.downvol_backtest, limits=limits, costs=costs2)
        runs2 = [fn2(dict(p), piece) for p, piece in zip(params, slices, strict=True)]
        tally.add("rule", len(runs2))
        for i, (a, b) in enumerate(zip(runs, runs2, strict=True)):
            if a.attrs["order_hash"] != b.attrs["order_hash"]:
                raise Stop(f"stop rule 13: {what} fold {i}: the orders at 2x differ from those at 1x")
        out.update(runs2=runs2, S2=stitch(runs2, windows))
    span = span_of(panel, windows, like=like)
    shares = [float(p["crypto_share"]) for p in params]
    steps = D.stitched_steps(
        span.index,
        windows,
        [r.attrs["z"] for r in runs],
        [r.attrs["share"] for r in runs],
        [r.attrs["q"] for r in runs],
        shares,
    )
    sched = steps.schedule
    r0 = T.run_span(span, sched, limits=limits, costs=costs1)
    tally.add("comparator")
    _same_book(r0, runs[0], windows[0].t0, f"{what}'s R_0")
    first = kept_of(runs[0], windows[0].t0)
    if not np.array_equal(r0["ret"].loc[first.index].to_numpy(), first.to_numpy()):
        raise Stop(f"stop rule 14: {what}'s R_0 is not S on the first fold's kept rows bit for bit")
    shifts, whole_shifts = {}, {}
    for u in offsets_of(offsets, len(sched.checks)):
        res = D.run_q_shift(span, steps, limits=limits, costs=costs1, u=int(u))
        tally.add("comparator")
        _same_book(res, runs[0], windows[0].t0, f"{what}'s q-only shift u = {u}")
        shifts[int(u)] = res["ret"].loc[s.index].to_numpy(dtype=float)
    for u in offsets_of(whole, len(sched.checks)):
        res = T.run_span(span, sched, limits=limits, costs=costs1, u=int(u))
        tally.add("comparator")
        _same_book(res, runs[0], windows[0].t0, f"{what}'s whole-schedule shift u = {u}")
        whole_shifts[int(u)] = res["ret"].loc[s.index].to_numpy(dtype=float)
    out.update(
        span=span,
        steps=steps,
        schedule=sched,
        R0_run=r0,
        R0=on_kept(r0, s.index),
        shifts=shifts,
        whole_shifts=whole_shifts,
        W=len(sched.checks),
    )
    if n0:
        n0_runs = []
        for i, (w, piece, r) in enumerate(zip(windows, slices, runs, strict=True)):
            n0_runs.append(
                T.always_in_n0(
                    piece,
                    r.attrs["targets"],
                    w.t0,
                    shares[i],
                    limits=limits,
                    costs=costs1,
                    base_states=r.attrs["z"],
                )
            )
            _same_book(n0_runs[-1], r, w.t0, f"{what}'s N0 fold {i}")
        tally.add("comparator", len(n0_runs))
        out.update(n0_runs=n0_runs, N0=stitch(n0_runs, windows))
        if costs2 is not None:
            n02 = [
                T.always_in_n0(
                    piece,
                    r.attrs["targets"],
                    w.t0,
                    shares[i],
                    limits=limits,
                    costs=costs2,
                    base_states=r.attrs["z"],
                )
                for i, (w, piece, r) in enumerate(zip(windows, slices, out["runs2"], strict=True))
            ]
            tally.add("comparator", len(n02))
            for i, (a, r) in enumerate(zip(n02, out["runs2"], strict=True)):
                _same_book(a, r, windows[i].t0, f"{what}'s N0 at 2x fold {i}")
            out["N0_2"] = stitch(n02, windows)
    if x:
        xs, infos = [], []
        for i, (w, piece, r) in enumerate(zip(windows, slices, runs, strict=True)):
            run, info = T.exposure_x(piece, r, w.t0, limits=limits, costs=costs1)
            _same_book(run, r, w.t0, f"{what}'s X fold {i}")
            xs.append(run)
            infos.append(info)
        tally.add("comparator", len(xs))
        out.update(x_runs=xs, X=stitch(xs, windows), x_info=infos)
    return out


def fixed_n0(
    panel: pd.DataFrame, run: pd.DataFrame, windows: Sequence, share: float, *, limits: Mapping, costs: Costs
) -> pd.Series:
    """INTERPRETATIONS["grid_n0"]: a fixed run's own N0 per fold, stitched on the kept rows."""
    parts = []
    for i, w in enumerate(windows):
        piece = T.h0_slice(panel, w)
        n = len(piece)
        res = T.always_in_n0(
            piece,
            run.attrs["targets"][:n],
            w.t0,
            share,
            limits=limits,
            costs=costs,
            base_states=run.attrs["z"][:n],
        )
        _same_book(res, run, w.t0, f"a fixed run's N0 fold {i}")
        parts.append(kept_of(res, w.t0))
    return pd.concat(parts)


# --------------------------------------------------------------------------------- criteria from series


def e1(bundle: Mapping, keep=None) -> dict:
    """E1 on a bundle's R_0 and its guarded q-only shifts (amendment M1)."""
    return T.e1_test(bundle["R0"].to_numpy(dtype=float), bundle["shifts"], bundle["W"], keep=keep)


def e1_whole(bundle: Mapping) -> dict:
    """E1-whole, a description: E1's rule on R_0 and its guarded whole-schedule shifts (VP's shift)."""
    return T.e1_test(bundle["R0"].to_numpy(dtype=float), bundle["whole_shifts"], bundle["W"])


def e1_numbers(res: Mapping) -> dict:
    keys = ("sharpe", "p5", "p50", "p95", "rank_p", "n_shifts", "at_or_above", "holds", "p95_holds")
    return {k: res[k] for k in keys}


def e2_numbers(res: Mapping) -> dict:
    return {k: res[k] for k in ("d", "p", "holds", "n_resamples", "mean_block", "seed")}


def g6_of(r) -> float:
    return T.g6_statistic(np.asarray(r, dtype=float))


def masked(series: pd.Series, mask) -> pd.Series:
    return series[np.asarray(mask, dtype=bool)]


def drawdown_of(r) -> float:
    return mc.max_drawdown(np.asarray(r, dtype=float))


def overshoot(w_btc, w_eth, limits: Mapping) -> dict:
    """R2: lowest cash, highest single-coin weight, most crypto, and the closes in breach of the limits."""
    wb, we = np.asarray(w_btc, dtype=float), np.asarray(w_eth, dtype=float)
    breach = (
        (wb + we > 1.0 - limits["min_cash"] + LIMIT_TOL)
        | (wb > limits["max_coin"] + LIMIT_TOL)
        | (we > limits["max_coin"] + LIMIT_TOL)
    )
    return {
        "lowest_cash": float(np.min(1.0 - wb - we)),
        "highest_coin": float(np.max(np.maximum(wb, we))),
        "most_crypto": float(np.max(wb + we)),
        "closes_in_breach": int(breach.sum()),
    }


def unit_distance(p: Mapping, q: Mapping) -> float:
    return float(math.sqrt(sum((s.to_unit(p[s.name]) - s.to_unit(q[s.name])) ** 2 for s in V.SPECS)))


def with_share(params: Mapping, share: float) -> dict:
    return {**plain_params(params), "crypto_share": float(share)}


def costs_for(config_dir: Path | None, book: float = REF_BOOK) -> Costs:
    return Costs.from_yaml(None if config_dir is None else Path(config_dir) / "costs.yaml", capital_usd=book)


ASSET_NAMES = ASSETS


# --------------------------------------------------------------------------------- orders and risk


def fixed_log(res: pd.DataFrame, kept: pd.DatetimeIndex) -> pd.DataFrame:
    log = T.order_log(res)
    return log[pd.DatetimeIndex(log["filled"]).isin(kept)].reset_index(drop=True)


def frequency(log: pd.DataFrame, kept: pd.DatetimeIndex, windows) -> dict:
    """The trade-frequency table (section 16): overall and per fold (that fold's kept closes)."""
    out = {"overall": T.trade_frequency(log, kept)}
    for i, w in enumerate(windows):
        fold_kept = kept[(kept > w.t0) & (kept <= w.last)]
        out[f"fold {i}"] = T.trade_frequency(log, fold_kept)
    return out


def r2_r5(limits: Mapping, rows: pd.DataFrame, log: pd.DataFrame, q) -> dict:
    """R2, R3 and R5 over the kept rows ``rows`` (ret and weights), with the kept-row order log and the q in force at
    each kept row's close (INTERPRETATIONS["r3"])."""
    wb, we = rows["w_BTC"].to_numpy(), rows["w_ETH"].to_numpy()
    qq = np.asarray(q, dtype=float)
    if qq.shape != wb.shape:
        raise ValueError("r2_r5: one q per kept row")
    cash = (wb + we) == 0.0
    stretch, best = 0, 0
    for flag in cash.tolist():
        stretch = stretch + 1 if flag else 0
        best = max(best, stretch)
    r = rows["ret"].to_numpy()
    return {
        "R2": {**overshoot(wb, we, limits), "limit_fixes": int((log["reason"] == "limit").sum())},
        "R3": {
            "worst_day": float(r.min()),
            "day_p1": float(np.percentile(r, 1)),
            "days_with_crypto": float(np.mean((wb + we) > 0.0)),
            "days_at_q": {f"{x:g}": float(np.mean(qq == x)) for x in V.QUARTERS},
        },
        "R5": {"days_all_usdc": float(cash.mean()), "longest_all_usdc_rows": int(best)},
    }


def frozen_numbers(results: dict) -> dict:
    """The numbers FROZEN.json holds from the reported run's summary (and the look checks against it)."""
    return {
        "theta_final": results["theta_final"],
        "fold_params": {lab: s["params"] for lab, s in results["seeds"].items()},
        "criteria": results["criteria"],
        "verdict": results["verdict"],
        "own": results["own"],
        "reported": results["reported"],
        "points": results["points"],
        "gates": results["gates"],
        "train_sharpe": {lab: s["sharpe"] for lab, s in results["seeds"].items()},
        "p_changes": results["seeds"]["A"]["P"]["total"],
        "default": results["default"],
    }

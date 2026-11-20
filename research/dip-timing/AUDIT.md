# Dip timing ("option C"): audit of the study's integrity

> **SCOUTING ONLY.** The study's profit numbers come from the reference backtester, not from NautilusTrader
> (AGENTS.md hard rule 3; the Nautilus runner is on hold). This is an audit of whether the study was run
> honestly and computed correctly. It is **not** a strategy audit, and nothing here goes into `reports/<strategy>/`.
> **The test window was not opened.** It is not burned for any strategy built from this study.

Audited 2026-11-20 by `backtest-auditor`. I treated [RESULTS.md](RESULTS.md) as unverified and recomputed its
numbers from the logged outputs and the raw data with my own code. Inputs:

- [PLAN.md](PLAN.md), committed in `f8d4208` before any result existed. It was later changed only by the
  data-engineer's look row `0a` (`62b2f11`).
- The code at HEAD `62b2f11` plus uncommitted changes.
  - Frozen config hash: `0cda419180466c5b2f677bca923c6877c7ac4bedcb20dcdc88e8020c1e904c3a`. It was the same at the
    train run, at the freeze, at the validate look and when this audit ended.
  - The train outputs still match the SHA-256 values in `results/dip-timing/FROZEN.json`.
- Data snapshot `1746a21b75683e76`. Its bars content hash is `08f5ca2c…`, the same as the hash of
  `b08377c310126e3f`, the snapshot PLAN.md names.
- My scripts are in [audit/](audit/). Run them from the repo root with `uv run python research/dip-timing/audit/<script>.py`.

## Verdict

**Study integrity: PASS.** All 7 checks pass:
- The test window was never read.
- There is no look-ahead in the features, the positioning data, the labels or the entry decisions.
- Costs are on, and every fill is at the next open.
- Every variant is counted. PBO and DSR come out the same when I recompute them with my own code.
- Every deviation from the plan is either disclosed or harmless.
- RESULTS.md's numbers come out the same when recomputed.
- **NO EDGE** follows from the pre-registered rules.

There are 4 text corrections to RESULTS.md and 2 housekeeping items (section "Findings"). None of them changes a
number that decides the verdict.

**Strategy verdict (the auditor's two-way format): RETURN TO RESEARCHER.**
- There is no candidate. No variant passes criterion 1 (every Holm p is 1.0000) or criteria 1-3 together.
- DSR is 0.367 (effective count) and 0.144 (raw count), against a pass mark of 0.95. PBO is 0.306, against a limit
  of 0.25.
- Nothing goes to `risk-officer`. Only a new pre-registration could change this; no fix to this study would.

## Checks

| # | Check | Result | Evidence (details below) |
|---|---|---|---|
| 1 | Test window never touched | **PASS** | Every data read goes through `dips.load_study_bars` / `load_study_positioning`. Requests after 2024-07-01 00:00 UTC are refused before anything loads (bars and positioning; 1 µs, 1 h, 1 day and 2026 past the cut). A loader that returns a 2024-07-02 bar raises an error. The raw Nautilus query capped at the cut returns at most 2024-07-01 00:00. The newest stored positioning value was known at 2024-06-30 23:55. The newest bar in the stored outputs: train 2023-01-01, validate 2024-06-02. |
| 2 | No look-ahead | **PASS** | I tampered the real train bars from 25 random cut times on and replaced them with random junk. Everything known before the cut stayed bit-identical (1055 events, 10454 day rows, 11341 labels, 4220 rule-target vectors, 75 model fits). A planted 1-bar leak failed this same check at 5 of the 25 cuts, so the check can find a leak. Positioning recomputed from the raw rows equals the lab's on all 4381 train closes. The newest value used was known 5 min before the close. Changing every raw value known at or after 60 random closes changed no earlier row. CPCV purge and embargo: an independent splitter gives the same splits, with 0 violations. Label columns never enter features. |
| 3 | Costs on, fills at the next open | **PASS** | My own fill and cost code, with costs read from `config/costs.yaml`, reproduces T1, T2, T3 and T4 for all 80 events (max diff 1.8e-15) and T1 at 2x costs (+3.3254%). The strategy-level T1 matches the logged daily series to 6.7e-16. The cost values are still the placeholders. |
| 4 | Every variant counted; DSR and PBO recomputed | **PASS** | 40 rows in `trials.jsonl`, `trials.parquet` and `trials.csv`. They match the plan's V01-V40 list one to one, all with status ok, under one config hash. My own CSCV gives a PBO of 0.3175 / 0.3294 / 0.2897 / 0.3214 / 0.2738 on the 5 paths (mean 0.3063). I also get 5.521 effective trials and a DSR of 0.3670 (effective count) and 0.1439 (raw count). Counting the uncounted reference runs too moves the raw DSR to 0.1406 or 0.1269. |
| 5 | Plan followed | **PASS** | All 7 deviations RESULTS.md lists are justified, and so are the interpretations it lists, which were fixed before the run. I found 2 more, both minor (F4, F6). Nothing was tuned after a look, and the hashed code did not change between the train run and the look. |
| 6 | RESULTS.md matches the numbers | **PASS** | More than 40 numbers recomputed (section 6) all match. There are 4 wording errors (F1-F3, F4) and no wrong number that matters. |
| 7 | The verdict follows the pre-registered criteria | **PASS** | NO EDGE holds if criterion 1 or 3 fails. Criterion 1 fails for all 9 primary variants: my bootstrap gives raw p 0.3047 to 0.9777, and Holm gives 1.0000 for all 9. Criterion 3 fails for 8 of 9. "Best" = V06 by the pre-registered fallback rule. |

## 1. Test window

- **Code paths.** `grep` finds only two loaders in `research/dip-timing/*.py`: `study.load_market` calls
  `dips.load_study_bars` and `dips.load_study_positioning`, and checks each frame again (`check_before_holdout`
  plus an `assert`). The other reads are the study's own JSON and Parquet outputs. `lab/` does not import
  `research/`.
- **Guard on the real catalog** (`audit/a1_a3_data.py`, part A):
  - All four instruments (`BTC/USD.KRAKEN`, `ETH/USD.KRAKEN`, `BTCUSDT.BINANCE`, `ETHUSDT.BINANCE`) load with a
    last bar of 2023-01-01 (train cut) or 2024-07-01 00:00 (validate cut).
  - Rows: Kraken 2191 / 2738 (BTC) and 2190 / 2737 (ETH); Binance 1963 / 2510.
  - A request 1 µs, 1 day or into 2026 past the cut raises `HoldoutWindowError` before anything loads, and so do
    positioning requests (1 µs and 1 h past the cut).
  - `ParquetDataCatalog.query_bars(end=cut)` returns at most 2024-07-01 00:00.
  - A loader that returns a bar closing 2024-07-02 is refused. The guard checks the frame as loaded, not the
    filtered one.
- **Stores and outputs.**
  - The positioning tables' newest `known_at` is 2024-06-30 16:00 (funding) and 23:55 (metrics).
  - `summary.json` and `look.json` record `last_close_read` 2023-01-01 and 2024-07-01. The train series ends
    2023-01-01. The newest validate `ts_end` is 2024-06-02.
  - The catalog itself holds bars up to 2026-10/11 (milestone 1). The study never asked for them.
- **Other scripts.** The researcher's scratch scripts (counting, pre-flight, OI check, hand check, tables) all
  cap at the cut. The only later date in any of them is the data-engineer's guard probe (`end="2024-07-02"`),
  which raises.
- **Limit of this evidence.** Nothing was committed, and the machine keeps no access log. "Never read" is shown
  for every code path and every recorded output, not for every process that ever ran here.

## 2. Look-ahead

- **Tamper the future on the real train bars** (`audit/a2_tamper.py`).
  - Setup: 25 cut times, each at a random event plus 0-31 bars. From the cut on, both coins' bars become a valid
    random walk. The study's own `build_eventset`, `rule_plan`, `event_targets`, `fit_models` and `decide` then
    run again.
  - Identical before the cut, bit for bit:
    - events (t0, P_ref, Q features, `ewma_vol_20`, `funding_7d`, `oi_chg_dip`);
    - all 24 model inputs on every day row decided before the cut;
    - `y_B` and `r_T1` / `y_Q` wherever the label window ends before the cut;
    - the T1-T4 targets decided at closes before the cut;
    - the probabilities of V05, V06, V08 and V12 models fitted on events whose labels were complete before the cut.
  - Every tamper moved later bars (25 of 25).
  - **Power check** (`audit/a2_power.py`): with T3's up-day signal leaking one bar (`close[t+1] > high[t-1]`),
    the same harness fails at 5 of 25 cuts.
- **Hand-breaks the researcher did not try** (`audit/breaks_audit.py`, on a temporary copy of `lab/`; the repo was
  not modified). All 7 are caught by `tests/test_dips.py`:
  - Q feature `ma_dist_100` read at t0+1: 2 failed;
  - `oi_chg_dip` at t0+1: 1 failed;
  - `b_depth` read from the next close: 2 failed;
  - embargo placed before the test group: 2 failed;
  - exit one bar early: 8 failed;
  - the 15 lab features at d+1: 2 failed;
  - T4's mean including today: 3 failed.
- **Positioning alignment** (`audit/a1_a3_data.py`, part E). Recomputed from the raw stored rows, read with the
  filter `known_at < 2023-01-01`:
  - `funding_7d` = the mean of the 21 rates with `known_at` in [t − 7 d, t). It equals the lab's on 1090 / 1090
    defined closes per coin.
  - `oi_last` = the newest valid open interest with `known_at` < t, no older than 1 h. It equals the lab's on 849
    (BTC) and 395 (ETH) closes.
  - The newest value used at any close was known 5 min before it. `known_at` is `create_time + 5 min`, which is
    conservative for the pre-2024-04-26 files that train uses.
  - Per event, `funding_7d` at t0 and `oi_chg_dip` equal my hand values. Coverage: funding 18 + 19, OI 15 + 8.
  - Multiplying every raw value known at or after a close (30 random closes per symbol) changed 0 earlier rows.
- **Labels stay out of features.**
  - Model inputs are `Q_COLS`, `B_FEATURES`, the 15 lab `FEATURES` and the positioning columns. No `y_` or `r_`
    column is among them.
  - `study.fit_and_decide` refits with every label outside the training events flipped. It asserts identical
    probabilities on every one of the 15 × variants CPCV fits, and the train run completed with it.
- **CPCV purge and embargo** (`audit/a2_cpcv.py`). My own splitter matches `dips.event_cpcv` exactly: 6
  contiguous groups and all C(6, 2) pairs, purging any span overlap and embargoing triggers within 31 days after
  a test group's last exit.
  - No kept training event overlaps any test event's span, and none lies in an embargo.
  - Training events per split: 44-53 (all events), 15-23 (funding subset), 9-14 (OI subset). Purged or
    embargoed per split: 1-9.
  - The path assembly passes an oracle: path j holds the j-th split that tested each group.
  - The closest training event ends 1 day before a test trigger. That is allowed: its label is complete before
    the test event starts.

## 3. Costs and fills

- `config/costs.yaml` is read by `Costs.from_yaml()`: pool 5 bps, aggregator 0, slippage 10 / 15 / 30 bps at
  USD 100 / 1,000 / 10,000 (log-linear, extended along the last segment above USD 10,000), and gas USD 0.10 per
  fill. The file says these are **placeholders**. They are not measured Base costs.
- My own per-event simulation (`audit/a1_a3_data.py`, part B) parses the YAML itself and simulates every fill:
  decision at close t, fill at the open of t+1, coin units held, the stop at a close ≤ the weighted average fill
  × 0.85, the exit decided at close t0+30 and filled at the open of t0+31. Differences from the study, over all
  80 D0 events:

  | Rule | Max abs diff from the study | Mean r_e by hand |
  |---|---|---|
  | T1 | 1.3e-15 | +4.0628% |
  | T2 | 1.6e-15 | +2.5511% |
  | T3 | 1.1e-15 | +2.2061% |
  | T4 | 1.8e-15 | +2.6949% |

  T1 at 2x costs (every cost doubled, gas included): +3.3254%, against +3.33% for V36.
- **Strategy level** (part C). My own two-sleeve T1 simulation gives Sharpe 0.2583, total −13.03% and max
  drawdown −76.78%. Its daily returns match the logged series `V01_path0` to 6.7e-16.
- Costs are on in every trial row (`costs_x` 1.0, or 2.0 for V35/V36). There is no zero-cost result anywhere.

## 4. Trial count, DSR and PBO

- **The log.** `trials.jsonl` (40 lines, appended as each trial finished), `trials.parquet` and `trials.csv` hold
  the same 40 IDs, V01-V40, in the plan's order.
  - Recipes match PLAN.md section 7: V09 = Q + T5 LightGBM (the better T5), V10 = Q + T4 (the best of T2-T4),
    V25-V40 = V06.
  - All rows have status `ok`, seed 0, snapshot `1746a21b75683e76`, commit `62b2f11+dirty` and the frozen
    config hash. No amendments were used.
  - The pipeline dry runs in the scratch area are synthetic (`synthetic: true`, snapshot `synthetic`, a
    different config hash). I found no trace of another real-data run on this machine.
- **Recomputed with my own code** (`audit/a4_overfit.py`: my own CSCV, eigen-entropy count and Bailey-López de
  Prado DSR), from `series.parquet` (2191 days × 40 variants × 5 paths):
  - PBO (10 blocks, 252 combinations): 0.3175, 0.3294, 0.2897, 0.3214 and 0.2738; mean **0.3063**. This
    matches `summary.json` and `stats.pbo` exactly.
  - Effective trials over the median-path series: **5.521**.
  - DSR of V06's median path (per-period Sharpe 0.01352, annualised 0.258; trial-Sharpe variance 0.000278):

    | Trial count | Expected max Sharpe | DSR |
    |---|---|---|
    | 5.52 effective | 0.02086 | **0.3670** |
    | 40 raw | 0.03649 | **0.1439** |
    | 42 (adding the two T1 reference runs) | | 0.1406 |
    | 52 (also adding the 10 fixed-day timing schedules) | | 0.1269 |
- **For the record.** The highest-Sharpe trial is V22, T1 on the X20/N10 cell, with Sharpe 0.992.
  - Its DSR is 0.934 with the effective count and 0.772 with the raw count, so it would not pass either.
  - It is a sensitivity run, not a candidate. Choosing it now would be a new, unregistered trial.

## 5. Plan followed: deviations

All 7 deviations RESULTS.md lists hold up, and so does each of its "Interpretations fixed before the real run":
- they are in `study.INTERPRETATIONS`, which is part of the hashed config at the train run;
- the OI timing change (deviation 3) makes the alignment stricter, not looser.

Other points I checked against the code:

- PLAN.md's every number reproduces:
  - D0's start (bar 100, close 2017-04-12; `WARMUP` = 101);
  - all 9 cells of the event-count table (for example X10/N10 44 / 50 and X20/N30 28 / 36);
  - funding coverage 37.
- The order of events is shown by file times only:
  - pre-flight (no outcomes) 03:23;
  - the last code edit 03:23:48;
  - the train run 03:26:44;
  - its outputs 03:27:07-03:27:09;
  - the researcher's hand-check script saved 03:28:18;
  - `FROZEN.json` 03:28:28;
  - `validate/STARTED` 03:28:34;
  - RESULTS.md 03:35.
- Not disclosed, minor:
  - **F4.** The single validate look also reported the 10-schedule timing profile on validate (`by_offset_mean_r`,
    the "Mean r_e, validate" row) and the validate nulls and random-entry benchmark. Deviation 7 names only
    V11-V16. All of it is descriptive, and nothing was tuned.
  - **F6.** `/results/` is git-ignored, so `FROZEN.json`, `trials.parquet` and `series.parquet` cannot be
    committed as they are. Deviation 5 implies that `FROZEN.json` replaces the commit. Only `trials.csv` and
    `validate.csv` in `research/` can go into git.

## 6. RESULTS.md against the numbers (recomputed)

`audit/a6_claims.py` uses my own month-block bootstrap (a different random stream, 10,000 draws), my own Holm and
sklearn AUC. I also recomputed numbers from bars in sections 3 and 4. All of these match:

- **Primary family, Δ vs T1.** The mean Δ is exact for all 9 variants. Raw p, mine against the study's:

  | Variant | Auditor p | Study p |
  |---|---|---|
  | V02 | 0.8141 | 0.8076 |
  | V03 | 0.8528 | 0.8565 |
  | V04 | 0.9777 | 0.9801 |
  | V05 | 0.9518 | 0.9536 |
  | V06 | 0.3047 | 0.3049 |
  | V07 | 0.7915 | 0.7827 |
  | V08 | 0.8299 | 0.8253 |
  | V09 | 0.8271 | 0.8234 |
  | V10 | 0.8763 | 0.8742 |

  - Holm gives 1.0000 for all 9.
  - The 80%-power Δ matches: 3.82, 3.85, 1.52, 3.28, 0.33, 6.27, 6.49, 6.52 and 6.69%.
  - The sd of Δ matches: V06 1.19, and 5.45 to 13.77 for T2-T5 logistic.
  - V06 differs from T1 in 24 of 80 events.
- **T1 on train.**
  - Per dip: mean +4.06%, median −7.11%, 40.0% winners.
  - `y_Q` share: BTC 45.9%, ETH 34.9%. Medians: BTC −2.58%, ETH −15.59%.
  - Strategy level: Sharpe 0.258, −13.0%, max drawdown −76.8%.
  - Average daily rise: BTC +0.21%, ETH +0.38%.
- **Nulls and criterion 3.** The 95th percentiles are timing +3.04%, skip +4.56% / +4.84% and both +3.27%.
  Criterion 3 passes for V06 only.
- **Positioning pairs.** Δ is −0.80%, +0.46% and −0.10%. My p values are 0.8533, 0.2029 and 0.5535, against the
  study's 0.8507, 0.2102 and 0.5545. Holm gives 1.0, 0.61 and 1.0, against the study's 1.0, 0.63 and 1.0. T1 on the
  subsets: −1.28% and −3.21%.
- **Timing profile and hindsight.** Train by day: 4.06, 2.61, 3.41, 2.35, 1.63, 1.80, 0.62, −0.81, −0.82, 0.08%.
  Waiting costs 0.44 points per day on train and 1.48 on validate. Hindsight bounds: +11.67%, −8.59% and +13.79%.
- **Validate.**
  - T1: +17.66%, 6 of 8 winners, Sharpe 1.765, +85.9%, max drawdown −16.8%.
  - The Q model: AUC 0.1667, θ 0.40, p from 0.3823 to 0.4334. It took only the 2024-03-20 pair (+1.85% and
    −3.66%). It skipped 6 dips, 5 of them winners (+15.0% to +36.3%).
  - Validate Δ for all 15 variants matches.
  - Buy-and-hold: Sharpe 1.917, +230.5%, max drawdown −22.7%. 50/50: 1.879, +90.0%, −12.4%.
- **Criteria for V06.**
  - Criterion 4: Δ +0.06% at 2x costs.
  - Criterion 5: 1 of 9 cells positive.
  - Criterion 6: 1 of 5 paths above T1's Sharpe, and PBO 0.306.
  - Criterion 7: −4.43%.

Corrections needed (wording; no number that decides the verdict):

- **F1.** "A round trip on USD 10,000 costs about 0.72%." It is **0.70%**: (5 + 30) bps plus gas of
  0.1 bp per leg, because USD 0.10 on USD 10,000 is 0.1 bp, not 1 bp.
- **F2.** "For V04 and V05 the interval excludes 0: they are worse than T1." This is an unregistered,
  unadjusted two-sided reading. The lower-tail p values are 0.0224 and 0.0483, and Holm over the 9 variants
  gives 0.20 and 0.39. Say instead "point estimates below T1; not significant after Holm".
- **F3.** "Buying at the next open after the dip signal (T1) was the best of everything tested." On train, V06
  was +0.06 points above T1 (p 0.30; it is nearly T1). Say instead "nothing beat T1 by a margin distinguishable
  from zero; on validate T1 was best".
- **F4.** Name the validate timing profile and the validate nulls in deviation 7 (section 5).

## 7. Verdict against the pre-registered criteria

- PLAN.md section 7: NO EDGE if criterion 1 or 3 fails. Criterion 1 fails for all of V02-V10, and criterion 3
  for all but V06.
- The best variant was chosen by the fallback rule: the highest train mean r_e among V01-V10 is V06 (+4.12%,
  against T1's +4.06%). The rule and the order were fixed before the run (`study.INTERPRETATIONS["best"]`).
- The positioning claim ("adds value" needs Holm < 0.05 and Δ > 0) fails for all 3 pairs.
- RESULTS.md's verdict, **NO EDGE**, is the one the rules give.

## Findings for the owner (not integrity failures)

- **F7. Buying every dip at once (T1) is fragile too.**
  - Its +4.06% per dip on train comes from 2017. The 11 events of 2017 average +27.6%; the 69 events of
    2018-2022 average +0.3%. Without the 3 best events the mean is −0.34%.
  - On Binance bars, which start in 2017-08, T1 loses −2.59% per dip.
  - On Sharpe, T1 is below all 100 random-entry strategies with the same exposure, and far below buy-and-hold
    (1.242) and 50/50 (1.339).
  - Validate is a bull market, where T1 made +17.66% per dip.
  - So "no edge" covers dip-buying itself, not just the timing and filter rules.
- **F8. The timing result is "no evidence that waiting helps", not "evidence that waiting hurts".**
  - The shared exit at t0+31 charges a later entry about one day of drift (+0.21% / +0.38% per day on train).
  - That bias against waiting is about as large as the observed Δs (−1.4 to −2.7 points). RESULTS.md says so
    under its known failure modes.
  - The random-timing null carries the same handicap, so criterion 3 is the fair timing test.
- **F9. Power.**
  - The 80%-power thresholds are 0.33 to 6.69 points per dip.
  - The positioning tests have only 37 and 23 events, from 2020 on.
  - "No edge" means no large edge was found. It does not show that a small one is absent.
- **F10. The ML bottom detector was not really tested.**
  - `make_model`'s `min_child_samples=200` leaves LightGBM almost constant on about 450-500 day rows (AUC
    0.4965 ± 0.0135).
  - V06, and with it every sensitivity run V25-V40, is mostly T1 again.
  - A real test needs new, pre-registered event-level settings (TESTING.md section 4).
- **F5. Configurations evaluated but not counted as trials.**
  - Two T1 reference runs (H = 20, a 10% stop) and the 10 fixed-day timing schedules are disclosed as "not
    trials".
  - Counting them would move the raw DSR from 0.144 to 0.141 or 0.127. There is no effect on any verdict.
  - Future studies should count them.
- **F6. Housekeeping.** With the owner's go-ahead, commit:
  - `lab/models/dips.py`, the `reference.scheduled` change and the tests;
  - the 4 study scripts;
  - PLAN.md, RESULTS.md, this file and `audit/`;
  - `trials.csv`, `validate.csv` and a copy of `FROZEN.json` placed under `research/dip-timing/`.

  Until then, the code behind every number exists only as uncommitted files on this disk, identified by the
  SHA-256 values in `FROZEN.json`. Hard rule 7 is met only through those hashes.

## Standing checklist (auditor role), applied to this study

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | Check 2 |
| 2 | Survivorship | N/A | BTC and ETH only; no Bold list |
| 3 | Data snooping | PASS | Validate: one outcome look (#1), plus counts and data-quality looks with no outcomes (#0, #0a), all logged. Test window untouched. |
| 4 | Point-in-time inputs | PASS | Check 2 (positioning recomputed from the raw rows) |
| 5 | Free parameters vs trades | N/A | Nothing was tuned; every parameter was fixed in PLAN.md. D0 has 5 fixed rule parameters and 160 fills. |
| 6 | Parameter plateau (±20%) | FAIL (information) | T1 over the (X, N) grid: Sharpe −0.024 to 0.992, mean r_e +1.23% to +6.92%. There is no plateau. |
| 7 | Walk-forward | N/A | The plan uses event-level CPCV and one forward look at validate (one refit). There was no rolling refit. |
| 8 | DSR ≥ 0.95 | FAIL | 0.367 (effective count) and 0.144 (raw count), recomputed |
| 9 | PBO ≤ 0.25 | FAIL | 0.306, recomputed |
| 10 | CPCV distribution | PASS | Every path reported (for example V06's Sharpe: 0.258 on 4 paths, 0.341 on one) |
| 11 | Cost model = `config/costs.yaml` | PASS (flag) | Exact match (check 3). The values are still placeholders. |
| 12 | Costs doubled, Sharpe > 0.5 | FAIL (information) | V35 0.167-0.245; V36 0.167 |
| 13 | Capacity | N/A | USD 10,000 sleeves; the slippage table is not measured |
| 14 | Monte Carlo drawdowns | N/A | Not pre-registered, and there is no candidate |
| 15 | Regimes | FAIL (information) | Most of T1's train profit comes from 2017 (F7); validate is a bull market |
| 16 | Benchmarks | FAIL (information) | T1 train Sharpe 0.258, against buy-and-hold 1.242, 50/50 1.339 and the random-entry 5th percentile 0.389 |
| 17 | Data quality, snapshot ID | PASS | The snapshot is on every trial row, and its bars equal `b08377c310126e3f`'s. One ETH bar is missing (2018-01-13), so one event spans 32 calendar days. Spans count bars, as the plan says. |

- **Test window:** not run. Items 8, 9, 12 and 15-16 fail, and this task forbids it. It stays unburned.
- **Equity curves:** the daily series of every variant and path are in `results/dip-timing/train/series.parquet`
  (T1: `V01_path0`). No figure was made.
- **Monte Carlo percentiles:** none (item 14).

## Data accessed by this audit

| What | Window | Outcomes computed |
|---|---|---|
| Kraken and Binance daily bars, through `dips.load_study_bars` | Train closes (≤ 2023-01-01) | Yes: train only (sections 2-4) |
| The same loaders capped at the validate cut | ≤ 2024-07-01 00:00 | No: only index bounds and row counts were printed, to check the guard |
| Raw positioning rows (Parquet filter `known_at < 2023-01-01`); `read_table` for the train tamper check | Train | No outcomes; feature values only |
| Stored outputs: `summary.json`, `series.parquet`, `events_d0.parquet`, `look.json`, `validate/events.parquet` | Train and validate, as stored | Recomputed from the stored values only. No validate bar was read for any outcome, and there was no second validate look. |
| Requests past the cut | — | Refused before loading (that was the point of the test) |

**Test tiers on this tree** (run by the auditor):
- Full tier: `uv run pytest -q -p no:cacheprovider -n 4 --ignore=tests/test_dashboard.py --cov=lab --cov-branch` gives
  **1304 passed**, 100% branch coverage of `lab/` (3473 statements, 1016 branches).
- Deep tier: `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 4 -m "not slow" --ignore=tests/test_dashboard.py`
  gives **1292 passed**.
- `uv run ruff check`: all checks passed, `audit/` included.

## Re-check after the audit fixes (2026-11-20, finalization by `ml-researcher`; not a new audit)

These notes record which of the auditor's scripts were re-run after the corrections in RESULTS.md ("Audit fixes"),
and what they gave. The verdicts above are the auditor's and are not changed here.

- **Nothing the checks depend on changed.** No file in `lab/`, no study script and no `config/` file was edited.
  `research/dip-timing/final_checks.py` asserts that the config hash (`0cda4191…`), every frozen file's SHA-256
  and the train outputs' SHA-256 still equal `FROZEN.json` before it computes anything. They do.
- **Re-run, both exit 0, same output as in this audit:**
  - `audit/a4_overfit.py`: PBO 0.3175 / 0.3294 / 0.2897 / 0.3214 / 0.2738 (mean 0.3063) from both the auditor's
    CSCV and `stats.pbo`. Effective trials 5.521. DSR 0.3670 (effective count), 0.1439 (40), 0.1406 (42), 0.1269
    (52) and 0.0469 (400). The highest-Sharpe trial is V22 (0.992), with DSR 0.7723 / 0.9336.
  - `audit/a6_claims.py`: every number in section 6 again, including Holm 1.0000 for all 9 primary variants and
    the lower-tail Holm 0.2016 (V04) and 0.3864 (V05). It read only stored outputs (row 1a of RESULTS.md's looks
    table). No bar or positioning value was loaded.
- **Not re-run:**
  - `a1_a3_data.py` loads bars capped at the validate cut;
  - `a2_tamper.py`, `a2_power.py`, `a2_cpcv.py` and `breaks_audit.py` check code and data that did not change.

  Their results stand as reported above.
- **The corrections, checked against the numbers.**
  - F1: the engine gives 0.7005% for a flat-price round trip of USD 10,000, and 1.398% at 2x costs. The audit's
    0.7020% is the additive 2 × 35.1 bps. Both read "about 0.70%", which is what RESULTS.md now says.
  - F2: from the study's own bootstrap draws (seed 0), the lower-tail p values are 0.0200 (V04) and 0.0465 (V05),
    and Holm over the 9 gives 0.180 and 0.372. This audit's own stream gave 0.20 and 0.39.
  - F3 and F4: the wording was changed as recommended.
  - F5: the DSR at 42 and 52 trials is now in RESULTS.md.
  - F6: `research/dip-timing/FROZEN.json` is a byte-identical copy (SHA-256 `2a69b932…`). Nothing was committed.
- **Four more wording errors were found and fixed** (they are not in this audit; RESULTS.md lists them):
  - the 80%-power range left out V06's 0.33;
  - "the observed Δs are on the wrong side of 0" does not hold for V06;
  - the logistic-AUC range was given as 0.41 to 0.44 for all logistic models;
  - the reason the ladder came closest to the low was wrong.
- **Test tiers after the fixes** (same code as in this audit):
  - quick 1292 passed;
  - full 1304 passed, 100% branch coverage of `lab/` (3473 statements, 1016 branches);
  - deep 1292 passed;
  - slow 12 passed;
  - dashboard 86 passed;
  - ruff clean.

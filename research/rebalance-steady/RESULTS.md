# rebalance-steady: results

> **SCOUTING ONLY.** Every return, Sharpe ratio and drawdown below comes from the reference portfolio engine
> (`lab/runner/portfolio.py`, driven by `lab/runner/steady.py`), not from NautilusTrader (AGENTS.md hard rule 3; the
> Nautilus work is on hold). All of them use the **placeholder** costs in `config/costs.yaml`. Exchange candles
> (Kraken in USD, Binance in USDT) stand in for Base prices. Every table below is labelled SCOUTING. Nothing here
> goes into `reports/<strategy>/` or `strategies/`, and nothing here is an audit.

## In plain words

We tested a simple rule for a cautious ("Steady") portfolio: hold BTC and ETH plus USDC cash at target weights, and
trade back to the targets when the coins drift too far. For each year, a search chose the mix, the drift limit and
the check frequency from earlier data only. The rule was then scored on 2019-2022 after placeholder costs. It made
+174.0% with a worst fall of −41.8% (Sharpe 0.938). Holding only BTC made +318.5% but fell −77.4% (Sharpe 0.864); a
50/50 BTC/cash mix rebalanced monthly made +167.9% and fell −49.5% (Sharpe 0.859). The rule's lead over those two
comes from its mix (mostly cash, some ETH), not from rebalancing. The same mix, bought at the start of each year and
left alone, did as well (Sharpe 0.948, +246.7%). About 1 random rebalancing schedule in 5 did as well or better, and
the rule rebalanced only 3 times in four years. A second search and a second data source agree. **Verdict: NO
EDGE**, so the 2023 to mid-2024 validation data stay unused for this strategy. All of these are scouting numbers from
our simple in-house simulator with placeholder costs, not NautilusTrader results.

## Verdict and headline (SCOUTING)

**Train verdict: NO EDGE. Headline: NO EDGE.** PLAN.md section 10 is applied mechanically: NO EDGE when E1 or E2
fails.

- **E1 fails.** Seed A's out-of-sample Sharpe, 0.938, is below the 95th percentile of random rebalancing with the
  same targets and the same number of rebalances (0.979). Its rank p is 0.214.
- **E2 fails.** S minus B4 is D = −0.0105 (S 0.938 against B4 0.948), with a paired bootstrap p of 0.581. B4 holds
  the same targets unrebalanced within each one-year block.
- Both also fail for seed B and on Binance. E3 fails for seed A, E4 fails (the seeds are FRAGILE) and E5 fails.
  E6 was not run.
- **What failed, in the plan's terms:** the band rule did not beat random rebalancing of the same targets, and did
  not beat holding the same mix unrebalanced over one-year blocks.
- **No validate look** (stop rule 8). The validate window (closes 2023-01-02 .. 2024-07-01) stays unlooked for
  rebalance-steady. **Validate looks used: 0.** No `FROZEN.json` was written, and `freeze.py` and `run_validate.py`
  were not run.
- **The test window was never read.** Every load went through `lab.data.panel.load_panel` with `last_close`
  2023-01-01 00:00 UTC. G9 is NOT RUN.
- **Gates, seed A:** G1 FAIL, G2 PASS, G3 FAIL, G4 FAIL, G5 PASS, G6 MISSING (the budget is TBD, which counts as a
  FAIL), G7 PASS, G8 FAIL, G9 NOT RUN. Even if E1-E6 had all held, the best possible headline was "EDGE, NOT A
  CANDIDATE (G1 FAIL, G3 FAIL, G4 FAIL, G6 MISSING, G8 FAIL)" (`headline_if_edge` in `summary.json`).
- **Superseded runs: none.** Run 0 is the only run. No amendment run was needed: no trial failed, nothing crashed,
  no stop rule fired and no code bug was found. There is therefore no earlier verdict or gate table to show next to
  this one. The audit found one test bug, which changed no number (TESTING.md #48; see "Hard rule 11" below).

**What this means.** These are descriptions, not criteria.
1. **The rule hardly traded.** The searches chose wide bands: b = 0.33-0.50 of the coin sleeve, which is
   0.13-0.20 in weight units. S therefore made 3 rebalances in 2019-2022, fold by fold 0, 1, 2 and 0, in both
   seeds. That is 0.75 trades per parameter, far under the flag of 30. It did not trade at all in 2019 or in 2022.
   With this little trading, S is close to a static mix, and E1 and E2 have little to tell apart (Known weaknesses).
   In training the chosen trials made 7-11 fill rows each, the initial buy included.
2. **G7 passes because of the mix, not the rule.** B4 holds the same targets without rebalancing within a year,
   and it also beats B1 and B2: 0.948 (seed A) and 1.030 (seed B) against 0.864 and 0.859. S's daily returns
   correlate 0.930 with buy-and-hold BTC.
3. **The band and check frequency added nothing beyond what the limits force.** B5 trades only when a Steady limit
   is breached. With 1 fill, it did at least as well as S in both seeds: 0.959 against 0.938, and 1.113 against
   1.046.
4. **Over the whole four years, a mix that is never rebalanced does worse.** B4-span holds each fold's targets
   from 2019 to 2022 with no reset. Its Sharpe was 0.688-0.812, and its max drawdowns were −71.4% to −75.0%. B4,
   reset once a year, fell −46.4% (seed A) and −44.1% (seed B). So in 2019-2022, resetting the mix about once a
   year mattered for risk; whether and when the rule rebalanced within the year did not (E1, E2). E2 does not test
   multi-year horizons (PLAN.md section 8), so this is a description only.
5. **Costs hardly matter at this turnover.** At 2x costs S's Sharpe went from 0.938 to 0.936 (seed B: 1.046 to
   1.044). With 10 bps of extra cost per unit of turnover, S's total return ranged from +173.69% to +173.79% to
   +173.89% (p5, p50, p95) against +173.97%. G2 and E3 therefore say little here.
6. **The coin share drives risk, but the search barely tells coin shares apart** (PLAN.md section 5). In the final
   studies, in-sample over all of train:
   - trials with s in [0.20, 0.30): median max drawdown −28.8% (seed A), median Sharpe 1.523;
   - trials with s in [0.70, 0.77]: median max drawdown −68.7%, median Sharpe 1.355.

   θ_final(A) sits at s = 0.2003, the lower edge of the box. None of these numbers sets or justifies the Steady
   drawdown budget (PLAN.md section 9).

## Run record

- **Command and commit.** Run 0 started at 2026-11-20 18:07:16 UTC (the RUNLOG line):
  `uv run python research/rebalance-steady/run_train.py`, on a clean tree at commit `9fdaa4d`. It finished in
  188.6 s with exit code 0. Its outputs were committed in `a6ec37c` ("rebalance-steady: train run 0 outputs").
- **Config hash:** `1506217f6a731f6a828595a7da183d48cb815f5df56ac4b9d6a55e63beffc638`. At the time this file was
  written, every hashed file still had run 0's start hash, and `study.config_hash(study.file_hashes())` gave the
  same value. PLAN.md was not edited after the run.
- **Data.** Snapshot `1746a21b75683e76`, bars content hash
  `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e`. This equals PLAN.md section 3, so stop rule 2
  did not fire.
  - Kraken train panel: 2190 rows, closes 2017-01-02 .. 2023-01-01. One close is dropped: 2018-01-13 has a BTC
    bar but no ETH bar. Panel hash `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6`.
  - Binance train panel: 1963 rows, closes 2017-08-18 .. 2023-01-01, nothing dropped. Panel hash
    `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587`.
  - The last close loaded was 2023-01-01 00:00 UTC on both panels. The test-window guard did not fire (stop rule 5),
    and no validate close was loaded.
- **Limits as read** at start, by `risk_limits("steady")` from `config/risk_levels.yaml` (SHA-256
  `158d7c9f10eeb664618188455255ca099cc2b265c32833df8a1a37ffab3f16f8`):
  - coins BTC, ETH and USDC; min_cash 0.20; max_coin 0.60;
  - drawdown budget `TBD`, read as none, so G6 is MISSING for the whole study;
  - the 4 box corners passed `check_box`.
- **Trials.** 10 studies of 200 trials each, 2000 in total. All are COMPLETE and none failed, so stop rule 4 did not
  fire. 56 trials scored −10 (fewer than 5 fills in their training rows) and are counted like any other:
  - seed A: 18 in `s0_wf00`, 2 in `s0_wf01`, 4 in `s0_wf02`;
  - seed B: 20 in `s1_wf00`, 12 in `s1_wf01`.
- **Timing.** The searches took 21.9 s (seed A) and 23.2 s (seed B). The evaluations took 52.8 s and 52.4 s.
- **Logged.** 3158 evaluations, i.e. runs that are not search trials (comparators, 2x, Binance, plateau, phase,
  IN-SAMPLE θ_final). There is no MLflow log (Deviations, row 1).

### Throughput and N (amendment A1, copied here as section 7 asks)

A1 was measured before the run by `quant-researcher` with `research/rebalance-steady/throughput.py`, on synthetic
data only, with `n_workers = 1`. The stand-in adapter made the pinned `rebalance` call.

| Measurement | Value |
|---|---|
| 200-trial study, 2190 synthetic rows | 3.86 s wall, 3.08 s CPU (0.0193 s wall per trial, TPE included); a second run 4.06 s |
| 20-trial study, 2190 rows | 0.39 s wall |
| 200-trial study, first 730 rows | 3.48 s wall |
| One backtest on 2190 rows, median of 20 | 0.0073 s (s 0.5, f 0.5, b 0.1, every 7); 0.0088 s (s 0.77, f 0.75, b 0.02, every 1) |
| One B3 draw on a 366-row slice, median of 50 | 0.0038 s |
| Projection, 10 × the largest study | 38.6 s, far under 60 CPU-minutes, so **N = 200** |
| Environment | Python 3.13.18, Optuna 5.1.0, 4 shared CPUs, load average 0.62 |
| Actual search phase of run 0 (real data) | 21.9 s + 23.2 s for the 10 studies |
| Built adapter against the stand-in (synthetic, measured after the run; Deviations, row 2) | median 0.01073 s against 0.01085 s (typical case, ratio 0.99) and 0.01239 s against 0.01275 s (worst case, ratio 0.97); returns bit-identical |

### Stop rule 1: the test tiers on the commit used

Run 0 used commit `9fdaa4d` ("rebalance-steady part 2: adapter and study scripts", branch
`claude/tender-brown-g86h44`). The lead ran the tiers on that commit before run 0, from `/home/user/osprey` on a
clean tree. `git status --porcelain` printed nothing before or after, and HEAD stayed at `9fdaa4d`.

| Tier | Command | Result |
|---|---|---|
| Full, with coverage | `uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch --cov-report=term-missing` | exit 0; **1654 passed** (12 of them slow), 0 failed, 189.14 s; branch coverage of `lab/` **100%** (4136 statements, 1220 branches, 0 missed); `fail_under = 100` reached |
| Deep profile | `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 -m "not slow" --ignore=tests/test_dashboard.py` | exit 0; **1642 passed**, 0 failed, 411.81 s |
| Lint | `uv run ruff check` | exit 0, "All checks passed!" |
| Dashboard | `uv run pytest -q -p no:cacheprovider -n 2 tests/test_dashboard.py` | exit 0; 86 passed, 2.13 s |
| Synthetic dry run (not a result) | `uv run python research/rebalance-steady/run_train.py --synthetic 7 --fast --out-dir <scratch>` | exit 0, 11.5 s; nothing written into the repo |

The counts match TESTING.md section 3 as it stood at `9fdaa4d`. Stop rule 1 holds: run 0 used `9fdaa4d`, and the
tiers passed there. There was no amendment run and no look, so no other run needed the tiers.

### Hard rule 11: the tiers on the commit that carries this file (audit item X1)

An earlier draft of this section said that no later commit needed the tiers. That holds for stop rule 1, but not
for AGENTS.md hard rule 11, under which an audit only counts if the full tier passed on its commit. RESULTS.md and
AUDIT.md go on top of `a6ec37c`, which added the tracked outputs (`RUNLOG.jsonl`, `trials.csv`,
`evaluations.csv`) and no code. **On `a6ec37c` the full tier failed: 1652 passed, 2 failed**
(`tests/test_steady_scripts.py::test_a_dirty_tree_is_refused_before_anything_is_written` and
`::test_real_runs_use_the_pinned_folders_only`). Branch coverage was still 100%.

- **Triage: a test bug; the code is right** (TESTING.md bug #48). The tests' stand-ins for the real-data folders
  did not cover the tracked `RUNLOG.jsonl`. Once `a6ec37c` added run 0's line to it, a real-data call in these
  tests stopped at the RUNLOG guard ("already records real run 0") before it reached the dirty-tree check and the
  `SNAPSHOT.json` read that the tests are about. Both calls still exited 2 and wrote nothing.
- **Fix, in the tests only.** The `real_folders` helper also points the study folder (`S.HERE`: the RUNLOG and the
  committed copies) at `tmp_path`, `test_the_look_s_other_refusals` gets its own stand-in for it (it read the repo's
  RUNLOG the same way and passed only because no look is recorded), and a new regression test,
  `test_real_folders_keep_real_runs_away_from_the_repo_s_runlog`, fails on the old helper. No assertion changed.
- **No number changed, and nothing the run depends on changed.** No code, config or plan file changed. Tests are not
  in the config hash, which is still `1506217f6a731f6a…` (`study.config_hash(study.file_hashes())`, recomputed after
  the fix). `RUNLOG.jsonl`, `trials.csv`, `evaluations.csv` and every file under `results/rebalance-steady/` had the
  same SHA-256 before and after the test runs. No bar was loaded. The verdict stays NO EDGE; stop rule 9 does not
  apply, because there was no look.

The tiers were rerun on `a6ec37c` plus the files that go into the commit carrying this file: the test fix,
TESTING.md (bug #48 and section 3), RESULTS.md, AUDIT.md and RISK.md. The tiers below ran after every edit to those
files, except that the result cells of this table were filled in afterwards (no test reads RESULTS.md).

| Tier | Command | Result |
|---|---|---|
| Full, with coverage | `COVERAGE_FILE=<scratch>/.coverage uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch --cov-report=term-missing` | exit 0; **1655 passed** (12 of them slow; the 1654 of `9fdaa4d` plus the new regression test), 0 failed, 189.77 s; branch coverage of `lab/` **100%** (4136 statements, 1220 branches, 0 missed); `fail_under = 100` reached |
| Deep profile, the steady files | `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 tests/test_steady.py tests/test_steady_scripts.py` | exit 0; **139 passed** (66 + 73), 0 failed, 72.06 s |
| Lint | `uv run ruff check` | exit 0, "All checks passed!" |
| Dashboard | `uv run pytest -q -p no:cacheprovider -n 2 tests/test_dashboard.py` | exit 0; 86 passed, 1.23 s |

The whole-suite deep profile was not rerun: only `tests/test_steady_scripts.py` changed, and no file under `lab/`.
The commit that carries this file must hold exactly this tree; if anything else changes before it, the full tier
is rerun on it.

## Gates (G1-G9) (SCOUTING)

| Gate | Default | Seed A | Number (A) | Seed B | Number (B) |
|---|---|---|---|---|---|
| G1 | OOS Sharpe after costs ≥ 1.0 | FAIL | 0.938 | PASS | 1.046 |
| G2 | Sharpe at 2x costs > 0.5 | PASS | 0.936 | PASS | 1.044 |
| G3 | DSR (effective count) ≥ 0.95 | FAIL | 0.783 | FAIL | 0.841 |
| G4 | mean PBO ≤ 0.25 | FAIL | 0.304 | FAIL | 0.304 |
| G5 | every parameter ±20% keeps ≥ 70% of the Sharpe | PASS | step/S 0.958-1.068; 0 of 8 steps not free | PASS | step/S 0.938-1.013; 1 of 8 steps not free |
| G6 | MC worst-5% drawdown within the Steady budget | MISSING | budget TBD (None); MC p5 -58.6% | MISSING | budget TBD (None); MC p5 -54.5% |
| G7 | Sharpe above B1 and B2 | PASS | S 0.938 vs B1 0.864, B2 0.859 | PASS | S 1.046 vs B1 0.864, B2 0.859 |
| G8 | no regime makes more than half the profit | FAIL | bull share 2.060 of total 1.008 (bull +2.076, bear -1.003, sideways -0.065) | FAIL | bull share 1.817 of total 1.115 (bull +2.025, bear -0.839, sideways -0.072) |
| G9 | test window, run once | NOT RUN |  | NOT RUN |  |

- Gates are computed on seed A's stitched out-of-sample series (Kraken, 1456 daily returns, closes 2019-01-04 ..
  2023-01-01). Seed B's are for the fragility check. A missing number fails; it never passes.
- **G5 is a plain PASS for both seeds, not "PASS (weak)".** Seed A has 0 of 8 steps clipped or at the limit, seed
  B has 1 (`every` ×0.8, because fold 3 has `every` = 1). Weak needs 3 or more.
- **G6 is MISSING, which counts as a FAIL.** Run 0 read the drawdown budget as `TBD` before loading any bar, and G6
  uses only that reading. The Monte Carlo p5 next to it is a description.
- **G7** passes for both seeds, but B4 passes it too (see "What this means", item 2).
- **G8** fails as PLAN.md section 9 warned: for a long-only portfolio, bull months hold more than the whole profit.
  It is applied literally (owner answer to question 4).
- G1 and G3 are weak evidence of an edge from rebalancing (PLAN.md sections 2 and 9). Seed A fails G1 and seed B
  passes it.

## Research criteria (E1-E6) (SCOUTING)

| Criterion | Seed A | Seed B | Binance (seed A's parameters) |
|---|---|---|---|
| E1 timing beats chance | fails: S 0.938 vs B3 p95 0.979 (p5 0.862, p50 0.905); rank p 0.2138 | fails: S 1.046 vs B3 p95 1.066 (p5 0.946, p50 0.992); rank p 0.1079 | fails: S 0.942 vs B3 p95 0.985 (p5 0.867, p50 0.911); rank p 0.2268 |
| E2 rebalancing beats holding (one-year blocks) | fails: D -0.0105 (B4 0.948), p 0.5806 | fails: D +0.0157 (B4 1.030), p 0.4656 | fails: D -0.0105 (B4 0.953), p 0.5806 |
| E3 survives 2x costs | fails: S 2x 0.936 vs B4 2x 0.948 | holds: 1.044 vs 1.030 | not part of E5 |
| E4 the seeds agree | fails: FRAGILE (outcomes differ on E3, G1; Sharpe gap 0.108 ≤ 0.25) | same | |
| E5 other data source | fails (E1 and E2 fail on Binance) | | E1 fails, E2 fails |
| E6 validate (reject-only) | NOT RUN: no look (stop rule 8) | NOT RUN | |

- **E1:** B3 has 1000 draws per seed. Each draw is its 4 fold pieces with seeds 10·j + i, stitched. Every draw
  has exactly k = 3 kept fills, the sum of S's k_i. The rank p is (1 + #{B3_j ≥ S}) / 1001.
- **E2:** D = Sharpe(S) − Sharpe(B4), with a one-sided paired stationary bootstrap: 10,000 resamples, mean block
  20, rng seed 0, the same indices for S and B4. p = (1 + #{D* ≤ 0}) / 10,001.
  - Seed B's D is positive (+0.0157) but far from significant (p 0.466).
  - Binance gives the same p as Kraken seed A (0.5806). The two S and B4 series are nearly identical and share the
    bootstrap indices; the run stage confirmed this by recomputing.
- **E3:** B4 at 2x equals B4 at 1x bit for bit, because B4 pays nothing in the kept rows.
- **E4:** distance between the seeds' chosen parameters in unit space: 0.526, 0.270, 0.175 and 0.515 per fold,
  0.243 for θ_final. Not part of the fragility rule.
- **E5:** seed A's per-fold parameters, re-run on Binance. Each fold slice had the same closes as Kraken's. B3 used
  its own k_i (0, 1, 2, 0, the same as Kraken), and B4 used the same bootstrap.

## Walk-forward per fold and the best stable regions (SCOUTING)

PLAN.md section 7 sets the folds: `walk_forward(2190, train_size=730, test_size=365, expanding=True)` on the Kraken
train panel, warmup 120 rows, 364 kept returns per fold. The other columns:
- "IS Sharpe" is the chosen trial's Sharpe on its training rows; WFE is OOS divided by IS.
- Costs are summed over the kept rows: per-bar cost fractions, and in USD the fill legs whose fill row is a kept
  row.
- "Return", "Max DD" and "Worst day" are over the kept rows.

### Per fold, seed A (0), Kraken train walk-forward, 1x costs (SCOUTING)

| Fold | OOS closes | Study (chosen trial) | s | f | b | every | w_btc | w_eth | band | IS Sharpe | OOS Sharpe | WFE | Fills k | Turnover | Costs (fraction / USD) | Return | Max DD | Worst day |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 2019-01-04 .. 2020-01-02 | rebalance-steady-s0_wf00 (#170) | 0.4103 | 0.4505 | 0.4987 | 8 | 0.1849 | 0.2255 | 0.2046 | 2.896 | 0.421 | 0.145 | 0 | 0.0000 | 0.00000 / 0.00 | +7.9% | -27.7% | -6.54% |
| 1 | 2020-01-04 .. 2021-01-01 | rebalance-steady-s0_wf01 (#113) | 0.4051 | 0.6656 | 0.3892 | 5 | 0.2696 | 0.1355 | 0.1577 | 2.224 | 2.355 | 1.059 | 1 | 0.2107 | 0.00053 / 8.21 | +107.8% | -25.7% | -15.35% |
| 2 | 2021-01-03 .. 2022-01-01 | rebalance-steady-s0_wf02 (#53) | 0.4861 | 0.6752 | 0.3639 | 8 | 0.3283 | 0.1579 | 0.1769 | 2.173 | 1.492 | 0.687 | 2 | 0.4503 | 0.00133 / 33.10 | +74.5% | -26.5% | -9.09% |
| 3 | 2022-01-03 .. 2023-01-01 | rebalance-steady-s0_wf03 (#149) | 0.4632 | 0.6368 | 0.3336 | 7 | 0.2949 | 0.1682 | 0.1545 | 1.953 | -1.506 | -0.771 | 0 | 0.0000 | 0.00000 / 0.00 | -30.0% | -30.9% | -4.80% |
| all | 1456 returns | | | | | | | | | | **0.938** | 0.406 | 3 | 0.6610 | 0.00186 / 41.31 | +174.0% | -41.8% | -15.35% |

Neighbourhoods (k = 10, `stable_region`), seed A:

| Fold | Neighbourhood score | Neighbour scores (min .. max) | s range | f range | b range | every range | Raw best trial: score, (s, f, b, every) |
|---|---|---|---|---|---|---|---|
| 0 | 0.769 | 0.096 .. 1.202 | 0.375-0.442 | 0.437-0.474 | 0.445-0.499 | 6-9 | 1.202, (0.410, 0.451, 0.499, 8) (= chosen) |
| 1 | 1.096 | 0.478 .. 1.377 | 0.375-0.436 | 0.648-0.692 | 0.349-0.420 | 4-6 | 1.377, (0.436, 0.648, 0.390, 5) |
| 2 | 1.003 | 0.854 .. 1.124 | 0.455-0.517 | 0.641-0.687 | 0.335-0.411 | 7-9 | 1.124, (0.512, 0.662, 0.402, 8) |
| 3 | 1.213 | 1.134 .. 1.253 | 0.429-0.500 | 0.606-0.658 | 0.332-0.395 | 6-9 | 1.299, (0.541, 0.643, 0.347, 5) |

### Per fold, seed B (1), Kraken train walk-forward, 1x costs (SCOUTING)

| Fold | OOS closes | Study (chosen trial) | s | f | b | every | w_btc | w_eth | band | IS Sharpe | OOS Sharpe | WFE | Fills k | Turnover | Costs (fraction / USD) | Return | Max DD | Worst day |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 2019-01-04 .. 2020-01-02 | rebalance-steady-s1_wf00 (#149) | 0.5509 | 0.6615 | 0.3422 | 4 | 0.3644 | 0.1865 | 0.1885 | 2.367 | 0.673 | 0.284 | 0 | 0.0000 | 0.00000 / 0.00 | +19.9% | -34.6% | -8.80% |
| 1 | 2020-01-04 .. 2021-01-01 | rebalance-steady-s1_wf01 (#69) | 0.3647 | 0.6781 | 0.3620 | 16 | 0.2473 | 0.1174 | 0.1320 | 1.784 | 2.376 | 1.332 | 1 | 0.1989 | 0.00048 / 6.98 | +92.8% | -23.2% | -13.67% |
| 2 | 2021-01-03 .. 2022-01-01 | rebalance-steady-s1_wf02 (#137) | 0.4168 | 0.6807 | 0.4541 | 5 | 0.2837 | 0.1331 | 0.1893 | 2.069 | 1.559 | 0.753 | 2 | 0.4837 | 0.00143 / 33.67 | +68.2% | -22.1% | -7.96% |
| 3 | 2022-01-03 .. 2023-01-01 | rebalance-steady-s1_wf03 (#90) | 0.3369 | 0.7059 | 0.4591 | 1 | 0.2378 | 0.0991 | 0.1547 | 2.020 | -1.549 | -0.767 | 0 | 0.0000 | 0.00000 / 0.00 | -21.6% | -22.2% | -3.32% |
| all | 1456 returns | | | | | | | | | | **1.046** | 0.508 | 3 | 0.6827 | 0.00191 / 40.66 | +204.8% | -36.7% | -13.67% |

Neighbourhoods (k = 10, `stable_region`), seed B:

| Fold | Neighbourhood score | Neighbour scores (min .. max) | s range | f range | b range | every range | Raw best trial: score, (s, f, b, every) |
|---|---|---|---|---|---|---|---|
| 0 | 0.671 | 0.309 .. 0.834 | 0.505-0.563 | 0.635-0.687 | 0.288-0.405 | 3-5 | 0.990, (0.510, 0.655, 0.401, 4) |
| 1 | 1.023 | 0.508 .. 1.311 | 0.330-0.394 | 0.654-0.699 | 0.330-0.439 | 13-19 | 1.359, (0.398, 0.649, 0.403, 8) |
| 2 | 0.990 | 0.784 .. 1.060 | 0.386-0.440 | 0.659-0.712 | 0.380-0.468 | 4-6 | 1.125, (0.491, 0.661, 0.408, 1) |
| 3 | 1.169 | 1.049 .. 1.239 | 0.298-0.365 | 0.679-0.719 | 0.379-0.478 | 1-1 | 1.327, (0.433, 0.662, 0.405, 1) |

**The best stable region is the neighbourhood, not the top trial.**
- Seed A's neighbourhoods have b 0.33-0.50 of the coin sleeve and s 0.38-0.52, and they check every 4-9 days.
- Seed B's neighbourhoods have b 0.29-0.48 and s 0.30-0.56. They check every 3-6 days, except fold 1 (every 13-19
  days) and fold 3, where all ten neighbours check daily (every = 1).
- In training the chosen trials made 7-11 fill rows each, over 730-1825 training rows. Out of sample they made 0-2
  per year.
- The stitched curves: seed A +174.0%, Sharpe 0.938, max drawdown −41.8%, 3 fills, turnover 0.661, costs USD
  41.31; seed B +204.8%, 1.046, −36.7%, 3 fills, 0.683, USD 40.66.

## Comparators (SCOUTING)

All comparators run with costs on, on the same kept rows as S.
- B1, B2 and B5 use S's harness, H120.
- B3 and B4 use H1 and start from S's book.
- B4-span holds each fold's targets from the open of fold 0's t0 to the last close of fold 3.

### Per fold, Sharpe of S and the comparators on the same kept rows (SCOUTING)

| Seed | Fold | S | S 2x | B4 | B5 | B1 | B2 | B3 mean kept fills |
|---|---|---|---|---|---|---|---|---|
| A | 0 | 0.421 | 0.421 | 0.485 | 0.421 | 1.223 | 1.179 | 0.0 |
| A | 1 | 2.355 | 2.353 | 2.421 | 2.433 | 2.305 | 2.333 | 1.0 |
| A | 2 | 1.492 | 1.489 | 1.311 | 1.437 | 0.961 | 0.948 | 2.0 |
| A | 3 | -1.506 | -1.506 | -1.501 | -1.506 | -1.336 | -1.399 | 0.0 |
| B | 0 | 0.673 | 0.673 | 0.747 | 0.673 | 1.223 | 1.179 | 0.0 |
| B | 1 | 2.376 | 2.374 | 2.436 | 2.448 | 2.305 | 2.333 | 1.0 |
| B | 2 | 1.559 | 1.555 | 1.260 | 1.620 | 0.961 | 0.948 | 2.0 |
| B | 3 | -1.549 | -1.549 | -1.545 | -1.549 | -1.336 | -1.399 | 0.0 |

S beat B4 only in fold 2 (2021), the year it rebalanced twice.
- In fold 1 (2020) it rebalanced once and trailed B4.
- In folds 0 and 3 it made no fill. There the gap to B4 comes only from where each book started: S's book was
  bought in the 120-row warmup and had drifted, while B4 bought the targets at the open of t0 (Open questions).

### Stitched over the 1456 kept rows (2019-01-04 .. 2023-01-01), seed A (SCOUTING)

| Series | Sharpe | Return | Max DD | Worst day | Fills | Turnover | Costs (fraction / USD) |
|---|---|---|---|---|---|---|---|
| **S**, the band rule | 0.938 | +174.0% | -41.8% | -15.35% | 3 | 0.6610 | 0.00186 / 41.31 |
| S at 2x costs | 0.936 | +173.5% | -41.8% | -15.35% | 3 | 0.6610 | 0.00371 / 82.46 |
| B1 buy-and-hold BTC | 0.864 | +318.5% | -77.4% | -38.94% | 0 | 0.0000 | 0.00000 |
| B2 50/50 BTC/USDC monthly | 0.859 | +167.9% | -49.5% | -18.35% | 52 | 2.2361 | 0.00497 |
| B4 static mix, reset yearly | 0.948 | +246.7% | -46.4% | -18.77% | 0 | 0.0000 | 0.00000 / 0.00 |
| B4 at 2x | 0.948 | +246.7% | -46.4% | -18.77% |  |  |  |
| B5 limit-only | 0.959 | +200.2% | -43.2% | -15.35% | 1 | 0.3260 | 0.00099 / 27.02 |
| B3 random rebalancing, 1000 draws (p5 / p50 / p95) | 0.862 / 0.905 / 0.979 | +178.1% / +196.8% / +241.9% | -45.4% / -43.5% / -42.2% | | 3 per draw | | |
| B4-span, fold 0's targets held 2019-2022 | 0.782 | +219.0% | -73.9% | -22.38% |  |  |  |
| B4-span, fold 1's targets held 2019-2022 | 0.739 | +181.7% | -73.0% | -22.43% |  |  |  |
| B4-span, fold 2's targets held 2019-2022 | 0.780 | +216.2% | -74.2% | -25.61% |  |  |  |
| B4-span, fold 3's targets held 2019-2022 | 0.776 | +213.0% | -74.0% | -24.72% |  |  |  |

### Stitched over the 1456 kept rows (2019-01-04 .. 2023-01-01), seed B (SCOUTING)

| Series | Sharpe | Return | Max DD | Worst day | Fills | Turnover | Costs (fraction / USD) |
|---|---|---|---|---|---|---|---|
| **S**, the band rule | 1.046 | +204.8% | -36.7% | -13.67% | 3 | 0.6827 | 0.00191 / 40.66 |
| S at 2x costs | 1.044 | +204.3% | -36.7% | -13.67% | 3 | 0.6827 | 0.00382 / 81.18 |
| B1 buy-and-hold BTC | 0.864 | +318.5% | -77.4% | -38.94% | 0 | 0.0000 | 0.00000 |
| B2 50/50 BTC/USDC monthly | 0.859 | +167.9% | -49.5% | -18.35% | 52 | 2.2361 | 0.00497 |
| B4 static mix, reset yearly | 1.030 | +287.8% | -44.1% | -16.98% | 0 | 0.0000 | 0.00000 / 0.00 |
| B4 at 2x | 1.030 | +287.8% | -44.1% | -16.98% |  |  |  |
| B5 limit-only | 1.113 | +260.8% | -36.7% | -13.67% | 1 | 0.3860 | 0.00125 / 36.97 |
| B3 random rebalancing, 1000 draws (p5 / p50 / p95) | 0.946 / 0.992 / 1.066 | +211.9% / +232.5% / +283.8% | -44.1% / -44.1% / -41.6% | | 3 per draw | | |
| B4-span, fold 0's targets held 2019-2022 | 0.812 | +248.0% | -75.0% | -27.93% |  |  |  |
| B4-span, fold 1's targets held 2019-2022 | 0.712 | +161.6% | -72.2% | -20.74% |  |  |  |
| B4-span, fold 2's targets held 2019-2022 | 0.743 | +184.4% | -73.2% | -22.93% |  |  |  |
| B4-span, fold 3's targets held 2019-2022 | 0.688 | +145.5% | -71.4% | -19.56% |  |  |  |

- B3's turnover and costs per draw were not recorded (Deviations, row 3). Every draw has exactly 3 kept fills.
  Per-draw Sharpe, return, max drawdown, worst day and fills are in `evaluations.csv`.
- B1 and B2 come from the single-asset reference runner, which reports costs as fractions only.
- B4-span makes no fill in the kept rows by construction.
- S is not the only series that beats B1 and B2 on Sharpe. For seed A, B3's median (0.905), B4 (0.948) and B5
  (0.959) beat them too.

### Binance, seed A's per-fold parameters (E5; no search on Binance) (SCOUTING)

| Series | Sharpe | Return | Max DD | Worst day | Fills | Turnover | Costs USD |
|---|---|---|---|---|---|---|---|
| S | 0.942 | +175.0% | -41.7% | -15.53% | 3 | 0.6615 | 41.41 |
| B4 | 0.953 | +248.4% | -46.3% | -18.96% | 0 | 0.0000 | 0.00 |
| B3 (p5 / p50 / p95) | 0.867 / 0.911 / 0.985 | +179.7% / +198.5% / +243.9% | -45.3% / -43.4% / -42.1% | | 3 per draw | | |

| Fold | Book V (USD) | k | Sharpe | Return | Max DD | Fills |
|---|---|---|---|---|---|---|
| 0 | 7,942.04 | 0 | 0.436 | +8.3% | -28.2% | 0 |
| 1 | 8,791.42 | 1 | 2.356 | +107.4% | -25.8% | 1 |
| 2 | 17,529.56 | 2 | 1.496 | +74.8% | -26.5% | 2 |
| 3 | 9,653.37 | 0 | -1.511 | -30.0% | -30.8% | 0 |

### Books of B3 and B4 (S's book at close test[0] − 1, USD)

| Seed | Fold 0 | Fold 1 | Fold 2 | Fold 3 |
|---|---|---|---|---|
| A, 1x | 7,954.93 | 8,779.30 | 17,500.02 | 9,647.53 |
| A, 2x | 7,946.70 | 8,770.24 | 17,477.35 | 9,635.83 |
| B, 1x | 7,287.25 | 8,897.94 | 16,452.97 | 9,741.58 |
| B, 2x | 7,276.27 | 8,889.86 | 16,435.33 | 9,733.50 |

Each fold's B3 and B4 are priced on S's own book at the close before t0: at 2x with V from S at 2x, and on Binance
with V from S on Binance. S's book at the open of t0 still differs from V by the overnight gap (PLAN.md section 8).

## Plateau (G5) (SCOUTING)

| Parameter | Factor | Seed A Sharpe | A step/S | A mark (fold marks) | Seed B Sharpe | B step/S | B mark (fold marks) |
|---|---|---|---|---|---|---|---|
| coin_share | ×0.8 | 0.954 | 1.018 | free (free, free, free, free) | 0.999 | 0.955 | free (free, free, free, free) |
| coin_share | ×1.2 | 1.001 | 1.068 | free (free, free, free, free) | 1.022 | 0.977 | free (free, free, free, free) |
| btc_share | ×0.8 | 0.995 | 1.061 | free (free, free, free, free) | 1.060 | 1.013 | free (free, free, free, free) |
| btc_share | ×1.2 | 0.920 | 0.981 | free (free, free, free, free) | 0.994 | 0.951 | free (free, free, free, free) |
| band_rel | ×0.8 | 0.898 | 0.958 | free (free, free, free, free) | 0.981 | 0.938 | free (free, free, free, free) |
| band_rel | ×1.2 | 0.946 | 1.009 | free (free, free, free, free) | 1.042 | 0.997 | free (free, free, free, free) |
| every | ×0.8 | 0.912 | 0.972 | free (free, free, free, free) | 1.051 | 1.005 | at the limit (free, free, free, at the limit) |
| every | ×1.2 | 0.947 | 1.010 | free (free, free, free, free) | 1.046 | 1.000 | free (free, free, free, free) |
| | | S = 0.938 | **PASS** (0 not free) | | S = 1.046 | **PASS** (1 not free) | |

The stepped values per fold:

| Parameter | Factor | Fold 0 | Fold 1 | Fold 2 | Fold 3 |
|---|---|---|---|---|---|
| A: coin_share | ×0.8 | 0.3283 | 0.3241 | 0.3889 | 0.3705 |
| A: coin_share | ×1.2 | 0.4924 | 0.4862 | 0.5834 | 0.5558 |
| A: btc_share | ×0.8 | 0.3604 | 0.5325 | 0.5402 | 0.5094 |
| A: btc_share | ×1.2 | 0.5406 | 0.7987 | 0.8103 | 0.7641 |
| A: band_rel | ×0.8 | 0.3990 | 0.3114 | 0.2911 | 0.2669 |
| A: band_rel | ×1.2 | 0.5985 | 0.4671 | 0.4367 | 0.4003 |
| A: every | ×0.8 | 6 | 4 | 6 | 6 |
| A: every | ×1.2 | 10 | 6 | 10 | 8 |
| B: coin_share | ×0.8 | 0.4407 | 0.2918 | 0.3334 | 0.2695 |
| B: coin_share | ×1.2 | 0.6611 | 0.4377 | 0.5002 | 0.4043 |
| B: btc_share | ×0.8 | 0.5292 | 0.5425 | 0.5446 | 0.5648 |
| B: btc_share | ×1.2 | 0.7938 | 0.8138 | 0.8168 | 0.8471 |
| B: band_rel | ×0.8 | 0.2737 | 0.2896 | 0.3633 | 0.3672 |
| B: band_rel | ×1.2 | 0.4106 | 0.4344 | 0.5449 | 0.5509 |
| B: every | ×0.8 | 3 | 13 | 4 | 1 |
| B: every | ×1.2 | 5 | 19 | 6 | 2 |

Every step is applied to every fold's own chosen value at once, run in H120 and stitched. No step was clipped. The
only "at the limit" step is seed B's `every` ×0.8, because fold 3 already has `every` = 1. All 16 steps keep
0.938-1.068 times S's Sharpe, so the plateau is flat. That fits a rule whose rebalances are rare: moving any
parameter by 20% changes few fills.

## Regimes (G8) (SCOUTING)

| Regime | Months | Kept rows | A: Σ ln(1+S) | A: share | A: excess over B4 | B: Σ ln(1+S) | B: share | B: excess over B4 |
|---|---|---|---|---|---|---|---|---|
| bull | 19 | 574 | +2.076 | +2.060 | -0.565 | +2.025 | +1.817 | -0.588 |
| bear | 12 | 364 | -1.003 | -0.995 | +0.222 | -0.839 | -0.752 | +0.259 |
| sideways | 17 | 518 | -0.065 | -0.065 | +0.108 | -0.072 | -0.064 | +0.088 |
| total | 48 | 1456 | +1.008 | | -0.235 | +1.115 | | -0.241 |
| G8 | | | | **FAIL** | | | **FAIL** | |

Month labels, January to December (by the bar's day, close time − 1 day):

| Year | Labels |
|---|---|
| 2019 | BEAR, bull, side, bull, bull, bull, side, side, BEAR, bull, BEAR, side |
| 2020 | bull, side, BEAR, bull, side, side, bull, side, side, bull, bull, bull |
| 2021 | bull, bull, bull, side, BEAR, side, bull, bull, side, bull, side, BEAR |
| 2022 | BEAR, bull, side, BEAR, BEAR, BEAR, bull, BEAR, side, side, BEAR, side |

- A month is bull if BTC's compounded close-to-close return over that month's kept rows is ≥ +10%, bear if it is
  ≤ −10%, and sideways otherwise. Each kept row belongs to the UTC month of its bar's day (close time − 1 day).
- Profit is Σ ln(1 + S_t). G8 passes if the total is above 0 and no regime has more than half of it.
- Bull months hold 2.060 (seed A) and 1.817 (seed B) times the total. Bear and sideways months lost.
- The excess over B4 is a description. In both seeds it is positive in bear and sideways months and negative in
  bull months: S lost less than B4 when prices fell or went sideways, and gained less when they rose. Over the 48
  months the excess is −0.235 (seed A) and −0.241 (seed B). This is the pattern the plan's failure mode predicts
  for a rebalancer in a trend. With 3 fills in four years, though, it cannot be put down to rebalancing: where each
  book started each block also matters (Comparators).

## Trial counts, DSR and PBO (SCOUTING)

### Trial counts and DSR

| | Count | DSR, seed A | DSR, seed B |
|---|---|---|---|
| Effective (gate G3; sum of `effective_trials` over the 10 studies) | 13.63 | 0.783 | 0.841 |
| Raw N_raw (every trial in every state) | 2000 | 0.394 | 0.477 |
| Strict, N_raw + 21 | 2021 | 0.393 | 0.476 |

- **N_raw = 2000**: every trial Optuna recorded, in every state, in the 10 studies of run 0 under
  `results/rebalance-steady/train/`. There are no amendment runs.
- **Effective count 13.63:** the sum of `effective_trials` over the studies. G3 uses it.
- **Strict count 2021 = N_raw + 21.** The 21 are: 16 plateau variants, 2 runs at 2x costs, 1 Binance run, and
  the 2 neighbouring mixes seen in the dip study (PLAN.md section 2, P1).
- Next to the strict count: **54 phase-sensitivity runs** (28 for seed A, 26 for seed B). They reuse trialled
  parameters and nothing was chosen from them. Benchmarks and null draws are comparators, not trials. The 3158
  logged evaluations hold the 21 runs of the strict count (as fold pieces and stitched rows) together with the
  comparators, the null draws, the phase runs and θ_final's IN-SAMPLE re-run. Only the 21 enter the strict count.
- The seed A and B DSRs use the same trial set, with S_A and S_B respectively.
- **Optuna studies**, all in `results/rebalance-steady/train/`: `rebalance-steady-s0_wf00` .. `_wf03`,
  `rebalance-steady-s0_final`, `rebalance-steady-s1_wf00` .. `_wf03` and `rebalance-steady-s1_final`.

### PBO per study (`stats.pbo(m, n_blocks=10)`, 252 combinations each)

| Study | Trials | PBO | Logit p5 | Logit p50 | Logit p95 | Share of logits ≤ 0 |
|---|---|---|---|---|---|---|
| rebalance-steady-s0_final | 200 | 0.401 | -2.260 | +0.352 | +3.669 | 0.401 |
| rebalance-steady-s0_wf00 | 200 | 0.067 | -0.368 | +2.096 | +4.600 | 0.067 |
| rebalance-steady-s0_wf01 | 200 | 0.278 | -1.199 | +0.498 | +1.821 | 0.278 |
| rebalance-steady-s0_wf02 | 200 | 0.306 | -0.878 | +0.519 | +2.319 | 0.306 |
| rebalance-steady-s0_wf03 | 200 | 0.321 | -2.347 | +0.519 | +2.710 | 0.321 |
| rebalance-steady-s1_final | 200 | 0.437 | -2.255 | +0.200 | +2.377 | 0.437 |
| rebalance-steady-s1_wf00 | 200 | 0.024 | +0.519 | +1.952 | +3.897 | 0.024 |
| rebalance-steady-s1_wf01 | 200 | 0.329 | -1.212 | +0.605 | +2.315 | 0.329 |
| rebalance-steady-s1_wf02 | 200 | 0.524 | -2.513 | -0.070 | +2.120 | 0.524 |
| rebalance-steady-s1_wf03 | 200 | 0.357 | -2.757 | +0.498 | +3.322 | 0.357 |
| mean (G4) | | **0.304** | | | | |

The logits are those of `stats.pbo(m, n_blocks=10)` on the matrix the report uses. The share of logits ≤ 0 equals
the PBO, since a logit of 0 counts as overfit.
- The fold-0 studies (training rows 2017-2018 only) have low PBO: 0.067 and 0.024.
- The final studies (all of train) have 0.401 and 0.437, and `s1_wf02` has 0.524.

## Monte Carlo (SCOUTING)

| | Seed A | Seed B |
|---|---|---|
| Block bootstrap max drawdown, p5 (G6's number) / p50 | -58.6% / -37.8% | -54.5% / -34.2% |
| Historical max drawdown of S | -41.8% | -36.7% |
| Trade shuffle, max drawdown p5 / p50 (3 kept trade periods) | -2.80% / -2.80% | -4.53% / -4.53% |
| Degraded execution, +10 bps per unit turnover: total return p5 / p50 / p95 (S: total) | +173.69% / +173.79% / +173.89% (+173.97%) | +204.51% / +204.63% / +204.74% (+204.84%) |

- The block bootstrap is `overfitting_report`'s: a stationary block bootstrap of S's stitched returns, mean block
  20, 1000 draws, seed 0. G6 would compare its p5 with the budget.
- **The trade shuffle says little here.** S has only 3 kept trade periods, which are chained rebalance periods,
  not round trips, so p5 equals p50. At that coarse grain it misses S's daily drawdowns inside the periods (−41.8%
  and −36.7%).
- **Degraded execution:** `degrade_execution` on S with S's kept turnover, 10 extra bps, 1000 draws, seed 0.

## Risk description (risk-officer) (SCOUTING)

Per fold, over the kept rows:

| Seed | Fold | s | w_btc | w_eth | Max DD | Worst day |
|---|---|---|---|---|---|---|
| A | 0 | 0.4103 | 0.1849 | 0.2255 | -27.7% | -6.54% |
| A | 1 | 0.4051 | 0.2696 | 0.1355 | -25.7% | -15.35% |
| A | 2 | 0.4861 | 0.3283 | 0.1579 | -26.5% | -9.09% |
| A | 3 | 0.4632 | 0.2949 | 0.1682 | -30.9% | -4.80% |
| B | 0 | 0.5509 | 0.3644 | 0.1865 | -34.6% | -8.80% |
| B | 1 | 0.3647 | 0.2473 | 0.1174 | -23.2% | -13.67% |
| B | 2 | 0.4168 | 0.2837 | 0.1331 | -22.1% | -7.96% |
| B | 3 | 0.3369 | 0.2378 | 0.0991 | -22.2% | -3.32% |

θ_final over the whole Kraken train panel (2190 rows, closes 2017-01-02 .. 2023-01-01), **IN-SAMPLE**:

| | θ_final(A) | θ_final(B) |
|---|---|---|
| Study, trial | rebalance-steady-s0_final #117 | rebalance-steady-s1_final #101 |
| s | 0.2003 | 0.2936 |
| f | 0.6526 | 0.7398 |
| b | 0.4372 | 0.4971 |
| every | 30 | 31 |
| w_btc / w_eth / cash | 0.1307 / 0.0696 / 0.7997 | 0.2172 / 0.0764 / 0.7064 |
| band | 0.0876 | 0.1460 |
| Sharpe (IN-SAMPLE) | 1.384 | 1.506 |
| Historical max drawdown | -28.9% | -33.2% |
| MC p5 / p50 (block 20, 1000 draws, seed 0) | -34.6% / -21.4% | -47.4% / -31.0% |
| Worst day / 1st-percentile day | -6.78% / -2.51% | -11.22% / -3.86% |
| Lowest cash / highest single coin at any close | 57.7% / 32.5% | 42.3% / 44.5% |
| Closes in breach of the limits | 0 | 0 |
| Legs (legs per year) | 18 (3.00) | 18 (3.00) |
| Leg size USD p5 / p50 / p95 / max | 151 / 1,939 / 4,035 / 4,083 | 466 / 3,850 / 18,069 / 22,443 |

Stitched S (overshoot):

| | Seed A | Seed B |
|---|---|---|
| Lowest cash at any kept close | 28.6% | 32.8% |
| Highest single coin | 42.4% | 50.0% |
| Closes in breach | 0 | 0 |

Note recorded with the run: "The folds chose different coin shares, so S's Monte Carlo p5 is not the drawdown of any one shippable configuration."

- **θ_final is an in-sample result.** It is the final study's own logged trial, re-run on all 2190 train rows, and
  it is labelled IN-SAMPLE.
- θ_final(A) holds 80% cash at target. It checks every 30 days with a band of 0.088 per coin, and between checks
  drift took cash as low as 57.7% at a close. This stayed inside the Steady limits: 0 closes in breach.
- Its legs are 3.00 per year. Leg sizes grow with the compounding book: the largest is USD 4,083 for θ_final(A) and
  USD 22,443 for θ_final(B), from a USD 10,000 start.
- **S's drawdown is not that of a shippable configuration.** The stitched S mixes four per-fold configurations
  with coin shares 0.41-0.49 (seed A) and 0.34-0.55 (seed B). Its −41.8% and its Monte Carlo p5 of −58.6% describe
  that mix. θ_final's in-sample numbers above are the drawdowns of one fixed configuration.

## s-profile (SCOUTING)

Trials / median score / median Sharpe (training rows of the study) per s-bin:

| Study | [0.20, 0.30) | [0.30, 0.40) | [0.40, 0.50) | [0.50, 0.60) | [0.60, 0.70) | [0.70, 0.77] |
|---|---|---|---|---|---|---|
| rebalance-steady-s0_final | 178 / 0.582 / 1.523 | 8 / 0.511 / 1.444 | 2 / 0.457 / 1.329 | 3 / 0.487 / 1.371 | 7 / 0.505 / 1.294 | 2 / 0.474 / 1.355 |
| rebalance-steady-s0_wf00 | 3 / -0.010 / 1.902 | 6 / 0.351 / 2.237 | 88 / 0.348 / 2.394 | 42 / 0.256 / 2.248 | 54 / 0.257 / 2.246 | 7 / 0.211 / 1.921 |
| rebalance-steady-s0_wf01 | 28 / 0.598 / 1.714 | 104 / 0.883 / 1.930 | 58 / 0.695 / 2.043 | 5 / 0.452 / 1.621 | 4 / 0.334 / 1.596 | 1 / 0.272 / 1.475 |
| rebalance-steady-s0_wf02 | 6 / 0.649 / 1.832 | 18 / 0.712 / 1.900 | 95 / 0.790 / 2.048 | 72 / 0.736 / 1.985 | 6 / 0.665 / 1.783 | 3 / 0.603 / 1.700 |
| rebalance-steady-s0_wf03 | 4 / 1.073 / 1.710 | 2 / 1.063 / 1.792 | 46 / 1.125 / 1.935 | 105 / 1.104 / 1.902 | 39 / 0.977 / 1.778 | 4 / 0.984 / 1.704 |
| rebalance-steady-s1_final | 94 / 0.626 / 1.505 | 89 / 0.515 / 1.431 | 7 / 0.458 / 1.316 | 4 / 0.511 / 1.391 | 5 / 0.481 / 1.339 | 1 / 0.502 / 1.247 |
| rebalance-steady-s1_wf00 | 6 / 0.213 / 1.910 | 5 / 0.257 / 1.963 | 55 / 0.374 / 2.257 | 104 / 0.386 / 2.251 | 15 / 0.213 / 1.895 | 15 / 0.196 / 1.946 |
| rebalance-steady-s1_wf01 | 26 / 0.769 / 1.746 | 123 / 0.814 / 1.937 | 44 / 0.697 / 1.917 | 2 / 0.491 / 1.656 | 5 / 0.511 / 1.575 | 0 |
| rebalance-steady-s1_wf02 | 21 / 0.712 / 1.835 | 83 / 0.754 / 2.078 | 86 / 0.849 / 2.121 | 6 / 0.677 / 1.819 | 1 / 0.558 / 1.759 | 3 / 0.657 / 1.742 |
| rebalance-steady-s1_wf03 | 13 / 1.058 / 1.835 | 56 / 1.066 / 1.899 | 86 / 1.134 / 1.941 | 30 / 1.112 / 1.777 | 13 / 1.084 / 1.721 | 2 / 1.063 / 1.668 |

Final studies, each trial's own logged returns over all of train (IN-SAMPLE): max drawdown median (worst) and MC p5 median (worst):

| s-bin | s0_final trials | s0_final max DD | s0_final MC p5 | s1_final trials | s1_final max DD | s1_final MC p5 |
|---|---|---|---|---|---|---|
| [0.20, 0.30) | 178 | -28.8% (-41.8%) | -38.2% (-51.5%) | 94 | -30.9% (-47.4%) | -41.8% (-60.7%) |
| [0.30, 0.40) | 8 | -44.0% (-52.7%) | -52.9% (-63.8%) | 89 | -38.4% (-55.4%) | -52.2% (-65.5%) |
| [0.40, 0.50) | 2 | -56.4% (-59.6%) | -65.4% (-67.0%) | 7 | -55.5% (-60.7%) | -66.3% (-69.3%) |
| [0.50, 0.60) | 3 | -66.3% (-72.4%) | -76.4% (-79.2%) | 4 | -65.1% (-66.4%) | -74.8% (-76.6%) |
| [0.60, 0.70) | 7 | -68.5% (-72.7%) | -80.3% (-81.2%) | 5 | -69.7% (-75.8%) | -78.3% (-83.2%) |
| [0.70, 0.77] | 2 | -68.7% (-71.7%) | -82.0% (-83.0%) | 1 | -68.4% (-68.4%) | -80.8% (-80.8%) |

This comes from the trial log, with no new runs. Score is the objective on the study's training rows; Sharpe is the
trial's training Sharpe. The final studies' drawdowns are over all of train and are IN-SAMPLE.
- Score and Sharpe change little with s, as PLAN.md section 5 expected. In the final studies they are slightly
  higher at low s.
- Drawdown grows steeply with s: the median max drawdown goes from −28.8% to −68.7%, and the median MC p5 from
  −38.2% to −82.0% (seed A).
- TPE spent 178 of seed A's 200 final trials in [0.20, 0.30). θ_final(A) is at the lower edge of the box.

## Phase sensitivity (SCOUTING)

| Seed | Fold | every (runs) | OOS Sharpe min | median | max | S (j = 0) |
|---|---|---|---|---|---|---|
| A | 0 | 8 (8) | 0.421 | 0.432 | 0.437 | 0.421 |
| A | 1 | 5 (5) | 2.349 | 2.375 | 2.395 | 2.355 |
| A | 2 | 8 (8) | 1.429 | 1.505 | 1.575 | 1.492 |
| A | 3 | 7 (7) | -1.506 | -1.496 | -1.491 | -1.506 |
| B | 0 | 4 (4) | 0.673 | 0.680 | 0.684 | 0.673 |
| B | 1 | 16 (16) | 2.312 | 2.373 | 2.467 | 2.376 |
| B | 2 | 5 (5) | 1.386 | 1.559 | 1.605 | 1.559 |
| B | 3 | 1 (1) | -1.549 | -1.549 | -1.549 | -1.549 |
| | | runs: A 28, B 26 | | | | |

- Each fold's chosen parameters were re-run with the slice starting j = 0 .. every − 1 rows earlier, so that every
  check phase occurs. The warmup grows to 120 + j; the kept rows stay the same.
- The phase moves fold Sharpes by up to 0.15 (seed A, fold 2: 1.429 to 1.575) and 0.22 (seed B, fold 2: 1.386 to
  1.605). The folds without fills (0 and 3) move by 0.02 or less. The stitched Sharpe across phases was not
  computed.

## Other descriptions (SCOUTING)

| | Seed A | Seed B |
|---|---|---|
| Unpaid turnover at fold boundaries 0→1, 1→2, 2→3 (total) | 0.0806, 0.0342, 0.0600 (0.1748) | 0.1735, 0.0464, 0.0527 (0.2726) |
| Kept turnover S paid for | 0.6610 | 0.6827 |
| Trades per parameter (kept fill rows / 4) | 0.75 (3 fills) FLAGGED (< 30) | 0.75 (3 fills) FLAGGED (< 30) |
| Correlation of S's daily returns with B1 / B2 | 0.930 / 0.932 | 0.921 / 0.930 |
| Walk-forward efficiency | 0.406 | 0.508 |
| Distance between the seeds' chosen parameters (unit space) | folds 0.526, 0.270, 0.175, 0.515; θ_final 0.243 | |

- **Unpaid turnover.** The stitched curve never paid to move from one fold's targets to the next. The sum of those
  moves is 0.175 (seed A) and 0.273 (seed B), against the 0.661 and 0.683 of turnover S did pay for in the kept
  rows.
- **Trades per parameter** is flagged in both seeds: 3 fill rows in 2019-2022, against the 120 that would clear
  the flag.

## Looks at the data (continues PLAN.md section 15; PLAN.md itself is not edited)

PLAN.md asks for the validate look to be logged in its section 15. There was no look, and PLAN.md is in the config
hash, so the train-phase looks are logged here instead, as in the dip-timing study.

| # | Date (UTC) | By | What was looked at |
|---|---|---|---|
| T0 | 2026-11-20, before 18:07 | lead (pre-run checks) | The tiers and a synthetic dry run (`--synthetic 7 --fast`, scratch output). No real bar was read. It confirmed that `results/rebalance-steady/` did not exist. |
| T1 | 2026-11-20 18:07:16 | `quant-researcher` (run stage) | **Train run 0** (`run_train.py`). Kraken daily BTC/ETH train closes 2017-01-02 .. 2023-01-01 (2190 rows) and Binance (1963 rows from 2017-08-18). It ran the 10 studies, the comparators, the plateau, the phase runs and θ_final IN-SAMPLE. The last close read was 2023-01-01 00:00 UTC; no validate or test bar was loaded. |
| T1a | 2026-11-20, after 18:10 | `quant-researcher` (run stage) | **Re-reads of run 0's stored outputs only** (`oos.parquet`, `evaluations.parquet`). These were cross-checks of the stitched Sharpes, the E2 bootstrap (10,000 resamples), E1's p95 and rank, and the regime labels. Every check matched `summary.json`. No bar was loaded and no backtest was rerun. |
| T1b | 2026-11-20 | `quant-researcher` (this file) | **Re-reads of stored outputs only** (`summary.json`, `oos.parquet`, `trials.csv`, `evaluations.csv`). The cross-checks were the stitched Sharpe, return and max drawdown of S, S at 2x, B1, B2, B4, B5, B4-span and the Binance S and B4 from `oos.parquet`, all equal to `summary.json`. It also counted the trials that scored −10 and looked up the chosen trials' training fills. A synthetic-only timing of the adapter was also run (Deviations, row 2). No bar was loaded. |
| T2 | 2026-11-20, from 18:44 | fix of audit item X1 | **No data.** The #48 test fix and the tier reruns (synthetic data and `tmp_path` folders only). No bar was loaded and no stored output was re-read; the SHA-256 of `RUNLOG.jsonl`, `trials.csv`, `evaluations.csv` and every file under `results/rebalance-steady/` were the same before and after. |
| 1 | not used | | **The single validate look was not used.** The train verdict is NO EDGE (stop rule 8), and the validate window stays unlooked for rebalance-steady. **Validate looks used: 0.** |

## Deviations from PLAN.md

| # | What | Why | When, relative to which result | Effect on numbers |
|---|---|---|---|---|
| 1 | No MLflow logging. Trials are in each study's Optuna journal, `trials.parquet` and `returns/`, plus `train/run0/trials.parquet` and the tracked `trials.csv`. | MLflow is not built, and the Nautilus/MLflow work is on hold. PLAN.md section 12 declares this departure from the AGENTS.md "Parquet + MLflow" rule. | Declared in PLAN.md before any run. | None. Every trial is logged and counted. |
| 2 | Section 7 step 4 (redo A1 if the built adapter's single backtest is over 2x slower than the stand-in's) was not recorded before run 0. | Missed in the run stage's record. | Done while writing this file, after run 0's results, on synthetic data only (`synthetic_market(2190, seed=21)`): typical case ratio 0.99, worst case 0.97, returns bit-identical to the stand-in's. The real search phase took 45.1 s against the 38.6 s projection. | None. A1 would not have been redone, and N = 200 stands. |
| 3 | B3's turnover and costs paid per draw were not recorded. Section 10 lists them among the stitched metrics for the comparators. The `summary.json` B3 block has Sharpe, return and max drawdown percentiles. | The harness records B3 per stitched draw with Sharpe, return, max drawdown, worst day and fills only (`study.INTERPRETATIONS["evaluations"]`). | Found while writing this file. | None on any criterion or gate. E1 uses B3's Sharpe. Every draw's fill count (3) equals k, as the consistency stop checks. |

## Readings used where the plan is loosely worded

These are pinned in `research/rebalance-steady/study.py` (`INTERPRETATIONS`) and in the docstring of
`lab/runner/steady.py`. Both files are covered by the config hash. The ones that shape the tables above:
- **G5 marks.** A step's mark is the most restrictive of its fold marks. So seed B's `every` ×0.8 is "at the
  limit" because fold 3 cannot move, even though folds 0-2 do. "PASS (weak)" counts steps that are not "free".
- **Fragility.** E1, E2, E3 and G1-G8 are compared between the seeds as outcomes. PASS and PASS (weak) count as
  pass; FAIL and MISSING count as fail.
- **B3 stitched draw.** Draw j is the 4 fold pieces with seeds 10·j + i, in fold order. B4-span starts from S's
  fold-0 book.
- **Costs paid.** The sum of per-bar cost fractions over the kept rows. In USD, the fill legs whose fill row is a
  kept row.
- **Legs per year.** legs / ((rows − 1) / 365); the first buy counts.
- **Breach.** w_BTC + w_ETH > 1 − min_cash + 1e-9, or a coin > max_coin + 1e-9.
- **s-profile.** The COMPLETE trials, binned at 0.20, 0.30, ..., 0.70, 0.77; each bin is [lo, hi) and the last
  is closed.
- **Unpaid turnover.** Per boundary: |next fold's w_btc − S's w_BTC at the last kept close|, plus the same for ETH.
- **G8.** Profits are `math.fsum` of `log1p`. Exactly half of the total passes. A month is the UTC month of the
  bar's day (close time − 1 day).
- **E1 ties** count against S.

## Known weaknesses

- **Scouting only.** These are results of the reference engine, not Nautilus.
  - The costs are pessimistic placeholders.
  - Exchange candles stand in for Base prices: Kraken quotes in USD, Binance in USDT, while Base trades against
    USDC.
  - USDC is priced at 1, with no yield and no depeg.
- **Little power.** S made 3 kept rebalances in four years, and none in 2019 or 2022. E1's null (random dates,
  k = 3) and E2's null (no rebalance in the year) are both close to S, so neither test could show much either
  way. A failure here says "no detectable edge from the band rule at the bands the search chose", not "rebalancing
  never helps".
- **Where each book starts, in folds without fills.** In folds 0 and 3 the S − B4 gap is the drift of S's warmup book
  against B4's fresh buy at t0, not a rebalancing decision.
- **B4 is reset to target for free** at each block start, so E2 tests horizons of up to one year only. The plan
  expected this to favour S in a trend. In 2019-2022 it did the opposite: B4-span, the multi-year static mix, did
  much worse than B4 (Sharpe 0.739-0.782 for seed A's targets, against 0.948), so the free yearly reset made B4 the
  harder null. S beat B4-span (0.938), but B4-span is a description and was never tested.
- **The coin share is weakly identified** (PLAN.md section 5):
  - the folds chose s 0.34-0.55, while θ_final chose 0.20 and 0.29;
  - θ_final(A) is at the box's lower edge;
  - the stitched S is not any one shippable configuration.
- **The seeds disagree near thresholds.** G1 is 0.938 against 1.046 around the 1.0 threshold, and E3 is 0.936
  against 0.948 and 1.044 against 1.030. Hence FRAGILE.
- **Out-of-sample Sharpe is about half the in-sample Sharpe** (WFE 0.406 and 0.508). In 2022 every fold-3 series
  lost, S and B4 alike (Sharpe about −1.5).
- **Few years.** Four out-of-sample years are few: even a strong true edge often fails DSR ≥ 0.95 at this length
  (TESTING.md section 4).
- **Prior looks.** These make G1 weak evidence (PLAN.md section 2). The DSR counts the trials inside this study
  only, not the choice of this strategy after dip-buying failed.
- **Daily closes only.** Decisions and breach checks happen only at 00:00 UTC closes. The engine shares a fill's
  cost pro rata, and the headroom h = 0.02 covers the live difference at fills; that difference is not modelled.
- **Unpaid turnover.** The stitched curve does not pay for target changes between folds (0.175 and 0.273 of
  turnover).

## Files

- `research/rebalance-steady/RESULTS.md`: this file (new, not committed when written). It goes into one commit with
  AUDIT.md, RISK.md, TESTING.md and the #48 test fix in `tests/test_steady_scripts.py` (audit items X1 and N4).
- Tracked, committed in `a6ec37c`:
  - `research/rebalance-steady/RUNLOG.jsonl`, 1 line (run 0);
  - `research/rebalance-steady/trials.csv`, 2000 trials (SHA-256 `9072a2e7e2a76c31…`);
  - `research/rebalance-steady/evaluations.csv`, 3158 rows (SHA-256 `b91f8d2436822c5b…`).
- Git-ignored, in `results/rebalance-steady/train/`:
  - `run0/summary.json` (SHA-256 `8dd86af8f706f127…`; start fields, then results);
  - `run0/trials.parquet`, `run0/evaluations.parquet` and `run0/oos.parquet` (the stitched series of S_A, S_B,
    B1, B2, B4, B5, B4-span, the B3 percentiles and Binance);
  - the 10 study folders, each with its Optuna journal, `meta.json`, `returns/` (one Parquet per trial) and
    `trials.parquet`.
- Not written, because there was no look: `results/rebalance-steady/FROZEN.json`, its copy in this folder, and
  `results/rebalance-steady/validate/`.

## Open questions for the auditor

1. **Power.** With k = 0, 1, 2 and 0, can E1 and E2 separate anything at all? A future plan could pre-register a
   minimum out-of-sample trade count or a narrower band range. That would be a new study, not an amendment.
2. **E2 in folds without fills.** There S − B4 measures H120 against H1, i.e. a drifted warmup book against a fresh
   buy at t0. The plan pinned this harness. Is that the intended null for those folds?
3. **G5 marks.** The "at the limit" mark is applied when any fold is at the limit. This is conservative and changes
   no verdict here.
4. **The coin share.** Should a later Steady plan fix or cap s, as the risk-officer recommended (owner question 3)?
   TPE put θ_final(A) at the box's lower edge, and s drives drawdown far more than it drives Sharpe.
5. **The validate window** is still unlooked for rebalance-steady. PLAN.md section 2 says it is not fresh for "does
   a BTC/ETH mix do well?".

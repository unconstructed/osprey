# rebalance-steady: independent audit of RESULTS.md (train run 0)

Written 2026-11-20 by `backtest-auditor`. SCOUTING study on the reference engine with placeholder costs (PLAN.md). Per the
plan, this audit is not filed under `reports/<strategy>/`.

- **Audited:** `research/rebalance-steady/RESULTS.md`, untracked when read (SHA-256 `5f179b5f81f46a17…`), against
  PLAN.md (`9a8c90dd7a30b9be…`, unchanged since the run), the code at the run commit `9fdaa4d`, and run 0's outputs:
  - `RUNLOG.jsonl` (`9cabeedc16da8dd1…`), `trials.csv` (`9072a2e7e2a76c31…`), `evaluations.csv` (`b91f8d2436822c5b…`);
  - `results/rebalance-steady/train/run0/summary.json` (`8dd86af8f706f127…`), plus `oos.parquet`, `evaluations.parquet`
    and `trials.parquet`;
  - the 10 study folders: journals, `meta.json`, and 2000 `returns/` files.
- **HEAD:** `a6ec37c`, which adds only the tracked outputs to `9fdaa4d`.
- **Not written:** FROZEN.json, `validate/` and `validate.csv`, all correctly absent (no look).
- **Read-only:** this file is the only thing I wrote in the repo. No bar was loaded and no backtest was run. Every
  recomputation used the logged returns.

## Verdict

**Audit: FAIL, with 1 blocking item, and that item is test-only.** RESULTS.md's content passes every check:
- every number I recomputed matches the outputs;
- the plan was followed, and its 3 deviations are logged;
- the test window was never read;
- validate was looked at 0 times;
- all 2000 trials are counted;
- the gates, E1-E5 and the verdict follow mechanically.

The one blocking item is that the full test tier fails on HEAD `a6ec37c`, the commit that RESULTS.md and this audit
would be committed on top of. AGENTS.md hard rule 11 says an audit only counts if the full tier passed on that commit.

The fix touches only the tests and changes no number. Once the full tier passes on the commit that carries RESULTS.md
and this file, this audit's content stands as written and needs no re-audit.

**Strategy: NO EDGE, confirmed. Return to the researcher; this is not ready for risk review.** Nothing in the run
needs fixing. The study is closed under stop rule 8. The test window was **not** run and is **not** burned for
rebalance-steady: checklist items 5, 8, 9, 14, 15 and 16 fail, and the persona's final step runs only after all 17
pass. The validate window also stays unlooked.

## Blocking item

| # | Item | Where | Why | Fix |
|---|---|---|---|---|
| X1 | The full tier fails on HEAD `a6ec37c`: **1652 passed, 2 failed**. Branch coverage of `lab/` is still 100% (4136 statements, 1220 branches) | `tests/test_steady_scripts.py::test_a_dirty_tree_is_refused_before_anything_is_written` (line 567) and `::test_real_runs_use_the_pinned_folders_only` (line 1324) | Hard rule 11. **Triage: test bug; the code is right.** The `real_folders` helper redirects `S.DEFAULT_OUT` and `S.DEFAULT_CATALOG`, but a real run still reads the tracked `research/rebalance-steady/RUNLOG.jsonl` (`S.runlog_path` → `S.HERE`). At `9fdaa4d` that file did not exist. Commit `a6ec37c` added it with real run 0, so `check_runlog` now refuses before the git check and the snapshot read. Both calls still exit 2 and write nothing, but the tests expect the "dirty" and "SNAPSHOT.json" messages. I confirmed the cause in a scratch export of `a6ec37c`: both tests fail with the committed RUNLOG and pass once it is removed. My run changed nothing (the RUNLOG and run0 hashes are identical before and after). RESULTS.md lines 136-138 say no later commit needed the tiers; that holds for stop rule 1 but not for hard rule 11 | Isolate the two tests from the repo's RUNLOG, for example by having `real_folders` also monkeypatch `S.HERE` (or `S.runlog_path`) to a folder in `tmp_path`, so each test reaches the guard it means to test. Log it as bug #48 in TESTING.md (test bug; the code is right; a committed run makes the real-data guard tests depend on repo state). Rerun the full tier, and the deep profile for `test_steady_scripts.py`, on the commit that carries RESULTS.md and AUDIT.md, and update TESTING.md section 3 |

## Protocol checks

| Check | Result | Evidence |
|---|---|---|
| Hashed files unchanged since the run | PASS | All 30 files in `summary.json` `start.file_hashes` have the same SHA-256 at `9fdaa4d` and in the working tree. `study.config_hash(study.file_hashes())` reproduces `1506217f6a731f6a…`. The hashed set covers every file PLAN section 12 names, every `.py` in `lab/search` and `lab/validation` included. `config/` was last changed in `4133d62`. The gates in `lab/search/report.py` and the frozen `portfolio.py` and `panel.py` have not changed since part 1 |
| Stop rule 1 (tiers on the run commit) | PASS | The lead's logs: full tier 1654 passed, 100% branch, written 17:58:56 after a 189 s run, so it started after `9fdaa4d` was committed at 17:55:21. Deep profile 1642 passed. The synthetic dry run wrote to scratch. I reran `ruff check`: pass. The dashboard line has no saved log; it is not material |
| Stop rule 2 (bars hash) | PASS | `data/catalog/SNAPSHOT.json` is `1746a21b75683e76` / `08f5ca2c…b3cd1e`, equal to PLAN section 3. Every study's context records both, plus the commit, dirty flag, config hash and limits as read |
| Test window never read | PASS | `run_train.py` loads bars only through `S.load_study_panel(source, TRAIN_LAST_CLOSE, ...)` (line 824), which refuses anything after 2024-07-01 and checks the returned index again. Under it, `load_panel`'s `HoldoutWindowError` guard is tested in `test_panel.py`. Nothing else in the study folder reads the catalog; `throughput.py` is synthetic only. Every stored series ends at or before 2023-01-01 00:00 UTC: both panels, all 2000 trial return files, `oos.parquet` and `evaluations`. **No validate close was loaded either** |
| Validate looked at most once, after the freeze | PASS (0 looks) | Train verdict NO EDGE, so stop rule 8 means no look. There is no `results/rebalance-steady/validate/` and no FROZEN.json in either place. RUNLOG has 1 line (`run_train.py`, run 0, real, clean, `9fdaa4d`). Git history holds no `validate.csv` or FROZEN.json |
| All trials of all runs counted | PASS | 10 study journals, 200 trials each, all COMPLETE: N_raw = 2000, equal to `trials.csv` and the summary. There are no other study folders under `train/` and no orphan return files (every file is a COMPLETE trial). RUNLOG.jsonl did not exist at `9fdaa4d` and the tree was clean at start, so no earlier real run since then left a trace. The first trial started at 18:07:16.58, after the RUNLOG line at 18:07:16.02. Strict count 2021 = 2000 + 21. The 54 phase runs are reported next to it |
| Stop rules 3-7 | PASS | N = 200 from A1. The real searches took 45 s; the journals' trial times span 18:07:16-18:08:01. 0 failed trials (rule 4), no crash (rule 6), no amendment run (rule 7), and the test-window guard never fired (rule 5) |
| Deviations logged | PASS | The 3 rows in RESULTS.md (MLflow; the adapter speed check of section 7 step 4 done after the run; B3 turnover and costs not recorded) are accurate and change no criterion. Small gaps are under N3 below |
| Plan followed (sections 7-12) | PASS | Folds, seeds and windows in every `meta.json` match section 7: seeds A 0/1000/2000/3000/4000 and B 1/1001/.../4001, training windows 730/1095/1460/1825/2190 rows. The stable region (k = 10) matches my own implementation for all 8 folds and both θ_final. The harnesses (H120 for S, B1, B2 and B5; H1 for B3 and B4, from S's book), B3 seeds 10·j + i, the bootstrap, G5 steps and G8 labels all match sections 8-10. Every item section 10 lists is reported |
| Gates, E-criteria and verdict follow mechanically | PASS | Recomputed below, independently of `study.gate_table` and `train_verdict` |

## Numbers recomputed independently (SCOUTING)

The script used my own Sharpe, max drawdown, DSR, effective trials, CSCV PBO, regime labels and bootstrap, from
`oos.parquet`, the trial `returns/` files and `evaluations.csv`. **All 142 numeric comparisons and both gate tables
match `summary.json`**, to 1e-9 relative or exactly. Every number in RESULTS.md's tables also matches `summary.json`
after rounding. The tables checked:
- per-fold tables, neighbourhoods and raw best trials;
- comparators per fold and stitched, Binance, the books;
- plateau steps (values recomputed from the chosen parameters, and their feasibility);
- regimes and the month labels (48 months, rebuilt from B1's kept returns, which are BTC's close-to-close returns);
- PBO with its logit p5, p50 and p95;
- Monte Carlo, the risk description, the s-profile (counts, medians and drawdowns), phase, unpaid turnover,
  correlations and seed distances.

| Number | Reported | Mine |
|---|---|---|
| OOS Sharpe, 1x: S_A / S_B | 0.9377 / 1.0458 | 0.9377 / 1.0458 |
| OOS Sharpe, 2x: S_A / S_B | 0.9363 / 1.0443 | same |
| B1 / B2 Sharpe | 0.8642 / 0.8588 | same. B1 is +318.5%, −77.4%; the run stage's handoff said +318.6% / −77.5%, but RESULTS.md has it right |
| B4: A / B; B5: A / B | 0.9482 / 1.0301; 0.9585 / 1.1130 | same |
| DSR, effective count 13.6316: A / B | 0.7832 / 0.8410 | same. The trial-Sharpe variance is 2.664e-4 per period over 2000 trials |
| DSR, raw 2000 / strict 2021: A | 0.3939 / 0.3933 | same |
| PBO per study (CSCV, 10 blocks, 252 splits), mean | 0.024-0.524; mean 0.3044 | same, all 10 |
| E1: S vs B3 p95, rank p (A; B; Binance) | 0.938 vs 0.979, 0.2138; 1.046 vs 1.066, 0.1079; 0.942 vs 0.985, 0.2268 | same. 213, 107 and 226 of 1000 draws ≥ S; every draw has 3 kept fills |
| E2: D, p (A; B; Binance) | −0.0105, 0.5806; +0.0157, 0.4656; −0.0105, 0.5806 | same with the pinned rng. My own stationary bootstrap (separate code and random stream) gives p 0.576, 0.464 and 0.578. Binance's p equals Kraken A's because the D* counts are equal (5806); D itself differs (−0.010463 against −0.010504) |
| E3: S 2x vs B4 (A; B) | 0.936 vs 0.948, fails; 1.044 vs 1.030, holds | same |
| G8: total, bull share (A; B) | 1.0078, 2.060; 1.1146, 1.817 | same; FAIL both |
| G6's number, MC p5 (A; B) | −0.5856; −0.5450 | same. Budget TBD, so MISSING |
| Fragility | differ on E3 and G1; gap 0.1081 | same: FRAGILE, so E4 fails |
| Verdict | NO EDGE | NO EDGE: E1 and E2 fail for A, so the rule needs no other input |

## Checklist (backtest-auditor, items 1-17)

FAIL here means the strategy fails the check, as RESULTS.md correctly reports. It is not an error in RESULTS.md.

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | Decisions at close t fill at the open of t+1. This is pinned by the contract and `test_portfolio.py` tamper-the-future tests, and by tamper-the-future on `steady_backtest`. Each fold's search saw only `bars.iloc[fold.train]`, which ends at row test[0]−1 (study windows in `meta.json`). No model is fitted. H120 reproduced `walk_forward_optimize` bit for bit (the run's stop check) |
| 2 | Survivorship | N/A | Steady trades BTC and ETH only, so no Bold list is involved |
| 3 | Data snooping | PASS | 0 validate looks; the test window was untouched. Prior looks P1-P5 are disclosed, and P1's 2 mixes are in the strict count |
| 4 | Point-in-time inputs | PASS | The rule reads only the drifted weights at the decision close. The limits are read once at start. G8's month labels are realised returns, used only for a descriptive gate |
| 5 | Free parameters vs trades | FAIL | 4 parameters, 3 out-of-sample fills per seed in 2019-2022: 0.75 per parameter, against the flag at 30. Flagged in RESULTS.md |
| 6 | Plateau ±20% | PASS | Step/S ratios 0.958-1.068 (A) and 0.938-1.013 (B); no step clipped; 1 step "at the limit" (B, `every` ×0.8). It is flat because the rule hardly trades, so it is not evidence of robustness |
| 7 | Walk-forward | PASS (method); G1 FAIL for A | Expanding 730/365 split, warmup 120, no labels so no purge needed. OOS Sharpe 0.938 (A) and 1.046 (B); WFE 0.41 and 0.51 |
| 8 | DSR, every trial | FAIL | 0.783 (A) and 0.841 (B) at the effective count 13.63; 0.394 and 0.477 at the raw count 2000 |
| 9 | PBO | FAIL | Mean 0.304, above 0.25 |
| 10 | CPCV, distribution | N/A (substitute reported) | No fitted model, so there are no CPCV paths. As pre-registered in section 10, each study's CSCV logit distribution (252 splits, p5/p50/p95 and share ≤ 0) is reported and matches |
| 11 | Cost model | PASS, with a flag | `Costs.from_yaml()` reads `config/costs.yaml`, hash recorded at start: per leg, 5 bps pool fee + 0 aggregator fee + slippage by USD size (log-linear between 100, 1k and 10k, extended along the last slope above 10k) + USD 0.10 gas. **The values are still placeholders** (the file says so), so every number is SCOUTING |
| 12 | Cost stress, 2x | PASS | 0.936 and 1.044, both above 0.5. Weak evidence: out-of-sample turnover was 0.66 in 4 years |
| 13 | Capacity | N/A for this study | There is no measured Base slippage (placeholders). θ_final(B)'s in-sample legs reach USD 22,443, above the table's last point |
| 14 | Monte Carlo | MISSING (fails) | Block bootstrap max drawdown p5 / p50: −58.6% / −37.8% (A) and −54.5% / −34.2% (B). The Steady budget is TBD. The trade shuffle is uninformative with 3 periods. Degraded execution moves the total by about 0.1 point |
| 15 | Regimes | FAIL | Bull months hold 206% (A) and 182% (B) of the total log profit |
| 16 | Benchmarks | FAIL | S beats B1 and B2 on Sharpe (G7 PASS), but B4, B5 and B3's median do too. It does **not** beat random rebalancing with the same count (E1) or the static mix (E2) |
| 17 | Data quality | PASS | The snapshot and bars hash are recorded for every trial. The Kraken 2018-01-13 close is dropped (no ETH bar) and documented; it falls only inside training windows. Binance has no gaps from 2017-08-18. Panel hashes are recorded, and nothing is filled or interpolated |

**Final step, the test window: NOT RUN.** Items 5, 8, 9, 14, 15 and 16 fail and the research verdict is NO EDGE, so the
test window is not opened. It is not burned for rebalance-steady.

## Metrics summary (SCOUTING, 1x placeholder costs unless stated)

- **Walk-forward, Kraken, 1456 daily returns (2019-01-04 .. 2023-01-01):**
  - seed A: Sharpe 0.938, +174.0%, max drawdown −41.8%, 3 fills, costs USD 41.31;
  - seed B: Sharpe 1.046, +204.8%, max drawdown −36.7%;
  - at 2x costs: 0.936 and 1.044.
- **Binance** (seed A's parameters): Sharpe 0.942.
- **CPCV-style:** PBO logit distributions per study, 0.024-0.524.
- **Test window:** not run.
- **Monte Carlo** max drawdown p5 / p50: −58.6% / −37.8% (A) and −54.5% / −34.2% (B).
- **Trials:** 2000 raw, 13.63 effective, 2021 strict, plus 54 phase runs.
- **Equity curves:** the daily net returns are in `results/rebalance-steady/train/run0/oos.parquet` (git-ignored),
  columns `S_A` and `S_B`; equity = cumprod(1 + r).

## Auditor's sensitivity check (description; it changes no criterion)

RESULTS.md's open question 2 asks about folds 0 and 3, where S made no fill. There, S runs from a book bought in the
120-row warmup and left to drift, while B3 and B4 buy the targets fresh at the open of t0. With k = 0, B3's pieces in
those folds equal B4's exactly. Replacing S's fold-0 and fold-3 pieces with B4's leaves S and both nulls identical
outside folds 1 and 2. Everything below comes from logged series only.

| | S′ Sharpe (S) | E1′: vs B3 p95, rank p | E2′: D, p |
|---|---|---|---|
| Kraken A | 0.901 (0.938) | below 0.979, 0.557 | −0.047, 0.719 |
| Kraken B | 1.008 (1.046) | below 1.066, 0.343 | −0.023, 0.605 |
| Binance A | 0.908 (0.942) | below 0.985, 0.538 | −0.045, 0.708 |

The difference in starting book favoured S, not the nulls, and **NO EDGE does not depend on it.** A later plan should
start S and its nulls from the same state at t0.

## Non-blocking items

| # | Item | Fix |
|---|---|---|
| N1 | The "In plain words" paragraph (line 18) says "A second search and a second data source agree". The pre-registered E4, named "the two searches agree", **fails** (FRAGILE on G1 and E3) | Say they reach the same NO EDGE result, but the two searches differ on G1 and E3, so E4 fails |
| N2 | Lines 424-426 say the 3158 evaluations "hold the 21 runs of the strict count". They hold 19: the 16 plateau variants, 2 runs at 2x and 1 Binance run. The other 2 are the dip study's mixes, which are prior looks | Change "21" to "19 of the 21" and name the two that are not runs |
| N3 | Section 10 asks for B3's stitched metrics as percentiles. Worst day (and turnover and costs, Deviation 3) are not reported. The per-draw worst day is in `evaluations.csv` | Add worst day to Deviation 3, or report its percentiles |
| N4 | RESULTS.md is uncommitted. PLAN section 12 lists it in the committed record. RISK.md also appeared untracked during this audit; I did not read it | Commit RESULTS.md and AUDIT.md together with the X1 fix, once the full tier passes |
| N5 | The adapter speed check (section 7 step 4) was done after the run (Deviation 2) | None. The real search phase took 45 s against a 60 CPU-minute limit |
| N6 | Design weakness: S and its nulls start each block in different states (see the sensitivity check above) | Pin a common starting state in any successor plan |

## Answers to RESULTS.md's open questions

1. **Power:** E1 and E2 can barely separate S from its nulls with 3 out-of-sample rebalances in 4 years. Any successor
   plan should pre-register a minimum out-of-sample rebalance count, or a band range that guarantees one. That is a new
   study, not an amendment.
2. **E2 in folds without fills:** this is the harness the plan pinned, and the review accepted it. It favoured S (see
   the sensitivity check), so the verdict stands. Fix it in a successor plan (N6).
3. **G5 marks:** taking the most restrictive fold mark is conservative and changes nothing here (1 of 8, where weak
   needs 3).
4. **Coin share:** this is for the owner and the risk-officer. The s-profile shows drawdown rising steeply with s
   while Sharpe barely moves, which supports fixing or capping s in a Steady plan.
5. **Validate window:** it is still unlooked and unburned for rebalance-steady. Any further rebalance-steady variant
   needs a new pre-registration, which should state that validate is not fresh for "does a BTC/ETH mix do well?"
   (PLAN section 2).

## Reproduce

- **Recomputation:** two read-only scripts in the auditor's scratchpad, `audit/recompute.py` and `audit/recompute2.py`.
  They load only the logged returns and summaries.
- **Full tier:** `uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch` on
  `a6ec37c`. Result: 1652 passed and 2 failed (X1) in 201 s, with 100% branch coverage. Coverage data went to scratch.
- **Lint:** `ruff check --no-cache .` passes.
- **Cause of X1:** both tests fail in a scratch `git archive a6ec37c` copy, and pass there once `RUNLOG.jsonl` is
  removed.

## Re-check of X1, 2026-11-20 (`backtest-auditor`)

**Scope:** X1 only. Nothing else was re-audited. No bar was loaded and no backtest was run. The only file I wrote in
the repo is this section. All scratch copies and logs are in the auditor's scratchpad, under `recheck/`.

**Result: X1 PASS. The audit now counts: PASS, with 0 blocking items.** One condition applies: the commit that
carries RESULTS.md and this file must hold exactly the tree I tested (see "Condition" below). The strategy verdict
is unchanged: **NO EDGE, return to the researcher, not ready for risk review.** The test window was not run and is
not burned. The validate window is still unlooked.

### What changed since the audit

Compared with HEAD `a6ec37c`:
- `tests/test_steady_scripts.py` (+14 −1):
  - `real_folders` now also points `S.HERE` at `tmp_path / "here"`;
  - `test_the_look_s_other_refusals` gets its own `S.HERE` stand-in;
  - a new regression test, `test_real_folders_keep_real_runs_away_from_the_repo_s_runlog`.
- `TESTING.md` (+11 −6): bug #48 and section 3.
- RESULTS.md (untracked) gained a section on hard rule 11 and X1. Its SHA-256 is now `e6fbe845e3f5125d…`; it was
  `5f179b5f81f46a17…` when audited.

No file under `lab/` or `config/` changed, and neither did `research/rebalance-steady/*.py`, PLAN.md or the gates.
`study.config_hash(study.file_hashes())` still gives run 0's `1506217f6a731f6a…`.

### Checks

| Check | Result | Evidence |
|---|---|---|
| The fix is test-only and weakens nothing | PASS | The diff adds setup lines, one docstring sentence and one new test. No assertion was removed, loosened or narrowed. `S.HERE` is read at call time, and only by `runlog_path` and `tracked_dir` (`study.py` lines 412-419). `run_train.py`, `freeze.py`, `run_validate.py` and the tests share one module object (`rebalance_steady_study` in `sys.modules`), so the patch reaches all three scripts. `S.PLAN` is fixed at import and still points at the repo's PLAN.md, which these tests need |
| The regression test catches the bug | PASS | I made a scratch copy of the fixed tree and removed only the `S.HERE` line from `real_folders`. Result: 3 failed, 1 passed. The new test, the dirty-tree test and `test_real_runs_use_the_pinned_folders_only` fail with "already records real run 0", the message from the audit. `test_the_look_s_other_refusals` passes because it has its own stand-in |
| The tests no longer depend on what the repo has recorded | PASS | Two scratch copies of the fixed tree, each running all of `test_steady_scripts.py`. (1) The RUNLOG holds real runs 0, 1 and 2 and a real look, and a stub FROZEN.json sits in the study folder: **73 passed**. (2) No `RUNLOG.jsonl`, the `9fdaa4d` state: **73 passed**. Afterwards the copied RUNLOG still had its 4 lines, and the second copy still had no RUNLOG. No test wrote into the study folder |
| Full tier (hard rule 11) | PASS | Run on the working tree: `a6ec37c` plus the files above. `COVERAGE_FILE=<scratch> uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch --cov-report=term-missing`: exit 0, **1655 passed** (12 of them slow), 0 failed, 198.57 s. Branch coverage of `lab/` **100%** (4136 statements, 1220 branches, 0 missed), so `fail_under = 100` is reached |
| Deep profile, the steady files | PASS | `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 tests/test_steady.py tests/test_steady_scripts.py`: exit 0, **139 passed** (66 + 73), 74.26 s |
| Lint and dashboard | PASS | `uv run ruff check --no-cache .`: "All checks passed!". `tests/test_dashboard.py`: 86 passed. The dashboard parses TESTING.md |
| My runs changed nothing the study depends on | PASS | I took SHA-256s before and after all my runs, and they are identical. Files: `RUNLOG.jsonl` (`9cabeedc…`), `trials.csv` (`9072a2e7…`), `evaluations.csv` (`b91f8d24…`), `summary.json` (`8dd86af8…`), the whole `results/rebalance-steady/` tree, the four scripts, PLAN.md, DATA.md, `data/catalog/SNAPSHOT.json`, the test file and TESTING.md. `git status` shows the same 2 modified and 3 untracked files |
| Bug log and section 3 | PASS | Bug #48 follows #47. It is triaged as a test bug, the code is right, and it notes that no assertion changed. Section 3's counts match my runs: 1655 in the full tier, `test_steady_scripts.py` (73), and 139 at the deep profile. Its 190 s against my 198.57 s is just a different run. It says why the whole-suite deep profile was not rerun: no `lab/` file changed |
| RESULTS.md after its edit | PASS (spot check only) | The new section correctly withdraws the claim that no later commit needed the tiers (the old lines 136-138). Every headline number in this audit's "Numbers recomputed" table still appears in RESULTS.md at its rounding: Sharpes, DSRs, PBO, E1, E2, G8, the Monte Carlo p5 and the verdict. I kept no copy of the version I audited, so I could not diff the rest of the text |

### Condition: the commit must carry exactly this tree

AGENTS.md hard rule 11 needs the full tier to pass on the commit. That commit does not exist yet, and committing is not
part of this stage. The tiers above passed on the tree that is to be committed, and no test reads AUDIT.md (checked
with grep). So the result holds for a commit that adds this AUDIT.md and these exact files on top of `a6ec37c`, and
changes nothing else:

| File | SHA-256 |
|---|---|
| `tests/test_steady_scripts.py` | `3a76bb72f06966b8e6dfadff4287bbfbc29631de2e2b8121ed4e179a12e5d146` |
| `TESTING.md` | `5102e5e2b75aff9d9d58c25fb0079f9b2da45ec5dfcfd8ea6b91258a62bd7e26` |
| `research/rebalance-steady/RESULTS.md` | `e6fbe845e3f5125d55b876da0633270c1ac65efa9072de779bbadbf175b9b5ac` |
| `research/rebalance-steady/RISK.md` | `09de92b1e3db0051dd894c2095ebb6c7b76b6c4637bc7fe2e5b30b27421b6e09` |

To check after committing: run `git show <commit>:<path> | sha256sum` for each file, and
`git diff --stat a6ec37c <commit>` (it must list only these four files and AUDIT.md). If any other file differs,
rerun the full tier on that commit.

### Non-blocking items (status when read; not re-checked)

- **N1 is still open.** RESULTS.md line 18 still says "A second search and a second data source agree".
- **N2 is still open.** Lines 461-462 still say the 3158 evaluations "hold the 21 runs of the strict count".
- **N3 and N5-N6:** not re-checked.
- **N4** is closed once RESULTS.md, AUDIT.md and the X1 fix are committed together, as above.

None of these changes a number or the verdict.

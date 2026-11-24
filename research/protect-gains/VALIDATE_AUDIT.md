# protect-gains V1: audit of the single validate look

**Verdict: PASS.** The look ran as [VALIDATE_PLAN.md](VALIDATE_PLAN.md) pre-registered it, once, without reading the
test window. Its outcome is right: **DOES NOT HOLD UP; whipsaw PASS.** Nothing found can flip it. Two findings should
be fixed in the records and the write-up; neither changes a number or an outcome.

`backtest-auditor`, 2026-11-24. This is the one check after the look that VALIDATE_PLAN.md section 7 asks for. It is
**SCOUTING**, like the look: the reference engine, placeholder costs and exchange candles. It was read-only: no
commit, no test-window bar. The reruns asked the loader for closes up to 2024-07-01 00:00 UTC only, through a guard
of the auditor's own. The audit did not read hold-mix-cap's result files or the "Hold this mix" section of
`docs/app/features.md`.

## What was checked

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | V-a, V-b, V-c, the verdict, the robustness labels and the per-mix table, recomputed from section 6 with the auditor's own code | **Match** | From `runs.parquet` and, separately, from `validate_runs.csv`, the same outcomes. Median C 0.090927 (V-a PASS); the 90th-percentile F is 0.233690 against R's 0.163573 and the worst 0.263811 against 0.177507 (V-b FAIL); re-stops 8 of 63 buy-backs, 12.7% (V-c PASS). Binance 1x and Kraken 2x: "DOES NOT HOLD UP; whipsaw PASS", so both labels are "same". Every per-mix number in VALIDATE.md matches. C from `v_end` equals the logged C exactly. 768 runs, none failed, no run id twice |
| 2 | Runs rerun from scratch with an engine that does not use `protect.py` | **Match** | A one-pass book in coin units and USDC cash, written from the plans. It shares only the cost model (`Costs.rate`, gas) and the loader with the lab. Panels came from `load_panel(..., last_close=2024-07-01 00:00 UTC)` through the guard. The engine reran all 84 runs of the Kraken 1x pool (R and A10/30d), all 84 of each robustness pool, and both settings for 0.70/0.75 over the full span. F, `v_end` and C agree with the logged runs to 3.2e-15 or better. Stop dates, buy-back dates and missed rebounds agree in every run checked. The headline and both robustness headlines rebuilt from this engine's own outputs are the same. The 0.70/0.75 j0 run, the pool's worst F (0.263811), has 3 stops and 3 buy-backs. The 30% mixes never fire and equal R bit for bit (`v_end` and F) on every source, cost and window; their largest F is 0.0841 |
| 3 | Protocol | **Held** | (a) In `run()`, STARTED, `start.json` and the RUNLOG line (`"event": "validate look V1"`, `"dirty": false`) are written before `study()` loads any bar. STARTED's time is the RUNLOG line's (23:57:50.565683). `start.json` was rewritten with the panels 0.6 s later, as the code says. `run_validate.py` at the look hashes to the start record's `4c4eb72d…`, equal to `d8855c9`'s and today's. (b) The test window was never read. The guarded loader refuses a request ending after the cut or a returned close after it. Both panels end at 2024-07-01 00:00 (the bar of 2024-06-30, a validate bar). (c) The train-part hashes, Kraken `355aabe2…` (2190 rows) and Binance `2c1a4257…` (1963 rows), equal run 0's `start.json` and PLAN.md section 3. The snapshot `1746a21b75683e76` and bars hash `08f5ca2c…` are as pinned. (d) There are 547 validate rows per source, none missing, and the auditor's own load confirms it. (e) There was one look. The RUNLOG holds one start line and one completion line. Git history is linear, and the reflog shows no reset. `validate_look.json`, `validate_runs.csv` and the V1 RUNLOG lines first appear in `5b5df1e`. `results/protect-gains/` holds only `run0/` and `validate/`. (f) VALIDATE_PLAN.md hashes to `dc9041f0…` today, at `d8855c9` and at its pre-registration commit `55e0dd4`, which came before the script (`e6654f8`). (g) The engine and config files, `protect.py`, `holdmix.py`, `portfolio.py`, `run.py`, `panel.py` and `config/*.yaml`, are byte-identical to run 0's. The only change since run 0 is a line added to PLAN.md's disclosure table. `look.json` and `validate_look.json` are byte-identical |
| 4 | Numbers and claims in VALIDATE.md | **Correct, with the wording points below** | Every headline, per-mix and robustness number is right. Claims confirmed: "never ended ahead in any of the 42 runs" (0 of 42); "cost money in every run where it fired" (28 of 28 fired runs, smallest C 1.7%); "the 30% crypto mixes never fired"; "the same answer from Binance prices and at doubled costs"; and the A10/trend numbers on Kraken 1x (Q 11.6% vs 16.4%, worst 15.5% vs 17.8%, median C 11.5%, median 36% of days in USDC). The mechanism holds (finding 3) |

**Could anything flip DOES NOT HOLD UP?** No. V-b fails on both of its conditions, by 7.0 points (the 90th
percentile) and 8.6 points (the worst). It fails the same way on all four pools (Kraken and Binance, 1x and 2x).
The fall was deeper than R's in 25 of the 28 runs where the brake fired. The CSV's rounding (at most 5e-7 off the
parquet) and the percentile method cannot move margins of that size. V-a passes by 0.009, and a pass there could not
rescue the verdict anyway.

## Findings

1. **Should fix: TESTING.md does not record the test tiers on the look's commit.** VALIDATE.md and the commit message
   say the full tier passed on `d8855c9` (2378 tests, 100% branch coverage), along with the deep profile (2362). But
   the "Last full run" paragraph in TESTING.md section 3 still describes `5e99d68`. Bug #67 records that the tier on
   `f7f3c0b` reached only 99.98% coverage, below `fail_under = 100`. `d8855c9` fixed that with a new test, but its own
   tier run appears nowhere in TESTING.md. Hard rule 11 needs that record. The audit did not rerun the tiers
   (read-only, light CPU). The risk is small: every engine file is byte-identical to run 0's, whose tiers are
   recorded, and the independent reruns reproduce the numbers. The timing also fits: `d8855c9` was committed at
   23:02 and the look started at 23:57, about 54 minutes, roughly what the full tier plus the deep profile take at
   `-n 3`. **Fix:** add the `d8855c9` tier record to TESTING.md section 3: test count, coverage, deep count, ruff,
   durations and a clean tree.

2. **Should fix: VALIDATE.md understates what the brake costs when it acts.** "A typical year ended 9.1% below the tool
   alone (median; mean 11.3%)" is the pool median, and it is correct. But 14 of the 42 runs, one third of the pool, are
   the 30% mixes. Those never fired and have C exactly 0. Over the 28 runs where the brake fired, the median cost was
   **18.3%**. V-a's PASS stands, because the plan fixed the pool before the look. The plain-words sentence should
   still say that V-a passed partly because a third of the pool could not fire, and give 18.3% for the runs where it
   did.

3. **Note: the stated mechanism holds, with two qualifiers.** VALIDATE.md says: "each sale locked in a 10% fall … thirty
   days later it bought back higher, and the next dip started from there."
   - **Where the fall bottoms.** In all 25 runs with a deeper fall than R's, the worst fall starts before a sale and
     bottoms after a buy-back. None bottoms while the wallet is in cash.
   - **How many stops.** 14 of those 25 falls hold one stop. 11 hold two or three: line A's high restarts at the
     buy-back, so a second 10% line sits on top of the loss already locked in.
   - **Gaps are not the driver.** Sales filled past the line by a median of only 1.2% (largest 4.5%).
   - **First qualifier: "bought back higher" is usual, not universal.** In 46 of 63 buy-backs, the mix's index was
     higher at the buy-back's fill than at the sale's (median +10.8%); in 17 it was lower. Say "in 46 of 63".
   - **Second qualifier:** see finding 5.

4. **Note: V-c's 8 of 63 is one market event.** All 8 re-stops are the buy-back of 2024-02-22 sold again on
   2024-03-20, 27 days later. The same event appears in 4 windows for each of the two 70% mixes. The 63 buy-backs are
   24 distinct (mix, date) events. The overlapping 12-month windows were pre-registered, so the 42 runs were never 42
   independent years.

   Five buy-backs come less than 30 days before their window ends, so a re-stop could not be seen. Two of them are
   copies of that same 2024-02-22 buy-back in window j2. Counting those two as re-stops gives 10 of 63 (15.9%);
   dropping all five gives 8 of 58 (13.8%). Either way V-c passes. "It did not whipsaw much" should say that this
   rests on one event.

5. **Note: "separate" equals "counts" by construction.** The tool is not asked to trade while the wallet is stopped. So
   its last counted trade comes at or before the stop close, and a buy-back 30 days later always comes after the
   tool's 15-day wait has run out. "No 30-day buy-back was held back by the tool's wait" is true, but it could never
   have been otherwise, so the "separate" runs add no information at this setting.

6. **Note: small slips in VALIDATE.md.**
   - "768 runs … in 13 s": `look.json`'s `grid_runtime_s` is 11.2 s, and 11.9 s passed from STARTED to the completion
     line.
   - "The full 18-month span (6 runs a mix)": it is one run per mix for each source, cost and setting, so 96 runs,
     16 per mix.
   - "A10 with the trend buy-back … cut the bad-case fall": true on Kraken 1x, as quoted. On Binance 2x its worst F
     is just above R's (17.83% against 17.67%). This is a description only.

## Records

- **Inputs:**
  - `results/protect-gains/validate/` (`STARTED`, `start.json`, `runs.parquet`, `stops.parquet`, `look.json`);
  - `research/protect-gains/` (`validate_look.json`, `validate_runs.csv`, `RUNLOG.jsonl`, `VALIDATE.md`,
    `VALIDATE_PLAN.md`, `run_validate.py`, `PLAN.md` section 3 and its disclosure table, `README.md`);
  - `results/protect-gains/run0/start.json` (panel hashes and file hashes only);
  - `lab/runner/protect.py` (docstring, pinned readings, `ToolStep`, `tool_params`, `run_measures`);
  - `lab/runner/portfolio.py` (`_simulate`, `_breach_test`);
  - `lab/data/panel.py` (`load_panel`), `lab/data/catalog.py` (`load_bars`) and `lab/runner/holdmix.py`
    (`window_slice`);
  - TESTING.md section 3 and bugs #65-#67;
  - git history and the reflog.
- **Scripts** (scratch, not committed), in
  `/tmp/claude-0/-home-user/45b9259c-cd7f-5869-8006-179fd7a14409/scratchpad/v1audit/`:
  - `recompute.py`: section 6 from the tables;
  - `claims.py`: VALIDATE.md's claims and the stop rows;
  - `rerun.py` and `engine.py`: the independent engine and its guarded loads;
  - `pool.py`: the three pools rebuilt from the engine;
  - `episodes.py`: the mechanism, the distinct events and window-end censoring.
- **Validate-window looks used for protect-gains:** 1 of 1. The test window was not read.

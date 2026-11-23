# protect-gains: audit of run 0

**Verdict: PASS.** The outcome stands: NO DEFAULT for line A and line B, "none" shown first, "counts" in force, D4
MISSING (boom: without the best 2), D5 MISSING. My own code reproduces every decision in `decision.json`. An
independent engine reproduces the runs. I found no look-ahead and no read past 2023-01-01. Nothing I found could
flip NO DEFAULT. RESULTS.md needs a few corrections (findings 1-3). None of them changes a decision.

`backtest-auditor`, 2026-11-23. The plan has one audit (PLAN.md section 11, step 5), and this is it. SCOUTING: the
run used the reference engine and placeholder costs, makes no edge claim and has no luck gates. The test window was
not run. That is correct here, because nothing is being signed off. Validate-window looks: 0. Test-window looks: 0.

## What I checked, and how

| # | Check | Result |
|---|---|---|
| 1 | **Decisions recomputed** from `runs.parquet` and `stops.parquet` by my own code, written from PLAN.md section 8 and A2. It does not call `protect.d1..d6` and does not use the `restops` column. Covered: D1 (`np.percentile(...,90)`, pooled and per-mix `3*Q <= 2*Q0`, the worst-F guard, the C̃ tie within 1e-12, then C̄, then the looser level), D2 (re-stop share from the stop rows, eligibility, the case table), D3, D6, D4 (Binance 1x, Kraken 2x, both boom removals with 12(Y−2017)−23 ≤ k ≤ 12(Y−2017)+11 and the 12-window minimum) and D5 | **Match.** Both readings: D1 is meaningful only at A/trend/10%; D2 A and B NO DEFAULT; D3 none; D6 recommends "counts" (no line has a default under both readings). Binance and 2x: NO DEFAULT, with A/trend/10% meaningful (Q 0.2556 and 0.2667, re-stop shares 34.5% and 36.4%). Boom −2017 keeps windows 12-48 (37) and gives NO DEFAULT. Boom −2017−2020 keeps windows 12 and 48, so MISSING. The yearly returns I computed from the panel equal `start.json`'s. My C (from `v_end`) equals the table's C exactly, and my re-stop, buy-back and stop counts equal the run columns on all 81,216 brake runs. The rounded committed `runs.csv` gives the same decisions |
| 2 | **Runs re-run from scratch** with an independent one-pass engine in coin units and USDC cash. It decides every order itself (the tool's band, limits and 15-day wait; the line; each buy-back mode; both readings) and uses a hand-written copy of the `costs.yaml` model. It is causal by construction and does not import `protect`, `holdmix` or `portfolio`. Bars came from `load_panel(..., last_close=2023-01-01 00:00 UTC)` | **285 runs, 0 mismatches.** I compared F, V_end, C, every stop close, buy-back, held buy-back, unfilled crossing, re-stop count and overshoot. The largest difference is 7e-15. The sample: 250 random runs (both sources, both cost levels, both readings, R and both lines); the A/trend/10% run holding the 2020-03-13 sale; 6 A/trend/10% runs with re-stops; 5 B runs that sold below D; 5 "counts" runs with held buy-backs; 3 runs with an unfilled crossing |
| 3 | **Look-ahead and timing** | **PASS.** Code read: `_simulate` fills an order from close t at the open of t+1. H, the lines, I, SMA200, R2's dip, the 7-day minimum and the "counts" hold all read closes up to t only. `next_stop` re-running is causal: a stop changes rows from t+1 on. Tamper-the-future on the real Kraken panel: every bar from a cut onward was scaled at random, and the fill open at the cut was kept. I used 75 cuts, including every stop close, every buy-back close and the close after each, over three settings (A/trend/10%, A/rebound0/10% with 12 stops, B/wait30). No `ret`, order, stop or buy-back before a cut moved. Data: both panels end 2023-01-01 00:00 UTC, with 2190 and 1963 rows. The panel hashes and the bars hash in `start.json` equal section 3's. Nothing else is read (A1's timing uses synthetic bars) |
| 4 | **RESULTS.md against the outputs** | All 72 rows of the full table match my numbers in every column: fires, Q, Q/Q0, mixes, worst F, C̃, C̄, re-stops, time in USDC and largest overshoot. So do the R table, the A/trend/10% section and the record. Exceptions: findings 1-7 |
| 5 | **Other** | Costs: `Costs.from_yaml(capital_usd=5000)` and `.stressed(2.0)` double fees, slippage and gas, and keep D = 5000. The fee split adds up to `money_metrics` (checked in the run). Windows: 49 Kraken and 41 Binance, with closes from the 2nd of M_k to the 1st of M_(k+24). Counts: 42,630 + 39,420 = 82,050, 0 failed. Since `5e99d68` only docs and outputs have changed. `tests/test_protect.py` and `tests/test_protect_run.py`: 111 passed (43 s, `-n 3`). I did not rerun the full tier; I rely on the recorded run on `5e99d68` |

## Could anything flip NO DEFAULT?

No. The only lever is D2's re-stop eligibility at A/trend/10%. If that setting were eligible, A's default would be
trend at 10%, because wait-30 has NO DEFAULT.

- **The definition is applied as pinned.** A re-stop is a buy-back whose next filled stop's order close is ≤ 30
  days after the buy-back's order close (its fill instant). Buy-backs near a window's end stay in the denominator.
  That gives 282 / 774 = 36.4%.
- **The share stays above 25% under every variant I tried.**
  - Re-stop gaps run 12-29 days. The share drops below 25% only if the window is 25 days or less; at ≤ 29 days it
    is 34.5%.
  - Dropping the 34 buy-backs that fall within 30 days of a window's end gives 37.3%.
  - Distinct (mix, buy-back date) events: 38.1% (n = 42). Distinct dates: 42.9% (n = 14).
  - Binance: 34.5%. Kraken 2x: 36.4%.
- **No other setting is near D1.**
  - A/wait30/10% passes the pooled test (0.664) but fails 4 of 6 mixes; the worst mix is at 0.853.
  - A/trend/15% fails 3 of 6 (worst 0.867).
  - A/wait180/10% fails 2 of 6, and wait-180 decides nothing anyway.
  - No line B setting protects any mix.

## Findings

**1. Should fix. "Sold below the deposit 101 times" is one crash day.** Every one of the 101 below-D sales (counts
reading) is the stop ordered at 2020-03-13 00:00 UTC, the close of 12 March 2020. They are 10 distinct (mix, Y) pairs,
mostly Y = 0.40, repeated across overlapping windows and the six buy-back modes. Also, "over the stage-1 pool" is
one reading: the stage-1 pool holds both readings, and has 202 such sales. RESULTS.md says this twice ("In plain
words" and "What did not work"). Suggested wording: "it sold below the deposit on one day, 12 March 2020, in 101
runs (10 mix and level pairs), the worst 17.2% below". The 17.2% worst figure is right.

**2. Should fix. A/trend/10%'s robustness leaves out the boom-year check, and that check matters for option 2.**
Without the windows overlapping 2017 (windows 12-48), A/trend/10% is not meaningful: 5 of 6 mixes pass, and the 30%
crypto, 75% BTC mix is at 0.726 of its Q0. The pooled ratio is 0.441 and the re-stop share 34.0%. RESULTS.md's
"Robustness" bullet names only Binance and 2x, which both pass. The headline row says "without 2017 NO DEFAULT",
which is true at D2, but it hides that the one protective setting itself fails there. Option 2 ("suggest line A at
10% with the trend buy-back anyway") should say so, and should say that its D4 label is MISSING.

**3. Should fix (small). "Line A at 15-20% (trend or wait-180) cut the pooled bad case by a third."** That holds for
trend at 15% and 20% and for wait-180 at 15%. Wait-180 at 20% is 0.743 and fails the pooled test. Six settings pass
the pooled test: trend 10/15/20%, wait30 10% and wait180 10/15%.

**4. Note. "In 2018 and 2022 a 30% crypto mix still fell about 40%."** Every 30%-crypto R window with F ≥ 35% (30
runs, 35.5-41.1%) troughs in 2018. The worst 2022 trough is 32.7%.

**5. Note. Thin or truncated figures that need their basis stated:**
- "By the window's start year ... 2021 −27%" comes from one window (k = 48) × 6 mixes. Each other year has 72 runs.
- "A median stop stayed out 91 days" includes the 196 stops never bought back, which are cut off at the window's
  end. For stops that were bought back, the median is 73 days.
- "Fires (share of windows)" is the share of runs (window × mix).

**6. Note. Small number slips.**
- Line B "fired in 63-74%" should be 63-73% (the maximum is 0.735).
- "Some made the worst fall deeper" is 35 of 72 settings, about half.
- README.md repeats "Validate-window looks used: 0."

**7. Note. "For the owner."** Option 2 is labelled correctly as an override, the owner's written decision and not a
lab default. Option 1 would show this study's table to customers in the app. Those numbers are scouting numbers:
reference engine, placeholder costs, 49 heavily overlapping in-sample windows, and D5's promise number MISSING. They
should be rerun on NautilusTrader with measured costs before a customer sees them as statistics. RESULTS.md should
say that next to option 1.

**8. Note, design (no action for run 0). D4 could not have said ROBUST.** BTC's two best years are 2017 and 2020,
and removing both leaves only windows 12 and 48. So the two-best-years check is MISSING for every possible default,
and every label in this study would have been MISSING at best. The plan accepted this ("may well be MISSING"). A
future plan that wants a usable boom check needs another removal rule or shorter windows.

**9. Note, description.** The trend buy-back with R2 waits through rallies, and that drives both the cost and the
re-stops. Its dip and its signal share one threshold, 1.02 × SMA200. A stop taken while the index is above its
trend waits for the next dip below the threshold, and then buys back on the first Monday above it. Example: window
40, mix 0.70/0.75 (re-run independently).
- It was stopped 2020-09-04, with no dip until 2021-05-24, so it sat in USDC through the late-2020 rally.
- It bought back 2021-06-07 (I/SMA 1.022) and was stopped again 15 days later.
- A second re-stop followed: bought back 2022-01-03 (I/SMA 1.028), stopped again 2022-01-22.

This matches the 71% missed rebound after the 2020-03-13 sale. RESULTS.md could say it in one line.

**10. Note.** The committed `runs.csv` is written with `%.6g`. The decisions recomputed from it are the same (I
checked). Boundary-exact rechecks need the git-ignored `runs.parquet`.

## The 2020-03-13 sale (re-run independently)

Window 38, mix 0.5/0.5, A/trend/10%, Kraken 1x, "counts":
- **The crash day.** The stop was ordered at close 2020-03-13 00:00 UTC. That bar is 12 March: Kraken BTC opened at
  7961.3 and closed at 4850.0, −39.1%.
- **The sale.** H was 5250.37 and the line 4725.34. The wallet sold at the next open; V at the fill row's close was
  3827.55. The overshoot was 0.1900, which is the pool's largest.
- **After the sale.** The trend buy-back was ordered 2020-04-27. The missed rebound was 71.1%, and the buy-back was
  not re-stopped.

The run's other stops were 2020-09-06, 2021-09-21 and 2021-11-27; the last was not bought back.

## Files read

- **Plan, write-up and record:**
  - `research/protect-gains/PLAN.md`, `RESULTS.md`, `README.md`, `RUNLOG.jsonl`
  - `research/protect-gains/decision.json` and `runs.csv`
- **Run 0's outputs:** `results/protect-gains/run0/start.json`, `summary.json`, `runs.parquet`, `stops.parquet`,
  `failures.parquet`, `decision.json` (`blocks/` listed only).
- **Code:**
  - `lab/runner/protect.py` (lines 125-685 and 920-1579)
  - `research/protect-gains/run.py` (lines 75-180, 520-580, 690-1300)
  - `lab/runner/portfolio.py` (`_simulate`, `_breach_test`)
  - `lab/runner/reference.py` (`Costs` slippage, rate, stressed)
  - `lab/runner/holdmix.py` (`mix_targets`, `window_slice`, the `money_metrics` docstring)
  - `lab/validation/montecarlo.py` (`max_drawdown`)
  - `lab/runner/trend.py` (`sma`)
  - `lab/data/panel.py` (`load_panel`'s signature)
- **Config and docs:** `config/costs.yaml`; TESTING.md (as loaded).
- **Run, not read:** `tests/test_protect.py`, `tests/test_protect_run.py`.
- **Data:** the Kraken and Binance daily train panels through `load_panel(..., last_close=2023-01-01 00:00 UTC)`.
  No validate or test bar was read. None of hold-mix-cap's result files and not the "Hold this mix" section of
  `docs/app/features.md`.
- **Scratch scripts:** `recompute.py`, `engine.py`, `rerun.py`, `claims.py` in
  `/tmp/claude-0/-home-user/45b9259c-cd7f-5869-8006-179fd7a14409/scratchpad/`.

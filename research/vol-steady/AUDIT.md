# vol-steady: audit of run 0 (SCOUTING)

`backtest-auditor`, 2026-11-24. This is the study's one audit (PLAN.md section 14, order of work step 6). It checks
run 0 (the train window only) and the lead's RESULTS.md against the plan as amended (M1, A1, A0) and against the
outputs. It was done lean, at the owner's request: one auditor, no sub-agents, focused checks only. I changed no code,
no PLAN.md, nothing in `config/` and no run output. My scratch scripts are in the session scratchpad under
`volaudit/`.

> Every number here is SCOUTING. It comes from the lab's reference portfolio engine, uses the placeholder costs in
> `config/costs.yaml`, and treats exchange candles as stand-ins for Base prices. Nothing here is a NautilusTrader
> result, and nothing here makes anything ready for paper.

## Result

**PASS for the run and its verdict.** Run 0 followed the protocol. I rebuilt every decisive number with my own code,
and each one matches `summary.json` to round-off. The verdict follows mechanically from the plan's rules: **NO
EDGE**, because E2 fails. E2's p is 0.245, nowhere near 0.05, so **nothing I found can flip NO EDGE**. There was no
validate look, and the test window was never read.

**The write-up is not final yet.** RESULTS.md's tables are right cell for cell, but six of its claims are wrong or
misleading (findings 1-6). One of them concerns the seed-A E1 pass. **That pass is not evidence of volatility
timing.** It comes from 2018 alone, and in large part from the share s that the walk-forward picked for each fold,
not from the volatility steps. None of the six changes the verdict, a gate or a criterion. They should be corrected
before RESULTS.md is final, because the next study (the owner's "different angle") will list this run as a prior
look and lean on its narrative.

**The strategy:** not ready for risk review. It is NO EDGE, and it fails G1, G3, G4, G6 and G8-excess. The plan
stops here. The final test window (G9) was not run, so it is still unused for vol-steady.

## What I checked

### 1. Protocol

| Check | Finding | Evidence |
|---|---|---|
| One run 0 only | PASS | `RUNLOG.jsonl` has one line (run 0, `run_train.py`, real data, commit `cc03c2a`, clean). `results/vol-steady/train/` holds `run0/` and the 12 study folders `vol-steady-s{0,1}_{wf00..wf04,final}`, with no `_a<k>` study. `trials.parquet` and `trials.csv` have 2400 rows each: 12 studies × 200 trials, all COMPLETE, all run 0. `evaluations.csv` has 1617 rows, 48 of them counted, so the strict count is 2400 + 48 + 1 = 2449, as recorded |
| Clean tree, right commit, code unchanged since | PASS | The start record has `git.dirty: false`, `changes: []` and commit `cc03c2a`. I recomputed all 40 file hashes in the start record against today's tree. Only `research/vol-steady/PLAN.md` differs, and its diff since `cc03c2a` is the T1 row of section 20 alone. `ea1426e` (the results commit) touches only PLAN.md, README.md, RESULTS.md, the RUNLOG and the two CSVs |
| A1, A0 and the owner's decision before run 0 | PASS | The start record's `prior_amendments` holds the A1 line (N = 200), the A0 line, and `owner_decision: reports/director/2026-11-24-owner-answer-vol-a0-power.md`. That record lists the four follow-up angles and says they were written before run 0 read a bar |
| No bar after 2023-01-01 00:00 UTC | PASS | The code path is `load_study_panel(TRAIN_LAST_CLOSE)` → `load_panel(last_close=2023-01-01)` → the catalog query with `end = last_close`, then a re-assert on `index.max()`. The recorded panels end at 2023-01-01 (Kraken 2190 rows from 2017-01-02; Binance 1963 rows from 2017-08-18). My own load went through a loader that refuses any request or returned bar past the cut. All four requests ended at 2023-01-01 |
| Train-window and snapshot pins | PASS | Snapshot `1746a21b75683e76` and bars hash `08f5ca2c…` are in the start record. My own load reproduces both panel hashes (`355aabe2…` and `2c1a4257…`, TP 3's). Kraken lacks only 2018-01-13, as pinned. Every trial's `context` carries the snapshot, the bars hash, commit `cc03c2a` and the config hash `266c6d43…` |
| Tiers on the run's commit | PASS on the record; see finding 7 | RESULTS.md says that on `cc03c2a` the full tier gave 2378 passed with 100% branch coverage, and the deep profile 2362. TESTING.md #68 records the one failure on `2bdd7fd` and its fix. I did not rerun the full tier. I reran the two vol-steady test files on today's tree: see finding 7 |
| No validate look | PASS | There is no FROZEN.json and no `validate/` folder, and `look_earned` is false. NO EDGE earns no look (TP 13) |

### 2. The decisive numbers, recomputed

I wrote the rule from PLAN.md section 4 myself:
- the basket log return;
- σ̂ by `numpy.std(ddof=1)` × √365, not the module's `math.fsum`;
- the quarter step and Monday checks.

I also wrote my own book, in coin units and USDC cash. Fills are at the next open. Leg costs come from
`config/costs.yaml`'s numbers in my own slippage function. Limit fixes are at 0.20 / 0.60 + 1e-9.

From the lab I used only:
- `load_panel`, behind my guarded loader;
- `montecarlo.stationary_bootstrap_indices` and `block_bootstrap_drawdowns`, to replicate E2's and G6's random draws.

I also ran E2 with my own stationary bootstrap at other seeds.

| Number | Mine | `summary.json` | Match |
|---|---|---|---|
| S, both seeds, every fold, 1x and 2x | Equal to `oos.parquet`'s S_A, S2_A, S_B and S2_B to 4.4e-16 per row. Sharpe 0.801922 (A) and 0.669482 (B) | the same | yes |
| σ̂ and q | Relative σ̂ difference ≤ 8e-15 from `volsteady.vol_path`; 0 q mismatches over all 10 fold runs | | yes |
| R_0 (one book, the share path stitched by fold, fold 0's per-row head) | Equal to `oos.parquet` to 4.4e-16. Sharpe 0.8632 (A), 0.6133 (B). R_0 equals S bit for bit on fold 0's 364 kept rows (M1's head reading) | the same | yes |
| E1 | A: W = 260; 3 of the 207 guarded shifts at or above; rank p 3+1 / 208 = **0.0192**. B: 57, **0.2788**. Each shift's Sharpe matches its `evaluations.parquet` row to 7e-15 | 0.0192 (3); 0.2788 (57) | yes |
| E2 | A: D = +0.08322, p **0.2454**. B: D = +0.07826, p 0.3048. My own bootstrap at seeds 11-13 (4000 resamples) gives p 0.240-0.244 (A) and 0.299-0.318 (B) | 0.2454; 0.3048 | yes, and robust to the draw |
| E3 | A: S −47.31% / MC p5 −69.38% against X −44.97% / −67.70%: both deeper, so it fails. B: S −45.39% / −66.86% against X −39.27% / −67.44%: the drawdown is deeper, so it fails | the same | yes |
| E4 | A: S at 2x 0.7934 > N0 at 2x 0.7172 | the same | yes |
| E6 (Δ_y = Σ ln(1+S) − ln(1+N0) by bar-year) | 2018 −0.0040, 2019 +0.1207, 2020 +0.1668, 2021 −0.1436, 2022 −0.0012. Total Δ +0.1387. Δ − Δ_2020 = **−0.0281 < 0**, so it fails | the same | yes |
| P | Per fold 27, 5, 3, 6, 4: **45** in 5 folds (B: 47). Each fold's first buy is not counted | the same | yes |
| G6 (p5 of 1000 block-bootstrap max drawdowns, block 20, seed 0) | **−0.6938** against a −0.35 budget. Seeds 1-3 give −0.703, −0.690 and −0.696; block 60 gives −0.722. The historical drawdown alone (−47.3%) breaks the budget | −0.6938 | yes |
| N0 and X | Each equals `oos.parquet` to ≤ 5.6e-16 (N0 at 1x and 2x, X; both seeds) | | yes |
| Bear years removed (2018 and 2022) | E1 rank p **0.3173** (65 at or above) | 0.3173 | yes |

**Nothing is close to flipping the verdict.** NO EDGE needs only E1 or E2 to fail (TP 12), and E2 fails at p ≈ 0.25
under every draw I tried. E3, E5, E6, E7 and E8 fail as well, but under a NO EDGE verdict they cannot move the
headline. Every gate that fails, fails by a wide margin. G6 is −69% against a 35% budget at S, and at every grid step
and S(s_k) (−51% to −85%). G3's DSR is 0.001, and G4's PBO is 0.70.

### 3. S rerun from scratch, look-ahead

- **The rerun.** I reran S for all five folds, both seeds, on the real panels from `load_panel(..., last_close =
  2023-01-01 00:00 UTC)`. It equals `oos.parquet` (table above). Seed A's kept fills are 27, 5, 3, 6 and 4. There
  were no limit fixes in any test year, which matches `limit_fixes: 0`.
- **No look-ahead.** My implementation decides at close c from closes up to c and fills at c + 1. The engine's
  returns equal mine to 4.4e-16, so the engine does the same.
- **Tamper check.** I also tampered with the lab's own adapter on real bars. For each of the 10 fold parameter sets I
  scaled every OHLC of both coins by random factors from a cut on, at 7 cuts (one of them a Monday check close). In
  all 70 cases the returns, the share path and the orders before the cut were unchanged, and later rows did move.

## Findings

Severity: **blocking** (the run or its verdict cannot stand), **should fix** (the write-up says something the outputs
do not support), **note** (worth knowing; no change required).

No finding is blocking.

**1. Should fix: the seed-A E1 pass is not evidence of volatility timing.** RESULTS.md says "the timing looked
meaningful with one search seed and not with the other". The outputs show that this pass is driven by 2018 and by the
walk-forward's per-fold share s, not by the volatility steps:

- **It is one year.** Without 2018 alone, seed A's rank p is 0.1875 (38 shifts at or above). Without 2018 and 2022
  it is 0.317. Without any other single year it stays near 0.02. Fold 0 also holds 27 of P's 45 share changes.
- **It is largely the per-fold s.** The plan's shift moves each entry with its fold's s (section 9). The searched s
  happens to be low in both bear years for seed A: 0.31 in 2018 and 0.37 in 2022, against 0.56 and 0.55 in 2019 and
  2021. A shift therefore puts more crypto into 2018. Two diagnostics on the same 207 offsets (mine, not plan
  criteria) separate the two parts:
  - shifting only q, with each fold's s kept in its own year, gives rank p **0.067** (A) and **0.082** (B), so both
    fail;
  - rotating only s, with q kept in place, gives **0.034** (A), which passes.
- **At a constant share it fails everywhere.** The plan's own S(s_k) runs keep the same L and τ, and so the same q
  path, at a fixed s. E1 fails at all four allowed shares: rank p 0.173 (s 0.30), 0.245 (0.40), 0.279 (0.50) and
  0.250 (0.60).
- **The seeds differ mostly in s.** Fold 0's L and τ are almost identical across the seeds (A: 10 days and 0.4646;
  B: 10 days and 0.4657). The q path on 2018's kept rows is identical in both, with 27 counted changes each. The seeds
  mostly differ in s: A 0.31, 0.56, 0.35, 0.55, 0.37; B 0.46, 0.39, 0.31, 0.32, 0.37.
- **Chance alone could produce one pass.** With two seeds tested, and the slow calibration's 13 of 200 false
  positives at (120, 0.80, 0.50), one pass in two seeds under the null is not rare.

**Fix:** say plainly in RESULTS.md that the seed-A E1 pass is not credible evidence of timing, with these numbers.
**For future plans** (a note to the director and the lead, not a change to this study): E1 credits the walk-forward's
year-to-year choice of a user setting. A pre-registered E1 that shifts q with s held at its calendar fold, or that is
judged at S(s_k), would test the timing alone. Since S(s_k)'s E1 is already a measurement point, the cheaper fix is
for the headline narrative to cite it.

**2. Should fix: "wild up-moves in 2020-21 made the rule step back from rallies" is not what the run saw.** Seed A
stepped down at four checks in 2020-21. At each one I measured the share of the L-day window's variance that came
from up days (squared deviations of the up-day basket returns over all squared deviations):

| Check | Share of window variance from up days | Window's basket return | The next 4 weeks |
|---|---|---|---|
| 2020-03-16 (q 1 → 0.25) | 0.21 | −40.3% (the 12-13 March crash) | +29.3% |
| 2021-01-25 (q 1 → 0.75) | 0.40 | +101% | +58.1% |
| 2021-05-24 (q 1 → 0.75) | 0.39 | −18.3% | +5.3% |
| 2021-06-28 (q 0.75 → 0.5) | 0.46 | −40.9% | +6.5% |

- **Down days carried most of the variance every time.** In 2020 the rule stepped back after a crash, then missed the
  rebound.
- **Only one step-down came inside a rally, and even there down days led.** On 2021-01-25 the largest moves in the
  window were the January drops.
- **Across all 21 of seed A's step-downs, up days rarely led.** Their up-day share ranges from 0.11 to 0.56, and only
  3 reach 0.50.

So a downside-only volatility would likely have stepped back at least as often here. **Fix:** replace the sentence. If
the lead wants to describe what cost the rule in 2020-21, it was steps back that then missed a rebound or a rally:
2021-01-25 .. 03-21 has the largest regret (+0.078 log against N0), then 2021-05-24 .. 07-18 (+0.017). Each was
triggered by a window in which down days carried most of the variance. The pre-registration of any downside study
should not cite this run as support.

**3. Should fix: "the 2018 step-back ... is the bulk of the rule's timing value" needs its two meanings separated.**

- **Against the shifts (E1), it is true but confounded.** Without 2018, seed A's E1 fails (rank p 0.19). Part of
  that is fold 0's low s (finding 1).
- **Against holding the same share (N0, the E2 and E6 comparator), it is false.** S's 2018 is −0.004 log behind N0.
  The January-July spell gained 0.059 and the November spell 0.048. Over 2018's rows S gained +0.106 while stepped back (q < 1) but lost
  −0.110 at the full share, as it re-cut back up to s while N0 drifted down unrebalanced.
- **S's lead over N0 comes from 2019 and 2020.** 2019 gives +0.121, mostly the July 2019 step-back (regret −0.075).
  2020 gives +0.167, and that is not timing:
  - S's and N0's books were identical until the 2020-03-16 step-back;
  - through 2020-04-06, S was 0.002 log *behind* N0;
  - the whole +0.169 came after the 2020-04-07 re-buy to the full share (crypto 0.38 against N0's drifted 0.28).

**Fix:** state both readings. In the E6 row, give the failing condition, not the negative years: without 2020, the
lead over N0 is −0.028.

**4. Should fix: the S(s_k) gate row gives the wrong reason.** RESULTS.md has "FAIL (G6 at every share from 0.30 to
0.60)". The "S(s_k) check" item is E1 and E2 measured at each allowed share, and its 8 points all fail:
- E1 rank p 0.17-0.28;
- E2 p 0.32, 0.11, 0.23 and 0.47.

G6 at S(s_k) is a separate point, under G6. **Fix:** say the timing fails at every allowed share. That is the most
direct evidence for finding 1.

**5. Should fix: two statements disagree with RESULTS.md's own fold table.**
- "So it held the full share about 90-97% of the days": the table's time at the full share for folds 1-4 is 86%,
  94%, 69% and 92%. The 92-98% figures are the mean q.
- "it stepped back half the time in 2018": it was below the full share on 85% of 2018's days. Its mean q was 0.52,
  so it held about half its share on average.

**6. Should fix: two numbers are attributed to the wrong series.**
- **The costs line describes R4, which is θ_final(A).** That is L = 15, τ = 1.05, s = 0.40, fitted on all the train
  years and run in-sample over the 1820 kept rows (`run_train.r4`). It is not S. "The Sharpe with gas charged is
  0.88" sits next to S's 0.80, and a reader will take it for the rule's. **Fix:** label it as θ_final(A), in sample.
- **"X ... did better on every measure."** X's worst day is −22.6%, against S's −14.7% (the table's own cells).

**7. Should fix (records): the tier runs on `cc03c2a` are recorded only in RESULTS.md.**
- TESTING.md section 3's "last full run" still names `d8855c9`. #68 records the failure on `2bdd7fd`, not the passing
  runs on `cc03c2a`. Hard rule 11 makes that pass the condition for the result to count, so it should be in TESTING.md
  section 3 with its times, like trend-steady's.
- I did not rerun the full tier. I reran `tests/test_volsteady.py` and `tests/test_volsteady_scripts.py` (`-m "not
  slow"`, `-n 3`) on today's tree, which now holds the real run 0 RUNLOG line. The result: 136 passed in 177 s, exit 0.
  So the #48/#59/#68 class (tests that depend on what the repo has recorded) did not recur with the real run 0 line
  in place.

**8. Note: E2's comparator never rebalances, so D is partly a rebalancing effect.** N0 orders (s/2, s/2) at t0 and
then only fixes limits. S re-cuts to s × q at every change of q. In 2020 that re-cut alone gave S its +0.169 log lead
(finding 3). A periodic rebalancer would have captured it with no volatility rule; the correlation with
rebalance-steady's S is 0.96. This is TP's reviewed design, and E2 fails anyway, so it changes nothing here. A later
study should know it.

**9. Note: few trades for the parameters.**
- Seed A's S has 45 kept fills for 3 free parameters: 15 per parameter, under the 30 that my checklist flags.
  `summary.json` flags it (`trades_per_parameter.flag: true`), but RESULTS.md does not mention it.
- 27 of the 45 are in 2018. After 2018, each fold chose τ near 1.0 and made 3-6 trades a year.

**10. Note: M1's readings hold and are conservative.**
- **The strict count.** N_raw + 49 = 2449 keeps TP's K4 term. It can only lower the strict DSR, which is about 3e-14
  at every count; the effective-count DSR is 0.001.
- **R_0's head.** Fold 0's per-row share reproduces R_0 bit for bit with my independent construction, and R_0 equals
  S on fold 0's kept rows.

**11. Note: the T1 row is outside its table.** PLAN.md section 20's T1 row was added after a blank line, so Markdown
renders it outside the looks table. Remove the blank line.

## Checklist (backtest-auditor)

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | Independent rule and book equal to 4.4e-16; 70 tamper cases unchanged before the cut |
| 2 | Survivorship | N/A | BTC and ETH only |
| 3 | Data snooping | PASS | Validate-window looks used: 0. The test window was not read. Prior train looks V1-V3 are disclosed (PLAN.md section 2) |
| 4 | Point-in-time inputs | PASS | σ̂ at c reads closes up to c; activation is at the first Monday with c ≥ L |
| 5 | Trades per parameter | FLAG | 45 / 3 = 15 (finding 9) |
| 6 | Plateau ±20% | PASS (G5) | Every step ≥ 0.7 × S's Sharpe |
| 7 | Walk-forward | PASS (as run) | 5 expanding folds, 365-row test blocks, H0 from row 0. S out of sample: Sharpe 0.80 (G1 FAIL) |
| 8 | DSR, total trial count | FAIL | 0.001 effective (about 16 effective trials of 2400); about 3e-14 at the raw and strict counts |
| 9 | PBO | FAIL | 0.70 (active rows), 0.72 (all rows) |
| 10 | CPCV distribution | N/A | Not in the plan (TP's protocol is walk-forward with the shift null) |
| 11 | Cost model | PASS (placeholders) | `config/costs.yaml` as read; costs are still placeholders (SCOUTING) |
| 12 | Doubled costs | PASS (G2) | S at 2x: 0.79 > 0.5 |
| 13 | Capacity | N/A | Scouting; no measured slippage |
| 14 | Monte Carlo against the budget | FAIL (G6) | p5 −69.4% against 35% |
| 15 | Regimes | FAIL (G8-excess) | The bull regime carries the excess over N0 |
| 16 | Benchmarks | PASS (G7) against B1 and B2; E1 and E2 fail | Section 2 |
| 17 | Data quality and snapshot | PASS | Snapshot and panel hashes reproduced; the one known missing close |

Final test window: **not run**. Items 1-17 do not all pass, and the verdict is NO EDGE.

> **Lead's correction, 2026-11-25 (after downvol-steady's audit found the same wording there).** Finding 8 says "N0
> orders (s/2, s/2) at t0 and then only fixes limits". As `trend.always_in_n0` is written (TP section 9), N0 orders
> the year's share at t0 only when the rule does not already hold those targets, that is, only when the rule was
> stepped back at the year's start. Here that was 2018 and 2019 (q 0.25 and 0.75 at t0). In 2020, 2021 and 2022 the
> rule held its full share, so N0 kept the rule's wallet as it had drifted (26%, 59% and 48% crypto at the year's first
> close, against shares of 35%, 55% and 37%). Rebuilt with `trend.always_in_n0` on the train panel, N0 equals
> `oos.parquet`'s N0_A bit for bit. No number, finding outcome or result of this audit changes; RESULTS.md now
> describes N0 this way.

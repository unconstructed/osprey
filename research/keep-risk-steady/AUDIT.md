# keep-risk-steady: audit of run 0 (`backtest-auditor`, 2026-11-25)

**Scope.** The study's one audit (PLAN.md section 13), of run 0 on commit `2a43cc4` and of RESULTS.md as committed in
`ccac3d6`. The study is a user tool under the owner's tool rules: it claims no return edge, AGENTS.md's managed-strategy
gates do not apply (PLAN.md section 1), no validate look is planned, and the test window is never opened for it. So
this audit does not run the test window. Every number below is SCOUTING (the reference engine, placeholder costs).

**What the auditor read:** CLAUDE.md, AGENTS.md, TESTING.md; PLAN.md in full; RESULTS.md in full; README.md's diff
since `2a43cc4`; the owner decision on A0-4 (`reports/director/2026-11-25-owner-answer-keeprisk-a0-alarm.md`); the
parts of `run.py` that hash, call the loader and record the start; the parts of `lab/runner/keeprisk.py`,
`lab/validation/montecarlo.py`, `lab/runner/reference.py` (`Costs`) and `lab/runner/portfolio.py` (`_simulate`) needed
to state the pinned algorithms. The auditor did not open any hold-mix-cap result file or the "Hold this mix" section of
`docs/app/features.md`.

**What the auditor ran:** scratch scripts in the session scratchpad (`krs/audit/`, not kept): `d1.py` (labels, Holm,
E1, D1, D2), `boot.py` and `robust.py` (the resampling), `rule.py`, `binance.py`, `k2x.py` (the rule, its copies and
the yardsticks rebuilt on the real train bars), `tables.py`, `tables2.py`, `cards.py` (RESULTS.md's numbers). None of
them imports `lab/runner/keeprisk.py` or `research/keep-risk-steady/run.py`. The only `lab/` code used is
`lab.data.panel.load_panel(..., last_close=2023-01-01 00:00 UTC)` to read the train bars. No bar after 2023-01-01
00:00 UTC was read, and nothing was written outside the scratchpad except this file.

## Verdicts

| | Verdict |
|---|---|
| **Run 0's validity** | **PASS.** Clean tree and the three tiers on the run's commit, the pinned hashes, the counts, no bar past the train window, 0 failed runs. D1, D2, every label, Holm, E1 and four cells' RISK-X statistics recompute exactly from the run's tables with independent code. Independent rebuilds of the rule, its copies, N and X from the bars match the engine to 5.6e-16 a day. |
| **The decision** | **Confirmed: NO DEFAULT, label MISSING (boom: without the best 2).** Every setting fails D1's rule 2 first at (30%, 50% BTC). The Binance, 2x-cost and without-the-best-year checks give NO DEFAULT. Without the two best years only windows 12 and 48 remain, so that check is MISSING. |
| **RESULTS.md's accuracy** | **Numbers: PASS.** Every number checked (the full 32-row table, all 16 recomputed columns; the per-setting, by-year, label-count and description tables; the plain-words ranges; 4 cards in full) matches the record. **Wording: FAIL as written, PASS once R1 and R2 below are made.** Two plain-words sentences overstate: one states as a finding the reading that A0-4 and amendment M3 say is unreliable in exactly that direction, and one headlines a weak timing result without its caveat. |

## 1. Run validity

| Check | Evidence | Result |
|---|---|---|
| Commit and tree | `start.json`: commit `2a43cc49…`, `dirty: false`, no changes listed. RUNLOG start line (20:03:17 UTC) holds the same commit, the config hash, `data: real` and `dirty: false`. | PASS |
| The three tiers on `2a43cc4` | `krs/tiers4/meta.txt`: commit `2a43cc4`, 0 dirty files before and after. Full tier: 2750 passed in 3151 s, TOTAL 8233 statements and 2436 branches at 100%, `fail_under` reached. Deep profile: 2732 passed in 852 s. Ruff: all checks passed. Dashboard: 86 passed. The tiers finished at 20:02 and the run started at 20:03. The earlier tiers on `8f87bd8` (`krs/tiers3`) passed everything except ruff (exit 1, 5 errors), as RESULTS.md's deviations say. Since `2a43cc4` only study records changed (PLAN.md's looks row, README, RESULTS, RUNLOG, decision.json, runs.csv, spans.csv): no `lab/`, test or config file. | PASS |
| Config hash | `de32565d…` recomputed from `start.json`'s file hashes and `run.py`'s pinned values: equal. All 26 hashed files at `2a43cc4` have the recorded SHA-256. Today only PLAN.md differs, by the post-run looks row (section 18). | PASS |
| Snapshot and data pins | Snapshot `1746a21b75683e76`; bars hash `08f5ca2c…`; Kraken panel `355aabe2…`, 2190 rows, 2017-01-02 .. 2023-01-01, 2018-01-13 missing; Binance `2c1a4257…`, 1963 rows from 2017-08-18. All equal PLAN.md section 3. | PASS |
| Limits and costs as read | Steady min_cash 0.20, max_coin 0.60, budget 0.35, risk-levels SHA `d3f58253…` (as section 14). 1x 5,000 USD: pool 5 bps, aggregator 0, slippage 10/15/30 bps at 100/1,000/10,000 USD, gas 0.10 USD. 2x doubles every item. | PASS |
| Stop rules 8 and 9 (prior amendments) | The A1 and A0 items are recorded. The A0 item reports `alarm: fired` and names `owner decision: reports/director/2026-11-25-owner-answer-keeprisk-a0-alarm.md`. That file exists, was committed in `8f87bd8` (17:26 UTC, before the run commit and before any bar was read), and answers alarm A0-4. It is not one of the decisions that answer no alarm (#78). | PASS |
| Projection | 24.7 CPU-minutes at the start, under 240. A0 re-time 248 at 100 panels, under M2's 600 (A0 was not rerun). | PASS |
| Counts | `summary.json` 117,760 expected and got, 478 blocks logged, `failed_runs: 0`, `failures.parquet` empty. By family: Kraken 1x 6,272 window + 16,640 span runs; Binance 5,248 + 14,528; Kraken 2x 6,272 + 16,640; L7 6,272 + 16,704; L28 6,272 + 16,512; 500 USD 6,272 + 128. Each equals section 7's formula (copies 258, 225, 259, 256). Every run's status is `ok`. | PASS |
| Consistency stops | Steps check: 1,536 groups, 0 pairs whose orders differ. Sigma recheck: 0 near-integer cases on any source, f or look-back. Copy 0, the yardsticks, the windows and the accounting checks are stops, and the run completed. | PASS |
| No bar after 2023-01-01 00:00 UTC | `runs.parquet`: the latest `last_close` of all 117,760 runs is 2023-01-01 00:00 UTC, and the earliest `first_close` is 2017-01-02. Both panels end at 2023-01-01. The `series.parquet` full-span series hold 2190 (Kraken) and 1963 (Binance) rows, exactly the train panels, and the auditor's own load of the panels gives the same rows. | PASS |
| Committed record against the run folder | `decision.json` is byte-identical (SHA `3636031d…`). `spans.csv` equals `spans.parquet` to 5e-7 (rounding) with identical labels. `runs.csv` holds 36,608 rows, one per window run, with no Sharpe column (section 15). | PASS |

## 2. D1 and D2, recomputed independently (Kraken 1x headline)

`d1.py` recomputes each label from `spans.parquet`'s V and p-values with section 9.4's order. Holm uses the four
settings per (pool, mix), with p_(j) < 0.05 / (5 − j) strict. E1 comes from the copies' V_u in `runs.parquet`, with u =
53..310 and ties against the rule. D1 uses the window rows of `runs.parquet`.

- **Labels:** 0 mismatches over all 13 labelled (family, rowset) sets × 32 cells (416 labels). Holm: 0 mismatches.
  E1 rank p: 0 mismatches, each pool with its pinned copy count (Kraken 258, Binance 225, starting at u = 53). Kraken
  1x: 31 NO NOTICEABLE DIFFERENCE and 1 CAN'T TELL (w 8%, 60%, 75%). The smallest p_calm in the pool is 0.149, so
  RISK-X passes Holm at no cell, and no cell can be CALMER or SMALLER, BUT BELOW NOTICE.
- **D1 per setting:**

| w | Rule 1 (2 × calmer ≥ 49) | Rule 2 (CALMER or CAN'T TELL) | Rule 3 (median c_X ≤ 2.0) | First failure |
|---|---|---|---|---|
| 8% | holds at 8/8 (31-46 calmer) | holds at 1/8 (60%, 75%) | fails at 8/8 | rule 2 at (30%, 50%) |
| 10% | holds at 8/8 (31-48) | holds at 0/8 | holds at 8/8 | rule 2 at (30%, 50%) |
| 12% | holds at 8/8 (36-47) | holds at 0/8 | fails at 5/8 | rule 2 at (30%, 50%) |
| 15% | fails at (60%, 75%): 22 of 49 | holds at 0/8 | fails at 2/8 | rule 2 at (30%, 50%) |

  No setting is usable, so the result is **NO DEFAULT**. Every per-mix number in `decision.json`'s D1 for Kraken 1x,
  Binance 1x and Kraken 2x (calmer windows, median c_X to 1e-12, label, the three rule outcomes, the first failure)
  equals the recompute: 0 mismatches.
- **D2:** the boom years ranked on `start.json`'s Kraken yearly returns are 2017 (+1,304%) and then 2020 (+304%).
  Windows overlapping no removed bar-year, counted by the auditor from the calendar: without 2017, k = 12..48 (37);
  without 2017 and 2020, k = 12 and 48 (2). The recomputed checks:
  - Binance (41 windows): NO DEFAULT.
  - 2x costs: NO DEFAULT.
  - Without the best 1 (37 windows, rowset labels): NO DEFAULT.
  - Without the best 2 (2 windows, fewer than 12): MISSING.

  So the robustness label is **MISSING (boom: without the best 2)**, with MISSING placed before ROBUST in D2's
  order. This equals `decision.json`.

## 3. The full-span statistics, recomputed

`boot.py` reads each cell's full-span rule and X daily returns (rows 1..2189) from `series.parquet`. It computes DD,
V, V*, the 90% interval, p_calm, p_rough, p_eq (ln 0.9), g and the cost p with its own code, under two resamplers:
(a) the pinned construction, written from section 9.2 and `stationary_bootstrap_indices`' documented algorithm
(`default_rng(0)`, mean block 60, 10,000 resamples, one index set); (b) an independent resampler (sequential
geometric blocks, another seed).

| Cell (Kraken 1x) | Run 0 | (a) pinned construction | (b) independent resampler |
|---|---|---|---|
| w 10%, 30%, 50% BTC | V −0.028823 [−0.0842, 0.0294]; p_calm 0.2102, p_rough 0.7899, p_eq 0.0102; cost p 0.3954; NO NOTICEABLE DIFFERENCE | identical (every value to 1e-12) | V the same; [−0.0831, 0.0294]; 0.2112, 0.7889, 0.0105; 0.3808 |
| w 8%, 60%, 75% BTC (the CAN'T TELL cell) | V −0.031792 [−0.1138, 0.0497]; 0.2682, 0.7319, p_eq 0.0692; 0.1239 | identical | [−0.1125, 0.0499]; 0.2760, 0.7241, 0.0662; 0.1206 |
| w 15%, 60%, 50% BTC | V +0.006555 [−0.0169, 0.0277]; 0.6969, 0.3032, 0.0001; 0.5699 | identical | [−0.0167, 0.0278]; 0.7044, 0.2957, 0.0001; 0.5676 |
| w 10%, 50%, 75% BTC | V −0.032073 [−0.0956, 0.0271]; 0.1990, 0.8011, 0.0282; 0.3729 | identical | [−0.0933, 0.0261]; 0.1971, 0.8030, 0.0260; 0.3560 |

- Under resampler (b) (seed 777), none of the 32 Kraken 1x labels changes. At w 10% the largest p_eq is 0.0282
  pinned and 0.0261 independent, far from 0.05. So the NO DEFAULT does not depend on the pinned seed. It does depend
  on the paired resampling's design, which A0-4 found too narrow on clustered markets (section 5 below).
- **E1:** each cell's rank p recomputes exactly from the copies' V_u in `runs.parquet`. The auditor also rebuilt
  four copies of w 10%, 30%, 50% BTC from the bars (u = 53, 120, 200 and 310: q rotated over the W = 311 Monday
  checks, 2017-01-16 .. 2022-12-26, each copy against its own X(u)). V_u and x_u equal the run's to 12 decimals.
- **X_eq:** at every Kraken 1x full span, X_eq's share is x × exp(V) exactly, and no cell was clipped.

## 4. RESULTS.md against the record

**Checked and right:**
- **The full table** (32 rows): the label, V and its interval, p_calm, p_rough, p_eq, E1 rank p, calmer windows, the
  median cuts against X and N, c_N, c_X, x, F of the rule, N and X (median and 90th percentile), orders and fees.
  Recomputed from `runs.parquet` and `spans.parquet`: 0 mismatches. The D1 rule marks equal the recompute.
- **The per-setting table:** E1 at 8, 8, 1 and 0 of 8 mixes; calmer windows; cut and c_X ranges; F rule − F X as
  the difference of medians; X_eq − rule. All equal.
- **The label-count table:** all 14 rows equal, including the one ROUGHER (without 2021, at w 15%, 60%, 50%,
  p_rough 0.038).
- **The by-year table:** all 60 numbers equal, and so is its prose (4-6% in windows starting 2019 and 2020, 0-2%
  otherwise).
- **The descriptions table:** all 24 rows equal. The cost flag fired at no cell of any family.
- **In plain words**, each range against the record:
  - cut against the full mix 3.2-33.5%;
  - c_N 0.42-29.1;
  - cut against X −0.1 to 3.9% ("0-4%");
  - F rule − F X up to +5.3;
  - c_X −1.21 to +6.32, positive at 28 of 32 cells;
  - E1 rank p 0.0039-0.0347 at w 8% and 10%;
  - X_eq − rule +1.07 to +8.67 points, positive at all 32 cells.

  The header's run facts are also right: 501 s, the 24.7 CPU-minute projection, the 1,536 step groups and no
  near-integer case.
- **The cards** (four checked in full: 8%/30/50, 10%/50/75, 12%/60/50, 15%/60/75): x, the share stepped back, the
  cut against N, F against F_N (median and worst), the c_N median and its 10th-90th, calmer windows and the median
  cut against X, trades a month, the busiest 30 days, fees, the missed rebound and the same-calm return. All equal.
  The plan's "stepped back in {k}% of weeks" became "of the time" (the share of rows with q < 1), and RESULTS.md
  discloses this in its notes.
- **M3 in the cards:** every card names its computed label, shows the CAN'T TELL sentence and carries A0's power
  line (10 of 100 PG, 21 of 100 PR), as M3 item 2 and D3 ask. The NO DEFAULT sentence ("no setting rode clearly
  calmer than simply holding less crypto") does not claim "no difference", which is consistent with M3.

**The lead's post-hoc reading about w = 10%.** It is accurate:
- rules 1 and 3 hold at all 8 mixes, and only rule 2 fails;
- read as CAN'T TELL, w = 10% would be the only usable setting, because 8% and 12% fail rule 3 and 15% fails rules 1
  and 3;
- its cut against X is 2.2-3.7%;
- F rule − F X is +0.0 to +3.0;
- X_eq − rule is +1.1 to +7.6.

It is labelled as deciding nothing, it states that M3 keeps the rules, and it puts the counter-evidence next to the
counterfactual. It is a fair disclosure. The auditor adds two points, the second as recommended text (C4):
- The counterfactual is not fragile: under the same reading, Binance, 2x costs and without-the-best-year also give
  w = 10% only, because the other settings fail rule 3 (or rule 1) there too.
- It must not become the reason for an amendment run or a D1 change, because any such change would now be chosen by
  this result.

**Wording that overstates (required, R1 and R2) or understates (recommended, C1-C3).** See the corrections below.

## 5. Look-ahead, yardsticks, costs, and what else could make the result wrong

- **No look-ahead.** `rule.py` rebuilds the rule from the raw train bars with its own code. The signal at close c
  uses the 14 log returns through c (numpy `std`, ddof 1, × √365). The quarter floor uses its 1e-9 tolerance. Checks
  are made at Monday 00:00 UTC closes c ≥ 14, with the switch-on decision at the run's first close. Orders fill at
  the next open, through a coin-unit book with its own cost code from `config/costs.yaml`. On the full span it
  reproduces the engine's daily returns to 5.6e-16 (Kraken 1x at 10%/30/50, 8%/60/75 and 15%/60/50; Binance 1x at
  10%/50/75 and 8%/30/50; Kraken 2x at 10%/50/75). The order counts by reason match exactly (for example 1 first,
  127 step, 21 drift and 0 limit at 10%/30/50). Ten window runs match DD, V_X, x and the order count to 10
  decimals: windows 0, 7, 24, 30 and 48 at two cells. These include a non-Monday switch-on with σ at that close
  (window 7, which also spans the missing 2018-01-13) and window 0's q_on = 1. A causal reimplementation agreeing to
  rounding is strong evidence that the engine reads nothing past close t and fills no earlier than t + 1. A tamper
  check on the auditor's own q path also passes: prices changed from row 1000 on leave every q before row 1000
  unchanged.
- **Yardsticks.**
  - X's target is the exact mean of the rule's in-force share over rows 0 .. n−2 (amendment M1), equal to the run's
    x to 12 decimals.
  - X trades only `first` and `drift` (for example 1 and 60), and N likewise.
  - X_eq = x × exp(V), with no clip needed.
  - The realised crypto weight gap (rule − X) is small: −0.21 points in the median window (10th-90th: −1.09 to
    +0.52) and −0.05 points on the full spans. It leans slightly in the tool's favour, so it cannot explain the
    tool's failure to beat X.
- **Costs are on.** 1x uses the placeholders and 2x doubles every item. Example drag: 0.57 points a year of CAGR at
  10%/30/50 on the full span, against zero cost. The placeholder costs and the scouting engine still apply (hard rule
  3): no number may reach users before a NautilusTrader rerun.
- **The structural caveat the owner should weigh.** The NO DEFAULT at w = 10% rests on D1's rule 2 alone. That rule
  is fed by p_eq < 0.05 (NO NOTICEABLE DIFFERENCE). A0-4 found the paired resampling too narrow in exactly that
  direction on clustered markets: on PG, 96 of 400 boundary tests failed against a limit of 30. M3 kept the rule,
  knowing it errs toward NO DEFAULT. The descriptions point the same way as the label:
  - the median cut against X is under 4% at every cell;
  - the tool's worst fall was deeper than X's in 28-49 of the 49 windows at every cell (median 44);
  - holding the same-calm share steadily returned 1-9 points a year more.

  So the advice "lower your crypto share" is supported beyond the one statistic.
- **Prior looks and snooping.** No validate look was taken (0 used), and the test window was never read. P8 (the
  volatility persistence of these bars) is disclosed as a prior look, and it is why E1's pass at w 8-10% is weak new
  evidence (PLAN.md section 16). Seven studies have looked at Steady claims on these rows, as RESULTS.md says.

## Required corrections

**R1. RESULTS.md, "In plain words", third bullet (lines 31-33).** The sentence states the computed NO NOTICEABLE
DIFFERENCE reading as a finding ("rules out"). That reading is the one A0-4 found overconfident in this direction, and
amendment M3 keeps it from users. Replace

> The down days
>   were a median 0-4% smaller, and the full-span reading rules out a cut as large as 10% at 31 of the 32 cells
>   (NO NOTICEABLE DIFFERENCE).

with

> The down days
>   were a median 0-4% smaller. The full-span test labels 31 of the 32 cells NO NOTICEABLE DIFFERENCE (a cut of 10%
>   or more rejected at the 5% level), but A0 found that this reading can be overconfident in exactly this direction
>   (the caveat below), so it is a computed label, not a finding shown to users.

**R2. RESULTS.md, "In plain words", fourth bullet (lines 35-37).** "Its timing is not random" generalises from 2 of
the 4 settings, and it presents as new evidence what P8 had already shown on these bars (PLAN.md section 16: "E1
mostly re-confirms a known fact"). Replace the whole bullet

> - **Its timing is not random.** At w = 8% and 10% the tool ranked in the top 4% of the guarded time-shifted copies of
>   its own stepping back (E1 at all 8 mixes; rank p 0.004-0.035): it does step back at better moments than chance. The gain is just too
>   small to beat a plain lower crypto share.

with

> - **At w = 8% and 10% its steps were better timed than chance.** The tool ranked in the top 4% of the guarded
>   time-shifted copies of its own stepping back (E1 at all 8 mixes; rank p 0.004-0.035); at 12% and 15% E1 held at
>   1 and 0 of 8 mixes. This mostly re-confirms what P8 had already shown on these bars (volatility clusters), so it
>   is weak new evidence (PLAN.md section 16). The gain is too small to beat a plain lower crypto share.

## Recommended corrections (accuracy of emphasis; not required)

- **C1. RESULTS.md line 177** ("and some return given up"). At Binance w 10% the tool earned a median 1.53 points a
  year more than X. Replace "and some return given up." with "and some return given up at 23 of the 24 rows (at
  Binance w 10% the tool earned a median 1.5 points a year more than X)."
- **C2. RESULTS.md lines 33-34** (the falls understate a negative finding). After "(up to 5 points at w = 8%)." add:
  "In the typical window the tool fell further than X at every cell: in 28-49 of the 49 windows (median 44)."
- **C3. The card at w 15%, 60%, 75% BTC (line 569).** The template gives "smaller ... (a median -0.1%)". Replace "(a
  median -0.1%)" with "(in the median period they were 0.1% larger)".
- **C4. The post-hoc paragraph (line 184).** After "and M3 keeps them unchanged." add: "It cannot be the reason for
  an amendment run or a change to D1: a rule changed after seeing this result would be chosen by the result."
- **C5. README.md line 27** repeats R1's claim ("a 10% cut ruled out at 31 of 32 cells (NO NOTICEABLE
  DIFFERENCE)"). Replace it with "31 of 32 cells labelled NO NOTICEABLE DIFFERENCE, a reading A0 found
  overconfident in that direction (M3)", to match R1.

**Validate-window looks used for keep-risk-steady: 0.** The test window was not read.

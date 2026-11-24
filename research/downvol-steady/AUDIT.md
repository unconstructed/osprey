# downvol-steady: audit of run 0 (SCOUTING)

`backtest-auditor`, 2026-11-24. This is the study's one audit (PLAN.md section 14, order of work step 7). It checks
run 0 (the train window only) and the lead's draft RESULTS.md against the plan as amended (M1, M2, M3, A1, A0) and
against the outputs. I changed no code, no test, no PLAN.md, nothing in `config/` and no run output. My scratch scripts
are in the session scratchpad under `dvaudit/aud/`.

> Every number here is SCOUTING. It comes from the lab's reference portfolio engine, uses the placeholder costs in
> `config/costs.yaml`, and treats exchange candles as stand-ins for Base prices. Nothing here is a NautilusTrader
> result, and nothing here makes anything ready for paper.

## Result

**PASS for the run and its verdict.** Run 0 followed the protocol. I rebuilt every decisive number with my own code,
and each one matches `summary.json` to round-off. The verdict follows mechanically from the plan's rules: **NO EDGE**,
because E1 and E2 both fail, and both fail by a wide margin. **Nothing I found can flip it.** There was no validate
look, and the test window was never read.

**As the owner asked, this NO EDGE means "the test could not tell".** A0, the pre-check on made-up markets, confirmed
an edge on only 1 of 20 markets built to have one, with 0 false alarms in 20 markets without one.

**The write-up is close, but not final.** RESULTS.md's tables are right cell for cell. Six of its claims need fixing
(findings 1-6; finding 6 was raised from a note by the corrections after the final check, at the end of the
Findings). The most important is finding 1: the 2020 shortfall comes mostly from the settings the search picked
for 2020, not from counting only the falling days. None of the six changes the verdict, a gate or a criterion. The
same corrections fix this audit's own text in four points; none of them changes the verdict either.

**The strategy: RETURN TO RESEARCHER (not ready for risk review).** It is NO EDGE, and it fails every gate except R1
(trade frequency). No fix to this run can change that; the plan stops here. The final test window (G9) was not run,
so it is still unused for downvol-steady.

## What I checked

### 1. Protocol

| Check | Finding | Evidence |
|---|---|---|
| One run 0 only | PASS | `RUNLOG.jsonl` has one line: run 0, `run_train.py`, real data, commit `e62233e`, `dirty: false`, 18:08:56 UTC. `results/downvol-steady/train/` holds `run0/` and the 12 study folders `downvol-steady-s{0,1}_{wf00..wf04,final}`, with no `_a<k>` study. `trials.parquet` has 2,400 rows: 12 studies × 200 trials, all COMPLETE. Every trial records commit `e62233e`, config hash `04d418e9…`, snapshot `1746a21b75683e76`, bars hash `08f5ca2c…`, and the pinned seeds (fold seed + 1000 i; final + 5000). `evaluations.parquet` has 2,031 rows, 48 counted, so the strict count is 2,400 + 49 + 2,400 = 4,849, as recorded. The tracked `trials.csv` and `evaluations.csv` equal the parquet files |
| Clean tree, right commit, code unchanged since | PASS | The start record has `git.dirty: false`, `changes: []`, commit `e62233e`. I recomputed all 41 file hashes in the start record against today's tree: every one matches, PLAN.md included (M3 keeps it byte-identical). The only commits since `e62233e` are `8a2876c` (both runs' RUNLOGs and CSVs) and `7257575` (TESTING.md). Today's tree also holds untracked draft RESULTS.md files for this study and for buy-the-dip; no hashed file is among them |
| A1, A0, the owner's decision and the follow-up note before run 0 | PASS | A1 (N = 200) and A0 (power 1 of 20, 0 false positives) are in PLAN.md section 15, committed in `8ab8dad` (13:58 UTC) with the owner's decision record. The follow-up's design note is in `e62233e` (16:51 UTC). Run 0 started at 18:08:56. The start record's `prior_amendments` holds both lines and the decision's path |
| Started together with buy-the-dip run 0 | PASS, with a note (finding 8) | Both recorded a clean tree at `e62233e`. buy-the-dip's RUNLOG file did not exist at `e62233e` and was created at 18:08:49. This run's tree check came about 7 seconds before its start record (18:08:56), so just before that file appeared. It recorded no change, and all 41 hashed files are unchanged |
| No bar after 2023-01-01 00:00 UTC | PASS | The code path is `load_study_panel(TRAIN_LAST_CLOSE)` → `load_panel(last_close = 2023-01-01)` → the catalog query with `end = last_close`, then a re-check of the last close. The recorded panels end at 2023-01-01. My own load went through a loader that refuses any request, or any returned bar, past the cut. All four requests (BTC and ETH, Kraken and Binance) ended at 2023-01-01 |
| Snapshot and panel pins | PASS | Snapshot `1746a21b75683e76` and bars hash `08f5ca2c…` are in the start record. My own load reproduces both panel hashes (`355aabe2…` Kraken, 2,190 rows from 2017-01-02; `2c1a4257…` Binance, 1,963 rows from 2017-08-18). Kraken lacks only 2018-01-13, as pinned |
| Tiers on the run's commit | PASS (on the record) | TESTING.md section 3 (commit `7257575`) and RESULTS.md record, on `e62233e`: the full tier 2,646 passed with 100% branch coverage of `lab/` (7,665 statements, 2,288 branches) in 3,488 s; the deep profile 2,628 passed in 1,095 s. I did not rerun the full tier. I reran `tests/test_downvol.py` and `tests/test_downvol_scripts.py` (`-m "not slow"`, `-n 3`) on today's tree, with the real run 0 RUNLOG line in place: **140 passed in 202 s**, exit 0 |
| The searches reproduce | PASS | I reran two logged studies in a scratch folder (seed A fold 0, seed B fold 2: 200 trials each, `n_workers` 1). Every trial's parameters and score equal `trials.parquet`'s exactly. So the parallel run did not disturb the search |
| No validate look | PASS | There is no FROZEN.json and no `validate/` folder, and `look_earned` is false. NO EDGE earns no look (TP 13) |

### 2. The decisive numbers, recomputed

**The tests, in one line each:**
- **E1 (timing):** does the rule's real step pattern beat the same steps moved to other weeks? It needs at most 9 of
  207 moved copies at or above it. Under M1, each year keeps its own share s and only the steps move.
- **E2 (beats holding):** is the rule's risk-adjusted return (Sharpe) above N0's, by more than chance? N0 is "buy
  or keep, then hold": it starts from the rule's own wallet at each year's start, buys the year's share only if the
  rule was then stepped back, and after that trades only to fix the limits (finding 6). A resampling test must give
  p < 0.05.
- **E3 (smaller falls):** are the rule's worst fall and its Monte Carlo worst fall both shallower than X's? X moves the
  rule's wallet to the rule's average crypto of the year at the year's start (buying or selling), then holds it,
  trading only to fix the limits.
- **E4:** does E2's lead survive doubled costs?
- **E6 (not one year):** does the lead over N0 survive dropping any one year?
- **P (enough information):** at least 20 share changes, spread over at least 4 years.
- **G6 (drawdown budget):** is the 95th-percentile worst fall, from 1,000 resampled histories, within the owner's 35%?

**How I rebuilt them.** I wrote the rule from PLAN.md sections 3-4 myself:
- the 50/50 basket's log return;
- the downside measure, √365 × √(2 × Σ min(x, 0)² / L), with numpy, not the module's `math.fsum`;
- the quarter step and the Monday checks.

I also wrote my own book, in coin units and USDC cash. Fills are at the next open. Leg costs come from
`config/costs.yaml`'s numbers in my own slippage function. Limit fixes are at 0.20 / 0.60 + 1e-9.

From the lab I used only:
- `load_panel`, behind my guarded loader;
- `montecarlo.stationary_bootstrap_indices` and `block_bootstrap_drawdowns`, to replicate E2's and G6's random draws.

I also ran E2 with my own stationary bootstrap at other seeds.

| Number | Mine | `summary.json` | Match |
|---|---|---|---|
| S, both seeds, every fold, 1x and 2x | Equal to `oos.parquet`'s S_A, S2_A, S_B and S2_B to 6.7e-16 per row. Sharpe 0.307721 (A), 0.370525 (B); at 2x 0.2817 and 0.3470 | the same | yes |
| The downside measure and q | Relative difference ≤ 2.9e-14 from `downvol.downvol_path`; 0 q mismatches over all 10 fold runs | | yes |
| R_0 (one book, the share path stitched by fold, fold 0's per-row head) | Equal to `oos.parquet` to 6.7e-16. Sharpe 0.2015 (A), 0.2978 (B). R_0 equals S bit for bit on fold 0's kept rows | the same | yes |
| E1 (q-only shifts, M1) | A: W = 260; 171 of the 207 guarded shifts at or above; rank p 172 / 208 = **0.827**. B: 149, **0.721**. Each shift's Sharpe matches its `evaluations.parquet` row to 5.7e-15 | 0.827 (171); 0.721 (149) | yes |
| E1-whole (VP's shifts, a description) | A: 172, 0.832. B: 145, 0.702. Matches to 6.3e-15 | the same | yes |
| E2 | A: D = **−0.460**, p **0.9938** (seed 0, 10,000 resamples, mean block 60). B: D = −0.394, p 0.9836. Other draws, 10,000 resamples each: `steady.paired_bootstrap` at seeds 1, 2 and 3 gives A 0.9950, 0.9954 and 0.9956, B 0.9836, 0.9846 and 0.9849; my own sampler at seeds 11, 12 and 13 gives A 0.9932, 0.9943 and 0.9936, B 0.9821, 0.9807 and 0.9821. Seed A's rule is ahead in 62, 50, 46 and 44 of the 10,000 resamples at seeds 0-3 (0.44-0.62%) | 0.9938; 0.9836 | yes, and robust to the draw |
| E3 | A: S −60.6% / MC p5 −79.6% against X −47.5% / −71.0%: both deeper, so it fails. B: S −60.3% / −78.1% against X −47.7% / −66.5%: fails | the same | yes |
| E4 | A: S at 2x 0.282 < N0 at 2x 0.765. B: 0.347 < 0.761 | the same | yes |
| E6 (Δ_y = Σ ln(1+S) − ln(1+N0) by bar-year) | A: 2018 −0.056, 2019 −0.021, 2020 **−0.694**, 2021 −0.161, 2022 −0.002; Δ = **−0.933 < 0**, so it fails. B: Δ = −0.849, positive only in 2022 (+0.037) | the same | yes |
| P | A: per fold 37, 2, 4, 6, 31 = **80** in 5 folds. B: 37, 2, 6, 4, 28 = 77. Each fold's first buy is not counted. Holds | the same | yes |
| G6 (p5 of 1,000 block-bootstrap worst falls, block 20, seed 0) | A: **−79.6%** against a −35% budget. Seeds 1-3 give −81.2%, −78.4% and −80.5%; block 60 gives −82.1%. The actual worst fall alone (−60.6%) breaks the budget | −79.6% | yes |
| N0, N0 at 2x and X | Each equals `oos.parquet` to ≤ 4.4e-16, both seeds | | yes |
| Bear years removed (2018 and 2022) | E1 rank p **0.841** (174 at or above) | 0.841 | yes |
| Leave one year out, E1 | 0.779, 0.928, 0.365, 0.928, 0.837 without 2018 .. 2022 | the same | yes |
| Binance (folds 1-4) | S equals `oos.parquet`'s S_binance_A to 3.3e-16. S: Sharpe 0.866, +146%, worst fall −36.4%. N0: Sharpe 1.288, +499%, −37.0% | 0.866; 1.288 | yes |

**Nothing can flip the verdict.** NO EDGE needs only E1 or E2 to fail (TP 12), and both fail by far:
- **E1** needs at most 9 of 207 shifts at or above the rule. It has 171 (seed A) and 149 (seed B).
- **E2** needs the rule to be ahead (D > 0). It is behind in both seeds (D −0.46 and −0.39), with p between 0.980
  and 0.996 under every draw I tried.
- **No reading comes close.** The closest is E1 and E2 without 2020: rank p 0.365, D −0.17, p 0.88. E1-whole and
  E1 without the bear years fail too.

Every gate except R1 fails, each by a wide margin:
- **G1:** Sharpe 0.31 against 1.0.
- **G2:** 0.28 at 2x against 0.5. This one passed for vol-steady.
- **G3:** the deflated Sharpe is 3e-5. It cannot pass at any trial count. Even with no deflation, the chance that
  the true Sharpe is above zero (PSR at 0) is only 0.75 for seed A and 0.80 for seed B, under the 0.95 needed.
- **G4:** PBO 0.78, against at most 0.25 (read from the record, not recomputed).
- **G6:** −79.6% against the 35% budget.

### 3. S rerun from scratch, look-ahead

- **The rerun.** I reran S for all five folds, both seeds, on the real panels from `load_panel(..., last_close =
  2023-01-01 00:00 UTC)`. It equals `oos.parquet` (table above). Seed A's kept fills are 37, 3, 4, 7 and 31 (82 in
  all). Two of them are limit fixes (2019-06-26 and 2021-01-04, when drift took crypto just past 80%).
- **No look-ahead.** My implementation decides at close c from closes up to c, and fills at c + 1. The engine's returns
  equal mine to 6.7e-16, so the engine does the same.
- **Tamper check.** I also tampered with the lab's own adapter (`downvol.downvol_backtest`) on real train bars. For
  each of the 10 fold parameter sets, I scaled every price of both coins by random factors from a cut on, at 8 cuts:
  five random, one Monday check close, the close after it, and a second Monday. In all 80 cases the returns,
  positions, turnover, the measure, q, the share, the targets and the orders before the cut were unchanged, and later
  rows did move.

## Findings

Severity: **blocking** (the run or its verdict cannot stand), **should fix** (the write-up says something the outputs
do not support, or leaves a wrong impression), **note** (worth knowing; no change required).

No finding is blocking.

**1. Should fix: the 2020 shortfall is mostly the search's 2020 settings, not the downside measure.** RESULTS.md says
"the plain rule forgot the crash in three weeks, this one in twelve", and "This run cannot tell whether the downside
measure or that choice is to blame". The audit can tell, at least for 2020. I reran 2020 (fold 2, s = 0.414) with the
two measures and the two searches' 2020 settings, all at this run's 2020 share (s = 0.414). Each run starts from the
panel's first row with the same 10,000 USD, as the fold runs do, so each enters 2020 with its own wallet. These are
descriptions; they decide nothing:

| 2020 (fold 2) | Steps | 2020 return | Against its own N0 (log) |
|---|---|---|---|
| Downside measure, this run's 2020 settings (85 days, τ 0.35), the run itself | 0 from 16 March to 8 June; never the full share | +32% | −0.69 |
| **Plain** volatility, the same 85 days and τ 0.35 | 0 from 23 March to 8 June; never the full share | +48% | −0.58 |
| Downside measure, vol-steady's 2020 window and target (15 days, τ 1.03) | a quarter for two weeks, back to full on 30 March | +141% | +0.01 |
| Plain volatility, the same 15 days and τ 1.03 (vol-steady's 2020 rule, at this run's s) | a quarter, back to full on 6 April | +156% | +0.16 |

The last column compares each run with its own N0, as the plan defines it (finding 6). In the two 85-day runs the
rule was at half its share when 2020 began, so N0 bought the year's share, 41%, and made +165% in 2020. In the two
15-day runs the rule already held its full share, so N0 kept that run's wallet as it was, 35% crypto (downside) and
30% (plain) at the 3 January close, when N0 decided, and made +138% and +118%. So compare the returns first.

- **At the same settings, the two measures behave almost alike.** With an 85-day window and a 0.35 target, plain
  volatility would also have sat out about 11 weeks and never held the full share in 2020.
- **With a 15-day window, the downside rule would have forgotten the crash faster than vol-steady did:** two weeks,
  not three.
- **So "three weeks against twelve" is the window** (15 days against 85), not the measure.
- **The measure did cost something at fixed settings.** On the 2020 returns, the downside rule made 0.11 log less
  than plain volatility at the 85-day pair and 0.06 less at the 15-day pair (0.11 and 0.15 against each run's own
  N0; the 15-day pair's two N0s differ, as said under the table). Over all five years at this run's own settings,
  plain volatility gives Sharpe 0.41 against 0.31. The steps differ at 61 of the 260 checks, mostly in the 10-day
  windows of 2018 and 2022.

**Fix:** replace the two sentences with these numbers, labelled as audit descriptions. Whether the downside measure
made the search more likely to choose (85 days, 0.35) for 2020 cannot be told from one run. The walk-forward's picks
are noisy (PBO 0.78).

**2. Should fix: say what "clearly worse than holding" is made of, and keep the owner's framing first.** The owner's
record says a NO EDGE is reported as "the test could not tell". The draft does say so. But its first bullets lead with
"It did clearly worse than holding, not just 'no better'", and it calls the backward reading of E2 "a stronger
statement than 'can't tell'". The numbers are right (the rule was ahead in about 0.6% of resampled histories). But a
reader can take this as evidence that downside timing harms, which the run does not show:
- **The timing itself was ordinary.** E1's rank p is 0.83, inside what chance gives about 1 time in 5 or 6.
- **The shortfall is one year.** Without 2020, D is −0.17, and the rule is ahead in about 12% of the resamples.
- **And that year is one settings pick** (finding 1). At vol-steady's 2020 settings, the same downside rule ends
  2020 level with its own N0 (+0.01 log). That N0 kept the rule's wallet (35% crypto at the 3 January close) instead of buying 41%. Against
  this run's N0, which did buy 41%, it trails by 0.09 log, where the run itself trails by 0.69.

**Fix:**
- Put the power caveat ("the test could not tell") before the shortfall bullets.
- Describe the shortfall as "the walk-forward's 2020 pick (an 85-day window and a 0.35 target) kept the rule out of
  the 2020 rally", with finding 1's numbers.
- Keep the line that the backward reading decides nothing.

**3. Should fix: the 2020 table's dates and one wording.**
- **The dates.** The note under "2020, step by step" says "Each stretch starts at the Monday check where the step
  changed". That is true for 16 March only. 9 June, 11 August and 8 September are the Tuesday closes after the checks
  (8 June, 10 August, 7 September), when the orders filled.
- **What the numbers are.** They are right for the dates printed. The "Basket" column is a buy-and-hold 50/50 over
  each stretch, and that should be said.
- **With the check dates as boundaries,** the log gaps are +0.03, −0.30, −0.13, +0.03 and −0.33 (sum −0.69).
- **Fix:** print the check dates, or say how each boundary is dated.
- **The wording.** "For the rest of the year it held half its share" leaves out four weeks at three quarters (10
  August to 7 September). Say "half its share, except four weeks at three quarters".

**4. Should fix: "Both rules stepped down on the same four Mondays of 2020-21" leaves out a fifth.** Seed A of this
run stepped down five times in 2020-21:
- 16 March 2020;
- **7 September 2020** (0.75 → 0.5, after stepping up on 10 August); vol-steady had no such step;
- 25 January, 24 May and 28 June 2021.

On 24 May 2021 it also stepped further than vol-steady: from 1 to 0.5, where vol-steady went to 0.75. **Fix:** say
"both stepped down on these four Mondays; this rule also stepped down on 7 September 2020".

**5. Should fix: "27 per parameter, not flagged" is wrong under the audit checklist.**
- 82 kept fills for 3 free parameters is 27 per parameter. My checklist flags anything under 30.
- `summary.json`'s flag is false only because it divides by 2 (TP's draft's two parameters; 41).
- **Fix:** "27 per parameter: under the audit's 30, flagged (summary.json divides by 2 as TP wrote it)".
- 68 of the 82 fills are in the two 10-day-window years, 2018 (37) and 2022 (31).

**6. Should fix (raised from a note on 2026-11-24): what N0 is, and "part of it is the comparator".**
- **What N0 is.** Each year N0 starts from the rule's own wallet at the year's start (the close t0). If the rule was
  then stepped back (below its full share), N0 buys the year's share, half BTC and half ETH. Otherwise it keeps the
  rule's wallet as it is, even where that wallet has drifted above or below the year's share. After that it never
  trades except to fix the limits. So N0 is "buy or keep, then hold"; it does not re-cut to the year's share every
  year, and it does not hold a constant share. This is the plan's reviewed design (TP 9; VP and this plan unchanged).
  My first version of this finding said N0 "re-cuts to each year's share at the start of the year", which was wrong.
- **Seed A, year by year.** I rebuilt N0 with `trend.always_in_n0` on the guarded train panel; it equals
  `oos.parquet`'s N0_A (and N0_B) bit for bit. The crypto shares below are of the wallet. "At the start" is the
  first kept close, the day after t0, where the year's returns begin:

| Year | Share s | Rule's step at t0 | N0 at the start | N0's average crypto | Rule's average crypto | N0's trades in the year |
|---|---|---|---|---|---|---|
| 2018 | 0.57 | a quarter | bought the share, 57%; 60% at the start | 42% | 38% | the purchase only |
| 2019 | 0.52 | full | kept the rule's wallet: 61% | 53% | 56% | a limit fix at the 26 June close |
| 2020 | 0.41 | half | bought the share, 41%; 43% at the start; 78% at the end | 57% | 20% | the purchase only |
| 2021 | 0.42 | full | kept the rule's wallet: 78% | 59% | 46% | a limit fix at the 4 January close, back to 42% |
| 2022 | 0.34 | full | kept the rule's wallet: 33% | 21% | 23% | none |

- **What this means for E2's gap.** In 2019, 2021 and 2022 N0 started from the same wallet as the rule, so the gap
  there comes from the rule's steps afterwards (in 2021 the same limit fix cut both back to 42% two days in). In the
  rising years N0's crypto drifted up well above its share: 57% on average in 2020 against a share of 41%, and 59% in
  2021 against 42%. The rule held 20% and 46%. So "holding the same share" meant holding more crypto than s in 2020 and
  2021, and part of E2's gap there is that. It is not so in 2019: N0 held less crypto than the rule on average (53%
  against 56%).
- **The rule drifts too.** Between steps it trades nothing, and it went from 21% to 39% crypto after its September
  2020 step.
- **The draft's own 2020 breakdown is about level, not drift:** 0.30 log for 12 weeks in USDC, and 0.46 for half a
  share through the rallies.
- **Even a buy-once holding beat the rule.** N0-span (bought once at the start of 2018, then limit fixes only) has
  Sharpe 0.40, against the rule's 0.31.
- **Not measured:** how much of the gap would remain against a comparator held at a constant share. That is close to
  the follow-up's question (finding 7), so I did not compute it.
- **Fix:** RESULTS.md should describe N0 as above wherever it says N0 re-cuts each year or always holds the fold's
  share, and say that in 2020 and 2021 "holding" carried more crypto on average than the rule (57% against 20%, 59%
  against 46%).

**7. Note: E3 and the follow-up.**
- **E3 failed even though it leans toward the rule.** The follow-up's design note warns that the plan's X drifts up
  in rallies, which tilts E3 in the rule's favour. E3 failed anyway (−60.6% against X's −47.5%).
- **The draft's "It did not cut falls any better than simply holding less crypto" is E3's reading:** worst fall and
  Monte Carlo fall, against that drifting X.
- **It is not the follow-up's question.** That question is the size of down days against a mix re-cut every week to
  the same crypto. Nobody has computed it.
- **I did not compute it either.** I computed no weekly re-cut mix (X_w) and no downside deviation of S, to keep the
  follow-up's decisive statistic unseen.
- **Fix (optional):** RESULTS.md could say so in one line.

**8. Note: two real runs started at the same second.**
- **The guard held, by under a second.** By my estimate from the recorded times, this run's dirty-tree check passed
  less than a second before buy-the-dip created its RUNLOG file, which would have shown as an untracked change.
- **Losing that race fails safe.** The run would have refused to start; it could not have run on changed code. All 41
  hashed files are unchanged.
- **Advice:** start real runs one after the other, so the guard's outcome does not depend on timing.

**9. Note: records still to update.**
- **PLAN.md section 20** needs its run 0 row. M3 allows it now, since NO EDGE earns no look.
- **README.md** has no run 0 line yet.
- **RESULTS.md** says "Audit: pending".
- **TESTING.md** already records the tiers on `e62233e`, unlike vol-steady (its audit's finding 7).

**10. Note: this audit adds looks at the train window.**
- Finding 1's reruns (plain volatility at this run's settings, and the four 2020 pairings) are new looks at the train
  years.
- So are the two study reproductions, though those only repeat logged trials.
- **Any later study on these years (the follow-up included) should list this audit as a prior look,** as this plan
  lists W1.

**11. Note: the readings of M1 and M2 hold.**
- **R_0's head.** My independent construction of R_0's head (fold 0's per-row share) and of the q-only shift
  (`s_fold(c_k) × q(c_(k+u) mod W)`) reproduces every stored shift.
- **z under the shift.** M2's reading that z moves with q changes no number here: activation comes before every check
  of the span.

**Corrections after the final check, 2026-11-24.** A final verifier checked this audit against the outputs. I
recomputed each point myself (scratch scripts in the session scratchpad under `dvaudit/fix2/`; the train panel loaded
through `load_panel` with `last_close` 2023-01-01 00:00 UTC behind a loader that refuses any later request or bar)
before changing anything:
- **Finding 6's description of N0 was wrong.** It said N0 re-cuts to each year's share at the start of the year. N0
  buys the year's share only where the rule was stepped back at t0 (seed A: 2018 and 2020); in 2019, 2021 and 2022 it
  kept the rule's wallet (61%, 78% and 33% crypto at the first kept close). Rewritten with a year-by-year table, from
  N0 rebuilt with `trend.always_in_n0` (bit for bit equal to `oos.parquet`). Because RESULTS.md made the same claim,
  the finding is now "should fix", and the Result counts six findings to fix instead of five. The E2 and E3 lines in
  section 2 now say what N0 and X are.
- **Finding 1's table:** plain volatility at 85 days and τ 0.35 against its own N0 is −0.5849 log, so −0.58, not
  −0.59. In the same finding, "about 0.10-0.15 log at either pair" mixed in the two 15-day runs' different N0s; on the
  2020 returns the measure cost 0.11 log at the 85-day pair and 0.06 at the 15-day pair. A note under the table now
  says what each run's own N0 is, and finding 2's "level with holding" now names its N0 and gives the gap against
  this run's N0 (−0.09 log). The sentence before the table said the reruns start "from the same book"; they start
  from the same 10,000 USD at the panel's first row, and enter 2020 with different wallets. It now says so.
- **Finding 6's 2020 starting figure:** 41% is the share N0 bought, decided at the 3 January 2020 close; 43% (42.7%)
  is N0's crypto at the next close, the first kept close of 2020. Both are now named. (The first version said 43%
  only.)
- **Section 2's E2 row:** the "other draws" I first quoted were 4,000-resample runs, given as ranges. They are
  replaced by 10,000-resample values at named seeds (the lab's `steady.paired_bootstrap` at seeds 1-3, my own sampler
  at seeds 11-13), and the stored p values are given to four places (0.9938 and 0.9836).
- None of these changes the verdict (NO EDGE), a criterion, a gate, the checklist or "RETURN TO RESEARCHER". These
  rechecks repeat computations already listed in finding 10 and add no new kind of look at the train years.

## Checklist (backtest-auditor)

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | Independent rule and book equal to 6.7e-16; 80 tamper cases unchanged before the cut and moved after it |
| 2 | Survivorship | N/A | BTC and ETH only |
| 3 | Data snooping | PASS | Validate-window looks used: 0; the test window not read. Prior looks disclosed (VP's V1-V6, W1, W2). This audit adds descriptions on train years (finding 10) |
| 4 | Point-in-time inputs | PASS | The measure at c reads closes up to c; activation at the first Monday with c ≥ L; orders fill at the next open |
| 5 | Trades per parameter | FLAG | 82 / 3 = 27, under 30 (finding 5) |
| 6 | Plateau ±20% | FAIL (G5) | (a) s × 1.2 keeps 0.67 of S's Sharpe; (b) the default's L × 1.2 keeps 0.67. Both steps reach outside the box, which the plan allows |
| 7 | Walk-forward | FAIL (G1) | 5 expanding folds, 365-row test blocks, H0 from row 0. S out of sample: Sharpe 0.31, +26%, worst fall −60.6% (seed B 0.37). Equity curve: the S_A column of `results/downvol-steady/train/run0/oos.parquet` |
| 8 | DSR, total trial count | FAIL | 3e-5 effective (about 18 effective trials of 2,400); 2e-16 raw; 4e-18 at the strict 4,849. PSR at 0 is only 0.75 |
| 9 | PBO | FAIL | 0.78 (all rows), 0.76 (active rows) |
| 10 | CPCV distribution | N/A | Not in the plan (TP's protocol is walk-forward with the shift null) |
| 11 | Cost model | PASS (placeholders) | `config/costs.yaml` as read and hashed (`0eeadeac…`); its values are still placeholders (SCOUTING) |
| 12 | Doubled costs | FAIL (G2) | S at 2x: 0.28, against > 0.5 |
| 13 | Capacity | N/A | Scouting; no measured slippage |
| 14 | Monte Carlo against the budget | FAIL (G6) | Worst-fall p5 −79.6% (p50 −56.1%) at block 20; −82.1% at block 60; shuffled trades −71.7%. Budget 35% |
| 15 | Regimes | FAIL (G8-excess) | S trails N0 in bull, bear and sideways months; bull months carry −0.88 of the −0.93 |
| 16 | Benchmarks | FAIL | G7: 0.31 against 0.43 (BTC) and 0.43 (50/50). Against random re-timing of its own steps (E1) and against holding (E2): fails |
| 17 | Data quality and snapshot | PASS | Snapshot and both panel hashes reproduced; the one known missing close (Kraken, 2018-01-13) |

Trial count: 2,400 (12 studies × 200, none failed); about 18 effective; strict 4,849 (4,863 with K4 as 15).

Final test window: **not run**. Items 1-17 do not all pass, and the verdict is NO EDGE. **Verdict: RETURN TO
RESEARCHER.** The plan ends here for downvol-steady; the follow-up, if the owner wants it, is a new pre-registered
study.

> **Lead's corrections after the second final check (2026-11-24).** Wording only, no number or result changed: the E3
> line now says X moves the wallet to the year's average crypto by buying or selling (at t0 the rule held more than
> its yearly average in 2019, 2021 and 2022, so X sold); the 35% and 30% figures of the 15-day reruns now name their
> point, the 3 January 2020 close. RESULTS.md now gives 2020's averages (holding 57%, the rule 20%), as finding 6's
> fix asks.

# vol-steady: pre-registration (a volatility-scaled hold)

**Status: PRE-REGISTRATION.** Written 2026-11-23 by the lead, at the owner's request in chat ("okay lets do
volatility now"), before any vol-steady code or result exists and before any bar was read for it. It is committed
before the code that runs it.

- Branch: R. Steady drawdown budget **35%** (`max_drawdown_budget_pct: 35`), as read from `config/risk_levels.yaml`
  (SHA-256 `d3f58253dfc2dbbe0ca5e54a4fa12489ab0e08827ecbc309e8ab2b7cc028723e`), owner-approved in writing on
  2026-11-21.

**How this plan is written.** It reuses trend-steady's reviewed and executed protocol: `research/trend-steady/PLAN.md`
at commit `b47fcf3`, with its amendments M1-M27, A1 and A0, called **TP** below.
- **TP applies section by section unless a section below changes it.** "TP 9" means trend-steady PLAN.md section 9.
- Only the trading rule, its parameters and what depends on them change; the stop-loss variant is dropped.
- So the folds, the harness, the objective, the search, the luck controls, the gates, the verdict and the one-look
  protocol are the ones already reviewed by `backtest-auditor` and `risk-officer`, built, tested and run once.

The owner asked for lean work ("keep it lean"), so there is no separate plan review. The `backtest-auditor` audit
after run 0 checks the run against this plan.

> **SCOUTING ONLY.** Every number comes from the lab's reference engine (`lab/runner/portfolio.py`, driven by
> `lab/runner/trend.py`'s one executor), not NautilusTrader (hard rule 3; the Nautilus work is on hold). It uses the
> **placeholder** costs of `config/costs.yaml`, and exchange candles stand in for Base prices. A result here can make
> nothing ready for paper; the best it can earn is "worth a Nautilus build".

## In plain words

**The rule.** Hold BTC and ETH half and half, with at most a crypto share s of the wallet (the customer's setting:
30%, 40%, 50% or 60%); the rest is USDC. Every Monday, measure how wild crypto has been over the last L days.
- When it has been calmer than a target level τ, hold the full share s.
- When it has been wilder, hold less, in steps of a quarter: ¾ s, ½ s, ¼ s, or none at all when it is four or more
  times as wild as the target.

**Why it might work.** Calm and wild spells cluster: a wild week tends to be followed by more wild weeks. If wild
spells don't pay more on average, stepping back during them gives a smoother ride for the same gain: a better return
for the risk taken. Studies of stocks and other markets ("volatility-managed portfolios", Moreira and Muir 2017; and
crypto papers since) report this. Our own synthetic demo did not show it (the volatility-sized dip buy did worse,
AGENTS.md), so it is a real test.

**What would count as an edge** (the same bar the trend rule had to clear):
- The rule's own timing beats the same schedule shifted to random other weeks.
- It beats simply holding the full share s, after costs, over 2018-2022.
- It also holds without BTC's best years and without any single year.
- It cuts falls more than holding the same average amount of crypto.

Otherwise the verdict is NO EDGE or INCONCLUSIVE, and the rule can still be offered as a risk dial (a smoother ride),
not as an edge.

## 1. Question and hypothesis (replaces TP 1)

- **Question.** Does scaling a Steady wallet's crypto share by recent crypto volatility give a better risk-adjusted
  return than holding the same mix, after costs, by more than chance? Data: the Kraken train window, out of sample
  2018-2022 by walk-forward.
- **H1:** E1 and E2 hold (section 11). **H0:** the share schedule's timing is worth no more than the same schedule
  shifted in time, and no more than holding.
- **The mechanism's prediction, stated before any result:** on panels with volatility clustering and a constant
  drift, E1 should often hold (the edge is real there). On panels with no serial structure it should hold at about
  its size, 5% (section 9).

## 2. Prior looks (disclosure; replaces TP 2)

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| V1 | trend-steady run 0 (2026-11-23, NO EDGE) on the same data: the trend rule's 2018-2022 path, its falls, and that holding 50/50 at s fell 61% | the lead, the owner | That 2018 and 2022 dominate; the choice of a non-trend rule |
| V2 | hold-mix-cap, rebalance-steady and protect-gains run 0: the falls of held mixes by crypto share | the lead, the owner | That the crypto share drives the fall |
| V3 | dip-timing (2026-11-20), including its single validate look | the lead, the owner | Validate-window dips (section 13) |
| V4 | The demo on synthetic data: volatility-sized dip buying did not help (AGENTS.md) | everyone | The expectation is open |
| V5 | General knowledge: BTC and ETH daily volatility is high (roughly 60-100% a year) and clusters | everyone | The τ range |
| V6 | protect-gains' validate look (V1 there), if it runs before vol-steady's look: brake results on 2023-01-02 .. 2024-07-01 | the lead, the owner | Validate only (section 13) |

The train window is far from fresh: four studies have run on it.

## 3. Data (TP 3 unchanged)

Kraken and Binance daily panels, snapshot `1746a21b75683e76`, and the bars hash and panel hashes of TP 3. Every frame
must have `index.max() <= 2023-01-01 00:00 UTC` until the validate look. The test window is never read.

## 4. The rule (replaces TP 4's trend states; the limits part of TP 4 unchanged)

**The basket return.** At each close t ≥ 1: b_t = 0.5 × (C_BTC,t / C_BTC,t−1 − 1) + 0.5 × (C_ETH,t / C_ETH,t−1 − 1),
and x_t = ln(1 + b_t). The 2-day row of 2018-01-13's missing close enters as one return, unscaled, as in TP.

**The volatility at check close c**, for lookback L:
- σ̂(c) = √365 × sd, the sample standard deviation (ddof 1) of x over t = c − L + 1 .. c;
- the mean and the sum of squared deviations are computed with `math.fsum`, two-pass, once per window (never a
  running sum, as TP's SMA);
- it exists only from c ≥ L.

**The share.**
- m(c) = 1.0 if σ̂(c) = 0, else min(1.0, τ / σ̂(c)).
- q(c) = `math.floor(m(c) * 4.0 + 1e-9) / 4.0`, so q ∈ {0, 0.25, 0.5, 0.75, 1}.
- **The crypto share in force** from check close c is s × q(c), with targets `trend.share_targets(s × q(c))` =
  (s q / 2, s q / 2).

**When it trades:**
- **Check closes:** every Monday 00:00 UTC close, as in TP 4. Before the first check close with c ≥ L, the share is
  0 (all USDC; TP's "start out").
- **Orders:** as in TP 4's executor. An order is sent at a check close where the target vector changes, and a limit
  breach between checks is fixed at the next open. Fills at the next open.

**Encoded in trend.py's schedule:** z = (1, 1) on every row from the first check close with c ≥ L, (0, 0) before,
and the per-check share s × q(c). So `trend.in_force`, `run_states`, `stitched_schedule`, `shifted`, `span_targets`
and `run_span` run unchanged.

**The quarter steps** are the one design choice not taken from the literature. They are fixed now to keep trades
few (R1), and disclosed in section 18.

**The limits.** Every target is (s q / 2, s q / 2) with q ≤ 1 and s ≤ 0.72 (the plateau extreme). Every such vector
passes `check_targets` with the Steady limits as read and h = 0.02: each coin is at most 0.36 against 0.60 − 0.02,
and cash is at least 0.28 against 0.20 + 0.02. TP's feasibility check (stop rule 12) runs unchanged, with the share
set extended to every s × q.

## 5. Parameters and search box (replaces TP 5's table)

| Parameter | Kind | Range | Scale | Spec |
|---|---|---|---|---|
| `lookback` L | int | 10 - 120 days | log | `Param("lookback", "int", 10, 120, log=True)` |
| `target_vol` τ | float | 0.30 - 1.20 (annualised) | log | `Param("target_vol", "float", 0.30, 1.20, log=True)` |
| `crypto_share` s | float | 0.30 - 0.60 | linear | `Param("crypto_share", "float", 0.30, 0.60)`, as TP 5 and TP 8 |

- **Why these bounds:**
  - L of 10-120 days spans the windows used in volatility-targeting work (about 1 to 6 months).
  - τ of 0.30-1.20 spans "step back almost always" to "step back only in extreme spells", given V5.
  - τ near the top makes the rule hold s nearly always: the search can choose "no timing", and E1 and E2 would then
    fail. That is allowed.
- **Fixed, not searched:** the BTC/ETH split 50/50, the Monday check day, the quarter steps, the start state (all
  USDC), h = 0.02, the limits as read and the cost model.
- **The first active row:** the smallest L (10) has its first check close at row 14 (2017-01-16), so no trial can
  hold a coin before row 15. TP's active-row readings of G3 and G4 start at row 15 (TP's started at 204).

## 6. Objective (TP 6 unchanged)

TP 6's objective, with its zero-row disclosure re-read for row 15.

## 7. Walk-forward, harness, search and selection (TP 7 unchanged)

These are unchanged from TP 7:
- the folds and harness H0, and the common start state;
- Optuna TPE, `n_workers = 1`, the seeds (fold seed + 1000 i, final + 5000) and the two searches, seeds A = 0 and
  B = 1;
- `stable_region(k = 10)`;
- the trial budget (12 studies × N per run, at most 2 amendment runs);
- the study names (`vol-steady-s0_wf00` .. and so on);
- the projection guard.

**N** comes from amendment A1, by TP 7's throughput rule (60 CPU-minutes for 12 studies), timed on the built adapter.

## 8. User settings and allowed values (TP 8 unchanged in substance)

- **Branch R.** The user setting is the most crypto the wallet may hold, s, with **allowed values 0.30, 0.40, 0.50
  and 0.60**, as in TP 8.
- **Who confirmed it:** `risk-officer` confirmed these values for trend-steady on 2026-11-22 (TP M24, TP 8), for targets
  (s/2, s/2). Here every target is (s q / 2, s q / 2) with q ≤ 1, a smaller holding of the same coins, so the same
  confirmation covers it. Section 4 shows each vector passes.
- **Fixed at θ_final's values:** L and τ are not user settings.
- **Unchanged from TP 8:** the default (the allowed value nearest θ_final's s; two distances within 1e-12 are a tie,
  which goes to the lower value, TP M19), the grid steps, the riskiest step and the narrowing rule.

## 9. Comparators and luck controls (TP 9, with these changes)

**Comparators.**
- S, R_0 and B3 (the 207 guarded shifts, u = 53..259, lead guard G = 52) are unchanged. R_0 executes S's per-check
  share path; a shift moves the whole share path, each entry carrying its fold's s.
- **Why the lead guard stays at 52 weeks:** the volatility reads at most 120 days (about 17 weeks) back, so 52 weeks
  is more than enough.
- **N0 (always in)** holds (s_i/2, s_i/2) from S's book at t0: the rule without its scaling.
- **X (the exposure-matched mix)** is unchanged; it is E3's comparator, and the heart of the question: does timing cut
  falls beyond simply holding less crypto?
- B1, B2, B3-lead and N0-span are unchanged.

**A0, procedure controls** (synthetic, before any real bar; replaces TP 9's A0 text):
- **Negative controls:** `shuffled_market` of each positive panel (seed j). Shuffling destroys volatility clustering,
  so there is no edge. **3 or more false positives in 20** (E1 and E2 both hold): stop rule 15. Triage, then the owner
  in writing.
- **Positive controls:** `make_panel(synthetic_market(2190, seed=1000+j, start="2017-01-02"), snapshot_id="synthetic")`,
  j = 0..19. They have volatility clustering and regimes. **Power below 4 of 20** (E1, E2 and P all hold): the owner
  is told in writing before run 0 and decides, as TP's power alarm.
- **Volatility clustering with no momentum** (replaces TP M21's size check; a description, no alarm): 200 panels
  built exactly as TP M21's (constant drift 0.001, GARCH(1,1) α 0.08 β 0.90 with Student-t(5) innovations, ETH = 0.8
  × BTC + 0.6 × own, `default_rng(10_000 + j)`, j = 0..199).
  - The rule runs at (L, τ, s) = (30, 0.60, 0.50); R_0 is scored against its 207 guarded shifts.
  - E1's pass rate is reported as **power where the mechanism is real**.
  - TP's M21 alarm does not apply: here a pass is a true positive.

**Slow calibration** (the null; replaces TP 9's two points):
- Panels: TP's iid random walks (constant volatility, so no clustering and no edge).
- The rule runs at (L, τ, s) = (10, 0.80, 0.50), the noisiest, and (120, 0.80, 0.50), the longest memory.
- τ = 0.80 is near those walks' basket volatility (about 0.82), so the share moves often.
- **Holds if at most 18 of the 200 panels pass E1 at each point**, as in TP.

## 10. Gates (TP 10 unchanged)

G1-G8 as in TP 10:
- G6's budget is 35%;
- G8 is G8-excess;
- every point of TP 10's "where measured" table applies;
- the stop-loss variant's rows are dropped.

## 11. Research criteria (TP 11, with these changes)

- **E1-E8 as in TP 11**, on vol-steady's S, R_0, N0 and X.
  - E5(b), check-day sensitivity, re-runs S with the other 6 weekdays.
  - E8 uses Binance folds 1-4 as in TP. This keeps the 155 shifts; Binance's first volatility comes earlier, but the
    reading is kept as pinned.
- **P, a minimum-information floor** (replaces TP's coin-state count):
  - Count at least 20 **share changes**: check closes where s × q(c) differs from the share in force before it, whose
    orders fill in kept rows.
  - At least one must fall in each of at least 4 of the 5 folds.
  - The first move from 0 at activation, re-cuts between folds and limit fixes do not count.
- **E9 at the validate look:** as in TP 11, with vol-steady's θ_final(A).

## 11A. The stop-loss variant: dropped

Nothing of TP 11A is run: no SL-* item, no placebo stops, no φ levels. Its run counts, A0 parts and outputs are
removed. Stop-losses are protect-gains' subject.

## 12. Verdict and headline (TP 12, with these changes)

- **The verdict:** NO EDGE, INCONCLUSIVE or EDGE, by TP 12's order.
- **The headline:** CANDIDATE FOR AUDIT, EDGE, NOT A CANDIDATE, or the verdict.
- **What EDGE means**, in words: "the volatility rule's timing beat the same share schedule shifted in time and beat
  holding the same mix, after costs, over 2018-2022, also without BTC's best years and without any single year, and
  it cut falls more than holding the same average amount of crypto (SCOUTING)".
- **There is no stop-loss variant line.**
- **R1-R5** as in TP 12. R3 reports:
  - the worst day and the 1st-percentile day;
  - the share of days with any crypto;
  - the share of days at each step q.

  TP's exit-delay item is dropped.
- **Descriptions never decide**, as TP 12 says.

## 13. The single validate look (TP 13 unchanged)

Earned only by TP 13's rule. E9 as in section 11. Prior looks at the validate window: V3, and V6 if protect-gains'
look runs first. Both are disclosed again at the look.

## 14-16. Trial counting, protocol and outputs (TP 14-16, with these changes)

- The stop rules, the amendment rules (stop rule 18 included), the strict count (with the stop-variant terms
  removed), the logging and the outputs are TP's.
- Paths and names use `vol-steady`: `results/vol-steady/`, `research/vol-steady/RUNLOG.jsonl`, `trials.csv` and
  `evaluations.csv`.
- **The order of work:**
  1. this plan committed;
  2. the build and its tests;
  3. the three tiers on the build's commit;
  4. A1 (N), then A0 (its alarms decide whether run 0 starts);
  5. run 0;
  6. RESULTS.md and one audit;
  7. the validate look only if earned.
- **Budgets:** run 0 and each amendment run 60 CPU-minutes; A0 120.
- **The scripts refuse a real run 0** until PLAN.md section 15 holds the A1 line (`N = <n>`) and the A0 line (no
  alarm, or an owner decision on file), as TP M27.

## 15. Amendments

- **M1 (2026-11-23, after the build, before A1, A0 or any run on real data): readings the build pinned.** The
  build is `lab/runner/volsteady.py`, `research/vol-steady/` and two test files (TESTING.md #65, #66). Each
  reading is in `INTERPRETATIONS` and the start record.
  - **Section 4 overstated what runs unchanged.** `trend.stitched_schedule` takes one share per fold and one
    share for the rows before the first check, while this rule's share moves every week. So
    `volsteady.stitched_schedule` builds R_0's schedule, and the rows before its first check take fold 0's share
    row by row. `trend.shifted`, `span_targets` and `run_span` run unchanged.
  - **The rule's floats:**
    - the basket return is `log1p(0.5 (r_BTC − 1) + 0.5 (r_ETH − 1))`, with r the close ratio;
    - σ̂ is `√365 × √(ss / (L − 1))`, with ss from two `math.fsum` passes over L panel rows;
    - activation is the first Monday check at row ≥ L of each panel's own rows, so Binance activates earlier in
      its folds.
  - **P:** in each fold run, the first share change is the first buy and is not counted. Order reasons are labels
    only: "switch" is the activation order, "re-cut" a quarter step.
  - **The strict trial count** stays TP's, N_raw + 49 (the K4-as-15 description + 63). It counts trend-steady's
    prior looks, which are not all vol-steady's. Keeping it can only lower the strict DSR, so it is the
    conservative reading.
  - **Descriptions adapted to this rule** (they decide nothing):
    - a whipsaw is a share change reversed within 28 days;
    - spells with q < 1 replace "out of the market" spells;
    - R3 reports the days at each q, and the exit delay is dropped;
    - correlations also include trend-steady's S_A.
  - **The slow calibration on the synthetic build** (null: iid walks, at most 18 of 200 allowed): 3 of 200 at
    (10, 0.80, 0.50) and 13 of 200 at (120, 0.80, 0.50). Both pass. The second is above the nominal 4.8%; about 17%
    of null runs would score that high, and it is reported as is.
- **A1 (2026-11-24, on commit `5b5df1e`, after the tiers passed on `d8855c9`; synthetic only): N = 200.** `throughput.py` on `make_panel(synthetic_market(2190, seed=21))`: a 200-trial study of the built adapter takes 4.4 CPU-seconds, so 12 studies need about 0.9 CPU-minutes, far under 60. One backtest takes 15.1 ms, under twice trend-steady's stand-in (13.1 ms), so no re-timing is needed. Projections: run 0 2.6 CPU-minutes (budget 60), A0 29.0 (budget 120).
- **A0 (2026-11-24, on commit `5b5df1e`; synthetic only): stop rule 15: no alarm; the power alarm fired (power 3 of 20); owner decision: reports/director/2026-11-24-owner-answer-vol-a0-power.md.** Negative controls: 1 false positive in 20 (E1 alone 2, E2 alone 1). Positive controls: E1, E2 and P together on 3 of 20 (E1 alone 6, E2 alone 4). Volatility clustering with no momentum: E1 on 26 of 200 (13%), a description. The owner answered "Run it" and asked the lead to think of a different angle. The candidate angles are written in that record before run 0.

## 17. Code to build, and its tests (TP 17, adapted)

- **`lab/runner/volsteady.py`** holds:
  - the basket return;
  - σ̂ by `math.fsum`, two-pass;
  - m, q and the share path at check closes;
  - its live twin (`VolStream`, fed one close at a time);
  - the param spec and the parse;
  - the adapter (`vol_backtest`, a `BacktestFn` through `trend.run_states`).

  It reuses `trend.py`'s executor, schedule, shift, N0, X, plateau, E1/E2 and gate helpers by import. Neither
  `trend.py` nor any other `lab/` file is edited. A helper that needs a change is copied into `volsteady.py` and
  tested there.
- **`research/vol-steady/`** holds study, run_train, freeze, run_validate, controls (A0) and throughput (A1). They
  are adapted from trend-steady's scripts, with the stop-loss variant removed.
- **`tests/test_volsteady.py` and `tests/test_volsteady_scripts.py`** carry TP 17's list where it applies, plus:
  - **by hand:** σ̂ on built paths (a flat path gives σ̂ = 0, so m = 1); q exactly on each quarter boundary (τ / σ̂ =
    0.25, 0.5, 0.75, 1, and one ulp below); activation at c ≥ L; the 2-day row;
  - **tamper-the-future:** σ̂, the shares, the targets, every result row and the orders;
  - **live/batch parity:** `VolStream` equals the batch shares on every close;
  - **identity:** with τ above every σ̂, the run equals N0's always-in path from activation;
  - **the slow calibration** at the two points of section 9;
  - A0's three control sets pinned by hand;
  - every reported number recomputed from its inputs, as TP's script tests do.
- **TESTING.md:** section 3 rows, and bug-log rows from #65 on (#64 is protect-gains' validate build).

## 18. Known weaknesses

1. **Not fresh data.** Four studies have used 2017-2022 (V1-V3). E1, E2, E6 and E7 limit the damage.
2. **The quarter steps** are our choice. Finer steps would trade more; coarser steps would time less.
3. **Two bear years** (2018 and 2022) drive E2, E3, E4 and G7, as in TP. E1 and E7 carry the claim.
4. **A Sharpe edge may come with less return.** Holding less crypto in wild spells can lower the total gain while
   raising the risk-adjusted return. RESULTS.md reports both.
5. **The scouting engine and the placeholder costs.**

## 19. Owner questions

None blocking.
- Run 0 waits for A0's alarms as in TP 9.
- Later, the target level τ could become a second user dial ("how much to step back when it gets bumpy"). That would
  need its own pre-registered range and grid. It is not part of this study.

## 20. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| Plan | 2026-11-23 | the lead | No market data. Read: trend-steady's PLAN.md (sections 4-12), `lab/runner/trend.py`'s function list and docstrings, and the protect-gains run 0 results already known (V2) |
| T1 | 2026-11-24 | the lead | Run 0 on the train window (Kraken and Binance, 2017-2022), commit `cc03c2a`: NO EDGE (`RESULTS.md`). No validate or test bar |

**Validate-window looks used for vol-steady: 0.**

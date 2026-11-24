# downvol-steady: pre-registration (a downside-volatility-scaled hold)

**Status: PRE-REGISTRATION.** Written 2026-11-24 by the lead, at the owner's request in chat ("yes set up downside
volatility next"), after vol-steady run 0 and before any downvol-steady code or result exists or any bar was read for
it. It is committed before the code that runs it.

- Branch: R. Steady drawdown budget **35%** (`max_drawdown_budget_pct: 35`), as read from `config/risk_levels.yaml`
  (SHA-256 `d3f58253dfc2dbbe0ca5e54a4fa12489ab0e08827ecbc309e8ab2b7cc028723e`), owner-approved in writing on
  2026-11-21.

**How this plan is written.** It is vol-steady's plan, `research/vol-steady/PLAN.md` at commit `ea1426e` with its
amendments M1, A1 and A0, called **VP** below. VP is itself trend-steady's reviewed protocol (TP) with the rule
swapped.
- **VP applies section by section unless a section below changes it.** Only the volatility measure changes, together
  with what depends on it (the prior looks and the trial count).
- So the folds, the harness, the objective, the search, the luck controls, the gates, the verdict, the one-look
  protocol and the allowed shares are vol-steady's, already built, tested, run once and audited.
- The owner asked for lean work, so there is no separate plan review. One `backtest-auditor` audit follows run 0.

> **SCOUTING ONLY,** as VP: the reference engine (`lab/runner/trend.py`'s executor), the placeholder costs and
> exchange candles. It cannot make anything ready for paper.

## In plain words

**The rule.** The same as vol-steady's:
- hold BTC and ETH half and half, up to the customer's crypto share s (30-60%);
- every Monday, step back in quarters when crypto has been wilder than a target τ.

**The one change: only falling days count as "wild".** A big up day no longer makes the rule step back; only the size
of the down days does. This targets what vol-steady run 0 suggested:
- plain volatility counts wild up-moves in rallies too;
- after 2018 the search mostly switched the scaling off.

**What counts as an edge:** exactly vol-steady's bar (E1-E8 and P; the gates).

## 1. Question and hypothesis (replaces VP 1)

- **Question.** Does scaling a Steady wallet's crypto share by recent **downside** volatility give a better
  risk-adjusted return than holding the same mix, after costs, by more than chance? Data: the Kraken train window,
  out of sample 2018-2022 by walk-forward.
- **H1:** E1 and E2 hold (VP 11). **H0:** the share schedule's timing is worth no more than the same schedule shifted
  in time, and no more than holding.

## 2. Prior looks (disclosure; VP 2 plus W1-W2)

Every prior look of VP 2 (V1-V6) applies, and two more:

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| W1 | **vol-steady run 0** (2026-11-24, NO EDGE) on these exact train years. The plain-volatility rule made +210% against +170% for holding (E2 p 0.25); its timing beat shifts with one seed only; after 2018 the search chose τ near 1.0 (rarely stepping back); its excess over holding was negative in 2021 | the lead, the owner | **The choice of this angle.** See below |
| W2 | protect-gains' validate look V1 (2026-11-24) on 2023-01-02 .. 2024-07-01 | the lead, the owner | Validate only (VP 13) |

**How this angle was chosen.** "Downside volatility" is the first of four angles that the lead wrote down before
vol-steady run 0 read any market bar, in
[reports/director/2026-11-24-owner-answer-vol-a0-power.md](../../reports/director/2026-11-24-owner-answer-vol-a0-power.md)
(committed in `2bdd7fd`, before run 0's commit `cc03c2a`).
- After run 0, the lead suggested it as the most promising of the four.
- The owner chose it.

So the angle predates run 0, but the decision to test it first came after seeing run 0. Run 0's 2,400 trials are
counted in this study's strict trial count (section 14).

## 3-4. Data and the rule (VP 3 unchanged; VP 4 with the volatility measure replaced)

**The basket return** is VP 4's: x_t = ln(1 + b_t), with b_t the 50/50 simple return.

**The downside volatility at check close c**, for lookback L:
- d_t = min(x_t, 0.0), over t = c − L + 1 .. c;
- σ̂⁻(c) = √365 × √(2 × ss / L), with ss = `math.fsum(d_t × d_t)`.
  - It is one exactly rounded sum per window, never a running sum.
  - It is computed around zero, not around the window's mean.
  - It divides by L, not L − 1.
- **The factor 2** makes σ̂⁻ about equal to σ̂ for returns symmetric around zero, so τ keeps VP 5's meaning ("a
  typical volatility of τ a year") and VP 5's box.
  - Exactly: for L returns alternating +a and −a (L even), σ̂⁻ = √365 × a, while σ̂ = √365 × a × √(L / (L − 1)).
- It exists only from c ≥ L, as σ̂ does.

**The share** is VP 4's with σ̂⁻ in place of σ̂:
- m(c) = 1.0 if σ̂⁻(c) = 0 (no down day in the window), else min(1.0, τ / σ̂⁻(c));
- q(c) = `math.floor(m(c) * 4.0 + 1e-9) / 4.0`;
- the share in force is s × q(c).

**Unchanged from VP 4:** the Monday check closes, all USDC before activation, the orders, the encoding into
`trend.py`'s schedule, the quarter steps and the limits.

## 5. Parameters and search box (VP 5 unchanged)

| Parameter | Range |
|---|---|
| `lookback` L | 10 - 120 days, log int |
| `target_vol` τ | 0.30 - 1.20, log |
| `crypto_share` s | 0.30 - 0.60, linear |

The first active row is 15, as in VP 5.

**A note on noise.** With L = 10, a window may hold only a few down days, so σ̂⁻ is noisier than σ̂. The box is kept
as VP's so that the two studies compare directly; the search decides.

## 6-13. Objective, walk-forward, settings, comparators, gates, criteria, verdict, the look (VP unchanged)

These are VP 6 to VP 13 as written, with the same names under `downvol-steady`:
- the objective and the walk-forward;
- H0 and both seeds;
- N from A1 (VP 7);
- the allowed shares 0.30-0.60 and the default (VP 8);
- R_0 with its 207 guarded shifts, N0, X, B1, B2, B3-lead and N0-span (VP 9);
- the gates G1-G8-excess, R1-R5, E1-E8 and P (P counting share changes);
- the verdict and headline;
- the single validate look, only if earned (VP 13).

**A0's three control sets** are VP 9's, run on this rule. On the "volatility clustering with no momentum" set the
fixed point is (L, τ, s) = (30, 0.60, 0.50).

**The slow calibration** runs at VP's two points, (10, 0.80, 0.50) and (120, 0.80, 0.50), on iid random walks. It
holds if at most 18 of 200 pass E1 at each point.

## 14-16. Trial counting, protocol and outputs (VP 14-16, with one change)

- **The strict trial count** is VP's (N_raw + 49) **plus 2,400**, vol-steady run 0's trials on the same data (W1).
  The effective count, PBO and the trial-Sharpe variance still come from this study's own searches.
- Paths and names use `downvol-steady`: `results/downvol-steady/`, and `research/downvol-steady/RUNLOG.jsonl`,
  `trials.csv` and `evaluations.csv`.
- **Order of work** (as VP):
  1. this plan committed;
  2. the build and its tests;
  3. the three tiers on the build's commit;
  4. A1, then A0;
  5. their records in section 15 and the tiers on that commit;
  6. run 0;
  7. RESULTS.md and one audit;
  8. the validate look only if earned.
- **Budgets:** run 0 and each amendment run 60 CPU-minutes; A0 120.
- **A real run 0 refuses** until section 15 holds the A1 line (`N = <n>`) and the A0 line (no alarm, or an owner
  decision on file), as VP.

## 15. Amendments

- **M1 (2026-11-24, after vol-steady's audit, before any downvol-steady code, run or bar): the reason corrected, and
  E1 judged with the share held fixed.**
  - **The reason in "In plain words" was wrong.** It read vol-steady run 0 as stepping back because of wild up-moves.
    vol-steady's audit (`research/vol-steady/AUDIT.md`, finding 2) showed that at the four 2020-21 step-downs, up days
    carried only 21-46% of the window's variance, so a downside-only measure would likely have stepped back about as
    often.
    - The lead told the owner. The owner chose to run this study anyway, together with the buy-the-dip study ("Why
      not both?", 2026-11-24, in chat).
    - W1 is therefore no support for this angle. The study is a test of an angle written down in advance, nothing
      more.
  - **E1 shifts only the volatility steps (finding 1 of that audit).** vol-steady's seed-A E1 passed because each
    fold's share s travelled with the shifted schedule. To stop that here:
    - **E1's null series for shift u** keeps each check close's own fold share and moves only the step:
      `share_u(c_k) = s_{fold(c_k)} × q(c_{(k+u) mod W})`. The rows before c_0 are unchanged. It uses the same guarded
      offsets u = 53..W − 1, the same rank-p rule (at most 9 of 207 at or above) and the same execution from S's book.
    - The same q-only shift is used for E1 inside E7, E8 (155 Binance shifts), the S(s_k) check (where s is constant
      anyway) and E9's validate shifts.
    - VP's whole-schedule shifts, where s moves with q, are still run and reported as **E1-whole**, a description that
      decides nothing.
    - The q-only shift is written in `lab/runner/downvol.py` and tested there:
      - by hand on a two-fold path;
      - with s held equal in every fold, it equals VP's whole-schedule shift bit for bit;
      - no price is read.
- **M2 (2026-11-24, after the build, before any run or bar): readings the build pinned** where the plan is silent
  (`study.INTERPRETATIONS`, recorded in the start record; no market data read):
  - **Under the q-only shift, z moves with q;** s, the fold, the check closes and the head rows stay. No number moves
    on any span the study runs, because activation (row ≤ 126) comes before every span's first check.
  - **E1-whole's scope:** at S for both seeds on Kraken, the 207 guarded offsets, logged as `shift_whole` evaluation
    rows that are never counted; its 2 × 207 runs are in the projection.
  - **The q-only shift is also used for the descriptions** B3-lead, the lag rank, the leave-one-year-out E1 and the
    bear-year E1, besides M1's list and A0 and the slow calibration. Where s is one value it equals VP's shift bit for
    bit.
  - **The seam:** `volsteady.py` calls its own σ̂ directly, so `downvol.py` holds copies of its four path functions with
    the measure as an argument; a test pins that with VP's σ̂ passed in, each equals vol-steady's bit for bit.
  - The 2,400 prior trials are a pinned value; the parameter parse is VP's (lookback ≥ 2); the correlations also use
    vol-steady's S_A.
- **M3 (2026-11-24, after the code review of the build, before A1, A0, run 0 or any bar):**
  - **One more description:** next to the lag rank, run 0 records the lag shifts' p5, p50 and p95 Sharpe
    (`descriptions.stitched.lags`, u = 208..259, q-only as M2). A review found that R_0 can sit above every lag shift
    under both nulls, so the rank alone cannot show which null was used; the percentiles can. It decides nothing.
  - **This file stays byte-identical from run 0's start until the look**, or until run 0's verdict earns no look. It is
    in the config hash, so an edit after run 0 would make `freeze.py` refuse an earned look (stop rule 10). Run 0 is
    recorded in RESULTS.md, README.md and the RUNLOG; section 20's row for it is added after the look, or once no look
    is earned.
  - The review's other test gaps (TESTING.md #73) were closed in the tests; no rule or number changed.
- **A1 (2026-11-24, on commit `7d582ef`, after the tiers passed on `7d582ef`; synthetic only): N = 200.** `throughput.py` on `make_panel(synthetic_market(2190, seed=21))`: a 200-trial study of the built adapter takes 6.7 CPU-seconds, so 12 studies need about 1.3 CPU-minutes, far under 60. One backtest takes 17.5 ms, under twice trend-steady's stand-in (13.1 ms), so no re-timing is needed. Projections: run 0 3.2 CPU-minutes (budget 60), A0 35.6 (budget 120).
- **A0 (2026-11-24, on commit `7d582ef`; synthetic only): stop rule 15: no alarm; the power alarm fired (power 1 of 20); owner decision: reports/director/2026-11-24-owner-answer-downvol-a0-power.md.** Negative controls: 0 false positives in 20 (E1 alone 0, E2 alone 0). Positive controls: E1, E2 and P together on 1 of 20 (E1 alone 5, E2 alone 1, P 19). Volatility clustering with no momentum: E1 on 17 of 200 (8.5%), a description. The owner answered "can we do the first and the third?": run 0 goes ahead as pre-registered, and a follow-up design for a more sensitive test is written first, on synthetic data only, and committed before run 0 reads any bar. A NO EDGE verdict here means the test could not tell.

## 17. Code to build, and its tests (VP 17, adapted)

- **`lab/runner/downvol.py`** holds σ̂⁻ and its live twin. Everything else is imported from `lab/runner/volsteady.py`
  and `lab/runner/trend.py`, through a small seam:
  - neither of those files is edited, because each is in a completed study's config hash;
  - a helper that must differ is written in `downvol.py` and tested there.
- **`research/downvol-steady/`** holds vol-steady's scripts, adapted: the rule, the names, the strict count and the
  prior looks.
- **`tests/test_downvol.py` and `tests/test_downvol_scripts.py`** carry VP 17's list, plus:
  - **by hand:** σ̂⁻ on built paths:
    - a window with no down day gives σ̂⁻ = 0 and m = 1;
    - a window of only up days far wilder than τ keeps the full share (the whole point of the rule);
    - alternating ±a paths give σ̂⁻ = √365 × a and σ̂ = √365 × a × √(L / (L − 1)), to 1e-12;
    - the divisor L and the factor 2;
    - zero is the reference, not the mean;
  - **tamper-the-future** on σ̂⁻, the shares, the orders and the result rows;
  - **live/batch parity** for the stream;
  - **an identity:** with the factor-2 σ̂⁻ swapped back to VP's σ̂, the run equals `volsteady.vol_backtest` bit for
    bit;
  - the slow calibration at the two points;
  - every reported number recomputed from its inputs, as VP's script tests do.
- **TESTING.md:** section 3 rows, and bug-log rows from #69 on.

## 18. Known weaknesses

1. **Not fresh data,** and **chosen after seeing vol-steady run 0** (W1). The strict count adds its 2,400 trials. E1,
   E2, E6 and E7 limit the damage but cannot remove it.
2. **Noisier at short lookbacks:** few down days in a short window.
3. **Two bear years** carry E2, E3, E4 and G7, as in VP and TP.
4. **The scouting engine and placeholder costs.**

## 19. Owner questions

None blocking. As in VP, run 0 waits for A0's alarms.

## 20. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| Plan | 2026-11-24 | the lead | No market data. Read: VP and vol-steady's RESULTS.md (W1) |
| Build, review | 2026-11-24 | `quant-researcher`, three reviewers, a verifier | No market data: synthetic bars and hand-built paths only (TESTING.md #69, #70, #73) |

**Validate-window looks used for downvol-steady: 0.**

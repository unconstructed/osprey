# keep-risk-steady: pre-registration (the "keep my risk steady" setting)

**Status: PRE-REGISTRATION, before any code or result.** Written 2026-11-25 at the owner's request in chat (the
record: [reports/director/2026-11-25-owner-answer-ride-test.md](../../reports/director/2026-11-25-owner-answer-ride-test.md)).
It was written before any keep-risk-steady code or result existed, and before any bar was read for it. No market bar
was read to write it: the sizing in appendix A uses synthetic markets only. It is committed before the code that runs
it.

**How it was chosen.** Three proposals were drafted in parallel from different angles (user-first, statistics-first,
reuse-first). After two were finished the owner asked for a lean process, so the planned judging and review rounds
were stopped. The lead adopted the user-first proposal as written. The statistics-first proposal was read only for
its summary: one knob is simpler for users, and its run-0 and A0 compute is about half. `risk-officer` then
confirmed section 14. No other review ran before commit.

> **SCOUTING ONLY.** Every number will come from the lab's reference portfolio engine (`lab/runner/portfolio.py`
> driven by a new `lab/runner/keeprisk.py`), not from NautilusTrader (AGENTS.md hard rule 3; the Nautilus work is on
> hold). Costs are the **placeholder** costs of `config/costs.yaml`, and Kraken and Binance candles stand in for Base
> prices. Nothing here can make anything ready for paper, and no number here may be shown to users before a
> NautilusTrader rerun of that number (hard rule 3).

**How this plan is written.** It follows buy-the-dip's plan (`research/buy-the-dip/PLAN.md`, run once and audited)
section by section, because both study a self-directed tool with a suggested default and no edge claim. The data
pins, the 24-month windows, the boom-year checks, the stop rules and the outputs are buy-the-dip's. The ride statistic,
its matched yardstick, the equivalence reading and the exposure-neutral shift test come from the 2026-11-24 design
note ([reports/director/2026-11-24-downvol-followup-design.md](../../reports/director/2026-11-24-downvol-followup-design.md)),
adapted to a tool with fixed settings instead of a walk-forward strategy. Everything specific to the tool is written
out below. `risk-officer` confirms the allowed values (section 14) before run 0, and one `backtest-auditor` audit
follows run 0.

## In plain words

**What the user switches on.** The app's words for the setting (a template the user owns, like buy-the-dip):

> "Keep my risk steady: when crypto gets wilder than **w** a week, hold less of it, in quarter steps, and go back as it
> calms down."

- The user keeps their own Steady mix (say 50% crypto, half BTC and half ETH). That mix is the **most** crypto the
  tool holds.
- Every Monday the tool looks at how much the user's BTC/ETH mix has been swinging over the last two weeks. If that
  swing is above the level **w** the user picked, it holds less crypto: three quarters, half, a quarter or none of the
  mix's crypto, the first step that brings the swing back under the level. When things calm down, it steps back up.
- So the wallet's weekly swing stays under about (crypto share) × w at each Monday: about 5% a week for a 50% mix with
  w = 10%. A sudden crash can still beat it for a week, before the tool sees it.
- The user picks w from four values: **8%, 10%, 12% or 15%** of a typical weekly move of their BTC/ETH mix. A lower w
  steps back more often. Nothing else is a knob: the two-week look-back, the Monday check, the quarter steps and the
  trading band are fixed.

**Why this study, and what it does not claim.** vol-steady and downvol-steady found no extra return from scaling
crypto by volatility. A description of the same years then showed why: volatility predicts the next week's volatility
fairly well, but not the next week's return (section 2, P8). So the honest value of this setting is a **calmer ride**,
not more money. This study claims **no return edge**. It asks the question a user would ask:

> "Is the ride calmer than if I simply held less crypto all the time? And what does it cost me?"

**What it measures.** For each setting and each of 8 tested user mixes, on 49 two-year periods of 2017-2022:
- **How calm:** the typical size of a down day of the wallet, against
  - the user's **full mix** held steadily (what switching on changes); and
  - a **plain mix holding the same average crypto** steadily (could the user get the same calm by simply setting a
    lower crypto share?). This is the fair yardstick.
- **What it costs:** the return a year it gave up against both, and its fees.
- **What it feels like:** the worst fall, the worst week, how often and how long it stepped back, the rebound it
  missed after the worst low, how often it trades.

**How it tells timing from luck.** Holding less crypto in wild weeks only helps if the wild weeks really come in
clusters. Otherwise a moving share is slightly **rougher** than a steady one with the same average (section 9). So the
study checks, on the full 2017-2022 history:
- that the cut against the same-average mix is unlikely to be chance (a resampling test, made stricter because four
  settings are tested);
- that the same steps, moved to other weeks, did not do as well (each moved copy against its own same-average mix);
- and, so that a "no" means something, whether the data rule out a cut of **10% or more** in the size of down days.

**What the app gets, for any setting a user picks.** A short card: how calm it was against the full mix and against
holding less, what it cost, how often it traded, and one of these labels:
- **CALMER THAN HOLDING LESS** (the claim holds, with the luck checks);
- **CAN'T TELL** (calmer in most periods, but chance is not ruled out);
- **NO NOTICEABLE DIFFERENCE** (it rode about like simply holding less crypto);
- **ROUGHER THAN HOLDING LESS** (holding less steadily was calmer).

**The suggested default.** Rules fixed now pick the **gentlest** setting (the largest w) that was calmer than holding
less in at least half the two-year periods, did not cost clearly more than holding less, and was not shown to be
"about the same as holding less". A setting confirmed CALMER THAN HOLDING LESS comes first. If no setting qualifies,
the answer is **NO DEFAULT**, and the app's honest advice is "to get a calmer ride, lower your crypto share instead".

**What to expect.** On made-up markets where volatility clusters (appendix A), the rule was calmer than the
same-average mix in most two-year periods, and its steps were much better timed than chance. But the cut was small
(about 3-11% in down-day size), so the full claim was confirmed on only 0-4 markets in 20 for any one setting. On
made-up markets without clustering, the rule was slightly rougher than holding the same average crypto, the claim was
almost never confirmed, and a default was named on 1 of 40 markets. So the likely outcomes on real data are a
default labelled CAN'T TELL, or NO DEFAULT. A clean CALMER THAN HOLDING LESS is possible but not likely. The
pre-check (A0, section 13) measures these chances properly before any real bar is read.

## 1. Question

For a Steady wallet using "keep my risk steady" at a fixed setting w, with the user's own mix (crypto share s, BTC's
share of the crypto f):
1. How much calmer is its ride than the user's full mix, and what does that cost a year?
2. At the **same average crypto**, is its ride calmer than a plain mix that simply holds that crypto steadily, by more
   than chance? Or do the data show it is about the same, or rougher?
3. How often and how long does it step back, how often does it trade, and what does it miss after a crash?
4. Which w is the best suggested default by section 10's rules, and how robust is that choice?

**What is claimed and what is not.**
- No return edge is claimed or tested. The return numbers are costs and descriptions, never a gate.
- The one claim the study can make is a **ride claim** for a setting: "calmer than holding the same average crypto
  steadily". It is made only through section 9's tests.
- The managed Steady portfolio's gates (AGENTS.md "Validation gates") are not changed and do not apply: this is a
  self-directed tool under the owner's tool rules (owner, 2026-11-25). Nothing here is one of our managed strategies.

## 2. Prior looks (disclosure)

Every study below read the 2017-2022 train bars this study will read. The train window is far from fresh. That is
acceptable for a tool that claims no return edge, but it weakens the ride claim (section 16), and every threshold
below is fixed before any keep-risk-steady run.

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| P1 | **rebalance-steady** run 0 (2026-11-20, NO EDGE): falls of rebalanced and static Steady mixes by crypto share, 2019-2022 and in-sample 2017-2022; falls grow steeply with the crypto share | the lead, the owner | That the crypto share drives the fall; the tested shares |
| P2 | **hold-mix-cap** run 0 (2026-11-21): the falls, fees and rebalance counts of thousands of held BTC/ETH/USDC mixes on 24-month windows. **Not read by this plan's author** (its RESULTS.md, RISK.md, AUDIT.md, decision.json, runs.csv and falls.csv), except the accidental lines of P13 | the lead, the owner, `risk-officer`, `backtest-auditor`, `director` | The yardsticks N and X are held mixes; expectations about their falls and fees |
| P3 | **trend-steady** run 0 (2026-11-23, NO EDGE): 2018 and 2022 dominate the falls; holding 50/50 at its share fell 61% | the lead, the owner | That two crash years drive any ride number (section 16) |
| P4 | **protect-gains** run 0 (2026-11-23) and its validate look V1 (2026-11-24, on 2023-01-02 .. 2024-07-01): the 24-month windows; held mixes past 35% in 2018 | the lead, the owner | The windows; the budget display; validate is not fresh (section 13) |
| P5 | **vol-steady** run 0 (2026-11-24, NO EDGE): plain-volatility scaling on these years; its timing beat shifted copies with one search seed only; after 2018 the walk-forward chose τ near 1.0 a year (about 14% a week), rarely stepping back | the lead, the owner | The rule family; the w range (section 5) |
| P6 | **downvol-steady** run 0 (2026-11-24, NO EDGE) and its audit: the walk-forward's 2020 pick (85-day look-back, τ 0.35) kept the rule out of the 2020 rebound (it ended 2020 up 33%, against 166% for holding). The audit's reruns of 2020: downside measure at 15 days and τ 1.03 +141%; plain volatility at the same +156%; plain volatility at 85 days and τ 0.35 sat out about 11 weeks, +48% (the rule itself +32% over the same days) | the lead, the owner | **A short fixed look-back** (section 5); the missed-rebound measure (section 8) |
| P7 | **buy-the-dip** run 0 (2026-11-24) and its audit: its yardsticks were cut by the Steady limits (the audit's main finding); BTC's best bar-years on Kraken are 2017 (+1,304%) then 2020 (+304%), so windows avoiding both are only k = 12 and 48 | the lead, the owner | Yardsticks that the limits never cut (section 6); the expectation that the "without the two best years" window check is MISSING (section 16) |
| P8 | **The lead's description of 2026-11-25** (scratch, decides nothing), on 2017-2022 Kraken daily bars: the rank correlation of one block's volatility with the next block's, for BTC, **+0.41** (7-day blocks), **+0.38** (14-day), **+0.25** (30-day); downside volatility weaker, +0.27, +0.22, +0.12; returns +0.01, +0.09, +0.14, none significant. For the 50/50 BTC/ETH basket: volatility +0.36, +0.30, +0.01; returns about 0 | the lead, the owner | **The choice of plain volatility, of a 14-day look-back and of a weekly check** (section 5), and the expectation of no return effect. It also means the study **knows already** that volatility clusters in these bars: the shift test (section 9) mostly re-confirms P8 and is weak new evidence. The net ride claim against the same-average mix is not answered by P8 |
| P9 | **dip-timing** (2026-11-20, NO EDGE), including its single validate look | the lead, the owner | Validate only: validate is described as a rising market (section 13) |
| P10 | **The 2026-11-24 design note**: synthetic markets only, no market data; its statistic, matched mix, equivalence δ = 10%, cost margin m = 2 points a year, exposure-neutral shift test and power warnings | the lead, the owner | Sections 6 and 9 (adapted, as the owner asked) |
| P11 | **General knowledge** of the public price history (the 2017 bubble, the 2018 bear market, March 2020, the 2020-21 rise, the 2022 bear market) and that BTC and ETH swing roughly 60-100% a year and cluster | everyone | The w values (8-15% a week); the boom years |
| P12 | **This plan's author** read: CLAUDE.md, AGENTS.md, TESTING.md; the owner record of 2026-11-25; the design note in full; buy-the-dip's PLAN.md in full, its AUDIT.md lines 1-120 and RESULTS.md lines 1-80; downvol-steady's RESULTS.md lines 1-60, PLAN.md lines 30-70 and AUDIT.md lines mentioning 2020; the verdict lines of rebalance-steady's, trend-steady's, protect-gains' and vol-steady's RESULTS.md; the prior-look rows of trend-steady's and vol-steady's PLAN.md; `reports/director/2026-11-21-boom-check.md`; the code of `volsteady.py`, `downvol.py`, `trend.py`, `protect.py`, `holdmix.py`, `portfolio.py`, `reference.py`, `montecarlo.py`, `lab/data/synthetic.py` and downvol-steady's `controls.py`; `config/*.yaml`. It ran the synthetic experiments of appendix A | this plan's author | Every choice below |
| P13 | **Accidental reads by this plan's author** (each by a search, not opened on purpose). (a) A search across `research/*/RESULTS.md` printed one line of hold-mix-cap's RESULTS.md: its count of validate looks (0), with no result. (b) A search of `docs/app/features.md` printed lines of its "Hold this mix" section and of its open-questions list. They hold the owner's hold-this-mix decisions (a drift band of 30% of each coin's target with at most 2 rebalances in any 30 days for wallets up to 5,000 USD, 50% with 1 above; Steady's "a few trades a month"), and one sentence of hold-mix-cap results (how often limit fixes broke through the cap by crypto share, up to 7 rebalances in 30 days at 78% crypto) | this plan's author | The trading band (section 5) **could** have been informed by (b). It was chosen as one quarter step (0.25) for the reason given in section 5, not from (b), and is not tuned. Agents who build, run or audit this study should not open those lines |

**Synthetic seeds already used** (appendix A; A0 must not reuse them): `trend.garch_panel(j)` for j = 70000-70019
(streams 80000-80019); `synthetic_market(seed)` 71000-71019 and 73000-73019 (shuffled with seeds 73500-73519);
`trend.random_walk_panel(seed)` 72000-72019; `default_rng(0)` for the scratch bootstraps. The design note's section 7
lists the seeds used before it (garch_panel up to 8719, synthetic_market up to 9929, default_rng 50000-50199 and
91000-91019). Its ranges 20000-69999 were reserved for a follow-up that was not run; this study does not use them.
The two proposals not adopted (2026-11-25) also used only streams below 200000: the statistics-first one
`trend.garch_panel` j in 70000-89000 and direct seeds 85000-97959; the unfinished reuse-first one `garch_panel` 60000,
90000 and 90100 and seeds 92000 and 93000. A0's ranges (from 200000) and its second range (from 300000) avoid all of them.

## 3. Data (buy-the-dip section 3, unchanged)

| Item | Pinned |
|---|---|
| Primary | Kraken daily `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN` through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=2023-01-01 00:00 UTC)`: 2190 rows, closes 2017-01-02 .. 2023-01-01; close 2018-01-13 is missing (no ETH bar) and never filled |
| Robustness | Binance daily `BTCUSDT`, `ETHUSDT`, the same `last_close`: 1963 rows from 2017-08-18 |
| Snapshot | `1746a21b75683e76`. Stop unless the bars hash is `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e` and the panel hashes (`steady.panel_hash`) are Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587` |
| Never read | The validate window and the test window. Every frame is checked: `panel.index.max() <= last_close` |
| Costs | `Costs.from_yaml(capital_usd=5000)` (1x) and its `.stressed(2.0)` (2x); `Costs.from_yaml(capital_usd=500)` for the small-wallet description |

**The periods.**
- **Windows (the user's experience):** protect-gains' 24-month windows, `protect.rolling_windows(source)`. Window k
  holds the closes from the 2nd of month M_k to the 1st of M_(k+24) at 00:00 UTC, both included, with M_0 = January
  2017. Kraken k = 0..48 (49 windows, 729-731 rows each); Binance k = 8..48 (41 windows, 730-731 rows).
- **The full span (the luck control):** every row of the source panel: Kraken rows 0..2189, Binance rows 0..1962.
- **The signal reads the full source panel** (point in time): at a window's first close the tool already sees the
  closes before it, as a user who switches it on would.

## 4. The wallet, the limits and what the user changes

- **The deposit:** D = 5,000 USD in USDC at the run's first close (row 0 of the window or span). No later deposits or
  withdrawals. The first buy is ordered at close 0 and filled at row 1's open.
- **The user's mix (conditions, not settings):** the crypto share s ∈ {0.30, 0.40, 0.50, 0.60} × BTC's share of the
  crypto f ∈ {0.50, 0.75}: 8 mixes. The mix is the most crypto the tool holds.
- **The Steady limits as read** from `config/risk_levels.yaml` through `portfolio.risk_limits("steady")`, with
  h = 0.02: cash at least min_cash (0.20) and each coin at most max_coin (0.60). The run refuses to start if the
  file's values differ from these. Every target of every run (section 6 included) passes `portfolio.check_targets`
  with h = 0.02 by construction: the largest target is 60% crypto, with BTC at most 45% and cash at least 40%.
- **The drawdown budget** (35%, as read) is shown next to the falls (D3), not enforced, as in protect-gains and
  buy-the-dip.

**What the user changes:**

| Setting | Values | In the app's words |
|---|---|---|
| w, the swing level | 8%, 10%, 12%, 15% | "Hold less crypto when your BTC/ETH mix's typical weekly move goes above w" |

**What is fixed** (the same for every user; section 5 says why):

| Fixed | Value |
|---|---|
| The swing measure | plain volatility (sample standard deviation) of the user's BTC/ETH mix's daily returns |
| The look-back | the last 14 daily returns |
| The check | every Monday at the 00:00 UTC daily close, plus a decision at switch-on |
| The steps | quarters of the mix's crypto: 1, 3/4, 1/2, 1/4 or 0 |
| Trading back to the level | when a coin is more than a quarter of its target away (b = 0.25), at a Monday |
| The BTC/ETH split of the crypto | the user's f, kept at every step |

## 5. The rule (exact)

**5.1 The mix's daily return.** For close t ≥ 1 of the source panel:
x_t = `math.log1p(f * (C_BTC,t / C_BTC,t-1 - 1.0) + (1.0 - f) * (C_ETH,t / C_ETH,t-1 - 1.0))`; x_0 is NaN. At
f = 0.50 this is `volsteady.basket_returns` bit for bit (tested). Kraken's missing 2018-01-13 close makes one 2-day
row, one return, unscaled (as vol-steady).

**5.2 The swing at close c.** σ(c) = `volsteady.sigma_hat(x, 14, rows=[c])[c]`: √365 × the sample standard deviation
(ddof 1) of x over rows c − 13 .. c (14 returns), two exactly rounded `math.fsum` passes, never a running sum. It exists
from row 14 on.

**5.3 The level.** τ = w × `math.sqrt(365.0 / 7.0)`, the annual figure of a weekly move w, so that σ and τ are on the
same scale. τ is 0.5777, 0.7221, 0.8665 and 1.0832 for w = 8%, 10%, 12% and 15%.

**5.4 The step.** q(c) = `volsteady.quarter(volsteady.scale(σ(c), τ))`: m = 1 if σ = 0, else min(1, τ / σ); q =
`math.floor(m * 4.0 + 1e-9) / 4.0`. So q is the largest quarter with q × σ ≤ τ (up to the 1e-9 tolerance): the tool
always steps far enough to bring the measured swing under the level.

**5.5 When it decides.**
- **Monday checks:** every close c ≥ 14 of the source panel whose close time is a Monday 00:00 UTC
  (`trend.check_closes(index, 0, 14)`). Kraken: W = 311 checks, from 2017-01-16 to 2022-12-26. Binance: W = 278, from
  2017-09-04.
- **The switch-on decision** at the run's first close r0 (a panel row): if r0 ≥ 14, q_on = q(r0) from σ at that close,
  whatever its weekday; if r0 < 14 (fewer than 14 returns: only Kraken window 0 and the two full spans), q_on = 1, so
  the tool holds the full mix until its first Monday check.
- **In force at close t:** the q of the latest decision at or before t (q_on before the run's first Monday check).

**5.6 The targets.** At close t: `trend.in_force(ones, s * q(t), f=f)`, that is (s q f, s q (1 − f)) of the wallet in
BTC and ETH, the rest in USDC. The same function builds the shifted copies (section 9), so the unshifted copy is the
rule bit for bit.

**5.7 The executor** (`keeprisk.ride_run`, a new driver of `portfolio._simulate`; one order per close; an order
decided at close t fills at the open of t + 1; the decision at the last close is never filled):
1. **Close 0:** order the targets in force (the first buy; reason `first`). An all-USDC target sends no order.
2. **At a Monday close t ≥ 1:**
   - if the targets in force differ from the last order's targets, order them (reason `step`);
   - else, if some coin a has |w_a(t) − T_a| > 0.25 × T_a (strict; w at close t, drifted), order the targets in force
     (reason `drift`). A coin with target 0 never triggers.
3. **At any close t ≥ 1 without an order from 2:** if the weights at close t break a Steady limit, judged at the
   limits with `portfolio.LIMIT_TOL` (`portfolio._breach_test(min_cash, max_coin)`, as `portfolio.rebalance` judges
   them), order the targets in force (reason `limit`).

The tool only buys and sells BTC and ETH against USDC, at the user's split. It holds no other coin, no leverage and no
short.

**5.8 Live and batch.** `keeprisk.KeepRiskStream`, fed one close at a time (with the switch-on close's history), gives
the q in force that section 5.5 gives on the panel, bit for bit (tested, TESTING.md section 7). This is what production
would run.

**Why these fixed choices.**
- **Plain volatility, not downside volatility.** In P8 plain volatility predicted the next block's volatility better
  (+0.41 / +0.38 / +0.25 for BTC against +0.27 / +0.22 / +0.12). A downside measure also reads 0 in a straight rally,
  so it holds the full share at a top. The **ride** is still measured on down days (section 8).
- **14 returns.** P8: 7- and 14-day blocks predict the next block best, 30-day blocks much less (+0.01 for the basket).
  Seven returns give a noisy standard deviation and about half again as many trades (appendix A: about 23 orders a
  year at w = 10% on GARCH markets with 7 returns, against 16 with 14). P6: an 85-day look-back sat out the 2020
  rebound. Seven and 28 returns are run as descriptions (section 7), never as settings or in D1.
- **A Monday check** matches the one-week horizon of P8, keeps trades to a few a month, and reuses tested code.
- **Quarter steps and the floor** reuse vol-steady's tested `quarter`, keep trades few, and read simply ("it steps
  back in quarters").
- **The band 0.25** is one quarter step: "the tool keeps each coin within one step of its level". It applies the same
  to the rule and to every yardstick (section 6), so drift cannot favour either. It is not tuned (P13).
- **The switch-on decision** copies what a user would see: when they switch it on, the tool looks at the last 14 days
  at once and does not wait for Monday.
- **w from 8% to 15% a week** (about 58% to 108% a year): around the typical swing of a BTC/ETH mix (P11). At 8% the
  tool steps back in most weeks; at 15% only in wild weeks. A higher level would almost never act.

**Code reused unchanged** (none of these files is edited; each is in a completed study's config hash):
`volsteady.sigma_hat`, `scale`, `quarter`, `basket_returns`; `trend.check_closes`, `in_force`, `Schedule`, `shifted`,
`span_targets`, `guarded_offsets`, `rank_holds`, `bar_years`, `without_years`, `rolling_count`;
`portfolio._simulate`, `_breach_test`, `check_targets`, `risk_limits`, `LIMIT_TOL`; `holdmix.money_metrics`,
`year_returns`; `protect.rolling_windows`, `boom_removals`, `windows_without`, `index_signal`;
`montecarlo.stationary_bootstrap_indices`; `steady.panel_hash`; `panel.load_panel`.

## 6. The yardsticks (each run against its own, in the same period, with the same costs)

All three are run by the same executor as the rule (section 5.7): the same first buy at close 0, the same Monday
check, the same band 0.25, the same limit fixes and the same costs. Only the target differs, and it never changes.

| Yardstick | Target crypto share | The question it answers |
|---|---|---|
| **N, your full mix** | s | What does switching the tool on change, and cost? |
| **X, the same average crypto** (decisive) | x = `math.fsum(share[0 .. n-2]) / (n - 1)`: the rule's in-force share (s × q) averaged over the rows whose decision can fill, in that run | Could the user get the same calm by simply holding less crypto steadily? |
| **X_eq, the same calm** (description) | x_eq = x × exp(V) (V of that run pair, section 8), scaled down by the largest λ ≤ 1 that passes `check_targets` with h if it ever fails (bisection to 1e-12, as `trend.exposure_target`); not run when V is MISSING (recorded) | For the same calm, how much return would holding less have given? |

**How they avoid buy-the-dip's yardstick problem.** buy-the-dip's twins ordered amounts the Steady limits then cut,
so they were not the schedules they claimed to be (P7). Here every yardstick's target is at most the user's mix
(60% crypto at most, each coin at most 45%), so `check_targets` with h passes and the limits never cut a target. X
holds exactly its stated share at each re-cut. Only drift inside the band (the same band for the rule) and rare limit
fixes (the same rule) move it.

**Known biases, stated now:**
- **X and X_eq are hindsight yardsticks.** x is known only at the period's end, like buy-the-dip's twins. They are
  benchmarks, not strategies a user could follow, so hard rule 4 does not apply to their targets. Their
  tamper-the-future test holds the target fixed and tampers only the prices.
- **X is matched on the average target, not the average realised crypto.** Between orders the rule and X both drift
  with prices, but at different times. The gap between their realised average crypto weights is reported per run
  (section 8). It is a description, not a stop, because it is a market outcome.
- **A moving share is penalised by design.** With no timing information, a share that moves around an average is
  slightly rougher than the same average held steadily, because a few high-crypto weeks weigh more than a few
  low-crypto weeks help (Jensen's inequality). So X is a demanding yardstick: the rule beats it only if its timing
  more than pays for that. Appendix A: on markets with no clustering, the rule's down days were 0-4% **larger** than
  X's.
- **Drift is not neutral in a trend.** In a rally both drift up between Mondays and in a crash both drift down. They
  drift at different moments, so V mixes a little of this with timing. The null sets of A0 measure where V sits when
  there is no timing.

**Not used as a yardstick:**
- **The app's "hold this mix" tool.** Its band and wait differ from this tool's, so a difference would mix timing with
  trading rules. The design note found that against it a no-edge control gave a false pass (P10).
- **The plain X of trend-steady** (bought once, then drifts): it drifts up in rallies, a known bias in the rule's
  favour (P10, section 2 of the note).

## 7. The grid and the counts

| | Values | Count |
|---|---|---|
| w, the swing level (the setting) | 8%, 10%, 12%, 15% | 4 |
| Look-back | 14 returns (fixed) | 1 |
| The user's mix: s | 0.30, 0.40, 0.50, 0.60 | 4 |
| The user's mix: f | 0.50, 0.75 | 2 |
| **Cells** (setting × mix) | | **32** |

**Pools.** Kraken 1x (49 windows; full span W = 311, guarded shifts u = 53..310: 258); Binance 1x (41 windows;
W = 278, 225 shifts); Kraken 2x (49 windows; 258 shifts).

**Runs.**
- **Window runs** (the rule, N, X, X_eq): 32 × (49 + 41 + 49) × 4 = **17,792**.
- **Full-span runs** (the rule, N, X, X_eq, and each guarded shift with its own same-average mix): per cell Kraken 1x
  4 + 2 × 258 = 520, Kraken 2x 520, Binance 4 + 2 × 225 = 454; 32 × 1,494 = **47,808**.
- **Descriptions** (Kraken 1x only; never in D1 or D2):
  - look-back 7 returns: 32 × (49 × 4 + 4 + 2 × 259) = 22,976;
  - look-back 28 returns: 32 × (49 × 4 + 4 + 2 × 256) = 22,784;
  - the 500 USD wallet at 14 returns: 32 × (49 × 4 + 4) = 6,400.
- **Total: 117,760 runs.**
- **Resampling** (10,000 resamples each): one index set per row set, shared by every cell that uses those rows:
  Kraken rows 1..2189 (Kraken 1x, 2x, the look-backs and the 500 USD wallet), Binance rows 1..1962, the two boom
  removals, and the six leave-one-year-out removals (Kraken): 10 index sets.
- **Amendment A1** times the run on synthetic bars before run 0. The scratch timing (appendix A: about 8 ms a
  full-span run and 3 ms a window run on this machine) projects about 15-30 CPU-minutes. The run refuses to start
  above 240 CPU-minutes (stop rule 7).

## 8. Measured per run

**Per window run** (the rule; each yardstick's own numbers too, where they apply). Returns are the run's daily net
returns r_t, rows 1..n − 1.
- **The ride:**
  - **DD, the typical down day:** DD = √(`math.fsum`(min(r_t, 0)²) / (n − 1)), the root mean square of the down days
    around zero.
  - **V_X = ln DD(rule) − ln DD(X)** and V_N = ln DD(rule) − ln DD(N). V < 0 is calmer. The app's "down days N%
    smaller" is 100 × (1 − exp(V)). A DD of 0 makes V MISSING.
  - **F, the worst fall:** `-holdmix.money_metrics(result, costs)["max_drawdown"]`; the worst week and the worst day
    from the same.
  - **Over-cap weeks:** the share of the period's Monday-to-Monday weeks whose realised move √(Σ r_t² over its 7 days)
    exceeds s × w, for the rule, N and X. In plain words: how often the promise "under about s × w a week" was broken.
- **The cost:**
  - CAGR = (Π(1 + r_t))^(365 / span) − 1, span = the days from the first to the last close;
  - **c_N = 100 × (CAGR(N) − CAGR(rule))** and **c_X = 100 × (CAGR(X) − CAGR(rule))**, in points a year (positive:
    the tool earned less); c_eq the same against X_eq;
  - fees and gas a year (`money_metrics`), and the first buy's cost.
- **Stepping back:**
  - x (the average crypto share), the rule's and X's realised average crypto weights and their gap, x_eq;
  - the share of rows 0..n − 2 with q < 1 and with q ≤ 0.5; the longest stretch with q < 1, in days; the number of
    step-downs and step-ups;
  - **the missed rebound:** I = `protect.index_signal(panel, f)` (the user's BTC/ETH mix, chain-linked); t_low = the
    first close of the period with the lowest I; the gap = N's return minus the rule's return from t_low to the first
    close at least 90 days later (or the last close), in points. In plain words: "after the worst low, it trailed
    your full mix by K points over the next three months".
- **Trading:** the orders by reason (`first`, `step`, `drift`, `limit`); orders after the first buy a year (× 365 /
  span); the most orders filled in any 30 days (`trend.rolling_count`).

**Per full span** (each cell and pool): the same numbers on the full span, plus section 9's statistics.

## 9. The luck control and the ride labels (full span, decided per cell)

The windows overlap heavily (one crash stands behind many of them), so they describe the user's experience but are not
separate evidence. The luck control runs on each cell's **full span**, one run of six years (Binance: five and a
half).

**9.1 The statistic.** V = ln DD(rule) − ln DD(X) on the full span (rows 1..n − 1), with X at the full span's x.

**9.2 RISK-X: is the cut against the same average crypto more than chance?**
- **The resampling:** a paired stationary bootstrap (`montecarlo.stationary_bootstrap_indices(n, 60, rng)`, mean
  block 60 days, 10,000 resamples, `rng = numpy.random.default_rng(0)`). The same index sets are used for the rule
  and X and for every cell on those rows (section 7). For resample b: V*_b = ½ (ln mean(min(r_rule, 0)²[idx_b]) −
  ln mean(min(r_X, 0)²[idx_b])). A resample with a zero mean for either series makes the cell MISSING.
- **The p-values:**
  - p_calm = (1 + #{V* ≥ 0}) / 10,001 (calmer);
  - p_rough = (1 + #{V* ≤ 0}) / 10,001 (rougher);
  - p_eq = (1 + #{V* ≤ ln 0.9}) / 10,001 (the equivalence reading: a cut of **δ = 10%** or more is ruled out when
    p_eq < 0.05).
- **Four settings are tested, so the calmer claim is made stricter (Holm).** Within each pool and mix, the four
  settings' p_calm are sorted, p_(1) ≤ p_(2) ≤ p_(3) ≤ p_(4). Setting (i) **passes** if p_(j) < 0.05 / (5 − j)
  for every j ≤ i (thresholds 0.0125, 0.0167, 0.025, 0.05; strict, as every p-value rule of the lab). This keeps the
  chance of any false "calmer" among the four at 5% or less within that mix. A setting that never steps back stays
  in the family with p_calm = 1.

**9.3 RISK-E1: were the steps better timed than the same steps on other weeks?** (exposure-neutral, as the design note
pins it.)
- **The copies:** the rule's q at its W Monday checks, q_0 .. q_(W−1), is rotated by u weeks: copy u holds
  q_((k + u) mod W) at check k. The rows before the first check keep q_on, unchanged. It is built as a
  `trend.Schedule` (checks c_k, z = 1, share s × q_k, one fold, the head at s × q_on), rotated by `trend.shifted`, and
  its per-row targets come from `trend.span_targets(schedule, n, f=f)`; it runs on `keeprisk.ride_run`.
- **Each copy against its own same-average mix:** X(u) at x_u, copy u's in-force share averaged over rows 0..n − 2.
  V_u = ln DD(copy u) − ln DD(X(u)). So holding less crypto on average never counts as timing.
- **The guarded copies:** u = 53..W − 1 (`trend.guarded_offsets(W)`; the one-sided lead guard of 52 weeks of
  trend-steady and vol-steady). Copies u = 1..52 see the future and are never in the null.
- **The rank:** rank p = (1 + #{u guarded : V_u ≤ V_0}) / (1 + #guarded), ties against the rule; E1 holds when rank p
  < 0.05 (`trend.rank_holds`). V_0 is the rule against X, and copy 0 must reproduce the rule bit for bit (section 11).
- E1 is not made stricter for the four settings: it is an extra condition and can only remove claims.

**9.4 The labels** (per cell and pool; checked in this order):

| Label | When |
|---|---|
| **MISSING** | A run of the cell failed (the rule, X, N, any copy or its mix), or V or a resample is undefined |
| **DOES NOT STEP BACK** | q = 1 at every decision of the full span (then the rule is N, X is N and V = 0) |
| **ROUGHER THAN HOLDING LESS** | p_rough < 0.05 |
| **CALMER THAN HOLDING LESS** | V < 0, RISK-X passes Holm, E1 holds, and p_eq ≥ 0.05 |
| **SMALLER, BUT BELOW NOTICE** | V < 0, RISK-X passes Holm, E1 holds, and p_eq < 0.05 (real but ruled out from reaching 10%) |
| **NO NOTICEABLE DIFFERENCE** | p_eq < 0.05 |
| **CAN'T TELL** | everything else |

**9.5 Flags printed with every label** (decide nothing outside D1-D2):
- **Cost flag** (the design note's, reject-only): with g = 365 × mean(ln(1 + r_rule) − ln(1 + r_X)) and g* the same
  on each resample, "COSTS MORE THAN HOLDING LESS" when (1 + #{g* ≥ −0.02}) / 10,001 < 0.05 (m = 2 points a year).
  Five or six years cannot show a cost is small; this flag only shows a clearly large one.
- **Same calm, more return?** CAGR(X_eq) against CAGR(rule) (point estimate).
- **The label in each check:** without each bar-year (2017 .. 2022, the owner's leave-one-year-out), without BTC's
  best bar-year and its two best, on Binance and at 2x costs (section 10, D2's checks), and at look-backs of 7 and 28
  returns.

**What a false label costs, and how each is bounded.**
- A false **CALMER** tells users something good that is not true. It is bounded by Holm within a mix (at most 5% if
  the bootstrap is honest), plus E1, and checked by A0 (section 13).
- A false **NO NOTICEABLE DIFFERENCE** or **ROUGHER** undersells the tool. Each is at 5% per cell, and A0 measures the
  first at its boundary.
- Seven studies have now looked at Steady claims on the same rows (section 2). No single 5% accounts for that; RESULTS
  says so next to any label.

## 10. Decision rules (fixed now, before any result)

Stage 1's pool (Kraken 1x) unless a rule names another. Medians are `numpy.median`, percentiles
`numpy.percentile(..., linear)`. MISSING flows through: a rule that needs a MISSING number gives MISSING, never a pass.
A failed run (other than an X_eq, a description) makes every rule whose pool holds it MISSING.

**D1. The suggested default** (one w for every user). For each setting w and each of the 8 mixes (49 windows each):
1. **Calmer than holding less in most periods:** V_X < 0 in at least half the windows (2 × count ≥ windows: 25 of 49).
2. **A noticeable cut is not ruled out, and it is not rougher:** the full-span label is CALMER THAN HOLDING LESS or
   CAN'T TELL.
3. **Not clearly costlier than holding less:** the median of c_X over the windows is at most 2.0 points a year
   (m, inclusive).
4. w is **usable** if 1-3 hold at each of the 8 mixes.
5. **Ranking among the usable settings:**
   - first, the settings labelled CALMER THAN HOLDING LESS at all 8 mixes;
   - then **the larger w** (the gentlest setting, which steps back least, costs least against the full mix and
     trades least). w is unique, so there is no further tie.
6. No usable setting gives **NO DEFAULT**. The output records, for every setting, the first rule and mix that failed.

**Why "gentlest first".** Every usable setting has passed the same ride tests, so the default is the one that changes
the user's wallet least. In appendix A a ranking by the number of calmer periods picked w = 8% or 10% in 31 of 33
cases; at 8% the tool held about 15-25% less crypto on average than the user chose. That is closer to "set a lower
crypto share" than to "keep my risk steady".

**D2. Robustness labels** (they decide nothing, but are printed next to the default; buy-the-dip's rules):
- The default is **ROBUST** only if each check gives the same default, or NO DEFAULT on both sides.
- A check that moves it gives **NOT ROBUST (check named)**; a MISSING check gives **MISSING (check named)**.
- Order: NOT ROBUST before MISSING before ROBUST.
- **The checks** (each reruns D1 on its own pool, with its own labels and Holm):
  - **Boom years** (the owner's rule, 2026-11-21): without BTC's best calendar year, then without its two best,
    ranked by `holdmix.year_returns` on Kraken's closes by bar day, ties to the earlier year
    (`protect.boom_removals`). The windows are those overlapping none of the removed years
    (`protect.windows_without`; fewer than 12 gives MISSING). The full-span labels are recomputed on the rows whose
    bar-year (`trend.bar_years`) is not removed: the same runs, a new index set over the kept rows (seed 0), E1 on the
    kept rows, Holm again. Nothing is refitted.
  - **Binance** (its 1x pool: 41 windows, rule 1 needs 21; its full span, 225 copies).
  - **2x costs** (the Kraken 2x pool).

**D3. The description and the app's card** (decides nothing; for every one of the 32 cells, the default highlighted):
- **Over the windows:** the median, the 10th and 90th percentiles and the share above 0 of V_X, V_N (as "N% smaller"),
  c_N, c_X and c_eq; x and x_eq; fees a year; F for the rule, N and X (median, 90th percentile Q and the worst),
  against the Steady budget of 35% as read (shown, not enforced) and the share of windows past it; the worst week; the
  over-cap weeks; the time stepped back and the longest stretch; the missed rebound (median and worst); orders a year
  and the busiest 30 days.
- **By the year of each window's first close**, the same core numbers (V_X, c_N, F).
- **The full span:** V and its 90% interval, p_calm (raw and its Holm outcome), p_rough, p_eq, E1's rank p, the label,
  the flags of 9.5.
- **The descriptions:** look-backs of 7 and 28 returns; the 500 USD wallet; the Binance and 2x numbers.
- **A0's power** printed next to every CAN'T TELL (section 13).

**The card the app can show for any tested setting** (filled from D3; numbers SCOUTING until rerun on NautilusTrader):

> **Keep my risk steady, at w = {w}% a week**, with your mix ({s}% crypto, {f}% of it BTC). In two-year periods of
> 2017-2022:
> - It held a median {x}% crypto and stepped back in {k}% of weeks.
> - **Against keeping your full mix:** down days {cut_N}% smaller; worst fall {F} against {F_N} (median; the worst
>   period {F_max} against {F_N,max}); it gave up a median {c_N} points a year (from {c_N,10} to {c_N,90}).
> - **Against simply holding {x}% crypto steadily:** {label sentence}.
> - About {t} trades a month (up to {t_max} in a busy month); fees about {fee}% a year.
> - After the worst low of a period it trailed your full mix by a median {rebound} points over the next three months.

**The label sentences:**
- **CALMER THAN HOLDING LESS:** "Its down days were about {cut_X}% smaller than holding {x}% crypto steadily. We tested
  four settings and checked that this is unlikely to be luck."
- **CAN'T TELL:** "Its down days were smaller than holding {x}% crypto steadily in {n} of 49 two-year periods (a median
  {cut_X}%), but we can't rule out that this was luck."
- **NO NOTICEABLE DIFFERENCE:** "It rode about like simply holding {x}% crypto steadily. If you want a calmer ride, a
  lower crypto share does about the same."
- **ROUGHER THAN HOLDING LESS:** "Simply holding {x}% crypto steadily gave a calmer ride than this setting."
- **SMALLER, BUT BELOW NOTICE:** "It was slightly calmer than holding {x}% crypto steadily, by less than a tenth."
- Any flag adds one line (for example "It cost clearly more than holding {x}% steadily", or "On Binance prices: can't
  tell").
- **NO DEFAULT** gives the app: "We don't suggest a setting: in 2017-2022, {reason, from D1's record}. To get a calmer
  ride, consider a lower crypto share."

## 11. Checks the run must pass (consistency stops)

Each is a bug if it fails (stop rule 5).
- **The steps do not depend on costs, the wallet or s.** For each source, f and w, the q path (every decision's q) is
  identical at every s, at 1x and 2x and at 500 and 5,000 USD, and so are the closes of the `step` orders. `drift` and
  `limit` orders read the wallet and may differ; those pairs are counted as a description.
- **An independent recompute of q:** at every decision, σ recomputed in `run.py` with numpy (`std(ddof=1)` × √365
  over the same 14 returns) agrees with the engine's to 1e-12 (relative), and the q from it is identical, except where
  4τ/σ lies within 1e-9 of a whole number (there the engine's value stands, and the case is listed).
- **Copy 0 is the rule:** the unshifted schedule's run equals the rule's run bit for bit (returns and orders), and every
  copy's multiset of check q's equals the rule's.
- **The yardsticks never step:** their orders are `first`, `drift` or `limit` only; X's target equals the rule's average
  share, recomputed, bit for bit.
- **Every order's targets** pass `portfolio.check_targets` with the Steady limits as read and h = 0.02.
- **Windows:** each window's row count matches the calendar (729-731), and its share path equals the full panel's on
  those closes after the switch-on decision.
- **Accounting** matches an independent book of coin units and cash on every 9th run, at run time; `money_metrics`'
  own fee check passes on every run.
- **Counts** equal section 7's exactly, failures included.
- **A config hash** covers `keeprisk.py`, `volsteady.py`, `trend.py`, `protect.py`, `holdmix.py`, `portfolio.py`,
  `reference.py`, `steady.py`, `lab/validation/*.py`, the data loaders (`panel.py`, `catalog.py`, `external.py`,
  `loaders.py` and the files they import: `interface.py`, `lab/config.py`), `config/*.yaml`, `pyproject.toml`,
  `uv.lock`, `run.py`, `controls.py` and this plan. The run stops if any of them changes during the run.

## 12. Code to build, and its tests (TESTING.md section 7)

- **`lab/runner/keeprisk.py`** (new; not registered in `lab/runner/__init__.py`, which other studies hash):
  `basket_returns(bars, f)`, `q_path` (section 5, the switch-on decision included), `KeepRiskStream`, `ride_run`,
  `keep_risk` (the `BacktestFn`), the yardsticks (`matched_share`, `equal_calm_share`), the statistics (DD, V, the
  paired resampling, Holm, the copies and E1 over V, the labels), the measures of section 8 and the rules D1-D3.
  No existing `lab/` file is edited.
- **`research/keep-risk-steady/run.py`:** the grid, the decisions and the outputs, with buy-the-dip's start guards: the
  dirty tree; the test-window guard; the snapshot and panel hashes; the RUNLOG line before any bar; dry runs only in
  scratch folders; the pinned folders; the projection guard; stop and crash logging with every block that returned
  kept; `--time` for A1.
- **`research/keep-risk-steady/controls.py`:** A0 (section 13), synthetic only.

**Tests** (`tests/test_keeprisk.py`, `tests/test_keeprisk_run.py`, `tests/test_keeprisk_controls.py`; synthetic and
hand-built paths only, no catalog):
- **Tamper the future** (hypothesis, with cuts at Monday checks, step orders, drift orders, limit fixes and the
  switch-on close): σ, q, the targets, the orders and every result row before a cut never change when later bars
  change; the same for X and N with their target held fixed. **Touch the present:** changing close t changes σ(t) and
  x_t.
- **Hand-built paths:**
  - **q at its edges:** τ / σ exactly 0.75, 0.5 and 0.25 gives that quarter, and one ulp below gives the next one down
    (beyond the 1e-9 tolerance); σ = 0 gives q = 1; τ above every σ never steps.
  - **The switch-on decision:** at a non-Monday first close with 14 returns of history it uses σ at that close; with 13
    it holds q = 1 until the first Monday check; Kraken window 0 by hand.
  - **The band:** a coin exactly 0.25 × its target away does not order, one ulp more does; a coin with target 0 never
    orders; a drift order only at a Monday.
  - **Limit fixes:** a breach on a Thursday is fixed at that close; a breach and a step on one Monday give one order.
  - **The calendar:** Monday checks across Kraken's missing 2018-01-13 (a Saturday); the 2-day row; a decision at the
    last close is never filled.
- **Identities, bit for bit:**
  - at f = 0.50, `basket_returns` is `volsteady.basket_returns`, and after the first Monday check the q path is
    `volsteady.vol_path`'s q (crypto_share 1);
  - with an infinite band, `ride_run` is `trend.run_states` on the same in-force targets;
  - with a constant target, f = 0.50, a panel starting on a Monday with no missing close, `ride_run` is
    `portfolio.rebalance(band = 0.25 × T, every = 7)`;
  - copy u = 0 is the rule; with one s, the rotation is `trend.shifted`'s;
  - a setting that never steps gives rule = X = N.
- **Live/batch parity:** `KeepRiskStream` equals `q_path` on every close (hypothesis; Mondays, a missing close, the
  switch-on close).
- **Accounting** against an independent book of coin units and cash with each order's own target vector, to 1e-12
  (hypothesis; `test_trend.vector_book`'s arithmetic).
- **The statistics by hand:** DD around zero (not around the mean); V; the resampler equal to a hand stationary
  resampler; p_calm, p_rough and p_eq at their boundaries (a p of 500 / 10,001 holds, 501 / 10,001 fails); Holm by hand
  (in first place 125 / 10,001 = 0.012499 passes and 126 / 10,001 fails; a step-down that stops); E1's rank with
  ties against the rule (with 258 copies, 11 at or below gives 12 / 259 and holds, 12 gives 13 / 259 and fails);
  each copy against its own mix (a test where the rule's raw DD rank and its V rank disagree); every label at its
  boundary.
- **The rules:** D1-D3 on hand-made tables, every boundary exact: 25 of 49 calmer windows passes, 24 fails; a median
  c_X of exactly 2.0 passes, one ulp more fails; one mix failing makes w unusable; CALMER first, then the larger w;
  MISSING propagation; D2's labels and their order; the boom windows by hand (without 2017: k = 12..48; without 2017
  and 2020: k = 12 and 48, so MISSING); the leave-one-year-out rows.
- **The run script:** the start guards and data stops (buy-the-dip's list); the counts by hand; every reported number
  recomputed from the runs tables by an independent statement of sections 8-10 in the test; every 9th run rerun from
  scratch; `runs.csv` one row per window run; workers 1 and 2 give byte-identical outputs.
- **The A0 script:** its panels by hand, its alarm rules at their boundaries, its seeds disjoint from section 2's.
- **Hand breaks** by the builder (about 30), each failing a test, recorded in the bug log: among them q rounded
  instead of floored, the look-back off by one row, ddof 0, √252, the switch-on decision skipped, the band judged at
  the next open, the band absolute instead of relative, X matched on N's share, the copies compared on raw DD instead
  of V, the lead guard removed, Holm replaced by 5% per setting, ties in E1 given to the rule, p_eq at ln 0.8, D1's
  ranking by the smaller w, a boom check keeping overlapping windows.

## 13. Protocol, stop rules and amendments

**Order of work:**
1. Commit this plan.
2. `risk-officer` confirms section 14 (config only). The owner answers section 17, or the pinned answers stand. The
   build may run at the same time.
3. Build the code and tests (TESTING.md bug rows from the next free number).
4. The three tiers on the build's commit: the full tier with 100% branch coverage, the deep profile, and ruff with the
   dashboard.
5. **A1** times run 0 and A0 on synthetic bars; both projection guards apply.
6. **A0**, the synthetic pre-check (below). Its record goes into section 13's amendment list.
7. Run 0 (all pools) on the train window, then RESULTS.md and one audit.

**Stop rules** (buy-the-dip section 12's, 1-7, with 8 and 9 added):
1. The three tiers must pass on the run's commit, with a clean tree.
2. The hashes and the row counts.
3. A bar after 2023-01-01 stops the run, and nothing from it is used.
4. A failed run is logged and the grid goes on; its pools give MISSING.
5. A consistency stop is a bug: a regression test, a dated amendment and a full rerun.
6. At most 2 amendment runs, and a crash is rerun, never resumed.
7. The projection guard: run 0 at 240 CPU-minutes, A0 at 300 (the owner's limit, 2026-11-25).
8. **A real run 0 refuses to start** unless section 13 holds exactly one A1 line and exactly one A0 line, and the A0
   line says "no alarm" or names an owner decision on file under `reports/director/` (trend-steady's `prior_amendments`).
9. **A0's alarms stop run 0** (below).

**A1 (timing).** `run.py --time` on synthetic bars (`trend.garch_panel(399999)`, the busiest cell: w = 8%, s = 0.60,
f = 0.50) times a full-span rule run, a copy with its mix, a window run of each kind and one resampling of 10,000, each
with every check, and projects run 0 (section 7's counts) and A0 (below). Run 0 repeats the timing at its start.

**A0 (the synthetic pre-check; at most 300 CPU-minutes).** It runs the decisive machinery of sections 9-10 on made-up
markets, at one mix (s = 0.50, f = 0.50), the four w and 14 returns, with 10,000 resamples and every guarded copy.
D1 is applied with that one mix ("at all 8 mixes" reads "at that mix"). Every panel is placed on Kraken's train
grid (`trend.train_grid()`, 2190 closes); the regime and shuffled panels' bars are relabelled with those closes in
order. The random streams are disjoint: `garch_panel(j)` draws from `default_rng(10000 + j)`, so PG uses streams
210000-210099, NC's prices 260000-260099 and NC's schedules 270000-270099; PR, NW and NS use 220000-220099,
230000-230099, 240000-240099 and 241000-241099.

| Set | Panels (100 each; seeds pinned, disjoint from section 2's) | Role |
|---|---|---|
| **PG** | `trend.garch_panel(j)`, j = 200000..200099 (volatility clusters, constant drift) | Positive: power |
| **PR** | `synthetic_market(2190, seed=220000 + j, start="2017-01-02")` (regimes and clustering) | Positive: power |
| **NW** | `trend.random_walk_panel(230000 + j)` (iid, no clustering) | Negative |
| **NS** | `shuffled_market(synthetic_market(2190, seed=240000 + j, ...), seed=241000 + j)` (clustering destroyed) | Negative |
| **NC** | prices `trend.garch_panel(250000 + j)`, with the q schedule computed on `trend.garch_panel(260000 + j)` at the same checks: steps as persistent as real ones, with no information | Negative: E1's own null |

**What A0 measures:**
- **False CALMER:** on NW, NS and NC, the panels with any w labelled CALMER THAN HOLDING LESS.
- **False default:** on NW, NS and NC, the panels where D1 names a default.
- **E1's size:** on NC, the panels where E1 holds, per w.
- **The resampling's honesty at the boundary** (no new runs): on the sets whose panels share one truth (PG, NW, NC),
  with V̄ the leave-one-out mean of V across the set at each w, the rate of (1 + #{V* ≥ V̄}) / 10,001 < 0.05 (the
  error of a "calmer" claim when the truth is exactly "no cut") and of (1 + #{V* ≤ V̄}) / 10,001 < 0.05 (the error of
  "rougher" at "no difference", and of "no noticeable difference" at a true cut of exactly 10%), pooled over the four
  w (400 tests per set and tail). PR and NS panels each have their own truth, so they are left out of this check.
- **Power** (a description): on PG and PR, the panels with E1, with RISK-X passing Holm, with CALMER at any w, with a
  default (and which w), and with each label.

**Alarms** (pinned; each stops run 0):
- **A0-1:** false CALMER on more than 10 of 100 panels in NW, NS or NC.
- **A0-2:** a false default on more than 10 of 100 panels in NW, NS or NC.
- **A0-3:** E1 holds on more than 10 of 100 NC panels at any w.
- **A0-4:** either tail's boundary rate above 7.5% (more than 30 of 400) in PG, NW or NC.

With 100 panels, "more than 10" stops about 1% of the time when a rate is really 5%, and about 42% of the time when it
is 10%. It cannot prove a rate is 5%. The pooled boundary count mixes four correlated settings, so its spread is wider
than a count of 400 independent tests. The boundary check needs no new runs: moving V by a constant moves every
resample with it, so each error rate at a boundary is one of the two counts above.

**If an alarm fires:** run 0 does not start, and the lead tells the owner with A0's numbers. No market bar has been read
for this study, so a fix is allowed, as a dated amendment that names A0 as a prior look. A0 then reruns on the second
seed range (all seeds above + 100000). A second alarm stops the study until the owner decides.

**Low power does not stop run 0:** the descriptions, D1 and the equivalence reading stay informative. If CALMER is
found on fewer than 10 of 100 panels in both PG and PR, RESULTS prints next to every CAN'T TELL: "On made-up markets
built to contain the effect, this test confirmed it on only {N} of 100." The owner sees A0's numbers before run 0.

**A0's cost:** per panel 4 × (3 + 2 × 258) = 2,076 full-span runs, 4 × 49 × 3 = 588 window runs and one resampling:
about 20 CPU-seconds from the scratch timings, about 160-170 CPU-minutes for 500 panels. If A1's projection exceeds 300
CPU-minutes, every set shrinks to 80 panels, pinned now (alarms: more than 8 of 80; pooled more than 24 of 320).

**No validate look is planned.** The study claims no return edge and picks a tool's default. If D1 names a default
labelled CALMER THAN HOLDING LESS at every mix, the lead may write a separate dated plan for one reject-only look at
Kraken validate (as protect-gains' V1), before any validate bar is read for this study. It would disclose P4's V1, P9's
look and that validate is known to be a rising market. Otherwise there is no look.

**Amendments:**
- **Amendment M1** (2026-11-25, written after the build, its code review and the fixes, TESTING.md #75-#77; before
  A1, A0 and run 0; no market bar read for this study). It changes no threshold, gate, grid, count or decision rule.
  It pins where the plan's words leave room:
  1. **x, the matched share (section 6),** is the correctly rounded mean of the in-force share over rows 0 .. n-2
     (the exact sum, one rounding), not `math.fsum(share[0 .. n-2]) / (n - 1)`, which rounds twice. The two differ
     only in the last bit, but for s = 0.40 on a 729-row window the formula gives 0.4 plus one ulp. A setting that
     never steps would then have X differ from N, and a V_X of about 1e-16 of either sign that D1's rule 1 would
     count as calmer about half the time. Section 12's identity (rule = X = N) and section 9.4's "X is N and V = 0"
     need the exact mean (TESTING.md #75).
  2. **Stop rule 8's A0 record:** "says no alarm" reads as the exact phrase `A0 alarms: none`, which `controls.py`
     prints as its last line when no alarm fires (it prints `A0 alarms: A0-<n>, ...` when one does). A bare
     "no alarm" is not a record. A line holding "to be written" (the placeholders below) is never a record. Only the
     A0 item is read, with its wrapped lines, never the plan's other text.
     - **Stop rule 9:** an A0 item that reports an alarm is refused unless it names an owner decision on file under
       `reports/director/`, whatever else it says. It reports one if it holds "fired" or names an alarm (A0-1 ..
       A0-4) as raised.
     - The full reading is `run.py`'s `INTERPRETATIONS["prior_amendments"]` (TESTING.md #77).
  3. **A0 measures the guarded copies and their mixes by DD only,** without the fee check. A0 checks the
     statistics, which read DD alone. Run 0 checks the accounting on every run (section 11). With run 0's full
     measures, A0's projection on this machine was 308 CPU-minutes, above stop rule 7's 300 (TESTING.md #76).
  4. **A0's resampling** is run 0's: one index set from `default_rng(0)` over the train grid's 2189 return rows,
     shared by every panel. Section 13's disjoint streams are the panels' market streams.
  5. **A0's tests** are in `tests/test_keeprisk_run.py`, not a third file `tests/test_keeprisk_controls.py`
     (section 12).
  6. **The other readings** are in `lab/runner/keeprisk.py`'s `READINGS_PINNED`, `run.py`'s `INTERPRETATIONS` and
     `controls.py`'s `READINGS`. They are recorded in each start record and covered by the config hash. Among them:
     - **Section 7's pools as six families:** Kraken 1x, Binance 1x and Kraken 2x at 14 returns and 5,000 USD;
       Kraken 1x at 7 and 28 returns, with copies and labels; and Kraken 1x at 500 USD, whose full span gets V and
       RISK-X's p-values only, with no copies and no label.
     - **The executor's Monday checks** include every Monday of the run, the rows before panel row 14 among them.
     - **An X_eq whose V is MISSING** is logged as not run and counted.
     - **Copy 0** is run in every full span as an uncounted check.
- **Amendment M2** (2026-11-25, written after A1, before A0 and run 0; no market bar read for this study). **Stop rule
  7's A0 limit is 600 CPU-minutes, not 300.** The owner raised it on 2026-11-25
  ([the decision](../../reports/director/2026-11-25-owner-answer-keeprisk-a0-budget.md)) after A1 (below) projected
  A0 at 405-481 CPU-minutes with 100 panels a set and 324-385 with 80, both above 300, so A0 could not start at
  either size. The A0 cost estimate above (about 20 CPU-seconds a panel) was low: A1's three projections give about 49-58. The
  fallback rule keeps its form at the new limit: 100 panels a set when the projection at 100 is at most 600, else 80
  when the projection at 80 is, else A0 refuses. Nothing else changes: the five sets, their seeds and sizes, the
  alarms and their limits, the resampling, the measures, run 0's limit of 240 CPU-minutes, the gates, the grid and
  every decision rule. `run.py`'s `A0_CPU_MINUTES_MAX` is 600.
- **A1** (2026-11-25, on commit `6f91f46` after the three tiers passed on it with a clean tree; synthetic bars only,
  `run.py --time`, three timings on an idle 4-core machine). Run 0: 38.7, 27.3 and 31.5 CPU-minutes, under its limit
  of 240. A0: 480.8, 448.2 and 404.9 CPU-minutes at 100 panels a set, and 384.7, 358.6 and 324.0 at 80, above the
  then limit of 300 (amendment M2 raises it to 600). The first timing's medians (3 repetitions): a full-span rule run
  with its checks and measures 37.6 ms, a guarded copy and its mix with their measures 36.2 ms, A0's copy and mix by
  DD only 43.6 ms, a window run 18.7 ms, one index set of 10,000 0.72 s and one RISK-X 0.33 s; its counts are
  section 7's (768 full-span runs, 40,192 copy pairs, 36,608 window runs, 10 index sets, 448 resamplings). Run 0 and
  A0 each re-time at their start. The timings are noisy: A0's DD-only pair, which does less work than the full pair,
  timed slower in all three, and it sets about 80% of A0's projected cost.
- **A0** (to be written after A1; synthetic only; it says "no alarm" or names the owner's decision).

## 14. Allowed range (`risk-officer` confirmed 2026-11-25, before run 0, config only)

The app offers these values only:
- w, the swing level: 8%, 10%, 12% or 15% of the mix's typical weekly move;
- on mixes with s ∈ {30%, 40%, 50%, 60%} crypto and f ∈ {50%, 75%} BTC. Any other mix is untested, and **the app does
  not offer the tool on it** (`risk-officer`, 2026-11-25; not "offered and labelled untested"). While the tool is on,
  the app does not let the user change to an untested mix; they switch the tool off first.

**Inside the Steady limits.** Every target of the tool is at most the user's mix, so every target of every order
passes `check_targets` with h = 0.02: at most 60% crypto, each coin at most 45%, cash at least 40%. Between checks,
prices can carry a coin up; a limit fix is ordered at the close that breaks a limit and fills at the next open
(section 5.7).

**What `risk-officer` checked (2026-11-25; config only, no market data, no catalog loader called, nothing under
`data/` or `results/` read).** A scratch script (`krs/risk/check_grid.py` in the session scratchpad, not kept):
- `portfolio.risk_limits("steady")` on `config/risk_levels.yaml` (SHA-256 `d3f58253dfc2dbbe…`): coins BTC, ETH, USDC;
  min_cash 0.20; max_coin 0.60; budget 0.35 (raw 35). The hold-this-mix key `hold_mix_max_rebalances_per_30d` is not
  among the values it returns, so the run cannot read it as one of its limits.
- All 40 targets of the grid (s 0.30/0.40/0.50/0.60 × f 0.50/0.75 × q 1, 0.75, 0.5, 0.25, 0), built through
  `trend.in_force` and equal to (s q f, s q (1 − f)) exactly, pass `check_targets` with h = 0.02. The smallest margin
  is 0.13 (s 0.60, f 0.75, q 1: BTC 0.45 against 0.58; cash 0.40 against 0.22).
- Every crypto share from 0 to 0.60 (step 0.001) passes at both f, so X's target does too. The largest share that
  passes with h is 0.78 at f 0.50 and 0.7733 at f 0.75. X_eq (a description, section 6) can exceed s when the rule is
  rougher than X (V > 0); its λ clip then keeps it inside the limits. It is never offered to users.
- τ is 0.5777, 0.7221, 0.8665 and 1.0832 for the four w, as section 5.3 says.
- A limit fix from the busiest targets (60% crypto, 75% BTC) needs BTC alone up ×1.83, or both coins up ×2.67, with
  no Monday order in between. The Monday drift trigger for BTC (above 56.25%) comes before the 60% cap.

The plan's numbers stand. No number in this section was wrong. Two wording notes below are corrected (it "only ever
holds less crypto", and the one-tool rule).

**`risk-officer`'s decisions on the open risk points (2026-11-25):**
- **Mixes:** the 8 tested mixes only (above).
- **Trades: not under the hold-this-mix limit.** `config/risk_levels.yaml` scopes `hold_mix_max_rebalances_per_30d:
  2` to "the self-directed hold-this-mix tool only". This tool is a separate tool, and leaving that limit off it
  loosens nothing approved. Its own cap is built into the rule: at most one step or drift order per Monday, so at most
  5 in any 30 days, plus limit fixes at any close (exempt, as in the hold-this-mix limit). Section 17 Q2's pinned
  answer stands. Whether up to 5 weekly orders in a wild month fits Steady's "a few trades a month" is the owner's
  call, because that phrase is product wording and not a config limit. The card's "up to {t_max} in a busy month"
  counts every order after the first buy, limit fixes included. A cap would be a rule amendment before run 0 and an
  owner-approved config entry (hard rule 10).
- **One tool per wallet:** the app allows exactly one of "keep my risk steady", "hold this mix", buy-the-dip and
  protect-gains on a wallet. Combinations are not offered (not "labelled untested"). This tool keeps the mix itself,
  so it takes the place of "hold this mix" on that wallet.
- **The 35% budget is shown, not enforced,** under the owner's tool rules (2026-11-25). This applies to self-directed
  tools only. A managed strategy still needs it as a gate.

**App wording notes (confirmed 2026-11-25, with corrections):**
- **w is a crypto number, the wallet follows.** w is the typical weekly move of the user's BTC/ETH mix. The wallet's
  weekly swing, measured over the last two weeks, stays under about s × w at each check, but not always: a crash can
  beat it for a week (the over-cap weeks of D3 say how often).
- **It never aims for more crypto than the user's mix** (corrected from "only ever holds less"). At the full step it
  holds the mix. Between Mondays prices can carry a coin up to a quarter above its target, and higher only until a
  limit fix. It does not try to earn more.
- **It sells in wild weeks and buys back as things calm down**, a quarter of the mix's crypto at a time. After a crash
  it can buy back after part of the rebound (the missed-rebound measure).
- **It trades back to its level** when a coin drifts more than a quarter of its target away, at a Monday.
- **It is one tool per wallet** (corrected). With "hold this mix", buy-the-dip or protect-gains on the same wallet (not
  simulated), their trades would fight, so the app does not allow it.
- **The 35% budget is shown, not enforced** (D3).

**Production must ship what was tested** (the app enforces these): the 14-return look-back of the user's own split;
the Monday 00:00 UTC check and the switch-on decision; quarter steps with the floor of section 5.4; the relative band
0.25 at Mondays; limit fixes at any daily close; one order per close, filled at the next open; BTC, ETH and USDC only.

**Matching production controls** (for the app to enforce; `risk-officer` cannot set them):
- **Trade router:** spot swaps between BTC or ETH and USDC only (no other coin, no leverage, no short); at most one
  order per daily close for this tool, filled at the next open; the tool is offered only on the 8 tested mixes and the
  4 w values.
- **Auto-trading permission:** coins BTC, ETH and USDC. No order may target more than the user's mix (s f in BTC,
  s (1 − f) in ETH). Holdings stay within Steady's limits as read from `config/risk_levels.yaml` at the time (each coin
  at most 60%, cash at least 20%), restored by the limit fix. One tool per wallet.

**No owner-approved limit is loosened.** The tool cannot aim above the user's own mix. Steady's limits and its 35%
budget are read from the file, unchanged, and the hold-this-mix limit keeps its scope. Whether Steady's "a few trades a
month" should cap this tool is the owner's call (section 17 Q2; the pinned answer stands until then).

## 15. Outputs

- **RESULTS.md**, whatever the outcome: the plain-words summary; the default with its label; D3's description; the 32
  cards; the full table per setting and mix; A0's power next to every CAN'T TELL; every deviation.
- **The committed record:** `runs.csv` (one row per window run: pool, w, s, f, k, kind, DD, V_X, V_N, x, x_eq, F, the
  worst week, CAGR, c_N, c_X, fees, trades, the time stepped back; no Sharpe column), `spans.csv` (one row per cell and
  pool: V, its interval, p_calm and its Holm outcome, p_rough, p_eq, E1's rank p, the label, the flags),
  `RUNLOG.jsonl` and `decision.json`.
- **Not committed:** `results/keep-risk-steady/` (git-ignored), which holds the full tables (every copy's V_u, the
  resampling summaries, every run's measures).

## 16. Known weaknesses

- **Not fresh data,** and no validate look. P8 already showed that volatility clusters in these very bars, so E1
  mostly re-confirms a known fact. The new evidence is RISK-X and the equivalence reading.
- **One short history.** The full span is one six-year path, and its down days are dominated by 2018, March 2020 and
  2022. The resampling handles noise inside that path, not a different future.
- **Low power for the calmer claim.** On made-up markets the cut against the same average crypto was small (about 3-11%)
  and noisy (appendix A). A0 measures the power; a CAN'T TELL is the likely outcome even if the effect is real.
- **Overlapping windows:** the 49 two-year windows share most of their days; "calmer in 41 of 49 periods" is not 41
  separate tests, and the card says so.
- **The boom check without the two best years is likely MISSING.** P7 shows BTC's two best bar-years on Kraken are 2017
  and 2020, which leaves windows 12 and 48 only (fewer than 12). The full-span labels without them are still reported.
  This expectation comes from a prior look.
- **Hindsight yardsticks:** X and X_eq use the period's own average.
- **The resampling's honesty** is measured only on made-up markets (A0). On heavy-tailed markets with changing regimes,
  appendix A found the resampling's spread smaller than the spread across markets.
- **Holm covers the four settings within one mix,** not the eight mixes, the checks or other studies.
- **One wallet size** for the decisions (5,000 USD; 500 USD is a description); no deposits; weekly checks only; one
  look-back offered.
- **The tool only steps down from the user's mix.** It cannot hold more crypto than the mix in calm times, so it never
  aims at the same average risk as the mix.
- **The scouting engine and placeholder costs.**

## 17. Owner questions (each has a pinned answer that stands unless the owner changes it before run 0)

1. **Should the app offer the tool with a default that is not confirmed calmer?** D1 can name a default labelled CAN'T
   TELL ("calmer in most periods, but we can't rule out luck"). *Pinned:* yes, with that honest label. The other choice
   is to offer a default only when it is labelled CALMER THAN HOLDING LESS.
2. **How does it sit next to "hold this mix" and Steady's "a few trades a month"?** The tool holds a mix itself, with
   weekly checks. In made-up markets it traded about 4-25 times a year, and it can trade up to 5 times in 30 days in a
   wild market. The limit of 2 rebalances in any 30 days is for "hold this mix" only (`config/risk_levels.yaml`). If
   the tool were a switch inside "hold this mix", that limit would hold back its weekly steps. *Pinned:* a separate
   tool with its own weekly rhythm, one tool per wallet, no cap beyond the weekly check; the study reports the busiest
   30 days. A cap would be an amendment before run 0.
3. **Is a 10% smaller typical down day the smallest difference worth telling users about (δ)?** And is 2 points a year
   the largest cost against holding less that a default may have (m)? Both come from the 2026-11-24 design note.
   *Pinned:* δ = 10%, m = 2 points a year. δ decides whether a setting reads NO NOTICEABLE DIFFERENCE, which also
   decides whether D1 can name it.

## 18. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| P1-P13 | before this plan | section 2 | Prior looks, disclosed |
| Plan | 2026-11-25 | this plan's author | **No market data**: no catalog loader called, nothing under `data/` or `results/` read. Read: P12's list. Accidental: P13. Synthetic experiments: appendix A (about 16 CPU-minutes) |
| Other proposals | 2026-11-25 | two more proposal authors | **No market data.** The statistics-first and reuse-first proposals (not adopted; the reuse-first one was stopped unfinished). The statistics-first author ran about 18 CPU-minutes of synthetic experiments (scratch only) |
| Range check | 2026-11-25 | `risk-officer` | **No market data**: no catalog loader called, nothing under `data/` or `results/` read. Read: this plan, the owner record of 2026-11-25, `config/risk_levels.yaml` through `portfolio.risk_limits`, the code of `portfolio.risk_limits`, `_breach_test`, `check_targets` and `trend.in_force`. A config-only scratch check of section 14 (under a second). Confirmed section 14 |

**Validate-window looks used for keep-risk-steady: 0.**

## Appendix A. The synthetic sizing behind this plan (scratch, decides nothing)

**What was run.** A scratch prototype of sections 5-9 (`krs_lib.py`, `exp1.py`, `exp2.py`, `an1.py`-`an3.py` in the
session scratchpad, `krs/prop-user/`; not kept), on `portfolio._simulate` with `Costs.from_yaml(capital_usd=5000)`, at
s = 0.50 and f = 0.50. It differs from the pinned rule in one detail: at a window's first close it used the previous
Monday's q instead of the switch-on decision. 80 panels: 20 each of GARCH (`trend.garch_panel`, j = 70000-70019),
regime (`synthetic_market`, 71000-71019), iid walks (`trend.random_walk_panel`, 72000-72019) and shuffled regime
markets (73000-73019, shuffled with 73500-73519). Experiment 1: look-backs 7, 14, 28 and w 8-20%, 1,000 resamples.
Experiment 2: 14 returns, w 8-15%, one joint resampling of 2,000 per panel, every guarded copy on 8 panels per set, the
49 windows. About 16 CPU-minutes in all.

**Speed:** about 8 ms a full-span run (2190 rows), 3 ms a window run, 0.06 s for 1,000 resamples.

**Results at 14 returns** (counts of 20 panels unless marked; E1 of 8):

| Set | w | median V_X | resampling sd | RISK-X at 5% | RISK-X, Holm | E1 | p_eq < 0.05 | calmer windows (median of 49) | orders a year |
|---|---|---|---|---|---|---|---|---|---|
| GARCH | 8% | −0.056 | 0.052 | 2 | 0 | 8 | 3 | 41 | 22.9 |
| GARCH | 10% | −0.055 | 0.042 | 3 | 1 | 8 | 7 | 43.5 | 16.3 |
| GARCH | 12% | −0.037 | 0.034 | 4 | 1 | 7 | 11 | 43 | 11.4 |
| GARCH | 15% | −0.029 | 0.023 | 7 | 0 | 8 | 18 | 40 | 7.3 |
| regime | 8% | −0.110 | 0.060 | 13 | 4 | 8 | 3 | 48 | 15.1 |
| regime | 10% | −0.086 | 0.047 | 9 | 4 | 8 | 4 | 46.5 | 10.6 |
| regime | 12% | −0.066 | 0.039 | 8 | 2 | 8 | 8 | 44.5 | 7.4 |
| regime | 15% | −0.037 | 0.025 | 5 | 2 | 8 | 12 | 36.5 | 4.9 |
| iid walk | 8% | +0.037 | 0.022 | 0 | 0 | 0 | 20 | 1 | 24.8 |
| iid walk | 10% | +0.024 | 0.017 | 0 | 0 | 0 | 20 | 4.5 | 25.4 |
| iid walk | 12% | +0.010 | 0.013 | 0 | 0 | 0 | 20 | 11.5 | 17.9 |
| iid walk | 15% | +0.001 | 0.008 | 0 | 0 | 0 | 20 | 17.5 | 7.3 |
| shuffled | 8% | +0.018 | 0.020 | 0 | 0 | 1 | 20 | 13.5 | 19.7 |
| shuffled | 10% | +0.010 | 0.015 | 0 | 0 | 0 | 20 | 13 | 11.0 |
| shuffled | 12% | +0.008 | 0.013 | 1 | 1 | 0 | 20 | 17 | 6.4 |
| shuffled | 15% | 0.000 | 0.010 | 1 | 1 | 0 | 20 | 16 | 4.1 |

**What this shaped:**
- **The cut is small and E1 is strong.** Where volatility clusters, the steps were clearly better timed than shifted
  copies, but the net cut against the same average crypto was only 3-11%, with a resampling spread of 0.02-0.06. So E1
  alone would overstate what a user gets; the label needs RISK-X. (E1 held on 63 of the 64 positive panel-settings it
  was run on, mean rank p 0.004-0.018.)
- **Without clustering the rule is rougher**, by 0-4% (Jensen's penalty), and E1 almost never held (1 of 64 null
  panel-settings). That is why X is the fair, demanding yardstick.
- **Multiplicity matters.** Across 8 settings (look-backs 14 and 28 × four w), "some setting calmer at 5%" happened on 4
  of 20 shuffled panels; with Bonferroni on 1. Holm over four settings costs power (GARCH 0-1, regime 2-4 of 20) but
  keeps the claim honest.
- **The windows separate positive from null clearly** (calmer in a median 36-48 of 49 periods on positive panels,
  1-18 on null panels), which is why D1 uses them, while the claim rests on the full span.
- **D1 rehearsed** (one mix, no cost rule, E1 on 8 panels per set only): a default on 16 of 20 GARCH and 17 of 20
  regime panels, almost always labelled CAN'T TELL (CALMER on 1 and 3-5); on 0 of 20 iid walks and 1 of 20 shuffled
  panels. With "gentlest first" the default spread over w = 8-15% (mostly 10-15%); ranking by the number of calmer
  periods instead picked 8% or 10% in 31 of 33 cases.
- **Trades and fees:** at 14 returns about 4-25 orders a year, fees about 0.1-0.8% of the wallet a year at 5,000 USD.
  Against the full mix the tool gave up about 1-9 points a year on GARCH markets, whose constant drift makes stepping
  back costly; about 1-2 on regime markets.
- **The resampling's spread** was 0.7-0.9 times the spread across panels on GARCH and iid walks (cautious), but above
  1 on regime and shuffled panels, whose panels each have their own truth. That is why A0's boundary check uses only
  sets with one truth, and why section 16 lists it.

# trend-steady: pre-registration (DRAFT)

**Status: draft, not committed, not frozen.** Assembled 2026-11-21 in a scratch folder from four independent plan
sketches (appendix A), **before any trend-following result exists**. Nothing was written in `/home/user/osprey`.
Audited the same day by an independent `backtest-auditor` pass; every fix is listed in the Critique log at the
end, and the pre-audit text is kept as `audit/PLAN_DRAFT.before_audit.md`. Still a draft.
Repo HEAD at drafting `652eefc` (branch `claude/tender-brown-g86h44`); the uncommitted `TESTING.md` edit and the
untracked `lab/runner/holdmix.py` and `tests/test_holdmix.py` there belong to the hold-mix-cap workflow, not to this
draft.

- Data snapshot `1746a21b75683e76`, bars content hash `08f5ca2c…`, as recorded in rebalance-steady's DATA.md and
  RESULTS.md.
- Risk level **Steady**: coins BTC and ETH, with USDC as cash.
- **Branch F (fixed settings)** unless the owner approves a Steady drawdown budget in writing before the freeze
  (section 8, owner question 1).

Next steps:
1. `quant-researcher` turns this draft into `research/trend-steady/PLAN.md` after hold-mix-cap's run is committed.
2. `backtest-auditor` and `risk-officer` review it.
3. It is committed and hashed **before anyone working on trend-steady reads hold-mix-cap's RESULTS.md** (section 15,
   stop rule 16).

> **SCOUTING ONLY.** Every number this study produces comes from the lab's reference portfolio engine
> (`lab/runner/portfolio.py`, driven by a new `lab/runner/trend.py`), not from NautilusTrader (AGENTS.md hard rule
> 3; the Nautilus runner is on hold). It uses the **placeholder** costs of `config/costs.yaml`, and Kraken and
> Binance candles stand in for Base prices. **This study cannot make anything ready for paper.** Its best possible
> headline is "CANDIDATE FOR AUDIT", which means only "worth a Nautilus build". While the Steady budget is TBD, the
> best possible headline is "EDGE, NOT A CANDIDATE". Nothing goes into `reports/<strategy>/`, `strategies/` or
> `exports/`.

The only real-data numbers in this file are:
- coverage counts and close dates from rebalance-steady's DATA.md;
- figures quoted from files the desk has already published (listed as prior looks in section 2).

The fold dates, check closes and row numbers come from `lab.validation.splits.walk_forward` run on a date grid
rebuilt from DATA.md's counts, with no prices (script in appendix B). No catalog bar was read. The feasibility checks
read `config/risk_levels.yaml` only. Timings are from synthetic data.

## In plain words

Steady's product plan lists "trend following that moves to cash in downtrends" as its second strategy idea
(`docs/app/product.md`). The owner said it "might be worth testing".

**The rule.** Once a week, at the Monday 00:00 UTC daily close, it looks at BTC and ETH separately:
- If a coin's price is more than a small buffer δ above its average of the last L days, the coin is in an uptrend
  and the book holds 25% in it.
- If the price is more than δ below that average, the coin is in a downtrend and its 25% goes to USDC.
- In between, nothing changes.

So the book is 25% BTC, 25% ETH and 50% USDC when both coins trend up, and 100% USDC when both trend down. The Steady
limits (at least 20% cash, at most 60% in any one coin) hold at every daily close.

**What the study asks.** Is the trend timing better than chance after costs? Specifically, does it beat:
- the same in/out schedule shifted to other dates (a schedule moved less than a year earlier would partly see its
  own future, so those shifts are left out);
- holding the same mix all the time;
- holding the same average amount of crypto, judged on falls;
- the lab's benchmarks?

It also asks whether the result still holds without any single year, and without BTC's best years (the owner's rule
of 2026-11-21). "No edge" is an acceptable answer.

**What we already know.** The first Steady study found three things:
- rebalancing timing added nothing;
- the crypto share drove return and drawdown;
- frequent trading mostly paid fees.

This plan is built around them:
- the crypto share is fixed, not tuned;
- the rule trades rarely (weekly checks, a buffer, no rebalancing inside a trend);
- the luck controls test the timing itself.

The years 2018 and 2022 were long bear markets, and everyone writing this knows it. So the plan leans on tests that
hindsight cannot pass for free: shifted timing, leave-one-year-out, and the boom-year check.

## 1. Question and hypothesis

**Question.** A Steady book holds BTC, ETH and USDC. It holds each coin at its share while that coin is in an
uptrend, and moves that coin's share to USDC in a downtrend. Does the trend timing earn a better risk-adjusted
return after costs, on the walk-forward out-of-sample span 2018-2022, than each of these?
- (a) the rule's own in/out schedule placed at other dates;
- (b) the same mix held always in;
- (c) the lab benchmarks (buy-and-hold BTC; 50/50 BTC/USDC every 30 days)?

Does it cut falls more than holding the same average amount of crypto? And does it pass the AGENTS.md gates?

**Hypothesis.** Crypto prices show time-series momentum at horizons of weeks to months, and their deepest losses come
in long bear markets. A rule that is out of a coin while its price sits clearly below its moving average misses much
of a long decline and keeps much of a long rise. It pays for this with lag and whipsaw in choppy and V-shaped
markets.

Why it might persist:
- slow diffusion of information and attention;
- herding and extrapolation;
- leverage-driven liquidations that take weeks;
- no fundamental anchor for the price.

**What the literature says** (full list and links in `sketch_evidence.md` section 12, read as abstracts or secondary
summaries where marked there):
- **Time-series momentum.** Moskowitz, Ooi & Pedersen (2012) and Hurst, Ooi & Pedersen (2017) find it in futures.
  Levine & Pedersen (2016) show that price-versus-average rules and time-series momentum are one family, so this
  study tests **one signal family**.
- **Crypto.** Liu & Tsyvinski (2021) find momentum at daily and weekly horizons. Detzel et al. (2021) find that
  price-to-average ratios predict BTC out of sample. Both overlap our train window.
- **Sceptical findings.**
  - Huang et al. (2020) find weak asset-by-asset evidence.
  - Kim, Tse & Wald (2016) find unscaled trend signals close to buy-and-hold.
  - Zakamulin finds the gains concentrated in a few severe bear markets.
  - Bajgrowicz & Scaillet (2012) find no value after multiple testing and costs.
  - Han, Kang & Ryu find that costs erase many crypto momentum results.
- **Whipsaw.** Clare et al. (2013) find whipsaw is the main cost of trend rules, which is why this rule has a buffer
  and weekly checks.
- **What this means.** The prior chance of a robust Sharpe edge is modest. A drawdown benefit concentrated in bear
  years is likely. Hence the controls below: an exposure-matched null, a leave-one-year-out test, a power floor, and
  every trial counted.

**This is wrong if** (section 11) either of these fails on 2018-2022 after costs:
- **E1:** the rule's own schedule beats the same schedule shifted to other dates (same time in market, same spell
  lengths, the same switches up to one splice, the same BTC/ETH co-timing; shifts that move the schedule 1-52
  weeks earlier are excluded because they read the rule's own future, section 9);
- **E2:** the rule's Sharpe is significantly above the same mix held always in.

**Expectations, written now so that surprises are visible.** These come from general knowledge of the price history
(prior look K1); they are not evidence and decide nothing.
- The rule is out of both coins for most of 2018 and 2022, so folds 0 and 4 should favour it strongly.
- 2020 and 2021 should favour always-in, because of the lag after the March 2020 crash and whipsaw around the 2021
  tops.
- 2019 is mixed.
- Costs should matter little, because there are few switches.
- G8 should fail, because a long-or-cash rule makes its profit in bull months.
- G6 is MISSING while the budget is TBD.

## 2. Prior looks (disclosure)

| # | What was seen | Bearing on this study |
|---|---|---|
| K1 | **General knowledge** of the public price history: the 2017 bubble, the 2018 bear market, March 2020, the 2020-21 rise and its tops, the 2022 bear market, the 2023-24 recovery. The authors' training data run to about mid-2026, so their general knowledge also covers the broad course of the **test window**. The public claim that 200-day and time-series-momentum rules side-stepped crypto bear markets is widely repeated | The dominant prior look, and it cannot be undone. **Strategy-level selection:** trend following was proposed partly because it is known to have worked in 2018 and 2022, and DSR cannot count that. So G1, G3 and G7 are weak evidence; E1, E2, E6 and E7 carry the question. Even the test window is not fresh to the authors' priors; only paper trading after their knowledge cutoff is truly unseen |
| K2 | `research/rebalance-steady/RESULTS.md`, read by this draft's author (lines 1-140) and quoted at length by all four sketches. It includes buy-and-hold BTC over 2019-2022 (+318.5%, max drawdown −77.4%, Sharpe 0.864, worst day −38.94% on the bar of 2020-03-12); per-fold buy-and-hold BTC Sharpes 1.223, 2.305, 0.961 and −1.336 (2019-2022); 50/50 monthly Sharpe 0.859, −49.5%; static mixes near 0.95-1.03; the limit-only mix B5 at 0.959 and 1.113; and the in-sample s-profile (drawdown grows steeply with the crypto share). Via the sketches: **a bull/bear/sideways label for every month of 2019-2022** (19 bull, 12 bear, 17 sideways) | A coarse map of the trend structure of 4 of this study's 5 out-of-sample years. It is the strongest look at our own data. The search box (section 5) comes from the literature and common practice, not from these labels, but nobody can unknow them |
| K3 | rebalance-steady `PLAN.md` (in full), `DATA.md` (via its counts), `RISK.md` (via the sketches' quotes) and `AUDIT.md` (finding N6 and its line 133 only) | Format, limits readings, fold layout and row counts. N6 ("S and its nulls start each block in different states") shaped the common start state (section 7) |
| K4 | `research/dip-timing/RESULTS.md` and `PLAN.md`, via the sketches' quotes. `ma_dist_100` (distance from the 100-day average) was one input of a dip-quality model, evaluated on train and at the dip study's single validate look D1. Validate is described as a **bull market** (BTC+ETH buy-and-hold Sharpe 1.917, +230.5%, −22.7%) | A look at a moving-average distance on train and validate, inside dip events only: **+1 in the strict count**. Validate is not fresh, so E9 can reject but not confirm |
| K5 | `research/hold-mix-cap/PLAN.md` (sections 0-3 and 16-17) and its README. **Its RESULTS.md does not exist yet** | When published, it will hold the returns and falls of thousands of held BTC/ETH/USDC mixes on 2017-2022. Those mixes resemble N0 (a comparator), not the rule. Stop rule 16 handles the ordering |
| K6 | `docs/app/product.md` and `features.md` (Steady and settings sections); `reports/director/2026-11-20-adjustable-settings.md` (via the sketches); `reports/director/2026-11-21-boom-check.md` (in full) | Product promises; the guardrail ruling ("a few trades a month" caps check frequency unless more checks are shown to pay); the owner's boom-years decision, built in here as E7 and in G7 |
| K7 | The evidence sketch's web research: published trend results on BTC and ETH, several overlapping our train window. Zarattini, Pagani & Barbon (2025) run through 2025, so they cover our validate and test windows | The box (L 20-200, buffer, weekly checks) was taken from this literature, not from our data. The thousands of rules others have tested are a selection effect that DSR cannot count |
| K8 | Synthetic timing stand-ins by three sketches (`timing_synthetic.py`, `throughput.py`, `standin_timing.py` in the scratch folder); `config/*.yaml` read for limits and costs; the date grid (appendix B) | No market data |
| K9 | The data quality reports (single-bar moves, some in the test window; rebalance-steady P3) | **Not opened** for this draft or any sketch |

**Counted honestly:**
- Looks by the desk at any trend rule on this data: **0**.
- Looks at a related trend signal: **1** (K4, in the strict count).
- **Validate-window looks for trend-steady: 0.** The validate window is unspent for this strategy but not fresh
  (K4).
- **The test window is never read.**

Not read for this draft: the catalog, `SNAPSHOT.json`, anything under `results/`, `trials.csv`, `evaluations.csv`,
the dip study's `AUDIT.md`, and the data quality reports.

## 3. Data

| Item | Pinned |
|---|---|
| Primary | Kraken daily bars, `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN`, through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=...)` |
| Robustness | Binance daily bars (`BTCUSDT`, `ETHUSDT`, quoted in USDT). **No search on Binance.** The Kraken-chosen parameters are re-run on Binance (E8) |
| Train phase | `last_close = 2023-01-01 00:00 UTC`. Kraken: 2190 rows, closes 2017-01-02 .. 2023-01-01. Close 2018-01-13 is dropped (no ETH bar), so one return spans 2 days and one L-row average spans L + 1 days; both are disclosed and neither is fixed. Binance: 1963 rows from 2017-08-18 |
| Validate look | Only if earned (section 13): `last_close = 2024-07-01 00:00 UTC`. Kraken 2737 rows; validate is rows 2190-2736 |
| Snapshot | Each run reads `snapshot_id` and `bars_content_sha256` from `data/catalog/SNAPSHOT.json`. Stop and amend unless the bars hash is `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e` and the panel hashes (`steady.panel_hash`) are Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587` (rebalance-steady run 0) |
| Slicing | Every run starts at its panel's **first row** (harness H0, section 7) and ends at a close time taken from the Kraken panel. Kept rows are compared by close time; a Binance kept index must equal Kraken's, or stop |
| Test window | **Never read.** No request asks for a close after 2024-07-01 00:00 UTC. `load_panel` raises `HoldoutWindowError` for such a request or for any returned bar after it. Each script asserts `panel.index.max() <= last_close` on every frame |

## 4. The rule and the Steady limits

`lab.runner.trend.trend_backtest(params, bars, *, limits, costs, s=0.50, f=0.50, weekday=0)`. It hands a
`decide(t, w)` callback to `portfolio._simulate`, the engine `rebalance` and `hold_mix` use. No engine file changes.

| Step | Rule |
|---|---|
| Average | For coin a ∈ {BTC, ETH}: SMA_a(t; L) = the mean of close_a over slice rows t−L+1 .. t, **including close t** (it is known at that close). It is computed per window, never as a running sum |
| Distance | m_a(t) = close_a(t) / SMA_a(t; L) − 1 |
| Activation | A = max(199, L − 1) slice rows. 199 = L_max − 1, so every L in the box starts on the same row; larger values occur only for G5 plateau steps above L = 200. Every run starts at its panel's row 0 (H0), so A is a panel row: Kraken row 199 is close 2017-07-20, Binance row 199 is close 2018-03-05. Before the first check close at or after A, both states are **out**, the book is all USDC, and nothing is ordered |
| Check closes | Closes with `index.day_of_week == weekday` (default 0: Monday 00:00 UTC, the bar of Sunday) at slice rows ≥ A. They are tied to the calendar, so the check phase never depends on where a slice starts. A missing check close is skipped, with no substitute. Kraken train has 313 Monday closes; the first check is 2017-07-24 (row 203); no 30 days hold more than 5 check closes. Use `day_of_week`, not `dayofweek` (deprecated in pandas 4) |
| State (hysteresis) | z_a ∈ {out, in}, starting **out**. At a check close: out → in if m_a(t) > +δ; in → out if m_a(t) < −δ; otherwise unchanged. Both inequalities are strict, so exact equality changes nothing. The same L and δ apply to both coins. The state is held between check closes |
| Targets | w_a = (s/2)·[z_a = in], with s = 0.50 and the 50/50 split f fixed: (0.25, 0.25), (0.25, 0), (0, 0.25) or (0, 0). USDC is the rest. A coin in a downtrend goes to USDC; it is never moved into the other coin (that would be rotation, a Bold idea) |
| Orders | At most one order per close, always the **full target vector**: (1) at a check close where either state changed, order the new targets (a switch); (2) otherwise, if the weights at close t breach a Steady limit (`portfolio._breach_test(min_cash, max_coin)`: coins > 1 − min_cash + 1e-9, or one coin > max_coin + 1e-9; today 0.80 and 0.60), order the current targets (a limit fix); (3) otherwise, no order. A switch and a breach on the same close give one order. A switch of one coin also re-cuts the other coin to its target (disclosed) |
| Fill | At the open of t+1 (hard rule 4). Each coin is a swap against USDC at its own open. A leg with zero change does not trade. An order decided at the last close of a slice is never filled |
| Between orders | Coin units and cash are held, and weights drift. **No band rebalancing and no drift trim inside a trend.** Only switches and limit fixes trade |
| Limits | `portfolio.risk_limits("steady")`, read at the start of every run and never typed (today min_cash 0.20, max_coin 0.60, coins exactly BTC/ETH/USDC; file SHA-256 `158d7c9f…`). Headroom h = 0.02: all four target sets pass `check_targets` with the limits as read and h before any bar is loaded, or the run refuses. On 2026-11-21 all four passed, and so did those for s ∈ {0.30, 0.40, 0.60, 0.70} (appendix B). Breaches are judged at the limits themselves |
| Costs | `Costs.from_yaml()` at 1x and `.stressed()` at 2x (k = `stress_multiplier` = 2.0), built once per run. Per leg: traded share × (5 bps pool + 0 aggregator + slippage at the leg's USD size) + USD 0.10 gas. The book starts at USD 10,000 at row 0 and compounds. A fill's cost is shared pro rata, so the book holds exactly the targets after a fill |
| Cash | USDC at price 1, with no yield and no depeg |

**Readings carried over** from rebalance-steady, confirmed by the owner on 2026-11-20 (Q1) or held by default (Q2,
Q6):
- a drifted breach at any close forces a full re-target;
- `max_coin_pct` applies to each coin, not to the coins together, and **not to USDC**. This study depends on that
  reading, because a 60% cap on USDC would forbid the all-cash state (owner question 2);
- h = 0.02.

**Decisions never depend on costs or book size.**
- The states depend on prices only.
- Limit fixes depend on weights, which a fill sets exactly to the targets and which then drift with prices only.
- So the orders (closes, reasons and targets) are identical at 1x, at 2x and at every book size. This is tested
  (section 17) and checked in every run by an order hash (stop rule 13).

**App wording (proposed):** "Holds 25% BTC, 25% ETH and 50% cash while each coin's price is above its L-day average;
moves that coin's share to cash when its price falls clearly below it. Checked weekly. It does not protect against
sudden one-day crashes."

**Production notes, not engine behaviour** (for the eventual risk note):
- sells go before buys;
- the caps are checked after the trade, on the full order;
- a breach is fixed at the next daily open, with an alert if it lasts more than one day;
- gas is booked to the paper account's book, as the backtest does;
- a loss-limit pause or Approve mode must not block an exit to cash (owner question 4).

## 5. Parameters and search box

Two free parameters (the cap is 4). Both move the switch dates, so the objective can tell their values apart, unlike
rebalance-steady's coin share.

| Parameter | Kind | Range | Scale | Spec |
|---|---|---|---|---|
| `lookback` L | int | 20 - 200 days (rows) | log | `Param("lookback", "int", 20, 200, log=True)` |
| `buffer` δ | float | 0.005 - 0.10 | log | `Param("buffer", "float", 0.005, 0.10, log=True)` |

- **Why these bounds.**
  - 20 days is the short end of crypto momentum studies (Grobys et al. 2020; Liu & Tsyvinski 2021 at weekly
    horizons). 200 days is the most quoted long average.
  - 0.5% is effectively no buffer; 10% is very sticky.
  - Log scales: 20 against 40 days matters as much as 100 against 200.
  - The bounds come from the literature and common practice (K7), not from our data.
  - L stops at 200 because a 365-day average would leave fold 0 almost no active training rows.
- **Every point of the box is feasible.** The targets depend on neither L nor δ.
- **Fixed, not searched and not user settings:**
  - the crypto share s = 0.50 (owner question 1);
  - the BTC/ETH split 50/50;
  - the Monday check day;
  - the activation rule A;
  - the start state (out);
  - h = 0.02;
  - the limits as read and the cost model.
- **Why s is not searched.** A Sharpe objective hardly identifies the crypto share (rebalance-steady section 5 and
  RESULTS.md: θ_final sat at the box edge), yet the share drives drawdown. It is fixed as the risk-officer
  recommended. Its sensitivity is a description (s = 0.30 and 0.70, section 16).
- **Expected trade frequency** (from reasoning and synthetic stand-ins, not data): about 2-12 switches per coin a
  year, fewer at larger L and δ, plus 0-2 limit fixes a year in long rises.
  - At USD 10,000, a switch of one coin trades about USD 2,500 (one leg at about 26 bps, plus gas).
  - Weekly checks cap switches at 5 in any 30 days by construction.

## 6. Objective

`lab.search.objective.evaluate_params` unchanged, through `run_study`, with `SearchConfig(n_trials=N, n_workers=1,
n_blocks=4, penalty=0.5, seed=..., periods_per_year=365, min_trades=5)`.

- Score = the mean of the 4 block Sharpes (annualised with √365) minus 0.5 × their standard deviation, over the
  fold's training rows, after costs at 1x.
- `min_trades = 5`, the lab default. It counts `trade_returns` entries, i.e. fill rows (switches and limit fixes,
  the first buy included). Trials scoring −10 are logged and counted like any other, and their number is reported
  per study.
- **Disclosed distortion.** Every training slice starts at row 0 (H0), and rows 0-202 are all cash for every trial
  (first check at row 203).
  - The first objective block of every study is therefore partly or wholly zero, and in fold 0 two of the four
    blocks are.
  - The zeros are the same for every trial, so they favour no L or δ. They do make the in-sample Sharpe and the
    walk-forward efficiency less meaningful.
  - **They also bias the luck statistics** (found by the audit; fixed in G3 and G4, section 10). Rows 0-203 are
    0 for every trial: 56% of fold 0's training rows, 9% of the final study's. Every trial Sharpe in a study is
    shrunk by about √(share of active rows), so the variance of trial Sharpes that sets DSR's luck benchmark is
    understated: on synthetic random walks (audit check, `audit/dsr_zero_rows_check.py`) the variance on all rows is
    0.44 of the active-row variance at fold 0's 365 rows, 0.72 at 730 and 0.91 at the final study's 2190, i.e.
    exactly the active share, roughly a fifth too small pooled over the 12 studies: **DSR is too lenient**. PBO's in-sample halves
    that hold only zero blocks tie every trial, which the tie rule scores as overfit: PBO is pushed up. Both are
    therefore also computed on the **active rows** (rows 204 .. end of each search study: the first check close is
    row 203 for every L in the box, so row 204 is the first row on which any trial can hold a coin), and each gate
    takes the stricter reading.
  - In fold 0 only about 162 training rows can trade (2017-07-24 .. 2018-01-01, the end of the 2017 bubble), and
    `min_trades` pushes the choice toward faster rules. This is noisy; whether it helps or hurts S is not known in
    advance.

## 7. Walk-forward, harness, search and selection

**Folds.** `walk_forward(2190, train_size=365, test_size=365, expanding=True)` on the Kraken train panel. This puts
**both** long bear markets (2018 and 2022) out of sample, which the leave-one-year-out test (E6) needs.

| Fold | Train rows (closes) | Test rows (t0 .. last) | Kept returns (closes) | Check closes deciding kept fills |
|---|---|---|---|---|
| 0 | 0-364 (2017-01-02 .. 2018-01-01) | 365-729 (2018-01-02 .. 2019-01-02) | 364 (2018-01-03 .. 2019-01-02) | 52 |
| 1 | 0-729 (.. 2019-01-02) | 730-1094 (2019-01-03 .. 2020-01-02) | 364 (2019-01-04 .. 2020-01-02) | 52 |
| 2 | 0-1094 (.. 2020-01-02) | 1095-1459 (2020-01-03 .. 2021-01-01) | 364 (2020-01-04 .. 2021-01-01) | 52 |
| 3 | 0-1459 (.. 2021-01-01) | 1460-1824 (2021-01-02 .. 2022-01-01) | 364 (2021-01-03 .. 2022-01-01) | 52 |
| 4 | 0-1824 (.. 2022-01-01) | 1825-2189 (2022-01-02 .. 2023-01-01) | 364 (2022-01-03 .. 2023-01-01) | 52 |
| final | 0-2189 | — | — | θ_final |

- **Out-of-sample span:** 5 × 364 = **1820 daily returns**, closes 2018-01-03 .. 2023-01-01. They span W = 260
  Monday check closes (2018-01-08 .. 2022-12-26).
- **Folds 1-4 have exactly rebalance-steady's 1456 kept rows** and are reported on their own too, so the two studies
  compare row for row.
- **No purge and no embargo.** There are no labels, the SMA at close t reads closes up to t only, and the first
  return of each block is dropped.

**Harness H0 (fixes path dependence and audit N6).**
- S is `walk_forward_optimize(..., warmup=2190)`, so `ctx_start = max(0, test[0] − 2190) = 0`. Every out-of-sample
  run starts at row 0, as every expanding training slice does.
- The hysteresis state at close t is then one fixed function of closes 0..t for given (L, δ), the same in training,
  out of sample, at θ_final and at the look.
- Kept rows are the closes after t0 (`res["ret"].loc[t0:].iloc[1:]`).
- `steady.fold_window(index, test, warmup=2190)` gives the same slice, so `buy_and_hold_b1` and `fifty_fifty_b2`
  run in H0 unchanged.
- **Cost of H0:** the book compounds from USD 10,000 in 2017, so later folds trade larger legs at higher
  (extrapolated) slippage. This is pessimistic for S and the same for its nulls, which start from S's book. It is
  disclosed, and the wallet-size description (R4) shows the size effect.

**Common start state.** Every null and comparator that is not a benchmark (R_0, the rotations, N0, X) copies S's
states up to close t0 − 1, so it holds **S's book at close t0 bit for bit** (asserted; stop rule 14). From close t0
on, each follows its own schedule and pays its own trades.

**Optuna.**
- TPE exactly as in `lab/search/study.py`: multivariate, 20 startup trials at N = 200, journal storage.
- `n_workers = 1`, so every study is exactly reproducible.
- Fold seeds are `seed + 1000·i`; the final study uses `seed + 5000`.

**N, trials per study.** The throughput rule (rebalance-steady A1, scaled to 12 studies):
1. Time a 200-trial study of the **built** adapter (`n_workers = 1`) on 2190 synthetic rows,
   `make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")`.
2. N = 200 if 12 × that time is at most 60 CPU-minutes. Otherwise N is the largest multiple of 25 that fits; below
   50, ask the owner.
3. Redo the timing if the built adapter's single backtest is more than 2× slower than the stand-in's.

Synthetic stand-ins of this rule measured 5.80 s (`timing_synthetic.py`), 5.84 s (`standin_timing.py`, 1940 rows)
and 5.96 s per 200-trial study, and 0.011-0.014 s per 2190-row backtest. 12 × 5.96 s ≈ 72 s, so **N = 200** is
expected.

**Trial budget.**
- Per run: 2 seeds × (5 folds + final) = 12 studies × 200 = **2400 trials**, all logged.
- At most 2 amendment runs, so N_raw ≤ 7200.

**Selection.**
- `stable_region(trials, specs, k=10)` inside `walk_forward_optimize`, unchanged.
- For every fold the report gives the chosen trial, each parameter's range over its 10 neighbours with their scores,
  and the raw best trial.
- "Best stable region" means that neighbourhood, never the top trial alone.

**Two searches.** Seed A = 0 (primary) and seed B = 1, identical in everything but the seed. Seed B gets its own
R_0, rotations, N0 and X, its own book and the same bootstrap. FRAGILE is defined in E5.

**Study names, one directory** (`results/trend-steady/train/`):
- run 0: `trend-steady-s0_wf00` .. `_wf04` and `trend-steady-s0_final`, and the same with `s1`;
- amendment run k: `trend-steady-s0_a<k>_wf00` .. `_wf04` and `trend-steady-s0_a<k>_final`, and the same with
  `s1`.

The `context` of every study records:
- the snapshot id and the bars hash;
- the git commit and dirty flag, and the config hash;
- the source, the seed and the run number;
- the branch (F or R);
- the limits as read (`min_cash`, `max_coin`, the raw budget value and the file's SHA-256).

## 8. User settings and allowed values

**Branch F, fixed settings: no setting a user can change.** This is the default, and today it is the only branch
open, for two reasons:
1. AGENTS.md "Settings ranges": the level's drawdown budget must be owner-approved **before** a range is
   pre-registered. Steady's budget is `TBD` (`config/risk_levels.yaml`, read 2026-11-21).
2. The allowed range must lie inside the search box. s is not searched in Branch F, so it cannot support a range.

The strategy would ship θ_final(A)'s L and δ with s = 0.50 and the 50/50 split. It is gated as AGENTS.md says for
fixed settings: on the walk-forward result, plus θ_final's own runs wherever the gate table names the default
(section 10). Those θ_final runs are in-sample (θ_final was chosen on all of train), so they add checks, not
evidence.

**A range cannot be added later.** Allowed values set after results would be post hoc. And a range that fails can
never be cut down to fixed settings.

**Lookback and buffer are never user settings**, in either branch:
- they are the timing the luck tests measure;
- letting users pick them invites picking by past results, which the app rules out ("No best settings",
  `features.md`);
- every extra value multiplies the combinations that must each pass every gate.

**Branch R (a crypto-share setting), only if, before PLAN.md is committed:**
1. the owner approves a Steady drawdown budget in writing (a number, or the method that sets it);
2. `risk-officer` writes the budget into `config/risk_levels.yaml` with that approval;
3. PLAN.md's header reads "Branch: R", quoting the number and the file's SHA-256;
4. section 2 lists, as prior looks that could inform the range (AGENTS.md "Settings ranges"), everything the owner
   and `risk-officer` had seen when they set the budget and the allowed values, in particular whether hold-mix-cap's
   RESULTS.md or any other result on 2017-2024 prices had been published by then.

Otherwise the header reads "Branch: F", and this paragraph is struck by a dated amendment before run 0. In Branch R:
- **Third searched parameter:** `Param("crypto_share", "float", 0.30, 0.60)`, linear.
  - The top is 0.60, not 0.78: near 0.78, a rise of about 13% forces a limit fix, which goes against "a few trades a
    month", and a one-day crash costs about s × the fall.
  - 0.60 also needs the per-coin reading of `max_coin_pct`.
  - All 4 states pass `check_targets` for every allowed value (appendix B).
- **Allowed values** (set by `risk-officer` in the pre-registration, both ends included): s ∈ {0.30, 0.40, 0.50,
  0.60}.
  - The **default** is the allowed value nearest θ_final(A)'s s; ties go to the lower value.
  - L, δ, the split and the check day stay at θ_final(A)'s values.
- **The grid** is the 4 steps. Every gate is measured where the AGENTS.md "Settings ranges" table says:
  - G1 and G2 at every step, held fixed over the out-of-sample span;
  - G5 from the default (L, δ and s, each ×0.8 and ×1.2) and at every step;
  - G6 at S and at the deepest step;
  - G7 and G8 at the default and at every step;
  - every grid run is added to the total trial count, never to the effective count.
  - One failing step fails the range.
- **This plan's out-of-sample range check (stricter than AGENTS.md, not a gate change).** A grid step carries
  θ_final's timing, which was chosen on all of train, so its fixed runs are in-sample in their timing. So, for each
  allowed s_k, S(s_k) = the walk-forward with each fold's chosen L and δ and s replaced by s_k must also have:
  - Sharpe ≥ 1.0 at 1x and > 0.5 at 2x;
  - a Monte Carlo p5 drawdown within the budget.

  A failing S(s_k) fails the range like a failing grid step.
- **Narrowing** follows AGENTS.md only:
  - only to meet a risk limit (the budget or the level's limits);
  - by dropping whole values from the riskiest end (the end whose steps include the deepest Monte Carlo p5);
  - each drop logged with its margin;
  - the dropped steps stay in the count;
  - frozen before any test-window run;
  - the range must keep the default: if meeting the budget would drop the default's value, the range fails (it
    is never re-centred and never cut to fixed settings).
- **Paper:** the riskiest step gets the second paper model account.

## 9. Comparators and luck controls

All comparators run with costs on (1x unless stated), on exactly S's kept rows. **Decisive** means the comparator
enters the verdict.

| ID | What | Harness | Role |
|---|---|---|---|
| S | `walk_forward_optimize(...)["oos_returns"]`, 1x adapter, seed A | H0 per fold, stitched | Gates; E2-E6 |
| R_0 | **S's own schedule, executed continuously.** One book from fold 0's t0 to the last train close, starting from S's fold-0 book (common start). At each of the W = 260 check closes c_k, the state pair is z(c_k): the state fold i's S run holds at c_k, where t0_i ≤ c_k ≤ last_i. It is held between check closes, and limit fixes are endogenous. Scored on S's 1820 kept closes (the closes t0_1 .. t0_4 are not kept rows of any fold, so they are dropped) | H0, one span | **E1's statistic.** On fold 0's kept rows R_0 equals S bit for bit (asserted). It differs from S only at fold boundaries, where R_0 pays the switch S's stitched curve never pays; the difference is reported |
| B3 | **Shifted timing.** For every offset u = G + 1 .. W − 1 with the **lead guard G = 52 weeks**, the schedule z_u(c_k) = z(c_{(k+u) mod W}) (both coins together), executed exactly as R_0 from the same book. **Exhaustive over the guarded offsets: 207 series (u = 53..259), no seeds.** Offsets u = 1..52 are not in the null: there z_u(c_k) is the state the rule takes u weeks *later*, which was set from prices that include the very returns the shifted schedule then earns (a 200-day average reaches 29 weeks back, and hysteresis carries a state further). Such a shift is a look-ahead copy of the signal, not chance; it tends to beat R_0 under any trend and even on a random walk, which pushes E1's false-positive rate far below 5%, costs power and would fail the draft's two-sided calibration band. On synthetic iid random walks (audit check, `audit/shift_null_check.py`, 400 panels, simplified one-coin model) 74% of these lead offsets beat R_0 at (L, δ) = (200, 0.10), and E1 with all 259 offsets passed on 0.0% of panels; with the guarded 207 offsets it passed on 5.0% (2.8% against 5.5% at (50, 0.02)). Offsets u = 208..259 (delays of 1-52 weeks) stay: a delayed state reads only past prices | H0, one span | **Decisive: E1.** It keeps time in market, spell lengths, the number of switches (up to the one splice) and the BTC/ETH co-timing; only the alignment with prices changes. A whole-span shift can move the 2018 or 2022 out-spells onto 2019-21, so it tests the timing of the big cycle, not only the timing within a year. It stands in for AGENTS.md's random-entry benchmark with the same number of trades |
| N0 | **Always in.** From S's book at close t0 of each fold, the states are forced to (in, in): it orders (0.25, 0.25) at close t0 unless S already holds that state, then makes limit fixes only. At 2x it starts from S-at-2x's book | H0 per fold, stitched | **Decisive: E2, E4, E6, E7** |
| X | **Exposure-matched static mix.** Per fold, targets ē_a = the mean of S's w_a over the fold's kept closes, from S's book at close t0, ordered at t0, then limit fixes only. If ē fails `check_targets` with the limits as read and h (possible only if S sat within h of a limit on average over a whole fold), both of X's targets are scaled by the largest common factor λ < 1 that passes, to 1e-12, and X is marked "clipped" with λ in RESULTS.md. This is an outcome, not a stop | H0 per fold, stitched | **Decisive: E3.** Does timing cut falls beyond simply holding less crypto? |
| B1 | Buy-and-hold BTC, `steady.buy_and_hold_b1` with `fold_window(..., warmup=2190)` | H0 | G7 |
| B2 | 50/50 BTC/USDC every 30 days, `steady.fifty_fifty_b2` likewise | H0 | G7 |
| B3-lead | The 52 excluded offsets u = 1..52 (leads), run exactly as B3 | H0, one span | Description only: a lead/lag profile of how sharp the timing is. Never a null, never in any criterion. (It replaces the draft's B3-fold, a circular shift within each 52-week fold: every one of its offsets leads the schedule over part of the year, so it was a look-ahead profile, not a within-year null) |
| N0-span | Always in, bought once at fold 0's t0 and held to 2023-01-01 | H0, one span | Description |

The two decisive tests do different jobs:
- E1 asks whether the *dates* were well chosen, holding exposure fixed.
- E2 asks whether timing beat *not timing*.

A long-biased rule beats a coin-flip null for free, so the shift null keeps S's exposure exactly.

**Procedure controls, before any real bar (amendment A0; synthetic only, not results).** The seed-A train pipeline
is run end to end (5 fold studies at N, H0, R_0 and its shifts, N0, P, E1 and E2) on two sets of 20 panels:
- **positive controls:** `make_panel(synthetic_market(2190, seed=1000+j, start="2017-01-02"),
  snapshot_id="synthetic")`, j = 0..19. These have persistent bull, bear and sideways regimes;
- **negative controls:** `shuffled_market` of those markets (seed j). This destroys every serial structure.

Reported:
- **power**, the share of positive panels where E1, E2 and P all hold;
- **false positives**, the share of negative panels where E1 and E2 both hold.

Then:
- 3 or more false positives in 20: stop and triage before any real bar (stop rule 15).
- Power below 4 of 20: tell the owner before run 0. The study would mostly return INCONCLUSIVE or NO EDGE (LOW
  POWER), and the owner decides whether to run it.

These panels are not trials and enter no count.

**Calibration test (slow tier).** Two pinned points, each its own parametrized test, with no search: (L, δ) = (50,
0.02) and the slowest corner of the box, (200, 0.10), where a state's memory is longest and any leak through the
lead guard would show first.
- 200 panels per point: `make_panel` of two Gaussian log-return random walks on the 2190-close train grid of
  appendix B (2018-01-13 dropped). Daily log-return mean 0.001 for both coins, sd 0.04 (BTC) and 0.05 (ETH),
  correlation 0.8, `np.random.default_rng(seed)` with seeds 0..199; start price 10,000 (BTC) and 500 (ETH);
  open = previous close (the first open = the first close), high = max(open, close), low = min(open, close),
  volume 1.
- On each panel the fixed rule runs in H0 as one span from row 0. Its schedule over the W = 260 Monday checks of
  the fold layout is R_0 (no folds, one parameter set), scored on rows 366..2189 without the four fold-boundary
  rows (1820 rows), against its 207 guarded shifts, at 1x costs. E1 is applied exactly as in section 11.
- **Holds if at most 18 of the 200 panels pass E1 at each point** (for a true rate of 5%, P(19 or more) = 0.6%).
  A rate far below 5% is allowed (conservative) and reported as a loss of power.
- Expected cost: about 208 runs × 200 panels × 0.013 s ≈ 9 CPU-minutes per point (stand-in timing).

## 10. Gates (AGENTS.md defaults, unchanged)

Computed on seed A's stitched S (Kraken, 1820 returns); seed B's are computed for E5.
- **A missing number fails; it never passes.**
- `rep = overfitting_report({"oos_returns": S_A, "wf_efficiency": ..., "studies": <every study of every run>,
  "total_trials": N_raw}, out_dir)`.
- **Where each gate is measured** follows AGENTS.md "Settings ranges" for fixed settings: the walk-forward result,
  plus θ_final(A) held fixed over the 1820 kept rows (in-sample) wherever the table names the default.

| Gate | Threshold | Measured at |
|---|---|---|
| G1 | OOS Sharpe after costs ≥ 1.0 | S: `gates(rep)["oos_sharpe >= 1.0"]` |
| G2 | Same at 2x costs > 0.5 | S re-run at 2x: the same per-fold parameters, H0, no new search |
| G3 | DSR ≥ 0.95, counting every trial | `gates(rep)["dsr (effective) >= 0.95"]` **and** the active-row DSR (section 14) ≥ 0.95: both must hold, and a missing one fails. The effective count comes from the search studies only. Taking the stricter of the two readings is this plan's measurement rule for the all-cash warmup rows (section 6), not a threshold change |
| G4 | PBO ≤ 0.25 | `gates(rep)["pbo <= 0.25"]`: the mean of the per-study PBO (10 blocks) over every study, **and** the same mean on the active rows (section 14) ≤ 0.25: both must hold |
| G5 | Plateau: each step keeps ≥ 70% of Sharpe(S), and Sharpe(S) > 0 | (a) From each fold's choice: L and δ each ×0.8 and ×1.2, applied to every fold at once (4 stitched runs, H0). (b) From θ_final(A), held fixed over the kept rows (4 runs). L steps: down = max(1, min(half_up(0.8·L), L − 1)), up = max(half_up(1.2·L), L + 1), with A = max(199, L − 1). δ steps: ×0.8, ×1.2. Steps outside the box are allowed and marked "outside the box" |
| G6 | Monte Carlo p5 max drawdown within the budget | S: `rep["mc_drawdown_worst5pct"]` (stationary block bootstrap, mean block 20, 1000 draws, seed 0) ≥ −budget. The budget is read by `risk_limits("steady")` **before any real bar** and recorded; only that reading counts for the whole study, amendment runs included. **`TBD` → MISSING = FAIL**, whatever is set later |
| G7 | Better risk-adjusted return than B1 and B2 | Sharpe(S) > Sharpe(B1) and > Sharpe(B2) on the same rows. **Also** with BTC's best bar-year of the kept span removed, and with its two best removed (the owner's rule, E7's ranking). **Also** θ_final(A) held fixed against B1 and B2 on the full rows |
| G8 | No regime makes most of the profit | Each kept row belongs to the month of its bar day (close − 1 day). A month is bull if BTC's compounded return over that month's kept rows is ≥ +10%, bear if it is ≤ −10%, and sideways otherwise. PASS if Σ ln(1 + r) > 0 and no regime holds more than half of it. Measured at S **and** at θ_final(A) held fixed. **Read literally** (owner question 5). Expected to FAIL by construction for a long-or-cash rule. The owner's alternative is pinned now so it cannot be defined after results: **G8-excess** = `steady.regime_split(S, table, benchmark=N0)`, PASS if `excess_total` > 0 and every regime's `excess` ≤ `excess_total` / 2 (at θ_final(A), against θ_final(A)'s own N0, built per fold from θ_final(A)'s book at each fold's t0 exactly as S's N0 is). G8-excess replaces the literal reading only if the owner chooses it in writing before PLAN.md is committed; both readings are always reported |
| G9 | Final test window, run once | **NOT RUN.** Never in this study |

Reading G1, G3 and G7: they are weak evidence (K1, K2). The 2018-2022 span holds two known bear years, which any rule
of this family largely sits out. B1 looks bad in 2018 and 2022 for the same reason. E1, E2, E6 and E7 carry the
research question.

## 11. Research criteria

Unless stated otherwise: seed A, Kraken, the 1820 stitched kept rows, costs at 1x, and Sharpe =
`stats.annualized_sharpe(r, 365)`. A **bar-year** is the calendar year of a kept row's bar day (close − 1 day); the
kept span has bar-years 2018-2022.

| ID | Criterion | Holds if |
|---|---|---|
| **E1** | Timing beats chance | Sharpe(R_0) > the 95th percentile (`np.percentile`, linear) of the 207 B3 Sharpes (guarded offsets u = 53..259, section 9). Ties count against S. The rank p = (1 + #{B3_u ≥ R_0}) / 208 is reported. The 52 lead offsets (B3-lead) are reported separately and never enter E1 |
| **E2** | Beats holding the same mix | D = Sharpe(S) − Sharpe(N0) > 0, **and** the one-sided paired stationary bootstrap gives p < 0.05: `steady.paired_bootstrap(S, N0, n_resamples=10000, mean_block=60, seed=0)`, with the same indices for both series and p = (1 + #{D* ≤ 0}) / 10,001. Mean block 60 because trend spells last months; a block of 20 understates D's variance. Block 20 is reported as a description |
| E3 | Cuts falls beyond holding less crypto | S's stitched historical max drawdown **and** S's Monte Carlo p5 max drawdown (G6's statistic) are both strictly shallower than X's |
| E4 | Survives doubled costs | Sharpe(S at 2x) > Sharpe(N0 at 2x) |
| E5 | Not fragile | (a) Seeds A and B give the same outcome for each of E1-E4, E6, E7, P and G1-G8, and their OOS Sharpes differ by ≤ 0.25. (b) **Check-day sensitivity:** S re-run with each of the other 6 check weekdays (seed A's per-fold L and δ, H0, nothing re-searched) keeps ≥ 0.7 × Sharpe(S) for every weekday, **and Sharpe(S) > 0** (as in G5: with Sharpe(S) ≤ 0 the 0.7× test would pass a weekday that does worse, so E5 fails). An edge that lives on Mondays only is luck about particular days |
| E6 | Not one year | Let Δ_y = Σ over bar-year y's kept rows of ln(1 + S_t) − ln(1 + N0_t), and Δ = Σ_y Δ_y (named Δ, not X, so it is never confused with the comparator X). Holds if Δ > 0 **and** Δ − Δ_y > 0 for every y in 2018-2022: the excess over always-in survives losing any one year, bear years included |
| E7 | Not the boom years (owner's rule, 2026-11-21) | Rank bar-years 2018-2022 by BTC's compounded close-to-close return over each year's kept rows (Kraken; ties: the earlier year ranks higher). With the best year's rows removed, and again with the two best years' rows removed (from every series alike; nothing refitted; the same offsets and the same bootstrap settings on the remaining rows in time order), **E1 and E2 both still hold** |
| E8 | Other data source | On Binance, folds 1-4 only (Binance has no signal until 2018-03-05, inside fold 0), with seed A's per-fold parameters: E1 (Binance R_0 against its 155 guarded shifts, u = 53..207, over the 208 check closes of folds 1-4, from Binance S's fold-1 book) and E2 (Binance S against Binance N0, 1456 rows) both hold. The Kraken folds 1-4 values are shown alongside |
| P | Power floor | At least 20 coin-state changes (both coins counted) at check closes whose orders fill in kept rows, with at least one in each of at least 4 of the 5 folds. First buys and limit fixes do not count |
| E9 | Validate does not contradict (reject-only; at the single look, section 13) | θ_final(A) on Kraken validate at 1x (546 kept returns): Sharpe > 0; ≥ 0.5 × Sharpe(S); ≥ 0.5 × Sharpe(N0 on validate); and > the median of its own 25 guarded validate shifts (u = 53..77 over the 78 validate check closes, the same lead guard G = 52). Beating N0 outright is not required: validate is a known bull window (K4) where a filter is expected to trail always-in, so the outcome of that test is known in advance |

**Notes on the criteria.**
- E1 and E2 form an intersection test, so each at 5% needs no correction.
- E2's power comes mostly from the two bear years, about 30 bootstrap blocks that are not independent, so its p is
  optimistic. E6 and E7 are the checks on that.
- E7 follows the director note of 2026-11-21: "a strategy that beats its comparators only with the boom years in does
  not count as beating them". The boom years are where always-in beats a trend rule, so E7 mostly guards the
  comparison with B1 and B2 (in G7) and the shift null. E6 guards against the opposite dependence, on one bear year.
- The leave-one-year-out results of E1, E2, G7 and the plateau are reported for every year, whatever their outcome.

## 12. Mechanical verdict and headline

**Verdict**, applied in this order:
1. **NO EDGE** if E1 or E2 fails. If P also fails, the headline reads "NO EDGE (LOW POWER: k switches)". Low power
   never turns a failure into anything else.
2. **INCONCLUSIVE** if E1 and E2 hold but P or any of E3-E8 fails, or a stop rule ends the study, or E9 fails at the
   look.
3. **EDGE** if E1-E8 and P hold, and E9 holds at the look. In words, wherever it is reported: "the trend rule's
   timing beat the same schedule shifted in time (by shifts that cannot see its own future) and beat holding the
   same mix always in, after costs, over
   2018-2022, also without BTC's best years and without any single year, and it cut falls more than holding the same
   average amount of crypto (SCOUTING)".

**Headline:**
- **CANDIDATE FOR AUDIT** if EDGE, G1-G8 all PASS where they are measured, and R1 holds. It means "worth a Nautilus
  build", never "ready for paper".
- **EDGE, NOT A CANDIDATE** if EDGE and any gate fails or is MISSING, or R1 fails. The failing items are listed.
  While the budget is TBD, G6 is MISSING, so this is the best this study can report. With G8 read literally, it is
  the best it can report even with a budget.
- Otherwise the verdict (**NO EDGE** or **INCONCLUSIVE**) is the headline.
- **Descriptions never decide.** Nothing listed as a description (sections 9, 12 R2-R5, 16) can change the verdict,
  the headline, θ_final, the shipped settings, the check day or s. In particular:
  - a daily-check variant, another weekday, s = 0.30 or 0.70, Binance alone, folds 1-4 alone, a block-20 E2 or the
    B3-lead profile that looks better than S is reported as a description only;
  - the daily-check variant cannot by itself meet the owner's "shown to pay" test for more frequent checks: that
    test needs its own pre-registration, which lists this study's trials as prior looks;
  - RESULTS.md opens with the mechanical verdict and headline, before any description.
- If an amendment run superseded an earlier run, RESULTS.md shows the superseded verdict and gate table next to the
  final one.

**Risk-officer conditions** (pre-registered; R1 enters the headline, R2-R5 are descriptions). Each is measured at S
and at θ_final(A) over the kept rows.
- **R1, "a few trades a month".**
  - Orders counted: every order filled in a kept row (switches and limit fixes; one order is one trip to a target
    vector, however many legs).
  - Holds if the mean is ≤ 2 orders per 30 days and no 30 consecutive days hold more than 5.
  - Switches occur only at check closes (at most 5 in any 30 days), so only limit fixes can break R1.
- **R2, limits.** Reported:
  - closes in breach (each fixed at the next open);
  - the highest single-coin weight and the lowest cash weight at any close;
  - the number of limit fixes.

  A target set refused during a run is a stop (stop rule 12).
- **R3, worst day and exit delay.** Reported:
  - the worst day and the 1st-percentile day;
  - the share of days in the market;
  - the longest delay from the first close below the lower band to the exit fill (at most 7 days plus one open, by
    design).
- **R4, small wallets** (descriptions only; the 4 sizes other than USD 10,000 are in the strict count, section 14;
  the orders are identical by construction). θ_final(A)
  rerun at books of USD 100, 500, 2,500, 10,000 and 50,000. Reported:
  - customer fees a year (pool + slippage, as a % of the wallet; gas excluded, since we sponsor it);
  - our gas cost a year in USD;
  - the Sharpe with gas charged;
  - the smallest of those books at which θ_final keeps ≥ 90% of its USD 10,000 Sharpe (a minimum-wallet proposal
    for the owner).
- **R5, all-cash concentration.** The share of days at 100% USDC and the longest such stretch. A USDC depeg is not
  modelled.

## 13. The single validate look

- **It runs only if E1-E8 and P all hold.** Otherwise the validate window stays unlooked for trend-steady.
- **Before it:** the train results are written, and `freeze.py` writes `results/trend-steady/FROZEN.json`.
  - `freeze.py` first recomputes the config hash and every per-file hash and compares them with the reported run's
    `summary.json` start fields. On any difference it exits without writing (the only exception is stop rule 10).
  - FROZEN.json holds: every hash; θ_final(A) and θ_final(B); the per-fold parameters; N, the seeds and the run
    number; the snapshot id and the train panel hashes; the limits and budget as read at train start; the branch;
    E1-E8, P, the verdict, the gates and the train Sharpes; the SHA-256 of `summary.json`; and the git state.
  - A byte-identical copy goes to `research/trend-steady/FROZEN.json`, committed with `trials.csv`,
    `evaluations.csv` and `RUNLOG.jsonl` before the look.
- **Start guard.** `run_validate.py` refuses if any of these holds:
  - the tree is dirty;
  - any hash differs from FROZEN.json;
  - FROZEN.json's numbers differ from `summary.json`'s;
  - `validate/STARTED` or `look.json` exists;
  - the tracked RUNLOG holds a look.

  Otherwise, **before loading any validate bar**, it appends its RUNLOG line and writes `validate/STARTED`. A crashed
  look counts as the look.
- **Consistency checks, before any validate number.**
  - The panels are `load_panel(..., last_close="2024-07-01")`. Their first 2190 (Kraken) and 1963 (Binance) rows
    must hash to the train panel hashes.
  - θ_final(A) and θ_final(B), re-run on the 2190 Kraken train rows, must reproduce their logged trial returns bit
    for bit.
  - If either check fails, stop: the look is spent and the verdict is INCONCLUSIVE.
- **What runs, once.**
  - θ_final(A) in H0 on Kraken rows 0-2736. t0 = row 2190 (close 2023-01-02, a Monday); the kept closes are
    2023-01-03 .. 2024-07-01 (546 returns).
  - Decisive (E9), from θ_final(A)'s book at close t0 (common start):
    - its N0;
    - its 25 guarded shifts (u = 53..77) over the 78 validate check closes (2023-01-02 .. 2024-06-24).
  - Descriptions only, which cannot change E9 or the verdict:
    - θ_final(B);
    - 2x costs;
    - B1, B2 and X;
    - Binance;
    - the regime split and Monte Carlo;
    - R1-R5.
- **Expectation, written now.** Validate is a known bull market (K4). An always-in mix should do well and a trend rule
  mostly holds the mix, so E9 can reject (for example, heavy whipsaw around the 2023-24 pullbacks) but cannot
  confirm.
- **After it:** nothing is tuned or changed. Any change needs a new pre-registration.

## 14. Trial counting and logging

- **N_raw:** every trial Optuna recorded, in every state, in every study of every run, loaded through `load_trials`.
  Nothing is deleted. Expected 2400 with no rerun, at most 7200.
- **DSR and PBO:** `overfitting_report` unchanged, with `out_dir = results/trend-steady/train/`.
  - The effective count, the trial-Sharpe variance and PBO come from the search studies only.
  - **Active-row reading** (section 6; G3 and G4 take the stricter reading). For every search study, cut each
    completed trial's logged return series to its rows 204 .. end (Kraken row numbers; every search study starts
    at row 0). Then, exactly as `overfitting_report` does on the full rows: the trial Sharpes are
    `stats.sharpe` of each cut column; each study's effective count is `stats.effective_trials` of its cut
    matrix, summed over studies; each study's PBO is `stats.pbo(cut, n_blocks=10)`, averaged over studies;
    the active-row DSR is `stats.deflated_sharpe_ratio(S_A, active trial Sharpes, n_trials=active effective
    count)`. The raw-count and strict-count DSRs are reported in both readings. S_A itself is unchanged (its kept
    rows start in 2018 and hold no warmup).
  - Seed B gets the same report with S_B, against the same trial set, in both readings.
- **Strict count (Branch F), reported but not gated: N_raw + 29.**

  | Runs | Count |
  |---|---|
  | Plateau steps from the fold choices (4 per seed) | 8 |
  | Plateau steps from θ_final(A) (the fixed-settings rule) | 4 |
  | S at 2x, both seeds | 2 |
  | S on Binance (seed A) | 1 |
  | Check-day variants for E5 (6 weekdays, seed A) | 6 |
  | Daily-check variant (seed A; the owner's "shown to pay" question) | 1 |
  | Crypto share 0.30 and 0.70 (seed A; descriptions for the risk-officer) | 2 |
  | θ_final(A) at the R4 book sizes other than USD 10,000 (cost variants, like the 2x runs) | 4 |
  | K4's look at a moving-average distance | 1 |
  | **Total** | **29** |

  Branch R: N_raw + 49:
  - 12 plateau steps from the fold choices (3 parameters × 2 factors × 2 seeds) and 6 from the default;
  - 2 runs at 2x and 1 Binance run;
  - 6 check-day variants and 1 daily-check variant;
  - 8 grid runs (4 steps at 1x and 2x) and 8 S(s_k) runs;
  - 4 R4 book sizes;
  - 1 for K4.

  **Not counted** (logged separately, with their seeds or offsets): R_0 and the shifts, N0, X, B1, B2, B3-lead,
  N0-span, the opposite-start state paths, the A0 control panels and θ_final(A)'s in-sample run
  (a logged trial, re-run).
- **Config hash:** SHA-256 over the per-file SHA-256s of:
  - `research/trend-steady/PLAN.md` and the scripts;
  - `lab/runner/trend.py`, `portfolio.py`, `reference.py`, `interface.py` and `steady.py` (its helpers are reused);
  - `lab/data/panel.py` and `catalog.py`; `lab/config.py`;
  - every `.py` file in `lab/search/` and `lab/validation/`;
  - `config/costs.yaml`, `splits.yaml` and `risk_levels.yaml` (today `0eeadeac…`, `a31ccc14…` and `158d7c9f…`);
  - `pyproject.toml` and `uv.lock`;
  - the pinned values: s, f, h, the check day, R0 = 199, the start state, N, the seeds, the folds and the harness.

  `RESULTS.md`, `RUNLOG.jsonl` and the FROZEN.json copy are not hashed (they change by design).
- **Recorded before any data is loaded.** `run_train.py` writes `summary.json` at start: git state, config hash,
  file hashes, the branch, and the limits and budget as read. It adds the panel hashes right after loading, before
  any backtest, and rewrites the file at the end with the start fields unchanged.
- **RUNLOG.** Every real run of `run_train.py` and `run_validate.py` first appends one line to the tracked
  `research/trend-steady/RUNLOG.jsonl`.
- **Files (git-ignored)** in `results/trend-steady/`:
  - `train/<study>/` for every study;
  - `train/run<k>/summary.json`, `trials.parquet`, `evaluations.parquet` (every run that is not a search trial) and
    `oos.parquet` (S_A, S_B, R_0, N0, X, B1, B2, N0-span, and the shift percentiles);
  - `FROZEN.json`, `validate/STARTED`, `validate/look.json`.
- **Committed record:** `research/trend-steady/trials.csv`, `evaluations.csv`, `RUNLOG.jsonl`, the FROZEN.json copy,
  `validate.csv` after a look, and `RESULTS.md`.
- **MLflow:** none. It is not built, and the Nautilus/MLflow work is on hold; this is a logged deviation.
- **Synthetic dry runs** and the A0 controls go to scratch folders only, never into `results/trend-steady/` or the
  repo.

## 15. Protocol, stop rules and amendments

**Order of work.**
1. The owner answers `OWNER_QUESTIONS.md`. Defaults hold if unanswered, and that is logged.
2. After hold-mix-cap's run is committed, `quant-researcher` writes `research/trend-steady/PLAN.md` from this draft.
   `backtest-auditor` and `risk-officer` review it, and it is committed with the branch line set.
3. Build `lab/runner/trend.py`, the scripts and their tests (section 17). The full tier with 100% branch coverage,
   the deep profile and ruff must pass.
4. Amendment A1 (throughput on the built adapter, synthetic) and amendment A0 (procedure controls, synthetic) are
   written into PLAN.md and committed.
5. Run 0, the train phase: both seeds, every comparator. Then RESULTS.md, the audit and the risk review.
6. The validate look, only if earned (section 13).

**Stop rules** (1-10 as rebalance-steady's, adapted):
1. No number counts unless the full tier (with coverage), the deep profile and ruff pass on the commit the run uses.
   Real runs refuse a dirty tree.
2. The bars hash, a panel hash or a row count differs from section 3: stop and amend.
3. The throughput rule allows fewer than 50 trials per study: stop and ask the owner.
4. A failed trial: finish the phase, then triage. A code bug gets a regression test that fails on the old code, a
   dated amendment row, and a full amendment run; the old trials stay and are counted. `freeze.py` refuses a run
   with failed trials unless it is given `--triaged "<note>"`.
5. The test-window guard fires: stop. Nothing from that run is used, and it is logged.
6. A crashed run is never resumed. It is rerun as an amendment run; its trials stay and are counted.
7. At most 2 amendment runs (k = 1, 2), each with its dated row committed first. A third need makes the verdict
   INCONCLUSIVE.
8. NO EDGE, or any of E3-E8 or P failing: no validate look.
9. A second look (including after a crashed look), or a bug found after the look that moves a validate number: the
   verdict is INCONCLUSIVE.
10. Any hash change between the train run and the look refuses the freeze. The one exception is a
    `risk_levels.yaml` change that leaves the Steady coins, `min_cash` and `max_coin` as read unchanged: it passes,
    a Deviations row is written, and G6 is never rescored.

**Added stop rules:**

11. **Branch guard.** `run_train.py` reads the branch line from the committed PLAN.md.
    - Branch R: it refuses unless the Steady budget read before any bar equals the owner-approved number quoted in
      the plan.
    - Branch F: it never builds a range, whatever the file says.
    - The branch can never change after run 0 starts.
12. **Feasibility before data.** Every target set the run can order passes `check_targets` with the limits as read
    and h before any bar is loaded: the 4 states; the s = 0.30 and 0.70 descriptions; in Branch R, every allowed
    value. A refusal of one of these during a run is a bug: stop and triage. X's targets come from S's weights, so
    they are checked when they are formed and clipped if needed (section 9); that is never a stop.
13. **Order invariance.** For each fold's S and for θ_final(A), the orders (closes, reasons and targets) must be
    identical at 1x, at 2x and at every R4 book size (an order hash). Otherwise stop: it is a bug.
14. **Common start.** R_0, every shift, N0 and X must hold S's book at close t0 bit for bit, and R_0 must equal S on
    fold 0's kept rows bit for bit. Otherwise stop: it is a harness bug.
15. **Procedure controls (A0).** 3 or more false positives in the 20 negative-control panels: stop before any real
    bar and triage (bug or design). A design change is a new draft.
16. **hold-mix-cap ordering.** This plan is committed before anyone working on trend-steady reads hold-mix-cap's
    RESULTS.md. If that is not possible, the reading is logged in section 2 before run 0, and every change made after
    it is a named amendment.

**Amendments.**
- Dated, written in the plan's amendment section and committed before the run they affect.
- A0 and A1 are planned (synthetic, before any real bar).
- An amendment run k needs a line starting `- **Amendment run k` with the date, the reason, how the bug was found
  and the regression test.

**Deviations.** Every departure from the plan goes into a Deviations table in RESULTS.md: what changed, why, when
relative to which result, and its effect on any number.

**Not done in this study:**
- reading the test window;
- Nautilus, `lab/costs/`, MLflow, `strategies/`, `reports/<strategy>/` or `exports/`;
- hourly bars, intraday fills, other coins, leverage or shorting;
- USDC yield or depeg;
- volatility scaling, BTC/ETH rotation, crossovers, Donchian channels or ensembles (each would be its own
  pre-registration);
- tuning on validate, or a second look;
- edits to `config/*.yaml`, `lab/search`, `lab/validation` or the gates;
- setting, proposing or justifying a drawdown budget from this study's numbers.

## 16. Outputs

**RESULTS.md, whatever the verdict.** Both seeds, every number labelled SCOUTING with placeholder costs.
- **The verdict and headline,** with E1-E9, P, the gate table and R1-R5.
- **Per fold:**
  - the chosen L and δ, the neighbourhood and the raw best;
  - IS and OOS Sharpe, and walk-forward efficiency;
  - switches per coin, limit fixes, orders and the most orders in any 30 days;
  - time in the market per coin;
  - turnover, costs paid, return, max drawdown and worst day;
  - the number of −10 trials.
- **Stitched:** S, R_0, N0, X, B1, B2 and N0-span. The shifts as 5/50/95 percentiles with R_0's rank p. S at 2x and
  on Binance. Folds 1-4 on their own, comparable row for row with rebalance-steady.
- **The R_0 − S difference:** the turnover S's stitched curve never paid at the 4 fold boundaries.
- **The boom-year and leave-one-year-out tables:** E1, E2, Δ_y, G7 and the plateau with each bar-year removed, and
  with the best and the two best BTC years removed.
- **The two bear years together** (description, reported whatever it shows): Δ, D and E1's rank p with both 2018
  and 2022 removed, i.e. what the timing did in 2019-2021 alone. E6 survives losing either bear year; this row
  shows how much of the edge, if any, lives in the two of them.
- **An episode table:**
  - each out-spell per coin, with the coin's return while S was out (the loss avoided);
  - whipsaws (switches reversed within 4 weeks), with their count, share and cost;
  - the regret against N0 in each rally.
- **DSR** with the effective, raw and strict counts.
- **PBO** per study, with the distribution of each study's PBO logits (5/50/95 percentiles and the share ≤ 0).
- **Monte Carlo** (descriptions next to G6's statistic):
  - the block bootstrap at mean blocks 20 and 60;
  - a trade-period shuffle;
  - degraded execution (+10 bps per unit of turnover, 1000 simulations, seed 0).
- **Trades per parameter:** kept fill rows / 2, flagged below 30 (expected to be flagged).
- **Descriptions:**
  - the daily-check variant (did checking more often pay?);
  - s = 0.30 and 0.70;
  - the six other check weekdays;
  - B3-lead (the 52 excluded lead offsets, as a lead/lag profile, never a null);
  - the block-20 E2;
  - the opposite-start check (the first close from which the two state paths agree, for every chosen
    configuration; whether they still differ at any fold's t0).
- **Risk descriptions:**
  - R2-R5;
  - θ_final(A) over all of train, labelled **IN-SAMPLE**: max drawdown, Monte Carlo p5 and p50, worst day,
    highest coin and lowest cash weight, legs a year and leg sizes in USD;
  - one sentence that the stitched S mixes per-fold configurations, so its drawdown is not that of any one shippable
    configuration.
- **Correlations** of S's daily returns with B1, B2, N0, and rebalance-steady's stored stitched S_A (train only).
- **Every failure.**

**Files:** as in section 14.

## 17. Code to build, and its tests

Built by `quant-researcher`. Everything is tested before any number counts (hard rule 11): 100% branch coverage of
`lab/`, the deep profile, and ruff.

**`lab/runner/trend.py`** (new; about 300-400 lines):
- `SPECS`, `HEADROOM = 0.02`, `R0 = 199`, `S_SHARE = 0.50`;
- `sma_distance(close, L)`, computed per window;
- `check_closes(index, weekday, start_row)`;
- `trend_states(bars, L, delta, *, weekday=0, start="out")`: point-in-time state arrays per coin;
- `run_states(bars, states, *, s, f, limits, costs)`: the **one executor**, through `portfolio._simulate`. It
  records states, reasons (switch or limit fix) and the order hash in `attrs`;
- `trend_backtest(params, bars, *, limits, costs, ...)`: the `BacktestFn`, bound with `functools.partial`;
- `stitched_schedule(...)`;
- `shifted(schedule, u)`;
- `run_span(...)` (R_0 and the shifts);
- `always_in_n0`, `exposure_x`;
- `plateau_steps`;
- `power_count`;
- `loyo` and `boom_years`;
- `rolling_order_count` (R1);
- `active_report(studies, out_dir, first_row=204)`: the active-row trial Sharpes, effective counts, PBOs and DSRs
  (section 14). With `first_row=0` it must equal `overfitting_report`'s numbers bit for bit (tested).

It reuses `steady.panel_hash`, `fold_window`, `kept_returns`, `buy_and_hold_b1`, `fifty_fifty_b2`, `regime_table`,
`regime_split`, `e1_rank`, `paired_bootstrap` (with `mean_block`), `report_trial_sharpes`, `study_pbo` and
`stable_neighbours` unchanged. `lab/search` and `lab/validation` run unchanged.

**`research/trend-steady/`:** `study.py`, `run_train.py`, `freeze.py`, `run_validate.py`, `controls.py` (A0) and
`throughput.py` (A1). They carry rebalance-steady's guards as they now stand:
- dirty-tree refusal and the pinned folders;
- the start record and RUNLOG before any bar;
- the config hash;
- the amendment rules;
- look-once;
- FROZEN.json checked against `summary.json`;
- dry runs that never write into the repo.

Plus the branch guard and stop rules 12-16.

**Tests** (TESTING.md section 7):
- **Tamper the future.** On `sma_distance`, `trend_states`, the targets and `trend_backtest`'s returns: every field
  of both assets from the cut on, except the fill open. Hypothesis, with `@example` cuts at R0 and at a check close.
- **Touch the present.** Lowering close t changes SMA and m at t; at a check close it can flip the state at t, never
  at t − 1.
- **Hand-built paths** (`make_panel` of `make_bars` paths):
  - exact switch closes across +δ and −δ (strict at exactly representable boundaries);
  - the Monday anchor and a missing Monday;
  - activation at row 199 and at max(199, L − 1) for L > 200;
  - start out;
  - one coin switching re-cuts the other;
  - a breach between checks fixed at the next open;
  - a switch and a breach on the same close giving one order;
  - the 2-day row of 2018-01-13 on a rebuilt grid.
- **Known answers:** SMA and m by hand; R1's rolling count by hand.
- **Identities:**
  - always-in states equal `portfolio.rebalance` with band 1.0, every 1, the limits and h, bit for bit;
  - shift 0 equals R_0;
  - R_0 equals S on fold 0's kept rows;
  - H0 equals `walk_forward_optimize(warmup=2190)`'s `oos_returns` bit for bit (`n_workers = 1`, a few trials);
  - nulls equal S's book at t0;
  - orders are equal at 1x, 2x and every book size.
- **Live/batch parity:** a streaming state machine fed one bar at a time equals `trend_states` on every bar.
- **Shift invariants** (hypothesis):
  - a shifted schedule keeps the count of each state pair and the multiset of spell lengths, up to the splice;
  - it never reads a price (tampering prices leaves the schedule unchanged);
  - its offsets are exactly u = G + 1 .. W − 1 with G = 52 (207, 155 and 25 offsets for W = 260, 208 and 78), and a
    span with W ≤ G + 1 raises;
  - no lead offset u = 1..52 ever enters E1, E7, E8 or E9 (see the oracle test).
- **Thresholds at their boundaries:**
  - E1 ties count against S;
  - the E2 p at exactly 0.05 fails;
  - Δ − Δ_y = 0 fails;
  - 19 switches fail P and 20 hold;
  - a 0.7× weekday step holds, and E5(b) fails whenever Sharpe(S) ≤ 0;
  - E7's year ranking with ties.
- **Calibration (slow):** the E1 false-positive rate on iid driftful panels at (50, 0.02) and (200, 0.10), at most
  18 of 200 each (section 9).
- **Oracle:** on a pinned synthetic panel, a schedule that is in a coin exactly when that coin's next check-to-check
  return (open after the check to open after the next) is positive ranks above every guarded shift (rank p =
  1/208) and E1 holds; replacing the series of any lead offset u = 1..52 with arbitrary values changes no E1, E7,
  E8 or E9 number.
- **Active-row report:** `active_report` equals `overfitting_report` bit for bit with `first_row=0`; on a small hand
  matrix with shared zero rows its DSR, effective count and PBO equal a hand computation on the cut rows; G3 and
  G4 fail when either reading fails.
- **X clipping:** ē outside the limits is scaled by the largest passing λ (by hand), marked "clipped", never a stop.
- **Recompute tests:** every reported number in `summary.json` and `look.json` rebuilt from its inputs.
- **Guards:** every guard, including the branch guard and stop rules 12-16.
- **Hand breaks:** each deliberate break of `trend.py` and of the scripts fails a test, as in bugs #43-#47.

## 18. Known weaknesses

1. **Hindsight, and no truly fresh window** (K1, K2, K7). "Trend cut the 2018 and 2022 falls" is close to certain in
   advance, and proves little. E1, E2, E6 and E7 limit the damage but cannot remove it.
2. **Few independent bear markets.** The edge, if any, rests on two (2018 and 2022). Five out-of-sample years are
   too short for DSR ≥ 0.95 to pass even a real edge often (TESTING.md section 4). Expect INCONCLUSIVE or NO EDGE
   more often than EDGE.
3. **Fold 0 is thin and odd.** It is chosen from about 162 tradable rows of the 2017 bubble, with `min_trades`
   pushing it toward faster rules. Every study's first objective block is zero (section 6).
4. **Whipsaw and lag.** These are exposed in the sideways 2019, after the V-shaped March 2020 crash, and around the
   2021 tops. Weekly checks exit after fast crashes, not before. No daily-close rule avoids a one-day crash (the bar
   of 2020-03-12, K2).
5. **Big one-shot legs.** A switch sells a whole coin sleeve at once. Slippage above USD 10,000 is extrapolated, and
   H0's compounding book makes later folds' legs larger. Costs are unmeasured placeholders. 0x may charge a 0.15%
   fee on some pairs while `aggregator_fee_bps` is 0; the 2x stress bounds a 15 bps fee.
6. **All cash means all USDC.** Depeg risk (March 2023, inside validate) is not modelled, nor is cash yield (missing
   yield works against S).
7. **Exposure creep.** Without a trim, a long uptrend lets crypto drift up to the Steady limits (80% coins, 60% per
   coin) before a limit fix. "25% each when trending up" is the weight at entry, not a ceiling. R2 reports it.
8. **The two coins are highly correlated**, so their switches often coincide, and the shift null keeps that
   co-timing. A switch re-cuts the other coin, which mixes a little rebalancing in. The nulls share that machinery.
9. **The stitched S mixes per-fold configurations.** Its drawdown is not that of any shippable configuration, and
   θ_final's numbers are in-sample. R_0 pays the fold-boundary switches that S never pays.
10. **Scouting only.** The reference engine, exchange candles as a proxy for Base prices, decisions at 00:00 UTC
    only, and fills at the next daily open.
11. **G6 is MISSING and G8 fails by construction**, so CANDIDATE FOR AUDIT is out of reach in this study as the gates
    stand.
12. **Production.** A loss-limit pause, Approve mode, or per-trade and per-day caps can block the exit to cash, the
    one order that protects the customer (owner question 4). The auto-trading permission's caps must allow a full
    switch.
13. **The lead guard is a judgement.** G = 52 weeks clears the longest average (200 days, 29 weeks) by about half a
    year, but a spell that started within 29 weeks of a return and lasted another 24 weeks can still carry a
    trace of it into a 53-week lead. That only makes E1 conservative; the slow calibration at the slowest corner
    (200, 0.10) measures it. The guard also removes 52 of 259 shifts and leaves E9 only 25.

## 19. Owner questions

Five questions, in plain language, each with a recommended default and why: see `OWNER_QUESTIONS.md` next to this
draft. If there is no answer, the default holds and is logged:
1. no budget → fixed settings at 50% crypto in uptrends (Branch F);
2. 100% USDC allowed when both coins are down;
3. weekly Monday checks fit "a few trades a month";
4. recommend letting exits to cash run during pauses (a product decision; the study is unchanged);
5. G8 stays literal.

Answers that change the plan, decided now:
- **Q2 "no"** (`max_coin_pct` also caps USDC): the all-cash state is forbidden and the rule cannot exist at Steady.
  This plan is withdrawn and nothing is run; a redesign is a new draft.
- **Q3 "no"** (weekly checks are not "a few trades a month"): withdrawn the same way. A slower check day cannot
  be picked from this draft's descriptions.
- **Q1** sets the branch (section 8). **Q5** chooses the literal G8 or the pinned G8-excess (section 10).
- Every answer, and every default that held for lack of one, is quoted with its date in PLAN.md's header before
  the commit. Q1 and Q5 count only if answered in writing before the commit; a later answer to either changes
  nothing in this study. A later "no" to Q2 or Q3 stops the study wherever it is; every trial already run stays
  logged and counted, and the stop is recorded in RESULTS.md.

## 20. Looks at the data

| # | Date | By | What was looked at |
|---|---|---|---|
| K1-K9 | before the plan | see section 2 | Prior looks, disclosed |
| A0 | reserved, before run 0 | `quant-researcher` | Procedure controls on 40 synthetic panels (no market data) |
| T1 | reserved | `quant-researcher` | Run 0: Kraken and Binance daily train bars to 2023-01-01 00:00 UTC |
| V1 | reserved | `quant-researcher` | The single validate look, only if E1-E8 and P hold |

**Validate-window looks used for trend-steady: 0.**

---

## Appendix A. How this draft was assembled (the judge's record)

Four sketches were written independently from four lenses: evidence, simplicity, luck and limits. Each was scored 1-5
on five criteria.

| Sketch | Evidence behind the rule | Simplicity and parameter count | Protection against luck and overfitting | Fit with Steady limits and AGENTS.md ("Settings ranges") | Feasibility on existing code | Total (of 25) |
|---|---|---|---|---|---|---|
| evidence (`sketch_evidence.md`) | 5 | 4 | 4 | 4 | 4 | **21** |
| limits (`sketch_limits.md`) | 3 | 3 | 4 | 5 | 4 | 19 |
| simple (`sketch_simple.md`) | 3 | 5 | 3 | 3 | 5 | 19 |
| luck (`sketch_luck.md`) | 3 | 2 | 5 | 3 | 3 | 16 |

**Why the scores.**
- **Evidence (the base).**
  - A literature-backed rule: one signal family, per-coin price-to-average, a buffer and weekly checks.
  - 2 parameters.
  - An exposure-preserving whole-span rotation null and an always-in null.
  - A power precondition.
  - Fixed settings with a reason.
- **Limits.**
  - The best fit: the branch structure tied to the budget, the range top 0.60, the R1-R5 conditions, the boom rule
    built in, E3 against holding less crypto, and production exits during pauses.
  - Less simple: a drift trim, a closure over the full panel, custom scored rows and folds.
- **Simple.**
  - The leanest and most feasible.
  - But a BTC-only signal drives ETH, and daily checks sit awkwardly with the owner's guardrail ruling.
  - Its null shuffles spells only within a year.
- **Luck.**
  - The strongest controls: 5 folds with both bears out of sample, harness H0 with a common start state,
    leave-one-year-out, a power floor, procedure controls, and the AGENTS.md grid-timing gap.
  - But 4 searched parameters (s and f weakly identified).
  - 100 bootstrapped null markets (about an hour of compute and 2-3 GB).
  - A strict count of N_raw + 82.

**Grafted onto the evidence base:**
- **From luck:**
  - 5 one-year folds (both bear years out of sample);
  - harness H0 (`warmup=2190`) with the common start state;
  - E6 leave-one-year-out (decisive);
  - the power floor of 20 switches in ≥ 4 folds, with low power never rescuing a failure;
  - the synthetic positive and negative procedure controls (A0);
  - Binance on folds 1-4;
  - the out-of-sample S(s_k) check for a grid in Branch R.
- **From limits:**
  - Branch F/R fixed before any result, with a branch guard;
  - s ≤ 0.60 in Branch R;
  - exhaustive weekly shifts instead of random offsets;
  - E2 at mean block 60;
  - E3 against an exposure-matched mix (decisive);
  - the owner's boom rule as E7 and in G7;
  - R1-R5;
  - the pauses risk and the production notes.
- **From simple:** s = 0.50 fixed; one shared executor for S and every null; the order-hash invariance stop; the app
  wording.
- **From evidence itself:**
  - R_0 as E1's statistic, so the null and the rule differ only in timing;
  - E9 not requiring a validate win over N0;
  - the daily-check variant;
  - the slow calibration test of E1.

**Not taken, and why:**
- **The 100 bootstrapped null markets (luck).** Long bear markets are themselves trends, so markets without long
  trends cannot tell "crypto trends" from "this sample had two long bears". With positive drift, a trend rule loses
  to always-in there, so N2 is nearly implied by E2 at large cost. Calibration of the procedure is kept, on synthetic
  panels (A0) and in the slow test.
- **The drift trim (limits).** It adds a rebalancing component and a pinned constant to a trend test. Exposure creep
  is reported instead (R2), and the app wording says "at entry".
- **A BTC-only signal and daily checks (simple).** "Moves to cash in downtrends" reads per holding. Daily checks need
  the owner's "shown to pay" test, so they are reported as a variant.
- **Searching s and f (luck).** They are weakly identified, and a range cannot be pre-registered without a budget.
- **Scoring from row 250 with a full-panel closure (limits).** H0 gives the same path independence with the lab's
  harness unchanged.

## Appendix B. Checks run for this draft (no market data)

Run from the scratch folder with the repo's `.venv/bin/python -B` and `PYTHONDONTWRITEBYTECODE=1`. Nothing was written
in the repo: `git status --short` showed only the other workflow's three entries before and after.
- **`judge/grid.py`:** the date grid rebuilt from DATA.md's counts (2190 closes, 2018-01-13 dropped) and
  `walk_forward(2190, 365, 365, expanding=True)`. It gives:
  - the fold table of section 7;
  - row 199 = 2017-07-20; the first Monday check = row 203, 2017-07-24;
  - 313 Mondays in train, at most 5 in any 30 days;
  - W = 260 check closes deciding kept fills, 52 per fold; with the lead guard G = 52 (added by the audit), E1 uses
    207 shifts, E8 155 (W = 208) and E9 25 (W = 78);
  - Binance row 199 = 2018-03-05, a Monday;
  - validate: row 2190 = 2023-01-02, with 78 decision Mondays from 2023-01-02 to 2024-06-24.
- **`judge/feas.py`:** `risk_limits("steady")` gives min_cash 0.2, max_coin 0.6, budget `TBD` → None, SHA-256
  `158d7c9f…`. All 20 target sets for s ∈ {0.30, 0.40, 0.50, 0.60, 0.70} × 4 states pass `check_targets` with h =
  0.02.
- **Timings:** quoted from the sketches' synthetic stand-ins (`timing_out/timing.json`: one 2190-row backtest 0.0131
  s, a 200-trial study 5.80 s; `standin_timing.py`: 5.84 s; the luck sketch: 5.96 s).
- **Audit checks (synthetic only; `audit/` in the scratch folder, run with the repo's `.venv/bin/python -I -B`, nothing
  written in the repo):**
  - `judge/grid.py` rerun: the fold table, W = 260 (52 per fold), Binance row 199 = 2018-03-05 and the 78 validate
    checks reproduce.
  - `audit/shift_null_check.py`: iid Gaussian random walks (daily mean 0.001, sd 0.04), one coin, weekly checks from
    row 203, no costs, 400 panels per point. E1 pass rate with all 259 offsets / with the guarded 207: (50, 0.02)
    2.8% / 5.5%; (200, 0.10) 0.0% / 5.0%; (20, 0.005) 6.0% / 6.8%. Share of lead offsets 1-52 at or above R_0: 57%,
    74% and 51%; of delays 1-52: 49%, 50% and 48%.
  - `audit/dsr_zero_rows_check.py`: 200 box points on 20 random walks per length; the variance of trial Sharpes on
    all rows over that on rows 204.. is 0.439, 0.720, 0.813, 0.860, 0.888 and 0.906 at 365, 730, 1095, 1460, 1825
    and 2190 rows, equal to the active share.

## Critique log (backtest-auditor, 2026-11-21)

An independent pass that tried to break this draft as a pre-registration. Nothing was read from the catalog,
`data/`, `results/` or the test window; no real-price statistic was computed. The only runs were synthetic (appendix
B, "Audit checks"). Nothing was written in `/home/user/osprey`; `git status --short` there showed only the other
workflow's entries before and after.

### Fixed in this draft

| # | Severity | Issue found | Fix (where) |
|---|---|---|---|
| C1 | Blocking: luck control invalid | E1's circular shift null used every offset u = 1..259. For u = 1..52 the shifted schedule holds, at week k, the state the rule takes u weeks *later*, set from prices that include the returns it then earns (a 200-day average spans 29 weeks; hysteresis carries states further). These are look-ahead copies of the signal. On synthetic random walks 74% of them beat R_0 at (200, 0.10) and E1 never passed (0.0%), so E1 was far too strict under the null, lost power under a real trend, and the draft's own two-sided calibration band would have failed. The same flaw sat in E7 (same offsets), E8 (207 of 207 offsets), E9 (77 of 77) and the A0 power estimate | Lead guard G = 52 weeks: the null uses u = 53..W−1 only, i.e. 207 shifts for E1 and E7, 155 for E8 (W = 208), 25 for E9 (W = 78). Delays of 1-52 weeks stay (they read only past prices). Guarded E1 passed 5.0-6.8% under the null in the synthetic check. Sections 0 (plain words), 1, 9 (B3 row), 11 (E1, E8, E9), 12 (EDGE wording), 13, 17 (offset and oracle tests), 18 (weakness 13), appendix B |
| C2 | Blocking: mislabelled description | B3-fold (circular shift within each 52-week fold, offsets 1..51) was described as "within-year timing", but every one of its offsets leads the schedule over part of the year, so it measured look-ahead, not timing | Replaced by B3-lead: the 52 excluded lead offsets reported as a lead/lag profile, never a null and never in any criterion (sections 9, 14, 16) |
| C3 | Blocking: gate measured leniently | Every search study starts at row 0 (H0), and rows 0-203 are 0 for every trial. Trial Sharpes shrink by √(active share), so the trial-Sharpe variance behind DSR's luck benchmark was understated (synthetic: exactly the active share, 0.44 in fold 0 to 0.91 in the final study, about a fifth pooled): **G3 too lenient**. PBO halves made only of zero blocks tie every trial, which the tie rule scores as overfit (G4 pushed up; direction not guaranteed in every study) | Active-row reading (rows 204 .. end) of trial Sharpes, effective counts, PBO and DSR; G3 and G4 must hold in both readings (stricter of the two; thresholds unchanged). New `active_report` helper with a bit-for-bit test against `overfitting_report` at `first_row=0` and a hand-computed case (sections 6, 10, 14, 17) |
| C4 | Blocking: unset threshold | The slow calibration test said "within the binomial band of 5%" with no band, one parameter point, and no generator settings; a two-sided band would also fail a valid but conservative test | Two pinned points, (50, 0.02) and the slowest corner (200, 0.10); generator fully pinned (means, sds, correlation, seeds, bar construction); 200 panels each; passes if at most 18 of 200 pass E1 (P = 0.6% at a true 5%); a rate far below 5% is reported, not failed. Cost stated: about 9 CPU-minutes per point (section 9, 17) |
| C5 | Blocking: undefined case | E5(b) "≥ 0.7 × Sharpe(S)" passes a worse weekday when Sharpe(S) ≤ 0 | E5(b) also requires Sharpe(S) > 0, as G5 does; boundary test added (sections 11, 17) |
| C6 | Blocking: outcome treated as a bug | X's exposure-matched targets come from S's realised weights, yet a `check_targets` refusal was a stop "for a bug", which would turn a data outcome into an amendment run | If ē fails the limits with h, X's targets are scaled by the largest passing common factor λ and marked "clipped"; never a stop. Stop rule 12 reworded; test added (sections 9, 15, 17) |
| C7 | Ambiguity | E6's X_y and X collided with the comparator X used by E3 | Renamed Δ_y and Δ (sections 11, 16, 17) |
| C8 | Blocking: optional analysis could become the result | Nothing stopped a description (the daily-check variant as the owner's "shown to pay" evidence, another weekday, s = 0.30/0.70, Binance alone, folds 1-4 alone, a block-20 E2) from being promoted after results | "Descriptions never decide": none can change the verdict, headline, θ_final, settings, check day or s; "shown to pay" needs its own pre-registration listing these trials as prior looks; RESULTS.md opens with the mechanical verdict (section 12) |
| C9 | Blocking: AGENTS.md "Settings ranges" gaps (Branch R) | (a) Narrowing that would drop the default had no defined outcome. (b) The budget and allowed values could be set after hold-mix-cap's RESULTS.md (static-mix drawdowns on the same years) without that look being listed, which "Settings ranges" requires | (a) The range fails; never re-centred, never cut to fixed settings. (b) Branch R condition 4: section 2 lists everything the owner and `risk-officer` had seen when setting the budget and values (section 8) |
| C10 | Blocking: rules that could be set after results | Owner question 5's alternative G8 was described only in words, so it could be defined after results. The consequences of "no" to Q2 or Q3, and of late answers, were undefined | G8-excess pinned (`regime_split` with N0 as benchmark: excess_total > 0 and no regime's excess above half); it replaces the literal G8 only if chosen before the commit; both always reported. Q2 or Q3 "no" withdraws the plan (or stops it wherever it is, trials kept and counted); Q1 and Q5 count only if answered before the commit (sections 10, 19) |
| C11 | Trial-count gap | The R4 wallet-size reruns (cost variants of θ_final with identical orders) were "not counted", while the 2x cost variants were | The 4 sizes other than USD 10,000 join the strict count: N_raw + 29 (Branch F), N_raw + 49 (Branch R) (sections 12 R4, 14) |
| C12 | Regime concentration not visible | E6 survives dropping either bear year, but nothing showed how much of the edge lives in 2018 and 2022 together | Description added, reported whatever it shows: Δ, D and E1's rank p with both bear years removed (section 16) |

### Checked and found sound (no change)

- **Look-ahead in the rule.** SMA over rows t−L+1..t includes close t, the decision is at close t and the fill at
  the open of t+1 (hard rule 4; the engine in `portfolio._simulate` fills orders decided at close t at the open of
  t+1 and never fills the last close's order). Activation A = max(199, L−1) gives the same first check (row 203,
  2017-07-24) for every L in the box. No indicator is fitted; X's ē and the G8/E7 labels are ex post but feed only
  comparators and row removal.
- **Folds and purge.** `judge/grid.py` rerun on a price-free date grid: training ends at t0−1, kept rows start at
  t0+1, so no training return touches a kept row; no labels, so no purge is needed. 52 checks per fold, 260 in all.
- **No validate or test bars before the rules allow.** Every train-phase run ends at close 2023-01-01; the validate
  panel is loaded only at the earned look; nothing requests a close after 2024-07-01 00:00 UTC.
- **Order invariance across costs and book size.** Costs are shared pro rata, so weights after a fill equal the
  targets whatever the costs; the order hash (stop rule 13) is a sound check.
- **Costs at small books.** `Costs.slippage` is flat at 10 bps below USD 100 and extended at 15 bps a decade above
  USD 10,000; a USD 2,500 leg costs about 26 bps as stated; `stressed()` doubles gas too; at USD 100 gas is 0.1% a
  leg, far from the engine's cannot-pay refusal.
- **Steady limits.** The 4 target sets sit well inside the limits with h = 0.02; the all-cash state depends on the
  per-coin reading of `max_coin_pct` (owner question 2, now with a defined "no" outcome).
- **Feasibility.** Train phase about 1-2 CPU-minutes of search plus seconds of nulls; bootstraps are vectorised;
  A0 about 20-30 CPU-minutes; the pinned calibration adds about 18 CPU-minutes to the slow tier.
- **Branch F against AGENTS.md.** No budget, so no range; θ_final(A) is gated where the "Settings ranges" table
  names the default (G5(b), G7, G8), and its runs are labelled in-sample.

### Residual notes (not blocking; left for the reviewers)

1. **G7's boom-year removal mostly helps a trend rule.** Removing 2019 and 2020 hurts buy-and-hold far more than a
   rule that sits out 2018 and 2022. It is the owner's rule as written; E7 (E1 and E2 without those years) is the
   check with teeth.
2. **E9 is weaker than before.** Its 25 guarded validate shifts are mostly delays of 1-25 weeks. The draft's 77
   shifts were biased toward rejecting by the leads, so this is a correction, but E9 can now reject less.
3. **K4 counts as 1.** The dip study's LightGBM also used the 15 lab features (`ret_20`, `ret_60`, `ma_dist_20`,
   `ma_dist_100`, `eff_ratio_20`), inside dip events only. One look is a defensible count; reviewers may prefer more.
4. **The objective's zero blocks still distort selection.** The fix above covers DSR and PBO only; the search
   objective (unchanged `lab/search`) still scores blocks that are all cash. This is disclosed (section 6), and
   changing it would mean editing `lab/search`, which the plan rules out.
5. **The guard G = 52 is a judgement** (weakness 13): it removes the leak shown in the synthetic check, and the slow
   calibration at (200, 0.10) is the standing test that it stays removed.

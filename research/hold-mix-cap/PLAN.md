# hold-mix-cap: pre-registration

Written 2026-11-21 by `quant-researcher`, **before any result exists**. Repo HEAD at writing `2aa8dcc` (branch
`claude/tender-brown-g86h44`), clean tree. None of this study's code exists yet (section 14 lists what to build). Data
snapshot `1746a21b75683e76` (bars content hash `08f5ca2c…`), as recorded in rebalance-steady's DATA.md and
RESULTS.md. The catalog was not opened for this plan, and no price was read.

Revised the same day after a review, **still before any result** and before any code: amendments A1-A4 (section 13).
The main change (A1): the first buy does not start the wait; the wait runs only between rebalances. After the build's
code review, still before any run on real data: A5 (the owner's boom-year check, as an addendum) and A6 (logging and
smaller fixes).

> **SCOUTING ONLY.** Every number this study produces comes from the lab's reference portfolio engine
> (`lab/runner/portfolio.py`, driven by the new `lab/runner/holdmix.py`), not from NautilusTrader (AGENTS.md hard
> rule 3). It uses the **placeholder** costs of `config/costs.yaml`, and exchange candles (Kraken in USD, Binance in
> USDT) stand in for Base prices. Every table is labelled SCOUTING. Nothing goes into `reports/<strategy>/`,
> `strategies/` or `exports/`.

## In plain words

The app will offer "hold this mix", a tool the customer runs on their own wallet (owner, 2026-11-20 and 2026-11-21;
`docs/app/features.md`, "Hold this mix"). The customer picks:
- how much of the wallet is crypto (the **crypto share** s; the rest stays in USDC cash);
- how the crypto is split between BTC and ETH (the **BTC share** f of the crypto);
- a **drift band** b: "trade back to the mix when a coin is more than b off its target";
- a **cap**: at most N rebalances a month, kept as a wait of at least W = ceil(30 / N) days between rebalances (the
  first buy is not a rebalance and does not start the wait).

The app trades the wallet back to the mix when a coin leaves its band, and always when a Steady limit is hit (cash
under 20% or one coin over 60%). The owner asked the lab to **recommend a number for the cap**, "based on our data
and sims", and left open whether Steady should also keep a **hard upper limit** on rebalances a month above the
number the customer sets. On how the cap is enforced, the owner said "you decide" (2026-11-21), so the readings this
plan needs are the lab's decisions (section 16).

This study simulates the tool on 2017-2022 prices for a fixed grid of mixes, bands, caps, wallet sizes and two cost
levels. Each run covers one 12-month stretch (60 of them) or the whole six years. Rules fixed in this file, before
any run, then produce:
1. a recommended **default drift band**;
2. a recommended **cap** for that band, and for every other band the app might offer;
3. evidence for the owner on a **Steady upper limit**: the number of rebalances a month above which more
   rebalancing hardly keeps mixes closer to their targets, for the fees it costs;
4. whether 1-3 change if costs are **twice** the placeholders, or on a **second data source** (Binance).

The rules pick what keeps mixes near their targets with few rebalances and low fees. **They never pick by return.**
Returns, Sharpe ratios and falls are reported as descriptions only. They are in-sample and hypothetical (simulated on
past prices). Between bands and caps, the differences in return and fall are expected to be small; the crypto share is
expected to move the worst fall the most (rebalance-steady: in its in-sample searches the median worst fall went from
about 29% at 20-30% crypto to about 69% at 70-77% crypto; RISK.md section 3). The first Steady study also found that
rebalancing timing added nothing (research/rebalance-steady/RESULTS.md). This study is not a strategy test, approves
nothing, claims no edge, and sets no limit and no drawdown budget. The owner decides what the app recommends and
whether Steady keeps an upper limit.

It reads the **train years only** (bar closes up to and including 2023-01-01 00:00 UTC). The validate window
(2023-01-01 to 2024-06-30) and the test window (from 2024-07-01) stay unread, so later Steady strategies can still use
them.

## 1. Question and expectations

**Question.** For the tool as decided (section 4), which drift band and which cap keep a customer's mix near its
target with few rebalances and low fees? Above which cap does allowing more rebalancing stop buying closeness to
target for its fees?

This is not an edge hypothesis. The study measures how a fixed rule behaves; it does not test whether it beats
anything. The template's "what would prove it wrong" becomes "what would change the product".

**What we expect** (written now, so a surprise is visible):
- Wider bands need fewer rebalances. Each halving of the band should multiply rebalances by about 3 to 4.
- With no cap, a mix is outside its band only on the closes where it breaks out, because it is traded back at the
  next open. A cap adds days outside the band only when the band breaks again before the wait is over. In calm years
  a cap of 1 or 2 a month should hardly ever bind; in busy years (2017-2018, 2020-2021) it will.
- Mixes close to a Steady limit will be traded by the limit often, whatever the cap. With 78% crypto, cash sits 2
  points above the 20% floor, so a crypto rise of about 13% against cash since the last trade forces a trade. With
  one coin at 52.5%, a rise of about 36% against the rest of the wallet does it.
- The decisions do not depend on costs or wallet size (section 4.6), so doubling costs moves only the fees.
- The worst fall grows with the crypto share far more than with the band or the cap.

**What would change the product** (each is reported, none is a failure of the study):
- No band meets rule A's conditions (section 9). The app would then have no evidence-based default band.
- The recommended cap for the default band is more than a few a month, which conflicts with Steady's "a few
  trades a month".
- For some mixes, limit hits break through the cap often. "A few trades a month" then cannot be promised near the
  limits, and the app should say so next to those mixes.
- Kraken and Binance, or 1x and 2x costs, give different recommendations (rule D).

## 2. Prior looks (disclosure)

These years have been looked at before, by this desk, with a rule of the same family. Everything this plan's author
read is listed, so the reader can judge how much the choices below could have been steered.

| # | When | Who | What was seen | Bearing on this study |
|---|---|---|---|---|
| L1 | 2026-11-20 18:07 UTC | `quant-researcher` (rebalance-steady run 0) | Kraken and Binance daily BTC/ETH train bars, 2017-2022: 2000 search trials and 3158 evaluations of a band rebalancer with the same targets, the same limits, h = 0.02, the same engine and costs | The same bars and years, re-read here |
| L2 | 2026-11-21 (this plan) | this plan's author | rebalance-steady RESULTS.md and RISK.md in full. In particular: the chosen relative bands 0.33-0.50 (checked every 4-9 days) rebalanced 3 times in 2019-2022, 0-2 times a year; the limit-only comparator B5 (34-55% crypto, bought fresh each year) traded once per seed, in 2021; θ_final (s 0.20 and 0.29, b 0.44 and 0.50, every 30 and 31 days) made 3.00 legs a year over 2017-2022 in-sample, its cash never fell below 57.7% and 42.3%, and no close was in breach; at that turnover costs hardly mattered (Sharpe 0.938 at 1x, 0.936 at 2x); a book with about 45% crypto lost 15.35% on its worst day (the bar of 2020-03-12); in-sample drawdowns grow steeply with s | Says roughly how often wide bands trade in these years. It shaped the grid's band and cap ranges and the thresholds of section 9 |
| L3 | 2026-11-21 | this plan's author | `docs/app/features.md`, which quotes rebalance-steady's final-study trial log (in-sample, 2017-2022): median Sharpe 1.50 for settings rebalancing less than once every 4 months (352 trials), 1.32 at 1-3 a month (6), 1.24 at 3-6 a month (6), 1.25 at 6 or more (3); the busiest trials (daily checks, a band of about 2% of the coin share, i.e. b ≈ 0.02) rebalanced on 697 and 757 of about 2,190 days, about 10 times a month | Says that very narrow bands with daily checks trade about 10 times a month in these years. That is why the narrowest band here is 0.05 and the loosest finite cap is 8 a month |
| L4 | 2026-11-21 | this plan's author | rebalance-steady PLAN.md (including its section 2 quotes of the dip-timing study: two BTC/ETH/USDC mixes on train and validate, random-entry Sharpe percentiles) and DATA.md (coverage counts and close dates, no prices) | Row counts and dates (section 3) come from DATA.md. The dip-study numbers are returns, which no rule here uses |
| L5 | inherited | dip-timing study | Its looks D0-D1a (rebalance-steady PLAN.md section 15), including its single validate look (Kraken bars to 2024-07-01) | Not looks by this study. This study reads no validate bar |
| L6 | inherited | `data-engineer` | The data quality reports (largest single-bar moves per series, some in the test window; rebalance-steady P3). **Not opened for this plan** | None |
| L7 | always | everyone | General knowledge of the public price history (the 2017 bubble, the 2018 crash, March 2020, the 2021 rise, the 2022 bear market) | Shapes priors and cannot be undone |
| L8 | 2026-11-21 | this plan's author | A timing run of a stand-in for the rule on **synthetic** data (section 11); `config/*.yaml` read for the limits and costs | No market data |
| L9 | 2026-11-21 | the plan's reviewer | A review of this plan, with an illustration of the two first-buy readings on **synthetic** prices: at b = 0.20 and W = 60, the median extra days out of band were 6.5 against 15.0 a year; at W = 120, 41.2 against 62.8 | No market data. It showed that the reading can move N\*(b), which is why A1 fixes the reading by the recorded decision, not by any number |

Not read for this plan: rebalance-steady's AUDIT.md, `trials.csv`, `evaluations.csv`, anything under `results/`, and
the catalog.

**What this means.**
- **Counted honestly: 0 looks at this study's grid.** No number of this study exists. The thresholds in section 9
  were fixed knowing roughly how often bands of 0.02 and 0.33-0.50 trade in these years (L2, L3). They were not
  computed on any data.
- The decision rules use no return, so what L1-L3 say about returns cannot steer them directly.
- **Validate-window looks used by this study: 0, and it makes none.** Its runs end at the last train close.
- **This study becomes a prior look for later Steady work.** It computes the train-window returns of 6,804
  rebalancing configurations per 12-month window, plus 972 of the other first-buy reading (A1). A later Steady
  rebalancing strategy searched on train must list it as a prior look (its strict trial count should include the
  configurations it resembles). It does not touch validate or test, so those stay fresh for that strategy. To keep
  the footprint small, per-configuration returns, Sharpe ratios and drawdowns stay in the git-ignored
  `runs.parquet`. The tracked files and RESULTS.md show returns and Sharpe ratios only for the recommended settings and
  their comparators, and falls only in the falls tables of section 10.

## 3. Data

| Item | Pinned |
|---|---|
| Primary | Kraken daily bars, `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN`, through `lab.data.panel.load_panel("KRAKEN", "1d", last_close="2023-01-01 00:00 UTC")` |
| Robustness | Binance daily bars, `BTCUSDT.BINANCE` and `ETHUSDT.BINANCE` (quoted in USDT, not USD), the same call with `"BINANCE"`. The same rules are applied to it (rule D); nothing is chosen on Binance alone |
| Rows | Kraken: **2190** rows, closes 2017-01-02 .. 2023-01-01; close 2018-01-13 is dropped (no ETH bar), so the rows for 2018-01-12 and 2018-01-14 are adjacent. Binance: **1963** rows, closes 2017-08-18 .. 2023-01-01, none dropped; the 228 closes before 2017-08-18 do not exist (DATA.md). Any other count: stop and amend |
| Bars | Daily, closing at 00:00 UTC. One panel row is one close. Decisions at a close, fills at the next open |
| Never read | Any close after **2023-01-01 00:00 UTC**: neither validate (closes 2023-01-02 .. 2024-07-01) nor test. `last_close` is the last train close. `load_panel` refuses any bar a loader returns after `last_close` and any request after 2024-07-01; `run.py` also asserts `panel.index.max() <= 2023-01-01 00:00 UTC` on each panel before any backtest |
| Snapshot | Before loading bars, `run.py` reads `snapshot_id` and `bars_content_sha256` from `data/catalog/SNAPSHOT.json`. The bars hash must be `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e`; otherwise stop and amend |
| Panel hashes | `lab.runner.steady.panel_hash` of each loaded panel. rebalance-steady's run 0 recorded the same two calls as Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587`. Any other hash means other bars: stop |
| Slicing | Every run's slice is taken by **close time** (`panel.loc[first:last]`), never by row number across sources |

## 4. The rule

### 4.1 In plain words (the version the app would show)

Once a day, at the daily close, the tool looks at the wallet.
1. If cash is under 20% or one coin is over 60% (the Steady limits), it trades back to the mix, that day, whatever
   else is true.
2. Otherwise, if its last rebalance was less than W days ago, it waits. The first buy is not a rebalance, so it does
   not start a wait.
3. Otherwise, if BTC or ETH is more than b off its target (as a share of that target), it trades back to the mix.
4. Otherwise, with the optional reset, if it has not traded at all (first buy included) for R days, it trades back to
   the mix.

"Trades back to the mix" means one rebalance, which swaps whatever coins it needs to. W comes from the cap: at most N
rebalances a month means a wait of W = ceil(30 / N) days.

**How the app should word the cap.** The wait guarantees at most N rebalances in any 30 days (for N of 1 or more),
apart from limit fixes, not N per calendar month. With a cap of 1 (W = 30) the tool can trade on the 1st and the 31st of
a 31-day month, and with a cap of 2 (W = 15) on the 1st, 16th and 31st. So the app should say "at least W days between
trades back to the mix" (or "at most N in any 30 days"), plus "a Steady limit hit can add trades".

### 4.2 The rule exactly

Inputs:
- targets T_BTC = s·f and T_ETH = s·(1 − f); cash 1 − s, in USDC;
- the relative band b ≥ 0;
- the wait W = `wait_days(N)` days: ceil(30 / N) computed in exact decimal arithmetic (`Fraction(30) /
  Fraction(str(N))`), so 30 / 0.3 gives 100; no cap gives W = 1;
- the optional reset R days (None = no reset);
- the Steady limits `min_cash` and `max_coin`, read at run start with `lab.runner.portfolio.risk_limits("steady")`
  from `config/risk_levels.yaml`, never typed (today 0.20 and 0.60). `run.py` refuses to start (exit 2) unless both
  are numbers, as `steady.py` refuses a level without both, so a key missing from the file can never run the study
  without a Steady limit;
- **how the limits are read:** `min_cash` is a floor on USDC; `max_coin` caps BTC and ETH **each on its own**. It does
  not apply to USDC, and not to the two coins together. This is the lab's reading (`portfolio.risk_limits`; RISK.md
  section 1). The owner has not confirmed it (features.md, the open Steady-limits questions). Section 9's
  descriptions show what the other readings would keep;
- the headroom h = 0.02 (`HEADROOM`, a required key of `hold_mix`): every target must pass
  `portfolio.check_targets(T_BTC, T_ETH, min_cash=, max_coin=, headroom=0.02)`, i.e. cash target ≥ min_cash + h and
  each coin target ≤ max_coin − h, up to `LIMIT_TOL` = 1e-9.

The rule keeps two clocks:
- `last_any` = the close time of the most recent order of **any** kind, the first buy included. Only the reset reads
  it.
- `last_reb` = the close time of the most recent **counted** order (limit, band or reset). It is empty until the first
  counted order, and while it is empty no wait runs. The wait reads only this clock (amendment A1).

At each close t of a run's slice (rows 0 .. n − 1), with w = the weights at close t (drifted by prices since the last
fill), the first matching step decides:

| Step | Condition at close t | Order | Reason | Counted as a rebalance | Restarts the wait |
|---|---|---|---|---|---|
| 1 | t = 0 (the book is all cash) | the targets | `first` | **no** | **no** (sets `last_any` only) |
| 2 | Breach: `portfolio._breach_test(min_cash, max_coin)(w)`, i.e. w_BTC + w_ETH > 1 − min_cash + 1e-9, or w_BTC > max_coin + 1e-9, or w_ETH > max_coin + 1e-9 | the targets, **even inside the wait** | `limit` | yes | yes |
| 3 | `last_reb` is set and ts[t] − `last_reb` < W days | none (a band break or a due reset is **held**) | | | |
| 4 | For BTC or ETH with target T > 0: `abs(w − T) > b * T` (strict) | the targets | `band` | yes | yes |
| 5 | A reset is set and ts[t] − `last_any` ≥ R days | the targets | `reset` | yes | yes |
| 6 | otherwise | none | | | |

Every order sets `last_any`; every counted order also sets `last_reb`. `hold_mix` and `path_metrics` call
`portfolio._breach_test` for step 2 and for "closes in breach", and use the same expression for the band, so the rule
and the metrics cannot disagree at a boundary.

- An order is always the **full target vector**. It fills at the open of row t + 1. Each coin's change is its own
  swap against USDC at that coin's open. A leg with zero change does not trade.
- **One order per close at most**, so one rebalance counts once, however many legs it swaps.
- The decision at the **last close** of a slice is never sent, so it is never counted.
- An order sent when the book is exactly at its targets trades nothing but still counts. On real prices this cannot
  happen (step 2 and step 4 need drift, and step 5 needs R days without any price move); such "empty orders" are
  counted and reported, and expected to be 0.
- A limit order sent while a wait is running (`last_reb` set and ts[t] − `last_reb` < W days) is flagged **inside
  the wait**. Before the first counted order no wait runs, so nothing there is inside the wait.

### 4.3 Edge cases (pinned)

- **A coin with target 0** (f = 0 or f = 1) is never out of band: step 4 skips it. The book holds none of it, so its
  weight stays exactly 0 and it can never breach `max_coin` either.
- **A breach and a band break on the same close:** one order, reason `limit`, counted once.
- **A band break and a due reset on the same close:** one order, reason `band`, counted once. (Only the label
  differs; the order is the same.)
- **A breach inside the wait:** ordered at that close, counted, flagged inside the wait, and the wait restarts from
  it.
- **The wait is counted in calendar days from the close of the last counted order** (the decision, not the fill),
  using the close timestamps: after a counted order at close time c, the next order that is not a limit order can be
  sent at the first close at or after c + W days. On a complete daily grid that is exactly W closes later (an order on
  day 0 with W = 4 allows the next one on day 4). Where a close is missing (Kraken 2018-01-13), the wait is still W
  calendar days, not W rows.
- **A held band break is not remembered.** At the first close after the wait, the band is judged on that close's
  weights. If the mix has drifted back inside its band, nothing trades.
- **The first buy** is ordered at close 0 and fills at the open of row 1. It is not a rebalance: it is left out of the
  rebalance counts, the leg counts and the yearly fees (its cost is reported separately). It does **not** start the
  wait: the wait runs only between rebalances (amendment A1, the lab's decision). So a band break or a breach at
  close 1 orders at close 1. This is what features.md records ("at least 30/N days (rounded up) between them", where
  "them" are rebalances, and the first buy is not one). The other reading (the first buy starts the wait) runs as a
  pre-registered description only (section 5).
- **The reset counts from the last order of any kind, the first buy included** (`last_any`): "if the tool has not
  traded for R days, it trades back to the mix". This is the one place where the first buy starts a clock. A reset
  that falls due while a wait is running (possible only when R < W) waits. Before the first counted order no wait
  runs, so the first reset can fall due R days after the first buy.
- **No cap** (N = none) is W = 1 day: every daily close may send an order.
- **Limits are judged at the limits themselves** (not at limit − h), at daily closes only, with the tolerance 1e-9 for
  round-off, exactly as `portfolio.rebalance` judges them.

### 4.4 Worked example (made-up numbers, not data)

s = 0.78 and f = 0.5, so BTC 39%, ETH 39% and cash 22%. b = 0.20, so each coin may sit between 31.2% and 46.8%. N = 2,
so W = 15 days.
- Day 0: the tool buys the mix (`first`, not counted). No wait starts, so an ordinary trade could come as early as
  day 1.
- Day 3: crypto has risen and cash is 19.6%, under the 20% floor. The tool trades back to the mix at once (`limit`,
  counted). It is the first rebalance, so no wait was running. The wait starts now: the next ordinary trade can be on
  day 18.
- Day 10: ETH is at 47.5%, outside its band. The wait holds it (a held close).
- Day 18: ETH is still at 47.1%, so the tool trades back (`band`, counted). The new wait runs to day 33.
- Day 25 (inside that wait): ETH is at 47.0% and cash at 19.8%. One order (`limit`, counted once, inside the wait),
  not two. The wait now runs to day 40.

### 4.5 Execution and costs (the engine)

`hold_mix` hands its decisions to `portfolio._simulate`, the engine `portfolio.rebalance` uses, unchanged:
- A decision at close t fills at the open of t + 1 (hard rule 4).
- Between fills the wallet holds coin units and cash, so weights drift with prices. Nothing is rebalanced for free.
- Each leg pays traded share × (pool fee + aggregator fee + slippage at the leg's own USD size) plus gas in USD per
  leg. The costs come from `Costs.from_yaml(capital_usd=V)` (1x) or `Costs.from_yaml(capital_usd=V).stressed()` (2x,
  k = `stress_multiplier` = 2.0 as read). Both are built once per cost setting at run start, never typed.
- The wallet starts at V USD in cash at close 0 of every run and compounds.
- A fill's cost is shared pro rata by the post-trade book, so the engine holds exactly the targets after a fill.
- **Gas is charged to the wallet**, as the engine does. In the app gas is sponsored (our cost, not the customer's),
  so the customer fees in section 8 leave it out and gas is reported on its own.
- A fill costing 100% of the wallet or more raises. At these sizes that cannot happen: the most gas a rebalance can
  cost is 2 × 0.20 USD at 2x, 0.08% of a 500 USD wallet, and under 1% even after that wallet has fallen 90%.

### 4.6 The decisions do not depend on costs or wallet size

After a fill the engine re-cuts the book to exactly the target weights of what is left after costs, and between
fills the weights drift by prices only. So the weights at every close, and with them every order of the rule, are
**the same at every wallet size and cost level** (unless a fill would cost the whole wallet, which raises).
Consequences:
- The closeness-to-target numbers and the rebalance counts (section 8) are identical across the 6 cost settings.
  Only fees and returns differ.
- At 2x costs, only the fee parts of the decision rules can move (rule D).
- `run.py` checks this on every configuration with a per-run hash of the orders, reasons, in-wait flags and weight
  columns, and stops if it fails (stop rule 8). (The other first-buy reading runs at one cost setting only, so this
  check does not apply to it.)

A live wallet pays each swap's fee out of that swap, so it lands a hair away from the targets. The headroom h covers
that at fills; it is not modelled.

## 5. The grid

| Dimension | Values | Count |
|---|---|---|
| Crypto share s | 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.78 | 7 |
| BTC share f | 0 (ETH only), 0.25, 0.50, 0.75, 1 (BTC only), where the targets keep h inside the limits | see below |
| Mixes (s, f) | 27 feasible pairs (table below) | 27 |
| Relative band b | 0.05, 0.10, 0.15, 0.20, 0.30, 0.50 | 6 |
| Cap N (rebalances a month) → wait W | none → 1 day; 8 → 4; 4 → 8; 2 → 15; 1 → 30; 0.5 → 60; 0.25 → 120 | 7 |
| Reset R | none; 365 days (the full runs only, section 6) | 1 or 2 |
| Wallet size V (USD) | 500, 5,000, 50,000 | 3 |
| Costs | 1x and 2x (`stressed()`) | 2 |
| First-buy reading | the lab's (A1: the first buy does not start the wait) for the whole grid; the other reading (it does) as a description only, below | 1 (+ description) |

**The other first-buy reading (description, A1).** The rolling windows of both sources, the 6 finite caps only (with
no cap, W = 1, the two readings make the same orders), at 5,000 USD and 1x: 27 mixes × 6 bands × 6 caps × 112 windows
= 108,864 runs, `hold_mix(..., first_buy_waits=True)`. Rules B and A are applied to it mechanically on each source,
with the grid's no-cap runs as the reference, and reported next to the headline, **never in place of it**.

**The 27 mixes** (targets in % of the wallet: BTC / ETH / cash):

| s \ f | 0 | 0.25 | 0.50 | 0.75 | 1 |
|---|---|---|---|---|---|
| 0.20 | 0 / 20 / 80 | 5 / 15 / 80 | 10 / 10 / 80 | 15 / 5 / 80 | 20 / 0 / 80 |
| 0.30 | 0 / 30 / 70 | 7.5 / 22.5 / 70 | 15 / 15 / 70 | 22.5 / 7.5 / 70 | 30 / 0 / 70 |
| 0.40 | 0 / 40 / 60 | 10 / 30 / 60 | 20 / 20 / 60 | 30 / 10 / 60 | 40 / 0 / 60 |
| 0.50 | 0 / 50 / 50 | 12.5 / 37.5 / 50 | 25 / 25 / 50 | 37.5 / 12.5 / 50 | 50 / 0 / 50 |
| 0.60 | not allowed | 15 / 45 / 40 | 30 / 30 / 40 | 45 / 15 / 40 | not allowed |
| 0.70 | not allowed | 17.5 / 52.5 / 30 | 35 / 35 / 30 | 52.5 / 17.5 / 30 | not allowed |
| 0.78 | not allowed | not allowed | 39 / 39 / 22 | not allowed | not allowed |

- **Feasibility.** With h = 0.02, the limits as read allow cash ≥ 22% (so s ≤ 0.78) and each coin ≤ 58%. A
  single-coin mix above 58% and s = 0.78 with f = 0.25 or 0.75 (58.5% in one coin) are not allowed and not run. The
  largest coin target in the grid is 52.5% and the smallest cash target 22%. On 2026-11-21 all 27 passed
  `check_targets` with the limits as read (`risk_levels.yaml` SHA-256 `158d7c9f…`), and the 8 left out were refused
  (scratch check, no market data).
- **At start**, `run.py` checks all 27 with `check_targets` against the limits as read, **before loading any bar**,
  and refuses to start if any fails. A tighter `risk_levels.yaml` then needs an amended grid before any run.
- **Why these values.**
  - s runs in steps of 0.10 from 0.20 (the low end of rebalance-steady's box) to 0.78, the largest crypto share the
    limits allow with h (the app's controls stop there, features.md).
  - b runs from 0.05 (a 1.25-point band on a 25% target) to 0.50. Narrower bands are left out: daily checks with b ≈
    0.02 already rebalanced about 10 times a month in these years (L3).
  - The caps run from one rebalance every 4 days (8 a month) to one every 120 days (0.25 a month), plus no cap. The
    app may offer other numbers; this study recommends only grid values.
  - Wallet sizes. At 500 USD almost every rebalance leg is under 100 USD, where the placeholder slippage is flat at
    10 bps, so customer fees in % are the same for any smaller wallet: 500 covers small wallets. Larger wallets pay
    more placeholder slippage per swap. Above 10,000 USD a leg's slippage is extrapolated along the table's last
    segment (`Costs.slippage`), so the 50,000 USD results lean on that extrapolation. The recommendation is meant to
    hold from small wallets up to 50,000 USD, not above.
- **The reset** is a description only, run on the full span (it can never fire in a 12-month window, whose last close
  is 364 or 365 days after its first, and an order at the last close is never sent).

## 6. Windows

**Rolling 12-month windows (the decision rules use these).** Window k = 0 .. 59 starts in month M_k = January 2017 +
k months. It holds the bars of the 12 calendar months M_k .. M_(k+11): a bar's day is its close time minus 1 day,
as in rebalance-steady's regime labels. So its closes run from the 2nd of M_k to the 1st of M_(k+12), both
included, at 00:00 UTC.

| | Windows | First window | Last window | Rows |
|---|---|---|---|---|
| Kraken | 60: k = 0 .. 59 (starts January 2017 .. December 2021) | closes 2017-01-02 .. 2018-01-01 | closes 2021-12-02 .. 2022-12-01 | 36 windows of 365 rows; 12 of 366 (k = 26 .. 37, whose months include 29 February 2020); 12 of 364 (k = 1 .. 12, which contain the missing close 2018-01-13) |
| Binance | 52: k = 8 .. 59 (starts September 2017 .. December 2021), **pinned from the calendar**: the windows whose first close is on or after Binance's first close, 2017-08-18 (section 3). Window k = 7 would start at close 2017-08-02, before it | closes 2017-09-02 .. 2018-09-01 | as Kraken | 40 of 365 rows; 12 of 366 |

- Each window spans 364 days (365 for the leap-day windows) from its first to its last close.
- Both window lists (Kraken k = 0 .. 59, Binance k = 8 .. 59) are written into `start.json` before any bar is read.
  They never come from the data: `run.py` stops (stop rule 5) if a panel lacks the first or last close of one of them.
- The windows **overlap**: each close sits in up to 12 of them. 60 windows are not 60 independent years
  (section 15). They also weight the years unevenly: January 2017 is in one window only, and December 2022 (closes
  2022-12-02 .. 2023-01-01) is in none, only in the full runs.
- **Full runs (descriptions only):** one run over each whole panel. Kraken: 2190 rows, 2017-01-02 .. 2023-01-01.
  Binance: 1963 rows, 2017-08-18 .. 2023-01-01. These also run the yearly reset.
- Each run starts all cash at its first close, buys the mix there (the first buy) and ends at its last close.
- **Check.** Each slice's row count must equal its calendar closes minus the source's missing closes inside it
  (Kraken: 2018-01-13; Binance: none). The window bounds come from the calendar, written into the start record before
  any bar is read. Otherwise stop.

## 7. Comparators

| Comparator | What | Run |
|---|---|---|
| **No cap** | The same s, f and b with N = none (W = 1) | It is in the grid; every capped run is paired with it on the same window, wallet size and costs |
| **Limit-only** | The same mix bought once and then traded back only when a Steady limit is hit (rebalance-steady's B5) | `hold_mix` with `band` = 1000 (b·T ≥ 1000 × 0.05 = 50 > 1 for every target in the grid, so the band never fires), `wait_days` = 1 and no reset, so its results carry the same `reasons`, `in_wait` and `held` attrs as the grid's. Test 13 proves this equals `portfolio.rebalance({"w_btc", "w_eth", "band": 1.0, "every": 1, "min_cash", "max_coin", "headroom": 0.02})` bit for bit, and `run.py` checks it again (below). One run per mix, window, wallet size and cost level |

**Limit-only's band metrics.** Its band-free metrics (d̄, distance, drift, counts, fees, money) are one row per run
in `runs.parquet` (`comparator` = `limit-only`, b and N empty). Its band-dependent metrics (in-band share, D_out, the
longest spell), measured against each of the 6 grid bands, are in `limit_only_bands.parquet`: one row per run and
band, 6 rows per run, keyed by the run's id.

**Parity checks (not comparators).** Where the relative band is the same absolute band for both coins (f = 0.5:
equal targets; f = 0 or 1: one coin), `hold_mix` with N = none and no reset must equal `portfolio.rebalance` with
`band = b·T` (T = the non-zero coin target) and `every = 1`, bit for bit. `run.py` runs this for the 15 such mixes,
6 bands, every window of both sources **and both full runs**, at 5,000 USD and 1x: 15 × 6 × (60 + 52 + 2) = 10,260
runs. It also checks every limit-only run at 5,000 USD and 1x against `portfolio.rebalance(band = 1.0, every = 1)`:
27 × 114 = 3,078 runs. 13,338 parity checks in all; `run.py` checks the count and stops on any mismatch.

No buy-and-hold BTC or 50/50 benchmark is run: nothing here is judged on return (AGENTS.md's benchmarks are for
strategies).

## 8. Metrics per run

Notation: a run has n rows with close times ts_0 .. ts_(n−1). E = rows 1 .. n − 1 (every close after the first buy has
filled; row 0, the all-cash close, is never in E). span = (ts_(n−1) − ts_0) in days. Annualised counts use 365 / span,
and "a month" is 30 days, the cap's own unit.

**Which weights.** In band, d_t, D_out, the longest spell and closes in breach use the result's `w_BTC` and `w_ETH` at
close t: after any fill at bar t's open and the move to close t, and before the fill of the order decided at close t.
These are exactly the weights the rule sees at close t. b·T is computed with the same expression as step 4, and a
breach with `portfolio._breach_test`, so a metric and the rule cannot disagree at a boundary.

**Rebalancing**
- **Rebalances:** orders at closes 1 .. n − 2, every reason; per 30 days = 30 × count / span. Also by reason (band,
  limit, reset), and per 30 days **without** limit-forced rebalances (a description, so the effect of the limits on
  mixes near them is visible).
- **Limit-forced inside the wait:** count and per year. This is how often limit hits break through the cap.
- **Held closes:** closes 1 .. n − 2 where step 4 or 5 would have ordered but the wait held it; per year. (The last
  close's decision is never sent, so it is never counted as held either.)
- **Most rebalances in any 30 days:** the largest number of counted orders (closes 1 .. n − 2) in any stretch
  [ts_i, ts_i + 30 days) that starts at an order close, limit fixes included.
- **Legs:** fill legs on rows ≥ 2 (the first buy fills on row 1); per year. Empty orders (expected 0).
- **Trade sizes** (from the fill log, rows ≥ 2): the largest single leg and the largest one-day turnover (the sum of a
  fill row's legs), each as % of the wallet just before that fill (V_open), and the smallest leg in USD. The first
  buy's legs are reported on their own (together they are s of the wallet). The customer's per-trade and per-day caps
  in the auto-trading permission, and the router's slippage protection, must allow a full trade back to the mix, or
  the wallet can be left past a Steady limit (section 15).

**Closeness to target**
- **In band** at a close in E: every coin with T > 0 has |w − T| ≤ b·T. **In-band share** = share of E in band.
  **Days out of band per year**, D_out = 365 × (out-of-band closes in E) / (n − 1). D_out divides by the n − 1 closes
  judged, while the rates divide by span in days. They differ only in the 12 Kraken windows with the missing close
  2018-01-13 (363 closes judged against a span of 364 days): the missing close is simply not judged.
- **Distance from target:** d_t = the largest |w − T| / T over the coins with T > 0, at each close in E: its mean d̄
  and its worst value.
- **Crypto-share drift:** |w_BTC + w_ETH − s| at each close in E: mean and worst, in weight points.
- **Longest spell out of band:** the longest run of consecutive out-of-band closes in E, in days (ts of its last
  close − ts of its first + 1 day; a missing close inside counts its two days).
- **Closes in breach:** closes in E where step 2's condition holds.

**Fees and money** (they differ by wallet size and cost level; everything above does not)
- **Customer fees**, % of the wallet a year: 100 × 365 / span × Σ over the legs on rows ≥ 2 of (leg cost USD − gas
  per leg) / V_open. **Gas**, the same with gas per leg. V_open = the leg's `usd` / |`weight_after` −
  `weight_before`|, the wallet just before that fill's swaps (from the engine's fill log). Customer fees + gas must
  equal 100 × 365 / span × Σ_(t ≥ 2) `cost`[t] to 1e-12 relative (checked on every run).
- The same two in USD a year, and the **first buy's cost** (% of V and USD), reported separately.
- **Return:** Π(1 + ret[1 .. n − 1]) − 1 (the first buy's cost included). **Sharpe:**
  `stats.annualized_sharpe(ret[1 .. n − 1], 365)`. Descriptions only.
- **Falls** (descriptions only; amendment A3). With e_0 = 1 at close 0 and e_t = Π(1 + ret[1 .. t]):
  - **Max drawdown:** `montecarlo.max_drawdown(ret[1 .. n − 1])`, a signed fraction ≤ 0 (the start counts as a
    peak). `money_metrics` also records its **trough** (the first close where e_t / max(e_0 .. e_t) − 1 reaches its
    minimum) and its **peak** (the first close at or before the trough where e equals the running maximum at the
    trough), and checks its own value against `montecarlo.max_drawdown`.
  - **Worst day:** min of ret[1 .. n − 1], with its close.
  - **Worst 7-day fall** (full runs only, to match a weekly loss limit): the minimum of e_t / e_u − 1 over the pairs
    of closes u, t with ts_t = ts_u + 7 days, with both dates. A pair whose end is a missing close is skipped.
  - **Every fall is shown as a positive size**: "fell 41.8% from its high" means −100 × max drawdown. Worse means more
    negative in the signed number, so a bad tail is its **minimum** (or its 10th percentile), never its 90th
    percentile, and never a median alone.

**Comparisons per run:** the differences from the no-cap run and from the limit-only run on the same mix, window,
wallet size and costs (rebalances, legs, customer fees, gas, D_out, d̄, return, Sharpe, max drawdown). They are kept
in `runs.parquet`; section 10 says which are shown.

## 9. Decision rules (pre-registered, applied mechanically by `run.py`)

**Pools.** Unless a rule says otherwise: the Kraken rolling windows, no reset. A **pair** is one mix in one window:
27 × 60 = 1,620 pairs for each (b, N) on Kraken, 27 × 52 = 1,404 on Binance. Closeness numbers and rebalance counts
come from the 5,000 USD 1x runs (they are identical in every cost setting, section 4.6, checked). Medians and
percentiles are `numpy.median` and `numpy.percentile` (linear interpolation). Every threshold is inclusive, as
written. The caps are ordered from tightest to loosest: 0.25, 0.5, 1, 2, 4, 8, none. **The bands are exactly the 6
grid bands**, which are the bands this study assumes the app offers; a pool over bands means those 6, each once.

**Thresholds, fixed now:**

| Name | Value | Plain meaning |
|---|---|---|
| EXTRA_OUT_MEDIAN | 7 days a year | With the cap, a typical mix-year spends at most about a week more outside its band than with no cap |
| EXTRA_OUT_P90 | 30 days a year | ... and 9 mix-years in 10 at most about a month more |
| RATE_MAX | 1.0 rebalance per 30 days | A typical mix-year needs about one trip back to the mix a month or fewer ("a few trades a month", with room to spare) |
| FEE_MAX | 0.25% of the wallet a year | In a typical mix-year the customer pays at most a quarter of a percent of the wallet a year in swap fees and slippage. It is judged at the pessimistic placeholder costs, which pushes the default band wider, and it leaves out any app swap fee (business.md says a small per-swap fee is possible later; if one is added, rule A's fee condition must be recomputed) |
| CLOSE_SHARE | 0.90 | A cap that already buys 90% of the closeness unlimited rebalancing buys |
| VALUE_FACTOR | 2 | Above the limit, the last rebalances cost at least twice their share of the closeness |

These numbers are judgement calls, made before any result (section 16).

### Rule B: the recommended cap for a band (computed first, for every band)

For a band b, each pair (m, w) and each finite cap N:
extra_out(m, w; b, N) = D_out(b, N) − D_out(b, none): the extra days a year outside the band that the cap causes.

- N **passes** for b if the median of extra_out over the pairs is ≤ EXTRA_OUT_MEDIAN **and** its 90th percentile is
  ≤ EXTRA_OUT_P90.
- **N\*(b)** = the smallest N in (0.25, 0.5, 1, 2, 4, 8) that passes **and** for which every looser finite cap also
  passes.
- If 8 does not pass, N\*(b) = "**more than 8**": the band needs more than 8 rebalances a month too often to be kept,
  and the app should not suggest it with a cap.

In plain words: the recommended cap is the tightest one (so the fewest rebalances and the lowest fees) that still lets
the band do its job almost all the time. N\*(b) does not depend on wallet size or costs (section 4.6).

### Rule A: the recommended default band

For each wallet size V and cost level k, a band b is **acceptable** if N\*(b) is a number (not "more than 8") and,
over the pairs at (b, N\*(b)):
- (i) the median rebalances per 30 days is ≤ RATE_MAX (every reason counts, limit-forced included);
- (ii) the median customer fees at (V, k) are ≤ FEE_MAX.

- **b\*(V, k)** = the narrowest band that is acceptable **and** for which every wider band in the grid is acceptable.
- If 0.50 is not acceptable: b\* = "**none**". The study then reports 0.50 with N\*(0.50), flagged "NO BAND MET THE
  CONDITIONS", and the owner decides.
- **Primary result:** Kraken, 1x, each of the three wallet sizes.
- **The app's single default** is the widest of b\*(V, 1x) over the three wallet sizes (so it meets the conditions
  for small, middle and large wallets), with that band's N\*. "none" counts as wider than 0.50, so if any wallet
  size has no acceptable band, the default is flagged NO BAND MET THE CONDITIONS. If b\*(V) differs by wallet size,
  the per-size values are reported too ("per book size"). The cap differs by wallet size only through the band.

In plain words: the default band is the narrowest (so the mix stays closest to the customer's choice) that still needs
about one trip back a month or fewer and costs at most a quarter of a percent of the wallet a year, with its
recommended cap in place.

### Rule C: evidence for a Steady upper limit on rebalances a month

Pool: all 6 bands × 27 mixes × 60 windows (Kraken, no reset), 9,720 runs per cap: the upper limit would apply to
every customer, whatever band they pick, and each band the app offers counts once.
- Dist(N) = the mean over the pool of d̄ (the mean distance from target, section 8) at cap N. Dist_L = the mean of
  d̄ over the limit-only runs of the same mixes and windows (d̄ does not depend on the band, so each limit-only run
  stands in for all 6 bands).
- **Closeness bought**, I(N) = (Dist_L − Dist(N)) / (Dist_L − Dist(none)): the share of the closeness that
  unlimited rebalancing buys over trading only at the limits that a cap of N already buys.
- **N_up** = the smallest N in (0.25 .. 8) with I ≥ CLOSE_SHARE at N **and** at every looser finite cap.
- **Fees:** F(N) = the mean customer fees over the pool at (V, k), F_L the same for limit-only, and C(N) = (F(N) −
  F_L) / (F(none) − F_L): the share of the extra fees of unlimited rebalancing already spent at cap N.
- **Value test** at N_up: **SUPPORTED** if 1 − C(N_up) ≥ VALUE_FACTOR × (1 − I(N_up)), i.e. beyond N_up the
  remaining rebalancing spends at least twice as large a share of the fees as the share of closeness it buys.
  Otherwise **WEAK**. The value test is WEAK whenever F(none) − F_L ≤ 0 (C undefined or of the wrong sign), and
  whenever I is undefined (Dist_L − Dist(none) ≤ 0). The headline uses 5,000 USD at 1x; all 6 cost settings are
  reported.
- **Outcomes are decided in this order:**
  1. **NO EVIDENCE** if Dist_L − Dist(none) ≤ 0: rebalancing never brought mixes closer than the limits alone did.
  2. Else **ABOVE 8** if no N in (0.25 .. 8) meets the I condition (I ≥ CLOSE_SHARE at N and at every looser finite
     cap): even a limit of 8 a month gives up more than a tenth of the closeness. The evidence does not support an
     upper limit at or below 8 a month.
  3. Else **EVIDENCE FOR A LIMIT AT N_up**, with its value test:
     - "**EVIDENCE FOR A LIMIT AT N_up, value test SUPPORTED**": above N_up rebalances a month, extra rebalancing
       bought less than a tenth of the closeness unlimited rebalancing buys, and cost a much larger share of its
       fees.
     - "**EVIDENCE FOR A LIMIT AT N_up, value test WEAK**": the same closeness finding, but the share of the extra
       fees saved above N_up is less than twice the share of the closeness given up.

  Every outcome is **SCOUTING evidence for the owner and sets no limit** (section 16). `decision.json` says so in a
  `status` field.
- **Bands the limit would hold back** (only for an EVIDENCE FOR A LIMIT outcome): every band whose N\*(b) is above
  N_up, or "more than 8". If the owner adopts the limit, the app should not offer these bands, because the limit would
  keep them from doing their job (this is how "a few trades a month caps the band" would work in practice).
- This rule uses the mean distance from target, the same yardstick for every band, because it asks what extra
  rebalancing buys for any customer. Rule B uses days outside the customer's own band, because it asks whether the
  cap keeps the customer's promise. The days-outside-the-band version of I(N) is reported as a description.
- **The pool's bands.** The pool is exactly the 6 grid bands, each counted once. The pooled ratio is driven most by the
  bands with the largest closeness gain, the narrow ones. That fits a guardrail, which binds exactly there, but it
  means N_up depends on the narrowest band offered (0.05). So I(N) and N_up(b) **per band** are reported as
  pre-registered descriptions: if the app offers a different set of bands, the reader can see what each band alone
  says.
- **Gas** (our cost, not the customer's) is left out of C(N). As a description next to rule C's table: gas per
  customer a year at each cap, in USD and as % of 500, 5,000 and 50,000 USD wallets. At the 0.10 USD placeholder per
  leg, 8 two-leg rebalances a month is about 19.5 USD a year (365 / 30 × 8 × 2 × 0.10), 3.9% of a 500 USD wallet,
  far above FEE_MAX if it were the customer's.

### Rule D: robustness, and what is reported when they disagree

- **2x costs.** By section 4.6, the closeness parts of rules B and C are identical at 2x. Only rule A's fee condition
  and rule C's value test can change; both are recomputed at 2x.
- **Binance.** Rules A-C are recomputed on Binance's 52 windows.
- **Robust values:**
  - N\*_rob(b) = the larger of N\*(b) on Kraken and on Binance ("more than 8" counts as the largest);
  - b\*_rob(V) = the narrowest band that is acceptable at (b, N\*_rob(b)) on **both** sources at **both** cost levels,
    with every wider band acceptable too; the app's default is again the widest over the wallet sizes;
  - **N_up,rob** (rule C's outcome, made robust):
    - Outcomes are ordered EVIDENCE FOR A LIMIT AT 0.25 < 0.5 < 1 < 2 < 4 < 8 < ABOVE 8, and N_up,rob is the larger
      of the two sources' outcomes.
    - If both sources say NO EVIDENCE, the robust outcome is NO EVIDENCE. If exactly one source says NO EVIDENCE, the
      robust outcome is the other source's, labelled NOT ROBUST (whatever the primary value).
    - **The robust value test** is run at N_up,rob on **each** source (never at each source's own N_up), with
      I(N_up,rob) and C(N_up,rob) at 5,000 USD, 1x and 2x. It is SUPPORTED only if all four tests pass; a test with an
      undefined I or C fails (rule C). There is no value test when N_up,rob is ABOVE 8 or NO EVIDENCE.
    - **The headline's bands held back** (when N_up,rob is a number): every band with N\*_rob(b) > N_up,rob or "more
      than 8".
  - **CONFLICT.** If N_up,rob is a number and either N\*_rob(b\*_rob) > N_up,rob (b\*_rob being the app's robust
    default band) or b\*_rob is "none", the headline is flagged **CONFLICT**: the recommended default band would be
    held back by the limit the evidence points to. The headline then also reports **the default under the limit**:
    for each wallet size, the narrowest band b with N\*_rob(b) ≤ N_up,rob that is acceptable at (b, N\*_rob(b)) on
    both sources and both cost levels, with every wider band that also has N\*_rob ≤ N_up,rob acceptable too; then
    the widest over the three wallet sizes ("none" counts as the widest, as in rule A), or "none" if no band
    qualifies. It goes in `decision.json`. The same check is run on the primary values (Kraken, 1x, N_up) and
    reported next to it.
- **The headline is the robust values.** The primary values (Kraken, 1x) stand next to them. The label is
  **ROBUST** when they are equal (and no NOT ROBUST case above applies). Otherwise it is **NOT ROBUST**, naming each
  setting that moved a value. In that case the Kraken result on Binance's 52 windows is also reported, to tell a
  data-source difference from the missing January-August 2017 windows.

### Rule E: failures and missing numbers

- A failed run has no metrics. Any decision whose pool holds a failed run is **MISSING** until triage (stop rule 4).
- If triage finds a code bug, there is an amendment run. If not (for example a fill the engine refuses because it would
  cost the whole wallet), every pair with a failed run is dropped from every pool. The dropped pairs are listed, and
  the decisions are computed on the rest.

### Pre-registered descriptions (computed mechanically by `run.py`, reported next to the headline, never in place of it)

- **The other first-buy reading (A1):** rules B and A at 5,000 USD and 1x on each source (section 5). Reported as
  N\*(b) per band and b\* under that reading.
- **Other readings of the Steady limits** (section 4.2). If 60% also capped cash, the targets would need s ≥ 0.42 with
  h, which removes the 15 mixes at s = 0.20, 0.30 and 0.40 (12 kept). If 60% capped the two coins together, they would
  need s ≤ 0.58, which removes the 7 mixes at s = 0.60, 0.70 and 0.78 (20 kept). Rules A-C are recomputed on each kept
  subset. This is not that reading's result: the extra limit trades the reading would add (cash over 60%, or the coins
  together over 60%) are not simulated. It shows only whether dropping those mixes moves the recommendation. A real
  change to the limits would still need its own run.
- **Few independent years:** rule B's median and 90th percentile of extra_out by window start year (2017 .. 2021) and
  on the five non-overlapping Kraken windows k = 0, 12, 24, 36, 48.
- **Without the boom years (A5; an addendum):** rules A-D recomputed with each train year left out in turn, and
  without the best one and two years for BTC, reporting whether each headline value holds. The removals and the
  rules are pinned in amendment A5.

## 10. What is reported (RESULTS.md, written by the lead after the run)

Every table is labelled SCOUTING with placeholder costs.
- **Headline:** the robust default band, its recommended cap (with W in days, and the customer wording of section
  4.1), the evidence on a Steady upper limit and its value test, the CONFLICT flag and the default under the limit
  (rule D), and the ROBUST / NOT ROBUST label; the primary values next to them. Next to it, never in place of it: the
  other first-buy reading's N\*(b) and b\* (A1). Also next to it, for each crypto share (especially 0.70 and 0.78):
  the most rebalances in any 30 days, limit fixes included (median and worst over windows), because an upper limit
  would not bound limit fixes (section 16).
- **Per band:** N\*(b); the median and 90th percentile of extra_out at every cap; rule A's (i) and (ii) at (b,
  N\*(b)) for every wallet size, cost level and source.
- **Rule C:** I(N), Dist(N), F(N) and C(N) at every cap and cost setting; I(N) and N_up(b) per band and the
  days-outside-the-band yardstick (descriptions); gas per customer a year at each cap (USD and % of each wallet
  size); the bands the limit would hold back.
- **Per crypto share s:** rebalances per 30 days (with and without limit-forced ones), limit-forced rebalances inside
  the wait per year, D_out and fees at the default band and cap. This shows how often limit hits break through the
  cap, mix by mix.
- **Trade sizes:** for each (b, N) and each crypto share, the largest single leg and the largest one-day turnover (%
  of the wallet), the smallest leg in USD, and the first buy's legs. The app needs these to size the per-trade and
  per-day caps of the auto-trading permission, or to warn the customer.
- **Comparisons:** each recommended setting against no cap and against limit-only.
- **Full runs:** every configuration over 2017-2022 (Kraken) and 2017-08-18 to 2022 (Binance), with and without the
  yearly reset: how often the reset fired, what it cost, and how it changed D_out and d̄.
- **Descriptions** of section 9 (the other limit readings; years; the first-buy reading).
- **Boom-year addendum** (A5), next to the headline and never in its place: for each removal (each train year, the
  best year, the best two years), the kept windows and whether N\*_rob(b), b\*_rob per wallet size, the app default,
  N_up,rob, the value test and CONFLICT equal the headline's (`decision.json`, `boom_check`).
- **Fees caveat.** Every fee number, and rule A's fee condition, uses placeholder costs. It must be rechecked with
  measured Base costs before the app shows a recommended number.
- **Falls** (amendment A3), in `falls.csv` and RESULTS.md, **by crypto share first**, then by mix:
  - For each crypto share and each mix, at the headline band and cap (when the headline is flagged NO BAND MET THE
    CONDITIONS: 0.50 with N\*_rob(0.50), or no cap if that is "more than 8"), 5,000 USD and 1x, on each source:
    (a) the **worst fall over all rolling windows**, naming that window; (b) the **full-run fall** with its peak and
    trough dates (Kraken 2017-01-02 to 2023-01-01; Binance from 2017-08-18), with and without the yearly reset;
    (c) the deepest fall over **every band and cap** of the grid for that mix (5,000 USD, 1x), naming the band, cap
    and window, so no grid setting fell further than shown.
  - For each crypto share, the worst of its mixes, naming the mix; and, from the full runs, the **worst day** and the
    **worst 7-day fall**, with their dates, to match the daily and weekly loss limits. They back the docs' line that a
    loss-limit pause does not cap a loss.
  - Each fall is a positive size ("fell X% from its high"). Where a spread over windows is shown, the bad tail is the
    minimum of the signed number or its 10th percentile, and the label says which. A median is never shown alone.
  - **Every table of falls carries this label:** "SCOUTING, hypothetical: simulated on past prices, 2017-2022 train
    years (the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall
    the app shows, and not a drawdown budget."
  - Expectation, written before any run, not a finding: between bands and caps the differences in return and fall are
    expected to be small; the crypto share is expected to move the worst fall the most (rebalance-steady).
- **Returns and Sharpe ratios** only for the recommended settings and their comparators (no cap, limit-only), as
  descriptions with the same label. Per-configuration returns stay in the git-ignored `runs.parquet` (section 2).
- The run record: commit, commands, tier results, timings, counts, failures, consistency checks, every stop rule
  that fired, and the deviations.

## 11. Run count and throughput (amendment A0)

| Runs | Count |
|---|---|
| Kraken rolling: 27 mixes × 6 bands × 7 caps × 6 cost settings × 60 windows | 408,240 |
| Binance rolling: the same × 52 windows | 353,808 |
| Full runs: 27 × 6 × 7 × 2 resets × 6 cost settings, per source | 13,608 + 13,608 |
| Limit-only: 27 mixes × 6 cost settings × (60 + 1) Kraken and (52 + 1) Binance | 9,882 + 8,586 |
| The other first-buy reading (A1, description): 27 × 6 bands × 6 finite caps × 112 windows, 5,000 USD, 1x | 108,864 |
| **Total logged runs** | **916,596** |
| Parity checks (section 7, logged separately): 10,260 band parity + 3,078 limit-only parity | 13,338 |

There is no randomness anywhere in this study (no seeds, no resampling), so every run is exactly reproducible and the
results do not depend on how runs are split across processes.

**A0, throughput (2026-11-21, synthetic data only, before any result).** AGENTS.md rule 5 asks for a timing before a
sweep. Measured by this plan's author with a stand-in: the rule of section 4.2 written as a `decide` callback for
`portfolio._simulate`, in a scratch script outside the repo. It ran on `make_panel(synthetic_market(2190, seed=21,
start="2017-01-02"), snapshot_id="synthetic")` and its first 365 rows, with the limits as read and
`Costs.from_yaml(capital_usd=5000)`. Medians of 30 runs:

| Case (s, f, b, W, R) | 365 rows: backtest / metrics | 2190 rows: backtest / metrics |
|---|---|---|
| 0.5, 0.5, 0.20, 15, none | 1.81 / 1.14 ms | 6.94 / 1.45 ms |
| 0.78, 0.5, 0.05, 1, none | 1.94 / 1.12 ms | 11.92 / 2.09 ms |
| 0.2, 0, 0.50, 120, 365 | 2.04 / 1.15 ms | 6.76 / 1.58 ms |

- `validate_panel`, which the built engine runs once per call, takes 1.75 ms on 365 rows and 1.64 ms on 2190 rows.
  `portfolio.rebalance` (validation included) takes 4.90 ms on the same 365 rows.
- Environment: Python 3.13.18, 4 shared CPUs, load average 0.22.
- **Projection:** about 5 ms per 365-row run and at most 16 ms per full run. That gives 762,048 × 5 ms + 27,216 × 16
  ms + 18,468 limit-only and 10,260 parity runs (about 2.5 CPU-minutes) ≈ 4,400 CPU-seconds, about 73 CPU-minutes,
  or about 37 minutes wall time on the 2 worker processes the run uses.
- **After A1 and A4** (no new timing; the same per-run figures): the other first-buy reading adds 108,864 × 5 ms ≈ 544
  CPU-seconds and the 3,078 limit-only parity checks at most 3,078 × 16 ms ≈ 50. In all about 4,990 CPU-seconds,
  about 83 CPU-minutes, or about 42 minutes wall time on 2 workers: well under the 240 CPU-minute guard.
- **Rule before the real run:** `run.py --time` repeats this measurement with the built `hold_mix` and metrics on
  the same synthetic panel and cases (output to a scratch folder) and records it in the start record. If its
  projection over every run and parity check in the table above is above **240 CPU-minutes**, the real run does not
  start: the grid is amended in section 13 (a dated row) before any result.

## 12. Logging, outputs and the config hash

- **Every run is logged** (hard rule 8): every configuration, both cost levels, every wallet size, every window, the
  comparators and the parity checks, and failures with their error text. Nothing is deleted. Superseded runs stay in
  their own folders.
- **Folders.** A real run writes only to `results/hold-mix-cap/run<k>/` (git-ignored) and to the tracked files
  below. It reads only `config/` and `data/catalog/`. `run.py` refuses any other `--out-dir`, `--config-dir` or
  `--catalog-dir` on real data.
- **Start record, before any bar is read.** `run<k>/start.json`: UTC time, run number, git commit and dirty flag,
  the config hash and every per-file hash, the limits as read (`min_cash`, `max_coin`, the file's SHA-256), the cost
  settings as read, the grid, the window bounds from the calendar, the thresholds, the A0 re-timing, and the snapshot
  id and bars hash from `SNAPSHOT.json`. Then one line is appended to the tracked
  `research/hold-mix-cap/RUNLOG.jsonl` (UTC time, script, run number, commit, dirty flag, config hash, snapshot id,
  "real"). Right after the panels load, before any backtest, `start.json` gets their row counts and panel hashes,
  and then each source's BTC calendar-year returns (A5's ranking).
- **Git-ignored results**, in `results/hold-mix-cap/run<k>/`:
  - `runs.parquet`: one row per run (916,596): run id, source, scope (rolling or full), window, first and last
    close, rows, comparator (grid or limit-only), first-buy reading (`lab` or `other`), s, f, w_btc, w_eth, b, N, W,
    R, V, k, status and error, the path hash, every metric of section 8 (falls with their peak, trough and worst-day
    dates), and the run's `snapshot_id` and git `commit` (hard rule 7; also in `start.json`);
  - `limit_only_bands.parquet`: limit-only's band-dependent metrics, 6 rows per limit-only run (section 7);
  - `parity.parquet`: the parity checks and their outcome;
  - `failures.parquet`: the failed runs with their tracebacks;
  - `blocks/`: each (source, scope, window) block's four tables (`<block>.runs.parquet`, `.lob`, `.parity`,
    `.failures`), written as soon as the block returns, so a stop, a crash or a killed process keeps every block
    computed so far (stop rule 6; A6). The four tables above are written as soon as the grid ends, before any count,
    check or decision, and `runs.parquet` again with the comparison columns;
  - `summary.json`: the consistency checks, timings, counts, the blocks and runs logged so far, the stop rules, and a
    pointer to `decision.json`, which holds the decision tables (A6);
  - `decision.json`: a byte-identical copy of the tracked one.
- **Tracked** (the lead commits them after the run), in `research/hold-mix-cap/`:
  - `RUNLOG.jsonl`;
  - `runs.csv`: one row per configuration and source (rolling: aggregated over the windows; full: the single run).
    Per source: 1,134 rolling grid rows, 2,268 full-run grid rows, 162 + 162 limit-only rows (one per mix, scope and
    band), and 972 rows of the other first-buy reading: **9,396 rows** in all, checked by `run.py`. It holds the
    closeness, rebalance and trade-size metrics once, and the fee and gas metrics once per cost setting, rounded to 6
    significant digits. Where it aggregates over windows it gives, for each metric, the median, the **bad tail** (the
    90th percentile where larger is worse: rebalances, D_out, d̄, the worst distance, drift, spells, breach closes,
    fees, gas, trade sizes; the 10th percentile where smaller is worse: in-band share, smallest leg) and the worst
    value over windows. It holds **no** return, Sharpe, drawdown or worst day (section 2). Every row carries a `label`
    column: "SCOUTING, placeholder costs, train years 2017-2022, reference engine". The exact columns are pinned in
    `run.py`;
  - `falls.csv`: the falls tables of section 10, falls as positive sizes, with the same label column and the label of
    section 10 in a `note` column;
  - `decision.json`: the mechanical output of section 9 (every rule's table, the descriptions, the thresholds, the
    counts and the dropped pairs) and the boom-year addendum (`boom_check`, A5), with a `label` field (as above) and
    a `status` field: "SCOUTING evidence for the owner; sets no limit";
  - `RESULTS.md`, written by the lead, not by `run.py`.
- **Config hash:** SHA-256 over a JSON blob of the per-file SHA-256s (sorted by path) and the pinned values (the
  grid, the windows, the thresholds, h, the first-buy reading of the grid and of the description). The files:
  - `research/hold-mix-cap/PLAN.md` and `run.py`;
  - `lab/runner/holdmix.py`, `portfolio.py`, `reference.py`, `interface.py`, `steady.py` (for `panel_hash`);
  - `lab/data/panel.py`, `catalog.py`, `external.py`; `lab/config.py`; every `.py` file in `lab/validation/`;
  - `config/costs.yaml`, `splits.yaml`, `risk_levels.yaml`; `pyproject.toml`; `uv.lock`.

  RUNLOG.jsonl, runs.csv, falls.csv, decision.json, README.md and RESULTS.md are not hashed (they change by design).
- **Synthetic dry runs** (`--synthetic SEED --out-dir <scratch>`, optionally `--fast`) test the script end to end on
  a synthetic panel shaped like DATA.md (the Kraken grid with the 2018-01-13 gap; Binance from 2017-08-18), fed
  through `load_panel` with a stand-in loader so its guards run. They refuse `results/hold-mix-cap/` and any folder
  inside the repo, write their RUNLOG and tracked copies under `<scratch>/tracked/`, are not runs of this study, and
  no number from them is reported.
- **MLflow: none.** It is not built, and the Nautilus/MLflow work is on hold. This is a declared deviation from the
  "Parquet + MLflow" rule, as in rebalance-steady.

## 13. Stop rules, amendments and deviations

**Stop rules.**
1. **Tiers.** No number counts unless the full tier with coverage (100% branch coverage of `lab/`, `fail_under =
   100`), the whole-suite deep profile and ruff pass on the commit the run uses (hard rule 11), run with `-n 2`:
   `uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch
   --cov-report=term-missing`, `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 -m "not slow"
   --ignore=tests/test_dashboard.py` and `uv run ruff check`. The lead runs them on that commit before each run and
   records the commands and counts in RESULTS.md.
2. **Dirty tree refused.** On real data `run.py` refuses to start when `git status --porcelain
   --untracked-files=all` prints anything (git-ignored files do not count), so the commit is well defined.
3. **Test-window and validate guard.** Every load asks for `last_close = 2023-01-01 00:00 UTC`. If any close after it
   is returned, the run stops before any backtest. Nothing from it is used, and it is logged in RUNLOG, RESULTS.md and
   section 17. If such a bar was ever in memory, the incident is reported to the owner as a possible look at
   validate for later Steady strategies.
4. **A failed run** (an exception inside one run) is logged with its error text, and the grid continues. After the
   run, every failure is triaged before anything is reported. A code bug gets a fix, a regression test that fails on
   the old code, a TESTING.md bug-log row (numbered after the last row, #49) and an amendment run. If there is no code
   bug, the run stands and rule E applies.
5. **Data.** A different bars hash, row count or panel hash (section 3), or a panel that lacks the first or last close
   of a window pinned from the calendar (section 6): stop and amend.
6. **A crash** (the process dies): it is not resumed. Its logged rows stay in its folder, and the run is repeated from
   scratch as an amendment run.
7. **A bug found in the outputs**, by a consistency stop or by reading the results: fix it, add a regression test, add
   a bug-log row and a dated amendment row here (committed before the rerun), and rerun as an amendment run.
   - At most **2 amendment runs** (k = 1, 2). If a third would be needed, stop: no recommendation, and everything is
     reported.
   - `run.py` without `--amendment` is run 0. It refuses if `results/hold-mix-cap/` exists or if the RUNLOG already
     holds a real run 0.
   - `run.py --amendment k` refuses unless `run<k−1>/start.json` exists (written at start, so a crashed run counts),
     its row `- **Amendment run k**` is in this section's list of amendments with the date, the reason, how the bug
     was found and the regression test, and neither `run<k>/` nor a RUNLOG line for run k exists.
   - The reported run is the last one, and it must be complete. RESULTS.md shows every superseded run's decision next
     to the final one.
8. **Consistency stops** (automatic, in `run.py`; each stops the run, which then needs an amendment run):
   - the path hash (orders, reasons, in-wait flags, weight columns) differs between the 6 cost settings of a
     configuration (section 4.6);
   - the reasons are not aligned with the engine's `orders`, or a non-limit order comes less than W days after the
     previous **counted** order (for the other first-buy reading of A1: the previous order of any kind), or an order
     inside the wait is not a limit order;
   - counting only orders that are not limit orders, a run has more of them in some 30-day stretch than ceil(30 / W);
   - a parity check fails (section 7);
   - customer fees + gas differ from the engine's `cost` column (section 8);
   - a slice's row count is wrong, or a close after 2023-01-01 00:00 UTC appears (section 6, stop rule 3).
9. **Throughput.** The `--time` projection is above 240 CPU-minutes (section 11): amend before the run.
10. **Changes.** A hashed file that changes after a run starts changes the config hash. Any later run must then be an
    amendment run, with its row here.

**Amendments.** Dated, written in this list and committed before the run they affect.
- **A0, throughput (2026-11-21, before any result).** The synthetic timing and the 240 CPU-minute rule of section 11.
  No change to the design.
- **A1, the first buy does not start the wait (2026-11-21, before any result and before any code).** The first draft
  let the first buy start the wait, which departed from the fixed design ("a minimum wait W between the order closes
  of consecutive rebalances"; "the first buy is not counted as a rebalance") and from features.md ("at least 30/N days
  (rounded up) between them"). The reviewer found it. On synthetic prices (L9, an illustration, not a result) the
  reading moved the median extra days out of band at b = 0.20, W = 60 from 6.5 to 15.0 a year, either side of
  EXTRA_OUT_MEDIAN, so it can move N\*(b) and the recommended cap. The owner said "you decide" (2026-11-21) and cannot
  answer it, and the app must do what the study does, so **the lab fixes the reading now, as recorded in features.md:
  the wait runs from the close of the last counted order (limit, band or reset), and before the first counted order
  there is no wait. The reset still counts from the last order of any kind, the first buy included.** features.md
  already says this, so it is unchanged. Changed here: sections 4.1-4.4 (two clocks, step 1 "Restarts the wait: no",
  the worked example), stop rule 8 ("previous counted order"), test 6 ("a band break on day 1 with W = 5 orders on
  day 1"), the hand break (now "the first buy starting the wait"), sections 15 and 16. The other reading runs as a
  pre-registered description at 5,000 USD and 1x (section 5, 108,864 runs, about 9 CPU-minutes), with rules B and A
  applied mechanically and reported next to the headline, never in place of it.
- **A2, rules C and D made fully mechanical (2026-11-21, before any result).** Found by the review. Rule C: the
  order of its outcomes (NO EVIDENCE, then ABOVE 8, then EVIDENCE FOR A LIMIT AT N_up); the value test is WEAK
  whenever F(none) − F_L ≤ 0 or I is undefined; the outcomes renamed "EVIDENCE FOR A LIMIT AT N_up" and marked as
  setting no limit. Rule D: the order of the outcomes, N_up,rob as the larger, one-source NO EVIDENCE, the robust
  value test at N_up,rob on each source (four tests), the headline's bands held back from N\*_rob, and the CONFLICT
  flag with the default under the limit (rule A picks b\*_rob without looking at N_up,rob, so without this flag the
  default to use under an adopted limit would be chosen after the results). Test 22 and the hand breaks extended.
- **A3, falls reported from the right tail, with dates and the hypothetical label (2026-11-21, before any result).**
  Found by the review: `montecarlo.max_drawdown` and the worst day are ≤ 0, so a 90th percentile would show the
  mildest tenth, and a median over fresh 12-month windows hides the 2018 and 2022 crashes. Every fall is now a positive
  size; for each crypto share and mix, the worst over windows (naming it) and the full-run fall with its peak and
  trough dates; the bad tail is the minimum or the 10th percentile of the signed number; never a median alone. Every
  table of falls carries the hypothetical label, and falls are shown by crypto share first. The caveat "the
  differences between settings are small", written before any result, is now worded as an expectation, with the
  crypto share expected to move the fall the most. A test recomputes the reported falls from `runs.parquet`.
- **A4, smaller review changes (2026-11-21, before any result).** Taken from the review's suggestions: the weights the
  closeness metrics use, and `held` counted on closes 1 .. n − 2 (section 8); the parity count includes both full runs;
  limit-only runs through `hold_mix` and is checked against `portfolio.rebalance` (3,078 more parity checks); the
  limit-only layout; the Binance windows pinned from the calendar; `run.py` refuses a Steady level without both
  limits, `headroom` is a required key, and the breach test is `portfolio._breach_test`; the limit reading stated,
  with the other readings as descriptions; the per-band rule C numbers, gas, trade sizes, the rate without limit
  fixes, the years description, and the worst day and worst 7-day fall per crypto share; FEE_MAX's wording; the cap's
  customer wording; the resume-after-pause pin and the production controls (section 15); labels inside the tracked
  files; `snapshot_id` and `commit` columns; per-configuration returns kept out of the tracked files; section 16's
  preface and its points on limits and budgets. Run count 916,596 and about 83 CPU-minutes (section 11).
- **A5, the boom-year addendum (2026-11-21, before any result).** The owner decided on 2026-11-21
  (`reports/director/2026-11-21-boom-check.md`, commit `652eefc`, after this plan's `1ff5ac2`) that every study is
  also checked "with and without" the boom years. Here the check is an **addendum**: it is reported next to the
  pre-registered result and never replaces it, and the rules of section 9 are unchanged. Found by the build's code
  review: the note left the windowed study's choices open, and settling them after run 0 would be a forking path.
  Pinned now, before run 0:
  1. **The removals:** each calendar year 2017, 2018, 2019, 2020, 2021 and 2022 in turn, then the best year, then the
     best two years. Years are bar days (close minus 1 day), as in section 6. The years are ranked by BTC's
     close-to-close return over each calendar year, R(Y) = C_end(Y) / C_start(Y) − 1, where C_end(Y) is BTC's close
     on Y's last bar and C_start(Y) the close on the last bar of Y − 1, or on Y's first bar when the panel has no bar
     of Y − 1. The ranking uses **Kraken's** BTC closes for both sources (Kraken holds every train year whole; Binance's
     2017 starts on 18 August, so its R(2017) covers 4.5 months). Largest first; a tie goes to the earlier year. Both
     sources' R(Y) are written into `start.json` right after the panels load, before any backtest (Binance's 2017
     from its first close, 2017-08-18). The yearly returns are public knowledge (BTC's largest yearly rises were in
     2017 and 2020); every year is removed in turn, so no year is picked with hindsight.
  2. **Which windows go:** window k overlaps year Y when one of its months M_k .. M_(k+11) is in Y, i.e. 12 (Y − 2017)
     − 11 ≤ k ≤ 12 (Y − 2017) + 11, and every window that overlaps a removed year is dropped. Without 2017, Kraken and
     Binance keep k = 12 .. 59 (48 windows each); without 2018, 37 and 36; without 2019, 2020 or 2021, 37 and 29
     (without 2020: k ≤ 24 and k ≥ 48); without 2022, k ≤ 48 (49 and 41). Without 2017 and 2020 both keep 25. The full
     runs are not split.
  3. **What is recomputed** on the kept windows: rules B, A and C per source and rule D, exactly as in section 9 (the
     same pools, settings and thresholds; `run.py`'s `decide_sources(runs, lob, windows=...)` and `holdmix.robust`).
     Nothing is rerun or refitted: the kept windows' logged runs are reused. For each removal, `decision.json`'s
     `boom_check` block holds rule D's output and whether N\*_rob(b) for each band, b\*_rob for each wallet size, the
     app default, N_up,rob (the outcome in words), the value test and the CONFLICT flag equal the headline's: True,
     False, or MISSING when either side is MISSING, and `all`. The descriptions, the per-share table and the falls are
     not recomputed. With failed runs, rule E's block carries the same check on its kept pairs (the windows each pool
     still holds).
  4. **Too few windows:** a removal that leaves either source fewer than **12** windows (one year of window starts) is
     MISSING, with no value computed. With this calendar no single year can do that (the fewest kept is Binance's 29);
     two years can (2019 and 2021 would leave Binance 6).

  Every block is labelled "ADDENDUM (owner decision 2026-11-21, PLAN.md A5) ... never in place of it" plus the
  SCOUTING label. The owner's strategy reading ("beats its comparators only with the boom years in") does not apply
  as such: this study recommends settings and claims no edge, so the addendum reports whether the recommendation
  holds. Changed here: sections 9, 10 and 12. It changes the config hash (`run.py`, `holdmix.py`, this file and the
  pinned values), before any run. Code: `holdmix.year_returns`, `best_years`, `overlaps`, `windows_without`,
  `boom_removals`, `boom_plan` and `boom_compare`, and `run.py`'s `boom_check`. Tests: TESTING.md bug-log row #53.
- **A6, logging and smaller fixes from the build's code review (2026-11-21, before any run on real data).** (1) **Every
  run logged on a stop or crash** (stop rule 6 and section 12, which the first build did not meet): it kept every row
  in memory and wrote the tables only at the end, so a stop from a block, the counts or `runs.csv`, or a crash in the
  decisions after the hour-long grid, left only `start.json` and `summary.json`. Now each block's tables go to
  `run<k>/blocks/` as the block returns (with 2 workers, blocks already running when another stops finish and are
  written too; the stopping block itself is not, its stop names the run), `summary.json` counts the blocks and runs
  logged, and the four tables are written before any count, check or decision. (2) **Rule D's label** also compares
  the CONFLICT flag and the default under the limit between the primary and the robust values (both are headline
  values, section 10): before, a default under the limit that moved left the label ROBUST. (3) A parity check compares
  the engine's own outcome, so a metric that fails after the engine ran is a failed run (stop rule 4), never a failed
  parity check (stop rule 8). (4) The stop rule 3 guard reads a loader's tz-naive index as UTC. (5) `start.json`
  records the platform (the workers are forked, which is safe on Linux, where the real run is made); `summary.json`
  points to `decision.json` for the decision tables. No change to the grid, the counts, the thresholds or any rule's
  number. Tests: TESTING.md bug-log row #53.

**Deviations.** Every departure from this plan, however small, goes in a Deviations table in RESULTS.md. Each row
says what changed, why, and when relative to which result, with its effect on any number.

**Not done in this study:**
- reading validate or test bars;
- NautilusTrader, `lab/costs/`, MLflow, or any file in `strategies/`, `reports/<strategy>/` or `exports/`;
- an Optuna search or a walk-forward: nothing is tuned for return, and the grid is fixed here;
- hourly bars, intraday checks, other coins, USDC yield or depeg;
- edits to any file in rebalance-steady's `frozen_paths()` (`lab/runner/portfolio.py`, `reference.py`,
  `interface.py`, `steady.py`, `lab/data/panel.py`, `catalog.py`, `external.py`, `lab/config.py`, `config/*.yaml`,
  `pyproject.toml`, `uv.lock`, `lab/search/*.py`, `lab/validation/*.py`), except for a real bug with a regression
  test and a bug-log row. Such an edit changes rebalance-steady's config hash, and it is announced loudly in
  RESULTS.md and the handoff. No new dependency.

**Reviews.** Before the build, `backtest-auditor` (method, guards, counting) and `risk-officer` (the limit readings,
the upper-limit evidence) may review this plan. Their changes come in as dated amendment rows, before any result. A
first review (2026-11-21) led to A1-A4.

## 14. Code to build, and its tests

### `lab/runner/holdmix.py` (new; the tool's engine, its metrics and the decision rules)

Scouting only, like `portfolio.py`. It calls `portfolio._simulate` with a `decide` callback, as `portfolio.rebalance`
does, and changes no existing file.

```python
HEADROOM = 0.02                                   # the lab's 2-point margin (rebalance-steady A2)
MONTH_DAYS = 30
CAPS = (None, 8, 4, 2, 1, 0.5, 0.25)              # None = no cap
BANDS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)

def wait_days(cap) -> int                          # None -> 1; N > 0 -> ceil(30 / N), exact decimal arithmetic
def mix_targets(s: float, f: float) -> tuple[float, float]           # (s * f, s * (1 - f))
def hold_mix(params, bars, costs=None) -> pd.DataFrame
    # params (strict): w_btc, w_eth, band (finite >= 0), wait_days (int >= 1),
    # min_cash, max_coin (required keys; a fraction in [0, 1], or None = off, for tests only;
    #   run.py refuses a level without both), headroom (required; >= 0; > 0 needs a limit),
    # reset_days (None or int >= 1; default None),
    # first_buy_waits (bool, default False = the lab's reading, A1; True only for the A1 description).
    # Breaches via portfolio._breach_test; targets checked as portfolio.check_targets does.
    # Result: _simulate's columns and attrs, plus attrs "reasons" (one per order: first/limit/band/reset),
    # "in_wait" (bool per order) and "held" (closes 1 .. n-2 where the wait held a band break or a due reset).
def path_metrics(result, *, targets, band, min_cash, max_coin, wait) -> dict     # section 8, closeness and counts
def trade_sizes(result) -> dict                                                  # section 8, legs and turnover
def money_metrics(result, costs) -> dict          # section 8, fees, gas, return, Sharpe, falls with their dates
def path_hash(result) -> str                                                     # orders, reasons, in_wait, weights
def rolling_windows(source) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]     # section 6, calendar only
def window_slice(panel, first, last) -> pd.DataFrame                             # .loc slice + the row-count check
# Decision rules on a runs table (pure functions; section 9)
def cap_for_band(runs, band) -> dict               # rule B
def default_band(runs, caps, book, cost) -> dict   # rule A
def upper_limit(runs, limit_only, book, cost) -> dict   # rule C, outcomes in their pinned order
def robust(primary, binance) -> dict               # rule D, incl. the robust value test and CONFLICT
def descriptions(runs, limit_only) -> dict         # section 9's pre-registered descriptions
def falls_tables(runs, headline) -> pd.DataFrame   # section 10's falls, positive sizes, with their dates
```

The decision rules live in `lab/` so that the existing coverage floor (100% branch coverage of `lab/`) covers
them.

### `research/hold-mix-cap/run.py` (new)

- Real run: `uv run python research/hold-mix-cap/run.py [--amendment k] [--workers 2]`.
- Dry run: `--synthetic SEED --out-dir <scratch> [--fast]`, where `--fast` runs 3 mixes, 2 bands, 3 caps, 1 wallet
  size, both cost levels and 4 windows.
- Timing: `--time --out-dir <scratch>` (synthetic only).
- Start guards on real data include: `risk_limits("steady")` must give numbers for both `min_cash` and `max_coin`
  (exit 2 otherwise); all 27 mixes pass `check_targets`; `HEADROOM` is passed to every `hold_mix` call.
- It does: the start guards of section 13; the start record and the RUNLOG line before any bar; the panels and
  their checks; the grid in 2 worker processes by (source, window) blocks, with rows sorted by a pinned key before
  writing; the consistency stops; the parity checks; the comparators; the other first-buy reading; `runs.parquet`,
  `limit_only_bands.parquet`, `runs.csv`, `falls.csv`, `decision.json` and `summary.json`.
- Exit codes: 0 done, 2 refused at start, 3 stopped by a guard or a consistency stop (recorded in `summary.json`).

### Tests (TESTING.md section 7; hard rule 11)

`tests/test_holdmix.py` (synthetic data, `make_bars` and hand-built panels, `tmp_path` configs only):
1. `wait_days` by hand: none → 1, 8 → 4, 4 → 8, 2 → 15, 1 → 30, 0.5 → 60, 0.25 → 120, 0.3 → 100, 7 → 5, 31 → 1; 0,
   negatives, NaN, inf, bools and strings raise.
2. **Strict params** with pinned messages: unknown and missing keys (`headroom` included); a negative or NaN band;
   `wait_days` 0 or 1.5; `reset_days` 0; `first_buy_waits` not a bool; targets summing above 1; targets breaking the
   limits with h; headroom without a limit; costs that are not a `Costs`.
3. **The relative band on hand-built paths:** with targets 45% / 15% and b = 0.2, an ETH move to 19% (more than 3
   points, 20% of 15%) orders, while a BTC move to 49% (less than 9 points) does not. The test is strict: a weight
   just inside b·T does not order, one just outside does.
4. **Target 0:** with f = 0 and f = 1, the zero coin never orders, even at b = 0, and its weight stays exactly 0.
5. **The wait on hand-built paths:** a band break inside the wait is held and ordered at the first close W days after
   the last counted order if still out of band; if the mix came back inside, nothing trades. W = 1, 3 and 15.
6. **The first buy** is not counted, is excluded from legs and fees, and does not start the wait: a band break on
   day 1 with W = 5 orders on day 1. The first counted order starts the wait: a second band break on day 2 waits until
   day 6. The reset still counts from the first buy: with R = 10 and no other order, it fires on day 10. With
   `first_buy_waits=True` (the A1 description), the same day-1 band break orders on day 5, not earlier.
7. **The limit override:** a breach inside the wait orders at that close (reason `limit`, flagged inside the wait),
   counts, and restarts the wait: a band break the next day waits W days from the limit order. A breach before the
   first counted order is not flagged inside the wait.
8. **The same close:** breach plus band break gives one `limit` order; band break plus due reset gives one `band`
   order; each counted once.
9. **The reset:** it fires R days after the last order of any kind even inside the band, waits when R < W, and
   restarts the wait.
10. **Calendar days, not rows:** on a panel with a missing close, the wait ends W calendar days after the order
    close; a row-counting version would order one row later. The same panel gives the right longest spell in days.
11. **Counting:** rebalances = orders at closes 1 .. n − 2; the last close's decision is never counted; `reasons`
    and `in_wait` are aligned with `attrs["orders"]`; only limit orders can be inside the wait; `held` by hand, on
    closes 1 .. n − 2 only (a hold at the last close is not listed).
12. **Identity with `portfolio.rebalance`** (hypothesis, with `@example`s): for f in {0, 0.5, 1}, W = 1 and no
    reset, `hold_mix` equals `rebalance(band = b·T, every = 1)` with the same limits and h, bit for bit: every
    column, `orders`, `fills`, `trade_returns` and `n_trades`. Also without limits.
13. **Identity with limit-only:** with a band that can never fire (b·T ≥ 1 for every coin) and no reset, for any W,
    `hold_mix` equals `rebalance(band = 1.0, every = 1)` bit for bit.
14. **Decisions do not depend on costs** (hypothesis): orders, reasons, in-wait flags, held rows and both weight
    columns are bit-identical under `Costs.zero()`, 1x and 2x, at 500, 5,000 and 50,000 USD, and so is
    `path_hash`.
15. **Accounting identities:** the per-bar identities of the module docstring (fill and no-fill bars), costs off
    against on, trade returns chaining from fill to fill to the wallet's growth, only fills pay, every leg's cost =
    usd × rate(usd) + gas. Against the independent book of coin units and cash in `tests/test_portfolio.py`
    (`unit_book`, `run_checked`), reused or copied.
16. **Tamper the future** (hypothesis, both first-buy readings): every field of both assets changed from row `cut`
    on, except the open of `cut` (a fill price), leaves the orders, reasons, in-wait flags and held rows before `cut`
    and every result row before `cut` bit-identical. Also a shorter panel equals the longer one cut at its last
    close.
17. **Orders follow the rule** (hypothesis, both first-buy readings): at every close, an order is sent exactly when
    steps 1-5 say so, recomputed independently from the result's weights and the close times. No order that is not a
    limit order comes less than W days after the previous counted order (with `first_buy_waits=True`: the previous
    order of any kind). Counting only orders that are not limit orders, no 30-day stretch holds more than ceil(30 / W)
    of them.
18. **Path metrics by hand** on a built path: in-band share, D_out, d̄ and the worst distance, crypto-share drift,
    the longest spell (with a missing close inside), closes in breach, rebalances per 30 days (with and without limit
    fixes), the most in any 30 days, legs, held closes, empty orders; the first buy and row 0 left out. A path where a
    fill at bar t's open moves a coin across its band shows that the metrics read the close-t weights the rule reads,
    not the next row's. Trade sizes by hand: the largest leg and one-day turnover as % of V_open, the smallest leg in
    USD, the first buy's legs apart.
19. **Money metrics by hand:** customer fees and gas from the fill log with V_open = usd / |weight change|, their sum
    against the `cost` column, USD totals, the first buy's cost, the return, Sharpe (`stats.annualized_sharpe`), max
    drawdown (equal to `montecarlo.max_drawdown`) with its peak and trough closes (the start as the peak; ties take the
    first close), the worst day with its close, and the worst 7-day fall with its dates (a pair ending on a missing
    close skipped).
20. **Windows by hand:** the 60 Kraken windows (first and last close of k = 0, 1, 12, 25, 26, 37, 38, 59, and the row
    counts 365 / 366 / 364); Binance exactly k = 8 .. 59 from the calendar (k = 7 is not listed, whatever the panel
    holds); nothing after 2023-01-01; `window_slice` refuses a slice with a missing or extra close.
21. **The grid:** all 27 mixes pass `check_targets` with the limits as read and h = 0.02, including the edge 0.78 /
    0.5; the 8 left-out pairs are refused; under a tighter `tmp_path` `risk_levels.yaml` some mixes are refused.
22. **Decision rules on hand-made runs tables:** rule B at its boundaries (a median of exactly 7 passes, a value just
    above fails; a 90th percentile of exactly 30 passes), the guard on looser caps, "more than 8"; rule A (a rate of
    exactly 1.0 and fees of exactly 0.25% pass), the guard on wider bands, "none" with its flag, the widest over
    wallet sizes; rule C (I exactly 0.90 passes), the guard, "ABOVE 8", "NO EVIDENCE", SUPPORTED and WEAK at the
    factor-2 boundary, C undefined, the bands held back; rule D's robust values and the ROBUST / NOT ROBUST labels;
    rule E's MISSING and dropped pairs. Also (A2): rule C's order (a table that is both NO EVIDENCE and short of
    CLOSE_SHARE is NO EVIDENCE; one that is short of CLOSE_SHARE at 8 is ABOVE 8 even if a tighter cap meets it);
    the value test WEAK at F(none) − F_L = 0 **and** < 0, and with I undefined; rule D's order and the larger of two
    outcomes (2 against 4; a number against ABOVE 8); NO EVIDENCE on both sources and on one (the other's outcome,
    labelled NOT ROBUST); the robust value test at N_up,rob on each source, where the sources' own N_up would give a
    different verdict, SUPPORTED only when all four pass, none at ABOVE 8 or NO EVIDENCE; the headline's bands held
    back from N\*_rob; CONFLICT from either trigger (N\*_rob(b\*_rob) > N_up,rob, and b\*_rob "none"), no CONFLICT when
    N_up,rob is not a number, and the default under the limit (its guard on wider bands, the widest over wallet sizes,
    "none"), on the robust and the primary values; the descriptions of section 9 (the other reading, the limit-reading
    subsets of 12 and 20 mixes, the years); the falls tables (positive sizes, the worst over windows with its window,
    the label).

`tests/test_holdmix_run.py` (synthetic dry runs in `tmp_path` only; the real catalog loader is replaced by one that
fails the test):
- **Start guards:** a dirty tree; a real run over an existing `results/hold-mix-cap/` or a RUNLOG run 0; the
  `--amendment` rules; other `--out-dir`, `--config-dir` or `--catalog-dir` on real data; a grid the limits as read
  refuse; a `tmp_path` `risk_levels.yaml` whose steady entry lacks `min_cash_pct` or `max_coin_pct` (refused, exit
  2); a snapshot or bars-hash mismatch; wrong row counts or panel hashes; a panel lacking the first close of a pinned
  window (a Binance stand-in panel without the close 2017-09-02 stops the run).
- **The start record and the RUNLOG line exist before any bar is read.** A loader that returns a close after
  2023-01-01 stops the run before any backtest (stop rule 3), and that is recorded.
- **Every run is logged:** the row count of `runs.parquet` equals the grid's count; failures carry their error text
  and make the affected decisions MISSING.
- **Each consistency stop fires** (a monkeypatched engine that breaks each check once).
- **Every reported number is recomputed from its inputs:** `decision.json`, `runs.csv` and `falls.csv` rebuilt from
  `runs.parquet` (and `limit_only_bands.parquet`) by an independent pandas computation; workers 1 and 2 give the same
  `runs.csv`, `falls.csv` and `decision.json` byte for byte.
- **The reported worst falls** (A3): each is recomputed from `runs.parquet` as −100 × the minimum of `max_drawdown`
  over the windows (with that window named), and as the full run's value with its peak and trough dates; a falls
  table built from the 90th percentile or the median of the signed number fails this test.
- **Labels:** every row of `runs.csv` and `falls.csv` carries the label, `decision.json` has the `label` and `status`
  fields, and `runs.csv` has no return, Sharpe, drawdown or worst-day column.
- Dry runs never write into the repo.

**Hand breaks.** In a scratch copy, each of these deliberate breaks must fail at least one test, and the result goes
in the TESTING.md bug log: an absolute band (\|w − T\| > b); `≥` for `>` in the band; the wait counted in rows; `≤`
for `<` in the wait; the wait rounded down; the first buy counted; **the first buy starting the wait** (A1); a limit
order held by the wait; a limit order not restarting the wait; a reset not waiting; a reset counted from the last
rebalance instead of the last order; the zero coin checked at b = 0; the last close's decision counted; the first
buy's fees counted; D_out divided by n instead of n − 1; gas left in the customer fees; each `≤` threshold in rule
A-C turned into `<`; the looser-cap and wider-band guards removed; the robust value taken as the smaller. Added by
the review (A2-A4): the robust value test run at each source's own N_up; the value test WEAK only at F(none) = F_L
(not when F(none) < F_L); rule C's outcomes checked in another order; one-source NO EVIDENCE taken as the robust
outcome; the CONFLICT check dropped; E including row 0; a held band break remembered after the wait; the breach
judged at limit − h; in-band measured one row late (after the next fill); the wait counted from the fill row t + 1;
the Binance windows taken from the data; `held` counted at the last close; a worst fall taken as the 90th percentile
(or the median) of the signed number; `headroom` given a default of 0.

TESTING.md gets the new files in section 3 and a row for every failure found while building (rule 1: triage first;
rule 3: a hypothesis case becomes an `@example`). `filterwarnings` stays as it is, and no test is weakened.

## 15. Known weaknesses, and what is not modelled

- **Scouting.** The reference engine, not Nautilus. The costs are pessimistic placeholders. Kraken quotes in USD and
  Binance in USDT, while Base trades against USDC. USDC is priced at 1, with no yield and no depeg.
- **In-sample, and seen before.** These are the train years the rebalance-steady study already searched (L1-L3), and
  this plan's thresholds were set knowing roughly how often bands trade in them.
- **Few independent years.** The 60 windows overlap heavily, and train holds six years. The 90th percentiles over
  windows reflect a few busy stretches (2017-2018, 2020-2021). Binance has no window before September 2017. The
  windows under-weight early 2017 and never include December 2022. Rule B by start year and on the five
  non-overlapping windows is reported as a description (section 9).
- **The pool weights mixes equally.** Low crypto shares have five BTC/ETH splits and 0.78 only one, so the pool leans
  toward low crypto shares. Real customers' choices are unknown. Per-s results are reported.
- **Every window starts fresh.** A real customer starts on any day, adds or withdraws cash, and edits the mix. Under
  the lab's reading (A1), a rebalance can come the day after the first buy; the first rebalance starts the wait.
- **The limit reading is the lab's, not yet the owner's** (section 4.2). The other readings are only approximated, by
  dropping the mixes they would not allow (section 9).
- **Daily closes only, at 00:00 UTC.** The app checks once a day at a fixed time that is not decided yet. Intraday
  moves past a limit are not seen, and the wallet can sit past a limit between a close and the next open.
- **Not modelled: pauses and approvals.** The customer's daily or weekly loss limit pauses the tool (owner,
  2026-11-20, rules 2026-11-21; confirmed again by the owner on 2026-11-21: "user loss limits should pause custom
  rules"), and Pause everything stops it. On Approve, a skipped or expired trade never runs. In all of these the mix
  drifts and nothing trades back, past its band and past Steady's limits. Here the tool always runs. The worst day and
  worst 7-day fall per crypto share (section 10) show how much a wallet could lose before or during a pause.
- **What the app does when the tool resumes** (pinned here so the app and the study behave the same way): the rule
  carries on with the same memory. A breach seen at the first daily check after the pause is fixed then, and counts.
  A band break orders at that check if W days have passed since the last counted order, and otherwise waits for the
  rest of W. The pause neither resets nor restarts the wait.
- **Not modelled: a minimum swap size.** On a 500 USD wallet a 0.05 band on a 5% BTC target trades about 1.25 USD.
  If the app or the router needs a minimum swap size, the study does not model it, and a minimum would break section
  4.6 (decisions would then depend on wallet size). The smallest legs in USD are reported (section 10).
- **Gas** is charged to the wallet (conservative for returns) although the app sponsors it. Gas is reported on its
  own and kept out of rule A's fee condition (section 16, choice 4).
- **Fees as fractions summed over the year** are a close stand-in for the drag on the wallet, not its exact
  compounded effect.
- **No worst fall for the app.** The drawdowns here are in-sample descriptions from the reference engine. The worst
  fall the app shows must come from Nautilus backtests with measured costs, over years agreed with
  `backtest-auditor` (features.md).
- **Parity with the app.** The app's rule must make exactly these decisions (the same first-buy, reset, wait and
  same-close readings). A decision-parity test against `hold_mix` belongs with the app's rule engine, which does not
  exist yet.
- **Production controls the eventual risk note should list** (not modelled; the lab cannot set them; for
  `risk-officer`):
  - (a) The trade router and risk engine must allow a trade back to the mix that brings a wallet back inside the
    Steady limits, even when the wallet starts outside them. "Fails closed" must not block the fix.
  - (b) Post-trade targets must keep cash ≥ min_cash + h and each coin ≤ max_coin − h, read from
    `config/risk_levels.yaml`.
  - (c) The wait, with the limit-fix exception, works exactly as in `hold_mix` (the decision-parity test above).
  - (d) The auto-trading permission's token list is BTC (cbBTC), ETH and USDC only, with amount caps big enough for a
    full rebalance and for the first buy (section 10, trade sizes).
  - (e) A refused fix triggers the "limit hit" push.

## 16. Choices this plan made (for the owner)

**These are the lab's decisions.** The owner said "you decide" on how the cap is enforced (2026-11-21) and has said
they cannot answer these questions. So choices 1-10 below are decided by the lab, before any result, and the app
should do what the study does. If the owner later answers one differently, that is a dated amendment and a new run,
reported next to run 0. It is never a quiet recompute of the headline.

1. **The first buy does not start the wait** (A1). It is not a rebalance, and the wait runs only between rebalances,
   as features.md records ("at least 30/N days (rounded up) between them"). So a rebalance can come the day after the
   first buy. The reset is the exception: "if the tool has not traded for R days" counts from the last trade of any
   kind, the first buy included. The other reading (the first buy starts the wait) is reported as a description
   next to the headline (section 9), because the review showed it can move the recommended cap.
2. **The reset counts from the last trade of any kind**: "if the tool has not traded for R days". A calendar reset
   (for example every 1 January) could fall due a few days after a band trade, inside the wait. The reset is a
   description here, run on the full span only, and enters no decision.
3. **The wait is counted in calendar days by close time**, not in rows, so a missing close never stretches it.
4. **Customer fees leave out gas**, because the app sponsors gas. Rule A's fee condition is about what the customer
   pays; gas is our cost and is reported in USD a year.
5. **The thresholds of section 9** (7 and 30 extra days a year out of band; 1 rebalance per 30 days; 0.25% of the
   wallet a year; 90% of the closeness; the factor 2) are judgement calls, fixed before any result. The full tables are
   reported, so the owner can see how close each band and cap came.
6. **Closeness for the upper limit** uses the mean distance from target, the same yardstick for every band. The
   cap rule uses days outside the customer's own band.
7. **Robustness takes the safer value**: the band and cap that meet the conditions on both sources and at both cost
   levels, and the looser upper limit.
8. **The cap recommendation depends only on the band**, never on wallet size or costs, because the rule's decisions
   do not (section 4.6). Wallet size can change the recommended band through fees.
9. **No Optuna search and no walk-forward.** Nothing is tuned for return, and the study makes no out-of-sample claim.
   That departs from the quant-researcher's usual steps, which are for strategies.
10. **The Steady limits are read as today's lab reading** (section 4.2): 60% caps BTC and ETH each, not cash and not
    the two together. The other readings are reported as descriptions.

**What this study does not decide:**
- **Nothing here changes a limit.** Rule C is evidence for the owner. If the owner adopts an upper limit on rebalances
  a month in writing, `risk-officer` adds it to the steady entry of `config/risk_levels.yaml` and the app's trade
  router enforces it, never a constant in `holdmix.py` or in app code. Limit fixes stay exempt, so such an upper limit
  would bound band and reset trades only. That is why the headline shows the most rebalances in any 30 days, limit
  fixes included, for each crypto share.
- **No number here sets or proposes a Steady drawdown budget.** Budgets come from the Monte Carlo 95th percentile of
  audited strategies. The falls by crypto share are descriptions for the open question of whether Steady's budget
  caps the tool's crypto share (features.md).
- **The 2-point margin.** HEADROOM = 0.02 is fine for scouting, and it is pinned in the config hash, as in
  rebalance-steady. But if the app's controls stop at 78% crypto because of it, it acts as a Steady limit. It should
  then move to `config/risk_levels.yaml` with the owner's approval; the owner has not been asked yet.

## 17. Looks at the data

| # | Date | By | What was looked at |
|---|---|---|---|
| L1-L9 | before run 0 (L9: the review, synthetic only) | see section 2 | Prior looks, disclosed |
| T1 | reserved | | Run 0 (`run.py`): Kraken and Binance daily train bars to 2023-01-01 00:00 UTC |

**Validate-window looks used by this study: 0** (none planned; the study never reads validate or test).

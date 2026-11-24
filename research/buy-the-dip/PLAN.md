# buy-the-dip: pre-registration (the owner's dip ladder)

**Status: PRE-REGISTRATION.** Written 2026-11-24 by the lead, at the owner's request in chat ("Why not both?", meaning
run the downside-volatility study and build the buy-the-dip rule). It was written before any buy-the-dip code or result
existed, and before any bar was read for it. It is committed before the code that runs it.

> **SCOUTING ONLY.** Every number will come from the lab's reference portfolio engine (`lab/runner/portfolio.py` and a
> new `lab/runner/dipbuy.py`), not from NautilusTrader (AGENTS.md hard rule 3; the Nautilus work is on hold). Costs are
> the **placeholder** costs of `config/costs.yaml`, and Kraken and Binance candles stand in for Base prices. Nothing
> here can make anything ready for paper.

**How this plan is written.** It follows protect-gains' plan (`research/protect-gains/PLAN.md`, the small version,
reviewed and run once), because both study a self-directed tool. The windows, the data pins, the index of the crypto
mix, the protocol, the stop rules and the outputs are protect-gains'. Everything specific to the dip ladder is written
out below. The owner asked for lean work, so there is no separate plan review. `risk-officer` confirms the allowed range
(section 13) before run 0, and one `backtest-auditor` audit follows run 0.

## In plain words

The owner's rule, a template the customer owns (`docs/app/features.md`, 2026-11-23):

> "when crypto falls Y% from its recent high, buy crypto with X% of my cash, and buy another X% at each further fall of
> Z%, until at most M% of my cash is used"

It buys small pieces as the price keeps dipping, without draining the cash on a falling market. The app suggests
starting values of X, Y, Z and M, and the customer can change them. It never buys while a "protect my gains" brake has
the wallet stopped.

**What this study does.** It simulates the rule on two-year windows of 2017-2022, for several wallets and 54 settings.
For each setting it measures:
- how often it buys;
- how much cash it puts to work;
- the bad-case fall;
- what it earned or cost against putting the same money in on a fixed monthly schedule ("dollar-cost averaging"), and
  against putting it all in at once.

Rules fixed now pick the suggested starting setting.

**What it does not do.** It claims no edge. The dip-timing study (section 2) already found that waiting for a smarter
dip did not beat buying at once. This study picks a sensible default for a tool, as protect-gains did. The search for
an edge goes on in the strategy studies (downvol-steady now).

## 1. Question

For a Steady wallet using the dip ladder:
- How often does each setting buy, and how much of the cash does it use?
- How deep is its bad-case fall, against spreading the same money monthly and against buying it at once?
- How much does it earn or cost against those two?
- Which (X, Y, Z, M) is the best starting setting by section 9's rules?

There is no hypothesis test and no edge claim, so there are no luck gates (E1, E2, DSR, PBO).

## 2. Prior looks (disclosure)

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| P1 | **dip-timing** (2026-11-20, NO EDGE; `research/dip-timing/RESULTS.md`): buying at the next open after a dip signal beat every rule that waited (in thirds lower down, for an up-day, for a quiet day, or for a model), by 1.4 to 2.7 points a dip on train. No dip-quality filter helped | the lead, the owner | The expectation that the ladder trails buying at once in rising windows; why no edge is claimed |
| P2 | **protect-gains** run 0 and V1 (2026-11-23/24): the brake, the index I, the 24-month windows, and the falls of held mixes | the lead, the owner | The windows, the index and the brake hook |
| P3 | **hold-mix-cap**'s falls of held BTC/ETH/USDC mixes (the lead only) | the lead, the owner | The mixes |
| P4 | rebalance-steady, trend-steady, vol-steady (each NO EDGE) | the lead, the owner | The years' shape: two bear years (2018, 2022), the 2020-21 boom |
| P5 | The 2017-2022 daily prices themselves, through all of those | everyone | Every choice below |

The train window is far from fresh. That is acceptable for a tool that claims no edge. Every threshold below is fixed
before any buy-the-dip run.

## 3. Data (protect-gains section 3, unchanged)

| Item | Pinned |
|---|---|
| Primary | Kraken daily `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN` through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=2023-01-01 00:00 UTC)`: 2190 rows, closes 2017-01-02 .. 2023-01-01; close 2018-01-13 is missing (no ETH bar) and never filled |
| Robustness | Binance daily `BTCUSDT`, `ETHUSDT`, the same `last_close`: 1963 rows from 2017-08-18 |
| Snapshot | `1746a21b75683e76`. Stop unless the bars hash is `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e` and the panel hashes (`steady.panel_hash`) are Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587` |
| Never read | The validate window and the test window. Every frame is checked: `panel.index.max() <= last_close` |
| Costs | `Costs.from_yaml(capital_usd=5000)` (1x) and its `.stressed(2.0)` (2x) |

## 4. The wallet

- **The deposit:** D = 5,000 USD in cash at the window's first close (row 0). There are no later deposits or
  withdrawals.
- **Four start wallets:** a starting crypto share s0 ∈ {0, 0.30} × BTC's share of the crypto f ∈ {0.50, 0.75}.
  - With s0 = 0.30 the first buy, to the targets (s0 · f, s0 · (1 − f)), is ordered at close 0 and filled at row 1's
    open. With s0 = 0 the wallet starts all in USDC.
  - f also sets how every ladder buy is split between BTC and ETH.
- **The Steady limits as read** from `config/risk_levels.yaml` through `portfolio.risk_limits("steady")`, with
  h = 0.02:
  - cash at least min_cash (0.20) and each coin at most max_coin (0.60);
  - the run refuses to start if the file's values differ from these, or if a start's targets fail
    `portfolio.check_targets` with h = 0.02.
- **Limit fix** (the rule never sells otherwise):
  - At a close t where cash < min_cash or a coin > max_coin (judged at the limits, with `portfolio.LIMIT_TOL`, as
    `portfolio.rebalance` judges them), the order scales both coins by λ. λ is the largest value ≤ 1 with every coin
    ≤ max_coin − h and cash ≥ min_cash + h, so the crypto is sold in its current BTC:ETH proportion.
  - A limit fix replaces any ladder buy due at that close. The buy's pieces are consumed and recorded as "blocked by
    the limits".

## 5. The rule (exact)

**The index I.** For each start's f, `protect.index_signal(panel, f)`: chain-linked over the full train panel, I = 1 at
row 0, close to close. It is computed once per source and f and passed into each window's run. "Crypto" in the owner's
rule is this index.

**The recent high.** H_t is the highest I over the panel rows whose close time is within 365 days before close t:
- t − 365 days < close ≤ t, so close t itself is included;
- it starts at the panel's first row, so the lookback is shorter in early 2017;
- it is read from the full panel, so a window's first close already has its year of history (from 2017-01-02 on).

**Why 365 days, and not a shorter "recent" window:** the ladder re-arms only at a new high of the same window (below).
A 30- or 90-day high would re-arm on every bounce inside one bear market, and each new ladder would spend M of the
remaining cash again. That is against the owner's "without draining the cash on a falling market". The app will say
"from its highest price of the past year". A shorter window can come back as an amendment or a later study.

**States.** The ladder is **armed** at row 0.

**Trigger.** At the first close t* (from row 0) where the ladder is armed and `I_t <= (1.0 - Y) * H_t`, a ladder starts.
It fixes, at t*:
- **H\*** = H_{t\*};
- **the base B** = the USDC in the wallet at close t*, in USD (V_{t*} × the cash weight), after any first buy ordered at
  the same close. At close 0 with s0 = 0.30 that is (1 − s0) × D;
- **the lines** line_k = (1 − Y) × H\* × (1 − Z)^(k − 1), for k = 1 .. K, with K = ceil(M / X − 1e-9).
  - "Each further fall of Z%" is read as Z% below the previous line. It is relative, as Y is.
- **the pieces:** X × B for k < K, and the remainder (M − (K − 1) × X) × B for k = K.
  - So the ladder never orders more than M × B in total.
  - With X = 0.10 and M = 0.25 the pieces are 10%, 10% and 5% of B.

**Buys.** At each close t from t* on, while the ladder runs:
- every line not yet crossed with `I_t <= line_k` is crossed now;
- the crossed lines' pieces are summed into **one order** at close t, filled at row t+1's open;
- the order adds the piece's USD to the crypto, split f to BTC and (1 − f) to ETH, at close t's prices: the target
  vector is the current weights plus (f, 1 − f) × piece / V_t;
- a line exactly at I_t is crossed.

**Caps [R1].** If the target would put a coin above max_coin − h or cash below min_cash + h, the added amount is cut
to the largest amount a, with 0 ≤ a ≤ the crossed pieces' sum, that keeps both. The cut part is lost, never carried
over, and is recorded as "capped".
- If no a > 0 keeps both (the wallet is within h of a limit but not past it, so no limit fix is due), no order is sent
  at that close and the whole amount is recorded as "capped". The ladder never sells; only a limit fix does.
- Every order's targets (the first buy, a ladder buy and a limit fix, in the twins too) pass `portfolio.check_targets`
  with the Steady limits as read and h = 0.02 (section 10).

**End of a ladder.** The ladder **re-arms** at the first close after t* where `I_t >= H_t` (I is the highest of its past
365 days). Lines not yet crossed are dropped. The next ladder takes its base B from the cash at its own trigger, so a
later ladder can only spend M of what is left.

**Checked at:** daily closes only. **One order per close:** the first buy, the ladder's buys and a limit fix all decide
at a close. A limit fix replaces the buy, and a first buy and a ladder buy at close 0 are one order. The decision at the
last close is never filled; a line crossed there is recorded as "not filled".

**Behind a brake (the app's rule; tested, not simulated in the grid).**
- While a protect-gains brake has the wallet stopped, the ladder is not asked: nothing buys, and lines crossed while
  stopped are not bought.
- After the brake's buy-back, the ladder starts **armed afresh**, with no lines carried over.

## 6. Comparators (each run against its own twins, in the same window and with the same costs)

- **hold:** the same start wallet with no ladder: the first buy, then only limit fixes.
- **dca-same:** the same total USD that the ladder ordered in that run (its pieces as ordered, before caps), spread in
  12 equal pieces.
  - Piece j (j = 0 .. 11) is ordered at the first close at least 30 × j days after close 0, and split f / (1 − f).
  - It has the same caps and limit fixes. Capped amounts are recorded.
- **lump-same:** the same total, ordered at close 0 (with the first buy), with the same caps and limit fixes.

A run whose ladder ordered nothing has twins equal to hold. The twins use the dip run's total, a number known only at
the window's end. They are yardsticks, not strategies a customer could run.

## 7. The grid and the counts

| | Values | Count |
|---|---|---|
| Y, the first fall | 0.10, 0.20, 0.30 | 3 |
| Z, each further fall | 0.05, 0.10, 0.20 | 3 |
| X, each piece | 0.10, 0.25 | 2 |
| M, the most of the cash used per fall | 0.25, 0.50, 1.00 | 3 |
| Settings | | **54** |
| Start wallets | section 4 | 4 |
| Windows | protect-gains' 24-month windows (`protect.rolling_windows`): Kraken k = 0..48 (49), Binance k = 8..48 (41) | |
| Costs | 1x, 2x | |

Each (start, window) has 54 dip runs, 54 dca-same and 54 lump-same twins, and 1 hold run: 163 runs.
- **Stage 1, the decision pool** (Kraken 1x): 163 × 4 × 49 = **31,948 runs**.
- **Stage 2, the robustness pools** (Binance 1x, 41 windows; Kraken 2x, 49 windows): 163 × 4 × 90 = **58,680 runs**.
- **Total: 90,628 runs.**
- Amendment A1 times a busy run on synthetic bars before run 0. The run refuses to start above 240 CPU-minutes (stop
  rule 7).

## 8. Measured per run

- **F, the worst fall:** `-holdmix.money_metrics(result, costs)["max_drawdown"]` over the whole window, as in
  protect-gains. F_hold, F_dca and F_lump are the twins'.
- **Buying:**
  - the ladders started;
  - the orders and pieces filled;
  - the days from close 0 to the first ladder order;
  - **δ, the cash put to work:** the USD ordered by the ladder (before caps) / B_0, with B_0 = (1 − s0) × D;
  - the USD capped, and the USD blocked by the limits;
  - the lines "not filled".
- **Money:**
  - T_dca = V_end / V_end(dca-same) − 1 (positive when the ladder beat the same money spread monthly);
  - T_lump = V_end / V_end(lump-same) − 1;
  - T_hold = V_end / V_end(hold) − 1;
  - **G, the gain per dollar moved:** (V_end − V_end(dca-same)) / (the USD the ladder ordered). It is undefined
    (NaN) in a run whose ladder ordered nothing. T_dca grows with the money moved, so a setting that moves little
    has T_dca near 0 either way; G compares the timing per dollar;
  - the USDC left at the last close, as a share of V_end.
- **The falling knife:** for each ladder, the fall of I from the open of its last order's fill row to I's lowest close
  before the ladder re-arms (or the last close). In plain words: "after its last buy, the price fell another ...".
- **Fees and gas a year**, from `money_metrics`.

## 9. Decision rules (fixed now, before any result)

Stage 1's pool (Kraken 1x) unless a rule names another. Every percentile is `numpy.percentile(..., 90)` (linear).
MISSING flows through: a rule that needs a MISSING number gives MISSING, never a pass. A failed run makes every rule
whose pool holds it MISSING.

**D1. The default setting.** For each setting θ and start σ (49 runs each):
1. **Active:** at least one ladder order is filled in at least half of the windows (≥ 25 of 49).
2. **No deeper bad case than spreading the money:**
   - Q = the 90th percentile of F over the 49 dip runs;
   - Q_dca = the same over their 49 dca-same twins;
   - both `Q <= Q_dca` and `max(F) <= max(F_dca)` must hold.
3. θ is **usable** if 1 and 2 hold for each of the 4 starts.
4. **Ranking among the usable settings:**
   - G̃ = the median of G over θ's runs with a ladder order (at least 100 of its 196, by rule 1);
   - the candidates are those whose G̃ is within 1e-12 of the largest G̃;
   - among them, the larger median δ wins (more cash put to work);
   - then the larger Y, the larger Z, the larger X and the smaller M (fewer, rarer buys).
5. No usable setting gives **NO DEFAULT**.

**D2. Robustness labels** (they decide nothing, but are printed next to the default; protect-gains D4's rules):
- A default is **ROBUST** only if each check gives the same default, or NO DEFAULT on both sides.
- A check that moves it gives **NOT ROBUST (check named)**; a MISSING check gives **MISSING (check named)**.
- Order: NOT ROBUST before MISSING before ROBUST.
- **The checks:**
  - **Boom years:** D1 on the Kraken 1x pool without the windows that overlap BTC's best calendar year, then without
    those overlapping its two best. This uses `protect.boom_removals` and `protect.windows_without`, and fewer than 12
    windows left gives MISSING.
  - **Binance** (its 1x pool, 41 windows; Active needs ≥ 21 of 41).
  - **2x costs** (the Kraken 2x pool).

**D3. The description printed with the default** (decides nothing):
- G, T_dca, T_lump and T_hold: median, 10th and 90th percentiles, and the share of windows above 0, per start;
- the same by the year of each window's first close;
- Q, Q_dca, Q_lump and Q_hold per start, against the Steady budget of 35% as read. The budget is shown, not enforced:
  a held Steady mix can already pass it in 2018, as protect-gains found;
- the falling knife: the median and the worst;
- δ, and the USDC left.

The app's wording follows from D3, for example: "In 2017-2022 tests, buying on dips beat spreading the same money
monthly in N% of two-year periods. After its last buy the price fell up to K% further."

## 10. Checks the run must pass (consistency stops)

- **When the ladder buys does not depend on costs.** The order closes of each dip run are equal at 1x and 2x on Kraken,
  for every setting, start and window. Their amounts may differ, since B reads the wallet.
- **One-pass recompute:** the crossed lines, the triggers and the re-arms are recomputed from I alone, and must equal
  the run's.
- **Twins:** each twin's ordered total equals its dip run's total (before caps), and a dip run with no order has twins
  equal to hold bit for bit.
- **Accounting** matches an independent book of coin units and cash on every 9th run, at run time.
- **[R1] Every order's targets** (the first buy, ladder buys and limit fixes, in dip runs and twins) pass
  `portfolio.check_targets` with the Steady limits as read and h = 0.02, checked at every order.
- **Counts** equal section 7's exactly (31,948 and 58,680), failures included.
- **A config hash** covers `dipbuy.py`, `protect.py`, `portfolio.py`, `holdmix.py`, `reference.py`, `trend.py`,
  `lab/validation/*.py`, the data loaders, `config/*.yaml`, `pyproject.toml`, `uv.lock`, the study script and this
  plan. The run stops if any of them changes during the run.

## 11. Code to build, and its tests (TESTING.md section 7)

- **`lab/runner/dipbuy.py`:** the H rule, the ladder, the caps and the limit fix, the twins, the measures of section 8,
  and the rules D1-D3.
  - The executor is `portfolio._simulate`, reached either through `protect.run_overlay`'s `Step` protocol (if it fits)
    or through a small driver in `dipbuy.py` that calls `_simulate` as `protect._pass` does. The ladder needs the
    wallet's USD value at each close.
  - `protect.py`, `holdmix.py`, `portfolio.py` and `trend.py` are **not edited**: each is in a completed study's
    config hash. `protect.index_signal`, `rolling_windows`, `boom_removals` and `windows_without` are reused
    read-only.
- **`research/buy-the-dip/run.py`:** the grid in its two stages, the decisions and the outputs. It has protect-gains'
  start guards:
  - the dirty tree;
  - the test-window guard;
  - the snapshot and panel hashes;
  - the RUNLOG before any bar;
  - dry runs only in scratch folders;
  - the pinned folders;
  - the projection guard;
  - stop and crash logging, with every block that returned kept.

**Tests** (`tests/test_dipbuy.py` and `tests/test_dipbuy_run.py`; synthetic and hand-built paths only, no catalog):
- **Tamper the future** (hypothesis, with cuts at triggers, line crossings, re-arms and limit fixes): H, the triggers,
  the lines, the orders and every result row before a cut never change when later bars change. **Touch the present:**
  changing close t's price changes I_t and H_t.
- **Hand-built paths:**
  - **The trigger:** exactly at `(1.0 - Y) * H` it fires, and one ulp above it does not.
  - **H's window:** a high 365 days back counts; one 365 days and one microsecond back does not; a missing close.
  - **The lines and pieces by hand:** K and the remainder (X 0.10, M 0.25 gives 0.10, 0.10, 0.05); a gap through
    three lines gives one order of three pieces; B at a trigger on close 0 with s0 = 0.30.
  - **Re-arming:** exactly at `I == H` it re-arms, and one ulp below it does not; a re-arm drops the lines not crossed;
    the next base is the cash left.
  - **Caps and limit fixes:** each coin's cap and the cash floor, each binding alone; λ by hand; a limit fix replaces
    a due buy and consumes its pieces; a fill at the last close is "not filled".
- **The twins by hand:** dca-same's 12 closes in calendar days across a missing close; lump-same at close 0 together
  with the first buy; a dip run with no order has twins equal to hold bit for bit.
- **Identities:**
  - with no limit breach, hold equals `portfolio.rebalance` at the start targets with band 1.0 (or the equivalent
    one-order run), bit for bit;
  - with Y so large that nothing triggers, the dip run equals hold bit for bit;
  - the order closes are equal at 1x, 2x and five wallet sizes.
- **Accounting** against an independent book of coin units and cash, with each order's own target vector (hypothesis).
- **Behind a brake:** through `protect.run_overlay` with a brake that stops the wallet, the ladder is not asked while
  stopped (a spy), crosses no line then, and starts armed afresh after the buy-back.
- **The rules:** D1-D3 by hand on hand-made run tables, every boundary exact:
  - 25 of 49 windows active, and 24 not;
  - `Q == Q_dca` passes, and one ulp more fails;
  - the worst-F guard at equality;
  - G̃ ties within 1e-12 broken by δ, then the order of section 9; runs without an order left out of G̃;
  - one start failing makes θ unusable;
  - MISSING propagation;
  - D2's labels and their order;
  - the boom windows by hand.
- **The run script:**
  - the start guards and data stops (protect-gains' list);
  - the counts by hand;
  - every reported number recomputed from the runs table by an independent statement of section 9 in the test;
  - every 9th run rerun from scratch;
  - `runs.csv` with one row per run;
  - workers 1 and 2 give byte-identical outputs.
- **Hand breaks** by the builder (about 25), each failing a test, recorded in the bug log.

## 12. Protocol, stop rules and amendments

**Order of work:**
1. Commit this plan.
2. `risk-officer` confirms section 13 (config only). The build may run at the same time.
3. Build the code and tests (TESTING.md bug rows from the next free number).
4. The three tiers on the build's commit: the full tier with 100% branch coverage, the deep profile, and ruff with the
   dashboard.
5. A1 times the run (synthetic bars only); the projection guard applies.
6. Run 0 (stages 1 and 2) on the train window, then RESULTS.md and one audit.

**Stop rules:** protect-gains section 11's, 1-7, unchanged:
1. The three tiers must pass on the run's commit, with a clean tree.
2. The hashes and the row counts.
3. A bar after 2023-01-01 stops the run, and nothing from it is used.
4. A failed run is logged and the grid goes on; its pools give MISSING.
5. A consistency stop is a bug: a regression test, a dated amendment and a full rerun.
6. At most 2 amendment runs, and a crash is rerun, never resumed.
7. The projection guard at 240 CPU-minutes.

**No validate look is planned.** The study claims no edge and picks a tool's default, as protect-gains did. A look can
only come as a dated amendment with its own pre-registration (as protect-gains' V1), before any validate bar is read
for this study.

**Amendments:**
- **R1 (2026-11-24, after `risk-officer`'s review, before any code, run or bar):** the caps never give a negative
  amount (section 5); every order's targets are checked (section 10); section 13 confirmed with the exact values the
  app offers and the wording notes.
- **R2 (2026-11-24, after the build and its code review, before A1, run 0 or any market bar): readings settled.**
  The build (TESTING.md #71, #72) and the review (#74) found four places where this plan is loose or contradicts
  itself. Each is settled here without any result, and the code already follows it (`dipbuy.READINGS_PINNED`,
  `run.py`'s `INTERPRETATIONS`, both in the config hash and the start record):
  1. **H's window is section 5's**: t − 365 days < close ≤ t, so a high exactly 365 days back does **not** count and
     one 365 days minus one microsecond back does (365 daily closes, close t included). Section 11's test-list line
     "a high 365 days back counts; one 365 days and one microsecond back does not" contradicted section 5. Section 5
     is the exact rule, so section 11's line is read as "a high exactly 365 days back does not count; one 365 days
     minus one microsecond back does; a missing close".
  2. **Section 10's "order closes equal at 1x and 2x"** is read as the ladder's own decisions: the triggers, the
     crossed lines and the re-arms (`dipbuy.events_hash`), compared exactly on every Kraken dip run's 1x/2x pair (a
     stop rule 5). They come from I and H alone, which hold no cost, and the one-pass recompute checks them on every
     run. The orders actually sent can differ, since a cap or a limit fix reads the wallet, which costs move by a hair.
     Those pairs are counted (`orders_differ_1x_2x`) as a description. Section 11's identity "the order closes are
     equal at 1x, 2x and five wallet sizes" is read the same way: the events always, and the orders where no limit is
     near.
  3. **"Ordered (before caps)"** = the amounts sent + capped + blocked by a limit fix. Lines crossed at the last close
     are "not filled" and are not in it. It feeds δ, G and the twins' totals.
  4. **"A dip run with no order"** (twins equal to hold) is a run whose ordered total is 0.
  Smaller readings, recorded with the code and listed here so nothing is chosen after a result: a cut that leaves at
  most 1e-9 of the wallet (`LIMIT_TOL`) is "no a > 0"; the knife is 1 − (lowest I from the last order's fill row
  through the re-arm close, or the last close) ÷ (I at that fill row's open), signed, the worst the largest; D1 is
  MISSING if any run of any kind in its pool failed, "active" is 2 × active windows ≥ windows (boom pools too), the
  median δ is over every run of the setting and G̃ over the runs with an order filled; D3 is described at the default
  only and shows the drawdown budget as read; behind a brake the buy-back restores the start's targets and the ladder
  is armed afresh (tests only, not in the grid); the snapshot id is recorded and the hashes decide, as in
  protect-gains; the config hash's "data loaders" are `panel.py`, `catalog.py`, `external.py` and `loaders.py` with
  the files they import (`interface.py`, `steady.py`, `lab/config.py`); a failed dip run's twins are logged as
  failed; the `--fast` grid is 4 settings × 2 starts.
- **A1 (2026-11-24, on commit `7d582ef`, after the tiers passed on `7d582ef`; synthetic bars only): 36.1
  CPU-minutes, under the 240 limit.** `run.py --time` on synthetic bars (731 rows, 20 repetitions; the busy setting
  (Y 0.10, Z 0.05, X 0.10, M 1.00) from the all-USDC start with f = 50%, which gave 4 ladders, 21 orders, 23 pieces
  and 7 limit fixes) gives 28.7 ms a dip run, 22.9 ms a dca twin, 20.3 ms a lump twin and 19.2 ms a hold run, each
  with every check. So the plan's 90,628 runs take about 36.1 CPU-minutes, about 18 minutes on 2 workers. Run 0
  repeats this timing at its start, and stop rule 7 applies.

## 13. Allowed range (`risk-officer`, 2026-11-24, config only) [R1]

**Confirmed.** The app offers these values only, in every combination (the 54 settings of section 7):
- Y, the first fall from the past year's highest close: 10%, 20% or 30%;
- Z, each further fall below the previous line: 5%, 10% or 20%;
- X, each piece: 10% or 25% of the USDC held when the fall starts;
- M, the most used per fall: 25%, 50% or 100% of that USDC;
- f, BTC's share of each buy: 50% or 75%. Any other split is untested.

The start wallets (all USDC, or 30% crypto) are conditions, not settings. A customer's own mix gets the same rule, but
its numbers are measured at these two only.

**Inside the Steady limits.**
- Every combination stays inside the Steady limits as read (cash ≥ 20%, each coin ≤ 60%, h = 0.02) at every close the
  rule decides at.
- Every order's targets pass `portfolio.check_targets` with h = 0.02: the caps (section 5) and the limit fix
  (section 4).
- Between closes, price moves can carry a wallet past a limit. The next close's limit fix brings it back to 22% cash
  and 58% per coin, as `portfolio.rebalance` does.
- The ladder never spends the reserve. M = 100% means spending down to 22% cash, or less if a coin reaches 58% first
  (at f = 75%, near 77% crypto).
- The app must not present any setting as keeping a Steady wallet inside its 35% budget (D3). The budget is shown, not
  enforced, and a full ladder can hold up to 78% crypto.

**App wording notes:**
- **Y** is the fall of the customer's BTC/ETH split, measured from the highest daily close of the past 365 days. It is
  not BTC alone.
- **Show every line.** The deepest line ranges from 10% below the high (Y 10%, X 25%, M 25%: one line) to 91% below it
  (Y 30%, Z 20%, X 10%, M 100%: 10 lines).
- **M is per fall,** as a share of the USDC held when that fall starts, so a later fall gets M of what is left. At
  M = 100% the first fall spends down to the 22% reserve.
- **Re-arming** needs a new one-year high, which after a crash and a sideways year can be far below the crash's peak.
  So a second ladder can start inside a long bear market.
- **Buying into a crash.** With Y 10%, Z 5%, X 25% and M 100%, the wallet reaches about 78% crypto within a 23% fall,
  and rides any deeper fall fully invested; a further 50% crypto fall then costs the wallet about 39%. Capped amounts
  are lost, not saved for lower prices.
- **It can sell.** When rises take cash below 20% or a coin above 60%, a limit fix sells back to 22% / 58%, and it
  replaces that close's buy.
- **An all-USDC start** buys nothing if crypto never falls Y from its yearly high.
- **With "hold this mix" on the same wallet** (not simulated), the mix tool would sell dip buys back toward the mix.
  The app allows one tool or the other on a wallet, or labels the combination untested. Ladder buys are not band or
  reset trades, so they neither count against nor get around `hold_mix_max_rebalances_per_30d`.

**Production must ship what was tested** (the app enforces these):
- the check at the daily close (00:00 UTC), one order per close, filled at the next open; the index, the 365-day high
  and the inclusive line crossings of section 5;
- ladder targets pass `check_targets` with h = 0.02 at the fill (re-capped at the fill price if the router sends USD
  amounts);
- a ladder's total is at most M × B;
- buys go only from USDC into BTC/ETH in the f split, and the only sales are limit fixes;
- coins BTC, ETH and USDC only;
- a protect-gains brake wins, and the ladder starts armed afresh after its buy-back;
- B is fixed at the trigger: a deposit made during a ladder is not added to its pieces, or the case is labelled
  untested.

**No owner-approved limit is loosened.** h tightens 20% and 60% to 22% and 58%; `LIMIT_TOL` is `rebalance`'s round-off
allowance; the coin list is the file's; the hold-mix limit is untouched. The 35% budget is shown, not enforced, as in
protect-gains' confirmation. If the owner wants the budget to bind self-directed tools, the range would be narrowed
from its riskiest end after D3's numbers, as AGENTS.md allows.

## 14. Outputs

- **RESULTS.md**, whatever the outcome:
  - the plain-words summary;
  - the default with its label;
  - D3's description;
  - the full table per setting and start;
  - every deviation.
- **The committed record:** `runs.csv` (one row per run, with F, δ, G, T_dca, T_lump, T_hold and the buying measures; no
  Sharpe column), `RUNLOG.jsonl` and `decision.json`.
- **Not committed:** `results/buy-the-dip/` (git-ignored), which holds the full tables.

## 15. Known weaknesses

- **Not fresh data,** and no validate look.
- **Overlapping windows:** the 49 two-year windows overlap heavily, so one crash stands behind many windows.
- **The twins use the run's own total,** known only at the end. They measure timing, not a strategy a customer could
  follow.
- **One wallet size** (5,000 USD); no later deposits; one lookback for the high (365 days); daily checks only.
- **The ladder never sells** (only the limit fix does), so its crypto share can only fall by price moves or a limit
  fix. That is the owner's rule as written.
- **f is 50% or 75% only;** other BTC/ETH splits are untested (section 13).
- **The scouting engine and placeholder costs.**

## 16. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| P1-P5 | before this plan | section 2 | Prior looks, disclosed |
| Plan | 2026-11-24 | the lead | No market data. Read: protect-gains' PLAN.md; dip-timing's RESULTS.md summary; `protect.py`'s function list, `Step` protocol, `run_overlay` and `index_signal`; `portfolio._simulate`'s signature; `docs/app/features.md`'s buy-the-dip and protect-gains rows |
| Risk | 2026-11-24 | `risk-officer` | No market data. Read: this plan's sections 4, 5, 7 and 13; `config/risk_levels.yaml`; `portfolio.risk_limits`, `check_targets` and `LIMIT_TOL`; protect-gains' section 12. A scratch check on random weights (config only). It read no result file |
| Build | 2026-11-24 | `quant-researcher` | No market data: synthetic bars and hand-built paths only (TESTING.md #71, #72) |
| Review | 2026-11-24 | two reviewers, a verifier, a fixer | No market data: the code, the tests and synthetic dry runs (#74; R2) |
| Run 0 | 2026-11-24 | the lead | The train years (Kraken and Binance daily bars, 2017-2022), commit `e62233e`: 90,628 runs; default (0.30, 0.10, 0.25, 1.00), NOT ROBUST (`RESULTS.md`). No validate or test bar |
| Audit | 2026-11-24 | `backtest-auditor`, a fact-checker, a verifier | The train years only: all 90,628 runs rebuilt with the auditor's own ladder and book, D1-D3 recomputed, tamper checks, the other reading of the one-year high, and descriptions behind RESULTS.md (`AUDIT.md`). No validate or test bar |

**Validate-window looks used for buy-the-dip: 0.**

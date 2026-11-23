# protect-gains: pre-registration (DRAFT, small version)

**Status: DRAFT, written 2026-11-23 by the lead before any protect-gains code or result exists; not yet reviewed and
not frozen.** The first draft (commit `5a83caf`) was cut down the same day to this **small version** at the owner's
request ("option 2", in chat, because of a usage limit). That draft was never reviewed or run. What was cut is listed
in section 12. Any change after this file is committed is a dated, named amendment in section 11. No protect-gains
code exists, no market bar was read for this plan, and no stop of this design has been run.

> **SCOUTING ONLY.** Every number this study produces will come from the lab's reference portfolio engine
> (`lab/runner/portfolio.py` through `lab/runner/holdmix.py` and a new overlay), not from NautilusTrader (AGENTS.md
> hard rule 3; the Nautilus work is on hold). It uses the **placeholder** costs of `config/costs.yaml`, and Kraken and
> Binance candles stand in for Base prices. It cannot make anything ready for paper.

## In plain words

Customers will be able to switch on a **"protect my gains"** brake. When their wallet falls too far, the app sells
the coins to USDC cash. Later it buys the mix back, either automatically when the market turns up again or when the
customer says so. The owner (2026-11-23, in chat) wants **both kinds of line** and **both kinds of buy-back** offered,
each with a **starting setting picked by our simulation**, which the customer can change:

- **A. "Sell if it falls X% below its highest value."** Example: $1,000 grows to $2,000; at X = 20% it sells at
  $1,600.
- **B. "Keep at least Y% of my profit."** Example: $1,000 grows to $2,000; at Y = 60% it sells at $1,600.

This is a **safety brake, not a money-maker**. trend-steady already found that a stop does not earn more than stops
at random weeks (section 2), so this study claims no edge. It measures four things: how much the brake cuts the
bad-case fall, what it costs, how often it fires, and how far below the line it really sells. It then picks the
cheapest setting that gives meaningful protection.

## 1. Question

For a customer using the **"hold this mix"** tool with a protect-gains brake on top:

- How often does each line fire?
- How much does it cut the bad-case fall?
- What does it cost in fees and missed rebounds?
- How far past the line does it sell?
- Which setting of A, of B and of the buy-back is the best starting setting by the rules of section 8?

There is **no hypothesis test and no edge claim**, so there are no luck gates (E1, E2, DSR, PBO).

## 2. Prior looks (disclosure)

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| P1 | trend-steady's stop-loss variant (RESULTS.md, 2026-11-23): sell after a 20/30/40% fall from the wallet's top, buy back when the trend turns up. On top of the trend rule it fired 4, 2 and 0 times in 2018-2022. At 20% it trimmed the worst fall by about 4 points, and it did no better than placebo stops | the lead and the owner | The levels grid (section 5), and the expectation that loose levels rarely fire |
| P2 | hold-mix-cap's results (the lead's K10): the falls of held BTC/ETH/USDC mixes by crypto share, mostly the 2018 crash | the lead and the owner | The mixes (section 4), and the tool's default band and cap (owner decision, 2026-11-22) |
| P3 | rebalance-steady, dip-timing and trend-steady (each NO EDGE) | the lead and the owner | Why this study claims no edge |
| P4 | The 2017-2022 daily prices themselves, through those studies | everyone | Every choice below |

The train window is far from fresh. That is acceptable for a tool that claims no edge. Every threshold below is
fixed before any protect-gains run.

## 3. Data

- **Primary:** Kraken daily BTC and ETH, the train window (closes from 2017-01-02 up to and including 2023-01-01
  00:00 UTC), through `lab.data.panel.load_panel` (the test-window guard), snapshot `1746a21b75683e76`.
- **Second source (a robustness check):** Binance daily, from 2017-08-18, same window end.
- **Never read:** the validate window and the test window. This version has no validate look (section 12).

## 4. The wallet and the tool underneath

- **Mixes** (crypto share s, BTC's share of the crypto f): s ∈ {0.30, 0.50, 0.70} × f ∈ {0.50, 0.75}, so 6 mixes,
  with targets from `holdmix.mix_targets(s, f)`.
  - Each must pass `check_targets` with the Steady limits as read and h = 0.02 before any bar is read; otherwise the
    run refuses.
  - The highest coin target is s = 0.70, f = 0.75: BTC 52.5%, inside 60% − 2%.
- **The tool:** `holdmix.hold_mix` at the owner's default for a 5,000 USD wallet (2026-11-22): band 0.30, cap 2 (a
  15-day wait), no reset, and the Steady limits as read.
- **One deposit of 5,000 USD** at the window's first close, bought at the next open. No later deposits or
  withdrawals.
- **Costs:** `config/costs.yaml` at 1x (the decision) and 2x (a robustness check).

## 5. The brake (exact rules)

Notation:
- V_t is the wallet's value at daily close t.
- D is the deposit: the wallet's value at the first close after the first buy.
- H_t is the highest V since the first buy, or since the last buy-back's fill, up to and including close t.

**Line A (trailing), level X ∈ {0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40}:**
- line_A,t = (1 − X) · H_t.
- **Fires** at close t when V_t ≤ line_A,t. A value exactly on the line fires.

**Line B (profit kept), level Y ∈ {0.40, 0.50, 0.60, 0.70, 0.80}, activation gain g = 0.20:**
- Active from the first close where H_t ≥ (1 + g) · D. Until then, B never fires: with no gain yet there is no
  profit to keep, and a line at D would fire on the first small dip.
- line_B,t = D + Y · (H_t − D). **Fires** at close t when it is active and V_t ≤ line_B,t.
- D stays the original deposit, also after a buy-back.

**When it fires:**
- An order at close t sells all crypto to USDC, filled at the open of t+1 with costs. 100% USDC is allowed (owner,
  2026-11-21).
- **The brake wins:** while the wallet is stopped, the tool places no orders. That includes no band trade and no
  limit fix: an all-USDC wallet meets every Steady limit.
- **Overshoot** of a stop is how far below the line the sale happened: (line_t − V at the fill open) / H_t for A, and
  (line_t − V at the fill open) / (H_t − D) for B (a share of the profit). It is positive when the sale came in below
  the line.

**Buy-back modes:**
- **auto:** checked at each Monday 00:00 UTC close c, at least 7 days after the stop's fill. Buy back when the mix's
  crypto index I is above its 200-day simple average by more than 2%: I_c > 1.02 · SMA200(I)_c. The buy is an order
  at c back to the mix's targets, filled at the open of c+1.
  - I is f · BTC + (1 − f) · ETH, each price divided by its close on 2017-01-02.
  - SMA200 is the mean of I over the 200 closes ending at c. With fewer than 200 closes of history there is no
    signal.
  - The 200-day average is a standard convention, fixed here; it is not chosen from any result (P1's chosen
    lookbacks are not used).
- **wait-D:** a model of a customer who comes back D calendar days after the stop's fill, D ∈ {30, 180}. The order is
  at the first close at least D days after the fill, back to the mix's targets, filled at the next open. If no close
  that late is left in the window, the wallet stays in USDC to the end.
- **After a buy-back:** H restarts at V at the buy-back's fill close. The tool's band, cap and wait restart from the
  buy-back, which counts as the tool's last order.
- **Reading for owner question Q2:** the brake's sales and buy-backs are the brake's trades. They do not count
  against the tool's limit of 2 trades back to the mix in any 30 days.

**Checked at** every daily close only.

## 6. The grid

| | Values | Count |
|---|---|---|
| Levels | A: 7 levels; B: 5 levels | 12 |
| Brake off | the reference R | 1 |
| Buy-back modes | auto, wait-30, wait-180 | 3 (brake on only) |
| Mixes | section 4 | 6 |
| Windows | 2-year windows starting at each month's first close, January 2017 to January 2021 | 49 |
| Costs | 1x, 2x | 2 |
| Sources | Kraken, Binance (its own 2-year windows, from September 2017) | 2 |

- **The decision pool** is Kraken at 1x, every mix: 49 windows × 6 mixes = 294 runs per (level, mode).
- **The allowed range** customers can choose from is the whole grid: X from 10% to 40%, and Y from 40% to 80%.
  `risk-officer` confirms it in writing before any run.
- **Size:** about (12 × 3 + 1) × 6 × 49 × 2 × 2 + Binance's fewer windows ≈ 43,000 runs. That is a few CPU-minutes;
  the run refuses above 60 CPU-minutes (stop rule 7).

## 7. Measured per run

- **Fires:** the number of stops, and the days from the deposit to the first stop.
- **Worst fall:** the wallet's worst fall from its high as it happened (overshoot included), F, with the brake; F0
  for R in the same window.
- **Overshoot** of every stop (section 5), and its largest value.
- **Cost:** C = 1 − V_end / V_end(R), the share of the ending value given up against R. It is negative when the brake
  helped.
- **Time in USDC** because of the brake.
- **Fees and gas a year.**
- **Re-stops:** stops within 30 days after a buy-back's fill, as a share of buy-backs.
- **Missed rebound:** for each stop, the mix's return from the sale's fill to the buy-back's fill.

## 8. Decision rules (fixed now, before any result)

All use the decision pool only.

**D1. The default level, for each line type (A, B) and each buy-back mode m:**
1. Q(ℓ, m) = the 90th percentile of F over the pool's 294 runs (the bad-case fall); Q0 = the same for R.
2. **Meaningful protection:** Q(ℓ, m) ≤ (2/3) · Q0, i.e. it cuts the bad-case fall by at least a third.
3. C̃(ℓ, m) = the median of C over the pool.
4. **The default level** is the meaningful level with the smallest C̃. A tie within 1e-12 goes to the looser level
   (the larger X; the smaller Y). If no level is meaningful, the result is **NO DEFAULT** for that (type, mode).

**D2. The default buy-back, for each line type:** compare auto with wait-30, each at its D1 default.
- **auto** is the default if C̃_auto ≤ C̃_wait-30 **and** auto's pooled re-stop share is at most 25%.
- Otherwise **wait** is the default, at wait-30's D1 level.
- If auto has NO DEFAULT and wait-30 has one, the default is wait. If both have NO DEFAULT, there is no default
  buy-back, and the owner decides.
- wait-30 stands for an attentive customer; wait-180 shows a slow one and decides nothing.

**D3. If the app must show one line type first,** it shows the type with the smaller C̃ at its D1-D2 defaults (ties
go to A).

**D4. Robustness labels** (they decide nothing but are printed next to each default). A default is **ROBUST** only if
D1-D2 give the same default in each check below; otherwise it is **NOT ROBUST**, and the owner sees which check moved
it:
- **Boom years** (owner, 2026-11-21): without the windows that overlap BTC's best calendar year, and then without
  those overlapping its best two years. Years are by bar day, ranked on Kraken's closes, with ties going to the
  earlier year. Fewer than 12 windows left is MISSING.
- **Binance's windows.**
- **2x costs.**

**D5. The promise number for the app:** the largest overshoot, and its 95th percentile, over every stop in the pool
at the default levels. The app says: "On fast falls it can sell below your line. In tests it sold up to Z below."

## 9. Checks the run must pass (consistency stops)

- **Brake off** gives `hold_mix` bit for bit. A level that never fires in a window equals R bit for bit there.
- **Each stop is recomputed:** its line, value and fill come from the run's own `ret` and the rules of section 5, and
  must equal the run's.
- **Accounting** matches an independent book of coin units and cash (as `test_portfolio.unit_book`).
- **Counts:** every run in section 6 is logged, failures included, and the count must equal the grid's.

## 10. Code to build, and its tests (TESTING.md section 7)

`lab/runner/protect.py` is the overlay on top of `holdmix.hold_mix` through `portfolio._simulate`, plus the measures
of section 7 and the rules of section 8. `research/protect-gains/run.py` runs the grid, the decisions and the
outputs, with the start guards of the earlier studies: dirty tree, test-window guard, snapshot, RUNLOG before any
bar, and dry runs only in scratch folders.

Tests (synthetic and hand-built paths only, no catalog):
- **Tamper the future:** stop events, lines, buy-backs and every result row before a cut never change when later
  bars change (hypothesis, with cuts at stop and buy-back closes).
- **Hand-built paths:**
  - Line A: a fall of exactly X fires, and one ulp less does not; the high restarts after a buy-back; overshoot by
    hand on a gap down.
  - Line B: inactive until a gain of exactly 20%; the line by hand.
  - auto buys back at the first qualifying Monday, at least 7 days after the fill, and never before 200 closes of
    history; wait-D at the first close at least D days later.
  - The brake wins: no tool order while stopped; a stop and a band break on one close give one order; a stop at the
    last close is never filled.
- **Identities:** brake off is `hold_mix` bit for bit; a level that never fires equals R (hypothesis).
- **Accounting** against an independent book.
- **Dip buying** (owner, 2026-11-23: the two must not fight): a toy dip buyer is blocked while stopped and resumes
  after the buy-back.
- **The rules:** D1-D5 by hand on hand-made run tables, every threshold at its boundary (Q exactly (2/3) · Q0, a
  re-stop share of exactly 25%, C̃ ties), and NO DEFAULT and MISSING.
- **Recompute:** every reported number from its inputs.
- **Hand breaks** by the builder (a short list, not a separate code-breaker team), each failing a test.

## 11. Protocol, stop rules and amendments

**Order of work:**
1. The owner answers section 13, or its defaults hold. Either way it is logged.
2. One review of this draft (`backtest-auditor`, with `risk-officer`'s written confirmation of the allowed range).
   Every change is a dated amendment. Then the commit as the pre-registration.
3. Build the code and tests. The full tier with 100% branch coverage, the deep profile and ruff must pass.
4. Run 0 on the train window, then RESULTS.md and one audit.

**Stop rules:**
1. No number counts unless the three tiers pass on the commit the run uses, with a clean tree.
2. The bars hash, a panel hash or a row count differs from the snapshot: stop.
3. A bar after 2023-01-01 00:00 UTC: stop. Nothing from that run is used, and it is logged.
4. A failed run is logged with its error, and the grid goes on. A pool with a failed run makes the decisions it
   feeds MISSING.
5. A consistency stop (section 9) is a bug: stop and triage. The fix needs a regression test, a dated amendment and
   a full rerun; the old run's logs stay.
6. At most 2 amendment runs; a crashed run is rerun as an amendment run, never resumed.
7. The projection guard: above 60 CPU-minutes the run refuses to start, and the owner is asked.

**Amendments:** each dated line in this section, committed before the run it affects.

## 12. Cut from the first draft (small version)

These were in the first draft and are **not** in this study. Each can be added later as its own named amendment or
study:
- The single validate look (2023 to mid-2024).
- The hourly-check description, which would show how much checking more often cuts the overshoot.
- The 500 and 50,000 USD wallets, and the 1-year and 3-year windows.
- The wait-90 and wait-365 customers.
- Leave-one-year-out.
- The plain held mix without the tool.
- A separate code-breaker review.

## 13. Owner questions (defaults hold if unanswered)

- **Q1. Is the brake on by default for a new wallet?** Default: off; the customer switches it on, and the app
  suggests the study's settings.
- **Q2. Do the brake's sale and buy-back count against the hold-this-mix limit (2 trades back to the mix in any 30
  days)?** Default: no.
- **Q3. Line B's activation gain g = 20%:** keep, or another number?
- **Q4. The thresholds of section 8:** "cuts the bad-case fall by at least a third" and "re-stops at most 25%". Keep?

## 14. Outputs

- **RESULTS.md**, whatever the outcome: the plain-words summary, the defaults with their ROBUST label, the promise
  number Z, the full table per level and mode, and every deviation.
- **The committed record:** `runs.csv` (one row per run, with no return or Sharpe columns), `RUNLOG.jsonl` and
  `decision.json`.
- **Not committed:** `results/protect-gains/` (git-ignored), which holds the full tables.

## 15. Known weaknesses

- **Not fresh data,** and no validate look in this version: every number comes from years that have been looked at
  many times.
- **Overlapping windows:** the 49 two-year windows overlap heavily. They describe; they are not independent tests.
- **One wallet size** (5,000 USD): fees and slippage differ for small and large wallets.
- **The customer model:** wait-30 and wait-180 stand in for real customers, who act on fear or news, not a calendar.
- **The 200-day buy-back signal** is one fixed convention.
- **Daily checks** only: a live brake could act faster, so the overshoot here is an upper side of what customers
  would see.
- **Scouting engine and placeholder costs.**

## 16. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| P1-P4 | before this plan | section 2 | Prior looks, disclosed |
| Plan | 2026-11-23 | the lead | No market data. Read for this plan: `lab/runner/holdmix.py`'s function list and the `hold_mix` docstring; `config/risk_levels.yaml`'s hold-mix limit line; trend-steady's RESULTS.md and summary (P1); the earlier owner decisions; `docs/app/features.md`'s "Strategies and rules" and "Customer controls" tables |
| T1 | reserved | | Run 0 on the train window |

**Validate-window looks used for protect-gains: 0.**

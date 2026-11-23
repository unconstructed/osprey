# protect-gains: pre-registration (DRAFT)

**Status: DRAFT, written 2026-11-23 by the lead before any protect-gains code or result exists. Not yet reviewed by
`backtest-auditor` and `risk-officer`, and not frozen.** Any change after this file is committed is a dated, named
amendment in section 13. Repo HEAD at writing: `97793c4` (branch `claude/tender-brown-g86h44`). No protect-gains code
exists, no market bar was read for this plan, and no stop of this design has been run.

> **SCOUTING ONLY.** Every number this study produces will come from the lab's reference portfolio engine
> (`lab/runner/portfolio.py` through `lab/runner/holdmix.py` and a new overlay), not from NautilusTrader (AGENTS.md
> hard rule 3; the Nautilus work is on hold). It uses the **placeholder** costs of `config/costs.yaml`, and Kraken and
> Binance candles stand in for Base prices. It cannot make anything ready for paper.

## In plain words

Customers will be able to switch on a **"protect my gains"** brake. When their wallet falls too far, the app sells
the coins to USDC cash. Later it buys the mix back, either automatically when the market turns up again or when the
customer says so. The owner (2026-11-23, in chat) wants **both kinds of line** offered:

- **A. "Sell if it falls X% below its highest value."** Example: $1,000 grows to $2,000; at X = 20% it sells at
  $1,600.
- **B. "Keep at least Y% of my profit."** Example: $1,000 grows to $2,000; at Y = 60% it sells at $1,600 (60% of
  the $1,000 profit kept).

**Both buy-back choices** are offered too: automatic, or wait for the customer. **The simulation picks the starting
setting of each**, by rules written here before any result. The customer can change them within the range below.

This is a **safety brake, not a money-maker**. The study claims no edge, and the app will say so. Earlier lab tests
showed that stops rarely add return: they often sell near a bottom and buy back higher. So the study measures four
things: how much protection the brake gives, what it costs, how often it fires, and how far below the line it
really sells on fast falls. It then picks the cheapest setting that gives meaningful protection.

## 1. Question

For a customer using the **"hold this mix"** tool (the one tool Steady customers have today), with a protect-gains
brake on top:

- How often does each line fire?
- How much does it cut the bad-case fall?
- What does it cost in fees and missed rebounds, and how far past the line does it sell?
- Which setting of A, of B and of the buy-back is the best starting setting by the rules of section 9?

There is **no hypothesis test and no edge claim**, so there are no luck gates (E1, E2, DSR, PBO). Section 9's rules
choose defaults from descriptions, as in hold-mix-cap.

## 2. Prior looks (disclosure)

The people who wrote this plan have seen results that could inform it:

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| P1 | trend-steady's stop-loss variant (RESULTS.md, 2026-11-23): sell after a 20/30/40% fall from the wallet's top, buy back when the trend turns up. On top of the trend rule it fired 4, 2 and 0 times in 2018-2022. At 20% it trimmed the worst fall by about 4 points, and it did no better than placebo stops | the lead and the owner | The levels grid (section 5), and the expectation that loose levels rarely fire |
| P2 | hold-mix-cap's results (RESULTS.md, RISK.md and `decision.json`; the lead's K10): the falls of held BTC/ETH/USDC mixes by crypto share, mostly the 2018 crash; the 2017 and 2018 boom and crash years move results | the lead and the owner | The mixes (section 4), and the default band and cap of the tool (owner decision, 2026-11-22) |
| P3 | rebalance-steady and dip-timing (NO EDGE) and trend-steady (NO EDGE) | the lead and the owner | That timing rules found no edge, which is why this study claims none |
| P4 | The 2017-2022 daily prices themselves, through those studies | everyone | Every choice below |

So the train window (2017-2022) is far from fresh. That is acceptable for a tool that claims no edge. Still, every
threshold below is fixed before any protect-gains run, and section 12 adds the single validate look as an
out-of-sample check of the chosen defaults.

## 3. Data

- **Primary:** Kraken daily BTC and ETH, the train window (closes from 2017-01-02 up to and including 2023-01-01
  00:00 UTC), through `lab.data.panel.load_panel` (the test-window guard), snapshot `1746a21b75683e76`.
- **Second source (descriptions):** Binance daily, from 2017-08-18.
- **Hourly description:** Kraken hourly bars over the same window, for the default settings only (section 10).
- **Never read:** the test window (closes after 2024-07-01 00:00 UTC). The validate window is read only at the single
  look of section 12.

## 4. The wallet and the tool underneath

- **Mixes** (crypto share s, BTC's share of the crypto f): s ∈ {0.30, 0.50, 0.70} × f ∈ {0.50, 0.75}, so 6 mixes.
  The targets are `holdmix.mix_targets(s, f)`. Each must pass `check_targets` with the Steady limits as read and
  h = 0.02 before any bar is read; otherwise the run refuses (s = 0.70, f = 0.75 is BTC 52.5%, inside 60% − 2%).
- **The tool:** `holdmix.hold_mix` at the owner's default for the wallet size (2026-11-22): up to 5,000 USD, band
  0.30 with cap 2 (a 15-day wait); above 5,000 USD, band 0.50 with cap 1 (a 30-day wait). There is no reset. The
  Steady limits are as read.
- **Comparison wallets (descriptions):** the same mix with the tool and no brake (the reference R in section 7); the
  same mix bought once and held, with no tool and no brake.
- **One deposit** at the window's first close (bought at the next open), with no later deposits or withdrawals.
  Wallet sizes: 500, 5,000 (primary) and 50,000 USD.
- **Costs:** `config/costs.yaml` at 1x (primary) and 2x.

## 5. The brake (exact rules)

Notation:
- V_t is the wallet's value at daily close t.
- D is the deposit: the wallet's value at the first close after the first buy.
- H_t is the highest V since the first buy, or since the last buy-back's fill, up to and including close t.

**Line A (trailing), level X:**
- line_A,t = (1 − X) · H_t.
- **Fires** at close t when V_t ≤ line_A,t. A value exactly on the line fires.

**Line B (profit kept), level Y, activation gain g = 0.20:**
- Active from the first close where H_t ≥ (1 + g) · D. Until then, B never fires: with no gain yet there is no
  profit to keep, and a line at D would fire on the first small dip.
- line_B,t = D + Y · (H_t − D). **Fires** at close t when it is active and V_t ≤ line_B,t.
- D stays the original deposit, also after a buy-back.

**When it fires:**
- An order at close t sells all crypto to USDC, filled at the open of t+1 with costs. 100% USDC is allowed (owner,
  2026-11-21).
- **The brake wins:** while the wallet is stopped, the tool places no orders. That includes no band trade and no
  limit fix: a wallet that is all USDC meets every Steady limit.
- **Overshoot** of a stop is how far below the line the sale happened: (line_t − V at the fill open) / H_t for A, and
  (line_t − V at the fill open) / (H_t − D) for B (a share of the profit). It is positive when the sale came in below
  the line.

**Buy-back modes:**
- **auto:** checked at each Monday 00:00 UTC close c, at least 7 days after the stop's fill. Buy back when the mix's
  crypto index I is above its 200-day simple average by more than 2%: I_c > 1.02 · SMA200(I)_c. The buy is an order
  at c back to the mix's targets, filled at the open of c+1.
  - I is f · BTC + (1 − f) · ETH, each price divided by its close on 2017-01-02, so it is the same for every window.
  - SMA200 is the mean of I over the 200 closes ending at c. With fewer than 200 closes of history there is no
    signal, so a stop before mid-2017 waits.
  - The 200-day average is a standard convention, fixed here; it is not chosen from any result (the chosen
    lookbacks of P1 varied from 24 to 128 days and are not used).
- **wait-D:** a model of a customer who comes back D calendar days after the stop's fill, D ∈ {30, 90, 180, 365}.
  The order is at the first close at least D days after the fill, back to the mix's targets, filled at the next open.
  If no close that late is left in the window, the wallet stays in USDC to the end.
- **After a buy-back:** H restarts at V at the buy-back's fill close. The tool's band, cap and wait restart from the
  buy-back, which counts as the tool's last order.
- **Reading pinned for an owner question (Q2):** the brake's sales and buy-backs are the brake's trades. They do not
  count against the tool's limit of 2 trades back to the mix in any 30 days. A description run counts them as well.

**Checked at:** every daily close (primary), and every hourly close (a description, section 10).

## 6. The grid

| | Values | Count |
|---|---|---|
| A, X | 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40 | 7 |
| B, Y | 0.40, 0.50, 0.60, 0.70, 0.80 | 5 |
| Brake off | the reference R | 1 |
| Buy-back modes | auto, wait-30, wait-90, wait-180, wait-365 | 5 (brake on only) |
| Mixes | section 4 | 6 |
| Windows | 2-year windows starting at each month's first close, from January 2017 to January 2021 (49, primary); 1-year (61) and 3-year (37) windows the same way (descriptions); the full train span | 148 |
| Wallets | 500, 5,000, 50,000 USD | 3 |
| Costs | 1x, 2x | 2 |
| Sources | Kraken (primary), Binance (descriptions, its own windows from September 2017) | 2 |

**The decision pool** is Kraken, 2-year windows, 5,000 USD, 1x, every mix, every level and every mode: 49 windows ×
6 mixes = 294 runs per (level, mode). **The allowed range** that customers can choose from is the whole grid: X from
10% to 40%, and Y from 40% to 80%. `risk-officer` confirms it in writing before any run (section 13). Every value in
the range is reported with every number in section 7.

**Size.** At most about 12 × 5 × 6 × 148 × 3 × 2 × 2 + the references ≈ 640,000 runs. Amendment A1 (section 13)
times the built overlay. If the full grid will not fit 240 CPU-minutes, the descriptions are cut first, in this order:
Binance at 2x, the 1-year windows, 50,000 USD at 2x. The decision pool is never cut.

## 7. Measured per run

- **Fires:** the number of stops; the days from the deposit to the first stop.
- **Worst fall:** the wallet's worst fall from its high, as it happened (overshoot included): F, with the brake, and
  F0, for R in the same window.
- **Overshoot** of every stop (section 5), and its largest value.
- **Cost:** C = 1 − V_end / V_end(R), the share of the ending value given up against R. It is negative when the brake
  helped.
- **Time in USDC** because of the brake.
- **Fees and gas a year** (customer fees, as hold-mix-cap reports them).
- **Re-stops:** stops within 30 days after a buy-back's fill, as a share of buy-backs.
- **Missed rebound:** for each stop, the mix's return from the sale's fill to the buy-back's fill. It is positive
  when the mix rose while the wallet sat in cash.

## 8. Checks the run must pass (consistency stops)

- **Brake off** gives `hold_mix` bit for bit. A level that never fires in a window equals R bit for bit there.
- **The order hash** (closes, reasons, targets) is the same at 1x and 2x and at every wallet size for the tool's
  orders before the first stop. Stops read the wallet's value, so stops may differ between costs and wallet sizes;
  each run's stop events are recomputed from its own `ret` and must equal the run's.
- **Every stop's line, value and fill** are recomputed from the run's `ret` and the rules of section 5.
- **Accounting** matches an independent book of coin units and cash (as `test_portfolio.unit_book`).
- **Counts:** every run in section 6 is logged, failures included, and the count must equal the grid's.

## 9. Decision rules (fixed now, before any result)

All of these use the decision pool only (section 6).

**D1. The default level, for each line type (A, B) and each buy-back mode m:**
1. For each level ℓ, compute Q(ℓ, m) = the 90th percentile of F over the pool's 294 runs (the bad-case fall), and
   Q0 = the same for R.
2. **Meaningful protection:** Q(ℓ, m) ≤ (2/3) · Q0, i.e. the brake cuts the bad-case fall by at least a third.
3. **The cost:** C̃(ℓ, m) = the median of C over the pool.
4. **The default level** is the meaningful level with the smallest C̃. A tie within 1e-12 goes to the looser level
   (the larger X; the smaller Y). If no level is meaningful, the result is **NO DEFAULT** for that (type, mode).

**D2. The default buy-back, for each line type:** compare auto with wait-30, each at its D1 default.
- **auto** is the default if C̃_auto ≤ C̃_wait-30 **and** auto's re-stop share (section 7, pooled) is at most 25%.
- Otherwise **wait** is the default (with wait-30's D1 level).
- If auto has NO DEFAULT and wait-30 has a default, the default is wait. If both have NO DEFAULT, there is no
  default buy-back, and the owner decides.
- Why wait-30: it is the most attentive realistic customer. wait-90, wait-180 and wait-365 are reported to show what
  slower customers would face, and decide nothing.

**D3. If the app must show one line type first,** the type with the smaller C̃ at its D1-D2 defaults (ties go to A,
the simpler one). Whether the brake is on by default for a new wallet is the owner's call (Q1); the study only
reports.

**D4. Robustness labels** (they decide nothing but are printed next to each default). The default is **ROBUST** only
if D1-D2 give the same default in every check below; otherwise it is **NOT ROBUST**, and the owner sees which check
moved it:
- **Boom years** (owner, 2026-11-21): rerun D1-D2 without the windows that overlap BTC's best calendar year, and
  then without those overlapping its best two years. Years are by bar day and ranked on Kraken's closes; ties go to
  the earlier year. Fewer than 12 windows left is MISSING.
- **Leave one year out:** D1-D2 without the windows that overlap each train year in turn.
- The same rules on Binance's windows, at 500 and at 50,000 USD, at 2x costs, and on 3-year windows.

**D5. The promise number for the app:** for the default levels, the 95th percentile and the largest overshoot over
every stop in the pool. The app says: "On fast falls it can sell below your line. In tests it sold up to Z below."
Z is the largest overshoot, not the 95th percentile. The hourly description (section 10) shows how much checking more
often would cut Z.

## 10. Descriptions (reported, decide nothing)

- Every level and mode, with every number in section 7: the median, 90th percentile and worst over the pool.
- Per mix, and per crypto share, whether one default for every share hides a big difference.
- The plain held mix (no tool) with and without the brake.
- The tool's own limit counted with the brake's trades (Q2's other reading).
- **Hourly checks** at the default settings: the same rules checked at every hourly close (the sale filled at the
  next hour's open), on Kraken hourly bars, for the overshoot Z, the fires and C.
- **Every stop event** in the full-span runs at the defaults: its date, line, sale, overshoot, buy-back date and the
  missed rebound.

## 11. Interaction with dip buying (owner, 2026-11-23: "don't stop loss and buying the dip fight each other")

- **The rule:** while the brake has the wallet stopped, no strategy or tool may buy. That includes dip buying. Buying
  resumes only after the brake's buy-back.
- **A strategy's own stop** must sit further away than its entry trigger and be measured from its buy price. The lab's
  dip-buying engine (`reference.dip_buy`) already measures its stop that way.
- No dip-buying strategy is offered today, so this study tests the rule's **mechanics only**, on hand-built paths
  with a toy dip buyer (section 14). A study of the combination waits for the Balanced dip-buying strategy.

## 12. The single validate look (description)

After the train decision is committed and frozen (a FROZEN.json with the defaults and the code and config hashes),
one run reads the validate window (closes 2023-01-02 .. 2024-07-01) through `load_panel`. It runs every mix with the
defaults and R on 6-month windows starting each month (13 windows), at 5,000 USD and 1x, and reports section 7's
numbers. It **cannot change a default.** It only labels each default "behaves as in train" or "differs".
- "Differs": for each default, Q against (2/3) · Q0, and whether C̃ is more than twice its train value.
- The test window is never read.

## 13. Protocol, stop rules and amendments

**Order of work:**
1. The owner answers the questions in section 15, or the defaults written there hold. Either way it is logged.
2. `backtest-auditor` and `risk-officer` review this draft. Every change is a dated amendment, and `risk-officer`
   confirms the allowed range in writing.
3. The plan is committed as the pre-registration.
4. Build `lab/runner/protect.py` (the overlay) and the study script, with their tests (section 14). The full tier
   with 100% branch coverage, the deep profile and ruff must pass.
5. Amendment A1 times the overlay and sizes the grid (section 6).
6. Run 0 on the train window, then RESULTS.md, the audit and the risk review.
7. The freeze, then the validate look (section 12).

**Stop rules:**
1. No number counts unless the three tiers pass on the commit the run uses, with a clean tree.
2. The bars hash, a panel hash or a row count differs from the snapshot: stop.
3. A bar after the window the stage may read: stop. Nothing from that run is used, and it is logged.
4. A failed run is logged with its error, and the grid goes on. A pool with a failed run makes the decisions it
   feeds MISSING.
5. A consistency stop (section 8) is a bug: stop and triage. The fix needs a regression test, a dated amendment and
   a full rerun; the old run's logs stay.
6. A crashed run is never resumed; it is rerun as an amendment run, and its logs stay.
7. At most 2 amendment runs.
8. The validate look runs once; a crashed look counts.
9. The projection guard: above 240 CPU-minutes the run refuses to start, and the owner is asked.

**Amendments:** each dated line in this section, committed before the run it affects. The amendments are A1 (the
throughput timing) and any review changes.

## 14. Code to build, and its tests (TESTING.md section 7)

`lab/runner/protect.py`: the overlay on top of `holdmix.hold_mix` through `portfolio._simulate`, plus the measures of
section 7. `research/protect-gains/run.py` runs the grid, the decisions, the outputs and the guards (as hold-mix-cap's
`run.py`).

Tests (synthetic and hand-built paths only, no catalog):
- **Tamper the future:** stop events, lines, buy-backs and every result row before a cut never change when later
  bars change (hypothesis, with cuts at stop and buy-back closes).
- **Hand-built paths, line A:** a fall of exactly X fires, and one ulp less does not; the high restarts after a
  buy-back; overshoot by hand on a gap down.
- **Hand-built paths, line B:** inactive until a gain of exactly 20%; the line at D + Y · (H − D), by hand; once
  active, every close at or below the line places a stop.
- **auto:** buys back at the first qualifying Monday, at least 7 days after the fill, and never before 200 closes of
  history; wait-D at the first close at least D days later; no buy-back left in the window means USDC to the end.
- **The brake wins:** no band trade and no limit fix while stopped; a stop and a band break on one close give one
  order (the stop); a stop at the last close is never filled.
- **Identities:** brake off is `hold_mix` bit for bit; a level that never fires equals R (hypothesis).
- **Accounting** against an independent book of coin units and cash.
- **Dip buying:** a toy dip buyer is blocked while stopped and resumes after the buy-back.
- **The rules:** D1-D5 by hand on hand-made run tables, every threshold at its boundary (Q exactly (2/3) · Q0; a
  re-stop share of exactly 25%; C̃ ties), and NO DEFAULT and MISSING.
- **Recompute:** every reported number from its inputs; the boom-year windows by hand.
- **Code-breaker hand breaks** of the overlay and the rules, each failing a test.

## 15. Owner questions (defaults hold if unanswered)

- **Q1. Is the brake on by default for a new wallet?** Default: off; the customer switches it on, and the app
  suggests the study's defaults.
- **Q2. Do the brake's sale and buy-back count against the hold-this-mix limit (2 trades back to the mix in any 30
  days)?** Default: no; they are the brake's trades. The other reading is reported (section 10).
- **Q3. Line B's activation gain g = 20%:** keep, or another number? Below g, line B does nothing (line A can still
  protect).
- **Q4. The thresholds of section 9:** "cuts the bad-case fall by at least a third" and "re-stops at most 25%". Keep?

## 16. Outputs

- **RESULTS.md**, whatever the outcome: the plain-words summary, the defaults with their ROBUST label, the promise
  number Z, the full table per level and mode, the stop events, the validate look and every deviation.
- **The committed record:** `runs.csv` (one row per run, with no return or Sharpe columns, as in hold-mix-cap),
  `RUNLOG.jsonl` and `decision.json`.
- **Not committed:** `results/protect-gains/` (git-ignored), holding the full tables.

## 17. Known weaknesses

- **Not fresh data:** the train window has been looked at many times (section 2). The validate look is the only
  fresh check, and it covers 18 months of a mostly rising market, so the brake will rarely fire there.
- **Overlapping windows:** the 49 two-year windows overlap heavily. They describe; they are not independent tests.
- **The customer model:** "wait-D" is a stand-in for real customers, who will act on fear or news, not on a calendar.
- **The 200-day buy-back signal** is one fixed convention; another could be better or worse, and testing many would
  be a search.
- **Daily checks** understate how quickly a live brake could act, and so overstate overshoot. The hourly description
  shows how much.
- **Scouting engine and placeholder costs.**

## 18. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| P1-P4 | before this plan | section 2 | Prior looks, disclosed |
| Plan | 2026-11-23 | the lead | No market data. Read for this plan: `lab/runner/holdmix.py`'s function list and the `hold_mix` docstring; `config/risk_levels.yaml`'s hold-mix limit line; trend-steady's RESULTS.md and summary (P1); the earlier owner decisions |
| T1 | reserved | | Run 0 on the train window |
| V1 | reserved | | The single validate look |

**Validate-window looks used for protect-gains: 0.**

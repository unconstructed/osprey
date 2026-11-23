# protect-gains: pre-registration (small version)

**Status: PRE-REGISTRATION. Written 2026-11-23 by the lead before any protect-gains code or result existed, revised
the same day after one review, and committed as the pre-registration (order of work, step 2).**

**How this version came about:**
1. The first draft (`5a83caf`) was cut down to a small version (`0afc969`) at the owner's request ("option 2", in
   chat, because of a usage limit).
2. The small version was reviewed the same day by `backtest-auditor` (11 blocking items) and `risk-officer` (the
   allowed range), with no market data.
3. The owner answered three questions in chat (section 13). This version folds in all of that (amendments R1-R4,
   section 11).

No protect-gains code exists, no market bar was read for this plan, and no stop of this design has been run.

> **SCOUTING ONLY.** Every number this study produces will come from the lab's reference portfolio engine
> (`lab/runner/portfolio.py` and a new `lab/runner/protect.py`), not from NautilusTrader (AGENTS.md hard rule 3; the
> Nautilus work is on hold). It uses the **placeholder** costs of `config/costs.yaml`, and Kraken and Binance candles
> stand in for Base prices. It cannot make anything ready for paper.

## In plain words

Customers will be able to switch on a **"protect my gains"** brake. When their wallet falls too far, the app sells
the coins to USDC cash. Later it buys the mix back. The owner (2026-11-23) wants both kinds of line offered:

- **A. "Sell if it falls X% below its highest value."** Example: $1,000 grows to $2,000; at X = 20% it sells at
  $1,600.
- **B. "Keep at least Y% of my profit."** Example: $1,000 grows to $2,000; at Y = 60% it sells at $1,600. B only
  switches on once its sell line would sit at least 10% below the top, so it never sells on an ordinary day's move.

And three ways to buy back:
1. **"When prices return to where we sold"** (the owner's idea): tested 5% below, at, and 5% above the sale price.
2. **"When the market's trend turns up"** (a 200-day average rule).
3. **"Wait for me"**, simulated as a customer who comes back after 1 month or after 6 months.

**The simulation picks the starting setting of each** by rules written here before any result. The customer can
change them within the range below. This is a **safety brake, not a money-maker**: trend-steady already found that a
stop does not earn more than stops at random weeks (section 2), so this study claims no edge. It measures four
things: how much the brake cuts the bad-case fall, what it costs, how often it fires, and how far below the line it
really sells. It then picks the cheapest setting that gives meaningful protection for every mix.

## 1. Question

For a customer using the **"hold this mix"** tool with a protect-gains brake on top:

- How often does each line fire?
- How much does it cut the bad-case fall?
- What does it cost?
- How far past the line does it sell?
- Which line level and buy-back is the best starting setting by section 8's rules?
- Should the brake's buy-backs count against the tool's limit of 2 trades back to the mix in any 30 days?

There is **no hypothesis test and no edge claim**, so there are no luck gates (E1, E2, DSR, PBO).

## 2. Prior looks (disclosure)

| # | What was seen | By | What it could inform here |
|---|---|---|---|
| P1 | trend-steady's stop-loss variant (RESULTS.md, 2026-11-23): sell after a 20/30/40% fall from the wallet's top, buy back when the trend turns up. On top of the trend rule it fired 4, 2 and 0 times in 2018-2022. At 20% it trimmed the worst fall by about 4 points, and it did no better than placebo stops | the lead and the owner | The levels grid, and the expectation that loose levels rarely fire |
| P2 | hold-mix-cap's results (the lead's K10): the falls of held BTC/ETH/USDC mixes by crypto share, mostly the 2018 crash | the lead and the owner | The mixes, and the tool's default band and cap (owner decision, 2026-11-22) |
| P3 | rebalance-steady, dip-timing and trend-steady (each NO EDGE) | the lead and the owner | Why this study claims no edge |
| P4 | The 2017-2022 daily prices themselves, through those studies | everyone | Every choice below |

The train window is far from fresh. That is acceptable for a tool that claims no edge. Every threshold below is
fixed before any protect-gains run.

## 3. Data

| Item | Pinned |
|---|---|
| Primary | Kraken daily `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN` through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=2023-01-01 00:00 UTC)`: 2190 rows, closes 2017-01-02 .. 2023-01-01; close 2018-01-13 is missing (no ETH bar) and never filled |
| Robustness | Binance daily `BTCUSDT`, `ETHUSDT`, the same `last_close`: 1963 rows from 2017-08-18 |
| Snapshot | `1746a21b75683e76`. Stop unless the bars hash is `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e` and the panel hashes (`steady.panel_hash`) are Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587` |
| Never read | The validate window and the test window. Every frame is checked: `panel.index.max() <= last_close` |
| Costs | `Costs.from_yaml(capital_usd=5000)` (1x) and its `.stressed(2.0)` (2x) |

## 4. The wallet and the tool underneath

- **Mixes** (crypto share s, BTC's share of the crypto f): s ∈ {0.30, 0.50, 0.70} × f ∈ {0.50, 0.75}, so 6 mixes,
  with targets `holdmix.mix_targets(s, f)`. All 6 pass `portfolio.check_targets` with the Steady limits as read
  and h = 0.02 (review, 2026-11-23; the tightest coin is s 0.70, f 0.75: BTC 0.525). The run checks again before
  any bar is read and refuses otherwise.
- **The tool:** the "hold this mix" rule (`holdmix.hold_mix`) at the owner's default for a 5,000 USD wallet
  (2026-11-22): band 0.30, cap 2 (a 15-day wait), no reset, and the Steady limits as read.
- **The deposit:** D = 5,000 USD in cash at the window's first close (row 0). The first buy is ordered at row 0 and
  filled at row 1's open. There are no later deposits or withdrawals.

## 5. The brake (exact rules)

**Notation.**
- Rows are the window's panel rows; row 0 is its first close.
- V_t is the wallet's value at close t.
- **The fill instant** of an order decided at close t is close t's timestamp (the open of row t+1). Every interval
  below is in calendar days from a fill instant.
- **H_t** is the highest V over rows 1..t. After a buy-back ordered at close c, it is the highest V over rows c+1..t.

**Line A (trailing), X ∈ {0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40}.** It fires at close t when
`V_t <= (1 - X) * H_t`. A value exactly on the line fires.

**Line B (profit kept), Y ∈ {0.40, 0.50, 0.60, 0.70, 0.80}.**
- **[R3] Its activation gain depends on Y**, so the line starts at least 10% below the high:
  g = 0.10 / (0.90 − Y), pinned as the values g = 0.20, 0.25, 1/3, 0.50 and 1.00 for Y = 0.40 .. 0.80.
- B is **active at close t only when** `H_t >= (1 + g) * D`, with H_t as defined. A buy-back therefore disarms B
  until the restarted high reaches (1 + g) · D again. D never changes.
- It fires at close t when it is active and `V_t <= D + Y * (H_t - D)`.

**When it fires:**
- An order at close t sells all crypto to USDC at row t+1's open, with costs. 100% USDC is allowed (owner,
  2026-11-21).
- **The brake wins:** while the wallet is stopped, the tool places no order (no band trade, no limit fix). An
  all-USDC wallet meets every Steady limit.
- A line crossed at the last close is listed as "not filled", and is left out of fires, overshoot and re-stops.

**Buy-back modes** (each order back to the mix's targets, decided at a close c and filled at row c+1's open):
- **rebound-r, r ∈ {−0.05, 0, +0.05} [R1, the owner's idea]:** at the first daily close c at least 7 days after the
  sale's fill instant with `I_c >= (1 + r) * I_t`. I_t is I at the sale's order close t.
- **trend:** at the first Monday 00:00 UTC close c at least 7 days after the sale's fill instant with
  `I_c > 1.02 * SMA200(I)_c`. **[R2]** Such a Monday qualifies only after I has closed at or below 1.02 · SMA200(I)
  at some close after the sale's fill instant, so the market must first have dipped below its trend and then come
  back. With no SMA yet (fewer than 200 panel rows before c) there is no signal.
- **wait-D, D ∈ {30, 180}:** at the first close at least D days after the sale's fill instant. This models a customer
  who comes back after a month or after six months.
- With no buy-back by the last close, the wallet stays in USDC to the end, flagged "not bought back".

**The index I.** For each source, I is computed once over the full train panel and passed into each window's run:
- I is chain-linked: I = 1 at the panel's first row, then I_c = I_{c−1} · (1 + f · r_BTC,c + (1 − f) · r_ETH,c),
  with close-to-close returns.
- SMA200(I)_c is the mean of the 200 panel rows ending at c, using `trend.sma`.
- The first signal is at row 199: Kraken 2017-07-20, Binance 2018-03-05.
- The rule is unchanged by rescaling I, so the start date does not matter.

**After a buy-back:**
- H restarts (above).
- B re-arms only as above.
- The tool's band, limit checks and wait restart from the buy-back's order close, as after a limit fix.

**[R4] The two readings of the tool's limit** (owner, 2026-11-23: "the sim may give us the best answer"; D6 decides):
- **"separate":** the buy-back is not one of the tool's 2 counted trades, and the tool's wait never holds it back.
- **"counts":** the buy-back is a counted trade. It waits until W = 15 days after the tool's last counted trade,
  and then counts.

The sale is never a trade back to the mix, so it is never counted in either reading.

**Checked at:** daily closes only.

## 6. The grid

| | Values | Count |
|---|---|---|
| Levels | A: 7; B: 5 | 12 |
| Buy-back modes | rebound −5%, rebound 0, rebound +5%, trend, wait-30, wait-180 | 6 |
| Limit readings | separate, counts | 2 |
| Brake off | the reference R | 1 |
| Mixes | section 4 | 6 |
| Windows | 2-year windows as in `holdmix.rolling_windows`, 24 months long: closes from the 2nd of month M_k to the 1st of M_(k+24). Kraken k = 0..48 (49 windows); Binance k = 8..48 (41) | |
| Costs | 1x, 2x | |

**Stage 1, the decision pool:** Kraken at 1x, every mix, both readings.
- Runs: (12 × 6 × 2 + 1) × 6 × 49 = **42,630**.
- Each (level, mode, reading) has 294 runs.

**Stage 2, the robustness pools:** run only for the reading D6 chooses.
- Pools: Binance 1x (41 windows) and Kraken 2x (49 windows).
- Runs: (12 × 6 + 1) × 6 × (41 + 49) = **39,420**.

**Total: 82,050 runs.** Amendment A1 times the overlay on the busiest setting (X = 0.10, rebound 0). The run
refuses above 240 CPU-minutes (stop rule 7).

**The allowed range** customers can choose from is the whole grid: X from 10% to 40%; Y from 40% to 80%, with its g;
the three buy-back kinds; and the rebound point from −5% to +5%. `risk-officer` confirmed it on 2026-11-23
(section 12).

## 7. Measured per run

- **F, the worst fall:** `F = -holdmix.money_metrics(result, costs)["max_drawdown"]`, a fraction ≥ 0, over the whole
  window. Its running peak starts at close 0 and is never reset at a buy-back. F0 is the same for R.
- **Fires:** the number of filled stops; the fire rate (the share of runs with at least one stop); and the days from
  close 0 to the first stop's order close.
- **Overshoot of each stop:**
  - In the app's unit: (line − V_sale) / line, where V_sale is V at the close of the sale's fill row. That is after
    the sale's costs; the wallet is all USDC from then on.
  - Per type: (line − V_sale) / H for A, and / (H − D) for B.
  - Also reported: the before-cost version.
- **B's sales below D:** their count and the worst one.
- **For B-active runs:** the share of the peak profit kept.
- **Cost:** C = 1 − V_end / V_end(R), with both runs in the same window. It is negative when the brake helped.
- **Time in USDC** because of the brake.
- **Fees and gas a year**, split into the tool's legs and the brake's legs.
- **Re-stops:** buy-backs whose next stop's order close is within 30 days of the buy-back's fill instant, divided by
  all buy-backs.
- **Missed rebound** of each stop: I's return from the open of the sale's fill row to the open of the buy-back's fill
  row. A wallet that is not bought back runs to the last close, flagged.
- **Distinct sale dates** behind each level's fires, so one crash shared by overlapping windows is visible.

## 8. Decision rules (fixed now, before any result)

Stage 1's pool (Kraken 1x) unless a rule names another. Every percentile is `numpy.percentile(..., 90)` (linear).
MISSING flows through: a rule that needs a MISSING number gives MISSING, never a pass.

**D1. The default level, for each line type (A, B), buy-back mode m and limit reading:**
1. For each level ℓ: Q = the 90th percentile of F over the pool (294 runs); Q0 = the same for R. If Q0 = 0, the
   result is NO DEFAULT.
2. **Meaningful protection** needs all three of:
   - `3 * Q <= 2 * Q0` over the pool;
   - the same for each of the 6 mixes over its own 49 runs, so the default protects every mix;
   - the pool's worst F at ℓ is no worse than R's worst F.
3. **Ranking:**
   - C̃ is the median of C over the pool, and C̄ is its mean.
   - The candidates are the meaningful levels whose C̃ is within 1e-12 of the smallest C̃.
   - Among them, the smaller C̄ wins, then the looser level (the larger X; the smaller Y).
   - No meaningful level gives NO DEFAULT.

**D2. The default buy-back, for each line type and reading:**
1. **Automatic candidates:** rebound −5%, rebound 0, rebound +5% and trend, each at its D1 default level.
   - A candidate is eligible if its re-stop share is at most 25%.
   - With no buy-backs at all, the share is MISSING, and the candidate is not eligible.
2. **The best automatic mode** is the eligible one with the smallest (C̃, then C̄). Ties go to the mode with fewer
   buy-backs in the pool, then in the order trend, rebound +5%, rebound 0, rebound −5%.
3. **Against wait:** the best automatic mode is the default if its (C̃, C̄) is no larger than wait-30's at
   wait-30's D1 default. Otherwise the default is wait, at wait-30's D1 level.
   - If no automatic mode is eligible or has a default, and wait-30 has one, the default is wait.
   - If wait-30 has NO DEFAULT and an automatic mode is eligible, the default is that mode.
   - With neither, there is no default buy-back, and the owner decides.
4. wait-30 stands for an attentive customer; wait-180 shows a slow one and decides nothing.

**D3. Which line the app shows first:** the type with the smaller (C̃, C̄) at its D1-D2 default (ties go to A). If
one type has NO DEFAULT, the other; if both, none.

**D6. [R4] The tool's limit reading:**
- **"counts" is the default reading:** it keeps the owner's existing limit as written.
- "separate" is **recommended** only if, for every line type with a default under both readings, it gives a strictly
  smaller (C̃, then C̄) at its own defaults.
- Even then, "separate" loosens an owner-approved limit (AGENTS.md, `risk-officer`). So the app keeps "counts" until
  the owner approves "separate" in writing.
- The defaults reported are those of the reading in force; both readings' tables are reported.

**D4. Robustness labels** (they decide nothing, but are printed next to each default):
- A default is **ROBUST** only if each check below gives the same default, i.e. the same (type, mode, level), or NO
  DEFAULT on both sides.
- A check that moves it gives **NOT ROBUST (check named)**; a MISSING check gives **MISSING (check named)**.
- **The checks** (stage 2, for the reading D6 chooses):
  - **Boom years** (owner, 2026-11-21), on the Kraken 1x pool without the windows that overlap BTC's best calendar
    year, then without those overlapping its two best years.
    - Years are by bar day, ranked on Kraken's closes; ties go to the earlier year.
    - Window k overlaps year Y when 12 (Y − 2017) − 23 ≤ k ≤ 12 (Y − 2017) + 11.
    - Fewer than 12 windows left gives MISSING. Removing two years leaves 1-2 windows for several pairs, so that
      check may well be MISSING; that is accepted, and it is reported.
  - **Binance** (its 1x pool).
  - **2x costs** (the Kraken 2x pool).

**D5. The promise number for the app**, for each line type at its D1-D2 default:
- the largest overshoot and its 95th percentile (the app's unit, section 7) over every stop in the pool;
- the worst F with the brake on, and B's worst sale below D;
- no stops gives MISSING.

The app says: "On fast falls it can sell below your line. In tests it sold up to Z below. Your highest value restarts
after each buy-back, so two stops in a row can add up."

## 9. Checks the run must pass (consistency stops)

- **The tool copy.** `protect.py` carries its own copy of hold_mix's decision steps, because `hold_mix` cannot be
  wrapped without editing it (review B6). It reuses `holdmix._hold_params` read-only, and `holdmix.py` is not edited.
  With the brake off, the copy must equal `hold_mix` bit for bit (`ret`, weights, orders, reasons, `in_wait`,
  `held`), checked on every run of R.
- **Stops and buy-backs are found by re-running,** as `trend.stop_events` does. They must equal a one-pass recompute
  from the run's own `ret` and the rules of section 5.
- **Accounting** matches an independent book of coin units and cash.
- **Counts** equal section 6's exactly (42,630 and 39,420), failures included.
- **A config hash** covers `protect.py`, `holdmix.py`, `portfolio.py`, `reference.py`, `config/*.yaml`, the study
  script and this plan. The run stops if any of them changes during the run.
- **Not checked:** the brake's decisions read V, so they depend on costs and wallet size. `path_hash`'s
  cost-invariance check is not applied to brake runs.

## 10. Code to build, and its tests (TESTING.md section 7)

- `lab/runner/protect.py`: the overlay (the tool copy plus the brake, the buy-back modes and both readings), the
  index I and its SMA, the measures of section 7, and the rules D1-D6.
  - The overlay wraps a generic decision step: the inner rule is not called while stopped, and is told of the
    buy-back. The dip-buying test can then plug in a toy dip buyer.
- `research/protect-gains/run.py`: the grid in its two stages, the decisions and the outputs. It has the start
  guards of the earlier studies: dirty tree, test-window guard, snapshot and panel hashes, the RUNLOG before any bar,
  dry runs only in scratch folders, and the projection guard.

Tests (synthetic and hand-built paths only, no catalog):
- **Tamper the future**, on the full panel: stops, lines, buy-backs, I, the SMA and every result row before a cut
  never change when later bars change (hypothesis, with cuts at stop, re-arm and buy-back closes).
- **Hand-built paths:**
  - Line A on its exact float expression: exactly on the line fires, and one ulp above does not. The high restarts
    after a buy-back. Overshoot by hand on a gap down.
  - Line B: the g table; inactive until `H >= (1 + g) * D` exactly; a buy-back below (1 + g) · D, after which there
    is no B stop until the new high reaches it; a sale below D, counted.
  - rebound-r at exactly `I_c == (1 + r) * I_t`, with the 7-day minimum counted from the fill instant.
  - trend: no buy-back until I has closed at or below 1.02 · SMA200, and none before row 199.
  - wait-D at exactly D days.
  - Both readings: under "counts", a buy-back inside the tool's wait waits, then counts; under "separate", it does
    not wait.
  - The brake wins: no tool order while stopped; a stop and a band break on one close give one order; a line crossed
    at the last close is "not filled".
- **Identities:** the tool copy equals `hold_mix` bit for bit (hypothesis: limit breaches inside the wait, the
  missing close); a level that never fires equals R.
- **I and SMA200** by hand, chain-linked, scale-free.
- **Accounting** against an independent book.
- **Dip buying:** a toy dip buyer is blocked while stopped and resumes after the buy-back (owner, 2026-11-23).
- **The rules:** D1-D6 by hand on hand-made run tables, every boundary exact (`3 * Q == 2 * Q0`, per-mix and pooled;
  the worst-F guard; a re-stop share of exactly 25%; C̃ ties broken by C̄; Q0 = 0; MISSING propagation; D2's case
  table; D6 both ways). The 24-month boom-year windows by hand against the calendar.
- **Recompute:** every reported number from its inputs; the run counts by hand.
- **Hand breaks** by the builder (a short list), each failing a test.

## 11. Protocol, stop rules and amendments

**Order of work:**
1. The owner's answers are recorded (section 13), and `risk-officer`'s confirmation of the allowed range (section 12).
2. Commit this plan as the pre-registration.
3. Build the code and tests. The full tier with 100% branch coverage, the deep profile and ruff must pass.
4. Amendment A1 times the overlay; the projection guard applies.
5. Run 0 (stages 1 and 2) on the train window, then RESULTS.md and one audit.

**Stop rules:**
1. No number counts unless the three tiers pass on the commit the run uses, with a clean tree.
2. The bars hash, a panel hash or a row count differs from section 3: stop.
3. A bar after 2023-01-01 00:00 UTC: stop. Nothing from that run is used, and it is logged.
4. A failed run is logged with its error, and the grid goes on. A pool with a failed run makes the decisions it
   feeds MISSING.
5. A consistency stop (section 9) is a bug: stop and triage. The fix needs a regression test, a dated amendment and
   a full rerun; the old run's logs stay.
6. At most 2 amendment runs. A crashed run is rerun as an amendment run, never resumed.
7. **The projection guard:** above 240 CPU-minutes the run refuses to start, and the owner is asked.

**Amendments** (dated, each committed before the run it affects):
- **R1-R4 (2026-11-23, after the review and the owner's answers, before any code or result):**
  - **R1:** the rebound buy-back (owner).
  - **R2:** the trend buy-back needs a dip below its trend first (review B4, option a).
  - **R3:** line B's activation gain depends on Y (risk-officer; owner: "start later").
  - **R4:** both readings of the tool's limit, and D6 (owner: "the sim may give us the best answer").
  - **The review's other blocking items:**
    - the sign and peak of F (B1);
    - B after a buy-back (B2);
    - the chain-linked index (B3);
    - the fill instant and intervals (B5);
    - the tool copy (B6);
    - the C̃ ties and C̄ (B7);
    - every mix protected (B8);
    - the gaps in D2-D5 (B9);
    - exact measures (B10);
    - the windows, counts and data pins (B11).
  - **Suggestions taken:**
    - D as the 5,000 USD deposit;
    - pinned float expressions;
    - the worst-F guard;
    - distinct sale dates;
    - the share of peak profit kept;
    - the dip-buyer hook;
    - the config hash;
    - no cost-invariance check on brake runs.
- **A1 (2026-11-23, before run 0): the throughput timing.** `run.py --time` on synthetic bars (no market data),
  20 repetitions of a 731-row window on the 70% crypto mix (f = 0.75): a reference run 17.8 ms; the busiest setting
  (A at X = 0.10, rebound 0, "counts") 70.1 ms, with 12 stops and 13 passes at 5.4 ms a pass. Charging every one of
  the 81,216 brake runs at the busiest run's time and the 834 reference runs at theirs gives **95.1 CPU-minutes**
  (about 48 minutes on 2 workers), under the 240 limit. The builder's earlier timing gave 68.0 on a quieter machine.
  `run.py` times again at start and refuses above 240 (stop rule 7).
- **A2 (2026-11-23, after the build, before any result): readings the build pinned** where the plan is loosely
  worded. Each is in `protect.READINGS_PINNED` and `run.py`'s `INTERPRETATIONS`, recorded in the start record.
  - **Stage 2's reading** (section 6, "the reading D6 chooses") is the reading D6 puts **in force**: "counts" unless
    the owner has approved "separate" in writing (section 13). If D6 recommends "separate", stage 2 still runs
    "counts", and a "separate" stage 2 is an amendment run after the owner's approval.
  - **After a buy-back the tool's wait restarts under both readings** (section 5, "as after a limit fix"). The
    readings differ only in whether the wait can hold the buy-back back and whether it is counted.
  - **A "counts" buy-back held by the wait** is ordered at the first close after the wait runs out, without checking
    its signal again.
  - **R2's dip** is a close strictly after the sale's order close and before the signal close; it may fall inside
    the 7-day minimum. A close with no SMA200 is neither a dip nor a signal.
  - **Missed rebound** reads I at the sale's and the buy-back's fill opens (I chain-linked from the previous close to
    the open); the before-cost overshoot uses V at the open, V_t · (1 + Σ w · g).
  - **A re-stop** is the next filled stop at most 30 days after the buy-back's fill instant (30 days included). A
    buy-back near the window's end still counts in the share's denominator. **Days in USDC** run from the sale's
    fill instant to the buy-back's, or to the last close.
  - **The share of peak profit kept** (section 7) is (V_end − D) / (P − D) per run where B was active at some
    close, P the run's highest V; each B stop also records its own kept share.
  - **The rules:** D2, D3 and D6 break ties on C̃ within D1's 1e-12 before comparing C̄. D2 is MISSING when any
    automatic mode's or wait-30's D1 is MISSING; D3 is MISSING when either line's D2 is. D6 needs at least one line
    type with defaults under both readings, and otherwise recommends "counts". D4's labels: NOT ROBUST before
    MISSING before ROBUST. D5: B's worst sale below D is "none" when there are stops and none sold below D.
  - **A line crossed at the last close** is not re-run, so a run's passes are its filled stops + 1.
  - **Start guards added:** the config hash also covers `trend.py`, `lab/validation/*.py` (F is
    `montecarlo.max_drawdown`), the data loaders, `pyproject.toml` and `uv.lock`. Section 3's snapshot id is
    recorded, not enforced; the bars and panel hashes decide. The tool's limit as read from
    `config/risk_levels.yaml` must be 2, or the run refuses to start.
  - **`runs.csv`** is one row per run, as section 14 says: about 82,050 rows (16-17 MB) with F, C and the brake
    measures, and no total return, end value, Sharpe or profit-share column.

## 12. Allowed range and production notes (`risk-officer`, 2026-11-23)

**Confirmed** (config only):
- The 6 mixes pass `mix_targets`, `check_targets` with h = 0.02, and `hold_mix`'s own check at band 0.30 with a
  15-day wait.
- An all-USDC wallet meets every Steady limit (the file sets no cash ceiling; owner, 2026-11-21).
- Line A, X from 0.10 to 0.40, and the buy-back kinds.

**Line B** is confirmed with R3's activation gains. The drafted g = 0.20 for every Y would have placed the line only
3.3-10% below the high when it switches on (a crypto move of 4.8-14.3% at s = 0.70), tighter than line A's tightest
setting.

**For the app's wording and controls:**
- For each X, show the crypto fall it means for the customer's mix (about X / s) and the study's fire rate. X = 0.10
  at s = 0.70 is a 14% crypto pullback, which is ordinary; X = 0.30-0.40 at s = 0.30 needs a crypto fall of about
  75% or more, so it rarely fires.
- The high restarts after each buy-back, so two stops in a row can lose 1 − (1 − X)² from the first high (36% at
  X = 0.20).
- X = 0.35 and 0.40 sit at or beyond Steady's 35% budget. They are allowed, but the app must not present them as
  keeping a Steady wallet inside its budget.
- Line B can sell below the deposit on a crash day, because the check is daily. The app must not promise "never
  below your deposit".
- **Production must ship what was tested:**
  - the check at the daily close (00:00 UTC);
  - H and D adjusted for deposits and withdrawals, with D as the customer's net deposits;
  - the buy-back signals exactly as in section 5;
  - the brake wins over the tool and any dip buyer;
  - a stop sells all crypto to USDC;
  - a buy-back goes to targets that pass `check_targets` with h = 0.02;
  - the customer's own buy-back is held to at least 7 days, as the automatic ones are, or labelled untested.

## 13. Owner answers (2026-11-23, in chat)

- **Buy-back "back to where we sold":** "Yes, add it (Recommended)" (R1).
- **Do the brake's trades count against the tool's limit?** "idk the sim may give us the best answer" (R4, D6).
  "counts" applies until the owner approves otherwise in writing.
- **Line B:** "Start later (Recommended)" (R3).
- **Q1** (is the brake on by default for a new wallet?): not answered, so the default holds: off; the customer
  switches it on, and the app suggests the study's settings.
- **Q4** (the thresholds of section 8): not answered, so they hold as written.

## 14. Outputs

- **RESULTS.md**, whatever the outcome:
  - the plain-words summary;
  - the defaults with their ROBUST label and the reading in force;
  - the promise number Z;
  - the full table per level, mode and reading, with the fire rate and the per-mix numbers;
  - the stop events at the defaults;
  - every deviation.
- **The committed record:** `runs.csv` (one row per run, with no return or Sharpe columns), `RUNLOG.jsonl` and
  `decision.json`.
- **Not committed:** `results/protect-gains/` (git-ignored), which holds the full tables.

## 15. Known weaknesses

- **Not fresh data,** and no validate look in this version.
- **Overlapping windows:** the 49 two-year windows overlap heavily, so one crash can stand behind many windows. The
  distinct sale dates are shown.
- **One wallet size** (5,000 USD), and only the tool's default band and cap.
- **The customer model:** wait-30 and wait-180 stand in for real customers.
- **One fixed convention** for each automatic buy-back (the 200-day trend; the ±5% rebound points).
- **Daily checks** only.
- **Scouting engine and placeholder costs.**

**Cut from the first draft** (each can come back as an amendment or its own study): the validate look, hourly
checks, the 500 and 50,000 USD wallets, the 1-year and 3-year windows, wait-90 and wait-365, leave-one-year-out, the
plain held mix without the tool, and a separate code-breaker review.

## 16. Looks at the data

| # | Date | By | What |
|---|---|---|---|
| P1-P4 | before this plan | section 2 | Prior looks, disclosed |
| Plan | 2026-11-23 | the lead | No market data. Read: `holdmix.py`'s function list and the `hold_mix` docstring; `config/risk_levels.yaml`'s hold-mix limit line; trend-steady's RESULTS.md, summary and section 3 (P1, and the data pins); the earlier owner decisions; `docs/app/features.md`'s "Strategies and rules" and "Customer controls" tables |
| Review | 2026-11-23 | `backtest-auditor` | No market data. Read: this plan and its README; `holdmix.py` lines 1-745 and 1600-1697; parts of `portfolio.py` and `trend.py`; `reference.py`'s `Costs` fields; `config/risk_levels.yaml` and `costs.yaml`; hold-mix-cap's PLAN.md (headings, sections 3, 4.3-4.6 and 11; not its results); `docs/app/features.md`'s headings and the two catalog rows; and the instruction files. It read none of hold-mix-cap's result files. Its two scratch checks used the config and the calendar only |
| Risk | 2026-11-23 | `risk-officer` | No market data. Read: this plan; `config/risk_levels.yaml`; parts of `holdmix.py` and `portfolio.py`; and the instruction files |
| Build | 2026-11-23 | `quant-researcher` | No market data. Built `lab/runner/protect.py`, `run.py` and their tests on synthetic and hand-built bars only. It read none of hold-mix-cap's result files or the "Hold this mix" section of `docs/app/features.md` |
| A1 | 2026-11-23 | the lead | No market data: `run.py --time` on synthetic bars (seed 21) |
| T1 | 2026-11-23 | the lead | Run 0 on the train window (Kraken and Binance, 2017-2022), commit `5e99d68`: NO DEFAULT for both lines (`RESULTS.md`). No validate or test bar |

**Validate-window looks used for protect-gains: 0.**

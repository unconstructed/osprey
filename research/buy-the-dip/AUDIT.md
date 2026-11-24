# buy-the-dip: audit of run 0 (SCOUTING)

`backtest-auditor`, 2026-11-24. This is the study's one audit (PLAN.md sections 12 and 16). It checks run 0 (the train
years 2017-2022 only) and the lead's draft RESULTS.md against the plan as amended (R1, R2, A1) and against the outputs.
I changed no code, no test, no PLAN.md, nothing in `config/` and nothing under `results/`. I read RESULTS.md only
after my own recompute was done. My scratch scripts are in the session scratchpad under `dipaudit/`.

> Every number here is SCOUTING. It comes from the lab's reference portfolio engine, uses the placeholder costs in
> `config/costs.yaml`, and treats Kraken and Binance candles as stand-ins for Base prices. Nothing here is a
> NautilusTrader result, and nothing here makes anything ready for paper.

## Result

**PASS for the run and its decision.** Run 0 followed the protocol. I wrote the ladder, its twins and the wallet book
myself, from PLAN.md, and reran **all 90,628 runs** from scratch. Every run matches `runs.parquet` to round-off
(about 1e-14). My own statement of the decision rules gives the same answer on my runs and on the run's:

- **default (Y, Z, X, M) = (30%, 10%, 25%, 100%)**;
- **label "NOT ROBUST (boom: without the best 1, Binance, boom: without the best 2: MISSING)"**.

**Nothing I found can change the default or its label** under the plan's rules. Two things the owner should know:

- **The default is a knife-edge pick.** It passes the bad-case test by 0.08 of a point, at one start wallet, in a
  comparison of two single windows. None of its one-step neighbours in the grid passes. Had that 0.08 gone the other
  way, the rules would have named (10%, 20%, 25%, 100%).
- **The label is solid.** Two checks move the default to NO DEFAULT, each by 1 to 5 points at several starts.

**The write-up is not final yet.** RESULTS.md's tables are right cell for cell: I checked both 54-row tables, the D2
table and the 80 by-year cells. But several claims are wrong or misleading. The main one: "spreading the same money
monthly" is not what the yardstick did. Every monthly twin at the default was cut by the Steady limits, reaching its
cap after about four months in the median window. None of the corrections changes a number the rules decide.

**The tool:** no validate look is planned, and the test window was never read. The bad-case fall at the default is
65-72% of the wallet, about twice the Steady budget of 35%. The plan shows the budget; it does not enforce it.

## What I checked

### 1. Protocol

| Check | Finding | Evidence |
|---|---|---|
| One run 0 only | PASS | `RUNLOG.jsonl` has two lines: the start (run 0, real data, commit `e62233e`, `dirty: false`, config hash `086fffac…`, snapshot `1746a21b75683e76`, 18:08:49 UTC) and "complete" (18:21:53 UTC). `results/buy-the-dip/` holds `run0/` only. There was no amendment run |
| Clean tree, right commit, code unchanged since | PASS | `start.json` has `git.dirty: false`, `changes: []`, commit `e62233e`. All 24 file hashes in `start.json` equal today's files. `run.py`'s own `config_hash` over today's files gives `086fffac…` again. The commits since (`8a2876c`, `7257575`, `1c0bb79`) touch only the run records (RUNLOG, `runs.csv`, `decision.json`, downvol-steady's CSVs), TESTING.md and the two studies' draft write-ups (this study's RESULTS.md, downvol-steady's RESULTS.md and AUDIT.md). None of those is hashed |
| The parallel run | PASS | downvol-steady run 0 started on the same commit (its RUNLOG line at 18:08:56 UTC, `dirty: false`). It shares no hashed file with this study. `run.py` hashes its 24 files again at the end, and a change would have stopped the run; it completed. The two runs shared the CPU, nothing else |
| A1 before the run | PASS | PLAN.md's A1 row was committed in `b73a770` (09:06 UTC), before `e62233e` and nine hours before the run. The run's own re-timing at its start gave 27.7 CPU-minutes, under the 240 limit, on synthetic bars only (`start.json` `timing`) |
| Tiers on the run's commit | PASS on the record | TESTING.md section 3 records the full tier on `e62233e` (2646 passed, 100% branch coverage of `lab/`) and the deep profile (2628). I did not rerun the full tier. I reran `tests/test_dipbuy.py` and `tests/test_dipbuy_run.py` (`-m "not slow"`, `-n 3`) on today's tree, which now holds the real RUNLOG lines: 126 passed in 33 s, and the tree was unchanged after. So the class of test that depends on what the repo has recorded (#48, #59, #68) did not recur |
| The Steady limits as read | PASS | `start.json` records min cash 0.20, max coin 0.60 and budget 0.35 from `config/risk_levels.yaml` (SHA-256 `d3f58253…`, today's file). `run.py` refuses to start with other limits |
| No bar after 2023-01-01 00:00 UTC | PASS | **Code path:** `study()` → `load_study_panel` → `load_panel(source, "1d", last_close=2023-01-01)` through `guarded()`. That calls the catalog with `end = 2023-01-01`, and the catalog query is bounded by that end. `guarded()` refuses any returned close after the cut, and `check_panel` re-asserts the last close. The A1 timing uses synthetic bars only. **My own load** went through a loader that refuses a request with no end or a later end before the catalog is asked, and refuses any returned close after the cut. It received four requests (BTC and ETH, Kraken and Binance), each from 2017-01-01 to 2023-01-01, and nothing later came back. Both panels end at 2023-01-01 |
| Snapshot and panel hashes | PASS | `SNAPSHOT.json`: id `1746a21b75683e76`, bars hash `08f5ca2c…`. My load reproduces both pinned panel hashes: Kraken `355aabe2…` (2190 rows from 2017-01-02, only 2018-01-13 missing) and Binance `2c1a4257…` (1963 rows from 2017-08-18). Every run row carries that snapshot and commit `e62233e` |
| Counts | PASS | 31,948 (stage 1) + 58,680 (stage 2) = 90,628: 30,024 dip runs, 30,024 of each twin, 556 hold runs, and no run id twice. The 139 block files hold the same 90,628 rows with equal numbers. 118,764 ladders were logged |
| No failed run | PASS | `status` is ok on all 90,628 rows, and `failures.parquet` is empty |
| Outputs | PASS | `run0/decision.json` is byte-identical to the tracked copy. `runs.csv` has 90,628 rows, no Sharpe, end-value or total-return column, and its values equal `runs.parquet` to its 6 significant digits |
| No validate look, test window unread | PASS | None is planned (section 12). There is no validate folder, and the README says 0 looks |

### 2. The decisive numbers, recomputed with my own code

**What I wrote myself, from PLAN.md sections 4-8.** It shares no code with `dipbuy.py`, `portfolio.py`, `holdmix.py`
or `run.py`:
- **The windows:** the 24-month windows from the calendar, each slice checked against the daily grid.
- **The one-year high H:** the highest index value over the closes less than 365 days back, close t included.
- **The ladder:**
  - the trigger, the lines, the pieces and K;
  - the line crossings (a line exactly at I is crossed);
  - the re-arm at a new one-year high;
  - the caps (R1) and the limit fix's λ;
  - one order per close, and nothing filled from the last close.
- **The wallet book:** coin units and USDC cash. Each order fills at the next open at its target weights. Costs are
  paid per leg, from `config/costs.yaml`'s numbers in my own slippage function, plus gas per leg.
- **The twins:** dca-same (12 pieces by calendar days), lump-same and hold, with the same caps and limit fixes.
- **Every measure:** F, the end value, δ, the buying counts, the knife, T_dca, T_lump, T_hold and G.

**From the lab I used only:**
- `load_panel`, behind my own guard;
- `steady.panel_hash`;
- `protect.index_signal` for the index I, which the plan allows. My own chain-linked index equals it bit for bit
  on both sources and both splits. My H equals `dipbuy.recent_high` bit for bit.

| What | Mine against the run's | Match |
|---|---|---|
| All 90,628 runs, every kind, all three pools | Every run found on its keys. F to 3.4e-15. End value to 1.0e-14 (relative). The amounts ordered, sent, cut and blocked to ≤ 1e-11. δ to 6.2e-14. T_dca, T_lump, T_hold and G to ≤ 1.3e-13. These are identical in every run: ladders, ladders filled, buy orders, pieces, lines not filled, limit fixes, the worst knife and the days to the first order | yes |
| All 118,764 ladders | Start, number of lines, lines crossed, orders sent and re-arm close identical. H* identical, B to 1.3e-14, knife identical | yes |
| The 1x/2x cost check (section 10, read as R2.2) | 10,584 Kraken dip pairs. My triggers, crossings and re-arms are equal in every pair. My sent orders differ in 63 pairs (25 settings, 30 windows, all four starts; none at the default): 3 in the number of buy orders, 13 in the number of limit fixes, 47 in a close or a reason only | yes |
| D1 on Kraken 1x (49 windows) | Default (30%, 10%, 25%, 100%), the only setting within 1e-12 of the best G̃. 10 of 54 settings usable. Every setting was active in all 49 windows at every start, so the activity rule never bound. Every G̃ and median δ to 1.3e-14; Q, Q_dca and the worst falls to 1.8e-15 | yes |
| D2 | BTC's yearly returns on Kraken, by bar day, equal `start.json`'s: 2017 +1,304%, 2020 +304%. Without 2017: 37 windows (k = 12..48), NO DEFAULT. Without 2017 and 2020: windows 12 and 48 only, MISSING. Binance (41 windows): NO DEFAULT. Kraken 2x: the same default. The label is the same, word for word | yes |
| D3 at the default | Every number per start and by year (G, T_dca, T_lump and T_hold: median, 10th and 90th percentiles, share above 0), Q of every kind, the knife (median 14.04%, worst 76.39%), δ and the USDC left: all within 1e-14 | yes |

I ran my statement of D1 and D2 both on my own runs table and on `runs.parquet`. Both give the default and the label
above.

**How the default passes D1.** D1's bad-case test compares, at each start wallet:
- **Q:** the fall from a peak that 1 window in 10 exceeds;
- **the worst fall:** the deepest of the 49 windows.

The ladder must be no deeper than its monthly twin on both. Kraken 1x, in % (margin = twin minus ladder):

| Start | Q / Q_dca | Margin | Worst / worst of dca-same | Margin |
|---|---|---|---|---|
| A: all USDC, buys 50/50 | 70.75 / 73.39 | 2.64 | 72.46 / 75.67 | 3.21 |
| B: all USDC, buys 75/25 | 64.74 / 68.62 | 3.88 | 66.26 / 69.75 | 3.49 |
| C: 30% crypto, 50/50 | 72.39 / 74.62 | 2.23 | 74.14 / 78.79 | 4.65 |
| D: 30% crypto, 75/25 | 67.22 / 68.85 | 1.63 | 71.19 / 71.27 | **0.08** |

At start D the ladder's worst window is window 0 (2017-01 to 2019-01), and dca-same's is window 10 (2017-11 to
2019-11).

**Can anything change the default or its label?** No, not under the plan's rules:
- **Arithmetic:** every run and every rule reproduces.
- **Doubled costs:** the same default. Start D's margin is 71.21% against 71.30%.
- **The other reading of the one-year high** (R2.1: a close exactly 365 days back counted, so 366 closes):
  - my rerun of all 90,628 runs changes the ladder's events in 8 of 30,024 dip runs;
  - D1 gives the same answer in all three pools, and the without-2017 check is still NO DEFAULT.
- **The label:** it needs only one moved check, and two move:
  - without 2017, the default fails Q at all four starts, by 1.9 to 3.5 points;
  - on Binance, it fails Q at the 75/25 starts, by 2.2 and 0.8 points.

**But the default is fragile, and RESULTS.md should say how** (finding 4). It is an isolated passing point. Each of
its one-step neighbours in the grid fails the bad-case test:
- **Y 20%:** (20%, 10%, 25%, 100%) has the deeper worst fall at B (by 2.4 points) and D (by 1.0);
- **Z 5%:** (30%, 5%, 25%, 100%) at D, by **0.04** points;
- **Z 20%:** (30%, 20%, 25%, 100%) at D, by 5.0 points;
- **X 10%:** (30%, 10%, 10%, 100%) fails Q at A, C and D, and the worst fall at A and D;
- **M 50%:** (30%, 10%, 25%, 50%) fails Q at A and the worst fall at D.

### 3. Runs rerun from scratch, look-ahead and tamper checks

- **The rerun covers every run, not a sample.** It covers:
  - every setting at every start, on all 49 Kraken windows at 1x and 2x and on all 41 Binance windows;
  - with each dip run's dca-same, lump-same and hold twins.

  It takes 31 s on 3 processes. The comparison is in the table above.
- **No look-ahead in the rule (code and rerun).** The decision at close t reads only:
  - I_t and H_t, which use closes up to t;
  - the wallet's weights and value at close t.

  The order fills at the open of t+1. My implementation decides the same way, and the engine's runs equal mine to
  round-off.
- **One known look-ahead, by design, in the yardstick.** The twins use the dip run's total for the whole window,
  which is known only at its end (PLAN.md sections 6 and 15). It is not in the rule a customer runs.
- **Tamper the future.** I tampered with the lab's own `dipbuy` on real Kraken train bars, 300 cases:
  - windows 0, 12, 18, 30 and 40;
  - three settings: the default, (10%, 5%, 10%, 100%) and (20%, 20%, 10%, 50%);
  - two starts: all-USDC 50/50 and 30%-crypto 75/25;
  - cuts at up to 10 of each run's trigger, crossing, re-arm and limit-fix closes, and at the close after each.

  From the cut on, I multiplied every open, high, low and close of both coins by random factors (and the volume by 3),
  then recomputed the index and the high over the whole tampered panel. In all 300 cases these were bit-identical
  before the cut:
  - every result row;
  - I and H;
  - every order (close, reason and targets);
  - every buy record and every ladder event.

  Later rows moved in all 300.
- **Touch the present.** Doubling both closes at one close moves I there and nothing before. H moves too where the
  new I tops the year's high. That happened at 4 of my 5 closes. At the fifth (late 2022) it did not, and H rightly
  stayed.
- **Fidelity at the default** (Kraken 1x, all 196 runs):
  - none of the 1,246 ladder buy orders included a sell leg, so section 13's "buys go only from USDC" holds in the
    simulation;
  - legs were a median 166 USD and at most 3,351 USD. None is above the 10,000 USD point of the slippage table, so no
    slippage was extrapolated. 29% are under 100 USD, where the table is flat.

## Findings

Severity: **blocking** (the run or its decision cannot stand), **should fix** (the write-up says something the
outputs do not support), **note** (worth knowing; no change required). **No finding is blocking.**

**1. Should fix: "spreading the same money monthly" is not what dca-same did.** RESULTS.md calls dca-same "the same
dollars in 12 monthly pieces" and uses "spreading the same money monthly" throughout, the app wording included. At the
default (Kraken 1x, 196 runs):

- **The limits cut every dca-same twin.**
  - The cut was a median 35-47% of its total, by start.
  - Its first cut came at a median of day 120. One twin in 10 was cut by day 45.
- **The reason:** the ladder ordered a median 1.73 times the starting cash. So each monthly piece is about 14% of it,
  and the wallet reaches the 78% crypto cap within a few months.
- **It moved less money than the ladder** in 173 of the 196 runs. In the median run it moved 84% of what the ladder
  moved.

So it is a monthly schedule of the ladder's own total, cut at the Steady limits. It is a fair yardstick for "when the
money goes in". But a customer will read "the same money spread monthly" as a calm year-long plan, and that is not what
was measured. The Readings section says the twins were cut, but then says "both end near the 22% cash floor", which
its own medians contradict (finding 2).

**Fix:** name it as it is wherever "spreading the same money monthly" appears. The app wording must not say "the same
money".

**2. Should fix: the twins did not "end near the 22% cash floor".**
- **What RESULTS.md says:** "both end near the 22% cash floor (median USDC left: dca-same 31-39%, lump-same 36-43%)".
- **The problem:** those medians are 9 to 21 points above 22%. At the end the twins held *more* USDC than the ladder
  (24-29%).
- **What does hold:** over a window the three were similarly invested on average. The median time-average crypto
  share is 68% for the ladder, 67% for dca-same and 68% for lump-same; the cap is 78%.

**Fix:** say that instead.

**3. Should fix: G is per dollar ordered, not per dollar moved.** RESULTS.md says:
- "each lost money per dollar moved" (D1's bullets);
- "G is T_dca rescaled by the money moved" (D3).

G divides by the amount ordered before the caps, and that includes the 27-37% (median by start) that the limits cut
and never bought. **Fix:** "per dollar ordered, before the limits cut it".

**4. Should fix: the default's fragility needs its full statement.** RESULTS.md gives the 0.08-point margin at start D.
It should add two facts from section 2:
- none of the default's five one-step neighbours passes the bad-case test, and one of them, (30%, 5%, 25%, 100%),
  fails by only 0.04 points;
- with D's margin the other way, D1 would have named (10%, 20%, 25%, 100%).

It should also replace "Its effect on these results was not measured" (the one-year-high reading) with section 2's
measurement: 8 of 30,024 dip runs change their events, and D1 and D2 are the same.

**5. Should fix: the app sentence.** It reads: "buying on dips beat spreading the same money monthly in 48% of two-year
periods. After its last buy the price fell up to 76% further." Three problems:
- **48%** pools the four start wallets over 49 overlapping windows (94 of 196 runs). By wallet it is 43-51%: a coin
  flip.
- **76%** is the 50/50 BTC/ETH mix. For a 75/25 split the worst was 68%. It is the mix's fall, not "the price".
- **The yardstick:** finding 1.

**Fix:** for example: "About half the time (43-51% of two-year periods, by wallet), buying on dips ended ahead of a
monthly schedule of the same total, cut at the Steady limits. After its last buy, the BTC/ETH mix fell up to 76%
(50/50) or 68% (75/25) further." Keep the two facts RESULTS.md puts next to it: the bad case is about 70% of the
wallet, and the default is NOT ROBUST.

**6. Should fix: smaller precision errors.**
- **Which windows bought on day one:** "windows starting in 2018, 2019 and early 2020". The 25 windows are those
  starting February 2018 to May 2019 and September 2019 to May 2020 (k = 13..28 and 32..40). The January 2018 window
  and the June to August 2019 windows did not buy on day one.
- **Which windows trailed lump-same:** "windows starting in 2017, and from June 2020 on". The ladder also trailed in
  the April 2018 window (k = 15, all four starts) and the May 2020 window (k = 40, three starts). It was ahead in the
  June and July 2017 windows (k = 5 and 6) at every start.
- **Fees:** "customer fees were a median 0.07-0.12% of the wallet a year". The medians by start are 0.066-0.115%, so
  0.07-0.11%. And "fees a year" leaves out fills on a window's second row:
  - in the 50 all-USDC runs whose ladder bought on day one, that first ladder buy (median 0.19% of the wallet) is in
    `first_cost_pct`, not in fees a year;
  - those runs show a median of 0.067% a year, against 0.116% for the others.

  Say so in a word.
- **The cash floor:** "a median 26% of the wallet was USDC (the floor is 22%)". The Steady limit is 20%. Buys stop at
  22%, and a limit fix restores 22%, but cash can sit between 20% and 22%. The lowest end share was 20.5%.
- **The amount the limits cut:** "which were 36% of everything it ordered". 36% is the pooled total. Per run the median
  is 33% (27-37% by start), which is the figure the D3 section quotes. Say which one is meant.

**7. Should fix (records).**
- RESULTS.md's "Audit: pending" should point here.
- The README's status still says "A1 and run 0 not yet run".
- PLAN.md section 16 has no row for run 0 or this audit. Adding rows changes PLAN.md's hash. That matters only for an
  amendment run, which would record the new hash.

**8. Note: the label is solid, and Binance's move is about windows, not prices.**
- **On Kraken's own runs over Binance's 41 windows** (k = 8..48), D1 also gives NO DEFAULT, failing at the same
  starts, B and D. So the Binance check moves the default because Binance has no windows starting January to August
  2017, not because its prices differ. RESULTS.md says this; I confirm it.
- **The bad-case test passes only with the 2017-start windows.** In every window starting May to December 2017
  (k = 4..11), at all four starts, dca-same's worst fall was deeper than the ladder's, by 1.3 points or more.

**9. Note: most of the range the app offers failed the plan's own bad-case test.** This is for `risk-officer`, who set
the range in section 13:
- **On Kraken:** 44 of the 54 combinations fell deeper than dca-same at some start.
- **On Binance and without 2017:** all 54 did.
- **Against the budget:** every combination at every start has a Q of at least 58.6% on Kraken (41.5% on Binance),
  against the 35% budget. On Kraken, a wallet that simply holds its 30% crypto start is above it too (59-61%).
- **At the default:** every one of the 196 runs fell more than 35% at some point; the smallest worst fall was 42%.

The budget is shown, not enforced (section 13), so this changes no rule. It does mean no combination can be presented
as gentler than a monthly schedule, and none as inside the Steady budget.

**10. Note: the default is picked in sample, and its edge over the yardstick is negative anyway.**
- **How it is picked:** D1 takes the best G̃ among the 10 usable settings, on the same 49 windows it is described on.
  That flatters it.
- **What G̃ is:** the median gain per dollar the ladder ordered, against dca-same. Even so the default's G̃ is
  −0.0057: about 0.6 cents behind per dollar ordered.
- **No setting that beat the yardstick passed:** all six settings with a positive G̃ failed the bad-case test.

With no validate look planned, the plan's own framing (no edge claimed) is the right one.

## Checklist (backtest-auditor), adapted to a tool-default study with no edge claim

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | All 90,628 runs rebuilt by independent code to about 1e-14; 300 tamper cases unchanged before the cut. The twins' total is known only at the window's end: a yardstick by design (PLAN.md sections 6 and 15), not in the rule |
| 2 | Survivorship | N/A | BTC, ETH and USDC only |
| 3 | Data snooping | PASS (disclosed) | Validate-window looks used: 0; the test window was not read; the train years' earlier looks are disclosed (PLAN.md section 2, P1-P5); no amendment run |
| 4 | Point-in-time inputs | PASS | I and H use closes up to t (H from the full panel's prior 365 days); B, the caps and the limit fix use the wallet at close t; fills at the next open |
| 5 | Parameters vs trades | N/A (no edge claim) | 4 settings, picked from a pre-registered grid of 54. At the default a window holds a median of 7 buy orders and 15.5 limit-fix sales, but the 49 windows overlap heavily (about six independent years) |
| 6 | Plateau | FLAG (not a plan gate; there is no Sharpe) | None of the default's one-step grid neighbours passes D1's bad-case test; the default's margin at start D is 0.08 points (finding 4) |
| 7 | Walk-forward | N/A | Nothing is fitted; D1 picks in sample on the same windows, and no out-of-sample look is planned (finding 10) |
| 8 | DSR, total trial count | N/A | No edge claim and no Sharpe. The grid is 54 settings; 90,628 runs, all logged, none failed |
| 9 | PBO | N/A | As item 8 |
| 10 | CPCV distribution | N/A | Not in the plan. D3 reports each measure's 10th, 50th and 90th percentiles over the windows, by start and by year |
| 11 | Cost model | PASS (placeholders) | `config/costs.yaml` as read (pool 5 bps, aggregator 0, slippage 10/15/30 bps at 100/1,000/10,000 USD, gas 0.10 USD a leg); my own cost function from those numbers reproduces every run. They are still placeholders (SCOUTING) |
| 12 | Doubled costs | PASS | Kraken 2x gives the same default, the same 10 usable settings, G̃ −0.0050 |
| 13 | Capacity | N/A (scouting) | At the default, legs median 166 USD, at most 3,351 USD; none above the slippage table's 10,000 USD point. No measured Base slippage yet |
| 14 | Bad case against the budget | FAIL (shown, not enforced) | No Monte Carlo in this plan. At the default, Q is 65-72% against the 35% budget, and every run fell more than 35% (smallest 42%). Every setting is above the budget (finding 9) |
| 15 | Regimes | FLAG | NOT ROBUST: without the windows touching 2017 there is no default. By the year a window starts, against dca-same: 2019 starts ahead in 83-100%, 2018 and 2020 starts in only 17-42% |
| 16 | Benchmarks | N/A (the plan's own yardsticks) | The plan compares with dca-same, lump-same and hold, not with BTC buy-and-hold or a 50/50 rebalance. Against dca-same: ahead in 48% of runs (a coin flip; finding 1 on what dca-same is). Against lump-same: ahead in 62%, median +5% |
| 17 | Data quality and snapshot | PASS | Snapshot, bars hash and both panel hashes reproduced; the one pinned missing close (Kraken 2018-01-13); 729-731 rows a window; every run row carries the snapshot id and commit |

**Final test window: not run, and not part of this study.** It claims no edge and picks a tool's default. No validate
look is planned (PLAN.md section 12), and the test window stays unread for buy-the-dip.

**Verdict:**
- **The run and its decision: PASS.** The default (30%, 10%, 25%, 100%) and its label NOT ROBUST stand as computed.
- **RESULTS.md: back to the lead** for findings 1-7. None of them changes a decided number.
- **The app wording** goes to `risk-officer` with findings 1, 5 and 9.

## Record

- **Audited:**
  - run 0, 2026-11-24 18:08:49 to 18:21:53 UTC, commit `e62233e`, config hash `086fffac…`, snapshot
    `1746a21b75683e76`;
  - outputs in `results/buy-the-dip/run0/` (read only), and the tracked `RUNLOG.jsonl`, `runs.csv` and `decision.json`.
- **My recompute:**
  - my own ladder, twins, book and costs, run over all 90,628 runs (31 s on 3 processes);
  - the same again under the other one-year-high reading (a description only);
  - my own statement of D1-D3 on my runs and on the run's;
  - 300 tamper cases and 5 touch-the-present cases on the lab's `dipbuy`;
  - the two buy-the-dip test files on today's tree (126 passed).
- **Bars read:** only through my guarded loader:
  - four requests, each ending 2023-01-01 00:00 UTC;
  - both panels end at 2023-01-01;
  - no validate or test bar was requested or received.
- **Not read:** hold-mix-cap's RESULTS.md, RISK.md, AUDIT.md, `decision.json`, `runs.csv` and `falls.csv`, and the
  "Hold this mix" section of `docs/app/features.md`.
- **Written:** this file only, plus scratch scripts in the session scratchpad (`dipaudit/`).
- **Validate-window looks used for buy-the-dip: 0.** The test window was not read.

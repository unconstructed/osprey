# protect-gains V1: the 30-day buy-back on the validate window (pre-registration)

**Status: PRE-REGISTRATION.** Written by the lead on 2026-11-23, after run 0 and its audit, before any validate bar
was read for protect-gains. The owner asked for it in chat ("yes", 2026-11-23) when offered "its own pre-registered
test on data we haven't used yet". It is committed before the code that runs it.

> **SCOUTING ONLY,** like run 0: the reference engine (`lab/runner/portfolio.py`, driven by `lab/runner/protect.py`),
> the placeholder costs of `config/costs.yaml`, and exchange candles in place of Base prices. A pass here makes
> nothing ready for paper and is **not a lab default**. It is evidence for the owner's own decision.

## 1. In plain words

After run 0, the lead looked back over the results and found one setting that did well all round:
- **line A at X = 10%** ("sell if the wallet falls 10% below its highest value");
- **with an automatic buy-back 30 days after the sale** (the plan's wait-30 mode);
- **under the "counts" reading** (in force).

This plan calls it **A10/30d**. Over 2017-2022 it:
- cut the bad-case two-year fall from 65% to 43%;
- kept nearly all of the typical gain (+112% against +114%);
- ended ahead of the tool alone on average.

But it was **picked after seeing 168 settings**. Run 0's own rules gave it no default:
- it protected only 2 of 6 mixes by a third (D1);
- 38% of its buy-backs were sold again within a month (D2 allows 25%).

This test runs A10/30d once, unchanged, on 2023-01-02 .. 2024-07-01, which no protect-gains run has read. It asks
three questions:
1. Does it keep the gain?
2. Does it avoid deeper falls?
3. Does it whipsaw?

## 2. What the lead and the owner already know about this window (disclosure)

| # | What was seen | By | What it could inform |
|---|---|---|---|
| P1-P4 | As in PLAN.md section 2 | | |
| T1 | protect-gains run 0 and its audit (train years) | the lead, the owner, `backtest-auditor` | The choice of A10/30d (post hoc) |
| V0a | dip-timing's single validate look (2026-11-20): 8 dip events in this window (BTC 4, ETH 4) and how they turned out | the lead and the owner | That the window holds dips of the size the brake reacts to |
| V0b | The data-quality record (`research/rebalance-steady/DATA.md`, milestone 1): 547 daily rows per source, 2023-01-02 .. 2024-07-01, none missing | the lead | The row counts pinned below |
| V0c | General knowledge: BTC and ETH rose strongly from early 2023 to mid-2024, with several pullbacks of roughly 20% | everyone | That this is a rising market, not a crash |

**So this window mainly tests the cost of the brake in a rising market.** It cannot test the protection against a
2018- or 2022-style crash, because it holds none. The checks below are set with that in mind, before the look.

## 3. Data

- **Bars:** `lab.data.panel.load_panel(source, "1d", last_close=2024-07-01 00:00 UTC)` for KRAKEN (primary) and
  BINANCE (robustness). The loader is never asked for a later close. Every frame is checked:
  `index.max() <= 2024-07-01 00:00 UTC`. **The test window is never read.**
- **Pins:**
  - snapshot `1746a21b75683e76`;
  - bars hash `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e`;
  - the rows up to 2023-01-01 must equal PLAN.md section 3's panel hashes (Kraken `355aabe2…`, Binance `2c1a4257…`);
  - the validate rows must be 547 per source, 2023-01-02 .. 2024-07-01, none missing.

  Any difference stops the look (INCONCLUSIVE, and the look is spent).
- **The index I** (for the missed-rebound measure and the trend description) is computed over each source's whole
  loaded panel, as in run 0, and cut to each window. Rows before a window are history, never future.
- **Costs:** `Costs.from_yaml(capital_usd=5000)` (1x) and `.stressed(2.0)` (2x).

## 4. Windows

- **12-month windows j = 0..6.** Window j holds the bars of the 12 months from M_j = January 2023 + j months. Its
  closes run from the 2nd of M_j to the 1st of M_(j+12) at 00:00 UTC, both included:
  - j = 0: 2023-01-02 .. 2024-01-01, 365 closes;
  - j = 6: 2023-07-02 .. 2024-07-01, 366 closes.

  Two-year windows do not fit in 18 months.
- **The full span** 2023-01-02 .. 2024-07-01 (547 closes), one run per mix. A description only.
- **D** is the 5,000 USD deposit at each window's first close, as in run 0 (PLAN.md section 4).

## 5. Runs (fixed now; nothing else is run on this window)

**Fixed in every run:**
- the 6 mixes of PLAN.md section 4;
- the tool at the owner's default (band 0.30, cap 2, a 15-day wait);
- the Steady limits as read.

**Per (source, cost, window, mix), four runs:**

| Run | Role |
|---|---|
| R: the tool alone | Reference |
| **A10/30d, "counts"**: line A, X = 0.10, mode wait30, reading counts | **The candidate** |
| A10/30d, "separate" | Description |
| A10/trend, "counts": run 0's strongest protection | Description |

**Count:**

| Part | Arithmetic | Runs |
|---|---|---|
| 12-month windows | 2 sources × 2 costs × 7 windows × 6 mixes × 4 runs | 672 |
| Full span | 2 sources × 2 costs × 6 mixes × 4 runs | 96 |
| **Total** | | **768** |

**Measures:** per run, as PLAN.md section 7 and amendment A2 define them, with the same code
(`protect.run_measures`):
- F, the worst fall;
- C = 1 − V_end / V_end(R) against R in the same window;
- fires;
- re-stops;
- days in USDC;
- the overshoot;
- the missed rebound.

## 6. The checks (fixed now)

**The pool:** Kraken, 1x, the 12-month windows, A10/30d "counts" against R: 42 runs each.

| # | Check | Passes when |
|---|---|---|
| V-a | **It keeps the gain** | The median of C over the 42 runs is ≤ 0.10. In a typical year it ends no more than 10% below the tool alone |
| V-b | **No deeper falls** | The 90th percentile of F (`numpy.percentile(..., 90)`) is ≤ R's, **and** the worst F is ≤ R's worst F |
| V-c | **Whipsaw** (run 0's D2 rule) | Re-stops / buy-backs ≤ 25% over the pool. With no buy-back the share is MISSING, and V-c fails |

**The verdict** (Kraken 1x):
- **HOLDS UP:** V-a and V-b pass.
- **DOES NOT HOLD UP:** either fails.
- **MISSING:** a failed run in the pool.

**The headline** names the verdict and V-c separately, e.g. "HOLDS UP; whipsaw FAIL". V-c is kept apart because the
window holds no crash: it is the brake's main risk in a rising market, and run 0 already failed it.

**Robustness** (descriptive, decides nothing): the same three checks and the verdict on Binance 1x and on Kraken 2x,
labelled "same" or "differs" against the headline.

**Also reported** (descriptive):
- every check per mix;
- the full-span runs;
- the "separate" reading and A10/trend against R;
- the mean C;
- how often A10/30d ended ahead;
- each stop's date and its overshoot.

**What the result means:**
- **HOLDS UP with whipsaw PASS:** the post-hoc pick looks as good on unseen, rising-market data as it did in
  training. It is still not a lab default (run 0's D1 and D2 gave none). The owner may choose to suggest it, as a
  written decision, after the NautilusTrader rerun with measured costs.
- **HOLDS UP with whipsaw FAIL:** it kept the gain and did no harm, but it still whipsaws. Same status, with that
  warning.
- **DOES NOT HOLD UP:** the pick does not survive fresh data. The app should not suggest it.

## 7. Protocol

- **Before the look:**
  1. This plan is committed.
  2. The code and its tests (section 8) are built and committed.
  3. On that commit, the full tier (100% branch coverage), the deep profile and ruff pass with a clean tree.
- **One look.** Before any validate bar is read, `run_validate.py` writes:
  - `results/protect-gains/validate/STARTED`;
  - a start record (commit, config hash, snapshot, this plan's SHA-256);
  - one RUNLOG line (`"event": "validate look V1"`).

  It refuses to start when the RUNLOG holds a validate look, when `results/protect-gains/validate/` exists, on a
  dirty tree, or with other folders than the pinned ones. A crash or a stop after `STARTED` spends the look: the
  outcome is INCONCLUSIVE, it is written to `look.json`, and the look is never repeated.
- **Validate-window looks for protect-gains:** this is the only one. After it, the window is spent for this study.
  No other setting is run on it.
- **Consistency checks** as in run 0 (PLAN.md section 9): the tool copy equals `hold_mix`, every brake check, and
  the counts (768 runs). A failure stops the look (INCONCLUSIVE).
- **Outputs:**
  - `results/protect-gains/validate/` (git-ignored): `start.json`, `runs.parquet`, `stops.parquet`, `look.json`;
  - committed: `RUNLOG.jsonl`, `validate_runs.csv` (one row per run, no Sharpe or return column) and
    `validate_look.json`;
  - the write-up `VALIDATE.md`, by the lead;
  - one `backtest-auditor` check after the look.

## 8. Code and tests

- **`research/protect-gains/run_validate.py`** reuses `lab/runner/protect.py` (unchanged) and `run.py`'s helpers.
- **`tests/test_protect_validate.py`**, synthetic bars only:
  - the 7 windows and the full span by hand from the calendar;
  - the count of 768;
  - **the test-window guard:** the loader is never asked past 2024-07-01, and a returned bar after it stops the look;
  - the train-part panel hash and the validate row count stop the look;
  - **one look:** `STARTED` and the RUNLOG line exist before any bar; a second start is refused (RUNLOG line, folder,
    copied folder); a crash spends the look and writes INCONCLUSIVE;
  - the dirty-tree and pinned-folder guards;
  - V-a, V-b, V-c and the verdict by hand at their boundaries (a median of exactly 0.10 passes; equal Q and equal
    worst F pass; a re-stop share of exactly 25% passes; no buy-backs fail V-c; a failed run gives MISSING);
  - **every reported number recomputed from the runs table:** the checks, robustness, per mix, full span;
  - **tamper-the-future** on a window's runs (rows before a cut unchanged);
  - a synthetic dry run, with workers 1 and 2 byte-identical if workers are used.

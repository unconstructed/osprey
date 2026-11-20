# Dip timing ("option C"): pre-registration

Written 2026-11-20 by `quant-researcher`, **before any result exists**. Repo HEAD at writing `2ef1632`; data
snapshot `b08377c310126e3f` (Kraken daily bars, `reports/data/2026-11-20.md`). The only numbers below are
**event counts** (no prices, returns or outcomes were computed). Risk level **Balanced** (stop required);
coins BTC and ETH, USDC is cash; daily bars `BTC/USD.KRAKEN`, `ETH/USD.KRAKEN`. Every profit number this study
produces is **SCOUTING** from the reference backtester, not NautilusTrader (hard rule 3; the Nautilus runner is
on hold). It is labelled that way everywhere, and nothing goes into `reports/<strategy>/`.

## 1. Question

The owner asked two things. (1) **Is this dip worth buying, or is it a falling knife?** (2) **When should we buy**
so the entry is as good as the statistics allow? Being close to the bottom counts only if it shows up as profit
after costs. "No edge" is an acceptable answer.

Hypothesis: crypto dips are often forced deleveraging. Once leverage is flushed out (funding turns negative,
open interest falls) and selling exhausts (an up-day, a narrower daily range), prices tend to recover over the
following weeks. Dips in a downtrend, or with leverage still building, more often keep falling. **This is
wrong if** no rule beats buying at once (T1) by more than random timing inside the same window does, and no
filter beats skipping the same share of dips at random, after costs.

**Why not a direct crash predictor.** The owner discussion counted about 41 separate 20%+ 10-day BTC drops
since 2015. That figure was not recounted here, because it covers 2015-16 and the test window. On train plus
validate only, the same drop gives 120 trigger days, which become 27 separate events with a 10-day cool-off and
22 with a 31-day cool-off. That is about 3.6 a year, consistent with ~41 over 2015-2026. About 20 BTC positives
in train cannot fit and validate a classifier. Spot-only, a crash call can only move us to cash, and false
alarms miss rebounds. Asking about a dip that has already happened nearly doubles the events per coin (BTC: 37
in train, against about 20 crashes), gives 80 events across BTC and ETH, and is exactly the decision
`dip-buy-balanced` takes.

## 2. Dip events

**One fixed primary definition (D0) plus a sensitivity grid that is reported but never used to choose.**
Tuning the definition would add trials, and the DSR is already strict at this sample size (TESTING.md
section 4). Trigger at close t: `close[t] / max(close[t-20..t]) - 1 <= -15%`, the same form as
`reference._dip_signal`. `P_ref` is that trailing high.

**De-duplication.** After a trigger at t0, the same coin cannot trigger again before t0 + 31 bars (cool-off =
H + 1). The position from one event is always closed before the next event can start, so event-level and
strategy-level results map one to one, and label spans for one coin never overlap. Price recovering above
`P_ref` does not end an event early, because a re-trigger while still holding could not be traded.

**Assignment.** An event belongs to the window that contains its whole span [t0, t0 + 31]. Windows count bars,
and gaps are not filled. Train events start once every feature exists (bar 100 of train, close 2017-04-12).
No bar before 2017-01-01 is loaded.

Train (validate) events per coin, BTC / ETH, from the counting run:

| X \ N | 10 | 20 | 30 |
|---|---|---|---|
| 10% | 44 (6) / 50 (7) | 46 (7) / 52 (8) | 48 (7) / 53 (8) |
| **15%** | 31 (1) / 38 (1) | **37 (4) / 43 (4)** | 38 (4) / 45 (6) |
| 20% | 20 (0) / 27 (1) | 28 (0) / 34 (1) | 28 (0) / 36 (1) |

- **D0 in numbers:** 80 train and 8 validate events. Excluded: 4 triggers before features exist, 1 BTC event
  whose span would reach past 2024-06-30, and 0 events straddling train and validate.
- **Why 15%/20:** at 10%, event spans cover two thirds or more of train days, which is hardly a "dip". At
  20%, validate keeps only 1 event.
- **Positioning coverage (D0 train):** funding 18 BTC + 19 ETH = 37 events; open interest 15 + 9 = 24. All 8
  validate events have both.

## 3. Entry timing rules (fixed list) and the shared exit

Every rule decides at a close and fills at the next open, using the reference engine semantics and
`config/costs.yaml`. Each coin is a sleeve of USD 10,000, in cash between events and at the rule's target
weight inside one (1, or steps of 1/3 for T2). The entry window is K = 10 decision days, t0 to t0+9.

| Rule | Entry |
|---|---|
| T1 | Next open after the trigger (fill at t0+1) |
| T2 | Ladder of target weights 1/3, 2/3, 1: the first third as T1. The second and third are bought at the next open after a close ≤ `P_ref·(1-X-5%)` and ≤ `P_ref·(1-X-10%)`. Unfilled tranches are cancelled after day t0+9. These are close-triggered, not intrabar limits: the engine and Nautilus bar execution fill at opens, and assuming limit fills at the touch is optimistic. |
| T3 | First close in the window with `close[t] > high[t-1]` |
| T4 | First close in the window with `ln(high/low)[t] <` the mean of the same over t-5..t-1 |
| T5 | First close in the window with model `p_B(t) ≥ θ_B` (section 4), where θ_B = the share of positive labels in that split's training rows. Nothing else is tuned. |

T3 to T5 are pure timing rules: if the signal never fires, they buy at the open after t0+9 (forced entry; the
share of forced entries is reported). Skipping a dip is the job of the Q filter (section 4).

**Shared exit, anchored to the trigger so every rule has the same exit:** sell at the open of t0+31. A stop
sells at the next open after any close ≤ average fill price × (1 - 15%). After a stop there is no re-entry in
that event.

## 4. Model targets and features

- **(a) Dip quality Q**, evaluated at t0: `y_Q = 1` if the T1 round trip, after costs and both legs (cash
  earns 0), returns more than 0. Model: L2 logistic regression with C = 1 on train-standardised inputs, using 3
  features:
  - speed: bars from `P_ref` to t0, divided by N;
  - `ma_dist_100`;
  - `vol_ratio_10_60`.
  A dip is taken when `p_Q ≥` the share of positive labels in the training rows.
- **(b) Bottom-in B**, evaluated on each day d in t0..t0+9: `y_B(d) = 1` if `min(low[d+1..d+10]) ≥ close[d]·(1-5%)`.
  The label window always stays inside the event span. Two models:
  - L2 logistic regression on 6 features: days since trigger; depth below `P_ref` in volatility units
    (`/(ewma_vol_20·√20)`); bounce off the lowest low since t0; T4's range ratio; T3's up-day flag;
    `volume_z_20`.
  - LightGBM (`train.make_model` defaults, seed 0) on those 6, the 3 Q features and the 15
    `lab.models.features`.
- **Positioning**, from Binance USDT-M perpetuals (`data.binance.vision`, CHECKSUM-verified, files only up to
  2024-06):
  - `funding_7d`: the mean of the last 21 funding prints with print time τ **strictly before** the bar close.
    The 00:00 print counts from the next bar on.
  - `oi_chg_dip`: ln(OI at the close / OI at `P_ref`'s close). OI is the last 5-minute `sum_open_interest`
    snapshot at or before close − 5 min.
  - Each positioning variant is paired with the same model **without** positioning on the same events, so the
    value of positioning is measured directly.

## 5. Baselines

Volatility-only (the Q model with `ewma_vol_20` as its only input, a learned volatility cutoff); base rate (T1
on every dip); rules T1-T4; buy-and-hold of both sleeves over the same days; 50/50 BTC/USDC (`constant_mix`,
weight 0.5, every 30 days). Null distributions, 100 seeds each and not trials: a random entry day in the
window, random skipping of the same share of dips, and `random_entry` with the same trade count and hold.

## 6. Evaluation

- **Train (events from close 2017-04-12 to 2022-12-31), event-level CPCV:**
  - Events of both coins are pooled and sorted by t0, then cut into 6 contiguous time groups with 2 test
    groups: 15 splits, 5 paths (`splits.cpcv` groups and `cpcv_paths`).
  - **Purge:** any training event whose span [t0, t0+31] overlaps a test group's span.
  - **Embargo:** training events with t0 within 31 days (≥ H) after a test group's span.
  - Day-level rows for B stay with their event.
  - T1 to T4 have no fitted parts, so their results are the same on every path.
- **Validate (2023-01-01 to 2024-06-30), one look at the end:**
  - Models are refit once on all train events and evaluated on the 8 validate events.
  - All of V01-V10 and the baselines are reported. The look is logged below.
- **Metrics:**
  - Per event, after costs: net return r_e, with a skipped event counted as 0. Paired Δ_e = r_e(V) − r_e(T1).
  - Entry distance above the dip's low: the minimum low over t0..t0+30. This is reported but has no role in
    the criteria.
  - Maximum adverse excursion, the share of dips skipped or partly filled, and the share of forced entries.
  - Strategy level, both sleeves (scouting): OOS Sharpe after costs per path, return, maximum drawdown, trades
    and turnover.
  - DSR on the best variant's median-path series. The raw count is every logged variant; the effective count
    is `stats.effective_trials`.
  - PBO with `stats.pbo` and 10 blocks over all variants, averaged over the 5 paths.
- **Inference:** the mean Δ uses a block bootstrap that resamples the trigger months together (BTC and ETH
  dips coincide): 10,000 draws, seed 0, one-sided. The primary family is V02-V10 against T1, with Holm
  correction at 5%. With 80 events, 80% power needs a mean Δ of at least 2.5·sd(Δ)/√80; that threshold is
  reported in % with the results.

## 7. Success criteria and trial budget

A variant has an **EDGE** only if all of these hold:
1. The train Holm-adjusted p < 0.05 for mean Δ > 0.
2. Model variants: Δ > 0 on at least 4 of 5 paths.
3. It beats the 95th percentile of its random null: random timing for T2-T5, random skipping for filters, and
   both for the combinations V09-V10.
4. Δ > 0 with costs doubled.
5. Δ > 0 in at least 6 of the 9 (X, N) cells.
6. Its strategy-level Sharpe is above T1's on at least 4 of 5 paths, and PBO ≤ 0.25.
7. Validate mean Δ ≥ 0. With 8 events this check can reject but cannot confirm.

The outcome is graded as follows:
- **EDGE:** criteria 1-7 hold and DSR (effective count) ≥ 0.95. The variant goes to `dip-buy-balanced` for a
  Nautilus build.
- **PROMISING:** criteria 1-7 hold, but DSR < 0.95. It is documented and not built.
- **NO EDGE:** criterion 1 or 3 fails.

Separately, and only as a description, the report states whether T1 beats cash, buy-and-hold and 50/50.
A positioning feature adds value only where its variant (V12, V14, V16) beats its paired reference (V11, V13,
V15), with Holm at 5% across the three and the same bootstrap.

**Budget: at most 45 logged variants.** 40 are fixed now and 5 are reserved for logged amendments, such as a
rerun after a bug fix, which gets a new ID. Every variant counts towards the DSR and PBO, whatever the outcome:
- V01 T1; V02 T2; V03 T3; V04 T4; V05 T5 (logistic); V06 T5 (LightGBM).
- V07 volatility-only + T1; V08 Q + T1.
- V09 Q + the better T5 on train; V10 Q + the best of T2-T4 on train.
- Positioning pairs:
  - V11/V12: Q vs Q + funding, on funding-covered events.
  - V13/V14: T5 vs T5 + funding, on the same events.
  - V15/V16: Q vs Q + funding + OI, on OI-covered events.
- V17-V24: T1 on the 8 other (X, N) cells.
- V25-V32: the best variant on those cells.
- V33-V34: θ = base rate ± 0.10.
- V35-V36: best and T1 at 2x costs.
- V37-V38: best and T1 on Binance bars.
- V39: best with H = 20.
- V40: best with a 10% stop.

"Best" means the variant with the highest train mean r_e among those passing criteria 1-3, or the highest
overall if none passes. The sensitivity runs happen either way, so the trial count does not depend on the
outcome. Every variant is logged as one row in `results/dip-timing/` (Parquet) and in the committed
`research/dip-timing/trials.csv`, with: ID, definition, rule, model, features, window, snapshot, commit, seed,
status and metrics. MLflow will be added once it exists. Failures are logged; nothing is deleted or rerun in
place.

## 8. What will NOT be done

- **The test window is never read.** No bar or positioning record after 2024-06-30 is downloaded, loaded or
  evaluated. Every loader call loads only up to close 2024-07-01 00:00 UTC, keeps `in_window(train) |
  in_window(validate)` and **asserts** that `index.max() <= 2024-07-01 00:00 UTC`. A test checks that the
  assert fires.
- **Validate:** no tuning on it, no second look, and no change after the look. Any change after that needs a
  new pre-registration.
- **No new features, rules, targets, coins or definitions** after seeing train results, except through a
  logged amendment in this file before the run. None at all after validate.
- **Out of scope:** no Optuna search (every parameter is fixed above), no hourly bars, no intrabar limit fills,
  no data before 2017, no futures trading (positioning is only a feature), no leverage or shorting, no
  pretrained models and no LLM.
- **Owner and auditor files untouched:** no edits to `config/*.yaml`, the gates in `lab/search/report.py` or
  `lab/validation/`.

## 9. Build plan and validate-window log

**Build.** All lab/ code has 100% branch coverage, passes the deep profile and is ruff clean before any number
counts (hard rule 11, TESTING.md section 7).
- `lab/data/positioning.py` (`data-engineer`): funding and OI with the alignment rule above. Tests:
  tamper-the-future (no print with τ ≥ close changes a feature at that close) and the test-window guard.
- `lab/models/dips.py`: events, dip features and labels. Tests: tamper-the-future, labels checked by hand on
  `make_bars` paths, and the test-window guard.
- `lab/runner/reference.py`: a `scheduled` rule that holds a target weight taken from a column known at close
  t and filled at t+1, added as an entry in the contract suite. The event-level purge is tested by checking
  that no training event's span reaches a test span plus the embargo.
- Study scripts and `RESULTS.md` go in `research/dip-timing/`.

| # | Date | By | What was looked at |
|---|---|---|---|
| 0 | 2026-11-20 | quant-researcher | Counted dip triggers per coin in validate for the 9 (X, N) cells (the counting script read validate closes). Counts only: no returns or outcomes. |
| 1 | reserved | | The single evaluation in section 6, after the train results and the frozen config hash are committed |

# Dip timing ("option C"): results

> **SCOUTING ONLY.** Every profit number below comes from the reference backtester (`lab/runner/reference.py`),
> not from NautilusTrader (AGENTS.md hard rule 3; the Nautilus runner is on hold). Nothing here goes into
> `reports/<strategy>/`, and nothing here is an audit.

Run 2026-11-20 by `ml-researcher` (with `quant-researcher` duties for the entry rules), exactly as pre-registered in
[PLAN.md](PLAN.md). Data snapshot `1746a21b75683e76` (its bars are bit-identical to `b08377c310126e3f`, the
snapshot PLAN.md names: same bars content hash; it adds the Binance futures positioning tables). Code at HEAD
`62b2f11` plus uncommitted changes (nothing was committed, as the task required); frozen config hash
`0cda419180466c5b2f677bca923c6877c7ac4bedcb20dcdc88e8020c1e904c3a` (`results/dip-timing/FROZEN.json`).
**The test window was never read:** the train run read closes up to 2023-01-01 00:00 UTC, the validate look up to
2024-07-01 00:00 UTC, and every load goes through `dips.load_study_bars` / `dips.load_study_positioning`, which
raise `HoldoutWindowError` for anything later (tested: `test_the_guard_fires_when_data_reach_the_test_window`), with
a second check on every frame in the scripts.

## Verdict

**NO EDGE.** The pre-registered rule says NO EDGE when criterion 1 or criterion 3 fails. Criterion 1 fails for all
nine primary variants: every Holm-adjusted p is 1.0000, and the smallest raw p is 0.3049 (V06). Criterion 3 fails
for eight of the nine. No variant passed criteria 1-3. "Best" therefore fell back to the highest train mean r_e
among V01-V10, which is V06 (T5 with LightGBM). V06 is mostly buying at once (T1) in disguise: its model is close to
constant (out-of-sample AUC 0.4965 ± 0.0135). Its result differs from T1's on at least one path in only 24 of 80
events, its per-event Δ has a standard deviation of 1.19 points (5.45 to 13.77 for T2-T5 logistic), and 2.5% of
its entries were forced. V06 also fails criterion 2 (1 of 5 paths), criterion 5 (Δ > 0 in 1 of 9 cells),
criterion 6 (Sharpe above T1 on 1 of 5 paths; PBO 0.306) and criterion 7 (validate mean Δ −4.43%). Its DSR is
0.367 with the effective trial count (5.52) and 0.144 with the raw count (40); 0.141 and 0.127 when the 2 or 12
evaluated but uncounted configurations are counted too (audit F5). Nothing goes to a Nautilus build. The audit
([AUDIT.md](AUDIT.md)) found the study's integrity sound and confirmed this verdict; its corrections are in
"Audit fixes" below.

What this means for the owner's two questions:

1. **Is this dip worth buying, or is it a falling knife?** On our data we could not tell them apart in advance.
   - The dip-quality model ranked dips *worse* than chance out of sample. Its inputs were how fast the price fell,
     how far it sits from its 100-day average, and short against long volatility. Its AUC was 0.42 on train CPCV.
     On the 8 validate dips it was 0.17. It skipped 6 dips, 5 of which went on to gain (+15.0% to +36.3%), and took
     2: one gained 1.85% and one lost 3.66%.
   - Volatility alone was a coin flip (AUC 0.52).
   - Adding funding rates and open interest did not help. The three positioning tests have Holm p 1.00, 0.63
     and 1.00.
   - Every filter that skipped dips lost 2.2 to 3.7 points per dip against simply buying all of them on train,
     and 17.7 to 21.0 points on validate.
2. **When should we buy?** Nothing tested beat buying at the next open after the dip signal (T1) by a margin
   distinguishable from zero. On train the closest was T5 with LightGBM, +0.06 points per dip above T1 (raw p
   0.30, Holm 1.00), and it is nearly T1. On validate T1 was the best of everything tested. This is "no evidence
   that waiting helps", not evidence that waiting hurts (see the shared-exit caveat below).
   - Every rule that waited had a lower average result per dip than T1 (point estimates; none is significant
     after Holm): buying in thirds lower down, waiting for an up-day, for a quiet day, or for a model's "bottom
     is in". The shortfall was 1.4 to 2.7 points on train (T2-T4 and T5 logistic) and 2.9 to 11.9 points on
     validate (T2-T5). T5 with LightGBM rarely waited, so it scored +0.06% on train and −4.43% on validate.
   - Waiting a random number of days did worse than T1 too: T1's +4.06% is above the 95th percentile (+3.04%) of
     100 random-day schedules.
   - On average each day of waiting cost about 0.4 points on train (+4.06% on day 0, about 0% by days 7-9) and
     about 1.5 points on validate (+17.7% on day 0, +4.3% on day 9). On train that is about what the coins'
     average daily rise (+0.21% BTC, +0.38% ETH) costs a later entry with the same exit (see Known failure
     modes).
   - No rule got meaningfully closer to the bottom. For the timing rules the average entry stayed 30.5% to 34.3%
     above the lowest low of the 31 days after the trigger (T1: 33.0%; the filters 34.3% to 35.6%). The ladder
     came closest (30.5%) because it bought its later thirds lower on the dips that kept falling. The price was a
     smaller position: 62.5% of dips were only partly filled, so it held less on the rebounds.
   - The "bottom is in" models had no skill (AUC 0.41 and 0.50). The best single raw score, the bounce off the
     lowest low, reached only 0.53.
3. **Description only (not a criterion): does buying dips beat cash, buy-and-hold and 50/50?**
   - *Train (2017-2022):* T1 made +4.06% per dip on average but lost on most dips (median −7.11%, 40.0%
     winners). With both coin sleeves together it lost 13.0% over six years (Sharpe 0.258, maximum drawdown
     −76.8%). On Sharpe it beats cash (0); on money it does not. Buy-and-hold made +7985.4% (Sharpe 1.242) and
     50/50 made +2216.4% (Sharpe 1.339). T1's Sharpe was below every one of 100 random-entry strategies with
     the same number of trades and the same hold (their 5th percentile is 0.389).
   - *Where T1's train mean comes from (audit F7):* 2017. Its 11 events average +27.64% per dip; the 69 events
     of 2018-2022 average +0.30%. Without the 3 best events (+159.7%, +111.8% and +79.7%; the best is the BTC
     dip of 2017-11) the mean is −0.34%. On Binance bars, which start in 2017-08, T1 loses 2.59% per dip. So
     "no edge" covers buying dips at all, not only the timing and filter rules.
   - *Validate (2023 to mid-2024, a bull market):* T1 did well: +17.66% per dip, 6 of 8 winners, sleeves +85.9%,
     Sharpe 1.765, maximum drawdown −16.8%. It still trailed buy-and-hold (Sharpe 1.917, +230.5%) and 50/50
     (Sharpe 1.879, +90.0%) on Sharpe.

## Audit fixes (2026-11-20, after [AUDIT.md](AUDIT.md))

The audit by `backtest-auditor` passed all 7 integrity checks and found **no bug in code**: nothing in `lab/`,
the study scripts or the frozen config needed fixing. So no variant was rerun and no trial was added. The count
stays at 40, and the 5 reserved amendments are still unused. The frozen config hash (`0cda4191…`), the frozen
files and the train outputs still match `FROZEN.json`, and **the verdict is unchanged: NO EDGE**. What changed
is wording in this file, plus one committable copy of the freeze record.

| Finding | What was wrong | Fixed here |
|---|---|---|
| F1 | "A round trip on USD 10,000 costs about 0.72%" counted gas as 1 bp. USD 0.10 on USD 10,000 is 0.1 bp. | About **0.70%**: 0.7005% in the engine at a flat price, 1.398% at 2x costs (Known failure modes) |
| F2 | "For V04 and V05 the interval excludes 0: they are worse than T1" is an unregistered two-sided reading with no correction for 9 tests | Point estimates below T1, **not significant after Holm**: lower-tail p 0.0200 and 0.0465, Holm 0.180 and 0.372 (Models and baselines) |
| F3 | "Buying at the next open after the dip signal (T1) was the best of everything tested". On train V06 was +0.06 points above T1. | "Nothing tested beat T1 by a margin distinguishable from zero; on validate T1 was the best" (Verdict, question 2) |
| F4 | Deviation 7 named only V11-V16 as extra output of the validate look | It also names the validate timing profile, the validate nulls and the random-entry benchmark |
| F5 | The two T1 reference runs and the 10 fixed-day schedules were evaluated but not counted | DSR with 42 and 52 trials added: 0.141 and 0.127, against 0.144 with 40 (Overfitting statistics; Trial count) |
| F6 | `/results/` is git-ignored, so `FROZEN.json` could not be committed | Byte-identical copy at `research/dip-timing/FROZEN.json`. The commit list is in Trial count and files, and **committing waits for the owner**. |

Corrections found while making these fixes (not in the audit; wording only, with numbers from the stored
outputs):

- The 80%-power range "1.5 to 6.7 points" left out V06's 0.33 points (Known failure modes, Small samples).
- "The observed Δs are on the wrong side of 0" is true for 8 of the 9 variants. V06's Δ is +0.06%, below its
  0.33% power threshold (Models and baselines).
- The logistic models' AUC was given as "0.41 to 0.44 on train CPCV" for all of them. That range holds only for
  V05 and V08. The positioning-pair models scored 0.39 to 0.52 and the volatility-only model 0.52 (Known
  failure modes, Unstable relationships).
- "The ladder came closest (30.5%) only because it bought smaller amounts" had the cause wrong. Buying less does
  not lower the average fill. Buying the later thirds lower on the dips that kept falling does, and the
  partly filled dips are the cost of that (Verdict, question 2).

Audit findings for the owner that are now reflected here, with no change to any number:
- F7: T1's train mean comes from 2017 (Verdict, question 3).
- F8: the timing result is "no evidence that waiting helps" (Verdict, question 2, and the shared-exit caveat).
- F9: power (Small samples).
- F10: LightGBM's defaults are too strict for event data. This is in Known failure modes and in TESTING.md
  section 4, under "Findings that are not bugs".

**How the corrected numbers were recomputed.** `uv run python research/dip-timing/final_checks.py` refuses to run
if the code, the config or the train outputs differ from `FROZEN.json`. It reads only the stored train outputs
and `config/costs.yaml`: no bars, no positioning data, nothing from validate or the test window. With the lab's
own functions it reproduces exactly:
- the study's bootstrap p values for all 9 primary variants, from the same seed and draws, with the lower tail
  read from those draws;
- DSR 0.1439 (raw count) and 0.3670 (effective count);
- the T1 concentration and the cost numbers above.

The auditor's `audit/a4_overfit.py` and `audit/a6_claims.py` were also re-run on the unchanged outputs. Both exit 0
with the numbers AUDIT.md reports (re-check notes appended there). The test window was not opened. There was
no new look at validate: `a6_claims.py` re-reads only look #1's stored outputs (row 1a below).

## Looks at the data (continues PLAN.md section 9; PLAN.md itself is not edited)

| # | Date (UTC) | By | What was looked at |
|---|---|---|---|
| 0b | 2026-11-20 ~03:05 | ml-researcher | Train closes only: event counts for the 9 (X, N) cells under two de-duplication readings, to fix the reading that reproduces PLAN.md's counts. Counts only. |
| 0c | 2026-11-20 ~03:23 | ml-researcher | Pre-flight on train data. Event timing (t0, span), positioning coverage and whether every CPCV split keeps training events, for the 9 cells, H = 20, the 10% stop and Binance bars. Then OI availability at each event's trigger and P_ref closes. No returns or outcomes. |
| 0d | 2026-11-20 03:26:44 | ml-researcher | **The train run** (`run_train.py`): all of V01-V40 on train. 40 trials logged. Before it, the pipeline was dry-run on synthetic bars only (`--synthetic`, scratch output, no real data). |
| 0e | 2026-11-20 ~03:27 | ml-researcher | Hand check of 5 train T1 events against the engine (max difference 6.7e-16). |
| **1** | **2026-11-20 03:28:34** | ml-researcher | **The single validate look** (`run_validate.py`, config frozen at 03:28:28 in `FROZEN.json`): models refit once on all train events, applied to the 8 validate events; V01-V16, baselines and nulls. It read bars and positioning up to 2024-07-01 00:00 UTC. The script now refuses to run again (`results/dip-timing/validate/STARTED`, `look.json`). Afterwards the stored outputs were split per coin for this file; nothing was rerun. |
| 1a | 2026-11-20, after look #1 | backtest-auditor; ml-researcher (finalization) | **Re-reads of look #1's stored outputs only** (`look.json`, `validate/events.parquet`), to check the validate numbers quoted here: by the audit (`audit/a6_claims.py`, [AUDIT.md](AUDIT.md) "Data accessed"), then the same script again after the audit fixes. No validate bar or positioning value was loaded, no outcome was computed anew, and nothing was refit or tuned. The audit's guard test also loaded bars capped at the validate cut and printed only index bounds and row counts. That was not re-run. |

## Deviations from PLAN.md

1. **Snapshot.** `1746a21b75683e76` instead of `b08377c310126e3f`: the data-engineer added the positioning
   tables in a new snapshot. Its bars content hash equals the old snapshot's, so the bars are bit-identical.
2. **Positioning module.** The data-engineer built `lab/data/external.py` (with `load_positioning`) instead of the
   planned `lab/data/positioning.py`, with the same alignment rules and tests.
3. **Open-interest snapshot time.** `oi_last` is the newest 5-minute value with `known_at = create_time + 5 min`
   strictly before the close, so `create_time <= close - 10 min`. PLAN.md says "at or before close − 5 min",
   which is 5 minutes later. The data-engineer found that `create_time` is the START of the 5-minute period in
   files from 2024-04-26 on (TESTING.md section 4), so PLAN.md's rule would use a value known exactly at the
   close. The house rule is `known_at < close`.
4. **Open-interest coverage: 23 events (15 BTC + 8 ETH), not 24.** `oi_chg_dip` needs the open interest at
   P_ref's close as well. For the ETH event that triggered on 2021-12-19, P_ref closed on 2021-12-01 00:00, before
   the first ETHUSDT open interest was known (00:05). Funding coverage is 37 events (18 + 19), as planned, and
   all 8 validate events are covered.
5. **No commit before the validate look.** PLAN.md wants "the train results and the frozen config hash
   committed". The task forbade commits, so `freeze.py` wrote `results/dip-timing/FROZEN.json` instead (frozen at
   2026-11-20T03:28:28Z). It holds the config hash, the SHA-256 of every frozen file (lab code, study scripts,
   PLAN.md, `config/costs.yaml`, `config/splits.yaml`) and of the train outputs. `run_validate.py` refuses to run
   if any of them differs. The train trial log recorded the same config hash, so nothing changed between the
   train run and the look. `/results/` is git-ignored, so `FROZEN.json` cannot be committed where it is. A
   byte-identical copy is now at `research/dip-timing/FROZEN.json` (added after the audit, F6), and it goes into
   git once the owner allows a commit.
6. **The look is logged here, not in PLAN.md** (the task forbids editing PLAN.md).
7. **More was reported from the single look than the minimum.** PLAN.md asks for V01-V10 and the baselines. The
   same single run also reports:
   - V11-V16, because all 8 validate events have positioning data;
   - the 10-schedule timing profile on validate (a full entry decided on a fixed day t0..t0+9, `by_offset_mean_r`
     in `look.json`; the "Mean r_e, validate" row of the timing-profile table), which PLAN.md does not list at all;
   - the nulls on validate (random entry day, and random skipping at V07-V10's shares) and the random-entry
     benchmark's Sharpe percentiles. PLAN.md section 5 lists these with the baselines, but section 6 does not say
     they are computed at the look.

   All of it is descriptive and came from the one run; nothing was tuned or rerun. (Added after the audit, F4.)

## Interpretations fixed before the real run

PLAN.md leaves these choices open. They are written in `study.py` (`INTERPRETATIONS`), are part of the frozen
config hash, and were fixed before any real-data outcome was computed.

- **De-duplication** runs over every trigger from the first loaded bar. Events before bar 100, or whose span
  leaves the window, are dropped but still block their 31-bar cool-off. This is the only reading that
  reproduces all 9 train counts in PLAN.md's table.
- **r_e** is the net return on a fresh USD 10,000 sleeve per event (cash before and after), after the costs of
  every fill. The strategy level instead compounds one sleeve per coin over the whole window.
- **Average fill price** is the mean of the fill opens, weighted by each tranche's weight step.
- **Stop against a T2 tranche:** if both trigger at the same close, the stop wins and the event is over.
- **Forced entries:** a T3-T5 rule that never fires buys at the open of t0+10. A signal on t0+9 itself is not
  counted as forced.
- **Thresholds:** theta is the share of positives in the split's training rows, and a model fires at
  `p >= theta - 1e-9`.
- **LightGBM inputs:** the 6 B features at d, the 3 Q features at t0 and the 15 lab features at d.
- **b_depth** is `ln(close/P_ref) / (ewma_vol_20 * sqrt(20))`; **b_bounce** is `ln(close / min low since t0)`.
- **funding_7d** is `funding_mean_7d`. The run checks that it is exactly 21 eight-hour prints wherever it is
  defined.
- **Positioning variants** (V11-V16) run their own 6-group CPCV over the covered events only.
- **V13/V14 use the logistic B model,** because LightGBM's `min_child_samples=200` cannot split on about 250 rows.
- **Delta of a model variant per event** is the mean of its 5 path deltas.
- **Bootstrap:** shifted (null-centred), resampling trigger months; the trigger month is that of the trigger day
  (ts0 − 1 day).
- **Nulls for V09-V10:** they must beat the 95th percentile of both the random-timing and the random-skip nulls.
  Random skipping drops round(mean number skipped over the paths) events.
- **"Best"** is chosen among V01-V10.
- **Theta fallback for V33/V34:** if the best variant has no threshold, they use the best model variant (here V06
  has one).
- **Deltas for V39/V40** are taken against T1 on the same definition. These T1 runs are reference computations,
  not trials.
- **V37/V38** find their events on the Binance bars themselves.
- **Embargo** is H + 1 calendar days.
- **`random_entry` null:** the same number of round trips per coin as T1 (37 / 43), each held 30 bars.

## Events and labels

- **D0 train events:** BTC 37 and ETH 43, 80 in all, from 46 trigger months. **Validate:** BTC 4 and ETH 4, from
  5 trigger months. Both match PLAN.md.
- Every cell of the (X, N) grid reproduces PLAN.md's train counts. The other event sets: H = 20 has 103 events
  (45 / 58), the 10% stop 80, Binance bars 68 (31 / 37; Binance starts 2017-08-18).
- **y_Q (T1 makes money after costs):** 40.0% of D0 train events (BTC 45.9%, ETH 34.9%); 6 of 8 validate events.
- **y_B (no low more than 5% below the close in the next 10 days):** 27.75% of D0 train day rows.
- **T1 median r_e on train:** BTC −2.58%, ETH −15.59%.

## T1-T5 comparison (train CPCV)

How to read the tables:
- **Mean r_e** is the net return per dip after costs; a skipped dip counts as 0.
- **Above the low** is the average fill price over the lowest low of t0..t0+30, minus 1.
- **MAE** is the worst low while holding, over the average fill price, minus 1.
- **Stopped, partly filled and forced** are shares of the dips that were entered.

#### T1-T5 and filters, train CPCV (D0, 80 events; model variants: mean over 5 paths)

| ID | Variant | Mean r_e | Median r_e | Δ vs T1 | 95% CI of Δ | Win rate | Above the low (mean / median) | MAE (mean / median) | Stopped | Skipped | Partly filled | Forced |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | T1 buy at once | +4.06% | -7.11% | +0.00% | +0.00% .. +0.00% | 40.0% | 33.0% / 20.5% | -15.1% / -15.8% | 41.2% | 0.0% | 0.0% | 0.0% |
| V02 | T2 ladder | +2.55% | -2.59% | -1.51% | -5.13% .. +1.66% | 43.8% | 30.5% / 17.9% | -14.3% / -13.9% | 40.0% | 0.0% | 62.5% | 0.0% |
| V03 | T3 up-day | +2.21% | -6.99% | -1.86% | -5.48% .. +1.50% | 40.0% | 34.3% / 24.3% | -14.3% / -13.9% | 36.2% | 0.0% | 0.0% | 8.8% |
| V04 | T4 narrow range | +2.69% | -6.49% | -1.37% | -2.67% .. -0.13% | 36.2% | 32.8% / 22.0% | -15.5% / -15.7% | 40.0% | 0.0% | 0.0% | 0.0% |
| V05 | T5 logistic | +1.40% | -4.08% | -2.67% | -5.77% .. -0.07% | 40.0% | 33.9% / 21.0% | -15.2% / -15.4% | 37.5% | 0.0% | 0.0% | 19.0% |
| V06 | T5 LightGBM | +4.12% | -6.84% | +0.06% | -0.19% .. +0.31% | 40.5% | 32.8% / 20.2% | -15.0% / -15.6% | 40.2% | 0.0% | 0.0% | 2.5% |
| V07 | vol-only filter + T1 | +1.89% | +0.00% | -2.17% | -8.07% .. +2.59% | 36.8% | 34.3% / 21.5% | -15.6% / -16.6% | 42.3% | 59.2% | 0.0% | 0.0% |
| V08 | Q filter + T1 | +1.13% | -1.19% | -2.93% | -9.31% .. +2.53% | 36.0% | 35.6% / 21.5% | -15.6% / -16.6% | 41.7% | 56.2% | 0.0% | 0.0% |
| V09 | Q + T5 LightGBM | +1.15% | -1.34% | -2.91% | -9.31% .. +2.60% | 36.6% | 35.5% / 21.5% | -15.4% / -16.0% | 41.1% | 56.2% | 0.0% | 4.0% |
| V10 | Q + T4 | +0.32% | -2.30% | -3.74% | -10.36% .. +1.96% | 31.4% | 35.6% / 22.1% | -16.1% / -16.5% | 41.1% | 56.2% | 0.0% | 0.0% |

#### Per coin, train (mean r_e / mean Δ vs T1)

| ID | BTC (37) | ETH (43) |
|---|---|---|
| V01 | +2.42% / +0.00% | +5.47% / +0.00% |
| V02 | +2.42% / -0.00% | +2.66% / -2.81% |
| V03 | -0.34% / -2.76% | +4.40% / -1.08% |
| V04 | +1.34% / -1.08% | +3.86% / -1.62% |
| V05 | -0.35% / -2.78% | +2.90% / -2.57% |
| V06 | +2.35% / -0.07% | +5.65% / +0.18% |
| V07 | +0.00% / -2.42% | +3.52% / -1.95% |
| V08 | +0.34% / -2.08% | +1.81% / -3.67% |
| V09 | +0.26% / -2.16% | +1.92% / -3.56% |
| V10 | -0.20% / -2.62% | +0.76% / -4.71% |

**Timing profile (descriptive, not a trial).** This is a full entry on a fixed day k after the trigger, with the
same exit, over all 80 train events. Choosing a day from this table would be a new, unregistered variant.

| Entry decided at | t0 | t0+1 | t0+2 | t0+3 | t0+4 | t0+5 | t0+6 | t0+7 | t0+8 | t0+9 |
|---|---|---|---|---|---|---|---|---|---|---|
| Mean r_e, train | +4.06% | +2.61% | +3.41% | +2.35% | +1.63% | +1.80% | +0.62% | −0.81% | −0.82% | +0.08% |
| Median r_e, train | −7.11% | −9.01% | −3.77% | −5.79% | −3.63% | −5.40% | −4.07% | −6.64% | −5.43% | −6.39% |
| Share winning, train | 40.0% | 33.8% | 41.2% | 42.5% | 40.0% | 43.8% | 45.0% | 40.0% | 40.0% | 38.8% |
| Above the low, train | 33.0% | 32.5% | 31.9% | 32.7% | 32.1% | 33.4% | 32.3% | 33.0% | 33.3% | 33.4% |
| Mean r_e, validate | +17.66% | +14.14% | +13.09% | +11.42% | +8.06% | +6.76% | +6.88% | +6.09% | +3.76% | +4.31% |

**Hindsight bounds (not trades; they use the future).** Over the 80 train events:
- best entry day per event: mean +11.67%;
- worst entry day per event: −8.59%;
- skipping every losing T1 dip: +13.79%.

Timing and selection would be worth a lot if they could be predicted; nothing tested predicts them.

## Models and baselines

#### Criteria 1-3, primary family (V02-V10 against T1)

| ID | Mean Δ | p (one-sided) | Holm p | C1 | 80%-power Δ | Paths Δ > 0 | C2 | Null 95th pct of mean r_e | C3 | Passes 1-3 |
|---|---|---|---|---|---|---|---|---|---|---|
| V02 | -1.51% | 0.8076 | 1.0000 | no | 3.82% | 0 of 5 | n/a | timing +3.04% | no | no |
| V03 | -1.86% | 0.8565 | 1.0000 | no | 3.85% | 0 of 5 | n/a | timing +3.04% | no | no |
| V04 | -1.37% | 0.9801 | 1.0000 | no | 1.52% | 0 of 5 | n/a | timing +3.04% | no | no |
| V05 | -2.67% | 0.9536 | 1.0000 | no | 3.28% | 0 of 5 | no | timing +3.04% | no | no |
| V06 | +0.06% | 0.3049 | 1.0000 | no | 0.33% | 1 of 5 | no | timing +3.04% | yes | no |
| V07 | -2.17% | 0.7827 | 1.0000 | no | 6.27% | 0 of 5 | no | skip +4.56% | no | no |
| V08 | -2.93% | 0.8253 | 1.0000 | no | 6.49% | 0 of 5 | no | skip +4.84% | no | no |
| V09 | -2.91% | 0.8234 | 1.0000 | no | 6.52% | 0 of 5 | no | both (reported) +3.27%, skip +4.84%, timing +3.04% | no | no |
| V10 | -3.74% | 0.8742 | 1.0000 | no | 6.69% | 0 of 5 | no | both (reported) +3.27%, skip +4.84%, timing +3.04% | no | no |

- The **random nulls** use 100 seeds on the D0 train events. Mean r_e (5th / 50th / 95th percentile):
  - random entry day: mean +1.39%, 5th percentile −0.34%, 95th percentile +3.04%;
  - random skipping at V07's share (47 of 80): mean +1.63%, 95th percentile +4.56%;
  - random skipping at V08-V10's share (45 of 80): mean +1.85%, 95th percentile +4.84%;
  - both at V08's share: mean +0.79%, 95th percentile +3.27%.
- **80%-power Δ** is 2.5 · sd(Δ) / √n, the smallest mean Δ this sample would detect 4 times in 5. Eight of the
  nine observed Δs are below 0, not merely too small; V06's +0.06% is below its own 0.33% threshold.
- V04 (95% CI −2.67% .. −0.13%) and V05 (−5.77% .. −0.07%) have point estimates below T1, but they are **not
  significantly worse after Holm**. Reading the two-sided interval was not registered and is not corrected for
  the 9 tests. The lower-tail p values from the same bootstrap draws are 0.0200 and 0.0465, and Holm over the 9
  variants gives 0.180 and 0.372 (`final_checks.py`; the auditor's own stream gives 0.20 and 0.39). (Corrected
  after the audit, F2.)

#### Forecast quality (out-of-sample AUC over the 15 CPCV splits; 0.5 = no skill)

| Model / score | Target | Mean AUC | SD | Splits above 0.5 |
|---|---|---|---|---|
| V05 T5 logistic | y_B (bottom in) | 0.4141 | 0.0670 | 2 of 15 |
| V06 T5 LightGBM | y_B (bottom in) | 0.4965 | 0.0135 | 0 of 15 |
| V07 vol-only filter + T1 | y_Q (dip worth buying) | 0.5199 | 0.0946 | 9 of 15 |
| V08 Q filter + T1 | y_Q (dip worth buying) | 0.4197 | 0.0490 | 1 of 15 |
| V11 Q + T1 (funding subset) | y_Q (dip worth buying) | 0.3889 | 0.1463 | 2 of 15 |
| V12 Q + funding + T1 | y_Q (dip worth buying) | 0.4431 | 0.1443 | 3 of 15 |
| V13 T5 logistic (funding subset) | y_B (bottom in) | 0.4575 | 0.0656 | 4 of 15 |
| V14 T5 logistic + funding | y_B (bottom in) | 0.4501 | 0.0821 | 6 of 15 |
| V15 Q + T1 (OI subset) | y_Q (dip worth buying) | 0.5203 | 0.3298 | 9 of 14 |
| V16 Q + funding + OI + T1 | y_Q (dip worth buying) | 0.4780 | 0.3375 | 8 of 14 |
| score `b_bounce` (no fitting) | y_B | 0.5285 | 0.0766 | 10 of 15 |
| score `b_days` (no fitting) | y_B | 0.5016 | 0.0548 | 8 of 15 |
| score `b_up_day` (no fitting) | y_B | 0.5027 | 0.0258 | 8 of 15 |
| score `neg_b_depth` (no fitting) | y_B | 0.4942 | 0.1080 | 8 of 15 |
| score `neg_b_range_ratio` (no fitting) | y_B | 0.5115 | 0.0508 | 10 of 15 |

For reference, the base rate (a constant forecast) scores AUC 0.5 by construction.

## Positioning (only over the period the data exist)

Funding covers 37 train events (from 2020-01), open interest 23 (BTC from 2020-09, ETH from 2021-12). On these
events T1 itself lost money: −1.28% per dip on the funding events and −3.21% on the OI events.

#### Positioning pairs (only events with positioning data; Δ = with minus without)

| ID | Variant | Events (BTC) | Mean r_e | T1 on the same events | Δ vs T1 | Q / B AUC | Strategy Sharpe, 5 paths |
|---|---|---|---|---|---|---|---|
| V11 | Q + T1 (funding subset) | 37 (18) | -1.07% | -1.28% | +0.21% | 0.389 | -0.179, -0.298, -0.066, 0.136, -0.029 |
| V12 | Q + funding + T1 | 37 (18) | -1.88% | -1.28% | -0.59% | 0.443 | -0.249, -0.393, -0.318, -0.120, -0.078 |
| V13 | T5 logistic (funding subset) | 37 (18) | -1.62% | -1.28% | -0.34% | 0.458 | -0.138, -0.180, -0.350, -0.257, -0.075 |
| V14 | T5 logistic + funding | 37 (18) | -1.16% | -1.28% | +0.12% | 0.450 | -0.067, -0.218, -0.222, -0.225, -0.096 |
| V15 | Q + T1 (OI subset) | 23 (15) | -1.78% | -3.21% | +1.42% | 0.520 | -0.440, 0.177, -0.292, -0.400, -0.123 |
| V16 | Q + funding + OI + T1 | 23 (15) | -1.88% | -3.21% | +1.32% | 0.478 | -0.081, -0.197, -0.465, -0.361, -0.123 |

| Pair | Events | Months | Mean Δ | 95% CI | p | Holm p | Adds value |
|---|---|---|---|---|---|---|---|
| V12 vs V11 | 37 | 20 | -0.80% | -2.42% .. +0.62% | 0.8507 | 1.0000 | no |
| V14 vs V13 | 37 | 20 | +0.46% | -0.67% .. +1.62% | 0.2102 | 0.6305 | no |
| V16 vs V15 | 23 | 16 | -0.10% | -1.32% .. +1.19% | 0.5545 | 1.0000 | no |

Per coin, as mean r_e / Δ vs T1:

| ID | BTC | ETH |
|---|---|---|
| V11 | +1.34% / +1.13% (18) | −3.36% / −0.66% (19) |
| V12 | −0.29% / −0.50% | −3.38% / −0.68% |
| V13 | −0.87% / −1.08% | −2.34% / +0.36% |
| V14 | −0.34% / −0.55% | −1.94% / +0.76% |
| V15 | +0.18% / −1.30% (15) | −5.46% / +6.52% (8) |
| V16 | −0.43% / −1.91% | −4.61% / +7.38% |

The +6.5 to +7.4 point ETH deltas come from 8 events and pass no test.

## Strategy level (both sleeves, USD 10,000 each, train window, SCOUTING)

#### Strategy level, both sleeves, train window (SCOUTING)

| ID | Sharpe, 5 paths | Total return, 5 paths | Max drawdown, 5 paths | Trades | Turnover |
|---|---|---|---|---|---|
| V01 | 0.258 (all) | -13.0% | -76.8% | 160 | 160.0 |
| V02 | 0.220 (all) | +6.2% | -51.9% | 207 | 110.5 |
| V03 | 0.190 (all) | -14.9% | -75.2% | 160 | 160.0 |
| V04 | 0.117 (all) | -43.8% | -83.3% | 160 | 160.0 |
| V05 | 0.044, 0.032, 0.154, 0.108, -0.130 | -54.8%, -47.0%, -37.8%, -44.7%, -70.9% | -74.9%, -78.7%, -82.6%, -75.6%, -86.7% | 160, 160, 160, 160, 160 | 160.0, 160.0, 160.0, 160.0, 160.0 |
| V06 | 0.258, 0.258, 0.258, 0.258, 0.341 | -13.0%, -13.0%, -13.0%, -13.0%, +16.9% | -76.8%, -76.8%, -76.8%, -76.8%, -71.7% | 160, 160, 160, 160, 160 | 160.0, 160.0, 160.0, 160.0, 160.0 |
| V07 | 0.068, 0.245, 0.191, 0.265, 0.243 | -29.3%, +6.4%, +6.1%, +12.1%, +5.8% | -76.6%, -64.5%, -52.4%, -63.9%, -64.7% | 72, 62, 62, 66, 64 | 72.0, 62.0, 62.0, 66.0, 64.0 |
| V08 | 0.388, 0.468, -0.337, 0.120, 0.026 | +55.4%, +80.8%, -67.1%, -13.7%, -33.2% | -55.6%, -54.7%, -72.4%, -77.4%, -82.3% | 66, 54, 76, 74, 80 | 66.0, 54.0, 76.0, 74.0, 80.0 |
| V09 | 0.388, 0.468, -0.337, 0.120, 0.096 | +55.4%, +80.8%, -67.1%, -13.7%, -19.5% | -55.6%, -54.7%, -72.4%, -77.4%, -80.9% | 66, 54, 76, 74, 80 | 66.0, 54.0, 76.0, 74.0, 80.0 |
| V10 | 0.245, 0.313, -0.446, 0.045, -0.208 | +16.8%, +33.8%, -73.2%, -26.4%, -57.4% | -61.5%, -62.7%, -76.9%, -78.6%, -87.5% | 66, 54, 76, 74, 80 | 66.0, 54.0, 76.0, 74.0, 80.0 |
| V11 | -0.179, -0.298, -0.066, 0.136, -0.029 | -46.3%, -34.6%, -32.4%, +5.4%, -8.6% | -56.3%, -52.8%, -57.0%, -25.2%, -26.8% | 40, 30, 32, 20, 18 | 40.0, 30.0, 32.0, 20.0, 18.0 |
| V12 | -0.249, -0.393, -0.318, -0.120, -0.078 | -54.6%, -40.1%, -57.9%, -35.7%, -10.2% | -60.0%, -55.4%, -62.6%, -57.0%, -26.3% | 44, 30, 36, 26, 16 | 44.0, 30.0, 36.0, 26.0, 16.0 |
| V13 | -0.138, -0.180, -0.350, -0.257, -0.075 | -49.6%, -54.7%, -68.4%, -63.3%, -45.1% | -62.1%, -65.9%, -71.9%, -68.9%, -61.3% | 74, 74, 74, 74, 74 | 74.0, 74.0, 74.0, 74.0, 74.0 |
| V14 | -0.067, -0.218, -0.222, -0.225, -0.096 | -43.9%, -60.8%, -57.9%, -52.3%, -42.0% | -60.4%, -67.4%, -65.4%, -70.2%, -63.6% | 74, 74, 74, 74, 74 | 74.0, 74.0, 74.0, 74.0, 74.0 |
| V15 | -0.440, 0.177, -0.292, -0.400, -0.123 | -33.2%, +8.8%, -14.2%, -33.2%, -21.0% | -40.9%, -26.5%, -20.7%, -38.7%, -46.7% | 18, 12, 6, 16, 24 | 18.0, 12.0, 6.0, 16.0, 24.0 |
| V16 | -0.081, -0.197, -0.465, -0.361, -0.123 | -16.1%, -20.9%, -22.4%, -28.2%, -21.0% | -43.3%, -46.2%, -25.8%, -33.8%, -46.7% | 22, 16, 8, 16, 24 | 22.0, 16.0, 8.0, 16.0, 24.0 |
| V17 | 0.716 (all) | +366.4% | -78.5% | 188 | 188.0 |
| V18 | 0.639 (all) | +237.8% | -81.3% | 196 | 196.0 |
| V19 | 0.437 (all) | +56.4% | -89.6% | 202 | 202.0 |
| V20 | 0.302 (all) | +19.9% | -77.9% | 138 | 138.0 |
| V21 | -0.024 (all) | -66.4% | -90.1% | 166 | 166.0 |
| V22 | 0.992 (all) | +581.9% | -58.6% | 94 | 94.0 |
| V23 | 0.458 (all) | +82.9% | -70.3% | 124 | 124.0 |
| V24 | 0.074 (all) | -31.6% | -75.4% | 128 | 128.0 |
| V25 | 0.342, 0.219, 0.240, 0.221, 0.121 | +8.9%, -31.6%, -24.7%, -19.9%, -41.6% | -83.7%, -86.2%, -88.1%, -81.8%, -81.1% | 188, 188, 188, 188, 188 | 188.0, 188.0, 188.0, 188.0, 188.0 |
| V26 | 0.166, 0.089, 0.195, 0.364, 0.219 | -31.6%, -47.8%, -20.0%, +24.9%, -16.3% | -87.1%, -85.0%, -88.1%, -81.8%, -84.1% | 196, 196, 196, 196, 196 | 196.0, 196.0, 196.0, 196.0, 196.0 |
| V27 | -0.035, 0.091, 0.387, 0.117, 0.094 | -60.0%, -44.6%, +41.6%, -40.1%, -41.7% | -92.4%, -87.0%, -84.7%, -90.9%, -89.3% | 202, 202, 202, 202, 202 | 202.0, 202.0, 202.0, 202.0, 202.0 |
| V28 | 0.302 (all) | +19.9% | -77.9% | 138 | 138.0 |
| V29 | 0.007, -0.024, -0.072, 0.020, -0.393 | -62.0%, -66.4%, -71.1%, -60.5%, -86.1% | -89.8%, -90.1%, -91.5%, -89.4%, -93.8% | 166, 166, 166, 166, 166 | 166.0, 166.0, 166.0, 166.0, 166.0 |
| V30 | 0.992 (all) | +581.9% | -58.6% | 94 | 94.0 |
| V31 | 0.458 (all) | +82.9% | -70.3% | 124 | 124.0 |
| V32 | 0.074 (all) | -31.6% | -75.4% | 128 | 128.0 |
| V33 | -0.175 (all) | -60.3% | -82.4% | 160 | 160.0 |
| V34 | 0.258 (all) | -13.0% | -76.8% | 160 | 160.0 |
| V35 | 0.167, 0.167, 0.167, 0.167, 0.245 | -36.0%, -36.0%, -36.0%, -36.0%, -15.1% | -80.8%, -80.8%, -80.8%, -80.8%, -76.8% | 160, 160, 160, 160, 160 | 160.0, 160.0, 160.0, 160.0, 160.0 |
| V36 | 0.167 (all) | -36.0% | -80.8% | 160 | 160.0 |
| V37 | -0.387 (all) | -82.7% | -88.9% | 136 | 136.0 |
| V38 | -0.387 (all) | -82.7% | -88.9% | 136 | 136.0 |
| V39 | 0.183, 0.143, 0.001, 0.128, 0.157 | -6.1%, -20.3%, -49.0%, -19.0%, -12.5% | -68.6%, -71.9%, -79.4%, -66.5%, -69.3% | 206, 206, 206, 206, 206 | 206.0, 206.0, 206.0, 206.0, 206.0 |
| V40 | 0.474, 0.474, 0.474, 0.474, 0.639 | +93.6%, +93.6%, +93.6%, +93.6%, +224.0% | -75.1%, -75.1%, -75.1%, -75.1%, -62.9% | 160, 160, 160, 160, 160 | 160.0, 160.0, 160.0, 160.0, 160.0 |

Benchmarks, train window: buy-and-hold Sharpe 1.242, total return +7985.4%, max drawdown -92.8%; 50/50 every 30 days Sharpe 1.339, total return +2216.4%, max drawdown -68.0%, 146 trades; random entry (same trips and hold, 100 seeds) Sharpe 5/50/95th pct 0.389 / 0.902 / 1.311, total return +28.5% / +810.3% / +6450.4%; T1's Sharpe beats 0% of the random-entry seeds.

## Sensitivity (V17-V40)

#### Sensitivity (V17-V40; V25-V32 and V33-V40 are V06 = T5 LightGBM)

| ID | Event set | Events | Mean r_e | Δ vs its reference | p | Forced | B AUC |
|---|---|---|---|---|---|---|---|
| V17 | X0.10_N10 | 94 | +6.92% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V18 | X0.10_N20 | 98 | +6.71% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V19 | X0.10_N30 | 101 | +5.66% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V20 | X0.15_N10 | 69 | +3.65% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V21 | X0.15_N30 | 83 | +1.23% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V22 | X0.20_N10 | 47 | +5.27% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V23 | X0.20_N20 | 62 | +4.28% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V24 | X0.20_N30 | 64 | +2.67% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V25 | X0.10_N10 | 94 | +2.98% | -3.94% vs V17 | 0.9925 | 31.5% | 0.5234 |
| V26 | X0.10_N20 | 98 | +3.36% | -3.35% vs V18 | 0.9725 | 28.0% | 0.5176 |
| V27 | X0.10_N30 | 101 | +2.68% | -2.99% vs V19 | 0.9489 | 30.9% | 0.5585 |
| V28 | X0.15_N10 | 69 | +3.65% | +0.00% vs V20 | 1.0000 | 0.0% | 0.5000 |
| V29 | X0.15_N30 | 83 | +0.66% | -0.56% vs V21 | 0.9444 | 8.0% | 0.4959 |
| V30 | X0.20_N10 | 47 | +5.27% | +0.00% vs V22 | 1.0000 | 0.0% | 0.5000 |
| V31 | X0.20_N20 | 62 | +4.28% | +0.00% vs V23 | 1.0000 | 0.0% | 0.5000 |
| V32 | X0.20_N30 | 64 | +2.67% | +0.00% vs V24 | 1.0000 | 0.0% | 0.5000 |
| V33 | D0 | 80 | +0.08% | -3.98% vs T1 (same set) | 0.9304 | 100.0% | 0.4965 |
| V34 | D0 | 80 | +4.06% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | 0.4965 |
| V35 | D0_costs2x | 80 | +3.39% | +0.06% vs V36 | 0.3049 | 2.5% | 0.4965 |
| V36 | D0_costs2x | 80 | +3.33% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V37 | D0_binance | 68 | -2.59% | +0.00% vs V38 | 1.0000 | 0.0% | 0.5000 |
| V38 | D0_binance | 68 | -2.59% | +0.00% vs T1 (same set) | 1.0000 | 0.0% | n/a |
| V39 | D0_H20 | 103 | +1.73% | -0.78% vs T1 H=20 (+2.50%) | 0.7174 | 34.6% | 0.6196 |
| V40 | D0_stop10 | 80 | +5.14% | +0.09% vs T1 stop 10% (+5.05%) | 0.1867 | 2.5% | 0.4965 |

Cells (V17-V24) are T1 on the other definitions; their spread is wide: mean r_e +1.23% to +6.92% and Sharpe
−0.024 to 0.992. These are sensitivity runs, not candidates. Picking a cell after seeing them would be a new
trial.

## Overfitting statistics (every logged variant counts: 40)

- **PBO** (`stats.pbo`, 10 blocks, all 40 variants): 0.3175, 0.3294, 0.2897, 0.3214 and 0.2738 on the 5 paths,
  mean **0.306**, above the 0.25 limit.
- **Effective trials** (`stats.effective_trials` over the median-path series): 5.52.
- **DSR of the best (V06) median-path series:** per-period Sharpe 0.01352 (0.258 annualised). The trial-Sharpe
  variance is 0.000278.
  - With the effective count: expected maximum Sharpe 0.02086, **DSR 0.367**.
  - With the raw count of 40: expected maximum Sharpe 0.03649, **DSR 0.144**.
  - Both are far below 0.95.
  - Counting the configurations that were evaluated but not logged as trials (audit F5) lowers it further: 42
    (the two T1 reference runs for V39/V40) gives expected maximum Sharpe 0.03681 and DSR 0.141; 52 (also the 10
    fixed-day timing schedules) gives 0.03819 and DSR 0.127. Only the count changes: those 12 have no stored
    daily series, so the trial-Sharpe variance is the 40 logged trials'. No verdict moves.

## Criteria for the best variant (V06)

| Criterion | Value | Pass |
|---|---|---|
| 1. Holm p < 0.05 | 1.0000 (raw 0.3049) | no |
| 2. Δ > 0 on at least 4 of 5 paths | 1 of 5 | no |
| 3. Beats random timing (95th pct +3.04%) | mean r_e +4.12% | yes (because T1 does: +4.06%) |
| 4. Δ > 0 at 2x costs (V35 vs V36) | +0.06% | yes (trivially, it is nearly T1) |
| 5. Δ > 0 in at least 6 of 9 cells | 1 of 9: D0 +0.06%; X10/N10 −3.94%, X10/N20 −3.35%, X10/N30 −2.99%, X15/N30 −0.56%; X15/N10 and all X20 cells 0.00% | no |
| 6. Sharpe above T1 on at least 4 of 5 paths, and PBO <= 0.25 | 1 of 5; PBO 0.306 | no |
| 7. Validate mean Δ >= 0 | −4.43% | no |
| DSR (effective) >= 0.95 | 0.367 | no |

## Validate look (single, logged above)

#### Validate look (8 events: BTC 4, ETH 4)

| ID | Variant | Mean r_e | Median | Δ vs T1 | BTC r / Δ | ETH r / Δ | Above the low | MAE | Skipped | Forced | Q / B AUC | Sharpe | Total return | Max DD | Trades |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | T1 buy at once | +17.66% | +21.38% | +0.00% | +20.87% / +0.00% | +14.44% / +0.00% | 6.8% | -5.7% | 0.0% | 0.0% | n/a | 1.765 | +85.9% | -16.8% | 16 |
| V02 | T2 ladder | +5.80% | +7.20% | -11.86% | +7.03% / -13.85% | +4.57% / -9.87% | 6.8% | -5.7% | 0.0% | 0.0% | n/a | 1.387 | +24.7% | -9.5% | 16 |
| V03 | T3 up-day | +12.20% | +14.83% | -5.46% | +14.53% / -6.35% | +9.87% / -4.58% | 12.4% | -7.2% | 0.0% | 0.0% | n/a | 1.341 | +51.6% | -19.5% | 16 |
| V04 | T4 narrow range | +9.77% | +10.55% | -7.88% | +13.19% / -7.68% | +6.35% / -8.09% | 14.9% | -6.9% | 0.0% | 0.0% | n/a | 1.148 | +40.9% | -17.0% | 16 |
| V05 | T5 logistic | +14.71% | +20.56% | -2.94% | +17.29% / -3.59% | +12.14% / -2.30% | 10.4% | -8.0% | 0.0% | 12.5% | 0.418 | 1.532 | +63.8% | -16.8% | 16 |
| V06 | T5 LightGBM | +13.23% | +21.38% | -4.43% | +17.42% / -3.45% | +9.04% / -5.40% | 11.9% | -9.0% | 0.0% | 37.5% | 0.762 | 1.425 | +55.7% | -18.9% | 16 |
| V07 | vol-only filter + T1 | +0.00% | +0.00% | -17.66% | +0.00% / -20.87% | +0.00% / -14.44% | n/a | n/a | 100.0% | 0.0% | 0.083 | 0.000 | +0.0% | +0.0% | 0 |
| V08 | Q filter + T1 | -0.23% | +0.00% | -17.88% | +0.46% / -20.41% | -0.91% / -15.36% | 14.1% | -11.6% | 75.0% | 0.0% | 0.167 | 0.042 | -0.9% | -16.8% | 4 |
| V09 | Q + T5 LightGBM | -3.36% | +0.00% | -21.02% | -2.72% / -23.59% | -4.01% / -18.46% | 29.5% | -22.2% | 75.0% | 100.0% | 0.167 | -0.774 | -13.5% | -16.6% | 4 |
| V10 | Q + T4 | -2.07% | +0.00% | -19.73% | -0.93% / -21.81% | -3.22% / -17.66% | 23.7% | -18.1% | 75.0% | 0.0% | 0.167 | -0.349 | -8.3% | -16.8% | 4 |
| V11 | Q + T1 (funding subset) | +7.78% | +0.00% | -9.88% | +9.54% / -11.34% | +6.02% / -8.42% | 9.3% | -8.0% | 50.0% | 0.0% | 0.333 | 0.948 | +30.9% | -16.8% | 8 |
| V12 | Q + funding + T1 | -0.46% | +0.00% | -18.11% | +0.00% / -20.87% | -0.91% / -15.36% | 24.5% | -19.7% | 87.5% | 0.0% | 0.500 | -0.086 | -1.8% | -10.3% | 2 |
| V13 | T5 logistic (funding subset) | +15.38% | +21.38% | -2.28% | +17.69% / -3.18% | +13.06% / -1.38% | 9.3% | -7.6% | 0.0% | 12.5% | 0.652 | 1.603 | +69.1% | -17.1% | 16 |
| V14 | T5 logistic + funding | +14.22% | +21.38% | -3.43% | +17.69% / -3.18% | +10.75% / -3.69% | 10.8% | -8.4% | 0.0% | 25.0% | 0.677 | 1.523 | +61.2% | -16.6% | 16 |
| V15 | Q + T1 (OI subset) | -0.23% | +0.00% | -17.88% | +0.46% / -20.41% | -0.91% / -15.36% | 14.1% | -11.6% | 75.0% | 0.0% | 0.167 | 0.042 | -0.9% | -16.8% | 4 |
| V16 | Q + funding + OI + T1 | -0.23% | +0.00% | -17.88% | +0.46% / -20.41% | -0.91% / -15.36% | 14.1% | -11.6% | 75.0% | 0.0% | 0.250 | 0.042 | -0.9% | -16.8% | 4 |

- **Benchmarks on validate:** buy-and-hold Sharpe 1.917, +230.5%, maximum drawdown −22.7%; 50/50 Sharpe 1.879,
  +90.0%, maximum drawdown −12.4%; random entry Sharpe 5th / 50th / 95th percentile −0.166 / 0.763 / 2.006.
- **Nulls on validate:** random entry day: mean +8.63%, 5th percentile +5.15%, 95th percentile +12.75%; T1
  (+17.66%) is above it. Random skipping of 6 of 8 dips (V08's share): mean +4.37%, 95th percentile +8.35%.
- **The 8 validate dips** (trigger close; T1 r_e; funding_7d; oi_chg_dip):

  | Coin | Trigger close | T1 r_e | funding_7d | oi_chg_dip |
  |---|---|---|---|---|
  | BTC | 2023-03-10 | +36.29% | 0.000042 | −0.1152 |
  | ETH | 2023-03-10 | +27.75% | 0.000049 | −0.0641 |
  | BTC | 2024-01-23 | +30.33% | 0.000100 | +0.0201 |
  | ETH | 2024-01-26 | +33.95% | 0.000100 | −0.0075 |
  | BTC | 2024-03-20 | +1.85% | 0.000276 | −0.0293 |
  | ETH | 2024-03-20 | −3.66% | 0.000307 | +0.0337 |
  | ETH | 2024-04-20 | −0.27% | 0.000070 | −0.2913 |
  | BTC | 2024-05-02 | +15.01% | 0.000055 | −0.1641 |

- **Fitted thresholds** (all 80 train events): theta_Q 0.40, theta_B 0.2775.
  - The Q model's p ranged from 0.382 to 0.433 on the 8 dips. It took only the 2024-03-20 pair, its two highest
    p values: the BTC dip that made +1.85% and the ETH dip that lost −3.66%.
  - The volatility-only model's p ranged from 0.337 to 0.384, all below 0.40, so it took nothing.
- **Positioning fits:** V12 (37 events) theta_Q 0.351; V16 (23 events) theta_Q 0.304; V13/V14 theta_B 0.2595.

## Known failure modes and caveats

- **The shared exit penalises waiting.** The exit is anchored at the open of t0+31 for every rule, so a later
  entry holds fewer days. Over train the average daily simple return was +0.21% (BTC) and +0.38% (ETH), which is
  of the same order as the roughly 0.4 points per day of waiting seen in the timing profile. So the timing rules
  showed no skill beyond what time in the market explains. The random-timing null carries the same handicap,
  which is why criterion 3 is the fair timing test. This is the design PLAN.md fixed, and it answers the owner's
  question as asked (same exit).
- **Small samples.** 80 train events in 46 months and 8 validate events in 5 months. BTC and ETH dips often
  coincide, and the bootstrap resamples months to respect that. 80% power needs a mean Δ of 1.5 to 6.7 points
  per dip for T2-T5 logistic and the filters, and 0.33 points for V06, which is nearly T1. So "no edge" means no
  large edge was found; it does not show that a small one is absent (audit F9).
- **Unstable relationships.** The fitted Q and B logistic models of the primary family scored AUC below 0.5 out
  of sample: 0.41 (V05, B) and 0.42 (V08, Q) on train CPCV, and the Q model 0.17 on validate. The models of the
  positioning pairs (V11-V16, with and without positioning) scored 0.39 to 0.52, and the volatility-only model
  0.52. Whatever the models fit on one period reversed in the next (2017-18 bubble, 2020, 2022 bear). (Range
  corrected after the audit: it said "0.41 to 0.44" for all logistic models.)
- **The LightGBM defaults are too strict for event data.** `train.make_model`'s `min_child_samples=200` lets at
  most about one split happen on 450-500 day rows, so T5 with LightGBM was close to constant (AUC 0.4965 ±
  0.0135; it differed from T1 in 24 of 80 events). This is a property of the lab defaults, logged in TESTING.md section 4; changing it would need
  a new pre-registration.
- **Positioning history is short.** Funding starts 2020-01 and open interest 2020-09 (BTC) / 2021-12 (ETH). The
  covered subsets are 37 and 23 events, and on them T1 itself lost money.
- **Data source sensitivity.** On Binance bars T1 lost −2.59% per dip (68 events, Sharpe −0.387) against +4.06%
  on Kraken (80 events). Binance's series starts in 2017-08, so the event set differs.
- **Costs** are the pessimistic placeholders in `config/costs.yaml`: a round trip on USD 10,000 costs about
  **0.70%** (5 bps pool fee + 30 bps slippage + USD 0.10 gas, which is 0.1 bp, per leg; the engine gives 0.7005% at
  a flat price because the exit leg is slightly smaller; 1.398% at 2x costs). It said "about 0.72%", counting gas
  as 1 bp (audit F1). At 2x costs, T1 made +3.33% per dip.
- **Baselines not run.** `statsforecast` models and a zero-shot pretrained model (Chronos-2, TimesFM) were not
  run: PLAN.md rules out pretrained models, no new dependency was allowed, and the targets are event
  classifications, for which the base rate, the volatility-only model and the fixed scores above are the
  baselines.
- **The test window is untouched** for this study, so it is still available for any future strategy built from
  it.

## Trial count and files

- **40 variants logged (V01-V40), 40 with status ok, 0 failed, 0 amendments (5 reserved, none used).**
- Not trials: two T1 reference runs for the V39/V40 deltas, the nulls (100 seeds each), the hindsight bounds and
  the timing profile (10 fixed-day entry schedules, t0..t0+9). The two reference runs and the 10 schedules are
  configurations that were evaluated, so a stricter count is 42 or 52; it moves the raw DSR from 0.144 to 0.141 or
  0.127 (Overfitting statistics; audit F5). Future studies should log such runs as trials.
- Pipeline dry runs used synthetic bars only and are not trials.
- Logs and outputs:
  - `research/dip-timing/trials.csv` and `results/dip-timing/train/trials.parquet` (plus `trials.jsonl`, appended
    as each trial finished): one row per variant with ID, definition, rule, model, features, window, snapshot,
    commit, config hash, seed, status and metrics.
  - `results/dip-timing/train/summary.json`: every train number.
  - `series.parquet`: daily strategy returns, every variant and path.
  - `events_d0.parquet`: per-event results.
  - `results/dip-timing/FROZEN.json`, and a byte-identical copy in `research/dip-timing/FROZEN.json` (SHA-256
    `2a69b932…`), because `/results/` is git-ignored and the copy is what can be committed (audit F6).
  - `results/dip-timing/validate/look.json` and `events.parquet`, plus `research/dip-timing/validate.csv`.
- **Code:**
  - `lab/models/dips.py` (events, features, labels, entry plans, stops, the event purge, the bootstrap, Holm and
    the test-window guard; `tests/test_dips.py`, 82 tests);
  - `lab/runner/reference.py` `scheduled` (contract entry `ref_scheduled_ladder` and rule tests);
  - `research/dip-timing/study.py`, `run_train.py`, `freeze.py`, `run_validate.py`;
  - `research/dip-timing/final_checks.py` (after the audit: recomputes the corrected numbers from the stored
    train outputs; not frozen, not a trial);
  - the audit: `research/dip-timing/AUDIT.md` and `research/dip-timing/audit/`.
- **Not committed yet** (the task forbade commits; audit F6). The code behind every number exists as uncommitted
  files identified by the SHA-256 values in `FROZEN.json`. Only `research/` files can go into git as they are:
  `/results/` and `*.parquet` are git-ignored, so `trials.csv`, `validate.csv` and the `FROZEN.json` copy are the
  committable record. Committing needs the owner's go-ahead.
- **Checks on the code** (before the real run): full tier 1304 passed (12 slow), 100% branch coverage of `lab/`
  (3473 statements, 1016 branches), deep profile 1292 passed, ruff clean.
- **Checks after the audit fixes** (2026-11-20 04:11-04:14 UTC, same code; `-p no:cacheprovider -n 4`, dashboard
  tests on their own):
  - quick tier: 1292 passed in 25 s;
  - full tier with coverage: 1304 passed in 37 s, 100% branch coverage of `lab/` (3473 statements, 1016
    branches, 0 missed);
  - deep profile: 1292 passed in 126 s;
  - slow tests: 12 passed;
  - `tests/test_dashboard.py`: 86 passed;
  - `uv run ruff check`: all checks passed, `final_checks.py` and `audit/` included.
- **Reproduce the train numbers:** move `results/dip-timing/train` aside, then run
  `uv run python research/dip-timing/run_train.py` (it refuses to overwrite a trial log). The validate look is
  never repeated.
- **MLflow:** nothing was registered. The lab has no MLflow logging yet (PLAN.md: added once it exists), and no
  model is fit to ship.

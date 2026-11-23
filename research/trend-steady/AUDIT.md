# trend-steady: audit of run 0 (SCOUTING)

`backtest-auditor`, 2026-11-23. This is an independent check of run 0 (the train window only) and of the lead's
RESULTS.md and RISK.md. It was done lean, at the owner's request: one auditor, no sub-agents, no long reruns. I did
not change any code, PLAN.md, `config/` or any run output. All scratch work is in the session scratchpad under
`trendrun/audit/`.

> Every number here is SCOUTING. It comes from the lab's reference portfolio engine, uses the placeholder costs in
> `config/costs.yaml`, and treats exchange candles as stand-ins for Base prices. Nothing here is a NautilusTrader
> result, and nothing here makes anything ready for paper.

## Result

**PASS for the run and its verdict.** Run 0 followed the protocol. Every decisive number I rebuilt matches the
record, and the verdict follows mechanically from the plan's rules: **NO EDGE**, with the stop-loss variant overall
also **NO EDGE**. There is no validate look, and the test window was never touched.

**The write-up is not final yet.** RESULTS.md has one wrong number, caused by a bug in a description's code, plus
four misstatements (B1-B5 below). They must be corrected before RESULTS.md counts as final. **None of them changes
the verdict, a gate, or any criterion.**

**The strategy:** not ready for risk review. It is NO EDGE, it fails G1, G3, G4, G6 and G8-excess, and the plan stops
here. The study never runs the final test window (G9), so that window is still unused for trend-steady.

## What I checked

### 1. Protocol

| Check | Finding | Evidence |
|---|---|---|
| Tiers passed on the run's commit | PASS | `check_587acfa/`: the full tier with coverage gave 2088 passed, 100% branch coverage (5806 statements, 1698 branches) in 2006.6 s, exit 0, from 02:29:48 to 03:03:15 UTC. The deep profile gave 2074 passed in 625.5 s, exit 0, ending 03:13:42. Ruff: "All checks passed!", exit 0. Dashboard: 86 passed, exit 0. `status_before.txt` and `status_after.txt` are both empty (clean tree). Run 0 started at 03:14:12, after all four. The logs do not echo the commands they ran, so the flags (`-n 3` and so on) rest on RESULTS.md's word. The counts and exits match what it says |
| Clean tree, right commit | PASS | The start record has `git.dirty: false`, `changes: []`, commit `587acfa`. The RUNLOG line says the same. Every study's `context` has commit `587acfa`, dirty false |
| A1, A0 and the owner's decision committed before run 0 | PASS | All three are in `587acfa` (02:29:37 UTC), and the RUNLOG start is 03:14:12. The start record's `prior_amendments` holds the A1 line (N = 200) and the A0 line, which names `reports/director/2026-11-23-owner-answer-trend-a0-power.md`. The A0 and A1 output files hash to the values the amendments quote (`7846f1ae…`, `d2919193…`). `controls.json` says what A0 says: 0 false positives, power 0 of 20, 49 of 1000 on the volatility check. The code did not change between `783ed2e` (where A0 and A1 ran) and `587acfa`: only PLAN.md, README, TESTING.md, one test file and the owner record differ |
| No bar after 2023-01-01 00:00 UTC | PASS | The code path is `run_train.load_panels` → `study.load_study_panel(source, TRAIN_LAST_CLOSE = 2023-01-01)` → `load_panel(last_close=…)`, which asks the catalog for `end = last_close`. It then re-asserts `panel.index.max() <= last_close`. The recorded panels are Kraken, 2190 rows from 2017-01-02 to 2023-01-01, hash `355aabe2…`, and Binance, 1963 rows from 2017-08-18 to 2023-01-01, hash `2c1a4257…`. Both hashes are section 3's. My own train-only load reproduced Kraken's hash |
| Snapshot, branch and budget recorded before any bar | PASS | Snapshot `1746a21b75683e76` with bars hash `08f5ca2c…`. Branch R. The limits read as 0.20 / 0.60, budget 0.35, `risk_levels.yaml` SHA-256 `d3f58253…` (the hash quoted in the header). The projection was 4.62 CPU-minutes against a 60-minute budget, and the run took 246 s |
| No validate look | PASS | There is no `results/trend-steady/FROZEN.json`, no `validate/` folder and no `research/trend-steady/FROZEN.json`. The RUNLOG has exactly one line (run 0, `run_train.py`). `look_earned` is false |
| Every trial logged and counted | PASS | 12 studies × 200 trials, all COMPLETE, numbered 0-199. Loading each study's journal gives 2400 trial return columns. `trials.parquet` and `trials.csv` both have 2400 rows and are identical (study, number, Sharpe), with 0 failures. The seeds are the plan's: 0, 1000-4000 and 5000 for seed A; 1, 1001-4001 and 5001 for seed B. `evaluations.parquet` equals `evaluations.csv` (4650 rows, 78 counted). The strict count is 2400 + 78 + 1 (K4) = 2479, which is the plan's N_raw + 49 + 30 row by row |
| Nothing hashed changed since run 0 | PASS | The config hash recomputed on today's HEAD is `eed7f8b8…`, equal to run 0's. All 39 per-file hashes are equal too |

### 2. The verdict follows mechanically

- **Section 12.** E1 fails (rank p 0.0865, not < 0.05), so the verdict is **NO EDGE**. P holds (76 switches), so no
  LOW POWER suffix applies. With a NO EDGE verdict the headline is the verdict, so the headline is NO EDGE. Stop rule
  18: there is one run, reported beside nothing.
- **Section 11A.** At 0.20, S^φ differs from S, so the level triggered. SL-E1 fails there, so it is NO EDGE. At 0.30
  the level also triggered and SL-E1 fails, so it is NO EDGE, and SL-P has only 2 stops, so the line carries "LOW
  POWER: 2 stops". At 0.40, S^φ equals S bit for bit (I checked), so it is NOT TRIGGERED. Overall, the least
  favourable level that triggered gives **NO EDGE**.
- **Section 10.** There are exactly 86 measurement points: G1 9, G2 9, G3 2, G4 2, G5 16, G6 9, G7 18, G8-excess 6,
  R1 7 and the S(s_k) check 8. Each item's outcome is the AND of its points:
  - G1 FAILS at S (0.901), and also at S(0.60) (0.981).
  - G2, G5, G7 and R1 pass at every point.
  - G3 and G4 fail in both readings.
  - G6 fails at all 9 points.
  - G8-excess fails at all 6 points.
  - The S(s_k) check fails: E2 fails at each of the four shares.

  Under a NO EDGE verdict, none of the gates can change the headline.

### 3. Recomputed (my code or the lab's functions on the logged outputs; recorded value in brackets where it differs in format)

**Rebuilt from the train bars.** From the logged per-fold choices and train-only Kraken bars, I rebuilt these, and
each matches the record bit for bit:
- **S and S at 2x** (1820 rows), so each fold's run reads only bars up to that fold's last close.
- **R_0, for both seeds.**
- **The default grid step**, s = 0.50.

**The stitched series** (1820 kept rows; my Sharpe = mean / sd(ddof 1) × √365; my drawdown from a start value of 1):

| Series | Sharpe | Return | Max drawdown | Worst day | Recorded |
|---|---|---|---|---|---|
| S | 0.9009 | +212.3% | −37.48% | −11.53% | same |
| S at 2x | 0.8577 | +192.5% | −38.62% | | same |
| R_0 | 0.8969 | +198.9% | −37.48% | | same |
| N0 | 0.6264 | +145.4% | −60.56% | −25.29% | same |
| N0 at 2x | 0.6226 | | | | same |
| N0-span | 0.3970 | +47.0% | −60.43% | | same |
| X | 0.9804 | +294.0% | −39.36% | | same |
| B1 | 0.4288 | +18.4% | −81.39% | −38.94% | same |
| B2 | 0.4284 | +56.5% | −53.57% | | same |
| S on Binance (1456 rows) | 1.1914 | +244.8% | −30.19% | | same |

**The research criteria:**
- **E1.** Rebuilt from scratch: W = 260 checks, 207 guarded shifts (offsets 53-259). 17 shifts are at or above
  R_0, so the rank p is 18/208 = **0.0865** (recorded 0.087). My shift Sharpes equal the logged ones to within 6e-16.
  Seed B: 37 at or above, rank p 0.1827 (recorded 0.183).
- **E2.** `steady.paired_bootstrap(S, N0, 10000, 60, seed 0)` gives D 0.2745 and **p 0.1794** (recorded 0.179).
  My own independent stationary bootstrap (2,000 resamples, another seed) gives p 0.189. Seed B: D 0.1965, p 0.2742.
- **E3.** Seed A holds: S −37.48% / p5 −59.28%, against X −39.36% / −61.76%. Seed B fails: S −46.9% against X
  −38.6%. This difference between the seeds is why E5(a) fails.
- **E4:** 0.8577 > 0.6226.
- **E6:** Δ = 0.241. By bar-year, Δ_y is +0.398 (2018), +0.093 (2019), −0.285 (2020), −0.263 (2021) and +0.298
  (2022). Removing 2018 leaves −0.157, so E6 fails.
- **E7.** BTC's kept-row returns by bar-year were −72.7% (2018), +90.9% (2019), +317.5% (2020), +57.0% (2021) and
  −65.4% (2022). So the two best years are 2020 and then 2019, as recorded.
- **E8.** Binance: 17 of 155 shifts at or above, rank p 0.1154. E2: D 0.1172, p 0.4032.
- **P.** Rebuilt from the bars: 27 / 9 / 6 / 16 / 18 per fold, 76 in total.

**Gates and luck statistics:**
- **G6 statistic** (block 20, 1000 draws, seed 0):
  - S −59.28%, seed B −69.58%.
  - Grid steps −36.23 / −44.38 / −49.59 / −56.95%.
  - S(s_k) −43.50 / −52.46 / −58.93 / −65.75% (not in RESULTS.md).
  - All are beyond −35%.
- **DSR** (`overfitting_report` on a scratch copy of the 12 studies):
  - Raw 0.0386, effective 0.5128 (16.72 effective trials).
  - Strict count 2479: 0.0379; with K4 counted as 15 (2493): 0.0377.
  - Active rows (204 onward): effective 0.0442 (16.73 trials), raw 1.7e-7.
- **PBO:** mean over all 12 studies 0.6647; on the active rows 0.6032 (0.329 to 0.948 per study).
- **G8-excess**, with my own month labels (21 bull, 16 bear, 23 sideways). The excess over N0 is bull −1.093, bear
  +1.182 and sideways +0.152, for a total of 0.241. It fails.
- **S(s_k) E1** (from the logged shifts): 6 / 8 / 7 / 9 of 207 at or above, so the rank p is 0.034 / 0.043 / 0.038 /
  0.048 (as recorded).
- **S(s_k) E2:** p 0.291 / 0.193 / 0.088 / 0.220.

**The rest:**
- **Stop variant.** At 0.20: Sharpe 1.0044, drawdown −33.28%. At 0.30: 0.8912, −37.16%. At 0.40: equal to S.
- **Trade frequency**, my own 30-day count of fill rows. S has 58 fills in kept rows: median 1 and worst 4 per 30
  days, and 0.95 orders per 30 days on average. The default (s = 0.50) is also median 1, worst 4. Both are as
  recorded.

## Blocking items (fix RESULTS.md before it is final; none changes the verdict)

- **B1. A wrong number, from a bug in a description's code.** RESULTS.md says the 36 whipsaws cost "about 7,108
  USD". That cannot be right: all of S's trading costs in the kept rows added up to only 3,960 USD. The cause is in
  `run_train.py`'s episode table. For each whipsaw it sums the cost of every leg filled on both of its fill rows.
  So:
  - consecutive whipsaws that share a fill count it twice;
  - a BTC whipsaw and an ETH whipsaw on the same close each count that close's whole fill, both coins' legs.

  Counting each fill once gives 3,366 USD. The fix: correct the code (count each fill once, and ideally only the
  whipsawing coin's legs), add a regression test that fails on today's code, log it in TESTING.md's bug log, and
  correct the number in RESULTS.md. No criterion, gate or verdict reads this number, so no amendment run is needed.
- **B2. A wrong unit, and a wrong reading of a number.** RESULTS.md says: "With both bear years (2018 and 2022)
  removed, the rule trails the held mix (Δ −0.455 in Sharpe, D 0.141)". But Δ is a gap in log growth, not in Sharpe:
  over 2019-2021 the rule ended with about 37% less money than the held mix (exp(−0.455) ≈ 0.63). D is the Sharpe gap, and it is **positive** (+0.141).
  So in 2019-2021 the rule lost to holding on return but was slightly ahead on risk-adjusted return. The sentence
  "what the timing did in 2019-2021 alone was to lose to holding" needs that qualifier.
- **B3. E1's statistic is misdescribed.** RESULTS.md says: "R_0 (the rule's own timing on fold 0's kept rows) has a
  Sharpe of 0.897". In fact R_0 is S's schedule run as one book over all 1820 kept rows, and 0.897 is its Sharpe over
  all of them. It equals S only on fold 0's rows.
- **B4. PBO is misdescribed.** RESULTS.md says: "PBO: mean 0.665 over seed A's studies (the gate's number)". In fact
  0.665 is the mean over all 12 studies of both seeds, as the plan requires. Seed A's six alone average 0.718.
- **B5. Seed B does not "agree at every level" of the stop variant.** At 0.40, seed A's stop never touched the kept
  rows (NOT TRIGGERED), while seed B's did trigger. At 0.20, seed B fails SL-B and SL-E3, which seed A passes; that
  difference is why SL-E5 fails. Seed B's level outcomes are also NO EDGE where they triggered, which is probably what
  was meant, but the sentence as written is wrong.

## Non-blocking notes

1. **RISK.md understates the risk at each allowed crypto share.** Its bottom line and G6 row quote the grid steps
   (−36% at s = 0.30 to −57% at s = 0.60) as "every allowed crypto share". Those runs are IN-SAMPLE: they use
   θ_final's timing. The out-of-sample walk-forward at each share, S(s_k), falls deeper: −43.5% at 0.30 to −65.7% at
   0.60. So even the lowest share misses the 35% budget by about 8.5 points, not about 1. The conclusion (it fails at
   every share) is unchanged.
2. **The plain words leave out the comparison that matters most.** X holds S's own average crypto amount, without
   timing. X earned more than S on both Sharpe (0.980 against 0.901) and return (+294% against +212%), with a
   slightly deeper fall (−39.4% against −37.5%). The rule's only win over simply holding less crypto was a slightly
   shallower fall, and seed B loses even that (E3 fails there). "So the rule looked better" compares it only with
   the held mix and with BTC. It should say this too.
3. **"Boom years 2020 and 2021".** The plan's boom years (E7: BTC's best bar-years) are 2020 and 2019; 2021 is
   third. The rule did lose to holding in 2020 and 2021 (E6), so the sentence is true, but it uses "boom years" in a
   different sense from the check it then cites.
4. **The trades-per-parameter flag is missing** (section 16). There were 58 kept fills for 3 free parameters, which
   is 19 per parameter, below the 30 the desk asks for. `summary.json` flags it; RESULTS.md does not mention it.
5. **G3's second reading is shown under the wrong name.** G3 is decided on both readings. The active-row DSR
   (0.044) appears under "luck statistics" as the "active-row re-scoring", which is a different description
   (amendment M6). The G3 line should show both readings.
6. **E1 held at every fixed crypto share but failed at S.** At each S(s_k), E1 held (rank p 0.034-0.048), but at S it
   failed (0.087). As pre-registered, the verdict is decided at S. The four S(s_k) results are extra conditions, all
   just under 0.05 and not corrected for four looks; E2 fails at each, and so does G6. One sentence would keep the
   owner from being surprised. RESULTS.md also gives only E2 as the reason the S(s_k) check fails; G1 at S(0.60) and
   G6 at all four fail too.
7. **Which shifts did as well as the rule (a description; it decides nothing).** 16 of the 17 shifts at or above
   R_0 are the same schedule delayed by 10-48 weeks, and the other is a 90-week delay. No delay of 1-9 weeks did as
   well, and only 5 of the 52 lead offsets did.
8. **The owner's decision after A0.** The owner wrote "finish it lean" after the lead had recommended running, and
   that was read as "run it anyway". The record says exactly this. With a NO EDGE outcome nothing hangs on it, but
   future gating questions should get an explicit choice.
9. **PLAN.md section 20** still lists row T1 (run 0's look at the train bars) as "reserved". It should record run 0
   (2026-11-23 03:14 UTC, Kraken and Binance train bars to 2023-01-01) and this audit's reading (list below).
10. **A commit landed after the HEAD my brief named.** `96cb928` (03:23 UTC: app docs, README, TESTING.md) came after
    `d103797`. I did not audit its app-doc text: `docs/app/features.md` is on the restricted list. The README's
    status line matches `summary.json`, apart from note 2's omission.
11. **SCOUTING labels.** The opening box says every table is SCOUTING, which covers them. "Luck statistics" holds
    numbers but has no label in its heading; it could carry one, as most sections do.

## Checklist (backtest-auditor standard)

These items describe the strategy, not the audit. Their failures are the strategy's, and they are consistent with
NO EDGE.

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | The tamper-the-future tests passed on `587acfa` (full and deep tiers). S rebuilt from bars cut at each fold's last close reproduces bit for bit. Orders fill at the next open (hard rule 4) |
| 2 | Survivorship | N/A | BTC and ETH only |
| 3 | Data snooping | PASS | Validate-window looks: 0 (README, RESULTS.md, PLAN.md section 20). No FROZEN.json and no `validate/` folder. The test window is never read. Prior looks are disclosed (K1-K12) |
| 4 | Point-in-time inputs | PASS | The SMA reads closes up to t; the panel stops at 2023-01-01 |
| 5 | Trades per free parameter ≥ 30 | FAIL | 58 kept fills / 3 parameters ≈ 19 |
| 6 | Parameter plateau (±20%) | PASS | G5: the lowest ratio is 0.80 (S's L × 0.8); all 16 points pass |
| 7 | Walk-forward | PASS (as a method) | 5 expanding folds, H0, no purge needed (no labels). Walk-forward efficiency 0.51 |
| 8 | DSR ≥ 0.95 at the total count | FAIL | Effective 0.513, active rows 0.044, strict 0.038 |
| 9 | PBO ≤ 0.25 | FAIL | 0.665, and 0.603 on the active rows |
| 10 | CPCV | N/A | Not part of this pre-registration (walk-forward plus shift nulls instead) |
| 11 | Cost model | PASS, with a flag | `config/costs.yaml` was used, but it is still the PLACEHOLDER (unmeasured). Labelled throughout |
| 12 | Costs doubled > 0.5 | PASS | 0.858 at S; 1.16-1.22 at every grid step |
| 13 | Capacity | Not measured | In-sample legs reach about 33,500 USD (p95), and slippage above 10,000 USD is extrapolated from placeholders. No Base measurement exists |
| 14 | Monte Carlo p95 drawdown within budget | FAIL | −59.3% at S against the 35% budget; also at every grid step and every S(s_k) |
| 15 | Regimes | FAIL | G8-excess: the bear months hold more than all of the lead (+1.18), and the bull months give back −1.09 |
| 16 | Benchmarks and random entries | Mixed | Beats B1 and B2 (G7 passes). Does not beat its own shifted timing (E1 fails) or the held mix beyond luck (E2 fails) |
| 17 | Data quality, snapshot | PASS | Snapshot ID and bars hash recorded. Panel hashes equal section 3. The one missing Kraken close (2018-01-13) is disclosed. No missing Binance close |
| — | Final test window | NOT RUN | Items 5, 8, 9, 14 and 15 fail, and this scouting study never runs it (G9) |

## Files read beyond PLAN.md, RESULTS.md and RISK.md (for PLAN.md section 20)

**My brief.** It named the files I must not read and held no summary of any hold-mix-cap result.

**PLAN.md.** I read sections 0-16 and 20, plus the A0 and A1 amendment lines.

**The study's committed record:** `README.md`, `RUNLOG.jsonl`, and `trials.csv` and `evaluations.csv` (loaded as
tables).

**Run outputs:**
- `results/trend-steady/train/run0/summary.json`, `oos.parquet`, `evaluations.parquet` and `trials.parquet`.
- The 12 study folders, read through a scratch copy, via `load_trial_returns`.

**Session scratchpad:**
- `trendrun/check_587acfa/`: the tier logs, `head.txt` and the two status files.
- `trendrun/run0/run0.log`.
- `trendrun/a0/out/controls.json` (its summary block and its SHA-256).
- `trendrun/a1/throughput.json`.
- A listing of `trendrun/check_783ed2e/`.

**Records:** `reports/director/2026-11-23-owner-answer-trend-a0-power.md`.

**Code:**
- Parts of `lab/search/report.py`, `lab/search/study.py`, `lab/data/panel.py`, `lab/runner/steady.py` and
  `lab/runner/trend.py`.
- Parts of `research/trend-steady/run_train.py` and `study.py`.
- I ran `study.file_hashes` and `study.config_hash` to recompute the hashes.

**Git and config:** `git log`, `git show --stat` and `git status`; the SHA-256 of `config/risk_levels.yaml`.

**`docs/app/features.md`:** its heading lines only, and the line numbers and first context line of `96cb928`'s two
diff hunks (lines 45 and 232-244, both outside "Hold this mix"). I did not read the body of any section.

**Loaded automatically:** CLAUDE.md, AGENTS.md and TESTING.md. TESTING.md holds hold-mix-cap run 0's test facts, not
its results.

**Market data:**
- Kraken daily BTC and ETH train bars to 2023-01-01 00:00 UTC, through `lab.data.panel.load_panel`, in four scratch
  scripts (rebuilding S, rebuilding E1, rebuilding G8 and the boom-year ranking, and the whipsaw check).
- No Binance bars (the Binance numbers come from the logged outputs).
- No validate or test-window data.

**Not read:**
- hold-mix-cap's RESULTS.md, RISK.md, AUDIT.md, `decision.json`, `runs.csv` and `falls.csv`.
- The "Hold this mix" section of `docs/app/features.md`.
- `reports/director/2026-11-22-owner-answers-hold-mix.md`.

**Scratch scripts and outputs:** `trendrun/audit/` (`recompute.py`, `rebuild.py`, `e1_rebuild.py`, `g8_rebuild.py`,
`whipsaw_check.py` and their `.json` outputs).

## Fixes after the audit (the lead, 2026-11-23; not re-audited)

- **B1:** bug #60 fixed in `run_train.py` (the whipsaw total counts each order once), with
  `test_the_whipsaw_total_counts_each_order_once` (fails on the old code: 62 instead of 28) and a TESTING.md bug-log
  row. RESULTS.md now gives 3,366 USD (this audit's own script, rerun by the lead, which also reproduces the recorded
  7,108), next to all kept fills' 3,960 USD, and a Deviations row. `summary.json` is left as the run wrote it. No
  amendment run: nothing decisive reads the number.
- **B2-B5:** corrected in RESULTS.md as this audit words them (log growth vs Sharpe with both bear years removed;
  R_0 over all 1820 kept rows; PBO 0.665 over all 12 studies, seed A alone 0.718; seed B's stop-loss differences at
  0.20 and 0.40).
- **Notes taken:** 1 (RISK.md gives the out-of-sample S(s_k) drawdowns, −43.5% to −65.7%, and labels the grid
  IN-SAMPLE), 2 (X in the plain words), 3 (the boom-year check's years, 2020 and 2019), 4 (the trades-per-parameter
  flag), 5 (G3's active-row reading named), 6 (the S(s_k) check's G1 and G6 failures), 9 (PLAN.md section 20 rows T1,
  Audit and V1), 11 (the SCOUTING tag). Notes 7, 8 and 10 need no change (8 is already disclosed in the owner
  record).
- The tiers are rerun on the commit with these fixes before they count (hard rule 11).

# hold-mix-cap: independent audit of RESULTS.md (run 0)

Written 2026-11-21 by `backtest-auditor`. This is a SCOUTING study on the reference engine with placeholder costs. It
is not a strategy, so per its PLAN.md (sections 2 and 13) this audit is not filed under `reports/<strategy>/`.

- **What I audited:** `research/hold-mix-cap/RESULTS.md`, which was untracked when I read it (SHA-256
  `2dab9538a6de2404…`). I checked it against:
  - PLAN.md (`2d2e8182ed4e985d…`, unchanged since the run commit);
  - the code at the run commit `afb7318`;
  - run 0's outputs: `RUNLOG.jsonl` (`926f1009c52bbd9f…`), `runs.csv` (`2ded285fa0b9629b…`), `falls.csv`
    (`678ab972c37ff0b2…`) and `decision.json` (`ab9671335caebdc0…`, byte-identical to the run folder's copy);
  - the run folder `results/hold-mix-cap/run0/`: `start.json` (`cb108c1cecffec4d…`), `summary.json`
    (`1b5722732c451095…`), `runs.parquet` (`0e2d864bbb485a2f…`), `limit_only_bands.parquet`, `parity.parquet`,
    `failures.parquet` and the 456 files in `blocks/`.
- **HEAD:** `1a9512c`. It adds only the four tracked outputs to `afb7318`.
- **What I wrote:** this file only, and I committed nothing. My scripts and logs are in a scratch folder outside the
  repo (see "Reproduce").
- **What I read:** run 0's outputs. I also loaded the Kraken and Binance daily **train** bars through
  `lab.data.panel.load_panel(..., last_close=2023-01-01 00:00 UTC)`, so I could re-simulate logged runs with my own
  code. I read no validate or test bar (look T3 below).
- **Not audited:** `research/hold-mix-cap/RISK.md`. It appeared, untracked, while I was working; I did not read it.

## Verdict

**Audit: FAIL, with 1 blocking item, and that item is in the test suite, not in the results.**

The blocking item: the whole-suite deep profile fails on HEAD `1a9512c`. It is 1 failed, 1868 passed, in
`tests/test_holdmix.py::test_money_metrics_by_brute_force`. HEAD has the same `lab/` code and tests as the run commit
`afb7318`. PLAN.md's stop rule 1 and AGENTS.md hard rule 11 say no number counts unless the tiers pass on the commit
used. Hypothesis saved the failing case in the git-ignored `.hypothesis/` folder, so on this machine even the fast and
full tiers now fail, as in TESTING.md #37 and #49. The tier stage's deep run on `afb7318` passed only because its
random draws missed this case.

RESULTS.md's content passes every check:
- every number I recomputed matches;
- the plan was followed, and its 3 deviations are logged;
- no validate or test bar was read;
- every run is logged, including the doubled-cost runs;
- the headline follows mechanically from the pre-registered rules B, A, C and D.

The failure cannot have touched any run-0 number (see "Blocking item"). Once it is triaged and fixed, with a bug-log
row, an `@example` and the tiers passing on the commit that carries RESULTS.md and this file, this audit's content
stands as written and needs no re-audit. That holds as long as the fix changes no run-0 number.

**Handoff, after that fix: ready for `risk-officer` and the owner, as SCOUTING evidence for the app's product
decisions.** This is not a strategy approval, and the study claims no edge.

**The test window was not run and is not spent.** This study must never read validate or test, so both stay unspent
for later Steady strategies. The checklist items that only apply to a strategy (5-10, 14 and 16) are N/A here, not
passed. My final step, the one-time test-window run, is for strategies at sign-off, so it does not apply.

What the owner should take from this audit, in plain words:
- **The single recommended default (band 0.50, cap 1 a month) is correct by the rules.** It rests on one thing: what
  50,000 USD wallets would pay at doubled placeholder costs. On Kraken, band 0.30 would cost them 0.273% a year,
  against the 0.25% limit. Measured Base costs could change it. It also moves in 6 of the 8 boom-year checks: to 0.30
  in 5 of them, and to "no band met the conditions" in 1. RESULTS.md says all of this, but not in its "In plain words"
  summary (item N1).
- **The evidence for a Steady upper limit of 2 rebalances a month is the steadiest result.** It holds on both
  sources, at both cost levels, at every wallet size, under both other readings of the 60% limit, and in all 8
  boom-year checks, with wide margins. The number 2 depends on which bands the app offers. In practice, adopting it
  means not offering bands 0.20 and narrower (see my answer to question 8).

## Blocking item

| # | Item | Where | Why | Fix |
|---|---|---|---|---|
| X1 | The deep profile fails on HEAD `1a9512c`, which has the same code and tests as run commit `afb7318`: 1 failed, 1868 passed, 589.7 s. Ruff is clean. The full tier passed (1881) before the case was found | `tests/test_holdmix.py::test_money_metrics_by_brute_force`. The error is raised by `lab/runner/holdmix.py` line 629, `money_metrics`' consistency check | Hypothesis drew targets w_btc = 2.6e-322 (a subnormal number, below the smallest normal double) and w_eth = 1.6e-161, with band 0, wait 1, no limits and the 1x cost model. With band 0 the engine trades a 4.9e-320 USD BTC leg whose weight change is a single subnormal step (about 5e-324), and pays 0.10 USD of gas on it (documented engine behaviour, #36). `money_metrics` recovers each leg's wallet value as V_open = usd / abs(weight_after − weight_before). Below the smallest normal double that division has no relative precision, so customer fees + gas (1e-05) no longer equal the cost column (1.00002e-05), and the 1e-12 check raises. Hard rule 11 and stop rule 1 need the tiers to pass on the commit used | For the lead, not the auditor (I do not edit `holdmix.py`). (1) Triage it in TESTING.md as #54: code or test (rule 1). (2) Add the case as an `@example`; the standalone reproduction is in "Reproduce". (3) Either fix `money_metrics` so it no longer divides by a subnormal weight change, which needs the wallet value from somewhere else, since in this case the only leg on the bar is the subnormal one; or, as in #37, give a written reason (rule 2) why targets below the smallest normal double are out of scope, and handle them in the test without narrowing anything else. (4) Rerun the full tier, the deep profile and ruff on the commit that carries RESULTS.md and this file |

**Why no run-0 number can be affected:**
- Run 0 had 0 failed runs, and the same check passed on all 916,596 runs.
- The smallest leg in run 0 was 4.9e-5 USD. Wallets stayed far below 1e10 USD, so every traded weight change was
  above 1e-12, far from the subnormal range (below 2.2e-308).
- My own re-simulation computes V_open directly from the book, with no division. It matched the reported fees to
  2e-14 relative on 315 runs.

So a fix that changes `money_metrics` only where a weight change is subnormal leaves every run-0 output as it is.
Any wider change to how V_open is found could move fees by about 1e-12 relative at most. That is invisible at
`runs.csv`'s 6 significant digits, and far below the smallest fee margin of any decision (0.0011 points on 0.25 for
Binance's 50,000 USD band at 2x).

**A code fix changes the config hash.** `holdmix.py` is hashed, so the lead should log that as a deviation. Stop rule 7
asks for an amendment run only for a bug in the outputs, and this is not one. If the lead prefers proof to
the argument above, recomputing a sample of runs with the fixed code is enough.

## Protocol checks

| Check | Result |
|---|---|
| Run commit and tree | `afb7318`, clean (`start.json`: `dirty` false, no changes). RUNLOG has the start line (19:32:12 UTC) and the "complete" line (20:31:18 UTC). `git diff afb7318 HEAD` shows only `RUNLOG.jsonl`, `runs.csv`, `falls.csv` and `decision.json` |
| Config hash (stop rule 10) | `a227c167…`. All 20 hashed files are byte-identical now to `start.json`'s per-file hashes (0 mismatches), so no hashed file changed after the run started |
| rebalance-steady's frozen files | Since `2aa8dcc` (the plan's starting HEAD), no file in `frozen_paths()` changed. The only changes are TESTING.md, the new `lab/runner/holdmix.py`, the study folder, the two new test files and two director notes. rebalance-steady's config hash is untouched |
| No validate or test bar | The latest last close of any run is exactly 2023-01-01 00:00 UTC, and 0 runs end later. The full runs end 2023-01-01. Stop rule 3 did not fire. My own `load_panel` calls with that `last_close` return the same panel hashes the run recorded |
| Data | Every run row carries snapshot `1746a21b75683e76`, and its bars hash `08f5ca2c…` matches `SNAPSHOT.json`. Both panel hashes equal the pinned ones. Kraken has 2190 rows (BTC's 2018-01-13 bar dropped, as pinned) and Binance 1963 |
| Windows from the calendar | The first and last closes of all 112 windows (Kraken k = 0..59, Binance k = 8..59) follow section 6's calendar rule. The row counts are as pinned: Kraken 36 × 365, 12 × 366 and 12 × 364; Binance 40 × 365 and 12 × 366 |
| Every run logged (hard rule 8) | `runs.parquet` has 916,596 rows, the plan's count. Run ids are unique, every status is `ok` and `failures.parquet` is empty. `blocks/` holds 114 blocks × 4 tables and the same 916,596 runs. 403,866 doubled-cost runs are logged. `limit_only_bands` has 110,808 rows, `parity.parquet` 13,338 (all `equal`) and `runs.csv` 9,396 |
| Decisions do not depend on costs (section 4.6) | I regrouped `runs.parquet` myself. All 134,622 configurations with 6 cost settings have a single path hash |
| Parity | 10,260 band checks with `band_abs` = b·T on f ∈ {0, 0.5, 1}, plus 3,078 limit-only checks. All equal |
| Tiers (stop rule 1, hard rule 11) | The workflow's tier stage ran them on `afb7318` (1881 passed with 100% branch coverage; deep 1869; ruff clean; dashboard 86). Deviation 3 logs this. **My rerun on HEAD `1a9512c`:** full tier 1881 passed (12 slow), 100% branch coverage of `lab/` (4896 statements, 1440 branches, 0 missed), 389 s; deep profile (`-m "not slow"`) **1 failed, 1868 passed** in 589.7 s (X1); ruff clean. After the deep run, the saved case also fails the default profile on this machine. The tree was unchanged before and after (only RESULTS.md untracked) |
| Looks | 0 validate-window looks; the test window was never read. RESULTS.md records T1 (the run) and T2 (the lead's reading). PLAN.md's T1 row stays "reserved", because editing PLAN.md would change the config hash (deviation 2) |
| Deviations | 3 are logged (no MLflow, the PLAN.md T1 row, and the tiers run by the tier stage). I found no unlogged departure in the protocol. A few reporting gaps are listed below (N5, N6) |

## Numbers recomputed independently (SCOUTING)

I wrote my own code for this: pandas and numpy only, with nothing imported from `holdmix` or `run.py`. It recomputed
the following from `runs.parquet` and `limit_only_bands.parquet`.

| What | RESULTS.md / decision.json | My recompute |
|---|---|---|
| Rule B, N\*(b) for bands 0.05 / 0.10 / 0.15 / 0.20 / 0.30 / 0.50 | Kraken: more than 8 / 8 / 4 / 4 / 2 / 1. Binance: the same, except 0.5 at band 0.50 | Same. All 72 medians and 90th percentiles of extra days out of band equal decision.json exactly (difference 0.0) |
| Rule A: rebalances per 30 days (median) at each band's robust cap | Kraken 2.225 / 1.233 / 0.824 / 0.412 / 0.165. Binance 2.060 / 1.151 / 0.742 / 0.411 / 0.165 | Same, to 1e-12 |
| Rule A: customer fees, % of the wallet a year (median), 30 cells per source (5 bands with a cap × 6 settings) | e.g. Kraken at 50,000 USD 2x, bands 0.20 / 0.30 / 0.50: 0.338 / 0.273 / 0.189 | 0.3380 / 0.27345 / 0.1890. Every cell equal to 1e-12 |
| b\*(wallet, costs) per source, and the app default | Kraken: 0.20 everywhere except 0.50 at 50,000 USD 2x. Binance: 0.20 everywhere except 0.30 at 50,000 USD 2x | Same 12 values and same 4 defaults |
| Rule C: Dist, I, F and C at every cap and cost setting | I(2) = 0.9445 (Kraken), 0.9506 (Binance). N_up = 2. Value test SUPPORTED at all 12 settings | Same, to 1e-12. 1 − C(2) is 0.242-0.295 on Kraken and 0.210-0.263 on Binance; the rule needs ≥ 0.111 and ≥ 0.099 |
| Rule D: robust values | N\*_rob as above, with 1 at band 0.50. b\*_rob 0.20 / 0.20 / 0.50. App default 0.50, cap 1. N_up,rob 2, all 4 robust value tests SUPPORTED. Bands held back 0.05-0.20. CONFLICT no | Same |
| Primary check | CONFLICT yes. Default under the limit: 0.30 with cap 2 at every wallet size | Same |
| Label | NOT ROBUST (moved: b\*(50,000), the app default, CONFLICT, the default under the limit) | Consistent with the values above |
| Kraken on Binance's 52 windows | N\*(0.20) 2, from a median of exactly 7.0, which passes (the threshold is inclusive). N\*(0.50) 0.5. b\*(50,000, 2x) 0.30 | Same |
| Other first-buy reading (A1) | Binance N\*(0.50) becomes 1. b\* 0.20 with cap 4 on both sources | Same |
| Other readings of the 60% limit | The 12-mix and 20-mix tables | Same N\*, app defaults and rule C outcomes |
| Years and non-overlapping windows | Both tables (72 cells) | Same |
| Boom-year addendum (A5) | 8 removals, kept windows and all comparisons with the headline | Same in all 8. Kept windows 48/48, 37/36, 37/29 (× 3), 49/41, 48/48 and 25/25 |
| Per crypto share, at the headline 0.50 and cap 1 | 14 rows | Same |
| Comparisons with no cap and limit-only | 24 rows, plus 10 rows of run-by-run differences | Same |
| Days-outside-the-band yardstick | D_out for limit-only: 234.8 (Kraken), 232.3 (Binance). N_up 4 | Same |
| Gas, USD a year | 0.19-4.33 (Kraken), 0.14-3.83 (Binance) | Same (but see N4 on the % columns) |
| Trade sizes | Tool: largest swap 55.9% and largest day 61.8% (Kraken, s 0.30, f 0.75, b 0.50, cap 0.25, k = 0). Limit-only: 56.9% and 63.6%. Smallest swap 0.000049 USD | Same, including all 294 cells of each Kraken table |
| Reset table | 21 rows, each with Kraken and Binance | Spot-checked 6 rows on both sources (bands 0.30 and 0.50 at no cap, cap 1 and cap 0.25), plus "never fired at 0.05-0.15"; same |
| Falls | By share (14 rows), by mix (54 rows), and the recommended settings (22 rows) | Same, including dates and the window named |

Counts: I parsed 550 cells of RESULTS.md's rule A, B and C tables and compared them with decision.json; 0 differed.
966 cells of its falls and trade-size tables compared with `runs.parquet`; 0 differed. 400 spot checks of
`runs.csv`'s medians, tails and worst values; 0 differed.

**Re-simulation from the bars.** I wrote my own version of the rule: a book of coin units and USDC cash, built from
PLAN.md's sections 4.2, 4.5 and 8, sharing no code with `holdmix.py` or `portfolio.py`. It re-simulated 315 logged
runs on the train bars. The sample was random across both sources, plus limit-only runs, other-reading runs,
yearly-reset full runs, Kraken windows that hold the missing 2018-01-13 close, and the 78% mix at the headline. **0
mismatches.** Rebalance counts, limit fixes, held closes and legs were exact. In-band share, days out of band and d̄
agreed to 2e-15. Fees and gas agreed to 2e-14 relative, and the return to 4e-13. This is direct evidence that the
logged runs apply the rule as written: fills at the next open, the wait counted in calendar days from the last
counted order, the limit fix inside the wait, the strict relative band, and the first buy left out.

## Checklist (backtest-auditor items 1-17, adapted to a SCOUTING tool study)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Look-ahead | PASS | A decision at close t fills at the open of t + 1. My independent re-simulation, built that way, reproduces 315 runs exactly. `test_holdmix.py` has tamper-the-future tests for both first-buy readings. Nothing is fitted |
| 2 | Survivorship | N/A | BTC and ETH only; there is no token list |
| 3 | Data snooping | PASS | 0 validate looks and the test window never read. Prior looks L1-L9 are disclosed, and the thresholds were fixed before any result. Looks T1, T2 (RESULTS.md) and T3 (this audit) are recorded |
| 4 | Point-in-time inputs | PASS | The rule reads only the weights at close t and the close timestamps |
| 5 | Free parameters vs trades | N/A | Nothing is fitted or chosen by return. The grid is fixed and reported whole |
| 6 | Parameter plateau | N/A | There is no tuned point. Every band and cap is reported, and neighbouring caps move N\*(b) by one step in the boom-year check |
| 7 | Walk-forward | N/A | No fitting (PLAN.md choice 9) |
| 8 | Deflated Sharpe | N/A | No edge claim and no selection by Sharpe. 916,596 runs and 13,338 parity checks are logged. This study is now a prior look for later Steady strategies, as RESULTS.md says |
| 9 | PBO | N/A | As item 8 |
| 10 | CPCV | N/A | The spread over the 60 / 52 overlapping windows is reported (median, 90th percentile, worst), by start year and on the non-overlapping windows |
| 11 | Cost model vs `config/costs.yaml` | PASS, flagged | The costs as read in `start.json` are the YAML's, and my re-simulation with the YAML values reproduces the fees to 2e-14. **Every value in the file is still a placeholder.** That covers every fee number, rule A's fee condition, rule C's value test and therefore the single default band. RESULTS.md says so |
| 12 | Cost stress | PASS | Every configuration ran at 2x, and the robust values use both cost levels. The "Sharpe > 0.5" part is N/A |
| 13 | Capacity | Flagged (N/A as a gate) | The placeholder slippage table is extrapolated above 10,000 USD a swap. The 50,000 USD result, which sets the single default, leans on that. Disclosed |
| 14 | Monte Carlo drawdown | N/A | None was pre-registered and there is no drawdown budget. Falls are reported as descriptions with the hypothetical label |
| 15 | Regimes | N/A as a gate | The years description and the boom-year addendum are reported, and I verified both |
| 16 | Benchmarks | N/A | Not judged on return (PLAN.md section 7). The comparators (no cap, limit-only) are reported and verified |
| 17 | Data quality | PASS | The snapshot id is on every run row. The bars and panel hashes match. The missing close and Binance's later start are handled, and the window row counts are verified |

## Key numbers (SCOUTING, placeholder costs, in-sample 2017-2022, 12-month windows, medians over mix-years)

| Setting | Source | Rebalances a month | Customer fees, % a year (5,000 USD, 1x) | In band (median / 10th pct of days) | Days out of band a year | d̄ |
|---|---|---|---|---|---|---|
| **0.50, cap 1 (headline)** | Kraken | 0.165 | 0.058 (500 USD 0.047, 50,000 USD 0.095; 2x 0.117) | 99.45% / 95.84% | 2.0 | 0.202 |
| | Binance | 0.165 | 0.048 | 99.73% / 97.53% | 1.0 | 0.199 |
| 0.20, cap 4 (per-size default up to 5,000 USD) | Kraken | 0.824 | 0.110 | 96.98% / 90.91% | 11.0 | 0.090 |
| | Binance | 0.742 | 0.103 | 97.25% / 93.41% | 10.0 | 0.089 |
| 0.30, cap 2 (default under a limit of 2) | Kraken | 0.412 | 0.087 | 98.63% / 93.41% | 5.0 | 0.131 |
| | Binance | 0.411 | 0.078 | 98.90% / 95.60% | 4.0 | 0.129 |

- The in-band share is not in RESULTS.md (N8). Days out of band a year are exactly 365 × (1 − the in-band share) on
  every run (checked to 6e-14), so RESULTS.md's days-out numbers say the same thing.
- **Upper limit:**
  - Kraken: I(2) = 0.9445, and at 5,000 USD 1x 1 − C(2) = 0.2774, against the 0.1109 the rule needs.
  - Binance: 0.9506, and 0.2443 against 0.0988.
  - The robust outcome is EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED.
- **Robustness:** NOT ROBUST, through 50,000 USD wallets at 2x only.
- **No equity curve file.** None was pre-registered. Per-run returns stay in the git-ignored `runs.parquet`
  (PLAN.md section 2).

## Non-blocking items

| # | Item | Where | Suggested fix |
|---|---|---|---|
| N1 | The plain-words summary presents the 0.50 default without its two caveats. It is labelled NOT ROBUST, and it rests entirely on 50,000 USD wallets at doubled placeholder costs. It also changes in 6 of the 8 boom-year removals: to 0.30 in five, and to "no band met the conditions" without 2019. Both are reported further down | RESULTS.md, "In plain words" | Add one sentence saying so |
| N2 | The run record lists the pandas `PerformanceWarning` from `run.py` line 1212 only. The console log also has it from line 1350. Both are harmless, and nothing came from `lab/` | RESULTS.md, Run record | Name both lines |
| N3 | README.md still says "Every real run will be logged … and the results will go in RESULTS.md" (future tense) | README.md | Update when RESULTS.md and this file are committed |
| N4 | The gas "% of 500 / 5,000 / 50,000 USD" columns are USD a year divided by the starting wallet (decision.json `gas.pct`). Section 8's per-run gas % divides by the wallet at each fill. They differ (Kraken, no cap, 500 USD: 0.867% against 0.713%). The plan's wording for this description ("as % of 500, 5,000 and 50,000 USD wallets") fits the reading used | RESULTS.md, gas tables | A one-line note under the tables |
| N5 | Section 10 asks for trade sizes "for each (b, N) and each crypto share". RESULTS.md gives the full table for Kraken; Binance appears only by crypto share. The Binance values are in `runs.csv` | RESULTS.md, Trade sizes | Add the Binance table, or point to `runs.csv` |
| N6 | Section 10(b) asks for the full-run fall "with its peak and trough dates … with and without the yearly reset". The with-reset column shows the fall without its dates; they are in `falls.csv` | RESULTS.md, Falls | Add the dates, or point to `falls.csv` |
| N7 | Open question 5 asks to "allow one swap of at least 56% of the wallet". That is right for the tool (55.9%). The limit-only comparator's largest single swap was 56.9%, so the parenthetical for "a mix left alone until a limit hit" would be 57% for one swap, as well as the 64% for one day | RESULTS.md, Open questions | Add "57%" to the parenthetical |
| N8 | The in-band share is never shown, though the task brief and section 8 name it. It carries the same information as days out of band | RESULTS.md | Optionally add it for the recommended settings (values above) |
| N9 | The run stage's handoff said 0.274% and "about 2.5". RESULTS.md has 0.273% (the value is 0.27345) and 2.6-3.0 (5.934 / 2.308 = 2.57, 2.308 / 0.824 = 2.80, 1.236 / 0.412 = 3.00). RESULTS.md is right; nothing to fix there | Handoff only | None |
| N10 | The upper-limit proposal ("if the owner has no preference, the lab suggests adopting it") goes a step beyond rule C's pre-registered output, which is evidence only. It is clearly marked as a proposal that sets no limit, it states its fragility (the days yardstick gives 4; band by band it gives 0.5 to 4), and the robust evidence behind it is strong. Acceptable | RESULTS.md, Steady upper limit | None needed; see question 8 |

## Answers to RESULTS.md's questions for `backtest-auditor`

**7. Are the knife-edge outcomes acceptable as they stand?** Yes. Both thresholds were applied exactly as
pre-registered, and neither moves the headline. I checked:
- **Binance's N\*(0.20).** Cap 2 fails by 0.0096 days on the median. The robust value takes the larger of the two
  sources, Kraken's 4, either way. Kraken on Binance's windows sits exactly on the inclusive 7.0 and passes, which is
  correct by the rule.
- **Binance's 50,000 USD band at 2x.** Band 0.30 passes by 0.0011 points (0.2489%). The robust b\*(50,000) of 0.50 is
  set by Kraken at 2x, where 0.30 misses by 0.0235 points (0.2735%). That is not a knife edge.
- **The real weak point is elsewhere.** The headline's most sensitive number is that Kraken 2x fee for 50,000 USD
  wallets. It sits on placeholder costs with slippage extrapolated beyond the table, so it should be the first number
  rechecked with measured Base costs.

**8. Is pooling the 6 bands in rule C the right yardstick?** It is the pre-registered rule, and it was applied as
written, so the outcome stands as reported. But the pooled number is driven by the narrow bands:
- band by band, N_up runs from 0.5 (band 0.50) to 4 (band 0.05);
- on the days-outside-the-band yardstick it is 4.

So in practice, "adopt an upper limit of 2" is the same decision as "do not offer bands 0.20 and narrower". At their
own recommended caps (2 and 1), bands 0.30 and 0.50 never reach that limit. I suggest asking the owner in that form,
"offer only bands 0.30 and 0.50, with caps of 2 and 1?", next to the limit question. RESULTS.md already explains this
under "Where the number 2 is fragile".

## Looks at the data (continues RESULTS.md's table)

| # | Date | By | What was looked at |
|---|---|---|---|
| T3 | 2026-11-21, after run 0 | `backtest-auditor` (this file) | Run 0's outputs (decision.json, runs.csv, falls.csv, runs.parquet, limit_only_bands.parquet, parity, failures, start and summary records). Also the Kraken and Binance daily train bars to 2023-01-01 00:00 UTC, loaded through `load_panel` to re-simulate 315 runs. No validate or test bar |

Validate-window looks by this study: still 0. Test window: never read, not spent.

## Reproduce

The scripts are in `/tmp/claude-0/-home-user/45b9259c-cd7f-5869-8006-179fd7a14409/scratchpad/holdmix/audit/`. Each
runs with `/home/user/osprey/.venv/bin/python -I <script>`.
- `recompute.py`: rules B, A, C and D, the primary default under the limit, and Kraken on Binance's windows, compared
  with decision.json.
- `recompute2.py`: per share, the comparisons, the days yardstick, gas, trade sizes, the reset table, the falls, the
  other reading, the limit readings, the years table and the 8 boom-year removals. Its output is in
  `recompute2.out`.
- `resim.py`: my own rule on the train bars, against 315 logged runs.
- `check_tables.py`: RESULTS.md's rule A, B and C cells against decision.json.
- `check_falls_sizes.py`: the by-mix falls and the trade-size tables against `runs.parquet`.
- `full_tier.log` and `deep_tier.log`: my tier runs on HEAD.
- `repro_subnormal.py`: the standalone reproduction of X1 on synthetic bars. It raises the same `ConsistencyError`;
  the BTC leg on bar 4 is 4.9e-320 USD with weights 2.569e-322 → 2.619e-322.

## Re-check, 2026-11-21 (after the fixes for X1 and X2)

Written 2026-11-21 by `backtest-auditor`. I re-checked only the two items I sent back:
- X1 above;
- X2, the falls wording in RESULTS.md. I raised it in my handoff after this file was written, so it is not in the
  tables above.

Nothing else in this audit was reopened, and I committed nothing.

**What I re-checked against:**
- HEAD `1a9512c`, with these files uncommitted on top: `tests/test_holdmix.py` (SHA-256 `dfbaad832a54e857…`),
  `TESTING.md` (`33ce17e037b26bc4…`), `research/hold-mix-cap/RESULTS.md` (`26659697c3ea580b…`), `RISK.md` (not read)
  and this file.
- **No `lab/` file and no hashed file changed.** I recomputed the config hash with `run.py`'s own functions. It is
  still `a227c167…`, and 0 of the 20 per-file hashes differ from `start.json`. `git diff afb7318` shows nothing under
  `lab/`, `config/`, `pyproject.toml`, `uv.lock` or `research/rebalance-steady/`, so rebalance-steady's config hash
  is untouched too.

### Re-check verdict

**Re-check: PASS. Both items are fixed, and the audit verdict is now PASS.** It was FAIL, on X1 only.

**Handoff: ready for `risk-officer` and the owner, as SCOUTING evidence for the app's product decisions.**
- This is not a strategy approval, and the study claims no edge.
- The test window is still not run and not spent.
- This study has still made 0 validate-window looks.

**One condition:** my tier runs were on the working tree described above. The commit that carries RESULTS.md and this
file must hold exactly those files: the same `tests/test_holdmix.py`, and no `lab/` change. If anything else changes
before the commit, rerun the tiers.

### X1 (the deep-profile failure): PASS

| Check | Result |
|---|---|
| Triaged in the bug log | TESTING.md #54 calls it a test bug, gives the written reason rule 2 asks for, and changes no code. Section 3 records the new tier runs |
| The case kept as an `@example` | There are two: the failing case, and the same case with the BTC target at 1e-307. My own script confirms what the row says. **The first case** still makes `money_metrics` refuse, with the fee check's message: BTC swaps of 4.9e-320 USD on bars 7, 8, 10, 13 and 15, and the recovered wallet value comes out as 10,000 or 9,999. So the old test fails on it. **In the second case** the weight changes are still subnormal (down to 4.1e-311), but every swap's USD size is a normal number (4.1e-307 to 2.3e-305). The wallet value is then recovered correctly (9,999.8 down to 9,998.1), and nothing is refused. So the test draws its line at the swap's USD size, which is where the precision is really lost |
| Not weakened (rule 2) | Every draw that returned metrics before still runs every old assertion. A new assertion runs on every draw: on every swap of at least 2.2e-308 USD, usd / weight change must equal the independent book's wallet value to 1e-12. A refusal is accepted only when all three hold: (a) it carries the fee check's message; (b) at least one rebalance swap is below 2.2e-308 USD; (c) the independent book's wallet values make fees + gas equal the cost column to 1e-12. No input range, cost model or tolerance changed, and there is no `assume()` |
| My hand break | In a scratch copy, I made `money_metrics` refuse whenever a rebalance swap is below 1e-300 USD. The new test fails, on the 1e-307 example. The repo's `holdmix.py` was not touched |
| Edge probe | I swept the BTC target across 205 values from 1e-280 down to 5e-324, on 3 panels, 2 cost models and bands 0 and 0.1: 2,460 cases. The test body never failed. 326 cases were refused, and each one met all three conditions. The fixed test also passed at the deep profile under hypothesis seeds 4 and 5 (the lead ran 1, 2 and 3) |
| Test fix, not code fix | Right here, for three reasons. PLAN.md section 8 pins the wallet value as usd / weight change, and the 1e-12 check on every run. In a real run the refusal stops the run (`run.py` treats `ConsistencyError` as a stop), so it can never produce a wrong number. And it needs a target below about 1e-290, while the grid's smallest is 0.05 |
| Recorded in RESULTS.md | Deviation 4 and the last row of the tier table |
| **My tier runs on this working tree** (`-n 2`) | Full tier: **1881 passed** (12 slow), **100% branch coverage of `lab/`** (4896 statements, 1440 branches, 0 missed), 377 s. This run also replays the saved failing case from `.hypothesis/`, which had made the fast and full tiers fail on this machine. Deep profile (`-m "not slow"`): **1869 passed**, 576 s. Ruff clean. Dashboard 86 passed. The tree and the file hashes were the same before and after |

### X2 (the falls wording in RESULTS.md): PASS

Each fix was made as asked:
- The plain-words summary now says which falls are at the default, and gives the deeper falls at other settings.
- Both "What the falls say" bullets now start with the default.
- A new note under the by-crypto-share tables says that the "Deepest over every band and cap" column covers 12-month
  windows only, and gives the full-run figures.

The lead went further than I asked: the worst day and the worst 7 days are now split between full runs and windows.

I recomputed every new number from `runs.parquet` with my own code (pandas only). I used the basis the tables state:
5,000 USD, normal costs and the lab's first-buy reading. All of them match, including the values that sit on a
rounding boundary.

| Claim in RESULTS.md | My recompute |
|---|---|
| At the default: 35% (20% crypto) to 76% (78%) in 12 months | 35.35 (Kraken, ETH only, k 11); 75.75 (Binance) |
| At the default: up to 29.5% in one day over the full run, and 32% in a window that began just before the March 2020 crash | 29.53 (Binance, 70%, f 0.25); 32.08 (Binance, 78%, window k 38, began 2020-03-02) |
| At the default, full runs: 29.2% in a day and 36.3% in 7 days (Kraken); 29.5% and 36.7% (Binance) | 29.18, 36.34, 29.53, 36.66 |
| At any band and cap: 42% (20% crypto) to 80% (70% crypto) in 12 months | 42.00 (Kraken, ETH only, b 0.05, cap 0.25); 80.43 (Kraken, f 0.25, b 0.05, no cap) |
| The new 7-row table: deepest full-run fall over every band and cap (28 values and 3 named settings) | All equal: for example 45.03 / 57.29 / 65.57 (Kraken, 20 / 30 / 40% crypto, with the settings it names), and 72.45 → 72.5, 79.25 → 79.2 |
| Up to 32.7% in one day and 39.6% in 7 days (Binance, 78%, b 0.10, no cap, in a window); full runs 32.1% and 39.4% (Binance, b 0.05, no cap); Kraken 31.7% and 39.0% | 32.65 and 39.55 (one run, window k 37); 32.09 and 39.37; 31.72 and 39.04 |
| The yearly reset changes none of them | With the reset, the deepest full-run fall equals the deepest without it at every crypto share, and the reset never sets the worst day or week |
| Budget 35%: 2 of the 27 mixes stay within it at every band and cap (20% crypto, f 0.75 and 1: 33.4% and 35.0%); 4 at the default (all 20% mixes except ETH only, which fell 35.3%) | 33.43 and 34.98. At the default 33.47 / 30.44 / 25.57 / 25.49, and ETH only 35.35 |

**Non-blocking, wording only (no rerun):**

| # | Item | Suggested fix |
|---|---|---|
| R1 | The note under the by-crypto-share tables places "32.7% and 39.6% at band 0.10 with no cap (Binance)" in the window that began on 2020-03-02. They come from the window that began on 2020-02-02 (k 37). The 2020-03-02 window at band 0.10 with no cap fell 32.08% and 39.35%, the same as at the default. The "What the falls say" bullet gives the same numbers without naming a window, and is correct | "... and 32.7% and 39.6% in the window that began on 2020-02-02, at band 0.10 with no cap (Binance)" |
| R2 | The summary's falls are at a 5,000 USD wallet and normal costs (the basis of the falls tables), but line 19 does not say so. Two figures move at other wallet sizes or at doubled costs. **(a)** At 500 USD, the deepest 12-month fall at 70% crypto is 81.0% at normal costs and 81.6% at doubled costs, not 80%. **(b)** The second mix inside the 35% budget (20% crypto, all BTC) is 34.98% at worst, only 0.02 points inside. At doubled costs it is 35.01-35.04% at every wallet size, so only 1 of the 27 mixes stays within. The 4 mixes at the default stay within at every wallet size and cost level (at most 33.54%). My own fix text for X2 left out the basis, so this gap is mine, not the lead's | Add "(5,000 USD wallet, normal costs)" after "At other bands and caps". After "only 2 of the 27 mixes", add "(1 at doubled costs: the all-BTC mix is only 0.02 points inside)" |

### Looks at the data (continues the table above)

| # | Date | By | What was looked at |
|---|---|---|---|
| T4 | 2026-11-21, after the fixes | `backtest-auditor` (this re-check) | Run 0's `runs.parquet` (falls columns) and `start.json`, to recompute the falls wording and the config hash, plus synthetic bars for the test probes. No train, validate or test bar was read |

Validate-window looks by this study: still 0. Test window: never read, not spent.

### Reproduce (re-check)

The scripts and logs are in `/tmp/claude-0/-home-user/45b9259c-cd7f-5869-8006-179fd7a14409/scratchpad/holdmix/recheck/`.
- `falls_recheck.py` and `falls_recheck2.py` (with their `.out` files): every falls number above. Run each with
  `/home/user/osprey/.venv/bin/python -I <script>`.
- `examples.py`: the two `@example` cases against the bug-log row.
- `sweep.py`: the boundary sweep through the test body. Run it from the scratch copy `seeds/`, with `PYTHONPATH` set
  to that copy.
- `break/`: the scratch copy with the hand break.
- `tiers.log`: my full tier, deep profile and ruff on the working tree.

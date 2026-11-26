# momentum-bold run 0: audit (light)

`backtest-auditor`, 2026-11-26. The owner asked for a light audit: I checked the decision and its key numbers, and
did not review the code again. I did not rerun the search, the run or any test tier. I read only train bars: S was
rebuilt fold by fold from `data/catalog_bold/`, which the loader serves up to 2023-01-01.

**Verdict: the run PASSES, and so do its numbers.** NOT A CANDIDATE stands; no finding below would change it.
RESULTS.md needs two corrections (findings 4 and 5) and three wording fixes (6-8).

## Checks

| # | Check | Result |
|---|---|---|
| 1 | Integrity | PASS. `start.json`: commit `f6be3aa`, `dirty: false`, no changes; snapshot `81b2116f5f4b562a` / `496a690f…` (amendment D1); config hash `c7e711f5…`. The current SHA-256 of `momentum.py`, `run.py`, PLAN.md and `costs.yaml` match the recorded hashes. The panel runs 2017-08-18 to 2023-01-01 (1963 rows, 418 symbols); no row of `oos.parquet` or `null.parquet` closes after 2023-01-01. The four `trials.parquet` files hold 60 COMPLETE trials each: 240, with no failures. Strict count 245. RUNLOG: one start line and one end line for run 0. The copies in `run0/` are byte-identical to `results/`. |
| 2 | Headline recomputed with `lab/validation/stats.py` and `montecarlo.py` from `oos.parquet`, `null.parquet` and the studies' logged returns | PASS. Every value equals summary.json to the last digit: Sharpe(S) 0.388271; at 2x 0.269739; B1 0.869642, B2 0.904327, B3 0.513193; steps 0.457089, 0.261105, 0.366496, 0.515658 against 0.7 × S = 0.271790; max drawdown -0.8534; total return -0.4156; log growth -0.5371; E1 k = 169, rank p 170/201 = 0.8458 (null p5/p50/p95 0.297/0.544/0.842); DSR 0.00779 (240), 0.00763 (245), 0.1498 (effective 10.58); PBO per study 0.484, 0.683, 0.837, 0.774, mean 0.694; block-bootstrap p5 drawdown -0.98999; correlations 0.665 (B1) and 0.853 (B3). S rebuilt from `folds.csv`'s choices equals `oos.parquet` bit for bit in every fold. |
| 3 | Gates against PLAN.md section 10, and the verdict rule | PASS. G1-G8 each FAIL as recorded (G5 fails on lookback ×1.2: 0.261 < 0.272; G8 fails on total log growth < 0). E1 fails. The rule gives NOT A CANDIDATE. |
| 4 | Setup bias against the rule (`momentum._simulate`, `CoinCosts`) | No bias found that could change the verdict; one pessimistic cost, below. Costs come off the book once: the legs' costs are deducted once from V_open, the `cost` column is only reported, and the haircut goes into `paid` once. The small-coin multiplier applies to symbols outside `MAJORS = {BTCUSDT, ETHUSDT}` only: `start.json` records major costs of 5 bps pool and 10/15/30 bps slippage, and minor costs of 10 bps and 20/30/60 bps, with gas 0.10 and aggregator 0 for both. The 2x run stresses both cost sets. The haircut applies only to a held coin with no bar at row t. None of the 91 coins S held is a stablecoin, fiat, wrapped or leveraged token. |

## Findings

1. **S's only forced sale was probably a token migration, not a failure, and the pinned haircut cost about 10% of
   the wallet.** LENDUSDT was held in fold 1 (K = 3). Its data end on 2020-10-13 (no later bar), so on 2020-10-14 it
   was sold at last close × 0.70. The cost was 585.67 USD on a 1,932 USD leg: 10.2% of the wallet that day, and
   0.103 of the 0.603 summed cost. LEND was swapped into AAVE at 100 LEND per AAVE around then. That is public
   knowledge; this audit did not check it against data. The real loss was therefore likely far below 30%. The
   haircut was pre-registered (section 6) and also hits the null (0.85 forced sales a draw on average) and B3 (5).
   With that day's haircut added back, S's Sharpe is about 0.41 and its total return about -35%. No gate and not E1
   moves. **Fix:** RESULTS.md names this sale and its effect. A later Bold plan should handle known migrations or
   renames (LEND→AAVE, ERD→EGLD, BCHABC→BCH) as a pre-registered case, not as delistings.
2. **Each fold's first test row is not in S** (1456 rows, not 1460: 2019-01-03, 2020-01-03, 2021-01-02 and
   2022-01-02 are missing). This is by design: `walk_forward_optimize` keeps `.iloc[1:]`, the decisions made inside
   the block. It is consistent across S, S_2x, the steps, B1-B3 and the null. No fix needed; noted for the record.
3. **No integrity, recomputation or gate finding.** See checks 1-3.
4. **RESULTS.md, 2020 is wrong.** "In 2020, a strong year for crypto, the rule earned almost nothing" does not match
   the record, and neither does "two good years were wiped out by 2022". Fold 1's Sharpe was 0.06, but S lost
   **52%** over 2020-01-04 .. 2021-01-01. BTC hold made +315% and B3 +94% over the same span. By year, S made +82%,
   -52%, +242% and -80%. **Wording:** "2019 (+82%) and 2021 (+242%) gained; 2020 (-52%, a year in which BTC rose
   about 315%; about 10 points of the loss were the forced sale of LEND) and 2022 (-80%) lost more."
5. **RESULTS.md, costs are overstated.** "Its costs, summed day by day, came to about 60% of the wallet" is the sum
   of per-bar cost fractions (0.603). That sum includes LEND's haircut (0.103) and is not a share of any one wallet
   value. Compounded, 1 - ∏(1 - cost_t) = 0.456. **Wording:** "Costs, including one forced sale, cut the wallet by
   about 45% over the four years compared with the same trades at no cost. The daily cost fractions add up to 0.60,
   of which 0.10 was the forced sale of LEND."
6. **RESULTS.md, "the rule's choice of coins added nothing".** The direction is right, but the sentence is loose.
   **Wording:** "The rule's choice of coins showed no edge: 169 of 200 random picks with the same coin count, cash
   share and turnover did as well or better (median 0.54 against 0.39). That shortfall is itself within luck."
7. **RESULTS.md, "the result is not close on any gate"** is slightly overstated. G5's lookback ×1.2 step missed by
   0.011 (0.261 against 0.272). **Wording:** "the result is far from G1 (0.39 against 1.0), the DSR (0.008) and E1
   (p 0.85); no amendment could bring G1 near its threshold."
8. **RESULTS.md, minor.** "Every number below is taken from summary.json": the by-year table comes from
   `folds.csv`, so say so. "No edge on 2017-2022": the out-of-sample evidence covers 2019-2022 (2017-2018 was train
   only), so say "on the walk-forward years 2019-2022". "The null's turnover matches the rule's, as the plan
   requires": the plan makes the two about equal by design (25.5 against 25.3), so "about equal, by design" is more
   exact.

## Not checked (light audit)

The search code, the universe and exclusion logic beyond the coins S held, the null's draw logic and seeds, the
regime split's month labels, B2's monthly schedule and the effective-count arithmetic. The correlation with the
Steady studies (section 10 leaves it to the audit) was not computed. Validate-window looks used: 0. Test window:
not opened.

# protect-gains V1: the 30-day buy-back on fresh data (SCOUTING)

> **SCOUTING ONLY:** the reference engine, the placeholder costs and exchange candles, as in run 0. The lead wrote
> this on 2026-11-23 from `validate_look.json` and `validate_runs.csv`. The look was pre-registered in
> [VALIDATE_PLAN.md](VALIDATE_PLAN.md) and run once, on commit `d8855c9`, after the full tier (2378 passed, 100%
> branch coverage) and the deep profile (2362 passed). Validate-window looks used for protect-gains: **1 of 1**. The
> test window was not read.

## In plain words

After run 0, the setting that looked best was "sell if the wallet falls 10% below its highest value, and buy back 30
days later" (A10/30d). It was picked after seeing the results, so it was tested once, unchanged, on 2023-01-02 ..
2024-07-01. No protect-gains run had read that window.

**It does not hold up.** In that mostly rising market:

- **It made falls deeper.** The bad-case fall (90th percentile over 42 one-year runs) was 23.4%, against 16.4% for
  the tool alone. The worst was 26.4% against 17.8%. Each sale locked in a 10% fall, and the wallet sat in cash while
  the market recovered. Thirty days later it bought back higher, and the next dip started from there.
- **It cost money in every run where it fired.** A typical year ended 9.1% below the tool alone (median; mean 11.3%),
  and it never ended ahead in any of the 42 runs.
- **It did not whipsaw much** (8 of 63 buy-backs, 12.7%, were sold again within a month). That part passed.
- **The 30% crypto mixes never fired.** Their wallet never fell 10% in this window, so they are identical to the
  tool alone.

The same answer came from Binance prices and at doubled costs. Run 0 already gave no default, and this fresh check
says the post-hoc pick should not be suggested either.

## The checks (Kraken 1x, 12-month windows, "counts", 42 runs each)

| Check | Rule | A10/30d | Tool alone | Result |
|---|---|---|---|---|
| V-a, keeps the gain | median C ≤ 0.10 | 0.091 (mean 0.113; ahead in 0 of 42) | | PASS |
| V-b, no deeper falls | 90th-percentile F ≤ R's, and worst F ≤ R's | 0.234 and 0.264 | 0.164 and 0.178 | **FAIL** |
| V-c, whipsaw | re-stops ≤ 25% of buy-backs | 8 / 63 = 12.7% | | PASS |
| **Verdict** | V-a and V-b | | | **DOES NOT HOLD UP; whipsaw PASS** |

**Robustness:** the same headline on Binance 1x and on Kraken 2x.

**Per mix (Kraken 1x, 7 windows each):**

| Mix (crypto, BTC's share) | Stops | Median C | Worst F (A10/30d vs tool alone) |
|---|---|---|---|
| 30%, 50% | 0 | 0.000 | 8.4% vs 8.4% |
| 30%, 75% | 0 | 0.000 | 8.0% vs 8.0% |
| 50%, 50% | 11 | 0.089 | 23.5% vs 13.9% |
| 50%, 75% | 10 | 0.099 | 18.6% vs 12.1% |
| 70%, 50% | 25 | 0.249 | 25.0% vs 17.8% |
| 70%, 75% | 25 | 0.279 | 26.4% vs 17.2% |

## Descriptions (decide nothing)

- **"Separate" reading:** the same numbers as "counts". No 30-day buy-back was held back by the tool's wait.
- **A10 with the trend buy-back** (run 0's strongest protection):
  - it cut the bad-case fall (Q 11.6% against 16.4%; worst 15.5% against 17.8%);
  - it cost a median 11.5% and never ended ahead (V-a FAIL);
  - it held crypto only part of the time (median 36% of days in USDC).
- **The full 18-month span** (6 runs a mix) is in `validate_look.json` (`full_span`).

## Record

- Commit `d8855c9`, config hash `b945f1d303d9b99c…`, snapshot `1746a21b75683e76`, VALIDATE_PLAN.md SHA-256
  `dc9041f0…`.
- 768 runs, none failed, in 13 s.
- Train-part panel hashes equal run 0's; 547 validate rows per source, none missing.
- **Deviations:** none.

# buy-the-dip

The owner's dip ladder, a self-directed template for the app: "when crypto falls Y% from its recent high, buy crypto
with X% of my cash, and buy another X% at each further fall of Z%, until at most M% of my cash is used". The study
picks a suggested starting setting of X, Y, Z and M by rules fixed in advance, and measures how it compares with
a monthly schedule of the ladder's own total and with buying that total at once (both cut at the Steady limits). It
claims no edge.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24), modelled on protect-gains' plan.
- Status 2026-11-24: **run 0 done** ([RESULTS.md](RESULTS.md)). The rules picked a default of Y 30%, Z 10%, X 25%,
  M 100% ("when crypto falls 30% from its highest close of the past year, buy with 25% of my cash, and another 25% at
  each further 10% fall, up to all of it"), labelled **NOT ROBUST**: on Binance, and on Kraken without the windows that
  touch 2017, no setting passes, and the pick passes its bad-case test by 0.08 of a point at one start wallet. Against
  a monthly schedule of the same total it was close to a coin flip (ahead in 43-51% of two-year windows, by start
  wallet). Its bad-case fall was about 70% of the wallet, twice the Steady budget (shown, not enforced). Audit: PASS
  ([AUDIT.md](AUDIT.md)). Validate-window looks used: 0 (none planned). The test window is never read.
- History: plan committed with amendments R1 (`risk-officer` confirmed the allowed range and tightened the caps rule)
  and R2 (readings settled after the build's code review). Built and reviewed: `lab/runner/dipbuy.py`,
  [run.py](run.py), `tests/test_dipbuy.py` and `tests/test_dipbuy_run.py` (TESTING.md #71, #72, #74). A1 (36.1
  CPU-minutes) on commit `7d582ef`; run 0 on `e62233e` (90,628 runs, none failed).
- The committed record: [runs.csv](runs.csv) (one row per run), [decision.json](decision.json) and
  [RUNLOG.jsonl](RUNLOG.jsonl).
- Every number it produces is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

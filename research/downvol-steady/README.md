# downvol-steady

A downside-volatility-scaled hold for the Steady level: vol-steady's rule, except that only falling days count as
"wild", so big up-moves in a rally no longer make it step back. The owner chose it on 2026-11-24, after vol-steady
run 0 (NO EDGE), from the angles written down before that run.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24). It reuses vol-steady's protocol (and so trend-steady's)
  and changes only the volatility measure.
- Status 2026-11-24: plan committed, with amendment M1: vol-steady's audit showed the plan's stated reason was wrong,
  and E1 now holds each fold's share fixed. The owner chose to run it anyway. Validate-window looks used: 0. The test window is never read.
- Build (2026-11-24, not yet committed): `lab/runner/downvol.py` (the measure, its live twin, the seam to vol-steady's
  rule and the q-only shift), the scripts here (vol-steady's, adapted) and `tests/test_downvol.py` and
  `tests/test_downvol_scripts.py` (TESTING.md #69-#70). Synthetic dry runs only; no market bar read, no A1, A0 or run 0
  on real data.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

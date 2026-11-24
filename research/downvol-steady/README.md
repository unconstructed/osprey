# downvol-steady

A downside-volatility-scaled hold for the Steady level: vol-steady's rule, except that only falling days count as
"wild", so big up-moves in a rally no longer make it step back. The owner chose it on 2026-11-24, after vol-steady
run 0 (NO EDGE), from the angles written down before that run.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24). It reuses vol-steady's protocol (and so trend-steady's)
  and changes only the volatility measure.
- Status 2026-11-24: plan committed, with amendment M1: vol-steady's audit showed the plan's stated reason was wrong,
  and E1 now holds each fold's share fixed. The owner chose to run it anyway. Validate-window looks used: 0. The test window is never read.
- Build (2026-11-24, commit `3c5de48`): `lab/runner/downvol.py` (the measure, its live twin, the seam to vol-steady's
  rule and the q-only shift), the scripts here (vol-steady's, adapted) and `tests/test_downvol.py` and
  `tests/test_downvol_scripts.py` (TESTING.md #69-#70). Code review: four test gaps closed (#73), amendment M3.
  Synthetic dry runs only; no market bar read, and no run 0 on real data yet.
- A1 and A0 (2026-11-24, commit `7d582ef`, synthetic only; PLAN.md section 15): N = 200; run 0 projects to 3.2
  CPU-minutes. A0's power alarm fired: power 1 of 20, with 0 false positives in 20. The owner chose to run it anyway
  and to design a more sensitive follow-up first
  ([the decision](../../reports/director/2026-11-24-owner-answer-downvol-a0-power.md);
  [the follow-up's design note](../../reports/director/2026-11-24-downvol-followup-design.md), committed before run 0
  read any market bar). A NO EDGE verdict from run 0 means the test could not tell.
- PLAN.md stays byte-identical from run 0's start until the look, or until run 0 earns no look (M3): it is in the
  config hash, and an edit would make `freeze.py` refuse.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

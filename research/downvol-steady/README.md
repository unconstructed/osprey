# downvol-steady

A downside-volatility-scaled hold for the Steady level: vol-steady's rule, except that only falling days count as
"wild", so big up-moves in a rally no longer make it step back. The owner chose it on 2026-11-24, after vol-steady
run 0 (NO EDGE), from the angles written down before that run.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24). It reuses vol-steady's protocol (and so trend-steady's)
  and changes only the volatility measure.
- Status 2026-11-24: **run 0 done, verdict NO EDGE** ([RESULTS.md](RESULTS.md)). A0's power was 1 of 20, so a pass
  would have been rare even with a real edge; read NO EDGE as "the test could not tell". Over 2018-2022 the rule made
  +26% (worst fall 61%), against +221% (63%) for the plan's holding comparison, and its timing looked like chance (171
  of 207 shifted copies did at least as well). Most of the gap is one walk-forward pick: for 2020 the search chose an
  85-day window and a low target, so the rule sat out 12 weeks after the March crash while crypto nearly doubled;
  plain volatility at the same settings did much the same (the audit). Audit: PASS ([AUDIT.md](AUDIT.md)). No validate
  look (validate-window looks used: 0); the test window is never read.
- Plan history: amendment M1 (vol-steady's audit showed the plan's stated reason was wrong, and E1 holds each fold's
  share fixed); the owner chose to run it anyway.
- Build (2026-11-24, commit `3c5de48`): `lab/runner/downvol.py` (the measure, its live twin, the seam to vol-steady's
  rule and the q-only shift), the scripts here (vol-steady's, adapted) and `tests/test_downvol.py` and
  `tests/test_downvol_scripts.py` (TESTING.md #69-#70). Code review: four test gaps closed (#73), amendment M3.
  Synthetic dry runs only at that point; no market bar read.
- A1 and A0 (2026-11-24, commit `7d582ef`, synthetic only; PLAN.md section 15): N = 200; run 0 projects to 3.2
  CPU-minutes. A0's power alarm fired: power 1 of 20, with 0 false positives in 20. The owner chose to run it anyway
  and to design a more sensitive follow-up first
  ([the decision](../../reports/director/2026-11-24-owner-answer-downvol-a0-power.md);
  [the follow-up's design note](../../reports/director/2026-11-24-downvol-followup-design.md), committed before run 0
  read any market bar). A NO EDGE verdict from run 0 means the test could not tell.
- PLAN.md stayed byte-identical from run 0's start until run 0 earned no look (M3); section 20's run 0 and audit rows
  were added after that.
- Every number it produces is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

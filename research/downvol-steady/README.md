# downvol-steady

A downside-volatility-scaled hold for the Steady level: vol-steady's rule, except that only falling days count as
"wild", so big up-moves in a rally no longer make it step back. The owner chose it on 2026-11-24, after vol-steady
run 0 (NO EDGE), from the angles written down before that run.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24). It reuses vol-steady's protocol (and so trend-steady's)
  and changes only the volatility measure.
- Status 2026-11-24: plan committed. No code, no run. Validate-window looks used: 0. The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

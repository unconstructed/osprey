# vol-steady

A volatility-scaled hold for the Steady level: hold BTC and ETH half and half up to the customer's crypto share, and
step back in quarters when crypto has been wilder than a target level. The owner asked for it on 2026-11-23 as the
next hunt for a real edge.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-23). It reuses trend-steady's reviewed protocol (the folds,
  the luck checks, the gates, the verdict and the one validate look) and changes only the rule.
- Status 2026-11-23: plan committed; code and tests built (`lab/runner/volsteady.py`, the scripts in this folder,
  `tests/test_volsteady.py`, `tests/test_volsteady_scripts.py`); amendment M1 records the build's readings. Next: the
  test tiers, then A1 and A0 (synthetic), then run 0. No run on real data yet. Validate-window looks used: 0. The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

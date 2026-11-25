# keep-risk-steady

A self-directed tool for the app, "keep my risk steady": when the user's BTC/ETH mix gets wilder than a weekly swing
level w they pick (8%, 10%, 12% or 15%), the wallet holds less crypto, in quarter steps, and goes back as things calm
down. The owner chose it on 2026-11-25 as the volatility "ride test", run as a user-tool study under tool rules
([the decision](../../reports/director/2026-11-25-owner-answer-ride-test.md)).

It claims no return edge. It asks whether the ride is calmer than simply holding less crypto all the time, and what
that costs, and it picks a suggested default by rules fixed in advance.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-25), modelled on buy-the-dip's plan, with the ride statistic
  of the 2026-11-24 design note adapted to fixed settings.
- Status 2026-11-25: plan committed; `risk-officer` confirmed the allowed range (section 14). Code and tests built,
  reviewed and fixed (`lab/runner/keeprisk.py`, `run.py`, `controls.py`; TESTING.md #75-#77; amendment M1), synthetic
  data only. The three tiers passed on `6f91f46`. A1 (synthetic timing) projected A0 above its 300 CPU-minute limit;
  the owner raised the limit to 600 ([the decision](../../reports/director/2026-11-25-owner-answer-keeprisk-a0-budget.md),
  amendment M2). Next: the tiers on the amendment's commit, A0, then run 0. No run, and no market bar read for this
  study yet. Validate-window looks used: 0 (none planned). The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

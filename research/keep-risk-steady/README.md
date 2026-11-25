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
  amendment M2). The tiers passed on `71697da` (2750 passed, 100% branch coverage; the deep profile 2732 passed).
  **A0 ran on `71697da` (synthetic only, 100 panels a set, 4,056 s) and raised alarm A0-4**: on PG (volatility
  clusters with a real effect) the resampling was too confident in its lower tail, 96 of 400 boundary tests against
  a limit of 30 (NC 20, NW 16; the upper tail 0, 17 and 13). A0-1, A0-2 and A0-3 did not fire
  ([A0's outputs](a0_first_range/)). Longer resampling blocks did not fix it (a recount at 120-500: 94-109). The
  owner decided ([the decision](../../reports/director/2026-11-25-owner-answer-keeprisk-a0-alarm.md), amendment M3):
  every decision rule stays as pinned (the error only makes D1 more cautious), and a setting labelled NO NOTICEABLE
  DIFFERENCE, SMALLER BUT BELOW NOTICE or ROUGHER is shown to users with the CAN'T TELL sentence. Next: the tiers on
  M3's commit, then run 0. No market bar read for this study yet. Validate-window looks used: 0 (none planned). The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

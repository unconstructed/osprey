# keep-risk-steady

A self-directed tool for the app, "keep my risk steady": when the user's BTC/ETH mix gets wilder than a weekly swing
level w they pick (8%, 10%, 12% or 15%), the wallet holds less crypto, in quarter steps, and goes back as things calm
down. The owner chose it on 2026-11-25 as the volatility "ride test", run as a user-tool study under tool rules
([the decision](../../reports/director/2026-11-25-owner-answer-ride-test.md)).

It claims no return edge. It asks whether the ride is calmer than simply holding less crypto all the time, and what
that costs, and it picks a suggested default by rules fixed in advance.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-25), modelled on buy-the-dip's plan, with the ride statistic
  of the 2026-11-24 design note adapted to fixed settings.
- Status 2026-11-25: plan committed; `risk-officer` confirmed the allowed range (section 14). No code, no run, and no
  market bar read for this study yet. Validate-window looks used: 0 (none planned). The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.

# Owner answers for trend-steady and Steady (2026-11-21, in chat, before any trend-steady result)

Asked with the draft pre-registration's owner questions (draft in the session scratchpad, not yet committed).
Recorded here before the plan is frozen and before any trend-following result exists.

1. **Steady drawdown budget: 35%.** The Monte Carlo 95th-percentile max drawdown (AGENTS.md gate) must stay within
   a 35% fall from the high point. `risk-officer` writes `max_drawdown_budget_pct: 35` into
   `config/risk_levels.yaml` (hard rule 10: owner-approved here). Not written yet: `research/hold-mix-cap/` hashes
   that file and its run has not happened, so the edit waits until hold-mix-cap's run is done, then goes in with
   its tests. With a budget, trend-steady's Branch R opens: customers may pick the crypto share for uptrends from
   the allowed values in the pre-registration (30%, 40%, 50%, 60%), and every value must pass every check.
2. **The regimes check ("no single kind of market makes most of the profit") is measured on the gain over holding
   the same mix**, so sitting out a crash counts, for trend-steady (the draft's exact definition: `regime_split`
   with the held-mix benchmark N0). Decided before any result. Whether this becomes the lab-wide wording of the
   AGENTS.md gate is a separate proposal.
3. **Sells to cash go through during a loss-limit pause or while waiting for approval** (a pause still stops all
   buying). A product decision for the app docs; the study does not model pauses.
4. **100% USDC is allowed** when both coins trend down: Steady's "max 60%" applies per coin, not to cash.

Also in force for trend-steady: the boom-year check (`2026-11-21-boom-check.md`) and the stop-loss variant the owner
accepted ("Ok", 2026-11-21): sell after a fall of 20%, 30% or 40% from the high point, with a pre-set buy-back rule.
Not asked, so the draft's default holds: the trend check runs once a week (within "a few trades a month").

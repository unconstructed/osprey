# trend-steady: risk notes (SCOUTING)

> Written by the lead on 2026-11-23 in place of a separate `risk-officer` review: the owner asked to "finish it
> lean". Every number is SCOUTING (reference engine, placeholder costs, exchange candles; not NautilusTrader) and
> every fall below is **hypothetical**. Nothing here approves anything, and nothing here is ready for paper.
> `config/` was not changed.

**Bottom line.** The rule cannot be offered at the Steady level as tuned. Its Monte Carlo 95th-percentile fall is
−59% (seed A; −70% for seed B) against Steady's owner-approved budget of 35%, at S and at every allowed crypto share
(−36% at s = 0.30 up to −57% at s = 0.60). The study's verdict is NO EDGE anyway, so no paper plan is drawn up.

| Check | Result |
|---|---|
| Steady limits at every close of S (seed A, 2018-2022) | Held: 0 closes in breach, highest single coin 43.1% (limit 60%), lowest cash 20.5% (floor 20%), no limit fix needed |
| The default and θ_final(A) (IN-SAMPLE fixed runs) | One close each with cash below the 20% floor after a price move (lowest 18.6% for the default, 19.7% for θ_final(A)); the rule fixed each at the next day's open, as designed |
| G6, MC 95th-percentile max drawdown vs 35% | FAIL at S (−59.3%) and at every grid step (s = 0.30 −36.2%, 0.40 −44.4%, 0.50 −49.6%, 0.60 −57.0%) |
| Narrowing (section 8) | Not possible: G6 fails at S, the walk-forward choice, and no range step passes either |
| Historical worst fall | S −37.5% (2018); grid steps −21% (s = 0.30) to −38% (s = 0.60), IN-SAMPLE; held mix N0 −61%; BTC −81% |
| Worst day | S −11.5%; held mix −25.3%; BTC −38.9% |
| Stop-loss at 20% from the top | Cut S's worst fall to −33.3% with 4 stops in five years; at 30% 2 stops; at 40% none. The stop sells at the next day's open, so on a crash day the fall can run past the level before the sale |
| Trade frequency vs "a few trades a month" | Median 1 fill per 30 days, worst 4; R1 passes everywhere it is measured |
| Time in USDC | All in cash on 38% of days; longest unbroken stretch 91 days |

**What this means for Steady.** The rule's protection is real in the record (it stepped aside for much of 2018 and
2022), but its bad cases are deeper than Steady allows, and the lab could not tell its timing apart from luck. Moving
to cash in downtrends stays a product idea; it is not a Steady strategy on this evidence. The owner rules this study
applied (sells to cash go through during a pause; 100% USDC allowed) need no change.

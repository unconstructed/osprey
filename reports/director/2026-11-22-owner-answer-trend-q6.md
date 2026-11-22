# Owner answer: trend-steady question 6, keep the regimes check as it is (2026-11-22, in chat, before A0)

The lead asked this in chat on 2026-11-22 at about 17:40 UTC (a multiple-choice prompt), after the owner asked what
was being run. It was asked after trend-steady's pre-registration was committed (`16d2363`, 16:18 UTC), before A0,
and before any trend rule had been run on market data.

**Question (verbatim):** "One of the lab's checks is 'no single kind of market (rising, falling, flat) makes most of
the profit'. A strategy that moves to cash in crashes earns most of its edge in falling markets, so it will very
likely fail this check whatever its skill. Its best result would then be 'has an edge, but not ready for the next
step'. The next step (the real trading engine) is on hold anyway. Keep the check as it is?"

**Options (verbatim):**
1. "Keep it as is (Recommended)": "No change. The test still tells us whether the trend timing beats chance. If it
   does, the best label is 'edge, not a candidate'. That changes nothing today, because the next step is on hold."
2. "Drop it for this strategy": "The check won't count against this strategy. It could then reach 'candidate', but a
   strategy that only works in crashes would no longer be flagged by it."

**Answer (owner, verbatim):** "Keep it as is (Recommended)".

**What it changes: nothing in the gates.** G8-excess (the regimes check measured on the gain over holding the same
mix, the owner's choice of 2026-11-21) stays as pinned in `research/trend-steady/PLAN.md` section 10. Its threshold,
the other gates and the verdict rules are unchanged. It is still expected to fail, so the expected best reachable
headline stays "EDGE, NOT A CANDIDATE". It answers the plan's question 6, which comes from the 2026-11-22 review's
finding (PLAN.md amendment M10). It is recorded as amendment M23 of PLAN.md, before A0, and counts once that
amendment is committed.

**How it was asked.** The lead marked option 1 as recommended. The question was shorter than PLAN.md section 19's Q6:
it left out the synthetic counts (0 of 40, and 1 of 13), the arithmetic ("none above half" means "none below zero"),
and that the owner had not been told on 2026-11-21 that this form would very likely fail too. Its second option was
"drop it", not Q6's "give another rule in your own words". The owner chose the option that keeps the check, which is
also Q6's default. PLAN.md section 19 has the full comparison.

Question 7 (may a customer's own per-trade or per-day limit block a sale to cash) is still open; a late answer is
fine.

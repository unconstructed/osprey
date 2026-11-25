# Owner decision: the volatility "ride test" becomes a user-tool study (2026-11-25, in chat)

**Context.** downvol-steady run 0 (NO EDGE, audit PASS) and vol-steady run 0 (NO EDGE) found no return edge from
scaling crypto by volatility. A quick description on the train years (2017-2022, Kraken daily, scratch only, decides
nothing) then showed why: volatility predicts the next week's or two weeks' volatility well (BTC rank correlation
+0.41 for 7-day blocks, +0.38 for 14-day, +0.25 for 30-day), but not the next period's return (+0.01, +0.09, +0.14,
none significant). The lead recommended using volatility for risk features rather than as a source of extra return.
The owner agreed, asked to try the ride test next, and restated the app's purpose:

> "Okay, I agree with your recommendation. We can try the ride test next, but remember, this app is creating
> suggestions based on our sims, where we can have a managed low-risk portfolio for our users, but really it's for the
> users to develop their own quantitative strategies without having to code, basically. And we run it for them."

**Questions (as put to the owner, 2026-11-25, as a multiple-choice prompt) and answers.**

1. "How should the volatility 'ride test' be set up?"
   - **Answer: "User tool study (Recommended)":** test "keep my risk steady" as a setting users switch on and tune:
     fixed settings a user could pick, on rolling two-year windows; measure the calmer ride and its return cost against
     simply holding less crypto; pick a suggested default (like buy-the-dip). A new pre-registration that lists every
     earlier look at 2017-2022.
   - Not chosen: "As designed" (the ride test of
     [2026-11-24-downvol-followup-design.md](2026-11-24-downvol-followup-design.md) on downvol-steady run 0's
     walk-forward S) and "Both, designed one first".
2. "Which bar should a volatility-based setting have to clear before the app offers it?"
   - **Answer: "Tool rules (Recommended)":** as a setting users choose, it gets tool-style rules like buy-the-dip: no
     edge claimed, a suggested default, honest wording about the ride and its cost. Anything we manage for users still
     needs the full gates (AGENTS.md "Validation gates").
   - Not chosen: "Full gates for all", "Relax gates for risk-cutting". **No gate changes.**
3. "The tool study's pre-check on made-up markets ... may need a few hours of computer time on this machine. It's free,
   but longer than earlier pre-checks (2 hours max). OK?"
   - **Answer: "Yes, up to ~5 hours (Recommended)".** The new study's A0 may use up to 300 CPU-minutes.

**Reading.**
- The design note's ride test on downvol-steady run 0's S is not run. Its statistic (down-day size against a plain mix
  at the same average crypto), its comparator X_w, its equivalence reading (δ) and its cautions about power carry over
  as inputs to the new plan, which pins its own versions before any code.
- The new study lists as prior looks every study that read the 2017-2022 bars (rebalance-steady, hold-mix-cap,
  trend-steady, protect-gains, vol-steady, downvol-steady with its audit's 2020 reruns, buy-the-dip) and the
  description above.
- Nothing in `config/`, the gates or the splits changes. The managed Steady portfolio's gates are unchanged.

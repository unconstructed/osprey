# Owner decision: trend-steady, run 0 after A0's power alarm (2026-11-23, in chat, before run 0)

`research/trend-steady/PLAN.md` section 9 says that when amendment A0's power alarm fires (power below 4 of 20),
the lead sends the owner a fixed question in writing, and run 0 waits for the written answer. Stop rule 15 and
order-of-work step 4 ([M27]) make the A0 amendment line name this record before a real run 0 can start.

**A0's outcome** (synthetic only, no market data; `controls.py` on commit `783ed2e`, clean tree, started
2026-11-23 01:36 UTC, 1302 s, 3 workers; output `trendrun/a0/out/controls.json` in the session scratchpad, SHA-256
`7846f1aea90c47f6412823ca462132ec3bc7c0fa7e8aa731b70bae41f4cd04b8`):
- Negative controls (20 shuffled panels): 0 false positives for the plain rule (E1 and E2), 0 for the stop-loss
  variant at each level 0.20, 0.30 and 0.40, and 0 for SL-T on its own at each level. E1 alone: 0 of 20; SL-E1
  alone: 0 of 20 at each level. **Stop rule 15 did not fire.**
- The one-off size check of E1 under volatility clustering: 49 of 1000 panels passed E1 (the limit is 67). Holds.
- Positive controls (20 panels): **power 0 of 20** (E1, E2 and P all holding). E1 alone held on 1 of 20 (5%), as
  did SL-E1 alone at each level. **The power alarm fired**, as section 9 [M21] said it was expected to.

**Question (verbatim, as PLAN.md section 9 words it, with k = 0).** The lead put it to the owner on 2026-11-23
at about 02:00 UTC as a multiple-choice prompt: "The procedure check found that this study can rarely detect a
trend edge on synthetic markets whose trends are short (power 0 of 20). Real bear markets last longer, so it may
do better on real data, but run 0 is likely to end INCONCLUSIVE or NO EDGE (LOW POWER). Run it anyway, or stop
here?" The prompt added a plain line: "the test is careful (no false alarms) but may be too weak to prove a real
edge. The real run itself costs little (about 5 computer-minutes)." Its options were "Run it anyway" and "Stop
here", with no option marked as recommended.

**How it was answered.** The owner did not pick an option; they asked for a plain overview of what had been done and
what was left, then what to do next. The lead's reply recommended running it: "Finish the trend test (my
recommendation: run it)", repeated that it "will probably come back 'no clear edge' or 'can't tell'", and asked them
to say "run it" or "stop".

**Answer (owner, verbatim):** "finish it lean"

**Reading.** "Run it anyway". "Lean" is about how the rest is done (no large multi-agent workflows; the owner is
near a usage limit): the lead writes RESULTS.md and the risk notes, and one `backtest-auditor` agent audits. It
changes no rule, gate, threshold, allowed value, budget, seed, size or verdict rule of the plan.

**Note on how it was asked.** The lead recommended running it before the owner answered, so the answer is the
lead's recommendation accepted, not a choice between neutral options. The recommendation used no trend-steady
result on market data (none exists before run 0) and no hold-mix-cap number.

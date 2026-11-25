# Owner decision: keep-risk-steady's A0 may use up to 600 CPU-minutes (2026-11-25, in chat)

**Context.** keep-risk-steady's plan (section 13, stop rule 7) caps A0, the synthetic pre-check, at 300 CPU-minutes,
the owner's limit of 2026-11-25 ([2026-11-25-owner-answer-ride-test.md](2026-11-25-owner-answer-ride-test.md)). If
the projection at 100 panels a set is above it, every set shrinks to 80 panels, and above it at 80 A0 refuses to start.
After the three tiers passed on commit `6f91f46` (2750 passed, 100% branch coverage of `lab/`; the deep profile 2732
passed), A1 (`run.py --time`, synthetic bars only) was run three times on that commit, on an idle 4-core machine:

| Timing | Run 0 (limit 240) | A0 at 100 panels a set | A0 at 80 panels a set |
|---|---|---|---|
| 1 | 38.7 | 480.8 | 384.7 |
| 2 | 27.3 | 448.2 | 358.6 |
| 3 | 31.5 | 404.9 | 324.0 |

Both A0 sizes were above 300, so A0 would refuse to start. The plan's estimate (about 20 CPU-seconds a panel) was low:
A1 measures about 50-58 CPU-seconds a panel (4 x (3 + 2 x 258) full-span runs at about 19-22 ms each, with 588 window
runs at about 13-19 ms). No market bar has been read for this study.

**Question (as put to the owner, 2026-11-25, as a multiple-choice prompt) and answer.**

"Before the real-data run, the keep-risk-steady study runs a pre-check (A0) on made-up markets. You capped it at 300
CPU-minutes (~5 CPU-hours). Three timings on this machine project 405-481 CPU-minutes at 100 test markets per set, and
324-385 at the plan's 80-market fallback. Both are over the cap, so the pre-check refuses to start. It costs no money,
only time. What should I do?"

- **Answer: "Raise cap to 600 (Recommended)":** "Raise A0's cap to 600 CPU-minutes. It runs as planned with 100
  markets a set, about 2-2.5 hours of wall time on 3-4 cores. A dated plan amendment records your decision. Nothing
  about the test changes."
- Not chosen: "Speed up the code first" (keep 300, make the inner runs faster, redo the review and the tiers, re-time)
  and "Fewer test markets" (keep 300, about 60 markets a set).

**Reading.**
- Stop rule 7's A0 limit is 600 CPU-minutes (PLAN.md amendment M2; `run.py`'s `A0_CPU_MINUTES_MAX`). The fallback
  rule is unchanged in form: 100 panels a set when the projection at 100 is at most 600, else 80 when the projection
  at 80 is, else A0 refuses.
- Nothing else changes: the five sets, their seeds and sizes, the alarms A0-1 .. A0-4 and their limits, the
  resampling, the measures, run 0's limit (240 CPU-minutes), the gates, the grid and every decision rule.
- This decision answers a compute budget only. It is not an answer to an A0 alarm: the A0 record still has to say
  `A0 alarms: none`, or name a separate owner decision on the alarm (stop rules 8 and 9).

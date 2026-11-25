# Owner decision on keep-risk-steady's A0 alarm A0-4 (2026-11-25, in chat)

**Context.** keep-risk-steady's A0, the synthetic pre-check (PLAN.md section 13), ran on commit `71697da` after the
three tiers passed on it with a clean tree. It used 100 panels a set and took 4,056 s. No market bar was read. Its
outputs are in [research/keep-risk-steady/a0_first_range/](../../research/keep-risk-steady/a0_first_range/).

| Alarm | What it counts | Result | Limit | Fired |
|---|---|---|---|---|
| A0-1 | False CALMER on NW, NS, NC | 0, 0, 0 of 100 | more than 10 | no |
| A0-2 | A false default on NW, NS, NC | 0, 1, 1 of 100 | more than 10 | no |
| A0-3 | E1 holds on NC, per w (8, 10, 12, 15%) | 6, 1, 4, 6 of 100 | more than 10 | no |
| A0-4 | The resampling's boundary rate, upper tail (a "calmer" claim at "no cut") on PG, NW, NC | 0, 13, 17 of 400 | more than 30 | no |
| A0-4 | The same, lower tail ("rougher" at "no difference", "no noticeable difference" at a 10% cut) | **96**, 16, 20 of 400 | more than 30 | **yes, on PG** |

Power (a description): on PG, CALMER at any w on 10 of 100 panels and E1 on 87-100; on PR, CALMER on 21 and E1 on
71-100.

**What the alarm means.** On PG (made-up markets with volatility clusters and a real effect), the paired resampling
is too narrow: its spread within one panel (about 0.036-0.063 in V) is smaller than V's spread across panels (about
0.063-0.087), and V across panels is skewed (a few panels with very large cuts). So on a typical panel the interval
sits above the true value. It errs in one direction only: it can say NO NOTICEABLE DIFFERENCE, SMALLER BUT BELOW
NOTICE or ROUGHER when the rule really cuts more. It does not over-claim CALMER (0 of 400 on PG). On NC, whose prices
are the same kind of process with no effect, the spreads agree (0.040 against 0.042).

**First answer, superseded.** The owner was first asked (multiple choice) and chose "Fix and retest (Recommended)":
lengthen the resampling blocks, then rerun A0 on the second seed range. Before any change, the lead recounted the
boundary check on the same first-range panels with mean blocks 60, 120, 250 and 500
([block_check.py](../../research/keep-risk-steady/a0_first_range/block_check.py),
[block_check.json](../../research/keep-risk-steady/a0_first_range/block_check.json); about 6 minutes, synthetic only).
PG's lower tail stayed at 94, 100 and 109 of 400 for the longer blocks (96 at 60), and the spread barely moved. The
cause is the rule itself: a paired resampling of return rows keeps the rule's decisions where they fell, so it cannot
show how much the cut would vary on another market path. Longer blocks cannot fix that, so the first answer was not
carried out.

**Question (as put to the owner, 2026-11-25, as a multiple-choice prompt) and answer.**

"The fix you picked doesn't work. I re-ran A0's check with blocks 2x, 4x and 8x longer, and the overconfidence stayed
(94-109 of 400, limit 30). The cause is the rule itself, so this kind of resampling can't fix it. The error only goes
one way: it can wrongly say a setting 'makes no noticeable difference' or is 'rougher' when it actually helps. It
never wrongly says 'calmer'. The default-picking rule treats those labels as reasons to reject a setting, so the error
makes the study more cautious, not more optimistic. How should I proceed?"

- **Answer: "Keep rules, soften wording (Recommended)":** "Leave every decision rule as it is (they stay cautious).
  The app never shows 'no noticeable difference', 'rougher' or 'slightly calmer' as findings; those show 'can't tell'
  instead. Your answer goes on file as the decision on alarm A0-4. Then a code review, the tests (~1.5 h) and the
  real-data run. About 2.5-3 hours."
- Not chosen: "Wider intervals, retest" (widen the resampling by a fixed factor chosen now, rerun A0 on fresh panels)
  and "Stop this study".

**Reading (PLAN.md amendment M3).**
- This is the owner's decision on alarm A0-4 (stop rules 8 and 9). A0 is not rerun on the second seed range; the
  plan's "A0 then reruns" after a fix does not apply, because no statistic is changed.
- Every decision rule is unchanged: the labels of section 9.4 are computed as pinned, and D1's rule 2 still excludes
  a setting labelled NO NOTICEABLE DIFFERENCE, SMALLER BUT BELOW NOTICE or ROUGHER at a mix. On A0's evidence those
  three labels can be wrong when the rule helps, so the exclusion errs toward NO DEFAULT, not toward a false default.
- What users see: a setting labelled NO NOTICEABLE DIFFERENCE, SMALLER BUT BELOW NOTICE or ROUGHER THAN HOLDING LESS
  is shown with the CAN'T TELL sentence, never its own sentence. RESULTS.md reports the computed label with this note.
- The CALMER claim, E1, D1 and the defaults are as tested by A0-1 .. A0-3 and A0-4's upper tail, which did not fire.
- This decision answers alarm A0-4 only. A0-1, A0-2 and A0-3 did not fire.

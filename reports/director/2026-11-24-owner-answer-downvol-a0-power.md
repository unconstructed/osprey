# Owner decision: downvol-steady, run 0 after A0's power alarm (2026-11-24, in chat, before run 0)

`research/downvol-steady/PLAN.md` follows vol-steady's section 9 (TP 9 as re-read there): when amendment A0's power
alarm fires (power below 4 of 20), the owner is told in writing before run 0 and decides. The scripts refuse a real
run 0 until section 15's A0 line names this record (TP M27; VP and this plan, sections 14-16).

**A0's outcome** (synthetic only, no market data; `controls.py` on commit `7d582ef`, after the three tiers passed
on that commit, clean tree, started 2026-11-24 09:05 UTC, 637 s, 3 workers; output `a0-downvol/controls.json` in
the session scratchpad, SHA-256 `40c9755848db4a9495ffc24b1d9119a3ab8790973b7e7f4b02a23aa8ce324bc6`):

| Control set | Result |
|---|---|
| Negative controls (20 shuffled panels) | 0 false positives (E1 and E2 both held), under the alarm of 3. E1 alone held on 0 of 20, E2 alone on 0. **Stop rule 15 did not fire** |
| Positive controls (20 panels with volatility clustering and regimes) | **Power 1 of 20** (E1, E2 and P all held). E1 alone held on 5 of 20, E2 alone on 1, P on 19. **The power alarm fired** |
| Volatility clustering with no momentum (200 panels, the fixed rule (30, 0.60, 0.50)) | E1 held on 17 of 200 (8.5%). This is a description with no alarm: the power where the mechanism is real |

For comparison, vol-steady's A0 gave power 3 of 20, 1 false positive, and E1 on 26 of 200 clustering panels.

**Question (as put to the owner, 2026-11-24, as a multiple-choice prompt).** "The downside-volatility study's
pre-check found it can rarely confirm an edge, even on made-up markets built to have one: 1 of 20, where the plan
wants at least 4 (plain volatility scored 3 of 20). It raised no false alarms on markets with no edge (0 of 20), so
a pass would still mean something. A 'no edge' result, though, would mostly mean 'can't tell'. The real run costs
about 3 minutes of computer time. Buy-the-dip doesn't depend on this and goes ahead either way. What should I do
with downside volatility?"

The options:
- "Run it anyway (Recommended)": run it as pre-registered; a pass would be meaningful given zero false alarms; treat
  'no edge' as 'can't tell'.
- "Stop here": don't run it; the angle stays untested.
- "Redesign first": pause and design a more sensitive test or another angle before any real run.

**Answer (owner, verbatim):** "can we do the first and the third?"

**Reading:**
- **Run it anyway.** Run 0 goes ahead as pre-registered. This changes no rule, gate, threshold, allowed value,
  budget, seed, size or verdict rule. A NO EDGE verdict is reported as "the test could not tell", with this record's
  power numbers next to it.
- **Redesign first.** Both answers are kept by doing the redesign first and the run after it. Before run 0 reads any
  market bar, the lead designs a more sensitive test, or another angle, as a follow-up study. The design uses
  synthetic data only, and it is committed with this record. It changes nothing in run 0. Any study built from it
  later lists downvol-steady run 0 (and vol-steady run 0) as prior looks, and pre-registers its own plan.
- The follow-up's design note: [2026-11-24-downvol-followup-design.md](2026-11-24-downvol-followup-design.md).

**Note on how it was asked.** The lead recommended running it before the owner answered. The recommendation used no
downvol-steady result on market data, because none exists before run 0.

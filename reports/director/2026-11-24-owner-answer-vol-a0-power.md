# Owner decision: vol-steady, run 0 after A0's power alarm (2026-11-24, in chat, before run 0)

`research/vol-steady/PLAN.md` section 9 (TP 9 as re-read there) says that when amendment A0's power alarm fires
(power below 4 of 20), the owner is told in writing before run 0 and decides. The scripts refuse a real run 0 until
section 15's A0 line names this record (TP M27, PLAN.md section 14-16).

**A0's outcome** (synthetic only, no market data; `controls.py` on commit `5b5df1e`, clean tree, started
2026-11-23 23:59 UTC, 532 s, 3 workers; output `vol_a0/controls.json` in the session scratchpad, SHA-256
`2dd9e00c90ab06488a2fc43398a20e99ce0577bebcfb1ba3268844e9467d29b6`):

| Control set | Result |
|---|---|
| Negative controls (20 shuffled panels) | 1 false positive (E1 and E2 both held), under the alarm of 3. E1 alone held on 2 of 20, E2 alone on 1. **Stop rule 15 did not fire** |
| Positive controls (20 panels with volatility clustering and regimes) | **Power 3 of 20** (E1, E2 and P all held). E1 alone held on 6 of 20, E2 alone on 4. **The power alarm fired** |
| Volatility clustering with no momentum (200 panels, the fixed rule (30, 0.60, 0.50)) | E1 held on 26 of 200 (13%). This is a description with no alarm: the power where the mechanism is real |

**Question (as put to the owner, 2026-11-24, as a multiple-choice prompt).** "The volatility study's pre-check found
it can rarely confirm an edge, even on made-up markets built to have one (3 of 20; the plan wants at least 4). Real
data has strong calm/wild spells, so it may do better, but a NO EDGE result would mostly mean 'can't tell', not
'proven useless'. The real run costs about 3 minutes of computer time. What should I do?"

The options:
- "Run it anyway (Recommended)";
- "Stop here";
- "Redesign first".

**Answer (owner, verbatim):** "Run it volatility is usually a great market predictor maybe think of a different angle"

**Reading:**
- **Run it anyway.** Run 0 goes ahead as pre-registered. This changes no rule, gate, threshold, allowed value,
  budget, seed, size or verdict rule.
- **"Think of a different angle"** is a request for a possible follow-up study, not a change to this one. To keep any
  follow-up honest, the lead wrote down these candidate angles **before run 0 has read any market bar**. Any study
  built on them later lists vol-steady run 0 as a prior look.
  1. **Downside volatility.** Scale by the spread of the falling days only (semivariance), so wild up-moves in a rally
     do not cut the crypto share.
  2. **The volatility trend.** Step back when short-term volatility rises above its own longer average (a "vol ratio"
     such as 10-day over 60-day), not when it is high in absolute terms.
  3. **A forecast instead of trailing volatility.** Use the lab's tested EWMA-anchored volatility model
     (`lab/models/train.py`) for the next weeks' volatility, in place of the trailing σ̂.
  4. **Volatility as a crash warning.** Ask whether a jump in volatility predicts the next weeks' fall, by its own
     pre-registered test, rather than using it only to size the holding.

**Note on how it was asked.** The lead recommended running it before the owner answered. The recommendation used no
vol-steady result on market data, because none exists before run 0.

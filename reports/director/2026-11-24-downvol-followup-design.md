# downvol-steady follow-up: the ride test at the same crypto (design note)

**Status: DESIGN NOTE, not a pre-registration.** Written 2026-11-24 by the lead, at the owner's request ("can we do
the first and the third?", recorded in
[2026-11-24-owner-answer-downvol-a0-power.md](2026-11-24-owner-answer-downvol-a0-power.md)). It was written and
committed **before downvol-steady run 0 read any market bar**, and it used synthetic data only. It changes nothing in
run 0.

It fixes the direction of a follow-up study. **Every choice that decides an outcome is pinned here, before run 0
starts** (section 3.13), including the values the owner is asked to confirm (section 6). A later PLAN.md can only add
detail. If anyone changes a pinned choice after run 0 has started, that change is an amendment that names run 0 as a
prior look, and it is reported as one.

> **SCOUTING ONLY.** Every number here comes from the reference engine (`lab/runner/trend.py`'s executor), placeholder
> costs and synthetic markets. Nothing here can make a rule ready for paper, and no number here may be shown to users
> (hard rule 3: only a NautilusTrader rerun can produce one).

How it was made: four proposals ("statistic", "data", "mechanism", "user") and twelve judgements of them. The lead
combined them into this design. A verifier then rebuilt the main check with its own script, and a completeness critic
reviewed the draft. The lead then revised it and ran one more check (section 4.5). Section 8 lists what the review
found and what changed.

---

## 1. In plain words

**Why today's test is weak.** The pre-registered test judges the rule by its Sharpe ratio (return per unit of total
swing), against the same mix held all the time. Over five years, a crypto wallet's Sharpe ratio is mostly decided by
where prices happened to go. This rule's job is to make falls smaller, and that changes risk much more than return. On
made-up markets built to contain the effect, the test confirmed it on only 1 of 20. The plan wants at least 4.

**What the follow-up would test.** It asks the question a Steady user would ask: *at the same average amount of
crypto, are my down days smaller with this rule than with a plain mix that simply holds less crypto?* The plain mix is
rebalanced every week, so it really does hold that amount and does not drift. Four checks come with it:
- **Timing, not luck.** Are the rule's step-backs better timed than the same step-backs moved to other weeks? Each
  version is compared with its own plain mix, so holding less crypto on average does not count as timing.
- **Not beaten by holding less.** Would holding even less crypto have given the same smoothness with more return?
- **Not one year.** Does the result survive without each year, and without BTC's best year and two best years (the
  owner's boom-year rule)?
- **Not costs.** Does it survive doubled costs?

It uses run 0's own rule and settings, and searches nothing new.

**What the outcomes would mean.**
- **PASS:** a smoother ride than simply holding less crypto, after costs, and unlikely to be luck at the stated levels.
  That last part rests on the follow-up's own pre-check, which can rule out false-alarm rates of about 10% or more but
  cannot prove they are 5% (section 3.13). The return it costs is shown with its range. Five years cannot prove that
  cost is small; they can only flag a clearly large one.
- **SMALLER, BUT BELOW NOTICE:** the down days are reliably smaller, and the data also rule out a cut of 10% or more.
  Real, but too small to offer.
- **NO NOTICEABLE RIDE ADVANTAGE:** the data rule out a cut of 10% or more in the size of down days, compared with
  holding less crypto. This does not say the timing is absent; it says the gain is too small to matter to a user.
- **DOMINATED:** smoother, but at the point estimate holding less crypto gave the same smoothness with more return.
  This is a point comparison, not a tested finding.
- **CAN'T TELL:** the data cannot separate these.

**The honest limit.** On the synthetic markets this test does **not** confirm an edge more often than today's test.
It passed on 1 of 65 made-up markets with an edge, against 4 of 65 for today's test. The reason is size: on those
markets the rule's down days were typically only about 0.6-5% smaller than the plain mix's, and five years of data
cannot see a cut that small. Where the rule steps back a lot, the noise is larger still. There, the test needs a cut of about 13% to
see it half the time, and about 19% to see it 80% of the time. On the 10 made-up markets where the measured cut was about
10% or more (V ≤ −0.10), it confirmed 1.

What it does add is a "no" that carries information. On 120 synthetic markets with no edge, it said "no noticeable
ride advantage" 115 times, and its main test never passed. Most of those markets were easy cases, though, well inside
"no edge". At the hard boundary, the main test's false-alarm rate was 3.6% (range 1.5-8.1%) in one construction. The
follow-up's own pre-check must confirm the rates on harder cases before any real number (section 3.13).

---

## 2. Why the pre-registered test has little power

**The A0 pre-check** (synthetic only; `controls.json` in the session's `a0-downvol/`):

| Control set | Result |
|---|---|
| 20 positive panels (volatility clustering and regimes; searched rule) | E1 held on 5, E2 on 1, P on 19; **all three on 1 of 20** (the plan wants 4) |
| 20 negative panels (the same markets shuffled, no clustering) | E1 0, E2 0: **0 false positives** (the alarm is 3) |
| 200 GARCH panels (clustering, constant drift, no momentum; fixed rule 30, 0.60, 0.50) | E1 held on 17 of 200 (8.5%) |
| vol-steady, the sister study, for comparison | power 3 of 20 |

A note on names: **E2 compares S with N0** (the same share held all the time), in the code
(`T.e2_test(b["S"], b["N0"])`) and in TP section 11. X, the exposure-matched static mix, is the comparator of E3
only.

**Why the power is low.** Four reasons, measured on the synthetic panels:
1. **Sharpe is dominated by noise in the mean return.** Across the shifted schedules, the yearly mean return varied
   with a standard deviation of about 2.7-4.4 points (mechanism design). Volatility timing changes the second moment
   (the size of moves), not the first.
2. **E2 mixes exposure with timing.** N0 holds more crypto than S, so E2 asks a different question from "better than
   holding less".
3. **The effect at the same exposure is small on these generators, and the noise is not.** The median log cut in
   downside deviation against the matched mix was 1.2% on A0's positive panels, 4.6% on 20 fresh positive panels and
   0.6% on 25 GARCH panels. On those three sets the median bootstrap standard deviation of that log cut was 0.045-0.055
   (0.028-0.044 on the null sets). But the noise grows with how much the rule steps back: on the 10 non-null panels
   with a measured cut of about 10% or more (V ≤ −0.10) it was 0.068-0.13 (median 0.084). At 0.084 a one-sided 5% test needs a log cut of about 0.14 (a 13% cut) for
   50% power and about 0.21 (19%) for 80%. This is arithmetic about five years of data, and no choice of statistic
   removes it.
4. **The search is not the main cost.** With the fixed rule on today's layout, E1 held on 5 of 20 and E2 on 1 of 20,
   the same as the searched rule (data design).

**A bias to flag to run 0's auditor (run 0 itself stays unchanged).** E3 compares S's falls (max drawdown and the
Monte Carlo 5th percentile) with the plan's X. X buys at t0 and then only fixes limits, so its crypto weight drifts up
in rising markets. That makes S look less risky than it is. Measured on E3's own statistics, with the fixed rule
(the critic's `e3_check.json`):
- On 20 iid random walks with no edge, E3 against the plan's X held on **8 of 20**. With the weekly re-cut X_w in X's
  place it held on 1 of 20.
- On 10 shuffled synthetic markets: 1 of 10 against X, 0 of 10 against X_w.

The draft's downside-deviation comparison against X showed the same bias (S "significantly smoother" on 15 of 20
random walks, 8 of 20 fresh shuffled panels and 2 of 20 of A0's shuffled panels). Run 0's E3 is a known bias in S's
favour, and its audit should read it that way.

---

## 3. The recommended follow-up

### 3.1 The question

At the same average crypto, after costs, does the rule's wallet have **smaller down days** than a plain mix that holds
that crypto steadily? Is the gain **timing rather than luck**? And is the rule **not beaten** by simply holding less
crypto?

This is a different claim from run 0's. Run 0 asks whether the rule gives a better risk-adjusted return than holding
(Sharpe). The follow-up asks whether it gives a smoother ride than holding less crypto.

### 3.2 The rule: no change, no new search

- **Which S.** The seed-A S of downvol-steady's reported run under stop rule 18. The per-fold L, τ and s are read
  from that run's logs, and S is recomputed deterministically. **R_0** and its **207 guarded q-only shifts**
  (amendment M1) are rebuilt the same way.
  - If an amendment run with trigger (a)-(c) supersedes run 0, its seed-A S is used.
  - If an amendment run with trigger "other, after the verdict" is reported beside run 0 (`combine_reported`), the
    follow-up runs on each reported run's seed-A S. It reports PASS only if every one of them gives PASS. Otherwise it
    reports each run's label side by side and makes no ride claim.
- **If run 0 has no S** (INCONCLUSIVE, crashed or stopped on a consistency check), the follow-up is void and does not
  run.
- There are no new Optuna trials and no new selection, so the follow-up adds nothing to the trial count. It is a
  second, pre-registered reading of run 0's own out-of-sample schedule.
- Seed B's S gets the same numbers as a fragility description (E5-style). It decides nothing.
- A known weakness: run 0 searched on Sharpe, and the follow-up judges by downside deviation. The search did not aim
  at what is tested, and that costs power. Re-searching on the new statistic was rejected: it would mean new trials on
  train years that vol-steady and downvol-steady have already read.

### 3.3 The comparator X_w: the same average crypto, held steadily

- **Per fold i:** targets = X's targets (TP section 9): S's realised mean BTC and ETH weights over fold i's kept
  closes, with X's clipping rule.
- **Start:** from S's book at t0_i. Before t0_i it follows S's own targets, so the book at t0_i is S's (stop rule 14:
  same book at t0, asserted).
- **Re-cut:** to its targets at t0_i and at **every Monday check close** after it. Limit fixes as usual. Costs on, the
  same cost model as S. At 2x, X_w is built from S at 2x (its book and its realised mean weights).
- **Kept rows:** the 1820 kept rows, stitched.
- **Exposure tolerance (pinned):** X_w's realised mean crypto weight must be within 0.01 of S's over the kept rows,
  and within 0.02 in every fold, or the run stops (a consistency stop). In the checks the span difference was at most
  0.0043 (on random walks; 0.0023 on A0's positive panels). By fold it was measured only on the verifier's 140 panels,
  where it reached 0.0071.
- **X_w is an ex-post reference, not a tradable rule.** Its targets are S's mean weights over each fold, which are known
  only at the fold's end. It is a benchmark, never a signal, so hard rule 4 does not apply to it. Its
  tamper-the-future test holds the targets fixed as inputs and tampers only the prices.
- **A known side effect.** X_w re-cuts every Monday; S trades only when its share changes or a limit breaks, and
  drifts in between. So V carries a small penalty for S's drift that has nothing to do with timing (the verifier
  measured V of about +0.017 on uninformative schedules that rarely step). This costs some power and means a label
  mixes timing with rebalancing frequency. A variant of X_w that trades only on S's fill closes is a description
  (3.9).

**Why this comparator, and not the others:**
- **The plan's X** drifts, which is the bias in section 2.
- **N0** holds more crypto than S.
- **The app's hold-this-mix tool** (relative band 0.30, 15-day wait) is not exposure-matched. Against it a
  shuffled-market control gave a false pass (statistic relevance judge, panel j = 9).
- **A span-wide X_Q** ("set your share lower once": every fold at s_i × κ, with one κ for the whole span) counts
  year-scale step-downs as timing, which a 60-day block bootstrap controls poorly. On these panels it gave the same
  PASS counts as X_w (1, 0 and 0, plus one DOMINATED). It is kept as a description.

### 3.4 The statistic

**DD(r) = √(mean of min(r_t, 0)²)**: the downside deviation around zero of daily net returns over the 1820 kept rows.
In plain words: the typical size of the down days. It is the rule's own measure, applied to the wallet.

**V = ln DD(S) − ln DD(X_w).** V < 0 means smaller down days than the plain mix. V = −0.105 is a 10% cut.

### 3.5 The decisive tests

| Test | Rule | Luck control |
|---|---|---|
| **RISK-X** (the app question) | V < 0 **and** p < 0.05 | One-sided paired stationary bootstrap (resampling blocks of days, the same blocks for S and X_w): mean block 60, 10,000 resamples, seed 0, p = (1 + #{V* ≥ 0}) / 10,001 |
| **RISK-E1** (the timing is not luck, at matched exposure) | rank p = (1 + #{u : V_u ≤ V_0}) / 208 < 0.05, i.e. at most 9 of the 207 shifts at or below R_0; ties count against R_0 | M1's q-only shifts u = 53..259 (E1's **one-sided** lead guard; a two-sided guard raised false positives on persistent nulls 1.2-1.9 times, mechanism validity judge's `guard_check.json`), each against its own matched mix (below), from S's book at 1x |
| **P** | As run 0: at least 20 share changes, in at least 4 folds | Information floor |

**RISK-E1 is exposure-neutral (pinned).**
- For R_0 (u = 0) and each guarded shift u, build its own matched mix X_w(u) over R_0's span:
  - before the first fold's t0, the series' own targets (so the book at t0 is the series' book);
  - from each fold's t0, the series' realised mean BTC and ETH weights over that fold's kept closes (X's clipping
    rule);
  - re-cut at each fold's t0 and at every Monday check close after the first t0, plus limit fixes, with costs on at
    1x.
- V_u = ln DD(series u) − ln DD(X_w(u)) on the 1820 kept rows. The rank compares V_0 with the 207 V_u.
- **Why.** A shift moves the step-backs to other weeks. When s differs by fold, that also changes how much crypto the
  shift holds on average. The first draft ranked plain DD, which then rewards holding less crypto as if it were timing
  (5 of 16 false positives in the critic's check; section 4.5). Comparing each series with its own matched mix takes
  the exposure out.
- V_0 is R_0 against a mix built over its whole span, so it differs slightly from RISK-X's V (S against per-fold mixes
  started from S's book at each t0).
- The largest gap between a series' realised mean crypto weight and its matched mix's is reported, for all 208.

### 3.6 The guards (each can stop a PASS; none can make one)

- **Not dominated (point estimate):** Sortino(S) ≥ Sortino(X_w), with Sortino = 365 × mean / (√365 × DD). For a
  constant mix this is about the same as asking whether S earns at least as much as the same mix scaled down to S's
  own downside risk. It answers the relevance judge's flaw in the statistic design: a GARCH panel (j = 24) that was
  smoother but beaten by holding less crypto. It is a point estimate: the return gap's noise is about 4-5 points a
  year, so near zero it is close to a coin flip.
- **Doubled costs (point):** V < 0 with S at 2x against X_w at 2x, and the Sortino guard at 2x.
- **Not one year (point):** V < 0 with each bar-year 2018-2022 removed. Downside deviation rests on a few crash days,
  mostly in 2018 and 2022.
- **The owner's boom-year rule (tested, 2026-11-21):** RISK-X and RISK-E1 must both still hold with BTC's best
  bar-year of the kept span removed, and again with its two best removed. Years are ranked by BTC's close-to-close
  return over each bar-year, as TP's E7 ranks them. Removing a year drops its returns from every series and every
  resample, and refits nothing.
- **Cost flag (reject-only):** with g = 365 × mean(S − X_w), a PASS is withdrawn if the same resamples show g
  significantly below −m: (1 + #{g* ≥ −m}) / 10,001 < 0.05, with **m = 2 points a year** (pinned, section 6). This flag
  can only show a clearly large cost. It can never show the cost is small.
- **Wallet size.** Everything is decided at run 0's reference wallet (10,000 USD). At 500 USD, V, g, the Sortino guard
  and the cost flag are reported as descriptions, with X_w's own cost next to g. In the critic's check (6 synthetic
  panels, fixed rule), X_w paid 0.8-2.2 points a year at 500 USD against S's 0.3-0.7, from gas on its small weekly
  legs. That moved g by 0.7-1.7 points a year in S's favour, about the size of m; V barely moved. At 10,000 USD the
  costs were similar (X_w 0.23-0.30, S 0.24-0.44).

### 3.7 The equivalence reading: making a "no" informative

**The equivalence reading** holds if the same resamples rule out a cut of δ or more in downside deviation:
(1 + #{V* ≤ ln(1 − δ)}) / 10,001 < 0.05, with **δ = 10%** (pinned, section 6). δ is the smallest cut a Steady user
would notice. The 10% is a proposal for the owner, not a finding.
- With RISK-X failing, it gives **NO NOTICEABLE RIDE ADVANTAGE**.
- With RISK-X holding, the cut is real but ruled out from reaching δ: **SMALLER, BUT BELOW NOTICE**, which is not
  offered (3.8).

### 3.8 The verdict

| Label | When |
|---|---|
| **PASS** (a smoother ride than holding less crypto) | RISK-X, RISK-E1 and P hold; the equivalence reading does not; not dominated at the point estimate, at 1x and at 2x; V < 0 at 2x and without each year; RISK-X and RISK-E1 hold without the best year and without the two best; no cost flag |
| **SMALLER, BUT BELOW NOTICE** | RISK-X, RISK-E1 and P hold, and so does the equivalence reading. Not offered |
| **DOMINATED** | RISK-X, RISK-E1 and P hold, the equivalence reading does not, and Sortino(S) is below the matched mix's at 1x (a point estimate, not a tested finding) |
| **NO NOTICEABLE RIDE ADVANTAGE** | RISK-X fails and the equivalence reading holds |
| **CAN'T TELL** | Everything else, including a result that fails only a robustness guard |

MISSING (a NaN, a failed run) is never a pass.

**False alarms.** A PASS needs every part to hold, so its false-positive rate is at most the size of a decisive part
whose null is true. For RISK-X that was 3.6% [1.5-8.1%] in one boundary construction (4.3); for RISK-E1, see 4.5. The
equivalence reading's error (saying "no" when the true cut is δ or more) is a separate error and is not bounded by
this: it was measured separately (4.4).

**App wording for a PASS** (only after a NautilusTrader rerun of every number in it, hard rule 3): "In 2018-2022, at
the same average crypto, its down days were N% smaller than a steadily held mix; it gave up about G points a year
(range a to b)."

### 3.9 Descriptions (decide nothing)

- X_Q (span-wide).
- X_w that trades only on S's own fill closes (removes the drift penalty of 3.3).
- The mix scaled down to S's own downside risk, run explicitly next to the Sortino guard.
- Max drawdown, the worst 30-day fall, weekly downside deviation and the Ulcer index (average drawdown depth), S
  against X_w. Max drawdown is a single path and too noisy to decide anything.
- The return gap g with its 90% interval, and each wallet's own cost.
- The 500 USD wallet (3.6).
- Binance folds 1-4 (point V).
- Each allowed s (0.30, 0.40, 0.50, 0.60) and the default: V, RISK-X's p and the guards at S(s_k). Whether the ride
  claim must hold across the allowed range is an owner question (section 6).
- Run 0's E1 and E2, and the first-draft RISK-E1 (the DD rank, section 4.5).
- The mechanism check: does the downside measure at a check close predict the next week's downside variance? This
  confirms the premise, and it is not evidence of an edge.
- The per-unit "re-matched" version of RISK-X. It is not calibrated (4.3).

### 3.10 How it combines with run 0

- **Run 0 decides its own claim** (better risk-adjusted return than holding) under its own plan, unchanged (M3).
- **The follow-up decides only the ride claim.** Neither study can upgrade the other.
- **Pinned: each claim is tested at 5%.** Across the two studies the chance of some false claim is then up to about
  10%. If the owner wants one 5% across both, the follow-up runs at 2.5% (Bonferroni), which costs power (section 6).
- **Desk-level multiplicity.** Seven studies have tested, or will test, Steady claims on the same 2018-2022 train rows
  (rebalance-steady, hold-mix-cap, trend-steady, protect-gains, vol-steady, downvol-steady, buy-the-dip). No single
  claim's 5% accounts for that; any write-up says so next to the result.
- An offer still needs the audit, the gates that apply (section 6 asks which), the validate look and paper.

### 3.11 The validate window

- **The follow-up does not read validate bars by itself.** Run 0's single look (E9) uses run 0's own
  `run_validate.py`, which is in run 0's config hash and stays unchanged, so the follow-up gets no numbers from it.
- **If the follow-up PASSes**, it may get one reject-only look on Kraken validate (546 kept rows), only with the
  owner's written approval. It fails if V(θ_final against X_w) ≥ 0 or the Sortino guard fails. That read is a separate
  validate look by this study family: it is logged in the README, the RUNLOG and the look table (hard rule 5).
- Prior looks at that window are disclosed: K4 (it is known to be a rising market), V3 (dip-timing's validate look),
  W2 (protect-gains' look V1), and run 0's own E9 if it ran. The test window is never read.

### 3.12 Data

- Kraken train: the 1820 kept rows of 2018-2022, from run 0's walk-forward. Binance as a description.
- No change to `config/splits.yaml`, `config/costs.yaml` or `config/risk_levels.yaml`. No new dependency (numpy only).

### 3.13 What is pinned now, before run 0 starts

1. **Everything in 3.2-3.11 as written,** with δ = 10%, m = 2 points a year, each claim at 5%, the exposure tolerance
   of 3.3, and the decisive form of RISK-E1 in 3.5. These are the proposals of section 6. The owner may change them;
   a change made after run 0 has started is an amendment that names run 0 as a prior look.
2. **Where the code lives.** A new folder `research/<follow-up>/` and a new module under `lab/runner/`. Until run 0's
   look is done or no look is earned, the follow-up touches **no file in downvol-steady's `frozen_paths()`** and does
   not edit downvol-steady's PLAN.md (M3). Otherwise run 0's config hash moves and `freeze.py` refuses an earned look
   (stop rule 10). That list is:
   - downvol-steady's PLAN.md and scripts;
   - `lab/__init__.py`, `lab/config.py`;
   - `lab/data/`: `__init__`, `catalog`, `external`, `futures`, `loaders`, `panel`, `sources` and `synthetic`;
   - `lab/runner/`: `__init__`, `downvol`, `interface`, `portfolio`, `reference`, `steady`, `trend` and `volsteady`;
   - every `.py` file in `lab/search/` and `lab/validation/` (globbed, so even a **new** file there moves the hash);
   - the config files, `pyproject.toml` and `uv.lock`.
   The new module must not be registered in `lab/runner/__init__.py`, which is hashed.
3. **The run protocol** (as run 0's): a start record and a RUNLOG line before any bar; a config hash over the new
   files; one run only, with amendment rules like run 0's; every evaluation logged as a row (X_w at 1x and 2x, each
   shift and its matched mix, X_Q, each S(s_k), the per-unit variant, Binance, the 500 USD wallet) and reported
   whatever the outcome (hard rules 7 and 8).
4. **The tests** (TESTING.md section 7): the X_w executor (same book at t0, by-hand weights on a built path,
   tamper-the-future with the targets fixed, the exposure tolerance), the statistics by hand (DD around zero, no √365
   in ratios, ties against R_0), every boom-year removal by hand, and every reported number recomputed from its inputs
   (hard rule 11).
5. **The follow-up's own A0, on NEW seeds** (synthetic only). None of the seeds in section 7 may be reused.
   - **Seeds (pinned), one disjoint range per generator,** because `synthetic_market(s)`, `shuffled_market(s)` and
     `random_walk_panel(s)` all draw from `default_rng(s)`, and `garch_panel(j)` from `default_rng(10000 + j)`:
     - `synthetic_market` 20000-20999;
     - `shuffled_market` 21000-21999;
     - `random_walk_panel` 22000-22999;
     - `garch_panel` j = 30000-30999 (its streams 40000-40999);
     - any other `default_rng` 60000-69999.
     Each set below takes its own sub-range, so no two sets share a market or a schedule. (The cross nulls of 4.5
     shared their price and schedule pairs across three layouts; the A0 does not.)
   - **The sets, 200 panels each:**
     - **RISK-X's size at its boundary:** the one-leg construction of 4.3, in four sets: GARCH and regime markets, each
       with one s and with s varying by fold.
     - **RISK-E1's size:** cross nulls (another panel's schedule on these prices) in four sets: one s; s and τ
       anti-paired across folds; s and τ co-paired; and schedules from real Optuna searches on synthetic panels, as
       run 0 makes them.
     - **The equivalence reading's error at δ:** the one-leg construction with the mix set so that the true cut is δ,
       in the same four sets as RISK-X, plus a set of schedules that step back a lot (bootstrap standard deviation about
       0.08 or more).
     - **Power, a description:** 40 positive panels (20 regime, 20 GARCH), searched as run 0 searches.
   - **Stop rule (pinned):** if any decisive error rate, in any set, is above 7.5% (more than 15 of 200), the follow-up
     does not run on run 0's S, and the owner is told. With 200 panels this stops the follow-up about 86% of the time
     when a rate is really 10%, about 43% of the time at 7.5%, and about 4% of the time at 5%. It cannot prove a rate
     is 5%. Nothing is redesigned after run 0 has been seen unless the redesign is labelled as informed by run 0.
   - **Report** to the owner, before the follow-up's real run: the share of positive and null panels that get a
     decided label, and the expected PASS power (about 0-1 in 20 here).
   - **Cost: about 5 CPU-hours** (about 2.5 hours on 2 workers), from this session's timings. Most of it is the 200
     searched schedules (about 0.9 CPU-minutes of search each, from A1). The RISK-E1 cross nulls take about 6.5
     CPU-seconds a panel (4.5), and the one-leg sets about half a second. That is over the 120 CPU-minutes that earlier
     A0s were held to, so the budget needs the owner's approval (section 6).
6. **The order of work:** this note committed now; then run 0 as pre-registered; then the follow-up plan, build,
   tests, tiers and A0; then the follow-up's computation on run 0's S.
   - *Considered and not taken:* writing the full follow-up plan and running its A0 before run 0. It needs no market
     data, so it would keep every calibration choice blind to run 0. It was not taken because it would delay run 0 by
     the build (about an agent-day) when the owner asked for run 0 now. Pinning every outcome-deciding choice here
     gives the decision rules the same blindness. The A0's numbers are synthetic and cannot depend on run 0. Its stop
     rule is pinned, so it can stop the follow-up but not reshape it.

---

## 4. The synthetic evidence

### 4.1 Script and settings

- **Main script:** `/tmp/claude-0/-home-user/45b9259c-cd7f-5869-8006-179fd7a14409/scratchpad/redesign/lead/recommended_check.py`
  (session scratchpad; not kept after the session).
  - Output: `.../redesign/lead/recommended_check.json`.
  - The first run with every shift computed is kept as `recommended_check_run1.json`. The second run added the
    per-unit variants and read the fresh panels' shift results (RISK-E1, E1, E2) from the first run. Its other
    numbers are identical to run 1's, which was checked.
- **Engine and comparator:** downvol-steady's own `study.plain_bundle` and `lab.runner.downvol`, `trend`,
  `volsteady`, with costs from `config/costs.yaml` at 1x and 2x. X_w as specified in 3.3.
- **Bootstrap:** mean block 60, **2,000 resamples** (the plan pins 10,000), seed 0 per panel. δ = 10%, m = 2 points.
- **Label names.** The scripts and their outputs call the equivalence label "NO MATERIAL ADVANTAGE"; this note renames
  it "NO NOTICEABLE RIDE ADVANTAGE" (the critic's wording). The rule is the same.
- **The first-draft RISK-E1 (DD rank)** on A0's 40 panels and the 25 GARCH panels was read from the statistic
  designer's `stage_searched.json` and `stage_garch.json` (reproduced bit for bit by the judges); on the 40 fresh
  panels it was computed here.
- **Panel sets:**
  - **A0 positive / negative:** A0's 20 + 20 panels with **A0's own searched per-fold parameters**.
  - **GARCH:** `trend.garch_panel(j)`, j = 0..24, the **fixed rule** (30, 0.60, 0.50).
  - **Fresh positive / negative:** `synthetic_market(2190, seed=3000+j, start 2017-01-02)` and their shuffles
    (seed 500+j), the fixed rule.
  - **Random walks:** `trend.random_walk_panel(j)`, j = 0..19.
  - **Cross nulls:** the fixed rule's targets from `garch_panel(300+j)` run on `garch_panel(j)`'s prices, j = 0..59.
- **Independent verification.** The verifier wrote its own script from this note and the lab's code, without reading
  or importing the designers' scripts. On A0's 40 panels it reproduced every count exactly (RISK-E1 8, RISK-X 1,
  PASS 1 at j = 11, 9 and 10 for the other labels; 0, 0, 0 and 20 on the negatives), and A0's own E1 rank p and E2 p
  on all 40 panels. It did not rerun the fresh, GARCH, random-walk and cross-null rows, the boundary sizes, X_Q or the
  drifting-X counts.

### 4.2 Power and false positives against today's test, on the same panels

"Today" means E1 & E2 & P, as A0 computes them. 95% Wilson intervals in brackets. A Wilson interval is the range of
true rates the count is consistent with. **These rows use the first-draft RISK-E1** (the DD rank); section 4.5 gives
the pinned, exposure-neutral form.

**The scripted verdict was simpler than 3.8.** `recommended_check.py` decided PASS from RISK-X, RISK-E1, P, the Sortino
guard at 1x, the cost flag, V < 0 at 2x and the leave-one-year-out check. It had no boom-year guard, no Sortino guard
at 2x and no SMALLER, BUT BELOW NOTICE label. None of that changes a count here:
- RISK-X held on one panel only (A0 positive j = 11), so the other panels cannot reach PASS, DOMINATED or SMALLER, BUT
  BELOW NOTICE.
- At j = 11 the fact-checker ran the missing guards. BTC's best bar-years there are 2022, then 2020. Without 2022,
  RISK-X gives V −0.198 (p 0.0095); without 2022 and 2020, V −0.246 (p 0.010). The exposure-neutral RISK-E1 gives
  p 0.0048 in both. The Sortino guard at 2x holds. The equivalence reading does not hold (V −0.130 against a bootstrap
  standard deviation of 0.068).
- No panel had RISK-X and the equivalence reading both holding.

| Panel set | Today: all three (E1 alone) | RISK-E1 (draft) | RISK-X | **PASS** | NO NOTICEABLE ADV. | CAN'T TELL |
|---|---|---|---|---|---|---|
| A0 positive, searched (20) | 1 (E1 5) | 8 | 1 | **1** [1-24%] | 9 | 10 |
| Fresh positive, fixed (20) | 3 (E1 8) | 6 | 0 | **0** [0-16%] | 6 | 14 |
| GARCH, fixed (25) | 0 (E1 2) | 17 | 0 | **0** [0-13%] | 16 | 9 |
| A0 negative, searched (20) | 0 | 0 | 0 | **0** | 20 | 0 |
| Fresh negative, fixed (20) | 0 | 0 | 0 | **0** | 20 | 0 |
| iid random walks, fixed (20) | n/a | n/a | 0 | **0** (RISK-X needed) | 20 | n/a |
| Cross nulls (60) | n/a | n/a | 0 | **0** (RISK-X needed) | 55 | n/a |

(Column "NO NOTICEABLE ADV." is NO NOTICEABLE RIDE ADVANTAGE.)

Read together:
- **Power for the app question is not higher than today's.** PASS: 1 of 65 positive and GARCH panels (A0 j = 11).
  Today's test: 4 of 65.
  - On the fresh positive panels today's test held on 3 panels where RISK-X did not (V −0.03 to −0.12, p 0.07-0.32).
    There the rule beat always-in on Sharpe partly because it held less crypto.
  - The two tests answer different questions and confirm different panels (today's passes A0 j = 16, where RISK-X's
    V −0.115 has p 0.101). With 20 panels nothing separates 0, 1 and 3 in 20.
- **The no-edge evidence, honestly scoped.**
  - RISK-X held on 0 of 120 null panels [0-3.1%], and the verifier found 0 of 100 more (iid Student-t walks, regime
    cross nulls, and cross nulls nearer the boundary). But every null set had a median V above zero: +0.030 to +0.073,
    deep inside the null, and +0.017 on the verifier's near-boundary set (about half a bootstrap standard deviation
    from zero). So this says little about the rate at the boundary (4.3 does that).
  - PASS held on 0 of 40 null panels where every label was computed. Those are shuffled panels, where the draft RISK-E1
    is conservative (mean rank p about 0.8). On persistent nulls the draft RISK-E1 held on 7 of 90 with one s (7.8%,
    Wilson 3.8-15.2%; statistic validity judge) and on 5 of 16 with s varying by fold (the critic). That is why 3.5 pins
    another form.
  - On one of the verifier's 20 regime cross nulls, today's test gave a false positive; the ride test gave none.
- **A "no" carries information, within limits.**
  - NO NOTICEABLE RIDE ADVANTAGE on 115 of 120 null panels [90.6-98.2%].
  - On 15 of 40 positive panels and 16 of 25 GARCH panels. There the measured cut was small or absent: on the panels
    with this label, median V +0.007 (A0 positive, 9 panels), −0.004 (fresh positive, 6) and +0.004 (GARCH, 16). Some of them had strong timing evidence (A0 j = 8 at a draft RISK-E1
    p of 0.005, j = 13 at 0.014): the label means "no noticeable ride advantage", not "no timing".
  - Only 3 (A0 positive), 4 (fresh positive) and 3 (GARCH) panels had V of −0.10 or below, a cut of about 10% or
    more. RISK-X held on 1 of those 10, with bootstrap standard deviations of 0.068-0.13.
- **The guards:**
  - Not dominated on 11 and 13 of 20 positive panels, but only 5 of 25 GARCH panels. GARCH's constant log drift makes
    stepping back give up return: the median gap to X_w there was −5.1 points a year.
  - The cost flag (m = 2) fired on 3 of 25 GARCH panels, 1 of 20 fresh positive panels and 0 of 20 A0 positive
    panels. On the null sets: 0 (A0 negative), 1 (fresh negative), 1 (random walks) and 6 of 60 (cross).

### 4.3 Is RISK-X's p-value honest at its boundary?

**What a "boundary" is.** The no-edge panels above sit deep inside the null, because a moving share is riskier than a
steady one (Jensen's inequality). The harder case is a rule whose timing gain exactly offsets that penalty. Two checks
were run (scripts and outputs in `.../redesign/lead/`):

- **One leg** (`boundary_one_leg.py`; 1,000 resamples).
  - **Construction:** a persistent schedule that carries no information (the fixed rule's steps from another panel)
    against a re-cut mix at its root-mean-square weight. Here the expected V is 0; measured, the mean V was 0.0005.
  - **Panels:** 40 GARCH + 30 regime panels, both tails counted.
  - **RISK-X as recommended rejected 5 of 140 one-sided tests (3.6%) [1.5-8.1%].** Its bootstrap standard deviation
    (0.043) was close to the real spread across panels (0.047). Blocks of 120 and 250 days gave 3.6% and 5.0%.
  - The critic repeated it with s varying by fold (70 panels, 2,000 resamples): 1 of 140 one-sided tests. That set sat
    slightly inside the null (mean V +0.011), so it is an easier case than the lead's.
  - Limit: these are low-activity schedules (bootstrap standard deviation about 0.042-0.048). Schedules that step back
    a lot are noisier, and the A0 must cover them (3.13).
- **The per-unit "re-matched" version.** This divides each wallet's downside by its mean crypto weight *inside every
  resample*; the user design and the statistic validity judge suggested it.
  - Its power looked better: RISK-X 2, 5 and 3 (against 1, 0 and 0); and 4, 12 and 8 with X_Q.
  - **It is not honest at the boundary:** 15 of 140 (10.7%) [6.6-16.9%] in the one-leg check. Its bootstrap standard
    deviation (0.028) was about 60% of the real spread (0.046).
  - The symmetric two-schedule check (`boundary_check.py`, 2,000 resamples, 60 GARCH + 40 regime triplets) agreed:
    22 of 200 (11%) [7.4-16.1%].
  - So most of its extra power came from understating the noise. **It is not adopted.** This also suggests that the
    user power judge's bootstrap figure (4 of 20, which re-matched per unit) is optimistic.

### 4.4 The equivalence reading at its boundary

The critic measured it (`critic-completeness/eq_boundary.py`, 2,000 resamples): the same one-leg construction with the
mix set so that the true cut is about 10% (mean V −0.102 with one s; −0.094, about 9%, with s varying by fold). The
reading wrongly said "no noticeable advantage" on 2 of 70 panels with one s (2.9%, Wilson 0.8-9.8%) and on 0 of 70
with s varying by fold, which was the easier point. This roughly supports the 5% level, in one
construction and for low-activity schedules only. The A0 must confirm it where the rule steps back a lot.

### 4.5 RISK-E1 made neutral to exposure

**Why.** The critic found that the first-draft RISK-E1, the plain rank of DD(R_0) among the shifts, is not neutral
to exposure when s differs by fold. On cross nulls (another panel's schedule run on these prices) with s and τ
anti-paired across folds, it held on 5 of 16. Across the shifts, DD rose with the shift's mean crypto weight (median
correlation 0.63).

**The check** (`.../redesign/lead2/e1_neutral.py`; outputs `e1_neutral.json` and `e1_neutral_one.json`; 3 workers,
about 20 CPU-minutes). It ran the exposure-neutral form of 3.5, the draft DD rank and run 0's Sharpe E1 on the same
runs:

| Panel set | Exposure-neutral RISK-E1 | Draft RISK-E1 (DD rank) | E1 (Sharpe rank) |
|---|---|---|---|
| Cross nulls, s and τ anti-paired across folds (40) | 3 [2.6-19.9%], mean p 0.53 | 11 [16.1-42.8%], mean p 0.29 | 3 |
| Cross nulls, s and τ co-paired (24) | 0 [0-13.8%], mean p 0.45 | 0, mean p 0.83 | 0 |
| Cross nulls, one s (40) | 2 [1.4-16.5%], mean p 0.50 | 3 | 1 |
| A0 negative, searched (20) | 0, mean p 0.55 | 0, mean p 0.79 | 0 |
| A0 positive, searched (20) | **11** [34-74%] | 8 | 5 |
| GARCH, new seeds, fixed rule (20) | **10** [30-70%] | 10 | 2 |

The cross nulls use the critic's construction and the critic's per-fold (s, τ): anti-paired s 0.30/0.60/0.35/0.55/0.45
with τ 1.0/0.40/0.90/0.50/0.60; co-paired with each fold's s swapped so that high s goes with high τ (0.60/0.30/0.55/
0.35/0.45); and the fixed rule for one s. **The three cross-null sets are not independent:** they share 40 price and
schedule pairs (prices `garch_panel(8000 + j)`, schedules `garch_panel(8100 + j)`) under three (s, τ) layouts, and
anti-paired j = 0..15 are the critic's own panels, where the problem was found. So the counts are per set, not pooled.
Read together:
- **About the right size, per set.** It held on 3 of 40, 0 of 24 and 2 of 40, and its mean rank p was about 0.5 in
  every null set, as an honest test's should be. The draft DD rank was biased both ways: mean p 0.29 when
  s and τ are anti-paired, 0.83 when co-paired.
- **Exposure taken out.** Across the shifts, V barely moved with the shift's mean crypto weight (median correlation
  −0.18 to 0.00), against 0.42-0.69 for DD.
- **Power kept:** 11 of 20 on A0's positive panels and 10 of 20 on new GARCH panels.
- **The weakest point** is the anti-paired set (3 of 40, 7.5%): its interval includes 5% but also 20%. The A0 must
  measure it on 200 panels of its own (3.13).
- **The PASS counts of 4.2 do not change.** A PASS also needs RISK-X, which held on only one positive panel (A0
  j = 11) and on no null panel. At j = 11 the exposure-neutral RISK-E1 also holds (p 0.005). DOMINATED needs RISK-X
  too, and the other labels do not read RISK-E1.

### 4.6 Caveats

- **Small samples.** 20-40 panels per set, so every count has a wide binomial band.
- **Fixed and searched rules are mixed.** The A0 sets use A0's searched parameters. The GARCH, fresh and null sets use
  the fixed rule. The follow-up runs on run 0's searched S.
- **2,000 resamples, not 10,000** (Monte Carlo error in p near 0.05: about ±0.005). The boundary checks used 1,000 or
  2,000.
- **Selection on synthetic data.** The statistic, comparator and guards were chosen by people who had looked at A0's
  panels. The fresh seeds and the boundary checks are partial protection only. The follow-up's A0 must use new seeds.
- **The generators build in the mechanism.** The positive panels tie wild markets to falling ones. GARCH has clustering
  with a constant drift, which penalises stepping back. Real crypto may differ either way.
- No real data, no Nautilus engine, placeholder costs.
- **Compute:** about 9.4 CPU-minutes for the main and boundary checks in one process; the verifier about 5.6; section
  4.5 about 20; the critic's checks a few more.

---

## 5. The alternatives, and why they ranked lower

**"Statistic" (the base, judges 6/5/5).** RISK-E1, RISK-X against X_w, a COST guard and P. It is kept as the base.
- The relevance judge's flaw: the COST guard ("no significant return loss") let a dominated rule through (GARCH
  j = 24). It is replaced by the not-dominated guard and a reject-only cost flag with a fixed margin, as the validity
  judge asked.
- The power judge's equivalence reading and the validity judge's boundary calibration are added.
- Its scratch X_w (its own book from row 0, every 7 rows) is replaced by the specified one. Results agree: A0 positive
  j = 16 gives p 0.101 in both.

**"Data" (fixed rule, whole span, hold-this-mix comparator; judges 5/3/6).**
- The power judge's flaws: the comparator it proposed was never run, and with it E2 held on 1 of 20 positive panels
  against 3 of 20 negatives. It cannot tell positives from negatives, and its 4-5 of 20 came from a held N0 that
  drifts.
- **Kept from it:** the comparator must rebalance; the correction that E2 compares with N0, not X; and the warning that
  the comparator choice moves results more than extra data does.
- **Not kept:** the whole-span, fixed-rule layout. It adds 19% more rows and about 8% less noise, at the price of a
  rule chosen without data.

**"Mechanism" (premise, then risk, then cost; judges 4/3/4).**
- Flaws: its synthetic check never ran the stage that answers the app question (when the judges ran it, it held on 0 of
  20); its two-sided shift guard raised false positives on persistent nulls (1.2-1.9 times the one-sided guard's); its
  headline power came from stages that confirm volatility clustering, not usefulness.
- **Kept from it:** the premise check as a description only; the drifting-X warning for E3; the one-sided guard.

**"User" (RIDE: volatility per unit of crypto; judges 5/4/4).**
- Flaws: its top label "smoother at little cost" rested on a point check of cost with no luck control, which passed on
  23% of GARCH panels whose true cost was about 6 points a year; its comparison with the twin had no significance test
  (with one, 4 of 20, and 4.3 shows that figure is optimistic); a rule that steps back after big *up* days passed it
  too.
- **Kept from it:** the verdict ladder and the honest "cost not established" wording.
- **Tested and not adopted:** its per-unit idea.

**Variants inside the winner, not adopted:**
- X_Q as the decisive comparator: it credits year-scale step-downs that a 60-day block bootstrap controls poorly, and it
  gave the same PASS counts.
- Total volatility instead of downside deviation: it penalises the rallies the rule deliberately stays in, and it
  barely moved RISK-X (1-2 of 25).
- Dropping RISK-E1: it cost no PASS here, and it is the only luck control at the scale of years.
- The first-draft RISK-E1 (the plain DD rank): not neutral to exposure (4.5).

**Alternatives the critic raised, not taken, with reasons:**
- **Pre-2017 history** (Kraken BTC from 2013): more crash episodes, which is what the noise in DD needs. It needs the
  owner's approval to change `config/splits.yaml`, and ETH's history is shorter. Left for the owner (section 6).
- **A path-based ride statistic** (weekly downside deviation, the Ulcer index, CDaR): closer to "smaller falls", but
  untested here; reported as descriptions (3.9), not decisive.
- **A tradable "set less crypto in advance" comparator** (κ from information at t0): a description at most; the
  decisive question is about timing at the same exposure, which needs the ex-post match.
- **The ride test on vol-steady's S:** post hoc, because vol-steady run 0 (W1) has been seen. Not done.

---

## 6. What needs the owner, and the cost

**Pinned now at the proposed values** (section 3.13). The owner can change them; a change after run 0 has started is
an amendment that names run 0 as a prior look.
1. **The claim.** "A smoother ride than simply holding less crypto" as a separate claim for this rule family, next to
   run 0's "better risk-adjusted return", with its app wording (3.8).
2. **δ = 10%,** the smallest noticeable cut in down-day size.
3. **m = 2 points a year,** the cost margin of the reject-only flag. Five years cannot prove a cost is small: the
   return gap's noise is about 4-5 points a year (median bootstrap standard deviation 3.7-4.8), so the flag fires only
   when the measured cost is about 8-10 points a year or worse.
4. **Each claim at 5%** (3.10), or one 5% across both (the follow-up at 2.5%).
5. **The A0 stop rule** (3.13 item 5: more than 15 of 200 in any set) and its fallback (the follow-up does not run).

**Questions only the owner can answer** (none blocks run 0):
6. **Which gates apply to an offer based on the ride claim.** AGENTS.md's gates include a walk-forward Sharpe of at
   least 1.0 after costs, and a better risk-adjusted return than buy-and-hold BTC and the 50/50 rebalance (G1 and G7 in
   trend-steady's numbering). A de-risking rule that passes the ride test would almost
   certainly fail them. Keeping them means a ride PASS cannot become an offer on its own; changing them is a gate
   change, which only the owner can make.
7. **The settings range.** AGENTS.md's "Settings ranges" approve a range of user choices, not one point. Should the
   ride claim have to hold at every allowed s and at the default? Pinned for now: decisive only at the walk-forward S,
   with each S(s_k) and the default reported (3.9).
8. **Whether to build it at all.** Expect PASS power of about 0-1 in 20 on these synthetic markets. The likely
   informative outcomes are NO NOTICEABLE RIDE ADVANTAGE or CAN'T TELL.
9. **The validate look** (3.11): whether a follow-up PASS gets its own reject-only look.
10. **More history** (section 5): whether pre-2017 data is worth a change to the splits.
11. **The A0's budget:** about 5 CPU-hours on this machine (3.13 item 5), over the 120 CPU-minutes earlier A0s were
    held to.
12. **Not needed:** no change to splits, costs or risk levels; no new dependency; no paid compute.

**Cost:**
- On run 0's data: X_w at 1x and 2x (10 executor runs), R_0 and its 207 shifts with their matched mixes (about 420
  executor runs), and the bootstraps. **A few CPU-minutes.**
- Its synthetic A0: about **5 CPU-hours** (section 3.13 item 5), mostly the 200 searched schedules. That is over the
  120 CPU-minutes earlier A0s were held to.
- The build: the X_w executor, the statistics, the labels and their tests, about one agent-day, then the three tiers.

---

## 7. Prior looks

- **This note was written and committed before downvol-steady run 0 read any market bar.** No market data was used.
  Nothing under `data/` or `results/` was read, and no catalog loader was called. Nothing inside the repo was written
  except this note. All checks ran in the session scratchpad.
- **Read:**
  - `CLAUDE.md`, `AGENTS.md`, `TESTING.md`.
  - `research/downvol-steady/PLAN.md` (which discloses W1 and the finding behind M1).
  - The comparator and criteria rows of `research/trend-steady/PLAN.md` (sections 9 and 11, by search), its prior-look
    table (K1-K12) and E7's year ranking; the prior-look table of `research/vol-steady/PLAN.md` (V1-V6), by search.
  - Code: `research/downvol-steady/controls.py` and `study.py`, `lab/runner/trend.py`, `downvol.py`, `volsteady.py`,
    `portfolio.py`, `reference.py`.
  - `reports/director/2026-11-24-owner-answer-downvol-a0-power.md` and `2026-11-21-boom-check.md`.
  - A0's synthetic `controls.json`; the designs', judges', verifier's and critic's scratch scripts and outputs.
  - `config/costs.yaml` and `config/risk_levels.yaml`, read by the code.
- **Not read:** any study's RESULTS.md, AUDIT.md, VALIDATE.md, RISK.md, summary.json, decision.json, runs.csv or
  falls.csv; vol-steady's PLAN.md beyond its prior-look rows; the "Hold this mix" section of `docs/app/features.md`.
- **For the later plan's disclosure**, the prior looks at these train years and windows:
  - Carried over: TP's K1-K12 (K1, general knowledge of the 2018 and 2022 crashes, is used here for the
    leave-one-year-out guard; K4 describes validate as a known rising window) and VP's V1-V6 (V2, the falls of held
    mixes by crypto share, bears directly on the "hold less crypto" comparator; V3 is dip-timing's validate look).
  - W1 (vol-steady run 0) and W2 (protect-gains' validate look V1), from downvol-steady's PLAN.md.
  - vol-steady's AUDIT findings 1-2, which led to M1.
  - downvol-steady run 0, and buy-the-dip run 0 if it runs before the follow-up.
- **Synthetic seeds already looked at** (the follow-up's A0 must not reuse any):
  - A0's: `synthetic_market` 1000-1019 and their shuffles (seeds 0-19); `garch_panel` 0-199.
  - The designs and judges: `synthetic_market` 3000+j, 4000+j, 5000+j and 6000+j (shuffles 100+j and 500+j);
    `garch_panel` 300+j, 400+j and 600+j; `random_walk_panel` j, 100+j, 200+j and 500+j (for the j each script ran).
  - The verifier: `synthetic_market` 9100-9219 and 9300-9459; Student-t walks from `default_rng(91000 + j)`,
    j = 0..19.
  - The judges, beyond the designs' seeds (the fact-checker's grep): `synthetic_market` 1020-1799 with shuffles
    20-299 (`data/power_null.py`, `judge-data-power/e2_holdmix.py`, `judge-mechanism-validity/guard_check.py`,
    `validity_check.py`); `garch_panel` 200-299 and 500-799 (`guard_check.py`); `default_rng(50000 + rep)`, rep
    0..199 (`judge-statistic-validity/check_b_boundary.py`), and `default_rng(50000 + s)`, s 0..19
    (`judge-user-validity/null_check.py`).
  - The critic: `garch_panel` 8000-8019, 8100-8119, 8200-8201, 8300-8339, 8400-8439; `synthetic_market` 9500-9503,
    9600-9609 (shuffled with seeds 9700-9709), 9800-9829, 9900-9929; `random_walk_panel` 700-719.
  - Section 4.5: `garch_panel` 8000-8039 (prices), 8100-8139 (schedules) and 8700-8719, and A0's 40 panels.

---

## 8. Review: what the verifier and the critic found, and what changed

- **Fact-check of the revision** (an independent agent, against every output file): every number it recomputed
  matched, except 22 problems it listed, all fixed here. They were mostly wording and figures (the exposure gaps, the
  noise ranges, a Wilson interval, the cost moves, which panels a median covers). The ones that changed the design:
  - the A0's cost was understated (now about 5 CPU-hours, an owner question);
  - the A0 stop rule could not confirm 5% (now more than 15 of 200, with its odds stated);
  - the A0 seed ranges let generators share a stream (now one range per generator);
  - the three cross-null sets of 4.5 shared their markets (no longer pooled);
  - a cut that is significant but below δ had no label (now SMALLER, BUT BELOW NOTICE);
  - the "other" amendment case of stop rule 18 needed its own rule for which S (3.2);
  - the hashed-file list was incomplete (3.13 item 2).
  It also confirmed, at A0 positive j = 11, that the guards the scripted verdict lacked do not change the one PASS
  (4.2).
- **Verifier: reproduced.** Its own script matched every A0-panel count and A0's own E1 and E2 p-values (4.1). It
  flagged: the null evidence sits deep inside the null; V carries a drift penalty (3.3); "no noticeable advantage" can
  sit next to timing evidence (4.2); X_w at 2x needed pinning (3.3); and its new seeds (section 7).
- **Critic, and the fixes:**
  - The draft RISK-E1 was not neutral to exposure when s differs by fold (5 of 16 false positives): replaced by the
    exposure-neutral form, checked in 4.5.
  - The owner's boom-year rule was missing: added as a guard (3.6).
  - The "can see a 10% cut" claim was too strong: replaced by the measured figures (sections 1 and 2).
  - "No false PASS" overclaimed: scoped (4.2). DOMINATED and "not dominated" are labelled point estimates (3.8). The
    intersection sentence now bounds only PASS (3.8).
  - The E3 bias is now a measurement, not an inference (section 2).
  - Hashed files, the validate window and hard rule 3: 3.13 item 2, 3.11 and 3.8.
  - Open choices (δ, m, the combination, the exposure tolerance, the A0 stop rule and fallback, which S): pinned now,
    before run 0 starts (3.13).
  - The run protocol, the wallet-size check, the gates and settings-range questions, the A0 cost, the prior looks and
    the alternatives not weighed: added (3.13, 3.6, section 6, section 7, section 5).
  - *Not taken:* moving the full plan and its A0 before run 0 (3.13 item 6 says why).

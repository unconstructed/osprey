# Director proposal: adjustable strategy settings (2026-11-20)

**Status: core APPLIED on 2026-11-20 with the owner's approval ("yes to 1").**
- **Owner's words (chat, 2026-11-20):** "yes to 1, go with the simple tool for 3". The numbers refer to the owner's chat
  summary, not to section 9: summary 1 = decision 1 (4.1-4.4 and 4.6), summary 3 = decision 5 ("hold this mix").
  Section 9's decision 3 (the Steady limits) is still open.
- **Applied:** sections 4.1-4.4 to AGENTS.md, as written, and the 4.6 edits to `.claude/agents/risk-officer.md`,
  `backtest-auditor.md`, `quant-researcher.md` and `research-methods.md`. 4.2 went in as written, so it includes the
  second paper model account at the riskiest combination; decision 2 can still drop that clause.
- **Small consistency edits made while applying** (not in the text below; none changes a threshold):
  - AGENTS.md: the opening paragraph says the pinned export configs carry each setting's default and approved range.
  - `risk-officer.md`: lists the ranges under "What you own" and in its description, which also says "paper model
    accounts". The export step points to the rest of AGENTS.md "Ready for production" (the limits as read, and both
    drawdowns for every combination). Step 1 adds AGENTS.md's conditions (the level's budget owner-approved first,
    earlier looks listed) and the owner's Steady trade guardrail (decision 10). A new rule restates AGENTS.md's
    narrowing rule: only to meet a risk limit, whole values from a setting's riskiest end, logged with the new edge's
    margin, the dropped combinations kept in the trial count, never to drop failing Sharpes, never after the test
    window opens. 4.6 had only the rule against widening, and the file's opening line lets the role tighten limits on
    its own. "Setting drawdown budgets" points to AGENTS.md's budget-first rule and to decision 11 (no method
    changed).
  - `backtest-auditor.md`: item 6 compares every grid step and each ±20% step from the default with S's Sharpe, as
    the 4.1 plateau row says, not with its own; fixed settings get θ_final's runs where the table names the default
    (4.1's last bullet), so the paragraph is now "Settings ranges and fixed settings". Each grid step's fixed run must
    pass the AGENTS.md walk-forward Sharpe gate, as its doubled-cost run must pass item 12 (4.1's first row; 4.6 named
    only item 12). The trial-Sharpe variance (item 8) and PBO (item 9) still come from the search's trials only (4.1's
    DSR and PBO row); item 9 said "across all trials", and grid runs are now logged trials, so it now says "all of the
    search's trials". The final step freezes the range before the test window opens and judges the default against S,
    every other grid step against its own fixed run (4.1's test-window row). The output adds the per-combination gate
    table, which the risk-officer's export reads its drawdowns from.
  - `quant-researcher.md` step 4: the allowed values are set before any search, pre-registered with the search box,
    and the search ranges must contain every allowed value (4.1, second bullet). `ml-researcher.md` gets the matching
    rule, because the 4.4 handoff line names both researchers.
  - `research-methods.md`: stage 6 says "Paper model accounts", and the PBO row says "the search's trials". A note
    under the funnel says stages 3 and 5 also cover every grid step. Live strategy-card figures come from the model
    account "at the default settings" (decision 2 may add a second one). "Risk-level budgets" points to AGENTS.md's
    budget-first rule and says the first budget is open (decision 11).
- **Not applied, still proposals:** 4.5 (hard rule 12) and section 7 (the stale AGENTS.md places).
- **Decided in section 9:** decision 1 (this approval), decision 5 ("hold this mix" is a self-directed tool, not one
  of our strategies) and decision 10 (Steady's trade guardrail caps the drift band and check frequency). The others are
  still open, including decision 11, added while applying.
- **Open, for the owner and `risk-officer` (found while applying; no method changed):** AGENTS.md now says a level's
  drawdown budget must be owner-approved before a range is pre-registered. But `risk-officer.md` ("Setting drawdown
  budgets") and `research-methods.md` ("Risk-level budgets") still take the budget from the Monte Carlo drawdowns of
  the level's audited strategies. A level's first study (Steady today) has none, so its budget has to come from
  somewhere else first, such as RISK.md's reference mix (section 3; PLAN.md section 9). Now decision 11.

When this proposal was written, nothing in it was in force. I edited no gate, threshold, `config/` file, test or
test tolerance, and I did not touch AGENTS.md, TESTING.md, `lab/`, `tests/` or `research/`. Every AGENTS.md change below
is quoted old text and new text for the owner to accept, change or reject.

**Every rebalance-steady number in this file is SCOUTING:** the reference engine, not NautilusTrader, with placeholder
costs (RESULTS.md, RISK.md, AUDIT.md).

- **Written by:** `director`, after rebalance-steady train run 0 (NO EDGE), its audit and its risk review.
- **Owner's direction, on the rebalance-steady settings** (crypto share, BTC/ETH split, drift band, check frequency,
  limits, max loss): *"All of this should be adjustable in the final application."*
- **Already done, in the app plan (`docs/app/`):** the requirement is written into `features.md` (new section "Adjustable
  strategy settings") and `technical.md` (new section "Strategy settings"), with small reconciliations in `product.md`
  and `README.md`. Section 8 lists every change.
- **No director branch or PR.** This review ran inside a workflow that shares the working tree with another agent and
  forbids branch switches. This file and the `docs/app/` edits were committed on `claude/tender-brown-g86h44`
  (fea468e and a581f9c), not on a `director/<date>` branch. I never merge my own changes.

**Terms used below.**
- **Sharpe:** return per unit of ups and downs (annualised); higher is better.
- **S:** the walk-forward result. Each fold's search picks settings from earlier data only, they trade the next unseen
  year, and the years are stitched into one out-of-sample series (2019-2022 in the first Steady study).
- **θ_final:** the final search's stable-region pick (`lab/search/stability.py`), searched over all of train.
- **G5 and G6:** the rebalance-steady plan's names for two AGENTS.md gates: "Parameter plateau" (G5) and "Monte Carlo
  95th-percentile max drawdown" (G6). **step/S:** a plateau run's Sharpe divided by S's Sharpe; G5 needs ≥ 0.70.
- **B4 and B5:** comparison baselines in the first Steady study, never put through the gates. B4 holds S's yearly
  mixes, resets them for free once a year and ignores the Steady limits. B5 holds S's targets and rebalances only when
  a Steady limit is hit.
- **Value and combination (grid step):** a value is one allowed setting for one control. A combination, or grid step,
  is one value for every setting a user can change (4.1).

## 1. The requirement, in plain words

1. Users can change a strategy's settings in the app. Each setting has a **default** and an **allowed range**.
2. The allowed range is the approved range (tested by the lab, approved by the owner), not a single tuned point.
   **Approval covers every combination a user can pick.**
3. Settings outside the approved range are blocked for our strategy. A user who wants to go further copies the strategy
   into their own rule, labelled as theirs, untested by us, with any backtest labelled hypothetical (the existing
   customer-rule path in `docs/app/technical.md`).
4. The risk level's limits cap what a user can pick. For Steady today (`config/risk_levels.yaml`): at least 20% cash, at
   most 60% per coin, drawdown budget `TBD`. Going past them means a different level or a customer-built rule.
5. A user's own stop or max loss may be tighter than the level's budget, never looser.
6. The app shows the backtested worst fall for the user's chosen settings.

## 2. What's working

- **The rebalance-steady study made this question answerable.** It was pre-registered. It counted all 2000 trials. It
  reported NO EDGE plainly, and it left the validate and test windows unused (RESULTS.md, AUDIT.md).
- **The risk-officer's s-profile is the key fact.** The crypto share sets the drawdown while barely moving the Sharpe.
  In seed A's final study, in-sample over 2017-2022, the median max drawdown went from −29% (20-30% crypto) to −69%
  (70-77% crypto, only 2 trials) and the median Sharpe from 1.52 to 1.36 (RISK.md section 2, SCOUTING). That tells us
  which setting matters most to cap and to show.
- **The limits are already read, never typed.** `portfolio.risk_limits` reads them from `config/risk_levels.yaml` with
  its hash (bug #41). `portfolio.rebalance` and `check_targets` refuse targets closer than `headroom` to a limit (#42);
  the study pinned 0.02 (`steady.HEADROOM`). A range rule can reuse both as they are.

## 3. Improvements, ranked

Ranked by the director's order: luck passing as skill first, then data, then new ideas, then time.

| # | Improvement | Rank class | Where |
|---|---|---|---|
| 1 | The gates hold on the walk-forward result, as today, **and** at the default and at every combination in the allowed range. The range is pre-registered before any result, and it is never trimmed to drop failing Sharpes | 1: stops luck passing as skill | AGENTS.md "Validation gates" (4.1); hard rule 12 (4.5, optional) |
| 2 | Exports list a default and allowed values per setting, not only pinned parameters. `risk-officer` owns the ranges, and the owner approves them | 1: what ships is exactly what was tested | AGENTS.md "Ready for production", Desk roles, Handoff (4.2-4.4) |
| 3 | What G5 and G6 mean over a range. G6 at the riskiest combination makes the Steady limits decision the cap on the crypto slider | 1, and an owner decision | Section 5 |
| 4 | Two stale AGENTS.md places named in TESTING.md 4a.8, plus one more | 4: saves agents' time and stops wrong code | Section 7, optional and separate |

**Why item 1 matters.** Today an export pins one set of parameters, and the gates test one point: the walk-forward
choice. If users can move the settings, every value they can reach is a strategy we run for them, under our name.
Approving one point and letting users move off it would ship untested settings. The fix only adds places where the
gates are measured: every gate is still measured on the walk-forward result S exactly as today, and the default and
every grid step must pass too. Grid runs only add to the total trial count (4.1, DSR row). **Every threshold
stays as it is, and passing can only get harder.**

Three guards keep the range itself from becoming a new way for luck to pass:
- **The range is set before any result.** It goes in the study's pre-registration, next to the search box, for risk
  and product reasons. If the range were drawn after seeing which settings scored well, that would be one more search,
  counted nowhere. The level's drawdown budget must be owner-approved before the range is pre-registered. The
  pre-registration also lists every earlier look at the same data that could inform the range, as rebalance-steady
  PLAN.md section 15 did with P1-P5. For Steady, run 0's results, the s-profile included, are such a look: a Steady
  range set now is not blind, and it must say so.
- **A range is narrowed only to meet a risk limit** (the drawdown budget or the level's limits), and only by dropping
  whole values from a setting's riskiest end: the end whose grid steps include the deepest Monte Carlo drawdown
  (G6's number), as measured, not assumed. It is never narrowed to drop combinations whose Sharpe failed. A new
  edge chosen this way was picked with drawdowns from the same data, so it only just fits: each narrowing is logged
  with the new edge's margin to the budget, the dropped combinations stay in the trial count, and the range gates run
  again.
- **The app never ranks settings by backtested return.** Users picking the best past result is the same in-sample
  selection, done by the user. `docs/app/features.md` now says so.

## 4. Proposed AGENTS.md edits (exact text)

### 4.1 Validation gates: measure the gates across the allowed range (core)

**Old** (AGENTS.md, "Validation gates", first line):

> A strategy is **ready for paper** (production model account) when `backtest-auditor` reports PASS on all of these. Thresholds are defaults the owner can change:

**New:**

> A strategy is **ready for paper** (production model account) when `backtest-auditor` reports PASS on all of these, on the walk-forward result as today **and at the default and at every combination of the allowed values** of the settings a user can change in the app (see "Settings ranges" below). Thresholds are defaults the owner can change:

**Add after the gates table, before "Ready for production"** (new text):

> **Settings ranges.** Users can change a strategy's settings in the app, so approval covers every combination a user can pick, not one tuned point.
> - `risk-officer` sets each setting's allowed values inside the risk level's limits, in the study's pre-registration, before any result. The level's drawdown budget must be owner-approved before then. The pre-registration lists every earlier look at the same data that could inform the range (a study's prior looks, as in its plan). The app offers those values only.
> - The allowed range lies inside the search box. Where the box reaches further, the walk-forward choice and θ_final can use values a user cannot pick, and the default can sit some way from θ_final. The walk-forward choice still has to pass every gate, and the grid covers what users can pick.
> - A grid step is one full combination (one value for every setting a user can change). The grid is every combination of the per-setting values, and every gate below covers each combination (the table says how). Each setting's values include both ends of its range. The default takes, for each setting, the value nearest θ_final's (θ_final is the final search's stable-region pick, `lab/search/stability.py`). A setting users cannot change keeps θ_final's value.
> - The thresholds above are unchanged. Where each gate is measured:
>
> | Gate | Measured at |
> |---|---|
> | Walk-forward out-of-sample Sharpe, and the same with costs doubled | The walk-forward choice, as today, **and** every grid step held fixed over the same out-of-sample span |
> | Deflated Sharpe Ratio; Probability of Backtest Overfitting | As today. Every grid run is logged and added to the total trial count (AGENTS.md "Running many simulations", rule 4), as the plateau and doubled-cost runs are (rebalance-steady's strict count, RESULTS.md). The effective count for correlated trials (`backtest-auditor` item 8) still comes from the search studies' trials, and the grid runs do not enter it: they were fixed before any result, so nothing was selected from them. The trial-Sharpe variance and PBO also still come from the search's trials. So the total-count DSR can only fall, and the effective-count DSR is unchanged |
> | Parameter plateau | As today (each parameter ×0.8 and ×1.2 from the walk-forward choices, against the walk-forward Sharpe S), **and** each parameter ×0.8 and ×1.2 from the default, **and** every grid step. The default's steps and the grid steps are each held fixed over the walk-forward out-of-sample span, and each must keep ≥ 70% of S's Sharpe |
> | Monte Carlo 95th-percentile max drawdown | The walk-forward choice, as today, **and** every grid step: S's drawdown and the deepest grid-step drawdown are both within the risk level's budget |
> | Beats benchmarks; regimes | The walk-forward choice, as today, **and** the default and every grid step |
> | Final test window, run once | One run covering the default and every grid step together. The default is judged against the walk-forward Sharpe S, as today; every other grid step against its own fixed run over the walk-forward out-of-sample span. The window is then burned for the whole range |
>
> - A failing walk-forward result fails the strategy, as today. One failing grid step fails the range. After an audit, a range may be narrowed only to meet a risk limit (the drawdown budget or the level's limits), and only by dropping whole values from a setting's riskiest end, never to drop combinations whose Sharpe failed. A setting's riskiest end is the end whose grid steps include the deepest Monte Carlo 95th-percentile max drawdown, as measured. Each narrowing is logged with the new edge's margin to the budget, the dropped combinations stay in the trial count, and the range gates run again. The range is frozen before the test window opens.
> - The default is chosen by the search, so its fixed runs on the search's own data are in-sample. That includes its runs and its ±20% steps over the walk-forward out-of-sample span, when the final search used those years. Those runs add checks, not evidence. Its out-of-sample evidence stays the walk-forward choice, the validate look and the test window. The other grid steps were fixed before any result, so they were not selected.
> - The grid runner and the per-combination gate table ship with the tests [TESTING.md](TESTING.md) section 7 describes (hard rule 11), including a test that recomputes every reported number from its inputs.
> - Fixed settings (no setting a user can change) ship θ_final, like today's pinned config. They are gated as today on the walk-forward result, plus θ_final's own runs wherever the table names the default. A range is fixed in the pre-registration: one that fails cannot be cut down to fixed settings afterwards, because that would drop combinations whose Sharpe failed.

### 4.2 Ready for production: exports carry defaults and ranges (core)

**Old:**

> **Ready for production (owner decision, not an agent's):** at least 4 weeks on a paper model account with results within tolerance of the backtest; the owner approves; `risk-officer` writes `exports/<name>/config.yaml` with pinned parameters, risk level, coin list and code commit.

**New:**

> **Ready for production (owner decision, not an agent's):** at least 4 weeks on paper model accounts, at the default and at the riskiest combination in the allowed range (the grid step with the deepest Monte Carlo 95th-percentile max drawdown), with results within tolerance of the backtest; the owner approves the default and the range; `risk-officer` writes `exports/<name>/config.yaml` with, for every setting a user can change, its default and its allowed values (a setting users can't change has one value), plus the risk level and its limits as read, the coin list, the backtested max drawdown and Monte Carlo 95th-percentile max drawdown for every combination, the code commit, the data snapshot ID and the model version (if any).

*Separable:* "and at the riskiest combination in the allowed range" adds a second paper node per strategy. Drop it if
the owner prefers one model account. The live record then covers the default only.

### 4.3 Desk roles: the risk-officer owns the ranges (core)

**Old:**

> | `risk-officer` | `config/risk_levels.yaml`, drawdown budgets, exports | Loosen a limit without the owner's written approval |

**New:**

> | `risk-officer` | `config/risk_levels.yaml`, drawdown budgets, each setting's allowed range (set before any result, inside the level's limits), exports | Loosen a limit or widen an approved range without the owner's written approval |

### 4.4 Handoff line (core)

**Old:**

> Handoff for any new strategy: `quant-researcher` (or `ml-researcher`) → `backtest-auditor` → `risk-officer` → paper model account → owner → export.

**New:**

> Handoff for any new strategy: `quant-researcher` (or `ml-researcher`) and `risk-officer` pre-register the search box and the allowed ranges → `backtest-auditor` → `risk-officer` → paper model accounts → owner → export.

### 4.5 A hard rule every agent sees (optional)

**Add after hard rule 11:**

> 12. **Approval covers a range, not a point.** Every setting a user can change in the app has an allowed range, set before any result, and every combination in it passed the audit. Nothing outside the approved range is exported.

4.1 already implies this. As a hard rule, it reaches `quant-researcher` and `ml-researcher` too, who read the hard
rules but not the gate details.

### 4.6 Matching edits outside AGENTS.md (same proposal; applied 2026-11-20, see the status)

AGENTS.md alone would leave the role files contradicting it:
- `.claude/agents/risk-officer.md`, step 5: "write `exports/<strategy>/config.yaml` with pinned parameters, ..." → "with
  each setting's default and allowed values, ..." (the rest of the step, including "model version (if any)", stays).
  Add a step before step 1: "Before any result, set each setting's allowed values inside the level's limits, in the
  study's pre-registration." Add to Rules: "Never widen an approved range without the owner's written approval."
- `.claude/agents/backtest-auditor.md`: items 5 (trades per parameter), 6 (plateau), 12 (cost stress), 13
  (capacity: leg sizes grow at the riskiest combination), 14 (Monte Carlo), 15 (regimes) and 16 (benchmarks) are
  measured as today **and** at every grid step held fixed over item 7's out-of-sample span, as in 4.1. Item 7 itself
  (walk-forward) is unchanged: grid steps are not re-fit. Item 8 adds the grid runs to the total trial count, not to the
  effective count. The final step runs the test window once, for the default and every grid step together.
- `.claude/agents/quant-researcher.md`, step 4: `params.yaml` holds "parameters, their search ranges, the allowed
  values set by `risk-officer`, and the risk level".
- `research-methods.md`, the "Parameter plateau" row: "Every parameter ±20%, and every combination of settings a user
  can pick; the result must stay mostly intact."

## 5. What this means for G5 and G6

### G5, the plateau

- **Today** (rebalance-steady PLAN.md section 9): each of the 4 parameters is moved alone, ×0.8 and ×1.2, from each
  fold's chosen value. It passes if all 8 steps keep ≥ 70% of S's Sharpe. Run 0 passed (SCOUTING): step/S was
  0.958-1.068 for seed A. The auditor noted the plateau was flat because the rule hardly traded (3 fills in four
  years), so the pass was "not evidence of robustness" (AUDIT.md item 6).
- **Under 4.1:** today's ±20% steps from each fold's choice stay. The same ±20% steps around the default, and every
  grid step, are added; each is held fixed over the walk-forward out-of-sample span and must also keep ≥ 70% of S's
  Sharpe. The default's runs over that span are in-sample when the final search used those years (in run 0 it did).
  - A range wider than ±20% is tested where users can actually go.
  - A range narrower than ±20% doesn't excuse the ±20% steps.
- **For Steady's crypto share, G5 will rarely be the binding gate.** The Sharpe barely moved with the share: in-sample
  medians of 1.52 at 20-30% crypto and 1.36 at 70-77% (only 2 trials in that bin; ratio 0.89, SCOUTING). Drawdown is
  what moves, and that is G6's job.

### G6, the Monte Carlo drawdown

- **Today:** the stationary block bootstrap 5th-percentile max drawdown of the walk-forward series must be within the
  level's budget. Run 0 gave −58.6% (seed A, SCOUTING). The budget is `TBD`, so G6 is MISSING, which counts as a FAIL.
- **Under 4.1:** S's 5th-percentile drawdown, as today, and the deepest one among the grid steps must be within the
  budget. The crypto share sets the drawdown, so **G6 sets the top of the crypto-share slider**: the highest share whose
  worst-5% drawdown fits the budget. (The grid includes every corner, because the split, band and check frequency can
  move the drawdown too.) S still has to fit as well; a range cannot carry a walk-forward result that fails.
- **While the budget is `TBD`,** G6 is MISSING for S and at every grid step. No Steady range, and no Steady default,
  can be approved. That is the same as today.
- **How this interacts with RISK.md's budget method.** The proposal (PLAN.md section 9, RISK.md section 3):
  - The reference is the box's riskiest coin share (77%), split evenly: BTC 0.385, ETH 0.385, USDC 0.23, rebalanced
    every 30 days. (The limits themselves allow 78% coins with the 2-point margin and 80% without, and an uneven
    split may fall further than an even one; nothing in run 0 measured that.)
  - The budget is the reference's bootstrap 5th-percentile drawdown, rounded up to the next 5 points.

  If the budget's reference and the grid steps are measured on the same closes (RISK.md section 3, point 4), a range
  whose top crypto share is the reference's 77% then passes G6 at the even split roughly by construction. As the
  method is written, the reference runs over all of train (2017-2022) and G6 over the walk-forward span (2019-2022),
  so that does not follow: the gap between the two histories can move it either way. The other combinations at that
  share (an uneven split; other bands and check frequencies) can still fail it and be cut. So under that method, with
  the same closes, G6 will hardly pull the crypto share below the box's top, and the **cash floor and per-coin cap
  become the real cap on what a Steady user can pick**. RISK.md expects a deep number: trials with 70-77% coins had
  in-sample bootstrap 5th percentiles around −80% (SCOUTING). That makes the risk-officer's open recommendation
  (tighten the Steady limits before the budget is computed, RISK.md section 3, point 3) the decision that sets the
  slider.
- **This is not a reason to change the budget method.** The method was pinned before any result, and it should stay that
  way. The point is that the owner's limits decision now has a visible product effect.
- **RISK.md point 4 (compare like with like)** applies to every grid step. Each grid step's drawdown should be
  measured on the same closes as the budget's reference.

### Cost of the grid

It is cheap on the reference engine. Amendment A1 measured 0.0073-0.0088 s per 2190-row backtest before run 0, on
synthetic data; run 0's real search phase took 45.1 s for 2000 trials (RESULTS.md, A1). A grid of a few hundred
combinations would take seconds, plus a 1000-draw bootstrap per combination. Throughput on Nautilus is unknown until
milestone 2. It is worth measuring then, before the first range audit.

## 6. Export sketch (illustration only; every value is a placeholder)

```yaml
# exports/<name>/config.yaml (sketch; nothing is approved)
strategy: <name>
risk_level: steady
coins: [BTC, ETH, USDC]
limits_as_read: { min_cash_pct: 20, max_coin_pct: 60, max_drawdown_budget_pct: <owner-approved>, sha256: <...> }
headroom: <the study's pinned value>
settings:                       # every setting a user can change; the grid is every combination of these values
  coin_share: { default: <x>, values: [<...>] }
  btc_share:  { default: <x>, values: [<...>] }
  band_rel:   { default: <x>, values: [<...>] }
  every_days: { default: <n>, values: [<...>] }
user_loss_limit: { loosest_pct: <the level's budget> }   # users may only set it tighter
step_results: <file>            # per combination: backtested max drawdown, MC 5th-percentile drawdown, worst day (hypothetical)
audit: reports/<name>/<date>.md
code_commit: <sha>
data_snapshot: <id>
model_version: <id or none>
owner_approval: <date and reference>
```

## 7. Separate, optional: stale places in AGENTS.md

These are not about adjustable settings. TESTING.md 4a.8 names the first two. Each can be accepted on its own.

### 7.1 The `on_bar` example uses a per-bar forecast as if it were annual

Forecasts are per bar since the merge (bugs #22 and #24). Copied as written, the example divides an annual `vol_target`
by a daily volatility. The forecast is then about 19 times (√365) too small and the ratio about 19 times too large, so
the size almost always lands on the `max_weight` cap and the volatility sizing does almost nothing.

**Old:**

```python
    forecast_vol = self.vol_model.predict(feats)
    size = min(self.max_weight, self.vol_target / forecast_vol)
```

**New** (the snippet also needs `import math`):

```python
    forecast_vol = self.vol_model.predict(feats)      # per bar, like every lab volatility
    annual_vol = forecast_vol * math.sqrt(365)         # daily bars; math.sqrt(8760) for hourly
    size = min(self.max_weight, self.vol_target / annual_vol)   # vol_target is annual
```

### 7.2 The starter-module table describes the old contract

**Old:**

> | `lab/runner/interface.py` | **The contract.** `backtest_fn(params, bars) -> DataFrame` with columns `ret` (net per-period return after all costs), `position`, `turnover`, plus `attrs["trade_returns"]` |

**New** (matches the `lab/runner/interface.py` docstring and TESTING.md 4a.5):

> | `lab/runner/interface.py` | **The contract.** `backtest_fn(params, bars) -> DataFrame` on exactly `bars.index` (bar close times), with columns `ret` (net return over the bar after all costs; 0 on the first bar), `position` (weight at the bar's close), `turnover` and `cost`, plus `attrs["trade_returns"]` (one per round trip; an open one is marked to market) and `attrs["n_trades"]` (fills). A decision at close t fills at the open of t+1. Every runner must pass `tests/contract/` |

### 7.3 Also stale (not in 4a.8): the starter-code counts

**Old:**

> The smart search, validation statistics and prediction pipeline already exist, with 159 tests (100% branch coverage) and an end-to-end demo. Build on them; don't rewrite them. Testing found and fixed 7 bugs, including three in the reference backtester's accounting; two more findings are open.

**New:**

> The smart search, validation statistics and prediction pipeline already exist, with an end-to-end demo; the current test count, coverage and bug log are in [TESTING.md](TESTING.md) sections 3 and 4. Build on them; don't rewrite them.

The current counts are in TESTING.md sections 3 and 4. Pointing to them keeps AGENTS.md from going stale again.

## 8. What I changed in `docs/app/` (this review)

| File | Change |
|---|---|
| `features.md` | New section **Adjustable strategy settings**: the rules in section 1 (the lab tests a range, the owner approves it); a Steady settings table with the limit that caps each setting; the 2-point margin; the 80% (78%) crypto ceiling the current limits allow on the per-coin reading (60%, 58% on the all-coins reading); and **What the first Steady study taught**, with RESULTS.md and RISK.md numbers labelled SCOUTING (reference engine, placeholder costs), drawdowns next to every "did as well on Sharpe", trial counts for the small crypto-share bins, and the yearly-reset and limit-only comparisons named as baselines never put through the gates. The worst fall shown names its years and says the default's is at least partly in-sample; "drawdown budget" and "in-sample" are explained where they first appear; the bootstrap figures are called medians. Also: a "Strategy settings" catalog row, the screen map, a "Change a strategy's settings" flow, a "does not do" line, a per-strategy loss limit in the Customer controls row (a pause stops trading; it doesn't sell), and seven open questions |
| `technical.md` | New section **Strategy settings**: where ranges come from (the export; worst fall per combination), what's stored (versioned per subscription), validation (approved values only, limits with margin, loss limit tighter than the budget, fails closed), who decides what (marked proposed, needing an owner decision; it also reaches customers on the defaults, whose wallets can drift from other weights than the model account's), and where the worst-fall number comes from. Reconciled: the chef/waiter "Decides" row (footnoted), Engine "Research and approval" (exports carry defaults and ranges; marked proposed, not in force), Database (settings are versioned records), the Risk engine's User layer, and Agent team rules (no agent changes approved setting ranges) |
| `product.md` | A pointer from "Built once, tuned by settings", and a Phase 1 bullet ("Strategy settings, as ranges are approved"). The Steady guardrail "a few trades a month" is unchanged (an earlier draft of this review made it "at most"; reverted, see below) |
| `README.md` | A "Strategy settings" decision row (marked proposed, not in force), a pointer from the "Engine vs. user trades" row to the per-customer case (marked as needing an owner decision), and open questions on the Steady limits and budget and on the per-customer decision check (decision 9) |

**Contradictions found and how I reconciled them** (minimal edits):
- **Chef and waiter, and "NautilusTrader is the only engine"** (`technical.md`, `README.md`): Nautilus decides "what to
  trade, and when", once per strategy, and the same strategy code runs in every mode. With per-user drift bands and
  check frequencies, *when* to trade back to target depends on each user's own wallet. So for users off the defaults,
  the new section's per-customer check would move trade timing out of Nautilus, into code that must pass a
  decision-parity test against the Nautilus strategy. That is a change to a key decision, not a detail. It is marked
  "proposed; needs an owner decision" in `technical.md` (the paragraph and a footnote on the chef/waiter "Decides"
  row), raised as an open question in `README.md` and `features.md`, and listed as decision 9. Where the check would
  run (rules service or trade router) stays open behind it.
- **"Only approved, pinned configs are exported"** (`technical.md`): reworded to defaults plus approved ranges, marked
  "proposed, not in force", with a pointer to this proposal. AGENTS.md is unchanged until the owner decides.
- **Who approves** (all four files): AGENTS.md says the lab never approves its own work for production. Every place
  says the range is tested by the lab and approved by the owner.
- **"A few trades a month"** (`product.md`, Steady's guardrails): `features.md` first said the drift band and check
  frequency had no Steady cap, while `product.md` lists this guardrail. The search box reached `every` = 1 and band
  b = 0.02. Seed A's final-search trial #0 (`every` = 2, b 0.033) rebalanced on 242 days over six years of train
  (about 3.4 a month), and the busiest trials (`every` = 1, b about 0.02) on 697 (seed A #13) and 757 (seed B #10)
  days, about 10 a month (in-sample, SCOUTING). I left the owner's wording as it was. `features.md` now names the guardrail next to those two
  settings and asks whether it caps them and how it is counted (trades or rebalances).
- **Customer-rule path for out-of-range settings:** the advanced builder's listed building blocks have no rebalancing
  block, and customer rules require a stop-loss. `features.md` says both, rather than promising a path that doesn't exist yet.
- **No contradiction found** with `business.md`. Its "backtests labeled hypothetical" and "worst expected drop per
  level" lines already cover the worst-fall display.

**Wording checks.** RISK.md asked RESULTS.md to drop "mostly cash, some ETH", and I don't use it. Everywhere I cite the
yearly-reset (B4), never-reset (B4-span) and random (B3) comparisons, I say they did not apply the Steady limits (RISK.md
request 2). Where B4 or B5 "did as well", I say it was on Sharpe and give the deeper worst fall (RISK.md request 3).
I quote B4's Sharpe for both searches (0.948 and 1.030), never one seed against the 1.0 bar. I say the timing test had
little power (3 rebalances), as RESULTS.md "Known weaknesses" does.

## 9. Decisions for the owner

1. **Accept 4.1-4.4** (core) as written, edited, or not at all. 4.5 and 4.6 follow from them. **Owner (2026-11-20):
   "yes to 1". 4.1-4.4 applied as written; 4.6 applied with the small consistency edits listed in the status; 4.5 was
   not part of the answer and stays a proposal.**
2. **The second paper model account** at the riskiest combination (4.2, separable). In AGENTS.md since 2026-11-20 as
   part of 4.2; still open: keep or drop.
3. **The Steady limits.** Tighten them before the budget is computed (RISK.md section 3, point 3)? Under 4.1 this sets the
   top of the Steady crypto slider. Today's limits allow up to 80% crypto. In the two final searches (in-sample, over
   all of 2017-2022), the 3 trials with 70-77% crypto fell 66-72% at worst (RISK.md section 2: about two thirds), each
   from a January 2018 peak (dated from the logged trial returns in `results/rebalance-steady/train/`; SCOUTING).
4. **The per-coin reading, and cash.** Does "max 60%" apply to each coin (the lab's reading) or to all coins together?
   And does it apply to USDC (the lab reads it as not, reading 4)? Both are still unconfirmed (RISK.md section 1). The
   first answer changes what the BTC/ETH split and the crypto share may reach (80% against 60%); a 60% cap on USDC
   would need at least 40% crypto and rule out the mostly-cash mixes the study reached.
5. **"Hold this mix" for Steady.** Offer it as one of our strategies (it must pass the gates) or as a self-directed tool
   like recurring buys, with its risk numbers shown and no performance claim. The yearly-reset comparison was a
   baseline, not a tested strategy: it reused the search's yearly mixes, ignored the Steady limits and was never put
   through the checks. Its Sharpe was 0.948 with one search and 1.030 with the other, either side of the lab's 1.0 bar
   (SCOUTING). The gates must not be relaxed to fit it. **Owner (2026-11-20): a self-directed tool, not one of our
   strategies ("go with the simple tool").** Like recurring buys: the user picks the mix and the app keeps it there. We
   make no claim that it beats anything, and the app still shows how far it would have fallen in the past. It is not
   put through the lab's gates.
6. **Out-of-range settings.** Blocked for our strategy, with the customer-rule path as the only way further (my
   recommendation, written into `features.md`). The alternative is to allow them with an "untested" label, which I
   advise against: our strategy's name would sit on untested settings.
7. **Separate user limits** (for example "keep at least 40% cash" on top of the mix). In Steady the limits also trigger
   trades, so such a limit is a strategy setting and needs its own approved range.
8. **Accept 7.1-7.3** (stale text), each on its own.
9. **Who decides trade timing for customers off the defaults.** Accept a per-customer decision check outside Nautilus,
   or keep Nautilus as the only decision-maker (fixed settings at launch, or one Nautilus node per approved
   combination)? The first departs from "NautilusTrader is the only engine" (`docs/app/technical.md`, README "Trading
   engine") and needs a decision-parity test against the Nautilus strategy. `technical.md` marks it proposed. The
   question also reaches customers on the defaults: a wallet that joined, or added cash, after the model account's
   last rebalance drifts from different weights, so following the model account's signals rebalances it on a schedule
   that differs from the backtest of its own book.
10. **Steady's "a few trades a month".** Does this `product.md` guardrail cap the drift band and the check frequency
   a user can pick, and is it counted in trades or in rebalances? If it caps them, `risk-officer` sets those two
   ranges inside it at pre-registration (4.1), like the level's limits. **Owner (2026-11-20): it caps them unless
   rebalancing that often is shown to pay.** In the first study's final searches it did not (in-sample, SCOUTING; the
   numbers are in `features.md`), so it caps them. How it is counted (trades or rebalances) is still open.
11. **A level's first drawdown budget.** AGENTS.md now says a level's budget must be owner-approved before any range
   at that level is pre-registered. But `risk-officer.md` ("Setting drawdown budgets") and `research-methods.md`
   ("Risk-level budgets") take the budget from the Monte Carlo drawdowns of the level's audited strategies, and a
   level's first study (Steady today) has none. Where does the first budget come from: a reference mix measured before
   the study, as RISK.md section 3 and PLAN.md section 9 propose, or something else? Found while applying decision 1;
   both files now point here, and no method changed.

## 10. Risks of this proposal

- **Fewer strategies will pass.** That is intended: a range is a stronger claim than a point. A strategy can still
  ship with fixed settings (θ_final), if fixed settings were what its pre-registration named. A range that fails can't
  be cut down to its passing point afterwards (4.1).
- **More runs to log and count.** Grid runs are added to the total trial count, which only lowers the total-count DSR. They
  do not enter the effective count the DSR gate uses, because nothing is selected from them (4.1, DSR row).
- **More moving parts in the app.** Settings records, validation, and (if decision 9 accepts it) a per-user check for
  users off the defaults.
  The per-user check is new money-path code and falls under the existing agent team rules (a second agent reviews it,
  and the owner reads it).
- **Interpretation risk.** "Held fixed over the same out-of-sample span" needs exact wording in the next study's plan.
  The auditor should pin it there before any run.

## 11. What the desk should stop doing

- **Stop treating a strategy as one tuned point.** The search's choice is the default, not the product. The product is
  the range users can reach.
- **Stop quoting the stitched walk-forward drawdown as a shippable drawdown.** RISK.md section 2 already says this:
  S mixes four per-fold configurations. Report the drawdown of each combination that can ship. S's drawdown still
  stays in G6, as today (4.1): it is a gate on the method, not the number a user is shown.

## Sources

Internal files only. No web research was needed for this proposal.
- `docs/app/README.md`, `features.md`, `product.md`, `technical.md`, `business.md`
- `AGENTS.md`: Validation gates, Ready for production, Risk levels, Hard rules, Desk roles
- `TESTING.md`: section 4a.5 (the contract), 4a.8 (stale AGENTS.md places), bugs #22, #24, #41, #42
- `config/risk_levels.yaml` (read only)
- `research/rebalance-steady/RESULTS.md` (including A1, the Deviations table, the s-profile and the trial counts),
  `RISK.md`, `AUDIT.md`, and PLAN.md sections 4, 5, 7, 8, 9, 12 and 15 (prior looks P1-P5)
- `results/rebalance-steady/train/` (read only): every study's `trials.parquet`, to recount the 70-77% crypto bin (38
  trials in the 10 searches, 3 of them in the two final searches) and seed A's final-search trial #0 (every 2, 242
  rebalance days) and #13 (697) / seed B #10 (757); the final searches' logged trial returns, to date the 3 final-search trials' worst falls (#7 −65.7% and #14
  −71.7% in seed A's, #22 −68.4% in seed B's, each from a January 2018 peak)
- `lab/runner/interface.py` (module docstring); `lab/runner/portfolio.py` and `lab/runner/steady.py` (`headroom`,
  `HEADROOM`); `lab/validation/stats.py` (`deflated_sharpe_ratio`: `n_trials` and the trial-Sharpe variance are
  separate inputs)
- `.claude/agents/risk-officer.md`, `backtest-auditor.md`, `quant-researcher.md`

## Handoff

- **Report:** `reports/director/2026-11-20-adjustable-settings.md`. **Branch:** no `director/` branch (the workflow
  forbids branch switches in the shared tree). This file and the `docs/app/` edits were committed on
  `claude/tender-brown-g86h44` (fea468e and a581f9c).
- **Top improvement in one sentence:** approval should cover every combination of settings a user can pick, so the
  gates must hold on the walk-forward result as today and also at every combination in a range fixed before any
  result, with the unchanged thresholds, the riskiest combination judged against the level's drawdown budget, and
  nothing narrowed to drop failing Sharpes.
- **Needs the owner:** the open decisions in section 9 (2-4, 6-9 and 11; 1, 5 and 10 are decided). The most urgent is decision 3 (tighten the Steady limits or not),
  because it now sets what a Steady user can pick.

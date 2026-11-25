# Proposal: limits for the two new risk levels, Cash-first and Explorer (DRAFT, not approved)

*`risk-officer`, 2026-11-25. This is a draft for the owner. Nothing here is in force, and `config/risk_levels.yaml`
and the tests are unchanged. The owner added the two levels on 2026-11-25 (`docs/app/features.md`, "Strategies by
risk level"; `docs/app/README.md`, "Strategy lineup"). The names are working names.*

Each number has a tag:
- **[measured]** comes from a finished study's outputs.
- **[derived]** is computed here from measured numbers, and the method is stated.
- **[judgement]** is my proposal, with no study behind it.

All study numbers are SCOUTING. They come from the reference engine on 2017-2022 train data, in-sample, with
placeholder costs.

## 1. The proposal in one table

| Field | Cash-first (proposed) | Steady (in force) | Balanced (in file) | Bold (in file) | Explorer (proposed) |
|---|---|---|---|---|---|
| Coins | BTC, ETH, USDC | BTC, ETH, USDC | BTC, ETH, USDC (+ vetted large tokens) | `[]` (vetted list) | BTC, ETH, USDC + tokens that pass the Explorer vetting (section 3) |
| Cash floor | **90%** [judgement, checked against derived falls] | 20% | none | none | **0%** [judgement] |
| Max per coin | **5%** each of BTC, ETH [judgement, checked against derived falls] | 60% | none | none | BTC, ETH: none. **20%** in each other token [judgement] |
| Exit-cost cap per position | — | — | — | — | **100 bps**: a position may not be larger than what one swap can sell for 1% total cost on a measured 0x quote [judgement] |
| Drawdown budget (MC p95 max drawdown) | **25%, interim** [judgement on derived falls] | 35% (owner, 2026-11-21) | TBD | TBD | **90%, interim** [judgement on measured anchors] |
| Stop-loss required | **no** [judgement] | no | yes | no | **yes** [judgement; owner question 4] |
| Hold-this-mix limit (rebalances in any 30 days) | **2**, as Steady [derived from Steady's evidence] | 2 (owner, 2026-11-22) | — | — | **not applicable**: the tool holds BTC, ETH and USDC only |

## 2. Cash-first

**Coins: BTC, ETH, USDC.** These are Steady's coins. The lab's runner (`portfolio.risk_limits` accepts exactly these)
and the hold-this-mix engine can test them today. They are the only tokens whose Base liquidity the docs already
rely on.

**Cash floor 90%, at most 5% in each coin.** With the lab's 2-point margin, targets go up to 3% BTC + 3% ETH. That is
6% crypto. At the limits themselves crypto is 10%.

Why so small: in hold-mix-cap even **20% crypto fell 34-42%** in its worst case [measured, `falls.csv`].
- At the default band, 20% crypto with ETH only fell 35.3% (Kraken). With half BTC it fell 28.2%.
- Over every band and cap, those mixes fell 42.0% and 34.3%.
- The 2018 crash is the main cause. Rebalancing back into the falling coins makes the fall deeper.

So a 15-20% crypto ceiling would put Cash-first's worst cases on top of Steady's 35% budget, and the levels would not
be separate.

How I derived the Cash-first falls [derived]:
- A mix kept near its targets loses roughly 1 − exp(−k·s), where s is the crypto share. I take k from the measured
  20% mixes (Kraken):
  - ETH only: 2.72 over all bands, 2.18 at the default band;
  - half BTC: 2.10 and 1.66;
  - BTC only: 2.07 and 1.34.
- Checked against the measured 30% mixes, the method over-predicts by 0.4-1.5 points, so it errs on the deep side.

| Crypto share (split) | Worst fall, default band (50%, cap 1) | Worst fall, any band and cap |
|---|---|---|
| 6% (3% + 3%: the most the 2-point margin allows) | ~9.5% | ~11.8% |
| 10% (5% + 5%: at the limits) | ~15.3% | ~19.0% |
| *For comparison, a wider option:* 12% (6% + 6%, from floor 85% and cap 8% with the margin) | ~18.1% | ~22.3% |
| *Measured, 20% (Steady's smallest tested mix)* | 28.2% (half BTC) to 35.3% (ETH only) | 34.3% to 42.0% |

The worst single day is derived the same way, scaled roughly in proportion to the share from the measured 20% mixes
(5.6-9.3%, 12 March 2020): about 2-3% at 6% crypto and 4-5% at 10% [derived].

**Drawdown budget: 25%, interim.**
- There is no Monte Carlo number for this level. In the finished studies, the Monte Carlo 95th-percentile fall ran
  **1.2 to 1.6 times** the historical worst fall [measured]:
  - rebalance-steady's S: −41.8% against −58.6%;
  - its 20-30% crypto mixes: −29% against −38%;
  - trend-steady's S: −37.5% against −59.3%; θ_final(A): −31.7% against −47.1%.
- Applied to the table [derived]: at the 6% targets the margin allows, about 14-19%. At the limits themselves, about
  23-30%.
- So 25% holds every target the app can offer with room to spare. It is 10 points below Steady's 35%.
- The wider option (85% / 8%) would reach about 27-36% and overlap Steady. I do not recommend it.

How the interim budget is replaced:
1. Before anything at this level is pre-registered, the owner approves a budget. That can be this one. This is
   decision 11 for this level (`reports/director/2026-11-20-adjustable-settings.md`). Steady's first budget was also
   an owner judgement.
2. A measured reference run can replace the derivation before any strategy exists. It would be the hold-this-mix
   engine at the riskiest Cash-first mixes (5%/5%, 3%/3%), train window only, with a block-bootstrap Monte Carlo,
   pre-registered by `quant-researcher`. That is one more logged look at train data, and the validate and test
   windows stay unread.
3. After the first audited Cash-first strategy, the budget becomes its Monte Carlo p95 rounded up.
   - If that is lower, I can tighten the budget on my own.
   - If it is higher, the strategy moves up a level. The budget is never loosened without the owner's written approval.

**No stop-loss required.** With at most 10% in crypto, a stop protects a few percent of the wallet and adds trades.
Recurring buys and hold-this-mix need none either.

**Hold-this-mix limit: 2 rebalances in any 30 days, the same as Steady.**
- Steady's "a cap of 2 gets about 95% of the closeness to target" result held on every source, cost level and wallet
  size [measured, mixes of 20-78% crypto]. Below 20% it was not tested.
- Limit fixes should be rare at this level [derived]. From 3% targets, a coin must rise about 70% against cash to
  reach 5%, and crypto must rise about 74% to break the 90% floor. At Steady's 78% mixes, limit fixes were frequent.
- Legs are tiny. In a 500 USD wallet, a trip back at the 30% band moves about 4.50 USD of a 3% coin. The 0.10 USD of
  sponsored gas is then about 2% of the leg (placeholder gas). `data-engineer`'s measured 0x quotes should include
  sizes this small.

## 3. Explorer

**Coins: BTC, ETH, USDC, plus tokens that pass the vetting below.** Every threshold is a [judgement] starting point.
The owner can set them once `data-engineer` has measured them.

Vetting rules for a token:
1. **Spot only.**
   - It is a plain ERC-20 on Base with verified source.
   - It is not leveraged, a derivative, an LP or yield-wrapper token, a rebasing token, or a stablecoin other than USDC.
   - It has no fee-on-transfer, blacklist, pause or un-timelocked admin mint. An upgradeable proxy is flagged.
   - It is canonical on Base. Bridged copies are out unless they are the disclosed canonical one, as cbBTC is.
   - The contract review is an engineering check outside the lab.
2. **Liquidity on Base:**
   - a round trip of 10,000 USD through 0x costs at most 100 bps in at least 95% of samples over 30 days;
   - at least two independent pools;
   - median daily DEX volume on Base of at least 1M USD over 90 days.
3. **Testable history:** at least 3 years of daily candles in at least two of the lab's sources (Kraken, Binance,
   Coinbase), so that any backtest includes at least one crash. The measured gap between the Base price and the
   exchange price must be within the lab's tolerance.
4. **Ongoing checks:**
   - Tokens are re-measured monthly.
   - A token that fails two checks in a row becomes **sell-only**: no new buys, holders are told, and nothing is
     force-sold at a bad price.
   - The router's allowlist and each auto-trading permission's coin list follow the vetted list.

What `data-engineer` would measure, per candidate:
- 0x quotes at 100, 1,000, 10,000 and 50,000 USD, buy and sell, several times a day for 30 days;
- pool TVL and fee tiers;
- daily DEX volume on Base;
- the Base-vs-exchange price gap;
- candle coverage and quality from each source.

The same measurements would fill Bold's empty list and Balanced's "vetted large tokens".

**Position limits.**
- Cash floor 0%. Bold and Balanced set none.
- No per-coin cap on BTC or ETH, so Explorer is not tighter than Balanced or Bold on the core coins.
- At most **20% in any one other token**.
- The **exit-cost cap**: a position may not be larger than what one swap sells for 1% total cost on the latest
  measured quote. A thin token can fall to near zero in days, and a wallet must always be able to get out.

**Drawdown budget: 90%, interim.**
- Measured anchors: BTC alone fell −77.4% (2019-2022, rebalance-steady) and −81% (2018-2022, trend-steady).
- Derived: an ETH-only wallet would have fallen about 93%, from k = 2.72 above.
- With the 1.2-1.6 Monte Carlo factor, any level that allows a whole wallet in one coin has a p95 of 90% or more.
- So 90% says: nothing ships that is likely to lose more than 9 in 10 dollars in a bad history.
- It is replaced, as for Cash-first, by the first audited Explorer strategy's Monte Carlo p95, rounded up.
- Explorer has no tested strategy, and the lab's runner holds BTC and ETH only (`risk_limits` refuses any other coin
  list). So no Explorer strategy can be studied until a multi-token runner exists. The same is true for Bold.

**Stop-loss required: yes.** The level's budget gives a single position little protection. On the other hand:
- a stop on a thin pool fills badly;
- trend-steady's stops added nothing measurable on BTC and ETH [measured].

So this is owner question 4.

**Hold-this-mix: not applicable.** The tool holds BTC, ETH and USDC only. Explorer's starting points are strategies
and rule templates until the tool is extended and tested.

## 4. How the five levels order, and what it means for Balanced and Bold

| | Cash-first | Steady | Balanced | Bold | Explorer |
|---|---|---|---|---|---|
| Budget | 25 (proposed) | 35 | TBD: must be above 35 and below Bold | TBD: must be below Explorer | 90 (proposed) |
| Cash floor | 90 | 20 | none | none | 0 |

Inconsistencies (I point these out and change nothing):
1. **Room above Steady is small.** If "clearly separated" means at least 10 points between neighbours [judgement],
   then Balanced must be 45-70% and Bold at most 80%.
   - A Bold strategy fully in crypto would be at or above that: BTC alone fell 77-81% historically.
   - So Bold only fits if its cash filter really cuts crashes. Otherwise Bold and Explorer become the same level by
     budget, and only the coin list separates them.
   - Explorer at 95% would leave Bold more room, but the budget would then mean almost nothing.
2. **Balanced and Bold have no position limits.** Their limits allow 100% in ETH (about 93% historical fall
   [derived]), deeper than any budget they could get.
   - Only the budget gate keeps their strategies in line, and the router and permissions have no cash floor or
     per-coin cap to enforce.
   - The new levels would have limits on both sides of them.
3. **Stop-loss ordering.** Balanced requires a stop and Bold does not. If Explorer also requires one, Bold is the odd
   level out.
4. **Per-token cap ordering.** Bold has none, so Bold could hold 100% of one vetted token while Explorer caps other
   tokens at 20%. Either Bold gets a per-token cap or Explorer's is dropped. The exit-cost cap is a fairer common rule.
5. **The hold-this-mix label rule** says "shown as Balanced or Bold". With five levels it needs a general form. I
   propose: the lowest level whose limits allow the mix **and** whose budget its fall fits.
   - Example: a 20% crypto, BTC-heavy mix fell about 23.5-25.6% at the default [measured]. That is under Cash-first's
     25% at the low end, but Cash-first's limits refuse 20% crypto, so it stays Steady.
6. **Steady's limits do not fit Steady's budget.** Steady allows 78% crypto, and every mix of 30% crypto or more fell
   more than 35% [measured]. Cash-first's limits are drawn to fit its budget, which avoids that problem. Tightening
   Steady is still the owner's open question (RISK.md, rebalance-steady section 3).

## 5. What would change on approval

**The YAML** (order lowest to highest; the keys `cash_first` and `explorer` stay even if the display names change):

```yaml
cash_first:                      # working name (owner, 2026-11-25)
  coins: [BTC, ETH, USDC]
  min_cash_pct: 90
  max_coin_pct: 5
  max_drawdown_budget_pct: 25    # interim, owner-approved <date>; replaced by the first audited strategy's MC p95
  hold_mix_max_rebalances_per_30d: 2   # as Steady's: band and reset trades; limit fixes exempt, restart the wait
steady:
  ...unchanged...
balanced:
  ...unchanged...
bold:
  ...unchanged...
explorer:                        # working name (owner, 2026-11-25)
  coins: [BTC, ETH, USDC]        # plus tokens that pass the Explorer vetting, once listed
  min_cash_pct: 0
  max_other_coin_pct: 20         # each token other than BTC, ETH and USDC
  max_position_exit_cost_bps: 100  # a position may not exceed what one swap sells for this cost (measured 0x quote)
  stop_loss_required: true
  max_drawdown_budget_pct: 90    # interim, owner-approved <date>; replaced by the first audited strategy's MC p95
```

`risk_limits` reads only `coins`, `min_cash_pct`, `max_coin_pct` and `max_drawdown_budget_pct`, so the two new keys
are for the app's router. `risk_limits("cash_first")` would read 0.90, 0.05 and 0.25. `risk_limits("explorer")`
reads until other tokens are listed, and then refuses, by design.

**Tests that would break.** I found these by reading the tests, not by running them, because mutation testing is
running:
- `tests/test_portfolio.py::test_the_real_file_sets_steady_s_budget_at_35_and_leaves_balanced_and_bold_missing`
  asserts `sorted(raw) == ["balanced", "bold", "steady"]`. It needs the two new levels, plus pins for their values.
- `tests/test_portfolio.py::test_the_real_file_caps_the_hold_this_mix_tool_at_2_rebalances_in_30_days_in_steady_only`
  asserts the same level list. It also asserts that exactly one line in the file holds `hold_mix_max_rebalances_per_30d`,
  and Cash-first's key would make two. It needs a per-entry check: Steady and Cash-first each hold the key once.
- `tests/test_holdmix_run.py::test_a_steady_level_without_both_limits_is_refused` takes the **first** `min_cash_pct`
  or `max_coin_pct` line in the file. With `cash_first` above `steady`, that line is Cash-first's, so
  `edit_steady`'s exactly-once assertion fails. There are two ways out:
  - look inside the steady entry, as the #55 helpers do (recommended);
  - or put the new entries after `bold`.
  This is the same class of breakage as #55 and #59.
- New test (recommended): pin the new entries, and check that the numeric budgets rise from level to level in the
  order Cash-first, Steady, Balanced, Bold, Explorer.
- I expect no break in `test_steady_scripts.py`, `test_trend_scripts.py` or the hash test of `test_holdmix_run.py`.
  They edit the steady entry by key (the #55 helpers) or take the file's hash at run time. `test_steady.py`,
  `test_holdmix.py` and the other `test_portfolio.py` tests write their own files.
- After the edit, run all three tiers (hard rule 11), and update TESTING.md section 3's `test_portfolio.py` row
  ("balanced and bold MISSING"). Make the edit only after the mutation run finishes, because its copy of `config/`
  and the tests read this file.

**Config hashes and stop rule 10.**
- The config hashes of rebalance-steady, hold-mix-cap and trend-steady all cover this file, so all three move.
- For rebalance-steady and trend-steady, `compare_hashes` takes stop rule 10's exception: only this file differs, and
  Steady's coins, `min_cash` and `max_coin` are unchanged. G6 keeps its run-start value and is never rescored.
- Both are NO EDGE, with no freeze or look pending. A Deviations row is needed only if either is ever frozen.
- hold-mix-cap's run 0 is complete and reads Steady only.
- dip-timing does not hash the file.

**App docs to update:**
- `docs/app/features.md`: the level table's "TBD" cells; "The risk label of a mix" (the general rule, point 5 above);
  "Steady's trade limit for this tool" (Cash-first's own limit); Cash-first presets in "Hold this mix".
- `docs/app/product.md`: its level table and "How the levels work" still list three levels, and so does the Phase 1
  scope line "customer picks Steady, Balanced or Bold".
- `docs/app/technical.md`: "Strategy settings", where the hold-mix limit is read from "Steady's entry" and should read
  from the level's entry; "Auto-trading permission", for the per-level allowlist, the per-token cap and the exit-cost
  cap.
- `docs/app/business.md` and `docs/app/README.md` (level names).
- AGENTS.md's "Risk levels" block and `.claude/agents/risk-officer.md` / `quant-researcher.md` name three levels.
  These are the owner's or director's files, so I only list them here.

## 6. Questions only the owner can answer

1. **Cash-first limits:** 90% cash and at most 5% per coin, so 6% crypto with the lab's margin? Or a wider ceiling,
   knowing the derived worst cases then reach Steady's 35%? Should the lab's 2-point margin be 1 point at this level,
   which would allow 8% crypto?
2. **First budgets (decision 11 for these levels):** approve 25% (Cash-first) and 90% (Explorer) as interim budgets
   now? Or wait for a measured reference-mix run for Cash-first first?
3. **"Clearly separated":** is 10 points between neighbouring budgets the rule? That sets Balanced at 45-70% and Bold
   at most 80%.
4. **Stop-losses:** should Explorer require one, and should Bold then require one too, for consistent ordering?
5. **Single-token concentration:** 20% per non-core token and the 1% exit-cost cap for Explorer? Should Bold get the
   same caps?
6. **Hold-this-mix at Cash-first:** the same limit of 2 rebalances in any 30 days as Steady, or 1?
7. **The label rule for five levels:** the lowest level whose limits allow the mix and whose budget its fall fits?
8. **The Explorer vetting thresholds** (100 bps at 10,000 USD, 1M USD daily volume, 3 years of history): set now, or
   after `data-engineer`'s measurements?

## 7. Owner answers (2026-11-25)

1. **Cash-first: about 8% crypto.** Read as: the limits stay 90% cash and at most 5% per coin, and the lab's margin at this level is 1 point instead of 2, so targets go up to 4% BTC + 4% ETH. Derived worst falls at 8% crypto (the method of section 3): about 12-16% historical, and about 15-25% with the Monte Carlo factor of 1.2-1.6. The deep end reaches the 25% budget, so a measured run at the 8% mixes should come before any Cash-first default is shown.
2. **Interim budgets approved:** 25% (Cash-first) and 90% (Explorer), to be replaced as section 3 describes.
3. **Stop-loss: required at Explorer only.** Bold stays as it is today.

Questions 3 and 5-8 of section 6 are still open. `config/risk_levels.yaml` is still unchanged: writing it, with the test updates of section 5, waits until the TESTING.md 5.4 work is finished.

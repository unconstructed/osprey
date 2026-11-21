# hold-mix-cap: risk-officer review (SCOUTING)

Written 2026-11-21 by `risk-officer`. I reviewed RESULTS.md as it stands uncommitted on top of `1a9512c`, together with
PLAN.md and run 0's outputs: the tracked `decision.json`, `runs.csv` and `falls.csv`, and the git-ignored
`results/hold-mix-cap/run0/runs.parquet` and `summary.json`. I read no bars and ran no backtests. Every number below
I either recomputed from those stored outputs (with scratch scripts outside the repo) or read from them. The only file
I edited is this one. `config/risk_levels.yaml` still has run 0's hash `158d7c9f10eeb664618188455255ca099cc2b265c32833df8a1a37ffab3f16f8`.

Every number here is **SCOUTING**. It comes from the lab's reference engine, not NautilusTrader, with the placeholder
costs and exchange prices standing in for Base prices. All of it is in-sample (2017-2022 only), and every fall is
**hypothetical**: a simulation on past prices.

## Outcome

- **One blocking item: RESULTS.md understates the worst falls** (section 4). Its plain-words summary and its "what the
  falls say" bullets give the falls of the recommended default (band 0.50, cap 1) without saying that is what they are.
  Customers pick their own band and cap, and at the same wallet size and costs the reported configurations fell
  further: up to 42% in 12 months at 20% crypto (45% over the six years), 80% at 70% crypto, and 33% in one day. The
  summary's "35% (20% crypto)" sits right on the 35% Steady budget the owner approved today, so it reads as if 20%
  crypto mixes stayed inside it. The fix is a wording change plus one line of numbers. No rerun is needed.
- **No reported configuration breaks the Steady limits** (section 1). All 27 mixes keep cash at 22% or more and each
  coin at 52.5% or less at target. On every close where drift pushed a wallet past a limit, the rule sent the fix.
- **Limit hits do break through the cap, but only for some mixes** (section 2). It never happened with 20% crypto.
  It happened in about 9 of 10 twelve-month windows with 78% crypto, and often when one coin's target is 45% or more.
- **My recommendation on the open question: yes, keep a hard Steady upper limit of 2 rebalances in any 30 days,
  with limit fixes exempt** (section 5). This is a proposal. The owner decides, and nothing here changes
  `config/risk_levels.yaml`.
- **One more owner decision this review raises:** Steady's 35% budget against the tool's crypto share (section 3).
- **Nothing is approved.** This is a self-directed tool and a scouting study. I write no risk note in
  `reports/hold-mix-cap/`, set no per-strategy limits and write nothing in `exports/`.

## 1. The Steady limits against the results

Limits as read at run 0's start: coins BTC, ETH and USDC; at least 20% cash; at most 60% in any one coin; drawdown
budget `TBD`. With the 2-point headroom, targets must keep cash at 22% or more and each coin at 58% or less.

| Check | Result |
|---|---|
| Spot only | BTC and ETH against USDC, long only, no borrowing. Nothing implies leverage, shorting, market making or arbitrage |
| Coins | BTC, ETH and USDC only, matching the Steady list |
| Targets of every run | 27 mixes in `runs.parquet`. The lowest cash target is 22% (78% crypto) and the highest coin target is 52.5%. **None is outside the limits with headroom.** `run.py` checks all 27 with `check_targets` against the limits as read (recorded in `start.json`) before reading any bar, and refuses to start if one fails. Run 0 started |
| Closes past a limit | 190,022 of the 916,596 runs had at least one close where drift put the wallet past a limit. That is the rule's trigger, not a breach of the rule: the fix goes in at the next open, inside the wait too |
| Was every one fixed? | Yes. In every run, the closes past a limit minus the limit orders sent is 0 (915,495 runs) or 1 (1,101 runs). The 1 is a run's last close, whose decision is never sent, by design (PLAN.md section 4.2). No run left a breach unanswered |
| Empty orders | 0 |
| Parity with the lab's tested rebalancer | 13,338 checks, all bit for bit (`summary.json`) |
| The limit reading | 60% caps BTC and ETH each, not cash and not the two together. **The owner has now confirmed it**: "Steady's max 60% applies per coin, not to cash" (2026-11-21, `reports/director/2026-11-21-owner-answers-trend-steady.md`, recorded before run 0). RESULTS.md still calls it unconfirmed (section 4, request 2) |
| How far past a limit a close went | Not measured by this study (rebalance-steady measured it; this plan did not). One data point: the largest single swap, 55.9% of the wallet (Kraken, 30% crypto with BTC 75% of it, cap 0.25, a 2017 window), was a limit fix inside a 120-day wait. Selling 55.9 points down to a 7.5% target means that coin stood at 63.4% or more of the wallet at the close before the fix, more than 3 points past the 60% limit, for one day |

**What that last row means for the app.** Limits are judged once a day, so a wallet can stand a few points past a
limit for up to a day before the fix. A tight cap (a long wait) lets a mix drift all the way to a limit, and the fix is
then a very large swap. That is why the trade router and the auto-trading permission must never block a fix (section 6).

## 2. How often limit hits broke through the cap

"Broke through" means a limit fix came while the cap's wait was still running. The customer then sees more trades
than the number they set. The rule does this on purpose (the owner's "fix it that day" rule), because a limit fix sells
the coin that rose, or sells crypto when cash falls under its floor. **It lowers risk, so it must stay exempt from any
cap.** The question is only how often the customer's number cannot be kept.

**By cap** (12-month windows, all 6 bands and 27 mixes, 5,000 USD, 1x: 9,720 windows per cap on Kraken, 8,424 on
Binance) (SCOUTING):

| Cap (rebalances a month) | Wait | Windows with a limit fix inside the wait, Kraken / Binance | Windows with more trades than the cap in some 30 days | Share of all limit fixes that came inside a wait |
|---|---|---|---|---|
| 0.25 | 120 days | 31% / 25% | (the wait is the promise) | 88% / 85% |
| 0.5 | 60 days | 23% / 19% | (the wait is the promise) | 82% / 79% |
| 1 | 30 days | 16% / 14% | 16% / 14% | 70% / 65% |
| 2 | 15 days | 10% / 8% | 7% / 6% | 51% / 46% |
| 4 | 8 days | 6% / 4% | 2% / 1% | 32% / 26% |
| 8 | 4 days | 4% / 3% | 0.1% / 0.1% | 11% / 9% |

**By mix**, at the two settings that stay available under the upper limit I recommend (section 5): the default
band 0.50 with cap 1, and band 0.30 with cap 2. Only mixes where it happened at all are listed. (SCOUTING)

| Mix (crypto share; BTC / ETH / cash at target) | Band 0.50, cap 1: windows with an in-wait fix (Kraken / Binance) | worst a year | most trades in 30 days | Band 0.30, cap 2: windows with an in-wait fix | worst a year | most trades in 30 days |
|---|---|---|---|---|---|---|
| 30%: 0 / 30 / 70 | 2% / 0% | 1 | 2 | 0% / 0% | 0 | 2 |
| 40%: 0 / 40 / 60 | 8% / 0% | 2 | 2 | 2% / 0% | 1 | 2 |
| 40%: 10 / 30 / 60 | 2% / 0% | 1 | 2 | 0% / 0% | 0 | 2 |
| 50%: 0 / 50 / 50 | 47% / 38% | 7 | 3 | 25% / 19% | 3 | 3 |
| 50%: 12.5 / 37.5 / 50 | 5% / 0% | 1 | 2 | 0% / 0% | 0 | 2 |
| 50%: 50 / 0 / 50 | 35% / 23% | 2 | 2 | 25% / 12% | 2 | 2 |
| 60%: 15 / 45 / 40 | 23% / 15% | 3 | 2 | 5% / 2% | 2 | 3 |
| 60%: 45 / 15 / 40 | 3% / 0% | 1 | 2 | 2% / 4% | 1 | 3 |
| 70%: 17.5 / 52.5 / 30 | 47% / 38% | 10 | 4 | 55% / 52% | 8 | 4 |
| 70%: 35 / 35 / 30 | 20% / 15% | 3 | 2 | 5% / 2% | 1 | 2 |
| 70%: 52.5 / 17.5 / 30 | 37% / 27% | 3 | 2 | 20% / 8% | 3 | 4 |
| 78%: 39 / 39 / 22 | **88% / 85%** | **22** | **7** | **88% / 87%** | **20** | **7** |

("Worst a year" and "most trades in 30 days" are the worse of the two sources; Kraken is the worse one, or tied, in
every row.)

In plain words:
- **20% crypto: never.** 30-40% crypto: rarely (only mixes with 75% or more of the crypto in ETH, in under 1 window
  in 10).
- **The mixes that break through are the ones parked near a limit:** 78% crypto (cash target 2 points above the
  20% floor) and mixes with one coin at 45% to 52.5% (7.5 to 15 points below the 60% cap). At 78% crypto almost every
  trade is a limit fix: a median of 3 a year inside the wait at the default, up to 22, and up to 7 trades in 30 days.
- RESULTS.md's per-crypto-share table at the default matches these numbers exactly (Kraken 78%: median 3.0, worst
  22.1; Binance 3.5 and 12.0). On Kraken the worst 78% windows held no band trade at all, so all 7 were limit fixes.

**What I suggest the app do with this** (proposals; the owner decides):
- Show "a Steady limit hit can add trades" next to any mix with 70% crypto or more, or with one coin's target at 45% or
  more. That group holds every mix in the table above where the customer's number was broken in 1 window in 5 or more
  (it also holds one mix, 45% BTC, where it was rarer).
- An upper limit on rebalances (section 5) would not change these numbers, because limit fixes stay exempt.

## 3. The worst falls, in plain words

**SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years, in-sample, reference engine, placeholder
costs. Not the worst fall the app shows, and not a drawdown budget.** Falls are shown as positive sizes: "fell 45%"
means 45% below its previous high.

| Crypto share | At the default (band 0.50, cap 1): worst 12 months, Kraken / Binance | At any band and cap: worst 12 months | At any band and cap: worst over the six years | Worst single day, any band and cap | Worst 7 days, any band and cap (six-year runs) |
|---|---|---|---|---|---|
| 20% | 35.3% / 34.6% | 42.0% / 41.8% | 45.0% / 40.7% | 12.7% | 20.3% |
| 30% | 51.1% / 51.0% | 54.3% / 54.1% | 57.3% / 54.0% | 18.1% | 24.4% |
| 40% | 61.4% / 61.3% | 64.5% / 64.1% | 65.6% / 64.8% | 22.2% | 27.8% |
| 50% | 64.6% / 64.4% | 72.7% / 72.5% | 72.5% / 72.5% | 26.1% | 32.9% |
| 60% | 72.2% / 71.9% | 74.7% / 74.6% | 74.8% / 74.5% | 28.7% | 35.4% |
| 70% | 75.5% / 75.3% | 80.4% / 80.1% | 80.4% / 80.1% | 31.2% | 38.3% |
| 78% | 75.6% / 75.8% | 79.7% / 79.2% | 79.8% / 79.2% | 32.7% | 39.4% |

All at a 5,000 USD wallet and 1x costs, the worst over the mixes of each crypto share. The last two columns are the
worse of the two sources. At 500 USD and doubled costs the engine charges the sponsored gas to the wallet, which makes
falls up to about 1 point deeper (81.6% at 70% crypto). The customer does not pay that gas, so I quote the 5,000 USD
numbers.

- **Almost all of it is the 2018 crash:** every row's worst fall runs from a high in mid-January 2018 to a low in late
  November or mid-December 2018. Every worst day is 12 March 2020. The worst weeks are the week to 13 March 2020, and
  at 20-30% crypto the week of 30 January to 6 February 2018.
- **A customer with 20% crypto could have lost 45%** of the wallet over 2018 (Kraken, ETH only, band 0.05, cap 0.25).
  At 70-78% crypto, about four fifths.
- **A loss limit is not a cap on losses.** In one day the wallet could have lost up to 13% at 20% crypto and a third at
  78%. The day's fall has already happened when the daily or weekly loss limit pauses the tool.
- **Rebalancing does not soften a crash; the crypto share does.** In the 2018 crash, trading back to the mix (buying
  coins as they fell) made the deepest falls of the recommended settings 75.6-80.0% (Kraken), against 68.1% for a mix
  bought once and touched only at a Steady limit. In a typical window the tool fell slightly less. Band and cap moved
  the worst fall by up to about 10 points; the crypto share moved it by about 40.

**Against Steady's drawdown budget.** On 2026-11-21 the owner approved a Steady budget of **35%**
(`reports/director/2026-11-21-owner-answers-trend-steady.md`). It is not yet in `config/risk_levels.yaml`, which is why
this run read `TBD`, correctly. The budget is a gate on strategies, measured as the Monte Carlo 95th-percentile fall of
an audited strategy, which usually comes out deeper than the history. So the comparison below is a pointer, not a test:
- **Only 2 of the 27 mixes stayed within a 35% fall** at every band, cap and window, on both sources: 20% crypto with
  75% or 100% of it in BTC. At the default band and cap, the 20% crypto mixes stayed within it, except ETH only on
  Kraken (35.3%).
- **Every mix with 30% crypto or more fell more than 35% in at least one 12-month window, even at the default band and
  cap.** Across all bands and caps, the share of 12-month windows past 35% was 1% at 20% crypto, 9% at 30%, 29% at 40%,
  47% at 50%, 75% at 60%, 93% at 70% and 97% at 78% (Kraken; Binance within 1 point).

Whether the 35% budget also limits the tool's crypto share is an open owner question (`docs/app/features.md`, "Hold
this mix"). My view, as a proposal: **a product should not ship under a label whose limits it is known to break.** So
either (a) under the Steady label the tool offers only crypto shares whose hypothetical worst fall fits the budget (on
this evidence, about 20%), or (b) the owner decides in writing that the budget does not apply to self-directed tools,
and the app shows each mix's hypothetical worst fall next to "Steady's budget: 35%" with a plain "this mix fell further
than Steady's budget". Either way it should be decided before launch. It is separate from the upper-limit question.

## 4. RESULTS.md: risk statements checked

**Recomputed from the stored outputs and matching RESULTS.md:**
- the per-crypto-share table at the default (rebalances, limit fixes inside the wait, most in 30 days, their medians
  and worst values);
- the falls tables at the default, and the "Deepest over every band and cap (12-month windows)" column (Kraken 42.0,
  54.3, 64.5, 72.7, 74.7, 80.4, 79.7, exactly);
- the rule C headline in `decision.json`: limit at 2, value test SUPPORTED, bands held back 0.05-0.20, CONFLICT no,
  NOT ROBUST;
- the largest swaps (55.9% and 61.8% for the tool; 56.9% and 63.6% for limit-only).

**Blocking (1).** The worst falls are understated where the owner will read them.
- *Where:* "In plain words" (line 19): "Worst falls, hypothetical (past prices, in-sample): 35% (20% crypto) to 76% (78%
  crypto) in 12 months, about 30% in one day." And "What the falls say" (lines 859-870), whose first and last bullets
  read as bounds ("from 35% ... to 76%", "up to 29.2% in one day ... and 36.3% in 7 days").
- *Why it matters:* these are the default band's falls only, and nothing in those lines says so. The customer picks the
  band and cap. At the same 5,000 USD and 1x, other bands and caps fell to 42-80% in 12 months, 45% over the six years
  at 20% crypto, 32.7% in one day and 39.4% in 7 days. The "Deepest over every band and cap" column covers the 12-month
  windows only, so it does not show the 45% either. And "35% (20% crypto)" lands exactly on the owner's new 35% Steady
  budget, so a reader would take 20% crypto as being within it.
- *Fix (wording only, no rerun):*
  1. Line 19: "Worst falls, **hypothetical** (past prices, in-sample), at the recommended default (band 0.50, cap 1):
     35% (20% crypto) to 76% (78% crypto) in 12 months, and up to 29.5% in one day. At other bands and caps the same
     crypto shares fell further: 42% (20% crypto) to 80% (70% crypto) in 12 months, 45% over the six years at 20%
     crypto, and up to 33% in one day. Steady's budget, approved by the owner on 2026-11-21, is 35%."
  2. Lines 859 and 868: start each with "At the default band and cap", and add to the worst-day bullet: "at any band
     and cap (5,000 USD, 1x): up to 32.7% in one day (78% crypto, Binance, band 0.10) and 39.4% in 7 days (78% crypto,
     Binance, band 0.05, no cap)".
  3. Under the two by-crypto-share tables: "The deepest column covers the 12-month windows. Over the six-year runs,
     other bands and caps fell further at low crypto shares: 45.0% at 20% crypto (Kraken, ETH only, band 0.05, cap
     0.25), 57.3% at 30% and 65.6% at 40% (Kraken)."

**Requests, not blocking.**
2. **The owner's answers of 2026-11-21, recorded before run 0.** "Max 60% applies per coin, not to cash": the limit
   reading is now the owner's. Known weaknesses (line 988, "not yet the owner's") and the "Other readings of the Steady
   limits" table should say that those rows describe readings the owner did not choose. Steady's 35% budget: worth one
   line next to the falls (the run record's "TBD" is right as read).
3. **"Limit fixes alone made up to 7 rebalances in 30 days (Kraken; 6 on Binance)"** (lines 115-116). True on Kraken.
   On Binance, the worst 78% windows also held one band trade, so say "up to 6 rebalances in 30 days, limit fixes
   included".
4. **Pauses** (Known weaknesses, lines 990-993). The owner also answered (same record, answer 3) that sells to cash go
   through during a loss-limit pause or while waiting for approval, while buying stays stopped. It was recorded for
   trend-steady as a decision for the app docs. If it applies to this tool too, a limit fix that only sells could still
   go through during a pause, and "drifts past Steady's limits" would hold for the buy side only. Ask the owner, then
   align RESULTS.md and `features.md`.
5. **Trade sizes are the largest seen in 2017-2022, not bounds** (open question 5). The largest swap came from a cap of
   0.25 holding back band trades for 120 days until a coin passed 60%. A worse year could need a larger fix. Section 6
   gives my answer.

## 5. Recommendation on the open question: a Steady upper limit on rebalances

The owner asked whether Steady should keep a hard upper limit on rebalances a month above the number the customer sets,
and said they do not know how to answer it.

**My recommendation: yes. A hard Steady limit of 2 rebalances in any 30 days (at least 15 days between trades back to
the mix), counting band and reset trades. Limit fixes stay exempt: they always go through, they still count, and they
restart the wait, exactly as the tool works today.** The customer can still pick a lower number. If you have no
preference, adopt it. This agrees with the lab's proposal in RESULTS.md.

Why, from the risk side:
1. **It is the steadiest result of the study.** The limit at 2 and its value test held on both data sources, at
   normal and doubled costs, at every wallet size, under every reading of the 60% limit, and in all 8 boom-year
   checks. The recommended default band moved; this did not.
2. **It gives up very little.** A cap of 2 a month already got about 95% of the closeness to target that unlimited
   daily rebalancing gets (94.5% Kraken, 95.1% Binance). The last 5% cost 21-30% of the extra fees.
3. **It does not weaken any Steady limit,** because limit fixes are exempt. If it turns out too tight, the cost is mixes
   a little further from target, not wallets past a limit.
4. **It does not make falls worse.** The bands it rules out (0.05 to 0.20) had the deepest crash falls among the
   recommended settings: 79.4-80.0% on Kraken, against 78.1% at 0.30 and 75.6% at 0.50 (in-sample, a small difference,
   not a reason on its own).
5. **It caps our own costs and exposure.** Gas is sponsored, so it is our cost: on average 2.13 USD per customer a year
   at cap 2, against 4.33 USD with no cap (Kraken, all bands and mixes), and a median of 4.80 USD at band 0.10 with cap
   8 (placeholder gas). Fewer swaps also mean
   fewer chances for a failed swap or a bad fill.
6. **It matches the owner's own rule for Steady** (2026-11-20): cap rebalancing unless rebalancing that often is shown
   to pay. Nothing has shown that it pays: this study uses no returns, and the first Steady study found nothing in
   rebalancing timing.
7. **It errs the right way.** Loosening a limit later needs your written approval; tightening does not. Starting at 2
   and loosening on evidence is safer than starting at 4 and taking bands away from customers who already use them.

What it costs:
- The app could not offer bands 0.20 or narrower for Steady (they need 4 or more rebalances a month to stay in their
  band). The app would offer 0.30 (cap up to 2) and 0.50 (recommended cap 1).
- The single default is unchanged: 0.50 with a cap of 1. If the app defaults by wallet size, wallets up to 5,000 USD
  would get 0.30 with a cap of 2 instead of 0.20 with a cap of 4.

What it does not do:
- It does not bound limit fixes. Mixes near the limits (78% crypto; one coin at 45% or more) will still trade more
  than 2 times in 30 days at times (section 2). The app should say so next to those mixes.
- It does not reduce the falls in section 3. Only the crypto share does that.

Where the number is fragile: measured by days outside the customer's own band instead of distance from target, the
same rule says 4, and band by band it ranges from 0.5 to 4. If the owner prefers the customer's number as the only cap,
the alternative is workable, but then the app should at least not offer band 0.05 with any cap, and should recommend
the study's cap for the band picked.

How it would be put in place, only after your written yes:
- `risk-officer` adds one key to Steady's entry in `config/risk_levels.yaml` (for example
  `max_rebalances_per_30d: 2`, with a comment that limit fixes are exempt), with tests. The app's rule engine and trade
  router read it from there. It is never a constant in `holdmix.py` or in app code.
- In the tool it is the same mechanism as the customer's cap: the app does not offer a cap above 2, so the wait is
  at least 15 days.
- Before the edit, check that rebalance-steady's guard on `risk_levels.yaml` (stop rule 10, written to let a budget
  change through) accepts a new key. `research/hold-mix-cap/` hashes that file too, so any later amendment run here
  would record a new config hash.

## 6. Production controls the app should enforce

The lab cannot set these. They are for the app team and the owner.
1. **Coins.** The auto-trading permission and the trade router allow only cbBTC, ETH and USDC for this tool.
2. **Targets.** The router refuses any mix whose targets leave less than 22% cash or more than 58% in one coin (the
   Steady limits with the 2-point headroom), read from `config/risk_levels.yaml`, never hard-coded.
3. **Limit fixes are never blocked.** A trade back to the mix that brings the wallet back inside the Steady limits goes
   through at the next daily check, inside the customer's wait and inside any upper limit. Fail-closed rules must not
   block it. If the router refuses it anyway, the app sends the "limit hit" push and retries at the next daily check.
   An alert fires if a wallet stays past a limit for more than one daily check.
4. **Amount caps on the auto-trading permission.** A full trade back to the mix in 2017-2022 needed up to 56% of the
   wallet in one swap and 62% in one day (57% and 64% for a mix touched only at limit hits), and the first buy needs up
   to 78% of the wallet in one day. These are the largest seen, not bounds. My requirement: the per-trade and per-day
   caps must allow a full trade back to the customer's own mix, whatever its size. If the app uses fixed percentages,
   at least 60% per swap and 80% per day, and anything larger goes to the customer for approval with the "limit hit"
   push, never silently dropped. The router's slippage protection must not block a fix for good either.
5. **Order of legs.** Sell legs before buy legs, and check cash and the coin caps after the whole trade, not leg by leg.
6. **The wait.** It works exactly as in `lab/runner/holdmix.py`: counted in calendar days from the last rebalance, the
   first buy not counted and not starting it, limit fixes exempt but counted. A decision-parity test against `hold_mix`
   belongs with the app's rule engine.
7. **The upper limit, if adopted:** read from `config/risk_levels.yaml`; the app offers customer caps of at most 2 and
   Steady bands of 0.30 and 0.50 only.
8. **Pauses.** Pause everything and the loss limit stop the tool. Whether a sell-only limit fix may still go through
   during a pause is the owner's question in section 4, request 4.
9. **Small swaps.** The study simulated swaps down to a fraction of a cent, each paying 0.10 USD of our gas. If the app
   adds a minimum swap size, it should apply to band and reset trades only, never to the main leg of a limit fix, and
   the study would need a rerun before the app shows its numbers (decisions would then depend on wallet size).
10. **What the customer sees.** The hypothetical worst fall for the chosen mix, band and cap, naming 2017-2022 and
    labelled in-sample, next to the crypto share and next to Steady's 35% budget; the worst single day (up to a third
    of the wallet at 78% crypto) next to the loss-limit setting, with "a loss limit pauses the tool; it does not cap a
    loss"; and "a Steady limit hit can add trades" for the mixes in section 2.

## 7. Not approved, and what is still open

- No approval, no risk note in `reports/`, no per-strategy limits and no export. The tool is self-directed, the study
  is scouting, and nothing here was audited on NautilusTrader.
- **Steady's 35% budget** was approved by the owner on 2026-11-21 and held back until this run finished, because the
  run hashes `config/risk_levels.yaml`. The run is done, so `risk-officer` should now write
  `max_drawdown_budget_pct: 35` in its own change, with its tests. Not done in this review, which edits nothing in
  `config/`.
- **Owner decisions this review asks for:** (1) the upper limit of 2 (section 5); (2) whether the 35% budget limits the
  tool's crypto share under the Steady label (section 3); (3) whether a sell-only limit fix may go through during a
  pause (section 4, request 4).

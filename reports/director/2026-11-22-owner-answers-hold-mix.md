# Owner answers on "hold this mix": one default, Steady's trade limit, risk labels (2026-11-22, in chat)

Asked with AskUserQuestion on 2026-11-22, after hold-mix-cap run 0, its audit and its risk review
(`research/hold-mix-cap/`: RESULTS.md, AUDIT.md, RISK.md and `decision.json`). Questions 1 to 3 are RISK.md section 7's
owner decisions (1) and (2) and RESULTS.md's open questions 1 to 3 for the owner. Question 4 asks whether the new limit
also applies to our own Steady strategies. Recorded by `director`.

Every hold-mix-cap number here is **SCOUTING**: it comes from the lab's reference engine, not NautilusTrader, with
placeholder costs and exchange prices standing in for Base prices. It is in-sample, from the 2017-2022 train years
only. Every fall is hypothetical (a simulation on past prices). The study approves nothing and claims no edge.

## The questions and the answers, exactly as asked and given

1. **Q1:** "Hold-this-mix default setting: should every customer get the same default (trade when a coin is 50% off
   its target, max 1 trade a month), or should small wallets (about $5,000 or less) get a tighter default (20% off,
   max 4 trades a month)? The tighter default only won in our tests because of the made-up fees."
   **Answer:** "Same for everyone (Recommended)" (option text: "50% off target, max 1 trade a month. Simpler and holds
   up better in the tests.")
   *Note (the lab's, added in review; not the owner's words):* the question's second sentence and the option's "holds
   up better in the tests" are not what the study found. The single 0.50 default is the one that depends on
   placeholder fees: it is 0.50 only because 50,000 USD wallets at doubled costs pay more than 0.25% a year at the
   narrower bands, so it is labelled NOT ROBUST, and it moved in 6 of the 8 boom-year checks. The 0.20 default with
   cap 4 for 500 and 5,000 USD wallets held at both cost levels and on both sources, and in 8 and 7 of the 8 boom-year
   checks (RESULTS.md, headline and boom-year addendum, the b\*(500) and b\*(5000) columns). Under Q2's limit the real
   alternative would have been 0.30 with cap 2 for wallets up to 5,000 USD, which was not asked. The answer is
   recorded as given; the owner is asked to confirm it or answer again (item (h) below). The owner may well keep one
   default for simplicity.
2. **Q2:** "Should Steady have a hard limit of at most 2 trades back to the mix in any 30 days? Customers can still
   choose fewer. Trades that fix a Steady limit breach (for example, too much in one coin) always go through. This
   means Steady can't offer settings tighter than 30% off target."
   **Answer:** "Yes, max 2 a month (Recommended)" (option text: "Our risk reviewer recommends it. It keeps about 95% of
   the benefit and saves about 25% of the extra fees.")
3. **Q3:** "In our 2017-2022 tests, only mixes with about 20% crypto stayed within Steady's 35% loss limit. Mixes with
   more crypto fell 40-76% in their worst year. What should the app do with those higher-crypto mixes?"
   **Answer:** "Label them by risk (Recommended)" (option text: "Any mix is allowed, but mixes that fell more than 35%
   in the past are shown as Balanced or Bold, not Steady.")
   *Note (the lab's):* "40-76%" rounds away the mixes near the line. At the default band and cap, 30% crypto with 75%
   or all of it in BTC fell 35.6-36.4% in its worst 12 months (both sources), and at most 38.6-39.7% at any band and
   cap (RESULTS.md, the by-mix falls tables). The 35% line the owner set is unaffected; these mixes matter for item
   (a).
4. **Q4:** "You just approved 'Steady: at most 2 trades back to the mix in any 30 days' for the hold-this-mix tool.
   Should that same limit also apply to our own Steady strategies? For example, the trend-following one we're about
   to test checks prices weekly and could trade up to 4 times a month."
   **Answer:** "Only the hold-this-mix tool (Recommended)" (option text: "Our strategies have to pass the lab's checks
   with costs on, so too much trading already shows up as a failure. The trend test still reports how often it
   trades.")

## What the answers mean, as the lab reads them

These are the lab's readings of the answers, not the owner's words.

1. **One default for every customer** (Q1): drift band 0.50 (trade back when BTC or ETH is more than 50% off its
   target) with a cap of 1 rebalance a month, that is at least 30 days between trades back to the mix. A Steady limit
   hit can add trades. There is no default per wallet size. The default is labelled NOT ROBUST: it depends on the
   placeholder fees of 50,000 USD wallets and on which boom years are in. So it must be rechecked with measured Base
   costs before customers see a number.
2. **A hard Steady limit for the hold-this-mix tool only** (Q2 and Q4): at most 2 rebalances in any 30 days, enforced
   as at least 15 days between trades back to the mix, counting band and reset trades.
   - **Limit fixes are exempt.** A limit fix is a trade that brings the wallet back inside a Steady limit (cash under
     20%, or one coin over 60%). Neither the wait nor the limit of 2 holds it back: it goes through at the next daily
     check, even inside the wait. It is not one of the 2, but it restarts the wait, exactly as the tool works today.
     A pause, or a trade on Approve that the customer does not approve, still holds it; whether a sell-only fix may go
     through during a pause is item (f).
   - **The customer may pick a cap lower than 2, never a higher one.** The recommended cap for the band (below) is a
     recommendation, not a ceiling: a customer on the 0.50 band may pick 2.
   - **Only two bands are offered:** 0.30 (recommended cap 2) and 0.50 (recommended cap 1). The question the owner
     said yes to reads "Steady can't offer settings tighter than 30% off target"; offering exactly the two bands of
     30% or wider that the study tested is the lab's reading. Any other band of 30% or wider, such as 40%, was not
     simulated. Bands of 0.20 and narrower are not offered, because their recommended caps are 4 or more a month
     (0.05: none up to 8).
3. **Our own Steady strategies are not capped by it** (Q4). The owner's Steady guardrail of 2026-11-20 still applies
   to them: "a few trades a month" caps the drift band and check frequency, unless rebalancing that often is shown to
   pay. They must also pass the lab's checks with costs on. The trend-steady study still reports how often it trades.
4. **Label by risk** (Q3). The answer the owner chose reads "Any mix is allowed"; the lab reads this as any mix the
   Steady limits allow: at least 20% cash and at most 60% in any one coin, with the lab's 2-point margin. Whether
   those limits still apply to a mix labelled Balanced or Bold is item (e). A mix whose hypothetical past worst fall
   is more than 35% (Steady's drawdown budget) is shown under Balanced or Bold, not Steady. The open items this
   raises are listed below.
5. Nothing here approves a strategy, sets Balanced's or Bold's budget, or changes the lab's gates.

**The answers fit together.** The default needs 1 rebalance a month, under the limit of 2: N\*_rob(0.50) = 1 ≤ 2, so
rule D's CONFLICT is "no" (RESULTS.md, headline). Under the limit, a per-size default for wallets up to 5,000 USD would
have been 0.30 with cap 2 instead of 0.20 with cap 4. Q1's answer sets that aside unless the owner answers it again
(item (h)).

The default moved in 6 of the 8 boom-year checks (AUDIT.md):
- to 0.30 in 5 of them (with cap 2, or cap 1 without the best two years), a band the tool still offers;
- to "no band met the conditions" for 50,000 USD wallets in 1 (without 2019).

## The evidence behind each answer (SCOUTING)

**Q1, one default.** The headline default is band 0.50 with cap 1 (`decision.json`, `robust.headline`).
- **Why it is NOT ROBUST.** It is 0.50 because at doubled costs a 50,000 USD wallet pays more than the 0.25% a year
  limit at narrower bands. On Kraken that is 0.338% at 0.20 (cap 4) and 0.273% at 0.30 (cap 2); only 0.50 passes, at
  0.189%. On Kraken at normal costs alone, the default would be 0.20 with cap 4.
- **The per-size default the owner turned down.** 0.20 with cap 4 for wallets up to 5,000 USD. It keeps coins about
  twice as close to target (typically 9% of the target away, not 20%). It costs 5 times the rebalances and about
  twice the fees: 0.11% against 0.06% of the wallet a year at 5,000 USD. Every fee here is a placeholder.

**Q2, the limit of 2.** Rule C: EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED. That held on both sources, at both
cost levels, at every wallet size, under both other readings of the 60% limit, and in all 8 boom-year checks.
- **What 2 keeps.** Over all 6 bands and 27 mixes, a cap of 2 a month got 94.5% (Kraken) and 95.1% (Binance) of the
  closeness to target that unlimited daily rebalancing buys over trading only at the limits.
- **What the rest costs.** The remaining closeness took 24-30% (Kraken) and 21-26% (Binance) of the extra fees of
  unlimited rebalancing.
- **Our gas.** Gas is sponsored, so it is our cost: 2.13 USD per customer a year at cap 2, against 4.33 USD with no
  cap (Kraken, placeholder gas).
- **Where 2 is fragile.** Measured by days outside the customer's own band instead of distance from target, the same
  rule gives 4. Band by band it gives 0.5 to 4.

**Q3, the risk label** (falls at a 5,000 USD wallet, 1x costs; RISK.md section 3 and RESULTS.md, "Falls").
- **Only 2 of the 27 mixes stayed within a 35% fall at every band, cap and window, on both sources:** 20% crypto, with
  75% or all of the crypto in BTC.
- **At 20% crypto, 4 of the 5 mixes stayed within 35% at the default band and cap.** ETH only did not: it fell 35.3%
  on Kraken.
- **Every mix with 30% crypto or more fell more than 35% in some 12-month window**, even at the default. Some sit just
  past the line: 30% crypto with 75% or all of it in BTC fell 35.6-36.4% in its worst 12 months at the default.
- **The share of 12-month windows past 35%**, across all bands and caps: 1% at 20% crypto, 9% at 30%, 29% at 40%,
  47% at 50%, 75% at 60%, 93% at 70% and 97% at 78% (Kraken; Binance within 1 point).
- **The crypto share moved the worst fall by about 40 points;** the band and cap moved it by up to about 10.

**Q4.** The hold-mix-cap study simulated the tool only, so it has no evidence on our strategies. The trend-steady
study is still being designed.

## What changes where

- **`config/risk_levels.yaml`:** Steady's entry gains `hold_mix_max_rebalances_per_30d: 2`, in the same commit as
  this record (hard rule 10: approved here by the owner, Q2). Its comment says three things: it is for the
  self-directed hold-this-mix tool only, not our strategies; it is enforced as at least ceil(30 / value) days between
  trades back to the mix (15 at 2), counting band and reset trades; and limit fixes are exempt: the wait never holds
  them back, they are not among the 2, and they restart the wait.
  - The app's rule engine and trade router read the number from there and derive the wait from it (30 / 2 = 15 days).
    It is never a constant in app code or in `lab/runner/holdmix.py` (RISK.md section 5).
  - The key sits in Steady's entry and its comment names the tool. That does not settle item (e): whether the limit
    also applies to a mix labelled Balanced or Bold.
  - Nothing else in the file changes. The Steady limits (20% cash, 60% per coin) and the 35% budget are unchanged, and
    Balanced's and Bold's budgets stay TBD.
  - Two studies hash this file (checked on the file as it now reads):
    - `research/rebalance-steady/`: its config hash is now `5c7aaa9f…` (run 0 recorded `1506217f…`; `f689da6f…`
      after TESTING.md #55). `study.compare_hashes` against run 0's recorded start: only `config/risk_levels.yaml`
      differs and the Steady coins and limits are unchanged, so stop rule 10's exception is taken (G6 keeps run 0's
      TBD and is never rescored). If a freeze or a look follows, its RESULTS.md needs a Deviations row for this
      change.
    - `research/hold-mix-cap/`: its config hash is now `7d679f5a…` (run 0 recorded `a227c167…`; `29fb8cfc…` after
      #55); only `config/risk_levels.yaml` differs from run 0's start. Run 0 is complete and stays as recorded; any
      later amendment run would record the new config hash (RISK.md section 5).
- **`tests/test_portfolio.py`** gains 3 tests that pin the key (154 → 157 tests in the file; no other test changes):
  - `test_the_real_file_caps_the_hold_this_mix_tool_at_2_rebalances_in_30_days_in_steady_only`: the value is the
    integer 2, in Steady's entry only, written once;
  - `test_the_hold_this_mix_cap_is_a_15_day_wait_in_the_engine`: `holdmix.wait_days(2) == 15`, and ceil(30 / 15) = 2
    band or reset trades in any 30 days;
  - `test_the_hold_this_mix_cap_leaves_steady_s_risk_limits_unchanged`: `risk_limits("steady")` gives the same keys
    and values with and without the key (only the file's hash moves).
- **`TESTING.md`** must record these tests (section 3: `test_portfolio.py` 154 → 157 and what they pin) and the full
  tier on the commit that carries the config and test change (hard rule 11), as #55 was recorded. That edit is not
  part of this record. On the uncommitted tree that carries this record (HEAD `368b90a`), the full tier gave 1886
  passed (12 of them slow), 100% branch coverage of `lab/` (4896 statements, 1440 branches), in 320 s; ruff clean.
- **`docs/app/`:** these decisions are now stated in:
  - `features.md`: "Hold this mix", its subsections, the feature catalog row, the "Hold a mix of your own" flow, the
    Steady settings and the open questions;
  - `technical.md` (Strategy settings), `README.md`, `product.md` and `business.md`.
  The scouting caveats stay: every number comes from 2017-2022 in-sample runs on placeholder costs, and is rechecked
  with measured Base costs before customers see it.
  - `features.md` also closes two questions of 2026-11-21: whether Steady's "at most 60%" is per coin, and whether it
    applies to cash. Both rest on the 2026-11-21 record's answer 4 ("Steady's 'max 60%' applies per coin, not to
    cash", `2026-11-21-owner-answers-trend-steady.md`). "Not the two together" stays `risk-officer`'s reading (RISK.md
    section 1).
- **Not changed:**
  - `research/hold-mix-cap/`. RESULTS.md, AUDIT.md and RISK.md are audited records and stay as written; their open
    owner questions are answered here, not there.
  - `lab/`, AGENTS.md and the lab's gates.

## What it does not do

- **It approves no strategy.** "Hold this mix" stays a self-directed tool. It is not put through the lab's checks, and
  the checks are unchanged.
- **It sets no budget for Balanced or Bold.** Both stay TBD in `config/risk_levels.yaml`.
- **The limit does not bound limit fixes.** Mixes near the limits will still trade more than twice in 30 days at
  times: 78% crypto, or one coin's target at 45% or more (RISK.md section 2). At 78% crypto, at the default band and
  cap, that was up to 7 rebalances in 30 days (Kraken).
- **The limit does not reduce the falls.** Only the crypto share does that.
- **It does not cap our own Steady strategies** (Q4).
- **It does not make the default robust.** The default stays NOT ROBUST until it is rechecked with measured Base costs,
  and on NautilusTrader once the lab's runner exists (AGENTS.md hard rule 3).
- **The label approves no mix and tests none.** It changes neither the Steady limits nor which mixes can be picked.
- **No number is ready for customers yet.** The worst fall the app shows will come from Nautilus backtests with
  measured costs, over years agreed with `backtest-auditor` (RESULTS.md, known weaknesses).

## Still open, and who decides

None of these is decided here. Where a proposal is obvious, it is marked as a proposal.

- **(a) Which number decides the label.**
  - *The problem:* the study's falls are in-sample, scouting and on placeholder costs. Steady's budget is defined as
    the Monte Carlo 95th-percentile max drawdown of an audited strategy, which usually comes out deeper than the
    history (RISK.md section 3).
  - *Also open:* at which band and cap the number is taken (they moved the worst fall by up to about 10 points), and
    which years the backtests cover (already open in `docs/app/features.md`).
  - *Who decides:* the owner, on `risk-officer`'s proposal, with `backtest-auditor` agreeing the years.
  - *Proposal:* the label uses the same measure as the budget, so that both mean the same thing. That is the Monte
    Carlo 95th-percentile max drawdown, from Nautilus backtests with measured Base costs, taken over every band and cap
    the tool offers for that mix, so the label does not change when the customer moves the band or the cap. The
    historical worst fall is shown next to it. Mixes near the line, such as the 30% crypto mixes above, are where this
    choice matters.
- **(b) Where Balanced ends and Bold begins.** Balanced's and Bold's budgets are still TBD in
  `config/risk_levels.yaml`, so that line is undefined.
  - *Who decides:* the owner approves each budget (AGENTS.md: a level's budget is owner-approved; hard rule 10), on
    `risk-officer`'s proposal.
  - *No proposal.* The options include setting Balanced's budget before launch, or showing every mix past 35% under
    Bold until it is set.
- **(c) Balanced requires a stop-loss** (`stop_loss_required: true`), and the tool has none. The customer's loss limit
  pauses the tool and sells nothing, so it is not a stop.
  - *Who decides:* the owner, with `risk-officer`, who owns that file.
  - *No proposal.* The options are: give the tool a stop for mixes labelled Balanced (a new feature; the study
    simulated none); decide in writing that Balanced's stop-loss rule does not apply to the self-directed tool; or show
    such mixes under Bold.
- **(d) Bold's coin list is empty in `config/risk_levels.yaml`.**
  - *Who decides:* `risk-officer` and `data-engineer` vet the list, and the owner approves the change (hard rule 10).
  - *Also open:* whether a mix may be shown under Bold if Bold's vetted list leaves out BTC or ETH.
- **(e) Whether the tool works the same way for a mix labelled Balanced or Bold.** That covers Steady's coin and cash
  limits and the limit of 2 rebalances in any 30 days.
  - *Who decides:* the owner.
  - *Proposal:* keep the same mechanics for every mix, because they are the only ones the study simulated. Anything
    else needs a new simulation before the app shows its numbers.
- **(f) Whether a sell-only limit fix may go through during a pause, or while waiting for approval** (still open from
  RISK.md section 4, request 4, and section 7, item 3).
  - *Who decides:* the owner.
  - *Background:* the owner answered it for our trend strategy only (sells to cash go through, buying stays stopped;
    `2026-11-21-owner-answers-trend-steady.md`, answer 3), not for the tool.
- **(g) Raised while writing this record: the usual warning and confirm.** When a customer picks a mix labelled above
  their own chosen level, does the app show the warning and confirm it shows for a strategy above their level
  (`docs/app/features.md`, "Customers choose, we label")?
  - *Who decides:* the owner.
  - *Proposal:* yes, the same warning and confirm.
- **(h) Raised in review: Q1's premise.** The owner answered Q1 on a premise the study does not support (the note
  under Q1): the single 0.50 default is the one that rests on placeholder fees, while 0.20 with cap 4 for wallets up
  to 5,000 USD held across sources, cost levels and most boom-year checks.
  - *Who decides:* the owner: confirm "Same for everyone", or answer again.
  - *Background:* under Q2's limit the per-size alternative would be 0.30 with cap 2 for wallets up to 5,000 USD
    (RESULTS.md, "Why NOT ROBUST"). Until the owner answers, the docs keep one default for every customer, as
    answered.

**Unchanged and still open:**
- the auto-trading permission's amount caps, which must allow a full trade back to the mix (RESULTS.md open question 5;
  RISK.md section 6);
- whether the app skips swaps under a minimum size (RESULTS.md open question 6);
- whether Steady launches with the tool only, if no Steady strategy of ours passes by launch.

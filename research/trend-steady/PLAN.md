# trend-steady: pre-registration

**Status: pre-registration, written 2026-11-22 by `quant-researcher` before any trend-steady result exists;
reviewed the same day by `backtest-auditor` and `risk-officer`, and revised for every blocking finding of that review
(amendments M9-M18) and the suggestions taken (M19-M22); committed as the pre-registration, before any result. Not
frozen: FROZEN.json is written only before an earned validate look (section 13).** [M22] This file is the draft of
2026-11-21, kept byte for byte next to it as
[PLAN_DRAFT_2026-11-21.md](PLAN_DRAFT_2026-11-21.md) (SHA-256
`95b84fba8c3863cd534c96140ef52260eb950a11daa4062c9d5a03d415f23045`, last written 2026-11-21 16:11 UTC), plus the
named amendments **M1-M8 of 2026-11-22** and **[M22]** the review amendments **M9-M22 of 2026-11-22**. Their table
is in section 15. Every place they change is marked **[Mk]**,
and `diff PLAN_DRAFT_2026-11-21.md PLAN.md` shows every changed line. Struck text (~~like this~~) is the draft's,
kept for the record; it does not apply. Repo HEAD at writing `d5b34bc` (branch `claude/tender-brown-g86h44`);
`52d7ee1` (2026-11-22 15:09 UTC: `docs/app/` and the 2026-11-22 owner record only, not read) landed while it was
written, and `config/risk_levels.yaml` is the same in both. **[M22]** The review amendments were written on HEAD
`52d7ee1`, the parent of the commit that freezes this plan. No trend-steady code exists, no catalog bar was read for
this plan, and no trend rule has been run on market data.

The draft's own status (2026-11-21, unchanged in substance): assembled in a scratch folder from four independent plan
sketches (appendix A), before any trend-following result existed, and audited the same day by an independent
`backtest-auditor` pass (Critique log at the end; the pre-audit text is `audit/PLAN_DRAFT.before_audit.md` in the
session scratchpad). Repo HEAD at drafting `652eefc`.

- Data snapshot `1746a21b75683e76`, bars content hash `08f5ca2c…`, as recorded in rebalance-steady's DATA.md and
  RESULTS.md.
- Risk level **Steady**: coins BTC and ETH, with USDC as cash.
- ~~**Branch F (fixed settings)** unless the owner approves a Steady drawdown budget in writing before the freeze
  (section 8, owner question 1).~~
- **Branch: R** [M1]. Steady drawdown budget **35%** (`max_drawdown_budget_pct: 35`), owner-approved in writing on
  2026-11-21 (`reports/director/2026-11-21-owner-answers-trend-steady.md`, commit `b05109e`, 16:31 UTC) and written
  into `config/risk_levels.yaml` with its tests by commit `368b90a` (2026-11-21 22:53 UTC).
  `config/risk_levels.yaml` SHA-256 at HEAD `d5b34bc`, and **[M22]** unchanged at `52d7ee1`, the parent of the commit
  that freezes this plan: `d3f58253dfc2dbbe0ca5e54a4fa12489ab0e08827ecbc309e8ab2b7cc028723e`. (The file also holds
  the hold-this-mix tool's `hold_mix_max_rebalances_per_30d: 2`, added by `9e96841`; this study does not read it.) If the file changes before
  the commit that freezes this plan, that commit puts the new SHA-256 here, and the reviewers check that the Steady
  coins, `min_cash_pct`, `max_coin_pct` and the budget are still the ones quoted (stop rule 11).

**Owner decisions that bind this study** (records in `reports/director/`; quoted with their dates) [M1-M4, M8]:
1. **Steady drawdown budget 35%; Branch R opens** (2026-11-21, `2026-11-21-owner-answers-trend-steady.md`, `b05109e`,
   16:31 UTC): "The Monte Carlo 95th-percentile max drawdown (AGENTS.md gate) must stay within a 35% fall from the
   high point." "With a budget, trend-steady's Branch R opens: customers may pick the crypto share for uptrends from
   the allowed values in the pre-registration (30%, 40%, 50%, 60%), and every value must pass every check." Written
   into `config/risk_levels.yaml`, with its tests, by `368b90a`.
2. **The regimes check on the gain over the held mix** (same record): "The regimes check ("no single kind of market
   makes most of the profit") is measured on the gain over holding the same mix, so sitting out a crash counts, for
   trend-steady (the draft's exact definition: `regime_split` with the held-mix benchmark N0)." G8-excess replaces the
   literal G8; both are reported [M2].
   **[M10] Put to the owner again, in writing, because the decision was taken on an incomplete explanation.** The
   owner was told (`OWNER_QUESTIONS.md` Q5, 2026-11-21) that the literal G8 "will almost surely fail" and was offered
   the gain over the held mix as the alternative. The review of 2026-11-22 found that G8-excess very likely fails by
   construction too: with three regimes, "no regime above half the total excess" means no regime's excess below
   zero; a long-or-cash rule usually trails the held mix in bull months, and where it does not, its bear months
   usually hold more than half the excess (section 1, section 10).
   **Question 6 (section 19), dated 2026-11-22. Owner's answer: none recorded at this commit.** Until the owner
   answers in writing, G8-excess stands as pinned and is expected to fail. The owner either keeps G8-excess as pinned,
   or states another rule in his own words; this study proposes none. An answer counts only if it is recorded with its
   date, as a named amendment that cites this finding, committed before any trend-steady result of any kind
   (amendment A0's synthetic controls included). After that, nothing about G8 changes.
3. **Sells to cash during a pause** (same record): "Sells to cash go through during a loss-limit pause or while
   waiting for approval (a pause still stops all buying). A product decision for the app docs; the study does not
   model pauses." [M3]
4. **100% USDC; weekly checks** (same record): "100% USDC is allowed when both coins trend down: Steady's "max 60%"
   applies per coin, not to cash." And: "Not asked, so the draft's default holds: the trend check runs once a week
   (within "a few trades a month")." [M3]
5. **With and without the boom years** (2026-11-21, `2026-11-21-boom-check.md`, `652eefc`): "Leave one year out",
   "Without the best years", and "A strategy that beats its comparators only with the boom years in does not count as
   beating them." For this study it is a criterion: E6, E7 and G7, as the draft has them, and the same checks in the
   stop-loss variant (section 11A).
6. **A basic stop-loss variant** (2026-11-21, in chat). The owner's words, as the lead quotes them from the chat: "we
   don't want to lose ... more than like 40% of the profit that we've made ... So if we put in 1,000 and then we
   make, you know, 2,000, we don't want to slide, you know, more than 40% below that 2,000". The owner accepted
   ("Ok") the proposal "sell after X% fall from the top (20/30/40%), buy back when the trend turns up". The
   2026-11-21 record notes it as "the stop-loss variant the owner accepted ("Ok", 2026-11-21): sell after a fall of
   20%, 30% or 40% from the high point, with a pre-set buy-back rule". The three levels are the owner's; everything
   else is pinned in section 11A before any result [M4].
7. **The hold-this-mix limit is the tool's only** (2026-11-22, in chat; `2026-11-22-owner-answers-hold-mix.md`,
   `9e96841`, 14:48 UTC). Asked whether the tool's limit of 2 trades back to the mix in any 30 days also applies to
   our own Steady strategies, the owner chose "Only the hold-this-mix tool" ("Our strategies have to pass the lab's
   checks with costs on, so too much trading already shows up as a failure. The trend test still reports how often it
   trades."). So trend-steady is not capped by it, and it reports its trade frequency (section 16) [M3].

The owner questions of section 19 therefore stand as follows: Q1 answered (35%, Branch R); Q2 answered "yes" (100%
USDC); Q3 not asked, so the default (weekly Monday checks) holds, logged here; Q4 answered (sells to cash go
through); Q5 answered (G8-excess). Q1 and Q5 were answered in writing before this plan's commit, so they count.
**[M9, M10]** Two new questions are open, put in writing in section 19 on 2026-11-22: **Q6** (G8-excess is expected
to fail by construction: keep it, or state another rule; no answer at this commit, so G8-excess stands) and **Q7**
(may a customer's own per-trade or per-day cap block a sell to USDC; a product question that changes no number here).

Next steps [M8]:
1. `backtest-auditor` and `risk-officer` review this plan. Any change they ask for is another named amendment
   (section 15), made before any trend-steady result. **[M22] Done on 2026-11-22:** the review's blocking findings are
   amendments M9-M18, and the suggestions taken are M19-M22 (section 15).
2. It is committed with the branch line and the `config/risk_levels.yaml` hash above. The draft's stop rule 16
   ("committed before anyone working on trend-steady reads hold-mix-cap's RESULTS.md") could not be met: those
   results were committed on 2026-11-21 at 22:13 UTC and read by the lead before this plan. Its replacement is stop
   rule 16 in section 15, and the readings are logged in section 2 (K10, K11).
3. Then the build and its tests (section 17), amendments A1 and A0, and run 0 (section 15, order of work).
4. **[M22] Open before A0 starts** (each recorded as a dated named amendment, or A0 and run 0 wait): the owner's
   written answer to Q6, if he gives one (none means G8-excess stands); `risk-officer`'s dated written confirmation of
   the allowed values {0.30, 0.40, 0.50, 0.60} (section 8); and what the `risk-officer` review read (section 20,
   stop rule 16).

> **SCOUTING ONLY.** Every number this study produces comes from the lab's reference portfolio engine
> (`lab/runner/portfolio.py`, driven by a new `lab/runner/trend.py`), not from NautilusTrader (AGENTS.md hard rule
> 3; the Nautilus runner is on hold). It uses the **placeholder** costs of `config/costs.yaml`, and Kraken and
> Binance candles stand in for Base prices. **This study cannot make anything ready for paper.** Its best possible
> headline is "CANDIDATE FOR AUDIT", which means only "worth a Nautilus build". ~~While the Steady budget is TBD, the
> best possible headline is "EDGE, NOT A CANDIDATE".~~ **[M1, M2]** With the 35% budget and G8 measured on the gain
> over the held mix, "CANDIDATE FOR AUDIT" ~~can be reached~~ **[M10]** can be reached only if G8-excess passes, which
> is unlikely by construction. G8-excess passes only if S's excess over N0 is ≥ 0 in bull, bear and sideways months
> alike. It is expected to FAIL, so CANDIDATE FOR AUDIT is expected to be unreachable, and the best reachable headline
> is "EDGE, NOT A CANDIDATE" (section 1; owner question 6). Nothing goes into `reports/<strategy>/`, `strategies/` or
> `exports/`.

The only real-data numbers in this file are:
- coverage counts and close dates from rebalance-steady's DATA.md;
- figures quoted from files the desk has already published (listed as prior looks in section 2).

**[M5]** No hold-mix-cap result is quoted anywhere in this file. Those results are described in words only (section
2, K10 and K11), so that reading this plan is not another look at them.

The fold dates, check closes and row numbers come from `lab.validation.splits.walk_forward` run on a date grid
rebuilt from DATA.md's counts, with no prices (script in appendix B). No catalog bar was read. The feasibility checks
read `config/risk_levels.yaml` only (**[M1]** rerun on 2026-11-22 for Branch R against the file as it reads now,
appendix B). Timings are from synthetic data.

## In plain words

Steady's product plan lists "trend following that moves to cash in downtrends" as its second strategy idea
(`docs/app/product.md`). The owner said it "might be worth testing".

**The rule.** Once a week, at the Monday 00:00 UTC daily close, it looks at BTC and ETH separately:
- If a coin's price is more than a small buffer δ above its average of the last L days, the coin is in an uptrend
  and the book ~~holds 25% in it~~ **[M9]** buys 25% of the wallet in it when its trend turns up (**[M1]** half the
  crypto share s; 25% at s = 50%).
- If the price is more than δ below that average, the coin is in a downtrend and ~~its 25%~~ **[M9]** all of that coin
  goes to USDC.
- In between, nothing changes.

So ~~the book is 25% BTC, 25% ETH and 50% USDC when both coins trend up~~ **[M9]** the book buys 25% BTC and 25% ETH,
keeping 50% USDC, when both coins turn up, and holds 100% USDC when both trend down. While the trend lasts, prices can
push the crypto part up to about 80% of the wallet (60% in one coin) before it is traded back to the chosen share;
there is no trim before that. ~~The Steady limits (at least 20% cash, at most 60% in any one coin) hold at every daily
close.~~ The Steady limits (at least 20% cash, at most 60% in any one coin) are checked at every daily close; a breach
is traded back at the next open.

**[M1] Customers choose the crypto share.** The share ~~held when both coins trend up~~ **[M9]** bought when a coin's
trend turns up will be a customer setting: 30%, 40%, 50% or 60% (so 15% to 30% in each coin at entry). **[M9]** It is
the share at entry, not a ceiling: at 60%, a rise of about 2.7 times in both coins takes crypto to 80% (a rise of 3.5
times in one coin takes that coin to 60%); at 50% it takes 4.0 and 4.5 times (appendix B). The search also picks a
share, and the default is the allowed value nearest its final pick. Each of the four values must pass every check on
its own; one failure fails the setting.

**[M4] A stop-loss variant.** The owner asked for a basic stop-loss on top: if the wallet falls 20%, 30% or 40% below
its highest value, sell everything to USDC, and buy back only when the trend turns up again. It is tested next to the
plain rule, ~~with the same luck checks~~ **[M15, M17]** with the plain rule's luck checks (shifted timing, holding
the same mix, holding the same average amount of crypto, doubled costs, the second seed, leave-one-year-out, the boom
years and the second data source) and two of its own: it must do better than the plain rule, and its stops must beat
the same stops moved to other weeks (section 11A). Two warnings: a check once a day cannot promise the fall stops at
exactly 20%, 30% or 40%, because a crash day can go past it (**[M20]** for scale: on the bar of 2020-03-12 BTC fell
38.9%, K2; if both coins fell that much, a wallet holding 60-80% crypto would lose about 23-31% that day before the
stop could act); and it is not the app's loss limit, which pauses trading and never sells.

**What the study asks.** Is the trend timing better than chance after costs? Specifically, does it beat:
- the same in/out schedule shifted to other dates (a schedule moved less than a year earlier would partly see its
  own future, so those shifts are left out);
- holding the same mix all the time;
- holding the same average amount of crypto, judged on falls;
- the lab's benchmarks?

It also asks whether the result still holds without any single year, and without BTC's best years (the owner's rule
of 2026-11-21). "No edge" is an acceptable answer.

**What we already know.** The first Steady study found three things:
- rebalancing timing added nothing;
- the crypto share drove return and drawdown;
- frequent trading mostly paid fees.

This plan is built around them:
- ~~the crypto share is fixed, not tuned;~~ **[M1]** in Branch R the crypto share is a customer setting; it is
  searched only so that the allowed values lie inside the search box, and every allowed value must pass every check;
- the rule trades rarely (weekly checks, a buffer, no rebalancing inside a trend);
- the luck controls test the timing itself.

The years 2018 and 2022 were long bear markets, and everyone writing this knows it. So the plan leans on tests that
hindsight cannot pass for free: shifted timing, leave-one-year-out, and the boom-year check.

## 1. Question and hypothesis

**Question.** A Steady book holds BTC, ETH and USDC. It holds each coin at its share while that coin is in an
uptrend, and moves that coin's share to USDC in a downtrend. Does the trend timing earn a better risk-adjusted
return after costs, on the walk-forward out-of-sample span 2018-2022, than each of these?
- (a) the rule's own in/out schedule placed at other dates;
- (b) the same mix held always in;
- (c) the lab benchmarks (buy-and-hold BTC; 50/50 BTC/USDC every 30 days)?

Does it cut falls more than holding the same average amount of crypto? And does it pass the AGENTS.md gates?

**Hypothesis.** Crypto prices show time-series momentum at horizons of weeks to months, and their deepest losses come
in long bear markets. A rule that is out of a coin while its price sits clearly below its moving average misses much
of a long decline and keeps much of a long rise. It pays for this with lag and whipsaw in choppy and V-shaped
markets.

Why it might persist:
- slow diffusion of information and attention;
- herding and extrapolation;
- leverage-driven liquidations that take weeks;
- no fundamental anchor for the price.

**What the literature says** (full list and links in `sketch_evidence.md` section 12, read as abstracts or secondary
summaries where marked there):
- **Time-series momentum.** Moskowitz, Ooi & Pedersen (2012) and Hurst, Ooi & Pedersen (2017) find it in futures.
  Levine & Pedersen (2016) show that price-versus-average rules and time-series momentum are one family, so this
  study tests **one signal family**.
- **Crypto.** Liu & Tsyvinski (2021) find momentum at daily and weekly horizons. Detzel et al. (2021) find that
  price-to-average ratios predict BTC out of sample. Both overlap our train window.
- **Sceptical findings.**
  - Huang et al. (2020) find weak asset-by-asset evidence.
  - Kim, Tse & Wald (2016) find unscaled trend signals close to buy-and-hold.
  - Zakamulin finds the gains concentrated in a few severe bear markets.
  - Bajgrowicz & Scaillet (2012) find no value after multiple testing and costs.
  - Han, Kang & Ryu find that costs erase many crypto momentum results.
- **Whipsaw.** Clare et al. (2013) find whipsaw is the main cost of trend rules, which is why this rule has a buffer
  and weekly checks.
- **What this means.** The prior chance of a robust Sharpe edge is modest. A drawdown benefit concentrated in bear
  years is likely. Hence the controls below: an exposure-matched null, a leave-one-year-out test, a power floor, and
  every trial counted.

**This is wrong if** (section 11) either of these fails on 2018-2022 after costs:
- **E1:** the rule's own schedule beats the same schedule shifted to other dates (same time in market, same spell
  lengths, the same switches up to one splice, the same BTC/ETH co-timing; shifts that move the schedule 1-52
  weeks earlier are excluded because they read the rule's own future, section 9);
- **E2:** the rule's Sharpe is significantly above the same mix held always in.

**Expectations, written now so that surprises are visible.** These come from general knowledge of the price history
(prior look K1); they are not evidence and decide nothing.
- The rule is out of both coins for most of 2018 and 2022, so folds 0 and 4 should favour it strongly.
- 2020 and 2021 should favour always-in, because of the lag after the March 2020 crash and whipsaw around the 2021
  tops.
- 2019 is mixed.
- Costs should matter little, because there are few switches.
- G8 should fail, because a long-or-cash rule makes its profit in bull months. **[M2]** That is the literal G8, now
  reported only. G8-excess (the gain over holding the same mix, owner decision 2) decides; ~~no expectation is
  written for it~~.
- **[M10] G8-excess is also expected to FAIL.** The gain over the held mix comes mostly from bear months, and bull
  months add a loss, so the bear share of the excess is likely above one half. In exact terms: the three regimes'
  excesses b, w and u add up to the total T, so "each at most T/2" means any two add up to at most T, and so the third
  is at least 0. G8-excess passes only if S's excess over N0 is ≥ 0 in bull, bear and sideways months alike. A
  long-or-cash rule buys at most the held mix's crypto, so in a bull month in which it is out for part of the month
  (it buys back late) it trails N0: its bull-month excess is usually negative, whatever its edge, and where it is not,
  the bear months usually hold more than half the excess. **So CANDIDATE FOR AUDIT is expected to be unreachable**,
  and the best reachable headline is EDGE, NOT A CANDIDATE. Indicative only (synthetic panels from the lab generator,
  no market data; the reviews' checks `trendrun/planreview/g8_excess_check.py` and `trendrun/planstats/g8x.py` in the
  session scratchpad, rerun for this amendment with the same output): with the lab's engine (costs at 1x, drift,
  limit fixes) on 30 regime-switching panels, a weekly rule at (L 100, δ 0.02, s 0.50) beat N0 overall on 13, and
  G8-excess passed on 1 of them (on 12 of the 13 the bear regime held more than half the excess, and on 7 the
  bull-month excess was negative); in a simpler model with fixed weights between checks (no drift, no costs), on 40
  panels of A0's positive-control generator (seeds 1000-1039) at each of (50, 0.02), (100, 0.05) and (200, 0.10), the
  bull-month excess was negative on 40 of 40 and G8-excess passed on 0 of 40. The gate is not changed (owner
  question 6).
- ~~G6 is MISSING while the budget is TBD.~~ **[M1]** G6 is computed against the 35% budget, at S, at the deepest
  grid step and at every S(s_k). From K2 alone (rebalance-steady's in-sample drawdowns grew steeply with the crypto
  share), the higher allowed shares are the likelier to fail it. The author of these amendments has also read K11
  (section 2), which points the same way; this expectation decides nothing.
- **[M4]** The stop at a 40% fall may never fire in 2018-2022 at these crypto shares, because the trend rule usually
  moves to cash first; the stop at 20% should fire a few times, for example after the January 2018 and March 2020
  falls (K1). Few stops mean low power for the variant.
- **[M21] SL-P is expected to fail**, and the variant to read INCONCLUSIVE (LOW POWER) or NOT TRIGGERED at each level.
  Indicative only (the review's synthetic check on 40 panels of A0's positive-control generator, seeds 1000-1039,
  no market data): the median
  number of stops filled in kept rows was 1-2, and 36, 20 and 5 of 40 panels triggered at φ = 0.20, 0.30 and 0.40.
  SL-T (the stop's own timing against moved stops, section 11A) will have little power with so few stops; LOW POWER
  is then the honest answer.

## 2. Prior looks (disclosure)

| # | What was seen | Bearing on this study |
|---|---|---|
| K1 | **General knowledge** of the public price history: the 2017 bubble, the 2018 bear market, March 2020, the 2020-21 rise and its tops, the 2022 bear market, the 2023-24 recovery. The authors' training data run to about mid-2026, so their general knowledge also covers the broad course of the **test window**. The public claim that 200-day and time-series-momentum rules side-stepped crypto bear markets is widely repeated | The dominant prior look, and it cannot be undone. **Strategy-level selection:** trend following was proposed partly because it is known to have worked in 2018 and 2022, and DSR cannot count that. So G1, G3 and G7 are weak evidence; E1, E2, E6 and E7 carry the question. Even the test window is not fresh to the authors' priors; only paper trading after their knowledge cutoff is truly unseen |
| K2 | `research/rebalance-steady/RESULTS.md`, read by this draft's author (lines 1-140) and quoted at length by all four sketches. It includes buy-and-hold BTC over 2019-2022 (+318.5%, max drawdown −77.4%, Sharpe 0.864, worst day −38.94% on the bar of 2020-03-12); per-fold buy-and-hold BTC Sharpes 1.223, 2.305, 0.961 and −1.336 (2019-2022); 50/50 monthly Sharpe 0.859, −49.5%; static mixes near 0.95-1.03; the limit-only mix B5 at 0.959 and 1.113; and the in-sample s-profile (drawdown grows steeply with the crypto share). Via the sketches: **a bull/bear/sideways label for every month of 2019-2022** (19 bull, 12 bear, 17 sideways) | A coarse map of the trend structure of 4 of this study's 5 out-of-sample years. It is the strongest look at our own data. The search box (section 5) comes from the literature and common practice, not from these labels, but nobody can unknow them |
| K3 | rebalance-steady `PLAN.md` (in full), `DATA.md` (via its counts), `RISK.md` (via the sketches' quotes) and `AUDIT.md` (finding N6 and its line 133 only) | Format, limits readings, fold layout and row counts. N6 ("S and its nulls start each block in different states") shaped the common start state (section 7) |
| K4 | `research/dip-timing/RESULTS.md` and `PLAN.md`, via the sketches' quotes. `ma_dist_100` (distance from the 100-day average) was one input of a dip-quality model, evaluated on train and at the dip study's single validate look D1. Validate is described as a **bull market** (BTC+ETH buy-and-hold Sharpe 1.917, +230.5%, −22.7%) | A look at a moving-average distance on train and validate, inside dip events only: **+1 in the strict count**. Validate is not fresh, so E9 can reject but not confirm |
| K5 | `research/hold-mix-cap/PLAN.md` (sections 0-3 and 16-17) and its README. **Its RESULTS.md does not exist yet** (as of the draft). **[M5]** Its run 0 outputs were committed on 2026-11-21 at 20:38 UTC (`1a9512c`) and its RESULTS.md, AUDIT.md, RISK.md and app docs at 22:13 UTC (`5e1e46e`): see K10-K12 | When published, it will hold the returns and falls of thousands of held BTC/ETH/USDC mixes on 2017-2022. Those mixes resemble N0 (a comparator), not the rule. ~~Stop rule 16 handles the ordering~~ **[M5]** Stop rule 16 could not be met; K10 and K11 log what was read |
| K6 | `docs/app/product.md` and `features.md` (Steady and settings sections); `reports/director/2026-11-20-adjustable-settings.md` (via the sketches); `reports/director/2026-11-21-boom-check.md` (in full) | Product promises; the guardrail ruling ("a few trades a month" caps check frequency unless more checks are shown to pay); the owner's boom-years decision, built in here as E7 and in G7. **[M5]** `features.md` has since gained hold-mix-cap's numbers in its "Hold this mix" section (`5e1e46e`, `9e96841`); agents on this study do not read that section |
| K7 | The evidence sketch's web research: published trend results on BTC and ETH, several overlapping our train window. Zarattini, Pagani & Barbon (2025) run through 2025, so they cover our validate and test windows | The box (L 20-200, buffer, weekly checks) was taken from this literature, not from our data. The thousands of rules others have tested are a selection effect that DSR cannot count |
| K8 | Synthetic timing stand-ins by three sketches (`timing_synthetic.py`, `throughput.py`, `standin_timing.py` in the scratch folder); `config/*.yaml` read for limits and costs; the date grid (appendix B) | No market data |
| K9 | The data quality reports (single-bar moves, some in the test window; rebalance-steady P3) | **Not opened** for this draft or any sketch |
| K10 | **[M5] The lead's reading of hold-mix-cap's results**, after they were committed (2026-11-21 22:13 UTC) and before this plan. The lead who runs this desk read `research/hold-mix-cap/RESULTS.md`, `RISK.md` and `decision.json`. In words (no number is copied here): how far held BTC/ETH/USDC mixes fell, by crypto share, over 2017-2022, mostly in the 2018 crash; that frequent rebalancing paid fees; and that the 2017 and 2018 boom and crash years move the results. The owner (who answered questions on them on 2026-11-22), `risk-officer` (who wrote RISK.md), `backtest-auditor` (AUDIT.md) and `director` (the 2026-11-22 record) saw them too | Those mixes resemble N0 (always in, limit fixes only) and X, not the rule. They could inform expectations about G6 at the higher allowed crypto shares, and the design of the stop-loss variant (how deep the falls of a held mix get). They could not inform the budget, the allowed values or the stop levels, which were fixed before hold-mix-cap's run 0 started (K12). The lead set the task for M1-M8 after this reading and listed the decisions to fold in; every change since the draft is a named amendment with this question answered (section 15) |
| K11 | **[M5] This plan's author's reading** (`quant-researcher`, 2026-11-22, while writing M1-M8). Read in full, as the task asked: `reports/director/2026-11-21-owner-answers-trend-steady.md`, `2026-11-21-boom-check.md` and `2026-11-22-owner-answers-hold-mix.md` (as committed in `9e96841`; its later change, committed by someone else in `52d7ee1` at 15:09 UTC while this plan was being written, was not read). **The 2026-11-22 record quotes hold-mix-cap's results**: the worst 12-month falls of held mixes by crypto share against the 35% budget, the share of 12-month windows past 35% by crypto share, the tool's fees and gas a year, and its trade counts near the limits, among other figures. Also read: `research/rebalance-steady/RESULTS.md` lines 1-80 (inside K2), its `PLAN.md` header and section 13 and its `RISK.md` section 3 (the budget method, with its notes on deep drawdowns at high coin shares), a part of `reports/director/2026-11-20-adjustable-settings.md` (the G6 notes, quoting rebalance-steady's Monte Carlo drawdown), and TESTING.md (loaded with the project instructions; it describes hold-mix-cap's code and run counts, ~~and no return, fall or fee~~ **[M22]** a few run-0 facts (its smallest trade leg, 4.9e-5 USD, and that every fee check passed) and the boom-year addendum's window counts, but no return, fall or fee level). **Not read:** hold-mix-cap's RESULTS.md, AUDIT.md, RISK.md, `decision.json`, `runs.csv`, `falls.csv` and README, the hold-mix-cap numbers in `docs/app/features.md`, the catalog, and anything under `results/` | Every amendment written on 2026-11-22 could have been informed by it; section 15 answers the question for each. The amendments that make choices (M4's reading of the stop, its buy-back and its verdict; M7's time budget) use no hold-mix-cap number. Agents who build, run or audit this study should not read `2026-11-22-owner-answers-hold-mix.md` either |
| K12 | **[M1] What the owner and `risk-officer` had seen when the budget and the allowed values were set** (section 8, Branch R condition 4). The allowed values {0.30, 0.40, 0.50, 0.60} were written into the draft's section 8 (by 16:11 UTC on 2026-11-21, from the limits sketch) and put to the owner in `OWNER_QUESTIONS.md` (15:51 UTC); the owner approved the 35% budget and those values in chat, recorded at 16:31 UTC (`b05109e`). **Published results on 2017-2024 prices by then:** `research/dip-timing/RESULTS.md` (`04eb81f`, 2026-11-20 04:16 UTC: buy-and-hold and 50/50 mixes on train and validate, K4); `research/rebalance-steady/RESULTS.md`, `AUDIT.md` and `RISK.md` (`1948d59`, 2026-11-20 19:05 UTC: falls of rebalanced and static Steady mixes by crypto share, in 2019-2022 and in-sample over 2017-2022, and S's Monte Carlo drawdown, K2); `reports/director/2026-11-20-adjustable-settings.md` (2026-11-20, quoting them); and the milestone 1 data quality reports. **Not published then: any hold-mix-cap result.** Its run 0 started at 19:32 UTC (its RUNLOG, as the lead reports it), its outputs were committed at 20:38 UTC (`1a9512c`) and its RESULTS.md at 22:13 UTC (`5e1e46e`). The budget was written into the file at 22:53 UTC (`368b90a`), after those results, because the 16:31 record said to wait for hold-mix-cap's run (that study hashes the file); the number written is the one approved at 16:31. The stop levels 20/30/40% were fixed by the owner before 16:00 UTC (the session note `OWNER_DECISIONS.md`) and recorded at 16:31. Whether the owner opened each published file is not recorded; this plan treats them all as seen | The budget and the allowed range could have been informed by rebalance-steady's and dip-timing's results on 2017-2022 (and dip-timing's validate numbers), never by hold-mix-cap's. AGENTS.md "Settings ranges" asks for this list |

**Counted honestly:**
- Looks by the desk at any trend rule on this data: **0**.
- **[M5]** Looks at hold-mix-cap's results by people working on or for this study: the lead (K10) and this plan's
  author, through the 2026-11-22 owner record (K11). Neither has seen any trend rule's result. **[M22]** Also, as the
  lead's one-sentence summary in their task briefs (K10's words; no file and no number), the 2026-11-22 reviewers and
  the author of M9-M22 (section 20).
- Looks at a related trend signal: **1** (K4, in the strict count).
- **Validate-window looks for trend-steady: 0.** The validate window is unspent for this strategy but not fresh
  (K4).
- **The test window is never read.**

Not read for this draft: the catalog, `SNAPSHOT.json`, anything under `results/`, `trials.csv`, `evaluations.csv`,
the dip study's `AUDIT.md`, and the data quality reports. **[M5]** Nor for the amendments (K11 lists what was read).

## 3. Data

| Item | Pinned |
|---|---|
| Primary | Kraken daily bars, `BTC/USD.KRAKEN` and `ETH/USD.KRAKEN`, through `lab.data.panel.load_panel("KRAKEN", "1d", last_close=...)` |
| Robustness | Binance daily bars (`BTCUSDT`, `ETHUSDT`, quoted in USDT). **No search on Binance.** The Kraken-chosen parameters are re-run on Binance (E8) |
| Train phase | `last_close = 2023-01-01 00:00 UTC`. Kraken: 2190 rows, closes 2017-01-02 .. 2023-01-01. Close 2018-01-13 is dropped (no ETH bar), so one return spans 2 days and one L-row average spans L + 1 days; both are disclosed and neither is fixed. Binance: 1963 rows from 2017-08-18 |
| Validate look | Only if earned (section 13): `last_close = 2024-07-01 00:00 UTC`. Kraken 2737 rows; validate is rows 2190-2736 |
| Snapshot | Each run reads `snapshot_id` and `bars_content_sha256` from `data/catalog/SNAPSHOT.json`. Stop and amend unless the bars hash is `08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e` and the panel hashes (`steady.panel_hash`) are Kraken `355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6` and Binance `2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587` (rebalance-steady run 0) |
| Slicing | Every run starts at its panel's **first row** (harness H0, section 7) and ends at a close time taken from the Kraken panel. Kept rows are compared by close time; a Binance kept index must equal Kraken's, or stop |
| Test window | **Never read.** No request asks for a close after 2024-07-01 00:00 UTC. `load_panel` raises `HoldoutWindowError` for such a request or for any returned bar after it. Each script asserts `panel.index.max() <= last_close` on every frame |

## 4. The rule and the Steady limits

`lab.runner.trend.trend_backtest(params, bars, *, limits, costs, s=0.50, f=0.50, weekday=0)`. It hands a
`decide(t, w)` callback to `portfolio._simulate`, the engine `rebalance` and `hold_mix` use. No engine file changes.
**[M1]** In Branch R the crypto share comes in `params` as `crypto_share` (searched, section 5), so the signature is
`trend_backtest(params, bars, *, limits, costs, f=0.50, weekday=0)` with `params` = `lookback`, `buffer`,
`crypto_share` and, **[M4]** only for the stop-loss variant, `stop` (φ, section 11A; absent means no stop).

| Step | Rule |
|---|---|
| Average | For coin a ∈ {BTC, ETH}: SMA_a(t; L) = the mean of close_a over slice rows t−L+1 .. t, **including close t** (it is known at that close). It is computed per window, never as a running sum |
| Distance | m_a(t) = close_a(t) / SMA_a(t; L) − 1 |
| Activation | A = max(199, L − 1) slice rows. 199 = L_max − 1, so every L in the box starts on the same row; larger values occur only for G5 plateau steps above L = 200. Every run starts at its panel's row 0 (H0), so A is a panel row: Kraken row 199 is close 2017-07-20, Binance row 199 is close 2018-03-05. Before the first check close at or after A, both states are **out**, the book is all USDC, and nothing is ordered |
| Check closes | Closes with `index.day_of_week == weekday` (default 0: Monday 00:00 UTC, the bar of Sunday) at slice rows ≥ A. They are tied to the calendar, so the check phase never depends on where a slice starts. A missing check close is skipped, with no substitute. Kraken train has 313 Monday closes; the first check is 2017-07-24 (row 203); no 30 days hold more than 5 check closes. Use `day_of_week`, not `dayofweek` (deprecated in pandas 4) |
| State (hysteresis) | z_a ∈ {out, in}, starting **out**. At a check close: out → in if m_a(t) > +δ; in → out if m_a(t) < −δ; otherwise unchanged. Both inequalities are strict, so exact equality changes nothing. The same L and δ apply to both coins. The state is held between check closes |
| Targets | w_a = (s/2)·[z_a = in], with s = 0.50 and the 50/50 split f fixed: (0.25, 0.25), (0.25, 0), (0, 0.25) or (0, 0). **[M1]** s is the run's crypto share (searched in 0.30-0.60; at a grid step, that step's allowed value): (s/2, s/2), (s/2, 0), (0, s/2) or (0, 0). USDC is the rest. A coin in a downtrend goes to USDC; it is never moved into the other coin (that would be rotation, a Bold idea) |
| Orders | At most one order per close, always the **full target vector**: (1) at a check close where either state changed, order the new targets (a switch); (2) otherwise, if the weights at close t breach a Steady limit (`portfolio._breach_test(min_cash, max_coin)`: coins > 1 − min_cash + 1e-9, or one coin > max_coin + 1e-9; today 0.80 and 0.60), order the current targets (a limit fix); (3) otherwise, no order. A switch and a breach on the same close give one order. A switch of one coin also re-cuts the other coin to its target (disclosed). **[M11] One rule for every executor:** an order is sent at a close where the target vector in force changes, or at a limit breach. In one run with one s (S's fold runs, θ_final, a grid step, S(s_k), N0, X) the vector changes only at a check close where a state changed, which is rule (1). In R_0, every shift, B3-lead, E8's Binance R_0 and shifts, and R_0^φ, an order is sent at a check close where the target vector changes: a state change, or a change of s between source folds (a re-cut). A re-cut counts as an order (fills, R_0 − S difference) but not as a coin-state change for P or the switch counts; limit fixes order the vector in force. (R_0^φ's vector, its shifts' and its placebos' can also change at a daily close through a stop's lock, section 11A; that too is an order) |
| Fill | At the open of t+1 (hard rule 4). Each coin is a swap against USDC at its own open. A leg with zero change does not trade. An order decided at the last close of a slice is never filled |
| Between orders | Coin units and cash are held, and weights drift. **No band rebalancing and no drift trim inside a trend.** Only switches and limit fixes trade. **[M9]** So s/2 per coin is the weight at entry, not a ceiling: from the limits as read, a fix comes only once crypto passes 80% of the wallet or one coin passes 60% at a close (at s = 0.60 after a rise of about 2.7 times in both coins, or 3.5 times in one; at s = 0.30 after about 9.3 and 8.5 times; appendix B), and it fills at the next open |
| Stop-loss variant **[M4]** | Only when `params` holds `stop`: section 11A (a stop sells every coin; a stop comes before a switch and a limit fix on the same close). Without it, nothing in this table changes |
| Limits | `portfolio.risk_limits("steady")`, read at the start of every run and never typed (~~today min_cash 0.20, max_coin 0.60, coins exactly BTC/ETH/USDC; file SHA-256 `158d7c9f…`~~ **[M22]** struck: the draft's reading of 2026-11-21, no longer the file). **[M1]** Read on 2026-11-22: min_cash 0.20, max_coin 0.60, budget 35 (0.35), coins exactly BTC/ETH/USDC, file SHA-256 `d3f58253…`. Headroom h = 0.02: all four target sets pass `check_targets` with the limits as read and h before any bar is loaded, or the run refuses. On 2026-11-21 all four passed, and so did those for s ∈ {0.30, 0.40, 0.60, 0.70} (appendix B). **[M1]** Rerun on 2026-11-22 against the file as it reads now: the 4 states pass for every allowed value s ∈ {0.30, 0.40, 0.50, 0.60}, for the plateau extremes 0.24 and 0.72, and the all-cash target passes (appendix B). Breaches are judged at the limits themselves |
| Costs | `Costs.from_yaml()` at 1x and `.stressed()` at 2x (k = `stress_multiplier` = 2.0), built once per run. Per leg: traded share × (5 bps pool + 0 aggregator + slippage at the leg's USD size) + USD 0.10 gas. The book starts at USD 10,000 at row 0 and compounds. A fill's cost is shared pro rata, so the book holds exactly the targets after a fill |
| Cash | USDC at price 1, with no yield and no depeg |

**Readings carried over** from rebalance-steady, confirmed by the owner on 2026-11-20 (Q1) or held by default (Q2,
Q6):
- a drifted breach at any close forces a full re-target;
- `max_coin_pct` applies to each coin, not to the coins together, and **not to USDC**. This study depends on that
  reading, because a 60% cap on USDC would forbid the all-cash state (owner question 2; **[M3]** confirmed by the
  owner on 2026-11-21, decision 4: "Steady's "max 60%" applies per coin, not to cash");
- h = 0.02.

**Decisions never depend on costs or book size.**
- The states depend on prices only.
- Limit fixes depend on weights, which a fill sets exactly to the targets and which then drift with prices only.
- So the orders (closes, reasons and targets) are identical at 1x, at 2x and at every book size. This is tested
  (section 17) and checked in every run by an order hash (stop rule 13).
- **[M4]** This holds for the plain rule. The stop-loss variant's stops read the wallet's value, which costs and book
  size move, so its stop events can differ between 1x and 2x; its trend states cannot (section 11A, stop rule 13).

**App wording (proposed):** ~~"Holds 25% BTC, 25% ETH and 50% cash while each coin's price is above its L-day average;
moves that coin's share to cash when its price falls clearly below it. Checked weekly. It does not protect against
sudden one-day crashes."~~ **[M1]** ~~"Holds your chosen crypto share, split evenly between BTC and ETH (25% each at
50%), while each coin's price is above its L-day average; moves that coin's share to cash when its price falls clearly
below it. Checked weekly. It does not protect against sudden one-day crashes."~~ **[M9]** "Buys your chosen crypto
share, split evenly between BTC and ETH (25% each at 50%), when each coin's trend turns up (its price clearly above its
L-day average); rising prices can take it as high as 80% before it is trimmed back. Moves a coin to cash when its
price falls clearly below that average. Checked weekly; the Steady limits are checked every day, and a breach is
traded back the next day. It does not protect against sudden one-day crashes."

**Production notes, not engine behaviour** (for the eventual risk note):
- sells go before buys;
- the caps are checked after the trade, on the full order;
- a breach is fixed at the next daily open, with an alert if it lasts more than one day;
- gas is booked to the paper account's book, as the backtest does;
- ~~a loss-limit pause or Approve mode must not block an exit to cash (owner question 4).~~ **[M3]** Decided by the
  owner (decision 3): sells to cash go through during a loss-limit pause or while waiting for approval, and a pause
  still stops all buying. The stop-loss variant's sale (section 11A) is a sell to cash and goes through too. Still
  open for the app (not decided here): whether an order with both sell and buy legs (a switch of one coin that
  re-cuts the other) sends its sell legs and holds its buy legs during a pause;
- ~~**[M3]** the auto-trading permission's per-trade and per-day caps must allow one full switch (s/2 of the wallet, up
  to 30% at s = 0.60) and, for the stop-loss variant, a sale of every coin (up to 80% of the wallet after drift).~~
  **[M9]** the auto-trading permission's per-trade and per-day caps must allow the orders this rule sends: any order
  that moves a coin to cash (a switch or a stop) can sell every coin held, up to about 80% of the wallet (more after a
  gap day); one switch into both coins buys up to s of the wallet (60% at s = 0.60); at most one order per day. Open
  for the owner (section 19, question 7): whether a customer's own per-trade or per-day cap (`docs/app/features.md`,
  "Personal limits") may block a sell to USDC. If it may, the strategy cannot promise its exit;
- **[M9]** the permission's coin list is locked to cbBTC, ETH and USDC.

## 5. Parameters and search box

Two free parameters (the cap is 4). Both move the switch dates, so the objective can tell their values apart, unlike
rebalance-steady's coin share. **[M1] Branch R adds a third, the crypto share s** (last row of the table), so there
are 3 free parameters, still within the cap. See "Why s is searched in Branch R" below.

| Parameter | Kind | Range | Scale | Spec |
|---|---|---|---|---|
| `lookback` L | int | 20 - 200 days (rows) | log | `Param("lookback", "int", 20, 200, log=True)` |
| `buffer` δ | float | 0.005 - 0.10 | log | `Param("buffer", "float", 0.005, 0.10, log=True)` |
| **[M1]** `crypto_share` s | float | 0.30 - 0.60 | linear | `Param("crypto_share", "float", 0.30, 0.60)` (section 8) |

- **Why these bounds.**
  - 20 days is the short end of crypto momentum studies (Grobys et al. 2020; Liu & Tsyvinski 2021 at weekly
    horizons). 200 days is the most quoted long average.
  - 0.5% is effectively no buffer; 10% is very sticky.
  - Log scales: 20 against 40 days matters as much as 100 against 200.
  - The bounds come from the literature and common practice (K7), not from our data.
  - L stops at 200 because a 365-day average would leave fold 0 almost no active training rows.
- **Every point of the box is feasible.** The targets depend on neither L nor δ. **[M1]** With s in 0.30-0.60, every
  target set passes `check_targets` with the limits as read and h = 0.02, and so does every plateau step (s × 0.8 down
  to 0.24, s × 1.2 up to 0.72; appendix B).
- **Fixed, not searched and not user settings:**
  - ~~the crypto share s = 0.50 (owner question 1);~~ **[M1]** in Branch R s is searched and is a user setting
    (section 8);
  - the BTC/ETH split 50/50;
  - the Monday check day;
  - the activation rule A;
  - the start state (out);
  - h = 0.02;
  - the limits as read and the cost model.
- ~~**Why s is not searched.** A Sharpe objective hardly identifies the crypto share (rebalance-steady section 5 and
  RESULTS.md: θ_final sat at the box edge), yet the share drives drawdown. It is fixed as the risk-officer
  recommended. Its sensitivity is a description (s = 0.30 and 0.70, section 16).~~
- **[M1] Why s is searched in Branch R.** The draft's reason for fixing it still holds: a Sharpe objective hardly
  identifies the crypto share, yet the share drives drawdown, so θ_final's s may well sit at an end of the box. It is
  searched only because AGENTS.md "Settings ranges" requires the allowed range to lie inside the search box and the
  default to be the allowed value nearest θ_final's. The search's choice of s is not evidence for any value: every
  allowed value must pass every check on its own (section 8). The draft's s = 0.30 and 0.70 descriptions are dropped:
  0.30 is an allowed value and is gated, and 0.70 lies outside the range and is not run.
- **Expected trade frequency** (from reasoning and synthetic stand-ins, not data): about 2-12 switches per coin a
  year, fewer at larger L and δ, plus 0-2 limit fixes a year in long rises.
  - At USD 10,000, a switch of one coin trades about USD 2,500 (one leg at about 26 bps, plus gas). **[M1]** In
    general s/2 of the book: USD 1,500-3,000 for s = 0.30-0.60.
  - Weekly checks cap switches at 5 in any 30 days by construction.

## 6. Objective

`lab.search.objective.evaluate_params` unchanged, through `run_study`, with `SearchConfig(n_trials=N, n_workers=1,
n_blocks=4, penalty=0.5, seed=..., periods_per_year=365, min_trades=5)`.

- Score = the mean of the 4 block Sharpes (annualised with √365) minus 0.5 × their standard deviation, over the
  fold's training rows, after costs at 1x.
- `min_trades = 5`, the lab default. It counts `trade_returns` entries, i.e. fill rows (switches and limit fixes,
  the first buy included). Trials scoring −10 are logged and counted like any other, and their number is reported
  per study.
- **Disclosed distortion.** Every training slice starts at row 0 (H0), and rows 0-202 are all cash for every trial
  (first check at row 203).
  - The first objective block of every study is therefore partly or wholly zero, and in fold 0 two of the four
    blocks are.
  - The zeros are the same for every trial, so they favour no L or δ. They do make the in-sample Sharpe and the
    walk-forward efficiency less meaningful.
  - **They also bias the luck statistics** (found by the audit; fixed in G3 and G4, section 10). Rows 0-203 are
    0 for every trial: 56% of fold 0's training rows, 9% of the final study's. Every trial Sharpe in a study is
    shrunk by about √(share of active rows), so the variance of trial Sharpes that sets DSR's luck benchmark is
    understated: on synthetic random walks (audit check, `audit/dsr_zero_rows_check.py`) the variance on all rows is
    0.44 of the active-row variance at fold 0's 365 rows, 0.72 at 730 and 0.91 at the final study's 2190, i.e.
    exactly the active share, roughly a fifth too small pooled over the 12 studies: **DSR is too lenient**. PBO's in-sample halves
    that hold only zero blocks tie every trial, which the tie rule scores as overfit: PBO is pushed up. Both are
    therefore also computed on the **active rows** (rows 204 .. end of each search study: the first check close is
    row 203 for every L in the box, so row 204 is the first row on which any trial can hold a coin), and each gate
    takes the stricter reading.
  - In fold 0 only about 162 training rows can trade (2017-07-24 .. 2018-01-01, the end of the 2017 bubble), and
    `min_trades` pushes the choice toward faster rules. This is noisy; whether it helps or hurts S is not known in
    advance.

## 7. Walk-forward, harness, search and selection

**Folds.** `walk_forward(2190, train_size=365, test_size=365, expanding=True)` on the Kraken train panel. This puts
**both** long bear markets (2018 and 2022) out of sample, which the leave-one-year-out test (E6) needs.

| Fold | Train rows (closes) | Test rows (t0 .. last) | Kept returns (closes) | Check closes deciding kept fills |
|---|---|---|---|---|
| 0 | 0-364 (2017-01-02 .. 2018-01-01) | 365-729 (2018-01-02 .. 2019-01-02) | 364 (2018-01-03 .. 2019-01-02) | 52 |
| 1 | 0-729 (.. 2019-01-02) | 730-1094 (2019-01-03 .. 2020-01-02) | 364 (2019-01-04 .. 2020-01-02) | 52 |
| 2 | 0-1094 (.. 2020-01-02) | 1095-1459 (2020-01-03 .. 2021-01-01) | 364 (2020-01-04 .. 2021-01-01) | 52 |
| 3 | 0-1459 (.. 2021-01-01) | 1460-1824 (2021-01-02 .. 2022-01-01) | 364 (2021-01-03 .. 2022-01-01) | 52 |
| 4 | 0-1824 (.. 2022-01-01) | 1825-2189 (2022-01-02 .. 2023-01-01) | 364 (2022-01-03 .. 2023-01-01) | 52 |
| final | 0-2189 | — | — | θ_final |

- **Out-of-sample span:** 5 × 364 = **1820 daily returns**, closes 2018-01-03 .. 2023-01-01. They span W = 260
  Monday check closes (2018-01-08 .. 2022-12-26).
- **Folds 1-4 have exactly rebalance-steady's 1456 kept rows** and are reported on their own too, so the two studies
  compare row for row.
- **No purge and no embargo.** There are no labels, the SMA at close t reads closes up to t only, and the first
  return of each block is dropped.

**Harness H0 (fixes path dependence and audit N6).**
- S is `walk_forward_optimize(..., warmup=2190)`, so `ctx_start = max(0, test[0] − 2190) = 0`. Every out-of-sample
  run starts at row 0, as every expanding training slice does.
- The hysteresis state at close t is then one fixed function of closes 0..t for given (L, δ), the same in training,
  out of sample, at θ_final and at the look.
- Kept rows are the closes after t0 (`res["ret"].loc[t0:].iloc[1:]`).
- `steady.fold_window(index, test, warmup=2190)` gives the same slice, so `buy_and_hold_b1` and `fifty_fifty_b2`
  run in H0 unchanged.
- **Cost of H0:** the book compounds from USD 10,000 in 2017, so later folds trade larger legs at higher
  (extrapolated) slippage. This is pessimistic for S and the same for its nulls, which start from S's book. It is
  disclosed, and the wallet-size description (R4) shows the size effect.

**Common start state.** Every null and comparator that is not a benchmark (R_0, the rotations, N0, X) copies S's
states up to close t0 − 1, so it holds **S's book at close t0 bit for bit** (asserted; stop rule 14). From close t0
on, each follows its own schedule and pays its own trades.

**Optuna.**
- TPE exactly as in `lab/search/study.py`: multivariate, 20 startup trials at N = 200, journal storage.
- `n_workers = 1`, so every study is exactly reproducible.
- Fold seeds are `seed + 1000·i`; the final study uses `seed + 5000`.

**N, trials per study.** The throughput rule (rebalance-steady A1, scaled to 12 studies):
1. Time a 200-trial study of the **built** adapter (`n_workers = 1`; **[M1]** with the Branch R box of three
   parameters) on 2190 synthetic rows,
   `make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")`.
2. N = 200 if 12 × that time is at most 60 CPU-minutes. Otherwise N is the largest multiple of 25 that fits; below
   50, ask the owner.
3. Redo the timing if the built adapter's single backtest is more than 2× slower than the stand-in's.

Synthetic stand-ins of this rule measured 5.80 s (`timing_synthetic.py`), 5.84 s (`standin_timing.py`, 1940 rows)
and 5.96 s per 200-trial study, and 0.011-0.014 s per 2190-row backtest. 12 × 5.96 s ≈ 72 s, so **N = 200** is
expected.

**Trial budget.**
- Per run: 2 seeds × (5 folds + final) = 12 studies × 200 = **2400 trials**, all logged.
- At most 2 amendment runs, so N_raw ≤ 7200.

**[M7] Time budget and projection guards.** From the draft's synthetic timings (a 200-trial study 5.80-5.96 s wall;
one 2190-row backtest 0.011-0.014 s; appendix B), run 0 in Branch R with the stop-loss variant needs about:
- the searches: 12 studies × about 6 s ≈ 72 s;
- about 1,000 full-length runs of the rule (the folds, 2x, the plateau, the check days, the grid, S(s_k), R4, B1, B2,
  Binance) and about 680 schedule runs (per seed, R_0 with its 207 shifts and 52 leads; on Binance, R_0 with its
  155 shifts): about 25 s;
- the stop-loss variant: 3 levels × 10 stitched runs of up to about 20 passes each (section 11A), plus R_0^φ and its
  259 shifts per level: about 1 minute;
- about 25 paired bootstraps (10,000 resamples each) and 25 Monte Carlo drawdown sets: about 1 minute.

That is about 4 CPU-minutes. **Run 0's budget is 60 CPU-minutes, and so is each amendment run's.** A0 (the procedure
controls: 40 synthetic panels, the seed-A pipeline with the stop-loss variant) needs about 40 × 50 s ≈ 35
CPU-minutes; **A0's budget is 120 CPU-minutes.** The slow calibration test stays at about 9 CPU-minutes per point.
**[M21]** With the one-off size check of E1 under volatility clustering (section 9, about 45 CPU-minutes at the
stand-in timing) and the placebo stops (3 × 207 schedule runs a panel, about 6 CPU-minutes over the 40 panels), A0
needs about 85-90 CPU-minutes, inside the same 120. **[M13, M15, M17]** Run 0's added comparators (the placebo stops,
X^φ, the Binance R_0^φ with its shifts, and each S(s_k)'s R_0 with its shifts and N0: about 1,900 schedule runs and 10
bootstraps) add about 45 s. The slow calibration (about 18 CPU-minutes for
its two points) also runs in the full tier with coverage, which TESTING.md #51 found several times slower; A1 times it
there and writes the expected full-tier wall time at `-n 2` (perhaps 35-40 minutes) into the A1 amendment. The review
of 2026-11-22 timed, on synthetic data on this machine, one 2190-row engine run with a trend-like callback at 0.015 s
(median of 20), one paired bootstrap of 10,000 resamples × 1820 rows at block 60 at 1.5 s, `e1_rank` over 207 series
at 0.01 s and 1000 Monte Carlo drawdowns at 0.1 s: run 0 at about 4-6 CPU-minutes fits its 60.

**Projection guard (stop rule 17).** Before any bar is read, `run_train.py`, and `controls.py` before any panel is
built, re-time on the throughput rule's synthetic panel: one 200-trial study of the built adapter (`n_workers = 1`,
the Branch R box), the median of 20 full-length runs, the median of 20 stop-variant runs at φ = 0.20 (with their
passes) and one paired bootstrap. Each projects its whole run from the pinned run counts (a table in `study.py`,
checked by hand in a test). Above its budget it refuses (exit 2, nothing written, so no run number is used up)
and prints the projection; a projection of exactly the budget starts, and a run that starts writes the timings and
the projection into its start record. A synthetic dry run records the projection and never refuses. Tests stub the
timing where they must pass the guard (TESTING.md #51: a coverage run is several times slower). A refusal goes to
the owner, like stop rule 3; the budgets are not raised to make a run start.

**Selection.**
- `stable_region(trials, specs, k=10)` inside `walk_forward_optimize`, unchanged.
- For every fold the report gives the chosen trial, each parameter's range over its 10 neighbours with their scores,
  and the raw best trial.
- "Best stable region" means that neighbourhood, never the top trial alone.

**Two searches.** Seed A = 0 (primary) and seed B = 1, identical in everything but the seed. Seed B gets its own
R_0, rotations, N0 and X, its own book and the same bootstrap. FRAGILE is defined in E5.

**Study names, one directory** (`results/trend-steady/train/`):
- run 0: `trend-steady-s0_wf00` .. `_wf04` and `trend-steady-s0_final`, and the same with `s1`;
- amendment run k: `trend-steady-s0_a<k>_wf00` .. `_wf04` and `trend-steady-s0_a<k>_final`, and the same with
  `s1`.

The `context` of every study records:
- the snapshot id and the bars hash;
- the git commit and dirty flag, and the config hash;
- the source, the seed and the run number;
- the branch (F or R; **[M1]** R);
- the limits as read (`min_cash`, `max_coin`, the raw budget value and the file's SHA-256).

## 8. User settings and allowed values

**[M1] This study is in Branch R.** The draft's Branch F text below is struck and kept for the record only.

~~**Branch F, fixed settings: no setting a user can change.** This is the default, and today it is the only branch
open, for two reasons:~~
1. ~~AGENTS.md "Settings ranges": the level's drawdown budget must be owner-approved **before** a range is
   pre-registered. Steady's budget is `TBD` (`config/risk_levels.yaml`, read 2026-11-21).~~
2. ~~The allowed range must lie inside the search box. s is not searched in Branch F, so it cannot support a range.~~

~~The strategy would ship θ_final(A)'s L and δ with s = 0.50 and the 50/50 split. It is gated as AGENTS.md says for
fixed settings: on the walk-forward result, plus θ_final's own runs wherever the gate table names the default
(section 10). Those θ_final runs are in-sample (θ_final was chosen on all of train), so they add checks, not
evidence.~~

**A range cannot be added later.** Allowed values set after results would be post hoc. And a range that fails can
never be cut down to fixed settings.

**Lookback and buffer are never user settings**, in either branch:
- they are the timing the luck tests measure;
- letting users pick them invites picking by past results, which the app rules out ("No best settings",
  `features.md`);
- every extra value multiplies the combinations that must each pass every gate.

**Branch R (a crypto-share setting), only if, before PLAN.md is committed:**
1. the owner approves a Steady drawdown budget in writing (a number, or the method that sets it);
2. `risk-officer` writes the budget into `config/risk_levels.yaml` with that approval;
3. PLAN.md's header reads "Branch: R", quoting the number and the file's SHA-256;
4. section 2 lists, as prior looks that could inform the range (AGENTS.md "Settings ranges"), everything the owner
   and `risk-officer` had seen when they set the budget and the allowed values, in particular whether hold-mix-cap's
   RESULTS.md or any other result on 2017-2024 prices had been published by then.

**[M1] All four conditions are met:**
1. the owner approved 35% in writing on 2026-11-21 (`b05109e`, 16:31 UTC; header, decision 1);
2. `risk-officer` wrote `max_drawdown_budget_pct: 35` into `config/risk_levels.yaml`, with its tests, in `368b90a`
   (2026-11-21 22:53 UTC);
3. the header reads "Branch: R" with the number and the file's SHA-256;
4. section 2, K12: hold-mix-cap's results had **not** been published when the budget and the values were set;
   rebalance-steady's and dip-timing's had. K10 and K11 log the later readings.

~~Otherwise the header reads "Branch: F", and this paragraph is struck by a dated amendment before run 0.~~ In Branch R
(**binding, [M1]**):
- **Third searched parameter:** `Param("crypto_share", "float", 0.30, 0.60)`, linear.
  - The top is 0.60, not 0.78: near 0.78, a rise of about 13% forces a limit fix, which goes against "a few trades a
    month", and a one-day crash costs about s × the fall.
  - 0.60 also needs the per-coin reading of `max_coin_pct`.
  - All 4 states pass `check_targets` for every allowed value (appendix B).
- **Allowed values** (set by `risk-officer` in the pre-registration, both ends included): s ∈ {0.30, 0.40, 0.50,
  0.60}. **[M1]** Approved by the owner on 2026-11-21 (decision 1), before any trend-steady or hold-mix-cap result
  (K12). `risk-officer`'s review of this plan checks them against the limits as read; they cannot change after any
  result.
  - **[M22]** AGENTS.md has `risk-officer` set the allowed values in the pre-registration. On record at this commit:
    the values were written into the draft's section 8 from its limits sketch (2026-11-21, by 16:11 UTC) and approved
    by the owner (16:31 UTC, decision 1); the 2026-11-22 review re-ran their feasibility against the file as it reads
    now (`trendrun/riskreview/feas_check.py` in the session scratchpad: all 24 target sets pass). A dated written
    confirmation by `risk-officer` is not yet in the record. It is recorded as a named amendment before A0 starts, or
    A0 and run 0 wait; it can confirm the four values only, never change them (they are fixed before any result).
  - The **default** is the allowed value nearest θ_final(A)'s s; ties go to the lower value. **[M19]** The distances
    are |s − s_k| in floating point, and when the two smallest distances differ by at most 1e-12 it is a tie, which
    goes to the lower value (in binary 0.35 − 0.30 and 0.40 − 0.35 are not equal).
  - L, δ, the split and the check day stay at θ_final(A)'s values.
- **The grid** is the 4 steps. Every gate is measured where the AGENTS.md "Settings ranges" table says:
  - G1 and G2 at every step, held fixed over the out-of-sample span;
  - G5 from the default (L, δ and s, each ×0.8 and ×1.2) and at every step;
  - G6 at S and at the deepest step;
  - G7 and G8 at the default and at every step;
  - every grid run is added to the total trial count, never to the effective count.
  - One failing step fails the range.
  - **[M13]** The exact measurement points of every gate, of R1 and of the S(s_k) check are the table "Where each gate
    and R1 is measured (Branch R)" in section 10; this list is its summary, and the table decides.
- **This plan's out-of-sample range check (stricter than AGENTS.md, not a gate change).** A grid step carries
  θ_final's timing, which was chosen on all of train, so its fixed runs are in-sample in their timing. So, for each
  allowed s_k, S(s_k) = the walk-forward with each fold's chosen L and δ and s replaced by s_k must also have:
  - Sharpe ≥ 1.0 at 1x and > 0.5 at 2x;
  - a Monte Carlo p5 drawdown within the budget;
  - **[M13]** E1 and E2, exactly as for S (section 11): its own R_0(s_k) (S(s_k)'s schedule executed continuously,
    section 9) against its 207 guarded shifts, and S(s_k) against its own N0(s_k), built per fold from S(s_k)'s book
    at each fold's t0. These are extra conditions (the owner's "every value must pass every check"); they enter the
    headline through the range, not the verdict.

  A failing S(s_k) fails the range like a failing grid step.
- **Narrowing** follows AGENTS.md only:
  - only to meet a risk limit (the budget or the level's limits);
  - by dropping whole values from the riskiest end (the end whose steps include the deepest Monte Carlo p5);
  - **[M19]** the riskiest end is read from G6's statistic (section 10) over the grid steps and the S(s_k): the most
    negative p5, ties to the higher s. If a narrowing is needed and that deepest p5 is not at s = 0.30 or 0.60,
    narrowing is reported as not possible, and the range fails. Values are dropped one at a time from that end; after each drop the range gates
    run again on the values left, with the new edge's margin to the budget logged, and the first range that passes
    is the one reported;
  - **[M19]** a narrowing never drops a value whose Sharpe failed. Any failure that is not a risk-limit failure (a
    Sharpe, plateau, benchmark or regimes failure, an R1 failure, or E1 or E2 at an S(s_k)) means narrowing fails,
    because AGENTS.md allows narrowing only for the drawdown budget or the level's limits, and only from an end. A
    G6 failure at S cannot be narrowed either: S is the walk-forward choice, and a failing walk-forward result fails
    the strategy;
  - each drop logged with its margin;
  - the dropped steps stay in the count;
  - frozen before any test-window run;
  - the range must keep the default: if meeting the budget would drop the default's value, the range fails (it
    is never re-centred and never cut to fixed settings).
- **[M1] The headline and a narrowing.** This study computes its headline on the full pre-registered range (section
  12). When narrowing could apply (every failure is a risk-limit failure at the riskiest end of s), the mechanical
  result of the rule above is reported next to the headline: "narrowing would keep {…}, with margin …" or "narrowing
  fails: it would drop the default". Applying a narrowing is the auditor's and `risk-officer`'s step after the audit
  (AGENTS.md), never this study's.
- **[M1] Where s enters the comparators.** R_0, the shifts, B3-lead, N0 and X use each fold's chosen s (section 9).
  Each grid step has its own N0 for G8-excess, built per fold from that step's book at each fold's t0, exactly as
  S's N0 is.
- **[M4] The stop-loss variant** runs on S's per-fold choices (section 11A); at each allowed s its S(s_k)^φ runs
  are descriptions only. The variant is not part of the range and is not gated.
- **Paper:** the riskiest step gets the second paper model account. **[M19]** The riskiest step is the allowed value
  with the deepest G6 statistic (Monte Carlo p5, ties to the higher s) in the range as finally approved, after any
  narrowing; one account covers both when the default is the riskiest step. This binds the Nautilus build's
  pre-registration; this scouting study sends nothing to paper.

## 9. Comparators and luck controls

All comparators run with costs on (1x unless stated), on exactly S's kept rows. **Decisive** means the comparator
enters the verdict.

| ID | What | Harness | Role |
|---|---|---|---|
| S | `walk_forward_optimize(...)["oos_returns"]`, 1x adapter, seed A | H0 per fold, stitched | Gates; E2-E6 |
| R_0 | **S's own schedule, executed continuously.** One book from fold 0's t0 to the last train close, starting from S's fold-0 book (common start). At each of the W = 260 check closes c_k, the state pair is z(c_k): the state fold i's S run holds at c_k, where t0_i ≤ c_k ≤ last_i. **[M1]** The schedule's entry at c_k is the target vector (s_i/2)·z(c_k) of that fold i, so each fold's s travels with its states. It is held between check closes, and limit fixes are endogenous. **[M11]** In R_0, every shift, B3-lead, E8's Binance R_0 and shifts, and R_0^φ, an order is sent at a check close where the target vector changes: a state change, or a change of s between source folds (a re-cut). A re-cut counts as an order (fills, R_0 − S difference) but not as a coin-state change for P or the switch counts; limit fixes order the vector in force. So at the first check close of a new fold whose s differs, with the states unchanged and a coin in, R_0 re-cuts to the new s; with both coins out nothing changes and nothing is ordered. Scored on S's 1820 kept closes (the closes t0_1 .. t0_4 are not kept rows of any fold, so they are dropped) | H0, one span | **E1's statistic.** On fold 0's kept rows R_0 equals S bit for bit (asserted). It differs from S only at fold boundaries, where R_0 pays the switch S's stitched curve never pays; the difference is reported |
| B3 | **Shifted timing.** For every offset u = G + 1 .. W − 1 with the **lead guard G = 52 weeks**, the schedule z_u(c_k) = z(c_{(k+u) mod W}) (both coins together; **[M1]** the whole target vector moves, carrying its fold's s), executed exactly as R_0 from the same book. **Exhaustive over the guarded offsets: 207 series (u = 53..259), no seeds.** Offsets u = 1..52 are not in the null: there z_u(c_k) is the state the rule takes u weeks *later*, which was set from prices that include the very returns the shifted schedule then earns (a 200-day average reaches 29 weeks back, and hysteresis carries a state further). Such a shift is a look-ahead copy of the signal, not chance; it tends to beat R_0 under any trend and even on a random walk, which pushes E1's false-positive rate far below 5%, costs power and would fail the draft's two-sided calibration band. On synthetic iid random walks (audit check, `audit/shift_null_check.py`, 400 panels, simplified one-coin model) 74% of these lead offsets beat R_0 at (L, δ) = (200, 0.10), and E1 with all 259 offsets passed on 0.0% of panels; with the guarded 207 offsets it passed on 5.0% (2.8% against 5.5% at (50, 0.02)). **[M16]** Those rates are under the draft's p95 rule. Rerun on 2026-11-22 with E1's rank-p rule (section 11; `trendrun/checks2/shift_null_rank.py`, the same 400 panels per point): 5.25%, 4.50% and 6.25% at (50, 0.02), (200, 0.10) and (20, 0.005), against 5.50%, 5.00% and 6.75% under the p95 rule (binomial sd about 1.1 points). Offsets u = 208..259 (delays of 1-52 weeks) stay: a delayed state reads only past prices | H0, one span | **Decisive: E1.** It keeps time in market, spell lengths, the number of switches (up to the one splice) and the BTC/ETH co-timing; only the alignment with prices changes. A whole-span shift can move the 2018 or 2022 out-spells onto 2019-21, so it tests the timing of the big cycle, not only the timing within a year. It stands in for AGENTS.md's random-entry benchmark with the same number of trades |
| N0 | **Always in.** From S's book at close t0 of each fold, the states are forced to (in, in): it orders (0.25, 0.25) (**[M1]** (s_i/2, s_i/2) with fold i's s) at close t0 unless S already holds that state, then makes limit fixes only. At 2x it starts from S-at-2x's book | H0 per fold, stitched | **Decisive: E2, E4, E6, E7** |
| X | **Exposure-matched static mix.** Per fold, targets ē_a = the mean of S's w_a over the fold's kept closes, from S's book at close t0, ordered at t0, then limit fixes only. If ē fails `check_targets` with the limits as read and h (possible only if S sat within h of a limit on average over a whole fold), both of X's targets are scaled by the largest common factor λ < 1 that passes, to 1e-12, and X is marked "clipped" with λ in RESULTS.md. This is an outcome, not a stop | H0 per fold, stitched | **Decisive: E3.** Does timing cut falls beyond simply holding less crypto? |
| B1 | Buy-and-hold BTC, `steady.buy_and_hold_b1` with `fold_window(..., warmup=2190)` | H0 | G7 |
| B2 | 50/50 BTC/USDC every 30 days, `steady.fifty_fifty_b2` likewise | H0 | G7 |
| B3-lead | The 52 excluded offsets u = 1..52 (leads), run exactly as B3 | H0, one span | Description only: a lead/lag profile of how sharp the timing is. Never a null, never in any criterion. (It replaces the draft's B3-fold, a circular shift within each 52-week fold: every one of its offsets leads the schedule over part of the year, so it was a look-ahead profile, not a within-year null). **[M20]** R_0's rank among the 52 lag offsets u = 208..259 (delays of 1-52 weeks, which stay in E1's null) is reported next to it, completing the lead/lag profile; a description, never a null |
| N0-span | Always in, bought once at fold 0's t0 and held to 2023-01-01 | H0, one span | Description |

The two decisive tests do different jobs:
- E1 asks whether the *dates* were well chosen, holding exposure fixed.
- E2 asks whether timing beat *not timing*.

A long-biased rule beats a coin-flip null for free, so the shift null keeps S's exposure exactly.

**Procedure controls, before any real bar (amendment A0; synthetic only, not results).** The seed-A train pipeline
is run end to end (5 fold studies at N, H0, R_0 and its shifts, N0, P, E1 and E2; **[M1]** with the Branch R box;
**[M4]** and the stop-loss variant at its three levels, with R_0^φ, its shifts, N0^φ, SL-E1 and SL-E2; **[M17]** and
its placebo stops and SL-T) on two sets of 20 panels:
- **positive controls:** `make_panel(synthetic_market(2190, seed=1000+j, start="2017-01-02"),
  snapshot_id="synthetic")`, j = 0..19. These have persistent bull, bear and sideways regimes;
- **negative controls:** `shuffled_market` of those markets (seed j). This destroys every serial structure.

Reported:
- **power**, the share of positive panels where E1, E2 and P all hold;
- **false positives**, the share of negative panels where E1 and E2 both hold;
- **[M4]** the variant's false positives: per level, the share of negative panels where SL-E1 and SL-E2 both hold;
- **[M17]** per level, the share of negative panels where SL-T holds on its own (the stop's own timing, section 11A);
- **[M21]** next to the joint counts, E1's own and SL-E1's own false-positive counts on the negative panels (and their
  shares on the positive panels). On shuffled markets the always-in mix keeps the drift while a trend rule's Sharpe
  is cut by about the square root of its time in the market, so E2 almost never holds there, and the joint counts
  cannot show a leaky E1 or SL-E1. These counts are reported only; the decision rule below is unchanged.

Then:
- 3 or more false positives in 20 (**[M4]** for the plain rule, or for the variant at any level; **[M17]** or SL-T on
  its own at any level): stop and triage before any real bar (stop rule 15). **[M21]** For a single test whose size is
  4.8%, 3 or more of 20 happens about 7% of the time by chance, so SL-T can raise this alarm with no bug. If the
  triage finds no bug and no design fault, the counts and the triage go to the owner in writing, and run 0 waits for
  his written decision; the controls are never rerun with other seeds to make them pass.
- Power below 4 of 20: tell the owner before run 0. The study would mostly return INCONCLUSIVE or NO EDGE (LOW
  POWER), and the owner decides whether to run it. **[M21] This alarm is expected to fire.** Indicative only (the
  review's synthetic check on 40 panels of this generator, seeds 1000-1039, at fixed parameters, with no search and
  no costs): E1 under the
  rank-p rule held on 6-7 of 40, E2 on 1-3, P on 14-40, and all three together on 0-3 (0-7.5%); at a true power of
  7.5% the chance of 4 or more of 20 is about 6%. The positive controls' regimes last about 40-67 days on average,
  short next to averages of up to 200 days, so A0's power says little about real data, where bear markets lasted
  about a year (K1). When it fires, the lead sends the owner this question in writing, and run 0 waits for the written
  answer: "The procedure check found that this study can rarely detect a trend edge on synthetic markets whose trends
  are short (power k of 20). Real bear markets last longer, so it may do better on real data, but run 0 is likely to
  end INCONCLUSIVE or NO EDGE (LOW POWER). Run it anyway, or stop here?"

**[M21] E1's size under volatility clustering (one-off, part of A0, not in the slow tier).** The slow calibration's
slowest point, (L, δ) = (200, 0.10) at s = 0.50, run exactly as the slow calibration test runs it (H0 as one span from
row 0, R_0 over the W = 260 checks against its 207 guarded shifts, the 1820 rows, 1x costs, E1's rank-p rule), on
1000 panels with no momentum but with volatility clustering:
- daily log returns 0.001 + σ_a·g_a(t), σ = (0.04, 0.05) for BTC and ETH: constant drift and no regimes;
- g_a is a unit-variance GARCH(1,1) (α 0.08, β 0.90, ω = 1 − α − β, the lab generator's settings; started at variance
  1 and a zero previous shock) of Student-t(5) innovations scaled to unit variance, drawn as one (2190, 2) array by
  `rng.standard_t(5, size=(2190, 2))`, with ETH's innovation set to 0.8 × BTC's + 0.6 × its own;
- `rng = np.random.default_rng(10_000 + j)`, j = 0..999; prices from 10,000 (BTC) and 500 (ETH), bars built as in the
  slow calibration test on the 2190-close train grid.

Holds if at most 67 of the 1000 panels pass E1 (at a true 5% that holds 99.3% of the time; a true 7.5% fails it 82% of
the time). More than 67: stop rule 15. About 45 CPU-minutes at the stand-in timing (208 runs × 1000 panels × 0.013 s).
Why: across its cases, the review's synthetic check found E1's pass rate up to 6.7% under the p95 rule with volatility
clustering, highest at this corner (3.3-6.3% under the rank-p rule in all its cases). The slow test (iid only, at most
18 of 200) cannot see a rate of that size: it passes a true 7.5% 83% of the time.

These panels are not trials and enter no count.

**Calibration test (slow tier).** Two pinned points, each its own parametrized test, with no search: (L, δ) = (50,
0.02) and the slowest corner of the box, (200, 0.10), where a state's memory is longest and any leak through the
lead guard would show first. **[M1]** Both at s = 0.50: the test is about the lead guard, and E1's shifts keep the
exposure whatever s is.
- 200 panels per point: `make_panel` of two Gaussian log-return random walks on the 2190-close train grid of
  appendix B (2018-01-13 dropped). Daily log-return mean 0.001 for both coins, sd 0.04 (BTC) and 0.05 (ETH),
  correlation 0.8, `np.random.default_rng(seed)` with seeds 0..199; start price 10,000 (BTC) and 500 (ETH);
  open = previous close (the first open = the first close), high = max(open, close), low = min(open, close),
  volume 1.
- On each panel the fixed rule runs in H0 as one span from row 0. Its schedule over the W = 260 Monday checks of
  the fold layout is R_0 (no folds, one parameter set), scored on rows 366..2189 without the four fold-boundary
  rows (1820 rows), against its 207 guarded shifts, at 1x costs. E1 is applied exactly as in section 11 (**[M16]** the
  rank-p rule: at most 9 of the 207 shifts at or above R_0).
- **Holds if at most 18 of the 200 panels pass E1 at each point** (for a true rate of 5%, P(19 or more) = 0.6%;
  **[M16]** at the rank-p rule's exact size of 4.8%, 0.4%).
  A rate far below 5% is allowed (conservative) and reported as a loss of power.
- Expected cost: about 208 runs × 200 panels × 0.013 s ≈ 9 CPU-minutes per point (stand-in timing).

## 10. Gates (AGENTS.md defaults, unchanged)

Computed on seed A's stitched S (Kraken, 1820 returns); seed B's are computed for E5 (**[M12]** at S_B only: G1, G2,
G3, G4, G5(a), G6, G7 with its boom-year removals and G8-excess; seed B has no default, grid or S(s_k) runs).
- **A missing number fails; it never passes.**
- `rep = overfitting_report({"oos_returns": S_A, "wf_efficiency": ..., "studies": <every study of every run>,
  "total_trials": N_raw}, out_dir)`.
- **Where each gate is measured** follows AGENTS.md "Settings ranges" ~~for fixed settings: the walk-forward result,
  plus θ_final(A) held fixed over the 1820 kept rows (in-sample) wherever the table names the default.~~ **[M1]** for
  a range, as section 8 lists: the walk-forward result S, the default and every grid step held fixed over the 1820
  kept rows (in-sample in their timing), plus this plan's out-of-sample S(s_k) check. **[M13]** The table after the
  gate table lists every measurement point exactly, and it decides.

| Gate | Threshold | Measured at |
|---|---|---|
| G1 | OOS Sharpe after costs ≥ 1.0 | S: `gates(rep)["oos_sharpe >= 1.0"]` |
| G2 | Same at 2x costs > 0.5 | S re-run at 2x: the same per-fold parameters, H0, no new search |
| G3 | DSR ≥ 0.95, counting every trial | `gates(rep)["dsr (effective) >= 0.95"]` **and** the active-row DSR (section 14) ≥ 0.95: both must hold, and a missing one fails. The effective count comes from the search studies only. Taking the stricter of the two readings is this plan's measurement rule for the all-cash warmup rows (section 6), not a threshold change |
| G4 | PBO ≤ 0.25 | `gates(rep)["pbo <= 0.25"]`: the mean of the per-study PBO (10 blocks) over every study, **and** the same mean on the active rows (section 14) ≤ 0.25: both must hold |
| G5 | Plateau: each step keeps ≥ 70% of Sharpe(S), and Sharpe(S) > 0 | (a) From each fold's choice: L and δ each ×0.8 and ×1.2, applied to every fold at once (4 stitched runs, H0). (b) From θ_final(A), held fixed over the kept rows (4 runs). **[M1]** In Branch R: (a) also s ×0.8 and ×1.2 (6 stitched runs per seed); (b) from the default instead (L, δ and s, 6 runs); and (c) every grid step (section 8). s steps are not rounded; steps outside 0.30-0.60 are marked "outside the box" (all feasible, appendix B). L steps: down = max(1, min(half_up(0.8·L), L − 1)), up = max(half_up(1.2·L), L + 1), with A = max(199, L − 1). δ steps: ×0.8, ×1.2. Steps outside the box are allowed and marked "outside the box" |
| G6 | Monte Carlo p5 max drawdown within the budget | S: `rep["mc_drawdown_worst5pct"]` (stationary block bootstrap, mean block 20, 1000 draws, seed 0) ≥ −budget. The budget is read by `risk_limits("steady")` **before any real bar** and recorded; only that reading counts for the whole study, amendment runs included. **`TBD` → MISSING = FAIL**, whatever is set later. **[M1]** Read on 2026-11-22: 35 → 0.35, so G6 = `gates(rep, budget_drawdown=0.35)`, p5 ≥ −0.35; also at the deepest grid step and at every S(s_k) (section 8). **[M19]** G6 compares with the budget recorded in the start record (`risk_limits("steady")["max_drawdown_budget"]`, read before any bar), never with a typed 0.35; the 35 of stop rule 11 is only a refusal check. At S, at every grid step and at every S(s_k) the statistic is exactly G6's: `mc.percentiles(mc.block_bootstrap_drawdowns(r, mean_block=20, n_sims=1000, seed=0), (5,))["p5"]` on that series' 1820 kept returns r, which is what `overfitting_report` computes for S. "Deepest" is the most negative p5, ties to the higher s; the same statistic defines the riskiest end and the riskiest step (section 8). The mean-block-60 bootstrap of section 16 is a description. This is the owner's "95th-percentile max drawdown within a 35% fall": the p5 of the (negative) drawdowns is the 95th percentile of the fall |
| G7 | Better risk-adjusted return than B1 and B2 | Sharpe(S) > Sharpe(B1) and > Sharpe(B2) on the same rows. **Also** with BTC's best bar-year of the kept span removed, and with its two best removed (the owner's rule, E7's ranking). **Also** ~~θ_final(A) held fixed against B1 and B2 on the full rows~~ (**[M1]** the default and every grid step, each with the boom-year removals too). **[M13]** In Branch R θ_final(A) is not a G7 point (AGENTS.md "Settings ranges" names the default and every grid step, and θ_final(A)'s unrounded s is not a value a user can pick; the draft's own Branch R list in section 8 said the same); its G7 numbers are an in-sample description. Points: the table below |
| G8 | No regime makes most of the profit | Each kept row belongs to the month of its bar day (close − 1 day). A month is bull if BTC's compounded return over that month's kept rows is ≥ +10%, bear if it is ≤ −10%, and sideways otherwise. PASS if Σ ln(1 + r) > 0 and no regime holds more than half of it. Measured at S **and** at θ_final(A) held fixed. **Read literally** (owner question 5). Expected to FAIL by construction for a long-or-cash rule. The owner's alternative is pinned now so it cannot be defined after results: **G8-excess** = `steady.regime_split(S, table, benchmark=N0)`, PASS if `excess_total` > 0 and every regime's `excess` ≤ `excess_total` / 2 (at θ_final(A), against θ_final(A)'s own N0, built per fold from θ_final(A)'s book at each fold's t0 exactly as S's N0 is). G8-excess replaces the literal reading only if the owner chooses it in writing before PLAN.md is committed; both readings are always reported. **[M2] The owner chose G8-excess in writing on 2026-11-21 (decision 2), before this plan's commit. G8-excess is the gate**, at S, at the default and at every grid step, each against its own N0 (section 8); the literal reading is reported next to it and decides nothing. **[M13]** In Branch R θ_final(A) is not a G8 point (as for G7); its G8 numbers are an in-sample description. **[M10] G8-excess is expected to FAIL by its arithmetic:** with three regimes, every regime's excess ≤ excess_total / 2 forces every regime's excess ≥ 0; a long-or-cash rule usually trails N0 in bull months, and otherwise its bear months usually hold more than half the excess (section 1; owner question 6). The gate is unchanged |
| G9 | Final test window, run once | **NOT RUN.** Never in this study |

**[M13] Where each gate and R1 is measured (Branch R).** A gate, R1 or the S(s_k) check **holds only if it holds at
every point listed in its row**; a failure or a MISSING number at any one point fails it, and the headline names that
point. "Grid step" means each of the four allowed values s_k ∈ {0.30, 0.40, 0.50, 0.60} with θ_final(A)'s L, δ, split
and check day, held fixed over the 1820 kept rows; **the default is one of the four grid steps**, named separately
only where AGENTS.md names it. Nothing that is not listed decides a gate or R1: θ_final(A)'s gate numbers, seed B's
(they enter only E5, section 11), S(s_k)'s G5, G7 and G8, and the stop-loss variant's runs (its own verdict line,
section 11A) are descriptions here.

| Item | Measured at (seed A, Kraken, 1820 kept rows) |
|---|---|
| G1 | S; every grid step; every S(s_k) |
| G2 | S at 2x; every grid step at 2x; every S(s_k) at 2x |
| G3 | S, in both readings (section 14) |
| G4 | the search studies, in both readings (section 14) |
| G5 | (a) S's per-fold choices with L, δ and s each ×0.8 and ×1.2 (6 stitched runs); (b) the default with L, δ and s each ×0.8 and ×1.2 (6 runs held fixed); (c) every grid step. Each against Sharpe(S), which must be > 0 |
| G6 | S; every grid step; every S(s_k); G6's statistic on each, against the budget recorded before any bar |
| G7 | S, the default and every grid step, each on the full rows, without BTC's best bar-year and without its two best |
| G8-excess | S, the default and every grid step, each against its own N0. The literal G8 is reported at the same points and decides nothing |
| G9 | not run |
| R1 | S; θ_final(A) held fixed; the default; every grid step |
| S(s_k) check | each S(s_k): G1, G2 and G6 as above, and E1 and E2 (section 8) |

Reading G1, G3 and G7: they are weak evidence (K1, K2). The 2018-2022 span holds two known bear years, which any rule
of this family largely sits out. B1 looks bad in 2018 and 2022 for the same reason. E1, E2, E6 and E7 carry the
research question.

## 11. Research criteria

Unless stated otherwise: seed A, Kraken, the 1820 stitched kept rows, costs at 1x, and Sharpe =
`stats.annualized_sharpe(r, 365)`. A **bar-year** is the calendar year of a kept row's bar day (close − 1 day); the
kept span has bar-years 2018-2022.

| ID | Criterion | Holds if |
|---|---|---|
| **E1** | Timing beats chance | ~~Sharpe(R_0) > the 95th percentile (`np.percentile`, linear) of the 207 B3 Sharpes (guarded offsets u = 53..259, section 9). Ties count against S. The rank p = (1 + #{B3_u ≥ R_0}) / 208 is reported.~~ **[M16]** The rank p = (1 + #{B3_u ≥ R_0}) / 208 < 0.05 over the 207 B3 Sharpes (guarded offsets u = 53..259, section 9), i.e. at most 9 of the 207 shifts at or above Sharpe(R_0); ties count against R_0. Read as `steady.e1_rank(...)["rank_p"]`, so `steady.py` is unchanged; `e1_rank`'s `holds` (Sharpe(R_0) > the linear 95th percentile) is reported as a description only. Under the null this test's size is 10/208 = 4.8% (the p95 rule's was about 5.5%, and it could report "holds" next to p = 12/208 = 0.058). The 52 lead offsets (B3-lead) are reported separately and never enter E1 |
| **E2** | Beats holding the same mix | D = Sharpe(S) − Sharpe(N0) > 0, **and** the one-sided paired stationary bootstrap gives p < 0.05: `steady.paired_bootstrap(S, N0, n_resamples=10000, mean_block=60, seed=0)`, with the same indices for both series and p = (1 + #{D* ≤ 0}) / 10,001. Mean block 60 because trend spells last months; a block of 20 understates D's variance. Block 20 is reported as a description |
| E3 | Cuts falls beyond holding less crypto | S's stitched historical max drawdown **and** S's Monte Carlo p5 max drawdown (G6's statistic) are both strictly shallower than X's |
| E4 | Survives doubled costs | Sharpe(S at 2x) > Sharpe(N0 at 2x) |
| E5 | Not fragile | (a) Seeds A and B give the same outcome for each of E1-E4, E6, E7, P and ~~G1-G8~~ **[M12]** the gates measured at S only: G1, G2, G3, G4, G5(a), G6 at S, G7 at S (with the boom-year removals) and G8-excess at S. The default, grid and S(s_k) parts are seed A only and do not enter E5. Also, their OOS Sharpes differ by ≤ 0.25. (b) **Check-day sensitivity:** S re-run with each of the other 6 check weekdays (seed A's per-fold ~~L and δ~~ **[M20]** L, δ and s, H0, nothing re-searched) keeps ≥ 0.7 × Sharpe(S) for every weekday, **and Sharpe(S) > 0** (as in G5: with Sharpe(S) ≤ 0 the 0.7× test would pass a weekday that does worse, so E5 fails). An edge that lives on Mondays only is luck about particular days |
| E6 | Not one year | Let Δ_y = Σ over bar-year y's kept rows of ln(1 + S_t) − ln(1 + N0_t), and Δ = Σ_y Δ_y (named Δ, not X, so it is never confused with the comparator X). Holds if Δ > 0 **and** Δ − Δ_y > 0 for every y in 2018-2022: the excess over always-in survives losing any one year, bear years included |
| E7 | Not the boom years (owner's rule, 2026-11-21) | Rank bar-years 2018-2022 by BTC's compounded close-to-close return over each year's kept rows (Kraken; ties: the earlier year ranks higher). With the best year's rows removed, and again with the two best years' rows removed (from every series alike; nothing refitted; the same offsets and the same bootstrap settings on the remaining rows in time order), **E1 and E2 both still hold** (**[M20]** and E3 and E4 too: the owner's rule covers every comparator, X and N0 at 2x included; E1 with the rank-p rule over the same 207 shifts). Bootstrap blocks may run across the gap a removed year leaves |
| E8 | Other data source | On Binance, folds 1-4 only (Binance has no signal until 2018-03-05, inside fold 0), with seed A's per-fold parameters (**[M20]** L, δ and s): E1 (Binance R_0 against its 155 guarded shifts, u = 53..207, over the 208 check closes of folds 1-4, from Binance S's fold-1 book; **[M16]** holds iff (1 + #{shifts at or above}) / 156 < 0.05, i.e. at most 6 of the 155, a size of 7/156 = 4.5%) and E2 (Binance S against Binance N0, 1456 rows) both hold. The Kraken folds 1-4 values are shown alongside |
| P | Power floor | At least 20 coin-state changes (both coins counted) at check closes whose orders fill in kept rows, with at least one in each of at least 4 of the 5 folds. First buys and limit fixes do not count. **[M20]** P is a minimum-information floor, not a power floor (A0 measures power). BTC and ETH often switch in the same week, so 20 coin switches can be about 15 separate decisions: the number of distinct switch weeks and of completed out-spells per coin are reported next to P (descriptions; P's rule is unchanged) |
| E9 | Validate does not contradict (reject-only; at the single look, section 13) | θ_final(A) on Kraken validate at 1x (546 kept returns): Sharpe > 0; ≥ 0.5 × Sharpe(S); ≥ 0.5 × Sharpe(N0 on validate); and > the median of its own 25 guarded validate shifts (u = 53..77 over the 78 validate check closes, the same lead guard G = 52). Beating N0 outright is not required: validate is a known bull window (K4) where a filter is expected to trail always-in, so the outcome of that test is known in advance |

**Notes on the criteria.**
- E1 and E2 form an intersection test, so each at 5% needs no correction. **[M16]** With E1 decided on its rank p, its
  size is 4.8% (E8's E1 4.5%); the review found E2 conservative at its boundary null in synthetic checks (0.5-3.5%).
  So the chance that a rule with no edge reads EDGE is at most about 5%: requiring both cannot raise it.
- **[M20] What EDGE rests on.** E2, E3, E4, E6 and G1 and G7 are all driven by the same two bear years, so an EDGE
  claim really rests on E1, and on E1 with the boom years removed (inside E7). Removing BTC's best years removes the
  rows where always-in beats a trend rule, so E7's E2 half is easier than E2 itself; its E1 half is the part with
  teeth. With two years removed, E2's bootstrap has about 1092 rows, roughly 18 blocks of 60, so its p is cruder.
  The "both bear years removed" row (section 16, a description) is shown next to E7 in RESULTS.md, as the matching
  check for this kind of rule.
- E2's power comes mostly from the two bear years, about 30 bootstrap blocks that are not independent, so its p is
  optimistic. E6 and E7 are the checks on that.
- E7 follows the director note of 2026-11-21: "a strategy that beats its comparators only with the boom years in does
  not count as beating them". The boom years are where always-in beats a trend rule, so E7 mostly guards the
  comparison with B1 and B2 (in G7) and the shift null. E6 guards against the opposite dependence, on one bear year.
- The leave-one-year-out results of E1, E2, G7 and the plateau are reported for every year, whatever their outcome.

## 11A. The stop-loss variant [M4]

Owner decision 6, pinned completely before any result. Section 15 (M4) says why each choice was made and whether
hold-mix-cap's results could have informed it.

**In plain words.** The owner asked for a basic stop-loss on top of the trend rule: "if we put in 1,000 and then we
make ... 2,000, we don't want to slide ... more than 40% below that 2,000". The variant tested here:
- Every day at the 00:00 UTC close, it compares the wallet's value with the highest value the wallet has had (since
  the strategy started, or since its last stop).
- If the wallet is φ or more below that high, it sells every coin to USDC at the next open. φ is 20%, 30% or 40%,
  each tested on its own (**SL20, SL30, SL40**). The owner chose these three levels.
- After a stop, a coin is bought back only when its trend turns up again: at a weekly check, its price has gone from
  clearly below its L-day average to clearly above it (the rule's own up-turn, section 4). A coin whose trend was
  still "up" when the stop sold it must first turn down and then up again, so the wallet is not bought back the week
  after it was sold.

Two things it cannot do:
- **It cannot promise the fall stops at φ.** It checks once a day, at the close, and sells at the next open. A crash
  day can go far past φ before the check (BTC fell 38.9% on the bar of 2020-03-12, K2), and the price can move again
  before the sale. The study reports how far past φ each stop actually sold.
- **It is not the app's loss limit.** The loss limit pauses trading and never sells; this stop sells. By owner
  decision 3, a sale to cash goes through during a loss-limit pause or while waiting for approval, so a pause does not
  block it.

The symbol φ is used for the stop level so it is never confused with the comparator X of section 9.

### (a) What falls φ: the wallet's value

- **The wallet's value** V(t) at close t is the value the engine books after every cost it pays (pool fee, slippage
  and gas): V = `np.cumprod(1 + res["ret"])` of the run's own result, a value index that starts at 1 at row 0. The
  ratio below does not depend on the starting USD.
- **Its high** H(t) is the largest V over the closes from the **reference close** to t, both included. The reference
  close is row 0 of the run (where the strategy starts) until the first stop event, and after that the close right
  after the latest stop event.
- **The fall** f(t) = V(t) / H(t) − 1, computed in that form, as `reference._dip_signal` computes a drop.
- **Why the wallet.** The owner's example is the wallet ("40% below that 2,000"), and the accepted proposal says
  "fall from the top".
- **Why the high restarts only at a stop.** "40% below that 2,000" holds whatever route the wallet took. A trend exit
  that leaves the wallet 15% below its high does not restart the high, so a further fall after the trend buys back is
  measured from the same high. A stop restarts it: a wallet sold at 1,200 is next protected from what it holds after
  the sale, and a buy-back is not sold again at once because the old high is out of reach.
- **Gas.** The engine charges gas to the wallet; in production we pay it. So V sits slightly below a customer's real
  wallet, by at most USD 0.10 per leg traded.
- **Readings left out, not run, not reported:**
  - a per-coin stop (each coin's sleeve falls φ from its own high; the session note `OWNER_DECISIONS.md` names it as
    an option). The owner's example is the wallet, each coin is already timed by its own trend signal, and a second
    per-coin signal would be another rule;
  - a "profit give-back" stop (sell when the wallet gives back φ of its gain over what was put in), one possible
    reading of the owner's first phrase, "more than like 40% of the profit that we've made". The owner accepted "fall
    from the top", and a give-back rule never protects a wallet that has no gain.

  Neither can be chosen after results; either needs its own pre-registration (section 19 asks the owner which he
  meant, with no effect on this study).

### (b) When it is checked, and what it sells

- It is checked at **every daily close**, Monday or not, from row 0. A **stop event** happens at a close t after the
  reference close where f(t) ≤ −φ. A fall of exactly φ counts; in floating point that is exact only for exactly
  representable values (TESTING.md section 4, the finding on the dip trigger).
- If the book holds any coin at close t (w_BTC(t) + w_ETH(t) > 0), the event orders (0, 0): every coin to USDC, each a
  swap against USDC at its own open of t + 1 (hard rule 4), paying the costs of any fill.
- If the book holds no coin (a trend exit's own fill took the wallet past φ), the event orders nothing, but it still
  locks both coins and restarts the high. Without this, the next trend buy would be sold the next day.
- One order per close, in this order: a stop, then a switch, then a limit fix. At a close that is both a stop event
  and a check close, the trend states are updated first and the stop comes last, so both coins end that close
  locked. A stop decided at the last close of a run is never filled.

### (c) The buy-back

- A stop event **locks** both coins. A locked coin's target is 0, whatever its trend state.
- Coin a is **unlocked** at the first check close strictly after the stop close at which its trend state z_a changes
  from out to in (section 4: m_a(c) > +δ at a check close c where z_a was out). The stop never changes z_a: the trend
  states stay a function of prices alone, exactly as in the plain rule.
- So a coin that was **out** at the stop comes back at its next up-turn, which is when the plain rule would buy it
  anyway. A coin that was **in** at the stop must first turn out (m_a < −δ at a check) and then in again. An up-turn on
  the stop close itself does not count.
- The **in-force target** is e_a(t) = (s/2)·[z_a(t) = in]·[a is not locked at t]. An order is sent at a close where e
  changes (a switch, or a stop that sells), or at a limit breach, as in section 4. With no stop event, e equals the
  plain rule's targets at every close, and the variant is the plain rule bit for bit.
- After a buy-back, a later stop needs a new fall of φ from the high that restarted at the last stop.

### How it is computed (exactly, with the engine unchanged)

The engine's `decide(t, w)` sees the weights, not the wallet's value. So the stop events are found by re-running:
1. run the variant with the stop events found so far (none at first);
2. from that run's `ret`, compute V, and H and f from the current reference close on;
3. the first close after the latest event (at the start, the first close of the run) with f ≤ −φ is the next event;
   add it and go back to 1;
4. when there is none, the last run is the result.

Adding an event at close t changes no decision before t, so every V up to close t, and every earlier event, stays the
same; each re-run adds exactly one event, and the result has one run more than it has events. Because V includes
costs, a run at 2x costs or at another wallet size finds its own events.

### (d) The three levels

φ ∈ {0.20, 0.30, 0.40}, set by the owner. They are **fixed values, not searched**, so the free parameters stay at 3
(L, δ and s). Each level runs on the plain rule's per-fold choices (seed A's L, δ and s for S^φ, seed B's for seed
B), in H0 from row 0 per fold (section 7), with nothing re-searched. **No level is chosen, before or after results.**

### (e) Comparators, criteria and the verdict

For each level φ, on S's 1820 kept rows, Kraken, costs at 1x unless stated:
- **S^φ:** each fold's run with the stop, stitched exactly as S.
- **R_0^φ:** S^φ's in-force schedule e(t), at every close from fold 0's t0 to the last train close but one ~~(each
  close's entry from the fold whose test rows hold it)~~, executed continuously by the one executor from S^φ's fold-0
  book, as R_0 is for S. It equals S^φ on fold 0's kept rows bit for bit. **[M11]** Each close's entry is
  E(t) = v(t) ⊙ (1 − l(t)), coin by coin: v(t) is R_0's trend target vector in force at t (the (s_j/2)·z(c_k) of the
  latest check close c_k ≤ t, from the fold j that holds c_k, and fold 0's for the closes before c_0; section 9), and
  l(t) is the lock pair (1 while a coin is locked) of the S^φ run of the fold whose test rows hold t. So the trend part
  moves to a new fold at that fold's first check close, exactly as in R_0 (a re-cut there if s changes), and when
  every l(t) in the span is 0 and S^φ's fold-0 book at t0 is S's, R_0^φ is R_0 bit for bit. An order is sent at a
  close where E changes (a switch, a re-cut, or a lock that turns on or off) or at a limit breach (section 4).
- **Its guarded week shifts** (u = 53..259, 207 series, the lead guard G = 52 of section 9). The W = 260 check closes
  cut the span into weekly segments: segment k runs from check close c_k to the close before c_(k+1), and the last
  one to the last close but one. The 6 closes before c_0 (2018-01-02 .. 2018-01-07) are common to every series
  (common start). In the series for offset u, a close at calendar-day offset j after c_k takes the entry of the latest
  close of segment (k + u) mod W whose offset is at most j. Every segment has 7 closes except segment 0 (the missing
  2018-01-13) and segment 259 (it ends before the last close), which have 6 (appendix B). For the plain rule, whose
  entries change only at check closes, this is exactly B3's shift. Stops move with their weeks; the shifted series run
  the schedule only, and no stop is re-decided.
- **[M17] Its placebo stops** (u = 53..259, 207 series): the locks moved to other weeks, the trend part kept where it
  is. l_u = `segment_shift`(l, u), with the weekly segments above, and the placebo's in-force target is
  e_u,a(t) = (s_i/2)·[z_a(t) = in]·[l_u,a(t) = 0], i.e. E_u(t) = v(t) ⊙ (1 − l_u(t)). Each runs with the one executor
  from S^φ's fold-0 book and is scored on the 1820 kept rows; no stop is re-decided, and u = 0 gives R_0^φ. They ask
  whether the stop's own dates beat stops of the same number and length at other dates, with S's trend schedule
  unchanged. (The review's synthetic check, placebos built this way on 40 panels of A0's positive-control generator,
  at (L, δ) = (50, 0.02) with no costs, found that placebo stops pass SL-B (i) on 45-59% of panels and SL-B (i) with
  (iii) on 23-27%, while the real stop beat 95% of its own placebos on only 0-5% of triggered panels: SL-B alone
  cannot tell a stop with skill from a random one.)
- **[M15] X^φ:** the exposure-matched static mix for S^φ, built per fold from S^φ's weights and S^φ's book at t0
  exactly as X is from S's (section 9): targets ē^φ = the mean of S^φ's w over the fold's kept closes, ordered at t0,
  then limit fixes only, clipped by λ if ē^φ fails `check_targets`. A comparator: logged, not counted.
- **[M15] On Binance** (folds 1-4, seed A's per-fold L, δ and s): Binance S^φ (a counted run, section 14), its R_0^φ over
  the 208 check closes of folds 1-4 from Binance S^φ's fold-1 book, its 155 guarded shifts (u = 53..207) and its
  N0^φ, built exactly as E8 builds them for the plain rule.
- **N0^φ:** always in from S^φ's book at each fold's t0, limit fixes only, no stop (as N0, section 9).
- **S:** the plain rule on the same rows, and S at 2x (G2's run).

"As E…" below applies that criterion's definition (section 11), with these series in place of S, R_0 and N0.

| ID | Criterion | Holds if |
|---|---|---|
| SL-E1 | Timing beats chance | As E1: ~~Sharpe(R_0^φ) > the 95th percentile of its 207 shift Sharpes~~ **[M16]** the rank p = (1 + #{shift Sharpes ≥ Sharpe(R_0^φ)}) / 208 < 0.05 over its 207 shifts, i.e. at most 9 at or above (ties count against it) |
| SL-E2 | Beats holding the same mix | As E2: Sharpe(S^φ) − Sharpe(N0^φ) > 0, and the paired bootstrap (mean block 60, 10,000 resamples, seed 0) gives p < 0.05 |
| SL-B | Beats the plain rule, at both cost levels and without the boom years | All of: (i) Sharpe(S^φ) ≥ Sharpe(S); (ii) Sharpe(S^φ at 2x) ≥ Sharpe(S at 2x); (iii) S^φ's historical max drawdown is strictly shallower than S's; (iv) S^φ's Monte Carlo p5 max drawdown (G6's statistic) is strictly shallower than S's; (v) (i) and (iii) also hold with BTC's best bar-year removed, and with its two best removed (E7's ranking and removal) |
| **[M15]** SL-E3 | Cuts falls beyond holding less crypto | S^φ's stitched historical max drawdown **and** its Monte Carlo p5 (G6's statistic) are both strictly shallower than X^φ's. A stop adds all-cash time, so a shallower fall than S's (SL-B (iii), (iv)) is nearly free; this asks whether it is shallower than simply holding S^φ's average crypto |
| **[M17]** SL-T | The stop's own timing beats chance | (1 + #{Sharpe(placebo_u) ≥ Sharpe(R_0^φ)}) / 208 < 0.05 over the 207 placebo stops, i.e. at most 9 at or above (ties count against R_0^φ) |
| SL-E4 | Survives doubled costs | As E4: Sharpe(S^φ at 2x) > Sharpe(N0^φ at 2x) |
| SL-E5 | Not fragile | Seed B's S^φ (on seed B's per-fold choices) gives the same triggered or not, and the same pass or fail for SL-E1, SL-E2 ~~and SL-B~~, SL-B, **[M15]** SL-E3 and **[M17]** SL-T |
| SL-E6 | Not one year | As E6, with S^φ and N0^φ |
| SL-E7 | Not the boom years | As E7: SL-E1 and SL-E2 (**[M20]** and SL-E3 and SL-E4, as E7 now requires E3 and E4; **[M17]** and SL-T) still hold with BTC's best bar-year removed, and with its two best removed |
| **[M15]** SL-E8 | Other data source | On Binance, folds 1-4 (the series above): SL-E1 (Binance R_0^φ against its 155 shifts: at most 6 at or above) and SL-E2 (Binance S^φ against Binance N0^φ, 1456 rows) both hold |
| SL-P | Enough stops to judge | At least 3 stop orders filled in kept rows, in at least 2 different bar-years |

**Verdict for each level**, applied in this order:
1. **NOT TRIGGERED** if S^φ's kept returns equal S's bit for bit at 1x (no stop touched the kept rows, directly or
   through the book at a fold's t0). Nothing else decides for that level; its descriptions are still reported.
2. **NO EDGE** if SL-E1 or SL-E2 fails.
3. **STOP DOES NOT HELP** if SL-E1 and SL-E2 hold and SL-B ~~fails~~ **[M15, M17]**, SL-E3 or SL-T fails.
4. **INCONCLUSIVE** if SL-E1, SL-E2 ~~and SL-B~~ **[M15, M17]**, SL-B, SL-E3 and SL-T hold and any of SL-E4, SL-E5,
   SL-E6, SL-E7, **[M15]** SL-E8 or SL-P fails.
5. **STOP HELPS** if all of them hold.

If SL-P fails, the verdict reads "(LOW POWER: k stops)"; low power never turns a failure into anything else.

**[M20]** Each level's verdict is always printed as "<verdict> (not a finding on its own; overall: <overall
verdict>)", so that one level's STOP HELPS cannot be quoted as the result. The overall verdict below is the only stop
verdict quoted anywhere else (the line after the headline, the README, notes to the owner).

**Overall, with no best level.** NOT TRIGGERED if every level is NOT TRIGGERED. Otherwise the least favourable
verdict among the levels that triggered, in the order NO EDGE < STOP DOES NOT HELP < INCONCLUSIVE < STOP HELPS. This
is an intersection over the levels, so no level is picked and no correction for three tries is needed. All three
levels are always reported.

**Counting.** The variant's runs are fixed before any result, and nothing is selected from them. Like the grid runs,
they join the strict count (30 runs, section 14) and never the effective count, the trial-Sharpe variance or PBO. Its
DSR is reported against the search studies' trials with the effective and the strict counts, as a description.
**[M15, M17]** R_0^φ, its shifts and placebo stops, N0^φ, X^φ and the Binance R_0^φ, shifts and N0^φ are comparators:
logged with their offsets, never counted.

**What it can and cannot change.** The variant's verdict is its own line after the headline (section 12). It never
changes the plain rule's verdict, the headline, θ_final, the settings, the check day or s. It never earns the
validate look by itself; if the plain rule earns it, θ_final(A) with each level runs at the look as a description
(section 13). STOP HELPS means only "worth carrying into the Nautilus build's pre-registration"; it is not evidence
for one level over another. **[M20]** Written now for that build: any Nautilus pre-registration that carries the
stop must gate it at every allowed s (here the S(s_k)^φ runs are descriptions only), and a stop level that users could
pick would be a second setting, so its grid would multiply (4 shares × 3 levels = 12 combinations, each gated).

**Descriptions** (reported in section 16; none decides), per level:
- every stop event: its date, f at the stop close, the fall from the high at the next close after the sale (how far
  past φ it went), each coin's state, the days locked, and each coin's return while locked (the regret);
- the deepest fall from the high, and the days at 100% USDC;
- the trade frequency (section 16);
- S^φ on Binance (folds 1-4, seed A's choices);
- the **fresh-customer** runs: the high and the locks restart at each fold's t0, as for a customer who starts that
  day (H0 otherwise gives every run a 2017 start). **[M20]** The book restarts too: USD 10,000 in USDC at close t0,
  which orders that close's in-force targets (the trend states computed from row 0, no lock), filled at the open of
  t0 + 1, as a new customer's first buy;
- S(s_k)^φ at every allowed s (section 8);
- its Monte Carlo p5 against the 35% budget (G6's statistic; not a gate for the variant);
- the number of stop events that differ between 1x and 2x (**[M20]** measuring the stop on the wallet's value after
  costs, found by re-running, stays as pinned; production sponsors gas, so a live wallet would not pay it, about 1e-5
  of a USD 10,000 book per leg).

## 12. Mechanical verdict and headline

**Verdict**, applied in this order:
1. **NO EDGE** if E1 or E2 fails. If P also fails, the headline reads "NO EDGE (LOW POWER: k switches)". Low power
   never turns a failure into anything else.
2. **INCONCLUSIVE** if E1 and E2 hold but P or any of E3-E8 fails, or a stop rule ends the study, or E9 fails at the
   look.
3. **EDGE** if E1-E8 and P hold, and E9 holds at the look. In words, wherever it is reported: "the trend rule's
   timing beat the same schedule shifted in time (by shifts that cannot see its own future) and beat holding the
   same mix always in, after costs, over
   2018-2022, also without BTC's best years and without any single year, and it cut falls more than holding the same
   average amount of crypto (SCOUTING)".

**Headline:**
- **CANDIDATE FOR AUDIT** if EDGE, G1-G8 all PASS where they are measured, and R1 holds. It means "worth a Nautilus
  build", never "ready for paper". **[M1, M2]** G8 is G8-excess, and in Branch R "where they are measured" includes
  the default, every grid step and every S(s_k) (section 8). **[M13]** Exactly: every point of the table "Where each
  gate and R1 is measured (Branch R)" in section 10, the S(s_k) check (with its E1 and E2) included; one failing or
  MISSING point is enough to fail.
- **EDGE, NOT A CANDIDATE** if EDGE and any gate fails or is MISSING, or R1 fails. The failing items are listed.
  ~~While the budget is TBD, G6 is MISSING, so this is the best this study can report. With G8 read literally, it is
  the best it can report even with a budget.~~ **[M1, M2]** With the 35% budget and G8-excess, CANDIDATE FOR AUDIT
  ~~can be reached.~~ **[M10]** can be reached only if G8-excess passes, which is unlikely by construction. G8-excess passes only
  if S's excess over N0 is ≥ 0 in bull, bear and sideways months alike (and the same at the default and at every grid
  step). It is expected to FAIL, so CANDIDATE FOR AUDIT is expected to be unreachable, and EDGE, NOT A CANDIDATE is
  the best headline this study is expected to be able to report (section 1; owner question 6). If G8-excess fails,
  the headline says so, and the gate is not redefined after the result. A narrowing that section 8's rule would allow
  is reported next to the headline, never applied here.
- Otherwise the verdict (**NO EDGE** or **INCONCLUSIVE**) is the headline.
- **[M4] The stop-loss variant's verdict** (section 11A), per level and overall, is reported on its own line right
  after the headline. It never changes the verdict, the headline, θ_final, the settings, the check day or s, and no
  stop level is chosen here. **[M20]** Each level's line carries "(not a finding on its own; overall: …)".
- **Descriptions never decide.** Nothing listed as a description (sections 9, 12 R2-R5, 16) can change the verdict,
  the headline, θ_final, the shipped settings, the check day or s. In particular:
  - a daily-check variant, another weekday, ~~s = 0.30 or 0.70,~~ Binance alone, folds 1-4 alone, a block-20 E2 or the
    B3-lead profile that looks better than S is reported as a description only (**[M1]** in Branch R the allowed
    values of s are gated, not described; **[M3, M6]** the trade-frequency tables, the active-row re-scoring and the
    DSR with K4 counted as 15 are descriptions too);
  - the daily-check variant cannot by itself meet the owner's "shown to pay" test for more frequent checks: that
    test needs its own pre-registration, which lists this study's trials as prior looks;
  - RESULTS.md opens with the mechanical verdict and headline, before any description.
- If an amendment run superseded an earlier run, RESULTS.md shows the superseded verdict and gate table next to the
  final one. **[M18]** An amendment run supersedes only under stop rule 18 ((a)-(c)); otherwise the verdict and the
  headline are the less favourable of the two runs' (NO EDGE < INCONCLUSIVE < EDGE; within EDGE, EDGE, NOT A CANDIDATE
  < CANDIDATE FOR AUDIT), and the stop-loss variant's overall verdict likewise. RESULTS.md lists every run's E1 rank p
  and E2 p side by side, whichever run is reported.

**Risk-officer conditions** (pre-registered; R1 enters the headline, R2-R5 are descriptions). Each is measured at S
and at θ_final(A) over the kept rows. **[M13]** R1 is measured at S, θ_final(A), the default and every grid step, and
holds only if it holds at each of them (section 10's table); R2-R5 are reported at the same points.
- **R1, "a few trades a month".**
  - Orders counted: every order filled in a kept row (switches and limit fixes; one order is one trip to a target
    vector, however many legs).
  - Holds if the mean is ≤ 2 orders per 30 days and no 30 consecutive days hold more than 5.
  - Switches occur only at check closes (at most 5 in any 30 days), so only limit fixes can break R1.
  - **[M3]** Owner decision 7: the hold-this-mix tool's limit (2 trades back to the mix in any 30 days) does not
    apply to this strategy. R1 is unchanged: it is the draft's reading of the owner's 2026-11-20 guardrail ("a few
    trades a month"), pre-registered before any result. **[M1]** In Branch R it is also measured at the default and
    every grid step. The stop-loss variant's R1 is reported as a description.
- **R2, limits.** Reported:
  - closes in breach (each fixed at the next open);
  - the highest single-coin weight and the lowest cash weight at any close;
  - **[M9]** the most crypto held at any close (both coins together), for S and for each allowed share;
  - the number of limit fixes.

  A target set refused during a run is a stop (stop rule 12).
- **R3, worst day and exit delay.** Reported:
  - the worst day and the 1st-percentile day;
  - the share of days in the market;
  - the longest delay from the first close below the lower band to the exit fill (at most 7 days plus one open, by
    design).
- **R4, small wallets** (descriptions only; the 4 sizes other than USD 10,000 are in the strict count, section 14;
  the orders are identical by construction). θ_final(A)
  rerun at books of USD 100, 500, 2,500, 10,000 and 50,000. Reported:
  - customer fees a year (pool + slippage, as a % of the wallet; gas excluded, since we sponsor it);
  - our gas cost a year in USD;
  - the Sharpe with gas charged;
  - the smallest of those books at which θ_final keeps ≥ 90% of its USD 10,000 Sharpe (a minimum-wallet proposal
    for the owner).
- **R5, all-cash concentration.** The share of days at 100% USDC and the longest such stretch. A USDC depeg is not
  modelled.

## 13. The single validate look

- **It runs only if E1-E8 and P all hold.** Otherwise the validate window stays unlooked for trend-steady.
- **Before it:** the train results are written, and `freeze.py` writes `results/trend-steady/FROZEN.json`.
  - `freeze.py` first recomputes the config hash and every per-file hash and compares them with the reported run's
    `summary.json` start fields. On any difference it exits without writing (the only exception is stop rule 10).
  - FROZEN.json holds: every hash; θ_final(A) and θ_final(B); the per-fold parameters; N, the seeds and the run
    number; the snapshot id and the train panel hashes; the limits and budget as read at train start; the branch;
    E1-E8, P, the verdict, the gates and the train Sharpes; the SHA-256 of `summary.json`; and the git state.
  - A byte-identical copy goes to `research/trend-steady/FROZEN.json`, committed with `trials.csv`,
    `evaluations.csv` and `RUNLOG.jsonl` before the look.
- **Start guard.** `run_validate.py` refuses if any of these holds:
  - the tree is dirty;
  - any hash differs from FROZEN.json;
  - FROZEN.json's numbers differ from `summary.json`'s;
  - `validate/STARTED` or `look.json` exists;
  - the tracked RUNLOG holds a look.

  Otherwise, **before loading any validate bar**, it appends its RUNLOG line and writes `validate/STARTED`. A crashed
  look counts as the look.
- **Consistency checks, before any validate number.**
  - The panels are `load_panel(..., last_close="2024-07-01")`. Their first 2190 (Kraken) and 1963 (Binance) rows
    must hash to the train panel hashes.
  - θ_final(A) and θ_final(B), re-run on the 2190 Kraken train rows, must reproduce their logged trial returns bit
    for bit.
  - If either check fails, stop: the look is spent and the verdict is INCONCLUSIVE.
- **What runs, once.**
  - θ_final(A) in H0 on Kraken rows 0-2736. t0 = row 2190 (close 2023-01-02, a Monday); the kept closes are
    2023-01-03 .. 2024-07-01 (546 returns).
  - Decisive (E9), from θ_final(A)'s book at close t0 (common start):
    - its N0;
    - its 25 guarded shifts (u = 53..77) over the 78 validate check closes (2023-01-02 .. 2024-06-24).
  - Descriptions only, which cannot change E9 or the verdict:
    - **[M4]** θ_final(A) with each stop level (3 runs; they cannot change the variant's verdict either);
    - **[M3]** the trade-frequency tables;
    - **[M1]** the default and every grid step (4 runs), each with its own N0 and shifts as θ_final(A) has;
    - θ_final(B);
    - 2x costs;
    - B1, B2 and X;
    - Binance;
    - the regime split and Monte Carlo;
    - R1-R5.
- **Expectation, written now.** Validate is a known bull market (K4). An always-in mix should do well and a trend rule
  mostly holds the mix, so E9 can reject (for example, heavy whipsaw around the 2023-24 pullbacks) but cannot
  confirm.
- **After it:** nothing is tuned or changed. Any change needs a new pre-registration.

## 14. Trial counting and logging

- **N_raw:** every trial Optuna recorded, in every state, in every study of every run, loaded through `load_trials`.
  Nothing is deleted. Expected 2400 with no rerun, at most 7200.
- **DSR and PBO:** `overfitting_report` unchanged, with `out_dir = results/trend-steady/train/`.
  - The effective count, the trial-Sharpe variance and PBO come from the search studies only.
  - **Active-row reading** (section 6; G3 and G4 take the stricter reading). For every search study, cut each
    completed trial's logged return series to its rows 204 .. end (Kraken row numbers; every search study starts
    at row 0). Then, exactly as `overfitting_report` does on the full rows: the trial Sharpes are
    `stats.sharpe` of each cut column; each study's effective count is `stats.effective_trials` of its cut
    matrix, summed over studies; each study's PBO is `stats.pbo(cut, n_blocks=10)`, averaged over studies;
    the active-row DSR is `stats.deflated_sharpe_ratio(S_A, active trial Sharpes, n_trials=active effective
    count)`. The raw-count and strict-count DSRs are reported in both readings. S_A itself is unchanged (its kept
    rows start in 2018 and hold no warmup).
  - Seed B gets the same report with S_B, against the same trial set, in both readings.
- ~~**Strict count (Branch F), reported but not gated: N_raw + 29.**~~ **[M1]** Branch F does not apply; its table is
  kept for the record.

  | Runs | Count |
  |---|---|
  | Plateau steps from the fold choices (4 per seed) | 8 |
  | Plateau steps from θ_final(A) (the fixed-settings rule) | 4 |
  | S at 2x, both seeds | 2 |
  | S on Binance (seed A) | 1 |
  | Check-day variants for E5 (6 weekdays, seed A) | 6 |
  | Daily-check variant (seed A; the owner's "shown to pay" question) | 1 |
  | Crypto share 0.30 and 0.70 (seed A; descriptions for the risk-officer) | 2 |
  | θ_final(A) at the R4 book sizes other than USD 10,000 (cost variants, like the 2x runs) | 4 |
  | K4's look at a moving-average distance | 1 |
  | **Total** | **29** |

  **[M1] Strict count (Branch R, this study), reported but not gated: N_raw + 49, plus [M4] 30 for the stop-loss
  variant = N_raw + 79:**
  - 12 plateau steps from the fold choices (3 parameters × 2 factors × 2 seeds) and 6 from the default;
  - 2 runs at 2x and 1 Binance run;
  - 6 check-day variants and 1 daily-check variant;
  - 8 grid runs (4 steps at 1x and 2x) and 8 S(s_k) runs;
  - 4 R4 book sizes;
  - 1 for K4;
  - **[M4]** the stop-loss variant, 10 runs per level, 30 in all: S^φ at 1x and 2x; seed B's S^φ at 1x and 2x; S^φ on
    Binance; the fresh-customer runs; S(s_k)^φ at the 4 allowed values (section 11A).

  **[M6]** The strict-count DSR is also reported with K4 counted as 15 instead of 1 (the dip model used 15 lab
  features; critique residual 3), i.e. N_raw + 93. A description.

  **Not counted** (logged separately, with their seeds or offsets): R_0 and the shifts, N0, X, B1, B2, B3-lead,
  N0-span, the opposite-start state paths, the A0 control panels and θ_final(A)'s in-sample run
  (a logged trial, re-run); **[M4]** R_0^φ, its shifts and N0^φ; **[M15, M17]** R_0^φ's placebo stops, X^φ, and the
  Binance R_0^φ, its shifts and N0^φ; **[M13]** each S(s_k)'s R_0(s_k), its shifts and N0(s_k); **[M21]** the 1000
  volatility-clustering panels of A0.
- **Config hash:** SHA-256 over the per-file SHA-256s of:
  - `research/trend-steady/PLAN.md` and the scripts;
  - `lab/runner/trend.py`, `portfolio.py`, `reference.py`, `interface.py` and `steady.py` (its helpers are reused);
  - `lab/data/panel.py` and `catalog.py`; `lab/config.py`;
  - **[M14]** `lab/data/external.py`, which sets the test-window cut every `load_panel` call is checked against
    (`holdout_cut`, `HoldoutWindowError`), as rebalance-steady's `frozen_paths()` has it; and every other `lab/` module
    the real-run path imports: `lab/__init__.py`, `lab/data/__init__.py`, `lab/runner/__init__.py`,
    `lab/data/futures.py`, `loaders.py` and `sources.py` (imported by `external.py` and `catalog.py`), and
    `lab/data/synthetic.py` (the projection guard's synthetic panel, stop rule 17). `lab/runner/holdmix.py` only if
    something on that path imports it (nothing is planned to). Checked on 2026-11-22 (no data read): importing
    `steady.py`, `portfolio.py` and `panel.py` loads exactly these modules but `synthetic.py`, plus modules of
    `lab/search` and `lab/validation`. A test checks that the hashed list holds every `lab/` module that
    `run_train.py`, `freeze.py` and `run_validate.py` have loaded once imported (section 17);
  - every `.py` file in `lab/search/` and `lab/validation/`;
  - `config/costs.yaml`, `splits.yaml` and `risk_levels.yaml` (today `0eeadeac…`, `a31ccc14…` and **[M1]**
    `d3f58253…`; `158d7c9f…` when the draft was written);
  - `pyproject.toml` and `uv.lock`;
  - the pinned values: s, f, h, the check day, R0 = 199, the start state, N, the seeds, the folds and the harness;
    **[M1]** the Branch R box and the allowed values of s in place of s; **[M4]** the stop levels and the stop's rules
    (the reference close, the lock, the order of priority); **[M7]** the two budgets of stop rule 17 and the run-count
    table of the projection.

  `RESULTS.md`, `RUNLOG.jsonl` and the FROZEN.json copy are not hashed (they change by design).
- **Recorded before any data is loaded.** `run_train.py` writes `summary.json` at start: git state, config hash,
  file hashes, the branch, and the limits and budget as read (**[M7]** and the timings and projection of stop rule
  17). It adds the panel hashes right after loading, before
  any backtest, and rewrites the file at the end with the start fields unchanged.
- **RUNLOG.** Every real run of `run_train.py` and `run_validate.py` first appends one line to the tracked
  `research/trend-steady/RUNLOG.jsonl`.
- **Files (git-ignored)** in `results/trend-steady/`:
  - `train/<study>/` for every study;
  - `train/run<k>/summary.json`, `trials.parquet`, `evaluations.parquet` (every run that is not a search trial) and
    `oos.parquet` (S_A, S_B, R_0, N0, X, B1, B2, N0-span, and the shift percentiles; **[M4]** S^φ, R_0^φ and N0^φ per
    level, with their shift percentiles; **[M15, M17]** X^φ and the placebo-stop percentiles per level; **[M13]** each
    S(s_k) with its R_0(s_k), N0(s_k) and shift percentiles);
  - `FROZEN.json`, `validate/STARTED`, `validate/look.json`.
- **Committed record:** `research/trend-steady/trials.csv`, `evaluations.csv`, `RUNLOG.jsonl`, the FROZEN.json copy,
  `validate.csv` after a look, and `RESULTS.md`.
- **MLflow:** none. It is not built, and the Nautilus/MLflow work is on hold; this is a logged deviation.
- **Synthetic dry runs** and the A0 controls go to scratch folders only, never into `results/trend-steady/` or the
  repo.

## 15. Protocol, stop rules and amendments

**Order of work.**
1. The owner answers `OWNER_QUESTIONS.md`. Defaults hold if unanswered, and that is logged. **[M8]** Done: Q1, Q2, Q4
   and Q5 answered on 2026-11-21; Q3 not asked, its default logged (header).
2. After hold-mix-cap's run is committed, `quant-researcher` writes `research/trend-steady/PLAN.md` from this draft.
   `backtest-auditor` and `risk-officer` review it, and it is committed with the branch line set. **[M8]** Written on
   2026-11-22 (this file), after hold-mix-cap's run and results were committed; the review and the commit are next.
   **[M22]** Reviewed on 2026-11-22 (amendments M9-M22) and committed. Before A0: the items of the header's next
   step 4 (owner question 6, if answered; `risk-officer`'s dated confirmation of the allowed values; the `risk-officer`
   review's reading in section 20).
3. Build `lab/runner/trend.py`, the scripts and their tests (section 17). The full tier with 100% branch coverage,
   the deep profile and ruff must pass.
4. Amendment A1 (throughput on the built adapter, synthetic) and amendment A0 (procedure controls, synthetic) are
   written into PLAN.md and committed. **[M1, M4, M7]** A1 is timed with the Branch R box; A0 includes the stop-loss
   variant; both run under stop rule 17's projection guard. **[M21]** A0 also holds the one-off size check of E1
   under volatility clustering (section 9), and A1 records the full tier's expected wall time (section 7).
5. Run 0, the train phase: both seeds, every comparator. Then RESULTS.md, the audit and the risk review.
6. The validate look, only if earned (section 13).

**Stop rules** (1-10 as rebalance-steady's, adapted):
1. No number counts unless the full tier (with coverage), the deep profile and ruff pass on the commit the run uses.
   Real runs refuse a dirty tree.
2. The bars hash, a panel hash or a row count differs from section 3: stop and amend.
3. The throughput rule allows fewer than 50 trials per study: stop and ask the owner.
4. A failed trial: finish the phase, then triage. A code bug gets a regression test that fails on the old code, a
   dated amendment row, and a full amendment run; the old trials stay and are counted. `freeze.py` refuses a run
   with failed trials unless it is given `--triaged "<note>"`.
5. The test-window guard fires: stop. Nothing from that run is used, and it is logged.
6. A crashed run is never resumed. It is rerun as an amendment run; its trials stay and are counted.
7. At most 2 amendment runs (k = 1, 2), each with its dated row committed first. A third need makes the verdict
   INCONCLUSIVE.
8. NO EDGE, or any of E3-E8 or P failing: no validate look.
9. A second look (including after a crashed look), or a bug found after the look that moves a validate number: the
   verdict is INCONCLUSIVE.
10. Any hash change between the train run and the look refuses the freeze. The one exception is a
    `risk_levels.yaml` change that leaves the Steady coins, `min_cash` and `max_coin` as read unchanged: it passes,
    a Deviations row is written, and G6 is never rescored.

**Added stop rules:**

11. **Branch guard.** `run_train.py` reads the branch line from the committed PLAN.md.
    - Branch R: it refuses unless the Steady budget read before any bar equals the owner-approved number quoted in
      the plan.
    - Branch F: it never builds a range, whatever the file says.
    - The branch can never change after run 0 starts.
    - **[M1]** The branch line reads R. Before any bar, `run_train.py` refuses unless `risk_limits("steady")` gives the
      budget 35 (0.35), `min_cash` 0.20, `max_coin` 0.60 and the coins BTC, ETH and USDC, as quoted in the header and
      section 4. A file SHA-256 other than the header's, with those same values, is recorded in the start record, not
      refused (the file also holds keys this study does not read).
12. **Feasibility before data.** Every target set the run can order passes `check_targets` with the limits as read
    and h before any bar is loaded: the 4 states; ~~the s = 0.30 and 0.70 descriptions;~~ in Branch R, every allowed
    value (**[M1]** and the plateau extremes s = 0.24 and 0.72; **[M4]** the stop's all-cash target is one of the 4
    states). A refusal of one of these during a run is a bug: stop and triage. X's targets come from S's weights, so
    they are checked when they are formed and clipped if needed (section 9); that is never a stop.
13. **Order invariance.** For each fold's S and for θ_final(A), **[M19]** and for the 1x and 2x pair of every grid
    step and of every S(s_k), the orders (closes, reasons and targets) must be
    identical at 1x, at 2x and at every R4 book size (an order hash). Otherwise stop: it is a bug. **[M4]** For the
    stop-loss variant, the trend states must be identical at 1x, at 2x and at every wallet size (a state hash), but
    its stop events may differ, because they read the wallet's value, which costs move. So every variant run's stop
    events are recomputed from its own `ret` (section 11A) and must equal the run's; otherwise stop: it is a bug.
14. **Common start.** R_0, every shift, N0 and X must hold S's book at close t0 bit for bit, and R_0 must equal S on
    fold 0's kept rows bit for bit. Otherwise stop: it is a harness bug. **[M4]** The same for R_0^φ, its shifts and
    N0^φ against S^φ. **[M13, M15, M17]** And for each S(s_k)'s R_0(s_k), shifts and N0(s_k) against S(s_k), for X^φ
    and the placebo stops against S^φ, and for the Binance series against Binance S (E8) and Binance S^φ (SL-E8).
15. **Procedure controls (A0).** 3 or more false positives in the 20 negative-control panels: stop before any real
    bar and triage (bug or design). A design change is a new draft. **[M4]** This holds for the plain rule and for the
    stop-loss variant at any level. **[M17]** It also holds for SL-T on its own, at any level. **[M21]** And for the
    one-off size check: more than 67 of its 1000 volatility-clustering panels passing E1 (section 9). A triage that
    finds no bug and no design fault goes to the owner in writing, and run 0 waits for his written decision; the
    controls are never rerun with other seeds.
16. ~~**hold-mix-cap ordering.** This plan is committed before anyone working on trend-steady reads hold-mix-cap's
    RESULTS.md. If that is not possible, the reading is logged in section 2 before run 0, and every change made after
    it is a named amendment.~~ **[M5] hold-mix-cap ordering, as it happened.** The first sentence could not be met:
    hold-mix-cap's RESULTS.md was committed on 2026-11-21 at 22:13 UTC and read by the lead before this plan was
    written. The fallback is applied: the readings are logged in section 2 (K10, the lead's; K11, this plan's
    author's), and every change to the draft after 2026-11-21 16:11 UTC is a named amendment in the table below,
    which says whether hold-mix-cap's results could have informed it. From now on, nobody who builds, runs or audits
    this study reads hold-mix-cap's RESULTS.md, AUDIT.md, RISK.md, `decision.json`, `runs.csv` or `falls.csv`, the
    hold-mix-cap numbers in `docs/app/features.md`, or `reports/director/2026-11-22-owner-answers-hold-mix.md`. Any
    further reader is logged in section 20 before run 0, with what was read. **[M22]** The briefs of this study's
    agents no longer repeat any summary of hold-mix-cap's results: each agent who gets one is another reader. The
    2026-11-22 reviews and the review revision are logged in section 20.
17. **[M7] Projection guard.** Before any bar is read, `run_train.py` refuses (exit 2, nothing written) if its
    re-timed projection of the run is above 60 CPU-minutes; before any panel is built, `controls.py` (A0) refuses
    above 120 CPU-minutes (section 7). Exactly the budget starts. A refusal goes to the owner; a budget is never
    raised to let a run start.
18. **[M18] Outcome-blind amendments.** An amendment run may supersede run k only if its bug was found in one of
    three ways: (a) a stop rule that fired during run k (4, 6, 12, 13 or 14); (b) a failing test in the committed
    suite; or (c) the post-run audit, which runs its full pre-registered check list (section 17's recompute tests)
    whatever run k's verdict is, and is recorded as having done so. If a bug is found any other way after run k's
    verdict is known, it is fixed, regression-tested and logged, and the corrected run is reported beside run k. The
    headline is then the less favourable of the two verdicts (NO EDGE < INCONCLUSIVE < EDGE; section 12). RESULTS.md
    lists every run's E1 rank p and E2 p side by side. The RUNLOG line of an amendment run records which of (a)-(c)
    found the bug, or "other, after the verdict". Why: each optional rerun redraws E1, E2 and the verdict, which no
    trial count adjusts for, so the decision to rerun must not depend on the verdict.

**Amendments.**
- Dated, written in the plan's amendment section and committed before the run they affect.
- A0 and A1 are planned (synthetic, before any real bar).
- An amendment run k needs a line starting `- **Amendment run k` with the date, the reason, how the bug was found
  (**[M18]** one of stop rule 18's (a)-(c), or "other, after the verdict") and the regression test.
- **[M5] Amendments M1-M8** (2026-11-22, to the draft as last written on 2026-11-21 at 16:11 UTC; before any
  trend-steady result). `quant-researcher` wrote all of them after reading K11 (section 2), so the last column says,
  for each, whether hold-mix-cap's results could have informed it.
- **[M22] Amendments M9-M22** (2026-11-22, after the `backtest-auditor` and `risk-officer` review of M1-M8 and before
  this plan's commit; before any trend-steady result). Written by `quant-researcher` (the review revision; its reading
  is logged in section 20). M9-M18 resolve the review's blocking findings; M19-M22 take the suggestions judged cheap and
  clearly right (the Review log at the end maps every finding to its amendment). The author's brief held the lead's
  one-sentence summary of hold-mix-cap's results (K10's words, no number), so the last column answers for each.

| # | What changed (where) | Why | Could hold-mix-cap's results have informed it? |
|---|---|---|---|
| M1 | **Branch R opened.** Header (branch line, budget, the file's SHA-256); section 0; section 4 (targets s/2, the limits as read, the signature); section 5 (s searched in 0.30-0.60: three free parameters); section 7 (A1 with the Branch R box; the branch in each study's context); section 8 (Branch F struck; Branch R binding; how the headline treats a narrowing; where s enters the comparators); section 13 (the default and the grid steps at the look, as descriptions); section 9 (the schedule carries each fold's s; N0 at s_i/2; calibration at s = 0.50); section 10 (gates for a range; G5 with s; G6 at 0.35; G7 at every step); sections 12 and 14; stop rules 11 and 12; section 17 (tests); section 18 (weaknesses 11 and 21); section 19; appendix B (the feasibility rerun against the file as it reads now: every target set passes) | Owner decision 1 (2026-11-21) and the draft's own section 8, which said what Branch R must do | **No** for every value it fixes. The budget (35%), the allowed values {0.30, 0.40, 0.50, 0.60} and the box 0.30-0.60 were fixed by 16:31 UTC on 2026-11-21, before hold-mix-cap's run 0 started (19:32 UTC). The budget's file edit (22:53 UTC) came after those results only because the owner's 16:31 record said to wait for that run, and it carries the 16:31 number. The rest is the draft's section 8 applied. Two small choices are new: the shifted schedule's target vector carries its fold's s (so a shift keeps the exposure), and this study reports a narrowing but never applies it. Neither uses a hold-mix-cap number |
| M2 | **G8-excess is the gate** (sections 1, 10 and 12) | Owner decision 2 (2026-11-21) | **No.** Decided at 16:31 UTC on 2026-11-21, and pinned in the draft at 16:11 |
| M3 | **Owner decisions 3, 4 and 7 recorded**: header; section 4 (readings; production notes: sells to cash go through a pause, the auto-trading caps); section 12 (R1 kept; the tool's limit does not apply); section 13; section 16 (trade frequency: switches and fills per 30 days, median and worst, per fold and overall); section 19 (Q3 not asked, default logged) | Owner decisions 3 and 4 (2026-11-21) and 7 (2026-11-22) | Decisions 3 and 4: **no** (16:31 UTC on 2026-11-21). Decision 7 was made after the owner saw hold-mix-cap's results, but it concerns that tool and removes nothing this draft ever had. The trade-frequency tables are descriptions and decide nothing |
| M4 | **The stop-loss variant**: new section 11A (the wallet reading; the high since the last stop; a stop event with or without coins; the lock until a fresh up-turn; how events are found; three fixed levels; SL-E1 to SL-P; the verdict per level and overall; **[M15, M17]** extended by the review: X^φ and SL-E3, SL-E8 on Binance, and SL-T, each with its section 17 tests); header; sections 0, 1, 4, 8, 9 (A0), 12, 13, 14 (+30 counted runs), 15 (stop rules 13-15), 16, 17 (code and tests), 18 (weaknesses 14-20) and 19 | Owner decision 6 (2026-11-21) | **Partly.** The three levels and "fall from the top, buy back when the trend turns up" are the owner's, fixed before 16:00 UTC on 2026-11-21. Every other choice was written on 2026-11-22 by an author who had read K11, which quotes how far held mixes fell by crypto share; that could in principle inform how deep falls get and how often a stop would fire. Each choice follows the owner's words or reuses the draft's machinery (E1, E2, E4-E7, the lead guard, H0, the one executor), with its reason written next to it. None uses a hold-mix-cap number, none selects among the three levels, and the verdict is an intersection over them |
| M5 | **Stop rule 16 replaced**; section 2 (K5 and K6 updated; K10, K11 and K12 added; "Counted honestly"); this list and table; section 20; header | The draft's ordering could not be met: hold-mix-cap's results were committed and read first | It is the record of those readings |
| M6 | **Critique residuals 3 and 4 partly closed** with descriptions (the DSR with K4 counted as 15; the active-row re-scoring of every study); the other residuals listed as weaknesses (section 18 and the Critique log's status note) | Cheap to close before results | **No.** Descriptions only, they decide nothing, and both come from the draft's own critique log (2026-11-21) |
| M7 | **Time budget and projection guards** (section 7; the start record in section 14; stop rule 17; section 17) | To pin the run's cost before any run, as hold-mix-cap's projection guard did | **No.** From the draft's synthetic timings (appendix B) |
| M8 | **Header, status, next steps and order of work**; the owner answers quoted | Moving from a draft to a plan | **No** |
| M9 | **Order sizes and the crypto share's wording** (blocking): the plain words (the share is bought at entry; prices can push crypto to about 80% of the wallet, 60% in one coin, before it is traded back; the limits are checked at every daily close and a breach is traded back at the next open); section 4 (Between orders; the app wording; the production notes: an order that moves a coin to cash can sell every coin held, up to about 80% of the wallet, more after a gap day; a switch into both coins buys up to s; at most one order a day; the coin list locked to cbBTC, ETH and USDC); section 12 (R2: the most crypto at any close, per allowed share); weaknesses 7 and 12; section 19 (Q7); appendix A (the app wording never said "at entry") | The draft's 30% figure was only the size of a buy at entry, and "holds 25%" and "the limits hold at every close" overstated how tightly risk is held. The figures come by hand from the limits as read (appendix B, `feas_r2.py`) | **No.** Arithmetic on the limits as read; no hold-mix-cap number |
| M10 | **G8-excess is expected to fail by construction** (blocking): header (owner decision 2's note; the SCOUTING box; the questions' status), section 1 (the expectation, its algebra, the synthetic checks as indicative only), section 10 (G8 row), section 12 (headline), weakness 11, section 17 (a test), section 19 (Q6, put to the owner in writing on 2026-11-22; no answer at this commit) | With three regimes, "none above half the total excess" forces none below zero; a long-or-cash rule usually trails the held mix in bull months, and otherwise its bear months usually hold more than half the excess. The owner chose G8-excess on 2026-11-21 after being told that only the literal G8 would fail. The gate is not changed; another rule can only be the owner's own, recorded before any result | **No.** Algebra and synthetic panels; the check concerns S against N0, which hold-mix-cap does not measure |
| M11 | **One order rule for every executor; re-cuts** (blocking): section 4 (Orders), section 9 (R_0), section 11A (R_0^φ's entry: the trend part from the check close in force, as in R_0, and the locks from the fold whose test rows hold the close, so that R_0^φ is R_0 when nothing is locked), section 17 (`run_states` takes a per-row target vector; the re-cut test; the identities) | Whether a change of s between folds orders anything was undefined, and it moves E1, E7, E8, the R_0 − S difference and the trade counts. Found while writing this amendment: R_0^φ took each close from the fold holding it, so with no stop it differed from R_0 on the 1-4 closes between each fold's t0 and its first check close | **No.** A definition, fixed before any result |
| M12 | **E5(a) compares the seeds on the gates measured at S only** (blocking): sections 10 and 11 (E5), section 17 (a boundary test) | Seed B has no default, grid or S(s_k) runs, so "G1-G8" had two readings that could turn EDGE into INCONCLUSIVE | **No** |
| M13 | **Where each gate and R1 is measured in Branch R** (blocking), and E1 and E2 at every S(s_k) (a suggestion): section 10 (the table; θ_final(A) is an R1 point, not a G7 or G8 point), sections 8 and 12, section 14 (their comparators not counted), section 17 (tests) | The [M1] text could be read as adding to θ_final(A) or as replacing it. AGENTS.md "Settings ranges" and the draft's own Branch R list (section 8) name the default and every grid step for G7 and G8, and θ_final(A)'s unrounded s is not a value a user can pick; R1 keeps θ_final(A), as the draft had it. E1 and E2 at each S(s_k) apply the owner's "every value must pass every check" to the research criteria; they only add conditions | **No** |
| M14 | **The config hash covers `lab/data/external.py`** and every other `lab/` module the real-run path imports (blocking): section 14, section 17 (tests) | `external.py` sets the test-window cut that every `load_panel` call is checked against, and a change to it did not move the hash | **No** |
| M15 | **The stop variant's exposure control and second source** (blocking): X^φ and SL-E3; SL-E8 on Binance; verdict steps 3 and 4; SL-E5 and SL-E7; the plain words list exactly the variant's checks; sections 9 (A0), 11A, 14, 17; weakness 14 | A stop adds all-cash time, so a shallower fall than S's is nearly free, and "the same luck checks" was not true | **No.** Built like the plain rule's X and E8 |
| M16 | **E1, and every test applied "as E1", decided on the rank p** (blocking): E1 holds iff (1 + #{shifts at or above R_0}) / 208 < 0.05 (at most 9 of 207), E8 at most 6 of 155, and E7, SL-E1, SL-E7, SL-E8, SL-T, the slow calibration and A0 on their own counts; `e1_rank`'s `holds` (p95) is a description; sections 9, 11, 11A, 17; appendix B (the draft audit's shift-null check rerun under both rules) | Under exchangeability the p95 rule's size is about 5.5% (5.6% for E8), and it could print "holds" next to p = 0.058; the rank rule's size is 4.8% (4.5%), so "each at 5%" is true | **No** |
| M17 | **SL-T, the stop's own timing against placebo stops** (blocking): section 11A (the placebos: the locks moved by the 207 guarded weekly-segment shifts, the trend part kept; SL-T in verdict step 3, SL-E5 and SL-E7), section 9 (A0 reports SL-T's false positives; 3 or more is stop rule 15), sections 14 and 15, section 17 (tests), weakness 22 | SL-B compared point estimates, with no luck control on what the stop itself adds; in the review's synthetic check placebo stops passed it often. The review's other suggestion (re-deriving locks at the moved dates) was not taken: the blocking form is simpler and needs no re-decided stop | **No** |
| M18 | **Stop rule 18, outcome-blind amendments** (blocking): section 15 (the rule; the amendment line records its trigger), section 12 (the less favourable verdict), section 17 (a test) | An amendment run could be started because of a disappointing verdict, which redraws E1, E2 and the verdict without any count adjusting for it | **No** |
| M19 | **The range, pinned further** (suggestions): section 8 (the default's tie within 1e-12 goes to the lower value; the riskiest end and step by G6's statistic; a narrowing needs the deepest p5 at 0.30 or 0.60, drops one value at a time and reruns the range gates, never drops a value whose Sharpe failed, and cannot fix a non-risk failure or S; paper's riskiest step), section 10 (G6's exact statistic at every point; G6 from the recorded budget), stop rule 13 (the order hash at every grid step and S(s_k)), section 16 (every step's falls, with margins and dates), section 17 (tests), weakness 21 | So that none of these can be chosen after results | **No** |
| M20 | **Criteria and the variant, tightened or clarified** (suggestions): E7 also requires E3 and E4, and SL-E7 SL-E3 and SL-E4 (the owner's boom rule covers every comparator); the per-fold s in E5(b), E8, the daily-check variant and the opposite-start check; notes on what EDGE rests on and on E7's bootstrap; P as an information floor, with distinct switch weeks and out-spells described; R_0's rank among the lag offsets; the per-level stop labels; the fresh-customer book; the stop's Nautilus note and its gas; the crash-day scale in the plain words; E2's boundary tests at 499 and 500 resamples | Cheap; each only adds a condition or pins a reading | **No.** The crash-day scale uses K2's BTC figure, already in this plan |
| M21 | **Procedure controls** (suggestions): A0 reports E1's and SL-E1's own false-positive counts; the one-off size check of E1 under volatility clustering (1000 panels, at most 67); the expected power alarm and the owner's question; the SL-P expectation; the full tier's time measured in A1; the time budget (sections 1, 7, 9, 15, 17) | On shuffled markets E2 almost never holds, which hides a leaky E1; the slow test cannot see a 7.5% size | **No.** Synthetic only |
| M22 | **Records**: header (status, next steps, the file hash at `52d7ee1`), section 2 (K11's TESTING.md line corrected; the reviews' briefs counted), section 4 (the draft's file hash struck), section 8 (`risk-officer`'s confirmation still to be recorded), stop rule 16 (briefs stop repeating the summary), section 20 (the reviews and this revision), appendix B (24 target sets, not 33; the reruns), the Review log (the review's findings mapped to the amendments), README | Stop rule 16 and the review asked for them | It is the record of those readings |

**Deviations.** Every departure from the plan goes into a Deviations table in RESULTS.md: what changed, why, when
relative to which result, and its effect on any number.

**Not done in this study:**
- reading the test window;
- Nautilus, `lab/costs/`, MLflow, `strategies/`, `reports/<strategy>/` or `exports/`;
- hourly bars, intraday fills, other coins, leverage or shorting;
- USDC yield or depeg;
- volatility scaling, BTC/ETH rotation, crossovers, Donchian channels or ensembles (each would be its own
  pre-registration);
- tuning on validate, or a second look;
- **[M4]** a per-coin stop, a profit give-back stop, or choosing one stop level;
- **[M3]** modelling a loss-limit pause or Approve mode;
- edits to `config/*.yaml`, `lab/search`, `lab/validation` or the gates;
- setting, proposing or justifying a drawdown budget from this study's numbers.

## 16. Outputs

**RESULTS.md, whatever the verdict.** Both seeds, every number labelled SCOUTING with placeholder costs.
- **The verdict and headline,** with E1-E9, P, the gate table and R1-R5. **[M1]** The gate table covers S, the default,
  every grid step and every S(s_k), with section 8's narrowing line. **[M4]** Then the stop-loss variant's verdict per
  level and overall, with SL-E1 to SL-P. **[M19]** For every grid step and every S(s_k), next to S: the historical
  max drawdown with its peak and trough dates, and G6's statistic, each with its margin to −budget, so that the
  export and the app's "worst fall for the chosen settings" have both numbers for every allowed value, and a later,
  tighter budget can be read off without rescoring (stop rule 10 never rescores G6). **[M18]** If more than one run
  exists, every run's E1 rank p and E2 p side by side.
- **Per fold:**
  - the chosen L and δ (**[M20]** and s), the neighbourhood and the raw best;
  - IS and OOS Sharpe, and walk-forward efficiency;
  - switches per coin, limit fixes, orders and the most orders in any 30 days;
  - time in the market per coin;
  - turnover, costs paid, return, max drawdown and worst day;
  - the number of −10 trials;
  - **[M3]** the trade frequency (below).
- **Stitched:** S, R_0, N0, X, B1, B2 and N0-span. The shifts as 5/50/95 percentiles with R_0's rank p. S at 2x and
  on Binance. Folds 1-4 on their own, comparable row for row with rebalance-steady.
- **The R_0 − S difference:** the turnover S's stitched curve never paid at the 4 fold boundaries.
- **[M3] Trade frequency** (owner decision 7: reported, not capped). For S, θ_final(A), the default, every grid step
  and S^φ: at every kept close t, the number of (a) **state switches** (changes of a coin's in-force state, each coin
  counted) and (b) **fills** (rows with turnover > 0: switches, limit fixes and stops) whose fill rows fall in the 30
  calendar days ending at t (closes in (t − 30 days, t]). Reported: the median and the worst over the kept closes, per
  fold (that fold's kept closes) and overall, and legs per 30 days the same way. R1 stays the pre-registered
  condition; this table decides nothing.
- **[M4] The stop-loss variant** (section 11A): per level, its verdict line, its criteria and every description listed
  there; the overall outcome.
- **The boom-year and leave-one-year-out tables:** E1, E2, Δ_y, G7 and the plateau with each bar-year removed, and
  with the best and the two best BTC years removed (**[M20]** and E3 and E4 with the best and the two best removed,
  as E7 now requires; the row below is shown next to E7).
- **The two bear years together** (description, reported whatever it shows): Δ, D and E1's rank p with both 2018
  and 2022 removed, i.e. what the timing did in 2019-2021 alone. E6 survives losing either bear year; this row
  shows how much of the edge, if any, lives in the two of them.
- **An episode table:**
  - each out-spell per coin, with the coin's return while S was out (the loss avoided);
  - whipsaws (switches reversed within 4 weeks), with their count, share and cost;
  - the regret against N0 in each rally.
- **DSR** with the effective, raw and strict counts.
- **PBO** per study, with the distribution of each study's PBO logits (5/50/95 percentiles and the share ≤ 0).
- **Monte Carlo** (descriptions next to G6's statistic):
  - the block bootstrap at mean blocks 20 and 60;
  - a trade-period shuffle;
  - degraded execution (+10 bps per unit of turnover, 1000 simulations, seed 0).
- **Trades per parameter:** kept fill rows / 2, flagged below 30 (expected to be flagged).
- **Descriptions:**
  - the daily-check variant (did checking more often pay?; **[M20]** seed A's per-fold L, δ and s);
  - ~~s = 0.30 and 0.70;~~ (**[M1]** replaced by the gated grid)
  - **[M6]** the active-row re-scoring (critique residual 4): every logged trial of every search study re-scored with
    the objective's formula on its rows 204 .. end only (4 blocks over those rows, the same penalty, its logged trade
    count for `min_trades`), and `stable_region` re-run on those scores. Reported: whether each study's choice would
    move, and how far in each parameter's unit distance. No new backtest, and the choice never changes;
  - **[M6]** the strict-count DSR with K4 counted as 15 (section 14);
  - the six other check weekdays;
  - B3-lead (the 52 excluded lead offsets, as a lead/lag profile, never a null);
  - the block-20 E2;
  - the opposite-start check (the first close from which the two state paths agree, for every chosen
    configuration, **[M20]** i.e. each fold's L, δ and s; whether they still differ at any fold's t0);
  - **[M20]** next to P: the number of distinct switch weeks and of completed out-spells per coin;
  - **[M20]** R_0's rank among the 52 lag offsets (u = 208..259), next to B3-lead, as the other half of the lead/lag
    profile;
  - **[M15, M17]** for the stop-loss variant: X^φ, the placebo stops' 5/50/95 percentiles with R_0^φ's rank p, and
    the Binance series of SL-E8.
- **Risk descriptions:**
  - R2-R5;
  - θ_final(A) over all of train, labelled **IN-SAMPLE**: max drawdown, Monte Carlo p5 and p50, worst day,
    highest coin and lowest cash weight, legs a year and leg sizes in USD;
  - one sentence that the stitched S mixes per-fold configurations, so its drawdown is not that of any one shippable
    configuration.
- **Correlations** of S's daily returns with B1, B2, N0, and rebalance-steady's stored stitched S_A (train only).
- **Every failure.**

**Files:** as in section 14.

## 17. Code to build, and its tests

Built by `quant-researcher`. Everything is tested before any number counts (hard rule 11): 100% branch coverage of
`lab/`, the deep profile, and ruff.

**`lab/runner/trend.py`** (new; about 300-400 lines):
- `SPECS`, `HEADROOM = 0.02`, `R0 = 199`, `S_SHARE = 0.50`; **[M1]** `SPECS` holds the three parameters of section 5,
  `ALLOWED_S = (0.30, 0.40, 0.50, 0.60)`, and `S_SHARE` remains only as the calibration test's s; **[M4]**
  `STOP_LEVELS = (0.20, 0.30, 0.40)`; **[M7]** the budgets of stop rule 17 (60 and 120 CPU-minutes);
- `sma_distance(close, L)`, computed per window;
- `check_closes(index, weekday, start_row)`;
- `trend_states(bars, L, delta, *, weekday=0, start="out")`: point-in-time state arrays per coin;
- ~~`run_states(bars, states, *, s, f, limits, costs)`~~ **[M11]** `run_states(bars, targets, *, limits, costs,
  states=None, locks=None)`: the **one executor**, through `portfolio._simulate`. `targets` is a per-row array of target
  vectors (the vector in force decided at each close, point in time), and it orders at a close where the vector
  differs from the previous close's (exact float comparison; before row 0 the book is all USDC) or at a limit breach
  (the vector in force). Every executor uses it: S's fold runs, θ_final, the grid steps, S(s_k), N0, X, R_0 and its
  shifts, B3-lead, the Binance series, and the stop variant's runs, R_0^φ, its shifts and placebos. `states` and
  `locks` only label each order's reason (switch, re-cut, limit fix, stop) and the switch counts; they never decide.
  It records the reasons and the order hash in `attrs`;
- `trend_backtest(params, bars, *, limits, costs, ...)`: the `BacktestFn`, bound with `functools.partial`;
- `stitched_schedule(...)`;
- `shifted(schedule, u)`;
- `run_span(...)` (R_0 and the shifts);
- `always_in_n0`, `exposure_x`;
- `plateau_steps`;
- `power_count`;
- `loyo` and `boom_years`;
- `rolling_order_count` (R1);
- `active_report(studies, out_dir, first_row=204)`: the active-row trial Sharpes, effective counts, PBOs and DSRs
  (section 14). With `first_row=0` it must equal `overfitting_report`'s numbers bit for bit (tested);
- **[M4]** `in_force` (the in-force targets from the trend states and the locks), `stop_events` (the re-running of
  section 11A, returning the result and its events), `recompute_stop_events` (stop rule 13's check from a run's own
  `ret`), `segment_shift` (the weekly-segment shift), `stop_verdict` and `overall_stop_outcome`;
- **[M3]** `trade_frequency`;
- **[M7]** `project_cpu_minutes` (the run-count table and the projection);
- **[M15, M17]** `exposure_x` also builds X^φ; `placebo_stops` (the lock series moved by `segment_shift`, the trend
  part kept);
- **[M16]** `rank_holds(rank_p)` (p < 0.05), the one decision rule of E1, E7's E1, E8, SL-E1, SL-E7, SL-E8, SL-T, the
  slow calibration and A0, fed with `steady.e1_rank(...)["rank_p"]`;
- **[M10, M13]** `g8_excess_pass` and `headline`, which reads every measurement point of section 10's table;
- **[M19]** `default_share` (the tie within 1e-12 to the lower value), `riskiest_step` and `narrowing`;
- **[M18]** `reported_verdict` (stop rule 18's less favourable verdict).

It reuses `steady.panel_hash`, `fold_window`, `kept_returns`, `buy_and_hold_b1`, `fifty_fifty_b2`, `regime_table`,
`regime_split`, `e1_rank`, `paired_bootstrap` (with `mean_block`), `report_trial_sharpes`, `study_pbo` and
`stable_neighbours` unchanged. `lab/search` and `lab/validation` run unchanged.

**`research/trend-steady/`:** `study.py`, `run_train.py`, `freeze.py`, `run_validate.py`, `controls.py` (A0) and
`throughput.py` (A1). They carry rebalance-steady's guards as they now stand:
- dirty-tree refusal and the pinned folders;
- the start record and RUNLOG before any bar;
- the config hash (**[M14]** `study.py`'s hashed-file list is exactly section 14's, `lab/data/external.py` included);
- the amendment rules;
- look-once;
- FROZEN.json checked against `summary.json`;
- dry runs that never write into the repo.

Plus the branch guard and stop rules 12-16 (**[M1]** the Branch R guard of stop rule 11; **[M7]** and the projection
guard of stop rule 17).

**Tests** (TESTING.md section 7):
- **Tamper the future.** On `sma_distance`, `trend_states`, the targets and `trend_backtest`'s returns: every field
  of both assets from the cut on, except the fill open. Hypothesis, with `@example` cuts at R0 and at a check close.
- **Touch the present.** Lowering close t changes SMA and m at t; at a check close it can flip the state at t, never
  at t − 1.
- **Hand-built paths** (`make_panel` of `make_bars` paths):
  - exact switch closes across +δ and −δ (strict at exactly representable boundaries);
  - the Monday anchor and a missing Monday;
  - activation at row 199 and at max(199, L − 1) for L > 200;
  - start out;
  - one coin switching re-cuts the other;
  - a breach between checks fixed at the next open;
  - a switch and a breach on the same close giving one order;
  - the 2-day row of 2018-01-13 on a rebuilt grid;
  - **[M11]** two folds with s 0.30 and 0.60 and the states unchanged across the boundary (a coin in) give exactly
    one re-cut order, at the new fold's first check close, in R_0 and in R_0^φ; with both coins out, none; the re-cut
    counts as an order and a fill, and not as a switch for P or the switch counts.
- **Known answers:** SMA and m by hand; R1's rolling count by hand.
- **Identities:**
  - always-in states equal `portfolio.rebalance` with band 1.0, every 1, the limits and h, bit for bit;
  - shift 0 equals R_0;
  - R_0 equals S on fold 0's kept rows;
  - H0 equals `walk_forward_optimize(warmup=2190)`'s `oos_returns` bit for bit (`n_workers = 1`, a few trials);
  - nulls equal S's book at t0;
  - orders are equal at 1x, 2x and every book size;
  - **[M11]** `run_states` fed one run's (s/2)·z targets equals that run's own order rule (rule (1) of section 4) bit
    for bit, and R_0^φ with every lock 0 and S's fold-0 book equals R_0 bit for bit.
- **Live/batch parity:** a streaming state machine fed one bar at a time equals `trend_states` on every bar.
- **Shift invariants** (hypothesis):
  - a shifted schedule keeps the count of each state pair and the multiset of spell lengths, up to the splice;
  - it never reads a price (tampering prices leaves the schedule unchanged);
  - its offsets are exactly u = G + 1 .. W − 1 with G = 52 (207, 155 and 25 offsets for W = 260, 208 and 78), and a
    span with W ≤ G + 1 raises;
  - no lead offset u = 1..52 ever enters E1, E7, E8 or E9 (see the oracle test).
- **Thresholds at their boundaries:**
  - E1 ties count against S;
  - **[M16]** with 207 shifts, 9 at or above R_0 holds and 10 fails; with 155 (E8, SL-E8), 6 holds and 7 fails; the
    same rule for E7's E1, SL-E1, SL-E7, SL-T, the slow calibration and A0; a case where `e1_rank`'s `holds` (p95) is
    true and p = 12/208 shows E1 failing;
  - ~~the E2 p at exactly 0.05 fails;~~ **[M20]** E2 at 10,000 resamples: 499 resamples with D* ≤ 0 hold (p =
    500/10,001) and 500 fail (p cannot equal exactly 0.05 there); "exactly 0.05 fails" with a small resample count:
    19 resamples and no D* ≤ 0 give p = 1/20, which fails, and 20 give 1/21, which holds;
  - Δ − Δ_y = 0 fails;
  - 19 switches fail P and 20 hold;
  - a 0.7× weekday step holds, and E5(b) fails whenever Sharpe(S) ≤ 0;
  - E7's year ranking with ties.
- **Calibration (slow):** the E1 false-positive rate on iid driftful panels at (50, 0.02) and (200, 0.10), at most
  18 of 200 each (section 9), **[M16]** with E1's rank-p rule. **[M21]** The one-off volatility-clustering check of A0
  (at most 67 of 1000) runs in `controls.py`, not in the slow tier, with its generator pinned by a test (the first
  innovations and closes of panel j = 0 by hand).
- **Oracle:** on a pinned synthetic panel, a schedule that is in a coin exactly when that coin's next check-to-check
  return (open after the check to open after the next) is positive ranks above every guarded shift (rank p =
  1/208) and E1 holds; replacing the series of any lead offset u = 1..52 with arbitrary values changes no E1, E7,
  E8 or E9 number.
- **Active-row report:** `active_report` equals `overfitting_report` bit for bit with `first_row=0`; on a small hand
  matrix with shared zero rows its DSR, effective count and PBO equal a hand computation on the cut rows; G3 and
  G4 fail when either reading fails.
- **X clipping:** ē outside the limits is scaled by the largest passing λ (by hand), marked "clipped", never a stop.
- **Recompute tests:** every reported number in `summary.json` and `look.json` rebuilt from its inputs.
- **Guards:** every guard, including the branch guard and stop rules 12-16.
- **Hand breaks:** each deliberate break of `trend.py` and of the scripts fails a test, as in bugs #43-#47.
- **[M4] The stop-loss variant:**
  - **tamper the future** on the stop events, the locks and the buy-backs (hypothesis): every field of both assets
    from the cut on is changed except the fill open, and every event, lock and order decided before the cut stays the
    same;
  - **hand-built paths:** a fall of exactly φ fires (an exactly representable path, e.g. V from 1 to 0.5 at φ = 0.5)
    and one ulp less does not; the high restarts after a stop and not after a trend exit; a trend exit whose own fill
    takes the wallet past φ is an event with no order (no buy-and-sell the next day); a coin in at the stop stays out
    until it turns out and then in; a coin out at the stop comes back at its next up-turn, on the same close as the
    plain rule; an up-turn on the stop close does not unlock; a stop beats a switch and a limit fix on the same close;
    a stop at the last close is never filled; one order per close;
  - **identities:** a level that never fires (on a path that never falls that far) equals the plain rule bit for bit;
    the re-running equals an independent one-pass computation in the test (a book of coin units and cash, as
    `test_portfolio.unit_book`) on drawn paths (hypothesis); each run's events equal `recompute_stop_events` on its
    own `ret`; `segment_shift` of a plain-rule schedule equals B3's check-close shift for every u; R_0^φ equals S^φ on
    fold 0's kept rows, and every null holds S^φ's book at t0; the trend states are equal at 1x, 2x and every wallet
    size;
  - **thresholds at their boundaries:** SL-P at 2 and 3 stops, and at 1 and 2 bar-years; SL-B (i) and (ii) hold on
    equal Sharpes, (iii) and (iv) fail on equal drawdowns; NOT TRIGGERED exactly when the kept returns are equal bit
    for bit; the overall order of outcomes; a changed variant verdict never moves the plain rule's verdict, headline or
    θ_final;
  - **[M15]** X^φ from S^φ's weights and book at t0 by hand (and clipped as X); SL-E3 fails on equal drawdowns (both
    the historical and the Monte Carlo one); SL-E8 on a Binance-style panel with a later start (its 155 shifts);
    verdict steps 3 and 4 with SL-E3, SL-T and SL-E8 each failing alone; SL-E5 and SL-E7 read SL-E3 and SL-T;
  - **[M17]** placebo stops: u = 0 reproduces R_0^φ bit for bit; a placebo never re-decides a stop (no stop search
    runs for it, and changing the wallet's path leaves its locks unchanged); the shifted locks keep their count and
    lengths up to the splice and never read a price; an oracle panel where a lock placed exactly on a coin's falls
    ranks first (p = 1/208) and SL-T holds; A0 counts SL-T's false positives on its own;
  - **[M20]** each level's verdict line carries "(not a finding on its own; overall: …)"; the fresh-customer runs
    start from USD 10,000 in USDC at t0 and buy that close's in-force targets.
- **[M1] Branch R:** the box and every plateau step pass `check_targets` with the limits as read (hypothesis); the
  default is the allowed value nearest θ_final(A)'s s, ties to the lower; the branch guard refuses a budget other than
  35, other `min_cash`, `max_coin` or coins (files in `tmp_path`), and records but accepts another file hash with the
  same values; the shifted schedule carries each fold's s; G8-excess, not the literal G8, enters the headline.
- **[M10] G8-excess:** it FAILs on every hand-built table where `excess_total` > 0 and one regime's excess is below 0
  (hypothesis over the three excesses, with `@example`s where the negative regime is bull, bear and sideways in turn),
  and passes exactly when `excess_total` > 0 and every regime's excess lies in [0, `excess_total` / 2] (both ends
  hand-built and exactly representable).
- **[M12] E5(a):** a failure at a grid step only (or at the default's plateau, or at an S(s_k)) leaves E5 unchanged;
  a failure of G6 at S_B alone fails E5.
- **[M13] Measurement points:** for every point of section 10's table, a hand-made gate table in which only that
  point fails (or is MISSING) moves the headline from CANDIDATE FOR AUDIT to EDGE, NOT A CANDIDATE and names that
  point; a failure at a point not listed (θ_final(A) for G7 or G8, seed B's numbers) does not move it; E1 or E2
  failing at one S(s_k) fails the range.
- **[M14] Config hash:** `lab/data/external.py` and the other modules of section 14 are hashed, and a change to
  `external.py` (or to any of them) moves the config hash; the hashed list holds every `lab/` module in `sys.modules`
  after `run_train.py`, `freeze.py` and `run_validate.py` are imported (a new import cannot escape it).
- **[M18] Stop rule 18:** an amendment run whose recorded trigger is "other, after the verdict" reports the less
  favourable verdict and headline of the two runs (each order of the two, and for the stop variant's overall
  verdict), and lists both runs' E1 rank p and E2 p; triggers (a), (b) and (c) supersede; a RUNLOG amendment line
  without a trigger is refused.
- **[M19] The range:** the default's tie within 1e-12 goes to the lower value (0.35 as Optuna's float, and 0.35 ± 1e-13);
  G6 follows the budget recorded in the start record, not 0.35 (records with 0.30 and 0.40 move G6's outcome on a
  hand-made p5 of −0.33); G6's statistic at a grid step equals `overfitting_report`'s on the same series; the riskiest
  step and end by hand (ties to the higher s); narrowing: dropped one value at a time from the end with the deepest
  p5 and rerun, "not possible" when the deepest p5 is at 0.40 or 0.50, "fails" on any non-risk failure, on a G6
  failure at S and when it would drop the default; the order hash at every grid step and S(s_k).
- **[M3] Trade frequency** by hand on a hand-built fill log (both ends of the 30-day window, a missing close).
- **[M7] Projection guard:** a projection above the budget refuses with nothing written, exactly the budget starts, a
  dry run records it, the run-count table by hand; tests stub the timing. **[M21]** A0's table includes the one-off
  volatility-clustering check, and A0 reports E1's and SL-E1's own false-positive counts next to the joint ones.

## 18. Known weaknesses

1. **Hindsight, and no truly fresh window** (K1, K2, K7). "Trend cut the 2018 and 2022 falls" is close to certain in
   advance, and proves little. E1, E2, E6 and E7 limit the damage but cannot remove it.
2. **Few independent bear markets.** The edge, if any, rests on two (2018 and 2022). Five out-of-sample years are
   too short for DSR ≥ 0.95 to pass even a real edge often (TESTING.md section 4). Expect INCONCLUSIVE or NO EDGE
   more often than EDGE.
3. **Fold 0 is thin and odd.** It is chosen from about 162 tradable rows of the 2017 bubble, with `min_trades`
   pushing it toward faster rules. Every study's first objective block is zero (section 6).
4. **Whipsaw and lag.** These are exposed in the sideways 2019, after the V-shaped March 2020 crash, and around the
   2021 tops. Weekly checks exit after fast crashes, not before. No daily-close rule avoids a one-day crash (the bar
   of 2020-03-12, K2).
5. **Big one-shot legs.** A switch sells a whole coin sleeve at once. Slippage above USD 10,000 is extrapolated, and
   H0's compounding book makes later folds' legs larger. Costs are unmeasured placeholders. 0x may charge a 0.15%
   fee on some pairs while `aggregator_fee_bps` is 0; the 2x stress bounds a 15 bps fee.
6. **All cash means all USDC.** Depeg risk (March 2023, inside validate) is not modelled, nor is cash yield (missing
   yield works against S).
7. **Exposure creep.** Without a trim, a long uptrend lets crypto drift up to the Steady limits (80% coins, 60% per
   coin) before a limit fix. "25% each when trending up" is the weight at entry, not a ceiling. R2 reports it.
   **[M9]** A customer who picks 60% can hold up to about 80% crypto when a crash comes (after a rise of about 2.7
   times in both coins), and the wallet can sit past a limit for up to a day, since a breach at a close is traded at
   the next open. The plain words and the app wording now say so; R2 reports the most crypto at any close.
8. **The two coins are highly correlated**, so their switches often coincide, and the shift null keeps that
   co-timing. A switch re-cuts the other coin, which mixes a little rebalancing in. The nulls share that machinery.
9. **The stitched S mixes per-fold configurations.** Its drawdown is not that of any shippable configuration, and
   θ_final's numbers are in-sample. R_0 pays the fold-boundary switches that S never pays.
10. **Scouting only.** The reference engine, exchange candles as a proxy for Base prices, decisions at 00:00 UTC
    only, and fills at the next daily open.
11. ~~**G6 is MISSING and G8 fails by construction**, so CANDIDATE FOR AUDIT is out of reach in this study as the gates
    stand.~~ **[M1, M2]** With the 35% budget and G8-excess, CANDIDATE FOR AUDIT ~~is within reach~~ **[M10]** can be
    reached only if G8-excess passes, which is unlikely by construction. G8-excess passes only if S's excess over N0
    is ≥ 0 in bull, bear and sideways months alike. It is expected to FAIL, so CANDIDATE FOR AUDIT is expected to be
    unreachable (section 1; owner question 6). The literal G8 still
    fails by construction and is reported. G6 is likely to bind at the higher allowed crypto shares, and one failing
    grid step fails the range (section 8).
12. **Production.** ~~A loss-limit pause, Approve mode, or per-trade and per-day caps can block the exit to cash, the
    one order that protects the customer (owner question 4).~~ **[M3]** The owner decided that sells to cash go through
    a pause or a wait for approval (decision 3). Still open: the auto-trading permission's per-trade and per-day caps
    must allow ~~a full switch (up to 30% of the wallet at s = 0.60) and, for the stop, a sale of every coin (up to 80%
    of the wallet after drift)~~ **[M9]** the orders this rule sends: any order that moves a coin to cash (a switch or a
    stop) can sell every coin held, up to about 80% of the wallet (more after a gap day); one switch into both coins
    buys up to s of the wallet (60% at s = 0.60); at most one order per day. Also open (owner question 7): whether a
    customer's own per-trade or per-day cap may block a sell to USDC; if it may, the strategy cannot promise its exit.
    And whether a mixed order's buy legs wait during a pause.
13. **The lead guard is a judgement.** G = 52 weeks clears the longest average (200 days, 29 weeks) by about half a
    year, but a spell that started within 29 weeks of a return and lasted another 24 weeks can still carry a
    trace of it into a 53-week lead. That only makes E1 conservative; the slow calibration at the slowest corner
    (200, 0.10) measures it. The guard also removes 52 of 259 shifts and leaves E9 only 25. **[M21]** The review's
    synthetic check found the opposite trace too: with volatility clustering at (200, 0.10), leads beat R_0 more
    often and E1 passed up to 6.7% of the time under the p95 rule; the one-off check in A0 (section 9) measures it at
    1000 panels. **[M20]** E1's null also keeps the lags of 1-52 weeks (a quarter of the shifts); a lag of 1-4 weeks
    is almost a copy of R_0, which lowers E1's power, not its validity (R_0's rank among the lags is reported). E9's 25
    shifts are mostly lags of 1-25 weeks, so "above the median" there is a weak test that can only reject.
14. **[M4] The Monte Carlo does not re-run the stop.** The block bootstrap resamples S^φ's returns, which already hold
    its stops; on a resampled path nothing is re-decided. So SL-B (iv) compares the drawdowns of two return series,
    not the stop's protection on new paths, and it can flatter or harm the stop. **[M15]** This is acceptable only as
    disclosed and next to SL-E3: a block bootstrap of a series with more all-cash days gives shallower drawdown paths
    by itself, so SL-B (iv) favours any rule with more cash; SL-E3 compares S^φ with X^φ, which holds the same average
    crypto.
15. **[M4] Few stops.** Over 2018-2022 a wallet stop at these levels may fire only a handful of times (section 1's
    expectation, K1). SL-P is then likely to fail, and the variant is likely INCONCLUSIVE or NOT TRIGGERED at best,
    especially at 40%.
16. **[M4] A stop depends on when the customer started.** H0 starts every run in 2017, so the high is a 2017
    customer's. A customer who started on another day has another high and other stop dates; the fresh-customer runs
    show one other start per fold.
17. **[M4] A lock can sit out a whole rally.** After a stop, a coin that keeps trending up stays in USDC until its
    trend turns down and up again. The regret is reported.
18. **[M4] Locks add memory, so SL-E1 is likely conservative.** A lock can last longer than the slack the lead guard
    G = 52 leaves (weakness 13), so some guarded shifts may still carry a trace of the stop's own future.
19. **[M4] The wallet's value includes gas** that production pays for the customer: at most USD 0.10 per leg.
20. **[M4] Two readings of the owner's words were left out** (a per-coin stop; a profit give-back). If the owner meant
    one of them, this study does not test it (section 19).
21. **[M1] s is weakly identified.** The search's s carries no evidence (section 5); the grid does the work. θ_final's s
    may sit at 0.30 or 0.60, and the default follows it. **[M19]** The walk-forward choice S also holds a weakly
    identified, noise-chosen s in each fold, so S's G6 can fail on that choice even when every allowed value passes,
    and no narrowing can fix S (section 8).
22. **[M17] SL-T has little power with few stops.** With 1-2 stops in the kept rows (section 1's expectation), the
    placebo stops can rarely rank R_0^φ in the top 5%. The variant will then most likely read STOP DOES NOT HELP or
    INCONCLUSIVE (LOW POWER). That is the honest answer, not a reason to drop SL-T.
23. **[M21] A0's power says little about real data.** The positive controls' regimes last about 40-67 days on average,
    short next to averages of up to 200 days, while real bear markets lasted about a year; the power alarm is expected
    to fire (section 9).

## 19. Owner questions

**[M3] Status on 2026-11-22** (quoted in the header): Q1 answered on 2026-11-21, a 35% budget, so Branch R; Q2
answered "yes"; Q3 **not asked**, so its default (weekly Monday checks) holds and is logged here; Q4 answered "yes"
(sells to cash go through; a pause still stops all buying); Q5 answered: the gain over the held mix (G8-excess). All
were answered in writing before this plan's commit. `OWNER_QUESTIONS.md` is in the session scratchpad, not in the
repo; the draft's text below is kept for the record. **[M9, M10]** Two new questions, Q6 and Q7, are open; their text
is below, written for the owner on 2026-11-22.

**[M10] Question 6, put to the owner in writing on 2026-11-22 (answer needed before any trend-steady result of any
kind, A0's synthetic controls included; none at this commit).** In plain words, for the lead to send as written:

> **Q6. The "no single kind of market makes most of the profit" check is expected to fail for this strategy even in
> the form you chose. Keep it as it is, or give another rule?**
>
> On 2026-11-21 you chose to measure this check on the strategy's gain over simply holding the same mix, so that
> sitting out a crash counts. We told you then that the check as first written would almost surely fail. We did not
> tell you that the version you chose is very likely to fail too, for a reason of arithmetic:
> - The check splits the gain over the held mix into rising, falling and sideways months, and passes only if no kind
>   holds more than half of the total gain.
> - With three kinds of month whose gains add up to the total, "none above half" means "none below zero". So the
>   strategy would have to do at least as well as the held mix in rising months too.
> - A strategy that steps out to cash in downtrends usually does a little worse than the held mix in rising months,
>   because it buys back late. Its gain comes from falling months, so even when it does not lose in rising months,
>   falling months usually hold more than half of its gain.
> - So the check is expected to fail whatever the strategy's skill, and this study's best possible result becomes "edge, but not a
>   candidate for the next stage". In synthetic tests (made-up markets, not real prices) it passed in none of 40
>   markets, and in a second test in 1 of the 13 markets where the strategy beat the held mix.
>
> **Options.** (a) Keep the check as it is. This is the default if you do not answer: the study runs as planned, and
> its best result is expected to be "edge, but not a candidate". (b) Give another rule now, in your own words. The
> study does not propose one; whatever you choose is written into the plan, dated, before any trend-steady result, and
> after that nothing about this check changes.

**[M9] Question 7, put to the owner in writing on 2026-11-22 (a product question; it changes no number in this
study, and a late answer is fine).**

> **Q7. May a customer's own per-trade or per-day limit block a sale to cash?**
>
> When this strategy steps out of a downtrend, or the stop-loss variant sells, one order can sell every coin the
> wallet holds: up to about 80% of the wallet, more after a big up day. A switch into both coins can buy up to the
> whole crypto share (60% of the wallet at 60%). If a customer's personal per-trade or per-day limit can block that
> sale, the strategy cannot promise to get the customer out. You already decided that sales to cash go through during
> a loss-limit pause or while waiting for approval (2026-11-21); this asks the same about the amount limits.

**[M4] New questions, with no effect on this study** (a late answer changes nothing here; it can shape a later
pre-registration):
- Did the owner mean "sell when the wallet is 40% below its high", or "sell when the wallet has given back 40% of its
  profit"? This study tests the first (section 11A), the reading of the proposal the owner accepted.
- Would customers pick the stop level, and would a stop be on by default?

Five questions, in plain language, each with a recommended default and why: see `OWNER_QUESTIONS.md` next to this
draft. If there is no answer, the default holds and is logged:
1. no budget → fixed settings at 50% crypto in uptrends (Branch F);
2. 100% USDC allowed when both coins are down;
3. weekly Monday checks fit "a few trades a month";
4. recommend letting exits to cash run during pauses (a product decision; the study is unchanged);
5. G8 stays literal.

Answers that change the plan, decided now:
- **Q2 "no"** (`max_coin_pct` also caps USDC): the all-cash state is forbidden and the rule cannot exist at Steady.
  This plan is withdrawn and nothing is run; a redesign is a new draft.
- **Q3 "no"** (weekly checks are not "a few trades a month"): withdrawn the same way. A slower check day cannot
  be picked from this draft's descriptions.
- **Q1** sets the branch (section 8). **Q5** chooses the literal G8 or the pinned G8-excess (section 10).
- Every answer, and every default that held for lack of one, is quoted with its date in PLAN.md's header before
  the commit. Q1 and Q5 count only if answered in writing before the commit; a later answer to either changes
  nothing in this study. **[M10]** Q6 counts only if answered in writing before any trend-steady result of any kind
  (A0's synthetic controls included), recorded with its date as a named amendment that cites the review's finding; a
  later answer changes nothing in this study, and with no answer G8-excess stands as pinned. A later "no" to Q2 or
  Q3 stops the study wherever it is; every trial already run stays logged and counted, and the stop is recorded in
  RESULTS.md.

## 20. Looks at the data

| # | Date | By | What was looked at |
|---|---|---|---|
| K1-K9 | before the plan | see section 2 | Prior looks, disclosed |
| K10 | **[M5]** 2026-11-21, after 22:13 UTC | the lead | hold-mix-cap's RESULTS.md, RISK.md and `decision.json` (section 2) |
| K11 | **[M5]** 2026-11-22 | `quant-researcher` | The 2026-11-22 owner record, which quotes hold-mix-cap's results, and rebalance-steady's files (section 2) |
| M1-M8 | **[M5]** 2026-11-22 | `quant-researcher` | No market data: `config/risk_levels.yaml` and the price-free date grid only (appendix B) |
| Review | **[M22]** 2026-11-22 | `backtest-auditor` and `risk-officer` | Their review of this plan (M1-M8). No market data; synthetic checks only (`trendrun/planstats/`, `trendrun/planreview/`, `trendrun/riskreview/` in the session scratchpad). Their task briefs held the lead's one-sentence summary of hold-mix-cap's results (K10's words: falls of held mixes by crypto share, mostly in 2018; fees from frequent rebalancing; 2017 and 2018 move the results), with no file and no number. The auditor reports reading no hold-mix-cap file, no hold-mix-cap number in `docs/app/features.md` and not the 2026-11-22 owner record. What the `risk-officer` review read beyond this plan is not yet in the record: the lead adds it here before A0 (stop rule 16) |
| M9-M22 | **[M22]** 2026-11-22 | `quant-researcher` | No market data. Read: this plan, the draft's hash only, the README, the review's findings and some of its synthetic scripts (`g8x.py`, `g8_excess_check.py`, `e1_volnull.py`, `gens.py`, `rule_size.py`), the 2026-11-21 owner record, `OWNER_QUESTIONS.md` Q5, the scratch checks of appendix B, `lab/` code (`steady.py`, `report.py`, `montecarlo.py`, `synthetic.py`, the import closure) and rebalance-steady's `frozen_paths()`, and TESTING.md (project instructions; see K11's corrected line). The task brief held the same one-sentence summary of hold-mix-cap's results. Not read: any hold-mix-cap result file, `docs/app/features.md`, the 2026-11-22 owner record (only `git diff --stat` of `52d7ee1`, which lists file names), the catalog and `results/`. Ran only the synthetic and price-free checks of appendix B |
| A0 | reserved, before run 0 | `quant-researcher` | Procedure controls on 40 synthetic panels (no market data) |
| T1 | reserved | `quant-researcher` | Run 0: Kraken and Binance daily train bars to 2023-01-01 00:00 UTC |
| V1 | reserved | `quant-researcher` | The single validate look, only if E1-E8 and P hold |

**Validate-window looks used for trend-steady: 0.**

---

## Appendix A. How this draft was assembled (the judge's record)

Four sketches were written independently from four lenses: evidence, simplicity, luck and limits. Each was scored 1-5
on five criteria.

| Sketch | Evidence behind the rule | Simplicity and parameter count | Protection against luck and overfitting | Fit with Steady limits and AGENTS.md ("Settings ranges") | Feasibility on existing code | Total (of 25) |
|---|---|---|---|---|---|---|
| evidence (`sketch_evidence.md`) | 5 | 4 | 4 | 4 | 4 | **21** |
| limits (`sketch_limits.md`) | 3 | 3 | 4 | 5 | 4 | 19 |
| simple (`sketch_simple.md`) | 3 | 5 | 3 | 3 | 5 | 19 |
| luck (`sketch_luck.md`) | 3 | 2 | 5 | 3 | 3 | 16 |

**Why the scores.**
- **Evidence (the base).**
  - A literature-backed rule: one signal family, per-coin price-to-average, a buffer and weekly checks.
  - 2 parameters.
  - An exposure-preserving whole-span rotation null and an always-in null.
  - A power precondition.
  - Fixed settings with a reason.
- **Limits.**
  - The best fit: the branch structure tied to the budget, the range top 0.60, the R1-R5 conditions, the boom rule
    built in, E3 against holding less crypto, and production exits during pauses.
  - Less simple: a drift trim, a closure over the full panel, custom scored rows and folds.
- **Simple.**
  - The leanest and most feasible.
  - But a BTC-only signal drives ETH, and daily checks sit awkwardly with the owner's guardrail ruling.
  - Its null shuffles spells only within a year.
- **Luck.**
  - The strongest controls: 5 folds with both bears out of sample, harness H0 with a common start state,
    leave-one-year-out, a power floor, procedure controls, and the AGENTS.md grid-timing gap.
  - But 4 searched parameters (s and f weakly identified).
  - 100 bootstrapped null markets (about an hour of compute and 2-3 GB).
  - A strict count of N_raw + 82.

**Grafted onto the evidence base:**
- **From luck:**
  - 5 one-year folds (both bear years out of sample);
  - harness H0 (`warmup=2190`) with the common start state;
  - E6 leave-one-year-out (decisive);
  - the power floor of 20 switches in ≥ 4 folds, with low power never rescuing a failure;
  - the synthetic positive and negative procedure controls (A0);
  - Binance on folds 1-4;
  - the out-of-sample S(s_k) check for a grid in Branch R.
- **From limits:**
  - Branch F/R fixed before any result, with a branch guard;
  - s ≤ 0.60 in Branch R;
  - exhaustive weekly shifts instead of random offsets;
  - E2 at mean block 60;
  - E3 against an exposure-matched mix (decisive);
  - the owner's boom rule as E7 and in G7;
  - R1-R5;
  - the pauses risk and the production notes.
- **From simple:** s = 0.50 fixed; one shared executor for S and every null; the order-hash invariance stop; the app
  wording.
- **From evidence itself:**
  - R_0 as E1's statistic, so the null and the rule differ only in timing;
  - E9 not requiring a validate win over N0;
  - the daily-check variant;
  - the slow calibration test of E1.

**Not taken, and why:**
- **The 100 bootstrapped null markets (luck).** Long bear markets are themselves trends, so markets without long
  trends cannot tell "crypto trends" from "this sample had two long bears". With positive drift, a trend rule loses
  to always-in there, so N2 is nearly implied by E2 at large cost. Calibration of the procedure is kept, on synthetic
  panels (A0) and in the slow test.
- **The drift trim (limits).** It adds a rebalancing component and a pinned constant to a trend test. Exposure creep
  is reported instead (R2), and the app wording says "at entry". **[M22]** That last clause was not true: neither the
  draft's nor M1's app wording said "at entry". M9's wording does: it buys the chosen share when the trend turns up,
  and rising prices can take it to 80% before it is trimmed back.
- **A BTC-only signal and daily checks (simple).** "Moves to cash in downtrends" reads per holding. Daily checks need
  the owner's "shown to pay" test, so they are reported as a variant.
- **Searching s and f (luck).** They are weakly identified, and a range cannot be pre-registered without a budget.
- **Scoring from row 250 with a full-panel closure (limits).** H0 gives the same path independence with the lab's
  harness unchanged.

## Appendix B. Checks run for this draft (no market data)

Run from the scratch folder with the repo's `.venv/bin/python -B` and `PYTHONDONTWRITEBYTECODE=1`. Nothing was written
in the repo: `git status --short` showed only the other workflow's three entries before and after.
- **`judge/grid.py`:** the date grid rebuilt from DATA.md's counts (2190 closes, 2018-01-13 dropped) and
  `walk_forward(2190, 365, 365, expanding=True)`. It gives:
  - the fold table of section 7;
  - row 199 = 2017-07-20; the first Monday check = row 203, 2017-07-24;
  - 313 Mondays in train, at most 5 in any 30 days;
  - W = 260 check closes deciding kept fills, 52 per fold; with the lead guard G = 52 (added by the audit), E1 uses
    207 shifts, E8 155 (W = 208) and E9 25 (W = 78);
  - Binance row 199 = 2018-03-05, a Monday;
  - validate: row 2190 = 2023-01-02, with 78 decision Mondays from 2023-01-02 to 2024-06-24.
- **`judge/feas.py`:** `risk_limits("steady")` gives min_cash 0.2, max_coin 0.6, budget `TBD` → None, SHA-256
  `158d7c9f…`. All 20 target sets for s ∈ {0.30, 0.40, 0.50, 0.60, 0.70} × 4 states pass `check_targets` with h =
  0.02.
- **Timings:** quoted from the sketches' synthetic stand-ins (`timing_out/timing.json`: one 2190-row backtest 0.0131
  s, a 200-trial study 5.80 s; `standin_timing.py`: 5.84 s; the luck sketch: 5.96 s).
- **Audit checks (synthetic only; `audit/` in the scratch folder, run with the repo's `.venv/bin/python -I -B`, nothing
  written in the repo):**
  - `judge/grid.py` rerun: the fold table, W = 260 (52 per fold), Binance row 199 = 2018-03-05 and the 78 validate
    checks reproduce.
  - `audit/shift_null_check.py`: iid Gaussian random walks (daily mean 0.001, sd 0.04), one coin, weekly checks from
    row 203, no costs, 400 panels per point. E1 pass rate with all 259 offsets / with the guarded 207: (50, 0.02)
    2.8% / 5.5%; (200, 0.10) 0.0% / 5.0%; (20, 0.005) 6.0% / 6.8%. Share of lead offsets 1-52 at or above R_0: 57%,
    74% and 51%; of delays 1-52: 49%, 50% and 48%.
  - `audit/dsr_zero_rows_check.py`: 200 box points on 20 random walks per length; the variance of trial Sharpes on
    all rows over that on rows 204.. is 0.439, 0.720, 0.813, 0.860, 0.888 and 0.906 at 365, 730, 1095, 1460, 1825
    and 2190 rows, equal to the active share.
- **[M1] Rerun on 2026-11-22 for Branch R** by `quant-researcher`, from the session scratchpad (`trendrun/checks/`,
  next to the draft's `trend/` folder), with the repo's `.venv/bin/python -I -B` and `PYTHONDONTWRITEBYTECODE=1`; no
  market data, and nothing written in the repo:
  - `feas_r.py`: `risk_limits("steady")` gives coins BTC, ETH and USDC; min_cash 0.2; max_coin 0.6; budget 35 →
    0.35; SHA-256 `d3f58253…`, equal to the hash of the file's bytes. For every allowed value s ∈ {0.30, 0.40, 0.50,
    0.60} and for the plateau extremes 0.24 and 0.72, the 4 states pass `check_targets` with h = 0.02, and so does the
    all-cash target (~~33 target sets~~ **[M22]** 24 target sets: 6 shares × 4 states, the all-cash state among them,
    19 distinct target vectors; the script's count of 33 counted 0.30 and 0.60 twice and the all-cash set once more).
    The largest s on a 0.001 grid whose 4 states pass is 0.78.
  - `grid.py` (the draft's `judge/grid.py`, copied unchanged): the fold table of section 7, row 199 = 2017-07-20, the
    first check at row 203 (2017-07-24), 313 Mondays in train with at most 5 in any 30 days, W = 260 (52 per fold),
    Binance row 199 = 2018-03-05, and validate row 2190 = 2023-01-02 with its 78 decision Mondays all reproduce.
  - `segments.py` (new, for section 11A): the 260 weekly segments of the out-of-sample span have 7 closes each,
    except segment 0 (2018-01-08 .. 2018-01-14 without 2018-01-13, a Saturday) and segment 259 (2022-12-26 ..
    2022-12-31, before the last close), which have 6; 6 closes (2018-01-02 .. 2018-01-07) come before c_0.
- **[M22] Rerun on 2026-11-22 for the review amendments** by `quant-researcher`, from the session scratchpad
  (`trendrun/checks2/`, and the earlier scripts in place), with the repo's `.venv/bin/python -B`; no market data, and
  `git status --porcelain` showed only `?? research/trend-steady/` before and after:
  - `feas_r2.py` (touched by M9 and the count): coins BTC, ETH and USDC; min_cash 0.2; max_coin 0.6; budget 35 →
    0.35; SHA-256 `d3f58253…`, equal to the file's bytes. All 24 target sets pass with h = 0.02 (19 distinct vectors);
    the largest feasible s on a 0.001 grid is 0.78. The rise before a limit fix, from the limits as read: both coins
    × 9.33, 6.00, 4.00 and 2.67 take crypto to 80% at s = 0.30, 0.40, 0.50 and 0.60; one coin alone × 8.5, 6.0, 4.5
    and 3.5 takes that coin to 60% (crypto then 67%, 70%, 73% and 77%). The review's `riskreview/feas_check.py`
    gives the same (24 passed, 0 failed).
  - `shift_null_rank.py` (touched by M16): the draft audit's `shift_null_check.py` model, unchanged (400 panels per
    point), scored under both E1 rules: p95 rule 5.50%, 5.00% and 6.75%; rank-p rule 5.25%, 4.50% and 6.25%, at
    (50, 0.02), (200, 0.10) and (20, 0.005).
  - `segments.py` and `grid.py` (used by M11, M16 and M17), rerun unchanged: W = 260 with 258 segments of 7 closes
    and 2 of 6 (segments 0 and 259), 6 closes before c_0; the fold table, 52 checks per fold, Binance row 199 =
    2018-03-05 and the 78 validate checks reproduce. The fold t0 closes are 2018-01-02 (a Tuesday), 2019-01-03,
    2020-01-03, 2021-01-02 and 2022-01-02, so a fold's first check close comes 1-6 closes after its t0 (M11).
  - The thresholds by arithmetic: E1 10/208 = 0.0481 holds and 11/208 = 0.0529 fails; E8 7/156 = 0.0449 holds and
    8/156 = 0.0513 fails; E2 500/10,001 = 0.049995 holds and 501/10,001 = 0.050095 fails; at a true 4.8% the chance
    of 19 or more of 200 is 0.4%, and of 3 or more of 20 6.9%; at 1000 panels, at most 67 holds with 99.3% at a
    true 5% and fails a true 7.5% 82% of the time (`scipy.stats.binom`).

## Critique log (backtest-auditor, 2026-11-21)

An independent pass that tried to break this draft as a pre-registration. Nothing was read from the catalog,
`data/`, `results/` or the test window; no real-price statistic was computed. The only runs were synthetic (appendix
B, "Audit checks"). Nothing was written in `/home/user/osprey`; `git status --short` there showed only the other
workflow's entries before and after.

### Fixed in this draft

| # | Severity | Issue found | Fix (where) |
|---|---|---|---|
| C1 | Blocking: luck control invalid | E1's circular shift null used every offset u = 1..259. For u = 1..52 the shifted schedule holds, at week k, the state the rule takes u weeks *later*, set from prices that include the returns it then earns (a 200-day average spans 29 weeks; hysteresis carries states further). These are look-ahead copies of the signal. On synthetic random walks 74% of them beat R_0 at (200, 0.10) and E1 never passed (0.0%), so E1 was far too strict under the null, lost power under a real trend, and the draft's own two-sided calibration band would have failed. The same flaw sat in E7 (same offsets), E8 (207 of 207 offsets), E9 (77 of 77) and the A0 power estimate | Lead guard G = 52 weeks: the null uses u = 53..W−1 only, i.e. 207 shifts for E1 and E7, 155 for E8 (W = 208), 25 for E9 (W = 78). Delays of 1-52 weeks stay (they read only past prices). Guarded E1 passed 5.0-6.8% under the null in the synthetic check. Sections 0 (plain words), 1, 9 (B3 row), 11 (E1, E8, E9), 12 (EDGE wording), 13, 17 (offset and oracle tests), 18 (weakness 13), appendix B |
| C2 | Blocking: mislabelled description | B3-fold (circular shift within each 52-week fold, offsets 1..51) was described as "within-year timing", but every one of its offsets leads the schedule over part of the year, so it measured look-ahead, not timing | Replaced by B3-lead: the 52 excluded lead offsets reported as a lead/lag profile, never a null and never in any criterion (sections 9, 14, 16) |
| C3 | Blocking: gate measured leniently | Every search study starts at row 0 (H0), and rows 0-203 are 0 for every trial. Trial Sharpes shrink by √(active share), so the trial-Sharpe variance behind DSR's luck benchmark was understated (synthetic: exactly the active share, 0.44 in fold 0 to 0.91 in the final study, about a fifth pooled): **G3 too lenient**. PBO halves made only of zero blocks tie every trial, which the tie rule scores as overfit (G4 pushed up; direction not guaranteed in every study) | Active-row reading (rows 204 .. end) of trial Sharpes, effective counts, PBO and DSR; G3 and G4 must hold in both readings (stricter of the two; thresholds unchanged). New `active_report` helper with a bit-for-bit test against `overfitting_report` at `first_row=0` and a hand-computed case (sections 6, 10, 14, 17) |
| C4 | Blocking: unset threshold | The slow calibration test said "within the binomial band of 5%" with no band, one parameter point, and no generator settings; a two-sided band would also fail a valid but conservative test | Two pinned points, (50, 0.02) and the slowest corner (200, 0.10); generator fully pinned (means, sds, correlation, seeds, bar construction); 200 panels each; passes if at most 18 of 200 pass E1 (P = 0.6% at a true 5%); a rate far below 5% is reported, not failed. Cost stated: about 9 CPU-minutes per point (section 9, 17) |
| C5 | Blocking: undefined case | E5(b) "≥ 0.7 × Sharpe(S)" passes a worse weekday when Sharpe(S) ≤ 0 | E5(b) also requires Sharpe(S) > 0, as G5 does; boundary test added (sections 11, 17) |
| C6 | Blocking: outcome treated as a bug | X's exposure-matched targets come from S's realised weights, yet a `check_targets` refusal was a stop "for a bug", which would turn a data outcome into an amendment run | If ē fails the limits with h, X's targets are scaled by the largest passing common factor λ and marked "clipped"; never a stop. Stop rule 12 reworded; test added (sections 9, 15, 17) |
| C7 | Ambiguity | E6's X_y and X collided with the comparator X used by E3 | Renamed Δ_y and Δ (sections 11, 16, 17) |
| C8 | Blocking: optional analysis could become the result | Nothing stopped a description (the daily-check variant as the owner's "shown to pay" evidence, another weekday, s = 0.30/0.70, Binance alone, folds 1-4 alone, a block-20 E2) from being promoted after results | "Descriptions never decide": none can change the verdict, headline, θ_final, settings, check day or s; "shown to pay" needs its own pre-registration listing these trials as prior looks; RESULTS.md opens with the mechanical verdict (section 12) |
| C9 | Blocking: AGENTS.md "Settings ranges" gaps (Branch R) | (a) Narrowing that would drop the default had no defined outcome. (b) The budget and allowed values could be set after hold-mix-cap's RESULTS.md (static-mix drawdowns on the same years) without that look being listed, which "Settings ranges" requires | (a) The range fails; never re-centred, never cut to fixed settings. (b) Branch R condition 4: section 2 lists everything the owner and `risk-officer` had seen when setting the budget and values (section 8) |
| C10 | Blocking: rules that could be set after results | Owner question 5's alternative G8 was described only in words, so it could be defined after results. The consequences of "no" to Q2 or Q3, and of late answers, were undefined | G8-excess pinned (`regime_split` with N0 as benchmark: excess_total > 0 and no regime's excess above half); it replaces the literal G8 only if chosen before the commit; both always reported. Q2 or Q3 "no" withdraws the plan (or stops it wherever it is, trials kept and counted); Q1 and Q5 count only if answered before the commit (sections 10, 19) |
| C11 | Trial-count gap | The R4 wallet-size reruns (cost variants of θ_final with identical orders) were "not counted", while the 2x cost variants were | The 4 sizes other than USD 10,000 join the strict count: N_raw + 29 (Branch F), N_raw + 49 (Branch R) (sections 12 R4, 14) |
| C12 | Regime concentration not visible | E6 survives dropping either bear year, but nothing showed how much of the edge lives in 2018 and 2022 together | Description added, reported whatever it shows: Δ, D and E1's rank p with both bear years removed (section 16) |

### Checked and found sound (no change)

- **Look-ahead in the rule.** SMA over rows t−L+1..t includes close t, the decision is at close t and the fill at
  the open of t+1 (hard rule 4; the engine in `portfolio._simulate` fills orders decided at close t at the open of
  t+1 and never fills the last close's order). Activation A = max(199, L−1) gives the same first check (row 203,
  2017-07-24) for every L in the box. No indicator is fitted; X's ē and the G8/E7 labels are ex post but feed only
  comparators and row removal.
- **Folds and purge.** `judge/grid.py` rerun on a price-free date grid: training ends at t0−1, kept rows start at
  t0+1, so no training return touches a kept row; no labels, so no purge is needed. 52 checks per fold, 260 in all.
- **No validate or test bars before the rules allow.** Every train-phase run ends at close 2023-01-01; the validate
  panel is loaded only at the earned look; nothing requests a close after 2024-07-01 00:00 UTC.
- **Order invariance across costs and book size.** Costs are shared pro rata, so weights after a fill equal the
  targets whatever the costs; the order hash (stop rule 13) is a sound check.
- **Costs at small books.** `Costs.slippage` is flat at 10 bps below USD 100 and extended at 15 bps a decade above
  USD 10,000; a USD 2,500 leg costs about 26 bps as stated; `stressed()` doubles gas too; at USD 100 gas is 0.1% a
  leg, far from the engine's cannot-pay refusal.
- **Steady limits.** The 4 target sets sit well inside the limits with h = 0.02; the all-cash state depends on the
  per-coin reading of `max_coin_pct` (owner question 2, now with a defined "no" outcome).
- **Feasibility.** Train phase about 1-2 CPU-minutes of search plus seconds of nulls; bootstraps are vectorised;
  A0 about 20-30 CPU-minutes; the pinned calibration adds about 18 CPU-minutes to the slow tier.
- **Branch F against AGENTS.md.** No budget, so no range; θ_final(A) is gated where the "Settings ranges" table
  names the default (G5(b), G7, G8), and its runs are labelled in-sample.

### Residual notes (not blocking; left for the reviewers)

1. **G7's boom-year removal mostly helps a trend rule.** Removing 2019 and 2020 hurts buy-and-hold far more than a
   rule that sits out 2018 and 2022. It is the owner's rule as written; E7 (E1 and E2 without those years) is the
   check with teeth.
2. **E9 is weaker than before.** Its 25 guarded validate shifts are mostly delays of 1-25 weeks. The draft's 77
   shifts were biased toward rejecting by the leads, so this is a correction, but E9 can now reject less.
3. **K4 counts as 1.** The dip study's LightGBM also used the 15 lab features (`ret_20`, `ret_60`, `ma_dist_20`,
   `ma_dist_100`, `eff_ratio_20`), inside dip events only. One look is a defensible count; reviewers may prefer more.
4. **The objective's zero blocks still distort selection.** The fix above covers DSR and PBO only; the search
   objective (unchanged `lab/search`) still scores blocks that are all cash. This is disclosed (section 6), and
   changing it would mean editing `lab/search`, which the plan rules out.
5. **The guard G = 52 is a judgement** (weakness 13): it removes the leak shown in the synthetic check, and the slow
   calibration at (200, 0.10) is the standing test that it stays removed.

### Status of the residual notes after M6 (2026-11-22)

1. G7's boom-year removal mostly helps a trend rule: **open**. It is the owner's rule as written (decision 5); E7 and
   SL-E7 are the checks with teeth.
2. E9 is weaker: **open** (weakness 13).
3. K4 counts as 1: **kept at 1**, and the strict-count DSR is also reported with K4 counted as 15 (M6, a description).
4. The objective's zero blocks distort selection: **still open**. The active-row re-scoring (M6) shows by how much for
   every study; fixing it would edit `lab/search`, which this plan rules out (weakness 3).
5. G = 52 is a judgement: **open** (weakness 13 and the slow calibration test; weakness 18 for the stop's locks).

## Review log (backtest-auditor and risk-officer, 2026-11-22) [M22]

The review of PLAN.md as it stood with M1-M8, before its commit. Nothing was read from the catalog, `data/`, `results/`
or the test window; its checks were synthetic (section 20). Every blocking finding is resolved by a named amendment
(section 15); none was left open. Where the fix asked for an owner's answer before the commit, the question is in
section 19 and the rule for its answer is in the header.

| # | Blocking finding | Resolved by |
|---|---|---|
| B1 | G8-excess very likely fails by construction too; no expectation written; "CANDIDATE FOR AUDIT can be reached" | M10: the expectation (section 1), "can be reached only if G8-excess passes, which is unlikely by construction" (header, section 12, weakness 11), Q6 to the owner in writing. No answer at this commit: G8-excess stands, and an answer counts only before any trend-steady result of any kind |
| B2 | Whether a change of s between folds orders anything was undefined | M11: one order rule for every executor, re-cuts defined and counted, `run_states` on per-row target vectors, the re-cut test; also R_0^φ's fold-boundary entries aligned with R_0's |
| B3 | E5(a)'s "G1-G8" undefined in Branch R | M12: seeds compared on the gates at S only; a boundary test |
| B4 | θ_final(A)'s role as a measurement point unclear | M13: the table of measurement points in section 10 (θ_final(A) for R1 only), "holds only if at every point", a test per point |
| B5 | The config hash left out `lab/data/external.py` | M14: it and the rest of the real-run import closure are hashed, with a test |
| B6 | The stop variant had no exposure control and no second source | M15: X^φ and SL-E3 (verdict step 3), SL-E8 on Binance (step 4), the plain words list the variant's checks, tests, the M4 row |
| B7 | One order can sell far more than 30% of the wallet | M9: the production notes and weakness 12 corrected; Q7 to the owner |
| B8 | The plain words and the app wording overstated how tightly risk is held | M9: plain words, app wording, appendix A corrected; R2 reports the most crypto at any close |
| B9 | E1's p95 rule is not a 5% test | M16: E1 and every test "as E1" on the rank p; boundary tests; appendix B rerun |
| B10 | SL-B had no luck control on what the stop adds | M17: SL-T with placebo stops (named SL-T rather than SL-E8, because B6's Binance check takes SL-E8 to mirror E8) |
| B11 | G8-excess as pinned cannot pass for a long-or-cash rule (the algebra) | M10, with B1: the algebra in section 1 and section 10, the test, Q6 with the algebra in plain words. The gate is unchanged and the study proposes no other reading |
| B12 | Amendment runs could depend on the result | M18: stop rule 18, its RUNLOG trigger and its test |

Suggestions taken: M19-M22 (and E1 and E2 at every S(s_k) in M13). Suggestions not taken, or taken in part:
- The stop-timing null that re-derives locks at the moved dates: B10's simpler placebo was taken instead (M17).
- Counting distinct switch weeks in P, or renaming P: P's rule is unchanged; distinct switch weeks and completed
  out-spells are reported next to it (M20). Changing a decisive count was not judged clearly right.
- A stand-alone slow calibration of SL-E1: not added (it needs the stop re-running on every panel); SL-E1's and SL-T's
  false-positive counts are reported in A0 instead (M17, M21).
- The review's confirmations (no look-ahead in the weekly state, the stop, the high or the buy-back; the lead guard;
  H0; the train-only loads; the strict count N_raw + 49 + 30; the [Mk] marks; the commit times of K12; the time
  budget) needed no change.

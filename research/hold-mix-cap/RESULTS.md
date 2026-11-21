# hold-mix-cap: results (SCOUTING)

> **SCOUTING ONLY.** Every number below comes from the lab's reference portfolio engine (`lab/runner/portfolio.py`,
> driven by `lab/runner/holdmix.py`), not from NautilusTrader (AGENTS.md hard rule 3). All of them use the
> **placeholder** costs in `config/costs.yaml`, and exchange candles (Kraken in USD, Binance in USDT) stand in for Base
> prices. They are in-sample: the 2017-2022 train years only. Every table is labelled SCOUTING. This study is not a
> strategy test: it approves nothing, claims no edge, and sets no limit and no drawdown budget. The owner decides.

## In plain words

We simulated the app's "hold this mix" tool on 2017-2022 BTC and ETH prices (Kraken, checked on Binance): 27 mixes, 6 drift bands,
7 caps, 3 wallet sizes, normal and doubled costs; 916,596 runs, none failed (all SCOUTING). **Recommended default: band 0.50**
(trade back when BTC or ETH is more than half off its target) **with a cap of 1 rebalance a month** (30 days apart; a Steady limit
hit can add trades). Why: 0.50 is the narrowest band that needed at most one trip back a month and at most 0.25% of the wallet a
year in fees at every wallet size, both cost levels and on both sources; 1 a month is the tightest cap that kept it in its band
almost as well as no cap. Other bands: 0.10 → 8, 0.15 and 0.20 → 4, 0.30 → 2 a month; never 0.05 with a cap. More rebalancing buys
closeness for fees: 0.20 with cap 4 (fine for wallets up to 5,000 USD) keeps coins about twice as close to target (typically 9% of
the target away, not 20%) for 5 times the rebalances and twice the fees (0.11% against 0.06% a year). Worst falls, **hypothetical**
(past prices, in-sample), **at the recommended default (band 0.50, cap 1)**: 35% (20% crypto) to 76% (78% crypto) in 12 months,
and up to 29.5% in one day over the whole 2017-2022 run (32% in a 12-month window that started just before the March 2020 crash). **At
other bands and caps the same crypto shares fell further:** 42% (20% crypto) to 80% (70% crypto) in 12 months, 45% over the whole
run at 20% crypto, and up to 33% in one day. Steady's drawdown budget, approved by the owner on 2026-11-21, is 35%: only 2 of
the 27 mixes (20% crypto with 75% or all of it in BTC) fell no more than that at every band and cap, and 4 at the default
(20% crypto, all but ETH only). **Proposal for the owner:** a
hard Steady limit of 2 rebalances in any 30 days, limit fixes exempt: the default fits under it; bands 0.20 and narrower would go.

## Headline (SCOUTING)

Rule D's robust values (PLAN.md section 9), applied mechanically by `run.py` (`decision.json`, `robust`). The primary
values (Kraken, 1x costs) stand next to them.

| Value | **Headline (robust)** | Primary (Kraken, 1x) |
|---|---|---|
| App default band | **0.50** | 0.20 |
| Its recommended cap | **1 rebalance a month: at least 30 days between trades back to the mix** | 4 a month (at least 8 days) |
| Default band per wallet size (500 / 5,000 / 50,000 USD) | **0.20 / 0.20 / 0.50** (caps 4 / 4 / 1) | 0.20 / 0.20 / 0.20 (cap 4) |
| Flag | none (a band met the conditions at every size) | none |
| Steady upper limit (rule C) | **EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED** (all four robust value tests SUPPORTED) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Bands that limit would hold back | **0.05, 0.10, 0.15, 0.20** | 0.05, 0.10, 0.15, 0.20 |
| CONFLICT (the default band needs more than the limit allows) | **no**: N\*_rob(0.50) = 1 ≤ 2 | **yes**: N\*(0.20) = 4 > 2 |
| Default under the limit | not needed (no CONFLICT) | 0.30 with cap 2, at every wallet size |
| Label | **NOT ROBUST** | |
| Status | SCOUTING evidence for the owner; sets no limit | |

**Customer wording** (PLAN.md section 4.1): "Rebalance when a coin is more than 50% off its target, at most once in any
30 days (at least 30 days between trades back to the mix). A Steady limit hit (cash under 20% or one coin over 60%)
is fixed that day and can add trades." For example, with a BTC target of 30% of the wallet, the tool trades back when
BTC is under 15% or over 45%. With large coin targets the Steady limits come first: a 52.5% ETH target would only
leave a 0.50 band above 78.75%, but the 60% limit trades it back long before that. The cap is not "per calendar
month": with a 30-day wait the tool can trade on the 1st and the 31st of a 31-day month.

**Why NOT ROBUST** (`robust.moved`): only one input moved, the band for 50,000 USD wallets.
- b\*(50,000 USD) and with it the app default: 0.20 on the primary values, 0.50 robust. The settings that moved it are
  Kraken at 2x and Binance at 2x. At 2x costs the median customer fees of a 50,000 USD wallet are 0.338% a year at
  0.20 (cap 4) and 0.273% at 0.30 (cap 2) on Kraken, both over the 0.25% limit; only 0.50 passes (0.189%). Binance at
  2x picks 0.30 (0.249%, just under the limit).
- CONFLICT (primary yes, robust no) and the default under the limit (primary 0.30 with cap 2, robust not needed)
  follow from that move.
- The pre-registered CONFLICT check looks only at the single app default. The per-size defaults for 500 and 5,000 USD
  (0.20 with cap 4) would also be held back by a limit at 2. Under it those sizes would get 0.30 with cap 2, which is
  acceptable at both sizes on both sources and both cost levels (read from the rule A table below; not a
  pre-registered output).
- Every recommended cap per band is the same on both sources except band 0.50 (Kraken 1, Binance 0.5); the robust
  value takes the larger, Kraken's, so it equals the primary value. Kraken on Binance's 52 windows is reported in
  "Robustness".

**Recommended cap for each band** (rule B; the larger of the two sources, N\*_rob) (SCOUTING)

| Band b | N\*(b) Kraken | N\*(b) Binance | N\*_rob(b) (headline) | Wait W (days) |
|---|---|---|---|---|
| 0.05 | more than 8 | more than 8 | **more than 8** | n/a |
| 0.10 | 8 | 8 | **8** | 4 |
| 0.15 | 4 | 4 | **4** | 8 |
| 0.20 | 4 | 4 | **4** | 8 |
| 0.30 | 2 | 2 | **2** | 15 |
| 0.50 | 1 | 0.5 | **1** | 30 |

**Next to the headline, never in its place: the other first-buy reading** (amendment A1: the first buy also starts
the wait; 5,000 USD, 1x; rules B and A on each source) (SCOUTING). It moves nothing on Kraken. On Binance it moves
N\*(0.50) from 0.5 to 1, Kraken's value, which the headline already uses.

| Source, reading | N\*(0.05) | N\*(0.10) | N\*(0.15) | N\*(0.20) | N\*(0.30) | N\*(0.50) | b\* (5,000 USD, 1x) | its cap |
|---|---|---|---|---|---|---|---|---|
| Kraken (other reading) | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 | 4 |
| Kraken (lab's reading, headline pools) | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 | 4 |
| Binance (other reading) | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 | 4 |
| Binance (lab's reading, headline pools) | more than 8 | 8 | 4 | 4 | 2 | 0.5 | 0.2 | 4 |

**Next to the headline: limit fixes per crypto share** (PLAN.md section 10; an upper limit would not bound these).
Most rebalances in any 30 days, limit fixes included, at the headline band and cap: median 1 for every crypto share up
to 70%, and 3 at 78%. The worst window held 7 (Kraken) and 6 (Binance) at 78%, and at most 4 (Kraken) and 3 (Binance)
at 70% crypto or less. The full table is under "Per crypto share".

## What the lab proposes to the owner: the Steady upper limit (SCOUTING)

The owner asked whether Steady should keep a hard upper limit on rebalances a month above the number the customer
sets, and said they do not know how to answer it. Here is the evidence as a proposal. It sets no limit: if the owner
adopts it in writing, `risk-officer` adds it to Steady's entry in `config/risk_levels.yaml` and the app's trade router
enforces it, never a constant in code (PLAN.md section 16).

**Proposal: yes, keep an upper limit of 2 rebalances in any 30 days** (at least 15 days between trades back to the
mix), with Steady-limit fixes exempt, as they are from the customer's own cap. If the owner has no preference, the lab
suggests adopting it: it is the plainest reading of "a few trades a month" that the data support. It also fits the
owner's rule for Steady's guardrail (2026-11-20: cap rebalancing unless rebalancing that often is shown to pay). This
study uses no returns, so it shows nothing about whether rebalancing pays; it shows that beyond 2 a month, extra
rebalancing mostly adds fees.

- **Why 2.** Over all 6 bands and 27 mixes, unlimited daily rebalancing kept mixes much closer to their targets than
  trading only at the Steady limits. A cap of 2 a month already got 94.5% of that gain (Kraken; Binance 95.1%). The
  last 5.5% (Binance 4.9%) cost 24-30% of the extra fees of unlimited rebalancing on Kraken and 21-26% on Binance, at
  every wallet size and both cost levels; the rule asks for at least twice the share of closeness given up, 11%
  (Binance 10%). This held on both sources, at both cost levels, in all 8 boom-year checks, and under both other
  readings of the 60% limit (checked at 5,000 USD, 1x).
- **What it would cost.** The app could not offer bands 0.20 or narrower, because they need 4 or more rebalances a
  month to stay in their band (rule B). The recommended single default (0.50, cap 1) is not affected. If the app
  uses a default per wallet size, wallets up to 5,000 USD would get 0.30 with a cap of 2 instead of 0.20 with a cap of
  4: 0.30 with cap 2 met every condition at 500 and 5,000 USD on both sources and both cost levels (rule A table
  below). It keeps mixes less close: a typical distance from target of 13% of the target instead of 9% (Kraken, 5,000
  USD), for half the rebalances (0.41 against 0.82 a month) and lower fees (0.087% against 0.110% a year).
- **What it would not do.** It does not bound limit fixes. At 78% crypto, limit fixes alone made up to 7 rebalances in
  30 days (Kraken; 6 on Binance), and broke through the wait up to 22 times a year (median 3). The app should say so
  next to mixes near the limits ("a Steady limit hit can add trades").
- **Where the number 2 is fragile.** It depends on the yardstick and on the bands offered. Measured by days outside
  the customer's own band, the same rule gives 4. Band by band it gives 4 for 0.05, 2 for 0.10 to 0.20, 1 for 0.30
  and 0.5 for 0.50 (rule C per band, below). If the app offers only 0.30 and 0.50, a limit of 2 never binds on band
  trades at their recommended caps (2 and 1).
- **The alternative.** No upper limit: the customer's own cap is the only cap, the app recommends N\*(b) for the band
  picked, and narrow bands stay available with caps up to 8 a month (0.05 not at all). Fees then reach 0.16% a year at
  band 0.10 with cap 8 (5,000 USD, 1x; 0.46% at 50,000 USD and 2x), and gas, our cost, 4.80 USD a customer a year.

## Per band: rules B and A (SCOUTING)

**Rule B, the recommended cap.** extra_out = days a year out of band with the cap minus without it, per pair (one mix
in one 12-month window). A cap passes when the median of extra_out is ≤ 7 and its 90th percentile ≤ 30; N\*(b) is the
tightest cap that passes with every looser cap passing too. Closeness numbers come from the 5,000 USD 1x runs and are
the same at every wallet size and cost level (PLAN.md section 4.6; checked on every configuration).

**Kraken** (rolling windows; median / 90th percentile of extra days a year out of band against no cap; ✗ = fails EXTRA_OUT_MEDIAN 7 or EXTRA_OUT_P90 30) (SCOUTING)

| Band | cap 0.25 (W 120) | cap 0.5 (W 60) | cap 1 (W 30) | cap 2 (W 15) | cap 4 (W 8) | cap 8 (W 4) | N\*(b) | pairs |
|---|---|---|---|---|---|---|---|---|
| 0.05 | 237.65 / 269.74 ✗ | 210.58 / 244.00 ✗ | 173.00 / 201.55 ✗ | 120.33 / 148.41 ✗ | 65.18 / 96.58 ✗ | 26.07 / 47.13 ✗ | more than 8 | 1620 |
| 0.10 | 232.46 / 276.76 ✗ | 178.49 / 243.67 ✗ | 117.32 / 189.08 ✗ | 61.17 / 113.34 ✗ | 19.05 / 52.14 ✗ | 3.01 / 14.08 | 8 | 1620 |
| 0.15 | 190.52 / 264.45 ✗ | 124.84 / 213.21 ✗ | 77.21 / 138.76 ✗ | 24.00 / 68.19 ✗ | 6.00 / 25.23 | 0.00 / 5.01 | 4 | 1620 |
| 0.20 | 134.55 / 238.65 ✗ | 77.21 / 170.05 ✗ | 39.11 / 99.30 ✗ | 8.02 / 36.11 ✗ | 1.00 / 12.07 | 0.00 / 2.00 | 4 | 1620 |
| 0.30 | 59.00 / 176.53 ✗ | 29.08 / 101.56 ✗ | 3.01 / 45.25 ✗ | 0.00 / 14.17 | 0.00 / 3.02 | 0.00 / 0.00 | 2 | 1620 |
| 0.50 | 0.00 / 91.25 ✗ | 0.00 / 38.10 ✗ | 0.00 / 11.03 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 1 | 1620 |

**Binance** (rolling windows; median / 90th percentile of extra days a year out of band against no cap; ✗ = fails EXTRA_OUT_MEDIAN 7 or EXTRA_OUT_P90 30) (SCOUTING)

| Band | cap 0.25 (W 120) | cap 0.5 (W 60) | cap 1 (W 30) | cap 2 (W 15) | cap 4 (W 8) | cap 8 (W 4) | N\*(b) | pairs |
|---|---|---|---|---|---|---|---|---|
| 0.05 | 243.67 / 271.74 ✗ | 214.59 / 245.67 ✗ | 174.00 / 202.55 ✗ | 117.32 / 146.40 ✗ | 61.00 / 94.26 ✗ | 23.06 / 44.82 ✗ | more than 8 | 1404 |
| 0.10 | 230.00 / 275.76 ✗ | 172.74 / 238.65 ✗ | 112.31 / 173.48 ✗ | 55.15 / 98.00 ✗ | 17.05 / 45.00 ✗ | 3.01 / 12.03 | 8 | 1404 |
| 0.15 | 182.50 / 254.70 ✗ | 117.32 / 194.37 ✗ | 72.00 / 125.00 ✗ | 20.05 / 54.15 ✗ | 5.01 / 17.05 | 0.00 / 4.00 | 4 | 1404 |
| 0.20 | 123.67 / 225.62 ✗ | 70.19 / 150.82 ✗ | 34.00 / 89.24 ✗ | 7.01 / 26.07 ✗ | 1.00 / 8.02 | 0.00 / 1.00 | 4 | 1404 |
| 0.30 | 48.13 / 151.41 ✗ | 24.07 / 79.22 ✗ | 1.00 / 36.10 ✗ | 0.00 / 7.71 | 0.00 / 1.00 | 0.00 / 0.00 | 2 | 1404 |
| 0.50 | 0.00 / 73.90 ✗ | 0.00 / 27.07 | 0.00 / 6.01 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.5 | 1404 |

Close calls: Binance at band 0.20 and cap 2 fails by 0.01 day (median 7.0096 against 7); Kraken on Binance's windows
gives exactly 7.0 there and passes. Kraken's own median there is 8.02, so the robust N\*(0.20) is 4 either way.

**Rule A, the recommended default band**, at each band's robust cap (rule D's view). A band is acceptable at (V, k)
when (i) the median rebalances per 30 days, every reason counted, is ≤ 1.0 and (ii) the median customer fees (swap fees
and slippage, gas left out) are ≤ 0.25% of the wallet a year. b\* is the narrowest acceptable band with every wider
band acceptable too.

**Kraken** at (b, N\*_rob(b)): (i) median rebalances per 30 days (≤ 1.0), (ii) median customer fees, % of the wallet a year (≤ 0.25); ✗ = the band is not acceptable at that setting, by (i), (ii) or both (SCOUTING, placeholder costs)

| Band | Cap N\*_rob | (i) rate | (ii) 500 USD 1x | (ii) 500 USD 2x | (ii) 5,000 USD 1x | (ii) 5,000 USD 2x | (ii) 50,000 USD 1x | (ii) 50,000 USD 2x |
|---|---|---|---|---|---|---|---|---|
| 0.05 | more than 8 | n/a | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) |
| 0.10 | 8 | 2.225 | 0.147 ✗ | 0.294 ✗ | 0.159 ✗ | 0.317 ✗ | 0.228 ✗ | 0.456 ✗ |
| 0.15 | 4 | 1.233 | 0.113 ✗ | 0.226 ✗ | 0.127 ✗ | 0.254 ✗ | 0.192 ✗ | 0.384 ✗ |
| 0.20 | 4 | 0.824 | 0.096 | 0.192 | 0.110 | 0.219 | 0.169 | 0.338 ✗ |
| 0.30 | 2 | 0.412 | 0.073 | 0.146 | 0.087 | 0.173 | 0.137 | 0.273 ✗ |
| 0.50 | 1 | 0.165 | 0.047 | 0.094 | 0.058 | 0.117 | 0.095 | 0.189 |

**Binance** at (b, N\*_rob(b)): (i) median rebalances per 30 days (≤ 1.0), (ii) median customer fees, % of the wallet a year (≤ 0.25); ✗ = the band is not acceptable at that setting, by (i), (ii) or both (SCOUTING, placeholder costs)

| Band | Cap N\*_rob | (i) rate | (ii) 500 USD 1x | (ii) 500 USD 2x | (ii) 5,000 USD 1x | (ii) 5,000 USD 2x | (ii) 50,000 USD 1x | (ii) 50,000 USD 2x |
|---|---|---|---|---|---|---|---|---|
| 0.05 | more than 8 | n/a | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) | not acceptable (no cap) |
| 0.10 | 8 | 2.060 | 0.138 ✗ | 0.277 ✗ | 0.150 ✗ | 0.300 ✗ | 0.215 ✗ | 0.430 ✗ |
| 0.15 | 4 | 1.151 | 0.108 ✗ | 0.215 ✗ | 0.120 ✗ | 0.240 ✗ | 0.178 ✗ | 0.356 ✗ |
| 0.20 | 4 | 0.742 | 0.090 | 0.181 | 0.103 | 0.207 | 0.157 | 0.314 ✗ |
| 0.30 | 2 | 0.411 | 0.066 | 0.132 | 0.078 | 0.157 | 0.125 | 0.249 |
| 0.50 | 1 | 0.165 | 0.039 | 0.077 | 0.048 | 0.096 | 0.078 | 0.155 |

**b\*(V, k) per source, each at its own N\*(b)** (rule A as each source alone gives it) (SCOUTING)

| Source | Wallet, costs | b\* | its N\* | flag |
|---|---|---|---|---|
| Kraken | 500 USD 1x | 0.2 | 4 |  |
| Kraken | 500 USD 2x | 0.2 | 4 |  |
| Kraken | 5,000 USD 1x | 0.2 | 4 |  |
| Kraken | 5,000 USD 2x | 0.2 | 4 |  |
| Kraken | 50,000 USD 1x | 0.2 | 4 |  |
| Kraken | 50,000 USD 2x | 0.5 | 1 |  |
| Binance | 500 USD 1x | 0.2 | 4 |  |
| Binance | 500 USD 2x | 0.2 | 4 |  |
| Binance | 5,000 USD 1x | 0.2 | 4 |  |
| Binance | 5,000 USD 2x | 0.2 | 4 |  |
| Binance | 50,000 USD 1x | 0.2 | 4 |  |
| Binance | 50,000 USD 2x | 0.3 | 2 |  |

**App default per source and cost level** (the widest b\* over wallet sizes) (SCOUTING)

| Source | Costs | App default band | its cap | b\* 500 | b\* 5,000 | b\* 50,000 |
|---|---|---|---|---|---|---|
| Kraken | 1x | 0.2 | 4 | 0.2 | 0.2 | 0.2 |
| Kraken | 2x | 0.5 | 1 | 0.2 | 0.2 | 0.5 |
| Binance | 1x | 0.2 | 4 | 0.2 | 0.2 | 0.2 |
| Binance | 2x | 0.3 | 2 | 0.2 | 0.2 | 0.3 |

## Rule C: the upper-limit evidence (SCOUTING)

I(N) is the share of the closeness unlimited rebalancing buys (over trading only at the limits) that a cap of N
already buys; C(N) the share of its extra customer fees already spent at N. N_up is the tightest cap with I ≥ 0.90 at
it and every looser cap. The value test is SUPPORTED when 1 − C(N_up) ≥ 2 × (1 − I(N_up)). The pool is all 6 bands ×
27 mixes × the windows (9,720 runs per cap on Kraken, 8,424 on Binance).

**Kraken: closeness** (pool: 6 bands x 27 mixes x 60 windows; the same at every cost setting, section 4.6) (SCOUTING)

| Cap | Dist(N): mean d̄ | I(N): closeness bought | D_out(N) (days a year) |
|---|---|---|---|
| limit-only | 0.4150 | 0 (by definition) | 234.8 |
| 0.25 | 0.2415 | 0.540 | 167.6 |
| 0.5 | 0.1785 | 0.736 | 130.7 |
| 1 | 0.1377 | 0.863 | 94.8 |
| 2 | 0.1114 | 0.945 | 62.0 |
| 4 | 0.1003 | 0.979 | 41.1 |
| 8 | 0.0953 | 0.995 | 29.6 |
| no cap | 0.0935 | 1.000 | 23.9 |

**Kraken: fees** F(N), mean customer fees, % of the wallet a year, and in brackets C(N), the share of the extra fees of no cap already spent at N (SCOUTING, placeholder costs)

| Cap | 500 USD 1x | 500 USD 2x | 5,000 USD 1x | 5,000 USD 2x | 50,000 USD 1x | 50,000 USD 2x |
|---|---|---|---|---|---|---|
| limit-only | 0.0319 | 0.0637 | 0.0475 | 0.0950 | 0.0744 | 0.1488 |
| 0.25 | 0.0576 (0.247) | 0.1152 (0.247) | 0.0765 (0.268) | 0.1530 (0.268) | 0.1219 (0.297) | 0.2437 (0.297) |
| 0.5 | 0.0738 (0.403) | 0.1476 (0.403) | 0.0941 (0.431) | 0.1882 (0.431) | 0.1499 (0.472) | 0.2997 (0.472) |
| 1 | 0.0919 (0.576) | 0.1837 (0.576) | 0.1132 (0.607) | 0.2264 (0.607) | 0.1788 (0.653) | 0.3575 (0.653) |
| 2 | 0.1052 (0.705) | 0.2104 (0.705) | 0.1257 (0.723) | 0.2514 (0.723) | 0.1957 (0.758) | 0.3912 (0.758) |
| 4 | 0.1169 (0.817) | 0.2337 (0.817) | 0.1371 (0.827) | 0.2740 (0.827) | 0.2107 (0.852) | 0.4211 (0.852) |
| 8 | 0.1262 (0.907) | 0.2524 (0.907) | 0.1462 (0.911) | 0.2922 (0.911) | 0.2222 (0.924) | 0.4441 (0.924) |
| no cap | 0.1359 (1.000) | 0.2719 (1.000) | 0.1558 (1.000) | 0.3114 (1.000) | 0.2344 (1.000) | 0.4684 (1.000) |

**Kraken: rule C per cost setting** (value test: 1 − C(N_up) ≥ 2 × (1 − I(N_up))) (SCOUTING)

| Setting | N_up | I(N_up) | 1 − C(N_up) | 2 × (1 − I(N_up)) | Value test | Outcome |
|---|---|---|---|---|---|---|
| 500 USD 1x | 2 | 0.9445 | 0.2954 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 500 USD 2x | 2 | 0.9445 | 0.2954 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 5,000 USD 1x | 2 | 0.9445 | 0.2774 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 5,000 USD 2x | 2 | 0.9445 | 0.2774 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 50,000 USD 1x | 2 | 0.9445 | 0.2419 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 50,000 USD 2x | 2 | 0.9445 | 0.2418 | 0.1109 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |

**Binance: closeness** (pool: 6 bands x 27 mixes x 52 windows; the same at every cost setting, section 4.6) (SCOUTING)

| Cap | Dist(N): mean d̄ | I(N): closeness bought | D_out(N) (days a year) |
|---|---|---|---|
| limit-only | 0.3845 | 0 (by definition) | 232.3 |
| 0.25 | 0.2149 | 0.580 | 159.6 |
| 0.5 | 0.1616 | 0.763 | 122.7 |
| 1 | 0.1296 | 0.872 | 87.8 |
| 2 | 0.1067 | 0.951 | 55.7 |
| 4 | 0.0976 | 0.982 | 36.6 |
| 8 | 0.0936 | 0.995 | 26.3 |
| no cap | 0.0922 | 1.000 | 21.1 |

**Binance: fees** F(N), mean customer fees, % of the wallet a year, and in brackets C(N), the share of the extra fees of no cap already spent at N (SCOUTING, placeholder costs)

| Cap | 500 USD 1x | 500 USD 2x | 5,000 USD 1x | 5,000 USD 2x | 50,000 USD 1x | 50,000 USD 2x |
|---|---|---|---|---|---|---|
| limit-only | 0.0195 | 0.0389 | 0.0279 | 0.0557 | 0.0446 | 0.0891 |
| 0.25 | 0.0473 (0.286) | 0.0946 (0.286) | 0.0599 (0.311) | 0.1197 (0.311) | 0.0961 (0.346) | 0.1922 (0.346) |
| 0.5 | 0.0635 (0.452) | 0.1269 (0.452) | 0.0776 (0.484) | 0.1551 (0.484) | 0.1237 (0.530) | 0.2472 (0.530) |
| 1 | 0.0801 (0.622) | 0.1601 (0.622) | 0.0950 (0.653) | 0.1900 (0.653) | 0.1492 (0.701) | 0.2982 (0.701) |
| 2 | 0.0913 (0.737) | 0.1826 (0.737) | 0.1056 (0.756) | 0.2111 (0.756) | 0.1623 (0.790) | 0.3245 (0.790) |
| 4 | 0.1019 (0.846) | 0.2037 (0.846) | 0.1161 (0.858) | 0.2321 (0.858) | 0.1758 (0.880) | 0.3515 (0.880) |
| 8 | 0.1093 (0.922) | 0.2186 (0.922) | 0.1231 (0.926) | 0.2462 (0.926) | 0.1842 (0.936) | 0.3681 (0.936) |
| no cap | 0.1169 (1.000) | 0.2337 (1.000) | 0.1307 (1.000) | 0.2613 (1.000) | 0.1937 (1.000) | 0.3872 (1.000) |

**Binance: rule C per cost setting** (value test: 1 − C(N_up) ≥ 2 × (1 − I(N_up))) (SCOUTING)

| Setting | N_up | I(N_up) | 1 − C(N_up) | 2 × (1 − I(N_up)) | Value test | Outcome |
|---|---|---|---|---|---|---|
| 500 USD 1x | 2 | 0.9506 | 0.2627 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 500 USD 2x | 2 | 0.9506 | 0.2627 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 5,000 USD 1x | 2 | 0.9506 | 0.2443 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 5,000 USD 2x | 2 | 0.9506 | 0.2443 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 50,000 USD 1x | 2 | 0.9506 | 0.2104 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| 50,000 USD 2x | 2 | 0.9506 | 0.2103 | 0.0988 | SUPPORTED | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |

**Robust value test at N_up,rob = 2, 5,000 USD** (rule D: SUPPORTED only if all four pass) (SCOUTING)

| Source | Costs | N | I(N) | C(N) | 1 − C(N) | 2 × (1 − I(N)) | Test |
|---|---|---|---|---|---|---|---|
| Kraken | 1x | 2 | 0.9445 | 0.7226 | 0.2774 | 0.1109 | SUPPORTED |
| Kraken | 2x | 2 | 0.9445 | 0.7226 | 0.2774 | 0.1109 | SUPPORTED |
| Binance | 1x | 2 | 0.9506 | 0.7557 | 0.2443 | 0.0988 | SUPPORTED |
| Binance | 2x | 2 | 0.9506 | 0.7557 | 0.2443 | 0.0988 | SUPPORTED |

**Descriptions next to rule C** (pre-registered; not part of the outcome): I(N) and N_up band by band, and the days
yardstick (I computed from days a year out of the band instead of distance from target).

**Kraken: I(N) per band, and the days-outside-the-band yardstick** (descriptions; I ≥ 0.90 at N and every looser cap gives N_up) (SCOUTING)

| Band | I at cap 0.25 | I at cap 0.5 | I at cap 1 | I at cap 2 | I at cap 4 | I at cap 8 | N_up |
|---|---|---|---|---|---|---|---|
| 0.05 | 0.431 | 0.628 | 0.774 | 0.884 | 0.945 | 0.980 | 4 |
| 0.10 | 0.464 | 0.675 | 0.817 | 0.921 | 0.972 | 0.994 | 2 |
| 0.15 | 0.504 | 0.717 | 0.855 | 0.950 | 0.985 | 0.998 | 2 |
| 0.20 | 0.553 | 0.755 | 0.887 | 0.966 | 0.990 | 1.000 | 2 |
| 0.30 | 0.636 | 0.827 | 0.937 | 0.985 | 0.997 | 1.000 | 1 |
| 0.50 | 0.763 | 0.902 | 0.968 | 0.994 | 0.999 | 1.000 | 0.5 |
| all 6 (days yardstick) | 0.318 | 0.493 | 0.663 | 0.819 | 0.918 | 0.973 | 4 |

**Binance: I(N) per band, and the days-outside-the-band yardstick** (descriptions; I ≥ 0.90 at N and every looser cap gives N_up) (SCOUTING)

| Band | I at cap 0.25 | I at cap 0.5 | I at cap 1 | I at cap 2 | I at cap 4 | I at cap 8 | N_up |
|---|---|---|---|---|---|---|---|
| 0.05 | 0.454 | 0.643 | 0.781 | 0.889 | 0.948 | 0.982 | 4 |
| 0.10 | 0.495 | 0.697 | 0.828 | 0.929 | 0.976 | 0.995 | 2 |
| 0.15 | 0.542 | 0.746 | 0.865 | 0.959 | 0.989 | 0.999 | 2 |
| 0.20 | 0.596 | 0.789 | 0.898 | 0.974 | 0.992 | 0.999 | 2 |
| 0.30 | 0.698 | 0.862 | 0.949 | 0.989 | 0.998 | 1.000 | 1 |
| 0.50 | 0.839 | 0.950 | 0.984 | 0.998 | 1.000 | 1.000 | 0.5 |
| all 6 (days yardstick) | 0.344 | 0.519 | 0.684 | 0.836 | 0.927 | 0.976 | 4 |

**Gas** (our cost: the app sponsors it). At the 0.10 USD placeholder per swap. Not in rule C's fees. (SCOUTING,
placeholder gas)

**Kraken: gas per customer a year** (mean over rule C's pool; our cost, sponsored; 0.10 USD a leg at 1x) (SCOUTING, placeholder gas)

| Cap | USD a year, 1x | USD a year, 2x | % of 500 USD | % of 5,000 USD | % of 50,000 USD |
|---|---|---|---|---|---|
| limit-only | 0.19 | 0.38 | 0.0381 | 0.0038 | 0.0004 |
| 0.25 | 0.59 | 1.18 | 0.1177 | 0.0118 | 0.0012 |
| 0.5 | 0.92 | 1.83 | 0.1830 | 0.0183 | 0.0018 |
| 1 | 1.44 | 2.88 | 0.2884 | 0.0288 | 0.0029 |
| 2 | 2.13 | 4.25 | 0.4253 | 0.0425 | 0.0043 |
| 4 | 2.82 | 5.64 | 0.5635 | 0.0564 | 0.0056 |
| 8 | 3.52 | 7.05 | 0.7049 | 0.0705 | 0.0070 |
| no cap | 4.33 | 8.67 | 0.8666 | 0.0867 | 0.0087 |

**Binance: gas per customer a year** (mean over rule C's pool; our cost, sponsored; 0.10 USD a leg at 1x) (SCOUTING, placeholder gas)

| Cap | USD a year, 1x | USD a year, 2x | % of 500 USD | % of 5,000 USD | % of 50,000 USD |
|---|---|---|---|---|---|
| limit-only | 0.14 | 0.27 | 0.0274 | 0.0027 | 0.0003 |
| 0.25 | 0.55 | 1.10 | 0.1097 | 0.0110 | 0.0011 |
| 0.5 | 0.87 | 1.74 | 0.1740 | 0.0174 | 0.0017 |
| 1 | 1.37 | 2.75 | 0.2748 | 0.0275 | 0.0027 |
| 2 | 1.99 | 3.98 | 0.3982 | 0.0398 | 0.0040 |
| 4 | 2.61 | 5.22 | 0.5219 | 0.0522 | 0.0052 |
| 8 | 3.22 | 6.43 | 0.6432 | 0.0643 | 0.0064 |
| no cap | 3.83 | 7.66 | 0.7658 | 0.0766 | 0.0077 |

## Per crypto share, at the headline band and cap (SCOUTING)

`decision.json`, `per_share`: band 0.50 with cap 1, 12-month windows, 5,000 USD and 1x for the counts, fees at each
wallet size at 1x. "Limit fixes inside the wait" counts trades a Steady limit forced while the cap's wait was running.

**Kraken, at the headline band 0.50 and cap 1** (rolling windows, 5,000 USD, 1x; fees at each wallet size, 1x) (SCOUTING)

| Crypto share s | pairs | Rebalances per 30 days, median | ... without limit fixes | Most in any 30 days, median | ... worst | Limit fixes inside the wait a year, median | ... worst | Days out of band a year, median | Fees % a year, 500 USD | 5,000 USD | 50,000 USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 300 | 0.247 | 0.247 | 1 | 1 | 0.0 | 0.0 | 3.0 | 0.045 | 0.052 | 0.079 |
| 0.30 | 300 | 0.165 | 0.165 | 1 | 2 | 0.0 | 1.0 | 2.0 | 0.047 | 0.060 | 0.097 |
| 0.40 | 300 | 0.165 | 0.082 | 1 | 2 | 0.0 | 2.0 | 2.0 | 0.053 | 0.064 | 0.105 |
| 0.50 | 300 | 0.165 | 0.082 | 1 | 3 | 0.0 | 7.0 | 1.0 | 0.047 | 0.059 | 0.102 |
| 0.60 | 180 | 0.165 | 0.082 | 1 | 2 | 0.0 | 3.0 | 1.0 | 0.048 | 0.056 | 0.092 |
| 0.70 | 180 | 0.165 | 0.082 | 1 | 4 | 0.0 | 10.0 | 1.0 | 0.048 | 0.062 | 0.101 |
| 0.78 | 60 | 0.495 | 0.000 | 3 | 7 | 3.0 | 22.1 | 0.0 | 0.065 | 0.077 | 0.120 |

**Binance, at the headline band 0.50 and cap 1** (rolling windows, 5,000 USD, 1x; fees at each wallet size, 1x) (SCOUTING)

| Crypto share s | pairs | Rebalances per 30 days, median | ... without limit fixes | Most in any 30 days, median | ... worst | Limit fixes inside the wait a year, median | ... worst | Days out of band a year, median | Fees % a year, 500 USD | 5,000 USD | 50,000 USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 260 | 0.247 | 0.247 | 1 | 1 | 0.0 | 0.0 | 3.0 | 0.037 | 0.043 | 0.067 |
| 0.30 | 260 | 0.165 | 0.165 | 1 | 1 | 0.0 | 0.0 | 2.0 | 0.042 | 0.049 | 0.078 |
| 0.40 | 260 | 0.164 | 0.082 | 1 | 1 | 0.0 | 0.0 | 2.0 | 0.037 | 0.049 | 0.080 |
| 0.50 | 260 | 0.164 | 0.082 | 1 | 2 | 0.0 | 3.0 | 1.0 | 0.036 | 0.048 | 0.080 |
| 0.60 | 156 | 0.082 | 0.082 | 1 | 2 | 0.0 | 2.0 | 1.0 | 0.036 | 0.046 | 0.077 |
| 0.70 | 156 | 0.165 | 0.082 | 1 | 3 | 0.0 | 4.0 | 1.0 | 0.041 | 0.052 | 0.085 |
| 0.78 | 52 | 0.494 | 0.000 | 3 | 6 | 3.5 | 12.0 | 0.0 | 0.049 | 0.059 | 0.095 |

At 78% crypto cash sits 2 points above the 20% floor, so every trade back to the mix was a limit fix (rebalances
without limit fixes: median 0). Mixes up to 70% crypto rebalanced about every 4 to 6 months (median 0.16 to 0.25 a
month; Binance 0.08 at 60% crypto).

## Trade sizes (SCOUTING)

For the auto-trading permission's per-trade and per-day caps and the router's slippage protection, which must allow a
full trade back to the mix (PLAN.md section 15). Percentages are of the wallet just before the fill; they do not
depend on the wallet size or the costs.

**Kraken, 12-month windows: largest single swap / largest one-day turnover, % of the wallet just before the fill, worst over the 60 windows and the mixes of each crypto share (first buy left out; the same at every wallet size and cost level)** (SCOUTING)

| Band | Cap | s 0.20 | s 0.30 | s 0.40 | s 0.50 | s 0.60 | s 0.70 | s 0.78 |
|---|---|---|---|---|---|---|---|---|
| 0.05 | no cap | 8.0 / 8.0 | 11.1 / 11.1 | 13.4 / 13.4 | 14.8 / 14.8 | 11.7 / 14.4 | 13.4 / 16.1 | 8.5 / 13.0 |
| 0.05 | 8 | 12.5 / 12.5 | 15.2 / 15.2 | 16.2 / 17.9 | 16.3 / 20.0 | 15.7 / 23.1 | 16.6 / 26.1 | 12.3 / 20.8 |
| 0.05 | 4 | 13.3 / 13.3 | 16.1 / 16.7 | 17.1 / 17.2 | 16.8 / 20.6 | 20.3 / 25.5 | 15.4 / 25.8 | 12.3 / 20.8 |
| 0.05 | 2 | 16.6 / 16.6 | 24.1 / 27.5 | 23.4 / 26.4 | 23.6 / 29.7 | 23.2 / 33.9 | 24.0 / 38.0 | 12.3 / 20.8 |
| 0.05 | 1 | 23.3 / 23.3 | 30.6 / 30.6 | 32.9 / 35.5 | 27.6 / 34.8 | 28.1 / 38.7 | 28.9 / 47.3 | 12.3 / 20.8 |
| 0.05 | 0.5 | 37.5 / 37.5 | 37.8 / 38.5 | 37.2 / 38.5 | 32.7 / 41.8 | 33.9 / 49.3 | 28.9 / 47.3 | 15.6 / 23.5 |
| 0.05 | 0.25 | 52.6 / 54.4 | 49.0 / 52.3 | 51.5 / 61.5 | 44.0 / 57.0 | 38.2 / 55.7 | 28.2 / 46.1 | 20.6 / 26.9 |
| 0.10 | no cap | 8.0 / 8.0 | 12.8 / 12.8 | 15.6 / 15.6 | 17.4 / 17.4 | 13.9 / 17.1 | 12.9 / 16.5 | 10.8 / 17.2 |
| 0.10 | 8 | 12.5 / 12.5 | 15.2 / 15.2 | 16.2 / 17.9 | 17.4 / 20.0 | 15.7 / 23.1 | 12.9 / 16.5 | 10.8 / 17.2 |
| 0.10 | 4 | 13.3 / 13.3 | 16.1 / 16.1 | 17.1 / 17.1 | 17.4 / 22.9 | 20.3 / 25.5 | 16.4 / 27.3 | 11.2 / 19.7 |
| 0.10 | 2 | 19.3 / 19.3 | 22.7 / 23.6 | 23.4 / 27.3 | 25.1 / 31.9 | 24.2 / 36.3 | 26.4 / 42.4 | 12.3 / 21.6 |
| 0.10 | 1 | 26.2 / 26.2 | 29.6 / 29.6 | 29.1 / 32.5 | 27.2 / 34.8 | 28.1 / 38.7 | 26.4 / 42.4 | 12.3 / 21.6 |
| 0.10 | 0.5 | 42.6 / 42.6 | 40.6 / 40.6 | 40.2 / 43.4 | 32.7 / 41.8 | 33.9 / 49.3 | 28.2 / 46.3 | 15.6 / 23.5 |
| 0.10 | 0.25 | 53.1 / 55.4 | 55.9 / 61.8 | 47.7 / 55.3 | 40.4 / 54.3 | 38.2 / 55.7 | 26.4 / 42.4 | 19.5 / 26.9 |
| 0.15 | no cap | 8.9 / 8.9 | 13.7 / 13.7 | 16.7 / 16.7 | 17.9 / 17.9 | 17.0 / 21.2 | 18.2 / 21.7 | 12.3 / 20.8 |
| 0.15 | 8 | 12.5 / 12.5 | 13.7 / 13.7 | 16.7 / 16.7 | 17.9 / 20.0 | 17.0 / 23.1 | 18.2 / 21.7 | 12.3 / 20.8 |
| 0.15 | 4 | 13.3 / 13.3 | 16.1 / 16.7 | 16.7 / 19.9 | 17.9 / 23.4 | 20.3 / 27.1 | 18.8 / 30.6 | 12.3 / 20.8 |
| 0.15 | 2 | 19.3 / 19.3 | 22.6 / 22.8 | 22.8 / 26.4 | 25.1 / 31.1 | 22.3 / 34.1 | 23.4 / 38.2 | 12.3 / 21.6 |
| 0.15 | 1 | 26.2 / 26.2 | 32.3 / 32.3 | 33.0 / 38.6 | 27.5 / 34.8 | 32.8 / 48.9 | 26.4 / 40.8 | 12.3 / 21.6 |
| 0.15 | 0.5 | 42.6 / 42.6 | 40.6 / 40.9 | 40.2 / 43.4 | 35.7 / 45.9 | 32.8 / 48.9 | 28.2 / 46.3 | 16.0 / 23.5 |
| 0.15 | 0.25 | 53.9 / 56.1 | 55.9 / 61.8 | 48.9 / 57.2 | 40.4 / 52.1 | 38.3 / 56.6 | 28.4 / 46.1 | 19.5 / 30.4 |
| 0.20 | no cap | 9.8 / 9.8 | 13.1 / 13.6 | 18.7 / 18.7 | 22.5 / 22.5 | 18.4 / 22.4 | 18.2 / 21.7 | 12.3 / 20.8 |
| 0.20 | 8 | 12.5 / 12.5 | 15.2 / 15.2 | 18.7 / 18.7 | 22.5 / 22.5 | 18.4 / 23.1 | 18.2 / 26.1 | 12.3 / 20.8 |
| 0.20 | 4 | 11.0 / 11.0 | 16.1 / 16.7 | 18.7 / 19.9 | 22.5 / 23.4 | 18.4 / 27.1 | 18.2 / 27.3 | 12.3 / 20.8 |
| 0.20 | 2 | 18.3 / 18.3 | 19.8 / 19.8 | 23.4 / 23.4 | 23.6 / 28.7 | 20.3 / 29.1 | 24.0 / 37.4 | 12.3 / 21.6 |
| 0.20 | 1 | 28.1 / 28.1 | 31.4 / 31.4 | 31.3 / 36.7 | 29.5 / 40.7 | 31.5 / 47.4 | 26.8 / 45.6 | 12.3 / 21.6 |
| 0.20 | 0.5 | 40.6 / 40.6 | 39.5 / 40.5 | 34.1 / 40.9 | 35.7 / 45.9 | 31.5 / 47.4 | 27.8 / 44.8 | 16.0 / 23.5 |
| 0.20 | 0.25 | 53.9 / 56.1 | 55.9 / 61.8 | 48.9 / 57.2 | 41.0 / 52.1 | 38.3 / 56.6 | 27.0 / 42.8 | 20.8 / 28.0 |
| 0.30 | no cap | 10.8 / 10.9 | 16.0 / 16.0 | 19.8 / 19.8 | 22.5 / 22.5 | 17.8 / 21.5 | 18.2 / 26.1 | 14.4 / 27.1 |
| 0.30 | 8 | 12.5 / 12.5 | 16.0 / 16.0 | 19.8 / 19.8 | 22.5 / 22.5 | 17.8 / 21.5 | 18.2 / 26.1 | 14.4 / 27.1 |
| 0.30 | 4 | 11.2 / 12.4 | 16.0 / 16.0 | 19.8 / 19.9 | 22.5 / 23.4 | 20.3 / 27.1 | 18.2 / 27.3 | 14.4 / 27.1 |
| 0.30 | 2 | 16.5 / 17.6 | 22.6 / 22.6 | 22.8 / 26.4 | 22.5 / 29.7 | 22.3 / 34.1 | 22.2 / 36.2 | 13.2 / 24.5 |
| 0.30 | 1 | 29.6 / 29.6 | 32.2 / 32.2 | 30.1 / 32.5 | 27.2 / 34.8 | 28.1 / 38.7 | 28.2 / 46.1 | 13.2 / 24.5 |
| 0.30 | 0.5 | 42.6 / 42.6 | 40.6 / 40.6 | 40.2 / 43.4 | 34.4 / 45.1 | 33.9 / 49.3 | 28.2 / 46.1 | 15.6 / 24.5 |
| 0.30 | 0.25 | 52.0 / 54.0 | 53.7 / 60.1 | 46.4 / 52.6 | 39.7 / 48.4 | 33.9 / 49.3 | 28.2 / 46.1 | 19.2 / 26.9 |
| 0.50 | no cap | 14.5 / 14.5 | 21.1 / 21.1 | 24.9 / 24.9 | 26.9 / 28.7 | 24.7 / 29.4 | 28.2 / 37.4 | 21.5 / 30.1 |
| 0.50 | 8 | 14.5 / 14.5 | 21.1 / 21.1 | 24.9 / 24.9 | 26.9 / 28.7 | 24.7 / 29.4 | 28.2 / 37.4 | 21.5 / 30.1 |
| 0.50 | 4 | 14.5 / 14.5 | 21.1 / 21.1 | 24.9 / 24.9 | 26.9 / 28.7 | 24.7 / 29.4 | 28.2 / 37.4 | 21.5 / 30.1 |
| 0.50 | 2 | 15.9 / 15.9 | 22.6 / 22.6 | 24.9 / 26.9 | 26.9 / 29.7 | 24.7 / 33.8 | 28.2 / 37.4 | 21.5 / 30.1 |
| 0.50 | 1 | 26.5 / 26.5 | 33.2 / 33.2 | 32.9 / 35.5 | 27.6 / 34.7 | 26.5 / 39.4 | 28.2 / 46.1 | 21.5 / 30.1 |
| 0.50 | 0.5 | 40.6 / 40.6 | 34.5 / 37.5 | 33.6 / 40.2 | 34.4 / 45.1 | 31.0 / 44.4 | 28.2 / 46.1 | 21.5 / 30.1 |
| 0.50 | 0.25 | 53.1 / 55.4 | 55.9 / 61.8 | 47.7 / 55.3 | 43.7 / 56.7 | 31.0 / 44.4 | 28.2 / 46.1 | 21.5 / 30.1 |

**Kraken, 12-month windows: smallest swap in USD on a 500 USD wallet at 1x, smallest over the windows and the mixes of each crypto share** (first buy left out; it scales with the wallet size: ×10 at 5,000 USD, ×100 at 50,000 USD, roughly) (SCOUTING)

| Band | Cap | s 0.20 | s 0.30 | s 0.40 | s 0.50 | s 0.60 | s 0.70 | s 0.78 |
|---|---|---|---|---|---|---|---|---|
| 0.05 | no cap | 0.0007 | 0.0020 | 0.0050 | 0.0008 | 0.0005 | 0.0008 | 0.0307 |
| 0.05 | 8 | 0.0030 | 0.0014 | 0.0005 | 0.0058 | 0.0029 | 0.0008 | 0.0610 |
| 0.05 | 4 | 0.0006 | 0.0027 | 0.0016 | 0.0033 | 0.0002 | 0.0008 | 0.0613 |
| 0.05 | 2 | 0.0005 | 0.0016 | 0.0051 | 0.0025 | 0.0053 | 0.0012 | 0.0746 |
| 0.05 | 1 | 0.0019 | 0.0019 | 0.0051 | 0.0004 | 0.0232 | 0.0093 | 0.0321 |
| 0.05 | 0.5 | 0.0046 | 0.0370 | 0.0051 | 0.0105 | 0.0344 | 0.0248 | 0.11 |
| 0.05 | 0.25 | 0.0046 | 0.0074 | 0.0051 | 0.0105 | 0.0344 | 0.0030 | 0.0749 |
| 0.10 | no cap | 0.0039 | 0.0040 | 0.0027 | 0.0056 | 0.0109 | 0.0248 | 0.10 |
| 0.10 | 8 | 0.0040 | 0.0027 | 0.0005 | 0.0056 | 0.0109 | 0.0165 | 0.10 |
| 0.10 | 4 | 0.0072 | 0.0083 | 0.0027 | 0.0056 | 0.0241 | 0.0058 | 0.10 |
| 0.10 | 2 | 0.0010 | 0.0069 | 0.0027 | 0.0054 | 0.0108 | 0.0248 | 0.10 |
| 0.10 | 1 | 0.0074 | 0.0016 | 0.0027 | 0.0056 | 0.0241 | 0.0022 | 0.0539 |
| 0.10 | 0.5 | 0.0244 | 0.0175 | 0.0027 | 0.0056 | 0.0092 | 0.0248 | 0.0682 |
| 0.10 | 0.25 | 0.0120 | 0.0175 | 0.0027 | 0.0056 | 0.0241 | 0.0040 | 0.0643 |
| 0.15 | no cap | 0.0308 | 0.0101 | 0.0068 | 0.0096 | 0.0188 | 0.0248 | 0.19 |
| 0.15 | 8 | 0.0224 | 0.0101 | 0.0068 | 0.0096 | 0.0188 | 0.0248 | 0.19 |
| 0.15 | 4 | 0.0094 | 0.0111 | 0.0198 | 0.0096 | 0.0188 | 0.0248 | 0.19 |
| 0.15 | 2 | 0.0156 | 0.0175 | 0.0033 | 0.0014 | 0.0188 | 0.0248 | 0.19 |
| 0.15 | 1 | 0.0061 | 0.0175 | 0.0115 | 0.0096 | 0.0188 | 0.0248 | 0.21 |
| 0.15 | 0.5 | 0.0016 | 0.0175 | 0.0409 | 0.0100 | 0.0273 | 0.0248 | 0.21 |
| 0.15 | 0.25 | 0.0120 | 0.0175 | 0.0409 | 0.0449 | 0.11 | 0.0248 | 0.0986 |
| 0.20 | no cap | 0.0164 | 0.0374 | 0.0081 | 0.0160 | 0.0063 | 0.0130 | 0.18 |
| 0.20 | 8 | 0.0164 | 0.0374 | 0.0081 | 0.0160 | 0.0063 | 0.0130 | 0.18 |
| 0.20 | 4 | 0.0164 | 0.0037 | 0.0081 | 0.0160 | 0.0063 | 0.0130 | 0.18 |
| 0.20 | 2 | 0.0171 | 0.0171 | 0.0125 | 0.0160 | 0.0063 | 0.0130 | 0.18 |
| 0.20 | 1 | 0.0023 | 0.0098 | 0.0125 | 0.0579 | 0.0127 | 0.0130 | 0.21 |
| 0.20 | 0.5 | 0.0184 | 0.0206 | 0.0364 | 0.0579 | 0.0127 | 0.0401 | 0.21 |
| 0.20 | 0.25 | 0.0120 | 0.0077 | 0.0364 | 0.0579 | 0.0127 | 0.0435 | 0.0986 |
| 0.30 | no cap | 0.0268 | 0.0423 | 0.0624 | 0.0677 | 0.0266 | 0.0513 | 0.0986 |
| 0.30 | 8 | 0.0268 | 0.0423 | 0.0624 | 0.0231 | 0.0266 | 0.0513 | 0.0986 |
| 0.30 | 4 | 0.0268 | 0.0423 | 0.0624 | 0.10 | 0.0266 | 0.0513 | 0.0986 |
| 0.30 | 2 | 0.0268 | 0.0381 | 0.0859 | 0.11 | 0.0266 | 0.0513 | 0.0986 |
| 0.30 | 1 | 0.0032 | 0.0433 | 0.0520 | 0.11 | 0.0266 | 0.0513 | 0.0986 |
| 0.30 | 0.5 | 0.0147 | 0.0234 | 0.0680 | 0.0289 | 0.0448 | 0.0447 | 0.0986 |
| 0.30 | 0.25 | 0.0268 | 0.0681 | 0.0859 | 0.11 | 0.0448 | 0.0513 | 0.0792 |
| 0.50 | no cap | 0.0075 | 0.0353 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 8 | 0.0075 | 0.0353 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 4 | 0.0075 | 0.0353 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 2 | 0.0067 | 0.0353 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 1 | 0.0075 | 0.0499 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 0.5 | 0.0075 | 0.0499 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |
| 0.50 | 0.25 | 0.0075 | 0.0499 | 0.0113 | 0.0129 | 0.0946 | 0.0296 | 0.0986 |

**Every band and cap, both scopes (12-month windows and the full runs), per crypto share: largest swap / largest one-day turnover (% of the wallet), smallest swap (USD, 500 USD wallet, 1x), and the first buy's legs** (SCOUTING)

| s | Kraken tool | Kraken limit-only | Kraken smallest swap | Binance tool | Binance limit-only | Binance smallest swap | First buy: largest leg / total (%) | First buy: smallest leg (USD, 500 USD wallet) |
|---|---|---|---|---|---|---|---|---|
| 0.20 | 53.9 / 56.1 | 56.9 / 60.3 | 0.0005 | 39.1 / 39.1 | 46.1 / 52.8 | 0.0006 | 20.0 / 20.0 | 25.00 |
| 0.30 | 55.9 / 61.8 | 56.0 / 63.6 | 0.0014 | 33.5 / 39.9 | 42.4 / 51.0 | 0.0001 | 30.0 / 30.0 | 37.50 |
| 0.40 | 51.5 / 61.5 | 50.8 / 60.8 | 0.0005 | 32.9 / 38.8 | 34.7 / 41.0 | 0.0004 | 40.0 / 40.0 | 50.00 |
| 0.50 | 44.0 / 57.0 | 44.7 / 59.3 | 0.0004 | 29.6 / 31.6 | 35.2 / 41.9 | 0.0002 | 50.0 / 50.0 | 62.50 |
| 0.60 | 38.3 / 56.6 | 38.3 / 55.3 | 0.0002 | 30.9 / 45.7 | 25.6 / 30.9 | 0.0003 | 45.0 / 60.0 | 75.00 |
| 0.70 | 28.9 / 47.3 | 28.2 / 46.1 | 0.0008 | 27.7 / 44.9 | 20.5 / 29.9 | 0.0010 | 52.5 / 70.0 | 87.50 |
| 0.78 | 21.5 / 30.4 | 19.9 / 36.6 | 0.0307 | 21.8 / 30.8 | 16.1 / 30.1 | 0.0214 | 39.0 / 78.0 | 195.00 |

- The largest single swap of the tool was **55.9%** of the wallet, and the largest one-day turnover **61.8%** (Kraken,
  30% crypto, BTC share 0.75, cap 0.25, window k = 0: 2017, when BTC alone rose 1304%). Limit-only reached 56.9% and
  63.6%. The first buy is up to 52.5% of the wallet in one swap and 78% in one day.
- The smallest swaps were tiny: about 0.00005 USD on a 500 USD wallet (Binance, 30% crypto, band 0.05, no cap,
  doubled costs; runs.parquet), each still paying the full 0.10 USD of gas. A minimum swap size is not modelled
  (Known weaknesses).

## Comparisons: each recommended setting against no cap and limit-only (SCOUTING)

Medians over the pairs of the 12-month windows at 5,000 USD and 1x, read from `runs.parquet` for this file (the run
stores every run's differences from no cap and from limit-only, same mix, window, wallet size and costs). Limit-only
buys the mix once and trades only at a Steady limit; its days out of band depend on the band
(`limit_only_bands.parquet`; rule C's tables give its mean, 234.8 days a year on Kraken and 232.3 on Binance).

**Kraken: each recommended setting and its comparators, 12-month windows, 5,000 USD, 1x (medians over the pairs; the 10th percentiles are the bad tails)** — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years, in-sample, reference engine, placeholder costs. Returns and Sharpe ratios are descriptions only; no rule used them. Falls: see the falls tables.

| Setting | pairs | Rebalances / 30 days | Customer fees % a year | Gas USD a year | Days out of band a year | d̄ | Return % (median) | Return % (10th pct) | Sharpe (median) | Sharpe (10th pct) |
|---|---|---|---|---|---|---|---|---|---|---|
| b 0.10, cap 8 | 1620 | 2.225 | 0.159 | 4.80 | 32.0 | 0.052 | 25.4 | -27.1 | 0.91 | -0.87 |
| b 0.10, cap no cap (comparator) | 1620 | 2.308 | 0.163 | 5.00 | 28.1 | 0.051 | 25.6 | -27.3 | 0.93 | -0.87 |
| b 0.15, cap 4 | 1620 | 1.233 | 0.127 | 2.61 | 20.1 | 0.072 | 25.9 | -26.9 | 0.93 | -0.86 |
| b 0.15, cap no cap (comparator) | 1620 | 1.236 | 0.127 | 2.61 | 15.0 | 0.069 | 26.5 | -27.3 | 0.93 | -0.85 |
| b 0.20, cap 4 | 1620 | 0.824 | 0.110 | 1.80 | 11.0 | 0.090 | 27.3 | -26.2 | 0.96 | -0.86 |
| b 0.20, cap no cap (comparator) | 1620 | 0.824 | 0.111 | 1.80 | 9.0 | 0.088 | 27.7 | -26.4 | 0.95 | -0.86 |
| b 0.30, cap 2 | 1620 | 0.412 | 0.087 | 0.80 | 5.0 | 0.131 | 27.8 | -26.6 | 0.97 | -0.89 |
| b 0.30, cap no cap (comparator) | 1620 | 0.412 | 0.087 | 0.80 | 5.0 | 0.127 | 28.1 | -26.2 | 0.97 | -0.88 |
| b 0.50, cap 1 | 1620 | 0.165 | 0.058 | 0.40 | 2.0 | 0.202 | 24.5 | -24.1 | 0.89 | -0.89 |
| b 0.50, cap no cap (comparator) | 1620 | 0.165 | 0.059 | 0.40 | 2.0 | 0.198 | 24.6 | -24.2 | 0.90 | -0.89 |
| b 0.05, cap no cap (0.05 has no usable cap) | 1620 | 5.934 | 0.238 | 12.60 | 72.2 | 0.033 | not shown (not a recommended setting; PLAN.md section 2) |  |  |  |
| limit-only (comparator) | 1620 | 0.000 | 0.000 | 0.00 | see note | 0.338 | 21.9 | -23.8 | 0.73 | -1.05 |

**Kraken: the recommended setting minus each comparator, run by run (median of the differences; same mix, window, wallet size and costs; 5,000 USD, 1x)**. Rebalances and legs are counts per 12-month window. SCOUTING, hypothetical, in-sample.

| Setting | vs no cap: rebalances | legs | fees | days out | d̄ | return (pts) | Sharpe | vs limit-only: rebalances | fees | days out | d̄ | return (pts) | Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b 0.10, cap 8 | -1.0 | -2.0 | -0.003 | 3.0 | 0.001 | 0.00 | 0.000 | 26.0 | 0.132 | -278.0 | -0.285 | -0.05 | 0.146 |
| b 0.15, cap 4 | 0.0 | 0.0 | 0.000 | 6.0 | 0.003 | 0.00 | 0.000 | 14.0 | 0.099 | -256.7 | -0.266 | 0.63 | 0.160 |
| b 0.20, cap 4 | 0.0 | 0.0 | 0.000 | 1.0 | 0.000 | 0.00 | 0.000 | 9.0 | 0.084 | -241.7 | -0.248 | 1.36 | 0.168 |
| b 0.30, cap 2 | 0.0 | 0.0 | 0.000 | 0.0 | 0.000 | 0.00 | 0.000 | 4.0 | 0.059 | -177.2 | -0.205 | 0.36 | 0.175 |
| b 0.50, cap 1 | 0.0 | 0.0 | 0.000 | 0.0 | 0.000 | 0.00 | 0.000 | 1.0 | 0.023 | -68.8 | -0.129 | 0.00 | 0.046 |

**Binance: each recommended setting and its comparators, 12-month windows, 5,000 USD, 1x (medians over the pairs; the 10th percentiles are the bad tails)** — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years, in-sample, reference engine, placeholder costs. Returns and Sharpe ratios are descriptions only; no rule used them. Falls: see the falls tables.

| Setting | pairs | Rebalances / 30 days | Customer fees % a year | Gas USD a year | Days out of band a year | d̄ | Return % (median) | Return % (10th pct) | Sharpe (median) | Sharpe (10th pct) |
|---|---|---|---|---|---|---|---|---|---|---|
| b 0.10, cap 8 | 1404 | 2.060 | 0.150 | 4.41 | 29.1 | 0.052 | 16.7 | -30.4 | 0.73 | -0.97 |
| b 0.10, cap no cap (comparator) | 1404 | 2.143 | 0.155 | 4.61 | 26.0 | 0.050 | 16.6 | -30.4 | 0.73 | -0.97 |
| b 0.15, cap 4 | 1404 | 1.151 | 0.120 | 2.41 | 19.1 | 0.070 | 17.1 | -30.2 | 0.74 | -0.96 |
| b 0.15, cap no cap (comparator) | 1404 | 1.154 | 0.121 | 2.51 | 14.0 | 0.068 | 17.6 | -30.3 | 0.75 | -0.97 |
| b 0.20, cap 4 | 1404 | 0.742 | 0.103 | 1.60 | 10.0 | 0.089 | 18.2 | -29.2 | 0.78 | -0.96 |
| b 0.20, cap no cap (comparator) | 1404 | 0.742 | 0.103 | 1.60 | 9.0 | 0.087 | 18.5 | -29.2 | 0.78 | -0.96 |
| b 0.30, cap 2 | 1404 | 0.411 | 0.078 | 0.80 | 4.0 | 0.129 | 18.9 | -29.1 | 0.78 | -0.97 |
| b 0.30, cap no cap (comparator) | 1404 | 0.411 | 0.079 | 0.80 | 4.0 | 0.127 | 19.1 | -28.9 | 0.78 | -0.96 |
| b 0.50, cap 1 | 1404 | 0.165 | 0.048 | 0.30 | 1.0 | 0.199 | 17.2 | -25.6 | 0.72 | -0.97 |
| b 0.50, cap no cap (comparator) | 1404 | 0.165 | 0.048 | 0.30 | 1.0 | 0.196 | 17.2 | -25.6 | 0.73 | -0.97 |
| b 0.05, cap no cap (0.05 has no usable cap) | 1404 | 5.440 | 0.222 | 12.00 | 66.2 | 0.033 | not shown (not a recommended setting; PLAN.md section 2) |  |  |  |
| limit-only (comparator) | 1404 | 0.000 | 0.000 | 0.00 | see note | 0.319 | 12.2 | -25.7 | 0.54 | -1.14 |

**Binance: the recommended setting minus each comparator, run by run (median of the differences; same mix, window, wallet size and costs; 5,000 USD, 1x)**. Rebalances and legs are counts per 12-month window. SCOUTING, hypothetical, in-sample.

| Setting | vs no cap: rebalances | legs | fees | days out | d̄ | return (pts) | Sharpe | vs limit-only: rebalances | fees | days out | d̄ | return (pts) | Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b 0.10, cap 8 | -1.0 | -1.0 | -0.002 | 3.0 | 0.001 | 0.00 | 0.000 | 24.0 | 0.128 | -283.9 | -0.268 | 1.03 | 0.161 |
| b 0.15, cap 4 | 0.0 | 0.0 | 0.000 | 5.0 | 0.002 | 0.00 | 0.000 | 13.0 | 0.099 | -261.7 | -0.251 | 1.81 | 0.179 |
| b 0.20, cap 4 | 0.0 | 0.0 | 0.000 | 1.0 | 0.000 | 0.00 | 0.000 | 8.0 | 0.084 | -241.7 | -0.232 | 2.69 | 0.184 |
| b 0.30, cap 2 | 0.0 | 0.0 | 0.000 | 0.0 | 0.000 | 0.00 | 0.000 | 4.0 | 0.060 | -175.2 | -0.186 | 1.56 | 0.187 |
| b 0.50, cap 1 | 0.0 | 0.0 | 0.000 | 0.0 | 0.000 | 0.00 | 0.000 | 1.0 | 0.025 | -60.2 | -0.116 | 0.00 | 0.049 |

The recommended caps cost little against no cap: the median pair made the same number of rebalances (one fewer at
0.10) and spent a few more days a year out of band (0 to 6). Against limit-only, the tool keeps mixes much closer to
target (d̄ lower by 0.12 to 0.29, that is 12 to 29% of the target) for 0.02 to 0.13% of the wallet a year in fees.

## Full runs, with and without the yearly reset (SCOUTING)

One run per configuration over each whole panel (Kraken 2017-01-02 .. 2023-01-01, Binance 2017-08-18 .. 2023-01-01),
with no reset and with a reset after 365 days without any trade (PLAN.md section 4.2, step 5). Medians over the 27
mixes of each band and cap, read from `runs.csv`; Δ = with the reset minus without, fees at 5,000 USD and 1x. Every
configuration is in `runs.csv`.

Bands where the reset never fired in any mix or cap, on either source: 0.05, 0.10, 0.15 (their rows are identical
with and without it).

| Band | Cap | Kraken: mixes where it fired | resets: median (most) | Δ fees % a year | Δ days out a year | Δ d̄ | Binance: mixes where it fired | resets: median (most) | Δ fees | Δ days out | Δ d̄ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.20 | no cap | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 8 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 4 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 2 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 1 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 0.5 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 | 0 of 27 | 0 (0) | 0.0000 | 0.00 | 0.0000 |
| 0.20 | 0.25 | 1 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 | 1 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | no cap | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 5 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 8 | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 5 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 4 | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 5 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 2 | 7 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 6 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 1 | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 5 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 0.5 | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 4 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 |
| 0.30 | 0.25 | 5 of 27 | 0 (2) | 0.0000 | 0.00 | 0.0000 | 4 of 27 | 0 (1) | 0.0000 | 0.00 | 0.0000 |
| 0.50 | no cap | 27 of 27 | 2 (3) | 0.0013 | 0.00 | -0.0050 | 26 of 27 | 2 (3) | 0.0018 | 0.00 | -0.0046 |
| 0.50 | 8 | 27 of 27 | 2 (3) | 0.0013 | 0.00 | -0.0050 | 26 of 27 | 2 (3) | 0.0018 | 0.00 | -0.0046 |
| 0.50 | 4 | 27 of 27 | 2 (3) | 0.0013 | 0.00 | -0.0050 | 26 of 27 | 2 (3) | 0.0018 | 0.00 | -0.0068 |
| 0.50 | 2 | 26 of 27 | 2 (3) | 0.0013 | 0.00 | -0.0070 | 25 of 27 | 2 (3) | 0.0018 | 0.00 | -0.0046 |
| 0.50 | 1 | 23 of 27 | 2 (3) | 0.0009 | 0.00 | -0.0013 | 24 of 27 | 2 (3) | 0.0000 | 0.00 | -0.0004 |
| 0.50 | 0.5 | 22 of 27 | 2 (3) | 0.0000 | 0.00 | 0.0000 | 22 of 27 | 1 (3) | 0.0000 | 0.00 | -0.0006 |
| 0.50 | 0.25 | 18 of 27 | 1 (3) | 0.0000 | 0.00 | 0.0000 | 17 of 27 | 1 (3) | 0.0000 | 0.00 | 0.0000 |

The reset hardly ever fired: it waits for 365 days without any trade, and narrower bands always traded sooner. At band
0.30 it fired in 4 to 7 of the 27 mixes, at most twice. At band 0.50 it fired in 17 to 27 of them, typically twice in
the six years; in the median mix it kept the mix slightly closer (d̄ lower by up to 0.007) and cost at most 0.002% of
the wallet a year. The median days out of band did not change.

## Robustness (SCOUTING)

| Check | What changed | Headline effect |
|---|---|---|
| Costs doubled | Fees only. Closeness and counts are identical: the per-run path hash agreed across the 6 cost settings of every configuration (134,622 configurations with 6 settings each) | b\*(50,000 USD) 0.20 → 0.50 (Kraken), 0.30 (Binance). Rule C unchanged (SUPPORTED at 2x on both sources) |
| Binance instead of Kraken | N\*(0.50) 0.5 instead of 1; everything else equal at 1x. At 2x, Binance's 50,000 USD band is 0.30 against Kraken's 0.50 | None from N\* (the robust value takes the larger); the 50,000 USD band takes Kraken's 0.50 |
| Kraken on Binance's 52 windows | N\*(0.20) 2, N\*(0.50) 0.5, b\*(50,000, 2x) 0.30 | The two values that differ between the sources take Binance's value, so the Binance difference comes from the early-2017 windows Binance lacks. N\*(0.20) = 2 differs from both sources (the knife-edge above) |
| The other first-buy reading (A1) | Binance N\*(0.50) 1 | None |
| Other readings of the 60% limit | 60% also caps cash (12 mixes): default 0.15 with cap 4 at 1x, 0.50 at 2x. 60% caps the two coins together (20 mixes): 0.20 with cap 4 | Limit at 2, SUPPORTED, under both |
| Window start year; non-overlapping windows | Most bands fail their cap in the 2017-start windows; on Kraken's 5 non-overlapping windows 0.15 with cap 4 fails (90th percentile 30.7) | 0.50 with cap 1 passes in every start year and on the non-overlapping windows |
| Boom years (A5) | See the addendum | Limit at 2 and its value test hold in all 8 removals; the default band holds only without 2021 or 2022 |

**Kraken on Binance's 52 windows** (`decision.json`, `kraken_on_binance_windows`; computed because the label is NOT
ROBUST) (SCOUTING)

| Pool | N\*(0.05) | N\*(0.10) | N\*(0.15) | N\*(0.20) | N\*(0.30) | N\*(0.50) | b\* 1x (500 / 5,000 / 50,000) | b\* 2x (500 / 5,000 / 50,000) | Rule C (5,000 USD, 1x) |
|---|---|---|---|---|---|---|---|---|---|
| Kraken, all 60 windows | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 / 0.2 / 0.2 | 0.2 / 0.2 / 0.5 | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Kraken on Binance's 52 windows | more than 8 | 8 | 4 | 2 | 2 | 0.5 | 0.2 / 0.2 / 0.2 | 0.2 / 0.2 / 0.3 | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Binance, 52 windows | more than 8 | 8 | 4 | 4 | 2 | 0.5 | 0.2 / 0.2 / 0.2 | 0.2 / 0.2 / 0.3 | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |

**Other readings of the Steady limits** (PLAN.md section 9: only the mixes each reading would keep; the extra limit
trades they would add are not simulated) (SCOUTING)

| Source | Mixes kept | N\*(0.05) | N\*(0.10) | N\*(0.15) | N\*(0.20) | N\*(0.30) | N\*(0.50) | App default 1x | App default 2x | Rule C (5,000 USD, 1x) |
|---|---|---|---|---|---|---|---|---|---|---|
| Kraken | 60% also caps cash (12 mixes, s ≥ 0.42) | more than 8 | 8 | 4 | 2 | 1 | 0.5 | 0.15 (cap 4) | 0.5 (cap 0.5) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Kraken | 60% caps BTC + ETH together (20 mixes, s ≤ 0.58) | more than 8 | 8 | 8 | 4 | 2 | 1 | 0.2 (cap 4) | 0.5 (cap 1) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Kraken | lab's reading (27 mixes) | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 (cap 4) | 0.5 (cap 1) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Binance | 60% also caps cash (12 mixes, s ≥ 0.42) | more than 8 | 8 | 4 | 2 | 1 | 0.25 | 0.15 (cap 4) | 0.5 (cap 0.25) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Binance | 60% caps BTC + ETH together (20 mixes, s ≤ 0.58) | more than 8 | 8 | 4 | 4 | 2 | 1 | 0.2 (cap 4) | 0.3 (cap 2) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |
| Binance | lab's reading (27 mixes) | more than 8 | 8 | 4 | 4 | 2 | 0.5 | 0.2 (cap 4) | 0.3 (cap 2) | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED |

**Few independent years** (rule B's numbers by window start year) (SCOUTING)

**Kraken: extra days out of band at each band's recommended cap (cap 8 for 0.05), by window start year, and on the non-overlapping windows k = 0, 12, 24, 36, 48** (median / 90th percentile; ✗ = fails rule B's test there) (SCOUTING)

| Band | Cap | start 2017 | start 2018 | start 2019 | start 2020 | start 2021 | non-overlapping |
|---|---|---|---|---|---|---|---|
| 0.05 | 8 | 36.20 / 51.28 ✗ | 28.08 / 38.10 ✗ | 16.00 / 29.00 ✗ | 32.09 / 52.14 ✗ | 23.06 / 48.83 ✗ | 25.07 / 45.37 ✗ |
| 0.10 | 8 | 10.06 / 22.10 ✗ | 2.01 / 11.06 | 2.00 / 7.00 | 4.01 / 12.03 | 2.01 / 10.03 | 4.01 / 17.68 |
| 0.15 | 4 | 20.11 / 45.25 ✗ | 5.01 / 13.04 | 5.00 / 11.00 | 6.02 / 25.07 | 2.01 / 11.03 | 6.02 / 30.72 ✗ |
| 0.20 | 4 | 9.54 / 27.15 ✗ | 0.00 / 7.02 | 0.00 / 6.70 | 1.00 / 10.03 | 0.00 / 5.01 | 1.01 / 19.05 |
| 0.30 | 2 | 9.05 / 29.81 ✗ | 0.00 / 3.01 | 0.00 / 4.00 | 2.01 / 15.04 | 0.00 / 4.01 | 0.00 / 19.65 |
| 0.50 | 1 | 4.02 / 29.86 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 12.73 | 0.00 / 0.00 | 0.00 / 24.67 |

**Binance: extra days out of band at each band's recommended cap (cap 8 for 0.05), by window start year, and on the non-overlapping windows k = 12, 24, 36, 48** (median / 90th percentile; ✗ = fails rule B's test there) (SCOUTING)

| Band | Cap | start 2017 | start 2018 | start 2019 | start 2020 | start 2021 | non-overlapping |
|---|---|---|---|---|---|---|---|
| 0.05 | 8 | 33.59 / 47.43 ✗ | 25.07 / 40.11 ✗ | 15.00 / 27.07 ✗ | 31.09 / 51.14 ✗ | 23.06 / 47.13 ✗ | 24.53 / 45.12 ✗ |
| 0.10 | 8 | 11.03 / 18.35 ✗ | 3.01 / 11.03 | 2.00 / 7.02 | 4.01 / 13.04 | 2.01 / 10.03 | 4.01 / 12.03 |
| 0.15 | 4 | 15.04 / 34.09 ✗ | 6.02 / 15.04 | 5.00 / 11.00 | 7.01 / 25.07 ✗ | 2.01 / 11.03 | 5.01 / 17.05 |
| 0.20 | 4 | 7.02 / 15.04 ✗ | 0.00 / 7.02 | 0.00 / 8.00 | 2.00 / 9.02 | 0.00 / 5.01 | 1.00 / 8.01 |
| 0.30 | 2 | 6.02 / 20.05 | 0.00 / 3.01 | 0.00 / 4.00 | 2.01 / 14.04 | 0.00 / 4.01 | 0.00 / 5.01 |
| 0.50 | 1 | 1.50 / 18.65 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 13.04 | 0.00 / 0.00 | 0.00 / 0.00 |

The 2017-start windows are the hardest: the 2017 rise moved weights fast, so narrow bands broke again before the wait
ended. In those windows only 0.50 with cap 1 (and 0.30 with cap 2 on Binance) passed.

## Boom-year addendum (owner decision 2026-11-21, PLAN.md A5) (SCOUTING)

ADDENDUM: the decision rules recomputed without each train year and without the best one and two years for BTC;
reported next to the pre-registered headline, never in place of it. Rules B, A and C per source and rule D were
recomputed on the kept windows' logged runs; nothing was rerun. A removal leaving either source fewer than 12 windows
would be MISSING; none did.

**BTC's calendar-year return (by bar day), as written to start.json before any backtest** (the ranking uses Kraken for both sources; Binance's 2017 starts 2017-08-18) (SCOUTING)

| Year | Kraken, % | Binance, % |
|---|---|---|
| 2017 | 1304.4 | 220.1 |
| 2018 | -73.6 | -73.0 |
| 2019 | 94.2 | 94.3 |
| 2020 | 304.0 | 302.0 |
| 2021 | 59.4 | 59.8 |
| 2022 | -64.2 | -64.2 |

**Does each headline value hold without the year(s)?** (windows kept Kraken / Binance) (ADDENDUM, SCOUTING)

| Removal | Windows | N\*(0.05) | N\*(0.1) | N\*(0.15) | N\*(0.2) | N\*(0.3) | N\*(0.5) | b\*(500) | b\*(5000) | b\*(50000) | app default | N_up | value test | CONFLICT | all |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| without 2017 | 48 / 48 | yes | yes | yes | **no** | yes | **no** | yes | yes | **no** | **no** | yes | yes | yes | **no** |
| without 2018 | 37 / 36 | yes | yes | yes | **no** | yes | yes | yes | yes | **no** | **no** | yes | yes | yes | **no** |
| without 2019 | 37 / 29 | yes | yes | **no** | yes | yes | yes | yes | **no** | **no** | **no** | yes | yes | **no** | **no** |
| without 2020 | 37 / 29 | yes | yes | **no** | yes | yes | yes | yes | yes | **no** | **no** | yes | yes | yes | **no** |
| without 2021 | 37 / 29 | yes | yes | **no** | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | **no** |
| without 2022 | 49 / 41 | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| best year (2017) | 48 / 48 | yes | yes | yes | **no** | yes | **no** | yes | yes | **no** | **no** | yes | yes | yes | **no** |
| best two years (2017, 2020) | 25 / 25 | yes | yes | yes | **no** | **no** | **no** | yes | yes | **no** | **no** | yes | yes | yes | **no** |

**What the values become** (N\*_rob for bands 0.05 / 0.10 / 0.15 / 0.20 / 0.30 / 0.50; b\*_rob for 500 / 5,000 / 50,000 USD) (ADDENDUM, SCOUTING)

| Removal | N\*_rob by band | b\*_rob by size | App default | Headline | Flag | Upper limit | CONFLICT | Default under the limit | Label |
|---|---|---|---|---|---|---|---|---|---|
| without 2017 | more than 8 8 4 2 2 0.5 | 0.2 / 0.2 / 0.3 | 0.3 | 0.3, cap 2 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| without 2018 | more than 8 8 4 2 2 1 | 0.2 / 0.2 / 0.3 | 0.3 | 0.3, cap 2 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| without 2019 | more than 8 8 8 4 2 1 | 0.2 / 0.3 / none | none | 0.5, cap 1 | NO BAND MET THE CONDITIONS | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | yes | none (per size 0.3/0.3/none) | NOT ROBUST |
| without 2020 | more than 8 8 8 4 2 1 | 0.2 / 0.2 / 0.3 | 0.3 | 0.3, cap 2 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| without 2021 | more than 8 8 8 4 2 1 | 0.2 / 0.2 / 0.5 | 0.5 | 0.5, cap 1 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| without 2022 | more than 8 8 4 4 2 1 | 0.2 / 0.2 / 0.5 | 0.5 | 0.5, cap 1 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| best year (2017) | more than 8 8 4 2 2 0.5 | 0.2 / 0.2 / 0.3 | 0.3 | 0.3, cap 2 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |
| best two years (2017, 2020) | more than 8 8 4 2 1 0.25 | 0.2 / 0.2 / 0.3 | 0.3 | 0.3, cap 1 |  | EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED | no |  | NOT ROBUST |

- **The upper limit holds in every case:** EVIDENCE FOR A LIMIT AT 2 with the value test SUPPORTED in all 8 removals.
- **The default band does not.** Only removing 2022 keeps every headline value. Without 2017, 2018, 2020 or the best
  two years the app default becomes 0.30 (with cap 2, or cap 1 without the best two years), because the 50,000 USD
  band at 2x moves to 0.30. Without 2019 no band met the conditions for 50,000 USD wallets (flag NO BAND MET THE
  CONDITIONS; the headline then reports 0.50 with cap 1, and CONFLICT). Without 2021 the default stays 0.50.
- Some recommended caps move by a step: N\*(0.15) to 8 without 2019, 2020 or 2021; N\*(0.20) to 2 without 2017, 2018
  or the best two years; N\*(0.30) to 1 and N\*(0.50) to 0.25 without the best two years; N\*(0.50) to 0.5 without
  2017.
- So the upper limit is the steadiest result, and the default band for large wallets the least steady.

## Falls (SCOUTING, hypothetical)

Every table of falls carries this label: **SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years
(the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall the app
shows, and not a drawdown budget.** Falls are positive sizes ("fell X% from its high"); a worst value is the minimum of
the signed number. From `falls.csv` (A3), at the headline band 0.50 and cap 1, 5,000 USD, 1x.

### By crypto share (the worst of its mixes)

**Kraken, by crypto share: the worst of its mixes** (falls as positive sizes, %; headline band 0.50, cap 1, 5,000 USD, 1x; full run 2017-01-02 .. 2023-01-01) — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall the app shows, and not a drawdown budget.

| s | Mix (f) of the worst window | Worst 12-month window fall | Window | Full-run fall | Peak → trough | Full run, yearly reset | Deepest over every band and cap (12-month windows) | Worst day (close) | Worst 7 days |
|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 0.00 | 35.3 | k 11: 2017-12-02 .. 2018-12-01 | 34.0 (f 0.00) | 2018-01-14 → 2018-12-16 | 34.0 | 42.0: f 0.00, b 0.05, cap 0.25, k 11 | 9.3 (2017-03-19, f 0.00) | 11.5 (2020-03-06 → 2020-03-13, f 0.25) |
| 0.30 | 0.00 | 51.1 | k 12: 2018-01-02 .. 2019-01-01 | 46.4 (f 0.00) | 2018-01-14 → 2018-12-16 | 46.4 | 54.3: f 0.00, b 0.05, cap 0.25, k 11 | 12.9 (2020-03-13, f 0.50) | 17.0 (2020-03-06 → 2020-03-13, f 0.50) |
| 0.40 | 0.00 | 61.4 | k 12: 2018-01-02 .. 2019-01-01 | 61.8 (f 0.00) | 2018-01-14 → 2018-12-16 | 61.8 | 64.5: f 0.00, b 0.10, cap 1, k 12 | 17.8 (2020-03-13, f 0.00) | 23.2 (2020-03-06 → 2020-03-13, f 0.00) |
| 0.50 | 0.25 | 64.6 | k 12: 2018-01-02 .. 2019-01-01 | 66.7 (f 0.00) | 2018-01-14 → 2018-12-16 | 66.7 | 72.7: f 0.00, b 0.10, cap 1, k 12 | 19.2 (2020-03-13, f 0.50) | 24.6 (2020-03-06 → 2020-03-13, f 0.50) |
| 0.60 | 0.25 | 72.2 | k 12: 2018-01-02 .. 2019-01-01 | 69.1 (f 0.25) | 2018-01-14 → 2018-12-16 | 69.1 | 74.7: f 0.25, b 0.15, cap 4, k 12 | 23.6 (2020-03-13, f 0.25) | 30.0 (2020-03-06 → 2020-03-13, f 0.25) |
| 0.70 | 0.25 | 75.5 | k 12: 2018-01-02 .. 2019-01-01 | 74.6 (f 0.25) | 2018-01-14 → 2018-12-16 | 74.6 | 80.4: f 0.25, b 0.05, no cap, k 12 | 29.2 (2020-03-13, f 0.25) | 36.3 (2020-03-06 → 2020-03-13, f 0.25) |
| 0.78 | 0.50 | 75.6 | k 12: 2018-01-02 .. 2019-01-01 | 76.2 (f 0.50) | 2018-01-14 → 2018-12-16 | 76.2 | 79.7: f 0.50, b 0.05, cap 8, k 12 | 28.2 (2020-03-13, f 0.50) | 35.1 (2020-03-06 → 2020-03-13, f 0.50) |

**Binance, by crypto share: the worst of its mixes** (falls as positive sizes, %; headline band 0.50, cap 1, 5,000 USD, 1x; full run 2017-08-18 .. 2023-01-01) — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall the app shows, and not a drawdown budget.

| s | Mix (f) of the worst window | Worst 12-month window fall | Window | Full-run fall | Peak → trough | Full run, yearly reset | Deepest over every band and cap (12-month windows) | Worst day (close) | Worst 7 days |
|---|---|---|---|---|---|---|---|---|---|
| 0.20 | 0.00 | 34.6 | k 11: 2017-12-02 .. 2018-12-01 | 34.5 (f 0.00) | 2018-01-14 → 2018-12-16 | 34.5 | 41.8: f 0.00, b 0.05, cap 0.25, k 11 | 7.2 (2020-03-13, f 0.75) | 10.4 (2021-05-15 → 2021-05-22, f 0.00) |
| 0.30 | 0.00 | 51.0 | k 12: 2018-01-02 .. 2019-01-01 | 46.3 (f 0.00) | 2018-01-14 → 2018-12-16 | 46.3 | 54.1: f 0.00, b 0.05, cap 0.25, k 11 | 13.3 (2020-03-13, f 0.00) | 17.5 (2020-03-06 → 2020-03-13, f 0.00) |
| 0.40 | 0.00 | 61.3 | k 12: 2018-01-02 .. 2019-01-01 | 61.2 (f 0.00) | 2018-01-14 → 2018-12-16 | 61.2 | 64.1: f 0.00, b 0.10, cap 1, k 12 | 18.1 (2020-03-13, f 0.00) | 23.5 (2020-03-06 → 2020-03-13, f 0.00) |
| 0.50 | 0.25 | 64.4 | k 12: 2018-01-02 .. 2019-01-01 | 63.7 (f 0.00) | 2018-01-14 → 2018-12-16 | 63.7 | 72.5: f 0.00, b 0.05, cap 8, k 12 | 19.6 (2020-03-13, f 0.75) | 25.0 (2020-03-06 → 2020-03-13, f 0.75) |
| 0.60 | 0.25 | 71.9 | k 12: 2018-01-02 .. 2019-01-01 | 65.0 (f 0.50) | 2018-01-14 → 2018-12-16 | 65.0 | 74.6: f 0.25, b 0.05, cap 8, k 12 | 24.2 (2020-03-13, f 0.25) | 30.7 (2020-03-06 → 2020-03-13, f 0.25) |
| 0.70 | 0.25 | 75.3 | k 12: 2018-01-02 .. 2019-01-01 | 74.3 (f 0.25) | 2018-01-14 → 2018-12-16 | 74.3 | 80.1: f 0.25, b 0.05, cap 8, k 12 | 29.5 (2020-03-13, f 0.25) | 36.7 (2020-03-06 → 2020-03-13, f 0.25) |
| 0.78 | 0.50 | 75.8 | k 12: 2018-01-02 .. 2019-01-01 | 75.3 (f 0.50) | 2018-01-14 → 2018-12-16 | 75.3 | 79.2: f 0.50, b 0.05, no cap, k 12 | 28.4 (2020-03-13, f 0.50) | 35.3 (2020-03-06 → 2020-03-13, f 0.50) |

**Read these two tables with care.** Every column except "Deepest over every band and cap" is at the default band
and cap only, and the customer picks the band and cap. The worst day and worst 7 days are from the full runs, as the
plan pins them. The "Deepest over every band and cap" column covers the 12-month windows only. Two things it does not
show, read from `runs.parquet` for this file (5,000 USD, 1x, the lab's first-buy reading, the yearly reset changes
none of them):
- **Over the full 2017-2022 runs, other bands and caps fell further than the windows at low crypto shares.** The
  deepest full-run fall over every band and cap, against the column above:

  | s | Kraken full run | Kraken 12-month windows | Binance full run | Binance 12-month windows |
  |---|---|---|---|---|
  | 0.20 | **45.0** (ETH only, b 0.05, cap 0.25) | 42.0 | 40.7 | 41.8 |
  | 0.30 | **57.3** (ETH only, b 0.50, cap 0.25) | 54.3 | 54.0 | 54.1 |
  | 0.40 | **65.6** (ETH only, b 0.30, cap 0.5) | 64.5 | 64.8 | 64.1 |
  | 0.50 | 72.5 | 72.7 | 72.5 | 72.5 |
  | 0.60 | 74.8 | 74.7 | 74.5 | 74.6 |
  | 0.70 | 80.4 | 80.4 | 80.1 | 80.1 |
  | 0.78 | 79.8 | 79.7 | 79.2 | 79.2 |

  SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (full runs: Kraken 2017-01-02 .. 2023-01-01,
  Binance 2017-08-18 .. 2023-01-01; windows: 12 months), in-sample, reference engine, placeholder costs. Not the worst
  fall the app shows, and not a drawdown budget.
- **Worst day and worst 7 days at other settings and in the windows.** At any band and cap the full runs fell up to
  32.1% in one day and 39.4% in 7 days (78% crypto, Binance, band 0.05, no cap; Kraken 31.7% and 39.0%). In the
  12-month windows, which start at the target mix, a window that began on 2020-03-02 held the full 78% crypto into the
  crash of 12 March 2020: 32.1% in one day and 39.4% in 7 days even at the default (Binance; Kraken 31.7% and 39.0%),
  and 32.7% and 39.6% at band 0.10 with no cap (Binance). Same label as above.

Steady's drawdown budget, approved by the owner on 2026-11-21, is 35% (not yet in `config/risk_levels.yaml`, which
run 0 read as TBD). It is a gate on a strategy's Monte Carlo falls, so this is a pointer, not a test: only 2 of the 27
mixes fell no more than 35% at every band, cap, window and full run on both sources (20% crypto with 75% or all of it
in BTC: 33.4% and 35.0% at worst), and 4 at the default (20% crypto, all but ETH only, which fell 35.3%).

### By mix

**Kraken, by mix** (headline band 0.50, cap 1, 5,000 USD, 1x; full run 2017-01-02 .. 2023-01-01; falls as positive sizes, %) — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall the app shows, and not a drawdown budget.

| s | f | Worst 12-month window | Full run | Peak → trough | Full run, yearly reset | Deepest, any band and cap (12-month windows) | Worst day (close) | Worst 7 days (full run) |
|---|---|---|---|---|---|---|---|---|
| 0.20 | 0.00 | 35.3 (k 11) | 34.0 | 2018-01-14 → 2018-12-16 | 34.0 | 42.0 (b 0.05, cap 0.25, k 11) | 9.3 (2017-03-19) | 9.3 (2020-03-06 → 2020-03-13) |
| 0.20 | 0.25 | 31.3 (k 12) | 33.5 | 2018-01-14 → 2018-12-16 | 33.5 | 40.4 (b 0.30, cap 0.25, k 11) | 8.6 (2020-03-13) | 11.5 (2020-03-06 → 2020-03-13) |
| 0.20 | 0.50 | 28.2 (k 12) | 30.4 | 2018-01-14 → 2018-12-16 | 30.4 | 34.3 (b 0.30, cap 0.25, k 11) | 7.2 (2020-03-13) | 9.7 (2020-03-06 → 2020-03-13) |
| 0.20 | 0.75 | 25.6 (k 12) | 25.4 | 2018-01-07 → 2018-12-16 | 25.4 | 28.7 (b 0.05, cap 0.25, k 9) | 7.5 (2020-03-13) | 10.0 (2020-03-06 → 2020-03-13) |
| 0.20 | 1.00 | 23.5 (k 12) | 24.6 | 2017-12-17 → 2018-12-16 | 24.6 | 33.9 (b 0.05, cap 0.25, k 9) | 5.6 (2020-03-13) | 8.9 (2017-12-18 → 2017-12-25) |
| 0.30 | 0.00 | 51.1 (k 12) | 46.4 | 2018-01-14 → 2018-12-16 | 46.4 | 54.3 (b 0.05, cap 0.25, k 11) | 11.5 (2020-03-13) | 15.3 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.25 | 42.6 (k 12) | 45.7 | 2018-01-14 → 2018-12-16 | 45.7 | 52.9 (b 0.30, cap 0.25, k 11) | 10.3 (2020-03-13) | 14.7 (2021-05-15 → 2021-05-22) |
| 0.30 | 0.50 | 39.4 (k 12) | 40.1 | 2018-01-14 → 2018-12-16 | 40.1 | 46.4 (b 0.30, cap 0.25, k 11) | 12.9 (2020-03-13) | 17.0 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.75 | 35.8 (k 12) | 36.1 | 2018-01-07 → 2018-12-16 | 36.1 | 39.2 (b 0.05, cap 8, k 12) | 11.3 (2020-03-13) | 14.9 (2020-03-06 → 2020-03-13) |
| 0.30 | 1.00 | 36.4 (k 11) | 34.6 | 2017-12-17 → 2018-12-16 | 34.6 | 39.7 (b 0.20, cap 0.25, k 9) | 8.1 (2020-03-13) | 10.7 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.00 | 61.4 (k 12) | 61.8 | 2018-01-14 → 2018-12-16 | 61.8 | 64.5 (b 0.10, cap 1, k 12) | 17.8 (2020-03-13) | 23.2 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.25 | 57.3 (k 12) | 56.0 | 2018-01-14 → 2018-12-16 | 56.0 | 62.5 (b 0.30, cap 0.25, k 11) | 17.1 (2020-03-13) | 22.3 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.50 | 48.9 (k 12) | 49.9 | 2018-01-14 → 2018-12-16 | 49.9 | 56.1 (b 0.30, cap 0.25, k 11) | 14.4 (2020-03-13) | 18.9 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.75 | 45.7 (k 12) | 46.9 | 2017-12-19 → 2018-12-16 | 46.9 | 48.8 (b 0.15, cap 0.5, k 12) | 14.0 (2020-03-13) | 18.3 (2020-03-06 → 2020-03-13) |
| 0.40 | 1.00 | 44.0 (k 11) | 45.0 | 2017-12-17 → 2018-12-16 | 45.0 | 46.1 (b 0.20, no cap, k 12) | 12.8 (2020-03-13) | 17.0 (2017-09-08 → 2017-09-15) |
| 0.50 | 0.00 | 63.2 (k 12) | 66.7 | 2018-01-14 → 2018-12-16 | 66.7 | 72.7 (b 0.10, cap 1, k 12) | 18.7 (2020-03-13) | 24.3 (2020-03-06 → 2020-03-13) |
| 0.50 | 0.25 | 64.6 (k 12) | 63.2 | 2018-01-14 → 2018-12-16 | 63.2 | 68.0 (b 0.05, cap 2, k 12) | 16.6 (2020-03-13) | 22.4 (2021-05-15 → 2021-05-22) |
| 0.50 | 0.50 | 57.7 (k 12) | 53.6 | 2018-01-14 → 2018-12-16 | 53.6 | 64.0 (b 0.30, cap 0.25, k 11) | 19.2 (2020-03-13) | 24.6 (2020-03-06 → 2020-03-13) |
| 0.50 | 0.75 | 53.9 (k 12) | 53.2 | 2018-01-07 → 2018-12-16 | 53.2 | 57.3 (b 0.05, cap 8, k 12) | 17.3 (2020-03-13) | 22.3 (2020-03-06 → 2020-03-13) |
| 0.50 | 1.00 | 49.5 (k 12) | 52.8 | 2017-12-17 → 2018-12-16 | 52.8 | 54.3 (b 0.15, cap 0.5, k 12) | 16.5 (2020-03-13) | 21.2 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.25 | 72.2 (k 12) | 69.1 | 2018-01-14 → 2018-12-16 | 69.1 | 74.7 (b 0.15, cap 4, k 12) | 23.6 (2020-03-13) | 30.0 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.50 | 67.3 (k 12) | 65.5 | 2018-01-14 → 2018-12-16 | 65.5 | 70.3 (b 0.20, cap 0.25, k 11) | 22.7 (2020-03-13) | 28.8 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.75 | 60.9 (k 12) | 61.8 | 2017-12-19 → 2018-12-16 | 61.8 | 64.7 (b 0.05, cap 8, k 12) | 21.2 (2020-03-13) | 26.9 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.25 | 75.5 (k 12) | 74.6 | 2018-01-14 → 2018-12-16 | 74.6 | 80.4 (b 0.05, no cap, k 12) | 29.2 (2020-03-13) | 36.3 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.50 | 73.8 (k 12) | 67.5 | 2018-01-14 → 2018-12-16 | 67.5 | 75.8 (b 0.05, cap 2, k 12) | 29.0 (2020-03-13) | 36.0 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.75 | 67.8 (k 12) | 66.8 | 2018-01-07 → 2018-12-16 | 66.8 | 70.6 (b 0.05, no cap, k 12) | 25.5 (2020-03-13) | 31.9 (2020-03-06 → 2020-03-13) |
| 0.78 | 0.50 | 75.6 (k 12) | 76.2 | 2018-01-14 → 2018-12-16 | 76.2 | 79.7 (b 0.05, cap 8, k 12) | 28.2 (2020-03-13) | 35.1 (2020-03-06 → 2020-03-13) |

**Binance, by mix** (headline band 0.50, cap 1, 5,000 USD, 1x; full run 2017-08-18 .. 2023-01-01; falls as positive sizes, %) — SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (the window or the full span is named), in-sample, reference engine, placeholder costs. Not the worst fall the app shows, and not a drawdown budget.

| s | f | Worst 12-month window | Full run | Peak → trough | Full run, yearly reset | Deepest, any band and cap (12-month windows) | Worst day (close) | Worst 7 days (full run) |
|---|---|---|---|---|---|---|---|---|
| 0.20 | 0.00 | 34.6 (k 11) | 34.5 | 2018-01-14 → 2018-12-16 | 34.5 | 41.8 (b 0.05, cap 0.25, k 11) | 6.8 (2020-03-13) | 10.4 (2021-05-15 → 2021-05-22) |
| 0.20 | 0.25 | 30.5 (k 12) | 33.3 | 2018-01-14 → 2018-12-16 | 33.3 | 40.0 (b 0.30, cap 0.25, k 11) | 6.8 (2020-03-13) | 9.1 (2020-03-06 → 2020-03-13) |
| 0.20 | 0.50 | 28.0 (k 12) | 29.1 | 2018-01-14 → 2018-12-16 | 29.1 | 33.9 (b 0.15, cap 0.25, k 11) | 6.6 (2020-03-13) | 8.9 (2020-03-06 → 2020-03-13) |
| 0.20 | 0.75 | 25.5 (k 12) | 25.3 | 2018-01-07 → 2018-12-16 | 25.3 | 28.7 (b 0.05, cap 0.25, k 9) | 7.2 (2020-03-13) | 9.6 (2020-03-06 → 2020-03-13) |
| 0.20 | 1.00 | 23.5 (k 12) | 25.5 | 2017-12-17 → 2018-12-16 | 25.5 | 33.4 (b 0.05, cap 0.25, k 9) | 6.5 (2020-03-13) | 8.6 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.00 | 51.0 (k 12) | 46.3 | 2018-01-14 → 2018-12-16 | 46.3 | 54.1 (b 0.05, cap 0.25, k 11) | 13.3 (2020-03-13) | 17.5 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.25 | 42.5 (k 12) | 45.3 | 2018-01-14 → 2018-12-16 | 45.3 | 52.5 (b 0.30, cap 0.25, k 11) | 13.0 (2020-03-13) | 17.1 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.50 | 39.2 (k 12) | 40.4 | 2018-01-14 → 2018-12-16 | 40.4 | 45.8 (b 0.30, cap 0.25, k 11) | 12.7 (2020-03-13) | 16.6 (2020-03-06 → 2020-03-13) |
| 0.30 | 0.75 | 35.8 (k 12) | 35.6 | 2018-01-14 → 2018-12-16 | 35.6 | 38.6 (b 0.05, no cap, k 12) | 13.0 (2020-03-13) | 17.0 (2020-03-06 → 2020-03-13) |
| 0.30 | 1.00 | 35.6 (k 11) | 35.5 | 2017-12-17 → 2018-12-16 | 35.5 | 39.2 (b 0.20, cap 0.25, k 9) | 8.1 (2020-03-13) | 12.3 (2017-12-17 → 2017-12-24) |
| 0.40 | 0.00 | 61.3 (k 12) | 61.2 | 2018-01-14 → 2018-12-16 | 61.2 | 64.1 (b 0.10, cap 1, k 12) | 18.1 (2020-03-13) | 23.5 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.25 | 57.2 (k 12) | 55.4 | 2018-01-14 → 2018-12-16 | 55.4 | 62.0 (b 0.30, cap 0.25, k 11) | 15.4 (2020-03-13) | 20.0 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.50 | 48.6 (k 12) | 50.2 | 2018-01-14 → 2018-12-16 | 50.2 | 55.4 (b 0.30, cap 0.25, k 11) | 15.4 (2020-03-13) | 20.0 (2020-03-06 → 2020-03-13) |
| 0.40 | 0.75 | 45.6 (k 12) | 46.9 | 2017-12-19 → 2018-12-16 | 46.9 | 48.7 (b 0.05, cap 8, k 12) | 14.2 (2020-03-13) | 18.4 (2020-03-06 → 2020-03-13) |
| 0.40 | 1.00 | 43.5 (k 11) | 48.3 | 2017-12-17 → 2018-12-16 | 49.1 | 46.0 (b 0.20, no cap, k 12) | 15.8 (2020-03-13) | 20.3 (2020-03-06 → 2020-03-13) |
| 0.50 | 0.00 | 63.6 (k 12) | 63.7 | 2018-01-14 → 2018-12-16 | 63.7 | 72.5 (b 0.05, cap 8, k 12) | 17.8 (2020-03-13) | 23.1 (2020-03-06 → 2020-03-13) |
| 0.50 | 0.25 | 64.4 (k 12) | 62.8 | 2018-01-14 → 2018-12-16 | 62.8 | 67.7 (b 0.05, cap 2, k 12) | 15.9 (2020-03-13) | 21.0 (2018-01-30 → 2018-02-06) |
| 0.50 | 0.50 | 57.4 (k 12) | 53.4 | 2018-01-14 → 2018-12-16 | 53.4 | 63.4 (b 0.30, cap 0.25, k 11) | 19.4 (2020-03-13) | 24.8 (2020-03-06 → 2020-03-13) |
| 0.50 | 0.75 | 53.7 (k 12) | 55.0 | 2017-12-19 → 2018-12-16 | 55.0 | 57.0 (b 0.05, cap 8, k 12) | 19.6 (2020-03-13) | 25.0 (2020-03-06 → 2020-03-13) |
| 0.50 | 1.00 | 49.5 (k 12) | 50.2 | 2017-12-17 → 2018-12-16 | 50.2 | 54.1 (b 0.15, cap 0.25, k 12) | 15.9 (2020-03-13) | 20.4 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.25 | 71.9 (k 12) | 63.3 | 2018-01-14 → 2018-12-16 | 63.3 | 74.6 (b 0.05, cap 8, k 12) | 24.2 (2020-03-13) | 30.7 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.50 | 67.0 (k 12) | 65.0 | 2018-01-14 → 2018-12-16 | 65.0 | 69.8 (b 0.20, cap 0.25, k 11) | 21.2 (2020-03-13) | 26.9 (2020-03-06 → 2020-03-13) |
| 0.60 | 0.75 | 60.8 (k 12) | 60.2 | 2018-01-07 → 2018-12-16 | 60.2 | 64.4 (b 0.05, cap 8, k 12) | 21.5 (2020-03-13) | 27.2 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.25 | 75.3 (k 12) | 74.3 | 2018-01-14 → 2018-12-16 | 74.3 | 80.1 (b 0.05, cap 8, k 12) | 29.5 (2020-03-13) | 36.7 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.50 | 73.5 (k 12) | 66.9 | 2018-01-14 → 2018-12-16 | 66.9 | 75.7 (b 0.05, cap 8, k 12) | 24.3 (2020-03-13) | 30.6 (2020-03-06 → 2020-03-13) |
| 0.70 | 0.75 | 67.8 (k 12) | 66.6 | 2018-01-07 → 2018-12-16 | 66.6 | 70.4 (b 0.10, cap 0.5, k 12) | 25.9 (2020-03-13) | 32.3 (2020-03-06 → 2020-03-13) |
| 0.78 | 0.50 | 75.8 (k 12) | 75.3 | 2018-01-14 → 2018-12-16 | 75.3 | 79.2 (b 0.05, no cap, k 12) | 28.4 (2020-03-13) | 35.3 (2020-03-06 → 2020-03-13) |

### Falls of each recommended setting and its comparators

12-month windows, 5,000 USD, 1x, from `runs.parquet` for this file. SCOUTING, hypothetical: simulated on past prices,
2017-2022 train years (12-month windows), in-sample, reference engine, placeholder costs. Not the worst fall the app
shows, and not a drawdown budget. Differences are medians of the run-by-run differences, as positive sizes (a negative
number means a smaller fall).

| Source | Setting | Fall % (median) | Fall % (bad tail: 10th percentile of the signed number) | Fall % (deepest) | Fall minus no cap's, pts (median) | Fall minus limit-only's, pts (median) |
|---|---|---|---|---|---|---|
| Kraken | b 0.10, cap 8 | 30.4 | 52.2 | 80.0 | 0.00 | -0.43 |
| Kraken | b 0.10, cap no cap (comparator) | 30.4 | 52.3 | 80.2 |  | -0.42 |
| Kraken | b 0.15, cap 4 | 30.0 | 52.1 | 79.9 | 0.00 | -0.57 |
| Kraken | b 0.15, cap no cap (comparator) | 30.3 | 51.8 | 79.7 |  | -0.55 |
| Kraken | b 0.20, cap 4 | 29.7 | 51.4 | 79.4 | 0.00 | -0.71 |
| Kraken | b 0.20, cap no cap (comparator) | 29.7 | 51.4 | 79.4 |  | -0.66 |
| Kraken | b 0.30, cap 2 | 29.8 | 50.3 | 78.1 | 0.00 | -0.21 |
| Kraken | b 0.30, cap no cap (comparator) | 29.7 | 50.5 | 78.1 |  | -0.39 |
| Kraken | b 0.50, cap 1 | 29.7 | 49.5 | 75.6 | 0.00 | 0.00 |
| Kraken | b 0.50, cap no cap (comparator) | 29.6 | 49.5 | 75.6 |  | 0.00 |
| Kraken | limit-only (comparator) | 32.6 | 49.8 | 68.1 |  |  |
| Binance | b 0.10, cap 8 | 30.5 | 53.0 | 79.5 | 0.00 | -0.22 |
| Binance | b 0.10, cap no cap (comparator) | 30.3 | 53.1 | 79.6 |  | -0.12 |
| Binance | b 0.15, cap 4 | 30.3 | 52.6 | 79.7 | 0.00 | -0.32 |
| Binance | b 0.15, cap no cap (comparator) | 30.5 | 52.4 | 79.7 |  | -0.26 |
| Binance | b 0.20, cap 4 | 29.9 | 52.3 | 79.0 | 0.00 | -0.43 |
| Binance | b 0.20, cap no cap (comparator) | 29.9 | 52.3 | 78.2 |  | -0.38 |
| Binance | b 0.30, cap 2 | 29.8 | 52.1 | 77.2 | 0.00 | 0.00 |
| Binance | b 0.30, cap no cap (comparator) | 30.0 | 52.2 | 77.2 |  | 0.00 |
| Binance | b 0.50, cap 1 | 30.0 | 50.2 | 75.8 | 0.00 | 0.00 |
| Binance | b 0.50, cap no cap (comparator) | 30.0 | 50.3 | 75.8 |  | 0.00 |
| Binance | limit-only (comparator) | 32.0 | 49.5 | 68.7 |  |  |

What the falls say (descriptions only):
- **The crypto share moves the worst fall the most**, as expected: at the default band and cap, from 35% (20% crypto)
  to 76% (78% crypto) over a 12-month window, nearly all in the 2018 crash (window k = 12, 2018-01-02 .. 2019-01-01;
  full runs peak 2018-01-14, low 2018-12-16). These are not bounds: at other bands and caps (5,000 USD, 1x) the same
  shares fell 42% (20% crypto) to 80% (70% crypto) over a 12-month window, and 45.0%, 57.3% and 65.6% over the
  full 2017-2022 runs at 20%, 30% and 40% crypto (Kraken; the note under the by-crypto-share tables).
- **The band and cap move it less, but not by nothing:** up to about 10 points between the headline and the deepest
  setting of the same mix (for example, ETH only at 50%: 63.2% at the headline against 72.7% at band 0.10 with cap 1).
  The plan expected small differences; up to 10 points is more than "small".
- **Trading back to the mix deepened the worst crash.** In 2018, buying the coins back as they fell made the tool's
  deepest 12-month falls (75.6 to 80.0% over its recommended settings) deeper than leaving the mix alone between limit
  hits (68.1% on Kraken). In the median window it was the other way round (29.7% against 32.6%).
- **Worst day and week**, at the default band and cap (full runs): up to 29.2% in one day (the day of 12 March 2020,
  at 70% crypto; Binance 29.5%) and 36.3% in 7 days (closes 6 to 13 March 2020; Binance 36.7%). At any band and cap
  (5,000 USD, 1x): up to 32.7% in one day (78% crypto, Binance, band 0.10, no cap, in a 12-month window) and 39.6% in
  7 days (the same run; 39.4% in the full runs, 78% crypto, Binance, band 0.05, no cap). A window started just before
  the crash fell 32.1% in one day and 39.4% in 7 days even at the default (78% crypto, Binance). A daily or weekly loss
  limit pauses the tool, but it cannot cap a loss: the day's fall has happened before the next daily check.

## Run record

| Item | Run 0 |
|---|---|
| Status | **complete** (exit 0), the reported run. No superseded runs and no amendment runs |
| Command | `uv run python research/hold-mix-cap/run.py` (2 workers, real data) |
| Commit | `afb73189cc196dbbce88fe3318950265f368756f` ("hold-mix-cap: engine and run script"), clean tree (`git status --porcelain --untracked-files=all` empty) |
| Started / ended | 2026-11-21 19:32:12 UTC / 20:31:18 UTC (`RUNLOG.jsonl`: start line and "complete" line) |
| Runtime | 3,546 s in all; the grid 3,379 s wall on 2 forked workers (Linux, Python 3.13.18) |
| A0 re-timing (stop rule 9) | 94.5 CPU-minutes projected (47.2 minutes wall on 2 workers), under the 240 limit. The grid took 56.3 minutes wall, about 19% more than projected |
| Config hash | `a227c1677b62e796940e6117557572dd279b6ea8b74dbe0b22002c95dbf2680f` (rechecked at the end; stop rule 10 did not fire) |
| Data | Snapshot `1746a21b75683e76`, bars hash `08f5ca2c…`; Kraken 2190 rows (2017-01-02 .. 2023-01-01, 2018-01-13 dropped: no ETH bar, so BTC's bar there was dropped), panel hash `355aabe2…`; Binance 1963 rows (2017-08-18 .. 2023-01-01, none dropped), panel hash `2c1a4257…`. All as pinned |
| Last close read | 2023-01-01 00:00 UTC. No validate or test bar was read; the test-window guard (stop rule 3) did not fire |
| Limits as read | min cash 0.20, max coin 0.60, coins BTC, ETH, USDC, drawdown budget TBD (`risk_levels.yaml` SHA-256 `158d7c9f…`); h = 0.02. All 27 mixes passed `check_targets` |
| Costs as read | pool fee 5 bps, aggregator 0, slippage 10 / 15 / 30 bps at 100 / 1,000 / 10,000 USD, gas 0.10 USD a swap; 2x doubles each |
| Runs | **916,596 logged, 0 failed** (every count equal to the plan's: grid 762,048 rolling + 27,216 full, limit-only 18,468, other first-buy reading 108,864; limit-only band rows 110,808; `runs.csv` 9,396 rows). 114 blocks, all logged in `run0/blocks/` |
| Parity checks | 13,338, all agreed bit for bit (10,260 band parity with `portfolio.rebalance`, 3,078 limit-only parity) |
| Consistency checks | 1,027,404 path checks (every run and limit-only band row), 916,596 fee checks, the path hash over 243,486 configuration groups; none fired |
| Stop rules fired | none |
| Failures and rule E | none; rule E not needed (`rule_E` is null) |
| Warnings in the log | pandas `PerformanceWarning: DataFrame is highly fragmented` from `run.py` line 1212 (sorting), harmless; nothing from `lab/` |
| Outputs committed | `RUNLOG.jsonl`, `runs.csv`, `falls.csv`, `decision.json` in `1a9512c` ("hold-mix-cap: run 0 outputs"); results in `results/hold-mix-cap/run0/` (git-ignored) |

**Independent checks of the outputs.** After the run, rules B, A, C and D were recomputed from `runs.parquet` by
separate code and matched `decision.json` exactly, and a set of per-run sanity checks passed (scratch scripts outside
the repo). For this file a second, smaller check recomputed from `runs.parquet` rule B's median and 90th percentile at
bands 0.20 and 0.50 (caps 0.5 to 4), I(2) at 5,000 USD 1x, C(2) at 50,000 USD 2x, and rule A's fee at (0.20, 4) at
50,000 USD 2x and its rate, on both sources: all equal to `decision.json` to 1e-12. The comparison table's median
extra days out of band equal rule B's medians.

### Stop rule 1 and hard rule 11: the test tiers on each commit used

All with `-n 2`, from `/home/user/osprey`, branch `claude/tender-brown-g86h44`.

| Commit | What it is | Full tier with coverage | Deep profile (`-m "not slow"`) | Ruff | Dashboard |
|---|---|---|---|---|---|
| `b05109e` + the uncommitted build fixes (later committed as `afb7318`) | the code review fixes (#52, #53, A5, A6) | 1881 passed (12 slow), 100% branch coverage of `lab/` (4896 statements, 1440 branches), 353 s | 1869 passed, 563 s | clean | 86 passed |
| **`afb7318`** | **the commit run 0 used** | **1881 passed (12 slow), 100% branch (4896 / 1440, 0 missed, 0 partial), 360.38 s; tree clean before and after** | **1869 passed, 591.29 s** | **clean** | **86 passed** |
| `1a9512c` (HEAD; this file uncommitted on top) | run 0's tracked outputs only (no code; the RUNLOG now holds real run 0) | 1881 passed (12 slow), 100% branch (4896 / 1440, 0 missed), 349.33 s | 1869 passed, 562.69 s | clean | 86 passed |
| `1a9512c` + the #54 test fix (uncommitted; to be committed with this file, AUDIT.md and RISK.md) | `tests/test_holdmix.py` only (TESTING.md #54); no `lab/` or other hashed file, so the config hash is still `a227c167…` | 1881 passed (12 slow), 100% branch (4896 / 1440, 0 missed, 0 partial), 353.53 s | 1869 passed, 565.11 s | clean | 86 passed |

Commands: `uv run pytest -q -p no:cacheprovider -n 2 --ignore=tests/test_dashboard.py --cov=lab --cov-branch
--cov-report=term-missing`; `HYPOTHESIS_PROFILE=deep uv run pytest -q -p no:cacheprovider -n 2 -m "not slow"
--ignore=tests/test_dashboard.py`; `uv run ruff check`; `uv run pytest -q -p no:cacheprovider -n 2
tests/test_dashboard.py`. The `1a9512c` row matters because a test that reads the repo's RUNLOG would now see a real
run 0 (the lesson of TESTING.md #48); all four passed there too, with the tree clean before and after (`git status
--porcelain` empty), so no test depends on the recorded run.

**A deep-profile failure found after run 0 (TESTING.md #54).** The audit reran the deep profile on `1a9512c`, which
has the same `lab/` code and tests as `afb7318`, and got 1 failed, 1868 passed: hypothesis drew a BTC target of
2.6e-322, a number below the smallest normal double (2.2e-308), in `test_money_metrics_by_brute_force`. Our own deep
runs on both commits had passed only because their random draws missed it. It is a **test bug**: at that size a
swap's USD amount has too few digits for `money_metrics` to recover the wallet value from it, so its own fee check
rightly refused to report fees, and the test had not allowed for that refusal. The test now checks that the
refusal is the right one and happens only there; no `lab/` file changed. **No run-0 number moves:** run 0's
smallest swap was 4.9e-5 USD, about 300 orders of magnitude above the problem, and all 916,596 fee checks passed.
With the fix, the tiers pass (the last row above), which is what stop rule 1 asks of the commit that carries this
file (deviation 4).

A synthetic dry run on `afb7318` (`run.py --synthetic 7 --fast --out-dir <scratch>`) completed: 588 runs, 0 failed,
every count as expected, nothing written into the repo. It is not a run of this study and no number from it is used.

## Expectations against results (PLAN.md section 1)

| Expectation, written before any run | Result (SCOUTING) |
|---|---|
| Each halving of the band multiplies rebalances by about 3 to 4 | **Less:** about 2.6 to 3.0 (no cap, Kraken medians 5.93, 2.31 and 0.82 a month at 0.05, 0.10 and 0.20; 1.24 and 0.41 at 0.15 and 0.30) |
| A cap adds days out of band only when the band breaks again within the wait; caps of 1-2 hardly bind in calm years, bind in busy ones | Yes: the 2017-start windows fail most often (by start year, above); at band 0.50 a cap of 1 adds a median of 0 days |
| Mixes close to a Steady limit are traded by the limit often, whatever the cap | Yes: at 78% crypto every rebalance was a limit fix, up to 7 in 30 days |
| Decisions do not depend on costs or wallet size | Yes: the path hash agreed in every configuration |
| The worst fall grows with the crypto share far more than with the band or cap | Yes, but band and cap still moved the worst 12-month fall by up to about 10 points |

What would change the product (PLAN.md section 1): a band met the conditions at every wallet size (0.50); the default
band's cap is 1 a month, not more than a few; **limit hits do break through the cap often at 78% crypto** (median 3 a
year inside the wait, up to 22), so the app should say so next to those mixes; and **the sources and cost levels did
give different recommendations** for 50,000 USD wallets (NOT ROBUST).

## Looks at the data (continues PLAN.md section 17; PLAN.md itself is not edited)

| # | Date | By | What was looked at |
|---|---|---|---|
| T1 | 2026-11-21 19:32-20:31 UTC | run 0 (`run.py`) | Kraken and Binance daily train bars to 2023-01-01 00:00 UTC: every run of the grid |
| T2 | 2026-11-21, after run 0 | `quant-researcher` (this file) | Run 0's outputs: `decision.json`, `runs.csv`, `falls.csv`, `runs.parquet`, `start.json`, `summary.json` (train years only) |

PLAN.md's T1 row still reads "reserved": editing PLAN.md changes the config hash, so the look is recorded here.
**Validate-window looks used by this study: 0. Test window: never read.** This study is now a prior look for later
Steady work: a Steady rebalancing strategy searched on train must list it (PLAN.md section 2).

## Deviations from PLAN.md

| # | What changed | Why | When | Effect on any number |
|---|---|---|---|---|
| 1 | No MLflow logging; every run is in Parquet only | Declared in PLAN.md section 12 before any result (MLflow not built; Nautilus/MLflow work on hold) | Before run 0 | None |
| 2 | PLAN.md section 17's T1 row was not filled in | Editing PLAN.md would change the config hash; recorded above instead | After run 0 | None |
| 3 | Stop rule 1's tiers on `afb7318` were run by the workflow's tier stage, not by the run stage, and are copied here from its report | The run stage relied on that stage; this file also reruns them on `1a9512c` | Before run 0 | None |
| 4 | Stop rule 1 was met on `afb7318` when run 0 started, but a later deep run on the same code (the audit's, on `1a9512c`) failed one test, `test_money_metrics_by_brute_force` (TESTING.md #54). It is a test bug, fixed in `tests/test_holdmix.py` only; the tiers were rerun and pass on the working tree that carries the fix and this file | Hard rule 11 and stop rule 1: no number counts unless the tiers pass. The failing input needs a BTC or ETH target below about 1e-290; the grid's smallest is 0.05 | After run 0, during its audit | None. No `lab/` or other hashed file changed (tests are not hashed), so the config hash is still `a227c167…`, and no amendment run is needed. Run 0's smallest swap was 4.9e-5 USD and all 916,596 fee checks passed |

No other departure: no amendment, no stop rule, no failed run, no change to any hashed file (the #54 fix is in a
test file, which is not hashed).

## Readings used where the plan is loosely worded

- **Comparisons, trade sizes per crypto share, the reset table and the falls of the recommended settings** are not in
  `decision.json`. They were read for this file from `runs.parquet` and `runs.csv` by a scratch script: medians over
  the pairs (12-month windows, 5,000 USD, 1x) of each band at its robust cap N\*_rob(b), of the same band with no cap,
  and of limit-only; for the differences, the medians of `vs_nocap_*` and `vs_limit_*`. Band 0.05 is shown with no cap
  (it has no usable cap). Trade sizes are the worst over windows (`runs.csv` `_worst` columns), then over the mixes of
  each crypto share. The reset table takes, per band and cap, medians over the 27 mixes of the full runs. No decision
  uses any of them.
- **Rule A's table** is shown at each band's robust cap N\*_rob(b) on both sources, which is what rule D reads. Each
  source's own rule A (at its own N\*) is listed below it.
- **Per crypto share** is `decision.json`'s `per_share`, at the robust headline (0.50, cap 1) only, as PLAN.md section
  10 asks ("at the default band and cap"); not at the per-size 0.20.
- **The years description** is shown at each band's recommended cap (cap 8 for 0.05); `decision.json` holds every cap.

## Known weaknesses

- **Scouting.** The reference engine, not Nautilus; pessimistic placeholder costs; Kraken in USD and Binance in USDT
  standing in for Base prices against USDC. USDC is priced at 1, with no yield and no depeg.
- **Fees caveat.** Every fee number, and rule A's fee condition, uses placeholder costs. They must be rechecked with
  measured Base costs before the app shows a recommended number. The NOT ROBUST move rests entirely on 50,000 USD
  wallets at doubled costs, where slippage above 10,000 USD a swap is extrapolated along the table's last segment.
- **Close calls.** Binance's N\*(0.20) failed cap 2 by 0.01 day; Binance's 50,000 USD band at 2x passed at 0.30 by
  0.001 percentage points (0.249%). The thresholds are judgement calls fixed before any result (PLAN.md section 16).
- **In-sample, and seen before.** These are the train years rebalance-steady already searched, and the thresholds were
  set knowing roughly how often bands trade in them (PLAN.md section 2).
- **Few independent years.** The 60 windows overlap heavily; six train years; Binance has no window before September
  2017. The boom-year check shows the default band for large wallets depends on which years are in.
- **The pool weights mixes equally,** so low crypto shares (five BTC/ETH splits each) count more than 78% (one).
- **Every window starts fresh.** Real customers start any day, add or withdraw cash, and edit the mix.
- **The limit reading is the lab's,** not yet the owner's; the other readings are only approximated by dropping mixes.
- **Daily closes only, at 00:00 UTC.** Intraday moves past a limit are not seen.
- **Not modelled: pauses and approvals.** The customer's daily or weekly loss limit pauses the tool (owner, confirmed
  again 2026-11-21: "user loss limits should pause custom rules"), and so does Pause everything; on Approve, a skipped
  trade never runs. Then the mix drifts past its band and past Steady's limits. When the tool resumes it carries on
  with the same memory (PLAN.md section 15).
- **Not modelled: a minimum swap size.** Swaps down to about 0.00005 USD were simulated and each paid 0.10 USD of gas.
  A minimum would make decisions depend on wallet size (section 4.6 would no longer hold).
- **Gas is charged to the wallet** although the app sponsors it (conservative for returns; kept out of the fees).
- **Fees summed as fractions over the year** are a close stand-in for their compounded drag, not its exact value.
- **No worst fall for the app.** The falls here are in-sample descriptions. The worst fall the app shows must come from
  Nautilus backtests with measured costs over years agreed with `backtest-auditor`.
- **Parity with the app.** The app's rule must make exactly these decisions; a decision-parity test against `hold_mix`
  belongs with the app's rule engine, which does not exist yet.

## Open questions

For the owner:
1. **One default or a default per wallet size?** One default for everyone is 0.50 with a cap of 1. Wallets up to
   5,000 USD could default to 0.20 with a cap of 4 (or 0.30 with a cap of 2 if the upper limit is adopted).
2. **Adopt the Steady upper limit of 2 rebalances in any 30 days?** The lab proposes yes (above). It would rule out
   bands 0.20 and narrower.
3. **Which bands does the app offer?** This study assumed exactly 0.05, 0.10, 0.15, 0.20, 0.30 and 0.50; 0.05 should
   not be offered with a cap.

For `risk-officer`:
4. If the owner adopts the limit: add it to Steady's entry in `config/risk_levels.yaml`, limit fixes exempt.
5. The auto-trading permission's caps must allow one swap of at least 56% of the wallet and 62% in one day (64% for a
   mix left alone until a limit hit), and a first buy of up to 78% of the wallet in one day; or the app warns. The
   production controls of PLAN.md section 15 (a)-(e) still apply.
6. Should the app skip swaps under some minimum size, and accept that this breaks section 4.6?

For `backtest-auditor` (if reviewed):
7. Are the knife-edge outcomes (Binance N\*(0.20), Binance's 50,000 USD band at 2x) acceptable as they stand, given
   that neither moves the headline?
8. Is pooling the 6 bands in rule C the right yardstick, given that the band-by-band N_up ranges from 0.5 to 4?

## Files

- `research/hold-mix-cap/PLAN.md` (pre-registration, amendments A0-A6), `README.md`, `run.py`
- `research/hold-mix-cap/RUNLOG.jsonl`, `runs.csv`, `falls.csv`, `decision.json` (run 0's tracked outputs, `1a9512c`)
- `research/hold-mix-cap/RESULTS.md` (this file)
- `lab/runner/holdmix.py`, `tests/test_holdmix.py`, `tests/test_holdmix_run.py`
- `results/hold-mix-cap/run0/` (git-ignored): `start.json`, `summary.json`, `runs.parquet`, `limit_only_bands.parquet`,
  `parity.parquet`, `failures.parquet`, `decision.json`, `blocks/`

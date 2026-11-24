# buy-the-dip: results of run 0 (SCOUTING)

> **SCOUTING ONLY:** the reference engine (`lab/runner/dipbuy.py` driving `lab/runner/portfolio.py`), the placeholder
> costs of `config/costs.yaml`, and Kraken and Binance daily candles in place of Base prices. Not NautilusTrader.
> Written 2026-11-24 from `results/buy-the-dip/run0/`, and revised the same day after the audit
> ([AUDIT.md](AUDIT.md): PASS) and an independent fact-check.
> - Run 0 ran on commit `e62233e` with a clean tree. On that commit the full tier passed (2646 tests, 100% branch
>   coverage of `lab/`), the deep profile passed (2628), ruff was clean and the dashboard passed (86).
> - Every number below was recomputed from `runs.parquet`, `ladders.parquet` and `decision.json` with scratch code
>   that shares nothing with `dipbuy.py` or `run.py`. It agrees with `decision.json` exactly: every D1, D2 and D3
>   number, and the three per-setting tables.
> - A few descriptions added in the revision (dca-same's first cut, the time-average crypto share, the index around
>   the worst knife, the other reading of the one-year high) come from the audit's own rerun. All but the last were
>   reproduced with `dipbuy.py` on train bars (Record).
> - It claims no edge. It picks a suggested starting setting for a tool the customer owns.
> - Validate-window looks used: 0 (none is planned). The test window was not read. No bar after 2023-01-01 00:00 UTC
>   was read.

## Default: Y 30%, Z 10%, X 25%, M 100%. Label: NOT ROBUST

`decision.json`: default (0.30, 0.10, 0.25, 1.00), label "NOT ROBUST (boom: without the best 1, Binance, boom:
without the best 2: MISSING)".

## In plain words

**The default setting, as the app would say it.** "When crypto falls 30% from its highest close of the past year, buy
crypto with 25% of my cash, and buy another 25% at each further fall of 10%, until at most 100% of my cash is used."
Its four buy lines sit 30%, 37%, 43% and 49% below that high. A buy never takes the wallet below 22% USDC (the Steady
limit of 20% plus a 2-point margin), or a coin above 58%. So the caps cut part of most ladders: from an all-USDC start
the first ladder loses most of its last piece (a median 19.5% and 21% of its order), from a 30%-crypto start the last
piece and part of the third (a median 31%), and later ladders, which start near the cap, lose more (a median 37-57%).
Over a run they cut a median 27-37% of what the ladder ordered, by start.

**What it did in 2017-2022.** Kraken prices, 49 two-year windows (one starting each month, January 2017 to January
2021), a 5,000 USD deposit, four start wallets: 196 runs. The four start wallets are:
- **A:** all USDC, each buy split 50% BTC / 50% ETH;
- **B:** all USDC, each buy split 75% BTC / 25% ETH;
- **C:** 30% crypto at the start, 50/50;
- **D:** 30% crypto at the start, 75/25.

The findings:
- **It bought in every window.** So did all 54 settings, at every start: every two-year window of 2017-2022 held a
  30% fall from a one-year high.
  - At the default a window held a median of 2 ladders and 7 buy orders.
  - In 100 of the 196 runs the ladder's first order came on the window's first day, because the mix was already 30%
    below its one-year high. These are the windows starting February 2018 to May 2019 and September 2019 to May 2020
    (k = 13..28 and 32..40).
  - In 58 of those 100 runs all four lines were already crossed, so the whole ladder went in as one order that day
    (windows starting April 2018, June 2018 to May 2019 and April 2020, and January 2020 at the 50/50 starts). There
    the ladder was a one-shot buy, not small pieces as the price kept dipping.
- **The two yardsticks are the ladder's own total on a schedule, cut at the Steady limits.** Each run is compared with
  twins that order the same total the ladder ordered (before the caps), with the same caps and limit fixes:
  - **dca-same** orders it in 12 pieces 30 days apart. At the default the limits cut every one of these twins (196 of
    196), by a median 35-47% of its total, by start. The ladder ordered a median 1.73 times the starting cash, so
    each monthly piece is about 14% of the starting cash, and the wallet reaches its 78% crypto cap within a few
    months: dca-same's first cut came at a median of day 120 (1 in 10 by day 45). It got less money into crypto than
    the ladder in 173 of the 196 runs (a median 84% of what the ladder sent). So it is a monthly schedule of the
    ladder's total that hit the limit after about four months in the median window, not the same money spread calmly
    over a year;
  - **lump-same** orders the total on day one. The limits cut it harder still (a median 46-65%).
- **Against dca-same** (the capped monthly schedule):
  - it ended ahead in 94 of 196 runs (48% over the four start wallets; 43-51% by start wallet);
  - the median difference in end value was small: −3.4% to +0.3% by start;
  - single windows swung widely. At start A, 1 window in 10 ended more than 65% behind and 1 in 10 more than 38%
    ahead;
  - per dollar it ordered (before the limits cut it), it ended a median 0.6 cents behind (G̃ = −0.0057).
- **Against lump-same** (the same total on day one, capped): ahead in 122 of 196 runs (62%), median +5%.
  - It fell behind mostly in the windows starting in 2017 (8 or 9 of the 12, by start; it was ahead in the June and
    July 2017 windows at every start) and in every window from June 2020 on. There it mostly waited with cash while
    prices rose.
  - It also trailed in the April 2018 window (all four starts) and the May 2020 window (three starts). In both it
    bought on day one.
- **Against keeping the start wallet** ("hold"):
  - for an all-USDC start, hold means keeping the cash. The ladder ended ahead in 65-67% of windows, median +61% to
    +62%;
  - for a 30%-crypto start, it ended ahead in 61-73%, median +22% to +29%.
- **How much cash it put to work.**
  - It ordered a median 1.73 times the starting cash (δ). That counts the amounts the limits then cut: 36% of all it
    ordered, pooled (a median 27-37% per run, by start).
  - It actually sent a median 1.12 times the starting cash into crypto. That is more than 100% because sales by the
    limit fix refill the cash, and later ladders spend it again.
  - At the end of a window a median 26% of the wallet was USDC. Buys stop at 22% USDC; the Steady limit is 20%, and 53
    of the 196 runs ended between 20% and 22%.
  - Over a window the ladder and its twins were similarly invested on average: the median time-average crypto share
    was 68% for the ladder, 67% for dca-same and 68% for lump-same (the cap is 78%). At the end the twins held more
    cash (Readings).
- **It also sold.** With M = 100% the wallet sits near the Steady limits, so a rise pushes it past them. The limit fix
  then sells crypto, in its BTC:ETH proportion, until cash is back to at least 22% and each coin is at most 58%: a
  median 14-18 sales per two-year window.
- **Costs:** customer fees were a median 0.07-0.11% of the wallet a year, by start, and gas (sponsored by us) about
  0.02-0.03%. Fees a year leave out a window's first fill (the start purchase at C and D). In the 50 all-USDC runs
  whose ladder bought on day one, that first ladder buy (a median 0.19% of the wallet) falls there too, so those runs
  show a median 0.07% a year against 0.12% for the other all-USDC runs.
- **The bad-case fall** (Q: the fall from a peak that 1 window in 10 exceeded):
  - 65% to 72% by start, about twice the Steady budget of 35%. The budget is shown here, not enforced;
  - the worst window fell 74%, and every one of the 196 runs fell more than 35% at some point (the smallest worst
    fall was 42%);
  - dca-same was a little worse (Q 69-75%), and lump-same a little better (64-69%);
  - a wallet that only held its 30% crypto start also fell further than the budget (Q 59-61%). In a rise its crypto
    share grows, and the limit fix sells only back to 22% cash (or 58% in BTC at the 75/25 start), so it can meet a
    crash at up to about 78% crypto.
- **The falling knife.** After a ladder's last buy, the BTC/ETH mix fell a median 14% further before its next
  one-year high (or the window's end). The worst was 76%: a ladder that bought its last piece in mid-March 2018 and
  then rode the 2018 crash. The mix's next one-year high came only on 2019-06-27, and it was a high of the past year
  only: the mix was still about half its January 2018 level (51% below it), and 2% below that last buy's price.

**The app's wording** (PLAN.md section 9's example, filled in from D3 and corrected after the audit): "In 2017-2022
tests, about half the time (**43-51%** of two-year periods, by start wallet), buying on dips ended ahead of a monthly
schedule of the same total, cut at the Steady limits. After its last buy, the BTC/ETH mix fell up to **76%** (a 50/50
split) or **68%** (75/25) further."
- It must not say "the same money spread monthly": the monthly yardstick hit the limits after about four months in
  the median window.
- 48% is the pooled figure (94 of 196 runs over four start wallets); the 49 windows overlap heavily.
- Two facts belong next to it: the bad-case fall was about 70% of the wallet, twice the Steady budget; and the default
  is NOT ROBUST.

**Why NOT ROBUST.**
- The rules pick a default only among settings whose bad-case falls are no deeper than their dca-same twins', at all
  four starts. On Kraken, 10 of the 54 settings passed. Among them the default trailed dca-same least per dollar
  ordered (its G̃, the median G, is the least negative).
- Doubled costs gave the same default.
- But the bad-case test rests on the windows starting May to December 2017, where dca-same bought into the late-2017
  top. In the windows starting January to April 2017 the ladder fell deeper than dca-same at the 30%-crypto starts.
  Binance's windows start in September 2017. On Binance, and on Kraken without the windows that touch 2017, no setting
  passes, so there is no default.
- Without both 2017 and 2020, only 2 windows are left: too few to decide (MISSING).

**So:** (30%, 10%, 25%, 100%) is the best of the 54 settings by the rules fixed before the run, but it is an isolated,
knife-edge pick.
- Its bad-case test holds only narrowly (start D: 71.19% against 71.27%, a margin of 0.08 of a point), and only with
  the 2017 windows.
- None of its five one-step neighbours in the grid passes that test. One of them, (30%, 5%, 25%, 100%), fails it by
  0.04 of a point.
- Had start D's margin gone the other way, the rules would have named (10%, 20%, 25%, 100%).
- Against the capped monthly schedule it is close to a coin flip, and its bad-case fall is far beyond the Steady
  budget.

## The default and the robustness checks (D1, D2)

**D1 on the decision pool** (Kraken 1x, 49 windows). Every setting was active: it filled at least one ladder order in
all 49 windows at every start, so rule 1 never bound. 10 of 54 settings kept both Q ≤ Q_dca and max F ≤ max F_dca at
all four starts:

| Y | Z | X | M | G̃ | Median δ | |
|---|---|---|---|---|---|---|
| 30% | 10% | 25% | 100% | −0.0057 | 1.73 | **the default** (the only candidate within 1e-12 of the best G̃) |
| 10% | 20% | 25% | 100% | −0.0187 | 2.83 | |
| 10% | 5% | 25% | 100% | −0.0393 | 4.48 | |
| 10% | 5% | 25% | 50% | −0.1357 | 2.76 | |
| 10% | 10% | 25% | 50% | −0.1451 | 2.40 | |
| 10% | 5% | 10% | 50% | −0.1736 | 1.90 | |
| 20% | 5% | 25% | 50% | −0.2778 | 1.35 | |
| 20% | 5%, 10%, 20% | 25% | 25% | −0.5033 | 0.77 | the same runs: with X = M there is one line, so Z changes nothing |

- **Every usable setting has a negative G̃:** in the median run, each ended behind its dca-same twin, per dollar it
  ordered (before the limits cut it). The default trails least.
- **Six settings had a positive G̃** (up to +0.036, at Y 10%, Z 20%, X 10%, M 100%). None was usable: each had a deeper
  bad-case fall than dca-same at one or more starts.
- **The default sits at a corner of the range:** the largest Y, X and M on offer.
- **It is an isolated passing point.** Each of its five one-step neighbours in the grid fails the bad-case test:
  - Y 20%: (20%, 10%, 25%, 100%) has the deeper worst fall at B (by 2.4 points) and D (by 1.0);
  - Z 5%: (30%, 5%, 25%, 100%) at D, by 0.04 of a point (71.53% against 71.49%);
  - Z 20%: (30%, 20%, 25%, 100%) at D, by 5.0 points;
  - X 10%: (30%, 10%, 10%, 100%) fails Q at A, C and D, and the worst fall at A and D;
  - M 50%: (30%, 10%, 25%, 50%) fails Q at A and the worst fall at D.
- **Its narrowest margin** is start D's worst fall: 71.19% against dca-same's 71.27%, 0.08 of a point, in a comparison
  of two single windows (the ladder's worst is window 0, dca-same's window 10). Had it gone the other way, D1 would have
  named the next usable setting, (10%, 20%, 25%, 100%) (G̃ −0.0187).

**D2, check by check.** The default's own numbers in each pool (Q / Q_dca; max F / max F_dca, in %; a failing pair
in bold):

| Pool | Windows | D1 gives (Y, Z, X, M in %) | Usable settings | Default's G̃ | A: Q / Q_dca; max F / F_dca | B | C | D |
|---|---|---|---|---|---|---|---|---|
| Kraken 1x (decision) | 49 | (30, 10, 25, 100) | 10 | −0.0057 | 70.75 / 73.39; 72.46 / 75.67 | 64.74 / 68.62; 66.26 / 69.75 | 72.39 / 74.62; 74.14 / 78.79 | 67.22 / 68.85; 71.19 / 71.27 |
| Kraken 2x | 49 | (30, 10, 25, 100) | 10 | −0.0050 | 70.76 / 73.41; 72.48 / 75.70 | 64.78 / 68.66; 66.29 / 69.74 | 72.41 / 74.64; 74.15 / 78.81 | 67.25 / 68.85; 71.21 / 71.30 |
| Binance 1x | 41 | NO DEFAULT | 0 | −0.0038 | 64.32 / 66.50; 71.11 / 75.45 | **62.45 / 60.28**; 65.22 / 68.67 | 65.58 / 72.72; 71.07 / 78.59 | **64.58 / 63.78**; 65.66 / 71.03 |
| Kraken 1x without 2017 | 37 | NO DEFAULT | 0 | −0.0109 | **64.35 / 61.40**; 65.40 / 66.61 | **62.70 / 59.35**; **65.46 / 62.20** | **65.30 / 63.43**; 65.66 / 73.03 | **63.30 / 59.77**; **65.44 / 63.95** |

- **2x costs (Kraken 2x, 49 windows): the same default.** The same 10 settings were usable; the default's G̃ is
  −0.0050. Doubled costs move each run's numbers by a hair; start D's margin is 71.21% against 71.30%.
- **Binance (1x, 41 windows, starting September 2017 to January 2021): NO DEFAULT, so it moved.** No setting was
  usable. Every setting was active in all 41 windows at every start, so the failures are all in the bad-case test:
  - the Q condition (Q ≤ Q_dca) held at all four starts for **no** setting. It failed most at the 75%-BTC starts: it
    held at start D for 5 of 54 settings, at B for 20, at A for 31 and at C for 34;
  - the worst-fall condition (max F ≤ max F_dca) held at all four starts for 29 settings;
  - **the default** passed both conditions at A and C, and failed Q at B (62.45% against 60.28%) and D (64.58%
    against 63.78%);
  - five settings failed at one start only, each on Q: (20%, 20%, 10%, 100%) at D, 64.32% against 62.14%;
    (30%, 5%, 25%, 50%) at D, 62.74% against 62.14%; (30%, 5%, 25%, 100%) at B, 60.39% against 60.14%;
    (30%, 20%, 10%, 100%) at D, 62.92% against 61.13%; (30%, 20%, 25%, 100%) at D, 65.50% against 62.29%;
  - a description (decides nothing; this file's recompute, not in `decision.json`): Kraken's own runs on Binance's 41
    windows (k = 8..48) also give NO DEFAULT, failing at the same starts. So the windows Binance lacks (starting
    January to August 2017) are enough to move it; Binance's prices are not needed for the move. The counts differ a
    little: the Q condition held at start D for 3 settings on Kraken's k = 8..48 against 5 on Binance, and the
    worst-fall condition at A for 35 against 37.
- **Without BTC's best year (2017, +1,304% on Kraken): NO DEFAULT, so it moved.** The windows that touch 2017 are
  k = 0..11; 37 remain (k = 12..48, starting January 2018 to January 2021).
  - No setting was usable. The Q condition held at all four starts for no setting; at start C it held for 1 setting
    and at D for none.
  - The default failed Q at all four starts (A 64.35% against 61.40%, B 62.70% / 59.35%, C 65.30% / 63.43%, D
    63.30% / 59.77%), and the worst fall at B and D.
- **Without the two best years (2017 and 2020, +304%): MISSING.** Every window from k = 13 to 47 touches 2020, and
  k = 0..11 touch 2017. Only k = 12 (2018-2019) and k = 48 (2021-2022) remain: 2 windows, fewer than the 12 the rule
  needs.
- BTC's calendar-year returns on Kraken, as ranked before any backtest (`start.json`): 2017 +1,304%, 2020 +304%, 2019
  +94%, 2021 +59%, 2022 −64%, 2018 −74%.

**What the checks say together** (a description from `runs.parquet`, at the default):
- In every window starting from May to December 2017 (k = 4..11), at all four starts, dca-same's worst fall was deeper
  than the ladder's by more than a point. dca-same's monthly pieces through 2017 bought into the late-2017 top.
- In the windows starting January to April 2017 (k = 0..3) it went the other way at the 30%-crypto starts: the
  ladder's worst fall was the deeper one, by 0.3 to 7.9 points (and at start A in the January and February 2017
  windows). So the windows that carry the test are those starting May to December 2017.
- The ladder's worst fall was the deeper one in 20 to 24 of the 49 windows (by start), always including the windows
  starting from March 2020 on (k = 38..48). In those from June 2020 on (k = 41..48) it waited with cash through the
  2020-21 rise (its first ladder order came 138 to 352 days in) and bought in the 2021-22 falls.
- Remove the 2017 windows, or only the January-August 2017 ones that Binance lacks, and Q tips against the ladder at
  some start. On Kraken's windows k = 8..48 the default fails Q at B (62.70% against 60.45%) and D (64.31% against
  63.95%), the same starts as on Binance.

## D3: the description at the default (Kraken 1x)

What each measure means:
- **G:** the end value against dca-same, per dollar the ladder ordered before the limits cut it:
  (V_end − V_end(dca-same)) / ordered. Over the runs with a ladder order (all 49 here).
- **T_dca, T_lump, T_hold:** how much more (or less) the ladder's wallet was worth at the window's end than dca-same,
  lump-same and hold. For an all-USDC start, hold is the cash, so T_hold is the ladder wallet's own gain. dca-same and
  lump-same are the ladder's total on a schedule, cut at the Steady limits (In plain words).
- **Q of each kind:** the 90th percentile of its 49 worst falls from a peak (1 window in 10 fell further).
- **The knife:** after a ladder's last buy, the further fall of the BTC/ETH mix from its price at that buy's fill (the
  next open) to its lowest close before the next one-year high (or the window's end). Positive is a further fall.
  Over every ladder that sent an order.
- **δ:** the money the ladder ordered (before the limits cut it) over the starting cash B_0 = (1 − s0) × 5,000 USD.
- **USDC left:** the wallet's USDC share at the last close.

**Per start** (the default's runs; median [10th, 90th percentile], share of the 49 windows above 0):

| Start | n | G: median [p10, p90], share > 0 | T_dca | T_lump | T_hold |
|---|---|---|---|---|---|
| A | 49 | −0.001 [−1.031, +0.431], 49% | −0.3% [−65.4%, +38.7%], 49% | +4.8% [−75.1%, +21.2%], 61% | +62.2% [−30.8%, +749.7%], 65% |
| B | 49 | −0.025 [−0.913, +0.378], 43% | −3.4% [−58.7%, +31.5%], 43% | +5.5% [−66.4%, +23.7%], 61% | +61.2% [−27.5%, +607.1%], 67% |
| C | 49 | +0.003 [−0.597, +0.244], 51% | +0.3% [−38.9%, +15.2%], 51% | +4.8% [−41.0%, +14.2%], 63% | +28.7% [−14.0%, +86.0%], 61% |
| D | 49 | −0.004 [−0.564, +0.272], 49% | −0.5% [−35.5%, +12.7%], 49% | +5.2% [−37.7%, +16.1%], 63% | +22.0% [−8.5%, +80.0%], 73% |

- G and T_dca have the same sign in every run, so their shares above 0 match: both divide the same end-value gap, G by
  the dollars the ladder ordered (before the limits cut them) and T_dca by dca-same's end value.
- Across the 196 runs: ahead of dca-same in 94 (48%), of lump-same in 122 (62%), of hold in 131 (67%).

**Bad case, knife and cash, per start** (against the Steady budget as read, 35%; shown, not enforced):

| Start | Q | Q_dca | Q_lump | Q_hold | Knife median | Knife worst | Median δ | Median USDC left |
|---|---|---|---|---|---|---|---|---|
| A | 70.7% | 73.4% | 69.0% | 0.0% | 14.0% | 76.4% | 1.45 | 23.9% |
| B | 64.7% | 68.6% | 63.8% | 0.0% | 7.7% | 67.7% | 1.51 | 29.1% |
| C | 72.4% | 74.6% | 69.0% | 61.3% | 14.0% | 76.4% | 1.95 | 24.4% |
| D | 67.2% | 68.9% | 63.8% | 59.4% | 7.7% | 67.7% | 1.91 | 29.0% |

- Above the 35% budget (`above_budget` in `decision.json`): Q, Q_dca and Q_lump at every start, and Q_hold at C and
  D. Q_hold is 0 at A and B, where hold is cash. At C and D, a rise lifts hold's crypto share, and the limit fix
  sells only until cash is back to at least 22% and each coin is at most 58%, so a held wallet can ride a crash at up
  to about 78% crypto.
- Over all four starts the knife's median is 14.0% and its worst 76.4% (446 ladders, all with an order sent). By the
  year the ladder started, the worst knives were 2018's (median 66%, worst 76%), then 2022's (median 42%, worst 48%)
  and 2019's (median 27%, worst 30%); ladders started in 2017 never saw the mix fall below their last buy's price.
- More on the cash (a description): the ladder sent a median 1.06-1.17 times the starting cash, and the limits cut a
  median 27-37% of each run's ordered amount. Nothing was blocked by a limit fix and no line was left "not filled" at
  the default. Ladders per window: 2 or 3; buy orders 4 to 9 (median 7); pieces filled median 8; limit-fix sales a
  median 14-18 (dca-same 13-16, lump-same 13-15).

**By the year of each window's first close** (median [10th, 90th percentile], share above 0; 12 windows a year, and
2021 holds only window 48):

| Start | Year | n | G | T_dca | T_lump | T_hold |
|---|---|---|---|---|---|---|
| A | 2017 | 12 | +0.031 [−1.857, +0.351], 58% | +5.1% [−70.7%, +49.8%], 58% | −35.3% [−82.2%, +18.3%], 25% | +61.0% [−24.2%, +146.5%], 75% |
| A | 2018 | 12 | −0.270 [−0.558, +0.007], 17% | −25.1% [−33.0%, +1.3%], 17% | +4.9% [+3.0%, +15.4%], 92% | −3.0% [−29.2%, +82.6%], 50% |
| A | 2019 | 12 | +0.183 [+0.011, +1.415], 92% | +7.6% [+0.4%, +38.9%], 92% | +6.7% [+5.3%, +22.0%], 100% | +628.2% [+483.2%, +851.7%], 100% |
| A | 2020 | 12 | −0.410 [−1.268, +0.317], 33% | −43.8% [−72.7%, +19.5%], 33% | −65.6% [−77.4%, +22.3%], 33% | −13.6% [−34.9%, +833.7%], 42% |
| A | 2021 | 1 | −0.119 [−0.119, −0.119], 0% | −20.8% [−20.8%, −20.8%], 0% | −52.5% [−52.5%, −52.5%], 0% | −37.7% [−37.7%, −37.7%], 0% |
| B | 2017 | 12 | −0.006 [−1.198, +0.297], 42% | −0.5% [−60.7%, +31.6%], 42% | −42.3% [−73.9%, +7.4%], 25% | +57.9% [−12.9%, +148.2%], 75% |
| B | 2018 | 12 | −0.115 [−0.429, +0.019], 17% | −14.4% [−27.0%, +3.1%], 17% | +7.0% [+5.3%, +13.1%], 92% | +16.3% [−14.6%, +86.9%], 58% |
| B | 2019 | 12 | +0.166 [−0.061, +1.447], 83% | +8.4% [−2.6%, +38.9%], 83% | +10.1% [+5.9%, +23.7%], 100% | +528.3% [+370.3%, +693.2%], 100% |
| B | 2020 | 12 | −0.452 [−1.017, +0.278], 33% | −38.6% [−66.4%, +19.0%], 33% | −58.4% [−71.3%, +25.0%], 33% | −12.4% [−32.8%, +597.4%], 42% |
| B | 2021 | 1 | −0.049 [−0.049, −0.049], 0% | −9.6% [−9.6%, −9.6%], 0% | −42.4% [−42.4%, −42.4%], 0% | −38.0% [−38.0%, −38.0%], 0% |
| C | 2017 | 12 | −0.037 [−0.577, +0.221], 42% | −3.4% [−41.7%, +23.1%], 42% | −25.9% [−39.9%, +13.7%], 25% | +1.1% [−12.0%, +65.6%], 50% |
| C | 2018 | 12 | −0.150 [−0.427, +0.023], 25% | −14.2% [−22.0%, +1.1%], 25% | +4.9% [+3.2%, +8.2%], 92% | −0.0% [−20.8%, +39.8%], 50% |
| C | 2019 | 12 | +0.125 [+0.026, +1.138], 100% | +5.8% [+0.7%, +17.9%], 100% | +6.5% [+5.3%, +14.8%], 100% | +78.4% [+76.3%, +92.2%], 100% |
| C | 2020 | 12 | −0.446 [−0.840, +0.191], 42% | −32.0% [−42.2%, +12.1%], 42% | −40.3% [−43.2%, +15.0%], 42% | −0.3% [−5.9%, +92.8%], 50% |
| C | 2021 | 1 | −0.199 [−0.199, −0.199], 0% | −21.6% [−21.6%, −21.6%], 0% | −35.2% [−35.2%, −35.2%], 0% | −17.5% [−17.5%, −17.5%], 0% |
| D | 2017 | 12 | −0.003 [−0.590, +0.192], 50% | −0.4% [−34.0%, +16.5%], 50% | −21.1% [−36.2%, +4.3%], 33% | +11.3% [−3.7%, +48.7%], 75% |
| D | 2018 | 12 | −0.067 [−0.282, +0.018], 33% | −7.1% [−16.9%, +1.7%], 33% | +6.6% [+5.2%, +9.0%], 92% | +12.1% [−8.9%, +41.3%], 75% |
| D | 2019 | 12 | +0.144 [−0.023, +0.880], 83% | +6.4% [−0.7%, +16.1%], 83% | +10.1% [+5.5%, +17.2%], 100% | +76.0% [+69.8%, +93.1%], 100% |
| D | 2020 | 12 | −0.393 [−0.649, +0.207], 33% | −29.6% [−37.8%, +8.5%], 33% | −35.6% [−39.5%, +14.8%], 33% | −1.1% [−8.2%, +92.0%], 50% |
| D | 2021 | 1 | −0.111 [−0.111, −0.111], 0% | −14.5% [−14.5%, −14.5%], 0% | −30.8% [−30.8%, −30.8%], 0% | −21.5% [−21.5%, −21.5%], 0% |

What the years show (descriptions):
- **Windows starting in 2019** were the ladder's best against dca-same: ahead in 83-100% of them, median +6% to +8%.
- **Windows starting in 2018 and 2020** were its worst: ahead in 17-42%.
  - In 11 of the 12 windows starting in 2018 (February to December) it bought on the window's first day; from the
    April window on (May aside) that first order took all four lines at once. The fall went on for months: at start A
    the mix fell another 26-75% after those whole-ladder orders, while dca-same's later pieces bought lower.
  - From June 2020 it waited with cash through the rise.
- **Windows starting in 2017** were mixed against dca-same (42-58% ahead), and mostly behind lump-same (25-33% ahead):
  money put in at once in early 2017 rode the 2017 rise.
- The overlapping windows share their years, so these rows are not independent: one crash or one boom stands behind
  many windows.

## The full table per setting and start (Kraken 1x, the decision pool)

- **Starts:** A all USDC, f 50%; B all USDC, f 75%; C 30% crypto, f 50%; D 30% crypto, f 75% (f is BTC's share of each
  buy).
- **Active:** every setting filled at least one ladder order in **49 of 49** windows at every start, so the column is
  left out.
- **The cells** are in % (Q / Q_dca, and max F / max F_dca, the worst fall over the 49 windows). A pair that fails D1's
  condition (the ladder's number above dca-same's) is in bold.
- **G̃** is the median G over the setting's 196 runs with an order (all of them here). **Median δ** is over its 196
  runs.
- Rows with X = M have one line, so Z changes nothing and their numbers repeat.

| Y | Z | X | M | Usable | Why not | G̃ | median δ | A: Q / Q_dca | A: max F / F_dca | B: Q / Q_dca | B: max F / F_dca | C: Q / Q_dca | C: max F / F_dca | D: Q / Q_dca | D: max F / F_dca |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 10 | 25 | no | max F at B | −0.3923 | 1.17 | 70.94 / 71.30 | 73.22 / 75.30 | 62.99 / 66.33 | **70.38 / 69.74** | 71.29 / 72.74 | 72.47 / 77.34 | 64.23 / 66.91 | 70.19 / 70.79 |
| 10 | 5 | 10 | 50 | yes | - | −0.1736 | 1.90 | 70.09 / 73.03 | 71.77 / 75.40 | 63.19 / 68.77 | 69.50 / 70.09 | 70.32 / 74.38 | 71.78 / 78.26 | 65.64 / 68.57 | 69.70 / 70.05 |
| 10 | 5 | 10 | 100 | no | max F at B,D | −0.0558 | 2.90 | 71.54 / 73.82 | 73.71 / 76.25 | 67.96 / 69.18 | **72.33 / 70.88** | 72.61 / 74.49 | 73.73 / 78.90 | 68.67 / 69.39 | **72.41 / 71.48** |
| 10 | 5 | 25 | 25 | no | max F at D | −0.3894 | 1.40 | 70.90 / 71.80 | 71.79 / 75.41 | 62.37 / 66.59 | 69.28 / 70.01 | 71.15 / 73.04 | 72.50 / 77.35 | 63.71 / 67.44 | **70.45 / 69.56** |
| 10 | 5 | 25 | 50 | yes | - | −0.1357 | 2.76 | 71.50 / 72.91 | 73.42 / 76.79 | 64.39 / 68.97 | 68.88 / 70.81 | 72.11 / 74.56 | 73.48 / 78.61 | 65.17 / 68.67 | 69.91 / 70.90 |
| 10 | 5 | 25 | 100 | yes | - | −0.0393 | 4.48 | 70.43 / 74.13 | 72.17 / 77.54 | 66.00 / 69.53 | 69.83 / 71.41 | 70.84 / 74.50 | 72.21 / 78.74 | 66.96 / 69.54 | 69.41 / 71.59 |
| 10 | 10 | 10 | 25 | no | Q at A; max F at B,D | −0.3928 | 1.01 | **71.65 / 71.16** | 73.86 / 75.09 | 62.60 / 65.85 | **70.23 / 69.90** | 72.15 / 72.79 | 73.00 / 76.89 | 65.59 / 66.40 | **70.17 / 69.62** |
| 10 | 10 | 10 | 50 | no | Q at A; max F at B,D | −0.1970 | 1.50 | **72.62 / 72.54** | 74.79 / 75.39 | 66.16 / 68.39 | **72.31 / 69.98** | 73.29 / 73.78 | 74.90 / 77.83 | 68.10 / 68.71 | **72.54 / 70.23** |
| 10 | 10 | 10 | 100 | no | Q at A; max F at A,B,D | +0.0021 | 2.15 | **74.02 / 72.95** | **75.98 / 75.49** | 67.42 / 68.98 | **72.99 / 70.22** | 74.57 / 74.62 | 76.09 / 78.62 | 68.46 / 68.79 | **72.97 / 71.00** |
| 10 | 10 | 25 | 25 | no | max F at D | −0.3894 | 1.40 | 70.90 / 71.80 | 71.79 / 75.41 | 62.37 / 66.59 | 69.28 / 70.01 | 71.15 / 73.04 | 72.50 / 77.35 | 63.71 / 67.44 | **70.45 / 69.56** |
| 10 | 10 | 25 | 50 | yes | - | −0.1451 | 2.40 | 71.50 / 72.91 | 73.42 / 76.83 | 63.29 / 68.87 | 68.53 / 70.44 | 72.18 / 74.56 | 73.48 / 78.61 | 64.02 / 68.57 | 69.61 / 70.00 |
| 10 | 10 | 25 | 100 | no | Q at B,D; max F at B,D | −0.0442 | 3.58 | 72.10 / 73.89 | 73.61 / 77.53 | **69.94 / 69.51** | **72.18 / 71.58** | 72.65 / 74.48 | 73.64 / 78.81 | **69.83 / 69.40** | **72.28 / 71.43** |
| 10 | 20 | 10 | 25 | no | Q at A,C; max F at B,D | −0.4553 | 0.83 | **71.29 / 68.35** | 74.42 / 74.69 | 62.39 / 64.36 | **72.08 / 69.61** | **72.33 / 71.51** | 73.19 / 75.61 | 65.31 / 65.77 | **72.27 / 70.50** |
| 10 | 20 | 10 | 50 | no | Q at A,B,C,D; max F at B,D | −0.1551 | 1.13 | **72.32 / 71.32** | 75.04 / 75.49 | **67.46 / 66.82** | **73.63 / 69.63** | **73.09 / 72.99** | 75.12 / 76.72 | **69.00 / 68.13** | **74.12 / 69.59** |
| 10 | 20 | 10 | 100 | no | Q at A,B,C,D; max F at A,B,C,D | +0.0364 | 1.36 | **75.59 / 73.09** | **78.54 / 75.53** | **68.81 / 68.25** | **75.37 / 69.77** | **76.73 / 74.55** | **79.00 / 78.40** | **70.43 / 68.73** | **75.81 / 71.32** |
| 10 | 20 | 25 | 25 | no | max F at D | −0.3894 | 1.40 | 70.90 / 71.80 | 71.79 / 75.41 | 62.37 / 66.59 | 69.28 / 70.01 | 71.15 / 73.04 | 72.50 / 77.35 | 63.71 / 67.44 | **70.45 / 69.56** |
| 10 | 20 | 25 | 50 | no | Q at D; max F at D | −0.1600 | 2.01 | 72.62 / 73.10 | 74.18 / 75.64 | 68.24 / 68.89 | 70.09 / 70.16 | 72.85 / 73.96 | 73.81 / 78.23 | **68.55 / 68.42** | **70.22 / 70.03** |
| 10 | 20 | 25 | 100 | yes | - | −0.0187 | 2.83 | 72.85 / 73.37 | 74.47 / 76.02 | 68.24 / 69.33 | 70.58 / 70.95 | 73.05 / 74.50 | 74.48 / 78.94 | 68.40 / 69.40 | 70.73 / 71.08 |
| 20 | 5 | 10 | 25 | no | Q at A; max F at B | −0.5395 | 0.62 | **70.33 / 68.71** | 72.32 / 73.94 | 62.65 / 63.94 | **71.11 / 69.61** | 70.88 / 70.90 | 72.19 / 75.75 | 63.75 / 64.76 | 70.83 / 70.89 |
| 20 | 5 | 10 | 50 | no | Q at D; max F at B,D | −0.3399 | 1.16 | 71.37 / 72.07 | 74.89 / 75.44 | 67.02 / 68.37 | **72.48 / 69.76** | 71.83 / 73.08 | 75.03 / 77.42 | **69.34 / 68.54** | **72.59 / 70.22** |
| 20 | 5 | 10 | 100 | no | max F at B | −0.0410 | 1.96 | 71.32 / 73.42 | 74.00 / 75.70 | 67.70 / 68.83 | **71.11 / 70.29** | 72.60 / 74.55 | 74.20 / 78.84 | 67.90 / 69.18 | 71.22 / 71.28 |
| 20 | 5 | 25 | 25 | yes | - | −0.5033 | 0.77 | 70.66 / 70.97 | 72.86 / 74.65 | 62.52 / 63.93 | 68.82 / 69.61 | 70.71 / 72.37 | 72.16 / 75.54 | 63.63 / 64.68 | 69.16 / 70.89 |
| 20 | 5 | 25 | 50 | yes | - | −0.2778 | 1.35 | 69.49 / 72.25 | 72.23 / 75.51 | 61.76 / 68.94 | 69.68 / 69.97 | 70.38 / 74.11 | 72.17 / 77.92 | 64.41 / 68.55 | 69.83 / 70.80 |
| 20 | 5 | 25 | 100 | no | max F at B,D | −0.0938 | 2.44 | 71.97 / 73.37 | 74.02 / 75.64 | 68.68 / 69.27 | **71.67 / 70.15** | 72.66 / 74.48 | 74.17 / 78.88 | 69.18 / 69.20 | **71.67 / 71.33** |
| 20 | 10 | 10 | 25 | no | Q at A,C; max F at A,B,D | −0.5652 | 0.61 | **71.46 / 67.98** | **74.01 / 73.96** | 62.43 / 63.99 | **70.95 / 69.48** | **71.75 / 70.92** | 74.00 / 75.41 | 64.21 / 64.52 | **71.98 / 70.89** |
| 20 | 10 | 10 | 50 | no | max F at B,D | −0.2665 | 1.04 | 71.20 / 71.72 | 74.42 / 75.37 | 66.18 / 67.49 | **70.64 / 69.59** | 72.70 / 73.04 | 74.44 / 76.83 | 67.11 / 68.17 | **71.78 / 69.58** |
| 20 | 10 | 10 | 100 | no | Q at A,C; max F at A,B,D | +0.0012 | 1.57 | **74.71 / 73.06** | **77.27 / 75.52** | 67.71 / 68.32 | **74.77 / 69.76** | **75.81 / 74.65** | 77.45 / 78.44 | 68.29 / 68.55 | **76.80 / 70.69** |
| 20 | 10 | 25 | 25 | yes | - | −0.5033 | 0.77 | 70.66 / 70.97 | 72.86 / 74.65 | 62.52 / 63.93 | 68.82 / 69.61 | 70.71 / 72.37 | 72.16 / 75.54 | 63.63 / 64.68 | 69.16 / 70.89 |
| 20 | 10 | 25 | 50 | no | Q at A,B,D; max F at B,D | −0.2946 | 1.36 | **72.26 / 72.25** | 74.05 / 75.52 | **68.69 / 68.36** | **70.20 / 70.02** | 72.84 / 73.89 | 74.23 / 77.76 | **68.75 / 68.55** | **70.23 / 70.22** |
| 20 | 10 | 25 | 100 | no | max F at B,D | −0.0731 | 2.36 | 72.47 / 73.37 | 74.60 / 75.70 | 68.32 / 69.00 | **72.35 / 69.96** | 73.15 / 74.50 | 74.74 / 78.87 | 68.37 / 69.06 | **72.41 / 71.37** |
| 20 | 20 | 10 | 25 | no | Q at A,C,D; max F at A,B,D | −0.5230 | 0.58 | **71.28 / 66.33** | **74.04 / 73.33** | 62.10 / 63.66 | **71.02 / 69.50** | **71.42 / 70.66** | 73.98 / 74.43 | **64.27 / 63.80** | **72.08 / 70.88** |
| 20 | 20 | 10 | 50 | no | Q at A,B,C,D; max F at A,B,C,D | −0.3028 | 0.84 | **73.78 / 70.81** | **76.69 / 74.07** | **66.89 / 64.48** | **73.72 / 69.62** | **74.33 / 72.81** | **76.54 / 75.26** | **67.69 / 67.17** | **74.70 / 70.50** |
| 20 | 20 | 10 | 100 | no | Q at A,B,C,D; max F at A,B,C,D | −0.0679 | 1.05 | **76.38 / 73.18** | **79.60 / 75.49** | **68.31 / 68.04** | **74.87 / 69.58** | **77.10 / 74.30** | **79.50 / 78.37** | **69.02 / 68.53** | **75.81 / 69.87** |
| 20 | 20 | 25 | 25 | yes | - | −0.5033 | 0.77 | 70.66 / 70.97 | 72.86 / 74.65 | 62.52 / 63.93 | 68.82 / 69.61 | 70.71 / 72.37 | 72.16 / 75.54 | 63.63 / 64.68 | 69.16 / 70.89 |
| 20 | 20 | 25 | 50 | no | Q at B,D; max F at B,D | −0.2923 | 1.35 | 71.45 / 72.24 | 75.18 / 75.36 | **68.50 / 68.31** | **72.39 / 70.02** | 72.13 / 73.89 | 75.33 / 77.79 | **68.94 / 68.56** | **72.42 / 70.22** |
| 20 | 20 | 25 | 100 | no | max F at B,D | −0.0100 | 2.00 | 71.85 / 72.79 | 74.27 / 75.70 | 67.55 / 68.95 | **71.46 / 70.26** | 72.63 / 74.58 | 74.43 / 78.62 | 68.23 / 68.90 | **71.49 / 70.96** |
| 30 | 5 | 10 | 25 | no | Q at A,C; max F at D | −0.5350 | 0.44 | **72.01 / 67.34** | 72.01 / 73.88 | 62.13 / 63.89 | 62.13 / 69.51 | **71.39 / 70.56** | 73.85 / 74.71 | 63.33 / 64.06 | **73.24 / 70.56** |
| 30 | 5 | 10 | 50 | no | Q at B; max F at D | −0.2871 | 0.87 | 70.73 / 71.41 | 70.82 / 75.36 | **66.25 / 64.97** | 66.25 / 69.61 | 72.43 / 72.96 | 74.25 / 77.20 | 67.12 / 68.30 | **73.33 / 69.62** |
| 30 | 5 | 10 | 100 | no | max F at D | +0.0125 | 1.62 | 72.37 / 73.32 | 72.37 / 75.53 | 66.28 / 68.38 | 66.28 / 69.61 | 72.88 / 74.67 | 74.57 / 78.61 | 66.96 / 68.71 | **72.92 / 70.84** |
| 30 | 5 | 25 | 25 | no | Q at A,C; max F at D | −0.5536 | 0.44 | **71.92 / 67.29** | 71.92 / 73.55 | 62.26 / 64.05 | 62.26 / 69.49 | **72.01 / 70.55** | 73.21 / 74.88 | 63.38 / 65.03 | **72.76 / 70.54** |
| 30 | 5 | 25 | 50 | no | max F at D | −0.3307 | 0.93 | 71.29 / 71.92 | 71.63 / 75.45 | 66.39 / 68.73 | 67.51 / 69.99 | 71.57 / 73.00 | 75.02 / 77.20 | 67.22 / 68.55 | **72.55 / 69.57** |
| 30 | 5 | 25 | 100 | no | max F at D | −0.0518 | 1.83 | 72.10 / 73.45 | 72.81 / 75.72 | 64.91 / 69.01 | 67.45 / 70.27 | 72.65 / 74.53 | 74.58 / 78.88 | 67.51 / 69.12 | **71.53 / 71.49** |
| 30 | 10 | 10 | 25 | no | Q at A,C,D; max F at D | −0.5058 | 0.44 | **71.09 / 66.15** | 71.09 / 73.22 | 62.04 / 62.35 | 62.04 / 69.39 | **71.18 / 70.30** | 72.36 / 73.45 | **63.86 / 63.64** | **73.84 / 70.87** |
| 30 | 10 | 10 | 50 | no | Q at A,B,D; max F at D | −0.1761 | 0.80 | **72.05 / 67.93** | 72.05 / 75.22 | **67.14 / 64.14** | 67.14 / 69.50 | 72.42 / 72.86 | 74.46 / 75.45 | **68.02 / 67.21** | **73.29 / 70.50** |
| 30 | 10 | 10 | 100 | no | Q at A,C,D; max F at A,D | +0.0328 | 1.31 | **75.50 / 73.10** | **75.50 / 75.45** | 67.97 / 68.42 | 67.97 / 69.66 | **75.64 / 74.47** | 78.09 / 78.39 | **69.10 / 68.28** | **77.19 / 70.80** |
| 30 | 10 | 25 | 25 | no | Q at A,C; max F at D | −0.5536 | 0.44 | **71.92 / 67.29** | 71.92 / 73.55 | 62.26 / 64.05 | 62.26 / 69.49 | **72.01 / 70.55** | 73.21 / 74.88 | 63.38 / 65.03 | **72.76 / 70.54** |
| 30 | 10 | 25 | 50 | no | Q at A; max F at D | −0.3417 | 0.90 | **72.12 / 71.92** | 72.66 / 75.41 | 66.49 / 67.70 | 66.81 / 69.88 | 72.60 / 73.00 | 74.54 / 77.20 | 66.98 / 68.36 | **72.53 / 70.81** |
| 30 | 10 | 25 | 100 | **yes (default)** | - | −0.0057 | 1.73 | 70.75 / 73.39 | 72.46 / 75.67 | 64.74 / 68.62 | 66.26 / 69.75 | 72.39 / 74.62 | 74.14 / 78.79 | 67.22 / 68.85 | 71.19 / 71.27 |
| 30 | 20 | 10 | 25 | no | Q at A,B,C,D; max F at C,D | −0.4059 | 0.44 | **68.01 / 62.39** | 68.01 / 71.30 | **58.60 / 58.07** | 58.60 / 69.39 | **70.89 / 67.60** | **73.74 / 72.74** | **63.71 / 63.00** | **73.85 / 70.87** |
| 30 | 20 | 10 | 50 | no | Q at A,C,D; max F at C,D | −0.2654 | 0.65 | **72.38 / 67.62** | 72.38 / 73.93 | 63.59 / 63.65 | 63.59 / 69.48 | **73.61 / 72.59** | **75.27 / 74.18** | **67.71 / 67.03** | **76.72 / 70.51** |
| 30 | 20 | 10 | 100 | no | Q at A,C,D; max F at D | −0.0481 | 0.83 | **74.73 / 72.20** | 74.73 / 75.38 | 65.17 / 66.05 | 65.17 / 69.49 | **75.75 / 73.69** | 77.79 / 77.97 | **68.74 / 68.20** | **77.69 / 69.61** |
| 30 | 20 | 25 | 25 | no | Q at A,C; max F at D | −0.5536 | 0.44 | **71.92 / 67.29** | 71.92 / 73.55 | 62.26 / 64.05 | 62.26 / 69.49 | **72.01 / 70.55** | 73.21 / 74.88 | 63.38 / 65.03 | **72.76 / 70.54** |
| 30 | 20 | 25 | 50 | no | max F at D | −0.2772 | 0.86 | 70.60 / 71.36 | 70.60 / 75.34 | 65.69 / 67.08 | 66.51 / 69.63 | 71.32 / 72.97 | 74.05 / 77.20 | 67.10 / 68.27 | **73.44 / 69.62** |
| 30 | 20 | 25 | 100 | no | max F at D | +0.0171 | 1.50 | 71.56 / 73.03 | 71.56 / 75.41 | 66.82 / 68.32 | 67.17 / 69.62 | 72.09 / 74.68 | 74.16 / 78.55 | 67.83 / 68.55 | **76.03 / 71.00** |

Summary of the decision pool:
- 10 settings usable;
- Q ≤ Q_dca held at all four starts for 25 settings, and max F ≤ max F_dca for 10. The worst-fall condition is the
  one that binds;
- by start, Q ≤ Q_dca held for 30 settings at A, 44 at B, 37 at C and 38 at D; max F ≤ max F_dca for 46 at A, 31 at
  B, 49 at C and 13 at D;
- 11 settings failed at one start only, all at B or D on the worst fall (one of them on Q too).

## Why each setting is usable or not, in each pool

One row per setting. "Q at B,D" means Q > Q_dca at starts B and D; "max F at D" means max F > max F_dca at D. No
setting failed the Active rule in any pool. Kraken without 2017 is the boom check's pool (windows 12..48); the check
without 2017 and 2020 has no pool (2 windows, MISSING).

| Y | Z | X | M | Kraken 1x (decision) | Kraken 2x | Binance 1x | Kraken without 2017 |
|---|---|---|---|---|---|---|---|
| 10 | 5 | 10 | 25 | max F at B | max F at B | Q at A,B,C,D; max F at A,B | Q at A,B,C,D; max F at A,B,C,D |
| 10 | 5 | 10 | 50 | usable (G̃ −0.1736) | usable (G̃ −0.1731) | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 10 | 5 | 10 | 100 | max F at B,D | max F at B,D | Q at B,D | Q at A,B,C,D; max F at B,D |
| 10 | 5 | 25 | 25 | max F at D | max F at D | Q at A,B,D; max F at B | Q at A,B,C,D |
| 10 | 5 | 25 | 50 | usable (G̃ −0.1357) | usable (G̃ −0.1351) | Q at A,B | Q at A,B,C,D; max F at A,C |
| 10 | 5 | 25 | 100 | usable (G̃ −0.0393) | usable (G̃ −0.0388) | Q at A,B | Q at A,B,D; max F at A,B,D |
| 10 | 10 | 10 | 25 | Q at A; max F at B,D | Q at A; max F at B,D | Q at A,B,C,D; max F at A,B | Q at A,B,C,D; max F at A,B,C,D |
| 10 | 10 | 10 | 50 | Q at A; max F at B,D | Q at A; max F at B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 10 | 10 | 10 | 100 | Q at A; max F at A,B,D | Q at A; max F at A,B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 10 | 10 | 25 | 25 | max F at D | max F at D | Q at A,B,D; max F at B | Q at A,B,C,D |
| 10 | 10 | 25 | 50 | usable (G̃ −0.1451) | usable (G̃ −0.1443) | Q at A,B,C | Q at A,B,C,D; max F at A,B,C,D |
| 10 | 10 | 25 | 100 | Q at B,D; max F at B,D | Q at B,D; max F at B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 10 | 20 | 10 | 25 | Q at A,C; max F at B,D | Q at A,C; max F at B,D | Q at A,B,C,D; max F at A,B | Q at A,B,C,D; max F at A,B,C,D |
| 10 | 20 | 10 | 50 | Q at A,B,C,D; max F at B,D | Q at A,B,C,D; max F at B,D | Q at A,B,C,D; max F at A,B | Q at A,B,C,D; max F at A,B,C,D |
| 10 | 20 | 10 | 100 | Q at A,B,C,D; max F at A,B,C,D | Q at A,B,C,D; max F at A,B,C,D | Q at A,B,D; max F at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 10 | 20 | 25 | 25 | max F at D | max F at D | Q at A,B,D; max F at B | Q at A,B,C,D |
| 10 | 20 | 25 | 50 | Q at D; max F at D | Q at D; max F at D | Q at A,B | Q at A,B,C,D; max F at A,B,D |
| 10 | 20 | 25 | 100 | usable (G̃ −0.0187) | usable (G̃ −0.0193) | Q at B,D | Q at A,B,C,D; max F at B,D |
| 20 | 5 | 10 | 25 | Q at A; max F at B | Q at A; max F at B | Q at C,D; max F at A,B | Q at C,D; max F at A,B,C,D |
| 20 | 5 | 10 | 50 | Q at D; max F at B,D | Q at D; max F at B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 20 | 5 | 10 | 100 | max F at B | max F at B | Q at B,D | Q at A,B,C,D; max F at B,D |
| 20 | 5 | 25 | 25 | usable (G̃ −0.5033) | usable (G̃ −0.5009) | Q at B,C,D; max F at A,B | Q at B,C,D; max F at A,B,C,D |
| 20 | 5 | 25 | 50 | usable (G̃ −0.2778) | usable (G̃ −0.2771) | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 20 | 5 | 25 | 100 | max F at B,D | max F at B,D | Q at B,D; max F at B | Q at A,B,C,D; max F at B,D |
| 20 | 10 | 10 | 25 | Q at A,C; max F at A,B,D | Q at A,C; max F at A,B,D | Q at C,D; max F at A,B | Q at C,D; max F at A,B,C,D |
| 20 | 10 | 10 | 50 | max F at B,D | max F at B,D | Q at A,B,D; max F at B | Q at A,B,C,D; max F at A,B,D |
| 20 | 10 | 10 | 100 | Q at A,C; max F at A,B,D | Q at A,C; max F at A,B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 20 | 10 | 25 | 25 | usable (G̃ −0.5033) | usable (G̃ −0.5009) | Q at B,C,D; max F at A,B | Q at B,C,D; max F at A,B,C,D |
| 20 | 10 | 25 | 50 | Q at A,B,D; max F at B,D | Q at A,B,D; max F at B | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 20 | 10 | 25 | 100 | max F at B,D | max F at B,D | Q at B,D | Q at A,B,C,D; max F at B,D |
| 20 | 20 | 10 | 25 | Q at A,C,D; max F at A,B,D | Q at A,C,D; max F at A,B,D | Q at C,D; max F at A,B | Q at C,D; max F at A,B,C,D |
| 20 | 20 | 10 | 50 | Q at A,B,C,D; max F at A,B,C,D | Q at A,B,C,D; max F at A,B,C,D | Q at C,D; max F at B | Q at C,D; max F at A,B,C,D |
| 20 | 20 | 10 | 100 | Q at A,B,C,D; max F at A,B,C,D | Q at A,B,C,D; max F at A,B,C,D | Q at D | Q at C,D; max F at A,B,D |
| 20 | 20 | 25 | 25 | usable (G̃ −0.5033) | usable (G̃ −0.5009) | Q at B,C,D; max F at A,B | Q at B,C,D; max F at A,B,C,D |
| 20 | 20 | 25 | 50 | Q at B,D; max F at B,D | Q at B,D; max F at B,D | Q at A,B,D | Q at A,B,C,D; max F at A,B,D |
| 20 | 20 | 25 | 100 | max F at B,D | max F at B,D | Q at B,D | Q at A,B,C,D; max F at A,B,D |
| 30 | 5 | 10 | 25 | Q at A,C; max F at D | Q at A,C; max F at D | Q at C,D; max F at A | Q at C,D; max F at C,D |
| 30 | 5 | 10 | 50 | Q at B; max F at D | Q at B; max F at D | Q at D; max F at B | Q at C,D; max F at D |
| 30 | 5 | 10 | 100 | max F at D | max F at D | Q at B,D | Q at A,B,C,D; max F at B,D |
| 30 | 5 | 25 | 25 | Q at A,C; max F at D | Q at A,C; max F at D | Q at C,D; max F at A,B | Q at C,D; max F at C,D |
| 30 | 5 | 25 | 50 | max F at D | max F at D | Q at D | Q at C,D; max F at D |
| 30 | 5 | 25 | 100 | max F at D | max F at D | Q at B | Q at A,B,C,D; max F at B |
| 30 | 10 | 10 | 25 | Q at A,C,D; max F at D | Q at A,C,D; max F at D | Q at C,D | Q at C,D; max F at C,D |
| 30 | 10 | 10 | 50 | Q at A,B,D; max F at D | Q at A,B,D; max F at D | Q at C,D; max F at A | Q at C,D; max F at C,D |
| 30 | 10 | 10 | 100 | Q at A,C,D; max F at A,D | Q at A,C,D; max F at A,D | Q at A,D | Q at A,C,D; max F at A,D |
| 30 | 10 | 25 | 25 | Q at A,C; max F at D | Q at A,C; max F at D | Q at C,D; max F at A,B | Q at C,D; max F at C,D |
| 30 | 10 | 25 | 50 | Q at A; max F at D | Q at A; max F at D | Q at D; max F at B | Q at C,D; max F at D |
| 30 | 10 | 25 | 100 | usable (G̃ −0.0057) | usable (G̃ −0.0050) | Q at B,D | Q at A,B,C,D; max F at B,D |
| 30 | 20 | 10 | 25 | Q at A,B,C,D; max F at C,D | Q at A,B,C,D; max F at C,D | Q at C,D | Q at C,D; max F at C,D |
| 30 | 20 | 10 | 50 | Q at A,C,D; max F at C,D | Q at A,C,D; max F at C,D | Q at C,D | Q at C,D; max F at C,D |
| 30 | 20 | 10 | 100 | Q at A,C,D; max F at D | Q at A,C,D; max F at D | Q at D | Q at C,D; max F at D |
| 30 | 20 | 25 | 25 | Q at A,C; max F at D | Q at A,C; max F at D | Q at C,D; max F at A,B | Q at C,D; max F at C,D |
| 30 | 20 | 25 | 50 | max F at D | max F at D | Q at D; max F at A,B | Q at C,D; max F at D |
| 30 | 20 | 25 | 100 | max F at D | max F at D | Q at D | Q at A,B,C,D; max F at B,D |

## The 1x/2x cost check and the counts

**The cost check** (PLAN.md section 10, read as amendment R2.2 settles it):
- 10,584 pairs of Kraken dip runs, the same setting, start and window at 1x and at 2x costs.
- The ladder's own decisions (its triggers, line crossings and re-arms, `events_hash`) were equal in all 10,584
  pairs. They come from the index and its one-year high alone, which hold no cost. A difference would have stopped the
  run (stop rule 5).
- The orders actually sent (their closes and reasons, `orders_hash`) differed in 63 pairs (0.6%), a description:
  - 3 differ in the number of buy orders and 13 in the number of limit fixes. The other 47 have the same counts, with
    an order on another close or with another reason;
  - they spread over 25 settings, 30 windows and all four starts;
  - none is at the default.
  - A cap or a limit fix reads the wallet's weights, which doubled costs move by a hair, so a buy can be cut to nothing
    or a limit fix can fall on a neighbouring close.

**The counts** (all as section 7 requires, 0 failed):

| Pool | Dip | dca-same | lump-same | Hold | Runs |
|---|---|---|---|---|---|
| Stage 1: Kraken 1x (49 windows) | 10,584 | 10,584 | 10,584 | 196 | **31,948** |
| Stage 2: Binance 1x (41 windows) | 8,856 | 8,856 | 8,856 | 164 | 26,732 |
| Stage 2: Kraken 2x (49 windows) | 10,584 | 10,584 | 10,584 | 196 | 31,948 |
| Total | 30,024 | 30,024 | 30,024 | 556 | **90,628** (stage 2: 58,680) |

- 118,764 ladders logged (Kraken 1x 41,940; Kraken 2x 41,940; Binance 34,884); 401 of them sent no order.
- No dip run in any pool had an ordered total of 0, so the "twins equal hold" check (section 10, R2.4) never applied.
- Every window held all its calendar closes except Kraken's one pinned missing close, 2018-01-13 (729 to 731 rows a
  window).
- `runs.csv` holds the 90,628 runs, one row each, with no Sharpe, end-value or total-return column. The tracked
  `decision.json` is byte-identical to the run's.

## Deviations and readings

**Deviations from the plan: none found.** Checked against PLAN.md as amended (R1, R2, A1):
- the grid (54 settings, 4 starts, 49 Kraken and 41 Binance windows, 1x and 2x) and the counts;
- the data pins in `start.json` (snapshot `1746a21b75683e76`, bars hash `08f5ca2c…`, panel hashes `355aabe2…` (2190
  rows) and `2c1a4257…` (1963 rows));
- the Steady limits as read (cash ≥ 20%, each coin ≤ 60%, budget 35%);
- D1-D3 recomputed from the runs, with identical results;
- the outputs of section 14.

The run's own start-up re-timing projected 27.7 CPU-minutes (amendment A1 had 36.1); the run took 784 s on 2 workers.

**Readings that matter** (pinned before any run in `dipbuy.READINGS_PINNED` and `run.py`'s `INTERPRETATIONS`, both
in the config hash and the start record, and settled in PLAN.md amendment R2):
- **The one-year high's window** (TESTING.md #74, DR5; R2.1).
  - H_t uses the closes with t − 365 days < close ≤ t: 365 daily closes, close t included. A high exactly 365 days back
    does not count. That is section 5's exact rule. Section 11's test list had said the opposite.
  - On the daily grid the other reading would use 366 closes. It can move a trigger or a re-arm only where the year's
    highest close sits exactly 365 days back.
  - The audit measured its effect (AUDIT.md section 2): rerun under the other reading, the ladder's events change in 8
    of the 30,024 dip runs. D1 gives the same results in all three pools, and the without-2017 check is still NO
    DEFAULT.
- **"Ordered (before caps)"** = the amounts sent + cut by a cap + blocked by a limit fix (R2.3). Lines crossed on the
  last close are "not filled" and not ordered. This total feeds δ, G and the twins.
  - So δ counts money the limits never let in. At the default it is 1.45-1.95 times the starting cash, while the ladder
    sent 1.06-1.17 times.
  - The twins order the same total, and the limits cut them harder. At the default the ladder's own orders were cut by
    a median 27-37% (by start), dca-same's by 35-47% and lump-same's by 46-65%.
  - So the twins got less money into crypto: in the median run lump-same sent 61% and dca-same 84% of what the ladder
    sent. They ended holding more cash (median USDC left: the ladder 24-29%, dca-same 31-39%, lump-same 36-43%), and
    only 16-20% of the twins' runs ended below 25% USDC, against 39-57% of the ladder's.
  - Over a window the three were similarly invested on average: the median time-average crypto share was 68% for the
    ladder, 67% for dca-same and 68% for lump-same (the cap is 78%).
  - So T_dca and T_lump mix when the money went in with how much of it got in. The comparison does not set dip-buying
    against a half-invested wallet, but neither twin is "the same money spread out": each is the ladder's total on a
    schedule, cut at the Steady limits.
- **The cost check** reads "order closes equal at 1x and 2x" as the ladder's decisions (R2.2; above).
- **Smaller readings:**
  - the knife from the open of the last order's fill row through the re-arm close (or the last close), signed;
  - G̃ over the runs with an order (all of them here); the median δ over every run of the setting;
  - Active as 2 × active windows ≥ windows (never binding here);
  - D1 MISSING on any failed run (none failed);
  - D3 at the default only;
  - a window's year is the calendar year of its first close;
  - the boom years ranked on Kraken's BTC closes by bar day, written into `start.json` before any backtest;
  - the base B, the cap amount (a cut that leaves at most 1e-9 of the wallet sends nothing) and λ of the limit fix, as
    written in `READINGS_PINNED`.

## Known weaknesses (PLAN.md section 15, and what this run showed)

- **Not fresh data,** and no validate look. Every price of 2017-2022 had been seen through earlier studies (section 2).
- **Overlapping windows:** 49 two-year windows a month apart. One crash (2018, 2022) or one boom (2017, 2020-21)
  stands behind many windows. The D2 checks show how much the default leans on the 2017 windows.
- **The twins use the run's own total,** known only at the end, and at M = 100% that total is above the starting cash,
  so the twins are capped too. At the default the limits cut every dca-same twin, from a median of day 120, and
  lump-same harder still. They are the ladder's total on a schedule, cut at the Steady limits: yardsticks, not the
  same money spread out, and not strategies a customer could follow.
- **One wallet size** (5,000 USD), no later deposits, one lookback for the high (365 days), daily checks only.
- **The ladder never sells except by the limit fix.** At the default the limit fix sold a median 14-18 times a window.
- **f is 50% or 75% only;** other BTC/ETH splits are untested.
- **The default sits at a corner of the range** (the largest Y, X and M), and its bad-case margin is thin (start D:
  71.19% against 71.27%). It is an isolated passing point: none of its five one-step neighbours passes the bad-case
  test, and with D's margin the other way D1 would have named (10%, 20%, 25%, 100%). It is also picked in sample, on
  the same 49 windows it is described on.
- **The scouting engine, the placeholder costs and exchange candles,** not NautilusTrader and not Base prices.

## Record

- **The run:** run 0, 2026-11-24 18:08:49 to 18:21:53 UTC, on commit `e62233e` with a clean tree (`start.json` and the
  RUNLOG).
  - Config hash `086fffac12e5df13…`, snapshot `1746a21b75683e76`, 2 workers (forked), 784 s (the grid 779 s).
  - 90,628 runs (31,948 in stage 1 and 58,680 in stage 2), 0 failed; 118,764 ladders logged.
- **Before the run:**
  - PLAN.md with amendments R1 (`risk-officer`'s review) and R2 (readings settled after the build's code review);
  - the build and its review (TESTING.md #71, #72 and #74);
  - amendment A1: 36.1 CPU-minutes projected, under the 240 limit.
  - On `e62233e`: the full tier, 2646 passed with 100% branch coverage of `lab/`, in 3488 s at `-n 3`; the deep
    profile, 2628 passed in 1095 s; ruff clean; dashboard 86 passed; the tree clean before and after.
- **Alongside:** downvol-steady run 0 started at the same moment on the same commit. Both read a clean tree before
  either wrote its RUNLOG line: this study's RUNLOG did not exist at `e62233e`, and its line (18:08:49 UTC) would have
  made the tree dirty for any later check. downvol-steady's line is at 18:08:56 UTC, after its own re-timing. The two
  runs shared the machine and no hashed file.
- **Outputs:**
  - `results/buy-the-dip/run0/` (git-ignored): `start.json`, `summary.json`, `decision.json`, `runs.parquet`,
    `ladders.parquet`, `failures.parquet` (empty) and `blocks/` (139 blocks);
  - tracked: [RUNLOG.jsonl](RUNLOG.jsonl), [runs.csv](runs.csv) and [decision.json](decision.json).
- **This file:**
  - every number recomputed from `runs.parquet`, `ladders.parquet` and `decision.json` by scratch code written from
    PLAN.md sections 8-9 and R2;
  - it agrees with `decision.json` exactly: D1 in all four pools, D2's label, D3, the setting tables and the cost
    check;
  - T_dca, T_lump, T_hold, G and δ were also recomputed from the runs' end values and ordered totals, with no
    difference;
  - the first draft read run 0's outputs only and loaded no bar;
  - the revision reran the default's 196 Kraken 1x dip runs and their dca-same and lump-same twins with
    `lab/runner/dipbuy.py` (each run's end value equal to `runs.parquet`'s), for the time-average crypto share,
    dca-same's first cut and the index around the worst knife. The bars came through
    `load_panel("KRAKEN", "1d", last_close=2023-01-01 00:00 UTC)` behind a guard that refuses a request with no end or
    a later end and any returned close after the cut. Each load made two requests (BTC and ETH, 2017-01-01 to
    2023-01-01), and the panel's last close, 2023-01-01, was asserted. No Binance bar and no validate or test bar was
    requested or received;
  - the other reading of the one-year high (8 of 30,024 dip runs) is the audit's rerun, read from its scratch tables.
- **Audit: PASS** for the run and its decision ([AUDIT.md](AUDIT.md), `backtest-auditor`, 2026-11-24).
  - It reran all 90,628 runs with its own ladder, twins, book and costs, written from PLAN.md (a match to about 1e-14),
    and its own statement of D1-D3 gives the same default and label. It also ran 300 tamper-the-future cases on real
    train bars, and its guarded loader showed that no bar after 2023-01-01 00:00 UTC was requested or returned.
  - Nothing it found can change the default or its label. Its corrections to this file's claims were applied the same
    day, together with an independent fact-check's; no decided number changed.
- **Validate-window looks used for buy-the-dip: 0.** None is planned (section 12). The test window was not read.

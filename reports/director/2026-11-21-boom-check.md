# Owner decision: check every strategy with and without the boom years (2026-11-21)

**Owner's concern (chat, 2026-11-21):** crypto does a big rise and then a fall. We may never see a boom like that
again, so a strategy must not depend on it, and "we don't wanna lose all our money" on the fall.

**Owner's decision:** "Test with and without" (keep all data; a strategy must also pass with the boom removed),
not "remove it everywhere". The owner was not sure which boom is meant, so the check covers every year
mechanically instead of using dates picked with hindsight.

## The check (declared before any further real-data run)

For every study, next to its normal result:
1. **Leave one year out:** recompute the result with each calendar year of the scored period removed in turn
   (2017-2022 in train, as each study's scored span allows).
2. **Without the best years:** recompute it with the calendar year in which BTC rose most removed, and again with
   the two best such years removed (ranked by BTC's close-to-close return over each calendar year in the study's
   own data).
3. A strategy that beats its comparators only with the boom years in does not count as beating them.

Removing a year means dropping that year's returns from the scored series (and, for windowed studies, every
window that overlaps it); nothing is refitted on the shortened data.

## Where it applies

| Study | Status | How the check is run |
|---|---|---|
| `dip-timing` | finished (NO EDGE) | Extra look on stored results, labelled post hoc; it cannot change the pre-registered verdict |
| `rebalance-steady` | finished (NO EDGE) | Extra look on stored out-of-sample returns, labelled post hoc; it cannot change the verdict |
| `hold-mix-cap` | pre-registered (`1ff5ac2`), not yet run on real data | Declared here before its real-data run; reported as an addendum next to its pre-registered result; its pre-registered recommendation rule is unchanged, and the addendum reports whether the recommendation holds without each year |
| `trend-steady` | being designed, not pre-registered | Built into its pre-registration as a criterion |

All numbers stay SCOUTING (reference engine, placeholder costs).

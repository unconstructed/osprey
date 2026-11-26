# Owner answer: customers may raise the hold-this-mix trade cap (2026-11-26, in chat)

## What the owner said

In chat, after momentum-bold run 0 (NOT A CANDIDATE):

> "thats okay if theres no edge we can still make suggestions and the users can set up their own standards thats
> kinda the point anyway and we should allow the use to increase their transactions per month if they want"

The lab then asked, with AskUserQuestion:

> "The hold-this-mix tool currently allows at most 2 trades back to the mix per 30 days. How far should users be able
> to raise it? The default would stay at 2. The earlier trade-limit study already measured the fees at 1, 2, 4 and 8
> trades per 30 days and with no limit, so the app can show each choice's estimated cost."

The owner chose **"1, 2, 4, 8 or no limit (Recommended)"**. The option read: "Default 2. Every choice was measured,
so the app can show its fee cost. 'No limit' means it trades back to the mix whenever the drift band is crossed."

## What changes

- **Steady's limit of 2 rebalances in any 30 days for the hold-this-mix tool (owner, 2026-11-22) is no longer a
  ceiling for the customer.** It is now the highest cap the app sets on its own. The defaults by wallet size are
  unchanged: a cap of 2 up to 5,000 USD, and 1 above.
- **The customer may pick 1, 2, 4 or 8 rebalances in any 30 days, or no cap.** Each cap is still enforced as a
  minimum wait between trades back to the mix: 30, 15, 8 and 4 days. With no cap, the mix is checked daily.
- **The cap still never holds back a limit fix**, the trade that brings a wallet back inside Steady's limits.
- **`config/risk_levels.yaml`** keeps `hold_mix_max_rebalances_per_30d: 2` as that default ceiling. A new key in
  Steady's entry lists the choices: `hold_mix_rebalances_per_30d_choices: [1, 2, 4, 8, none]`.
  - `tests/test_portfolio.py` pins the new key.
  - The keep-risk-steady and buy-the-dip studies read Steady's limits from this file, and those limits are
    unchanged.
- **Direction recorded:** a study without an edge still informs what the app suggests, and customers set their own
  standards. That is the point of the self-directed tools.

## Still open (not decided here)

- **Tighter bands.** The rule "no band tighter than 30% off target" (owner, 2026-11-22) was set together with the
  limit of 2. The trade-limit study recommended caps of 4 or more for bands of 20% or less (8 at 10%). With caps of
  4, 8 or none now allowed, should the app offer the 20%, 15%, 10% or 5% bands? Until the owner answers, the app
  offers 30% and 50% only.
- **Fees.** More trades cost the customer more. Gas is sponsored, so it also costs us more: the study's placeholder
  gas was about 2.13 USD per customer a year at a cap of 2, against 4.33 USD with no cap. The app should show the
  fee estimate next to each choice.
- **Risk label.** Does a customer who picks no cap still see the mix labeled Steady? The label comes from the mix's
  past worst fall, which the cap barely changes. The lab's reading: yes, the label is unchanged.

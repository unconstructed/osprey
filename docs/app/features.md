# Features: What the App Does

[← Hub](README.md) · [Product](product.md) · [Technical](technical.md) · [Business](business.md)

*Updated 2026-11-19 for the lean self-custody direction. Adjustable strategy settings and "hold this mix" added 2026-11-20; the owner's answers on the tool's drift band, trading modes and loss limit recorded the same day.*

## In one sentence

An iPhone and Android app where users **own their crypto wallet and our strategies trade inside it**, automatically or with one-tap approval. Licensed ramp partners handle dollars in and out, and we never hold customer money.

## What customers can do

1. **Sign up and get a wallet in under a minute:** email or Apple, Face ID, no seed phrase
2. **Add cash** with Apple Pay, a debit card or a bank transfer; it shows as a dollar balance (USDC)
3. **Buy, sell and hold crypto** by hand, set up recurring buys ("$25 of BTC every Friday"), or pick a mix of crypto and cash that the app keeps within a drift band they choose ("hold this mix", a self-directed tool; owner, 2026-11-20; its phase is proposed)
4. **Pick a risk level and use our strategies:** choose Steady, Balanced or Bold, browse strategy cards that show the risks as well as the gains, then subscribe
5. **Build their own rules** from templates like "buy $X when BTC drops Y%", with a required stop-loss
6. **Let it run or stay in the loop:** each strategy and rule runs on **Auto-trade** (inside a limited permission) or **Approve each trade** (one tap and Face ID), and so does "hold this mix" (owner, 2026-11-20)
7. **Stay in control** with their own limits, a loss limit that auto-pauses, and a Pause everything button that also revokes auto-trading
8. **Understand every trade** through a one-line plain-English reason for why it happened
9. **Practice risk-free** in demo mode with fake money
10. **Cash out to their bank** anytime, and download their trade history for taxes

## What the app offers

| Offering | What the customer gets | Who decides each trade | How we earn | When |
|---|---|---|---|---|
| Self-custody wallet | A wallet only they control; add cash and cash out through ramp partners | Customer | — (ramp partners charge their own fees) | Phase 1 |
| Self-directed trading | Manual buy/sell, recurring buys | Customer | Possible small swap fee later | Phase 1 |
| **"Hold this mix"** | A crypto and cash mix the customer picks, kept by the app within a drift band they pick; their own choice, not one of our strategies. See [Hold this mix](#hold-this-mix) | Customer, by picking the mix and its band | Not set yet | Phase 1 (proposed) |
| **Customer rules** | Rules that run automatically within their permission, or with approval | Customer, by setting the rule | Subscription | Phase 1 |
| **Our strategies, Approve mode** | Our strategies suggest trades; customer approves or skips | Customer, by tapping approve | Subscription | Phase 1 |
| **Our strategies, Auto-trade mode** | Our strategies trade inside their permission | Our strategy, within the customer's permission and limits | Subscription | Phase 1 (owner decision; see [Business: Accepted risks](business.md#accepted-risks)) |
| Demo mode | Try any strategy with fake money | — | Free (sales tool) | Phase 1 |
| Advanced rule builder | Build more complex rules from building blocks and backtest them | Customer, by setting the rule | Paid tier | Phase 2 |
| AI copilot | Explains moves and signals; turns plain English into rules | Customer (the copilot never trades on its own) | Higher subscription tiers | Phase 2 |
| Brokerage version | Broker holds the money; bank deposits; stocks later | Same modes | Trading fees through the CaaS partner | Later track |

## Strategies by risk level

Customers choose how much risk they want; each level has its own strategies, all built in NautilusTrader. Coins are limited to tokens with deep trading on Base. Details in [Product: Strategies by risk level](product.md#strategies-by-risk-level).

| Risk level | For someone who… | Launch strategy | Add later |
|---|---|---|---|
| **Steady** | Wants smaller swings | Rebalancing: BTC, ETH and a slice of cash; trades only when the mix drifts | Trend following that moves to cash in downtrends |
| **Balanced** | Is OK with normal crypto swings | Dip buying: buys BTC or ETH after a set drop, capped | A second dip strategy with different timing |
| **Bold** | Accepts big drops for bigger upside | Momentum: holds the strongest few of the most liquid tokens on Base, rotates weekly | Mean reversion, grid trading |

- **Customers choose, we label.** The app doesn't recommend a level or strategy for a specific person; going above your level means a warning and a confirm.
- **Levels are measured.** A strategy whose live results leave its level's range is halted automatically and reviewed.
- **Guardrails per level** (allowed coins, max per coin, cash floor) are enforced by the trade router, and the coin list is also locked into each auto-trading permission.
- **Bitcoin is held as cbBTC** (backed 1:1 by bitcoin held by Coinbase), disclosed plainly.
- **No level uses** leverage, short selling, market making or arbitrage.
- **Steady's own tested strategy is still to be found.** The lab's first rebalancing study found no edge (NO EDGE; SCOUTING; see [What the first Steady study taught](#what-the-first-steady-study-taught)). Meanwhile, Steady customers can use ["hold this mix"](#hold-this-mix), a self-directed tool, not one of our strategies (owner, 2026-11-20).

## Hold this mix

*Added 2026-11-20. Owner decision (2026-11-20): offer "hold this mix" for Steady as a self-directed tool, like recurring buys, not as one of our strategies ("go with the simple tool"). The design below is the plan's sketch the owner answered, plus details that follow from rules elsewhere in these docs (Steady's coins and limits with the lab's 2-point margin, Pause everything, fees shown, no suggested or ranked mixes). Anything else beyond the sketch is marked proposed or open. The owner then answered three follow-up questions (2026-11-20, "Yes to all 3"): the customer also picks a drift band, within Steady's "a few trades a month" cap; the tool runs on Auto-trade or Approve, the customer's choice; and the customer's daily or weekly loss limit pauses it.*

The customer picks a mix of crypto and cash, and the app keeps it there, within a drift band the customer picks. Like a recurring buy, it is the customer's own choice. We make no claim it beats anything, and it is not put through the lab's checks. Its place on the Trade tab is proposed.

- **The customer picks** the crypto share (the rest stays in cash, USDC), how the crypto part is split between BTC and ETH, and a drift band. Coins are BTC (held as cbBTC), ETH and USDC only.
- **The app keeps it there, within the band** (owner, 2026-11-20). When BTC or ETH moves more than the band from its target, the app trades back to the mix. It also trades back when a Steady limit is hit, and optionally on a long reset schedule (the study's comparison reset once a year). So "keeps it there" means within the band. Without a band, a mix far from the limits could drift a long way: in the study, the comparison that traded only at a Steady limit (bought fresh each year; mixes of 34-55% crypto) hit a limit once in four years with each search, both times in 2021 (SCOUTING; RISK.md section 1). Close to a limit it trades often, even with a wide band ([open questions](#open-questions-that-change-the-feature-set)). There is no reset-only option, because it would break the Steady limits between resets.
- **A few trades a month.** Steady's guardrail "a few trades a month" caps the band (owner, 2026-11-20), as it caps the drift band and check frequency of our Steady strategies ([Steady settings](#steady-settings)). A narrow band in a volatile market would trade far more often. The customer sets the cap's number, and the app recommends one based on the lab's data and simulations (owner, 2026-11-20; the lab's simulation is in progress, on 2017-2022 data only). The cap counts rebalances: one trip back to the mix counts once, however many coins it swaps (fees are shown per swap). It is enforced as a minimum wait: at most N rebalances a month means at least 30/N days (rounded up) between them, and the app checks the mix once a day at a fixed time. Every rebalance counts, resets included. A Steady limit hit (cash under 20% or one coin over 60%) is the one exception: it is fixed at the next daily check even inside the wait, and it still counts and restarts the wait (decided by the lab; owner, 2026-11-21: "you decide"). The wait can leave the mix past its band for a while before the next trade back. Whether Steady keeps an upper limit above the customer's number is open ([open questions](#open-questions-that-change-the-feature-set)).
- **Auto-trade or Approve, the customer's choice** (owner, 2026-11-20). Like a customer rule, it runs on Auto-trade (inside the customer's auto-trading permission) or Approve each trade. The owner's acceptance of the auto-trading risks covers it ([Business: Accepted risks](business.md#accepted-risks)). On Approve, the mix is only kept there if the customer approves each trade back to it; an expired trade is never run late.
- **Pausing.** Pause everything stops it, as it stops all trading. The customer's daily or weekly loss limit pauses it too, as it pauses their strategies and their own rules (owner, 2026-11-20; rules 2026-11-21). A pause stops trading; it doesn't sell what the wallet holds, so the loss limit is not a cap on losses ([Adjustable strategy settings](#adjustable-strategy-settings)). While the tool is paused, nothing trades back to the mix, so it can drift past its band and Steady's limits.
- **Labeled as the customer's own.** The app says plainly that this is the customer's mix, not one of our strategies, with no claim it beats anything. It doesn't suggest a mix or rank mixes by past results. *Proposed, beyond the owner's words:* it shows no backtested return, only the worst fall.
- **The worst fall is shown, next to the crypto share.** How far the chosen mix would have fallen at worst in a backtest on past prices, labeled hypothetical and naming the years it covers. In the study the crypto share moved the worst fall the most, and how often the mix was reset also mattered ([below](#what-the-first-steady-study-taught)), so the number sits right next to the crypto share. *Proposed:* the controls move in steps, so every mix, drift band and reset schedule the app offers has been backtested.
- **Fees are shown.** Each trade back to the mix pays swap fees and price slippage, shown with the trade. A narrower band trades more often, so it pays them more often. Network fees are sponsored. The backtested worst fall includes all of these costs.
- **Steady's limits hold.** The mix keeps at least 20% cash and at most 60% in any one coin, with the lab's 2-point margin, and the controls stop there. A limit hit triggers a trade back to the mix, even if the coin is still inside its band. The open Steady-limits questions below (tighten them? per coin or all coins together? does 60% apply to cash?) also set how much crypto the tool allows. Whether Steady's drawdown budget also caps it is open. While the tool is paused, or on Approve until the customer approves a trade back (a skipped or expired one never runs), the mix can sit past a limit (see Pausing, above). Whether the trade cap can also hold back a trade after a limit hit is open (below).
- **No required stop-loss.** Like recurring buys, the tool needs no stop-loss. So "like a customer rule", here and in [Technical](technical.md#strategy-settings), is about how it runs (modes, per-customer checks, versioned record), not the rule checks (customer rules need a stop-loss). *The stop-loss point is proposed; not in the owner's words.*
- **Not a strategy setting.** It has no approved range, no model account and no live record of ours. A customer's results come from their own on-chain trades, as always. See [Technical: Strategy settings](technical.md#strategy-settings).

## Adjustable strategy settings

*Added 2026-11-20. The owner, on the Steady settings: "All of this should be adjustable in the final application."*

Customers can change the settings of our strategies. Every setting has a **default** and an **allowed range**. This section covers our strategies only. Self-directed tools, like recurring buys and ["hold this mix"](#hold-this-mix), are the customer's own choices and have no approved range.

- **The range is tested by the lab and approved by the owner.** The owner approves the whole range a customer can pick, not one tuned number, and only after the [Strategy Lab](../../AGENTS.md#validation-gates)'s checks pass at every point of it (every combination of settings), not just the default. *(In AGENTS.md "Validation gates" and "Ready for production" since 2026-11-20, owner: "yes to 1"; see [reports/director/2026-11-20-adjustable-settings.md](../../reports/director/2026-11-20-adjustable-settings.md).)*
- **Settings move in steps.** Every combination of settings a customer can pick was backtested, so the app never shows a number for settings nobody tested.
- **Outside the range, it is no longer our strategy.** The controls stop at the edge of the approved range. *Proposed (director report decision 6, open):* a customer who wants to go further can copy the strategy into their own rule ([advanced rule builder](#strategies-and-rules), Phase 2; for Steady this needs a rebalancing building block, which the builder doesn't list yet). It is then labeled as their own rule, not tested by us, and any backtest of it is labeled hypothetical. It follows the same checks as every [customer rule](technical.md#customer-rules-and-advanced-mode), including the required stop-loss.
- **The risk level caps the range.** No setting can take a strategy past its level's limits. Going past them means picking a higher level (with the usual warning and confirm) or building their own rule.
- **A customer's own loss limit can only be tighter.** They can set it below the level's drawdown budget (the worst fall the level allows), never above it. A loss limit pauses the strategy. It does not sell what the wallet holds, so the app never presents it as a cap on losses: the first Steady study's rule, holding about 45% crypto, lost 15.4% in one day, 12 March 2020 (SCOUTING, [RISK.md](../../research/rebalance-steady/RISK.md)). A stop-loss that is part of a strategy, like Balanced's, is a setting with an approved range like any other.
- **The app shows the worst fall for the chosen settings.** Next to the controls: how far that exact combination of settings fell at worst in the lab's backtest, and how far it fell in the worst 1 of 20 simulated histories. Both are labeled hypothetical, name the years the backtest covers, and are shown next to the level's budget. For the default settings the backtest is at least partly in-sample: the search that chose the default used some or all of the same years, so the number flatters it, and the app says so.
- **No "best settings".** The app doesn't rank settings by backtested return or suggest settings for a specific person. Picking the setting with the best past result is the kind of luck the lab's checks exist to catch.
- **The live record runs the defaults.** The strategy card's live record comes from the model account on the default settings. Before production, AGENTS.md also requires at least 4 weeks on a second paper model account at the riskiest combination in the range (the owner can still drop it; director report decision 2). Whether that account keeps running after that, or shows on the card, is not decided. A customer's own results come from their own on-chain trades, as today.
- **Until a range is approved, the default is the only setting.** A strategy can launch with fixed settings; the controls appear once the owner approves a range that passed the lab's checks.

### Steady settings

These are the settings of a Steady rebalancing strategy of ours, once one passes the lab's checks. The first one did not ([below](#what-the-first-steady-study-taught)). ["Hold this mix"](#hold-this-mix) shares the first three controls (crypto share, BTC/ETH split and drift band), but it is the customer's own tool, with no approved range.

| Setting | What it changes | Steady limit that caps it |
|---|---|---|
| Crypto share | How much is in BTC and ETH; the rest is cash (USDC) | At least 20% cash |
| BTC/ETH split | How the crypto part is split between BTC and ETH | At most 60% in any one coin |
| Drift band | How far BTC or ETH may move from its target before the app trades back to it | None in the lab's limits. Steady's guardrail "a few trades a month" ([Product](product.md#strategies-by-risk-level)) caps it (owner, 2026-11-20; see below) |
| Check frequency | How often the mix is checked, from daily to every few months | None in the lab's limits. The same "a few trades a month" guardrail caps it (owner, 2026-11-20; see below) |
| Loss limit | Pause the strategy if it falls this far from its high point | Tighter than Steady's drawdown budget (not set yet) |

- The limits come from the lab's `config/risk_levels.yaml`: at least 20% cash, at most 60% per coin, and a drawdown budget that is still TBD. Until the owner approves a budget, no Steady setting can be approved: the lab counts a missing budget as a failed check.
- Every setting also stays inside its approved range, which can be narrower than the limits.
- Targets stay a little inside the limits (the lab used 2 points). On a live wallet each fee comes out of its own swap, so a target exactly on a limit would end just past it and trade again the next day.
- Today's limits alone allow up to 80% crypto (78% with the 2-point margin), on the lab's per-coin reading of "at most 60%". If 60% applied to all coins together, the cap would be 60% (58% with the margin). In the first study's two final searches (in-sample, over all of 2017-2022; in-sample means measured on the same data the search used to choose, so it flatters), the few mixes with 70-77% crypto (3 trials) fell about two thirds at worst, in the 2018 crash (SCOUTING; RISK.md section 2, dated from the logged trial returns). The lab's risk officer has asked the owner whether to tighten the Steady limits before the budget is set. That decision sets how much crypto a Steady customer can pick.

### What the first Steady study taught

> **SCOUTING.** From the lab's simple in-house simulator (the reference engine), not NautilusTrader, with placeholder costs. Out of sample, 2019-2022, unless marked in-sample. Nothing was approved; the verdict was NO EDGE. Sources: [RESULTS.md](../../research/rebalance-steady/RESULTS.md) and [RISK.md](../../research/rebalance-steady/RISK.md).

- **The mix sets risk and return.** The searched rule made +174.0% with a worst fall of −41.8% (Sharpe 0.938; Sharpe is return per unit of ups and downs, and higher is better). Holding only BTC made +318.5% and fell −77.4% (Sharpe 0.864).
- **The rebalancing timing added nothing.** The same mix bought at the start of each year and left alone did as well on Sharpe (0.948, +246.7%), though its worst fall was deeper (−46.4% against −41.8%). About 1 random rebalancing schedule in 5, with the same number of rebalances, did as well or better on Sharpe. Rebalancing only when a Steady limit was hit also did as well on Sharpe (0.959), again with a deeper worst fall (−43.2%).
  - The rule rebalanced only 3 times in four years, so the test had little power. It found no edge from timing; that is not proof that timing never helps.
  - The yearly-reset and random comparisons did not apply the Steady limits.
- **Never resetting was worse.** The same mixes held for all four years with no reset fell −71% to −75%. This comparison also ran without the Steady limits, and it is a description, not a test.
- **The crypto share sets the worst fall.** In one of the study's two final searches, over 2017-2022, in-sample, with the 2018 and 2022 crashes:
  - mixes with 20-30% crypto fell a median −29% at worst; in each mix's worst 1 of 20 simulated histories, the median fall was −38%;
  - mixes with 70-77% crypto (only 2 in that search) fell a median −69%, and a median −82% in the worst 1 of 20;
  - the median Sharpe barely moved: 1.52 against 1.36;
  - even the search's 20% crypto, 80% cash mix fell −28.9%.

**What this means for the app.** The rule found no edge, so Steady's own tested strategy is still to be found. "Hold this mix" is offered meanwhile as a self-directed tool, not as one of our strategies (owner, 2026-11-20; see [Hold this mix](#hold-this-mix)). It claims no edge, so it is not put through the lab's checks, and the checks are unchanged. The study still shapes how the tool is shown:
- **The crypto share is the main risk control,** so the worst-fall number sits right next to it.
- **A held mix can still fall far.** The study's comparisons that held a mix with little or no rebalancing were baselines, not tested strategies. The yearly-reset one, which ignored the Steady limits, fell −46.4% at worst with one search and −44.1% with the other. The one that traded back only when a Steady limit was hit fell −43.2% and −36.7%. It ran one year at a time, as the rule did: each year it was bought fresh at that year's mix (34-55% crypto) before the year began, at no cost in these numbers. So it is closest to the tool with a yearly reset. A fixed mix held four years with only the limits was not run. The same mixes held four years with no reset, also without the Steady limits, fell −71% to −75% (both searches). All SCOUTING.
- **Today's limits alone don't give smaller swings.** RISK.md section 2 says they do not give the "smaller swings" [Product](product.md#strategies-by-risk-level) promises Steady customers, unless the owner tightens them (RISK.md section 3, point 3). The worst fall of a customer's mix depends mostly on its crypto share, and also on how often it is reset.
- **These are scouting numbers.** The worst fall the app shows will come from Nautilus backtests with all costs included. Still pending: Nautilus results with measured costs.

## Feature catalog

**Build first:** auto-trading with a clear, limited permission, demo mode, honest strategy cards, and "why did this trade happen."

Priority key: **Must** = must-have · **Standout** = what sets us apart · **Later** = nice-to-have. Numbers match the ranked list in [Product: Features](product.md#features).

### Account and wallet

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Onboarding | Sign up with email or Apple; wallet created automatically; Face ID passkey, no seed phrase | Sign-up flow | 1 | Must #1 |
| Wallet recovery | Get back into the wallet after a lost phone, through the wallet provider's recovery | Account | 1 | Must #6 |
| Sponsored network fees | Users never need ETH to pay for transactions | App-wide | 1 | — |
| Wallet export | Users can take their wallet to another app | Account | 1 | — |
| Connect an existing wallet | Use MetaMask, Coinbase Wallet and others | Account | 2 | — |

### Money in and out

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Add cash | Apple Pay, debit card or bank through Coinbase Onramp or MoonPay; arrives as USDC | Trade, Home | 1 | Must #3 |
| Cash out | Sell to USDC, then a ramp partner deposits dollars to the user's bank; always a Face ID-confirmed send | Trade | 1 | Must #3 |
| Cash balance | USDC shown as a dollar balance | Home | 1 | — |
| Receive and send crypto | Face ID for every send; address book; warning on new addresses | Account | 1 | Must #6 |

### Portfolio and trading

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Portfolio view | Coins, cash, profit/loss, every trade with a blockchain link | Home, Activity | 1 | Must #2 |
| Manual buy/sell | Swap between cash and allowed coins | Trade | 1 | — |
| Recurring buys (DCA) | "Buy $25 of BTC every Friday" | Trade | 1 | Must #4 |
| Hold this mix | The customer picks the crypto share, the BTC/ETH split and a drift band (capped by Steady's "a few trades a month"; the customer sets the number and the app recommends one); the app trades back to the mix when BTC or ETH leaves the band or a Steady limit is hit, and optionally on a long reset schedule, on Auto-trade or Approve. Their loss limit and Pause everything pause it. Labeled as the customer's own choice, not our strategy, with no claim it beats anything; the backtested worst fall for the mix (labeled hypothetical) and the fees are shown. See [Hold this mix](#hold-this-mix) | Trade (proposed) | 1 (proposed) | — |

### Strategies and rules

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Risk levels | Customer picks Steady, Balanced or Bold; strategies grouped and labeled by level; warning and confirm to go above it | Strategies, Account | 1 | — |
| Strategy library | One starter strategy per risk level (rebalancing, dip buying, momentum) | Strategies | 1 | — |
| Honest strategy cards | Plain-English description, risk level, worst losing streak, biggest drop; backtest and live results shown separately and clearly labeled | Strategies | 1 | Standout #10 ⭐ |
| Strategy settings | Change a strategy's settings within the approved range, tested by the lab and approved by the owner (for Steady: crypto share, BTC/ETH split, drift band, check frequency, loss limit); the backtested worst fall for the chosen settings is shown, labeled hypothetical. See [Adjustable strategy settings](#adjustable-strategy-settings) | Strategies | 1, as ranges are approved | — |
| Rule builder, simple mode | Templates like "buy $X when BTC drops Y%"; stop-loss required | Strategies | 1 | — |
| Trading mode per strategy and rule | Auto-trade or Approve each trade; switch anytime. "Hold this mix" has the same two modes ([Hold this mix](#hold-this-mix)) | Strategies | 1 | — |
| One-tap signal approval | Push → approve or skip → Face ID → the user's wallet signs; signals expire and are never executed late | Notification, Home | 1 | Standout #12 |
| Advanced rule builder (paid tier) | More building blocks: moving averages, RSI, price change, AND/OR conditions, several coins, take-profit and stop-loss. Backtest button with all costs included and results labeled hypothetical | Strategies | 2 | — |
| AI rule builder | Type "buy ETH if it drops 10% this week, but never more than $200" and get a rule to review and confirm | Strategies | 2 | Standout #13 |
| More strategies | A second strategy at each risk level | Strategies | 2 | — |
| Strategy leaderboard | Live results only, never backtests | Strategies | 2 | Later #15 |

### Auto-trading

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Auto-trading permission | Plain-English screen; Face ID grant; swaps only, allowed coins only, amount caps, money can never leave the wallet; expires in 90 days | Strategies, Account | 1 | Standout #8 ⭐ |
| Permission manager | See every active permission, its limits and expiry; revoke with one tap | Account | 1 | — |
| Auto-trade notifications | "Bought $100 of BTC — BTC dropped 6% today" after each auto-trade | Notification | 1 | — |

### Customer controls

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Personal limits | Max amount per trade and per day, also enforced inside the auto-trading permission | Account | 1 | Must #5 |
| Loss limit auto-pause | Daily or weekly loss limit that pauses the customer's strategies, their own rules and "hold this mix" (rules: owner, 2026-11-21); each strategy can also have its own loss limit, tighter than its level's drawdown budget. A pause stops trading; it doesn't sell | Account | 1 | Must #5 |
| Pause everything | One big button that stops all trading and revokes auto-trading | Account | 1 | Must #5 |

### Trust and transparency

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| "Why did this trade happen?" | One plain-English line on every trade; no black box | Activity | 1 | Standout #11 ⭐ |
| Demo mode | Paper trading with fake money; best sales tool | Account (toggle) | 1 | Standout #9 ⭐ |
| Weekly recap | Trades made, how they did, and why | Notification / Home | 2 | Later #14 |
| AI copilot explanations | Explains market moves and why a signal fired; never trades on its own | App-wide | 2 | — |
| Education hub | Short lessons tied to each strategy | Strategies | 2 | — |

### Notifications

| Feature | What it does | Phase |
|---|---|---|
| Push alerts | Trade executed, signal waiting for approval, limit hit, strategy paused, cash in/out status, permission expiring | 1 |
| In-app inbox and email statements | Backup for missed pushes; pending approvals always also show on Home | 1 |

### Security

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Face ID everywhere it matters | Unlock, sends, approvals and permission changes | App-wide | 1 | Must #6 |
| Keys never touch our servers | Private keys stay in the wallet provider's secure hardware | — | 1 | — |
| Privacy and device checks | Balances blurred in the app switcher; jailbreak/root detection; remote session revoke | App-wide | 1 | — |

### Tax

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Tax export | One button to download trade history with cost basis, built from on-chain records; no broker sends tax forms, so this matters from day one | Account | 1 | Must #7 |
| Richer tax reports | Direct integrations with tax software | Account | 2 | — |

### Growth

| Feature | What it does | Phase |
|---|---|---|
| Referral program | Customers invite others | 2 |
| Widgets and watch apps | Home-screen widgets; Apple Watch / Wear OS glanceable balances | 2 |
| More chains | For example Solana, for a wider token list | 2 |

### Later tracks

| Feature | What it does |
|---|---|
| Brokerage version | A CaaS partner (Alpaca first) holds the money; bank deposits; stocks later |
| Performance fees | Earn a share of gains on strategies |
| Social / copy trading | Follow other traders' moves (Later #16) |

## Screen map

| Tab | What's on it |
|---|---|
| **Home** | Total balance (coins and cash), today's change, active strategies with their mode, anything waiting for approval |
| **Strategies** | Strategies grouped by risk level, honest strategy cards, subscribe with Auto-trade or Approve, strategy settings within the approved range, rule builder |
| **Trade** | Buy/sell, recurring buys, hold this mix (proposed), Add cash, Cash out |
| **Activity** | Every trade with its "why" reason and blockchain link, cash in and out |
| **Account** | Wallet (address, receive, send, recovery), auto-trading permissions, limits, Pause everything, risk level, security, tax export, demo mode toggle |

## Key flows

**Add cash**
1. Trade → Add cash → choose amount
2. Ramp partner's flow: Apple Pay, debit card or bank; ID check if required
3. USDC arrives in the user's wallet and shows as cash

**A strategy trade on Auto-trade**
1. Nautilus fires a signal ("buy BTC")
2. The trade router sizes the user's trade from their allocation, limits and on-chain balance
3. It builds the swap with price protection and executes it inside the user's permission; the wallet provider checks every limit before signing
4. Push after the fact: "Bought $100 of BTC — BTC dropped 6% today"

**A strategy trade on Approve**
1. Push shows the trade in plain English
2. Tap → approval screen → Face ID → the user's wallet signs
3. Expired signals are dropped, never run late

**Change a strategy's settings**
1. Strategies → the strategy → Settings
2. Each control moves in the steps the lab tested and stops at the approved range; the backtested worst fall for the new settings updates next to the level's budget, labeled hypothetical
3. Save; the change is a new version. If the new mix needs trades, they run in the strategy's mode (Auto-trade or Approve) like any other trade
4. To go past the range: copy the strategy into your own rule (Phase 2; proposed, director report decision 6, open)

**Hold a mix of your own** (screens proposed)
1. Trade → Hold this mix
2. Pick the crypto share, the BTC/ETH split and a drift band, and optionally a long reset schedule. Each control moves in steps (proposed); how narrow the band can go is capped by Steady's "a few trades a month": the customer sets that number, and the app shows its recommended one. The backtested worst fall for that mix updates next to the crypto share, labeled hypothetical
3. The screen says plainly: this is your own mix, not one of our strategies, and we don't claim it beats anything. The fees a trade back to the mix pays are shown
4. Choose Auto-trade or Approve each trade, and save. The trades that set up the mix, and every later trade back to it, run in that mode

**Cash out**
1. Trade → Cash out → choose amount
2. Coins are sold to USDC if needed
3. The user confirms the send to the ramp partner with Face ID; dollars arrive in their bank by ACH

## What the app does not do

- **Hold customer money.** Users own their wallets; we never have a key that can send their money out.
- **Trade outside the permission.** Auto-trades are limited to swaps of allowed coins within the user's caps, enforced by the wallet provider.
- **Offer leverage, short selling, market making or arbitrage** at any risk level. Bold means more coins and more trades, not borrowed money.
- **Recommend a strategy for a specific person.** Customers choose their own risk level; we label.
- **Run customer-written code.** Customer strategies are rules built from our building blocks and stored as data. A developer API for customers' own bots is possible much later as a separate product.
- **Pass off backtests as real results.** Backtests are labeled hypothetical; the leaderboard is live-only.
- **Run our strategies on untested settings.** A strategy's settings stay inside the approved range (tested by the lab, approved by the owner). Going further would make it the customer's own rule (proposed; director report decision 6, open).
- **Show engine names.** Customers see strategies, not the software behind them.

## Behind the scenes

Every feature runs on the same backend pieces (details in [Technical](technical.md#architecture)):

- **Strategy engine** (NautilusTrader): one instance per strategy, not per customer; trades only its own paper model account
- **Rule engine**: one shared service runs every customer's rules, which are stored as small versioned records (data, not code); see [Technical: Customer rules](technical.md#customer-rules-and-advanced-mode)
- **Trade router**: turns one signal into a swap for each user, sizes it to their limits and balance, adds price protection, and executes it in Auto mode or sends it for approval
- **Auto-trading permission**: a limited signer on each user's wallet, enforced by the wallet provider; see [Technical: Auto-trading permission](technical.md#auto-trading-permission)
- **Risk engine**: four layers (platform kill switch, strategy auto-halt, customer limits, wallet permission); any error rejects the trade
- **Chain watcher and reconciliation**: confirms every trade on Base and compares our records with the chain; pauses auto-trading and alerts on any mismatch
- **Ledger and audit log**: every signal, approval, permission change, trade and cash movement, append-only

## Open questions that change the feature set

- [ ] Apple review: will in-app swaps be treated as exchange features?
- [ ] Which ramp partner for buying and which for cashing out (Coinbase Offramp needs a Coinbase account; MoonPay selling isn't available in Louisiana, Texas or New York)
- [ ] Which policy conditions Privy enforces natively for the auto-trading permission
- [ ] Final coin list per risk level on Base
- [ ] Steady limits: tighten them before the drawdown budget is set? That decision sets how much crypto a Steady customer can pick
- [ ] Is Steady's "at most 60%" per coin (the lab's reading) or for all coins together? Not yet confirmed by the owner
- [ ] Does Steady's "at most 60%" also apply to cash (USDC)? The lab reads it as not (RISK.md reading 4). If it did, a Steady customer would need at least 40% crypto, and the mostly-cash mixes the first study reached (70-80% cash) would be ruled out
- [ ] For customers off a strategy's defaults: decide their trade timing per customer, outside Nautilus, or keep Nautilus as the only decision-maker (fixed settings at launch, or one Nautilus node per approved combination)? See [Technical: Strategy settings](technical.md#strategy-settings)
- [x] "Hold this mix" for Steady: one of our strategies (it must pass the lab's checks) or a self-directed tool like recurring buys? **Owner (2026-11-20): a self-directed tool ("go with the simple tool").** The customer picks the mix and the app keeps it there. We make no claim it beats anything, and the app shows how far the mix would have fallen in the past, labeled hypothetical. It is not one of our strategies, so it is not put through the lab's checks, and the checks are unchanged. See [Hold this mix](#hold-this-mix)
- [x] "Hold this mix": the owner's words are "the app keeps it there", but with trades only at a Steady limit or a long reset, most mixes drift far between trades (above). Should the customer also pick a drift band? **Owner (2026-11-20): yes.** The customer picks a drift band, within Steady's "a few trades a month" cap, and the app trades back to the mix when BTC or ETH leaves it. See [Hold this mix](#hold-this-mix)
- [x] "Hold this mix": how is the trade cap enforced, and does it count trades or rebalances? **Decided by the lab; owner, 2026-11-21: "you decide":** it counts rebalances and is enforced as a minimum wait of 30/N days (rounded up) between them, checked once a day; resets count; a Steady limit hit is fixed at the next daily check even inside the wait and still counts. See [Hold this mix](#hold-this-mix)
- [ ] "Hold this mix": what number does the app recommend for the trade cap? The lab's simulation is in progress (2017-2022 data only)
- [x] "Hold this mix": who sets that cap? The tool has no approved range from the lab, so the lab's pre-registration doesn't set it, as it does for our strategies. **Owner (2026-11-20): the customer sets the number; the app recommends one based on the lab's data and simulations** (the lab's simulation is in progress, on 2017-2022 data only)
- [ ] "Hold this mix": does Steady keep an upper limit above the number the customer sets, or is the customer's number the only cap?
- [x] "Hold this mix": does Steady's "a few trades a month" also cap the tool's own trades (trades back to the mix after a limit hit, and resets), not only its drift band? **Decided by the lab; owner, 2026-11-21: "you decide":** resets count and wait like any rebalance; a limit hit is fixed at the next daily check even inside the wait, and counts. The simulation measures how often limit hits break through the cap. With a coin's target 2 points under the 60% cap and the rest of the wallet flat, the tool sells each time that coin gains about 8.6% since the last trade (simple arithmetic, not a lab result)
- [ ] "Hold this mix": does Steady's drawdown budget (not set yet) also cap the tool's crypto share? Or can a mix whose backtested worst fall is past the budget still be offered under the Steady label? The [hub](README.md#open-questions) says the budget helps set how much crypto a Steady customer can pick, and [Product](product.md#how-the-levels-work) gives each level a measured range for its worst drop
- [ ] "Hold this mix": which years its worst-fall backtests cover. Covering 2023 onward would spend the lab's unseen validate and test data for any later Steady rebalancing strategy ([Technical: Strategy settings](technical.md#strategy-settings))
- [ ] "Hold this mix": who can use it? It is described as a Steady option, but it sits on the Trade tab with recurring buys. Can a Balanced or Bold customer use it, and under which level's guardrails? Bold's coin list is still to be vetted and may not include BTC and ETH
- [x] "Hold this mix": does the customer's daily or weekly loss limit, which pauses the customer's strategies, also pause the tool? Pause everything already stops it. **Owner (2026-11-20): yes.** The loss limit pauses the tool as it pauses the customer's strategies; a pause stops trading and sells nothing
- [x] "Hold this mix" on Auto-trade: the owner's acceptance of the auto-trading risks (2026-11-19) names only our strategies and customer rules. Can the tool trade automatically too, not only after the customer approves each trade? **Owner (2026-11-20): yes.** It runs on Auto-trade or Approve each trade, the customer's choice, and the owner's acceptance of the auto-trading risks now covers it. See [Business: Accepted risks](business.md#accepted-risks)
- [ ] Steady at launch: if no Steady strategy of ours passes the lab's checks by launch, does Steady launch with "hold this mix" only? The strategy library plans one starter strategy per risk level
- [x] Does Steady's guardrail "a few trades a month" ([Product](product.md#strategies-by-risk-level)) cap the drift band and check frequency? **Owner (2026-11-20): yes, unless rebalancing that often is shown to pay; if it is not profitable, cap it.** In the first study it did not pay: across the 400 trials of the two final searches (in-sample, 2017-2022, reference engine, placeholder costs; SCOUTING), the median Sharpe was 1.50 for settings that rebalanced less than once every 4 months (352 trials), 1.32 at 1-3 rebalances a month (6 trials), 1.24 at 3-6 a month (6) and 1.25 at 6 or more a month (3), counting rebalances after the first buy. The same held inside one mix: with 20-35% crypto, 1.51 against 1.25. Few trials sat at the busy end, because the search did not favour it, so this is a description, not a test. So the guardrail caps the drift band and check frequency, and `risk-officer` sets those ranges inside it. It counts rebalances, not swaps (decided by the lab; owner, 2026-11-21: "you decide"). The lab's limits have no such cap: the first study searched check frequencies from daily and bands from 2% of the coin share, and the busiest in-sample trials, checking daily with a band of about 2% of the coin share, rebalanced on 697 and 757 of about 2,190 days, roughly 10 times a month; each rebalance can be up to two swaps (the two final searches, 2017-2022; SCOUTING)
- [ ] Customer limits beyond the mix (for example a separate "keep at least 40% cash"): in Steady the limits also trigger trades, so such a limit is a strategy setting and needs its own approved range
- [ ] Subscription price, given gas sponsorship and provider costs

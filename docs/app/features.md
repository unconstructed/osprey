# Features: What the App Does

[← Hub](README.md) · [Product](product.md) · [Technical](technical.md) · [Business](business.md)

*Updated 2026-11-19 for the lean self-custody direction. Adjustable strategy settings added 2026-11-20.*

## In one sentence

An iPhone and Android app where users **own their crypto wallet and our strategies trade inside it**, automatically or with one-tap approval. Licensed ramp partners handle dollars in and out, and we never hold customer money.

## What customers can do

1. **Sign up and get a wallet in under a minute:** email or Apple, Face ID, no seed phrase
2. **Add cash** with Apple Pay, a debit card or a bank transfer; it shows as a dollar balance (USDC)
3. **Buy, sell and hold crypto** by hand, or set up recurring buys ("$25 of BTC every Friday")
4. **Pick a risk level and use our strategies:** choose Steady, Balanced or Bold, browse strategy cards that show the risks as well as the gains, then subscribe
5. **Build their own rules** from templates like "buy $X when BTC drops Y%", with a required stop-loss
6. **Let it run or stay in the loop:** each strategy or rule runs on **Auto-trade** (inside a limited permission) or **Approve each trade** (one tap and Face ID)
7. **Stay in control** with their own limits, a loss limit that auto-pauses, and a Pause everything button that also revokes auto-trading
8. **Understand every trade** through a one-line plain-English reason for why it happened
9. **Practice risk-free** in demo mode with fake money
10. **Cash out to their bank** anytime, and download their trade history for taxes

## What the app offers

| Offering | What the customer gets | Who decides each trade | How we earn | When |
|---|---|---|---|---|
| Self-custody wallet | A wallet only they control; add cash and cash out through ramp partners | Customer | — (ramp partners charge their own fees) | Phase 1 |
| Self-directed trading | Manual buy/sell, recurring buys | Customer | Possible small swap fee later | Phase 1 |
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

## Adjustable strategy settings

*Added 2026-11-20. The owner, on the Steady settings: "All of this should be adjustable in the final application."*

Customers can change the settings of our strategies. Every setting has a **default** and an **allowed range**.

- **The range is tested by the lab and approved by the owner.** The owner approves the whole range a customer can pick, not one tuned number, and only after the [Strategy Lab](../../AGENTS.md#validation-gates)'s checks pass at every point of it (every combination of settings), not just the default. *(The lab-side change is proposed to the owner in [reports/director/2026-11-20-adjustable-settings.md](../../reports/director/2026-11-20-adjustable-settings.md). It is not in force: today AGENTS.md exports one pinned set of parameters.)*
- **Settings move in steps.** Every combination of settings a customer can pick was backtested, so the app never shows a number for settings nobody tested.
- **Outside the range, it is no longer our strategy.** The controls stop at the edge of the approved range. A customer who wants to go further can copy the strategy into their own rule ([advanced rule builder](#strategies-and-rules), Phase 2; for Steady this needs a rebalancing building block, which the builder doesn't list yet). It is then labeled as their own rule, not tested by us, and any backtest of it is labeled hypothetical. It follows the same checks as every [customer rule](technical.md#customer-rules-and-advanced-mode), including the required stop-loss.
- **The risk level caps the range.** No setting can take a strategy past its level's limits. Going past them means picking a higher level (with the usual warning and confirm) or building their own rule.
- **A customer's own loss limit can only be tighter.** They can set it below the level's drawdown budget (the worst fall the level allows), never above it. A loss limit pauses the strategy. It does not sell what the wallet holds, so the app never presents it as a cap on losses: the first Steady study's rule, holding about 45% crypto, lost 15.4% in one day, 12 March 2020 (SCOUTING, [RISK.md](../../research/rebalance-steady/RISK.md)). A stop-loss that is part of a strategy, like Balanced's, is a setting with an approved range like any other.
- **The app shows the worst fall for the chosen settings.** Next to the controls: how far that exact combination of settings fell at worst in the lab's backtest, and how far it fell in the worst 1 of 20 simulated histories. Both are labeled hypothetical, name the years the backtest covers, and are shown next to the level's budget. For the default settings the backtest is at least partly in-sample: the search that chose the default used some or all of the same years, so the number flatters it, and the app says so.
- **No "best settings".** The app doesn't rank settings by backtested return or suggest settings for a specific person. Picking the setting with the best past result is the kind of luck the lab's checks exist to catch.
- **The model account runs the defaults.** The strategy card's live record comes from the default settings. A customer's own results come from their own on-chain trades, as today.
- **Until a range is approved, the default is the only setting.** A strategy can launch with fixed settings; the controls appear once the owner approves a range that passed the lab's checks.

### Steady settings

| Setting | What it changes | Steady limit that caps it |
|---|---|---|
| Crypto share | How much is in BTC and ETH; the rest is cash (USDC) | At least 20% cash |
| BTC/ETH split | How the crypto part is split between BTC and ETH | At most 60% in any one coin |
| Drift band | How far BTC or ETH may move from its target before the app trades back to it | None in the lab's limits. Steady's guardrail "a few trades a month" ([Product](product.md#strategies-by-risk-level)) may cap it; open question below |
| Check frequency | How often the mix is checked, from daily to every few months | None in the lab's limits. The same "a few trades a month" guardrail may cap it; open question below |
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

**What this means for the app.** A simple "hold this mix" Steady option could be considered. The customer picks the crypto share and the BTC/ETH split. The app trades when a Steady limit is hit, and optionally on a long reset schedule (the study's comparison reset once a year). A reset-only option is not on the table: it would break the Steady limits between resets, because the yearly-reset comparison ignored them. Both of those comparisons were baselines, not tested strategies: the study gives no evidence that either would pass the lab's checks. The yearly-reset comparison still fell −46.4% at worst (seed A, SCOUTING). RISK.md section 2 says today's limits alone do not give the "smaller swings" [Product](product.md#strategies-by-risk-level) promises Steady customers, unless the owner tightens them (RISK.md section 3, point 3). The crypto share is the main risk control, so the worst-fall number belongs right next to it. Still pending:
- Nautilus results with measured costs. These are scouting numbers.
- How to offer it. It claims no edge, and the lab's checks test for one. The yearly-reset comparison was a baseline, not a tested strategy: it reused the search's yearly mixes, ignored the Steady limits and was never put through the checks. Its Sharpe was 0.948 with one search and 1.030 with the other, either side of the lab's 1.0 bar (SCOUTING). As one of our strategies, it must pass the same checks as any other. Otherwise it can be a self-directed tool like recurring buys, with its risk numbers shown and no performance claim. This is the owner's decision.

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

### Strategies and rules

| Feature | What it does | Tab | Phase | Priority |
|---|---|---|---|---|
| Risk levels | Customer picks Steady, Balanced or Bold; strategies grouped and labeled by level; warning and confirm to go above it | Strategies, Account | 1 | — |
| Strategy library | One starter strategy per risk level (rebalancing, dip buying, momentum) | Strategies | 1 | — |
| Honest strategy cards | Plain-English description, risk level, worst losing streak, biggest drop; backtest and live results shown separately and clearly labeled | Strategies | 1 | Standout #10 ⭐ |
| Strategy settings | Change a strategy's settings within the approved range, tested by the lab and approved by the owner (for Steady: crypto share, BTC/ETH split, drift band, check frequency, loss limit); the backtested worst fall for the chosen settings is shown, labeled hypothetical. See [Adjustable strategy settings](#adjustable-strategy-settings) | Strategies | 1, as ranges are approved | — |
| Rule builder, simple mode | Templates like "buy $X when BTC drops Y%"; stop-loss required | Strategies | 1 | — |
| Trading mode per strategy and rule | Auto-trade or Approve each trade; switch anytime | Strategies | 1 | — |
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
| Loss limit auto-pause | Daily or weekly loss limit that pauses the customer's strategies; each strategy can also have its own loss limit, tighter than its level's drawdown budget. A pause stops trading; it doesn't sell | Account | 1 | Must #5 |
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
| **Trade** | Buy/sell, recurring buys, Add cash, Cash out |
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
4. To go past the range: copy the strategy into your own rule (Phase 2)

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
- **Run our strategies on untested settings.** A strategy's settings stay inside the approved range (tested by the lab, approved by the owner); going further makes it the customer's own rule.
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
- [ ] "Hold this mix" for Steady: one of our strategies (it must pass the lab's checks) or a self-directed tool like recurring buys?
- [ ] Does Steady's guardrail "a few trades a month" ([Product](product.md#strategies-by-risk-level)) cap the drift band and check frequency, and is it counted in trades (each coin's swap) or in rebalances? The lab's limits have no such cap: the first study searched check frequencies from daily and bands from 2% of the coin share, and the busiest in-sample trials, checking daily with a band of about 2% of the coin share, rebalanced on 697 and 757 of about 2,190 days, roughly 10 times a month; each rebalance can be up to two swaps (the two final searches, 2017-2022; SCOUTING)
- [ ] Customer limits beyond the mix (for example a separate "keep at least 40% cash"): in Steady the limits also trigger trades, so such a limit is a strategy setting and needs its own approved range
- [ ] Subscription price, given gas sponsorship and provider costs

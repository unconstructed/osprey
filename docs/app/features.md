# Features: What the App Does

[← Hub](README.md) · [Product](product.md) · [Technical](technical.md) · [Business](business.md)

*Updated 2026-11-19 for the lean self-custody direction.*

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
| Loss limit auto-pause | Daily or weekly loss limit that pauses the customer's strategies | Account | 1 | Must #5 |
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
| **Strategies** | Strategies grouped by risk level, honest strategy cards, subscribe with Auto-trade or Approve, rule builder |
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
- [ ] Subscription price, given gas sponsorship and provider costs
